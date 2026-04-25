"""Sanity-check sweep: does ANY model learn keep/maybe at 128 samples?

V1.1 iteration 1 (see eval_findings.md): LR rescorer CV-lost to the rule
baseline (0.625 vs 0.738) with AUC 0.546. Before concluding "data-limited,
not model-limited" we need to rule out the mundane explanation: LR is just
the wrong model for these features.

This script runs the same CV protocol across logistic regression, histogram
gradient boosting, and random forest. If all three sit in the same AUC band
(0.50 ± 0.10), the ceiling is sample count, not model choice. If one clearly
breaks away, we switch defaults before shipping V1.1.

Not a permanent tool — delete once the answer is recorded in eval_findings.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# Reuse the feature list from train_rescorer.py — same signal, different heads.
sys.path.insert(0, str(Path(__file__).parent))
from train_rescorer import (  # type: ignore
    _MISSING_SIGNAL_COLS, _NUMERIC_FEATURES, _FUSION_FEATURES,
    _CATEGORICAL_FEATURES, build_feature_matrix,
)


def build_head(name: str, numeric_cols, categorical_cols):
    """Swap the classifier; keep identical preprocessing."""
    num = Pipeline([("impute", SimpleImputer(strategy="median")),
                    ("scale",  StandardScaler())])
    pre = ColumnTransformer([
        ("num", num, numeric_cols),
        ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols),
    ])
    if name == "lr":
        clf = LogisticRegression(class_weight="balanced", max_iter=1000, C=1.0)
    elif name == "gbm":
        # HGB handles NaNs natively, but we keep the imputer for apples-to-apples.
        clf = HistGradientBoostingClassifier(
            max_iter=200, max_depth=3, learning_rate=0.05,
            class_weight="balanced", random_state=42,
        )
    elif name == "rf":
        clf = RandomForestClassifier(
            n_estimators=400, max_depth=6, min_samples_leaf=3,
            class_weight="balanced", n_jobs=-1, random_state=42,
        )
    else:
        raise ValueError(name)
    return Pipeline([("pre", pre), ("clf", clf)])


def main() -> None:
    path = Path("training.csv")
    if not path.exists():
        sys.exit("ERROR: training.csv not found. Run export_training_set.py first.")

    raw = pd.read_csv(path)
    sub = raw[raw["manual_label"].isin(["keep", "maybe"])].copy()
    df, feature_cols = build_feature_matrix(sub)
    numeric_cols = [c for c in feature_cols if c != "scene"]
    categorical_cols = ["scene"]
    X = df[feature_cols]
    y = (df["manual_label"] == "keep").astype(int).values
    scenes = df["scene"].fillna("unknown")

    n_keep = int(y.sum()); n_maybe = int((1 - y).sum())
    print(f"Sweep on {len(sub)} keep/maybe rows (keep={n_keep} maybe={n_maybe})")
    print(f"Baseline trivial: always-keep → acc = {n_keep/len(sub):.3f}")
    print()
    print(f"  {'model':<6s} {'acc':>6s} {'AUC':>6s} {'keep_R':>7s} {'maybe_R':>8s}")

    results: dict[str, dict[str, float]] = {}
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    for name in ("lr", "gbm", "rf"):
        pipe = build_head(name, numeric_cols, categorical_cols)
        yp = cross_val_predict(pipe, X, y, cv=skf, n_jobs=-1)
        yq = cross_val_predict(pipe, X, y, cv=skf, n_jobs=-1, method="predict_proba")[:, 1]
        acc = (yp == y).mean()
        try:
            auc = roc_auc_score(y, yq)
        except ValueError:
            auc = float("nan")
        keep_R = (yp[y == 1] == 1).mean()
        maybe_R = (yp[y == 0] == 0).mean()
        results[name] = {"acc": acc, "auc": auc, "keep_R": keep_R, "maybe_R": maybe_R}
        print(f"  {name:<6s} {acc:>6.3f} {auc:>6.3f} {keep_R:>7.3f} {maybe_R:>8.3f}")

    print()
    # Landscape-only check: only scene with enough maybe for within-scene CV
    ls_mask = (scenes == "landscape").values
    if ls_mask.sum() >= 10:
        print(f"Landscape-only subset ({int(ls_mask.sum())} rows, "
              f"{int(y[ls_mask].sum())} keep / {int((1-y[ls_mask]).sum())} maybe):")
        for name in ("lr", "gbm", "rf"):
            pipe = build_head(name, numeric_cols, categorical_cols)
            # Can't use 5-fold on 25 rows with 11 maybes — use 3-fold.
            skf_ls = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
            yp = cross_val_predict(pipe, X.iloc[ls_mask], y[ls_mask],
                                   cv=skf_ls, n_jobs=-1)
            try:
                yq = cross_val_predict(pipe, X.iloc[ls_mask], y[ls_mask],
                                       cv=skf_ls, n_jobs=-1,
                                       method="predict_proba")[:, 1]
                auc = roc_auc_score(y[ls_mask], yq)
            except (ValueError, IndexError):
                auc = float("nan")
            acc = (yp == y[ls_mask]).mean()
            print(f"  {name:<6s} acc={acc:.3f}  AUC={auc:.3f}")
    print()

    aucs = [results[n]["auc"] for n in ("lr", "gbm", "rf")]
    spread = max(aucs) - min(aucs)
    print("=" * 62)
    if spread < 0.1:
        print(f"  All three AUCs within {spread:.3f} → signal ceiling is DATA, "
              f"not model choice.")
    else:
        winner = max(("lr", "gbm", "rf"), key=lambda n: results[n]["auc"])
        print(f"  AUC spread {spread:.3f}; best = {winner} "
              f"(AUC {results[winner]['auc']:.3f})")
    print("=" * 62)


if __name__ == "__main__":
    main()
