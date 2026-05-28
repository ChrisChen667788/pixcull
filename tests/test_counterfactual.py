"""Tests for pixcull/scoring/counterfactual.py — v0.13-P0-2."""

from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.scoring.counterfactual import (
    Counterfactual,
    RULE_VARIANTS,
    VARIANT_FNS,
    best_counterfactual,
    generate_variants,
)


@pytest.fixture
def fake_jpg(tmp_path):
    """Write a tiny solid-color RGB JPEG; PIL can open it."""
    from PIL import Image
    p = tmp_path / "fake.jpg"
    Image.new("RGB", (200, 150), color=(180, 90, 200)).save(p)
    return p


def test_rule_variants_canonical_four():
    assert set(RULE_VARIANTS) == {
        "rule_of_thirds", "centered", "diagonal", "golden_ratio",
    }
    assert len(RULE_VARIANTS) == 4
    # All have a corresponding fn
    for r in RULE_VARIANTS:
        assert r in VARIANT_FNS


def test_generate_variants_returns_all_four(fake_jpg):
    vs = generate_variants(fake_jpg)
    assert set(vs.keys()) == set(RULE_VARIANTS)
    # Each is a numpy ndarray with shape (H, W, 3)
    for arr in vs.values():
        assert arr.ndim == 3
        assert arr.shape[-1] == 3


def test_variants_are_actually_crops_not_originals(fake_jpg):
    """The cropped variants should be slightly smaller than the
    original (we crop ~10% to make room for the re-frame)."""
    import numpy as np
    from PIL import Image
    orig = np.asarray(Image.open(fake_jpg).convert("RGB"))
    for arr in generate_variants(fake_jpg).values():
        assert arr.shape[0] < orig.shape[0] or arr.shape[1] < orig.shape[1]


def test_counterfactual_label_human_readable():
    cf = Counterfactual(
        rule="rule_of_thirds", delta=0.08,
        new_score=0.82, original_score=0.74,
    )
    assert "rule of thirds" in cf.label
    assert "+0.08" in cf.label


def test_counterfactual_negative_delta_in_label():
    cf = Counterfactual(
        rule="centered", delta=-0.05,
        new_score=0.50, original_score=0.55,
    )
    # Use Unicode minus per the label spec
    assert "−0.05" in cf.label or "-0.05" in cf.label


def test_best_counterfactual_picks_highest_delta(fake_jpg):
    """Mock the score function to award +0.10 only for diagonal."""
    rule_seen = {"count": 0}
    def mock_score(arr):
        # Original = first call → 0.50; subsequent variants:
        #   rule_of_thirds=0.50, centered=0.50, diagonal=0.60, golden=0.50
        if rule_seen["count"] == 0:
            rule_seen["count"] = 1
            return 0.50
        rule_seen["count"] += 1
        # Variants run in dict-insertion order (Python 3.7+).  Diagonal
        # is at index 3 → 4th call (counts: 0 orig, then 1,2,3,4)
        return 0.60 if rule_seen["count"] == 4 else 0.50
    # v0.13.3 added auto_detect_rule which would skip whatever rule
    # the fake purple test image classifies as; disable for this
    # pre-v0.13.3 expectation that all 4 variants are scored.
    cf = best_counterfactual(fake_jpg, mock_score, auto_detect_rule=False)
    assert cf is not None
    assert cf.rule == "diagonal"
    assert abs(cf.delta - 0.10) < 1e-6


def test_best_counterfactual_returns_none_below_threshold(fake_jpg):
    """No variant improves by ≥ 0.01 → suppress chip."""
    def flat_score(arr):
        return 0.50
    assert best_counterfactual(fake_jpg, flat_score) is None


def test_best_counterfactual_skips_current_rule(fake_jpg):
    """skip_current_rule excludes that variant from the candidate set."""
    calls = []
    def mock_score(arr):
        calls.append(arr.shape)
        return 0.50  # always flat → returns None, but check we
                    # only got called for 4 cases (1 orig + 3 variants
                    # since centered is skipped)
    best_counterfactual(fake_jpg, mock_score,
                        skip_current_rule="centered",
                        auto_detect_rule=False)
    # 1 original + 3 variants (centered skipped)
    assert len(calls) == 4


def test_best_counterfactual_picks_higher_when_tied(fake_jpg):
    """First-encountered higher delta wins on ties via > (strict)."""
    seq = iter([0.50, 0.60, 0.60, 0.60, 0.60])
    def mock_score(arr):
        return next(seq)
    cf = best_counterfactual(fake_jpg, mock_score, auto_detect_rule=False)
    # All 4 variants tie at 0.60 - the first one encountered (rule_of_thirds)
    # wins via "delta > best.delta" being False for ties.
    assert cf is not None
    assert cf.rule == "rule_of_thirds"
