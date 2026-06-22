"""Apply scene template weights + bonuses/penalties to raw detector metrics.

The fusion step normalizes each detector's metric into [0, 1], applies the
scene-specific weights, then adds bonuses and penalties based on flags.
"""

import math
from typing import Any

from pixcull.config import PixCullConfig, SceneTemplate


def _coalesce(value: Any, default: float = 0.5) -> float:
    """Return ``value`` as a float, or ``default`` when it is missing.

    CRITICAL: ``fuse_score`` is called with ``row.to_dict()`` from a pandas
    DataFrame, where a Python ``None`` in a numeric column becomes ``NaN`` —
    which is NOT caught by ``x is None``.  An un-coalesced NaN propagates
    through the weighted sum and ``min(1.0, NaN)`` clamps to 1.0, silently
    forcing every no-signal frame to score_final == 1.0 (== always keep).
    So coalesce both ``None`` AND ``NaN`` to the neutral default.
    """
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) else f


def _normalize_sharpness(lap_subject: float | None, lap_global: float, tpl: SceneTemplate) -> float:
    """Map Laplacian variance into [0, 1]. Above 2× the threshold is saturated to 1.0."""
    thr = tpl.blur.get("laplacian_subject_min", 80)
    value = lap_subject if lap_subject is not None else lap_global
    if value <= 0:
        return 0.0
    return min(1.0, value / (2 * thr))


def _normalize_exposure(highlight_pct: float, shadow_pct: float, mean_luma: float) -> float:
    """Penalize clipping and extreme under/over exposure."""
    score = 1.0
    score -= min(0.5, highlight_pct / 20.0)
    score -= min(0.5, shadow_pct / 20.0)
    if mean_luma < 40 or mean_luma > 220:
        score -= 0.3
    return max(0.0, score)


def _aesthetic_blend(laion_aes: float, clipiqa_v: float) -> float:
    """Blend LAION-AES (1-10) and CLIP-IQA (0-1) into unified aesthetic score.

    V0.2: was (laion-2)/7 only. CLIP-IQA showed 17% cull/keep gap in diagnostics
    vs LAION-AES's 3% gap, so give CLIP-IQA equal weight.
    """
    aes_laion = max(0.0, min(1.0, (laion_aes - 2.0) / 7.0))
    aes_clip = max(0.0, min(1.0, clipiqa_v))
    return 0.5 * aes_laion + 0.5 * aes_clip


# v2.14-P1 — map each fusion dim to its closest rubric axis (the axes
# personal_learn learns weights over). "subject" has no fusion dim, so it does
# not reweight anything; the other five line up 1:1.
_DIM_RUBRIC_AXIS = {
    "sharpness":   "technical",
    "composition": "composition",
    "exposure":    "light",
    "aesthetic":   "aesthetic",
    "moment":      "moment",
}
_N_RUBRIC_AXES = 6  # technical, subject, composition, light, moment, aesthetic


def _personalize_weights(
    w: dict[str, float], axis_pref: dict[str, float]
) -> dict[str, float]:
    """Tilt the per-dim fusion weights toward the rubric axes THIS user values.

    ``axis_pref`` is ``personal_learn.axis_weights(profile)`` — normalised over
    the 6 rubric axes (sum 1).  Each fusion dim's weight is scaled by how much
    its rubric axis exceeds the equal-weight baseline (1/6), clamped to
    [0.5, 2.0] so a noisy profile nudges rather than overrides (mirrors the
    ±0.08 threshold-shift cap's "gentle calibration").  The total weight budget
    is PRESERVED (re-normalised), so only the score's emphasis shifts, not its
    scale.  An uninformative profile (equal axis_pref) is a no-op by
    construction; a missing/empty axis_pref returns ``w`` unchanged.
    """
    base_total = sum(w.values())
    if base_total <= 0 or not axis_pref:
        return w
    eq = 1.0 / _N_RUBRIC_AXES
    tilted: dict[str, float] = {}
    for dim, wk in w.items():
        ax = _DIM_RUBRIC_AXIS.get(dim)
        rel = 1.0
        if ax is not None and axis_pref.get(ax) is not None:
            rel = max(0.5, min(2.0, axis_pref[ax] / eq))
        tilted[dim] = wk * rel
    t_total = sum(tilted.values())
    if t_total <= 0:
        return w
    scale = base_total / t_total
    return {dim: v * scale for dim, v in tilted.items()}


def fuse_score(
    raw: dict[str, Any],
    flags: list[str],
    scene: str,
    config: PixCullConfig,
    axis_pref: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute per-dimension scores + final weighted score.

    Args:
        raw: flattened metric dict (e.g. {"laplacian_subject": 180, "laion_aes": 6.3, ...})
        flags: detector flags (e.g. ["closed_eyes", "highlights_clipped"])
        scene: scene name
        config: loaded PixCullConfig

    Returns:
        {"sharpness": ..., "composition": ..., "exposure": ...,
         "aesthetic": ..., "moment": ..., "final": ...}
    """
    tpl = config.template_for(scene)
    w = tpl.weights or config.defaults.get("weights", {})
    # v2.14-P1 — axis-aware personalization: tilt the per-dim weights toward
    # the axes this user demonstrably values. No-op when axis_pref is None
    # (the default — every caller except the personalized orchestrator path),
    # so generic runs are byte-identical.
    if axis_pref:
        w = _personalize_weights(w, axis_pref)

    sharp = _normalize_sharpness(
        raw.get("laplacian_subject"), raw.get("laplacian_global", 0), tpl
    )
    expo = _normalize_exposure(
        raw.get("highlight_clip_pct", 0),
        raw.get("shadow_clip_pct", 0),
        raw.get("mean_luma", 128),
    )
    aes = _aesthetic_blend(raw.get("laion_aes", 5.0), raw.get("clipiqa", 0.5))
    # composition + moment: computed from dedicated signals when available
    # (composition_classifier; v2.14 moment_score from the wedding-moment
    # classifier / blink flag in worker.py).  When a signal is genuinely
    # ABSENT the value is None → fall back to the deliberate neutral 0.5
    # placeholder.  Dropping the axis from the weighted sum was tried in V0.2
    # and shifted cull scores UP (sharpness is saturated noise at 2048px), so
    # neutral-0.5 stays the honest default for frames with no signal.  NOTE: a
    # plain ``.get(k, 0.5)`` is NOT enough now — worker writes an explicit
    # ``moment_score: None`` key, so we must coalesce None → 0.5 here.
    comp = _coalesce(raw.get("composition_score"))
    moment = _coalesce(raw.get("moment_score"))

    dims = {
        "sharpness":   sharp,
        "composition": comp,
        "exposure":    expo,
        "aesthetic":   aes,
        "moment":      moment,
    }

    final = sum(dims[k] * w.get(k, 0.0) for k in dims)

    # apply bonuses / penalties
    for flag, delta in (tpl.bonuses or {}).items():
        if flag in flags:
            final += float(delta)
    for flag, delta in (tpl.penalties or {}).items():
        if flag in flags:
            final -= abs(float(delta))

    dims["final"] = max(0.0, min(1.0, final))
    return dims
