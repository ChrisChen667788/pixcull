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

from tests._model_gate import is_cached

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


@pytest.mark.skipif(not is_cached(CLIP), reason="CLIP is not in the local "
                    "hub cache on this machine")
def test_loading_a_cached_model_opens_no_socket(monkeypatch):
    """Asserted against the socket layer, not against the call order.

    Loopback is blocked too: a local proxy is how many laptops reach the
    hub, and a probe that let 127.0.0.1 through measured an online run
    and reported it as offline.
    """
    transformers = pytest.importorskip("transformers")
    from pixcull.model_assets import from_pretrained

    opened = []
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

    proc = from_pretrained(transformers.CLIPProcessor, CLIP)
    model = from_pretrained(transformers.CLIPModel, CLIP)
    assert proc is not None and model is not None
    assert opened == [], f"a cached model reached for the network: {opened}"
