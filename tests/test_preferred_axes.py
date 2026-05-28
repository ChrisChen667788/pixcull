"""Tests for pixcull/preferred_axes.py — v0.13-P2-1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.preferred_axes import (
    AXES,
    AxisPrefs,
    load,
    prefs_path,
    reset_to_defaults,
    reweight,
    save,
)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_axes_match_canonical_six():
    """Stay in sync with attribution.AXES."""
    assert set(AXES) == {
        "technical", "subject", "composition",
        "light", "moment", "aesthetic",
    }


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------


def test_default_prefs_no_mute_no_boost():
    p = AxisPrefs()
    assert p.muted == []
    assert p.weight_boost == {}
    for ax in AXES:
        assert not p.is_muted(ax)
        assert p.boost_for(ax) == 1.0


# ---------------------------------------------------------------------------
# boost clamp
# ---------------------------------------------------------------------------


def test_boost_clamps_to_max():
    p = AxisPrefs(weight_boost={"moment": 99.0})
    assert p.boost_for("moment") == 3.0


def test_boost_clamps_to_min():
    p = AxisPrefs(weight_boost={"technical": 0.0})
    assert p.boost_for("technical") == 0.1


def test_boost_normal_range_unchanged():
    p = AxisPrefs(weight_boost={"composition": 1.5})
    assert p.boost_for("composition") == 1.5


# ---------------------------------------------------------------------------
# reweight
# ---------------------------------------------------------------------------


def test_reweight_drops_muted():
    prefs = AxisPrefs(muted=["technical"])
    scores = {"technical": 0.5, "subject": 0.8}
    out = reweight(scores, prefs)
    assert "technical" not in out
    assert out["subject"] == 0.8


def test_reweight_applies_boost():
    prefs = AxisPrefs(weight_boost={"moment": 1.5})
    scores = {"moment": 0.4, "subject": 0.4}
    out = reweight(scores, prefs)
    assert abs(out["moment"] - 0.6) < 1e-9
    assert out["subject"] == 0.4   # unchanged


def test_reweight_ignores_garbage_score():
    prefs = AxisPrefs()
    out = reweight({"technical": "not a number"}, prefs)
    assert out == {}


def test_reweight_combines_mute_and_boost():
    prefs = AxisPrefs(muted=["light"],
                      weight_boost={"composition": 0.5})
    out = reweight({"light": 0.9, "composition": 0.8,
                    "subject": 0.6}, prefs)
    assert "light" not in out
    assert abs(out["composition"] - 0.4) < 1e-9
    assert out["subject"] == 0.6


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def test_save_then_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = AxisPrefs(muted=["technical"],
                  weight_boost={"moment": 1.4, "aesthetic": 0.8})
    save(p)
    loaded = load()
    assert loaded.muted == ["technical"]
    assert loaded.weight_boost == {"moment": 1.4, "aesthetic": 0.8}


def test_load_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = load()
    assert p.muted == []
    assert p.weight_boost == {}


def test_load_corrupt_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    prefs_path().write_text("not json {", encoding="utf-8")
    p = load()
    assert p.muted == []


def test_load_drops_unknown_axis(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    prefs_path().write_text(json.dumps({
        "version": 1,
        "muted": ["technical", "not_a_real_axis"],
        "weight_boost": {"moment": 1.5, "bogus": 2.0},
    }), encoding="utf-8")
    p = load()
    assert p.muted == ["technical"]
    assert "bogus" not in p.weight_boost
    assert p.weight_boost == {"moment": 1.5}


def test_load_unknown_version_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    prefs_path().write_text(json.dumps({
        "version": 99,
        "muted": ["technical"],
    }), encoding="utf-8")
    p = load()
    assert p.muted == []


def test_reset_writes_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = reset_to_defaults()
    assert p.muted == []
    # File exists + can be reloaded
    assert prefs_path().exists()
    assert load().muted == []
