"""v0.8-P0-2 — LAN sync event protocol.

Storage model
=============
One JSON file per active event:
  <run_output_dir>/events/<event_id>.json

Schema (v1):
  {
    "schema":      "pixcull.sync.event/v1",
    "event_id":    "evt_abc123",
    "token":       "secrets.token_urlsafe(16)",
    "run_id":      "<run_id>",
    "issued_at":   ISO,
    "expires_at":  ISO,
    "issued_by":   <user_label or "">,
    "label":       <free text, e.g. "wedding-2026-06-15">,
    "revoked":     false
  }

Change-list protocol
====================
Collaborators poll:
  GET /api/v1/sync/event/<token>/changes?since=<ms_epoch>

The server walks <output_dir>/annotation/*.json, filters files
whose ``mtime`` (or recorded ``updated_at``) ≥ since, and returns:

  {
    "schema":      "pixcull.sync.changes/v1",
    "run_id":      str,
    "server_ts":   <ms_epoch — what the next ?since= should pass>,
    "annotations": [{filename, decision, rubric_stars, ...,
                     updated_at_ms, edited_by}, ...]
  }

apply_remote_changes(local_rows, remote_payload) returns a list of
{filename, decision, conflict, ...} tuples that the JS side merges
into rows[].  Conflict detection is by-field — if the remote
decision differs from local and the remote's ``updated_at_ms`` is
older than the local row's last-known mtime, we flag a conflict
(the local edit happened after the remote we just received,
suggesting the user has un-pulled-in local work).
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


EVENT_TOKEN_LEN = 16  # bytes input to token_urlsafe → ~22-char output


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _events_dir(run_output_dir: Path) -> Path:
    p = run_output_dir / "events"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Event lifecycle
# ---------------------------------------------------------------------------


class EventSession:
    """Lightweight value-object representing a sync event.

    Persisted via ``issue_event`` / ``load_event`` to a single
    JSON file. Mutating ``revoked`` and re-saving is the supported
    revocation path (we never delete the file so audit logs stay).
    """

    SCHEMA = "pixcull.sync.event/v1"

    def __init__(self, data: dict):
        self.data = dict(data)

    @property
    def event_id(self) -> str:
        return self.data.get("event_id", "")

    @property
    def token(self) -> str:
        return self.data.get("token", "")

    @property
    def run_id(self) -> str:
        return self.data.get("run_id", "")

    @property
    def revoked(self) -> bool:
        return bool(self.data.get("revoked"))

    @property
    def expires_at(self) -> str | None:
        return self.data.get("expires_at")

    def is_active(self, now: datetime | None = None) -> bool:
        if self.revoked:
            return False
        exp = self.expires_at
        if not exp:
            return True
        try:
            exp_dt = datetime.fromisoformat(exp)
            return exp_dt >= (now or datetime.now(timezone.utc))
        except ValueError:
            return True

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "EventSession":
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls(data)


def issue_event(
    run_output_dir: Path,
    run_id: str,
    label: str = "",
    issued_by: str = "",
    ttl_hours: int = 12,
) -> EventSession:
    """Create + persist a new event under ``run_output_dir/events/``."""
    eid = "evt_" + secrets.token_hex(5)   # 10 hex chars → 1 in ~10^12
    token = secrets.token_urlsafe(EVENT_TOKEN_LEN)
    exp = (datetime.now(timezone.utc) + timedelta(hours=max(1, int(ttl_hours)))).isoformat()
    sess = EventSession({
        "schema":      EventSession.SCHEMA,
        "event_id":    eid,
        "token":       token,
        "run_id":      run_id,
        "issued_at":   _now_iso(),
        "expires_at":  exp,
        "issued_by":   issued_by[:80],
        "label":       label[:120],
        "revoked":     False,
    })
    (_events_dir(run_output_dir) / f"{eid}.json").write_text(
        sess.to_json(), encoding="utf-8"
    )
    return sess


def load_event(
    run_output_dir: Path, event_id: str
) -> EventSession | None:
    """Read an event from disk. Returns None when the file is absent
    or unreadable."""
    if not event_id or not event_id.startswith("evt_"):
        return None
    p = _events_dir(run_output_dir) / f"{event_id}.json"
    if not p.exists():
        return None
    try:
        return EventSession.from_json(p.read_text(encoding="utf-8"))
    except OSError:
        return None


def find_event_by_token(
    run_output_dir: Path, token: str
) -> EventSession | None:
    """Linear scan of <output>/events/*.json to find a matching token.

    O(n) in #events per run, which is bounded (a single run rarely
    has > 5 active events).  We use constant-time compare to avoid
    timing-attack signal.
    """
    if not token:
        return None
    ed = _events_dir(run_output_dir)
    if not ed.exists():
        return None
    for p in ed.glob("evt_*.json"):
        try:
            sess = EventSession.from_json(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        if secrets.compare_digest(sess.token, token):
            return sess
    return None


def revoke_event(
    run_output_dir: Path, event_id: str
) -> bool:
    """Idempotent revoke. Returns True if state changed, False if
    already revoked or missing."""
    sess = load_event(run_output_dir, event_id)
    if sess is None or sess.revoked:
        return False
    sess.data["revoked"] = True
    sess.data["revoked_at"] = _now_iso()
    (_events_dir(run_output_dir) / f"{event_id}.json").write_text(
        sess.to_json(), encoding="utf-8"
    )
    return True


# ---------------------------------------------------------------------------
# Change-list protocol
# ---------------------------------------------------------------------------


def _ms_now() -> int:
    return int(time.time() * 1000)


def compute_changes_since(
    annotations_source: Path,
    since_ms: int = 0,
) -> tuple[list[dict], int]:
    """Read annotations and return [(annotation, updated_at_ms), ...]
    for every entry with timestamp*1000 >= since_ms.

    Accepts either:
      * a JSONL file (one JSON object per line) — the canonical
        v0.5+ format under <run>/output/annotations.jsonl
      * a directory of individual *.json files — legacy fallback

    Returns (list_of_annotation_dicts, server_ts_ms).  The
    server_ts is the moment we sampled — the next poll should
    pass this as ?since= to avoid missing changes that happened
    between this call and the next.

    Each returned annotation dict carries an ``updated_at_ms``
    field (canonical "when was this last edited") and, for JSONL
    rows, the original ``timestamp`` (seconds) is preserved.

    JSONL is the common case: the file is append-only so the same
    filename can appear multiple times (every re-label gets a new
    row).  We collapse to the LAST line per filename — that's the
    current decision the user sees in the grid.
    """
    server_ts = _ms_now()
    out: list[dict] = []

    # --- JSONL (canonical v0.5+) ---
    if annotations_source.is_file():
        latest: dict[str, dict] = {}  # filename → latest row
        try:
            with open(annotations_source, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    fn = row.get("filename")
                    if not isinstance(fn, str) or not fn:
                        continue
                    ts_sec = row.get("timestamp")
                    try:
                        updated_ms = int(float(ts_sec) * 1000)
                    except (TypeError, ValueError):
                        updated_ms = 0
                    row["updated_at_ms"] = updated_ms
                    # Map overall_label → decision for parity with
                    # the grid's row schema (the JS merger checks
                    # `decision`, not `overall_label`).
                    if "decision" not in row and "overall_label" in row:
                        row["decision"] = row["overall_label"]
                    # Last-write-wins per filename
                    latest[fn] = row
        except OSError:
            return out, server_ts
        for row in latest.values():
            if row.get("updated_at_ms", 0) >= since_ms:
                out.append(row)
        out.sort(key=lambda d: d.get("updated_at_ms", 0), reverse=True)
        return out, server_ts

    # --- legacy dir of *.json (older deployments / future v2) ---
    if annotations_source.is_dir():
        for p in annotations_source.glob("*.json"):
            try:
                mtime_ms = int(p.stat().st_mtime * 1000)
            except OSError:
                continue
            if mtime_ms < since_ms:
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            data.setdefault("filename", p.stem)
            data["updated_at_ms"] = mtime_ms
            if "decision" not in data and "overall_label" in data:
                data["decision"] = data["overall_label"]
            out.append(data)
        out.sort(key=lambda d: d.get("updated_at_ms", 0), reverse=True)
        return out, server_ts

    # neither file nor directory — nothing to read
    return out, server_ts


def apply_remote_changes(
    local_rows: Iterable[dict],
    remote_annotations: Iterable[dict],
    local_mtimes: dict[str, int] | None = None,
) -> list[dict]:
    """Merge ``remote_annotations`` into ``local_rows``.

    Returns the list of "merge decisions" — one per remote
    annotation — with shape:
      {
        "filename":   str,
        "action":     "applied" | "skipped" | "conflict",
        "remote":     <full remote dict>,
        "local":      <existing row from local_rows, or None>,
        "reason":     str  (only when action=="skipped" or "conflict")
      }

    Conflict rule: if the local row's ``decision`` differs from
    the remote's, AND the local's ``updated_at_ms`` (from
    ``local_mtimes``) is newer than the remote's, we mark conflict
    instead of applying.  The UI can then prompt the user to pick
    a winner; the underlying file is NOT touched by this function.

    This is a pure function — caller is responsible for actually
    writing the merged annotations to disk if action=="applied".
    """
    local_map = {r.get("filename"): r for r in local_rows
                 if isinstance(r, dict) and r.get("filename")}
    local_mtimes = local_mtimes or {}
    results: list[dict] = []
    for ra in remote_annotations:
        if not isinstance(ra, dict):
            continue
        fn = ra.get("filename")
        if not isinstance(fn, str) or not fn:
            continue
        local = local_map.get(fn)
        if local is None:
            results.append({
                "filename": fn,
                "action":   "applied",
                "remote":   ra,
                "local":    None,
            })
            continue
        # Same decision → no-op (we still report "applied" so the
        # client knows the remote view matches locally).
        local_dec = local.get("decision")
        remote_dec = ra.get("decision")
        if local_dec == remote_dec:
            results.append({
                "filename": fn,
                "action":   "applied",
                "remote":   ra,
                "local":    local,
            })
            continue
        # Decisions diverge — is the local one newer?
        local_ts = int(local_mtimes.get(fn, 0))
        remote_ts = int(ra.get("updated_at_ms") or 0)
        if local_ts > remote_ts:
            results.append({
                "filename": fn,
                "action":   "conflict",
                "remote":   ra,
                "local":    local,
                "reason":   "local newer than remote",
            })
        else:
            # Remote is the most-recent edit — apply it.
            results.append({
                "filename": fn,
                "action":   "applied",
                "remote":   ra,
                "local":    local,
            })
    return results
