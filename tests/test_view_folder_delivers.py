"""v3.58 — the delivery folder, when there is nothing to deliver.

`pixcull view-folder <run> --out <dir>` is v2.99, and the first item in
**What's new** on both front doors. Pointed at a directory that did not
exist yet it raised

    FileNotFoundError: [Errno 2] No such file or directory: '…/_目录.json'

as an unhandled traceback in front of a photographer.

The mechanism is worth stating, because "it forgot mkdir" is not it.
The destination was created as a *side effect* of `out.parent.mkdir`
while copying the first photograph. So it existed whenever there was
something to copy, and did not when there was nothing — every frame
culled, or `--only` matching none of them. A photographer who runs this
before deciding anything has no keeps yet, which makes the crash the
normal first encounter rather than an edge case.

`pixcull/export/proof_sheet.py`, the sibling command in the same block,
has always created its output directory unconditionally. Same argument,
two behaviours.

Fixing the traceback left the softer half: a green tick over "0
photographs", handed to somebody who asked for a folder to give a
client. That says so now, and exits non-zero.
"""
import csv
import json
from pathlib import Path

import pytest

from pixcull.export.view_folder import write_view_folder

ROOT = Path(__file__).resolve().parent.parent


def _rows(decisions: list[str]) -> list[dict]:
    return [{"filename": f"IMG_{i:04d}.jpg", "decision": d,
             "score_final": 0.5, "datetime": f"2026:01:01 10:{i:02d}:00"}
            for i, d in enumerate(decisions)]


def test_a_run_with_nothing_to_deliver_does_not_raise(tmp_path):
    """The reported defect, reproduced at its source."""
    dest = tmp_path / "never-created"
    res = write_view_folder(_rows(["cull"] * 6), dest,
                            resolve=lambda _f: None, only="keep")
    assert dest.is_dir(), "the destination was not created"
    assert (dest / "_目录.json").is_file(), "the manifest was not written"
    assert res["written"] == 0


def test_the_manifest_is_readable_and_says_nothing_was_written(tmp_path):
    dest = tmp_path / "empty"
    write_view_folder(_rows(["cull", "cull"]), dest,
                      resolve=lambda _f: None, only="keep")
    manifest = json.loads((dest / "_目录.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "pixcull.view_folder/v1"
    assert manifest["written"] == 0


def test_it_still_delivers_when_there_is_something_to_deliver(tmp_path):
    """The fix must not have bought quiet by writing nothing."""
    src = tmp_path / "src"
    src.mkdir()
    originals = {}
    for i in range(3):
        p = src / f"IMG_{i:04d}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")
        originals[p.name] = p
    dest = tmp_path / "out"
    res = write_view_folder(_rows(["keep"] * 3), dest,
                            resolve=originals.get, only="keep")
    assert res["written"] == 3
    copied = [p for p in dest.rglob("*.jpg")]
    assert len(copied) == 3, f"expected 3 photographs on disk, found {copied}"


def test_the_sibling_command_has_the_same_habit():
    """proof_sheet.py creates its output directory unconditionally and
    always has. This is the assertion that the two stay aligned — the
    drift between them is what produced the defect."""
    for module in ("view_folder", "proof_sheet"):
        src = (ROOT / "pixcull" / "export" / f"{module}.py").read_text("utf-8")
        body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        assert "mkdir(parents=True, exist_ok=True)" in body, module


def test_the_cli_refuses_rather_than_reporting_an_empty_folder_as_done():
    """A green tick over "0 photographs" is the same defect, softened."""
    import re
    src = (ROOT / "pixcull" / "cli.py").read_text(encoding="utf-8")
    at = src.index("def view_folder(")
    body = src[at:at + 4000]
    assert 'if not res["written"]' in body, (
        "view-folder does not check whether it wrote anything")
    assert "Nothing to deliver" in body
    assert re.search(r'raise typer\.Exit\(code=1\)', body)
