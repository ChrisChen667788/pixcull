from enum import Enum
from typing import Literal

from pixcull.config import PixCullConfig


class Decision(str, Enum):
    KEEP = "keep"
    MAYBE = "maybe"
    CULL = "cull"


Strictness = Literal["strict", "standard", "lenient"]


# Scenes where "tiny subject" is compositionally normal (environmental portraits,
# wide landscapes, architectural wide-angles). For these, `no_clear_subject`
# becomes an advisory flag rather than a hard cull — otherwise we wrongly cull
# 4-5 keep photos per eval. See eval_findings.md §V0.5.
_TINY_SUBJECT_TOLERANT_SCENES = frozenset({"landscape", "street", "architecture"})

# V0.8: Scenes where global sharpness is not a quality gate. Long-exposure
# water / clouds / ICM (intentional camera movement) are legitimate landscape
# techniques — 3J0A3760 and 3J0A4411 were photographer keeps that the
# `severely_blurry` hard-cull was firing on. On the golden set, 0 correct
# culls depend on this flag, so gating it for landscape is pure upside.
_BLUR_TOLERANT_SCENES = frozenset({"landscape"})


def decide(
    final_score: float,
    flags: list[str],
    config: PixCullConfig,
    strictness: Strictness = "standard",
    scene: str | None = None,
    *,
    rescorer_prob_keep: float | None = None,
    vertical: str | None = None,
) -> tuple[Decision, list[str]]:
    """Map final score + blocking flags to Keep / Maybe / Cull with human-readable reasons.

    Args:
        scene: scene name (optional). When set to landscape/street/architecture,
            `no_clear_subject` is demoted from hard-cull to advisory so that
            minimalist compositions aren't over-culled.
        rescorer_prob_keep: V1.2 — probability-of-keep output of the learned
            rescorer for this row. ``None`` means the rescorer had no opinion
            (mode=off, model unloaded, row was a rule-cull, or scoring failed),
            in which case decide() behaves exactly as V1.1. When the config's
            rescorer mode is "adjudicate" AND this value is set AND the rule
            landed on MAYBE, the rescorer can promote the row to KEEP (if
            ``prob_keep >= keep_threshold``) or demote it to CULL (if
            ``prob_keep <= maybe_to_cull_threshold`` and no protective flags).
            Rule-keeps and rule-culls are never overridden — V1.2 deliberately
            only re-sorts the ambiguous middle bucket.
        vertical: V17.2 — business vertical key (kids / wedding / bird /
            sports / etc). When set and matches a registered vertical, its
            ``policy`` shifts ``keep_min`` / ``cull_max`` thresholds and
            adds tolerated flags. Unknown / empty vertical = no override
            (back-compat with V1.x callers that don't pass this kwarg).
    """
    presets = config.fusion.get("strictness_presets", {})
    thr = presets.get(strictness) or config.fusion.get("decision", {})
    keep_min = float(thr.get("keep_min_score", 6.5)) / 10.0
    cull_max = float(thr.get("cull_max_score", 4.0)) / 10.0

    # V17.2 — vertical policy override. V17.4 — uses
    # ``get_effective_policy`` which layers any auto-tuned override
    # (saved by the V17.4 admin "🎯 自动调参" button) on top of the
    # curated registry default. Falls through to no override on any
    # error so scoring never breaks because of registry hiccups.
    vert_policy = None
    if vertical:
        try:
            from pixcull.verticals import get_effective_policy
            vert_policy = get_effective_policy(vertical)
            if vert_policy is not None:
                keep_min = max(0.0, min(1.0, keep_min + vert_policy.keep_min_delta))
                cull_max = max(0.0, min(1.0, cull_max + vert_policy.cull_max_delta))
        except Exception:
            # Verticals module is non-essential; never let it break decide().
            vert_policy = None

    reasons: list[str] = []
    # Hard-cull flags: any of these forces CULL regardless of score.
    #
    # V0.8: `severely_underexposed` removed. On the golden set, 0 correct culls
    # relied on it while 3 keep-photos got wrongly culled (AB4A4609/AB4A4644
    # stilllife low-key product shots, 20210801-3J0A8098 landscape silhouette).
    # Underexposure is either intentional mood or recoverable from RAW, and
    # `score_exposure` already folds luma into `final_score`. The flag stays
    # emitted so downstream dashboards can inspect it.
    hard_cull = {
        "closed_eyes",
        "motion_blur_on_face",
        "severely_overexposed",
        "no_clear_subject",
        "severely_blurry",
    }
    # Scene-aware exemption: tiny-subject scenes tolerate `no_clear_subject`.
    if scene in _TINY_SUBJECT_TOLERANT_SCENES:
        hard_cull = hard_cull - {"no_clear_subject"}
    # V0.8 scene-aware exemption: landscape tolerates `severely_blurry`
    # (intentional long-exposure / ICM). The flag stays on the record so
    # downstream tooling can inspect it.
    if scene in _BLUR_TOLERANT_SCENES:
        hard_cull = hard_cull - {"severely_blurry"}
    # V17.2 — vertical-level tolerated flags (e.g. kids tolerates
    # ``motion_blur_on_face``; wedding tolerates ``shadows_clipped``).
    if vert_policy is not None and vert_policy.tolerated_flags:
        hard_cull = hard_cull - set(vert_policy.tolerated_flags)

    triggered = set(flags) & hard_cull
    if triggered:
        reasons.extend(sorted(triggered))
        return Decision.CULL, reasons

    # Rule stack's own verdict — same as V0.8/V1.1.
    if final_score >= keep_min:
        rule_decision = Decision.KEEP
        rule_reasons = [f"score={final_score:.2f}"]
    elif final_score <= cull_max:
        rule_decision = Decision.CULL
        rule_reasons = [f"low_score={final_score:.2f}", *flags]
    else:
        rule_decision = Decision.MAYBE
        rule_reasons = [f"score={final_score:.2f}", *flags]

    # V1.2 adjudicate mode: the rescorer can override rule=MAYBE only.
    # Rule-keeps and rule-culls are never touched in this phase — we only
    # resort the ambiguous middle bucket, which is where the rescorer's
    # signal is strongest (and where the rule stack was least certain
    # anyway). See RescorerConfig docstring for the rationale.
    rescorer_mode = getattr(config.rescorer, "mode", "off") \
        if hasattr(config, "rescorer") else "off"
    if (
        rescorer_mode == "adjudicate"
        and rule_decision is Decision.MAYBE
        and rescorer_prob_keep is not None
    ):
        keep_thr = float(config.rescorer.keep_threshold)
        cull_thr = float(config.rescorer.maybe_to_cull_threshold)
        if rescorer_prob_keep >= keep_thr:
            return Decision.KEEP, [
                *rule_reasons,
                f"rescorer_promoted(P={rescorer_prob_keep:.2f})",
            ]
        if cull_thr > 0 and rescorer_prob_keep <= cull_thr:
            return Decision.CULL, [
                *rule_reasons,
                f"rescorer_demoted(P={rescorer_prob_keep:.2f})",
            ]

    return rule_decision, rule_reasons
