#!/usr/bin/env python3
"""v3.1 — reproduce the advice-depth baseline from the M3 cache.

`docs/ADVICE-DEPTH-BASELINE.md` was assembled by hand once. Its numbers
were right, and they drifted the moment the cache grew — which is how a
baseline stops being something a regression can trip over.

This script rebuilds it. It reads the local verdict cache, splits the two
call types apart (the split v2.81 had to make by hand after publishing a
figure that averaged them), and reports each text field separately and by
name. Nothing here calls an API or spends anything.

    python scripts/measure_advice_depth.py [--cache PATH] [--json]

The two call types are told apart by `raw_text`: advice calls store the
model's whole reply so the nine-key shape can be re-parsed, verdict calls
do not. Advice fields are extracted with the product's own
`parse_vlm_response`, not a private parser, so a change to how replies
are read shows up here instead of quietly diverging.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pixcull.scoring.advice_depth import summarise  # noqa: E402

#: Advice fields worth measuring, in the order the baseline reports them.
#: `reading` is the deep critique; the other two are reported because a
#: change that improves `reading` by moving text out of `alternative`
#: would otherwise look like a win.
ADVICE_FIELDS = ("reading", "alternative", "rationale")


def load(cache: Path) -> tuple[list, dict[str, list]]:
    from pixcull.scoring.vlm_judge import parse_vlm_response

    verdict: list[str | None] = []
    advice: dict[str, list[str | None]] = {f: [] for f in ADVICE_FIELDS}
    for line in cache.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        v = row.get("verdict") or row
        if not isinstance(v, dict):
            continue
        if v.get("raw_text") is not None:
            parsed = parse_vlm_response(v.get("raw_text") or "")
            parsed = parsed if isinstance(parsed, dict) else {}
            for f in ADVICE_FIELDS:
                advice[f].append(parsed.get(f))
        else:
            verdict.append(v.get("overall_rationale"))
    return verdict, advice


def _row(s: dict) -> str:
    n = max(s["n"], 1)
    return (
        f"{s['field']:<28} n={s['n']:<5d} empty={100*s['empty']/n:>5.1f}% "
        f"med={s['median_length']:<5d} sees={100*s['sees_the_picture_rate']:>5.1f}% "
        f"argues={100*s['argues_rate']:>5.1f}% both={100*s['both_rate']:>5.1f}% "
        f"hedged={100*s['hedged_rate']:>5.1f}% subj={s['mean_subjects']:.2f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path,
                    default=Path.home() / ".pixcull" / "cache" / "m3_verdicts.jsonl")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.cache.exists():
        print(f"no cache at {args.cache} — nothing to measure", file=sys.stderr)
        return 1

    verdict, advice = load(args.cache)
    out = [summarise(verdict, field="verdict.overall_rationale")]
    out += [summarise(advice[f], field=f"advice.{f}") for f in ADVICE_FIELDS]

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for s in out:
            print(_row(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
