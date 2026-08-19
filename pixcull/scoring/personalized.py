"""P-AI-1 — personalized keep/maybe/cull thresholds.

A general rescorer (V1.1, V2) gives a probability that a frame is
"keep-worthy" given universal labels. But two photographers labeling
the same 100 frames will disagree on 15-30 of them — wedding
photographers forgive eye-closed; sports photographers don't;
landscape photographers are stricter on technical.

P-UX-12 already surfaces the user's taste profile (avg axis stars
when keep vs cull) on the admin page. This module closes the loop:
read those statistics, derive per-user keep/maybe thresholds, and
apply them at decision time so a fresh shoot inherits the user's
historical pickiness.

The personalization is intentionally LIGHTWEIGHT:
  - no per-user fine-tuning of CLIP / rescorer weights
  - no continuous online learning
  - just a single linear shift on the global keep_min / maybe_min
    thresholds, sized by how much the user's keep-rate diverges
    from the global median

Trade-off: shifts a 0.6 keep-threshold to ~0.55 for a "permissive"
labeler who keeps 50% of their batches, or to ~0.65 for a strict
labeler who only keeps 20%. Nothing fancy; transparent + reversible.

The personalization only kicks in once the user has ≥ MIN_ANNS
labeled rows (default 50). Below that we don't have enough signal
to know if "this user keeps 90%" reflects taste or just easy
batches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Optional

import logging
logger = logging.getLogger(__name__)


MIN_ANNS_FOR_PERSONALIZATION = 50
# Global baseline keep_rate across all PixCull deployments — derived
# from the golden set (130 rows, 84 keep ≈ 0.65). A user whose keep
# rate matches the baseline gets zero shift; deviations move the
# threshold proportionally.
BASELINE_KEEP_RATE = 0.65
# Cap the absolute shift so a single user with weird first-batch
# data can't tank precision. ±0.08 = ±8 pp on a 0-1 score scale.
MAX_THRESHOLD_SHIFT = 0.08


@dataclass
class PersonalProfile:
    """Per-user threshold + axis preference summary."""
    user_id: str
    n_annotations: int
    keep_rate: float                  # what fraction of annotations were keep
    cull_rate: float                  # ... were cull (rest = maybe)
    keep_threshold_shift: float       # signed shift to apply
    axis_keep_means:   dict[str, float]   # avg star per axis when KEEP
    axis_cull_means:   dict[str, float]   # avg star per axis when CULL
    most_cared_axis:   Optional[str]      # axis with the biggest keep-cull gap
    #: v2.57 — where the annotations behind this profile came from.
    #:
    #: The profile on the author's own machine was built from 608
    #: "corrections" whose labels were byte-identical to the rule stack's
    #: own decisions. It concluded the photographer culls 20.4% of a
    #: shoot and shifted the keep threshold by -0.060 accordingly. A
    #: blind pass on the same photographer says the real rate is 6.7% —
    #: off by 3.1x. The badge said "tuned to you"; it was tuned to the
    #: rules, and the user had no way to tell.
    #:
    #: "" means unknown, which is what every profile written before this
    #: field carries. Unknown is not trusted: see is_active().
    label_provenance: str = ""
    #: v2.60.1 — {flag: [scene, ...]}. Learned per photographer rather
    #: than shipped, because the evidence behind any one entry is one
    #: shoot's worth.
    scene_exemptions: dict = field(default_factory=dict)

    #: Provenances that can move a threshold. `blind` is what
    #: `pixcull m3 label` writes — the photographer judged the frame with
    #: no system opinion on screen, so the labels cannot echo the rules.
    TRUSTED = ("blind", "independent")

    def is_active(self) -> bool:
        """Apply personalization iff we have enough data AND can trust it.

        Enough data was the old bar and it is not sufficient: 608 rows of
        the rule stack's own output is plenty of data and worth nothing.
        """
        if self.label_provenance not in self.TRUSTED:
            return False
        return self.n_annotations >= MIN_ANNS_FOR_PERSONALIZATION

    def inactive_reason(self) -> str:
        """Why personalization is off, in words a user can act on."""
        if self.label_provenance not in self.TRUSTED:
            got = self.label_provenance or "unknown"
            return (f"label provenance {got!r} — corrections made while the "
                    f"system's own verdict was on screen can echo it back. "
                    f"Build a profile from `pixcull m3 label` (blind).")
        if self.n_annotations < MIN_ANNS_FOR_PERSONALIZATION:
            return (f"{self.n_annotations} annotations, need "
                    f"{MIN_ANNS_FOR_PERSONALIZATION}")
        return ""


def profile_from_preferences(prefs: dict) -> PersonalProfile:
    """Build a PersonalProfile from a /api/v1/users/preferences response.

    Shape of ``prefs`` is what P-UX-12's endpoint already produces:
      {total_human_annotations: N,
       scene_decision_counts: {scene: {keep,maybe,cull}},
       avg_rubric_when: {keep|maybe|cull: {axis: avg_stars}}}
    """
    n = int(prefs.get("total_human_annotations") or 0)
    scenes = prefs.get("scene_decision_counts") or {}
    total = 0; keeps = 0; culls = 0
    for sc in scenes.values():
        k, m, c = sc.get("keep", 0), sc.get("maybe", 0), sc.get("cull", 0)
        total += (k + m + c); keeps += k; culls += c
    keep_rate = keeps / total if total else BASELINE_KEEP_RATE
    cull_rate = culls / total if total else 0.0

    # Threshold shift: user keeps MORE than baseline → permissive →
    # LOWER threshold (let more in). user keeps LESS → strict →
    # RAISE threshold (require higher confidence). The factor 0.5
    # turns "10pp keep-rate gap" into "5pp threshold shift" — a
    # gentle calibration, not an aggressive override.
    shift = -(keep_rate - BASELINE_KEEP_RATE) * 0.5
    shift = max(-MAX_THRESHOLD_SHIFT, min(MAX_THRESHOLD_SHIFT, shift))

    keep_means = (prefs.get("avg_rubric_when") or {}).get("keep") or {}
    cull_means = (prefs.get("avg_rubric_when") or {}).get("cull") or {}
    # The axis where the user has the biggest gap between keep + cull
    # means is the one they care about most. Surfaces "you really
    # weight composition" / "you tolerate soft technical" insights.
    gaps = {}
    for axis in keep_means.keys():
        k_v, c_v = keep_means.get(axis), cull_means.get(axis)
        if k_v is not None and c_v is not None:
            gaps[axis] = float(k_v) - float(c_v)
    most_cared = max(gaps, key=lambda a: gaps[a]) if gaps else None

    return PersonalProfile(
        user_id=str(prefs.get("user_id") or "default"),
        n_annotations=n,
        keep_rate=round(keep_rate, 4),
        cull_rate=round(cull_rate, 4),
        keep_threshold_shift=round(shift, 4),
        axis_keep_means={k: round(float(v), 2)
                          for k, v in keep_means.items() if v is not None},
        axis_cull_means={k: round(float(v), 2)
                          for k, v in cull_means.items() if v is not None},
        most_cared_axis=most_cared,
        label_provenance=str(prefs.get("label_provenance") or ""),
    )


def apply_threshold_shift(
    base_keep_threshold: float,
    base_maybe_threshold: float,
    profile: PersonalProfile,
) -> tuple[float, float]:
    """Return (personalized_keep_threshold, personalized_maybe_threshold).

    If personalization isn't active (< MIN_ANNS_FOR_PERSONALIZATION),
    returns the baseline thresholds unchanged.
    """
    if not profile.is_active():
        return base_keep_threshold, base_maybe_threshold
    return (
        round(base_keep_threshold + profile.keep_threshold_shift, 4),
        round(base_maybe_threshold + profile.keep_threshold_shift * 0.5, 4),
    )


def save_profile(profile: PersonalProfile, path: Path) -> None:
    """Persist a profile snapshot so the pipeline can pick it up
    without re-aggregating the preferences endpoint on every photo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema":     "pixcull.personal_profile.v1",
        "user_id":    profile.user_id,
        "n_annotations":     profile.n_annotations,
        "keep_rate":         profile.keep_rate,
        "cull_rate":         profile.cull_rate,
        "keep_threshold_shift": profile.keep_threshold_shift,
        "axis_keep_means":   profile.axis_keep_means,
        "axis_cull_means":   profile.axis_cull_means,
        "most_cared_axis":   profile.most_cared_axis,
        "label_provenance":  profile.label_provenance,
        "scene_exemptions":  profile.scene_exemptions,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def load_profile(path: Path) -> Optional[PersonalProfile]:
    """Reverse of save_profile. Returns None if missing or unreadable."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("schema") != "pixcull.personal_profile.v1":
        return None
    return PersonalProfile(
        user_id=data.get("user_id", "default"),
        n_annotations=int(data.get("n_annotations", 0)),
        keep_rate=float(data.get("keep_rate", BASELINE_KEEP_RATE)),
        cull_rate=float(data.get("cull_rate", 0.0)),
        keep_threshold_shift=float(data.get("keep_threshold_shift", 0.0)),
        axis_keep_means=data.get("axis_keep_means") or {},
        axis_cull_means=data.get("axis_cull_means") or {},
        most_cared_axis=data.get("most_cared_axis"),
        label_provenance=str(data.get("label_provenance") or ""),
        scene_exemptions=data.get("scene_exemptions") or {},
    )
