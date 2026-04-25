"""Train the V1.1 learned rescorer on top of the V0.8 rule stack.

Why (see eval_findings.md §V0.9): the rule stack plateaued at 66.4% exact /
87.5% within-one on the 128-photo golden set. Three hypothesis tests in V0.9
confirmed the remaining errors are subjective-curation mistakes, *not* missing
technical-quality signal. The V1.0 path is learning the keep/maybe boundary
that rules can't capture.

Scope: this rescorer only decides **keep vs maybe**, never cull. Hard-cull
flags (cull precision 0.90 in V0.8) stay rule-based — that's the part the rule
layer is good at. The rescorer only runs on rows the rule stack did not cull.

Target: binary — manual_label == 'keep' (1) vs 'maybe' (0). Rows with
manual_label == 'cull' are excluded; so are rows with decision == 'cull'
at inference time.

Honest caveats on 128 samples:
  - Only landscape (14 keep / 11 maybe) has per-scene maybe signal.
    stilllife (22/1), event (19/2), street (5/1), wildlife (2/1) are too
    sparse for scene-conditional learning. We therefore train ONE global
    model and include `scene` as a one-hot feature — cross-scene transfer
    is what we're banking on at this sample size.
  - 123/128 rows have ≥ 1 NaN feature (face metrics only fire on portrait,
    horizon_tilt on outdoor scenes). We impute with median + add a
    missing-indicator column so the model can learn "face signal absent"
    is itself scene-informative.
  - Class balance is 84:20 (keep:maybe) → `class_weight='balanced'` in LR.

Usage:
    python scripts/train_rescorer.py training.csv models/rescorer_v1.joblib

    # Smaller output (no joblib save) for hyperparameter scans:
    python scripts/train_rescorer.py training.csv - --cv 5

Output:
  - `models/rescorer_v1.joblib` — sklearn Pipeline (Imputer + Scaler + LR)
  - stdout report: CV accuracy/AUC mean±std, per-scene breakdown, vs.
    rule baseline on the same rows.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# These columns are "scene-conditional missing": NaN carries signal (the
# detector didn't fire because the shot is non-portrait / no horizon). We add
# a missing-indicator sibling feature for each, so the model can distinguish
# "low value" from "absent" — these turned out to be among the more
# informative features in the GBM sweep (2025-04, 128 samples).
_MISSING_SIGNAL_COLS = ("face_min_ear", "face_max_blink", "horizon_tilt_deg")

# Numeric detector features. Excludes fusion outputs (score_*) to avoid
# leaking the rule-based decision into the learner — we want the rescorer
# to learn a *different* function, not memorise what the rule stack does.
#
# `face_region_lap_var` is dropped: 121/128 NaN, and some stratified CV folds
# end up with zero non-NaN values → imputation warning + zero signal. Revisit
# once portrait label count grows past ~80 (then the column will be non-NaN
# on more than a handful of rows).
_NUMERIC_FEATURES = [
    "laplacian_global",
    "laplacian_subject",
    "mean_luma",
    "highlight_clip_pct",
    "shadow_clip_pct",
    "laion_aes",
    "clipiqa",
    "scene_confidence",
    "face_count",
    "face_max_blink",
    "face_min_ear",
    "horizon_tilt_deg",
    "rule_of_thirds_offset",
    "composition_score",
    "subject_fraction",
]

# Fusion scores — included as a separate optional block. A fair rescorer
# should *add* information over `score_final`; if the learner only uses
# score_final, it's re-learning the rule stack and we've gained nothing.
# We train WITH these, but also report the delta vs. a simple score_final
# threshold to sanity-check the learner isn't just echoing rules.
_FUSION_FEATURES = [
    "score_sharpness",
    "score_composition",
    "score_exposure",
    "score_aesthetic",
    "score_final",
]

_CATEGORICAL_FEATURES = ["scene"]


def build_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Attach missing-indicator siblings for scene-conditional NaN columns.

    Returns (augmented df, full feature list).
    """
    df = df.copy()
    added = []
    for col in _MISSING_SIGNAL_COLS:
        if col in df.columns:
            ind = f"{col}__missing"
            df[ind] = df[col].isna().astype(int)
            added.append(ind)
    feature_cols = _NUMERIC_FEATURES + _FUSION_FEATURES + added + _CATEGORICAL_FEATURES
    present = [c for c in feature_cols if c in df.columns]
    missing = set(feature_cols) - set(present)
    if missing:
        print(f"WARNING: missing feature columns: {sorted(missing)}", file=sys.stderr)
    return df, present


