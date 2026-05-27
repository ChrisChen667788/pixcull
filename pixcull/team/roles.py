"""v0.10-P1-1 — per-event role assignment (head-shooter override).

In a LAN sync event, one user is the "head shooter" — typically
the photographer who's responsible for the final delivery to the
client.  When the conflict resolution modal fires (two peers
diverged on the same photo), the head-shooter's decision is
pre-selected as the default winner.

This module is a small JSON-on-disk persistence layer because the
LAN sync event already lives as a JSON file under
``<run_output_dir>/events/<event_id>.json``.  We extend that file
with a ``head_shooter_user_id`` field rather than building a new
data-store.

Why JSON-on-disk (not in-memory): the host might restart between
events (laptop sleeps + wakes during a ceremony), and the head-
shooter assignment shouldn't be lost.  A 5-line JSON read on
each presence/push request is plenty fast for the scale.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path


def _events_dir(run_output_dir: Path) -> Path:
    p = run_output_dir / "events"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _event_file(run_output_dir: Path, event_id: str) -> Path:
    safe = event_id.replace("/", "_").replace("\\", "_")
    return _events_dir(run_output_dir) / f"{safe}.json"


def set_head_shooter(
    run_output_dir: Path,
    event_id: str,
    user_id: str,
) -> bool:
    """Tag an event with a head-shooter user_id.

    Idempotent: assigning the same user a second time is a no-op
    that returns True.  Returns False when the event file is
    missing.
    """
    path = _event_file(run_output_dir, event_id)
    if not path.exists():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(doc, dict):
        return False
    doc["head_shooter_user_id"] = str(user_id)[:80]
    try:
        path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


def get_head_shooter(
    run_output_dir: Path,
    event_id: str,
) -> str | None:
    """Return the assigned head_shooter_user_id, or None."""
    path = _event_file(run_output_dir, event_id)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    v = doc.get("head_shooter_user_id")
    return v if isinstance(v, str) and v else None


def clear_head_shooter(
    run_output_dir: Path,
    event_id: str,
) -> bool:
    """Drop the head_shooter assignment from an event.  Returns
    True only when a value was actually removed."""
    path = _event_file(run_output_dir, event_id)
    if not path.exists():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(doc, dict) or "head_shooter_user_id" not in doc:
        return False
    del doc["head_shooter_user_id"]
    try:
        path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True
