"""Tests for pixcull/shortcuts.py — v0.12-P0-1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull import shortcuts as sh
from pixcull.shortcuts import (
    ACTIONS,
    Action,
    Binding,
    Conflict,
    action,
    actions_for_scope,
    default_bindings,
    find_conflicts,
    load_bindings,
    reset_to_defaults,
    save_bindings,
    shortcuts_path,
)


# ---------------------------------------------------------------------------
# catalogue integrity
# ---------------------------------------------------------------------------


def test_action_ids_unique():
    ids = [a.id for a in ACTIONS]
    assert len(ids) == len(set(ids)), "duplicate action ids"


def test_action_scopes_valid():
    valid = {"grid", "lightbox", "compare", "inspector", "global"}
    for a in ACTIONS:
        assert a.scope in valid, f"{a.id} has invalid scope {a.scope}"


def test_actions_for_scope_filters():
    grid = actions_for_scope("grid")
    assert grid
    assert all(a.scope == "grid" for a in grid)
    # Lightbox actions are not in the grid scope
    assert all(a.scope != "lightbox" for a in grid)


def test_action_lookup():
    a = action("lightbox.next")
    assert a is not None
    assert a.scope == "lightbox"
    assert action("not.a.real.action") is None


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------


def test_default_bindings_non_empty():
    d = default_bindings()
    assert len(d) > 0


def test_default_bindings_cover_every_action_with_default():
    """Every action whose default_chords is non-empty should produce
    at least one binding."""
    d = default_bindings()
    bound_ids = {b.action_id for b in d}
    for a in ACTIONS:
        if a.default_chords:
            assert a.id in bound_ids, f"{a.id} has defaults but isn't bound"


def test_default_bindings_no_conflicts():
    """The shipped defaults should be conflict-free per-scope."""
    conflicts = find_conflicts(default_bindings())
    assert conflicts == [], f"default bindings have conflicts: {conflicts}"


# ---------------------------------------------------------------------------
# conflict detection
# ---------------------------------------------------------------------------


def test_conflict_same_scope_same_chord():
    bs = [
        Binding(action_id="lightbox.next", scope="lightbox", chord="x"),
        Binding(action_id="lightbox.prev", scope="lightbox", chord="x"),
    ]
    conflicts = find_conflicts(bs)
    assert len(conflicts) == 1
    assert conflicts[0].scope == "lightbox"
    assert conflicts[0].chord == "x"
    assert set(conflicts[0].action_ids) == {"lightbox.next", "lightbox.prev"}


def test_conflict_cross_scope_allowed():
    """Same chord in different scopes is FINE — that's the whole
    point of scopes."""
    bs = [
        Binding(action_id="lightbox.next", scope="lightbox", chord="j"),
        Binding(action_id="grid.focus_next", scope="grid", chord="j"),
    ]
    assert find_conflicts(bs) == []


def test_conflict_same_action_multiple_slots_allowed():
    """Binding the same action to TWO chords is the "slot 1 + slot 2"
    feature, not a conflict."""
    bs = [
        Binding(action_id="lightbox.next", scope="lightbox", chord="ArrowRight"),
        Binding(action_id="lightbox.next", scope="lightbox", chord="j"),
    ]
    assert find_conflicts(bs) == []


# ---------------------------------------------------------------------------
# persistence — round-trip via tmp HOME
# ---------------------------------------------------------------------------


def test_save_then_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    bs = [
        Binding(action_id="lightbox.next", scope="lightbox", chord="k"),
        Binding(action_id="lightbox.prev", scope="lightbox", chord="j"),
    ]
    save_bindings(bs)
    loaded = load_bindings()
    assert len(loaded) == 2
    assert {b.chord for b in loaded} == {"k", "j"}


def test_load_falls_back_to_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    # Nothing saved → defaults
    loaded = load_bindings()
    assert loaded == default_bindings()


def test_load_falls_back_on_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = shortcuts_path()
    p.write_text("not json {", encoding="utf-8")
    loaded = load_bindings()
    assert loaded == default_bindings()


def test_load_falls_back_on_unknown_version(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = shortcuts_path()
    p.write_text(json.dumps({"version": 999, "bindings": []}),
                 encoding="utf-8")
    loaded = load_bindings()
    assert loaded == default_bindings()


def test_load_silently_drops_invalid_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = shortcuts_path()
    p.write_text(json.dumps({
        "version": 1,
        "bindings": [
            {"action_id": "lightbox.next", "scope": "lightbox",
             "chord": "k"},          # valid
            {"action_id": "not.a.real", "scope": "lightbox",
             "chord": "x"},          # unknown action id — drop
            "not even a dict",       # garbage — drop
            {"action_id": "lightbox.prev"},  # missing scope/chord — drop
        ],
    }), encoding="utf-8")
    loaded = load_bindings()
    assert len(loaded) == 1
    assert loaded[0].action_id == "lightbox.next"


def test_load_empty_file_falls_back_to_defaults(tmp_path, monkeypatch):
    """If the file exists but yields zero valid bindings, defaults
    win — never leave the user stuck with no keys."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = shortcuts_path()
    p.write_text(json.dumps({"version": 1, "bindings": []}),
                 encoding="utf-8")
    loaded = load_bindings()
    assert loaded == default_bindings()


def test_reset_to_defaults_writes_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    bs = reset_to_defaults()
    assert shortcuts_path().exists()
    loaded = load_bindings()
    assert {b.action_id for b in bs} == {b.action_id for b in loaded}
