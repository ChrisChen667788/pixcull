#!/usr/bin/env python3
"""v3.96 — what the labels a personalisation figure was computed over did to it.

v3.29 taught the taste profile to leave two kinds of correction out: burst
siblings rejected in the compare modal, and corrections synced from another
photographer. Its charter asked for `evaluate()` with and without those rows,
so that if the difference was material every earlier figure could say it was
computed over polluted labels. This runs that measurement on any label set,
and prints it per subset so a figure can be traced to the rows behind it.

Two input shapes:

    # a corrections file (JSONL, each record with its own `axes`):
    # evaluate() with the excluded rows kept, and without them
    scripts/measure_label_provenance.py --corrections corrections.jsonl

    # a label sheet joined to the scores it was made from, optionally
    # split into named subsets (each a CSV whose `filename`s pick rows)
    scripts/measure_label_provenance.py --labels training.csv \\
        --scores scores.csv --subset endorsed=a.csv --subset v011=b.csv

What it found the first time (2026-10-28, the owner's own files): the
published 0.801 vs 0.799 reproduces exactly from the 608-row sheet, and
neither of the excluded kinds occurs in it or in any label set on that
machine. The sheet is two sets with opposite results: on the 408 rows the
owner endorsed with the verdict on screen, personalisation scores below
generic; on the 200 rows that carry real disagreements, above it.
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

from pixcull.scoring.personal_learn import (
    AXES, DECISIONS, Example, _f, evaluate, load_corrections,
)


def _read_csv(path) -> list[dict]:
    # utf-8-sig: these sheets go through Excel, which adds a BOM that
    # renames the first column and makes every lookup miss.
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def examples_from_sheet(labels, scores) -> tuple[list[tuple[str, Example]], list[str]]:
    """Join a label sheet (`filename`, `manual_label`) to the rubric stars
    in a scores CSV. Returns (filename, example) pairs and the filenames
    that could not be joined, so a short sample says why it is short."""
    stars = {r["filename"]: r for r in _read_csv(scores) if r.get("filename")}
    out, unjoined = [], []
    for r in _read_csv(labels):
        fn = (r.get("filename") or "").strip()
        d = (r.get("manual_label") or "").strip().lower()
        s = stars.get(fn)
        if s is None or d not in DECISIONS:
            unjoined.append(fn)
            continue
        out.append((fn, Example(axes={a: _f(s.get(f"rubric_{a}_stars"))
                                      for a in AXES}, decision=d)))
    return out, unjoined


def reordered(exs: list[Example], n: int) -> list[float]:
    """Δ under `n` seeded reorderings of the same examples.

    Stride folds are drawn by position, so one ordering of a file is one
    draw of the folds, and a figure from it can be an accident of how the
    file happened to be sorted. Measured on the owner's 158 blind
    corrections: +0.041 as the file lies, anywhere from -0.279 to +0.065
    across 200 reorderings, mean -0.048. Whole-shoot folds do not depend
    on order and are not reordered."""
    out = []
    for seed in range(n):
        xs = exs[:]
        random.Random(seed).shuffle(xs)
        ev = evaluate(xs)
        if not ev.get("refused"):
            out.append(ev["delta"])
    return out


def _row(name: str, exs: list[Example], reorder: int = 0) -> str:
    ev = evaluate(exs)
    kinds = Counter(e.decision for e in exs)
    mix = " ".join(f"{k}={kinds[k]}" for k in DECISIONS if kinds[k])
    if ev.get("refused"):
        return f"{name:<28} n={ev['n']:<4} {mix:<28} not measured: {ev['refused']}"
    fd = ev["fold_deltas"]
    held = "whole shoots" if ev["grouped"] else "stride"
    line = (f"{name:<28} n={ev['n']:<4} {mix:<28} generic {ev['generic_f1']:.3f}  "
            f"personal {ev['personal_f1']:.3f}  Δ {ev['delta']:+.3f}  "
            f"folds {min(fd):+.3f}…{max(fd):+.3f} ({ev['folds']}, {held})")
    if reorder and not ev["grouped"]:
        ds = reordered(exs, reorder)
        line += (f"  | reordered ×{len(ds)}: Δ {min(ds):+.3f}…{max(ds):+.3f}, "
                 f"mean {statistics.mean(ds):+.3f}")
    return line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corrections", type=Path)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--scores", type=Path)
    ap.add_argument("--subset", action="append", default=[],
                    metavar="NAME=CSV")
    ap.add_argument("--reorder", type=int, default=200, metavar="N",
                    help="also report Δ under N seeded reorderings of each "
                         "stride-folded set (0 to skip)")
    a = ap.parse_args(argv)
    if not a.corrections and not (a.labels and a.scores):
        ap.error("give --corrections, or --labels with --scores")

    if a.corrections:
        left_out: Counter = Counter()
        without = load_corrections(a.corrections, excluded=left_out)
        with_ = load_corrections(a.corrections, include_excluded=True)
        print(f"{a.corrections.name}: v3.29 leaves out "
              + (", ".join(f"{n} {k}" for k, n in sorted(left_out.items()))
                 or "nothing"))
        print(_row("with the excluded rows", with_, a.reorder))
        print(_row("without them (as learned)", without, a.reorder))
        # Held out by whole shoot when the file says which shoot; the
        # stride figure beside it is the one comparable with a sheet.
        print(_row("without them, stride folds",
                   [Example(axes=e.axes, decision=e.decision) for e in without],
                   a.reorder))

    if a.labels:
        pairs, unjoined = examples_from_sheet(a.labels, a.scores)
        if unjoined:
            print(f"{a.labels.name}: {len(unjoined)} row(s) not joined to a score "
                  f"or not labelled keep/maybe/cull")
        print(_row(a.labels.name, [e for _, e in pairs], a.reorder))
        for spec in a.subset:
            name, _, path = spec.partition("=")
            pick = {r.get("filename") for r in _read_csv(path)}
            print(_row(f"  {name}", [e for fn, e in pairs if fn in pick], a.reorder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