def build_pipeline(
    numeric_cols: list[str],
    categorical_cols: list[str],
    model: str = "gbm",
) -> Pipeline:
    """Imputer + scaler on numerics, one-hot on scene, class-balanced head.

    Default is histogram gradient boosting: the scripts/compare_rescorers.py
    sweep on 128 samples showed GBM captures feature × scene interactions
    that a linear model cannot (AUC 0.667 vs 0.546). LR stays available for
    interpretability audits (--model lr).
    """
    numeric_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale",  StandardScaler()),
    ])
    pre = ColumnTransformer([
        ("num", numeric_pipe, numeric_cols),
        ("cat", OneHotEncoder(handle_unknown="ignore", drop=None), categorical_cols),
    ])
    if model == "lr":
        clf = LogisticRegression(
            class_weight="balanced", max_iter=1000, C=1.0, solver="lbfgs",
        )
    elif model == "gbm":
        # Shallow trees + many rounds is the right bias on ~100 samples.
        # learning_rate 0.05 + early stop = reasonable overfit guard.
        clf = HistGradientBoostingClassifier(
            max_iter=200, max_depth=3, learning_rate=0.05,
            class_weight="balanced", random_state=42,
        )
    elif model == "rf":
        clf = RandomForestClassifier(
            n_estimators=400, max_depth=6, min_samples_leaf=3,
            class_weight="balanced", n_jobs=-1, random_state=42,
        )
    else:
        raise ValueError(f"unknown model: {model!r} (choose lr | gbm | rf)")
    return Pipeline([("pre", pre), ("clf", clf)])


def rule_baseline_score(rule_decision: pd.Series, y: pd.Series) -> dict[str, float]:
    """What does the current rule stack get on this same keep/maybe subset?

    The rule stack's job here is to tell keep from maybe (cull rows already
    excluded). `rule_decision` is 'keep' or 'maybe' — we compute accuracy,
    and per-class recall, exactly as the learner will be scored.
    """
    pred_keep = (rule_decision == "keep").astype(int)
    y_keep = (y == "keep").astype(int)
    acc = (pred_keep == y_keep).mean()
    # Recall on the minority class (maybe) — rule tends to over-call keep
    maybe_mask = y_keep == 0
    maybe_recall = (pred_keep[maybe_mask] == 0).mean() if maybe_mask.any() else 0.0
    keep_recall = (pred_keep[~maybe_mask] == 1).mean() if (~maybe_mask).any() else 0.0
    return {
        "accuracy": float(acc),
        "keep_recall": float(keep_recall),
        "maybe_recall": float(maybe_recall),
    }


