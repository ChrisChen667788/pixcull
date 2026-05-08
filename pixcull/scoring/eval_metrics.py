"""V15 evaluation metrics — pure, testable, dependency-light.

Why a separate module instead of inlining in eval_on_golden_set.py:
* The script does I/O + pandas + pipeline orchestration. The metrics
  underneath are pure: ``list[truth, pred] → float``. Splitting them
  out lets us unit-test the math without spinning up the pipeline.
* Same metrics get reused by the V14.1 admin "Eval against goldenset"
  button (planned) and by ``compare_rescorers.py`` style ad-hoc
  sweeps. One source of truth for accuracy / F1 / kappa avoids
  metric drift between callers.

Functions
---------
* ``confusion_matrix(pairs, labels)``     → 2-D dict
* ``per_class_pr(pairs, labels)``         → {label: (precision, recall, f1)}
* ``macro_f1(pairs, labels)``             → float
* ``cohen_kappa(pairs, labels)``          → float
* ``decision_summary(pairs, labels)``     → packaged dict for HTML report
* ``axis_mae(truth, pred)``               → float (and ``axis_r2`` for paired)
* ``compare_runs(base, new, labels)``     → dict of deltas

All functions accept ``pairs: Iterable[tuple[str, str]]`` of
``(truth_label, pred_label)`` and ``labels: Sequence[str]`` for the
class ordering. Out-of-vocab labels are ignored (counted as neither
TP nor FP / FN for any class) so a noisy GT doesn't crash the
metric — the caller can decide how strict to be.

Cohen's kappa formula (linear-weighted): see Wikipedia
"Cohen's kappa". For our 3-class keep/maybe/cull case the unweighted
version is what users intuit ("agreement minus chance"), so that's
the default; pass ``weighted=True`` for the linear variant.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

import math


# -----------------------------------------------------------------------------
# Decision metrics
# -----------------------------------------------------------------------------

def confusion_matrix(
    pairs: Iterable[tuple[str, str]],
    labels: Sequence[str],
) -> dict[str, dict[str, int]]:
    """rows[truth][pred] count. Off-vocab pairs are dropped."""
    label_set = set(labels)
    out = {t: {p: 0 for p in labels} for t in labels}
    for truth, pred in pairs:
        if truth in label_set and pred in label_set:
            out[truth][pred] += 1
    return out


def per_class_pr(
    pairs: Iterable[tuple[str, str]],
    labels: Sequence[str],
) -> dict[str, tuple[float, float, float]]:
    """Per-class (precision, recall, F1). Skips off-vocab.

    F1 = 2PR / (P + R) — using the convention that 0/0 → 0.0
    (the class never appeared in either truth or pred).
    """
    counts = {l: {"tp": 0, "fp": 0, "fn": 0} for l in labels}
    label_set = set(labels)
    for truth, pred in pairs:
        if truth not in label_set or pred not in label_set:
            continue
        for cls in labels:
            if pred == cls and truth == cls:
                counts[cls]["tp"] += 1
            elif pred == cls and truth != cls:
                counts[cls]["fp"] += 1
            elif pred != cls and truth == cls:
                counts[cls]["fn"] += 1

    out: dict[str, tuple[float, float, float]] = {}
    for cls, c in counts.items():
        p_denom = c["tp"] + c["fp"]
        r_denom = c["tp"] + c["fn"]
        p = c["tp"] / p_denom if p_denom else 0.0
        r = c["tp"] / r_denom if r_denom else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        out[cls] = (p, r, f1)
    return out


def macro_f1(
    pairs: Iterable[tuple[str, str]],
    labels: Sequence[str],
) -> float:
    """Unweighted mean of per-class F1 — robust to class imbalance."""
    pr = per_class_pr(pairs, labels)
    if not pr:
        return 0.0
    return sum(f1 for _, _, f1 in pr.values()) / len(pr)


def accuracy(
    pairs: Iterable[tuple[str, str]],
    labels: Sequence[str],
) -> float:
    pairs = [(t, p) for t, p in pairs if t in set(labels) and p in set(labels)]
    if not pairs:
        return 0.0
    return sum(1 for t, p in pairs if t == p) / len(pairs)


def cohen_kappa(
    pairs: Iterable[tuple[str, str]],
    labels: Sequence[str],
    *,
    weighted: bool = False,
) -> float:
    """Agreement adjusted for chance.

    Range:
        +1.0  perfect agreement
         0.0  pure chance
        -1.0  perfect disagreement (in practice never seen)

    Linear-weighted (``weighted=True``) penalises a "keep vs cull"
    miss more than "keep vs maybe" — useful when the label space has
    an ordinal feel (which keep/maybe/cull does).
    """
    pairs = [(t, p) for t, p in pairs if t in set(labels) and p in set(labels)]
    n = len(pairs)
    if n == 0:
        return 0.0

    cm = confusion_matrix(pairs, labels)
    label_idx = {l: i for i, l in enumerate(labels)}
    n_labels = len(labels)

    # Marginals
    row_total = {l: sum(cm[l].values()) for l in labels}
    col_total = {l: sum(cm[t][l] for t in labels) for l in labels}

    if not weighted:
        po = sum(cm[l][l] for l in labels) / n  # observed agreement
        pe = sum((row_total[l] / n) * (col_total[l] / n) for l in labels)
        if pe == 1.0:
            return 1.0  # everyone agrees on a single class
        return (po - pe) / (1 - pe)

    # Linear-weighted: w(i,j) = 1 - |i - j| / (n_labels - 1)
    def w(li: str, lj: str) -> float:
        di = label_idx[li]; dj = label_idx[lj]
        return 1.0 - abs(di - dj) / max(1, n_labels - 1)

    po = sum(w(li, lj) * cm[li][lj] for li in labels for lj in labels) / n
    pe = sum(
        w(li, lj) * (row_total[li] / n) * (col_total[lj] / n)
        for li in labels for lj in labels
    )
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def decision_summary(
    pairs: list[tuple[str, str]],
    labels: Sequence[str],
) -> dict:
    """Packaged decision-level report. Convenient for the HTML view."""
    return {
        "n":          len(pairs),
        "accuracy":   accuracy(pairs, labels),
        "macro_f1":   macro_f1(pairs, labels),
        "kappa":      cohen_kappa(pairs, labels),
        "kappa_lin":  cohen_kappa(pairs, labels, weighted=True),
        "per_class":  {
            l: {"precision": p, "recall": r, "f1": f1}
            for l, (p, r, f1) in per_class_pr(pairs, labels).items()
        },
        "confusion":  confusion_matrix(pairs, labels),
    }


# -----------------------------------------------------------------------------
# Per-axis (regression) metrics
# -----------------------------------------------------------------------------

def axis_mae(
    truth: Iterable[float],
    pred:  Iterable[float],
) -> float:
    """Mean absolute error in stars. Pairs with NaN on either side
    are dropped (we don't pretend to predict where there's no GT)."""
    pairs = [(t, p) for t, p in zip(truth, pred)
             if t is not None and p is not None
             and not (isinstance(t, float) and math.isnan(t))
             and not (isinstance(p, float) and math.isnan(p))]
    if not pairs:
        return float("nan")
    return sum(abs(t - p) for t, p in pairs) / len(pairs)


def axis_r2(
    truth: Iterable[float],
    pred:  Iterable[float],
) -> float:
    """Coefficient of determination. NaN if variance is 0 (all GT same)."""
    pairs = [(float(t), float(p)) for t, p in zip(truth, pred)
             if t is not None and p is not None
             and not (isinstance(t, float) and math.isnan(t))
             and not (isinstance(p, float) and math.isnan(p))]
    if len(pairs) < 2:
        return float("nan")
    ts = [t for t, _ in pairs]
    mean_t = sum(ts) / len(ts)
    ss_tot = sum((t - mean_t) ** 2 for t in ts)
    if ss_tot == 0:
        return float("nan")
    ss_res = sum((t - p) ** 2 for t, p in pairs)
    return 1.0 - ss_res / ss_tot


# -----------------------------------------------------------------------------
# Run-vs-run comparison (V1 rescorer vs V2)
# -----------------------------------------------------------------------------

def compare_runs(
    base: dict,
    new:  dict,
    labels: Sequence[str],
) -> dict:
    """Compute deltas between two ``decision_summary`` dicts.

    Positive delta = new > base = improvement. Useful for the
    "did the latest auto-retrain actually help?" check the
    V11.2 path is missing.
    """
    return {
        "n_base":      base["n"],
        "n_new":       new["n"],
        "accuracy":    {"base": base["accuracy"], "new": new["accuracy"],
                        "delta": new["accuracy"] - base["accuracy"]},
        "macro_f1":    {"base": base["macro_f1"], "new": new["macro_f1"],
                        "delta": new["macro_f1"] - base["macro_f1"]},
        "kappa":       {"base": base["kappa"],    "new": new["kappa"],
                        "delta": new["kappa"]    - base["kappa"]},
        "verdict":     _improvement_verdict(base, new),
    }


def _improvement_verdict(base: dict, new: dict) -> str:
    """Heuristic verdict — see DOC at top of eval_on_golden_set.py.

    Thresholds are conservative: a 0.5 percentage-point bump on a
    50-image goldenset is just noise; we want a 2-pt gap before
    flipping a "ship V2" recommendation.
    """
    f1_delta = new["macro_f1"] - base["macro_f1"]
    if f1_delta > 0.02:
        return "✓ 推荐替换 (macro-F1 上升 >2pp)"
    if f1_delta > 0.005:
        return "≈ 接近平 (差距 <2pp,谨慎替换)"
    if f1_delta > -0.01:
        return "≈ 持平"
    return "✗ 回归 (macro-F1 下降 >1pp,不要替换)"


__all__ = [
    "accuracy",
    "axis_mae",
    "axis_r2",
    "cohen_kappa",
    "compare_runs",
    "confusion_matrix",
    "decision_summary",
    "macro_f1",
    "per_class_pr",
]
