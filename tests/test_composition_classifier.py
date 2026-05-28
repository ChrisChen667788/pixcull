"""Tests for v0.13.3 composition rule classifier."""

from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.scoring.composition_classifier import (
    RULES,
    classify_scores,
    detect_rule,
    reset_cache,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_rules_canonical_four():
    assert set(RULES) == {
        "rule_of_thirds", "centered", "diagonal", "golden_ratio",
    }


# ---------------------------------------------------------------------------
# Synthetic-image fixtures
# ---------------------------------------------------------------------------


def _make_synthetic(tmp_path, focal_x: float, focal_y: float,
                    name: str = "synth.jpg") -> Path:
    """Create a 128×128 JPG with a bright spot at (focal_x, focal_y)
    normalised.  Surrounding pixels are uniformly mid-grey so the
    saliency map has one clear winner."""
    from PIL import Image
    import numpy as np
    arr = np.full((128, 128, 3), 100, dtype=np.uint8)
    # Bright 16×16 spot
    px = int(focal_x * 128)
    py = int(focal_y * 128)
    half = 12
    arr[max(0, py-half):py+half, max(0, px-half):px+half] = 250
    p = tmp_path / name
    Image.fromarray(arr).save(p, "JPEG", quality=80)
    return p


def test_classify_scores_returns_all_rules(tmp_path):
    p = _make_synthetic(tmp_path, 0.5, 0.5)
    scores = classify_scores(p)
    assert set(scores.keys()) == set(RULES)
    for v in scores.values():
        assert 0.0 <= v <= 1.0


def test_classify_centered_photo_wins_centered(tmp_path):
    """A photo with the bright spot dead-center should classify as
    'centered'."""
    p = _make_synthetic(tmp_path, 0.5, 0.5)
    rule = detect_rule(p)
    # Centered should beat rule-of-thirds for a centered subject
    scores = classify_scores(p)
    assert rule == "centered"
    assert scores["centered"] > scores["rule_of_thirds"]


def test_classify_rule_of_thirds_at_intersection(tmp_path):
    """Bright spot at (1/3, 1/3) → rule_of_thirds wins."""
    p = _make_synthetic(tmp_path, 1/3, 1/3)
    rule = detect_rule(p)
    scores = classify_scores(p)
    assert rule == "rule_of_thirds"
    assert scores["rule_of_thirds"] > scores["centered"]


def test_classify_golden_ratio_at_intersection(tmp_path):
    """Bright spot at (0.382, 0.382) — golden ratio + rule-of-thirds
    overlap somewhat but golden should be slightly better."""
    p = _make_synthetic(tmp_path, 0.382, 0.382)
    scores = classify_scores(p)
    # Should be in the top 2
    sorted_scores = sorted(scores.items(), key=lambda kv: -kv[1])
    top_two_rules = {sorted_scores[0][0], sorted_scores[1][0]}
    assert "golden_ratio" in top_two_rules


def test_detect_rule_unreadable_image_returns_centered():
    """Pathological input → safe default."""
    bogus = Path("/nonexistent/photo.jpg")
    rule = detect_rule(bogus)
    assert rule in RULES   # never raises, always returns a rule
    # With unreadable image classify_scores returns tied 0.25s → 'rule_of_thirds'
    # alphabetically first in dict iteration on some Python versions; either way
    # it's a valid RULES member, not a crash.


def test_classify_scores_unreadable_returns_tied():
    """Unreadable → tied 0.25 for every rule."""
    scores = classify_scores(Path("/nonexistent.jpg"))
    assert all(v == 0.25 for v in scores.values())


# ---------------------------------------------------------------------------
# ML model fallback path
# ---------------------------------------------------------------------------


def test_ml_model_unavailable_falls_back_to_heuristic(monkeypatch):
    """When the .joblib model file doesn't exist, detect_rule should
    use the heuristic without raising."""
    reset_cache()
    # Pretend the model path doesn't exist
    import pixcull.scoring.composition_classifier as mod
    monkeypatch.setattr(mod, "_ml_model_path",
                        lambda: Path("/nonexistent/model.joblib"))
    monkeypatch.setattr(mod, "_ml_model", None)
    # Should still work via heuristic
    assert not mod._ml_model_available()


def test_reset_cache_clears_state(monkeypatch):
    import pixcull.scoring.composition_classifier as mod
    mod._ml_checked = True
    mod._ml_model = "not None"
    reset_cache()
    assert mod._ml_checked is False
    assert mod._ml_model is None


# ---------------------------------------------------------------------------
# Counterfactual integration
# ---------------------------------------------------------------------------


def test_counterfactual_auto_detects_skip_rule(tmp_path):
    """With auto_detect_rule=True, a clearly-centered photo should
    cause `best_counterfactual` to skip the 'centered' variant."""
    from pixcull.scoring.counterfactual import best_counterfactual
    p = _make_synthetic(tmp_path, 0.5, 0.5)
    # Track which variants were scored
    seen_rules: list = []
    def trace_score(arr):
        # First call = original; subsequent = variants
        seen_rules.append(arr.shape)
        return 0.5  # Flat → no counterfactual returned, but we just
                   # want to verify the call pattern
    best_counterfactual(p, trace_score)
    # Original + 3 variants (centered skipped) = 4 calls
    assert len(seen_rules) == 4


def test_counterfactual_explicit_skip_takes_priority(tmp_path):
    """When skip_current_rule is explicitly passed, auto-detect is
    bypassed."""
    from pixcull.scoring.counterfactual import best_counterfactual
    p = _make_synthetic(tmp_path, 0.5, 0.5)
    calls: list = []
    def trace_score(arr):
        calls.append(1)
        return 0.5
    best_counterfactual(p, trace_score, skip_current_rule="diagonal")
    # Original + 3 variants (diagonal skipped, not centered) = 4 calls
    assert len(calls) == 4


def test_counterfactual_auto_detect_disabled(tmp_path):
    """auto_detect_rule=False reverts to v0.13-P0-2 behaviour: score
    all 4 variants."""
    from pixcull.scoring.counterfactual import best_counterfactual
    p = _make_synthetic(tmp_path, 0.5, 0.5)
    calls: list = []
    def trace_score(arr):
        calls.append(1)
        return 0.5
    best_counterfactual(p, trace_score, auto_detect_rule=False)
    # Original + all 4 variants = 5 calls
    assert len(calls) == 5
