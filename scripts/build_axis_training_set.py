"""Walk all run dirs and assemble a per-axis training CSV.

This is the V2.1 training-data ingest. We pool every annotated run
the demo has produced, prefer human stars over auto stars on each
axis, and emit a flat CSV ready for ``train_axis_rescorers.py``.

Behavior
========
For each row in each run's ``scores.csv`` we emit:

  * The numeric features the rescorer learns from (same set V1.1
    used: laplacian_*, mean_luma, clipiqa, laion_aes, etc.)
  * Six target columns ``target_<axis>`` containing the stars to
    learn against, with a sibling ``target_<axis>_source`` column
    saying whether it was human-labeled or auto-decomposed.

Why pool runs across time
=========================
Each demo run produces an ``annotations.jsonl`` of human grades for
that batch only. A photographer building up labeled data over weeks
needs every annotation to count — not just the latest run. We walk
``_DEMO_ROOT/<run_id>/output/`` for every run on disk.

Privacy note
============
Filenames are kept in the CSV so debugging is easy, but no image
content or paths leave ``/tmp``. The training script doesn't reach
back to the originals.

Usage:
    python scripts/build_axis_training_set.py
        [--demo-root /tmp/pixcull_demo]
        [--out training_axis.csv]
        [--include-auto]   # default: only emit rows with at least
                           #          one human-labeled axis
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from pixcull.scoring.rubric import RUBRIC_AXES


# Same numeric feature set V1.1 used. Kept as a module constant so
# train_axis_rescorers.py imports the same list without drift.
FEATURE_COLS_NUMERIC = [
    # sharpness
    "laplacian_global", "laplacian_subject", "face_region_lap_var",
    # exposure
    "mean_luma", "highlight_clip_pct", "shadow_clip_pct",
    # aesthetic
    "laion_aes", "clipiqa",
    # scene confidence
    "scene_confidence",
    # face
    "face_count", "face_max_blink", "face_min_ear",
    # composition
    "horizon_tilt_deg", "rule_of_thirds_offset", "composition_score",
    # subject
    "subject_fraction",
    # fusion outputs
    "score_sharpness", "score_composition", "score_exposure",
    "score_aesthetic", "score_moment", "score_final",
]
FEATURE_COLS_CATEGORICAL = ["scene"]
AXIS_NAMES = [a.name for a in RUBRIC_AXES]


def _parse_annotations(ann_path: Path) -> dict[str, dict]:
    """Read annotations.jsonl, return {filename: latest_record}."""
    out: dict[str, dict] = {}
    if not ann_path.exists():
        return out
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
                out[fn] = rec  # later lines win
    return out


def _gather_run(run_dir: Path) -> list[dict]:
    """Pull one run's rows merged with annotations."""
    output = run_dir / "output"
    scores_path = output / "scores.csv"
    if not scores_path.exists():
        return []

    df = pd.read_csv(scores_path)
    human_by_fn = _parse_annotations(output / "annotations.jsonl")

    rows: list[dict] = []
    for _, r in df.iterrows():
        fn = str(r["filename"])
        # Start with all features the model expects
        out_row: dict[str, Any] = {"filename": fn, "_run_id": run_dir.name}
        for col in FEATURE_COLS_NUMERIC + FEATURE_COLS_CATEGORICAL:
            out_row[col] = r.get(col)

        # Per-axis target: prefer human, fall back to auto-decomposed
        # stars (which the orchestrator persisted as
        # ``rubric_<axis>_stars`` columns at the end of the run).
        human_axes = (human_by_fn.get(fn) or {}).get("axes") or {}
        for axis in AXIS_NAMES:
            human_stars = (human_axes.get(axis) or {}).get("stars")
            auto_stars = r.get(f"rubric_{axis}_stars")
            if human_stars is not None:
                out_row[f"target_{axis}"] = float(human_stars)
                out_row[f"target_{axis}_source"] = "human"
            elif auto_stars is not None and pd.notna(auto_stars):
                out_row[f"target_{axis}"] = float(auto_stars)
                out_row[f"target_{axis}_source"] = "auto"
            else:
                out_row[f"target_{axis}"] = None
                out_row[f"target_{axis}_source"] = None
        rows.append(out_row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo-root", type=Path,
                        default=Path("/tmp/pixcull_demo"),
                        help="Root of run dirs (default /tmp/pixcull_demo)")
    parser.add_argument("--out", type=Path,
                        default=Path("training_axis.csv"),
                        help="Output CSV path")
    parser.add_argument("--include-auto", action="store_true",
                        help="Include rows where ALL targets are auto. "
                             "Default: at least one axis must be human-labeled. "
                             "Use this for bootstrap (no annotations yet) — "
                             "the model will basically learn the check-list.")
    parser.add_argument("--also-from-goldenset",
                        type=Path, default=None,
                        help="Optional: also pull rows from a goldenset eval "
                             "output (path to <gs>/_eval_output/scores.csv). "
                             "The scene/manual_label from ground_truth.csv "
                             "drives all 6 axis targets at score_final's "
                             "level — coarse but useful as warm-start data.")
    args = parser.parse_args()

    demo_root = args.demo_root
    if not demo_root.exists():
        print(f"ERROR: demo root not found: {demo_root}", file=sys.stderr)
        return 2

    all_rows: list[dict] = []
    n_runs = 0
    n_runs_with_human = 0
    for run_dir in sorted(demo_root.iterdir()):
        if not run_dir.is_dir():
            continue
        if not (len(run_dir.name) == 10 and
                all(c in "0123456789abcdef" for c in run_dir.name)):
            continue
        rows = _gather_run(run_dir)
        if not rows:
            continue
        n_runs += 1
        had_human = any(
            any(r.get(f"target_{ax}_source") == "human" for ax in AXIS_NAMES)
            for r in rows
        )
        if had_human:
            n_runs_with_human += 1
        all_rows.extend(rows)

    if not all_rows:
        print(f"ERROR: no runs found under {demo_root}", file=sys.stderr)
        return 2

    df = pd.DataFrame(all_rows)

    # Optional: append goldenset rows for a warm-start when the demo
    # hasn't generated annotations yet. The goldenset gives us the
    # photographer's original keep/maybe/cull, which we map to a
    # uniform 5/3/1 ★ across all axes — coarse but consistent.
    if args.also_from_goldenset and args.also_from_goldenset.exists():
        gs_scores = pd.read_csv(args.also_from_goldenset)
        gt_path = args.also_from_goldenset.parent.parent / "ground_truth.csv"
        if gt_path.exists():
            gt = pd.read_csv(gt_path, comment="#")
            gt = gt[gt["manual_label"].isin(["keep", "maybe", "cull"])]
            merged = gs_scores.merge(
                gt[["filename", "manual_label"]],
                on="filename",
                how="inner",
            )
            label_to_stars = {"keep": 5.0, "maybe": 3.0, "cull": 1.0}
            for _, r in merged.iterrows():
                fallback = label_to_stars.get(r["manual_label"], 3.0)
                row: dict[str, Any] = {
                    "filename": r["filename"],
                    "_run_id": "goldenset_warmstart",
                }
                for col in FEATURE_COLS_NUMERIC + FEATURE_COLS_CATEGORICAL:
                    row[col] = r.get(col)
                # Prefer per-axis rubric stars from V2.0+ pipeline runs
                # (rubric_<axis>_stars columns). Fall back to coarse
                # 5/3/1 only when the column is missing or NaN — that
                # gives the model real per-axis variance even with
                # warm-start data.
                for axis in AXIS_NAMES:
                    auto_v = r.get(f"rubric_{axis}_stars")
                    if pd.notna(auto_v):
                        row[f"target_{axis}"] = float(auto_v)
                        row[f"target_{axis}_source"] = "goldenset_v2"
                    else:
                        row[f"target_{axis}"] = fallback
                        row[f"target_{axis}_source"] = "goldenset"
                all_rows.append(row)
            df = pd.DataFrame(all_rows)
            print(f"  + {len(merged)} rows from goldenset warm-start")

    # Filter: by default keep only rows that have at least one human label
    if not args.include_auto:
        human_mask = pd.Series(False, index=df.index)
        for axis in AXIS_NAMES:
            human_mask |= (df[f"target_{axis}_source"] == "human")
        df_filt = df[human_mask]
        print(f"  filtered: {len(df_filt)} / {len(df)} rows have ≥1 human axis")
        df = df_filt

    if df.empty:
        print(
            "WARNING: 0 rows after filtering. Either:\n"
            "  - no annotations have been saved yet → run --include-auto\n"
            "  - or use --also-from-goldenset to bootstrap from the \n"
            "    goldenset eval output.",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    print(f"\n=== Wrote {len(df)} rows × {len(df.columns)} cols → {args.out}")
    print(f"  runs scanned: {n_runs}  (with human labels: {n_runs_with_human})")
    print("\n  per-axis label coverage:")
    print(f"    {'axis':12s}  {'total':>6s}  {'human':>6s}  {'auto':>6s}  {'gs_v2':>6s}  {'gs':>6s}")
    for axis in AXIS_NAMES:
        col = f"target_{axis}_source"
        n_total = df[f"target_{axis}"].notna().sum()
        n_human = (df[col] == "human").sum()
        n_auto = (df[col] == "auto").sum()
        n_gs_v2 = (df[col] == "goldenset_v2").sum()
        n_gs = (df[col] == "goldenset").sum()
        print(f"    {axis:12s}  {n_total:6d}  {n_human:6d}  {n_auto:6d}  "
              f"{n_gs_v2:6d}  {n_gs:6d}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
