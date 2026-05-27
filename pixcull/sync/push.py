"""v0.10-P0-1 — two-way sync push protocol.

v0.8-P0-2 shipped pull-only sync: collaborators poll the host every
5s for annotation changes, but the only way edits flow the *other*
direction (from collaborator back to host) was the user manually
re-typing the change on the host's machine.  That made the LAN sync
feel like a one-way mirror.

This module closes the loop:

  * POST /api/v1/sync/event/<token>/push   body: {edits: [...]}
    Collaborator pushes a batch of edits.  Server appends to the
    host's annotations.jsonl (atomic-ish append), then the next
    pull from other peers picks them up via the existing
    compute_changes_since() machinery — no extra fan-out logic.

  * The same module accepts edits from the host UI too, so the
    write path is single (no host-vs-guest fork).

  * Edits are append-only — never modifying past JSONL lines —
    so the file remains an audit trail.  Multiple edits to the
    same filename are simply multiple lines; the latest wins on
    read via compute_changes_since's last-line-per-filename
    collapse.

Conflict semantics
==================
The HTTP layer doesn't resolve conflicts.  Each edit lands on disk
in the order it arrived; readers (other peers via /changes polling)
see them in timestamp order and merge via apply_remote_changes(),
which is the function that flags conflicts.

The client UI is responsible for prompting the user to pick a
winner when apply_remote_changes() returns action="conflict".  See
the v0.10-P0-1 conflict resolution modal in results.html.

Offline queue
=============
Clients hold edits in IndexedDB when the network is down and flush
them on reconnect.  This module just sees one big batched push;
ordering inside the batch is preserved.  The client is free to
attach its own ``client_ts_ms`` to disambiguate "I made this edit
at T1 even though I sent it at T2".  We accept ``client_ts_ms``,
fall back to server-receive time, and pass it through as
``timestamp`` so compute_changes_since reads the same field it
already understood.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# Minimal schema for an inbound edit.  We don't enforce a complete
# rubric shape — the client is free to push partial edits (only
# the decision, only the rubric_stars, only the cull_reason, ...)
# and the read path collapses to "latest non-None per field" lazily.
REQUIRED_FIELDS = ("filename",)
ALLOWED_FIELDS = (
    "filename",
    "decision",          # keep / maybe / cull
    "overall_label",     # legacy alias for decision
    "rubric_stars",
    "rubric_human_labeled",
    "rubric_human_user",
    "rubric_human_at",
    "cull_reason",
    "advice",
    "client_id",         # who pushed this edit
    "client_ts_ms",      # when the client made it (their wall clock)
    "timestamp",         # canonical seconds-since-epoch (we set it)
    "edited_by",         # display name from presence
    "event_id",          # for audit
)


def normalize_edit(raw: Any, *, now_ms: int | None = None) -> dict | None:
    """Coerce one inbound edit into the on-disk JSONL row shape.

    Returns None when the edit is unusable (missing filename / not
    a dict).  Truncates string fields to defensive lengths so a
    malicious / buggy client can't bloat the host's annotations
    file unboundedly.
    """
    if not isinstance(raw, dict):
        return None
    fn = raw.get("filename")
    if not isinstance(fn, str) or not fn:
        return None
    out: dict[str, Any] = {}
    for k in ALLOWED_FIELDS:
        if k in raw:
            v = raw[k]
            if isinstance(v, str):
                # Defensive cap — filename + names + ids + reasons
                # are all "human-readable strings"; advice can be
                # longer but capped to 4 KB to keep one JSONL line
                # under a sane size.
                if k == "advice":
                    v = v[:4096]
                else:
                    v = v[:512]
            out[k] = v

    # Normalise the timestamp story.  Three cases:
    #   (a) client sent client_ts_ms → use it as our authoritative
    #       per-edit timestamp.  Reflects WHEN the user clicked,
    #       not when the bytes hit our socket.
    #   (b) client sent timestamp (seconds) → use it.
    #   (c) nothing → use server's now.
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if "client_ts_ms" in out:
        try:
            ts_ms = int(out["client_ts_ms"])
        except (TypeError, ValueError):
            ts_ms = now
    elif "timestamp" in out:
        try:
            ts_ms = int(float(out["timestamp"]) * 1000)
        except (TypeError, ValueError):
            ts_ms = now
    else:
        ts_ms = now
    # Both fields stay so downstream readers can use either; the
    # canonical one is `timestamp` (seconds).
    out["timestamp"] = ts_ms / 1000.0
    out["client_ts_ms"] = ts_ms

    # decision ↔ overall_label parity — accept either, persist both.
    if "decision" in out and "overall_label" not in out:
        out["overall_label"] = out["decision"]
    elif "overall_label" in out and "decision" not in out:
        out["decision"] = out["overall_label"]

    return out


def append_edits_jsonl(
    annotations_jsonl: Path,
    edits: list[dict],
    *,
    now_ms: int | None = None,
) -> list[dict]:
    """Append normalised edits to <output_dir>/annotations.jsonl.

    Returns the list of accepted (post-normalisation) rows so the
    HTTP handler can echo back what we wrote — useful for the
    client to confirm the server-assigned timestamps match its
    expectations.

    Atomicity: open(..., "a") + a single write call per edit is
    not strictly atomic at the byte level, but JSONL is line-
    oriented so the worst case is an unfinished trailing line
    after a crash — which compute_changes_since's "skip lines that
    don't parse" branch handles cleanly.
    """
    accepted: list[dict] = []
    for raw in edits:
        norm = normalize_edit(raw, now_ms=now_ms)
        if norm is None:
            continue
        accepted.append(norm)
    if not accepted:
        return []
    annotations_jsonl.parent.mkdir(parents=True, exist_ok=True)
    # Append in one open() so the order across a single batch is
    # preserved (other writers see the batch as contiguous lines).
    with open(annotations_jsonl, "a", encoding="utf-8") as fh:
        for row in accepted:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return accepted


def push_edits(
    run_output_dir: Path,
    edits: list[dict],
    *,
    event_id: str = "",
    now_ms: int | None = None,
) -> dict:
    """Top-level entry — what the HTTP handler calls.

    Returns a summary dict the handler serialises as the response:
      {
        "ok":         True,
        "accepted":   <count of edits persisted>,
        "rejected":   <count of malformed edits skipped>,
        "server_ts":  <ms-epoch the host wrote at>,
        "rows":       <list of post-normalisation rows>,
      }
    """
    if not isinstance(edits, list):
        raise ValueError("edits must be a list")
    # Tag every edit with the event_id so downstream audit can
    # filter "what arrived via this token".
    tagged = []
    for e in edits:
        if isinstance(e, dict):
            ee = dict(e)
            if event_id:
                ee.setdefault("event_id", event_id)
            tagged.append(ee)
        else:
            tagged.append(e)
    accepted = append_edits_jsonl(
        run_output_dir / "annotations.jsonl", tagged, now_ms=now_ms,
    )
    return {
        "ok":         True,
        "accepted":   len(accepted),
        "rejected":   len(edits) - len(accepted),
        "server_ts":  now_ms if now_ms is not None
                      else int(time.time() * 1000),
        "rows":       accepted,
    }
