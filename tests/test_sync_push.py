"""Tests for pixcull.sync.push — v0.10-P0-1 two-way sync push.

Covers
------
* normalize_edit returns None for malformed input
* normalize_edit truncates oversized strings
* normalize_edit propagates client_ts_ms → timestamp
* decision ↔ overall_label parity at normalisation time
* append_edits_jsonl writes one line per edit, in order
* append_edits_jsonl tolerates partial / unknown fields
* push_edits returns the accepted/rejected summary
* push_edits tags event_id when one is provided
* push_edits + compute_changes_since round-trip — what we push
  is what other peers see on the next poll
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.sync.event import compute_changes_since
from pixcull.sync.push import (
    ALLOWED_FIELDS,
    append_edits_jsonl,
    normalize_edit,
    push_edits,
)


def test_normalize_drops_non_dict():
    assert normalize_edit(None) is None
    assert normalize_edit("string") is None
    assert normalize_edit(42) is None
    assert normalize_edit([{"filename": "a"}]) is None


def test_normalize_requires_filename():
    assert normalize_edit({}) is None
    assert normalize_edit({"decision": "keep"}) is None
    assert normalize_edit({"filename": ""}) is None
    assert normalize_edit({"filename": 12}) is None


def test_normalize_passes_through_allowed_fields():
    edit = {
        "filename":    "IMG_001.jpg",
        "decision":    "keep",
        "rubric_stars": {"technical": 4.5},
        "cull_reason":  "",
        "client_id":    "web-abc123",
        "edited_by":    "二摄-小陈",
    }
    out = normalize_edit(edit, now_ms=1_000_000_000_000)
    assert out["filename"] == "IMG_001.jpg"
    assert out["decision"] == "keep"
    assert out["rubric_stars"] == {"technical": 4.5}
    assert out["edited_by"] == "二摄-小陈"
    # Parity field auto-populated
    assert out["overall_label"] == "keep"


def test_normalize_truncates_oversized_strings():
    huge = "x" * 10000
    out = normalize_edit({
        "filename": huge,
        "advice":   huge,
        "cull_reason": huge,
    })
    assert len(out["filename"]) <= 512
    assert len(out["advice"])   <= 4096
    assert len(out["cull_reason"]) <= 512


def test_normalize_client_ts_takes_priority():
    out = normalize_edit({
        "filename":     "a.jpg",
        "client_ts_ms": 1_700_000_000_123,
    }, now_ms=9_999_999_999_999)
    assert out["client_ts_ms"] == 1_700_000_000_123
    assert out["timestamp"] == 1_700_000_000.123


def test_normalize_fallback_to_server_now_when_no_client_ts():
    out = normalize_edit({"filename": "a.jpg"}, now_ms=1_500_000_000_000)
    assert out["client_ts_ms"] == 1_500_000_000_000
    assert out["timestamp"] == 1_500_000_000.0


def test_normalize_decision_overall_label_parity():
    # decision only → overall_label auto-set
    a = normalize_edit({"filename": "a.jpg", "decision": "cull"})
    assert a["overall_label"] == "cull"
    # overall_label only → decision auto-set
    b = normalize_edit({"filename": "b.jpg", "overall_label": "maybe"})
    assert b["decision"] == "maybe"
    # Both provided → both kept as-is
    c = normalize_edit({"filename": "c.jpg",
                         "decision": "keep", "overall_label": "keep"})
    assert c["decision"] == c["overall_label"] == "keep"


def test_normalize_strips_unknown_fields():
    out = normalize_edit({
        "filename": "a.jpg",
        "evil_key": "should not survive",
        "decision": "keep",
    })
    assert "evil_key" not in out


def test_append_edits_jsonl_writes_one_line_per_edit(tmp_path: Path):
    p = tmp_path / "annotations.jsonl"
    accepted = append_edits_jsonl(p, [
        {"filename": "a.jpg", "decision": "keep"},
        {"filename": "b.jpg", "decision": "cull"},
    ], now_ms=1_000_000_000_000)
    assert len(accepted) == 2
    assert p.exists()
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    rows = [json.loads(l) for l in lines]
    assert [r["filename"] for r in rows] == ["a.jpg", "b.jpg"]


def test_append_edits_jsonl_silently_drops_malformed(tmp_path: Path):
    p = tmp_path / "annotations.jsonl"
    accepted = append_edits_jsonl(p, [
        {"filename": "a.jpg"},
        None,                        # not a dict
        {"no_filename": True},       # missing required field
        {"filename": "b.jpg"},
    ])
    assert len(accepted) == 2
    assert {a["filename"] for a in accepted} == {"a.jpg", "b.jpg"}


def test_append_edits_jsonl_appends_to_existing_file(tmp_path: Path):
    p = tmp_path / "annotations.jsonl"
    p.write_text('{"filename":"old.jpg","timestamp":100}\n', encoding="utf-8")
    append_edits_jsonl(p, [{"filename": "new.jpg"}])
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    rows = [json.loads(l) for l in lines]
    assert rows[0]["filename"] == "old.jpg"
    assert rows[1]["filename"] == "new.jpg"


def test_push_edits_returns_accepted_rejected_summary(tmp_path: Path):
    res = push_edits(tmp_path, [
        {"filename": "a.jpg", "decision": "keep"},
        None,
        {"filename": "", "decision": "cull"},
        {"filename": "b.jpg"},
    ], event_id="evt_test", now_ms=1_000_000_000_000)
    assert res["ok"] is True
    assert res["accepted"] == 2
    assert res["rejected"] == 2
    assert res["server_ts"] == 1_000_000_000_000
    assert len(res["rows"]) == 2
    # event_id tagged on every accepted row
    assert all(r.get("event_id") == "evt_test" for r in res["rows"])


def test_push_edits_rejects_non_list():
    with pytest.raises(ValueError):
        push_edits(Path("/tmp"), "not-a-list")


def test_push_then_compute_changes_roundtrip(tmp_path: Path):
    """End-to-end: push edits → other peer polls /changes → sees them.

    This is the canary that two-way sync works on top of the
    existing pull machinery.  No special fan-out logic — we lean
    on the fact that compute_changes_since reads the SAME JSONL
    file we just appended to.
    """
    res = push_edits(tmp_path, [
        {"filename": "a.jpg", "decision": "keep",
         "client_ts_ms": 1_500_000_000_000},
        {"filename": "b.jpg", "decision": "cull",
         "client_ts_ms": 1_500_000_001_000},
    ], event_id="evt_test")
    assert res["accepted"] == 2

    jsonl = tmp_path / "annotations.jsonl"
    changes, server_ts = compute_changes_since(jsonl, since_ms=0)
    by_fn = {c["filename"]: c for c in changes}
    assert by_fn["a.jpg"]["decision"] == "keep"
    assert by_fn["b.jpg"]["decision"] == "cull"
    # Timestamps survived the round-trip
    assert by_fn["a.jpg"]["updated_at_ms"] == 1_500_000_000_000
    assert by_fn["b.jpg"]["updated_at_ms"] == 1_500_000_001_000


def test_allowed_fields_constant_is_stable():
    """The wire contract — keep this stable; bumping it is a v2 break."""
    must_have = {"filename", "decision", "rubric_stars",
                 "client_id", "client_ts_ms", "timestamp",
                 "event_id"}
    assert must_have.issubset(set(ALLOWED_FIELDS))
