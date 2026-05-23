"""Tests for pixcull.shortlink — short-link issuer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pixcull.shortlink import issue, resolve


def test_issue_returns_6_char_code(tmp_path: Path):
    rec = issue(tmp_path, "/share/r1/abc...")
    assert len(rec["short_code"]) == 6
    assert rec["long_url"] == "/share/r1/abc..."
    assert rec["expires_at"]


def test_resolve_returns_record(tmp_path: Path):
    rec = issue(tmp_path, "/share/r1/abc...")
    out = resolve(tmp_path, rec["short_code"])
    assert out is not None
    assert out["long_url"] == "/share/r1/abc..."


def test_resolve_missing_returns_none(tmp_path: Path):
    assert resolve(tmp_path, "Aabcde") is None


def test_resolve_rejects_bad_input(tmp_path: Path):
    # Wrong length
    assert resolve(tmp_path, "abc") is None
    assert resolve(tmp_path, "abcdefg") is None
    # Outside alphabet (path traversal attempt)
    assert resolve(tmp_path, "../etc") is None
    assert resolve(tmp_path, "abc/de") is None
    assert resolve(tmp_path, "") is None
    assert resolve(tmp_path, None) is None  # type: ignore[arg-type]


def test_idempotent_for_same_long_url(tmp_path: Path):
    """Re-issuing the same URL should return the SAME code so the host
    doesn't accidentally mint dozens of codes for one share link."""
    a = issue(tmp_path, "/share/r1/abc")
    b = issue(tmp_path, "/share/r1/abc")
    assert a["short_code"] == b["short_code"]


def test_different_urls_get_different_codes(tmp_path: Path):
    a = issue(tmp_path, "/share/r1/abc")
    b = issue(tmp_path, "/share/r1/xyz")
    assert a["short_code"] != b["short_code"]


def test_expired_resolve_returns_expired_marker(tmp_path: Path):
    rec = issue(tmp_path, "/share/r1/abc", ttl_hours=1)
    # Manually backdate the stored record
    store = tmp_path / "_shortlinks.json"
    data = json.loads(store.read_text(encoding="utf-8"))
    data["links"][rec["short_code"]]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    store.write_text(json.dumps(data), encoding="utf-8")
    out = resolve(tmp_path, rec["short_code"])
    assert out is not None
    assert out.get("expired") is True


def test_store_file_is_atomic_write(tmp_path: Path):
    """After an issue, the tmp file shouldn't linger on disk."""
    issue(tmp_path, "/share/r1/abc")
    assert not (tmp_path / "_shortlinks.json.tmp").exists()
    assert (tmp_path / "_shortlinks.json").exists()


def test_issue_rejects_empty_long_url(tmp_path: Path):
    with pytest.raises(ValueError):
        issue(tmp_path, "")
    with pytest.raises(ValueError):
        issue(tmp_path, "   ")


def test_ttl_clamps_to_min_1h(tmp_path: Path):
    rec = issue(tmp_path, "/share/r1/abc", ttl_hours=0)
    exp = datetime.fromisoformat(rec["expires_at"])
    # Should be at least roughly 1h ahead
    delta = exp - datetime.now(timezone.utc)
    assert 50 * 60 < delta.total_seconds() < 70 * 60
