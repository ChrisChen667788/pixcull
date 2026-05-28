"""Tests for pixcull/sync/webrtc.py — v0.11-P0-3 WebRTC signaling relay.

The relay never sees image data or annotations — it only marshals SDP
offers/answers and ICE candidates between peers.  We test:
  * happy-path offer/answer/candidate round-trip
  * self-addressed messages rejected
  * unknown kinds rejected
  * inbox isolation (one peer's messages don't leak to another)
  * TTL expiry
  * concurrency safety (smoke test)
"""

from __future__ import annotations

import json
import threading

import pytest

from pixcull.sync.webrtc import (
    SignalingRelay,
    handle_get_inbox,
    handle_post,
)


# ---------------------------------------------------------------------------
# Basic happy-path
# ---------------------------------------------------------------------------


def test_offer_lands_in_recipient_inbox():
    r = SignalingRelay()
    resp = r.post(kind="offer", sender="alice", recipient="bob",
                  payload={"sdp": "v=0..."})
    assert resp["ok"]
    msgs = r.inbox("bob")
    assert len(msgs) == 1
    assert msgs[0]["kind"] == "offer"
    assert msgs[0]["from"] == "alice"
    assert msgs[0]["payload"] == {"sdp": "v=0..."}


def test_answer_back():
    r = SignalingRelay()
    r.post(kind="offer", sender="alice", recipient="bob",
           payload={"sdp": "o1"})
    r.post(kind="answer", sender="bob", recipient="alice",
           payload={"sdp": "a1"})
    alice_inbox = r.inbox("alice")
    bob_inbox = r.inbox("bob")
    assert [m["kind"] for m in alice_inbox] == ["answer"]
    assert [m["kind"] for m in bob_inbox] == ["offer"]


def test_candidate_exchange():
    r = SignalingRelay()
    r.post(kind="candidate", sender="a", recipient="b",
           payload={"candidate": "candidate:1 1 UDP ..."})
    r.post(kind="candidate", sender="a", recipient="b",
           payload={"candidate": "candidate:2 1 UDP ..."})
    inbox = r.inbox("b")
    assert len(inbox) == 2
    assert all(m["kind"] == "candidate" for m in inbox)


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


def test_rejects_self_addressed():
    r = SignalingRelay()
    resp = r.post(kind="offer", sender="a", recipient="a", payload={})
    assert not resp["ok"]
    assert "self" in resp["error"].lower()


def test_rejects_unknown_kind():
    r = SignalingRelay()
    resp = r.post(kind="banana", sender="a", recipient="b", payload={})
    assert not resp["ok"]
    assert "unknown kind" in resp["error"].lower()


def test_rejects_missing_peers():
    r = SignalingRelay()
    assert not r.post(kind="offer", sender="", recipient="b",
                      payload={})["ok"]
    assert not r.post(kind="offer", sender="a", recipient="",
                      payload={})["ok"]


def test_rejects_non_dict_payload():
    r = SignalingRelay()
    resp = r.post(kind="offer", sender="a", recipient="b",
                  payload="not a dict")
    assert not resp["ok"]


# ---------------------------------------------------------------------------
# Inbox isolation + since
# ---------------------------------------------------------------------------


def test_inbox_isolation_per_peer():
    r = SignalingRelay()
    r.post(kind="offer", sender="alice", recipient="bob", payload={})
    r.post(kind="offer", sender="alice", recipient="carol", payload={})
    assert len(r.inbox("bob")) == 1
    assert len(r.inbox("carol")) == 1
    # Unknown peer — empty
    assert r.inbox("dave") == []


def test_since_ms_filters_old_messages():
    r = SignalingRelay()
    r._clock = lambda: 100
    r.post(kind="offer", sender="a", recipient="b", payload={})  # ts=100
    r._clock = lambda: 200
    r.post(kind="candidate", sender="a", recipient="b", payload={})  # ts=200
    # Read everything
    all_msgs = r.inbox("b")
    assert len(all_msgs) == 2
    # Read since after the first
    new_msgs = r.inbox("b", since_ms=100)
    assert len(new_msgs) == 1
    assert new_msgs[0]["kind"] == "candidate"
    # Read with cutoff in the future
    none_msgs = r.inbox("b", since_ms=999)
    assert none_msgs == []


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


def test_ttl_expires_messages():
    r = SignalingRelay(ttl_ms=1000)
    r._clock = lambda: 100
    r.post(kind="offer", sender="a", recipient="b", payload={})
    assert len(r.inbox("b")) == 1
    # Jump past TTL
    r._clock = lambda: 1500
    assert r.inbox("b") == []
    # Inbox cleaned up
    assert "b" not in r.peer_ids()


def test_partial_ttl_keeps_recent():
    r = SignalingRelay(ttl_ms=1000)
    r._clock = lambda: 100
    r.post(kind="offer", sender="a", recipient="b", payload={})  # ts=100
    r._clock = lambda: 800
    r.post(kind="candidate", sender="a", recipient="b", payload={})  # ts=800
    # Jump to t=1200 — the t=100 msg expired but t=800 still valid
    r._clock = lambda: 1200
    inbox = r.inbox("b")
    assert len(inbox) == 1
    assert inbox[0]["kind"] == "candidate"


# ---------------------------------------------------------------------------
# HTTP-handler-shaped helpers
# ---------------------------------------------------------------------------


def test_handle_post_happy():
    r = SignalingRelay()
    body = json.dumps({
        "kind": "offer", "from": "a", "to": "b",
        "payload": {"sdp": "v=0"},
    }).encode("utf-8")
    status, resp = handle_post(r, body)
    assert status == 200
    assert resp["ok"]


def test_handle_post_invalid_json():
    r = SignalingRelay()
    status, resp = handle_post(r, b"not json")
    assert status == 400
    assert not resp["ok"]


def test_handle_post_missing_to():
    r = SignalingRelay()
    body = json.dumps({"kind": "offer", "from": "a"}).encode("utf-8")
    status, resp = handle_post(r, body)
    assert status == 400
    assert not resp["ok"]


def test_handle_get_inbox_happy():
    r = SignalingRelay()
    r.post(kind="offer", sender="a", recipient="b", payload={"sdp": "v=0"})
    status, resp = handle_get_inbox(r, "b")
    assert status == 200
    assert resp["ok"]
    assert len(resp["messages"]) == 1


def test_handle_get_inbox_missing_peer():
    r = SignalingRelay()
    status, resp = handle_get_inbox(r, "")
    assert status == 400


# ---------------------------------------------------------------------------
# Concurrency smoke test
# ---------------------------------------------------------------------------


def test_concurrent_posts_no_data_loss():
    r = SignalingRelay()
    n = 200

    def writer(thread_id: int):
        for i in range(n):
            r.post(
                kind="candidate", sender=f"t{thread_id}",
                recipient="server",
                payload={"i": i, "tid": thread_id},
            )

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    inbox = r.inbox("server")
    # 4 threads × 200 msgs each = 800 messages stored
    assert len(inbox) == 4 * n
