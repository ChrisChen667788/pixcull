#!/usr/bin/env python3
"""v3.51 — every skip in a CI run has to be one somebody decided.

Five times in ten versions the same defect: a test that exists, is
committed, is counted in the suite total, and does not run where it
matters, so the tick is green and nothing was checked. ffmpeg in v2.45
(re-found in v3.48), exiftool in v3.41, the whole browser lane in v3.42,
the design-token ratchet in v3.46, the packaged rescorer in v3.49.

Every one of them was found by tripping over it. This makes the census
routine instead: read the `SKIPPED` lines a run actually printed, match
each reason against a committed ledger, and fail when a reason has no
disposition. Not a source grep — what skips on a maintainer's laptop and
what skips on a runner are different lists, which is the whole reason
the previous five went unnoticed.

Usage
=====
    pytest ... -rs | tee run.txt
    python scripts/audit_ci_skips.py run.txt

Ledger: ``tests/ci_skip_dispositions.tsv``, one row per reason PATTERN
(not per test id — a rename must not rewrite the ledger):

    pattern <TAB> disposition <TAB> note

``covered-elsewhere``  another lane runs it; the note names which
``deliberate``         it should not run here, and the note says why
``owner-blocked``      needs a person; the note names the ask
``gap``                it should run and does not; the note names what
                       closes it
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "tests" / "ci_skip_dispositions.tsv"

DISPOSITIONS = {"covered-elsewhere", "deliberate", "owner-blocked", "gap"}

#: `SKIPPED [3] tests/test_face.py:122: MediaPipe / model weights unavailable`
SKIP_LINE = re.compile(r"^SKIPPED \[\d+\] (\S+?):\d+: (.*)$", re.M)


def reasons(report: str) -> list[tuple[str, str]]:
    """(test file, reason) for every skip the run printed."""
    return [(m.group(1), m.group(2).strip()) for m in SKIP_LINE.finditer(report)]


def ledger() -> list[list[str]]:
    rows = []
    for raw in LEDGER.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 3:
            raise SystemExit(f"malformed ledger row: {raw[:70]!r}")
        rows.append([p.strip() for p in parts])
    return rows


def unmatched(report: str) -> list[str]:
    rows = ledger()
    out = []
    for where, reason in reasons(report):
        if not any(pat.lower() in reason.lower() for pat, _, _ in rows):
            out.append(f"{where}: {reason}")
    return sorted(set(out))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    report = Path(argv[1]).read_text(encoding="utf-8", errors="replace")

    for pat, disp, note in ledger():
        if disp not in DISPOSITIONS:
            print(f"[skip-audit] unknown disposition {disp!r} for {pat!r}",
                  file=sys.stderr)
            return 2

    found = reasons(report)
    if not found:
        # A report with no SKIPPED lines is either a clean run or a run
        # invoked without -rs. The second is indistinguishable from the
        # first here, and silently passing on it is how this whole class
        # of defect works, so say which one to expect.
        print("[skip-audit] no SKIPPED lines in the report — if the run "
              "was not invoked with -rs, this audit checked nothing",
              file=sys.stderr)
        return 0

    bad = unmatched(report)
    if bad:
        print(f"[skip-audit] FAIL — {len(bad)} skip reason(s) with no "
              f"disposition in {LEDGER.relative_to(ROOT)}:", file=sys.stderr)
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        print("[skip-audit] add a row saying whether it is covered "
              "elsewhere, deliberate, owner-blocked, or a gap — and for a "
              "gap, what closes it", file=sys.stderr)
        return 2

    print(f"[skip-audit] OK — {len(found)} skip(s), every reason "
          f"dispositioned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
