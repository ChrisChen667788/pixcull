"""v3.64 — the product's first claim is that it runs on your machine.

It did not. `transformers` contacts the hub before it will use a model
it already has, so with the weights sitting in `~/.cache/huggingface`
and the network away, every frame failed:

    OSError: Can't load processor for 'openai/clip-vit-base-patch32'
    Analyzed 0/32 images
    No analyzable images.

Setting `HF_HUB_OFFLINE=1` made the same run work, which is the tell:
the files were on disk and usable, and only the lookup was failing. A
photographer on a plane, or on a shoot with no signal — the situation
local-first exists for — got nothing back, with the model on their own
disk the whole time.

Found while upgrading numpy, not by looking for it.

v3.89 — v3.64 fell back to the disk after the network attempt failed,
so the run worked and still paid for every attempt: 48 on 32 photos with
a warm cache, each one an OS connect timeout on a network that drops
rather than refuses (issue #3, 149 s for 0/23 on Windows). The disk
comes first now.
"""
import ast
import socket
from pathlib import Path

import pytest

from tests._model_gate import absent, is_cached

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pixcull"
WRAPPER = PACKAGE / "model_assets.py"
CLIP = "openai/clip-vit-base-patch32"


def _raw_from_pretrained_calls(path: Path) -> list[int]:
    """Lines calling ``<something>.from_pretrained(`` — parsed, so a comment
    or a docstring does not count and every attribute form does."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "from_pretrained"]


def test_nothing_calls_from_pretrained_without_the_wrapper():
    """A new caller that goes straight to `transformers` reintroduces the
    defect for whichever model it loads, and nothing would say so until
    somebody ran the product with the wifi off.

    v3.89: the whole package, not a list of three files. The list was
    right when it was written and would not have seen a fourth caller.
    """
    bad = [f"{p.relative_to(ROOT)}:{line}"
           for p in sorted(PACKAGE.rglob("*.py")) if p != WRAPPER
           for line in _raw_from_pretrained_calls(p)]
    assert not bad, (
        "these call transformers directly and will reach for the network "
        f"even when the model is cached: {bad}. Use "
        "pixcull.model_assets.from_pretrained.")


def test_the_scan_sees_a_raw_call(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "# Cls.from_pretrained(x) in a comment\n"
        '"""Cls.from_pretrained(x) in a docstring"""\n'
        "a = CLIPModel.from_pretrained('x')\n"
        "b = transformers.AutoModel.from_pretrained('x')\n",
        encoding="utf-8")
    assert _raw_from_pretrained_calls(probe) == [3, 4]


class _Recorder:
    """A stand-in for a transformers class: records each call's
    ``local_files_only`` and answers from a script."""

    def __init__(self, *, on_disk: bool, network: bool):
        self.calls, self.on_disk, self.network = [], on_disk, network

    def from_pretrained(self, name, **kw):
        local = bool(kw.get("local_files_only"))
        self.calls.append(local)
        if local:
            if self.on_disk:
                return "from disk"
            raise OSError("not in the local cache: " + name)
        if self.network:
            return "downloaded"
        raise OSError("could not reach the hub: " + name)


def test_a_cached_model_never_asks_the_network():
    """v3.89, issue #3. A warm cache is one call, and it is local."""
    from pixcull.model_assets import from_pretrained
    fake = _Recorder(on_disk=True, network=False)
    assert from_pretrained(fake, "some/model") == "from disk"
    assert fake.calls == [True]


def test_a_model_not_on_disk_is_downloaded():
    """The other side: a cold cache still reaches the network, so a first
    run downloads rather than failing."""
    from pixcull.model_assets import from_pretrained
    fake = _Recorder(on_disk=False, network=True)
    assert from_pretrained(fake, "some/model") == "downloaded"
    assert fake.calls == [True, False]


def test_an_explicit_local_only_is_passed_through_once():
    from pixcull.model_assets import from_pretrained
    fake = _Recorder(on_disk=True, network=True)
    assert from_pretrained(fake, "m", local_files_only=True) == "from disk"
    assert fake.calls == [True]


def test_a_model_that_is_genuinely_absent_reports_the_network_error():
    """Not cached and no network: the message the user needs names the
    network, because connecting once is what fixes it."""
    from pixcull.model_assets import from_pretrained
    fake = _Recorder(on_disk=False, network=False)
    with pytest.raises(OSError, match="could not reach the hub") as err:
        from_pretrained(fake, "some/model")
    assert "not in the local cache" in str(err.value.__cause__)


def test_an_explicit_network_allowed_does_not_collide():
    """``local_files_only=False`` plus the wrapper's own ``True`` was a
    TypeError, caught as a cache miss; offline it surfaced as a network
    error caused by a TypeError."""
    from pixcull.model_assets import from_pretrained
    fake = _Recorder(on_disk=True, network=True)
    assert from_pretrained(fake, "m", local_files_only=False) == "from disk"
    assert fake.calls == [True]


@pytest.mark.parametrize("exc", [MemoryError("out of memory loading weights"),
                                 TypeError("unexpected keyword")])
def test_a_load_failure_that_is_not_a_miss_is_not_retried_online(exc):
    """The model is on disk and could not be loaded. Going to the network
    cannot fix that, and with no network it would be reported as one."""
    from pixcull.model_assets import from_pretrained
    calls = []

    class OnDiskButUnloadable:
        @staticmethod
        def from_pretrained(name, **kw):
            calls.append(bool(kw.get("local_files_only")))
            if kw.get("local_files_only"):
                raise exc
            raise OSError("could not reach the hub")

    with pytest.raises(type(exc)):
        from_pretrained(OnDiskButUnloadable, "some/model")
    assert calls == [True], "the network was asked about a local failure"


