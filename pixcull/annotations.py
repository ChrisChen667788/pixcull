"""Where a photographer's own verdict lives, and who is allowed to ignore it.

v3.76 — `scores.csv` holds what the pipeline concluded. When somebody
opens the review page and changes a verdict, that correction is appended
to `annotations.jsonl`; the CSV is not rewritten. So every reader of the
CSV is implicitly answering a question — "do I want the machine's answer
or the person's?" — and until now most of them answered it by accident.

`serve_app` had the resolution written correctly, inline, with a
docstring explaining why: "so a photo the user manually marked keep
after the original run still shows up". `cli.py`'s XMP exporter did not,
and that is the one that writes into the photographs. Measured:

    pipeline said        : cull
    photographer said    : keep
    what the export wrote: cull   (XMP rating 1)

An hour of corrections, discarded at the one moment they were for.

There is one implementation now. Readers that should honour a correction
call `decision_overrides`; readers that genuinely want the machine's
untouched verdict say so in `OVERRIDE_EXEMPT` with a reason, and a test
holds that list closed.
"""
from __future__ import annotations

import json
from pathlib import Path

#: The three verdicts a person can set. Anything else in the file is
#: some other kind of annotation (rubric stars, a note) and is not a
#: decision.
DECISIONS = frozenset({"keep", "maybe", "cull"})


def decision_overrides(output_dir: Path | str) -> dict[str, str]:
    """``filename -> decision`` for every frame a person re-decided.

    Both layouts, oldest first so the newest wins:

    * ``annotation/<filename>.json`` — the pre-v0.5 layout, one file per
      frame. Still read because runs from then still exist on disks.
    * ``annotations.jsonl`` — canonical since v0.5, append-only, so the
      LAST line for a filename is the current verdict. A photographer
      who changes their mind twice leaves two lines and means the
      second.

    Returns an empty mapping when there is nothing to apply, which is
    the common case and must not be an error.
    """
    out: dict[str, str] = {}
    root = Path(output_dir)

    legacy = root / "annotation"
    if legacy.is_dir():
        for f in sorted(legacy.glob("*.json")):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("decision") in DECISIONS:
                out[f.stem] = rec["decision"]

    jsonl = root / "annotations.jsonl"
    if jsonl.is_file():
        try:
            with jsonl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    fn = rec.get("filename")
                    label = rec.get("overall_label") or rec.get("decision")
                    if fn and label in DECISIONS:
                        out[fn] = label
        except OSError:
            pass
    return out


def decision_for(row: dict, overrides: dict[str, str]) -> str:
    """The verdict that should be acted on for one `scores.csv` row."""
    fn = (row.get("filename") or "").strip()
    if fn and fn in overrides:
        return overrides[fn]
    return (row.get("decision") or "").strip()


#: Readers that deliberately want the pipeline's own verdict, and why.
#: Keyed ``module::function``. A reader missing from both this list and
#: the set of `decision_overrides` callers is an accident, and
#: tests/test_corrections_reach_the_export.py says so.
OVERRIDE_EXEMPT = {
    "pixcull/pipeline/orchestrator.py::run_pipeline":
        "Writes scores.csv. It is the source of the machine verdict, so "
        "there is nothing to override yet.",
    "pixcull/report/serve_app.py::_handle_apply_style_guide":
        "Applies studio rules TO the machine verdict and records what it "
        "changed. Folding corrections in first would credit the rule "
        "engine with the photographer's decisions.",
    "pixcull/report/serve_app.py::_enumerate_runs":
        "Run-level totals for the picker. It reports what each run "
        "produced; a per-frame correction belongs to the run's review, "
        "not to its identity in a list.",
    "pixcull/report/serve_app.py::_collect_history_entries":
        "Same, for the history page: what the run produced at the time.",
    "pixcull/report/serve_app.py::_photo_timeline_items":
        "A timeline of what was shot and scored, not of what survived "
        "review.",
    "pixcull/scoring/ground_truth.py":
        "Reads the machine verdict on purpose: it is the side being "
        "measured against a label.",
    "pixcull/scoring/reel.py":
        "Reel candidates come from scoring; a reel is assembled before "
        "review, not after.",
    "pixcull/scoring/rubric_decompose.py":
        "Decomposes the machine's own score into axes.",
    "pixcull/report/executive_pdf.py::compute_dashboard":
        "A pure roll-up over rows it is handed; it never opens the CSV, "
        "so the caller decides which verdicts those rows carry.",
    "pixcull/tether.py":
        "Writes rows live during a shoot. Nothing has been reviewed yet.",
}
