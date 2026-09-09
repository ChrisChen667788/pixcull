"""v3.54 — what a tag push is allowed to do, and what the version says.

Two defects, one of them mine.

**A tag push published to PyPI.** The upload step ran whenever
`PYPI_API_TOKEN` happened to be set, and it is set. So tagging — an
ordinary, reversible act — silently performed an irreversible one: PyPI
refuses a version number twice, so a mistagged release burns that number
permanently. I told the owner tagging would not touch PyPI, checked, and
found the opposite.

**The version stopped tracking.** `pyproject.toml` was bumped in lockstep
with the iteration number — v2.73 to 2.73.0, v2.74 to 2.74.0, v2.75 to
2.75.0 — and then stopped on 2026-08-22 while seventy-eight iterations
shipped. The release rail itself was built (v2.22-P1) because "every
version since v0.7.0 shipped with no git tag, no GitHub Release and no
artifact". The rail was built and then nobody drove it.
"""
import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / ".github" / "workflows" / "release.yml"

#: How far the packaged version may trail the newest release commit.
MAX_ITERATIONS_BEHIND = 4

_VERSION_COMMIT = re.compile(r"^v(\d+\.\d+(?:\.\d+)*)\s*(?:—|:|-)\s")


def _workflow() -> dict:
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))


def _declared_version() -> tuple[int, ...]:
    m = re.search(r'^version\s*=\s*"([\d.]+)"',
                  (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert m, "pyproject.toml has no version"
    return tuple(int(x) for x in m.group(1).split("."))


def _newest_release_commit() -> tuple[int, ...] | None:
    out = subprocess.run(["git", "log", "--format=%s"], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    best = None
    for subject in out.stdout.splitlines():
        m = _VERSION_COMMIT.match(subject.strip())
        if m:
            v = tuple(int(x) for x in m.group(1).split("."))
            if best is None or v > best:
                best = v
    return best


def test_a_tag_push_cannot_publish_to_pypi_on_its_own():
    """The whole point. Building, checking and releasing on GitHub are
    all reversible; the upload is not, so it does not share a trigger
    with them."""
    steps = list(_workflow()["jobs"].values())[0]["steps"]
    upload = [s for s in steps
              if "twine upload" in str(s.get("run", ""))]
    assert upload, "no PyPI upload step — has the rail been removed?"
    for step in upload:
        cond = str(step.get("if", ""))
        assert "workflow_dispatch" in cond and "publish_pypi" in cond, (
            "the PyPI upload runs without an explicit opt-in: a tag push "
            f"would publish irreversibly. Condition was {cond!r}")


def test_the_opt_in_is_off_by_default():
    trig = _workflow().get(True) or _workflow().get("on")
    inputs = trig["workflow_dispatch"]["inputs"]
    assert inputs["publish_pypi"]["default"] is False
    assert "rreversible" in inputs["publish_pypi"]["description"], (
        "the input description should say what cannot be undone")


def test_the_reversible_half_still_runs_on_a_tag():
    """Guarding the upload must not accidentally guard the release."""
    trig = _workflow().get(True) or _workflow().get("on")
    assert trig["push"]["tags"] == ["v*"]
    steps = list(_workflow()["jobs"].values())[0]["steps"]
    for needle in ("build", "twine check", "gh release create"):
        matching = [s for s in steps if needle in str(s.get("run", ""))]
        assert matching, f"no step runs {needle!r}"
        for s in matching:
            assert "publish_pypi" not in str(s.get("if", "")), (
                f"{needle!r} is gated behind the PyPI opt-in; a tag push "
                "should still build and release on GitHub")


def test_the_packaged_version_has_not_stopped_tracking():
    """v2.75.0 in pyproject while v3.53 was the newest release. Seventy-
    eight iterations, and the only visible symptom was a stale badge."""
    newest = _newest_release_commit()
    if newest is None or newest < (2, 0):
        raise AssertionError(
            "cannot read release commits — this needs full history "
            "(actions/checkout with fetch-depth: 0)")
    declared = _declared_version()
    # Compare on (major, minor); the patch position is the release's own.
    behind = (newest[:2] > declared[:2])
    gap = 0
    if behind:
        gap = (newest[0] - declared[0]) * 1000 + (newest[1] - declared[1])
    assert gap <= MAX_ITERATIONS_BEHIND, (
        f"pyproject.toml says {'.'.join(map(str, declared))} and the newest "
        f"release is v{'.'.join(map(str, newest))}. Bump it, or the wheel "
        "goes out claiming a version it is not.")


def test_the_two_places_the_version_lives_agree():
    """`pixcull.__version__` falls back to a literal when the package
    metadata is unavailable, which is exactly the case inside a source
    checkout — so the literal is what a developer sees."""
    src = (ROOT / "pixcull" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([\d.]+)"', src)
    assert m, "no fallback __version__ literal in pixcull/__init__.py"
    assert tuple(int(x) for x in m.group(1).split(".")) == _declared_version()
