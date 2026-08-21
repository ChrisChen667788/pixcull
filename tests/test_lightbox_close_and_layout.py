"""v2.68.3 — closing the lightbox locked the tab, and the nav arrows sat
on top of the inspector.

Both reported from one screenshot, both real, and the first one is the
freeze the photographer had been hitting all along::

    const _lbOpenObserver = new MutationObserver(() => {
      if (!lb.classList.contains("show")) {
        lb.classList.remove("info-expanded");     // writes what it watches
      }
    });
    _lbOpenObserver.observe(lb, {attributes: true, attributeFilter: ["class"]});

`DOMTokenList.remove()` runs its "update steps" unconditionally — the
class attribute is re-serialised and SET whether or not the token was
present — and setting an attribute queues a mutation record even when
the value does not change. Close the lightbox, `show` goes away, the
callback removes an absent token, the write queues another record, the
callback runs again. 100% CPU until reload.

It can only fire on CLOSE: with `show` present the branch is skipped.
That is exactly how it was reported — opening a photo was fine, exiting
killed the page — and it matches the WebContent sample taken during the
freeze, whose hottest leaf was
`DOMTokenList::remove -> setAttributeInternal -> enqueueMutationRecord`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "pixcull/report/templates/src"


def test_the_lightbox_class_observer_does_not_write_unconditionally():
    """A callback that observes `class` and writes `class` must check
    first, or the write is its own next event."""
    js = (SRC / "modules/27-lb-touch.js").read_text(encoding="utf-8")
    at = js.index("_lbOpenObserver = new MutationObserver")
    body = js[at:js.index("_lbOpenObserver.observe", at)]
    assert 'classList.remove("info-expanded")' in body, (
        "the callback changed shape; re-check this guard against it")
    assert 'classList.contains("info-expanded")' in body, (
        "the callback removes `info-expanded` without checking whether it "
        "is there. DOMTokenList.remove() sets the class attribute either "
        "way, that queues a mutation record, and this observer watches "
        "class on the very element it just wrote to — an unconditional "
        "write here is an infinite loop on every close.")


# ---------------------------------------------------------------------------
# Layout: everything on the right edge belongs to the IMAGE column
# ---------------------------------------------------------------------------

CSS = SRC / "modules/lightbox.css"


def test_the_inspector_width_has_exactly_one_definition():
    """`right: 408px` and `right: 452px` were 380 + 28 and 380 + 72.

    Three controls each carried their own copy of the inspector's width,
    written as a magic number, and `.nav-next` carried a fourth answer —
    `right: 18px`, the viewport edge — which is why the next-photo arrow
    rendered on top of the inspector with half of it off-screen.
    """
    css = CSS.read_text(encoding="utf-8")
    assert "--lb-inspector-w" in css, "the width is not a variable"
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for magic in ("right: 408px", "right: 452px"):
        assert magic not in body, (
            f"`{magic}` is a hardcoded guess at the inspector width")
    assert "grid-template-columns: 1fr 380px" not in body, (
        "the grid still hardcodes the width the controls now read from a "
        "variable, so the two can drift apart")


def test_the_nav_arrows_are_symmetric_about_the_image():
    """Left and right arrows must sit the same distance inside the image
    column — which means the right one has to clear the inspector."""
    body = re.sub(r"/\*.*?\*/", "",
                  CSS.read_text(encoding="utf-8"), flags=re.S)
    prev = re.search(r"\.nav-prev\s*\{\s*left:\s*([0-9]+)px", body)
    nxt = re.search(
        r"\.nav-next\s*\{\s*right:\s*calc\(var\(--lb-inspector-w\)\s*\+\s*"
        r"([0-9]+)px\)", body)
    assert prev, "nav-prev's offset moved"
    assert nxt, (
        "nav-next is not positioned against the image column. Absolutely-"
        "positioned children of `.lightbox` resolve `right` against the "
        "whole grid, so a bare `right: 18px` lands inside the inspector.")
    assert prev.group(1) == nxt.group(1), (
        f"asymmetric: prev sits {prev.group(1)}px from the image's left "
        f"edge, next {nxt.group(1)}px from its right")


@pytest.mark.parametrize("selector", [".close-btn", ".rotate-grp"])
def test_right_edge_controls_clear_the_inspector(selector):
    body = re.sub(r"/\*.*?\*/", "",
                  CSS.read_text(encoding="utf-8"), flags=re.S)
    at = body.index(f".lightbox {selector}")
    rule = body[at:body.index("}", at)]
    assert "var(--lb-inspector-w)" in rule, (
        f"{selector} positions itself against the viewport, so it will "
        f"overlap the inspector at any width but the one it was tuned to")
