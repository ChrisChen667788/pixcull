"""Tests for scripts/eval_rescorer.py + scripts/eval_style_v2.py +
scripts/ci_rescorer_regression.py — v0.10-P0-3 ML eval harness.

The eval scripts are pure pandas + arithmetic; we test their cores
on small synthetic datasets so a regression in metric math gets
caught before the next "rescorer trained, recall went the wrong
way" surprise.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def _load(rel_path: str):
    p = Path(__file__).resolve().parent.parent / "scripts" / rel_path
    spec = importlib.util.spec_from_file_location(rel_path, p)
    assert spec and spec.loader, p
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# eval_rescorer.recall_at_k
# ---------------------------------------------------------------------------


def test_recall_at_k_perfect():
    er = _load("eval_rescorer.py")
    # Top 3 predictions are exactly the keeps
    pred = ["a", "b", "c", "d", "e"]
    gt   = {"a", "b", "c"}
    assert er.recall_at_k(pred, gt, k=3) == 1.0
    assert er.recall_at_k(pred, gt, k=5) == 1.0
    assert er.recall_at_k(pred, gt, k=2) == 2/3  # missed one


def test_recall_at_k_empty_gt_returns_zero():
    er = _load("eval_rescorer.py")
    assert er.recall_at_k(["a", "b"], set(), k=5) == 0.0


def test_recall_at_k_no_matches():
    er = _load("eval_rescorer.py")
    assert er.recall_at_k(["x", "y"], {"a", "b"}, k=5) == 0.0


# ---------------------------------------------------------------------------
# eval_rescorer.confusion_at_threshold
# ---------------------------------------------------------------------------


def test_confusion_at_threshold():
    er = _load("eval_rescorer.py")
    scores = pd.DataFrame([
        {"filename": "a.jpg", "score_final": 0.90},  # pred keep
        {"filename": "b.jpg", "score_final": 0.55},  # pred maybe
        {"filename": "c.jpg", "score_final": 0.30},  # pred cull
        {"filename": "d.jpg", "score_final": 0.70},  # pred keep
    ])
    gt = pd.DataFrame([
        {"filename": "a.jpg", "manual_label": "keep"},
        {"filename": "b.jpg", "manual_label": "keep"},
        {"filename": "c.jpg", "manual_label": "cull"},
        {"filename": "d.jpg", "manual_label": "maybe"},
    ])
    cm = er.confusion_at_threshold(scores, gt)
    # GT keep predicted (a) keep + (b) maybe
    assert cm["keep"]["keep"]  == 1
    assert cm["keep"]["maybe"] == 1
    # GT maybe predicted (d) keep
    assert cm["maybe"]["keep"] == 1
    # GT cull predicted (c) cull
    assert cm["cull"]["cull"]  == 1


# ---------------------------------------------------------------------------
# eval_rescorer.per_vertical_recall
# ---------------------------------------------------------------------------


def test_per_vertical_recall_buckets():
    er = _load("eval_rescorer.py")
    scores = pd.DataFrame([
        # wedding — score keeps high
        {"filename": "w1.jpg", "score_final": 0.92},
        {"filename": "w2.jpg", "score_final": 0.88},
        {"filename": "w3.jpg", "score_final": 0.30},
        # landscape — perfect ordering
        {"filename": "l1.jpg", "score_final": 0.95},
        {"filename": "l2.jpg", "score_final": 0.85},
    ])
    gt = pd.DataFrame([
        {"filename": "w1.jpg", "vertical": "wedding",   "manual_label": "keep"},
        {"filename": "w2.jpg", "vertical": "wedding",   "manual_label": "keep"},
        {"filename": "w3.jpg", "vertical": "wedding",   "manual_label": "cull"},
        {"filename": "l1.jpg", "vertical": "landscape", "manual_label": "keep"},
        {"filename": "l2.jpg", "vertical": "landscape", "manual_label": "keep"},
    ])
    out = er.per_vertical_recall(scores, gt, k=5)
    # Both wedding keeps top-2 of 3 → recall@5 = 100%
    assert out["wedding"]   == 1.0
    assert out["landscape"] == 1.0


# ---------------------------------------------------------------------------
# eval_rescorer end-to-end on synthetic data
# ---------------------------------------------------------------------------


def test_evaluate_end_to_end(tmp_path):
    er = _load("eval_rescorer.py")
    scores_csv = tmp_path / "candidate.csv"
    scores_csv.write_text(
        "filename,score_final\n"
        "a.jpg,0.92\n"
        "b.jpg,0.85\n"
        "c.jpg,0.45\n"
        "d.jpg,0.30\n",
        encoding="utf-8",
    )
    gt_csv = tmp_path / "gt.csv"
    gt_csv.write_text(
        "filename,vertical,manual_label\n"
        "a.jpg,wedding,keep\n"
        "b.jpg,wedding,keep\n"
        "c.jpg,wedding,maybe\n"
        "d.jpg,wedding,cull\n",
        encoding="utf-8",
    )
    out = er.evaluate(scores_csv, gt_csv, label="v3")
    assert out["n_rows"]   == 4
    assert out["n_keep_gt"] == 2
    # Top-5 contains both keeps → recall@5 = 100%
    assert out["recall_at"]["k=5"]  == 1.0
    # Top-2 contains both keeps → recall@2 not asked, but k=5,10,20 default
    assert "wedding" in out["per_vertical"]


def test_render_markdown_emits_expected_headers():
    er = _load("eval_rescorer.py")
    cand = {
        "label": "v3", "n_rows": 100, "n_keep_gt": 40,
        "recall_at":    {"k=5": 0.80, "k=10": 0.92, "k=20": 0.99},
        "per_vertical": {"wedding": 0.83, "landscape": 0.77},
        "axis_mae":     {"technical": {"mae": 0.45, "n": 100}},
        "confusion":    {"keep": {"keep": 35, "maybe": 4, "cull": 1}},
    }
    base = {
        "label": "v2", "n_rows": 100, "n_keep_gt": 40,
        "recall_at":    {"k=5": 0.76, "k=10": 0.90, "k=20": 0.99},
        "per_vertical": {"wedding": 0.79, "landscape": 0.74},
        "axis_mae":     {"technical": {"mae": 0.52, "n": 100}},
        "confusion":    {},
    }
    md = er.render_markdown(cand, base)
    assert "# Rescorer evaluation · v3" in md
    assert "Recall@k" in md
    assert "+4.0pp" in md          # 80% vs 76%
    assert "Per-vertical recall@5" in md
    assert "Per-axis MAE" in md
    assert "Confusion @ threshold 0.65" in md


# ---------------------------------------------------------------------------
# eval_style_v2 — blend math + sweep
# ---------------------------------------------------------------------------


def test_blend_handles_missing_terms():
    es = _load("eval_style_v2.py")
    assert es.blend(None, None, 0.5) is None
    assert es.blend(0.3,  None, 0.5) == 0.3   # V1 only
    assert es.blend(None, 0.7,  0.5) == 0.7   # V2 only
    # Normal case
    assert es.blend(1.0, 0.0, 0.0) == 0.0     # λ=0 → V2
    assert es.blend(1.0, 0.0, 1.0) == 1.0     # λ=1 → V1
    assert es.blend(1.0, 0.0, 0.5) == 0.5


def test_sweep_one_vertical_excludes_keep_refs():
    es = _load("eval_style_v2.py")
    # Distances — lower = better match
    dists = {
        "a.jpg": {"v1": 0.1, "v2": 0.1},   # very close
        "b.jpg": {"v1": 0.2, "v2": 0.2},
        "c.jpg": {"v1": 0.5, "v2": 0.5},   # far
        "d.jpg": {"v1": 0.3, "v2": 0.3},   # ref — should be skipped
    }
    gt = pd.DataFrame([
        {"filename": "a.jpg", "manual_label": "keep", "is_keep_ref": 0},
        {"filename": "b.jpg", "manual_label": "keep", "is_keep_ref": 0},
        {"filename": "c.jpg", "manual_label": "cull", "is_keep_ref": 0},
        {"filename": "d.jpg", "manual_label": "keep", "is_keep_ref": 1},  # ref
    ])
    sweep = es.sweep_one_vertical(dists, gt, [0.0, 0.5, 1.0], k=5)
    # Two non-ref keeps (a, b); both rank top-2 by distance → recall = 1.0
    assert sweep[0.0] == 1.0
    assert sweep[0.5] == 1.0
    assert sweep[1.0] == 1.0


def test_render_markdown_picks_best_lambda():
    es = _load("eval_style_v2.py")
    per_vertical = {
        "wedding":   {0.0: 0.50, 0.3: 0.60, 0.5: 0.70, 0.7: 0.65, 1.0: 0.55},
        "landscape": {0.0: 0.40, 0.3: 0.55, 0.5: 0.55, 0.7: 0.45, 1.0: 0.30},
    }
    md = es.render_markdown(per_vertical, [0.0, 0.3, 0.5, 0.7, 1.0])
    # Wedding's best is λ=0.5 (70%); render uses %5.1f → " 70.0"
    # so the bolded cell reads `** 70.0%**` (the space is from the format spec).
    assert "70.0%**" in md
    # 0.3 wins the tie for landscape — chosen as global recommended default
    assert "Global recommended default" in md
    assert "λ = 0.3" in md


# ---------------------------------------------------------------------------
# ci_rescorer_regression — exit codes
# ---------------------------------------------------------------------------


def test_ci_gate_no_baseline():
    ci = _load("ci_rescorer_regression.py")
    code, msg = ci.gate({"candidate": {"recall_at": {"k=5": 0.7}},
                          "baseline": None})
    assert code == 0
    assert "no baseline" in msg.lower()


def test_ci_gate_passes_within_tolerance():
    ci = _load("ci_rescorer_regression.py")
    code, msg = ci.gate({
        "candidate": {"recall_at": {"k=5": 0.755}},
        "baseline":  {"recall_at": {"k=5": 0.760}},
    }, tolerance=0.01)
    # delta = -0.5pp, within 1pp tolerance → OK
    assert code == 0


def test_ci_gate_fails_on_regression():
    ci = _load("ci_rescorer_regression.py")
    code, msg = ci.gate({
        "candidate": {"recall_at": {"k=5": 0.70}},
        "baseline":  {"recall_at": {"k=5": 0.80}},
    }, tolerance=0.01)
    # delta = -10pp >> 1pp → fail
    assert code == 2
    assert "regression" in msg.lower()


def test_ci_gate_handles_malformed_json():
    ci = _load("ci_rescorer_regression.py")
    code, _ = ci.gate({})
    assert code == 3
    code, _ = ci.gate({"candidate": "not-a-dict", "baseline": None})
    assert code == 3
