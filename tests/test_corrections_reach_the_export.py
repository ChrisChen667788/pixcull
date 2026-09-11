"""v3.76 — an hour of corrections, discarded at the moment they were for.

`scores.csv` holds the pipeline's verdict. A verdict a person changes in
the review page is appended to `annotations.jsonl`; the CSV is not
rewritten. So every reader of that CSV silently answers "the machine's
answer or the person's?", and most of them answered by accident.

`serve_app` had the resolution written correctly, inline, with a
docstring saying why. `cli.py`'s XMP exporter — the one that writes into
the photographs and into Lightroom — did not. Measured before the fix:

    pipeline said        : cull
    photographer said    : keep
    what the export wrote: cull   (XMP rating 1)

The contact sheet had it too: a frame rescued in review was still absent
from the sheet handed to the client.

Counted at function granularity, twelve functions read `decision` out of
`scores.csv` and seven ignored corrections. Some of those seven are
right to — the rule engine applies studio rules TO the machine verdict,
the tether writes rows before anything is reviewed. That is the
difference this file holds: honouring a correction is the default, and
ignoring one is a decision somebody wrote down.
"""
import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

from pixcull.annotations import (  # noqa: E402
    OVERRIDE_EXEMPT, decision_for, decision_overrides,
)

_READS_DECISION = re.compile(
    r'\[["\']decision["\']\]|get\(\s*["\']decision["\']')


def _functions_reading_the_csv_verdict():
    """Every function that pulls `decision` out of `scores.csv`.

    AST, not grep: the point is which function a line belongs to, and a
    file-level search cannot tell. The first cut of this scan was
    file-level and reported `cli.py` as compliant because the file
    mentions `annotations.jsonl` somewhere else entirely.
    """
    found = []
    for path in sorted(ROOT.joinpath("pixcull").rglob("*.py")):
        src = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = str(path.relative_to(ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, node) or ""
            body = "\n".join(l.split("#", 1)[0] for l in seg.splitlines())
            if "scores.csv" not in body or not _READS_DECISION.search(body):
                continue
            # Either the shared helper, or its own inline read of the
            # corrections file. Both consider the photographer's verdict,
            # which is what this gate is about; how many copies of the
            # resolution exist is the separate question below.
            honours = bool(re.search(
                r"decision_overrides|decision_for|ann_overrides"
                r"|annotations\.jsonl|overall_label", body))
            found.append((f"{rel}::{node.name}", rel, honours))
    return found


def test_the_scan_still_sees_the_readers():
    """A scan that finds nothing passes and reads like a scan that found
    nothing wrong. Five versions of this repo shipped that mistake."""
    found = _functions_reading_the_csv_verdict()
    assert len(found) >= 8, (
        f"only {len(found)} readers of the CSV verdict found — the scan is "
        "broken, not the code")


def test_every_reader_either_honours_a_correction_or_says_why_not():
    accidental = []
    for key, rel, honours in _functions_reading_the_csv_verdict():
        if honours or key in OVERRIDE_EXEMPT or rel in OVERRIDE_EXEMPT:
            continue
        accidental.append(key)
    assert not accidental, (
        "these read the pipeline's verdict out of scores.csv and ignore a "
        f"correction the photographer made, without saying they meant to: "
        f"{accidental}. Call pixcull.annotations.decision_for, or add an "
        "entry to OVERRIDE_EXEMPT with the reason.")


def test_an_exemption_has_to_carry_a_reason():
    for key, why in OVERRIDE_EXEMPT.items():
        assert why and len(why) > 30, (
            f"{key} is exempt with no real reason: {why!r}")


# ── the resolution itself ────────────────────────────────────────────

def test_the_last_line_wins(tmp_path):
    """Append-only: somebody who changes their mind twice means the
    second time."""
    (tmp_path / "annotations.jsonl").write_text(
        json.dumps({"filename": "a.jpg", "overall_label": "keep"}) + "\n"
        + json.dumps({"filename": "a.jpg", "overall_label": "cull"}) + "\n",
        encoding="utf-8")
    assert decision_overrides(tmp_path) == {"a.jpg": "cull"}


def test_the_canonical_layout_beats_the_legacy_one(tmp_path):
    (tmp_path / "annotation").mkdir()
    (tmp_path / "annotation" / "a.jpg.json").write_text(
        json.dumps({"decision": "cull"}), encoding="utf-8")
    (tmp_path / "annotations.jsonl").write_text(
        json.dumps({"filename": "a.jpg.json", "overall_label": "keep"}) + "\n",
        encoding="utf-8")
    assert decision_overrides(tmp_path)["a.jpg.json"] == "keep"


def test_junk_lines_do_not_take_the_run_down(tmp_path):
    (tmp_path / "annotations.jsonl").write_text(
        "not json\n"
        + json.dumps({"filename": "a.jpg", "overall_label": "keep"}) + "\n"
        + json.dumps({"filename": "b.jpg", "overall_label": "nonsense"}) + "\n",
        encoding="utf-8")
    got = decision_overrides(tmp_path)
    assert got == {"a.jpg": "keep"}, (
        "a malformed line must be skipped, and a label that is not a "
        "decision must not become one")


def test_nothing_to_apply_is_not_an_error(tmp_path):
    assert decision_overrides(tmp_path) == {}


def test_a_row_with_no_correction_keeps_its_verdict():
    row = {"filename": "a.jpg", "decision": "cull"}
    assert decision_for(row, {}) == "cull"
    assert decision_for(row, {"a.jpg": "keep"}) == "keep"


# ── the two paths that were wrong, end to end ────────────────────────

def _run_with_a_correction(tmp_path):
    import csv
    Image = pytest.importorskip("PIL.Image", reason="Pillow needed")
    run = tmp_path / "output"
    run.mkdir(parents=True)
    src = tmp_path / "input"
    src.mkdir()
    img = src / "IMG_1.jpg"
    Image.new("RGB", (64, 48), (120, 90, 60)).save(img)
    with (run / "scores.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "filename", "decision",
                                           "score_final"])
        w.writeheader()
        w.writerow({"path": str(img), "filename": "IMG_1.jpg",
                    "decision": "cull", "score_final": "0.42"})
    (run / "annotations.jsonl").write_text(
        json.dumps({"filename": "IMG_1.jpg", "overall_label": "keep",
                    "source": "human"}) + "\n", encoding="utf-8")
    return run


