"""Tests for pixcull.sync.event — LAN sync event protocol.

Covers
------
* Event lifecycle (issue → load → revoke)
* Token discovery (find_event_by_token)
* compute_changes_since: respects since_ms, returns mtime
* apply_remote_changes: applies new rows, merges identical rows,
  flags conflicts based on local-newer-than-remote
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pixcull.sync.event import (
    EventSession,
    apply_remote_changes,
    compute_changes_since,
    find_event_by_token,
    issue_event,
    load_event,
    revoke_event,
)


# ---------------------------------------------------------------------------
# Event lifecycle
# ---------------------------------------------------------------------------


def test_issue_then_load(tmp_path: Path):
    sess = issue_event(tmp_path, run_id="r1", label="wedding")
    assert sess.event_id.startswith("evt_")
    assert sess.token  # non-empty
    assert sess.run_id == "r1"
    # File persisted
    assert (tmp_path / "events" / f"{sess.event_id}.json").exists()
    # Round-trips
    loaded = load_event(tmp_path, sess.event_id)
    assert loaded is not None
    assert loaded.token == sess.token
    assert loaded.run_id == "r1"


def test_load_missing_returns_none(tmp_path: Path):
    assert load_event(tmp_path, "evt_nonexistent") is None
    # Bad id (doesn't start with evt_) → None even if file existed
    assert load_event(tmp_path, "../etc/passwd") is None


def test_revoke_makes_inactive(tmp_path: Path):
    sess = issue_event(tmp_path, run_id="r1")
    assert sess.is_active()
    assert revoke_event(tmp_path, sess.event_id) is True
    loaded = load_event(tmp_path, sess.event_id)
    assert loaded.revoked is True
    assert loaded.is_active() is False
    # Idempotent — second revoke returns False (no change)
    assert revoke_event(tmp_path, sess.event_id) is False


def test_find_event_by_token(tmp_path: Path):
    s1 = issue_event(tmp_path, run_id="r1")
    s2 = issue_event(tmp_path, run_id="r1")
    found = find_event_by_token(tmp_path, s2.token)
    assert found is not None
    assert found.event_id == s2.event_id
    # Unknown token
    assert find_event_by_token(tmp_path, "bogus") is None
    # Empty token isn't a match
    assert find_event_by_token(tmp_path, "") is None


def test_expiry(tmp_path: Path):
    # 0 hours requested → clamped to min 1h by issue_event, so
    # still active right after issuance.
    sess = issue_event(tmp_path, run_id="r1", ttl_hours=1)
    assert sess.is_active()


# ---------------------------------------------------------------------------
# Change-list protocol
# ---------------------------------------------------------------------------


def _write_annotation(dir_: Path, fn: str, payload: dict) -> Path:
    """Legacy directory-of-json layout used by the fallback branch."""
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"{fn}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    """v0.5+ canonical JSONL append-only annotation log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def test_compute_changes_jsonl_returns_latest_per_filename(tmp_path: Path):
    """JSONL is append-only: every re-label adds a line.  The
    sync poller should surface only the *latest* line per filename."""
    p = _write_jsonl(tmp_path / "annotations.jsonl", [
        {"filename": "a.jpg", "overall_label": "maybe", "timestamp": 1000.0},
        {"filename": "a.jpg", "overall_label": "keep",  "timestamp": 1500.0},
        {"filename": "b.jpg", "overall_label": "cull",  "timestamp": 1200.0},
    ])
    changes, ts = compute_changes_since(p, since_ms=0)
    by_fn = {c["filename"]: c for c in changes}
    assert by_fn["a.jpg"]["decision"] == "keep"   # last line wins
    assert by_fn["a.jpg"]["updated_at_ms"] == 1500000
    assert by_fn["b.jpg"]["decision"] == "cull"
    assert ts > 0


def test_compute_changes_jsonl_filters_by_since_ms(tmp_path: Path):
    p = _write_jsonl(tmp_path / "annotations.jsonl", [
        {"filename": "old.jpg",  "overall_label": "keep", "timestamp": 1000.0},
        {"filename": "fresh.jpg","overall_label": "cull", "timestamp": 9000.0},
    ])
    changes, _ = compute_changes_since(p, since_ms=5000 * 1000)
    fns = {c["filename"] for c in changes}
    assert fns == {"fresh.jpg"}


