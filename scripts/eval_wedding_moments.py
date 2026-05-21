"""P-PRO-4.2 — wedding-moment classifier eval helper.

Walks a folder of wedding JPGs, runs the CLIP zero-shot moment
classifier, and emits:

  · `predictions.csv`  — one row per photo with top-3 moments
                         + probs + abstain flag
  · stdout report       — distribution + coverage analysis

Usage:
    python scripts/eval_wedding_moments.py <folder> [--out OUT_DIR]

For golden-set work the photographer hand-labels the
"ground_truth_moment" column in predictions.csv (open in
Numbers / Excel), then re-runs with:

    python scripts/eval_wedding_moments.py <folder> --confusion predictions.csv

to get the confusion matrix + per-class precision/recall.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image


def _photo_paths(folder: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in exts)


def predict(folder: Path, out_dir: Path) -> Path:
    """Run the classifier + write predictions.csv."""
    from pixcull.detectors.wedding_moment import WeddingMomentDetector
    from pixcull.scoring.wedding_moments import (
        WEDDING_MOMENTS, moment_label_zh,
    )

    paths = _photo_paths(folder)
    if not paths:
        sys.exit(f"no photos in {folder}")
    print(f"scanning {len(paths)} photos in {folder} ...", file=sys.stderr)

    det = WeddingMomentDetector()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "predictions.csv"

    keys = [m.key for m in WEDDING_MOMENTS]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "filename", "predicted_moment", "predicted_moment_zh",
            "top1_prob", "runner_prob", "margin",
            "abstained", "ground_truth_moment",
            "top1_key", "top2_key", "top3_key",
        ])
        for i, p in enumerate(paths):
            try:
                img = Image.open(p).convert("RGB")
                res = det.analyze(img)
            except Exception as exc:
                print(f"  [{i+1}/{len(paths)}] {p.name}: ERROR {exc}",
                      file=sys.stderr)
                continue
            moment = res.extras.get("wedding_moment") or "unknown"
            probs  = res.extras.get("wedding_moment_probs") or {}
            top_p  = res.metrics.get("wedding_moment_confidence") or 0.0
            ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
            top1, top2, top3 = (
                ranked[0][0] if len(ranked) >= 1 else "",
                ranked[1][0] if len(ranked) >= 2 else "",
                ranked[2][0] if len(ranked) >= 3 else "",
            )
            runner = ranked[1][1] if len(ranked) >= 2 else 0.0
            margin = (top_p - runner)
            w.writerow([
                p.name, moment, moment_label_zh(moment),
                f"{top_p:.4f}", f"{runner:.4f}", f"{margin:.4f}",
                "abstained" if "moment_uncertain" in res.flags else "",
                "",  # ground_truth_moment — left blank for human fill
                top1, top2, top3,
            ])
            if (i + 1) % 10 == 0:
                print(f"  [{i+1}/{len(paths)}] {p.name} → {moment} ({top_p:.2f})",
                      file=sys.stderr)
    print(f"\nwrote {out_csv}\n", file=sys.stderr)
    return out_csv


def report(out_csv: Path) -> None:
    from pixcull.scoring.wedding_moments import (
        mandatory_moment_keys, moment_label_zh,
    )
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    n = len(rows)
    if not n:
        print("  (no rows)"); return

    moments  = Counter(r["predicted_moment"] for r in rows)
    abstain  = sum(1 for r in rows if r["abstained"])
    margins  = [float(r["margin"]) for r in rows]

    print(f"# Moment distribution ({n} photos)\n")
    for key, cnt in moments.most_common():
        label = moment_label_zh(key)
        pct = 100.0 * cnt / n
        bar = "█" * int(pct / 2)
        print(f"  {key:24s} {label:8s}  {cnt:3d}  {pct:5.1f}%  {bar}")
    print(f"\n  abstained (margin < 0.05): {abstain} ({100.0*abstain/n:.1f}%)")
    print(f"  median margin: {sorted(margins)[n//2]:.4f}")

    # Coverage check on mandatory moments
    print("\n# Mandatory coverage")
    mand = mandatory_moment_keys()
    for k in mand:
        c = moments.get(k, 0)
        flag = "✓" if c > 0 else "✗ MISSING"
        print(f"  {k:24s} {moment_label_zh(k):8s} {c:3d}   {flag}")


def confusion(predictions_csv: Path) -> None:
    """If the user has hand-labeled ground_truth_moment, compute
    confusion + per-class precision/recall."""
    from pixcull.scoring.wedding_moments import (
        known_moment_keys, moment_label_zh,
    )
    rows = list(csv.DictReader(predictions_csv.open(encoding="utf-8")))
    labeled = [r for r in rows if (r.get("ground_truth_moment") or "").strip()]
    if not labeled:
        sys.exit("no rows with ground_truth_moment filled — open "
                 f"{predictions_csv} in a spreadsheet, label some "
                 "rows, then re-run.")
    print(f"# Confusion ({len(labeled)} labeled / {len(rows)} total)")

    keys = known_moment_keys()
    matrix: dict[tuple[str, str], int] = defaultdict(int)
    for r in labeled:
        gt = (r["ground_truth_moment"] or "").strip()
        pr = r["predicted_moment"]
        matrix[(gt, pr)] += 1

    # Print the confusion matrix (compact: only non-zero cells)
    gts = sorted({gt for gt, _ in matrix})
    print("\n  gt → predicted (only non-zero cells):")
    correct = 0
    total = sum(matrix.values())
    for gt in gts:
        preds = [(pr, c) for (g, pr), c in matrix.items() if g == gt]
        preds.sort(key=lambda kv: -kv[1])
        line = "  ".join(f"{pr}={c}" for pr, c in preds)
        n_gt = sum(c for _, c in preds)
        if any(pr == gt for pr, _ in preds):
            correct += next(c for pr, c in preds if pr == gt)
        flag = "✓" if any(pr == gt and c >= n_gt//2 for pr, c in preds) else "✗"
        print(f"  {flag} {gt:22s}  ({n_gt}x): {line}")
    print(f"\n  overall accuracy: {correct}/{total} = {100.0*correct/total:.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Wedding moment classifier eval helper")
    ap.add_argument("folder", type=Path, nargs="?",
                    help="Folder of wedding JPGs.")
    ap.add_argument("--out", type=Path, default=Path("out_wedding_eval"),
                    help="Output directory for predictions.csv.")
    ap.add_argument("--confusion", type=Path, default=None,
                    help="Skip prediction; just compute confusion "
                         "from an already-labeled predictions.csv.")
    ap.add_argument("--report-only", type=Path, default=None,
                    help="Skip prediction; just print distribution "
                         "from an existing predictions.csv.")
    args = ap.parse_args()

    if args.confusion:
        confusion(args.confusion)
        return
    if args.report_only:
        report(args.report_only)
        return
    if not args.folder:
        ap.print_help(sys.stderr)
        sys.exit(2)

    out_csv = predict(args.folder, args.out)
    report(out_csv)


if __name__ == "__main__":
    main()
