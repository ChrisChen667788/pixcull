"""v3.92 — the oldest torch we promise has to be one that works.

``pyproject.toml`` said ``torch>=2.2,<3`` beside ``transformers>=4.40,<6``.
transformers decides for itself which torch it will use, and raises that
bar as it goes: 5.6 wants 2.4, 5.18 wants 2.5. Below the bar it does not
fail to import. It logs

    Disabling PyTorch because PyTorch >= 2.5 is required but found 2.4.1

and from then on every model class raises "requires the PyTorch library
but it was not found" — with torch installed. So the declared range
admitted a pair that cannot load a model, and named the wrong cause when
it did.

Nothing here saw it, for three reasons that stack. A fresh install
resolves the newest of both and works. Every lane that pinned the old
torch ran tests that load no model. And the one lane that does load
models had been skipping all of them (v3.91.1). It surfaced the first
time that lane ran: on its own pin. The Docker image was pinned to the
same pair, so an image built that day could not have analysed a
photograph.

Two things are held. The declarations agree — the floor, the pinned
lanes, the image, the Studio — so the floor is a version that CI runs.
And transformers accepts the torch that is installed, which is the
assertion that turns red in the floor-pinned lane on the day
transformers moves its bar past ours, instead of in someone's terminal.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

#: Lanes that hold torch still on purpose (a red run there means the code
#: changed, not the index). They run the declared floor.
PINNED_JOBS = ("pytest (hermetic subset)", "browser (playwright)")
#: Lanes that resolve the way a user's pip does.
FLOATING_JOBS = ("install + import smoke", "real-model integration")


def _minor(v: str) -> tuple[int, int]:
    a, b = v.split(".")[:2]
    return int(a), int(b)


def _floor(spec: str) -> tuple[int, int]:
    m = re.search(r">=\s*([\d.]+)", spec)
    assert m, f"no lower bound in {spec!r}"
    return _minor(m.group(1))


def _declared() -> dict[str, str]:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    out = {}
    for d in deps["project"]["dependencies"]:
        m = re.match(r"\s*(torch|torchvision|transformers)\b(.*)", d)
        if m:
            out[m.group(1)] = m.group(2).strip()
    assert set(out) == {"torch", "torchvision", "transformers"}, out
    return out


def _strip_comment(line: str) -> str:
    """A shell line without its comment — whole-line or trailing.

    Three times in this block a comment either satisfied a check or
    tripped one: a commented-out call still "present", a step's comment
    quoting the old pin read as a pin. A trailing `# was: torch==2.4.1`
    would do it again here.
    """
    return re.sub(r"(^|\s)#.*$", "", line)


def _commands(job: dict) -> str:
    """The job's shell, comments removed — the comments quote old pins."""
    lines = (_strip_comment(line) for s in job["steps"]
             for line in (s.get("run") or "").splitlines())
    return "\n".join(l for l in lines if l.strip())


def _jobs() -> dict[str, dict]:
    jobs = yaml.safe_load(WORKFLOW.read_text("utf-8"))["jobs"]
    return {j.get("name", k): j for k, j in jobs.items()}


def _job(prefix: str) -> dict:
    hits = [j for name, j in _jobs().items() if name.startswith(prefix)]
    assert len(hits) == 1, f"{prefix!r} matches {len(hits)} jobs"
    return hits[0]


def _pins(text: str) -> dict[str, str]:
    return dict(re.findall(r"\b(torch|torchvision)\s*==\s*([\d.]+)", text))


def test_a_pin_in_a_comment_is_not_a_pin():
    job = {"steps": [{"run": (
        "# pinned torch==2.4.1 torchvision==0.19.1 once\n"
        "pip install torch torchvision  # was: torch==2.5.1 torchvision==0.20.1\n"
        "pip install -e '.[dev]'\n")}]}
    assert _pins(_commands(job)) == {}
    real = {"steps": [{"run": 'pip install "torch==2.5.1" "torchvision==0.20.1"  # floor\n'}]}
    assert _pins(_commands(real)) == {"torch": "2.5.1", "torchvision": "0.20.1"}


# -- the declarations agree --------------------------------------------------