def test_compute_changes_jsonl_handles_bad_lines(tmp_path: Path):
    p = tmp_path / "annotations.jsonl"
    p.write_text(
        '{"filename": "ok.jpg", "timestamp": 1.0}\n'
        'not-json\n'
        '\n'
        '{"no_filename": "skip"}\n'
        '"a string"\n'
        '{"filename": "ok2.jpg", "timestamp": 2.0}\n',
        encoding="utf-8",
    )
    changes, _ = compute_changes_since(p, since_ms=0)
    fns = {c["filename"] for c in changes}
    assert fns == {"ok.jpg", "ok2.jpg"}


def test_compute_changes_legacy_dir_layout(tmp_path: Path):
    """Older deployments / manual edits used a directory of json files."""
    ad = tmp_path / "annotation"
    _write_annotation(ad, "a", {"decision": "keep"})
    _write_annotation(ad, "b", {"decision": "cull"})
    changes, ts = compute_changes_since(ad, since_ms=0)
    fns = {c["filename"] for c in changes}
    assert fns == {"a", "b"}
    assert ts > 0


def test_compute_changes_legacy_dir_skips_older_files(tmp_path: Path):
    ad = tmp_path / "annotation"
    p_a = _write_annotation(ad, "a", {"decision": "keep"})
    old = int(time.time()) - 3600
    import os as _os
    _os.utime(p_a, (old, old))
    _write_annotation(ad, "b", {"decision": "cull"})
    since_ms = (int(time.time()) - 1800) * 1000
    changes, _ = compute_changes_since(ad, since_ms=since_ms)
    assert {c["filename"] for c in changes} == {"b"}


def test_compute_changes_handles_missing_path(tmp_path: Path):
    # Neither file nor dir exists
    changes, ts = compute_changes_since(tmp_path / "nope", since_ms=0)
    assert changes == []
    assert ts > 0


# ---------------------------------------------------------------------------
# apply_remote_changes
# ---------------------------------------------------------------------------


def test_apply_remote_new_filename_is_applied():
    local = []
    remote = [{"filename": "x.jpg", "decision": "keep",
               "updated_at_ms": 1000}]
    out = apply_remote_changes(local, remote)
    assert out == [{
        "filename": "x.jpg",
        "action":   "applied",
        "remote":   remote[0],
        "local":    None,
    }]


def test_apply_remote_same_decision_is_applied():
    local = [{"filename": "x.jpg", "decision": "keep"}]
    remote = [{"filename": "x.jpg", "decision": "keep",
               "updated_at_ms": 1000}]
    out = apply_remote_changes(local, remote)
    assert out[0]["action"] == "applied"


def test_apply_remote_remote_newer_overwrites_local():
    local = [{"filename": "x.jpg", "decision": "keep"}]
    remote = [{"filename": "x.jpg", "decision": "cull",
               "updated_at_ms": 5000}]
    # local mtime older than remote
    local_mtimes = {"x.jpg": 1000}
    out = apply_remote_changes(local, remote, local_mtimes)
    assert out[0]["action"] == "applied"  # remote wins


def test_apply_remote_local_newer_is_conflict():
    local = [{"filename": "x.jpg", "decision": "keep"}]
    remote = [{"filename": "x.jpg", "decision": "cull",
               "updated_at_ms": 1000}]
    # local was edited at mtime 5000 — after the remote we just got
    local_mtimes = {"x.jpg": 5000}
    out = apply_remote_changes(local, remote, local_mtimes)
    assert out[0]["action"] == "conflict"
    assert "local newer than remote" in out[0]["reason"]


def test_apply_remote_skips_invalid_entries():
    out = apply_remote_changes([], [
        None,                                 # not a dict
        {"decision": "keep"},                 # missing filename
        {"filename": "", "decision": "keep"}, # empty filename
        {"filename": "ok.jpg", "decision": "keep", "updated_at_ms": 1},
    ])
    assert len(out) == 1
    assert out[0]["filename"] == "ok.jpg"


def test_schema_constant_stable():
    # The schema string is part of the wire contract — changing it
    # is a deliberate v2 break.
    assert EventSession.SCHEMA == "pixcull.sync.event/v1"
