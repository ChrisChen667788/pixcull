"""v2.85 — hydration rebuilt a hundred identical cards to append 4,269 placeholders.

Background hydration ends with one full render(). On a 5,069-row run
that tore the first hundred cards out of the DOM and built them again —
same photographs, same order — purely so the grid could grow from 800
children to 5,069.

Measured before and after, three samples each:

  image requests         107 -> 55      (54 duplicates -> 2)
  grid rebuilds            2 -> 1
  long tasks after 600ms 125 -> 67 ms
  FIRST-SCREEN READY     798 -> 359 ms

The first-screen number is the surprise, and it corrects v2.84. That
version measured four hypotheses for the warm path, refuted all four,
and concluded the warm path was closed at ~800 ms. It was not: the
viewport thumbnails were being requested twice, and first-screen ready
takes the LATER responseEnd. Every one of v2.84's experiments was
looking one layer below the cause.

The reuse check is conservative by construction. Getting it wrong shows
the wrong photograph under the wrong filename, which is worse than any
render cost, so anything unexpected falls back to the full rebuild.
"""
import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "templates" / "src" / "results.js"
BUILT = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "templates" / "results.html"


def _js_no_comments(text: str) -> str:
    return "\n".join("" if l.lstrip().startswith("//") else l.split("//", 1)[0]
                     for l in text.splitlines())


def _reuse_block() -> str:
    code = _js_no_comments(SRC.read_text(encoding="utf-8"))
    i = code.find("let reusable = 0;")
    assert i > 0, "the append-only path is gone"
    return code[i:i + 2400]


def test_a_card_must_match_the_filename_wanted_at_its_position():
    """Reusing by position alone would leave photograph A's DOM under
    photograph B's index the moment a sort or filter reorders."""
    blk = _reuse_block()
    assert "segRows[i]" in blk
    assert "el.dataset.fn !== want.filename" in blk, (
        "cards are reused without checking the filename at that position")


def test_a_placeholder_must_match_the_index_it_carries():
    blk = _reuse_block()
    assert 'el.dataset.idx !== String(i)' in blk, (
        "placeholders are reused without checking data-idx, so "
        "materialisation would render the wrong segment")


def test_anything_unrecognised_falls_back_to_a_full_rebuild():
    """Scene dividers, and whatever the next version adds, must not be
    silently treated as reusable."""
    blk = _reuse_block()
    assert re.search(r"\}\s*else\s*\{\s*ok\s*=\s*false", blk), (
        "an element that is neither a card nor an indexed placeholder "
        "does not force a rebuild")


def test_reuse_is_refused_when_the_list_did_not_grow():
    """Append-only is only valid when the DOM is a strict PREFIX. A list
    that shrank, or stayed the same length with different contents, must
    rebuild."""
    blk = _reuse_block()
    assert "kids.length < segments.length" in blk, (
        "reuse is not gated on the new list being longer")


def test_the_rebuild_is_skipped_only_when_something_is_reusable():
    code = _js_no_comments(SRC.read_text(encoding="utf-8"))
    i = code.find("let reusable = 0;")
    tail = code[i:i + 3000]
    assert "if (!reusable) {" in tail
    j = tail.find("if (!reusable) {")
    k = tail.find('grid.innerHTML = segments.slice(0, FIRST_BATCH)')
    assert 0 <= j < k, "innerHTML is assigned outside the !reusable guard"


def test_placeholders_start_after_the_reused_prefix():
    """Starting the placeholder loop at FIRST_BATCH after reusing 800
    children would duplicate 700 of them."""
    blk = _reuse_block()
    assert "(reusable || FIRST_BATCH)" in blk, (
        "the placeholder loop does not start after the reused prefix")


def test_the_built_template_carries_the_change():
    """results.html is a build artifact; editing the source without
    rebuilding ships the old page."""
    built = _js_no_comments(BUILT.read_text(encoding="utf-8"))
    assert "let reusable = 0;" in built, "results.html was not rebuilt"
    assert "(reusable || FIRST_BATCH)" in built
