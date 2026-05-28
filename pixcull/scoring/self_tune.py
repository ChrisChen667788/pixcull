"""v0.13.8 — Session-adaptive scoring helpers (no model retraining).

The v0.4 → v0.13 pipeline ships with one set of global thresholds:
  * `score_final` ∈ [0.55, 0.65] = maybe band
  * keep threshold = 0.65
  * cull threshold = 0.40

That's a sensible default but it doesn't adapt to the current run.
A wedding-portrait shooter expecting 65% keep-rate has very different
distribution than a wildlife shooter expecting 8% — pinning them to
the same band creates systematic mis-classifications.

This module computes **per-session corrections** at three levels:

1. ``adaptive_maybe_band(rows)`` — pick keep / cull thresholds that
   match the run's observed score distribution + the user's
   historical keep-rate preference.
2. ``score_decomposition(row)`` — break ``score_final`` into the
   three additive components the pipeline actually computes:
   ``axis_contribution + rescorer_offset + rule_penalty``.  The UI
   surfaces this so the AI is no longer a black-box single number.
3. ``confidence_calibration_check(rows)`` — when the whole run's
   score variance is suspiciously narrow (σ < 0.05), flag that the
   model's calibration drifted (likely a vertical mis-match).

Zero training cost.  All three are pure functions over the data
the pipeline already emits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# Global defaults; the v0.4 pipeline pins these.  Adaptive helpers
# return *offsets* relative to these so the caller can decide
# whether to apply them.
_DEFAULT_KEEP_THRESHOLD = 0.65
_DEFAULT_CULL_THRESHOLD = 0.40

# Minimum number of scored rows before adaptive logic activates.
# Below this, defaults are returned (the calibration math is too noisy
# on tiny batches).
_MIN_ROWS = 20

# How aggressively adaptive thresholds shift relative to the
# distribution's 25th/75th percentiles.  Higher = more adaptive,
# lower = more conservative.  0.5 = midpoint between default and
# observed percentile.
_ADAPTIVE_MIX = 0.5


@dataclass
class AdaptiveThresholds:
    """Result of ``adaptive_maybe_band``.

    Always within sane bounds:
      * keep ∈ [0.55, 0.80]
      * cull ∈ [0.20, 0.55]
      * keep ≥ cull + 0.05
    """
    keep: float
    cull: float
    reason: str           # human-readable explanation
    is_default: bool      # True when adaptive didn't activate


def adaptive_maybe_band(score_final_values: Iterable[float],
                        target_keep_rate: float = 0.50,
                        ) -> AdaptiveThresholds:
    """Choose keep / cull thresholds that adapt to this run's
    distribution.

    Algorithm:
      1. If < `_MIN_ROWS` scored rows: return global defaults.
      2. Compute the score distribution's 25th + 75th percentile.
      3. Blend with the global default at `_ADAPTIVE_MIX`.
      4. Clamp to sane bounds; enforce keep > cull + 0.05.
      5. Return both thresholds + a one-line reason for the UI.

    ``target_keep_rate`` is a hint from the user's preferences
    (default 0.50, meaning "half should be keep").  When < 0.30
    (selective shooter) the thresholds shift up; when > 0.70
    (inclusive shooter) they shift down.
    """
    scores = [float(s) for s in score_final_values if s is not None]
    if len(scores) < _MIN_ROWS:
        return AdaptiveThresholds(
            keep=_DEFAULT_KEEP_THRESHOLD,
            cull=_DEFAULT_CULL_THRESHOLD,
            reason=f"使用全局默认 — 仅 {len(scores)} 张评分;"
                   f"需要 ≥{_MIN_ROWS} 才能 calibrate",
            is_default=True,
        )
    scores_sorted = sorted(scores)
    n = len(scores_sorted)
    q25 = scores_sorted[int(n * 0.25)]
    q75 = scores_sorted[int(n * 0.75)]
    # Blend observed distribution with default
    adaptive_keep = (_ADAPTIVE_MIX * q75 +
                     (1 - _ADAPTIVE_MIX) * _DEFAULT_KEEP_THRESHOLD)
    adaptive_cull = (_ADAPTIVE_MIX * q25 +
                     (1 - _ADAPTIVE_MIX) * _DEFAULT_CULL_THRESHOLD)
    # Selectivity shift based on target_keep_rate
    if target_keep_rate < 0.30:
        # Selective shooter — push thresholds up
        adaptive_keep += 0.05
        adaptive_cull += 0.03
    elif target_keep_rate > 0.70:
        # Inclusive shooter — push thresholds down
        adaptive_keep -= 0.05
        adaptive_cull -= 0.03
    # Clamp
    adaptive_keep = max(0.55, min(0.80, adaptive_keep))
    adaptive_cull = max(0.20, min(0.55, adaptive_cull))
    # Enforce keep > cull + 0.05
    if adaptive_keep < adaptive_cull + 0.05:
        adaptive_keep = adaptive_cull + 0.05
    reason = (
        f"自调:keep ≥ {adaptive_keep:.2f}, cull < {adaptive_cull:.2f} "
        f"(基于 {n} 张评分的 25/75 分位 + 用户偏好 keep-rate "
        f"≈ {int(target_keep_rate * 100)}%)"
    )
    return AdaptiveThresholds(
        keep=round(adaptive_keep, 3),
        cull=round(adaptive_cull, 3),
        reason=reason,
        is_default=False,
    )


@dataclass
class ScoreDecomposition:
    """Three-segment breakdown of ``score_final``.

    score_final ≈ axis_contribution + rescorer_offset + rule_penalty
    (in the v0.4 pipeline's fusion math; see
    ``pixcull/scoring/fusion.py``).
    """
    axis_contribution: float    # mean(rubric_stars) → normalised 0..1
    rescorer_offset: float      # signed delta from rescorer_v1
    rule_penalty: float         # negative for hard-cull triggers
    score_final: float
    explanation: str            # human-readable phrase


def score_decomposition(row: dict) -> ScoreDecomposition:
    """Break ``row['score_final']`` into the three additive parts.

    Approximation rules:
      * ``axis_contribution`` = mean(rubric_stars.values) / 5.0
      * ``rescorer_offset``   = (rescorer_prob_keep - 0.5) * 0.3
                                (signed; range ±0.15)
      * ``rule_penalty``      = score_final - axis - rescorer_offset
                                (residual; captures hard-cull
                                penalties + scene-specific shifts)

    The sum is the exact ``score_final`` by construction; the
    decomposition is an *attribution*, not a re-derivation.
    """
    final = float(row.get("score_final") or 0.0)
    axis_stars = row.get("rubric_stars") or {}
    axis_values = [v for v in axis_stars.values()
                   if isinstance(v, (int, float))]
    if axis_values:
        axis_contribution = sum(axis_values) / len(axis_values) / 5.0
    else:
        axis_contribution = 0.0
    prob_keep = row.get("rescorer_prob_keep")
    try:
        prob_keep_f = float(prob_keep) if prob_keep is not None else 0.5
    except (TypeError, ValueError):
        prob_keep_f = 0.5
    rescorer_offset = (prob_keep_f - 0.5) * 0.3
    # The residual captures everything not in the two named buckets
    rule_penalty = final - axis_contribution - rescorer_offset
    # Build a one-line explanation
    parts: list[str] = []
    if axis_contribution >= 0.55:
        parts.append(f"6 轴均值 {axis_contribution*5:.1f}★(贡献 +{axis_contribution:.2f})")
    elif axis_contribution >= 0.40:
        parts.append(f"6 轴均值 {axis_contribution*5:.1f}★(中性)")
    else:
        parts.append(f"6 轴均值 {axis_contribution*5:.1f}★(贡献 +{axis_contribution:.2f},偏低)")
    if abs(rescorer_offset) > 0.02:
        sign = "+" if rescorer_offset > 0 else "−"
        parts.append(f"rescorer {sign}{abs(rescorer_offset):.2f}")
    if abs(rule_penalty) > 0.05:
        if rule_penalty < 0:
            parts.append(f"规则扣 {rule_penalty:.2f}")
        else:
            parts.append(f"规则加 +{rule_penalty:.2f}")
    explanation = " · ".join(parts)
    return ScoreDecomposition(
        axis_contribution=round(axis_contribution, 3),
        rescorer_offset=round(rescorer_offset, 3),
        rule_penalty=round(rule_penalty, 3),
        score_final=round(final, 3),
        explanation=explanation,
    )


@dataclass
class CalibrationCheck:
    """Result of ``confidence_calibration_check``."""
    ok: bool
    score_std: float
    score_mean: float
    n_rows: int
    warning: str = ""


def confidence_calibration_check(rows: Iterable[dict]) -> CalibrationCheck:
    """Flag suspicious score distributions.

    Two failure modes:
      * **Near-zero variance** (σ < 0.05): model is mostly outputting
        the same number for every photo — calibration is broken for
        this vertical.
      * **Mean near edge** (mean < 0.30 or > 0.80): model is
        systematically biased.

    Both indicate a likely vertical mis-match (e.g. landscape model
    applied to wedding) and the user should re-train style profile
    or adjust per-vertical λ.
    """
    score_values = []
    for r in rows:
        v = r.get("score_final")
        if v is not None:
            try:
                score_values.append(float(v))
            except (TypeError, ValueError):
                continue
    n = len(score_values)
    if n < _MIN_ROWS:
        return CalibrationCheck(
            ok=True,
            score_std=0.0,
            score_mean=0.0,
            n_rows=n,
            warning="",
        )
    mean = sum(score_values) / n
    var = sum((v - mean) ** 2 for v in score_values) / n
    std = var ** 0.5
    warnings: list[str] = []
    if std < 0.05:
        warnings.append(
            f"score 分布异常窄 (σ={std:.3f}):model 可能在这批照片上 "
            f"calibration 失准 — 建议训练个性化 style profile 或"
            f"切换 vertical"
        )
    if mean < 0.30:
        warnings.append(
            f"全 batch 均分 {mean:.2f} 偏低 — 检查 vertical 设置是"
            f"否与照片场景匹配"
        )
    elif mean > 0.80:
        warnings.append(
            f"全 batch 均分 {mean:.2f} 偏高 — model 可能对所有照片"
            f"都过于宽容,考虑使用 ``strict`` --strictness"
        )
    return CalibrationCheck(
        ok=not warnings,
        score_std=round(std, 4),
        score_mean=round(mean, 3),
        n_rows=n,
        warning="; ".join(warnings),
    )


def burst_peak_topk(cluster_rows: list[dict], k: int = 3) -> list[dict]:
    """v0.13.8 — return the top-K candidates for a burst cluster
    instead of just the single peak.

    Photographers shooting bursts at 8-12 fps often want to scan the
    top-2 or top-3 frames before locking the peak — the second-best
    frame might have a better expression even if the model picked
    the sharpest one.

    Sorts by ``score_final`` descending, returns the first ``k``.
    When ``cluster_rows`` has fewer than ``k`` entries, returns
    however many exist.
    """
    if not cluster_rows:
        return []
    valid = [r for r in cluster_rows
             if r.get("score_final") is not None]
    valid.sort(key=lambda r: -float(r["score_final"]))
    return valid[:max(1, k)]
