"""v0.13.9 — Workflow depth helpers.

Three small features that turn the grid from "ad-hoc cull tool" into
a workflow:

  * **Bookmarks** — a third decision channel orthogonal to keep / maybe
    / cull.  "I need to check this with the client" or "remind me to
    add a color correction note" — survives across runs.  Stored
    per-user in ``~/.pixcull/bookmarks.json``.
  * **Recap** — server-side summary endpoint that aggregates today's
    annotation activity into a digest:  rows touched, decisions made,
    time saved estimate, top cull reason, longest run.
  * **Session conflict detection** — flags photos the user culled in
    a previous run but is now keeping (or vice versa).  Surfaces a
    yellow "你之前选了不同决策" warning in the Inspector.

All three are pure Python, file-based, no DB.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


@dataclass
class Bookmark:
    """One bookmark — orthogonal to keep/maybe/cull."""
    filename: str
    run_id: str
    note: str = ""
    color: str = "blue"  # blue / green / yellow / red — pure label
    created_at: float = 0.0


def _bookmarks_path() -> Path:
    if os.name == "posix":
        base = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        base = Path.home() / ".pixcull"
    base.mkdir(parents=True, exist_ok=True)
    return base / "bookmarks.json"


def _load_bookmarks() -> list[Bookmark]:
    p = _bookmarks_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
        return []
    out: list[Bookmark] = []
    for b in data.get("bookmarks", []):
        if not isinstance(b, dict):
            continue
        try:
            out.append(Bookmark(
                filename=str(b["filename"]),
                run_id=str(b["run_id"]),
                note=str(b.get("note", "")),
                color=str(b.get("color", "blue")),
                created_at=float(b.get("created_at", 0.0)),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _save_bookmarks(bookmarks: list[Bookmark]) -> None:
    p = _bookmarks_path()
    body = json.dumps({
        "version": SCHEMA_VERSION,
        "bookmarks": [asdict(b) for b in bookmarks],
    }, ensure_ascii=False, indent=2)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)


def toggle_bookmark(run_id: str, filename: str,
                    note: str = "", color: str = "blue") -> bool:
    """Add/remove a bookmark.  Returns True when bookmark was added,
    False when removed."""
    if not run_id or not filename:
        raise ValueError("run_id + filename required")
    bookmarks = _load_bookmarks()
    # Find existing (filename + run_id pair is unique)
    for i, b in enumerate(bookmarks):
        if b.filename == filename and b.run_id == run_id:
            bookmarks.pop(i)
            _save_bookmarks(bookmarks)
            return False
    bookmarks.append(Bookmark(
        filename=filename, run_id=run_id,
        note=note, color=color,
        created_at=time.time(),
    ))
    _save_bookmarks(bookmarks)
    return True


def list_bookmarks(run_id: str | None = None) -> list[Bookmark]:
    """Return all bookmarks (or just this run's when ``run_id`` given)."""
    all_bookmarks = _load_bookmarks()
    if run_id is None:
        return all_bookmarks
    return [b for b in all_bookmarks if b.run_id == run_id]


def is_bookmarked(run_id: str, filename: str) -> bool:
    return any(
        b.filename == filename and b.run_id == run_id
        for b in _load_bookmarks()
    )


# ---------------------------------------------------------------------------
# Daily recap
# ---------------------------------------------------------------------------


@dataclass
class DailyRecap:
    """Today's activity rollup."""
    date_iso: str               # YYYY-MM-DD
    n_annotations: int
    n_keep: int
    n_maybe: int
    n_cull: int
    n_bookmarks: int
    n_runs_touched: int
    top_cull_reason: str        # most-used reason today
    top_cull_reason_count: int
    longest_run_id: str         # run with most annotations today
    longest_run_count: int
    time_saved_min: int         # rough estimate, see _estimate_time_saved


def _estimate_time_saved(n_annotated: int, n_cull: int) -> int:
    """Back-of-envelope:  each cull keeps the photographer from
    looking at it later in Lr ~= 15 sec saved per cull;  each keep/
    maybe is ~= 5 sec saved.  Round to whole minutes."""
    seconds = n_cull * 15 + (n_annotated - n_cull) * 5
    return max(0, seconds // 60)


def daily_recap(runs_root: Path,
                date_iso: str | None = None) -> DailyRecap:
    """Walk ``runs_root`` for today's annotations + aggregate.

    Same data source as ``pixcull.scoring.bias_audit`` — every
    ``annotations.jsonl`` under ``runs_root``.

    ``date_iso``:
      * None → today's date (default)
      * YYYY-MM-DD → arbitrary day (for past-day recap)
    """
    import datetime as _dt
    if date_iso is None:
        date_iso = _dt.date.today().isoformat()
    try:
        target_day = _dt.date.fromisoformat(date_iso)
    except ValueError:
        target_day = _dt.date.today()
        date_iso = target_day.isoformat()
    n_keep = n_maybe = n_cull = 0
    runs_seen: dict[str, int] = {}
    cull_reasons: dict[str, int] = {}
    if runs_root.exists():
        for ann_path in runs_root.rglob("annotations.jsonl"):
            run_name = ann_path.parent.name
            try:
                with ann_path.open("r", encoding="utf-8") as fh:
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
                        ts = row.get("timestamp")
                        try:
                            ts_f = float(ts) if ts else 0.0
                        except (TypeError, ValueError):
                            continue
                        row_day = _dt.date.fromtimestamp(ts_f)
                        if row_day != target_day:
                            continue
                        dec = (row.get("decision")
                               or row.get("overall_label") or "").lower()
                        if dec == "keep":
                            n_keep += 1
                        elif dec == "maybe":
                            n_maybe += 1
                        elif dec == "cull":
                            n_cull += 1
                            reason = row.get("cull_reason", "")
                            if reason:
                                cull_reasons[reason] = (
                                    cull_reasons.get(reason, 0) + 1)
                        if dec in ("keep", "maybe", "cull"):
                            runs_seen[run_name] = (
                                runs_seen.get(run_name, 0) + 1)
            except OSError:
                continue
    n_total = n_keep + n_maybe + n_cull
    n_bookmarks = sum(
        1 for b in _load_bookmarks()
        if _dt.date.fromtimestamp(b.created_at).isoformat() == date_iso
    )
    top_reason = ""
    top_reason_count = 0
    if cull_reasons:
        top_reason, top_reason_count = max(
            cull_reasons.items(), key=lambda kv: kv[1])
    longest_run_id = ""
    longest_run_count = 0
    if runs_seen:
        longest_run_id, longest_run_count = max(
            runs_seen.items(), key=lambda kv: kv[1])
    return DailyRecap(
        date_iso=date_iso,
        n_annotations=n_total,
        n_keep=n_keep,
        n_maybe=n_maybe,
        n_cull=n_cull,
        n_bookmarks=n_bookmarks,
        n_runs_touched=len(runs_seen),
        top_cull_reason=top_reason,
        top_cull_reason_count=top_reason_count,
        longest_run_id=longest_run_id,
        longest_run_count=longest_run_count,
        time_saved_min=_estimate_time_saved(n_total, n_cull),
    )


# ---------------------------------------------------------------------------
# Session conflict detection
# ---------------------------------------------------------------------------


def session_conflicts(runs_root: Path,
                      current_run_id: str) -> dict[str, dict]:
    """Find photos whose decision in the current run conflicts with
    a previous run's decision for the SAME filename.

    Returns ``{filename: {previous_decision, current_decision,
    previous_run_id, previous_ts}}`` — empty when no conflict.

    Useful when a photographer is re-curating a wedding 2 weeks
    later and changes their mind on borderline keeps — surfaces
    "you culled this on 6-14, keeping now — change of heart?"
    """
    if not runs_root.exists():
        return {}
    # Walk every annotations.jsonl, build {filename: [(run, dec, ts)]}
    by_filename: dict[str, list] = {}
    for ann_path in runs_root.rglob("annotations.jsonl"):
        run_name = ann_path.parent.name
        try:
            with ann_path.open("r", encoding="utf-8") as fh:
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
                    dec = (row.get("decision")
                           or row.get("overall_label") or "").lower()
                    ts = row.get("timestamp")
                    if (not fn or dec not in ("keep", "maybe", "cull")
                            or ts is None):
                        continue
                    by_filename.setdefault(fn, []).append(
                        (run_name, dec, float(ts)))
        except OSError:
            continue
    out: dict[str, dict] = {}
    for fn, decisions in by_filename.items():
        # Sort by timestamp ascending
        decisions.sort(key=lambda d: d[2])
        # Find latest in current run
        latest_current = None
        for run_name, dec, ts in decisions:
            if run_name == current_run_id:
                latest_current = (dec, ts)
        if latest_current is None:
            continue   # not annotated in current run
        # Find any previous run's last decision
        previous = None
        for run_name, dec, ts in decisions:
            if run_name != current_run_id and ts < latest_current[1]:
                previous = (run_name, dec, ts)
        if previous is None:
            continue
        if previous[1] != latest_current[0]:
            out[fn] = {
                "previous_decision": previous[1],
                "current_decision":  latest_current[0],
                "previous_run_id":   previous[0],
                "previous_ts":       previous[2],
            }
    return out
