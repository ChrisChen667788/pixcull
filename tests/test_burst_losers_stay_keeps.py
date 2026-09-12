"""v3.85 — v3.83 demoted the burst losers, and the owner's labels said no.

v3.83 turned every non-peak frame of a burst from `keep` into `maybe`,
on the reasoning that the product had already decided which frame won
and was handing over the losers anyway. The reasoning was sound and the
assumption underneath it was never tested.

Tested afterwards, blind, on the same 149 frames — the photograph, a
serial number and two buttons, no verdict on screen:

    demoted to `maybe` by v3.83   100 frames
    the photographer kept          87
    the photographer culled        13

So it moved a hundred frames into review to catch thirteen. Within
bursts the ranking is 6-3 better than chance across the nine clusters
where the photographer culled anything at all, which is not evidence of
much either way from nine.

Across four contiguous blocks the effect it relies on — that a frame
which lost its burst is worse — did not hold up. Three candidate
explanations for the one block that disagreed were tested and
eliminated: genre (two blocks from the same shoot, same model,
disagree), overall cull rate (10.0% against 11.4%, effectively
identical, opposite results), and the clustering thresholds (forcing the
tighter preset moved the odds ratio from 1.01 to 0.52, further the wrong
way).

**What this file holds.** The ranking is reported and not acted on. A
frame that lost its burst stays a `keep` until there is evidence it
should not, and the bar for that evidence is named below so the next
attempt starts from more than an argument.

To try again, what would have to be true: on a shoot the owner has
blind-labelled, the frames a demotion would move should be culled at a
materially higher rate than the ones it would leave — not 13 in 100 —
and it should replicate across shoot types rather than three in four
with an unexplained exception.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "pixcull"
ORCH = PKG / "pipeline" / "orchestrator.py"

#: Measured 2026-09-12 on the Zhangye contiguous block, blind-labelled.
DEMOTED = 100
KEPT_BY_OWNER = 87


def _functions_that_write_decision_from_peakness():
    """Any function that reads `is_burst_peak` and assigns to a
    `decision` field. Structural, so it catches a re-introduction under
    a different name — the argument for doing it is attractive enough
    that somebody will make it again."""
    hits = []
    for path in sorted(PKG.rglob("*.py")):
        src = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            reads_peak = writes_decision = False
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and sub.value == "is_burst_peak":
                    reads_peak = True
                # df.at[i, "decision"] = ... / df["decision"] = ...
                if isinstance(sub, ast.Assign):
                    for tgt in sub.targets:
                        if isinstance(tgt, ast.Subscript):
                            seg = ast.get_source_segment(src, tgt) or ""
                            if '"decision"' in seg or "'decision'" in seg:
                                writes_decision = True
            if reads_peak and writes_decision:
                hits.append(f"{path.relative_to(ROOT)}::{node.name}")
    return hits


def test_the_measurement_is_stated_not_remembered():
    """The numbers are the whole reason this gate exists. If they drift
    out of the file the gate becomes an assertion with no argument."""
    assert DEMOTED == 100 and KEPT_BY_OWNER == 87
    assert KEPT_BY_OWNER / DEMOTED > 0.8, (
        "the recorded measurement no longer supports the revert")


def test_nothing_turns_a_burst_loser_into_a_maybe():
    hits = _functions_that_write_decision_from_peakness()
    assert not hits, (
        f"{hits} decide a verdict from `is_burst_peak`. v3.83 did that and "
        f"v3.85 reverted it: of {DEMOTED} frames it demoted, the "
        f"photographer kept {KEPT_BY_OWNER}. Read this file's docstring "
        "for what new evidence would justify trying again.")


def test_the_removed_function_has_not_come_back():
    """Named explicitly as well as structurally — the structural check
    depends on a string constant that a reimplementation might reach
    through a variable."""
    for path in sorted(PKG.rglob("*.py")):
        src = path.read_text(encoding="utf-8", errors="ignore")
        body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        assert "def demote_non_peak_bursts" not in body, (
            f"{path.relative_to(ROOT)} reintroduces demote_non_peak_bursts")


def test_the_orchestrator_still_ranks_the_bursts():
    """The revert must not take the ranking with it. It is a real
    feature — it is reported in the review page and the CSV, and README
    claim 6 is about it."""
    tree = ast.parse(ORCH.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "rank_burst_peaks" in called, (
        "the revert removed the ranking as well as the demotion")


def test_the_readme_no_longer_promises_the_demotion():
    for rel in ("README.md", "modelscope/README.md", "docs/README-CLAIMS.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "losers come back as `maybe`" not in text, (
            f"{rel} still advertises the demotion")
        assert "输的那些回到 `maybe`" not in text, (
            f"{rel} still advertises the demotion (zh)")
