"""V15 — eval metrics regression tests.

The metrics functions are pure math; pin behaviour against
hand-computed examples + edge cases (empty, all-correct, NaN
inputs) so accidental regressions can't silently bias the
"V1 vs V2" verdict.
"""

from __future__ import annotations

import math

import pytest

from pixcull.scoring.eval_metrics import (
    accuracy,
    axis_mae,
    axis_r2,
    cohen_kappa,
    compare_runs,
    confusion_matrix,
    decision_summary,
    macro_f1,
    per_class_pr,
)


LABELS = ["keep", "maybe", "cull"]


# ---------------------------------------------------------------------------
# Confusion matrix
# ---------------------------------------------------------------------------

def test_confusion_matrix_shape():
    pairs = [("keep", "keep"), ("maybe", "cull"), ("cull", "cull")]
    cm = confusion_matrix(pairs, LABELS)
    assert cm["keep"]["keep"] == 1
    assert cm["maybe"]["cull"] == 1
    assert cm["cull"]["cull"] == 1
    assert cm["keep"]["cull"] == 0


def test_confusion_matrix_drops_oov():
    pairs = [("keep", "junk"), ("???", "keep"), ("keep", "keep")]
    cm = confusion_matrix(pairs, LABELS)
    # Only the 3rd pair counts
    assert cm["keep"]["keep"] == 1
    assert sum(sum(row.values()) for row in cm.values()) == 1


# ---------------------------------------------------------------------------
# Per-class P/R/F1
# ---------------------------------------------------------------------------

def test_per_class_pr_perfect():
    pairs = [("keep", "keep")] * 5 + [("cull", "cull")] * 5
    pr = per_class_pr(pairs, LABELS)
    assert pr["keep"] == (1.0, 1.0, 1.0)
    assert pr["cull"] == (1.0, 1.0, 1.0)
    # maybe never appeared — P/R/F1 should all be 0 (no error,
    # no prediction)
    assert pr["maybe"] == (0.0, 0.0, 0.0)


def test_per_class_pr_basic():
    # 5 keeps: 4 right, 1 → maybe
    # 3 maybes: 2 right, 1 → cull
    # 2 culls: 1 right, 1 → maybe
    pairs = (
        [("keep", "keep")] * 4 + [("keep", "maybe")]
        + [("maybe", "maybe")] * 2 + [("maybe", "cull")]
        + [("cull", "cull")] + [("cull", "maybe")]
    )
    pr = per_class_pr(pairs, LABELS)
    # keep: 4 TP, 0 FP, 1 FN → P=1.0, R=0.8, F1≈0.889
    assert pr["keep"][0] == pytest.approx(1.0)
    assert pr["keep"][1] == pytest.approx(0.8)
    assert pr["keep"][2] == pytest.approx(2 * 1.0 * 0.8 / (1.0 + 0.8))


# ---------------------------------------------------------------------------
# Macro-F1 + accuracy
# ---------------------------------------------------------------------------

def test_macro_f1_perfect():
    pairs = [("keep", "keep"), ("maybe", "maybe"), ("cull", "cull")]
    assert macro_f1(pairs, LABELS) == pytest.approx(1.0)


def test_macro_f1_chance_with_3_classes():
    # All-keep predictions, 1/3 of each class
    pairs = (
        [("keep", "keep")] * 3
        + [("maybe", "keep")] * 3
        + [("cull", "keep")] * 3
    )
    f1 = macro_f1(pairs, LABELS)
    # Only keep has any F1: P=1/3, R=1.0 → F1=0.5
    # The other two: 0
    # Macro = (0.5 + 0 + 0)/3 ≈ 0.1667
    assert f1 == pytest.approx(0.5 / 3, rel=0.01)


def test_accuracy_empty_returns_zero():
    assert accuracy([], LABELS) == 0.0


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------

def test_kappa_perfect_is_one():
    pairs = [("keep", "keep")] * 5 + [("cull", "cull")] * 5
    assert cohen_kappa(pairs, LABELS) == pytest.approx(1.0)


def test_kappa_chance_is_zero():
    """When pred is independent of truth, kappa should hover near 0.

    Construct exactly 1/3 each of (truth, pred) class crossings —
    expected agreement equals observed agreement, kappa = 0.
    """
    pairs = []
    for t in LABELS:
        for p in LABELS:
            pairs.extend([(t, p)] * 3)
    k = cohen_kappa(pairs, LABELS)
    assert abs(k) < 0.05


