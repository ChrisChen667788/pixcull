#!/usr/bin/env python3
"""v0.13-P1-4 — Auto-augment the goldenset from disagreement rows.

Closes the active-learning loop:

    [user labels in app] → [annotations.jsonl writes model_decision_before]
                ↓
        [disagreement.jsonl extracted by this script]
                ↓
       [appended to goldenset/v0.<NEXT>/ground_truth.csv]
                ↓
       [next rescorer train consumes the increment]

Runs in two modes:

* ``--top N`` (default 200): pick the N most-informative reversals
  per the rescorer's confidence × scene under-representation joint
  score.  These are the rows that *teach* the rescorer.
* ``--all``: append every disagreement (use sparingly — bloats the
  goldenset with redundant near-duplicates).

Source: every ``annotations.jsonl`` under ``~/.pixcull/runs/``.
Output: ``goldenset/v0.<next_version>/ground_truth.csv`` (computed
from the current charter version + 1 by reading
``docs/ROADMAP-v0.<X>-charter.md``).

Usage
=====

    # Default: top-200 to the next version's goldenset
    python scripts/goldenset_auto_augment.py

    # Dry-run — print stats, don't append
    python scripts/goldenset_auto_augment.py --dry-run

    # Force-target a specific output
    python scripts/goldenset_auto_augment.py \\
        --out goldenset/v0.14/ground_truth.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _iter_disagreements(runs_root: Path):
    """Yield (filename, human_label, model_label, scene, prob_keep,
    run_name) for every reversal across every run."""
    if not runs_root.exists():
        return
    for ann_path in runs_root.rglob("annotations.jsonl"):
        run_name = ann_path.parent.name
        try:
            fh = ann_path.open("r", encoding="utf-8")
        except OSError:
            continue
        try:
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
                user = (data.get("decision")
                        or data.get("overall_label") or "").strip().lower()
                model = (data.get("model_decision")
                         or data.get("rescorer_pred") or "").strip().lower()
                if not user or not model or user == model:
                    continue
                if user not in ("keep", "maybe", "cull"):
                    continue
                prob = data.get("rescorer_prob_keep")
                try:
                    prob_f = float(prob) if prob is not None else None
                except (TypeError, ValueError):
                    prob_f = None
                yield {
                    "filename": fn,
                    "manual_label": user,
                    "model_decision": model,
                    "scene": data.get("scene", "") or data.get("vertical", ""),
                    "vertical": data.get("vertical", "") or data.get("scene", ""),
                    "rescorer_prob_keep": prob_f,
                    "run_name": run_name,
                }
        finally:
            fh.close()


def _informativeness(row: dict, scene_counts: dict[str, int]) -> float:
    """Score how informative this reversal is for the next training cycle.

    Higher = more useful.  Two factors:
      * model confidence (closer to 0 or 1 = bigger surprise)
      * scene under-representation (smaller bucket = more useful)
    """
    prob = row.get("rescorer_prob_keep")
    if prob is None:
        prob_score = 0.5
    else:
        prob_score = max(prob, 1 - prob)   # 0.5..1.0
    scene = row.get("scene", "") or row.get("vertical", "")
    # Inverse-frequency boost — rare scenes get a higher score.  Add 1
    # to avoid div-by-zero on the first sighting.
    rarity = 1.0 / (scene_counts.get(scene, 0) + 1)
    return prob_score * 0.7 + rarity * 0.3


def _detect_next_version() -> str:
    """Read the latest ROADMAP-v0.<X>-charter.md and return v0.<X+1>."""
    charters = sorted(
        (REPO_ROOT / "docs").glob("ROADMAP-v0.*-charter.md")
    )
    if not charters:
        return "v0.14"   # safe default
    # Names are 'ROADMAP-v0.13-charter.md'; extract the version
    latest = charters[-1].stem
    try:
        major, minor = latest.split("ROADMAP-")[1].split("-charter")[0].split(".")
        return f"{major}.{int(minor) + 1}"
    except (ValueError, IndexError):
        return "v0.14"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Auto-augment the goldenset from disagreement rows."
    )
    p.add_argument(
        "--runs-root", type=Path,
        default=Path.home() / ".pixcull" / "runs",
        help="Where annotations.jsonl files live"
    )
    p.add_argument(
        "--out", type=Path, default=None,
        help="Output CSV path (default: goldenset/<next-version>/"
             "ground_truth.csv)"
    )
    p.add_argument(
        "--top", type=int, default=200,
        help="Number of most-informative reversals to keep (default 200)"
    )
    p.add_argument(
        "--all", action="store_true",
        help="Append every disagreement (overrides --top)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print stats, don't write"
    )
    args = p.parse_args(argv)

    # Step 1 — gather all disagreements + count scenes for rarity score
    rows: list[dict] = []
    scene_counts: dict[str, int] = {}
    for r in _iter_disagreements(args.runs_root):
        rows.append(r)
        sc = r.get("scene", "")
        if sc:
            scene_counts[sc] = scene_counts.get(sc, 0) + 1
    if not rows:
        print(f"[goldenset-aug] no disagreements found under {args.runs_root}",
              file=sys.stderr)
        return 2

    # Step 2 — score + rank
    scored = [(r, _informativeness(r, scene_counts)) for r in rows]
    scored.sort(key=lambda t: -t[1])
    keep = scored if args.all else scored[:args.top]

    # Step 3 — determine target path
    if args.out is None:
        next_ver = _detect_next_version()
        args.out = (REPO_ROOT / "goldenset" / next_ver /
                    "ground_truth.csv")

    print(f"[goldenset-aug] {len(rows):,} disagreements found",
          file=sys.stderr)
    print(f"[goldenset-aug] keeping top {len(keep):,} most-informative",
          file=sys.stderr)
    by_label = {}
    for r, _ in keep:
        by_label[r["manual_label"]] = by_label.get(r["manual_label"], 0) + 1
    print("[goldenset-aug] label split: " +
          "  ".join(f"{k}={v}" for k, v in sorted(by_label.items())),
          file=sys.stderr)
    print(f"[goldenset-aug] target: {args.out}", file=sys.stderr)

    if args.dry_run:
        print("[goldenset-aug] DRY RUN — no file written", file=sys.stderr)
        return 0

    # Step 4 — append (or create) the CSV.  Schema matches
    # scripts/build_goldenset.py: filename,manual_label,scene,vertical,
    # source,updated_at_ms
    args.out.parent.mkdir(parents=True, exist_ok=True)
    existing_filenames: set[str] = set()
    fieldnames = [
        "filename", "manual_label", "scene", "vertical",
        "source", "updated_at_ms",
    ]
    write_header = not args.out.exists()
    if not write_header:
        with args.out.open("r", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                existing_filenames.add(r.get("filename", ""))
    with args.out.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        n_written = 0
        n_skipped = 0
        for r, _ in keep:
            if r["filename"] in existing_filenames:
                n_skipped += 1
                continue
            w.writerow({
                "filename":      r["filename"],
                "manual_label":  r["manual_label"],
                "scene":         r["scene"],
                "vertical":      r["vertical"],
                "source":        f"auto-aug:{r['run_name']}",
                "updated_at_ms": 0,
            })
            n_written += 1
            existing_filenames.add(r["filename"])
    print(f"[goldenset-aug] ✓ wrote {n_written:,} new rows "
          f"({n_skipped:,} skipped as dup) to {args.out}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
