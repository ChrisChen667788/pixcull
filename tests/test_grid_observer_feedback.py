"""v2.68.1 — the MutationObserver feedback loop that froze Safari.

A photographer opened a 5,069-photo run, scrolled, clicked a photo, and
the tab locked up at 100% CPU and never came back. Sampling the
WebContent process mid-freeze put 3,152 of 3,319 main-thread samples
inside ``MutationObserver::notifyMutationObservers``, hottest leaf::

    jsDOMTokenListPrototypeFunction_remove
      -> DOMTokenList::removeInternal
        -> updateAssociatedAttributeFromTokens
          -> Element::setAttributeInternal
            -> MutationObserverInterestGroup::enqueue...
              -> MutationObserver::enqueueMutationRecord

That chain is the bug in one stack: the observer callback writes
``classList`` on every card, each write enqueues another mutation
record, and the delivery loop refills its own queue.

The engine driving it is v2.26's de-materialiser, which swaps cards and
placeholders as DIRECT CHILDREN of the grid — so every scroll is a
``childList`` mutation on the observed node. Two callbacks then re-walked
all 5,069 cards on every swap, wrote to each one, forced layout, changed
what intersected the viewport, and got swapped again.

It converges at ~1.3k rows and does not at 5k, which is why it survived
every test and every earlier session. The 80ms throttle that used to sit
on one of these callbacks could not have helped: throttling a walk that
is itself the cause of the next mutation only slows the loop down.

So the rule this file enforces is structural: **a grid childList
observer reacts to the nodes that arrived, not to the fact that
something changed.**
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "pixcull/report/templates/src"

#: (file, needle identifying the .observe() call on the grid)
GRID_OBSERVERS = [
    ("results.js", "_bucketsObserver.observe(grid"),
    ("modules/23-bookmark-conflicts.js", "mo.observe(gridEl"),
    ("modules/04-hero-reveal.js", "lateObs.observe(grid"),
]


def _strip_comments(js: str) -> str:
    """Line comments out, so the lint reads code and not prose.

    Its first version counted the word `querySelectorAll` inside the
    comment explaining why `querySelectorAll` had been removed, and
    failed the fix it was written to protect.
    """
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in js.splitlines())


def _callback_source(body: str, observe_needle: str) -> str:
    """Source of the MutationObserver whose .observe() matches the needle.

    Handles both an inline callback and ``new MutationObserver(fnName)``
    — the second form is not a loophole, and the first version of this
    helper treated it as one: it read four tokens of source, found no
    ``addedNodes`` in them, and would have failed a correct fix.
    """
    at = body.index(observe_needle)
    start = body.rindex("new MutationObserver", 0, at)
    src = body[start:at]
    named = re.match(r"new MutationObserver\(\s*([A-Za-z_$][\w$]*)\s*\)", src)
    if named:
        fn = named.group(1)
        m = re.search(rf"(?:const|let|var|function)\s+{re.escape(fn)}\b", body)
        assert m, f"cannot find the definition of {fn}"
        return body[m.start():m.start() + 2000]
    return src


@pytest.mark.parametrize("rel,needle", GRID_OBSERVERS)
def test_grid_observers_react_only_to_added_cards(rel, needle):
    body = (SRC / rel).read_text(encoding="utf-8")
    assert needle in body, f"{rel}: the grid observer moved or was renamed"
    cb = _callback_source(body, needle)
    assert "addedNodes" in cb, (
        f"{rel}: this observer fires on every grid mutation without looking "
        f"at what arrived. v2.26's de-materialiser makes a grid mutation out "
        f"of every scroll, so the callback runs constantly — and if it writes "
        f"to the DOM it feeds itself. That combination froze Safari at 5k "
        f"rows for 15+ minutes at 100% CPU.")


@pytest.mark.parametrize("rel,fn", [
    ("results.js", "_refreshCardBucketTags"),
    ("modules/23-bookmark-conflicts.js", "_refreshBookmarkBadges"),
])
def test_the_per_card_walks_can_be_scoped_to_a_subset(rel, fn):
    """Filtering the mutations is only half of it.

    The callbacks also have to be *able* to act on a subset, or the
    filter just hands a short list to a function that walks everything
    anyway.
    """
    body = (SRC / rel).read_text(encoding="utf-8")
    m = re.search(rf"function {re.escape(fn)}\(([^)]*)\)", body)
    assert m, f"{rel}: {fn} is gone"
    assert m.group(1).strip(), (
        f"{fn} takes no arguments, so it can only ever walk the whole grid")


def test_no_grid_observer_requeries_the_grid_per_added_node():
    """`grid.querySelectorAll(...)` inside the per-node loop is O(n^2).

    04-hero-reveal did exactly this — once per added node, during a
    streaming render of thousands. Self-limiting (it disconnects after
    2.2s) and so it never surfaced, but it is the same shape as the bug
    that did.
    """
    body = (SRC / "modules/04-hero-reveal.js").read_text(encoding="utf-8")
    cb = _strip_comments(_callback_source(body, "lateObs.observe(grid"))
    inner = cb[cb.index("addedNodes"):]
    hits = [m.start() for m in re.finditer(r"querySelectorAll", inner)]
    # Zero is fine. One is fine IF it is memoised — the count has to come
    # from somewhere the first time. What is not fine is a query that
    # runs again for every node, which is what this used to do.
    assert len(hits) <= 1, (
        f"{len(hits)} grid queries inside the per-node path")
    for at in hits:
        guard = inner[max(0, at - 160):at]
        assert ("== null" in guard or "=== null" in guard
                or "||" in guard or "if (!" in guard), (
            "the grid is re-queried for every node that arrives; memoise "
            "the count instead")


# ---------------------------------------------------------------------------
# v2.68.2 — layout thrash in the de-materialiser
# ---------------------------------------------------------------------------

#: Properties whose read forces a synchronous layout.
_LAYOUT_READS = ("offsetHeight", "offsetWidth", "offsetTop", "offsetLeft",
                 "getBoundingClientRect", "clientHeight", "clientWidth",
                 "scrollHeight", "getComputedStyle")


def _fn_body(js: str, decl: str) -> str:
    """Source of a `const name = (args) => {...}` arrow function."""
    at = js.index(decl)
    depth, i = 0, js.index("{", at)
    start = i
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces after {decl!r}")


def test_the_dematerialiser_does_not_read_layout_while_mutating():
    """The 527ms long task, and why throttling could never have fixed it.

    `_dematerialize` removes a card and inserts a placeholder. It used to
    read `card.offsetHeight` itself, inside a loop that was also doing
    those removals — so every read after the first forced a fresh
    layout, and laying out this grid costs 8-10ms because it always has
    ~5,069 direct children. The de-materialiser swaps their CONTENTS; it
    never reduces their NUMBER.

    A batch of 50 receding cards therefore paid for 50 full layouts.
    Measured: 8-10ms per forced layout, 527ms median long task while
    scrolling, and zero long tasks with the observer disconnected — it
    was the only source of jank on the page.

    Read-then-write. Same values, all taken before the first mutation.
    """
    js = _strip_comments(
        (SRC / "results.js").read_text(encoding="utf-8"))
    body = _fn_body(js, "const _dematerialize = ")
    for prop in _LAYOUT_READS:
        assert prop not in body, (
            f"_dematerialize reads `{prop}`, forcing a layout inside the "
            f"loop that is mutating the grid")


def test_the_dematerialiser_batches_its_reads():
    """Removing the read from the callee is only half of it — the caller
    has to take every measurement before it starts mutating."""
    js = _strip_comments((SRC / "results.js").read_text(encoding="utf-8"))
    at = js.index("_dematIo = new IntersectionObserver")
    cb = js[at:at + 1400]
    assert "offsetHeight" in cb, (
        "nothing measures the card any more; placeholders will all fall "
        "back to the constant and the scroll position will jump")
    read_at = cb.index("offsetHeight")
    write_at = cb.index("_dematerialize(")
    assert read_at < write_at, (
        "the heights are read after the mutations start, which is the "
        "thrash this fix removed")
