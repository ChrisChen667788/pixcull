#!/usr/bin/env python3
"""v0.11-P0-1 — Build the ``goldenset/v0.11/ground_truth.csv``.

Pulls every human-supplied label this checkout knows about into a single
flat CSV that ``train_rescorer.py`` and ``eval_rescorer.py`` can consume.

Sources (in priority order — first hit wins per filename)
==========================================================
1. ``out_wedding_eval/*/ground_truth.csv`` and any other
   ``ground_truth.csv`` directly under a per-user runs/ tree.  These
   were curated by hand and are the authoritative truth.
2. Per-user run dirs (10-char hex name) containing ``scores.csv`` rows
   with ``rubric_human_labeled == True`` — the in-app "I corrected
   this score" path.
3. ``annotations.jsonl`` files anywhere under the per-user runs/ tree —
   the keep/cull/maybe decisions captured by the grid + lightbox.

We do NOT pull from:
  - V2 demo runs that never received a human pass (auto-rubric only)
  - ``out_wedding_eval`` rows lacking a ``manual_label`` column

Dedup rule
==========
First source wins (priority 1 > 2 > 3).  Within a single source, later
``updated_at_ms`` wins — handles the "user changed their mind"
case that v0.10 multiplayer made common.

Output columns
==============
``filename, manual_label, scene, vertical, source, updated_at_ms``

``scene`` is the legacy column that older eval scripts key on;
``vertical`` is the v0.10+ replacement.  Both populated so eval
scripts on either schema keep working.

Usage
=====

    # Default: scans the current checkout
    python scripts/build_goldenset.py

    # Custom roots
    python scripts/build_goldenset.py \\
        --wedding-eval out_wedding_eval \\
        --runs-root ~/.pixcull/runs \\
        --out goldenset/v0.11/ground_truth.csv

    # Dry-run — print stats, don't write
    python scripts/build_goldenset.py --dry-run

Exit codes
==========
* 0 — wrote (or dry-ran successfully)
* 2 — no sources found (nothing to build)
* 3 — output dir doesn't exist and ``--mkdir`` not passed
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent

_VALID_LABELS = {"keep", "maybe", "cull"}

# Filename → preserved source/order is meaningful here, so we use a
# small dataclass instead of overloading dict semantics.
@dataclass
class Row:
    filename: str
    manual_label: str
    scene: str = ""
    vertical: str = ""
    source: str = ""
    updated_at_ms: int = 0
    extra: dict = field(default_factory=dict)


def _is_run_dir(p: Path) -> bool:
    """Per-user run dirs follow a 10-char hex naming convention."""
    return (
        p.is_dir()
        and len(p.name) == 10
        and all(c in "0123456789abcdef" for c in p.name)
    )


def _normalise_label(raw: object) -> str:
    """Map various label aliases to the canonical 3-class set."""
    if not isinstance(raw, str):
        return ""
    s = raw.strip().lower()
    if s in _VALID_LABELS:
        return s
    # v0.7 added "no" / "yes" as Annotation modal shortcuts
    if s in ("yes", "y", "1", "true"):
        return "keep"
    if s in ("no", "n", "0", "false"):
        return "cull"
    return ""


def _pick_vertical(scene: str, vertical: str | None) -> tuple[str, str]:
    """Return (scene, vertical) — fill blanks from whichever is set."""
    scene = (scene or "").strip()
    vertical = (vertical or "").strip()
    if scene and not vertical:
        vertical = scene
    if vertical and not scene:
        scene = vertical
    return scene, vertical


# ---------------------------------------------------------------------------
# Source 1 — ground_truth.csv files
# ---------------------------------------------------------------------------

def _scan_ground_truth_csvs(root: Path) -> Iterator[Row]:
    """Yield Row for every line in every ground_truth.csv under ``root``.

    Recurses one level (out_wedding_eval/<set>/ground_truth.csv).
    """
    if not root.exists():
        return
    for csv_path in sorted(root.rglob("ground_truth.csv")):
        try:
            df = pd.read_csv(csv_path, comment="#")
        except Exception as exc:  # noqa: BLE001
            print(f"[goldenset] skip {csv_path}: {exc}", file=sys.stderr)
            continue
        if "filename" not in df.columns or "manual_label" not in df.columns:
            continue
        for _, r in df.iterrows():
            label = _normalise_label(r.get("manual_label"))
            if not label:
                continue
            scene, vertical = _pick_vertical(
                str(r.get("scene", "") or ""),
                str(r.get("vertical", "") or ""),
            )
            yield Row(
                filename=str(r["filename"]),
                manual_label=label,
                scene=scene,
                vertical=vertical,
                source=f"gt:{csv_path.relative_to(root)}",
                # ground_truth.csv has no per-row timestamp, so use the
                # file's mtime — gives "newest curated file wins".
                updated_at_ms=int(csv_path.stat().st_mtime * 1000),
            )


# ---------------------------------------------------------------------------
# Source 2 — scores.csv with rubric_human_labeled rows
# ---------------------------------------------------------------------------

def _scan_in_app_corrections(runs_root: Path) -> Iterator[Row]:
    if not runs_root.exists():
        return
    for run_dir in sorted(runs_root.iterdir()):
        if not _is_run_dir(run_dir):
            continue
        scores_csv = run_dir / "scores.csv"
        if not scores_csv.exists():
            continue
        try:
            df = pd.read_csv(scores_csv)
        except Exception as exc:  # noqa: BLE001
            print(f"[goldenset] skip {scores_csv}: {exc}", file=sys.stderr)
            continue
        if "rubric_human_labeled" not in df.columns:
            continue
        sub = df[df["rubric_human_labeled"] == True]  # noqa: E712 — pandas
        for _, r in sub.iterrows():
            # The in-app correction sets a decision, not a manual_label,
            # so we read the human-edited decision.
            label = _normalise_label(
                r.get("decision_human") or r.get("decision")
            )
            if not label:
                continue
            scene, vertical = _pick_vertical(
                str(r.get("scene", "") or ""),
                str(r.get("vertical", "") or ""),
            )
            yield Row(
                filename=str(r.get("filename", "")),
                manual_label=label,
                scene=scene,
                vertical=vertical,
                source=f"app:{run_dir.name}",
                updated_at_ms=int(scores_csv.stat().st_mtime * 1000),
            )


# ---------------------------------------------------------------------------
# Source 3 — annotations.jsonl
# ---------------------------------------------------------------------------

def _scan_annotations(runs_root: Path) -> Iterator[Row]:
    """Walk every annotations.jsonl under ``runs_root`` and yield latest
    decision per filename per file."""
    if not runs_root.exists():
        return
    for ann_path in sorted(runs_root.rglob("annotations.jsonl")):
        # Maintain last-write-wins within this jsonl
        latest: dict[str, Row] = {}
        try:
            with ann_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    fn = data.get("filename")
                    if not isinstance(fn, str) or not fn:
                        continue
                    label = _normalise_label(
                        data.get("decision") or data.get("overall_label")
                    )
                    if not label:
                        continue
                    try:
                        ts_ms = int(float(data.get("timestamp", 0)) * 1000)
                    except (TypeError, ValueError):
                        ts_ms = 0
                    cur = latest.get(fn)
                    if cur is None or ts_ms >= cur.updated_at_ms:
                        scene, vertical = _pick_vertical(
                            str(data.get("scene", "") or ""),
                            str(data.get("vertical", "") or ""),
                        )
                        latest[fn] = Row(
                            filename=fn,
                            manual_label=label,
                            scene=scene,
                            vertical=vertical,
                            source=f"ann:{ann_path.parent.name}",
                            updated_at_ms=ts_ms,
                        )
        except OSError as exc:
            print(f"[goldenset] skip {ann_path}: {exc}", file=sys.stderr)
            continue
        yield from latest.values()


# ---------------------------------------------------------------------------
# Merge — priority + dedup
# ---------------------------------------------------------------------------

def _merge_rows(*streams: Iterable[Row]) -> list[Row]:
    """Higher-priority streams come first.  First non-empty source per
    filename wins; within a source, latest timestamp wins."""
    out: dict[str, Row] = {}
    source_priority: dict[str, int] = {}
    for prio, stream in enumerate(streams):
        for row in stream:
            existing = out.get(row.filename)
            if existing is None:
                out[row.filename] = row
                source_priority[row.filename] = prio
                continue
            # Same-or-higher priority source: latest timestamp wins
            if prio == source_priority[row.filename]:
                if row.updated_at_ms > existing.updated_at_ms:
                    out[row.filename] = row
            # Lower priority (prio > existing): ignore
    return sorted(out.values(), key=lambda r: r.filename)


def _write_csv(rows: list[Row], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "filename", "manual_label", "scene", "vertical",
            "source", "updated_at_ms",
        ])
        for r in rows:
            w.writerow([
                r.filename, r.manual_label, r.scene, r.vertical,
                r.source, r.updated_at_ms,
            ])


def _summary(rows: list[Row]) -> str:
    """Human-readable counts — labelled `[goldenset]` for grepability."""
    n = len(rows)
    if n == 0:
        return "[goldenset] (empty)"
    by_label: dict[str, int] = {}
    by_vertical: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in rows:
        by_label[r.manual_label] = by_label.get(r.manual_label, 0) + 1
        v = r.vertical or r.scene or "unknown"
        by_vertical[v] = by_vertical.get(v, 0) + 1
        # Source family (gt / app / ann)
        family = r.source.split(":", 1)[0] if r.source else "?"
        by_source[family] = by_source.get(family, 0) + 1
    parts = [f"[goldenset] {n:,} rows"]
    parts.append(
        "  labels:  "
        + "  ".join(f"{k}={v}" for k, v in sorted(by_label.items()))
    )
    parts.append(
        "  sources: "
        + "  ".join(f"{k}={v}" for k, v in sorted(by_source.items()))
    )
    top_verticals = sorted(by_vertical.items(), key=lambda kv: -kv[1])[:8]
    parts.append(
        "  top verticals: "
        + "  ".join(f"{k}={v}" for k, v in top_verticals)
    )
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build goldenset/v0.11/ground_truth.csv from all "
                    "human-supplied label sources in this checkout."
    )
    p.add_argument(
        "--wedding-eval", type=Path,
        default=REPO_ROOT / "out_wedding_eval",
        help="Root for ground_truth.csv files "
             "(default: out_wedding_eval/)"
    )
    p.add_argument(
        "--runs-root", type=Path,
        default=Path.home() / ".pixcull" / "runs",
        help="Per-user run dirs root "
             "(default: ~/.pixcull/runs)"
    )
    p.add_argument(
        "--out", type=Path,
        default=REPO_ROOT / "goldenset" / "v0.11" / "ground_truth.csv",
        help="Output CSV path"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print stats, don't write"
    )
    p.add_argument(
        "--mkdir", action="store_true", default=True,
        help="Create the output parent dir if missing (default on)"
    )
    args = p.parse_args(argv)

    rows = _merge_rows(
        _scan_ground_truth_csvs(args.wedding_eval),
        _scan_in_app_corrections(args.runs_root),
        _scan_annotations(args.runs_root),
    )

    print(_summary(rows), file=sys.stderr)

    if not rows:
        print(
            "[goldenset] no rows found.\n"
            f"  expected sources:\n"
            f"    - {args.wedding_eval}/**/ground_truth.csv\n"
            f"    - {args.runs_root}/<run>/scores.csv (rubric_human_labeled)\n"
            f"    - {args.runs_root}/**/annotations.jsonl\n",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(f"[goldenset] DRY RUN — would write {len(rows):,} rows to "
              f"{args.out}", file=sys.stderr)
        return 0

    _write_csv(rows, args.out)
    print(f"[goldenset] wrote {len(rows):,} rows to {args.out}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
