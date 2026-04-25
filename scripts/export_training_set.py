"""Export per-image detector features + GT labels for training a learned head.

Motivation (V0.9, see `tests/fixtures/eval_findings.md`): rule-based accuracy
has plateaued at 66.4% exact / 87.5% within-one on the golden set. The three
V0.9 hypothesis tests (tighter face thresholds, landscape sibling-demote,
per-scene score_final tuning) all returned zero or negative signal — the
features we currently compute are *orthogonal* to subjective curation above
technical-quality gates. The rule-based loop cannot get further without
a learned component.

This script is the bridge to V1.0: given a golden-set dir with
`ground_truth.csv` + a run's `scores.csv`, emit a flat CSV with per-image
feature columns + `manual_label` ready for sklearn / pandas / pytorch.

Output schema (single CSV):
  filename              (string, join key)
  scene                 (categorical, pipeline-classified — use as feature
                         not as stratifier for CV; GT scene in a separate col)
  manual_label          (target: keep | maybe | cull)
  gt_scene              (from ground_truth.csv for reference only)
  plus ~20 numeric feature columns from the detector outputs

What's intentionally excluded: `decision`, `reason`, `flags`, `elapsed_s`,
`cluster_id`, and `scene_probs`. Decision+reason are what we're trying to
predict. Flags are deterministic from the numerics and would leak. cluster_id
is run-specific. scene_probs is a list-encoded string (if you want it, parse
it separately).

Usage:
    python scripts/export_training_set.py <golden_dir> <out_csv>

    python scripts/export_training_set.py tests/fixtures/ training.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

LABELS = ("keep", "maybe", "cull")

# Numeric per-image features worth handing to a learner. Any column we drop
# here is either (a) leakage from decision logic, (b) non-numeric and needs
# separate parsing, or (c) run-specific (cluster_id, elapsed_s).
FEATURE_COLS = [
    # sharpness
    "laplacian_global",
    "laplacian_subject",
    "face_region_lap_var",
    # exposure
    "mean_luma",
    "highlight_clip_pct",
    "shadow_clip_pct",
    # aesthetic
    "laion_aes",
    "clipiqa",
    # scene
    "scene_confidence",
    # face
    "face_count",
    "face_max_blink",
    "face_min_ear",
    # composition
    "horizon_tilt_deg",
    "rule_of_thirds_offset",
    "composition_score",
    # subject
    "subject_fraction",
    # fusion outputs — technically derivable from the above, but handy as
    # calibration inputs for a rescorer.
    "score_sharpness",
    "score_composition",
    "score_exposure",
    "score_aesthetic",
    "score_moment",
    "score_final",
]


def main(golden_dir: Path, out_csv: Path) -> None:
    gt_path = golden_dir / "ground_truth.csv"
    scores_path = golden_dir / "_eval_output" / "scores.csv"
    if not gt_path.exists():
        print(f"ERROR: {gt_path} not found", file=sys.stderr)
        sys.exit(2)
    if not scores_path.exists():
        print(
            f"ERROR: {scores_path} not found — run eval_on_golden_set.py first "
            f"so scores.csv exists.",
            file=sys.stderr,
        )
        sys.exit(2)

    gt = pd.read_csv(gt_path, comment="#")
    gt = gt[gt["manual_label"].isin(LABELS)].copy()
    gt = gt.rename(columns={"scene": "gt_scene"})

    scores = pd.read_csv(scores_path)

    missing_cols = [c for c in FEATURE_COLS if c not in scores.columns]
    if missing_cols:
        print(
            f"WARNING: {len(missing_cols)} feature columns missing from scores.csv: "
            f"{missing_cols} — run the current pipeline to refresh.",
            file=sys.stderr,
        )
    present_cols = [c for c in FEATURE_COLS if c in scores.columns]

    keep_cols = ["filename", "scene", *present_cols]
    merged = gt.merge(scores[keep_cols], on="filename", how="inner")

    # Reorder: id columns first, target next, features last
    out_cols = [
        "filename",
        "scene",        # pipeline-classified
        "gt_scene",     # photographer's folder tag
        "manual_label", # training target
        *present_cols,
    ]
    merged = merged[out_cols]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_csv, index=False)

    n = len(merged)
    print(f"Wrote {n} rows × {len(out_cols)} cols → {out_csv}")
    print("Label distribution:")
    print(merged["manual_label"].value_counts().to_string())
    print("\nScene distribution (pipeline-classified):")
    print(merged["scene"].value_counts().to_string())

    # Sanity: missing features per row?
    n_missing_feature = merged[present_cols].isna().any(axis=1).sum()
    if n_missing_feature:
        print(
            f"\nNote: {n_missing_feature}/{n} rows have at least one NaN feature "
            f"(e.g. face metrics on landscape shots). Imputation is the "
            f"consumer's call — a learner can use missingness as a feature."
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "usage: export_training_set.py <golden_dir> <out_csv>",
            file=sys.stderr,
        )
        sys.exit(1)
    main(Path(sys.argv[1]).expanduser().resolve(), Path(sys.argv[2]).expanduser().resolve())
