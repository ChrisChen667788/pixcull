"""V19.2 — fold scan_multi feature CSVs into training_axis.csv.

scan_multi.py (since V19.2) writes a sister ``<basename>.features.csv``
alongside its slim JSON, containing the full per-image feature vector
(laplacian_*, mean_luma, clipiqa, face_*, score_*, ...). This script
takes one or more of those CSVs and appends rows to training_axis.csv
in the schema expected by train_axis_rescorers.py.

Why this script exists
======================
The original ``build_axis_training_set.py`` only knew how to read
``/tmp/pixcull_demo/<run_id>/output/scores.csv`` (annotated demo
runs). The V18 5439-image background scan wrote slim per-folder JSONs
that dropped the feature vector — useless for axis retraining.
``scan_multi.py``'s V19.2 upgrade fixed the output side; this script
is the consumer.

How targets are derived
=======================
The scan didn't ask for human stars. We use the rule-stack ``decision``
(keep / maybe / cull) as a coarse warm-start label, mapped uniformly
across all 6 axes:

    keep  → 5★    (the rule stack found nothing wrong)
    maybe → 3★    (mid-tier; rule stack uncertain)
    cull  → 1★    (something is wrong)

This is the same coarse 5/3/1 mapping the existing goldenset
warm-start uses. Coarse but useful: the model still learns the
feature → quality direction even without per-axis annotations, and
the V18 scan brings in real face_count / face_max_blink / face_min_ear
which were entirely missing from the pre-V18 training set.

target_<axis>_source = "scan_v19_2" so future scripts (and the meta
JSON) can audit which rows came from this ingestion vs. human /
goldenset / auto.

Usage
=====
    python scripts/ingest_scan_to_axis_training.py \\
        /tmp/scan_v19_2/*.features.csv \\
        --training-csv training_axis.csv \\
        [--out training_axis.csv]   # default: in-place append
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from pixcull.scoring.rubric import RUBRIC_AXES

AXIS_NAMES = [a.name for a in RUBRIC_AXES]

# decision (rule-stack output) → coarse 5/3/1 stars across all axes.
# Mirrors how goldenset warm-start handles the keep/maybe/cull labels.
_DECISION_TO_STARS: dict[str, float] = {
    "keep":  5.0,
    "maybe": 3.0,
    "cull":  1.0,
}


def ingest_one_csv(scan_csv: Path, run_id: str) -> list[dict]:
    """Convert one features.csv from scan_multi into training rows."""
    df = pd.read_csv(scan_csv)
    rows: list[dict] = []
    for _, r in df.iterrows():
        dec = str(r.get("decision") or "").strip()
        stars = _DECISION_TO_STARS.get(dec)
        if stars is None:
            # Unknown decision token → skip this image; the rule-stack
            # always emits one of keep/maybe/cull, so this only fires
            # on a corrupted CSV.
            continue
        out: dict = {
            "filename": r["filename"],
            "_run_id":  run_id,
        }
        # Copy feature columns verbatim. Any column missing in the CSV
        # becomes NaN in the DataFrame, which the trainer handles via
        # the __missing indicator.
        for col in df.columns:
            if col in ("filename", "decision"):
                continue
            out[col] = r[col]
        # Apply the coarse target across all 6 axes
        for axis in AXIS_NAMES:
            out[f"target_{axis}"] = stars
            out[f"target_{axis}_source"] = "scan_v19_2"
        rows.append(out)
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scan_csvs", nargs="+", type=Path,
                    help="One or more <basename>.features.csv from scan_multi.py")
    p.add_argument("--training-csv", type=Path, default=Path("training_axis.csv"),
                    help="Existing training_axis.csv to extend (read-side)")
    p.add_argument("--out", type=Path, default=None,
                    help="Where to write the augmented CSV (default: overwrite "
                         "--training-csv in-place after backup)")
    p.add_argument("--dry-run", action="store_true",
                    help="Print what would change, don't write")
    args = p.parse_args()

    if not args.training_csv.exists():
        print(f"ERROR: {args.training_csv} not found", file=sys.stderr)
        return 2

    base = pd.read_csv(args.training_csv)
    n_base = len(base)
    print(f"baseline: {n_base} rows × {len(base.columns)} cols "
          f"({args.training_csv})")

    new_rows: list[dict] = []
    for csv_path in args.scan_csvs:
        if not csv_path.exists():
            print(f"  SKIP missing: {csv_path}")
            continue
        # V19.2 run-id pattern keeps each scan-folder distinct so
        # users can later filter / blame rows back to the folder.
        run_id = f"v19_2_{csv_path.stem.replace('.features', '')}"
        rows = ingest_one_csv(csv_path, run_id)
        print(f"  + {len(rows):4d} rows from {csv_path.name}  (run_id={run_id})")
        new_rows.extend(rows)

    if not new_rows:
        print("nothing to ingest.", file=sys.stderr)
        return 1

    add = pd.DataFrame(new_rows)
    # Align columns — add NaN for any column present in base but not in add
    # (and vice versa). pandas concat handles this with sort=False.
    merged = pd.concat([base, add], ignore_index=True, sort=False)

    # De-dup on (_run_id, filename) — re-ingesting the same scan should
    # not double-count rows. "last" wins so re-runs overwrite stale
    # feature values on the same image.
    if "_run_id" in merged.columns and "filename" in merged.columns:
        n_before = len(merged)
        merged = merged.drop_duplicates(
            subset=["_run_id", "filename"], keep="last"
        ).reset_index(drop=True)
        if n_before != len(merged):
            print(f"  dedup: dropped {n_before - len(merged)} duplicate rows")

    n_total = len(merged)
    n_added = n_total - n_base
    print(f"\n=== result: {n_base} → {n_total} (+{n_added})")
    print(f"  per-axis source breakdown after merge:")
    for axis in AXIS_NAMES:
        col = f"target_{axis}_source"
        if col not in merged.columns:
            continue
        vc = merged[col].value_counts(dropna=False)
        parts = ", ".join(f"{src}={n}" for src, n in vc.head(5).items())
        print(f"    {axis:12s}  {parts}")

    if args.dry_run:
        print("\n--dry-run: not writing.")
        return 0

    out = args.out or args.training_csv
    if out == args.training_csv:
        backup = args.training_csv.with_suffix(
            f".csv.bak.{int(time.time())}"
        )
        args.training_csv.rename(backup)
        print(f"  backed up old CSV → {backup}")
    merged.to_csv(out, index=False)
    print(f"  wrote {out}  ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
