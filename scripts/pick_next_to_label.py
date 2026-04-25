"""Pick the next N photos to label, optimised for filling per-scene gaps.

V1.1 iteration 1 concluded the rescorer ceiling on 128 samples is data,
specifically per-scene maybe coverage. Naively random-sampling the user's
catalog for more labels wastes effort — most photos in any catalog are
confident keeps; they'd bulk up the majority class without helping the
keep/maybe boundary at all. The shortfall is in the tail cells; on the
current 128-row fixture golden set the biggest gaps (after scene-name
normalisation) are:

  - landscape maybe (currently  1 → target ≥ 30)
  - landscape keep  (currently  7 → target ≥ 40)
  - street   keep   (currently  5 → target ≥ 25)
  - event    cull   (currently  2 → target ≥ 15)
  - wildlife anything (currently 1 keep / 0 else → target ≥ 20 keep)

This script reads a catalog-scale `scores.csv` (output of `pixcull` run on
the full photo library) plus the current `ground_truth.csv`, identifies the
under-represented (scene, label-band) cells, and picks candidates whose
pipeline-predicted score puts them in the relevant band. It does NOT assign
labels — that would bias the golden set — it just prioritises which photos
the user should review next.

Output:
  - stdout report: per-cell current count, target, and picks
  - optional `--out-csv`: flat CSV ready to append to ground_truth.csv
    (leaves manual_label blank — user fills during review)

Usage:
    # Demo on the existing fixtures (not a real catalog, but proves the wiring)
    python scripts/pick_next_to_label.py \\
        tests/fixtures/_eval_output/scores.csv \\
        tests/fixtures/ground_truth.csv \\
        --n 40

    # Real labelling queue against the user's personal catalog run
    python scripts/pick_next_to_label.py \\
        ~/Pictures/catalog_eval/scores.csv \\
        tests/fixtures/ground_truth.csv \\
        --n 100 --out-csv to_label.csv
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Per-cell labelling targets, informed by the V1.1 error-slice analysis.
# "maybe" and "cull" cells are where the rule stack is blind — that's where
# new labels yield the most learning signal per sample reviewed.
#
# Targets are calibrated for a 500-sample V1.2 push; scale linearly if you're
# pushing further. Landscape-maybe is the single highest-ROI cell because
# the rescorer's landscape accuracy is 0.560 (effectively random) in V1.1.
_TARGETS = {
    # scene        keep   maybe   cull
    "landscape":  ( 40,    30,     20),
    "portrait":   ( 40,    25,     20),
    "stilllife":  ( 35,    20,     15),
    "event":      ( 30,    20,     15),
    "street":     ( 25,    15,     10),
    "architecture":( 25,   15,     10),
    "wildlife":   ( 20,    10,     10),
}

# Rule-score bands we sample from when filling each label cell. Score is
# on [0,1]; these mirror the strictness='standard' thresholds in the
# pipeline (keep ≥ 0.65, cull ≤ 0.40, maybe in between).
_BANDS = {
    "keep":  (0.65, 1.01),
    "maybe": (0.40, 0.65),
    "cull":  (0.00, 0.40),
}


@dataclass
class Cell:
    scene: str
    label: str
    current: int
    target: int
    shortfall: int


def tally_current(gt: pd.DataFrame) -> dict[tuple[str, str], int]:
    return (
        gt.groupby(["scene", "manual_label"]).size().to_dict()
    )


def find_gaps(gt: pd.DataFrame) -> list[Cell]:
    tally = tally_current(gt)
    gaps: list[Cell] = []
    for scene, (k, m, c) in _TARGETS.items():
        for label, target in (("keep", k), ("maybe", m), ("cull", c)):
            current = tally.get((scene, label), 0)
            short = target - current
            gaps.append(Cell(scene, label, current, target, short))
    return sorted(gaps, key=lambda g: -g.shortfall)


def pick_candidates(
    scores: pd.DataFrame,
    already_labeled: set[str],
    cell: Cell,
    max_picks: int,
) -> pd.DataFrame:
    """Pick up to `max_picks` unlabeled rows in the (scene, band) slice.

    Ranking strategy: within the target score band, take samples closest to
    the band midpoint first — they're the least-certain cases and the most
    informative to label. Uncertainty sampling from the pipeline's point of
    view.
    """
    lo, hi = _BANDS[cell.label]
    pool = scores[
        (scores["scene"] == cell.scene)
        & (scores["score_final"] >= lo)
        & (scores["score_final"] < hi)
        & (~scores["filename"].isin(already_labeled))
    ].copy()
    if pool.empty:
        return pool
    mid = (lo + hi) / 2
    pool["_dist_to_mid"] = (pool["score_final"] - mid).abs()
    return pool.nsmallest(max_picks, "_dist_to_mid")


def allocate_budget(gaps: list[Cell], n: int) -> dict[tuple[str, str], int]:
    """Split a total budget of N picks across the shortfall cells.

    Proportional-to-shortfall with a floor of 0. Cells already at target get
    zero budget.
    """
    positives = [g for g in gaps if g.shortfall > 0]
    if not positives:
        return {}
    total_short = sum(g.shortfall for g in positives)
    out: dict[tuple[str, str], int] = {}
    remaining = n
    for i, g in enumerate(positives):
        if i == len(positives) - 1:
            # Last cell gets the rounding remainder
            out[(g.scene, g.label)] = max(0, remaining)
        else:
            take = min(g.shortfall, round(n * g.shortfall / total_short))
            out[(g.scene, g.label)] = take
            remaining -= take
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("scores_csv", type=Path,
                    help="Pipeline scores.csv (any catalog — fixtures or user-run)")
    ap.add_argument("gt_csv", type=Path,
                    help="ground_truth.csv with existing manual_label column")
    ap.add_argument("--n", type=int, default=50,
                    help="Total photos to suggest (default: 50)")
    ap.add_argument("--out-csv", type=Path,
                    help="If given, write a CSV of picks (filename,scene,suggested_band)")
    args = ap.parse_args()

    if not args.scores_csv.exists():
        sys.exit(f"ERROR: {args.scores_csv} not found")
    if not args.gt_csv.exists():
        sys.exit(f"ERROR: {args.gt_csv} not found")

    scores = pd.read_csv(args.scores_csv)
    gt = pd.read_csv(args.gt_csv, comment="#")

    # Normalise: the golden-set ground_truth uses `scene` for GT scene, but
    # the pipeline scores.csv also uses `scene` for the pipeline-classified
    # scene. We want to sample against the pipeline scene (what we'll see
    # when running on an unlabeled catalog).
    already_labeled = set(
        gt.loc[gt["manual_label"].isin(("keep", "maybe", "cull")), "filename"]
    )

    gaps = find_gaps(gt.rename(columns={"scene": "scene"}))
    positive = [g for g in gaps if g.shortfall > 0]

    print(f"Catalog scores: {len(scores):,} rows from {args.scores_csv.name}")
    print(f"Existing labels: {len(already_labeled):,} from {args.gt_csv.name}")
    print()
    print(f"{'scene':<14s} {'label':<7s} {'current':>8s} {'target':>7s} {'short':>6s}")
    for g in gaps:
        marker = " •" if g.shortfall > 0 else ""
        print(f"{g.scene:<14s} {g.label:<7s} {g.current:>8d} {g.target:>7d} "
              f"{g.shortfall:>6d}{marker}")
    total_short = sum(g.shortfall for g in positive)
    print(f"\nTotal shortfall across cells: {total_short}")
    print(f"Requested picks: {args.n}  (will prioritise largest gaps first)")
    print()

    budget = allocate_budget(gaps, args.n)
    picks_by_cell: list[tuple[Cell, pd.DataFrame]] = []
    for g in positive:
        want = budget.get((g.scene, g.label), 0)
        if want <= 0:
            continue
        picked = pick_candidates(scores, already_labeled, g, want)
        if picked.empty:
            continue
        picks_by_cell.append((g, picked))

    print(f"{'scene':<14s} {'target':<7s} {'picks':>6s}   top 3 filenames")
    print("-" * 78)
    total_picked = 0
    for g, picks in picks_by_cell:
        preview = " ".join(picks["filename"].head(3).tolist())
        print(f"{g.scene:<14s} {g.label:<7s} {len(picks):>6d}   {preview}")
        total_picked += len(picks)
    print(f"\nPicked {total_picked} of {args.n} requested")
    empty_cells = [(g.scene, g.label) for g in positive
                   if g.shortfall > 0 and (g.scene, g.label) not in {
                       (c.scene, c.label) for c, _ in picks_by_cell}]
    if empty_cells:
        print(f"NOTE: {len(empty_cells)} cell(s) had no matching candidates in "
              f"the catalog:")
        for s, l in empty_cells:
            print(f"       - {s} {l}  (band empty; catalog doesn't contain "
                  f"rule-scored matches)")

    if args.out_csv:
        out_rows = []
        for g, picks in picks_by_cell:
            for _, row in picks.iterrows():
                out_rows.append({
                    "filename": row["filename"],
                    "scene": g.scene,
                    "suggested_band": g.label,
                    "score_final": round(float(row["score_final"]), 3),
                    "manual_label": "",  # user fills during review
                    "notes": "",
                })
        out_df = pd.DataFrame(out_rows)
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        out_df.to_csv(args.out_csv, index=False)
        print(f"\nWrote {len(out_df)} picks → {args.out_csv}")
        print("Next: open each in the review viewer, set manual_label, then "
              "append to ground_truth.csv and re-run train_rescorer.py.")


if __name__ == "__main__":
    main()
