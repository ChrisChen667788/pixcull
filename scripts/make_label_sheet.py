#!/usr/bin/env python3
"""v2.14-P0-2 — turn a pipeline ``scores.csv`` into a fill-in-the-blank
labeling sheet (CSV) you open in Excel / Numbers and type your verdict into.

Why a flat CSV: the web UI works too, but a spreadsheet is the fastest way to
rip through a few hundred frames — and the output is exactly the
``manual_label`` shape ``check_v1_2_trigger.py`` / the rescorer training path
already consume.

The sheet is sorted **uncertainty-first** by default: the frames whose
``score_final`` sits closest to 0.5 (the maybe/keep band where the model is
least sure and your judgment matters most) come first, so even a partial pass
labels the highest-value rows.

Columns:
    filename, scene, model_decision, score_final,
    tech/subj/comp/light/moment/aesthetic★  (model's per-axis stars, context),
    manual_label   <-- YOU fill: keep | maybe | cull  (leave blank to skip),
    notes          <-- optional free text

Usage:
    python scripts/make_label_sheet.py RUN/output/scores.csv -o label_sheet.csv
    python scripts/make_label_sheet.py RUN/output/scores.csv --n 400          # cap rows
    python scripts/make_label_sheet.py RUN/output/scores.csv --order scene    # group by scene
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

AXES = ("technical", "subject", "composition", "light", "moment", "aesthetic")
VALID = {"keep", "maybe", "cull", ""}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_rows(scores_csv: Path, order: str):
    with open(scores_csv, newline="", encoding="utf-8") as fh:
        src = list(csv.DictReader(fh))
    if not src:
        raise SystemExit(f"[make-label-sheet] {scores_csv} has no rows")

    out = []
    for r in src:
        sf = _f(r.get("score_final"))
        row = {
            "filename": r.get("filename") or r.get("path") or r.get("sha1") or "",
            "scene": r.get("scene") or "",
            "model_decision": r.get("decision") or "",
            "score_final": "" if sf is None else round(sf, 4),
            "manual_label": "",          # <-- you fill this
            "notes": "",
        }
        for a in AXES:
            v = _f(r.get(f"rubric_{a}_stars"))
            row[f"{a}★"] = "" if v is None else round(v, 1)
        # sort key: distance from the 0.5 decision boundary (None → last)
        row["_uncert"] = 99.0 if sf is None else abs(sf - 0.5)
        out.append(row)

    if order == "uncertain":
        out.sort(key=lambda x: x["_uncert"])
    elif order == "scene":
        out.sort(key=lambda x: (x["scene"], x["_uncert"]))
    elif order == "file":
        out.sort(key=lambda x: x["filename"])
    for r in out:
        r.pop("_uncert", None)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scores_csv", type=Path, help="pipeline scores.csv (any run)")
    ap.add_argument("-o", "--out", type=Path, default=Path("label_sheet.csv"))
    ap.add_argument("--n", type=int, default=0, help="cap to the first N rows (0 = all)")
    ap.add_argument("--order", choices=("uncertain", "scene", "file"),
                    default="uncertain", help="row order (default: uncertain-first)")
    args = ap.parse_args(argv)

    rows = build_rows(args.scores_csv, args.order)
    if args.n > 0:
        rows = rows[: args.n]

    cols = (["filename", "scene", "model_decision", "score_final"]
            + [f"{a}★" for a in AXES] + ["manual_label", "notes"])
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:  # BOM → Excel-friendly
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    n_scene = {}
    for r in rows:
        n_scene[r["scene"]] = n_scene.get(r["scene"], 0) + 1
    print(f"[make-label-sheet] wrote {len(rows)} rows → {args.out}")
    print(f"[make-label-sheet] by scene: {dict(sorted(n_scene.items()))}")
    print("[make-label-sheet] open in Excel/Numbers, fill the 'manual_label' "
          "column with keep / maybe / cull (blank = skip), save as CSV, hand back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
