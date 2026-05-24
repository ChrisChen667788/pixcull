"""v0.9-P1-2 — multiplayer presence for LAN sync events.

The v0.8-P0-2 sync subsystem already lets two-or-more PixCull
instances share annotation edits via an event token.  What that
slice doesn't surface is "who else is here right now and what are
they looking at" — second-shooter + editor wandering through the
same gallery feel completely alone unless one of them happens to
edit a row the other has open.

Presence model
==============
Per-event presence file:
  <run_output_dir>/presence/<event_id>.json

Shape (v1):
  {
    "schema":  "pixcull.sync.presence/v1",
    "event_id": "evt_abc123",
    "peers": {
      "<client_id>": {
        "client_id":            str,
        "display_name":         str,
        "last_viewed_filename": str | None,
        "last_action":          str | None,   # e.g. "keep", "cull", "ann"
        "last_action_filename": str | None,
        "last_action_at_ms":    int,
        "last_seen_ms":         int           # epoch-ms of newest heartbeat
      },
      ...
    }
  }

Heartbeats come in via POST every ~30 s; the GET endpoint filters
out anyone older than ``STALE_TTL_MS`` so the UI never shows a
ghost peer who closed their tab.

Pure-IO module: no Flask, no HTTP — the serve_demo handler is the
only caller.  Keeps tests cheap (just touch the JSON file).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


SCHEMA = "pixcull.sync.presence/v1"

# A client that hasn't heartbeated within this window is considered
# gone (browser tab closed, device asleep, dropped WiFi, ...).
# 30s heartbeat × 3 → 90s feels right; longer and ghosts linger,
# shorter and a momentary network blip drops the peer.
STALE_TTL_MS = 90_000

# Cap how many peers we ever persist — protects against a runaway
# script that generates a new client_id every heartbeat.  In real
# use a wedding has ≤ 5 collaborators; cap at 32.
MAX_PEERS = 32


def _ms_now() -> int:
    return int(time.time() * 1000)


def _presence_dir(run_output_dir: Path) -> Path:
    p = run_output_dir / "presence"
    p.mkdir(parents=True, exist_ok=True)
    return p


def presence_path(run_output_dir: Path, event_id: str) -> Path:
    """Filesystem location of a per-event presence file."""
    safe = event_id.replace("/", "_").replace("\\", "_")
    return _presence_dir(run_output_dir) / f"{safe}.json"


# ---------------------------------------------------------------------------
# Read / merge / write
# ---------------------------------------------------------------------------


def _read_raw(path: Path) -> dict[str, Any]:
    """Read the on-disk JSON or return a fresh blank skeleton."""
    if not path.exists():
        return {"schema": SCHEMA, "peers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "peers": {}}
    if not isinstance(data, dict):
        return {"schema": SCHEMA, "peers": {}}
    peers = data.get("peers")
    if not isinstance(peers, dict):
        data["peers"] = {}
    data.setdefault("schema", SCHEMA)
    return data


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    """Atomic write so concurrent heartbeats can't corrupt the file."""
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    # NamedTemporaryFile in the SAME directory so os.replace is atomic
    # (cross-device rename would not be).
    dir_ = path.parent
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(dir_),
            prefix=".presence-", suffix=".tmp", delete=False) as fh:
        fh.write(payload)
        tmpname = fh.name
    os.replace(tmpname, path)


def read_presence(
    run_output_dir: Path,
    event_id: str,
    now_ms: int | None = None,
) -> dict[str, dict]:
    """Return live peers, pruning anyone older than STALE_TTL_MS.

    Returns the peers dict keyed by client_id; does NOT include the
    outer schema wrapper.  Caller decides whether to filter further
    (e.g. exclude the requester).
    """
    if not event_id:
        return {}
    data = _read_raw(presence_path(run_output_dir, event_id))
    peers = data.get("peers", {})
    cutoff = (now_ms if now_ms is not None else _ms_now()) - STALE_TTL_MS
    live = {
        cid: rec for cid, rec in peers.items()
        if isinstance(rec, dict) and int(rec.get("last_seen_ms") or 0) >= cutoff
    }
    return live


def update_presence(
    run_output_dir: Path,
    event_id: str,
    client_id: str,
    *,
    display_name: str | None = None,
    last_viewed_filename: str | None = None,
    action: str | None = None,
    action_filename: str | None = None,
    now_ms: int | None = None,
) -> dict:
    """Merge a heartbeat into the presence file.

    Idempotent.  Returns the post-merge presence record for the
    given client_id so the caller can echo it back to the client
    (handy for the UI's own "you're listed as ..." footer line).
    """
    if not event_id or not client_id:
        raise ValueError("event_id and client_id required")
    path = presence_path(run_output_dir, event_id)
    data = _read_raw(path)
    peers: dict = data.setdefault("peers", {})
    ts = now_ms if now_ms is not None else _ms_now()
    rec = peers.get(client_id) or {}
    # Carry forward any fields the heartbeat didn't update — a
    # second-shooter's *last_action* should persist between viewer
    # heartbeats that only update *last_viewed_filename*.
    rec["client_id"]    = client_id
    if display_name:
        rec["display_name"] = display_name[:60]
    elif "display_name" not in rec:
        rec["display_name"] = f"peer-{client_id[:6]}"
    if last_viewed_filename is not None:
        rec["last_viewed_filename"] = last_viewed_filename[:200] or None
    if action:
        rec["last_action"] = action[:32]
        rec["last_action_filename"] = (action_filename or "")[:200] or None
        rec["last_action_at_ms"]    = ts
    rec["last_seen_ms"] = ts
    peers[client_id] = rec
    # Prune stale before persisting so the file doesn't grow
    # forever for a busy multi-day wedding.
    cutoff = ts - STALE_TTL_MS
    fresh = {
        cid: r for cid, r in peers.items()
        if int(r.get("last_seen_ms") or 0) >= cutoff
    }
    # Hard cap.  Keep the most-recently-seen.
    if len(fresh) > MAX_PEERS:
        sorted_pairs = sorted(
            fresh.items(),
            key=lambda kv: int(kv[1].get("last_seen_ms") or 0),
            reverse=True,
        )
        fresh = dict(sorted_pairs[:MAX_PEERS])
    data["peers"] = fresh
    data["event_id"] = event_id
    _write_atomic(path, data)
    return rec


def drop_peer(
    run_output_dir: Path, event_id: str, client_id: str
) -> bool:
    """Explicit-disconnect — used by ``navigator.sendBeacon`` on
    page unload to give peers an instant "they're gone" instead of
    waiting 90s for the stale TTL to expire.
    """
    if not event_id or not client_id:
        return False
    path = presence_path(run_output_dir, event_id)
    if not path.exists():
        return False
    data = _read_raw(path)
    peers = data.get("peers", {})
    if client_id not in peers:
        return False
    del peers[client_id]
    _write_atomic(path, data)
    return True
