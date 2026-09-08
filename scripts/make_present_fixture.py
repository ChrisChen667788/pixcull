#!/usr/bin/env python3
"""Build the hermetic run fixture `tests/fixtures/present_run`.

`tests/test_client_present.py` guards the one mode where a bug is
visible to the photographer's *client*: Shift+C hides every verdict,
score and star so a laptop can be turned around at a delivery meeting.
Four of its tests need a served run with more than ten cards on screen,
and they had been pointed at `/tmp/pixcull_perf/perf5069` — a 5,069-row
run that exists on one laptop. Everywhere else, including CI, they
skipped, which is the fourth or fifth time this repository has shipped a
test that reports green by not running.

So the fixture is generated rather than measured: this expands the six
committed `smoke_run` rows into twenty-four, varying filename, decision,
score and stars deterministically. No images, no models, no network —
the probe reads text nodes, and a card with a broken thumbnail still
renders every number the client must not see.

The realistic run still wins when it is there: the test prefers
`PIXCULL_TEST_DEMO_ROOT` / `PIXCULL_TEST_RUN` and falls back to this.

Regenerate with:  python scripts/make_present_fixture.py
Checked by:       tests/test_client_present.py::test_the_fixture_matches_its_generator
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tests" / "fixtures" / "smoke_run"
DST = ROOT / "tests" / "fixtures" / "present_run"

#: Enough that the grid is a grid. The tests assert >10 cards and >50
#: visible judgement strings; six rows gave neither.
N_ROWS = 24

#: Cycled so the fixture exercises all three verdict colours and the
#: client-present mode has something of each kind to hide.
_DECISIONS = ("keep", "maybe", "cull")


def _rows() -> list[dict]:
    base = list(csv.DictReader((SRC / "output" / "scores.csv").open()))
    if not base:
        raise SystemExit("smoke_run fixture is empty")
    out = []
    for i in range(N_ROWS):
        row = dict(base[i % len(base)])
        row["filename"] = f"IMG_{i:04d}.jpg"
        row["path"] = f"IMG_{i:04d}.jpg"
        row["decision"] = _DECISIONS[i % 3]
        # Spread the score across the band so the grid is not 24 copies
        # of one number, and keep two decimals — the probe looks for
        # `\d\.\d\d`, and a client reading 0.42 off the screen is the
        # exact leak these tests exist to catch.
        score = 0.30 + (i % 12) * 0.055
        row["score_final"] = f"{score:.6f}"
        row["reason"] = f"score={score:.2f}"
        for j, axis in enumerate(("technical", "subject", "composition",
                                  "light", "moment", "aesthetic")):
            col = f"rubric_{axis}_stars"
            if col in row:
                row[col] = f"{1.0 + ((i + j) % 5) * 0.95:.2f}"
        out.append(row)
    return out


def main(argv: list[str]) -> int:
    if not (SRC / "output" / "scores.csv").is_file():
        raise SystemExit(f"missing source fixture: {SRC}")
    (DST / "output").mkdir(parents=True, exist_ok=True)
    rows = _rows()
    with (DST / "output" / "scores.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # rubric.jsonl — one line per row, same filenames, so the inspector
    # has stars to render rather than falling back to an empty pane.
    src_rubric = SRC / "output" / "rubric.jsonl"
    base_rubric = ([json.loads(l) for l in
                    src_rubric.read_text(encoding="utf-8").splitlines() if l.strip()]
                   if src_rubric.is_file() else [])
    if base_rubric:
        with (DST / "output" / "rubric.jsonl").open("w", encoding="utf-8") as fh:
            for i in range(N_ROWS):
                rec = dict(base_rubric[i % len(base_rubric)])
                rec["filename"] = f"IMG_{i:04d}.jpg"
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    src_manifest = SRC / "output" / "manifest.json"
    if src_manifest.is_file():
        shutil.copyfile(src_manifest, DST / "output" / "manifest.json")

    print(f"[fixture] wrote {DST} ({N_ROWS} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
