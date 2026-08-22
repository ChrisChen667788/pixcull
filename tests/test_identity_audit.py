"""v2.75 — photographs the product cannot show you.

Every map from a photo to its bytes here is keyed on the **basename**.
`manifest.json` is `{filename: path}`; the image endpoints are
`/thumb/<run>/<filename>`; the grid identifies a card by `data-fn`;
`library index` builds `out[fn] = path`. Each is a dict, and a dict
keyed on a name that is not unique keeps the last writer.

Measured on a real 5,069-frame run of a recursively scanned folder:

    scores.csv rows          5069
    manifest.json entries    4616
    photographs unreachable   774   (738 names used by >1 file)

Those photographs have a card in the grid. The card shows **another
photograph's** thumbnail, because the URL resolves the basename to
whichever file won the dict. Verified in the browser: two cards, two
different source paths, byte-identical thumbnail URLs.

The identity scheme is not fixed in this version — it reaches
decisions, annotations, XMP export and the library index, and changing
it at speed is how the next seventeen-version defect gets written. What
this version does is make the loss impossible to miss, which is v2.71's
rule: an invisible failure is worse than a loud one, because only one of
them gets fixed.
"""

from __future__ import annotations

import pytest

from pixcull.scoring.identity_audit import audit_rows


def test_two_files_one_name_is_a_photograph_you_cannot_see():
    rows = [
        {"filename": "a.jpg", "path": "/shoot/one/a.jpg"},
        {"filename": "a.jpg", "path": "/shoot/two/a.jpg"},
        {"filename": "b.jpg", "path": "/shoot/one/b.jpg"},
    ]
    a = audit_rows(rows)
    assert not a.ok
    assert a.n_colliding_names == 1
    assert a.n_unreachable == 1, (
        "one of the two `a.jpg` files has no URL that can address it")
    assert "UNREACHABLE" in a.summary()


def test_the_same_file_listed_twice_is_not_a_collision():
    """One photograph enumerated twice is a different problem, and a
    harmless-looking one. Counting it here would inflate the number that
    is supposed to mean "you cannot see these"."""
    rows = [
        {"filename": "a.jpg", "path": "/shoot/a.jpg"},
        {"filename": "a.jpg", "path": "/shoot/a.jpg"},
    ]
    a = audit_rows(rows)
    assert a.ok, "same path counted as a collision"
    assert a.n_unreachable == 0


def test_three_files_one_name_hides_two():
    rows = [{"filename": "a.jpg", "path": f"/d{i}/a.jpg"} for i in range(3)]
    assert audit_rows(rows).n_unreachable == 2


def test_a_clean_run_says_so_positively():
    rows = [{"filename": f"{i}.jpg", "path": f"/d/{i}.jpg"} for i in range(5)]
    a = audit_rows(rows)
    assert a.ok
    assert "all addressable" in a.summary()


def test_src_path_is_accepted_as_well_as_path():
    """The built row renames `path` to `src_path` — the same rename that
    made the advice pass unreachable for seventeen versions (v2.68.6).
    This auditor reads both, so it works on a CSV row and on a built
    row."""
    rows = [
        {"filename": "a.jpg", "src_path": "/one/a.jpg"},
        {"filename": "a.jpg", "src_path": "/two/a.jpg"},
    ]
    assert audit_rows(rows).n_unreachable == 1


def test_the_photographer_is_told_in_the_workspace_bar():
    """A log line reaches whoever started the server. The person who
    needs this is the one about to make decisions on those cards, and
    from the grid a run that lost 774 frames looks exactly like a run
    that did not."""
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]
    js = (root / "pixcull/report/templates/src/results.js").read_text(
        encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith("//"))
    # Scoped to the render expression, not merely the identifier: the
    # first version of this assertion passed while the chip had been
    # switched off with `...(false ? …)`, because the name still
    # appeared in the tooltip a few characters later.
    assert re.search(r"\.\.\.\(summary\.n_unreachable", code), (
        "the count reaches the page and the chip is not conditioned on it")
    assert "stat-fault" in code
    css = (root / "pixcull/report/templates/src/modules/chips.css").read_text(
        encoding="utf-8")
    assert ".stat-fault" in css, "the warning chip has no styling"

    serve = (root / "pixcull/report/serve_app.py").read_text(encoding="utf-8")
    assert 'summary["n_unreachable"]' in serve, (
        "the server never puts the count in the summary")
