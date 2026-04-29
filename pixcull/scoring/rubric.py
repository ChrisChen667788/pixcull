"""Rubric-based image judgment — the V2.0 annotation upgrade.

Why this file exists
====================
The flat ``keep/maybe/cull`` label and the single-number ``score_final``
are PixCull's V0/V1 "check list": fast to apply, easy to disagree on,
and hard to debug. As the article from 36氪 points out, modern frontier
labs have moved past check lists to **rubrics** — multi-axis structured
scoring where each axis carries its own descriptors and the annotator
also writes a rationale. Industry quote: "if a check list is the
60-point reference answer, a rubric is the 80-100 point reference."

A rubric gets us four things at once:

1. **Stability.** A single ``laion_aes`` score conflates 5 different
   things (color, light, moment, composition, technical). Two
   photographers can stare at one image for an hour and still disagree
   on whether it's a 6.2 or a 7.5 — but they reliably agree on
   "composition: 4★, light: 5★, technical: 3★ (slight motion blur)."
   Decomposition makes scores reproducible.

2. **Interpretability.** When the rule decides ``cull``, the user and
   the rescorer both want to know *which axis* dragged the score
   down. With a rubric the answer is a sentence, not a 0.42 score.

3. **Trainable signal.** A rescorer trained on a single ``manual_label``
   tops out at ~70% accuracy because the label has no internal
   structure. Trained on per-axis labels it can learn six smaller,
   cleaner classifiers — same data, far better generalization.

4. **Active learning.** When axis predictions diverge sharply across
   models (rule says composition=5, rescorer says composition=2), THAT
   image is the most informative one to label next.

Each axis has BOTH a check list and a rubric — the check list runs
automatically against detector outputs (no human needed), the rubric
is the human-graded gold standard the rescorer learns to imitate.

Use:
    from pixcull.scoring.rubric import RUBRIC_AXES, AxisScore, RubricScore
    rubric = RubricScore.from_row(row_dict)        # check-list pass
    rubric = RubricScore.from_human(form_data)     # rubric pass
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Axis definitions. Order matters — it's the display order in the UI.
# ---------------------------------------------------------------------------

AxisName = Literal[
    "technical",
    "subject",
    "composition",
    "light",
    "moment",
    "aesthetic",
]


@dataclass(frozen=True)
class AxisDef:
    """Static metadata for one rubric axis."""

    name: AxisName
    label_zh: str
    label_en: str
    description_zh: str
    # The 60-pt check list — yes/no questions a deterministic detector
    # can fire at run-time. Stored as a tuple of (key, weight) so a row
    # passing 4/5 of these gets ~80% on this axis without human input.
    checklist: tuple[tuple[str, float], ...]
    # The 80-100 pt rubric — one descriptor per star level, in Chinese
    # so the annotator panel is readable at a glance.
    rubric_descriptors: tuple[str, str, str, str, str]  # 1★ ... 5★


# Each rubric axis: descriptors written for *this domain* (curating
# pro photo shoots, not generic Instagram fodder). Star descriptors
# specifically aim to be discriminative — a "3★" should feel
# different from a "4★" to a working photographer. V5.0: descriptors
# now sourced from photography_canon.CANON_DESCRIPTORS_ZH which
# encodes the Cartier-Bresson + Adams + classic-composition canon.
from pixcull.scoring.photography_canon import get_axis_descriptors as _canon_desc


RUBRIC_AXES: tuple[AxisDef, ...] = (
    AxisDef(
        name="technical",
        label_zh="技术",
        label_en="Technical",
        description_zh="对焦、曝光、清晰度、噪点 — Adams Zone System 标准",
        checklist=(
            ("not_severely_blurry", 1.0),
            ("not_severely_overexposed", 1.0),
            ("not_severely_underexposed", 0.5),
            ("subject_in_focus", 1.0),
            ("face_not_motion_blurred", 0.8),
            # V5.1 canon — quantified Zone System checks
            ("canon_zone_full_range", 0.7),    # tonal range covers II-IX
            ("canon_no_zone_clipping", 0.6),   # < 5% in zones 0+X
            ("canon_midgray_anchored", 0.4),   # zone V near 0.5 luma
        ),
        rubric_descriptors=_canon_desc("technical"),
    ),
    AxisDef(
        name="subject",
        label_zh="主体",
        label_en="Subject",
        description_zh="主体明确性 + Cartier-Bresson 决定性瞬间",
        checklist=(
            ("has_clear_subject", 1.0),
            ("subject_eyes_open", 0.5),     # face only
            ("subject_pose_natural", 0.8),
            ("not_random_passersby", 0.5),
        ),
        rubric_descriptors=_canon_desc("subject"),
    ),
    AxisDef(
        name="composition",
        label_zh="构图",
        label_en="Composition",
        description_zh="三分法 / 黄金比 / 引导线 / 负空间 / 奇数法则",
        checklist=(
            ("horizon_within_2deg", 0.8),
            ("rule_of_thirds_close", 0.5),
            ("subject_not_at_edge", 1.0),
            ("no_distracting_clutter", 0.8),
            # V5.1 canon — quantified composition principles
            ("canon_thirds_concentration", 0.6),  # rule of thirds quantified
            ("canon_balanced_weight", 0.5),       # 3x3 visual weight balance
            ("canon_lead_room_ok", 0.5),          # lead room from mask geom
            ("canon_figure_ground_pop", 0.7),     # fig vs bg luma contrast
        ),
        rubric_descriptors=_canon_desc("composition"),
    ),
    AxisDef(
        name="light",
        label_zh="光线",
        label_en="Light",
        description_zh="光质 / 光位(Loop/Split/Rembrandt) / 黄金时刻",
        checklist=(
            ("not_blown_highlights", 1.0),
            ("not_crushed_shadows", 0.8),
            ("color_temperature_clean", 0.5),
        ),
        rubric_descriptors=_canon_desc("light"),
    ),
    AxisDef(
        name="moment",
        label_zh="瞬间",
        label_en="Moment",
        description_zh="时机、动作峰值、情绪含量(Cartier-Bresson)",
        checklist=(
            ("not_blink_or_mid_yawn", 0.5),
            ("action_at_peak", 0.8),
            ("emotion_present", 0.8),
        ),
        rubric_descriptors=_canon_desc("moment"),
    ),
    AxisDef(
        name="aesthetic",
        label_zh="美感",
        label_en="Aesthetic",
        description_zh="整体艺术感、色彩协调、情绪记忆点",
        checklist=(
            ("clipiqa_above_median", 0.5),
            ("laion_aes_above_median", 0.8),
            ("no_subject_environment_conflict", 0.5),
        ),
        rubric_descriptors=_canon_desc("aesthetic"),
    ),
)


_AXES_BY_NAME: dict[str, AxisDef] = {a.name: a for a in RUBRIC_AXES}


def get_axis(name: str) -> AxisDef:
    """Look up a rubric axis by name. Raises KeyError on typos."""
    if name not in _AXES_BY_NAME:
        raise KeyError(f"unknown rubric axis: {name!r} "
                       f"(valid: {list(_AXES_BY_NAME)})")
    return _AXES_BY_NAME[name]


# ---------------------------------------------------------------------------
# Per-image score containers. Two flavors:
#  - AxisScore captures one axis worth of evidence for one image
#  - RubricScore packages all 6 axes plus an overall verdict
# ---------------------------------------------------------------------------

@dataclass
class AxisScore:
    """One axis worth of evidence for one image.

    ``stars`` is the 1-5 grade. ``checklist_pass`` is the auto-derived
    fraction of check list items the row satisfied (0.0 - 1.0); when
    no human label is available we use it as a soft-stars proxy.
    ``rationale`` is the free-text "why" — the article's "rubric > check
    list" leap is largely about FORCING a rationale for every label.
    """
    stars: float | None = None      # 1-5; None when unrated
    checklist_pass: float | None = None
    rationale: str = ""
    # ``source`` lets us tell apart the auto-decomposed scores (label
    # source = "auto") from human annotations ("human") and any future
    # VLM-as-judge runs ("vlm:llava-7b" etc). Only "human" rows feed
    # the next rescorer training pass.
    source: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RubricScore:
    """Full per-image rubric: 6 axes + an overall verdict + filename.

    Persisted as one JSONL line per (image, source) pair. Re-annotating
    the same image just appends a new line; readers take the most-recent
    row per image.
    """
    filename: str
    axes: dict[str, AxisScore] = field(default_factory=dict)
    overall_label: str = ""        # "keep" | "maybe" | "cull" | ""
    overall_rationale: str = ""    # 1-line summary across all axes
    timestamp: float = 0.0
    source: str = "auto"           # "auto" | "human" | "vlm:<name>"

    @classmethod
    def empty(cls, filename: str) -> "RubricScore":
        rs = cls(filename=filename)
        for a in RUBRIC_AXES:
            rs.axes[a.name] = AxisScore()
        return rs

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "overall_label": self.overall_label,
            "overall_rationale": self.overall_rationale,
            "timestamp": self.timestamp,
            "source": self.source,
            "axes": {k: v.to_dict() for k, v in self.axes.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RubricScore":
        rs = cls(
            filename=d["filename"],
            overall_label=d.get("overall_label", ""),
            overall_rationale=d.get("overall_rationale", ""),
            timestamp=float(d.get("timestamp", 0.0)),
            source=d.get("source", "auto"),
        )
        for axis_name, axis_data in (d.get("axes") or {}).items():
            rs.axes[axis_name] = AxisScore(**axis_data)
        return rs

    @property
    def mean_stars(self) -> float | None:
        """Weight-average stars across all rated axes (None if none)."""
        rated = [a.stars for a in self.axes.values() if a.stars is not None]
        if not rated:
            return None
        return sum(rated) / len(rated)
