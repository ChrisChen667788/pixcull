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
#
# V18: ``wildlife`` + ``astro`` added based on the V17.13 100CANON scan
# (1858 real RAW shots). The flag fired on 27 wildlife shots (telephoto
# of small/distant subjects — birds across a lake, monkeys at canopy
# distance) where the small subject IS the genre's defining trait. F1
# improved on the user's wildlife pool from 0.40 → 0.65 in offline
# replay. Astro inherits this for the same reason: a starfield with
# the milky way doesn't have a "clear subject" in the rule-detector
# sense.
#: v2.60 — what the scene classifier writes when it could not decide.
#: `scene_uncertain` and `scene == "unknown"` coincided on 9 of 9 frames
#: in the blind pass, so either spelling means the same thing.
_UNKNOWN_SCENE_LABELS = frozenset({"unknown", "uncertain", "none", "—"})

_TINY_SUBJECT_TOLERANT_SCENES = frozenset({
    "landscape", "street", "architecture",
    "wildlife", "astro",
})

# V0.8: Scenes where global sharpness is not a quality gate. Long-exposure
# water / clouds / ICM (intentional camera movement) are legitimate landscape
# techniques — 3J0A3760 and 3J0A4411 were photographer keeps that the
# `severely_blurry` hard-cull was firing on. On the golden set, 0 correct
# culls depend on this flag, so gating it for landscape is pure upside.
_BLUR_TOLERANT_SCENES = frozenset({"landscape"})


#: v2.48-P1 — how a vision judge's own word maps onto our three buckets.
#: Kept as data so an unknown label (a model that answered "maybe not")
#: falls through to the rule stack instead of being coerced into a guess.
_VLM_LABELS: dict[str, Decision] = {
    "keep":  Decision.KEEP,
    "maybe": Decision.MAYBE,
    "cull":  Decision.CULL,
    # Words the models actually return instead of our three.
    "reject": Decision.CULL,
    "discard": Decision.CULL,
    "borderline": Decision.MAYBE,
}


#: v2.59 — the same set `decide()` builds, exported so a report can name
#: these flags without a second hardcoded copy. Two lists of hard-cull
#: flags is how one of them silently goes stale.
_HARD_CULL_FLAGS_FOR_REPORT = frozenset({
    "closed_eyes", "motion_blur_on_face", "severely_overexposed",
    "no_clear_subject", "severely_blurry",
})


