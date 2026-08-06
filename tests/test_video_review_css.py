"""v2.44-P2 — every CSS variable a template uses must be one it defines.

Found by probing the live page: the v2.43 transcript panel styled itself
with the shared design tokens (``--fg-2``, ``--muted``, ``--surface-2``,
``--border``, ``--focus-ring``, ``--accent-soft``), and
``video_review.html`` never receives those.  It declares its own palette
— ``--ink``, ``--dim``, ``--line``, ``--panel-solid``, ``--indigo`` — in
a ``:root`` block at the top.

An undefined ``var()`` makes the whole declaration invalid at
computed-value time, so the property falls back to inherited or initial.
That is quiet: text still had a colour (inherited), so the panel looked
fine.  What was actually gone were the things with nothing to inherit —
``:hover`` backgrounds resolved to nothing, so the rows had no hover
feedback at all.

This is the same failure mode as the v2.3.1 palette leak: CSS that reads
correctly and does not do what it says.  Only a live DOM probe or a lint
like this one catches it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / \
    "pixcull" / "report" / "templates"

# Variables the server injects into every template it serves through
# _read_template (design tokens + theme boot). Templates may rely on
# these without declaring them.
_INJECTED_PREFIXES = ("--pc-",)

_DEF = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")
_USE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,([^()]*(?:\([^()]*\))?[^()]*))?\)")


def _strip_comments(css: str) -> str:
    """A commented-out example must not count as a definition or a use."""
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


def _style_blocks(html: str) -> str:
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))


def _defined_and_used(path: Path) -> tuple[set[str], dict[str, bool]]:
    css = _strip_comments(_style_blocks(path.read_text(encoding="utf-8")))
    defined = set(_DEF.findall(css))
    used: dict[str, bool] = {}
    for name, fallback in _USE.findall(css):
        # A var() with a fallback still renders when undefined, so it is
        # a deliberate optional, not a mistake.
        used[name] = used.get(name, False) or bool((fallback or "").strip())
    return defined, used


def _self_contained_templates() -> list[Path]:
    """Templates that carry their own palette rather than the tokens."""
    out = []
    for p in sorted(TEMPLATES.glob("*.html")):
        defined, _ = _defined_and_used(p)
        if any(v in defined for v in ("--ink", "--bg", "--fg")):
            out.append(p)
    return out


@pytest.mark.parametrize("path", _self_contained_templates(),
                         ids=lambda p: p.name)
def test_no_undefined_css_variables(path: Path):
    defined, used = _defined_and_used(path)
    missing = sorted(
        n for n, has_fallback in used.items()
        if n not in defined and not has_fallback
        and not n.startswith(_INJECTED_PREFIXES))
    assert not missing, (
        f"{path.name} uses CSS variables it never defines: {missing}\n"
        f"It declares its own palette ({sorted(defined)[:8]}…), so the "
        f"shared design tokens are NOT available here. Either use this "
        f"page's own names or give the var() a fallback.")


def test_video_review_is_actually_covered():
    """The parametrisation must not quietly select nothing.

    A discovery helper that returns an empty list turns this whole file
    into zero tests while still reporting green — the shape of failure
    this repo keeps finding.
    """
    names = {p.name for p in _self_contained_templates()}
    assert "video_review.html" in names, (
        f"video_review.html not picked up for linting; found {names}")


def test_transcript_panel_hover_has_a_real_background():
    """The specific thing that was broken: hover resolved to nothing."""
    css = _strip_comments(
        _style_blocks((TEMPLATES / "video_review.html").read_text("utf-8")))
    m = re.search(r"\.tx-line:hover\s*\{([^}]*)\}", css)
    assert m, ".tx-line:hover rule is gone"
    body = m.group(1)
    assert "background" in body, "hover no longer sets a background"
    for name, fallback in _USE.findall(body):
        defined, _ = _defined_and_used(TEMPLATES / "video_review.html")
        assert name in defined or fallback.strip(), (
            f"hover background depends on undefined {name}")


# ── v2.46 — speaker chips ─────────────────────────────────────────────

_TPL = TEMPLATES / "video_review.html"


def _js() -> str:
    """The page's inline script, comments stripped."""
    html = _TPL.read_text(encoding="utf-8")
    js = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I))
    return re.sub(r"//[^\n]*", "", js)


def test_speaker_chip_is_only_rendered_when_a_label_exists():
    """No label must mean no chip, not a chip reading "0".

    Paraformer reports None rather than 0 when its clusterer could not
    tell people apart, and Whisper never reports speakers at all. A chip
    in either case would show a finding the model never made.
    """
    js = _js()
    assert "tx-spk" in js, "speaker chip markup is gone"
    m = re.search(r"const spk\s*=\s*\((.*?)\)\s*\n?\s*\?", js, re.S)
    assert m, "the chip's null-guard is gone"
    guard = m.group(1)
    assert "undefined" in guard and "null" in guard, (
        f"chip guard no longer covers both absent forms: {guard.strip()!r}")


def test_speaker_chip_lives_outside_the_editable_text_span():
    """paintEdit() rewrites the text span; a chip inside it gets wiped.

    Measured when the chip was first added: 23 chips rendered, 0 left
    after the first paintEdit(), because the span's textContent then
    read "0新郎新娘…" while the server said "新郎新娘…", so the repaint
    replaced the lot with plain text.
    """
    js = _js()
    m = re.search(r"'<span class=\"tx-t\">'\+fmtT\([^)]*\)([^\n]*)", js)
    assert m, "timestamp span markup changed shape"
    assert "spk" in m.group(1), (
        "the speaker chip is no longer emitted inside the timestamp span; "
        "putting it in the text span makes paintEdit strip it")
    # and it must NOT be in the text span
    m2 = re.search(r"'<span>'\+([a-zA-Z+ ]*)\+'</span></button>'", js)
    assert m2, "text span markup changed shape"
    assert "spk" not in m2.group(1), (
        f"chip is back inside the text span: {m2.group(1)!r}")


def test_paint_edit_compares_against_what_is_displayed():
    """v2.45.1's fix — compare with the DOM, not with the original."""
    js = _js()
    assert "lastElementChild.textContent !== x.kept_text" in js, (
        "paintEdit no longer compares against the displayed text; undoing "
        "a word-level cut will leave stale text on screen")
