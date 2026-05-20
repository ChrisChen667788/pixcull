"""P-CORE-1 — aggregate every annotations.jsonl across all runs into a
single training_v2.csv, then ``train_rescorer.py training_v2.csv …``.

The historical training.csv has 130 hand-labeled rows. As the user
runs PixCull on real shoots and hand-annotates frames (via the
1/2/3 quick-label or the rubric modal), each annotation lands in
that run's ``output/annotations.jsonl``. This script reaps those
annotations + joins them against the run's scores.csv feature
columns to produce a unified retraining input.

Usage:
    python scripts/aggregate_annotations.py \\
        --demo-root /tmp/pixcull_demo \\
        --golden    training.csv \\
        --output    training_v2.csv \\
        --min-confidence  3        # default: include all human labels

The output schema matches training.csv exactly so train_rescorer.py
can consume it without modification. Adds two columns:
  ``source_run``   — which run this row came from (for stratified CV)
  ``ann_timestamp`` — when the user labeled (for time-aware splits)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def _latest_annotations(ann_path: Path) -> dict[str, dict]:
    """Reduce an annotations.jsonl to {filename: latest_record}."""
    latest: dict[str, dict] = {}
    try:
        with open(ann_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fn = rec.get("filename")
                if fn:
                    latest[fn] = rec
    except OSError:
        pass
    return latest


def _scores_by_filename(csv_path: Path) -> dict[str, dict]:
    """Load scores.csv into {filename: row_dict}."""
    out: dict[str, dict] = {}
    if not csv_path.is_file():
        return out
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fn = (row.get("filename") or "").strip()
                if fn:
                    out[fn] = row
    except OSError:
        pass
    return out


def aggregate(
    demo_root: Path,
    golden: Path | None = None,
) -> tuple[list[dict], list[str]]:
    """Walk every run, join annotations with scores.csv rows.

    Returns ``(rows, columns)``. Rows are dicts; columns is the
    union of all source headers (so writer can DictWrite cleanly).
    """
    rows: list[dict] = []
    columns: list[str] = []
    columns_set: set[str] = set()

    def _extend_cols(headers):
        for h in headers:
            if h not in columns_set:
                columns.append(h); columns_set.add(h)

    # 1. Seed with the historical golden set (training.csv)
    if golden and golden.is_file():
        with open(golden, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            _extend_cols(reader.fieldnames or [])
            for row in reader:
                row["source_run"] = "_golden"
                row["ann_timestamp"] = ""
                rows.append(row)
        _extend_cols(["source_run", "ann_timestamp"])

    # 2. Walk every run dir
    for run_dir in sorted(demo_root.glob("*/")):
        run_id = run_dir.name
        ann_path = run_dir / "output" / "annotations.jsonl"
        scores_path = run_dir / "output" / "scores.csv"
        if not ann_path.is_file() or not scores_path.is_file():
            continue

        latest = _latest_annotations(ann_path)
        if not latest:
            continue
        scores = _scores_by_filename(scores_path)
        if not scores:
            continue

        for fn, ann in latest.items():
            label = str(ann.get("overall_label", "")).strip().lower()
            if label not in ("keep", "maybe", "cull"):
                continue
            row = scores.get(fn)
            if row is None:
                continue
            # Overlay human verdict + reason on the scoring features.
            # train_rescorer expects "manual_label" (per the golden
            # set's convention); add it as a top-level field.
            row = dict(row)
            row["manual_label"] = label
            row["cull_reason"] = ann.get("cull_reason", "") or ""
            row["source_run"] = run_id
            row["ann_timestamp"] = str(ann.get("timestamp", "") or "")
            # Capture per-axis human stars when the user used the
            # rubric modal (axes dict has stars per axis); train_v2
            # can use these as supervision for axis-specific heads.
            axes_obj = ann.get("axes") or {}
            for axis_name, ax in axes_obj.items():
                if isinstance(ax, dict) and ax.get("stars") is not None:
                    row[f"human_{axis_name}_stars"] = str(ax["stars"])
            _extend_cols(row.keys())
            rows.append(row)
    return rows, columns


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo-root", type=Path,
                     default=Path("/tmp/pixcull_demo"),
                     help="root containing <run_id>/output/ subdirs")
    ap.add_argument("--golden", type=Path,
                     default=Path("training.csv"),
                     help="historical golden-set CSV to seed with")
    ap.add_argument("--output", type=Path, default=Path("training_v2.csv"),
                     help="path to write the aggregated CSV")
    ap.add_argument("--min-rows", type=int, default=50,
                     help="warn if total < this many rows")
    args = ap.parse_args(argv)

    rows, columns = aggregate(args.demo_root, args.golden)
    if not rows:
        print(f"WARN: no annotated rows found under {args.demo_root}",
              file=sys.stderr)
        return 1
    if len(rows) < args.min_rows:
        print(f"WARN: only {len(rows)} rows aggregated, < --min-rows "
              f"({args.min_rows}). Rescorer V2 retrain may not be useful "
              f"yet — keep labeling more frames.", file=sys.stderr)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    # Quick summary
    from collections import Counter
    src = Counter(r.get("source_run", "?") for r in rows)
    lbl = Counter(r.get("manual_label") or r.get("decision") or "?" for r in rows)
    print(f"wrote {args.output}  rows={len(rows)} cols={len(columns)}")
    print(f"  by source_run: {dict(src.most_common(10))}")
    print(f"  by label:      {dict(lbl)}")
    if len(rows) >= args.min_rows:
        print("\nNext step:")
        print(f"  python scripts/train_rescorer.py {args.output} "
              "models/rescorer_v2.joblib --cv 10 --model gbm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
