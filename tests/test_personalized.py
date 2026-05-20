"""P-AI-1 — tests for the personalized keep/maybe-threshold derivation."""
from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.scoring.personalized import (
    BASELINE_KEEP_RATE,
    MAX_THRESHOLD_SHIFT,
    MIN_ANNS_FOR_PERSONALIZATION,
    PersonalProfile,
    apply_threshold_shift,
    load_profile,
    profile_from_preferences,
    save_profile,
)


def test_below_min_annotations_no_shift():
    """User with < MIN_ANNS_FOR_PERSONALIZATION → not active, no shift."""
    prefs = {
        "total_human_annotations": 10,
        "scene_decision_counts": {"landscape": {"keep": 8, "maybe": 1, "cull": 1}},
        "avg_rubric_when": {"keep": {"technical": 4.5}, "cull": {"technical": 2.0}},
    }
    p = profile_from_preferences(prefs)
    assert not p.is_active()
    # apply_threshold_shift returns input unchanged
    base_keep, base_maybe = 0.60, 0.40
    out_keep, out_maybe = apply_threshold_shift(base_keep, base_maybe, p)
    assert out_keep == base_keep
    assert out_maybe == base_maybe


def test_permissive_user_lowers_threshold():
    """A user who keeps 90% gets a NEGATIVE shift (lower threshold)."""
    prefs = {
        "total_human_annotations": 100,
        # 90 keep, 5 maybe, 5 cull = keep_rate 0.9
        "scene_decision_counts": {"landscape": {"keep": 90, "maybe": 5, "cull": 5}},
        "avg_rubric_when": {"keep": {"technical": 4.0}, "cull": {"technical": 2.0}},
    }
    p = profile_from_preferences(prefs)
    assert p.is_active()
    assert p.keep_rate > BASELINE_KEEP_RATE
    assert p.keep_threshold_shift < 0
    keep, maybe = apply_threshold_shift(0.60, 0.40, p)
    assert keep < 0.60   # lowered for permissive user
    assert maybe < 0.40


def test_strict_user_raises_threshold():
    """A user who keeps 20% gets a POSITIVE shift (raise threshold)."""
    prefs = {
        "total_human_annotations": 100,
        "scene_decision_counts": {"landscape": {"keep": 20, "maybe": 20, "cull": 60}},
        "avg_rubric_when": {"keep": {"technical": 4.8}, "cull": {"technical": 2.0}},
    }
    p = profile_from_preferences(prefs)
    assert p.keep_rate < BASELINE_KEEP_RATE
    assert p.keep_threshold_shift > 0
    keep, _ = apply_threshold_shift(0.60, 0.40, p)
    assert keep > 0.60


def test_shift_capped_by_max():
    """Even extreme keep-rates can't move the threshold more than MAX_THRESHOLD_SHIFT."""
    extreme_prefs = {
        "total_human_annotations": 100,
        "scene_decision_counts": {"x": {"keep": 100, "maybe": 0, "cull": 0}},
        "avg_rubric_when": {"keep": {}, "cull": {}},
    }
    p = profile_from_preferences(extreme_prefs)
    assert abs(p.keep_threshold_shift) <= MAX_THRESHOLD_SHIFT + 1e-9


def test_most_cared_axis_from_keep_vs_cull_gap():
    """most_cared_axis is the axis with the largest keep-mean − cull-mean gap."""
    prefs = {
        "total_human_annotations": 100,
        "scene_decision_counts": {"x": {"keep": 50, "maybe": 30, "cull": 20}},
        "avg_rubric_when": {
            "keep": {"technical": 4.5, "subject": 4.7, "composition": 4.9, "light": 4.5, "moment": 4.0, "aesthetic": 4.0},
            "cull": {"technical": 3.5, "subject": 4.6, "composition": 1.0, "light": 4.0, "moment": 4.0, "aesthetic": 4.0},
        },
    }
    p = profile_from_preferences(prefs)
    # composition gap is 3.9 — bigger than every other
    assert p.most_cared_axis == "composition"


def test_save_and_load_round_trip(tmp_path: Path):
    p = PersonalProfile(
        user_id="testuser",
        n_annotations=120,
        keep_rate=0.55,
        cull_rate=0.20,
        keep_threshold_shift=0.05,
        axis_keep_means={"technical": 4.3, "subject": 4.5},
        axis_cull_means={"technical": 2.0, "subject": 3.0},
        most_cared_axis="technical",
    )
    path = tmp_path / "profile.json"
    save_profile(p, path)
    loaded = load_profile(path)
    assert loaded is not None
    assert loaded.user_id == "testuser"
    assert loaded.n_annotations == 120
    assert loaded.keep_threshold_shift == 0.05
    assert loaded.axis_keep_means == {"technical": 4.3, "subject": 4.5}
    assert loaded.most_cared_axis == "technical"
    assert loaded.is_active()  # 120 >= MIN_ANNS_FOR_PERSONALIZATION


def test_load_profile_missing_returns_none(tmp_path: Path):
    assert load_profile(tmp_path / "ghost.json") is None


def test_load_profile_bad_schema(tmp_path: Path):
    """Wrong schema field returns None instead of crashing."""
    p = tmp_path / "bad.json"
    p.write_text('{"schema": "wrong", "user_id": "x"}', encoding="utf-8")
    assert load_profile(p) is None


def test_empty_preferences_defaults_to_baseline():
    """Zero annotations → keep_rate falls back to BASELINE, no shift."""
    p = profile_from_preferences({})
    assert p.n_annotations == 0
    assert not p.is_active()
    assert p.keep_threshold_shift == 0.0   # no shift when no signal