def test_torchvision_floor_is_the_one_that_ships_with_the_torch_floor():
    """torchvision 0.N pairs with torch 2.(N-15); a floor on one that the
    other's floor cannot install beside is a floor nobody can reach."""
    d = _declared()
    t, v = _floor(d["torch"]), _floor(d["torchvision"])
    assert t[0] == 2 and v[0] == 0
    assert v[1] == t[1] + 15, (
        f"torch>={t[0]}.{t[1]} pairs with torchvision>=0.{t[1] + 15}, "
        f"not 0.{v[1]}")


@pytest.mark.parametrize("job", PINNED_JOBS)
def test_the_pinned_lanes_run_the_declared_floor(job):
    """Otherwise the oldest torch we promise is one no lane has run —
    which is how a floor of 2.2 sat beside lanes pinned at 2.4."""
    d = _declared()
    pins = _pins(_commands(_job(job)))
    assert set(pins) == {"torch", "torchvision"}, (
        f"{job} must pin torch and torchvision together, found {pins}")
    assert _minor(pins["torch"]) == _floor(d["torch"]), (
        f"{job} pins torch {pins['torch']}; the declared floor is "
        f"{d['torch']}")
    assert _minor(pins["torchvision"]) == _floor(d["torchvision"]), (
        f"{job} pins torchvision {pins['torchvision']}; the declared "
        f"floor is {d['torchvision']}")


@pytest.mark.parametrize("job", FLOATING_JOBS)
def test_the_floating_lanes_hold_nothing_still(job):
    hits = [j for name, j in _jobs().items() if name.startswith(job)]
    assert hits, f"no job named {job!r}"
    for j in hits:
        assert not _pins(_commands(j)), f"{job} pins the torch family"


def test_the_image_is_built_on_the_declared_floor_or_above():
    """The Dockerfile pinned torch 2.4.1 and installed transformers
    unpinned. Built on a day transformers wanted 2.5, that image had a
    torch its own transformers would not use."""
    d = _declared()
    text = "\n".join(l for l in (ROOT / "Dockerfile").read_text("utf-8")
                     .splitlines() if not l.lstrip().startswith("#"))
    pins = _pins(text)
    assert set(pins) == {"torch", "torchvision"}, pins
    assert _minor(pins["torch"]) >= _floor(d["torch"])
    assert _minor(pins["torchvision"])[1] == _minor(pins["torch"])[1] + 15, (
        f"the image pins a torch/torchvision pair that do not ship "
        f"together: {pins}")


def test_the_studio_declares_the_same_floor():
    d = _declared()
    req = (ROOT / "modelscope" / "requirements.txt").read_text("utf-8")
    for pkg in ("torch", "torchvision"):
        m = re.search(rf"^{pkg}\s*(.+)$", req, re.M)
        assert m, f"modelscope/requirements.txt does not declare {pkg}"
        assert _floor(m.group(1)) == _floor(d[pkg]), (
            f"{pkg}: Studio says {m.group(1)!r}, the package says "
            f"{d[pkg]!r}")


# -- and the pair actually works ---------------------------------------------

def test_transformers_will_use_the_torch_that_is_installed():
    """The assertion that moves. In the floor-pinned lanes this is the
    declared floor against whatever transformers the index serves today;
    when transformers raises its own requirement past the floor, this is
    where it shows — as a failure that names both versions."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    from transformers.utils import is_torch_available
    assert is_torch_available(), (
        f"transformers {transformers.__version__} refuses torch "
        f"{torch.__version__}. Every model class will raise 'requires the "
        f"PyTorch library but it was not found'. Raise the torch floor in "
        f"pyproject.toml (and the pinned lanes, the Dockerfile and the "
        f"Studio with it) to what this transformers accepts.")


def test_a_model_class_can_be_reached():
    """``is_torch_available`` is transformers' own word for it; this is
    what a refusal costs. Constructing nothing — reaching the class is
    what fails when PyTorch has been disabled."""
    pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    try:
        transformers.CLIPModel.from_pretrained
    except ImportError as exc:                       # pragma: no cover
        pytest.fail(f"CLIPModel is unusable in this environment: {exc}")