def cv_report(
    pipe: Pipeline,
    X: pd.DataFrame,
    y_binary: np.ndarray,
    scenes: pd.Series,
    cv: int,
    seed: int,
) -> tuple[dict, np.ndarray, np.ndarray]:
    """Run stratified k-fold CV and return per-fold + aggregate metrics."""
    skf = StratifiedKFold(n_splits=cv, shuffle=True, random_state=seed)
    y_pred = cross_val_predict(pipe, X, y_binary, cv=skf, n_jobs=-1)
    y_proba = cross_val_predict(pipe, X, y_binary, cv=skf, n_jobs=-1,
                                method="predict_proba")[:, 1]

    acc_all = float((y_pred == y_binary).mean())
    from sklearn.metrics import roc_auc_score
    try:
        auc = float(roc_auc_score(y_binary, y_proba))
    except ValueError:
        auc = float("nan")
    keep_mask = y_binary == 1
    keep_recall = float((y_pred[keep_mask] == 1).mean()) if keep_mask.any() else 0.0
    maybe_recall = float((y_pred[~keep_mask] == 0).mean()) if (~keep_mask).any() else 0.0

    per_scene: dict[str, dict[str, float]] = {}
    for scene in sorted(scenes.unique()):
        mask = (scenes == scene).values
        n = int(mask.sum())
        if n == 0:
            continue
        correct = int((y_pred[mask] == y_binary[mask]).sum())
        per_scene[scene] = {
            "n": n,
            "accuracy": correct / n if n else 0.0,
            "n_keep": int((y_binary[mask] == 1).sum()),
            "n_maybe": int((y_binary[mask] == 0).sum()),
        }

    return {
        "accuracy": acc_all,
        "auc": auc,
        "keep_recall": keep_recall,
        "maybe_recall": maybe_recall,
        "per_scene": per_scene,
    }, y_pred, y_proba


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("training_csv", type=Path,
                    help="Output of scripts/export_training_set.py")
    ap.add_argument("out_path", type=Path,
                    help="Where to save the joblib. Use '-' to skip saving.")
    ap.add_argument("--cv", type=int, default=5, help="Stratified k-fold (default: 5)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model", choices=["lr", "gbm", "rf"], default="gbm",
                    help="Classifier head (default: gbm — see compare_rescorers.py)")
    ap.add_argument("--runs-csv", type=Path,
                    help="Path to a scores.csv — used to compute the rule baseline "
                         "on the same rows (defaults to tests/fixtures/_eval_output/scores.csv).")
    args = ap.parse_args()

    if not args.training_csv.exists():
        sys.exit(f"ERROR: {args.training_csv} not found. Run "
                 f"scripts/export_training_set.py first.")

    raw = pd.read_csv(args.training_csv)
    total_rows = len(raw)
    sub = raw[raw["manual_label"].isin(["keep", "maybe"])].copy()
    print(f"Loaded {total_rows} rows from {args.training_csv.name}, "
          f"{len(sub)} usable for keep/maybe rescorer (cull excluded)")
    if len(sub) < 30:
        sys.exit(f"ERROR: only {len(sub)} keep/maybe rows — need at least 30 "
                 f"for a meaningful 5-fold CV.")

    df, feature_cols = build_feature_matrix(sub)
    numeric_cols = [c for c in feature_cols if c != "scene"]
    categorical_cols = ["scene"] if "scene" in feature_cols else []
    X = df[feature_cols]
    y = df["manual_label"]
    y_binary = (y == "keep").astype(int).values
    scenes = df["scene"].fillna("unknown")

    print(f"Features: {len(numeric_cols)} numeric + {len(categorical_cols)} categorical")
    print(f"Class balance: keep={int(y_binary.sum())}  maybe={int((1-y_binary).sum())}")
    print()

    pipe = build_pipeline(numeric_cols, categorical_cols, model=args.model)
    metrics, y_pred, y_proba = cv_report(pipe, X, y_binary, scenes, args.cv, args.seed)

    print("=" * 62)
    print(f"  V1.1 RESCORER · model={args.model} · {args.cv}-fold stratified CV "
          f"· seed={args.seed}")
    print("=" * 62)
    print(f"  Accuracy:      {metrics['accuracy']:.3f}")
    print(f"  ROC-AUC:       {metrics['auc']:.3f}")
    print(f"  keep recall:   {metrics['keep_recall']:.3f}  "
          f"(predicting a true keep as keep)")
    print(f"  maybe recall:  {metrics['maybe_recall']:.3f}  "
          f"(catching true maybes — this is what rules miss)")
    print()

    # Per-scene breakdown
    print("  Per-scene accuracy (CV predictions):")
    print(f"  {'scene':<12s} {'n':>4s} {'keep':>5s} {'maybe':>6s} {'acc':>7s}")
    for scene, d in sorted(metrics["per_scene"].items(),
                           key=lambda kv: -kv[1]["n"]):
        print(f"  {scene:<12s} {d['n']:>4d} {d['n_keep']:>5d} "
              f"{d['n_maybe']:>6d} {d['accuracy']:>7.3f}")
    print()

    # Rule baseline on the same rows for comparison
    runs_csv = args.runs_csv or Path("tests/fixtures/_eval_output/scores.csv")
    if runs_csv.exists():
        runs = pd.read_csv(runs_csv)[["filename", "decision"]]
        sub_with_rule = df[["filename", "manual_label"]].merge(runs, on="filename", how="left")
        # Some rows may have been CULL'd by the rule stack; the rescorer only
        # adjudicates within the KEEP/MAYBE call anyway, so measure baseline
        # on rule's non-cull rows (the inference-time domain).
        non_cull = sub_with_rule[sub_with_rule["decision"].isin(["keep", "maybe"])]
        if len(non_cull):
            rule_metrics = rule_baseline_score(
                non_cull["decision"], non_cull["manual_label"],
            )
            print(f"  Rule baseline on same {len(non_cull)} non-cull rows:")
            print(f"    accuracy:      {rule_metrics['accuracy']:.3f}")
            print(f"    keep recall:   {rule_metrics['keep_recall']:.3f}")
            print(f"    maybe recall:  {rule_metrics['maybe_recall']:.3f}")
            delta = metrics["accuracy"] - rule_metrics["accuracy"]
            marker = "✓ BEATS rule" if delta > 0.02 else \
                     ("≈ TIES rule (within 2pp)" if abs(delta) <= 0.02
                      else "✗ LOSES to rule")
            print(f"  Δ accuracy vs rule: {delta:+.3f}  {marker}")
        else:
            print("  (no non-cull rows to baseline against)")
    else:
        print(f"  (skipping rule baseline — {runs_csv} not found)")
    print()

    # Train final model on ALL rows (no holdout) and save.
    if str(args.out_path) != "-":
        pipe.fit(X, y_binary)
        args.out_path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "pipeline": pipe,
            "model_name": args.model,
            "feature_cols": feature_cols,
            "numeric_cols": numeric_cols,
            "categorical_cols": categorical_cols,
            "cv_metrics": metrics,
            "cv_folds": args.cv,
            "train_rows": len(sub),
            "train_label_balance": {
                "keep": int(y_binary.sum()),
                "maybe": int((1 - y_binary).sum()),
            },
            "notes": (
                "V1.1 rescorer. Binary keep vs maybe, trained on 128-photo "
                "golden set. Runtime: only call on rows where rule stack did "
                "not return CULL. Expect small-sample variance."
            ),
        }
        joblib.dump(artifact, args.out_path)
        print(f"  Saved model → {args.out_path}  "
              f"({args.out_path.stat().st_size // 1024} KB)")
    else:
        print("  (skipping save — out_path='-')")


if __name__ == "__main__":
    main()
