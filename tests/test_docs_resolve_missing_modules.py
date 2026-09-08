"""v3.40 — a document that names a module nobody can find has to say why.

`ROADMAP-v2.71-charter.md` discussed `counterfactual.py`, quoted its
docstring and proposed evaluating `best_variant()` against 493 blind
frames.  Neither exists.

The answer turned out to be the good one: v2.73 measured the thing and
deleted it — on 100 blind frames the proposed crop's gain did not
distinguish the photographer's culls from their keeps, and the chip
appeared on 52% of kept frames against 32% of culled ones, backwards
from its purpose.  The charter did what it said: ship one of two things,
not neither.

So this is not a defect in the decision.  It is that three historical
charters send a reader looking for a module that was removed on purpose,
and nothing on the path from the charter to the answer says so.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Words that count as saying what happened to it.
RESOLUTION = ("no longer exists", "deleted", "removed", "superseded",
              "does not exist", "was dropped")

MODULE_REF = re.compile(r'`([a-z_][a-z0-9_]*\.py)`')

#: Characters either side of a reference that count as "near it".  A
#: document that says "deleted" once in a footnote does not answer a
#: reference eight screens above it.
NEARBY = 900


def unresolved(text: str, live: set[str]) -> list[str]:
    """Names in `text` that no file provides and no nearby line explains."""
    out = []
    for m in MODULE_REF.finditer(text):
        name = m.group(1)
        if name in live:
            continue
        window = text[max(0, m.start() - NEARBY):m.end() + NEARBY].lower()
        if any(word in window for word in RESOLUTION):
            continue
        out.append(name)
    return out


def _tracked_basenames() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    return {Path(f).name for f in out.split()}


def _docs():
    return (sorted((ROOT / "docs").glob("*.md"))
            + [ROOT / "README.md", ROOT / "CLAUDE.md",
               ROOT / "modelscope" / "README.md"])


def test_every_named_module_either_exists_or_is_accounted_for():
    """Narrow on purpose: only backticked `something.py`, only in docs.

    A reference that resolves to nothing is a reader's dead end, and the
    cost of answering it is one sentence written by whoever removed the
    file — who is the only person who still knows.
    """
    live = _tracked_basenames()
    dangling = []
    for d in _docs():
        try:
            text = d.read_text(encoding="utf-8")
        except OSError:
            continue
        for name in sorted(set(unresolved(text, live))):
            dangling.append(f"{d.relative_to(ROOT)}: {name}")
    assert not dangling, (
        "these documents name a module that is not in the repository and "
        "do not say what happened to it: " + "; ".join(dangling))


def test_the_gate_can_see_a_dangling_reference():
    """A linter that passes by matching nothing is the worst kind."""
    live = _tracked_basenames()
    assert "counterfactual.py" not in live
    fake = "`a_module_that_never_was.py` is great."
    assert unresolved(fake, live) == ["a_module_that_never_was.py"]
    assert unresolved(fake + " It was deleted in v9.", live) == []
    # far away does not count
    assert unresolved(fake + " x" * NEARBY + " It was deleted.",
                      live) == ["a_module_that_never_was.py"]
    # a name that resolves to a real file is never flagged
    assert unresolved("`orchestrator.py` runs it.", live) == []


def test_the_classifier_it_fed_says_it_has_no_consumer():
    """Kept rather than deleted because nothing has measured IT, and
    v2.70's rule stands: never act on the absence of evidence.  That is a
    decision, and it has to stay written down or the next reader deletes
    it as dead code."""
    src = (ROOT / "pixcull" / "scoring"
           / "composition_classifier.py").read_text(encoding="utf-8")
    flat = " ".join(src.split())
    assert "no consumer in the product" in flat
    assert "nothing has measured IT" in flat


def test_the_charters_point_at_the_outcome():
    """The word list is not proof.

    `RESOLUTION` matches "deleted" wherever it appears in the window, and
    the v2.71 charter *proposed* deleting the module — so proximity alone
    would have let that file pass with no answer in it.  These three
    files are therefore pinned by name to the actual outcome, and the
    general check is what catches the next one nobody remembers.
    """
    for rel in ("ROADMAP-v2.57-charter.md", "ROADMAP-v2.68-charter.md",
                "ROADMAP-v2.71-charter.md"):
        text = (ROOT / "docs" / rel).read_text(encoding="utf-8")
        assert "no longer exists" in text, rel
        assert "v2.73" in text, rel
