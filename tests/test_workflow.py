"""Tests for v0.13.9 workflow helpers."""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

import pytest

from pixcull.workflow import (
    Bookmark,
    DailyRecap,
    daily_recap,
    is_bookmarked,
    list_bookmarks,
    session_conflicts,
    toggle_bookmark,
)


# ---------------------------------------------------------------------------
# Bookmark round-trip
# ---------------------------------------------------------------------------


def test_toggle_bookmark_add_then_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert not is_bookmarked("r1", "a.jpg")
    added = toggle_bookmark("r1", "a.jpg", note="check focus")
    assert added is True
    assert is_bookmarked("r1", "a.jpg")
    removed = toggle_bookmark("r1", "a.jpg")
    assert removed is False
    assert not is_bookmarked("r1", "a.jpg")


def test_list_bookmarks_filter_by_run(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    toggle_bookmark("r1", "a.jpg")
    toggle_bookmark("r1", "b.jpg")
    toggle_bookmark("r2", "c.jpg")
    assert len(list_bookmarks()) == 3
    assert len(list_bookmarks("r1")) == 2
    assert len(list_bookmarks("r2")) == 1
    assert list_bookmarks("absent") == []


def test_bookmark_note_and_color_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    toggle_bookmark("r1", "a.jpg", note="check this with client",
                    color="yellow")
    bookmarks = list_bookmarks("r1")
    assert bookmarks[0].note == "check this with client"
    assert bookmarks[0].color == "yellow"


def test_toggle_bookmark_missing_args_raises():
    with pytest.raises(ValueError):
        toggle_bookmark("", "a.jpg")
    with pytest.raises(ValueError):
        toggle_bookmark("r1", "")


def test_bookmark_corrupt_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    # Pre-write garbage
    p = tmp_path / ".pixcull" / "bookmarks.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json", encoding="utf-8")
    assert list_bookmarks() == []


# ---------------------------------------------------------------------------
# Daily recap
# ---------------------------------------------------------------------------


def _write_run_with_today_annotations(runs_root: Path, run_id: str,
                                       rows: list[dict]) -> None:
    run = runs_root / run_id
    run.mkdir(parents=True, exist_ok=True)
    ann = run / "annotations.jsonl"
    now = time.time()
    with ann.open("w", encoding="utf-8") as fh:
        for row in rows:
            row.setdefault("timestamp", now)
            fh.write(json.dumps(row) + "\n")


def test_daily_recap_empty_root(tmp_path):
    r = daily_recap(tmp_path / "absent")
    assert r.n_annotations == 0
    assert r.n_keep == 0


def test_daily_recap_aggregates_today(tmp_path):
    runs = tmp_path / "runs"
    _write_run_with_today_annotations(runs, "r1", [
        {"filename": "a.jpg", "decision": "keep"},
        {"filename": "b.jpg", "decision": "cull",
         "cull_reason": "out_of_focus"},
        {"filename": "c.jpg", "decision": "cull",
         "cull_reason": "out_of_focus"},
        {"filename": "d.jpg", "decision": "maybe"},
    ])
    r = daily_recap(runs)
    assert r.n_annotations == 4
    assert r.n_keep == 1
    assert r.n_maybe == 1
    assert r.n_cull == 2
    assert r.top_cull_reason == "out_of_focus"
    assert r.top_cull_reason_count == 2
    assert r.longest_run_id == "r1"
    assert r.longest_run_count == 4


def test_daily_recap_filters_old_days(tmp_path):
    runs = tmp_path / "runs"
    old_ts = time.time() - 86400 * 7   # 7 days ago
    _write_run_with_today_annotations(runs, "r1", [
        {"filename": "old.jpg", "decision": "keep", "timestamp": old_ts},
        {"filename": "today.jpg", "decision": "keep"},
    ])
    r = daily_recap(runs)
    assert r.n_annotations == 1   # only today's


def test_daily_recap_picks_busiest_run(tmp_path):
    runs = tmp_path / "runs"
    _write_run_with_today_annotations(runs, "r1", [
        {"filename": "a.jpg", "decision": "keep"},
    ])
    _write_run_with_today_annotations(runs, "r2", [
        {"filename": "b.jpg", "decision": "keep"},
        {"filename": "c.jpg", "decision": "cull"},
        {"filename": "d.jpg", "decision": "maybe"},
    ])
    r = daily_recap(runs)
    assert r.longest_run_id == "r2"
    assert r.longest_run_count == 3
    assert r.n_runs_touched == 2


def test_daily_recap_time_saved_estimate(tmp_path):
    runs = tmp_path / "runs"
    _write_run_with_today_annotations(runs, "r1", [
        # 60 culls × 15s + 0 keeps = 900s = 15 min
        {"filename": f"c{i}.jpg", "decision": "cull"} for i in range(60)
    ])
    r = daily_recap(runs)
    assert r.time_saved_min == 15


def test_daily_recap_explicit_date(tmp_path):
    runs = tmp_path / "runs"
    _write_run_with_today_annotations(runs, "r1", [
        {"filename": "a.jpg", "decision": "keep"},
    ])
    # Recap a different day → empty
    r = daily_recap(runs, date_iso="2020-01-01")
    assert r.n_annotations == 0
    assert r.date_iso == "2020-01-01"


# ---------------------------------------------------------------------------
# session_conflicts
# ---------------------------------------------------------------------------


def test_conflicts_finds_decision_change(tmp_path):
    runs = tmp_path / "runs"
    older = time.time() - 86400 * 7
    newer = time.time()
    _write_run_with_today_annotations(runs, "old_run", [
        {"filename": "a.jpg", "decision": "cull", "timestamp": older},
    ])
    _write_run_with_today_annotations(runs, "current", [
        {"filename": "a.jpg", "decision": "keep", "timestamp": newer},
    ])
    c = session_conflicts(runs, "current")
    assert "a.jpg" in c
    assert c["a.jpg"]["previous_decision"] == "cull"
    assert c["a.jpg"]["current_decision"] == "keep"
    assert c["a.jpg"]["previous_run_id"] == "old_run"


def test_conflicts_no_change_no_warning(tmp_path):
    runs = tmp_path / "runs"
    older = time.time() - 86400 * 7
    newer = time.time()
    _write_run_with_today_annotations(runs, "old_run", [
        {"filename": "a.jpg", "decision": "keep", "timestamp": older},
    ])
    _write_run_with_today_annotations(runs, "current", [
        {"filename": "a.jpg", "decision": "keep", "timestamp": newer},
    ])
    c = session_conflicts(runs, "current")
    assert "a.jpg" not in c   # same decision = no conflict


def test_conflicts_no_previous_run(tmp_path):
    runs = tmp_path / "runs"
    _write_run_with_today_annotations(runs, "current", [
        {"filename": "a.jpg", "decision": "keep"},
    ])
    c = session_conflicts(runs, "current")
    assert c == {}


def test_conflicts_filename_only_in_other_run(tmp_path):
    """File annotated in another run but NOT in current — no conflict
    because current hasn't taken a position."""
    runs = tmp_path / "runs"
    _write_run_with_today_annotations(runs, "old_run", [
        {"filename": "a.jpg", "decision": "cull"},
    ])
    _write_run_with_today_annotations(runs, "current", [
        {"filename": "b.jpg", "decision": "keep"},
    ])
    c = session_conflicts(runs, "current")
    assert "a.jpg" not in c
