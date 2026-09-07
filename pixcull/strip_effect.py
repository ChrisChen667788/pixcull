"""v3.34 — does the burst face strip change what the photographer does?

v3.12 built a strip that shows the same face across a burst, and its
measure is the override rate on burst winners with and without it.  That
is a question about a person's behaviour, and no amount of code answers
it — but the answer can fall out of ordinary use instead of requiring a
study.

INSTRUMENTING A PERSON IS NOT INSTRUMENTING A MODEL

Off unless asked for, written to the run's own directory, never
transmitted, and readable as plain JSONL by the person it is about.  A
test asserts this module contains no HTTP client of any kind.

AND IT REFUSES TO REPORT A RATE ON TWO SESSIONS

A percentage printed over n=1 is how a number gets quoted six months
later with the sample size lost.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FILENAME = "strip_effect.jsonl"
SCHEMA = "pixcull.strip_effect/v1"
ENV_FLAG = "PIXCULL_MEASURE_STRIP"

#: Below this many observations on either side, no rate is reported.
MIN_PER_ARM = 5


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "0") == "1"


def record(output_dir: Path | str, *, cluster: str, strip_open: bool,
           overrode: bool) -> None:
    """One burst reviewed. Silent when the measurement is off."""
    if not enabled():
        return
    path = Path(output_dir) / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"schema": SCHEMA, "cluster": str(cluster),
                             "strip_open": bool(strip_open),
                             "overrode": bool(overrode)},
                            ensure_ascii=False) + "\n")


def _load(output_dir: Path | str) -> list[dict]:
    path = Path(output_dir) / FILENAME
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("schema") == SCHEMA:
            out.append(rec)
    return out


def rates(output_dir: Path | str) -> dict:
    """Counts on both sides, and a verdict that is usually a refusal."""
    recs = _load(output_dir)
    with_s = [r for r in recs if r.get("strip_open")]
    without = [r for r in recs if not r.get("strip_open")]

    def _arm(rows):
        return {"n": len(rows),
                "overrides": sum(1 for r in rows if r.get("overrode"))}

    a, b = _arm(with_s), _arm(without)
    if a["n"] < MIN_PER_ARM or b["n"] < MIN_PER_ARM:
        verdict = (f"too few observations — need {MIN_PER_ARM} bursts on "
                   f"each side, have {a['n']} with the strip and {b['n']} "
                   f"without")
    else:
        verdict = (f"with {a['overrides']}/{a['n']}, "
                   f"without {b['overrides']}/{b['n']}")
    return {"with_strip": a, "without_strip": b, "verdict": verdict}
