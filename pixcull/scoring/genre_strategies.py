"""V8.2 Per-genre scoring strategies — different photographic genres
have different definitions of "good".

Why this is needed
==================
The V5/V6 rubric weights every check the same regardless of genre.
That fails on edge cases where a check is meaningful for one genre
and meaningless for another:

* A macro shot of an insect's eye doesn't have a "subject's pose";
  judging it on ``subject_pose_natural`` is nonsense.
* Astrophotography is supposed to have a center-heavy composition
  (Milky Way over horizon); rule-of-thirds isn't the right frame.
* Fashion photography rewards stylized poses precisely BECAUSE
  they're not "natural"; the subject_pose_natural check inverts.
* Architectural photography is judged on geometric symmetry +
  perspective; lead room is irrelevant for a building.

Strategy
========
For each genre we override:
  - axis_emphasis: per-axis multiplier (e.g. 1.5× for composition
    in architectural, 0.6× for moment in stilllife)
  - check_overrides: same syntax as style_modes
    ('suppress' | 'boost' | 'invert')

Defaults to identity for unknown / unrecognized genres so behavior
is unchanged for the rule stack's old 6 genres until callers opt in.

Sources synthesized
===================
* Wedding photography (Joe Buissink, Jose Villa) — moment + emotion
  outweighs technical perfection
* Sports photography (Walter Iooss Jr., Sports Illustrated) —
  peak action + sharpness; composition often centered
* Macro photography (Levon Biss, USDA) — focus stack + subject
  isolation; lead room not applicable
* Food photography (Penny De Los Santos, Bon Appétit) — high-key
  flat lay symmetric composition; saturation expected
* Architectural (Iwan Baan, Julius Shulman) — geometric symmetry,
  perspective control, leading lines
* Documentary (W. Eugene Smith, Sebastião Salgado) — narrative +
  emotion + decisive moment outweigh aesthetic polish
* Fashion (Avedon, Helmut Newton, Tim Walker) — stylized pose +
  light + concept; "natural" is anti-pattern
* Abstract (Aaron Siskind, Andreas Gursky) — pattern / texture /
  form is the entire content
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GenreStrategy:
    """Per-genre rubric overlay. axis_emphasis gets multiplied into
    each axis's final star score (after check-list aggregation);
    check_overrides operate at the per-check level (same as
    style_modes overrides).
    """

    axis_emphasis: dict[str, float] = field(default_factory=dict)
    check_overrides: dict[str, str] = field(default_factory=dict)
    notes_zh: str = ""

    def emphasis_for(self, axis: str) -> float:
        return self.axis_emphasis.get(axis, 1.0)


# ---------------------------------------------------------------------------
# Per-genre strategies. Keys MATCH SceneDetector's SCENE_PROMPTS.
# ---------------------------------------------------------------------------

GENRE_STRATEGIES: dict[str, GenreStrategy] = {
    # — V0.x genres ——
    "portrait": GenreStrategy(
        axis_emphasis={
            "subject": 1.30, "moment": 1.15, "light": 1.10,
            "composition": 1.00, "technical": 0.95, "aesthetic": 1.00,
        },
        notes_zh="人像:主体+表情+光质权重高;技术失分需明显才扣分。",
    ),
    "wildlife": GenreStrategy(
        axis_emphasis={
            "subject": 1.25, "moment": 1.30, "technical": 1.20,
            "composition": 1.00, "light": 0.95, "aesthetic": 0.90,
        },
        notes_zh="野生动物:动物姿态 + 决定性瞬间 + 锐度并重。",
    ),
    "event": GenreStrategy(
        axis_emphasis={
            "moment": 1.40, "subject": 1.15, "aesthetic": 0.85,
            "composition": 0.95, "light": 1.00, "technical": 1.00,
        },
        notes_zh="活动/婚礼:决定性瞬间为王,美感分让位于真实性。",
    ),
    "stilllife": GenreStrategy(
        axis_emphasis={
            "composition": 1.30, "light": 1.30, "aesthetic": 1.20,
            "technical": 1.15, "subject": 1.00, "moment": 0.50,
        },
        check_overrides={
            "not_blink_or_mid_yawn": "suppress",
            "action_at_peak": "suppress",
            "emotion_present": "suppress",
        },
        notes_zh="静物:不评瞬间;构图/光线/美感主导。",
    ),
    "landscape": GenreStrategy(
        axis_emphasis={
            "composition": 1.30, "light": 1.40, "aesthetic": 1.20,
            "technical": 1.10, "moment": 0.85, "subject": 0.85,
        },
        check_overrides={
            "subject_eyes_open": "suppress",
            "face_not_motion_blurred": "suppress",
        },
        notes_zh="风光:光质/构图/黄金时刻 = 灵魂;主体可以是抽象的山或云。",
    ),
    # v2.14-P2 — 航拍(DJI / 无人机俯瞰)。像风光但更偏俯瞰构图与图案/光影;
    # 没有人脸、没有决定性瞬间可言,主体即大地肌理 → 抑制人脸/瞬间类 check。
    "aerial": GenreStrategy(
        axis_emphasis={
            "composition": 1.40, "aesthetic": 1.25, "light": 1.25,
            "technical": 1.10, "subject": 0.70, "moment": 0.50,
        },
        check_overrides={
            "subject_eyes_open": "suppress",
            "face_not_motion_blurred": "suppress",
            "not_blink_or_mid_yawn": "suppress",
            "action_at_peak": "suppress",
            "emotion_present": "suppress",
        },
        notes_zh="航拍:俯瞰构图/图案/光影主导;无人脸与决定性瞬间,主体即大地肌理。",
    ),
    "street": GenreStrategy(
        axis_emphasis={
            "moment": 1.35, "subject": 1.10, "composition": 1.10,
            "aesthetic": 1.00, "light": 0.95, "technical": 0.90,
        },
        notes_zh="街拍:Cartier-Bresson 决定性瞬间 + 真实感优先。",
    ),
    # — V8.2 expanded genres ——
    "architecture": GenreStrategy(
        axis_emphasis={
            "composition": 1.50, "light": 1.20, "technical": 1.20,
            "aesthetic": 1.00, "subject": 0.80, "moment": 0.40,
        },
        check_overrides={
            # Buildings don't have a "natural pose" or "lead room"
            "subject_pose_natural": "suppress",
            "canon_lead_room_ok": "suppress",
            "not_blink_or_mid_yawn": "suppress",
            "action_at_peak": "suppress",
            "emotion_present": "suppress",
            # Symmetry is a positive in architecture
            "subject_eyes_open": "suppress",
        },
        notes_zh="建筑:几何对称 + 透视控制;不评瞬间/姿态/lead room。",
    ),
    "documentary": GenreStrategy(
        axis_emphasis={
            "moment": 1.45, "subject": 1.25, "composition": 1.05,
            "light": 1.00, "aesthetic": 0.85, "technical": 0.90,
        },
        notes_zh="纪实:Smith/Salgado 标准 — 叙事+决定性瞬间 > 技术完美。",
    ),
    "fashion": GenreStrategy(
        axis_emphasis={
            "subject": 1.30, "light": 1.30, "aesthetic": 1.30,
            "composition": 1.10, "technical": 1.10, "moment": 0.85,
        },
        check_overrides={
            # Stylized poses are the point in fashion
            "subject_pose_natural": "invert",
        },
        notes_zh="时尚:刻意造型才对!不评 '自然' — 反向评。",
    ),
    "macro": GenreStrategy(
        axis_emphasis={
            "technical": 1.50, "subject": 1.30, "aesthetic": 1.10,
            "composition": 1.00, "light": 1.10, "moment": 0.30,
        },
        check_overrides={
            # No pose, no lead room, no eye-blink for an insect head
            "subject_pose_natural": "suppress",
            "subject_eyes_open": "suppress",
            "canon_lead_room_ok": "suppress",
            "not_blink_or_mid_yawn": "suppress",
            "action_at_peak": "suppress",
            "emotion_present": "suppress",
        },
        notes_zh="微距:对焦/景深/纹理放大权重;无人像维度。",
    ),
    "food": GenreStrategy(
        axis_emphasis={
            "aesthetic": 1.35, "composition": 1.30, "light": 1.20,
            "technical": 1.05, "subject": 1.00, "moment": 0.30,
        },
        check_overrides={
            "subject_eyes_open": "suppress",
            "face_not_motion_blurred": "suppress",
            "not_blink_or_mid_yawn": "suppress",
            "action_at_peak": "suppress",
            "emotion_present": "suppress",
        },
        notes_zh="美食:平铺构图 + 高调柔光 + 鲜艳色彩。",
    ),
    "sports": GenreStrategy(
        axis_emphasis={
            "moment": 1.50, "technical": 1.30, "subject": 1.20,
            "composition": 0.95, "light": 0.85, "aesthetic": 0.85,
        },
        check_overrides={
            # Center subject is fine in sports
            "canon_thirds_concentration": "suppress",
        },
        notes_zh="体育:快门凝固 + 动作峰值 = 一切;构图次要。",
    ),
    "astro": GenreStrategy(
        axis_emphasis={
            "technical": 1.40, "composition": 1.30, "aesthetic": 1.20,
            "light": 1.10, "subject": 0.70, "moment": 0.50,
        },
        check_overrides={
            # No human subjects in astrophotography
            "has_clear_subject": "suppress",
            "subject_pose_natural": "suppress",
            "subject_eyes_open": "suppress",
            "face_not_motion_blurred": "suppress",
            # Long exposure is core
            "not_severely_blurry": "suppress",
            # Dark frames are normal
            "not_severely_underexposed": "suppress",
            "canon_no_zone_clipping": "suppress",
        },
        notes_zh="天文:主体是星空;长曝光必然 + 暗调正常 + 锐度看星点。",
    ),
    "abstract": GenreStrategy(
        axis_emphasis={
            "composition": 1.35, "aesthetic": 1.30, "light": 1.10,
            "technical": 1.00, "subject": 0.50, "moment": 0.40,
        },
        check_overrides={
            "has_clear_subject": "suppress",  # form > subject
            "subject_pose_natural": "suppress",
            "canon_lead_room_ok": "suppress",
            "not_blink_or_mid_yawn": "suppress",
            "action_at_peak": "suppress",
            "emotion_present": "suppress",
        },
        notes_zh="抽象:Pattern / 纹理 / 形态 > 主体;构图与美感最重。",
    ),
}


def get_strategy(scene: str) -> GenreStrategy:
    """Look up a strategy by scene name. Returns identity strategy
    for unknown scenes so the caller never has to None-check."""
    return GENRE_STRATEGIES.get(scene, GenreStrategy())


def render_genre_section_zh(scene: str) -> str:
    """A short Markdown brief about how this genre is judged.
    Injected into VLM + meta-judge prompts so they grade against the
    genre's actual standards instead of the generic canon."""
    s = get_strategy(scene)
    if not s.notes_zh:
        return ""
    emph_pairs = [
        f"{k}({v:.2f}×)" for k, v in s.axis_emphasis.items() if v != 1.0
    ]
    emph = " · ".join(emph_pairs)
    return (
        f"## 题材标准 · {scene}\n"
        f"{s.notes_zh}\n"
        + (f"权重调整: {emph}\n" if emph else "")
    )