def test_kappa_weighted_penalises_keep_vs_cull_more():
    """Linear-weighted kappa: keep↔cull miss should hurt more than
    keep↔maybe."""
    # 10 keeps, predicted as: 5 keep, 5 maybe
    near_pairs = [("keep", "keep")] * 5 + [("keep", "maybe")] * 5
    # 10 keeps, predicted as: 5 keep, 5 cull
    far_pairs = [("keep", "keep")] * 5 + [("keep", "cull")] * 5
    near = cohen_kappa(near_pairs, LABELS, weighted=True)
    far = cohen_kappa(far_pairs, LABELS, weighted=True)
    # Both will be 0 (only one truth class) but the math under
    # weighted should still produce different observed agreement.
    # Test instead with both classes present.
    pairs1 = (
        [("keep", "keep")] * 5 + [("keep", "maybe")] * 5
        + [("cull", "cull")] * 5 + [("cull", "maybe")] * 5
    )
    pairs2 = (
        [("keep", "keep")] * 5 + [("keep", "cull")] * 5
        + [("cull", "cull")] * 5 + [("cull", "keep")] * 5
    )
    k1 = cohen_kappa(pairs1, LABELS, weighted=True)
    k2 = cohen_kappa(pairs2, LABELS, weighted=True)
    assert k1 > k2  # 1-step misses score higher than 2-step


def test_kappa_empty_is_zero():
    assert cohen_kappa([], LABELS) == 0.0


# ---------------------------------------------------------------------------
# Axis MAE / R²
# ---------------------------------------------------------------------------

def test_axis_mae_basic():
    truth = [3, 4, 5, 2]
    pred  = [3, 4, 5, 2]
    assert axis_mae(truth, pred) == 0.0
    pred2 = [4, 5, 4, 3]
    # diffs: 1, 1, 1, 1 → mean = 1.0
    assert axis_mae(truth, pred2) == pytest.approx(1.0)


def test_axis_mae_drops_nan():
    truth = [3, float("nan"), 5]
    pred  = [3,            4, 5]
    assert axis_mae(truth, pred) == 0.0  # only 2 valid pairs, both perfect


def test_axis_mae_empty_returns_nan():
    assert math.isnan(axis_mae([], []))


def test_axis_r2_perfect():
    truth = [1.0, 2.0, 3.0, 4.0]
    pred  = [1.0, 2.0, 3.0, 4.0]
    assert axis_r2(truth, pred) == pytest.approx(1.0)


def test_axis_r2_zero_variance():
    """R² is undefined when GT has no variance — should return NaN."""
    truth = [3, 3, 3, 3]
    pred  = [3, 4, 2, 3]
    assert math.isnan(axis_r2(truth, pred))


# ---------------------------------------------------------------------------
# Run-vs-run comparison
# ---------------------------------------------------------------------------

def test_compare_runs_recommends_replacement_on_big_f1_jump():
    base = {"n": 50, "accuracy": 0.7, "macro_f1": 0.65,
            "kappa": 0.5, "kappa_lin": 0.55,
            "per_class": {}, "confusion": {}}
    new = {"n": 50, "accuracy": 0.78, "macro_f1": 0.74,
           "kappa": 0.6, "kappa_lin": 0.65,
           "per_class": {}, "confusion": {}}
    cmp = compare_runs(base, new, LABELS)
    assert "推荐替换" in cmp["verdict"]
    assert cmp["macro_f1"]["delta"] == pytest.approx(0.09, rel=1e-3)


def test_compare_runs_warns_on_regression():
    base = {"n": 50, "accuracy": 0.78, "macro_f1": 0.74,
            "kappa": 0.6, "kappa_lin": 0.65,
            "per_class": {}, "confusion": {}}
    new = {"n": 50, "accuracy": 0.72, "macro_f1": 0.67,
           "kappa": 0.55, "kappa_lin": 0.6,
           "per_class": {}, "confusion": {}}
    cmp = compare_runs(base, new, LABELS)
    assert "回归" in cmp["verdict"]
    assert cmp["macro_f1"]["delta"] < 0


def test_compare_runs_calls_a_tie_a_tie():
    base = {"n": 50, "accuracy": 0.74, "macro_f1": 0.70,
            "kappa": 0.55, "kappa_lin": 0.6,
            "per_class": {}, "confusion": {}}
    new = {"n": 50, "accuracy": 0.745, "macro_f1": 0.703,
           "kappa": 0.553, "kappa_lin": 0.61,
           "per_class": {}, "confusion": {}}
    cmp = compare_runs(base, new, LABELS)
    assert "持平" in cmp["verdict"]


# ---------------------------------------------------------------------------
# Decision summary packaging
# ---------------------------------------------------------------------------

def test_decision_summary_shape():
    pairs = [("keep", "keep"), ("maybe", "maybe"), ("cull", "cull")]
    s = decision_summary(pairs, LABELS)
    assert s["n"] == 3
    assert s["accuracy"] == 1.0
    assert s["macro_f1"] == 1.0
    assert s["kappa"] == 1.0
    assert "per_class" in s
    assert "confusion" in s
    assert s["confusion"]["keep"]["keep"] == 1
