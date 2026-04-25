"""V1.2 trigger audit — single-command "is the rescorer ready to ship yet?"

V1.1's `eval_findings.md` locked in three thresholds for wiring the learned
rescorer into `pixcull.rules.decide`. This script checks all three against
the current `training.csv` + `scores.csv` and prints a checklist. Exits 0
when every condition is green, 1 otherwise — so it's CI-friendly.

Thresholds (from eval_findings.md V1.1 "Decision: V1.1 does not ship
runtime integration"):

  1. Training set ≥ 400 rows
  2. Landscape-only CV AUC ≥ 0.70
  3. Global Δ accuracy vs rule ≥ +0.03

The first is a labelling-push milestone. The second is "per-scene signal
exists at all." The third is "the learned head actually beats the rule
stack on ship numbers, not just ties it."

Usage:
    python scripts/check_v1_2_trigger.py training.csv

    # Or with a custom pipeline run used to compute the rule baseline:
    python scripts/check_v1_2_trigger.py training.csv \\
        --runs-csv ~/Pictures/catalog_eval/scores.csv

Every time the user does a labelling pass and re-exports training.csv,
this is the one command that says "keep labelling" or "time to wire it in."
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

# Reuse the feature + pipeline definitions from V1.1 trainer so the audit
# and the shipped trainer stay lock-step.
sys.path.insert(0, str(Path(__file__).parent))
from train_rescorer import (  # type: ignore
    build_feature_matrix, build_pipeline, cv_report, rule_baseline_score,
)

# V1.2 ship gate (fixed; change requires updating eval_findings.md too).
_MIN_ROWS = 400
_MIN_LANDSCAPE_AUC = 0.70
_MIN_DELTA_ACC = 0.03

_GREEN = "\033[32m"
_RED = "\033[31m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _mark(passed: bool) -> str:
    return f"{_GREEN}[✓]{_RESET}" if passed else f"{_RED}[✗]{_RESET}"


def landscape_auc(X: pd.DataFrame, y_binary: np.ndarray,
                  scenes: pd.Series) -> tuple[float, int, int]:
    """CV AUC on the landscape slice only.

    Uses 3-fold (vs 5-fold global) because landscape is the smallest scene
    with both keep and maybe present — 5-fold would put 1-2 samples per
    fold. Returns (auc, n_keep, n_maybe). If there aren't enough rows of
    each class for any CV at all, returns NaN.
    """
    mask = (scenes == "landscape").values
    n = int(mask.sum())
    n_keep = int(y_binary[mask].sum())
    n_maybe = int(n - n_keep)
    if n_keep < 3 or n_maybe < 3:
        return float("nan"), n_keep, n_maybe

    X_ls = X.iloc[mask]
    y_ls = y_binary[mask]
    # 3-fold keeps at least 1 of each class per fold at n_maybe=3; drop to 2
    # if we have to (rare — would only hit at landscape push < 10 rows).
    n_splits = 3 if min(n_keep, n_maybe) >= 3 else 2
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    # Build a fresh pipe so the landscape CV doesn't reuse global-fit state.
    numeric_cols = [c for c in X.columns if c != "scene"]
    categorical_cols = ["scene"] if "scene" in X.columns else []
    pipe = build_pipeline(numeric_cols, categorical_cols, model="gbm")
    try:
        y_proba = cross_val_predict(
            pipe, X_ls, y_ls, cv=skf, n_jobs=-1, method="predict_proba",
        )[:, 1]
        return float(roc_auc_score(y_ls, y_proba)), n_keep, n_maybe
    except (ValueError, IndexError):
        return float("nan"), n_keep, n_maybe


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("training_csv", type=Path,
                    help="Output of scripts/export_training_set.py")
    ap.add_argument("--runs-csv", type=Path,
                    default=Path("tests/fixtures/_eval_output/scores.csv"),
                    help="scores.csv for rule baseline (default: fixtures)")
    ap.add_argument("--cv", type=int, default=5,
                    help="Folds for the global CV (default: 5)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not args.training_csv.exists():
        sys.exit(f"ERROR: {args.training_csv} not found. Run "
                 f"scripts/export_training_set.py first.")

    raw = pd.read_csv(args.training_csv)
    total_rows = len(raw)
    sub = raw[raw["manual_label"].isin(["keep", "maybe"])].copy()
    if len(sub) < 30:
        sys.exit(f"ERROR: only {len(sub)} keep/maybe rows — need ≥ 30 for CV.")

    df, feature_cols = build_feature_matrix(sub)
    numeric_cols = [c for c in feature_cols if c != "scene"]
    categorical_cols = ["scene"] if "scene" in feature_cols else []
    X = df[feature_cols]
    y_binary = (df["manual_label"] == "keep").astype(int).values
    scenes = df["scene"].fillna("unknown")

    pipe = build_pipeline(numeric_cols, categorical_cols, model="gbm")
    metrics, _, _ = cv_report(pipe, X, y_binary, scenes, args.cv, args.seed)
    global_acc = metrics["accuracy"]
    global_auc = metrics["auc"]

    # Rule baseline on the non-cull slice (same methodology as train_rescorer.py)
    delta_acc = float("nan")
    rule_acc = float("nan")
    rule_n = 0
    if args.runs_csv.exists():
        runs = pd.read_csv(args.runs_csv)[["filename", "decision"]]
        merged = df[["filename", "manual_label"]].merge(runs, on="filename", how="left")
        non_cull = merged[merged["decision"].isin(["keep", "maybe"])]
        rule_n = len(non_cull)
        if rule_n:
            rm = rule_baseline_score(non_cull["decision"], non_cull["manual_label"])
            rule_acc = rm["accuracy"]
            delta_acc = global_acc - rule_acc

    ls_auc, ls_keep, ls_maybe = landscape_auc(X, y_binary, scenes)

    # Three gates
    gate_rows = total_rows >= _MIN_ROWS
    gate_landscape = (not np.isnan(ls_auc)) and ls_auc >= _MIN_LANDSCAPE_AUC
    gate_delta = (not np.isnan(delta_acc)) and delta_acc >= _MIN_DELTA_ACC
    all_green = gate_rows and gate_landscape and gate_delta

    # Report
    print()
    print(f"{_DIM}═══ V1.2 RESCORER RUNTIME-INTEGRATION TRIGGER CHECK ═══{_RESET}")
    print()
    print(f"  training rows         : {total_rows} "
          f"(keep+maybe usable: {len(sub)})")
    print(f"  global GBM CV (5-fold): acc={global_acc:.3f}  "
          f"AUC={global_auc:.3f}")
    if np.isnan(ls_auc):
        print(f"  landscape-only CV     : "
              f"INSUFFICIENT DATA (keep={ls_keep} maybe={ls_maybe})")
    else:
        print(f"  landscape-only CV     : AUC={ls_auc:.3f}  "
              f"(keep={ls_keep} maybe={ls_maybe})")
    if np.isnan(delta_acc):
        print(f"  rule baseline         : N/A ({args.runs_csv} missing or no "
              f"matching rows)")
    else:
        print(f"  rule baseline         : acc={rule_acc:.3f} on {rule_n} rows  "
              f"→  Δ vs rescorer = {delta_acc:+.3f}")
    print()
    print(f"  {'gate':<32s} {'threshold':<10s} {'actual':<10s} status")
    print(f"  {'-' * 32} {'-' * 10} {'-' * 10} ------")
    print(f"  {'(1) training rows':<32s} "
          f"{'≥ ' + str(_MIN_ROWS):<10s} "
          f"{total_rows!s:<10s} {_mark(gate_rows)}")
    ls_display = "—" if np.isnan(ls_auc) else f"{ls_auc:.3f}"
    print(f"  {'(2) landscape-only CV AUC':<32s} "
          f"{'≥ ' + f'{_MIN_LANDSCAPE_AUC:.2f}':<10s} "
          f"{ls_display:<10s} {_mark(gate_landscape)}")
    delta_display = "—" if np.isnan(delta_acc) else f"{delta_acc:+.3f}"
    print(f"  {'(3) Δ acc vs rule':<32s} "
          f"{'≥ +' + f'{_MIN_DELTA_ACC:.2f}':<10s} "
          f"{delta_display:<10s} {_mark(gate_delta)}")
    print()

    if all_green:
        print(f"  {_GREEN}STATUS: READY{_RESET} — wire rescorer into "
              f"pixcull.rules.decide behind a strictness flag.")
        print(f"  {_DIM}Next: add rescorer load path to decide module, re-run "
              f"golden-set eval.{_RESET}")
        sys.exit(0)
    else:
        print(f"  {_RED}STATUS: NOT READY{_RESET} — keep labelling / keep "
              f"iterating features.")
        if not gate_rows:
            print(f"  {_DIM}  → (1) needs {_MIN_ROWS - total_rows} more labelled "
                  f"rows. Run scripts/pick_next_to_label.py.{_RESET}")
        if not gate_landscape:
            print(f"  {_DIM}  → (2) landscape AUC still sub-0.70 — either "
                  f"add features that encode within-scene curation, or keep "
                  f"accumulating landscape labels.{_RESET}")
        if not gate_delta:
            print(f"  {_DIM}  → (3) rescorer ties/loses to rule on global "
                  f"accuracy. Re-check feature set.{_RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