def test_the_xmp_export_writes_the_photographers_verdict(tmp_path):
    """The defect exactly: the pipeline said cull, the person said keep,
    and Lightroom was handed cull."""
    run = _run_with_a_correction(tmp_path)
    from pixcull.cli import _export_xmp
    _written, _skipped, per_decision = _export_xmp(run, target="collected")
    assert per_decision == {"keep": 1}, (
        f"export wrote {per_decision}; the photographer marked it keep")


def test_the_contact_sheet_shows_a_rescued_frame(tmp_path):
    """It is handed to a client, so it shows the selects, not the first
    guess at them."""
    run = _run_with_a_correction(tmp_path)
    # v3.76 — there was an `importorskip("reportlab")` here, and the
    # contact sheet does not use reportlab; it draws with Pillow. So this
    # test skipped, everywhere, for a dependency that is not a dependency
    # — the exact skip-as-a-pass shape this repository keeps finding,
    # introduced in the version fixing that class of defect.
    from pixcull.report.contact_sheet import contact_sheet_from_run
    _pages, photos = contact_sheet_from_run(
        run, tmp_path / "sheet.pdf", decision="keep", with_cover=False)
    assert photos == 1, (
        f"sheet carried {photos} keeps; the frame was rescued in review")


# ── how many copies of one rule ──────────────────────────────────────

#: Call sites that parse `annotations.jsonl` themselves instead of
#: calling `decision_overrides`.
#:
#: I expected four. There are fourteen — ten in `serve_app` alone, plus
#: `personal_learn`, `sync/event`, and two in `workflow`. That is the
#: defect underneath this version's defect: the rule for "what did the
#: photographer decide" is written out fourteen times, so the exporter
#: was not forgetting a shared thing, it was one of fifteen places that
#: each had to remember independently, and it was the one that did not.
#:
#: Not migrated in one go, deliberately. `serve_app`'s copy carries the
#: pre-v2.76 filename migration alongside the parse, and moving that is
#: its own change with its own way of going wrong. This is a ratchet in
#: the meantime: the number may go DOWN, and may not go up.
MAX_INLINE_PARSERS = 14


def test_the_resolution_is_not_being_copied_again():
    """The defect underneath the defect.

    A rule written out four times is a rule that will be written out a
    fifth, and the fifth will be as wrong as the exporter was. Adding a
    new inline parse fails here; moving one onto the shared helper makes
    this number smaller and the assertion still passes.
    """
    inline = []
    for path in sorted(ROOT.joinpath("pixcull").rglob("*.py")):
        if path.name == "annotations.py":
            continue          # the shared implementation itself
        src = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = str(path.relative_to(ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, node) or ""
            body = "\n".join(l.split("#", 1)[0] for l in seg.splitlines())
            if re.search(r"annotations\.jsonl", body) and re.search(
                    r"overall_label", body):
                inline.append(f"{rel}::{node.name}")
    assert len(inline) <= MAX_INLINE_PARSERS, (
        f"{len(inline)} call sites parse annotations.jsonl themselves "
        f"({inline}); the cap is {MAX_INLINE_PARSERS}. Use "
        "pixcull.annotations.decision_overrides, or lower the cap in the "
        "same commit that adds a copy and say why here.")
