#!/usr/bin/env python3
"""v3.4 — seed the critique exemplar bank from this tool's own best output.

AtelierJudge's System-1 half is exemplar retrieval: ground a subjective
judgement in a concrete reference before generating one. PixCull's prompt
grounds itself in the photography canon — Cartier-Bresson, the Zone
System — as *abstract principle text*. It has never shown the model a
finished critique.

WHERE THE EXEMPLARS COME FROM, AND WHY IT MATTERS

Not from the author. A critique written by someone who is not a working
photographer, injected into the prompt as an example of expertise, would
be this project teaching a model to imitate a non-expert — a quieter
version of the label-fabrication this repo refuses everywhere else.

They come instead from the tool's own cached output, ranked by the
`advice_depth` signals: distinct things named in the frame, observations
connected to consequences, no template hedging. This is best-of-N
distilled back into the prompt. It can reduce variance and it cannot
raise the ceiling — a model imitating its own best day does not become
better than its best day. Said plainly here so nobody mistakes the
mechanism for a quality claim.

The bank is per-vertical by design. It is seeded under `_default` because
the cache value did not record which shoot type each call was for; v3.4
starts recording it, so a later rebuild can segment properly.

    python scripts/build_critique_exemplars.py [--cache PATH] [--top N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pixcull.scoring.advice_depth import measure  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "pixcull" / "scoring" / "data" \
    / "critique_exemplars.json"

#: Long enough to show the form, short enough not to eat the prompt.
MIN_LEN, MAX_LEN = 150, 400


def main() -> int:
    from pixcull.scoring.vlm_judge import parse_vlm_response

    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path,
                    default=Path.home() / ".pixcull" / "cache" / "m3_verdicts.jsonl")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()
    if not args.cache.exists():
        print(f"no cache at {args.cache}", file=sys.stderr)
        return 1

    scored: list[tuple[tuple, str, str]] = []
    for line in args.cache.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        v = row.get("verdict") or row
        if not isinstance(v, dict) or v.get("raw_text") is None:
            continue
        parsed = parse_vlm_response(v.get("raw_text") or "")
        if not isinstance(parsed, dict):
            continue
        text = (parsed.get("reading") or "").strip()
        if not (MIN_LEN <= len(text) <= MAX_LEN):
            continue
        m = measure(text)
        if m.hedges:
            continue          # a template tell disqualifies an exemplar
        vertical = str(v.get("vertical") or v.get("scene") or "").strip()
        scored.append(((-m.n_subjects, -m.n_connectives, -m.length),
                       vertical or "_default", text))

    scored.sort(key=lambda t: t[0])
    banks: dict[str, list] = {}
    for _, vertical, text in scored:
        bank = banks.setdefault(vertical, [])
        if len(bank) >= args.top:
            continue
        bank.append({
            "reading": text,
            "provenance": "cache-selected",
            "note": ("this tool's own output, ranked by advice_depth "
                     "signals; a demonstration of form, not of expertise"),
        })

    payload = {
        "version": 1,
        "selection": {
            "ranked_by": ["n_subjects", "n_connectives", "length"],
            "excluded": "any text carrying an advice_depth hedge",
            "length_window": [MIN_LEN, MAX_LEN],
            "candidates": len(scored),
        },
        "exemplars": banks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} — "
          + ", ".join(f"{k}:{len(v)}" for k, v in banks.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