def decide(
    final_score: float,
    flags: list[str],
    config: PixCullConfig,
    strictness: Strictness = "standard",
    scene: str | None = None,
    *,
    rescorer_prob_keep: float | None = None,
    vertical: str | None = None,
    personal_shift: float = 0.0,
    #: v2.60.1 — {flag: [scene, ...]} learned from THIS photographer's
    #: blind pass. Kept out of the global exemption sets on purpose: the
    #: proposals that produce it come from one shoot, and n=10 from one
    #: card is a fact about that card until it is a fact about the
    #: photographer. Per-profile it costs nobody else anything.
    personal_exemptions: dict | None = None,
    vlm_label: str | None = None,
    vlm_axes: dict[str, float | None] | None = None,
    # v2.58 — `off` by default, downgraded from `primary`.
    #
    # A blind pass (150 frames, labelled before anything was scored) gave
    # `primary` 1 of the 10 frames the photographer would delete, with a
    # 95% CI spanning zero. Shipping full override authority on that is
    # more than the measurement supports. Turning the judge on no longer
    # silently hands it the power to overrule a keep; that now takes a
    # second, explicit `--vlm-authority`.
    # v2.64 — `primary` by default, on 394 blind frames.
    #
    #     mode      destroys keepers   finds your culls   second looks
    #     rule           126 / 366          5 / 28            31
    #     primary         15 / 366          4 / 28           195
    #
    #     macro-F1 (maybe scored as "not destroyed"): rule 0.413,
    #     primary 0.559 → +14.6 pts, 95% CI [+7.1, +22.7]
    #
    # The rule stack auto-deletes 131 frames of which 126 are keepers — a 96%
    # error rate on the one action that cannot be undone. `primary` cuts that
    # to 15 while finding one fewer cull, and asks for 195 second looks.
    #
    # What `maybe` means was measured, not assumed: on frames the
    # photographer kept, 58 of 60 were "worth another look after a crop"
    # (97%); on frames they culled, 13 of 16 were genuine misses (81%). Both
    # passes were blind. The scoring above treats a `maybe` on a cull as a
    # miss, so the number is conservative.
    vlm_authority: str = "primary",
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

    # v2.4-P0-2b — personal-taste calibration. ``personal_shift`` is the
    # user's learned keep_threshold_shift (signed; + = this shooter keeps
    # fewer → stricter). Nudges the keep/cull boundary like a vertical
    # policy; 0.0 (default / < 50 corrections) is a no-op.
    if personal_shift:
        keep_min = max(0.0, min(1.0, keep_min + personal_shift))
        cull_max = max(0.0, min(1.0, cull_max + personal_shift * 0.5))

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
    # v2.60 — and an UNKNOWN scene tolerates it too, on principle rather
    # than on taste.
    #
    # `no_clear_subject` is a claim about what the frame is of. The
    # exemptions above exist because that claim is meaningless for a
    # landscape or an astro frame. When the classifier could not say what
    # the frame is at all, the claim is not wrong so much as unfounded —
    # and this is the only flag that hard-culls on a judgement about
    # subject matter, so it is the only one where not knowing the subject
    # should buy a reprieve.
    #
    # Measured on a blind pass: it fired on 5 `unknown` frames and the
    # photographer wanted none of them deleted. Small, but the argument
    # does not rest on that — an assertion the system says it cannot make
    # should not be grounds for destroying a photograph. The asymmetry
    # this repo already writes down settles the tie: a missed cull costs
    # thirty seconds, a wrong cull costs the photograph.
    #
    # `scene=None` is NOT this case, and a pre-existing test says so
    # correctly: a caller who omitted the argument has told us nothing,
    # while a classifier that wrote "unknown" has told us it could not
    # decide. Only the second is evidence of uncertainty. My first draft
    # conflated them and turned an API-usage case into a silent
    # weakening of the flag for every library caller.
    if scene in _UNKNOWN_SCENE_LABELS:
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
    # v2.60.1 — the photographer's own, applied last so it can only
    # widen tolerance, never re-arm a flag the rules already forgave.
    for _flag, _scenes in (personal_exemptions or {}).items():
        if scene in set(_scenes):
            hard_cull = hard_cull - {_flag}

    triggered = set(flags) & hard_cull

    # v2.48-P1 — the vision judge gets real authority.
    #
    # Until now a VLM verdict landed in a parallel CSV column and changed
    # nothing: score_final and decision were already written before the
    # VLM stage ran, and rule-CULL rows were skipped outright. Five stars
    # on every axis could not save one photo.
    #
    # ``vlm_authority``:
    #   "off"     — v2.47 behaviour. The default, and what ships until
    #               the positioning rewrite lands with it.
    #   "shadow"  — record the disagreement, change nothing. Safe to
    #               leave on; this is how you find out whether you would
    #               have trusted it before you do.
    #   "primary" — M3 decides.
    #
    # In "primary" the hard-cull flags stop being a veto, and that is
    # deliberate rather than reckless: the judge was shown those exact
    # measurements in its prompt (see m3.build_evidence_block). When it
    # returns "keep" on a frame flagged closed_eyes, it is not ignorant
    # of the closed eyes — it is saying the frame is worth keeping
    # anyway, which for a laughing-with-eyes-shut candid is the correct
    # call and the one the rule stack has always got wrong.
    #
    # What it is NOT allowed to do is be incoherent. A verdict of "keep"
    # alongside its own technical rating of 1-2 stars on a frame the
    # detectors flagged is not a considered override, it is the model
    # contradicting itself, and that is exactly the over-confidence the
    # meta-judge was built to catch. Those fall back to the rule.
    vlm_says = (vlm_label or "").strip().lower()

    # v2.53 — "rescue": the mode the evidence actually supports.
    #
    # The owner reviewed 18 frames the rule stack hard-culled and M3 kept.
    # They agreed with M3 on 17 — 94%. That is a strong, verified result
    # about ONE behaviour: M3 is very good at spotting a frame the
    # detectors wrongly discard, because it was handed the blink count and
    # the Laplacian variance and chose to overrule them anyway.
    #
    # It is NOT a result about judging in general. M3 disagrees with the
    # rule on 200 rows; 182 of those were never reviewed, and on the
    # measured set as a whole it scores well below the rule stack.
    #
    # So this mode gives M3 exactly the authority the data earns it and
    # not one bit more: it may overturn a hard-cull, and it may not touch
    # anything else. A frame the rule was going to keep or send to maybe
    # is none of its business.
    if vlm_authority == "rescue" and vlm_says in _VLM_LABELS and triggered:
        tech = (vlm_axes or {}).get("technical")
        if (vlm_says in ("keep", "maybe")
                and not (tech is not None and float(tech) <= 2.0)):
            return _VLM_LABELS[vlm_says], [
                *reasons, f"vlm_rescued({','.join(sorted(triggered))})"]

    incoherent_note: list[str] = []
    if vlm_authority == "primary" and vlm_says in _VLM_LABELS:
        tech = (vlm_axes or {}).get("technical")
        incoherent = (
            vlm_says == "keep" and triggered
            and tech is not None and float(tech) <= 2.0
        )
        if incoherent:
            # v2.68 — recorded like the shadow note, for the reason the
            # shadow note already gives a few lines below: it used to be
            # appended to `reasons`, and `reasons` is only returned on
            # the hard-cull path. Once a flag demoted instead of culling,
            # `rule_reasons` was built fresh and this note vanished from
            # exactly the rows worth recording — the judge contradicting
            # itself, silently.
            incoherent_note.append(
                f"vlm_incoherent(keep_but_technical={float(tech):.0f}★)")
            reasons.extend(incoherent_note)
        else:
            vdec = _VLM_LABELS[vlm_says]
            vreasons = [*reasons, f"vlm={vlm_says}"]
            if triggered and vdec is not Decision.CULL:
                # Say it out loud. A photographer who sees a flagged
                # frame kept must be able to tell that a judge chose it
                # over the detector, not that the detector was dropped.
                vreasons.append(
                    f"vlm_kept_despite({','.join(sorted(triggered))})")
            return vdec, vreasons
    # Shadow annotation is appended to whichever list is actually
    # returned. Appending to `reasons` here would only survive the
    # hard-cull path — `rule_reasons` below is built fresh — so the
    # observation would vanish on exactly the rows worth observing.
    shadow_note = ([f"vlm_shadow={vlm_says}"]
                   if vlm_authority == "shadow" and vlm_says in _VLM_LABELS
                   else [])

    # v2.68 — a hard-cull flag stops deleting photographs.
    #
    # Cross-validated on 493 blind frames (5-fold, thresholds fitted on
    # training folds only, every row scored by a model that never saw
    # it), against the rule stack alone with the judge off:
    #
    #     rule stack           destroys keepers   finds culls   macro-F1
    #     as it shipped              274              8           0.400
    #     flags demote to MAYBE       82             21           0.568
    #
    # Held-out +16.8 macro-F1 points, 95% CI [+10.8, +23.8], and it
    # dominates on both axes a photographer feels rather than trading
    # one for the other.  Every fold picked `maybe` over both `cull` and
    # `ignore`, under two different objectives.
    #
    # The mechanism was already on the record and nobody had costed it:
    # the detector flags carry **0.9x lift** against this photographer's
    # culls — worse than chance.  The stack was auto-deleting on a
    # signal anti-correlated with the thing it deleted for.
    #
    # `ignore` loses for a reason worth keeping: with flags gone the
    # stack culls 1 frame in 494 and finds none of the 43 real culls.
    # That scores well on a metric that rewards not destroying keepers,
    # and it is a disablement rather than a calibration.  The flags are
    # not evidence enough to delete; they are evidence enough to ask.
    policy = str((config.fusion.get("decision") or {}).get(
        "flags_policy", "maybe"))
    if triggered and policy == "cull":
        reasons.extend(shadow_note)
        reasons.extend(sorted(triggered))
        return Decision.CULL, reasons

    # Rule stack's own verdict — same as V0.8/V1.1.
    if final_score >= keep_min:
        rule_decision = Decision.KEEP
        rule_reasons = [f"score={final_score:.2f}", *shadow_note,
                        *incoherent_note]
    elif final_score <= cull_max:
        rule_decision = Decision.CULL
        rule_reasons = [f"low_score={final_score:.2f}", *flags, *shadow_note,
                        *incoherent_note]
    else:
        rule_decision = Decision.MAYBE
        rule_reasons = [f"score={final_score:.2f}", *flags, *shadow_note,
                        *incoherent_note]

    # v2.68 — a flag demotes, and only ever downward.
    #
    # Applied AFTER the score verdict, not before it. The first draft
    # returned MAYBE from the flag branch directly, which meant a frame
    # the score alone would have culled came back as MAYBE *because it
    # was flagged* — the flag making a photograph safer. It also meant
    # the shipped rule and the cross-validated one were not the same
    # rule, so the +16.8 points measured in `rule_calibration` described
    # a system that was never going to run.
    if triggered and policy == "maybe" and rule_decision is Decision.KEEP:
        rule_decision = Decision.MAYBE
        rule_reasons = [*rule_reasons, *sorted(triggered)]

    # V1.2 adjudicate mode: the rescorer can override rule=MAYBE only.
    # Rule-keeps and rule-culls are never touched in this phase — we only
    # resort the ambiguous middle bucket, which is where the rescorer's
    # signal is strongest (and where the rule stack was least certain
    # anyway). See RescorerConfig docstring for the rationale.
    rescorer_mode = getattr(config.rescorer, "mode", "off") \
        if hasattr(config, "rescorer") else "off"
    # v2.68 — a MAYBE that a flag produced is not adjudicable.
    #
    # The flag policy change made every flagged frame a MAYBE, and
    # `adjudicate` rewrites MAYBE rows — so without this the rescorer
    # could promote a flagged frame straight to KEEP and cancel the
    # second look entirely. What the blind labels measured is that a
    # flag is not evidence enough to DELETE a photograph. Nothing in
    # them says it is not evidence enough to ask a human to glance at
    # it, so the ask survives.
    if (
        rescorer_mode == "adjudicate"
        and rule_decision is Decision.MAYBE
        and not triggered
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
