"""v0.8-P0-2 — multi-user LAN sync subsystem.

Lets two-or-more PixCull instances (host + second-shooter / editor
/ assistant) collaborate on the same run by sharing an "event"
token.  Host issues a token; collaborators open a URL containing
the token; collaborators' clients poll the host for annotation
changes every 5 seconds and merge them into their local rows[].
Conflicting decisions (e.g. host says keep, second-shooter says
cull) surface as a "⚠ conflict" badge until reconciled.

This package is intentionally *transport-light* for v1:
  * Pull-only (collaborators fetch from host; no push-back yet)
  * HTTPS over the LAN with token auth (URL contains token)
  * No mDNS auto-discovery (paste URL or scan QR)
  * No SQLite migration (annotations stay as JSON files under
    <output_dir>/annotation/, indexed by mtime for change-list)

Follow-up slices:
  * v0.8-P0-2b — SQLite adapter wrapping the JSON files
  * v0.8-P0-2c — zeroconf mDNS auto-discovery
  * v0.8-P0-2d — push-back (collaborators commit changes back to host)
                 + full reconciliation modal

The v1 model is sufficient for the wedding/event use case the
charter calls out: a second-shooter on a tablet reviewing what
the main shooter (host) is keeping, ranking, culling.  Real
two-way edits + auto-merge land in v0.8-P0-2d.
"""

from pixcull.sync.event import (
    EventSession,
    apply_remote_changes,
    compute_changes_since,
    find_event_by_token,
    issue_event,
    load_event,
    revoke_event,
)
# v0.9-P1-2 — multiplayer presence (Figma-lite "who's looking at what")
from pixcull.sync.presence import (
    drop_peer,
    presence_path,
    read_presence,
    update_presence,
)
# v0.10-P0-1 — two-way push protocol (collaborators → host)
from pixcull.sync.push import (
    append_edits_jsonl,
    normalize_edit,
    push_edits,
)

__all__ = [
    "EventSession",
    "apply_remote_changes",
    "compute_changes_since",
    "find_event_by_token",
    "issue_event",
    "load_event",
    "revoke_event",
    # v0.9-P1-2
    "drop_peer",
    "presence_path",
    "read_presence",
    "update_presence",
    # v0.10-P0-1
    "append_edits_jsonl",
    "normalize_edit",
    "push_edits",
]
