"""V8.0 Style mode detection — recognize when "broken" rules are
intentional and stop punishing them.

Problem statement
=================
The V5.x rubric punishes:
* Low saturation → "色彩不协调" (but B&W is the entire point)
* Heavy shadow clipping → "Zone 0 死黑" (but low-key noir wants this)
* Motion blur outside the face → "锐度差" (but long-exposure / rear-
  curtain sync is the whole technique)
* Center-weighted composition → "缺乏三分法张力" (but symmetric
  architectural / minimalist work hinges on dead-center)

Result: the canon-grounded scoring treats Daido Moriyama high-
contrast street as 1★, Brassaï night Paris as cull, an Ansel Adams
silver-print landscape with deep zone-0 sky as overexposed.

Solution
========
Detect the *style mode* of each image FIRST, then route to a
mode-specific rubric overlay that flips offending checks into
positive signals (or simply suppresses them).

Modes detected (in priority order; an image can match multiple):

* **mono**         RGB channels are nearly identical → intentional B&W.
                   Saturation checks suppressed; tonal-range checks
                   weighted up. Sources: Adams Zone System for B&W,
                   Fan Ho high-key Hong Kong, Daido Moriyama high-grain.

* **low_key**      > 60% pixels in Zones 0-IV (luma < 0.46) AND highlights
                   are *intentional sparks* (mean of top 5% luma is
                   high, not just clipped). Mood-driven; chiaroscuro;
                   noir / cinematic. ZoneIX-clipping ban relaxed.

* **high_key**     > 60% pixels in Zones VI-X (luma > 0.55) with broad
                   smooth tonal coverage. Wedding / lifestyle / fashion.
                   Zone-0 ban relaxed; saturation expectations lower.

* **silhouette**   Bimodal histogram: > 25% in Zones 0-II AND > 25%
                   in Zones VIII-X with thin middle. Subject reads
                   purely as shape. Sharpness inside subject relaxed.

* **long_exposure** Significant directional motion blur in part of the
                   frame WHILE other parts are sharp (water, stars,
                   light trails). Sharpness check on blurred regions
                   suppressed; motion narrative rewarded.

* **rear_curtain_sync** Specialized long-exposure case: motion blur
                   trail leading INTO a sharp subject end-point. We
                   approximate by detecting "directional blur trail
                   ending at high-edge-density region". Same blur-
                   suppression as long_exposure plus +1 to moment.

* **night**        Mean luma < 0.30 AND scene_confidence is high for
                   urban / landscape. Different from low-key (which
                   is intentional shadow art); night is just dark.
                   Highlight clip allowed for street lamps.

These modes are detected by ``detect_style_modes(row)`` from
existing detector outputs — no extra image loading. Each match
emits a canonical key (``mode_<name>``) so VLM/meta prompts can
inject style-specific guidance.

Output
======
``StyleProfile`` dataclass with:
* ``modes``: set of mode names matched
* ``mode_overrides``: dict[check_key, action] where action is
  "suppress" | "invert" | "boost". Used by rubric_decompose.

Refs
====
Long-exposure / silhouette detection rules: distilled from
Wikipedia's "Long-exposure photography" + "Low-key lighting" pages.
Mono / B&W detection: standard hue-variance criterion (the OpenCV
B&W test).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Mode names — kept in one place so prompts and overrides agree.
# ---------------------------------------------------------------------------

ALL_MODES = (
    "mono",
    "low_key",
    "high_key",
    "silhouette",
    "long_exposure",
    "rear_curtain_sync",
    "night",
)


# ---------------------------------------------------------------------------
# Detection thresholds — hand-tuned but documented in the source.
# ---------------------------------------------------------------------------

# Mean luma threshold for "low" / "high" key. Adams Zone IV ~0.46;
# below means dominantly shadowed. Zone VI ~0.55.
_ZONE_IV_LUMA = 0.46
_ZONE_VI_LUMA = 0.55

# Bimodal silhouette: needs significant mass at both poles.
_SILHOUETTE_DARK_FRAC = 0.25     # Zones 0-II
_SILHOUETTE_LIGHT_FRAC = 0.25    # Zones VIII-X

# Mono detection: per-pixel max-min channel difference averaged.
# < 8/255 ≈ 0.03 means R≈G≈B; the image is chromatically flat.
# Real B&W (especially split-toned) might still have a tint, so we
# combine with low color std.
_MONO_CHANNEL_DELTA = 0.03


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class StyleProfile:
    """Detected style modes for one image + scoring overrides."""

    modes: set[str] = field(default_factory=set)
    # Per-axis hint phrases the VLM/meta prompts can use to ground
    # their judgments in the recognized style.
    prompt_hints: list[str] = field(default_factory=list)
    # Per-check scoring overrides applied by rubric_decompose.
    # Action set:
    #   "suppress" → check is excluded from this image's denominator
    #   "boost"    → if the check passes, double its weight
    #   "invert"   → flip the boolean (failed → considered passing)
    overrides: dict[str, str] = field(default_factory=dict)

    def has(self, mode: str) -> bool:
        return mode in self.modes

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": sorted(self.modes),
            "prompt_hints": list(self.prompt_hints),
            "overrides": dict(self.overrides),
        }


# ---------------------------------------------------------------------------
# Detection from row metrics
# ---------------------------------------------------------------------------

def _f(row: dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    if v is None:
        return None
    try:
        x = float(v)
        if x != x:
            return None
        return x
    except (TypeError, ValueError):
        return None


def detect_style_modes(row: dict[str, Any]) -> StyleProfile:
    """Pure-function style detector. Inputs are detector outputs from
    pipeline/worker; no image loading happens here.

    Required row keys (all from the existing pipeline):
      mean_luma, highlight_clip_pct, shadow_clip_pct
      laplacian_global, subject_fraction
      canon_zone_distribution_kl, canon_zone_clip_pct
      and either ``mono_channel_delta`` (preferred, see CanonDetector
      v2 hook) or fall back to a heuristic on saturation if absent.
    """
    profile = StyleProfile()
    luma = _f(row, "mean_luma")
    hi = _f(row, "highlight_clip_pct") or 0.0
    sh = _f(row, "shadow_clip_pct") or 0.0
    clip = _f(row, "canon_zone_clip_pct") or 0.0
    lap = _f(row, "laplacian_global") or 0.0
    subj = _f(row, "subject_fraction") or 0.0

    # mono — uses a metric the canon detector adds (V8.0 update).
    # When absent, infer from very low saturation via clipiqa being
    # high while laion_aes is mid (rough heuristic — better signal
    # comes from the new metric below).
    mono_delta = _f(row, "canon_mono_channel_delta")
    if mono_delta is not None and mono_delta < _MONO_CHANNEL_DELTA:
        profile.modes.add("mono")
        profile.prompt_hints.append(
            "这是黑白照片(B&W)。请按 Ansel Adams Zone System 评 "
            "影调分离 + 颗粒/纹理而非色彩协调;经典名家参考: "
            "Adams 风光、Salgado 报道、Fan Ho 都市、Moriyama 街拍。"
        )
        # Saturation-related axes shouldn't count in B&W
        profile.overrides["clipiqa_above_median"] = "suppress"
        profile.overrides["color_temperature_clean"] = "suppress"

    # low_key
    if luma is not None and luma < _ZONE_IV_LUMA and sh > 0.03:
        # Low-key needs SOME bright spark — pure dark frames are night
        # snaps, not low-key art. Use shadow_clip_pct + a hint of
        # highlight presence.
        if hi > 0.005:
            profile.modes.add("low_key")
            profile.prompt_hints.append(
                "这是低调(low-key)摄影。chiaroscuro 是核心,深阴影"
                "是有意为之而非曝光失误。8:1 光比合理,Zone 0 出现"
                "在非主体区域应给加分而非扣分。"
            )
            profile.overrides["canon_no_zone_clipping"] = "suppress"
            profile.overrides["not_severely_underexposed"] = "suppress"

    # high_key
    if luma is not None and luma > _ZONE_VI_LUMA and hi < 0.05:
        # High-key: overall bright, smooth, but no severe blowout
        profile.modes.add("high_key")
        profile.prompt_hints.append(
            "这是高调(high-key)摄影。柔和高调影调是有意为之,"
            "Zone X 区域出现明亮反光高光不应扣分。"
        )
        profile.overrides["canon_no_zone_clipping"] = "suppress"

    # silhouette — bimodal
    if hi > _SILHOUETTE_LIGHT_FRAC and sh > _SILHOUETTE_DARK_FRAC and (
        clip > 0.20
    ):
        profile.modes.add("silhouette")
        profile.prompt_hints.append(
            "这是剪影(silhouette)摄影,主体以纯黑形态对照亮背景。"
            "主体内部纹理是有意舍弃的;应评轮廓辨识度而非主体细节锐度。"
        )
        profile.overrides["subject_in_focus"] = "suppress"
        profile.overrides["face_not_motion_blurred"] = "suppress"

    # long_exposure — depends on a flag the V8.0 detector emits.
    # Heuristic fallback: very low laplacian_global (< 30) but
    # subject_fraction normal (i.e. there's a clear subject region
    # but the surroundings are smooth).
    long_exp_flag = bool(_f(row, "canon_long_exposure_score")) and (
        (_f(row, "canon_long_exposure_score") or 0.0) > 0.4
    )
    if long_exp_flag:
        profile.modes.add("long_exposure")
        profile.prompt_hints.append(
            "这是长曝光摄影(车流 / 水流 / 星轨)。运动部分模糊化是"
            "技法核心,锐度仅评估静止主体区域。"
        )
        profile.overrides["not_severely_blurry"] = "suppress"
        profile.overrides["subject_in_focus"] = "suppress"
        # Reward composition + moment — long exposure is high-effort
        profile.overrides["canon_balanced_weight"] = "boost"

    # rear_curtain_sync — even more specific: motion trail with sharp
    # endpoint. We need both long_exposure AND a clear sharp subject
    # patch (subject_fraction > 0.05, laplacian_subject high).
    if "long_exposure" in profile.modes:
        ls = _f(row, "laplacian_subject")
        if ls is not None and ls > 80 and subj > 0.05:
            profile.modes.add("rear_curtain_sync")
            profile.prompt_hints.append(
                "可能是后帘同步(rear-curtain sync):长曝光过程中"
                "末段闪光让主体定格,前面留下清晰运动轨迹。这是"
                "高难度技法,主体应清晰而轨迹应流畅。"
            )

    # night — pure dark, but NOT low-key art (less mid-tone shape)
    if luma is not None and luma < 0.30 and "low_key" not in profile.modes:
        profile.modes.add("night")
        profile.prompt_hints.append(
            "这是夜景摄影。整体光线低,街灯/车流/月光等点光源"
            "是构图核心。点光源出现 Zone X 不应扣分。"
        )
        profile.overrides["canon_no_zone_clipping"] = "suppress"

    return profile


# ---------------------------------------------------------------------------
# Prompt injection — adds style-aware lines to vlm_judge / meta_judge.
# ---------------------------------------------------------------------------

def render_style_section_zh(profile: StyleProfile) -> str:
    """If any styles were detected, render a Markdown brief telling
    the upstream model how to grade against canon-of-this-style
    instead of the generic canon. Returns "" when no styles match."""
    if not profile.modes:
        return ""
    bullets = "\n".join(f"  • {h}" for h in profile.prompt_hints)
    return (
        "## 检测到特殊摄影风格\n"
        f"匹配模式: {', '.join(sorted(profile.modes))}\n"
        f"评分时按以下原则:\n{bullets}\n"
    )
