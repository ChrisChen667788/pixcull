"""v3.70 — the preflight list cannot quietly stop covering things.

`scripts/preflight.py` runs the release-bookkeeping gates before a push,
because those are the ones that kept failing nine minutes after one. A
hand-maintained list of that kind decays: the next doc gate gets written,
nobody adds it, and preflight goes on reporting OK while covering less
than it did.

So the list is derived-checked rather than trusted. A test file that
asserts on the packaged version, the READMEs, the changelogs or the git
release history is bookkeeping by definition, and has to be in the list.

This does NOT execute preflight. A unit test that shells out to a whole
script reports every failure inside it at the test's own location, and
the signal then points somewhere unrelated — that mistake cost a real
debugging session on another project.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = ROOT / "scripts" / "preflight.py"

#: Touching any of these makes a test release bookkeeping. They are the
#: artefacts a release updates and a product change does not.
#: Deliberately NOT `pyproject.toml`: plenty of product tests read it to
#: check what a pin does, and sweeping those in made the rule mean
#: "touches a file a release touches" rather than "describes the product
#: to the public". The first cut did exactly that and pulled in the
#: aesthetic and transcription suites.
BOOKKEEPING = (
    "README.md", "CHANGELOG.md",
    "modelscope/README.md", "modelscope/CHANGELOG.md", "README-PYPI.md",
)


def _listed() -> list[str]:
    """The test files named in preflight's GATES, read as a literal."""
    tree = ast.parse(PREFLIGHT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == "GATES"):
            return [e.elts[0].value for e in node.value.elts]
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "GATES" for t in node.targets)):
            return [e.elts[0].value for e in node.value.elts]
    raise AssertionError("scripts/preflight.py no longer declares GATES")


def test_every_gate_named_actually_exists():
    listed = _listed()
    assert len(listed) >= 8, f"preflight covers only {len(listed)} gates"
    missing = [p for p in listed if not (ROOT / p).exists()]
    assert not missing, f"preflight names files that are gone: {missing}"


def test_no_bookkeeping_gate_is_left_out_of_preflight():
    """The drift this exists to stop. A new gate on the README or the
    version that is not in preflight is a gate that will only ever fire
    on a runner, which is where the last eight fixups came from."""
    listed = set(_listed())
    should = []
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        if p.name == Path(__file__).name:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # The name has to appear in real code, not only in the prose
        # explaining the gate — a guard satisfied by its own commentary
        # is this repository's most-repeated defect.
        body = "\n".join(l.split("#", 1)[0] for l in text.splitlines())
        body = re.sub(r'"""[\s\S]*?"""', "", body)
        if any(a in body for a in BOOKKEEPING):
            should.append(f"tests/{p.name}")

    # The scan has to be alive: an empty `should` agrees with any list.
    assert len(should) >= 5, (
        f"only {len(should)} bookkeeping gates detected — the scan is "
        "broken, not the list")

    absent = sorted(set(should) - listed)
    assert not absent, (
        f"these assert on {', '.join(BOOKKEEPING[:3])}… and are not in "
        f"scripts/preflight.py: {absent}. Add them, or they will only "
        "ever fail after a push.")


def test_the_makefile_offers_it():
    """A script nobody is told about is a script nobody runs."""
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^preflight:", mk, re.M), (
        "Makefile has no `preflight` target")
    assert "scripts/preflight.py" in mk