#: The effect test below needs CLIP on disk, which the hermetic CI run does
#: not have. Naming it "covered elsewhere" is only true if somewhere runs it.
EFFECT_TEST = ("tests/test_runs_without_network.py::"
               "test_loading_a_cached_model_opens_no_socket")
#: v3.94.1 — the aesthetic metrics load outside transformers, so their
#: offline test is separate and needs its own weights in the lane.
AESTHETIC_EFFECT_TEST = ("tests/test_runs_without_network.py::"
                         "test_loading_the_cached_aesthetic_metrics_opens_no_socket")


def _real_model_lane() -> list[str]:
    """The lane's shell, step by step, comments removed: a test named in a
    comment is not a test the lane runs (this check used to search the raw
    file, which a comment would have satisfied)."""
    import re

    import yaml
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml")
                          .read_text("utf-8"))["jobs"]
    job = next(j for j in jobs.values()
               if str(j.get("name", "")).startswith("real-model integration"))
    return ["\n".join(re.sub(r"(^|\s)#.*$", "", line)
                      for line in (step.get("run") or "").splitlines())
            for step in job["steps"]]


def test_the_real_model_lane_runs_the_effect_test():
    steps = _real_model_lane()
    runs = "\n".join(steps)
    for test in (EFFECT_TEST, AESTHETIC_EFFECT_TEST):
        assert test in runs, (
            f"the real-model lane does not run {test}; it skips everywhere "
            "else for want of the weights, so this lane is the only place it "
            "means anything")
    fetch = next((i for i, s in enumerate(steps) if "from_pretrained(" in s), None)
    run = next(i for i, s in enumerate(steps) if EFFECT_TEST in s)
    assert fetch is not None and fetch < run, "the weights must be fetched first"
    assert "facebook/dinov2-base" in steps[fetch]
    assert "from pixcull.scoring.aesthetic import _metrics" in steps[fetch] \
        and "_metrics()" in steps[fetch], (
        "the lane does not fetch the aesthetic metrics' weights through the "
        "product's loader; their offline test would fail there for want of "
        "weights, not for a regression")


#: Every Hugging Face model the analysis loads, by the repo and classes the
#: product passes to model_assets.from_pretrained. v3.94.1 — this test
#: loaded CLIP only; DINOv2 goes through the same wrapper, so a transformers
#: change that touched AutoModel's load path would have passed it.
CACHED_LOADS = {
    "CLIP": (CLIP, ("CLIPProcessor", "CLIPModel")),
    "DINOv2": ("facebook/dinov2-base", ("AutoImageProcessor", "AutoModel")),
}


def _refuse_the_network(monkeypatch) -> list:
    """Every IPv4/IPv6 connect raises and is recorded. Loopback is blocked
    too: a local proxy is how many laptops reach the hub, and a probe that
    let 127.0.0.1 through measured an online run and reported it as
    offline."""
    opened: list = []
    real_connect = socket.socket.connect

    def _refuse(self, addr, *a, **k):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            opened.append(addr)
            raise OSError(101, "network blocked by test")
        return real_connect(self, addr, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    # The loader must set this itself — a cached `.bin` checkpoint starts a
    # background conversion request to the hub otherwise.
    monkeypatch.delenv("DISABLE_SAFETENSORS_CONVERSION", raising=False)
    return opened


def test_the_loads_held_here_are_the_ones_the_product_makes():
    """The repo ids above are what the detectors pass; a renamed model
    would leave this test loading something nothing uses."""
    pkg = Path(__file__).resolve().parent.parent / "pixcull"
    sources = "\n".join(p.read_text(encoding="utf-8") for p in pkg.rglob("*.py"))
    for name, (repo, classes) in CACHED_LOADS.items():
        assert f'"{repo}"' in sources, f"{name}: no detector loads {repo} any more"


@pytest.mark.parametrize("name", sorted(CACHED_LOADS))
def test_loading_a_cached_model_opens_no_socket(monkeypatch, name):
    """Asserted against the socket layer, not against the call order."""
    repo, classes = CACHED_LOADS[name]
    if not is_cached(repo):
        absent(f"{name} is not in the local hub cache on this machine")
    transformers = pytest.importorskip("transformers")
    from pixcull.model_assets import from_pretrained

    opened = _refuse_the_network(monkeypatch)
    for cls in classes:
        assert from_pretrained(getattr(transformers, cls), repo) is not None
    assert opened == [], f"a cached {name} reached for the network: {opened}"


def test_loading_the_cached_aesthetic_metrics_opens_no_socket(monkeypatch):
    """v3.94.1. The aesthetic axis loads its weights outside transformers:
    openai-clip's downloader for the CLIP backbones of laion_aes and
    clipiqa, and pyiqa's load_file_from_url for their heads. Both look on
    disk first; this holds that, through the product's own loader, so an
    update to either cannot start asking the network for a file it has.

    Whether the weights are here is decided by trying with the network
    refused: a laptop without them skips, and the real-model lane, which
    downloads them first and sets PIXCULL_REQUIRE_MODELS, fails instead —
    that lane is where this test means something."""
    pytest.importorskip("pyiqa")
    from pixcull.scoring import aesthetic

    aesthetic._metrics.cache_clear()
    opened = _refuse_the_network(monkeypatch)
    try:
        metrics, _device = aesthetic._metrics()
    except Exception as exc:  # noqa: BLE001 — classified just below
        if opened:
            absent("pyiqa's aesthetic weights are not cached on this machine "
                   f"({type(exc).__name__} after reaching for {opened[0]})")
        raise
    finally:
        aesthetic._metrics.cache_clear()
    assert set(metrics) == {"laion_aes", "clipiqa"}
    assert opened == [], f"a cached aesthetic metric reached for the network: {opened}"
