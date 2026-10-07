"""v3.94.1 — the aesthetic axis was missing from every fresh install.

pyiqa builds laion_aes and clipiqa on `clip` (openai-clip 1.0.1), whose
module starts with `from pkg_resources import packaging`. setuptools 82
(2026-02-08) removed pkg_resources, and torch requires setuptools (2.14:
>=77.0.3 on every Python), so a fresh install gets the newest and `import
clip` raised, `AestheticScorer` caught the
ImportError, and runs went on with five axes and a warning telling the
user to install pyiqa, which was installed. 3.92.0, 3.93.1 and 3.94.0 all
shipped like that; reproduced on 3.94.0 in a fresh Python 3.13 install
(setuptools 84): `aesthetic metrics produced: []`. No test noticed because
none imports clip without the weights, and a laptop that has had setuptools
for a while still has pkg_resources — this one has 81.

These run the real openai-clip module with pkg_resources made absent the
way setuptools 82 leaves it: the bare import fails (the control), the
product's loader gets through it, and nothing is left behind.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys

import pytest

from pixcull.scoring import aesthetic


class _NoPkgResources:
    """A meta-path finder that makes pkg_resources unimportable, unless
    something has put a module in sys.modules (which is checked first)."""

    def find_spec(self, name, path=None, target=None):
        if name == "pkg_resources" or name.startswith("pkg_resources."):
            raise ModuleNotFoundError("No module named 'pkg_resources'", name=name)
        return None


@pytest.fixture
def setuptools_82(monkeypatch):
    """pkg_resources gone, and no clip imported yet."""
    for name in list(sys.modules):
        if name == "pkg_resources" or name.startswith("pkg_resources."):
            monkeypatch.delitem(sys.modules, name)
        if name == "clip" or name.startswith("clip."):
            monkeypatch.delitem(sys.modules, name)
    real_find_spec = importlib.util.find_spec

    def find_spec(name, *a, **k):
        if name == "pkg_resources":
            return None
        return real_find_spec(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    blocker = _NoPkgResources()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
    yield
    for name in list(sys.modules):
        if name == "clip" or name.startswith("clip."):
            del sys.modules[name]


def test_openai_clip_is_what_pyiqa_imports():
    """The premise. If pyiqa stops depending on openai-clip, or clip stops
    reading pkg_resources, the shim has nothing to do."""
    spec = importlib.util.find_spec("clip")
    assert spec is not None, "openai-clip is not installed; pyiqa requires it"
    import re
    from pathlib import Path
    taken = set()
    for py in Path(spec.origin).parent.glob("*.py"):
        for names in re.findall(r"^\s*from pkg_resources import (.+)$",
                                py.read_text(encoding="utf-8"), re.M):
            taken |= {n.strip() for n in names.split(",")}
        assert not re.search(r"^\s*import pkg_resources", py.read_text(encoding="utf-8"), re.M), (
            f"{py.name} imports pkg_resources whole; the shim supplies one name")
    assert taken == {"packaging"}, (
        f"openai-clip takes {sorted(taken)} from pkg_resources; the shim "
        "supplies only `packaging`")


def test_without_the_shim_clip_cannot_be_imported(setuptools_82):
    """The control: the failure every fresh install had."""
    with pytest.raises(ModuleNotFoundError, match="pkg_resources"):
        importlib.import_module("clip")


def test_the_loader_gets_clip_through(setuptools_82):
    with aesthetic._pkg_resources_for_openai_clip():
        clip = importlib.import_module("clip")
    assert hasattr(clip, "load")


def test_nothing_is_left_behind(setuptools_82):
    """A library that probes for pkg_resources afterwards must find it
    absent, not a module with one attribute."""
    with aesthetic._pkg_resources_for_openai_clip():
        importlib.import_module("clip")
    assert "pkg_resources" not in sys.modules
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pkg_resources")


def test_metrics_are_built_inside_the_shim(setuptools_82, monkeypatch):
    """The wiring, without weights: pyiqa.create_metric is where clip gets
    imported, and _metrics must call it inside the shim."""
    pyiqa = pytest.importorskip("pyiqa")
    built = []

    def create_metric(name, device=None):
        importlib.import_module("clip")
        built.append(name)
        return object()

    monkeypatch.setattr(pyiqa, "create_metric", create_metric)
    aesthetic._metrics.cache_clear()
    try:
        metrics, _device = aesthetic._metrics()
    finally:
        aesthetic._metrics.cache_clear()
    assert built == ["laion_aes", "clipiqa"] and set(metrics) == set(built)


def test_a_real_pkg_resources_is_left_alone(monkeypatch):
    """Where setuptools < 82 is installed nothing is substituted."""
    sentinel = type(sys)("pkg_resources")
    monkeypatch.setitem(sys.modules, "pkg_resources", sentinel)
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: object() if name == "pkg_resources" else None)
    monkeypatch.delitem(sys.modules, "clip", raising=False)
    with aesthetic._pkg_resources_for_openai_clip():
        assert sys.modules["pkg_resources"] is sentinel
    assert sys.modules["pkg_resources"] is sentinel


@pytest.mark.parametrize("missing,says", [
    ("pkg_resources", "the import that failed is pkg_resources"),
    ("pyiqa", "pip install pyiqa"),
])
def test_the_warning_names_what_actually_failed(monkeypatch, caplog, missing, says):
    """It used to tell everyone to install pyiqa."""
    pytest.importorskip("torch")
    from PIL import Image

    def broken():
        raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)

    monkeypatch.setattr(aesthetic, "_metrics", broken)
    with caplog.at_level(logging.WARNING, logger="pixcull.scoring.aesthetic"):
        out = aesthetic.AestheticScorer().analyze(Image.new("RGB", (32, 32)))
    assert out.flags == ["aesthetic_unavailable"]
    assert says in caplog.text
    if missing != "pyiqa":
        assert "pip install pyiqa" not in caplog.text
