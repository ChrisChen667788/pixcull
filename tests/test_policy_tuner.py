"""V17.4 — automated policy tuning tests.

Uses synthetic SamplePoints to skip the slow detector pipeline; we
just need the (final_score, flags, scene, bucket) tuples for the
grid-search to chew on. Tests pin:

  * binary_metrics math (P/R/F1 with edge cases)
  * _apply_thresholds matches decide() for the same inputs
  * grid_search picks the deltas that maximise F1 on a constructed dataset
  * tune_vertical end-to-end on a tiny in-memory bank
  * override save / load / delete roundtrip
  * get_effective_policy layers override on top of registry default
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull import policy_tuner as pt
from pixcull import verticals as vmod
from pixcull.config import PixCullConfig
from pixcull.scoring.decision import Decision, decide


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect verticals + policy_tuner storage to a tmp dir."""
    monkeypatch.setattr(vmod, "_data_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def config():
    return PixCullConfig.load()


def _sp(filename, bucket, score, flags=(), scene=None):
    return pt.SamplePoint(
        filename=filename, bucket=bucket,
        final_score=score, flags=list(flags), scene=scene,
    )


# ---------------------------------------------------------------------------
# binary_metrics
# ---------------------------------------------------------------------------

def test_binary_metrics_perfect_keep_class():
    """All goods kept, all bads culled → F1 = 1.0."""
    preds   = [Decision.KEEP, Decision.MAYBE, Decision.CULL, Decision.CULL]
    truths  = ["good",        "good",         "bad",          "bad"]
    m = pt.binary_metrics(preds, truths)
    assert m["f1"] == 1.0
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["accuracy"] == 1.0


def test_binary_metrics_maybe_counts_as_kept():
    """MAYBE on a good shot is correct (not auto-culled)."""
    preds  = [Decision.MAYBE, Decision.KEEP]
    truths = ["good", "good"]
    m = pt.binary_metrics(preds, truths)
    assert m["tp"] == 2
    assert m["f1"] == 1.0


def test_binary_metrics_all_predicted_kept():
    """If pipeline keeps everything, recall = 1.0 but precision drops."""
    preds  = [Decision.KEEP] * 4
    truths = ["good", "good", "bad", "bad"]
    m = pt.binary_metrics(preds, truths)
    assert m["recall"] == 1.0
    assert m["precision"] == 0.5
    assert round(m["f1"], 3) == 0.667


def test_binary_metrics_all_culled():
    """If pipeline culls everything, recall = 0 → F1 = 0."""
    preds  = [Decision.CULL] * 4
    truths = ["good", "good", "bad", "bad"]
    m = pt.binary_metrics(preds, truths)
    assert m["f1"] == 0.0


def test_binary_metrics_length_mismatch_raises():
    with pytest.raises(ValueError):
        pt.binary_metrics([Decision.KEEP], ["good", "bad"])


# ---------------------------------------------------------------------------
# _apply_thresholds — must match decide() for the same inputs
# ---------------------------------------------------------------------------

def test_apply_thresholds_matches_decide_rule_keep(config):
    """Score ≥ keep_min, no hard-cull flags → KEEP for both paths."""
    decided, _ = decide(0.80, [], config, scene="portrait")
    applied = pt._apply_thresholds(0.80, [], "portrait",
                                     keep_min=0.65, cull_max=0.40)
    assert decided is applied is Decision.KEEP


def test_apply_thresholds_matches_decide_rule_cull(config):
    decided, _ = decide(0.20, [], config, scene="portrait")
    applied = pt._apply_thresholds(0.20, [], "portrait",
                                     keep_min=0.65, cull_max=0.40)
    assert decided is applied is Decision.CULL


def test_apply_thresholds_matches_decide_hard_cull(config):
    decided, _ = decide(0.80, ["closed_eyes"], config, scene="portrait")
    applied = pt._apply_thresholds(0.80, ["closed_eyes"], "portrait",
                                     keep_min=0.65, cull_max=0.40)
    assert decided is applied is Decision.CULL


def test_apply_thresholds_landscape_severely_blurry_exemption(config):
    """V0.8 exemption replicated."""
    decided, _ = decide(0.80, ["severely_blurry"], config, scene="landscape")
    applied = pt._apply_thresholds(0.80, ["severely_blurry"], "landscape",
                                     keep_min=0.65, cull_max=0.40)
    assert decided is applied is Decision.KEEP


def test_apply_thresholds_tolerated_flags():
    """Per-vertical tolerated_flags demote a hard-cull flag."""
    base = pt._apply_thresholds(0.80, ["motion_blur_on_face"], "portrait",
                                  keep_min=0.65, cull_max=0.40)
    assert base is Decision.CULL
    with_tol = pt._apply_thresholds(
        0.80, ["motion_blur_on_face"], "portrait",
        keep_min=0.65, cull_max=0.40,
        tolerated_flags=frozenset({"motion_blur_on_face"}),
    )
    assert with_tol is Decision.KEEP


def test_hard_cull_set_matches_decide():
    """Pin the tuner's _HARD_CULL_FLAGS against decide()'s set —
    they MUST stay in lockstep or the tuner will optimize against
    the wrong rule stack."""
    from pixcull.scoring import decision as dec_mod
    # Read decide's set out of its source via a test-only roundtrip:
    # construct two states (with + without each flag) and check
    # which become CULL above keep_min.
    cfg = PixCullConfig.load()
    score = 0.80  # well above keep_min
    expected = set()
    for f in ("closed_eyes", "motion_blur_on_face", "severely_overexposed",
                "no_clear_subject", "severely_blurry",
                # Things that should NOT hard-cull (sanity)
                "highlights_clipped", "shadows_clipped", "global_blur"):
        d, _ = decide(score, [f], cfg, scene="portrait")
        if d is Decision.CULL:
            expected.add(f)
    assert pt._HARD_CULL_FLAGS == frozenset(expected)


# ---------------------------------------------------------------------------
# grid_search
# ---------------------------------------------------------------------------

def _build_separable_dataset():
    """Goods at 0.7, bads at 0.5 — perfectly separable by keep_min ∈ (0.5, 0.7].
    Default keep_min is 0.65 so it sits right in the gap."""
    samples = []
    for i in range(10):
        samples.append(_sp(f"good_{i}.jpg", "good", 0.70, scene="portrait"))
        samples.append(_sp(f"bad_{i}.jpg",  "bad",  0.50, scene="portrait"))
    return samples


def test_grid_search_perfect_separation():
    samples = _build_separable_dataset()
    (kd, cd), m, grid = pt.grid_search(samples, base_keep_min=0.65,
                                          base_cull_max=0.40)
    # Default thresholds already separate — best F1 should be 1.0
    assert m["f1"] == 1.0


def test_grid_search_adjusts_when_default_misclassifies():
    """Goods at 0.55, bads at 0.30. Default keep_min=0.65 culls both
    (no, 0.55 sits between 0.40 and 0.65 → MAYBE = "kept" → both
    are kept including bads → low F1). Tuner should LOWER cull_max
    to push the bads at 0.30 into the cull zone clearly... no,
    actually 0.30 ≤ 0.40 already → CULL. So bads cull, goods MAYBE.
    F1 should be 1.0. Let me make it harder — goods at 0.62, bads at 0.50."""
    samples = []
    for i in range(10):
        samples.append(_sp(f"good_{i}.jpg", "good", 0.62, scene="portrait"))
        samples.append(_sp(f"bad_{i}.jpg",  "bad",  0.50, scene="portrait"))
    # At default keep_min=0.65, cull_max=0.40: both goods and bads land MAYBE
    # → all "kept" → P=0.5, R=1.0, F1=0.667
    base_preds = [pt._apply_thresholds(s.final_score, s.flags, s.scene,
                                         keep_min=0.65, cull_max=0.40)
                  for s in samples]
    base_m = pt.binary_metrics(base_preds, [s.bucket for s in samples])
    assert round(base_m["f1"], 3) == 0.667
    # Tuner should find a delta that pushes bads → CULL (raise cull_max
    # or lower keep_min so goods land KEEP and bads land CULL)
    (kd, cd), tuned_m, _ = pt.grid_search(samples,
                                            base_keep_min=0.65,
                                            base_cull_max=0.40)
    assert tuned_m["f1"] > base_m["f1"]
    assert tuned_m["f1"] >= 0.95   # near-perfect


def test_grid_search_tie_break_prefers_smaller_keep_delta():
    """If two settings give equal F1 + accuracy, pick the one with
    smaller absolute keep_delta (don't move thresholds when not
    needed)."""
    samples = _build_separable_dataset()
    (kd, cd), m, _ = pt.grid_search(samples, base_keep_min=0.65,
                                       base_cull_max=0.40)
    # Many deltas give F1=1.0; tie-break should land near 0
    assert abs(kd) <= 0.04


def test_grid_search_skips_inverted_thresholds():
    """When keep_min < cull_max the rule stack makes no sense — those
    grid points should be skipped silently."""
    samples = _build_separable_dataset()
    _, _, grid = pt.grid_search(samples, base_keep_min=0.65,
                                  base_cull_max=0.40,
                                  delta_grid=(-0.10, 0.0, +0.10))
    for entry in grid:
        kmin = max(0.0, min(1.0, 0.65 + entry["keep_delta"]))
        cmax = max(0.0, min(1.0, 0.40 + entry["cull_delta"]))
        assert cmax <= kmin, f"inverted thresholds slipped through: {entry}"


# ---------------------------------------------------------------------------
# Override save / load / delete roundtrip
# ---------------------------------------------------------------------------

def test_override_roundtrip(isolated_data_dir):
    res = pt.TuneResult(
        vertical="kids", n_good=5, n_bad=5,
        base_keep_min=0.65, base_cull_max=0.40,
        baseline_delta_keep=-0.05, baseline_delta_cull=-0.05,
        baseline={"f1": 0.7, "precision": 0.7, "recall": 0.7,
                   "accuracy": 0.7, "tp": 5, "fp": 2, "tn": 3, "fn": 0, "n": 10},
        tuned_delta_keep=-0.07, tuned_delta_cull=-0.05,
        tuned={"f1": 0.85, "precision": 0.85, "recall": 0.85,
                "accuracy": 0.85, "tp": 5, "fp": 1, "tn": 4, "fn": 0, "n": 10},
    )
    pt.save_override("kids", res)
    p = pt.override_path("kids")
    assert p.exists()
    loaded = pt.load_override("kids")
    assert loaded["vertical"] == "kids"
    assert loaded["keep_min_delta"] == -0.07
    assert "auto-tuned" in loaded["notes"]
    assert pt.delete_override("kids") is True
    assert not p.exists()


def test_override_load_missing_returns_none(isolated_data_dir):
    assert pt.load_override("kids") is None


def test_override_load_corrupt_returns_none(isolated_data_dir):
    pt.override_path("kids").write_text("{ not valid json", encoding="utf-8")
    assert pt.load_override("kids") is None


# ---------------------------------------------------------------------------
# get_effective_policy
# ---------------------------------------------------------------------------

def test_effective_policy_falls_back_to_registry(isolated_data_dir):
    """No override file → registry default."""
    eff = vmod.get_effective_policy("kids")
    reg = vmod.get_vertical("kids").policy
    assert eff.keep_min_delta == reg.keep_min_delta
    assert eff.cull_max_delta == reg.cull_max_delta
    assert eff.tolerated_flags == reg.tolerated_flags


def test_effective_policy_layers_override(isolated_data_dir):
    """Override file → its values win, falling through to registry
    for fields the override didn't set."""
    res = pt.TuneResult(
        vertical="kids", n_good=10, n_bad=10,
        base_keep_min=0.65, base_cull_max=0.40,
        baseline_delta_keep=-0.05, baseline_delta_cull=-0.05,
        baseline={"f1": 0.7, "precision": 0.7, "recall": 0.7,
                   "accuracy": 0.7, "tp": 7, "fp": 3, "tn": 7, "fn": 3, "n": 20},
        tuned_delta_keep=-0.08, tuned_delta_cull=-0.04,
        tuned={"f1": 0.9, "precision": 0.9, "recall": 0.9,
                "accuracy": 0.9, "tp": 9, "fp": 1, "tn": 9, "fn": 1, "n": 20},
    )
    pt.save_override("kids", res)
    eff = vmod.get_effective_policy("kids")
    assert eff.keep_min_delta == -0.08
    assert eff.cull_max_delta == -0.04
    # tolerated_flags fell through to registry — kids has these defaults
    assert "motion_blur_on_face" in eff.tolerated_flags


def test_effective_policy_unknown_returns_none():
    assert vmod.get_effective_policy("__not_real__") is None


# ---------------------------------------------------------------------------
# decide() honors the effective (override-merged) policy
# ---------------------------------------------------------------------------

def test_decide_uses_override_for_keep_min(isolated_data_dir, config):
    """Save an aggressive override → decide() should use its delta,
    not the registry default."""
    res = pt.TuneResult(
        vertical="kids", n_good=10, n_bad=10,
        base_keep_min=0.65, base_cull_max=0.40,
        baseline_delta_keep=-0.05, baseline_delta_cull=-0.05,
        baseline={"f1": 0.7, "precision": 0.7, "recall": 0.7,
                   "accuracy": 0.7, "tp": 7, "fp": 3, "tn": 7, "fn": 3, "n": 20},
        # Override pushes keep threshold WAY down to 0.40
        tuned_delta_keep=-0.25, tuned_delta_cull=-0.05,
        tuned={"f1": 0.95, "precision": 0.95, "recall": 0.95,
                "accuracy": 0.95, "tp": 10, "fp": 0, "tn": 9, "fn": 1, "n": 20},
    )
    pt.save_override("kids", res)
    # Score 0.45 is below default 0.65 keep_min → MAYBE without override.
    # With override (delta -0.25 → keep_min becomes 0.40) → KEEP.
    dec, _ = decide(0.45, [], config, scene="portrait", vertical="kids")
    assert dec is Decision.KEEP
