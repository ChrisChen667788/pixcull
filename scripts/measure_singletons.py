#!/usr/bin/env python3
"""v3.97 — is a frame with no near-duplicate culled more often, and does
the scene classifier explain the block where it is not?

Each block is a contiguous run of frames the owner labelled blind. A
singleton is a frame `cluster_bursts` put in a cluster of one. For every
block this prints the singleton and in-burst cull rates and their odds
ratio three ways: as the run clustered them; with every frame under one
label at the thresholds of the scene the classifier gave most of them
(which removes the splits a changing label makes); and with every frame
under the block's real genre.

    scripts/measure_singletons.py \\
        --block "portrait, mid-shoot" RUN_DIR SHEET.json portrait \\
        --block ...

RUN_DIR holds `scores.csv` and `burst_embeddings.npz` (or has them under
`output/`). A block whose recorded `cluster_id` cannot be reproduced from
its own vectors is refused rather than measured: that is the check the
2026-09-13 attempt did not have, and it ran on the CLIP search vectors.

What it found the first time (2026-10-28, the owner's four blocks): the
mid-shoot portrait block, the one exception, was classified landscape on
119 of 150 frames. Re-clustered under portrait thresholds its singletons
go from 70 to 45 and none of the 45 was culled, against 15 of 105 in
bursts. The misclassification had raised its odds ratio toward 1, not
diluted it, so it does not explain the exception.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from scipy.stats import fisher_exact

from pixcull.detectors.duplicate import (
    WrongVectors, load_burst_vectors, recluster,
)
from pixcull.scoring.ground_truth import load_blind_sheet


def _find(run_dir: Path, name: str) -> Path:
    for p in (run_dir / name, run_dir / "output" / name):
        if p.is_file():
            return p
    raise FileNotFoundError(f"no {name} in {run_dir} or {run_dir / 'output'}")


def singleton_table(clustered: pd.DataFrame, labels: dict[str, str]) -> dict:
    """Cull rate for singletons and in-burst frames among the labelled
    frames, with the odds ratio and Fisher's exact p. Cluster sizes are
    counted over every frame in the block, labelled or not."""
    size = clustered.groupby("cluster_id")["cluster_id"].transform("size")
    d = clustered.assign(single=size.eq(1))
    d = d[d["filename"].isin(labels)]
    cull = d["filename"].map(labels).eq("cull")
    a = int((d.single & cull).sum())
    b = int((d.single & ~cull).sum())
    c = int((~d.single & cull).sum())
    e = int((~d.single & ~cull).sum())
    # Plain odds ratio. The 2026-09-13 table added 0.5 to every cell
    # (Haldane), which is why its landscape figure is 5.24 where this
    # gives 5.35 from the same counts.
    if not (a + b and c + e):
        # No singletons, or none in bursts, among the labelled frames:
        # there is nothing to compare, which is not an odds ratio of nan.
        odds = p = None
    else:
        odds, p = fisher_exact([[a, b], [c, e]])
    return {"n": len(d), "singletons": a + b, "single_cull": a / (a + b) if a + b else 0.0,
            "burst_cull": c / (c + e) if c + e else 0.0, "odds_ratio": odds, "p": p,
            "cells": (a, b, c, e)}


def _line(label: str, t: dict) -> str:
    head = (f"  {label:<44} singletons={t['singletons']:<4} "
            f"singleton cull {t['single_cull']:6.1%}  in-burst {t['burst_cull']:6.1%}  ")
    if t["odds_ratio"] is None:
        return head + "OR n/a (no singletons or no bursts among labelled frames)"
    return head + f"OR {t['odds_ratio']:5.2f}  p={t['p']:.3g}"


def measure_block(name: str, run_dir: Path, sheet: Path, genre: str) -> list[str]:
    scores = pd.read_csv(_find(run_dir, "scores.csv"))
    vectors = load_burst_vectors(_find(run_dir, "burst_embeddings.npz"))
    labels = {r["filename"]: str(r["overall_label"]).lower()
              for r in load_blind_sheet(sheet) if r.get("overall_label")}
    as_run, reproduced = recluster(scores, vectors)
    if not reproduced:
        raise WrongVectors(f"{name}: these vectors do not reproduce the run's "
                           f"cluster_id, so nothing measured on them is about it")
    order = as_run.sort_values(["datetime", "filename"])["scene"]
    switches = int((order != order.shift()).sum() - 1)
    scenes = Counter(scores["scene"])
    top, top_n = scenes.most_common(1)[0]
    out = [f"{name}: {len(scores)} frames, {sum(1 for f in scores['filename'] if f in labels)} "
           f"labelled, cull {sum(v == 'cull' for v in labels.values()) / max(len(labels), 1):.1%}; "
           f"classified {top} on {top_n}, label changes {switches} times"]
    out.append(_line("as run", singleton_table(as_run, labels)))
    out.append(_line(f"one label, {top} thresholds",
                     singleton_table(recluster(scores, vectors, scene=top)[0], labels)))
    if genre != top:
        out.append(_line(f"one label, {genre} thresholds (its genre)",
                         singleton_table(recluster(scores, vectors, scene=genre)[0], labels)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--block", nargs=4, action="append", required=True,
                    metavar=("NAME", "RUN_DIR", "SHEET", "GENRE"))
    a = ap.parse_args(argv)
    refused = 0
    for name, run_dir, sheet, genre in a.block:
        try:
            print("\n".join(measure_block(name, Path(run_dir).expanduser(),
                                          Path(sheet).expanduser(), genre)))
        except (WrongVectors, FileNotFoundError) as exc:
            print(f"{name}: not measured — {exc}")
            refused += 1
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
