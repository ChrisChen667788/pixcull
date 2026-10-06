"""v3.0.3 — a re-shot screenshot has to reach ModelScope.

The sync workflow watched `modelscope/README.md` and the sync script.
Replacing an image leaves both untouched, so nothing fired and the model
card went on serving the old picture — indefinitely, and silently,
because every local check reports the assets as "hosted": they are, just
not the current ones.

Found the day 25 and 26 were replaced with real photographs and the
ModelScope card kept showing the synthetic samples.
"""
import importlib.util
import re
from pathlib import Path

import pytest

WF = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
      / "sync-modelscope.yml")
README = Path(__file__).resolve().parents[1] / "modelscope" / "README.md"


def _paths() -> list[str]:
    text = WF.read_text(encoding="utf-8")
    m = re.search(r"^\s*paths:\s*$((?:\s*(?:#[^\n]*|-\s*'[^']+')\s*$)+)",
                  text, re.M)
    assert m, "the workflow has no paths filter"
    return re.findall(r"-\s*'([^']+)'", m.group(1))


def test_the_screenshots_are_watched():
    pats = _paths()
    assert any(p.startswith("docs/screenshots") for p in pats), (
        "replacing a screenshot changes no watched file, so ModelScope "
        "keeps serving the old one and nothing says so")


def test_the_readme_is_still_watched():
    """Adding the images must not have replaced the text trigger."""
    assert any(p.endswith("modelscope/README.md") for p in _paths())


def _sync_module():
    path = (Path(__file__).resolve().parents[1] / "scripts"
            / "sync_modelscope_readme.py")
    spec = importlib.util.spec_from_file_location("_sync_for_triggers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_image_the_card_references_is_covered_by_a_watched_path():
    """The real invariant: whatever the model card shows must be able to
    trigger a sync when it changes.

    "Whatever the card shows" is what the sync hosts, so the references are
    found with the sync's own pattern.  This test used to carry its own,
    for png, svg and gif in Markdown image syntax: a jpg, a webp, an
    ``<img>`` tag or the film's mp4 could change without a sync, and this
    reported nothing because it was not looking for them.

    A file the card loads from raw.githubusercontent.com is served by
    GitHub, current on every push, and needs no sync; the brand lockup and
    the hero are loaded that way.  Everything else the card loads from
    ModelScope — a relative path, or a modelscope.cn address like the
    film's — and is only as current as the last sync."""
    text = re.sub(r"https://raw\.githubusercontent\.com/\S+", "",
                  README.read_text(encoding="utf-8"))
    refs = set(_sync_module().ASSET_RE.findall(text))
    assert refs, "the card references no images — check the regex"
    assert "docs/video/pixcull-30s.mp4" in refs, (
        "the pattern no longer sees the film the card links")
    pats = _paths()
    def covered(ref: str) -> bool:
        for p in pats:
            base = p.rstrip("*").rstrip("/")
            if ref == p or ref.startswith(base + "/") or ref.startswith(base):
                return True
        return False
    missed = sorted(r for r in refs if not covered(r))
    assert not missed, (
        "these images can change without triggering a sync, so the card "
        f"would keep the old ones: {missed[:6]}")
