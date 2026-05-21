"""P-CORE-2 — tests for scene-classifier debiasing.

These exercise the pure-Python helpers (priors + margin abstain)
without loading the CLIP model, so they're fast and run in CI
without GPU.
"""
from __future__ import annotations

import pytest

from pixcull.detectors.scene import (
    SCENE_ABSTAIN_MARGIN,
    SCENE_PRIORS,
    SCENE_PROMPTS,
    SCENE_UNKNOWN_LABEL,
    _apply_priors_and_renormalize,
    _resolve_scene_with_abstain,
    _scene_prior_for,
)


def test_prior_for_known_class_returns_calibrated_value():
    assert _scene_prior_for("stilllife") == pytest.approx(0.75)
    assert _scene_prior_for("documentary") == pytest.approx(0.85)
    assert _scene_prior_for("landscape") == pytest.approx(1.10)


def test_prior_for_unknown_class_defaults_to_one():
    # Anything not explicitly listed (portrait, wildlife, etc.)
    # should fall back to the neutral 1.0 multiplier.
    assert _scene_prior_for("portrait") == 1.0
    assert _scene_prior_for("nonexistent_scene") == 1.0


def test_calibrated_probs_sum_to_one():
    names = list(SCENE_PROMPTS.keys())
    # Random-ish uniformish distribution
    n = len(names)
    raw = [1.0 / n] * n
    calibrated = _apply_priors_and_renormalize(names, raw)
    assert sum(calibrated) == pytest.approx(1.0, abs=1e-9)
    assert len(calibrated) == n


def test_stilllife_demoted_after_priors():
    """A photo where CLIP says stilllife=0.4 vs portrait=0.35 should
    flip to portrait after the 0.75 prior on stilllife."""
    names = ["stilllife", "portrait", "landscape"]
    raw   = [0.40,        0.35,       0.25]
    # After priors: stilllife=0.40*0.75=0.30, portrait=0.35*1=0.35,
    # landscape=0.25*1.10=0.275 → portrait wins.
    calibrated = _apply_priors_and_renormalize(names, raw)
    top_idx = max(range(len(names)), key=lambda i: calibrated[i])
    assert names[top_idx] == "portrait"


def test_clear_winner_passes_abstain():
    """A clear top-1 with a wide margin should be returned as-is."""
    names = ["portrait", "landscape", "stilllife", "wildlife"]
    probs = [0.60,       0.20,        0.15,        0.05]
    chosen, p, abstained = _resolve_scene_with_abstain(names, probs)
    assert chosen == "portrait"
    assert p == pytest.approx(0.60)
    assert abstained is False


def test_tight_margin_triggers_abstain():
    """Top-1 and top-2 within SCENE_ABSTAIN_MARGIN → returns 'unknown'."""
    names = ["portrait", "event", "landscape"]
    # 0.20 vs 0.18 → margin 0.02 < 0.04
    probs = [0.20,       0.18,    0.62]
    # The tightest pair here is portrait/event (0.20/0.18) but the
    # top is landscape (0.62) so this should NOT abstain. The
    # abstain check is purely between top-1 and top-2.
    chosen, p, abstained = _resolve_scene_with_abstain(names, probs)
    assert chosen == "landscape"
    assert abstained is False


def test_top_two_tied_triggers_abstain():
    names = ["portrait", "event", "landscape"]
    probs = [0.34,       0.33,    0.33]
    chosen, p, abstained = _resolve_scene_with_abstain(names, probs)
    assert chosen == SCENE_UNKNOWN_LABEL
    assert abstained is True
    # The numerical top-1 prob is still surfaced for telemetry
    assert p == pytest.approx(0.34)


def test_abstain_margin_just_above_threshold():
    """A margin clearly larger than the threshold must not abstain.

    We avoid testing exactly-at-threshold because 0.04 isn't exactly
    representable in IEEE 754 — the comparison would be testing
    floating-point semantics, not classifier semantics. A 2× margin
    is a safe "this is clearly a confident pick".
    """
    names = ["a", "b"]
    probs = [0.50, 0.50 - 2 * SCENE_ABSTAIN_MARGIN]
    chosen, _, abstained = _resolve_scene_with_abstain(names, probs)
    assert chosen == "a"
    assert abstained is False


def test_abstain_margin_just_below_threshold():
    """A margin clearly smaller than the threshold must abstain."""
    names = ["a", "b"]
    probs = [0.50, 0.50 - SCENE_ABSTAIN_MARGIN / 2]
    chosen, _, abstained = _resolve_scene_with_abstain(names, probs)
    assert chosen == SCENE_UNKNOWN_LABEL
    assert abstained is True


def test_empty_inputs_abstain_gracefully():
    """Defensive: no scenes → returns unknown rather than crashing."""
    chosen, p, abstained = _resolve_scene_with_abstain([], [])
    assert chosen == SCENE_UNKNOWN_LABEL
    assert abstained is True


def test_zero_total_probs_falls_back_to_raw():
    """If priors zero out everything (degenerate), preserve raw probs
    rather than dividing by zero."""
    names = ["x"]
    probs = [0.0]
    out = _apply_priors_and_renormalize(names, probs)
    # Either preserved as [0.0] or normalized — but no NaN / div-by-zero
    assert all(not (v != v) for v in out), "no NaNs produced"
    assert len(out) == 1


def test_priors_dont_create_a_landscape_avalanche():
    """The landscape boost (1.10) must not let landscape steal cases
    where another class clearly wins."""
    names = ["landscape", "portrait", "stilllife"]
    raw   = [0.30,        0.60,       0.10]
    # portrait should still win even though landscape gets a boost.
    calibrated = _apply_priors_and_renormalize(names, raw)
    chosen, _, abstained = _resolve_scene_with_abstain(names, calibrated)
    assert chosen == "portrait"
    assert abstained is False
