#!/usr/bin/env python3
"""v0.10-P0-3 — standalone rescorer evaluation harness.

Different from scripts/eval_on_golden_set.py (which re-runs the
entire pipeline on a goldenset): this script reads PRE-COMPUTED
scores.csv files for two rescorer versions on the same dataset
and compares them.  Faster to iterate when tuning hyper-params
or comparing trained models, and the data-prep is a one-time
cost.

Pipeline
========

    # Cut a scores.csv with the current rescorer:
    python scripts/eval_on_golden_set.py path/to/golden --report --label v3
    cp path/to/golden/_eval_output/scores.csv eval_v3.csv

    # Same with the previous version (just swap the rescorer model):
    python scripts/eval_on_golden_set.py path/to/golden --report --label v2
    cp path/to/golden/_eval_output/scores.csv eval_v2.csv

    # Compare:
    python scripts/eval_rescorer.py eval_v3.csv eval_v2.csv \\
        --ground-truth path/to/golden/ground_truth.csv \\
        --out docs/RESCORER-V3-EVAL.md

The output markdown carries: recall@5 / recall@10 / per-axis MAE /
per-vertical breakdown / confusion matrix at 0.65 keep-threshold,
in both candidate-vs-baseline and absolute terms.

Sentinel exit codes (for CI consumption):
    0 → candidate ≥ baseline (or first-time eval)
    2 → candidate regressed > --tolerance recall@5 (default 1%)
    3 → ground-truth CSV missing columns / unreadable
    4 → score CSVs have mismatched filename sets

(see ``scripts/ci_rescorer_regression.py`` for the CI wrapper that
reads the same eval JSON and gates a release.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


AXES = ("technical", "subject", "composition", "light", "moment", "aesthetic")
KEEP_THRESHOLD = 0.65  # canonical score_final ≥ x → keep


def _load_scores(p: Path, label: str) -> pd.DataFrame:
    """Load + sanity-check a scores.csv from a prior run."""
    if not p.exists():
        sys.exit(f"[eval] {label}: not found: {p}")
    df = pd.read_csv(p)
    if "filename" not in df.columns or "score_final" not in df.columns:
        sys.exit(f"[eval] {label}: missing filename/score_final columns")
    return df


def _load_ground_truth(p: Path) -> pd.DataFrame:
    """Load goldenset GT csv.  Required columns: filename + manual_label.
    Optional: scene + vertical + gt_<axis>_stars for axis MAE."""
    df = pd.read_csv(p)
    for col in ("filename", "manual_label"):
        if col not in df.columns:
            sys.exit(f"[eval] ground truth missing column '{col}'")
    # vertical defaults to scene; older goldensets only have one or the other
    if "vertical" not in df.columns:
        df["vertical"] = df.get("scene", "unknown").fillna("unknown")
    return df


def recall_at_k(predicted_keeps: list[str], gt_keeps: set[str], k: int) -> float:
    """Recall@k = |top-k predictions ∩ GT-keeps| / |GT-keeps|.

    Standard metric for "did the rescorer surface the right photos
    at the top of the sort?"  Higher k means we tolerate the
    photographer scrolling.
    """
    if not gt_keeps:
        return 0.0
    top_k = set(predicted_keeps[:k])
    return len(top_k & gt_keeps) / len(gt_keeps)


def _decision_at_threshold(score: float) -> str:
    if score >= KEEP_THRESHOLD:
        return "keep"
    if score >= 0.40:
        return "maybe"
    return "cull"


def confusion_at_threshold(df: pd.DataFrame, gt: pd.DataFrame) -> dict:
    """Confusion matrix between predicted decision (from score_final)
    and GT manual_label, at the canonical 0.65 threshold."""
    merged = df.merge(gt, on="filename", how="inner")
    cm: dict[tuple[str, str], int] = {}
    for _, row in merged.iterrows():
        pred = _decision_at_threshold(float(row["score_final"]))
        truth = str(row["manual_label"])
        cm[(truth, pred)] = cm.get((truth, pred), 0) + 1
    # Pivot to a nested dict {gt: {pred: n}}
    out: dict[str, dict[str, int]] = {}
    for (t, p), n in cm.items():
        out.setdefault(t, {})[p] = n
    return out


def per_vertical_recall(
    df: pd.DataFrame,
    gt: pd.DataFrame,
    k: int = 5,
) -> dict[str, float]:
    """Recall@k bucketed by vertical (wedding / landscape / wildlife…)."""
    merged = df.merge(gt, on="filename", how="inner")
    out: dict[str, float] = {}
    for vert, sub in merged.groupby("vertical"):
        ranked = sub.sort_values("score_final", ascending=False)["filename"].tolist()
        gt_keeps = set(sub[sub["manual_label"] == "keep"]["filename"])
        out[str(vert)] = recall_at_k(ranked, gt_keeps, k)
    return out


def axis_mae(df: pd.DataFrame, gt: pd.DataFrame) -> dict[str, dict]:
    """Per-axis MAE between rubric_<axis>_stars and gt_<axis>_stars,
    when the GT has per-axis stars (older goldensets don't)."""
    merged = df.merge(gt, on="filename", how="inner")
    out: dict[str, dict] = {}
    for axis in AXES:
        gt_col = f"gt_{axis}_stars"
        pred_col = f"rubric_{axis}_stars"
        if gt_col not in merged.columns:
            continue
        if pred_col not in merged.columns:
            continue
        pairs = merged[[gt_col, pred_col]].dropna()
        if pairs.empty:
            continue
        mae = (pairs[gt_col] - pairs[pred_col]).abs().mean()
        out[axis] = {"mae": float(mae), "n": int(len(pairs))}
    return out


def evaluate(
    scores_path: Path,
    gt_path: Path,
    label: str,
    *,
    ks: Iterable[int] = (5, 10, 20),
) -> dict:
    """Compute the full metric bundle for one scores.csv."""
    scores = _load_scores(scores_path, label)
    gt = _load_ground_truth(gt_path)
    merged = scores.merge(gt, on="filename", how="inner")
    if merged.empty:
        sys.exit(f"[eval] {label}: 0 rows after merging filename — schema mismatch?")
    # Overall recall@k
    ranked = merged.sort_values("score_final", ascending=False)["filename"].tolist()
    gt_keeps = set(merged[merged["manual_label"] == "keep"]["filename"])
    metrics: dict = {
        "label":       label,
        "n_rows":      int(len(merged)),
        "n_keep_gt":   len(gt_keeps),
        "recall_at":   {f"k={k}": recall_at_k(ranked, gt_keeps, k) for k in ks},
        "per_vertical": per_vertical_recall(scores, gt, k=5),
        "axis_mae":    axis_mae(scores, gt),
        "confusion":   confusion_at_threshold(scores, gt),
    }
    return metrics


def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def render_markdown(cand: dict, base: dict | None = None) -> str:
    """Render the side-by-side markdown report."""
    lines = []
    lines.append(f"# Rescorer evaluation · {cand['label']}\n")
    lines.append(f"Dataset: **{cand['n_rows']}** rows ·"
                 f" **{cand['n_keep_gt']}** keep in GT\n")

    # --- overall recall@k ---
    lines.append("## Recall@k\n")
    lines.append("| k | candidate | baseline | Δ |")
    lines.append("|---|-----------|----------|---|")
    for k_label in cand["recall_at"]:
        c = cand["recall_at"][k_label]
        b = (base["recall_at"].get(k_label) if base else None)
        delta = (c - b) if (b is not None) else None
        delta_str = (f"{(delta * 100):+.1f}pp" if delta is not None else "—")
        b_str = (_fmt_pct(b) if b is not None else "—")
        lines.append(f"| {k_label} | {_fmt_pct(c)} | {b_str} | {delta_str} |")
    lines.append("")

    # --- per-vertical recall@5 ---
    lines.append("## Per-vertical recall@5\n")
    lines.append("| vertical | candidate | baseline | Δ |")
    lines.append("|---|---|---|---|")
    verticals = sorted(set(cand["per_vertical"])
                        | (set(base["per_vertical"]) if base else set()))
    for v in verticals:
        c = cand["per_vertical"].get(v)
        b = (base["per_vertical"].get(v) if base else None)
        delta = (c - b) if (c is not None and b is not None) else None
        delta_str = (f"{(delta * 100):+.1f}pp" if delta is not None else "—")
        lines.append(
            f"| {v} | {_fmt_pct(c) if c is not None else '—'} "
            f"| {_fmt_pct(b) if b is not None else '—'} | {delta_str} |"
        )
    lines.append("")

    # --- axis MAE ---
    if cand["axis_mae"]:
        lines.append("## Per-axis MAE (lower is better)\n")
        lines.append("| axis | candidate | baseline | n |")
        lines.append("|---|---|---|---|")
        for axis, m in cand["axis_mae"].items():
            b_mae = ((base or {}).get("axis_mae") or {}).get(axis, {}).get("mae")
            b_str = f"{b_mae:.2f}" if b_mae is not None else "—"
            lines.append(f"| {axis} | {m['mae']:.2f} | {b_str} | {m['n']} |")
        lines.append("")

    # --- confusion at 0.65 keep-threshold ---
    lines.append("## Confusion @ threshold 0.65 (candidate)\n")
    decisions = ["keep", "maybe", "cull"]
    lines.append("| gt \\ pred | " + " | ".join(decisions) + " |")
    lines.append("| --- |" + " --- |" * len(decisions))
    cm = cand.get("confusion") or {}
    for t in decisions:
        row = [str(cm.get(t, {}).get(p, 0)) for p in decisions]
        lines.append(f"| **{t}** | " + " | ".join(row) + " |")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Compare two rescorer scores.csv outputs against a goldenset."
    )
    p.add_argument("candidate",   type=Path,
                   help="scores.csv from the candidate rescorer")
    p.add_argument("baseline",    type=Path, nargs="?", default=None,
                   help="optional baseline scores.csv for delta comparison")
    p.add_argument("--ground-truth", required=True, type=Path,
                   help="goldenset CSV with filename + manual_label columns")
    p.add_argument("--candidate-label", default="candidate")
    p.add_argument("--baseline-label",  default="baseline")
    p.add_argument("--out",         type=Path, default=None,
                   help="markdown output path (default: stdout)")
    p.add_argument("--json-out",    type=Path, default=None,
                   help="JSON metrics dump (for CI consumption)")
    p.add_argument("--tolerance",   type=float, default=0.01,
                   help="max acceptable recall@5 regression (default 1%%)")
    args = p.parse_args(argv)

    cand = evaluate(args.candidate, args.ground_truth, args.candidate_label)
    base = None
    if args.baseline:
        base = evaluate(args.baseline, args.ground_truth, args.baseline_label)

    md = render_markdown(cand, base)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"[eval] wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(md)

    if args.json_out:
        payload = {"candidate": cand, "baseline": base}
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Exit code: regression check
    if base is not None:
        c5 = cand["recall_at"].get("k=5", 0)
        b5 = base["recall_at"].get("k=5", 0)
        if c5 + args.tolerance < b5:
            print(
                f"[eval] REGRESSION: recall@5 {c5:.3f} < baseline {b5:.3f}"
                f" (tolerance {args.tolerance:.3f})",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
