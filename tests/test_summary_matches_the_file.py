"""v2.95 — the run summary counted a list the judge had already overruled.

Observed on a six-frame run:

    VLM authority primary — 6 decision(s) changed by the judge
    ✓ Done. Keep=6 Maybe=0 Cull=0

and every row in scores.csv said `cull`. The photographer reads that the
whole shoot was kept, opens the results, and finds nothing was — with
the line that explains it printed immediately above and contradicted.

`decisions` is a list appended per row while scoring. The judge rewrites
`df["decision"]` in place afterwards, and the CSV is exported from `df`.
Two sources, one stale, no way for a reader to tell which.
"""
import ast
from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[1] / "pixcull" / "pipeline"
       / "orchestrator.py")


def _code_only(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    docs = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    body = "\n".join("" if l.lstrip().startswith("#") else l.split("#", 1)[0]
                     for l in text.splitlines())
    for d in docs:
        body = body.replace(d, "")
    return body


def test_the_summary_counts_the_exported_frame():
    code = _code_only(SRC)
    i = code.find("counts = Counter(")
    assert i > 0, "the summary no longer counts anything"
    stmt = code[i:code.find("\n", i)]
    assert "df_export" in stmt, (
        "the summary counts something other than the frame written to "
        "scores.csv, so the two can disagree — and did")
    assert "decisions" not in stmt, (
        "`decisions` is built before the VLM judge overrides df, so "
        "counting it reports the run that did not happen")


def test_the_count_is_taken_after_the_export():
    """Counting before the export would work today and break the moment
    a later pass edits the frame between the two."""
    code = _code_only(SRC)
    export = code.find("df_export.to_csv(")
    counts = code.find("counts = Counter(")
    assert 0 < export < counts


def test_the_judge_writes_where_the_export_reads():
    """The mechanism. If the judge ever writes somewhere else again, the
    summary silently goes stale a second time."""
    code = _code_only(SRC)
    assert 'df.at[df.index[i], "decision"] = dec.value' in code
    assert "df_export = df.drop(" in code


def test_counter_is_given_strings():
    """A pandas column can hold an enum or a numpy object; Counter over
    those produces keys that never match "keep" and a summary of all
    zeros that looks like an empty run."""
    code = _code_only(SRC)
    i = code.find("counts = Counter(")
    stmt = code[i:code.find("\n", i)]
    assert "str(" in stmt
