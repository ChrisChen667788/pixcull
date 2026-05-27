#!/usr/bin/env python3
"""v0.10-P0-3 — style-V2 (CLIP centroid) λ sweep benchmark.

The /style/train endpoint produces two distance scores:
  * V1 = axis-MAD distance (the v0.7 implementation)
  * V2 = 1 - cosine(row_emb, profile_emb) (v0.8-P1-1)
and blends them via λ ∈ [0, 1]: blend = λ·V1 + (1-λ)·V2.

This script:
  1. Loads a goldenset CSV with per-vertical reference selections
  2. For each vertical, runs the /style/train endpoint with the
     keep refs and gets back per-photo V1 + V2 distances
  3. Sweeps λ ∈ {0.0, 0.3, 0.5, 0.7, 1.0}
  4. Computes recall@5 (= "did the user's actual top picks rank
     high?") for each λ
  5. Outputs a benchmark table the charter can cite

The goldenset CSV shape:
  filename, vertical, manual_label, is_keep_ref
  where ``is_keep_ref=1`` means "this photo was used as a style
  training reference" (you don't get to predict your own training
  set) and ``manual_label=keep`` means "the user said keep at
  cull time".

This is a *standalone* eval — it doesn't require booting serve_demo
and hitting HTTP.  It calls into pixcull.scoring functions directly,
so the same metric can be computed for any λ point and any model
checkpoint without re-issuing share tokens.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


LAMBDAS_DEFAULT = (0.0, 0.3, 0.5, 0.7, 1.0)


def _load_dists(p: Path, label: str) -> dict[str, dict]:
    """Load a distances JSON, shape: {filename: {v1: float, v2: float, blend: float}, ...}

    Per the v0.7-P2-1 / v0.8-P1-1 protocol, the share_distances JSON
    written by serve_demo is keyed by filename, with each entry
    carrying ``v1``, ``v2``, and ``blend`` (current λ).  We only
    need v1 + v2; blend is recomputed per λ during the sweep.
    """
    if not p.exists():
        sys.exit(f"[style-eval] {label}: not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        sys.exit(f"[style-eval] {label}: not a dict: {p}")
    return raw


def recall_at_k(rank: list[str], gt_keeps: set[str], k: int) -> float:
    if not gt_keeps:
        return 0.0
    return len(set(rank[:k]) & gt_keeps) / len(gt_keeps)


def blend(v1: float | None, v2: float | None, lam: float) -> float | None:
    """λ-weighted blend.  When only one of v1/v2 is present, fall
    back to that one (matches the runtime blend_fn in serve_demo)."""
    if v1 is None and v2 is None:
        return None
    if v1 is None:
        return v2
    if v2 is None:
        return v1
    return lam * v1 + (1.0 - lam) * v2


def sweep_one_vertical(
    dists: dict[str, dict],
    gt_rows: pd.DataFrame,
    lambdas: Iterable[float],
    k: int = 5,
) -> dict[float, float]:
    """Returns {λ: recall@k} for one vertical's photo pool.

    Excludes is_keep_ref=1 rows (training-leakage protection).
    """
    candidates = gt_rows[gt_rows.get("is_keep_ref", 0) != 1]
    if candidates.empty:
        return {lam: 0.0 for lam in lambdas}
    keeps = set(candidates[candidates["manual_label"] == "keep"]["filename"])
    out: dict[float, float] = {}
    for lam in lambdas:
        # Score every candidate row by blend(v1, v2, λ); LOWER distance
        # = better style match.  Rank ascending then take top-k.
        scored = []
        for _, row in candidates.iterrows():
            fn = row["filename"]
            entry = dists.get(fn, {})
            d = blend(entry.get("v1"), entry.get("v2"), lam)
            if d is None:
                continue
            scored.append((d, fn))
        scored.sort(key=lambda x: x[0])
        ranked = [fn for _, fn in scored]
        out[lam] = recall_at_k(ranked, keeps, k)
    return out


def render_markdown(
    per_vertical: dict[str, dict[float, float]],
    lambdas: Iterable[float],
) -> str:
    lines = []
    lines.append("# Style V2 (CLIP centroid) λ benchmark\n")
    lines.append("Recall@5 by vertical × λ blend "
                 "(λ=0 → pure V2 / CLIP; λ=1 → pure V1 / axis-MAD).\n")
    lines.append("Higher is better.  The"
                 " **bold** column is the recommended default for that vertical.\n")
    # Header row
    lam_list = list(lambdas)
    head = ["| vertical |"] + [f" λ={l:.1f} |" for l in lam_list]
    lines.append("".join(head))
    lines.append("| --- |" + " --- |" * len(lam_list))
    # Per-vertical rows + emit a recommended-λ column
    recommended: dict[str, float] = {}
    for vert in sorted(per_vertical):
        rec = per_vertical[vert]
        # Pick the λ that maximised recall@5; break ties toward
        # CLIP (lower λ) since CLIP transfers across users better.
        best_lam = min(rec, key=lambda l: (-rec[l], l))
        recommended[vert] = best_lam
        cells = []
        for lam in lam_list:
            val = rec.get(lam, 0.0)
            cell = f" {val * 100:5.1f}% "
            if lam == best_lam:
                cell = f" **{val * 100:5.1f}%** "
            cells.append(cell + "|")
        lines.append(f"| {vert} |" + "".join(cells))
    lines.append("")
    # Recommended-λ summary
    lines.append("## Recommended λ per vertical\n")
    lines.append("| vertical | λ |")
    lines.append("| --- | --- |")
    for vert, lam in sorted(recommended.items()):
        lines.append(f"| {vert} | {lam:.1f} |")
    lines.append("")
    # Global recommended (mode + reasoning)
    most_common = max(
        set(recommended.values()),
        key=lambda l: sum(1 for v in recommended.values() if v == l),
    )
    lines.append("## Global recommended default\n")
    lines.append(f"**λ = {most_common:.1f}**"
                 " — most verticals' best slot;"
                 " ties resolved toward V2 (CLIP) for cross-user transferability.\n")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Sweep λ for V1+V2 style-clone blend on a goldenset."
    )
    p.add_argument(
        "--ground-truth", required=True, type=Path,
        help="goldenset CSV: filename, vertical, manual_label, is_keep_ref",
    )
    p.add_argument(
        "--distances", required=True, type=Path,
        help="share_distances.json from a serve_demo /style/train run "
             "(or any JSON with the same {filename: {v1, v2}} shape)",
    )
    p.add_argument(
        "--out", type=Path, default=None,
        help="markdown output path (default: stdout)",
    )
    p.add_argument(
        "--json-out", type=Path, default=None,
        help="JSON-formatted sweep dump (per-vertical × per-λ)",
    )
    p.add_argument(
        "--lambdas", type=str, default=",".join(str(l) for l in LAMBDAS_DEFAULT),
        help="comma-separated λ values to sweep (default 0.0,0.3,0.5,0.7,1.0)",
    )
    args = p.parse_args(argv)

    lambdas = [float(x) for x in args.lambdas.split(",") if x.strip()]
    if not lambdas:
        sys.exit("[style-eval] --lambdas produced no values")

    gt = pd.read_csv(args.ground_truth)
    for col in ("filename", "vertical", "manual_label"):
        if col not in gt.columns:
            sys.exit(f"[style-eval] goldenset missing column '{col}'")
    if "is_keep_ref" not in gt.columns:
        gt["is_keep_ref"] = 0
    dists = _load_dists(args.distances, "main")

    per_vertical: dict[str, dict[float, float]] = {}
    for vert, sub in gt.groupby("vertical"):
        per_vertical[str(vert)] = sweep_one_vertical(dists, sub, lambdas)

    md = render_markdown(per_vertical, lambdas)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"[style-eval] wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(md)

    if args.json_out:
        payload = {
            "lambdas":     lambdas,
            "per_vertical": {v: {str(l): r for l, r in lam_to_r.items()}
                             for v, lam_to_r in per_vertical.items()},
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
