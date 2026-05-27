"""Tests for pixcull.team — v0.10-P1-1 studio multi-user workflows.

Covers
------
* load_user_taste: missing files / malformed JSON / valid weights
* aggregate_taste: mean / median / stddev math
* discrepancy_report: z-score signs + sort order
* set/get/clear_head_shooter: round-trip + idempotency
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.team.taste import (
    PROFILE_AXES,
    aggregate_taste,
    discrepancy_report,
    load_user_taste,
)
from pixcull.team.roles import (
    clear_head_shooter,
    get_head_shooter,
    set_head_shooter,
)


# ---------------------------------------------------------------------------
# taste.load_user_taste
# ---------------------------------------------------------------------------


def test_load_user_taste_missing_returns_none(tmp_path: Path):
    assert load_user_taste(tmp_path / "nope.json") is None


def test_load_user_taste_malformed_json_returns_none(tmp_path: Path):
    p = tmp_path / "pref.json"
    p.write_text("not-json{{{", encoding="utf-8")
    assert load_user_taste(p) is None


def test_load_user_taste_missing_axis_weights_returns_none(tmp_path: Path):
    p = tmp_path / "pref.json"
    p.write_text('{"other_key": "value"}', encoding="utf-8")
    assert load_user_taste(p) is None


def test_load_user_taste_loads_valid_weights(tmp_path: Path):
    p = tmp_path / "pref.json"
    p.write_text(json.dumps({
        "axis_weights": {
            "technical":   0.20,
            "subject":     0.15,
            "composition": 0.25,
            "light":       0.10,
            "moment":      0.20,
            "aesthetic":   0.10,
            "irrelevant":  0.99,    # dropped — not in PROFILE_AXES
        },
    }), encoding="utf-8")
    out = load_user_taste(p)
    assert out is not None
    assert set(out.keys()) == set(PROFILE_AXES)
    assert out["composition"] == 0.25
    assert "irrelevant" not in out


# ---------------------------------------------------------------------------
# taste.aggregate_taste
# ---------------------------------------------------------------------------


def test_aggregate_taste_empty_input():
    assert aggregate_taste({}) == {}


def test_aggregate_taste_mean_median_stddev():
    tastes = {
        "alice": {"composition": 0.10, "moment": 0.30},
        "bob":   {"composition": 0.20, "moment": 0.20},
        "cathy": {"composition": 0.30, "moment": 0.10},
    }
    stats = aggregate_taste(tastes)
    # composition: [0.10, 0.20, 0.30] → mean 0.20, median 0.20, stddev ≈ 0.0816
    c = stats["composition"]
    assert c["mean"]   == pytest.approx(0.20, abs=1e-9)
    assert c["median"] == pytest.approx(0.20, abs=1e-9)
    assert c["stddev"] == pytest.approx(0.0816, abs=1e-3)
    assert c["n"] == 3
    # moment: same values reversed → same stats
    m = stats["moment"]
    assert m["mean"]   == pytest.approx(0.20, abs=1e-9)


def test_aggregate_taste_drops_unknown_axes():
    """Aggregation ignores keys that aren't in PROFILE_AXES so
    weird preferences.json files can't pollute the team baseline."""
    tastes = {"alice": {"weird_axis": 0.5, "composition": 0.3}}
    stats = aggregate_taste(tastes)
    assert "weird_axis" not in stats
    assert stats["composition"]["mean"] == 0.3


def test_aggregate_taste_skips_users_with_no_dict():
    tastes = {"alice": "not-a-dict", "bob": {"moment": 0.4}}  # type: ignore
    stats = aggregate_taste(tastes)
    assert "moment" in stats
    assert stats["moment"]["n"] == 1


# ---------------------------------------------------------------------------
# taste.discrepancy_report
# ---------------------------------------------------------------------------


def test_discrepancy_report_returns_zscores():
    tastes = {
        "alice": {"composition": 0.10},
        "bob":   {"composition": 0.20},
        "cathy": {"composition": 0.30},
    }
    rep = discrepancy_report(tastes)
    # |z| desc → alice and cathy (deltas ±0.10) tie at top
    assert len(rep) == 3
    top_two = rep[:2]
    assert all(abs(r["delta"]) == pytest.approx(0.10) for r in top_two)
    bob = next(r for r in rep if r["user_id"] == "bob")
    assert bob["delta"] == pytest.approx(0.0)
    assert bob["stddev_n"] == pytest.approx(0.0)


def test_discrepancy_report_handles_zero_stddev():
    """When everyone has the same weight, stddev is 0 and we
    return 0 z-scores (no divide-by-zero)."""
    tastes = {"a": {"composition": 0.20}, "b": {"composition": 0.20}}
    rep = discrepancy_report(tastes)
    for r in rep:
        assert r["delta"] == 0.0
        assert r["stddev_n"] == 0.0


def test_discrepancy_report_empty_input_returns_empty_list():
    assert discrepancy_report({}) == []


# ---------------------------------------------------------------------------
# roles.set/get/clear_head_shooter
# ---------------------------------------------------------------------------


def _bootstrap_event(tmp_path: Path, event_id: str = "evt_x") -> Path:
    """Create a minimal event JSON file so the roles module has
    something to mutate."""
    events = tmp_path / "events"
    events.mkdir()
    p = events / f"{event_id}.json"
    p.write_text(json.dumps({
        "schema":   "pixcull.sync.event/v1",
        "event_id": event_id,
        "token":    "abcdef",
        "run_id":   "r1",
    }), encoding="utf-8")
    return p


def test_set_head_shooter_round_trip(tmp_path: Path):
    _bootstrap_event(tmp_path, "evt_a")
    assert set_head_shooter(tmp_path, "evt_a", "alice") is True
    assert get_head_shooter(tmp_path, "evt_a") == "alice"


def test_set_head_shooter_idempotent(tmp_path: Path):
    _bootstrap_event(tmp_path, "evt_a")
    set_head_shooter(tmp_path, "evt_a", "alice")
    # Second assignment to the same value → True, no error
    assert set_head_shooter(tmp_path, "evt_a", "alice") is True
    # Override to a different user works
    set_head_shooter(tmp_path, "evt_a", "bob")
    assert get_head_shooter(tmp_path, "evt_a") == "bob"


def test_set_head_shooter_missing_event_returns_false(tmp_path: Path):
    # No event file → False
    assert set_head_shooter(tmp_path, "evt_missing", "alice") is False
    assert get_head_shooter(tmp_path, "evt_missing") is None


def test_clear_head_shooter(tmp_path: Path):
    _bootstrap_event(tmp_path, "evt_a")
    set_head_shooter(tmp_path, "evt_a", "alice")
    assert clear_head_shooter(tmp_path, "evt_a") is True
    assert get_head_shooter(tmp_path, "evt_a") is None
    # Idempotent on the already-cleared event → False (nothing to remove)
    assert clear_head_shooter(tmp_path, "evt_a") is False


def test_head_shooter_truncates_oversized_user_id(tmp_path: Path):
    _bootstrap_event(tmp_path, "evt_a")
    huge = "x" * 500
    set_head_shooter(tmp_path, "evt_a", huge)
    out = get_head_shooter(tmp_path, "evt_a")
    assert out is not None
    assert len(out) <= 80


def test_path_traversal_safe(tmp_path: Path):
    """The event_id sanitiser must collapse / + \\ so a malicious
    or buggy caller can't escape the events dir."""
    # No file at that escaped path either way, so this test just
    # confirms we don't crash + return False cleanly.
    assert set_head_shooter(tmp_path, "../etc/passwd", "x") is False
