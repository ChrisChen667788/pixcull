"""Tests for pixcull/scoring/hard_examples.py — v0.11-P1-4."""

from __future__ import annotations

import json
from pathlib import Path

from pixcull.scoring.hard_examples import (
    HardExampleStats,
    Reversal,
    build_stats,
    clear_cache,
    get_stats,
    _extract_reversal,
    _is_high_confidence,
)


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# _is_high_confidence
# ---------------------------------------------------------------------------


def test_high_confidence_near_one():
    assert _is_high_confidence(0.95)
    assert _is_high_confidence(0.85)


def test_high_confidence_near_zero():
    assert _is_high_confidence(0.10)
    assert _is_high_confidence(0.15)


def test_high_confidence_middle_rejected():
    assert not _is_high_confidence(0.50)
    assert not _is_high_confidence(0.60)
    assert not _is_high_confidence(None)


# ---------------------------------------------------------------------------
# _extract_reversal
# ---------------------------------------------------------------------------


def test_extract_reversal_happy_keep_to_cull():
    row = {
        "filename": "p.jpg",
        "model_decision": "keep",
        "decision": "cull",
        "rescorer_prob_keep": 0.90,
        "scene": "wedding",
        "vertical": "wedding",
    }
    rv = _extract_reversal(row)
    assert rv is not None
    assert rv.filename == "p.jpg"
    assert rv.model_decision == "keep"
    assert rv.human_decision == "cull"
    assert rv.scene == "wedding"


def test_extract_reversal_uses_rescorer_pred_alias():
    """Legacy schemas use rescorer_pred instead of model_decision."""
    row = {
        "filename": "p.jpg",
        "rescorer_pred": "cull",
        "decision": "keep",
        "rescorer_prob_keep": 0.10,
        "scene": "portrait",
    }
    rv = _extract_reversal(row)
    assert rv is not None
    assert rv.model_decision == "cull"
    assert rv.scene == "portrait"
    assert rv.vertical == "portrait"  # fills from scene


def test_extract_reversal_agreement_skipped():
    """Model and human agree → not a reversal."""
    row = {
        "filename": "p.jpg",
        "model_decision": "keep",
        "decision": "keep",
        "rescorer_prob_keep": 0.95,
    }
    assert _extract_reversal(row) is None


def test_extract_reversal_low_confidence_skipped():
    """Model wasn't certain → ambiguity, not a 'hard example'."""
    row = {
        "filename": "p.jpg",
        "model_decision": "keep",
        "decision": "cull",
        "rescorer_prob_keep": 0.55,
    }
    assert _extract_reversal(row) is None


def test_extract_reversal_missing_keys_skipped():
    assert _extract_reversal({}) is None
    assert _extract_reversal({"filename": "p.jpg"}) is None


# ---------------------------------------------------------------------------
# build_stats — end-to-end on a tmpdir
# ---------------------------------------------------------------------------


def test_build_stats_empty_dir_returns_empty(tmp_path):
    s = build_stats(tmp_path / "absent")
    assert s.reversals == []
    assert s.scenes_with_reversals == {}


def test_build_stats_aggregates_across_runs(tmp_path):
    runs = tmp_path / "runs"
    # run 1 — 2 wedding reversals
    _write_jsonl(runs / "run1" / "annotations.jsonl", [
        {"filename": "a.jpg", "model_decision": "keep",
         "decision": "cull", "rescorer_prob_keep": 0.92,
         "scene": "wedding"},
        {"filename": "b.jpg", "model_decision": "cull",
         "decision": "keep", "rescorer_prob_keep": 0.05,
         "scene": "wedding"},
    ])
    # run 2 — 1 portrait reversal + 1 agreement (skipped)
    _write_jsonl(runs / "run2" / "annotations.jsonl", [
        {"filename": "c.jpg", "model_decision": "keep",
         "decision": "cull", "rescorer_prob_keep": 0.88,
         "scene": "portrait"},
        {"filename": "d.jpg", "model_decision": "keep",
         "decision": "keep", "rescorer_prob_keep": 0.99,
         "scene": "portrait"},
    ])
    s = build_stats(runs)
    assert len(s.reversals) == 3
    assert s.scenes_with_reversals == {"wedding": 2, "portrait": 1}


def test_boost_for_dominant_scene_is_one(tmp_path):
    runs = tmp_path / "runs"
    _write_jsonl(runs / "run1" / "annotations.jsonl", [
        {"filename": f"w{i}.jpg", "model_decision": "keep",
         "decision": "cull", "rescorer_prob_keep": 0.90,
         "scene": "wedding"} for i in range(10)
    ] + [
        {"filename": "p.jpg", "model_decision": "keep",
         "decision": "cull", "rescorer_prob_keep": 0.90,
         "scene": "portrait"},
    ])
    s = build_stats(runs)
    # wedding has 10 reversals → max → boost 1.0
    assert s.boost_for(scene="wedding") == 1.0
    # portrait has 1 reversal out of 10 max → 0.1
    assert abs(s.boost_for(scene="portrait") - 0.1) < 1e-9
    # Unknown scene → 0
    assert s.boost_for(scene="moon-landing") == 0.0
    # Empty inputs → 0
    assert s.boost_for() == 0.0


def test_boost_for_uses_vertical_fallback(tmp_path):
    runs = tmp_path / "runs"
    _write_jsonl(runs / "run1" / "annotations.jsonl", [
        {"filename": "w.jpg", "model_decision": "keep",
         "decision": "cull", "rescorer_prob_keep": 0.90,
         "scene": "wedding", "vertical": "wedding"},
    ])
    s = build_stats(runs)
    assert s.boost_for(vertical="wedding") > 0


# ---------------------------------------------------------------------------
# get_stats caching
# ---------------------------------------------------------------------------


def test_get_stats_caches_within_ttl(tmp_path):
    clear_cache()
    runs = tmp_path / "runs"
    _write_jsonl(runs / "r1" / "annotations.jsonl", [
        {"filename": "a.jpg", "model_decision": "keep",
         "decision": "cull", "rescorer_prob_keep": 0.90,
         "scene": "wedding"},
    ])
    s1 = get_stats(runs)
    # Mutate the file — cached call should NOT pick this up
    _write_jsonl(runs / "r1" / "annotations.jsonl", [])
    s2 = get_stats(runs, ttl_sec=999)
    assert s1 is s2   # exact same instance


def test_get_stats_rebuilds_after_clear_cache(tmp_path):
    clear_cache()
    runs = tmp_path / "runs"
    _write_jsonl(runs / "r1" / "annotations.jsonl", [
        {"filename": "a.jpg", "model_decision": "keep",
         "decision": "cull", "rescorer_prob_keep": 0.90,
         "scene": "wedding"},
    ])
    s1 = get_stats(runs)
    clear_cache()
    # Even at ttl 999 the cleared cache forces a fresh build
    s2 = get_stats(runs, ttl_sec=999)
    assert s1 is not s2
