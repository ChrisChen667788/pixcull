"""v3.82 — a run that removes nothing should not read like a selection.

Measured on a contiguous 149-frame stretch of one real shoot — contiguous
deliberately, because v3.81's sample was spread evenly across each shoot
and so could not contain near-duplicates to test against:

    ✓ Done. Keep=149 Maybe=0 Cull=0

with 28 near-duplicate clusters covering 127 of those frames, the largest
holding 30, and `is_burst_peak` False on 99. **The product worked out
which frame won each burst and kept every loser.**

It is not an ordering mistake that can be swapped around. The decision is
made per frame inside the scoring loop and is final before any
cross-frame column exists on the dataframe: `df["decision"]` is assigned
two lines BEFORE `df["score_final"]`, and `rank_burst_peaks` needs
`score_final`. A burst is cross-frame by definition, so the architecture
decides each frame alone and learns which were siblings afterwards. That
is also why `demote_mediocre_bursts` rebuilds its own time-bucket
grouping instead of reusing the clusters, and why its scope is still
`stilllife` alone.

Whether non-peak members SHOULD be culled is a product decision with a
real argument on both sides — on events and portraits a photographer
often wants several frames of one moment, which is why the existing
demotion stayed narrow. What is not defensible is silence: "Keep=149
Maybe=0" on a shoot with 28 bursts in it reads as "every one of these is
a select".
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORCH = ROOT / "pixcull" / "pipeline" / "orchestrator.py"


def _src() -> str:
    return ORCH.read_text(encoding="utf-8")


def test_the_summary_reports_bursts_it_did_not_remove():
    src = _src()
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_report_unculled_bursts" in names, (
        "the run summary no longer says when it kept every member of a burst")


def test_the_reporter_is_actually_called():
    """A reporter defined and never called is this repository's most
    frequent defect; the attribution heatmap removed in v3.78 had a
    tested backend and no caller for sixty versions."""
    tree = ast.parse(_src())
    called = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "_report_unculled_bursts" in called, (
        "_report_unculled_bursts is defined and never called")


def test_it_runs_after_the_export_frame_exists():
    """It reads `df_export`, the frame actually written to disk — the
    same rule v2.95 established when the summary and the CSV disagreed."""
    src = _src()
    # By line number from the AST, not by `str.index`. The search string
    # `_report_unculled_bursts(df_export` matches the function's own
    # DEFINITION as happily as its call, and the definition sits above
    # `run_pipeline` — so the first cut of this test compared the
    # definition's position and failed on correct code.
    tree = ast.parse(src)
    calls = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_report_unculled_bursts"]
    assert len(calls) == 1, f"expected one call site, found {len(calls)}"
    counts_line = next(i for i, l in enumerate(src.splitlines(), 1)
                       if "counts = Counter(str(v) for v in df_export" in l)
    assert calls[0] > counts_line, (
        "the burst line is printed before df_export is settled")


def test_a_summary_helper_can_never_fail_a_run():
    """Scoring a shoot must not die because a count could not be taken."""
    tree = ast.parse(_src())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_report_unculled_bursts")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try)
                for h in n.handlers]
    assert handlers, "the burst reporter has no failure path"


def test_the_decision_is_still_made_before_the_cross_frame_columns():
    """The structural fact the message explains, asserted so that if it
    ever changes somebody re-reads the message rather than leaving it
    describing a shape the code no longer has."""
    src = _src()
    dec = src.index('df["decision"] = decisions')
    final = src.index('df["score_final"] = [d["final"] for d in dim_scores]')
    rank = src.index("df = rank_burst_peaks(df)")
    assert dec < final < rank, (
        "the ordering changed: the decision now sees columns it did not "
        "before. Re-read _report_unculled_bursts — its explanation may "
        "no longer be true.")


def test_the_whole_burst_demotion_still_covers_still_life_only():
    """Named here because the summary message says so out loud. If the
    scope widens, the message becomes wrong."""
    dup = (ROOT / "pixcull" / "detectors" / "duplicate.py").read_text(encoding="utf-8")
    m = re.search(r"rules = scene_rules or \{(.*?)\}\s*\n", dup, re.S)
    assert m, "demote_mediocre_bursts no longer declares its default scopes"
    scopes = set(re.findall(r'"([a-z]+)":\s*\{', m.group(1)))
    assert scopes == {"stilllife"}, (
        f"whole-burst demotion now covers {scopes}; the run summary claims "
        "still life only")
