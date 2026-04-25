"""Run pipeline against a labeled golden set and report accuracy.

Expected layout:
    golden/
        ground_truth.csv   # columns: filename, scene, manual_label, notes
        images/
            *.jpg / *.cr3 / ...

Usage:
    python scripts/eval_on_golden_set.py <golden_dir>

Prints a confusion matrix (rows=manual label, cols=pipeline decision) plus
per-class precision/recall and the list of misclassified files.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from pixcull.pipeline.orchestrator import run_pipeline

LABELS = ["keep", "maybe", "cull"]


def _confusion(pairs: list[tuple[str, str]]) -> pd.DataFrame:
    mat = {l: Counter() for l in LABELS}
    for truth, pred in pairs:
        if truth in mat:
            mat[truth][pred] += 1
    df = pd.DataFrame(mat).T.reindex(index=LABELS, columns=LABELS).fillna(0).astype(int)
    df.index.name = "truth\\pred"
    return df


def _pr(pairs: list[tuple[str, str]]) -> dict[str, tuple[float, float]]:
    by_class: dict[str, dict] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for truth, pred in pairs:
        for cls in LABELS:
            if pred == cls and truth == cls:
                by_class[cls]["tp"] += 1
            elif pred == cls and truth != cls:
                by_class[cls]["fp"] += 1
            elif pred != cls and truth == cls:
                by_class[cls]["fn"] += 1
    out = {}
    for cls, c in by_class.items():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        out[cls] = (p, r)
    return out


def main(golden_dir: Path) -> None:
    gt_path = golden_dir / "ground_truth.csv"
    images_dir = golden_dir / "images"
    if not gt_path.exists():
        print(f"ERROR: {gt_path} not found", file=sys.stderr)
        sys.exit(2)
    if not images_dir.exists():
        print(f"ERROR: {images_dir} not found", file=sys.stderr)
        sys.exit(2)

    gt = pd.read_csv(gt_path, comment="#")
    gt = gt[gt["manual_label"].isin(LABELS)]

    output = golden_dir / "_eval_output"
    run_pipeline(images_dir, output)
    pred = pd.read_csv(output / "scores.csv")[["filename", "decision"]]

    merged = gt.merge(pred, on="filename", how="inner")
    missing = set(gt["filename"]) - set(pred["filename"])
    extra = set(pred["filename"]) - set(gt["filename"])

    pairs = list(zip(merged["manual_label"], merged["decision"]))
    correct = sum(1 for t, p in pairs if t == p)
    total = len(pairs)

    print("\n=== Confusion matrix ===")
    print(_confusion(pairs).to_string())

    print("\n=== Per-class precision / recall ===")
    for cls, (p, r) in _pr(pairs).items():
        print(f"  {cls:<6}  P={p:.2f}  R={r:.2f}")

    print(f"\nOverall accuracy: {correct}/{total} = {correct/total:.1%}" if total else "No overlapping rows.")

    if missing:
        print(f"\nGT rows without predictions ({len(missing)}): {sorted(missing)[:10]}")
    if extra:
        print(f"Predictions without GT rows ({len(extra)}): {sorted(extra)[:10]}")

    mis = merged[merged["manual_label"] != merged["decision"]]
    if len(mis):
        print(f"\n=== Misclassified ({len(mis)}) ===")
        print(mis[["filename", "scene", "manual_label", "decision"]].to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: eval_on_golden_set.py <golden_dir>", file=sys.stderr)
        sys.exit(1)
    main(Path(sys.argv[1]).expanduser().resolve())
