"""Tests for v0.13.8 session-adaptive scoring helpers."""

from __future__ import annotations

import pytest

from pixcull.scoring.self_tune import (
    AdaptiveThresholds,
    CalibrationCheck,
    ScoreDecomposition,
    adaptive_maybe_band,
    burst_peak_topk,
    confidence_calibration_check,
    score_decomposition,
)


# ---------------------------------------------------------------------------
# adaptive_maybe_band
# ---------------------------------------------------------------------------


def test_adaptive_returns_defaults_below_min_rows():
    out = adaptive_maybe_band([0.7] * 5)
    assert out.is_default
    assert out.keep == 0.65
    assert out.cull == 0.40


def test_adaptive_activates_at_min_rows():
    # 30 rows distributed uniformly around 0.5
    scores = [0.30 + (i / 30) * 0.4 for i in range(30)]
    out = adaptive_maybe_band(scores)
    assert not out.is_default
    # Adaptive keep should be near the 75th percentile
    assert 0.55 <= out.keep <= 0.80
    assert 0.20 <= out.cull <= 0.55
    # keep > cull + 0.05 always
    assert out.keep > out.cull + 0.04


def test_adaptive_selective_shooter_shifts_thresholds_up():
    """A user with target_keep_rate=0.20 (very selective) gets
    higher thresholds — fewer rows qualify as keep."""
    scores = [0.5] * 30
    inclusive = adaptive_maybe_band(scores, target_keep_rate=0.80)
    selective = adaptive_maybe_band(scores, target_keep_rate=0.15)
    assert selective.keep > inclusive.keep
    assert selective.cull >= inclusive.cull


def test_adaptive_clamps_keep_above_cull():
    """Even pathological inputs should preserve keep > cull + 0.05."""
    # Force all scores at 0.5 — naive blend would land both at 0.5
    out = adaptive_maybe_band([0.5] * 30)
    assert out.keep > out.cull + 0.04


def test_adaptive_handles_none_values():
    """None entries are filtered before percentile math."""
    scores = [None, 0.4, None, 0.5, 0.6] * 7  # 21 non-None
    out = adaptive_maybe_band(scores)
    # Should not crash; should activate (≥ 20 non-None)
    assert not out.is_default


# ---------------------------------------------------------------------------
# score_decomposition
# ---------------------------------------------------------------------------


def test_decomposition_sums_to_score_final():
    """The three components must add up to score_final by construction."""
    row = {
        "score_final": 0.78,
        "rubric_stars": {"technical": 4.0, "subject": 4.5,
                          "composition": 4.0, "light": 3.5,
                          "moment": 4.0, "aesthetic": 4.0},
        "rescorer_prob_keep": 0.70,
    }
    d = score_decomposition(row)
    # Components should sum to (approximately) score_final
    assert abs(d.axis_contribution + d.rescorer_offset
               + d.rule_penalty - d.score_final) < 0.005


def test_decomposition_axis_avg_calc():
    """6 axes all 5.0 → axis_contribution = 1.0."""
    row = {
        "score_final": 1.0,
        "rubric_stars": {a: 5.0 for a in
                          ("technical", "subject", "composition",
                           "light", "moment", "aesthetic")},
        "rescorer_prob_keep": 0.5,
    }
    d = score_decomposition(row)
    assert d.axis_contribution == 1.0


def test_decomposition_no_rubric_stars_safe():
    row = {"score_final": 0.5, "rescorer_prob_keep": 0.5}
    d = score_decomposition(row)
    assert d.axis_contribution == 0.0


def test_decomposition_explanation_mentions_strong_axes():
    row = {
        "score_final": 0.85,
        "rubric_stars": {"technical": 4.5, "subject": 4.5,
                          "composition": 4.5, "light": 4.5,
                          "moment": 4.5, "aesthetic": 4.5},
        "rescorer_prob_keep": 0.9,
    }
    d = score_decomposition(row)
    # Should mention the high axis avg + positive rescorer
    assert "+0.12" in d.explanation or "+" in d.explanation


# ---------------------------------------------------------------------------
# confidence_calibration_check
# ---------------------------------------------------------------------------


def test_calibration_ok_on_healthy_distribution():
    rows = [{"score_final": 0.4 + (i / 50) * 0.4} for i in range(50)]
    out = confidence_calibration_check(rows)
    assert out.ok
    assert out.score_std > 0.05


def test_calibration_warns_on_narrow_variance():
    rows = [{"score_final": 0.5 + (i % 3) * 0.01} for i in range(30)]
    out = confidence_calibration_check(rows)
    assert not out.ok
    assert "异常窄" in out.warning


def test_calibration_warns_on_low_mean():
    rows = [{"score_final": 0.20 + (i % 5) * 0.02} for i in range(30)]
    out = confidence_calibration_check(rows)
    assert not out.ok
    assert "偏低" in out.warning


def test_calibration_warns_on_high_mean():
    rows = [{"score_final": 0.85 + (i % 5) * 0.02} for i in range(30)]
    out = confidence_calibration_check(rows)
    assert not out.ok
    assert "偏高" in out.warning


def test_calibration_silent_below_min_rows():
    rows = [{"score_final": 0.5}] * 5
    out = confidence_calibration_check(rows)
    assert out.ok    # not enough data to warn
    assert out.warning == ""


# ---------------------------------------------------------------------------
# burst_peak_topk
# ---------------------------------------------------------------------------


def test_burst_peak_topk_returns_sorted():
    cluster = [
        {"filename": "a", "score_final": 0.7},
        {"filename": "b", "score_final": 0.9},
        {"filename": "c", "score_final": 0.5},
        {"filename": "d", "score_final": 0.8},
    ]
    out = burst_peak_topk(cluster, k=3)
    assert [r["filename"] for r in out] == ["b", "d", "a"]


def test_burst_peak_topk_handles_fewer_than_k():
    cluster = [{"filename": "a", "score_final": 0.5}]
    out = burst_peak_topk(cluster, k=3)
    assert len(out) == 1


def test_burst_peak_topk_drops_none_scores():
    cluster = [
        {"filename": "a", "score_final": 0.7},
        {"filename": "b", "score_final": None},
        {"filename": "c", "score_final": 0.5},
    ]
    out = burst_peak_topk(cluster, k=3)
    assert len(out) == 2


def test_burst_peak_topk_empty_cluster_empty_result():
    assert burst_peak_topk([], k=3) == []
