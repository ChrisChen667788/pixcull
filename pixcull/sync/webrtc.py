"""v0.11-P0-3 — WebRTC signaling relay.

Why this lives here
===================
The actual WebRTC peer connection lives 100% in the browser
(``RTCPeerConnection`` + ``RTCDataChannel``).  The Python server
never sees image data, annotation deltas, or anything that
would normally travel through it — it only relays the SDP
offer/answer and ICE candidates *while* the two browsers
negotiate the direct connection.  Once the datachannel opens,
peer-to-peer messages bypass this server entirely.

That makes the server-side responsibility very small:

  * accept POST /api/v1/sync/webrtc/offer with ``{from, to, sdp}``
  * accept POST /api/v1/sync/webrtc/answer with ``{from, to, sdp}``
  * accept POST /api/v1/sync/webrtc/candidate with ``{from, to, candidate}``
  * GET /api/v1/sync/webrtc/inbox?peer=<id>&since=<ms>
    → return every message addressed *to* this peer since <ms>

The protocol is JSON only, no streams, no long-poll.  The browser
polls inbox every ~500ms while negotiating; once datachannel is
open polling stops.

Privacy guarantees
==================
* No image bytes, annotation deltas, or filenames ever pass through
  this server.  The datachannel handles all of that browser-direct.
* SDP offers contain the ICE candidates (local IP + STUN-discovered
  public IP).  This is the same info that LAN mDNS already
  broadcasts.  No cookies, no IDs from outside the local pixcull
  session.
* Messages expire from the inbox after ``_TTL_MS``
  (default 60s) regardless of read state — sessions are
  ephemeral by design.

Fallback contract
=================
Callers MUST set a 5s timeout on RTCDataChannel.open and fall back
to the existing HTTP-polling sync layer (``pixcull.sync.event``)
if the datachannel doesn't open in time.  WebRTC is an
upgrade, not a replacement.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable


# Per-peer inbox TTL.  60s is plenty for SDP exchange + ICE
# negotiation (typically completes in 1-3s on LAN, 3-8s for
# STUN-traversed WAN).
_TTL_MS = 60_000


@dataclass
class _Message:
    kind: str          # "offer" | "answer" | "candidate" | "bye"
    sender: str        # peer id of the sender
    payload: dict      # SDP or ICE candidate
    ts_ms: int         # epoch ms when stored


@dataclass
class Inbox:
    """One peer's pending signaling messages.

    The state is intentionally simple — a list of messages
    addressed *to* this peer.  We never expose absolute message IDs;
    callers paginate by timestamp.
    """
    peer_id: str
    messages: list[_Message] = field(default_factory=list)


class SignalingRelay:
    """In-memory signaling relay.

    Thread-safe (covers the BaseHTTPRequestHandler thread pool used
    by ``scripts/serve_demo.py``).

    The relay is keyed by *recipient* peer ID for cheap GET lookup.
    Senders address messages explicitly via the ``to`` field on POST;
    the relay stores the message in ``inboxes[to]``.
    """

    def __init__(self, ttl_ms: int = _TTL_MS) -> None:
        self._ttl_ms = int(ttl_ms)
        self._inboxes: dict[str, Inbox] = {}
        self._lock = threading.Lock()
        # Test/dev hook so tests can pin time.  Production uses time.time().
        self._clock = lambda: int(time.time() * 1000)

    # ------------------------------------------------------------------
    # POST handlers (server-side, called from serve_demo.py)
    # ------------------------------------------------------------------

    def post(self, *, kind: str, sender: str, recipient: str,
             payload: dict) -> dict:
        """Store a signaling message addressed to ``recipient``.

        Returns the server-stamped envelope so the sender can log
        the relay timestamp.
        """
        kind = (kind or "").strip().lower()
        if kind not in ("offer", "answer", "candidate", "bye"):
            return {"ok": False, "error": f"unknown kind: {kind!r}"}
        if not sender or not recipient:
            return {"ok": False, "error": "sender + recipient required"}
        if sender == recipient:
            return {"ok": False, "error": "self-addressed"}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "payload must be an object"}
        msg = _Message(
            kind=kind, sender=sender, payload=payload,
            ts_ms=self._clock(),
        )
        with self._lock:
            inbox = self._inboxes.setdefault(recipient, Inbox(peer_id=recipient))
            inbox.messages.append(msg)
            self._gc_locked()
        return {"ok": True, "ts_ms": msg.ts_ms}

    # ------------------------------------------------------------------
    # GET handlers
    # ------------------------------------------------------------------

    def inbox(self, peer_id: str, since_ms: int = 0) -> list[dict]:
        """Drain a peer's inbox.  Returns every message stored *for*
        this peer since ``since_ms``.

        Messages stay in the inbox until they age out — clients should
        track the highest ts_ms they've seen and pass it as ``since``.
        """
        with self._lock:
            self._gc_locked()
            inbox = self._inboxes.get(peer_id)
            if inbox is None:
                return []
            out = []
            for m in inbox.messages:
                if m.ts_ms <= since_ms:
                    continue
                out.append({
                    "kind": m.kind,
                    "from": m.sender,
                    "payload": m.payload,
                    "ts_ms": m.ts_ms,
                })
            return out

    def peer_ids(self) -> list[str]:
        """Return all peer IDs with active inboxes (debug helper)."""
        with self._lock:
            self._gc_locked()
            return sorted(self._inboxes.keys())

    # ------------------------------------------------------------------
    # House-keeping
    # ------------------------------------------------------------------

    def _gc_locked(self) -> None:
        """Drop expired messages.  Holds the lock — caller's problem."""
        now = self._clock()
        cutoff = now - self._ttl_ms
        for box in list(self._inboxes.values()):
            box.messages = [m for m in box.messages if m.ts_ms > cutoff]
            if not box.messages:
                # Clean up empty inbox to keep peer_ids() honest
                self._inboxes.pop(box.peer_id, None)


# ---------------------------------------------------------------------------
# HTTP route helpers — drop-in for BaseHTTPRequestHandler
# ---------------------------------------------------------------------------

def handle_post(relay: SignalingRelay, body: bytes) -> tuple[int, dict]:
    """Parse a POST body for /api/v1/sync/webrtc/{kind} and store it.

    The kind comes from the URL path, the payload from the body.
    Returns (http_status, response_json).
    """
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return 400, {"ok": False, "error": "invalid JSON"}
    if not isinstance(data, dict):
        return 400, {"ok": False, "error": "body must be an object"}
    kind = data.get("kind", "")
    sender = data.get("from", "")
    recipient = data.get("to", "")
    payload = data.get("payload", {})
    resp = relay.post(
        kind=kind, sender=sender, recipient=recipient, payload=payload,
    )
    return (200 if resp.get("ok") else 400), resp


def handle_get_inbox(relay: SignalingRelay, peer_id: str,
                     since_ms: int = 0) -> tuple[int, dict]:
    """Serve /api/v1/sync/webrtc/inbox?peer=<id>&since=<ms>."""
    if not peer_id:
        return 400, {"ok": False, "error": "peer parameter required"}
    messages = relay.inbox(peer_id, since_ms=since_ms)
    return 200, {"ok": True, "messages": messages}


# Convenience: most servers want a single relay shared across requests.
_default_relay = SignalingRelay()


def default_relay() -> SignalingRelay:
    return _default_relay
