"""v3.74 — what CI installs was not what anybody installs.

Two gaps, same shape, both in the lane whose name is "install + import
smoke" and whose entire job is to prove that installing this package
works.

**Python 3.11 was advertised everywhere and tested nowhere.**
`requires-python` says `>=3.11,<3.13`, the wheel carries a
`Programming Language :: Python :: 3.11` classifier so PyPI lists it,
`README-PYPI.md` says "Python 3.11-3.12", the README opens with a badge
that reads `python 3.11 | 3.12`, and both quickstarts name it. The
matrix ran `['3.12']`, and the commit log says it never ran anything
else. Someone reading the badge and installing on 3.11 was the first
person to find out.

**Every lane pinned `torch==2.4.1`.** The pin's stated reason is that
torch and torchvision must arrive together so the editable install
cannot upgrade one half against the other — a reason to install them in
one command, not a reason to freeze a version. `pyproject.toml` allows
`>=2.2,<3`; a machine resolving today gets 2.11. So the install-smoke
lane proved that a two-year-old torch imports, and the seven minor
versions between were exercised by nothing. (Measured on this machine at
the time: 54 torch-dependent tests pass on 2.11 — the range was
untested, not broken. Which is the point: nothing would have said so.)

The other three lanes stay pinned deliberately. A fixed pair makes a red
run mean "the code changed" rather than "the index did". The smoke lane
is the one place where the opposite is what we want.
"""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
try:
    import tomllib
except ModuleNotFoundError:                       # pragma: no cover
    tomllib = pytest.importorskip("tomli")

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

#: The lane that exists to prove a fresh install works.
SMOKE_JOB = "import"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _shell(job: dict) -> str:
    """Every `run:` block in a job with comments stripped.

    Stripped because this file would otherwise be read as this repo's
    other recurring defect: a check satisfied by the prose that explains
    it. The step below carries a comment naming `torch==2.4.1` to say
    why it is gone, and a raw substring search finds that comment.
    """
    out = []
    for step in job.get("steps", []):
        run = step.get("run") or ""
        out.extend(line.split("#", 1)[0] for line in run.splitlines())
    # Join backslash continuations, so a command split across lines is
    # one line to match against. Third time in two versions that a check
    # of mine has been defeated by a line break: v3.73 shipped a broken
    # browser lane because a filename on its own line still "appeared in
    # the script", and its fixup had to learn the same thing.
    joined, buf = [], ""
    for line in out:
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        joined.append(buf + stripped)
        buf = ""
    if buf:
        joined.append(buf)
    return "\n".join(joined)


def _declared_pythons() -> set:
    doc = tomllib.loads(WORKFLOW.parent.parent.parent.joinpath("pyproject.toml")
                        .read_text(encoding="utf-8"))
    proj = doc["project"]
    out = set()
    for c in proj.get("classifiers", []):
        m = re.match(r"Programming Language :: Python :: (\d+\.\d+)$", c.strip())
        if m:
            out.add(m.group(1))
    # requires-python is the other half of the claim: a floor and a
    # ceiling imply every minor in between.
    rp = proj.get("requires-python", "")
    lo = re.search(r">=\s*(\d+)\.(\d+)", rp)
    hi = re.search(r"<\s*(\d+)\.(\d+)", rp)
    if lo and hi and lo.group(1) == hi.group(1):
        for minor in range(int(lo.group(2)), int(hi.group(2))):
            out.add(f"{lo.group(1)}.{minor}")
    return out


def _matrix_pythons() -> set:
    job = _workflow()["jobs"][SMOKE_JOB]
    versions = job.get("strategy", {}).get("matrix", {}).get("python-version", [])
    return {str(v) for v in versions}


def test_the_smoke_lane_runs_every_python_the_package_advertises():
    """A classifier is a promise PyPI displays. Making it without
    running it is the same defect as a README naming a command that does
    not exist, with a slower feedback loop — the reader finds out by
    installing."""
    declared, tested = _declared_pythons(), _matrix_pythons()
    assert declared, "pyproject advertises no Python versions at all"
    assert tested, "the smoke lane declares no python-version matrix"
    missing = sorted(declared - tested)
    assert not missing, (
        f"pyproject.toml and the PyPI classifiers advertise Python "
        f"{sorted(declared)}, and the {SMOKE_JOB} lane only runs "
        f"{sorted(tested)}. Untested: {missing}.")


def test_the_smoke_lane_does_not_pin_the_torch_family():
    """Otherwise it rehearses an install nobody performs.

    Pinning is right for the lanes that test behaviour and wrong for the
    one that tests installation, which has to resolve the way a user's
    pip does or it is answering a different question.
    """
    code = _shell(_workflow()["jobs"][SMOKE_JOB])
    pins = re.findall(r"\b(torch\w*)\s*==\s*([\d.]+)", code)
    assert not pins, (
        f"the {SMOKE_JOB} lane pins {pins}. It exists to prove that "
        "installing this package works; with a pin it proves that "
        "installing those exact versions works, which no user does.")


def test_the_smoke_lane_still_installs_the_pair_together():
    """The original pin had a real reason underneath it — torch and
    torchvision resolved separately gives a CUDA/CPU mismatch that only
    shows up as `operator torchvision::nms does not exist` at import.
    Unpinning must not lose that."""
    code = _shell(_workflow()["jobs"][SMOKE_JOB])
    together = re.search(r"pip install[^\n]*\btorch\b[^\n]*\btorchvision\b", code)
    assert together, (
        "torch and torchvision are no longer installed by one pip "
        "command in the smoke lane; resolved separately they can end up "
        "a CPU/CUDA mismatch that only fails at import time")


def test_the_behaviour_lanes_are_still_reproducible():
    """Stated so that unpinning the smoke lane cannot be mistaken for a
    decision to unpin everything. If these ever go unpinned it should be
    a deliberate edit that fails here first."""
    wf = _workflow()
    unpinned = []
    for job in ("browser", "pytest"):
        if job not in wf["jobs"]:
            continue
        if not re.search(r"\btorch\s*==\s*[\d.]+", _shell(wf["jobs"][job])):
            unpinned.append(job)
    assert not unpinned, (
        f"{unpinned} no longer pin torch. A behaviour lane wants a fixed "
        "pair so a red run means the code changed, not the index.")
