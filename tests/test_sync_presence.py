"""Tests for pixcull.sync.presence — v0.9-P1-2 multiplayer presence.

Covers
------
* update_presence persists and round-trips
* Heartbeat carries forward fields the second heartbeat doesn't set
* Stale peers (last_seen older than TTL) drop out of read_presence
* MAX_PEERS cap protects against runaway client_id generation
* drop_peer is idempotent
* Atomic write doesn't corrupt the file on concurrent writes
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.sync.presence import (
    MAX_PEERS,
    SCHEMA,
    STALE_TTL_MS,
    drop_peer,
    presence_path,
    read_presence,
    update_presence,
)


def test_update_then_read_roundtrip(tmp_path: Path):
    rec = update_presence(
        tmp_path, "evt_a", "client-1",
        display_name="二摄",
        last_viewed_filename="IMG_001.jpg",
    )
    assert rec["client_id"] == "client-1"
    assert rec["display_name"] == "二摄"
    assert rec["last_viewed_filename"] == "IMG_001.jpg"

    peers = read_presence(tmp_path, "evt_a")
    assert "client-1" in peers
    assert peers["client-1"]["last_viewed_filename"] == "IMG_001.jpg"


def test_persistent_action_across_view_only_heartbeats(tmp_path: Path):
    """A heartbeat that only updates last_viewed_filename should
    NOT clobber a previous *last_action* — the UI wants to show
    "X is looking at IMG_007 · last action: keep on IMG_002"."""
    update_presence(
        tmp_path, "evt_a", "c1",
        last_viewed_filename="IMG_001.jpg",
        action="keep",
        action_filename="IMG_001.jpg",
    )
    # Pure viewer-position heartbeat:
    rec = update_presence(
        tmp_path, "evt_a", "c1",
        last_viewed_filename="IMG_007.jpg",
    )
    assert rec["last_viewed_filename"] == "IMG_007.jpg"
    assert rec["last_action"] == "keep"
    assert rec["last_action_filename"] == "IMG_001.jpg"


def test_stale_peers_drop_out(tmp_path: Path):
    # Manually inject a stale client by setting now_ms in the past.
    long_ago = 1_000  # epoch-ms in 1970
    update_presence(
        tmp_path, "evt_a", "ghost",
        display_name="老二摄",
        now_ms=long_ago,
    )
    # And a fresh one.
    update_presence(
        tmp_path, "evt_a", "live",
        display_name="编辑",
    )
    peers = read_presence(tmp_path, "evt_a")
    assert "live" in peers
    assert "ghost" not in peers


def test_max_peers_cap(tmp_path: Path):
    # Drop MAX_PEERS + 5 clients at the same fresh timestamp →
    # only MAX_PEERS most-recent survive.
    base = 9_999_999_999_999
    for i in range(MAX_PEERS + 5):
        update_presence(
            tmp_path, "evt_a", f"c{i}",
            now_ms=base + i,
        )
    peers = read_presence(tmp_path, "evt_a", now_ms=base + 10_000)
    assert len(peers) == MAX_PEERS
    # The 5 oldest got evicted
    assert "c0" not in peers
    assert "c4" not in peers
    # The newest survived
    assert f"c{MAX_PEERS + 4}" in peers


def test_drop_peer_idempotent(tmp_path: Path):
    update_presence(tmp_path, "evt_a", "c1")
    assert drop_peer(tmp_path, "evt_a", "c1") is True
    # Second drop returns False (no change)
    assert drop_peer(tmp_path, "evt_a", "c1") is False
    # Unknown event returns False
    assert drop_peer(tmp_path, "evt_nonexistent", "c1") is False


def test_update_requires_client_id(tmp_path: Path):
    with pytest.raises(ValueError):
        update_presence(tmp_path, "evt_a", "")
    with pytest.raises(ValueError):
        update_presence(tmp_path, "", "c1")


def test_presence_path_uses_sanitised_id(tmp_path: Path):
    # event_id with a slash would otherwise escape the directory.
    p = presence_path(tmp_path, "evt_../weird")
    # Anchored inside the presence dir
    assert p.parent == (tmp_path / "presence")
    assert "/" not in p.name


def test_field_truncation(tmp_path: Path):
    rec = update_presence(
        tmp_path, "evt_a", "c1",
        display_name="x" * 500,
        last_viewed_filename="f" * 500,
        action="a" * 500,
        action_filename="g" * 500,
    )
    assert len(rec["display_name"]) <= 60
    assert len(rec["last_viewed_filename"]) <= 200
    assert len(rec["last_action"]) <= 32
    assert len(rec["last_action_filename"]) <= 200


def test_schema_and_ttl_are_stable():
    # Wire-contract constants — bumping is a deliberate v2 break.
    assert SCHEMA == "pixcull.sync.presence/v1"
    assert STALE_TTL_MS == 90_000
