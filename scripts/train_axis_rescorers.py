"""V2.1 multi-axis rescorer trainer.

Reads the flat CSV that ``build_axis_training_set.py`` emits and
trains one HistGradientBoostingRegressor per axis. Each axis writes
its own joblib so the runtime can hot-swap individual axes without
retraining the whole stack.

Why per-axis regressors instead of one multi-output model
=========================================================
* Individual axes are missing data at different rates (e.g. ``moment``
  needs face features that may be absent). A multi-output model would
  drop a row from ALL axes the moment one was unrated. Independent
  models keep ``aesthetic`` data even when ``moment`` is missing.
* Audit + retraining are simpler: "the light axis seems off" → retrain
  just the light model, leave the others alone.
* CV scoring is straightforward; multi-output joint metrics get fuzzy.

Usage:
    python scripts/train_axis_rescorers.py training_axis.csv
        [--out-dir models/]
        [--cv 5]
        [--seed 42]
        [--min-rows 30]    # axes with fewer rows are skipped (warning)

Run with ``--bootstrap`` to skip the human-label requirement and use
auto stars (good for first-time setup before any human annotations).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.axis_rescorer import axis_meta_path, axis_model_path

# Imports kept lazy where possible; sklearn is heavy.

AXIS_NAMES = [a.name for a in RUBRIC_AXES]


def build_feature_matrix(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Same feature schema as V1.1's ``build_feature_matrix``.

    Returns (X, numeric_cols, categorical_cols). The numeric columns
    plus their ``__missing`` indicators plus the categorical column
    is the canonical schema. Both the trainer and the runtime use
    this exact list — single source of truth via the script itself.
    """
    from scripts.build_axis_training_set import (
        FEATURE_COLS_NUMERIC,
        FEATURE_COLS_CATEGORICAL,
    )

    numeric_present = [c for c in FEATURE_COLS_NUMERIC if c in df.columns]
    cat_present = [c for c in FEATURE_COLS_CATEGORICAL if c in df.columns]

    X = df[numeric_present + cat_present].copy()

    # Add __missing indicators for every numeric column that has any
    # NaN in the training set. This is the V1.1 trick: missingness
    # itself can be informative (face features absent on landscape →
    # signal that this is a non-portrait shot).
    indicators_added = []
    for col in numeric_present:
        if X[col].isna().any():
            X[f"{col}__missing"] = X[col].isna().astype(int)
            indicators_added.append(f"{col}__missing")

    return X, numeric_present + indicators_added, cat_present


def build_pipeline(numeric_cols: list[str], cat_cols: list[str], seed: int):
    """Standardize-impute-onehot → HistGBM. Same skeleton across axes."""
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    pre = ColumnTransformer(
        transformers=[
            ("num", Pipeline([
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
            ]), numeric_cols),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             cat_cols),
        ],
        remainder="drop",
    )
    clf = HistGradientBoostingRegressor(
        max_depth=4,
        max_iter=200,
        learning_rate=0.06,
        l2_regularization=0.5,
        random_state=seed,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


def train_one_axis(
    df: pd.DataFrame,
    axis: str,
    out_dir: Path,
    cv: int,
    seed: int,
    min_rows: int,
) -> dict[str, Any] | None:
    """Train one axis worth of model and persist the joblib.

    Returns metadata dict, or None if training was skipped (too few rows).
    """
    target_col = f"target_{axis}"
    src_col = f"target_{axis}_source"
    if target_col not in df.columns:
        return None

    rated = df[df[target_col].notna()].copy()
    if len(rated) < min_rows:
        print(f"  [{axis:12s}] skipped — only {len(rated)} labeled rows "
              f"(min {min_rows})")
        return None

    n_human = int((rated[src_col] == "human").sum()) if src_col in rated.columns else 0

    X, num_cols, cat_cols = build_feature_matrix(rated)
    feature_cols = list(X.columns)  # canonical order incl. __missing
    y = rated[target_col].astype(float).values

    from sklearn.model_selection import KFold, cross_val_score

    pipeline = build_pipeline(num_cols, cat_cols, seed)
    kf = KFold(n_splits=min(cv, len(rated)), shuffle=True, random_state=seed)
    r2 = cross_val_score(pipeline, X, y, cv=kf, scoring="r2").mean()
    mae = -cross_val_score(
        pipeline, X, y, cv=kf, scoring="neg_mean_absolute_error"
    ).mean()
    pipeline.fit(X, y)

    # Persist
    import joblib
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = {
        "pipeline": pipeline,
        "feature_cols": feature_cols,
        "cv_r2": float(r2),
        "cv_mae": float(mae),
        "train_rows": len(rated),
        "n_human_targets": n_human,
        "target_axis": axis,
    }
    joblib.dump(artifact, axis_model_path(out_dir, axis))

    return {
        "axis": axis,
        "rows": len(rated),
        "n_human": n_human,
        "cv_r2": round(float(r2), 3),
        "cv_mae": round(float(mae), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="V2.1 per-axis rescorer trainer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("training_csv", type=Path,
                        help="Output of build_axis_training_set.py")
    parser.add_argument("--out-dir", type=Path, default=Path("models"),
                        help="Where to write rescorer_axis_<name>.joblib")
    parser.add_argument("--cv", type=int, default=5,
                        help="K for K-fold CV (default 5)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-rows", type=int, default=30,
                        help="Skip an axis if it has fewer labeled rows.")
    parser.add_argument("--axes", default=None,
                        help="Comma-separated axis subset (default: all 6)")
    args = parser.parse_args()

    if not args.training_csv.exists():
        print(f"ERROR: {args.training_csv} not found", file=sys.stderr)
        return 2

    df = pd.read_csv(args.training_csv)
    print(f"Loaded {len(df)} rows from {args.training_csv}")

    target_axes = (
        [a.strip() for a in args.axes.split(",") if a.strip()]
        if args.axes
        else AXIS_NAMES
    )

    print(f"\n{'=' * 64}")
    print(f"  V2.1 per-axis rescorer training · seed={args.seed} cv={args.cv}")
    print("=" * 64)
    print(f"  {'axis':12s}  {'rows':>6s}  {'human':>6s}  {'CV R²':>7s}  "
          f"{'CV MAE':>7s}")
    print("  " + "-" * 50)

    summaries: list[dict[str, Any]] = []
    for axis in target_axes:
        result = train_one_axis(
            df, axis, args.out_dir, args.cv, args.seed, args.min_rows
        )
        if result is None:
            continue
        summaries.append(result)
        print(f"  {result['axis']:12s}  {result['rows']:6d}  "
              f"{result['n_human']:6d}  {result['cv_r2']:7.3f}  "
              f"{result['cv_mae']:7.3f}")

    # Persist meta JSON for the demo's /retrain endpoint to display
    meta = {
        "created_at": pd.Timestamp.utcnow().isoformat() + "Z",
        "training_csv": str(args.training_csv.resolve()),
        "n_rows_in_csv": len(df),
        "axes": summaries,
        "seed": args.seed,
        "cv": args.cv,
    }
    axis_meta_path(args.out_dir).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n  Saved:")
    for s in summaries:
        out = args.out_dir / f"rescorer_axis_{s['axis']}.joblib"
        print(f"    {out}  ({out.stat().st_size // 1024} KB)")
    print(f"    {axis_meta_path(args.out_dir)}")

    if not summaries:
        print("\nWARNING: no axes trained. Annotate more or pass "
              "--min-rows lower.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
