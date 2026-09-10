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
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Every place the package pulls a model down from the hub.
HUB_CALLERS = (
    "pixcull/detectors/scene.py",
    "pixcull/detectors/duplicate.py",
    "pixcull/scoring/reel_caption.py",
)


def test_nothing_calls_from_pretrained_without_the_offline_fallback():
    """A new caller that goes straight to `transformers` reintroduces the
    defect for whichever model it loads, and nothing would say so until
    somebody ran the product with the wifi off."""
    bad = []
    for rel in HUB_CALLERS:
        src = (ROOT / rel).read_text(encoding="utf-8")
        body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        for m in re.finditer(r"(\w+)\.from_pretrained\(", body):
            # `_fp(Cls, name)` is the wrapper; `Cls.from_pretrained(` is
            # the raw call. The wrapper's own definition lives in
            # model_assets and is not in this list.
            bad.append(f"{rel}: {m.group(0)}")
    assert not bad, (
        "these call transformers directly and will fail with no network "
        f"even when the model is cached: {bad}. Use "
        "pixcull.model_assets.from_pretrained.")


def test_the_fallback_tries_the_network_first_then_the_disk():
    """Order matters both ways: local-only first would never pick up an
    updated model, and network-only is the bug."""
    from pixcull.model_assets import from_pretrained

    calls = []

    class Fake:
        @staticmethod
        def from_pretrained(name, **kw):
            calls.append(kw.get("local_files_only", False))
            if not kw.get("local_files_only"):
                raise OSError("Can't load processor for " + name)
            return "from disk"

    assert from_pretrained(Fake, "some/model") == "from disk"
    assert calls == [False, True], (
        f"expected a network attempt then a disk attempt, got {calls}")


def test_a_model_that_is_genuinely_absent_reports_the_useful_error():
    """When nothing is cached AND there is no network, the message the
    user needs is the first one — it names what to fix."""
    from pixcull.model_assets import from_pretrained

    class Fake:
        @staticmethod
        def from_pretrained(name, **kw):
            raise OSError("no network, and nothing cached")

    with pytest.raises(OSError, match="no network, and nothing cached"):
        from_pretrained(Fake, "some/model")
