"""v3.31 — every number the report shows, checked against the file on disk.

v2.95 found the run summary counting a list built during scoring while
the CSV was written from a dataframe the judge had since rewritten. Two
sources, one stale, and the console said "Keep=6" while every row in
scores.csv said cull.

That was one number. The report renders a dozen, and every one of them
is computed in memory beside a file that is the actual deliverable —
the file the photographer opens in Lightroom, hands to a client, and
still has in a year. When they disagree, the file is right and the
number on screen is the lie.

WHAT IS ALLOWED TO DIFFER

Some numbers legitimately drift, and pretending otherwise would make this
audit noisy enough to switch off:

* an annotation saved in this session but not yet flushed
* `elapsed_s` and the timestamps, which are about the run and not the rows
* anything derived from a file other than scores.csv — client picks live
  in their own file precisely so they do not overwrite the photographer's

So the audit names the fields it checks rather than diffing everything,
and a field nobody listed is a field nobody has thought about.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

#: summary key -> how to recompute it from the rows on disk.
#:
#: Counting functions, not a schema. The point is to recompute
#: independently, so a shared helper between the report and this file
#: would defeat it — that is exactly how v2.95 happened.
CHECKS: dict[str, Any] = {
    "n_total": lambda rows: len(rows),
    "n_keep": lambda rows: sum(1 for r in rows if r.get("decision") == "keep"),
    "n_maybe": lambda rows: sum(1 for r in rows if r.get("decision") == "maybe"),
    "n_cull": lambda rows: sum(1 for r in rows if r.get("decision") == "cull"),
}

#: Fields the report may show that this audit deliberately does not check,
#: each with the reason. A field in neither dict is an unexamined number.
NOT_CHECKED: dict[str, str] = {
    "n_human_labeled": "counts annotations.jsonl, not scores.csv",
    "n_human_decided": "same",
    "n_promotable": "same",
    "rescorer_active": "in-memory state of this run, not a row property",
    "rescorer_n_scored": "same",
    "rescorer_n_disagrees": "same",
    "rubric_axis_means": "a mean of floats; equality is the wrong test",
    "mode": "run metadata",
    "origin_folder": "run metadata",
    "started_at": "run metadata",
    "finished_at": "run metadata",
    "elapsed_s": "about the run, not the rows",
}


def rows_from_disk(output_dir: Path | str) -> list[dict]:
    path = Path(output_dir) / "scores.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def audit(summary: dict, output_dir: Path | str) -> dict[str, Any]:
    """Compare the rendered summary against scores.csv.

    Returns ``{"ok": bool, "mismatches": [...], "unexamined": [...]}``.
    ``unexamined`` is the half that keeps this honest as the report grows:
    a new number nobody classified is neither checked nor deliberately
    skipped, and silence about it would read as coverage.
    """
    rows = rows_from_disk(output_dir)
    mismatches = []
    for key, fn in CHECKS.items():
        if key not in summary:
            continue
        want = fn(rows)
        got = summary.get(key)
        try:
            same = int(got) == int(want)
        except (TypeError, ValueError):
            same = got == want
        if not same:
            mismatches.append({"field": key, "on_screen": got,
                               "in_the_file": want})
    unexamined = [k for k in summary
                  if k not in CHECKS and k not in NOT_CHECKED]
    return {"ok": not mismatches, "mismatches": mismatches,
            "unexamined": sorted(unexamined),
            "n_rows_on_disk": len(rows)}


def decision_counts(output_dir: Path | str) -> dict[str, int]:
    """What the file says, for a caller that wants the truth directly."""
    return dict(Counter(r.get("decision", "")
                        for r in rows_from_disk(output_dir)))
