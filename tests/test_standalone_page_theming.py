"""v2.35 — every standalone page honours the user's light/dark choice.

The bug: `_DESIGN_TOKENS_CSS` has carried a complete
``html[data-theme="light"]` block since v2.2, but the pages that inject
those tokens never set `data-theme`, so light theme had never once
applied on /library, /history, /tether, /admin, /upload, /verticals,
/privacy, /first_run, /admin/disagreement or /vertical_bulk.  Five of
those didn't even inject the tokens: their module-level constants are
built ABOVE where `_DESIGN_TOKENS_CSS` used to be defined, so the
``.replace`` would have raised NameError and was simply never written —
leaving them on a hand-rolled pre-v2.21 palette.

Both injections now happen inside `_read_template`, once, so a page
added later cannot forget either.  These tests lock that in.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PAGES_DIR = REPO / "pixcull" / "report" / "templates" / "pages"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "serve_app_theming_test", REPO / "pixcull" / "report" / "serve_app.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["serve_app_theming_test"] = m
    spec.loader.exec_module(m)
    return m


def _page_templates():
    return sorted(PAGES_DIR.glob("*.html"))


def test_there_are_page_templates_to_check():
    assert _page_templates(), "no page templates found — path drifted?"


@pytest.mark.parametrize("page", _page_templates(), ids=lambda p: p.name)
def test_every_page_declares_the_shared_tokens(page):
    """A page with its own palette silently misses every future design
    change — and, before v2.35, light theme entirely."""
    assert "/*__DESIGN_TOKENS_CSS__*/" in page.read_text(encoding="utf-8"), (
        f"{page.name} does not inject the shared design tokens; it will "
        f"drift from the design system and cannot respond to data-theme")


@pytest.mark.parametrize("page", _page_templates(), ids=lambda p: p.name)
def test_no_page_redefines_a_core_colour_token(page):
    """Redefining --bg/--fg/--accent locally is what broke theming: the
    page's own value wins over the shared light block for that token."""
    text = page.read_text(encoding="utf-8")
    # strip the injected-token marker comment lines; look only at what
    # the page itself declares
    own = set(re.findall(
        r'(--(?:bg|fg|accent|border|muted|chrome|surface)[a-z0-9-]*)\s*:',
        text))
    # --bg-grad is a page-specific gradient, not a palette override
    own.discard("--bg-grad")
    assert not own, (
        f"{page.name} declares its own core colour tokens {sorted(own)} — "
        f"these must come from _DESIGN_TOKENS_CSS so light theme reaches it")


@pytest.mark.parametrize("page", _page_templates(), ids=lambda p: p.name)
def test_read_template_injects_tokens_and_theme_boot(mod, page):
    html = mod._read_template(f"pages/{page.name}")
    assert "/*__DESIGN_TOKENS_CSS__*/" not in html, (
        f"{page.name}: token marker survived — tokens were not injected")
    assert 'html[data-theme="light"]' in html, (
        f"{page.name}: no light-theme block in the rendered page")
    assert "pixcull_theme" in html, (
        f"{page.name}: theme-boot script missing, so data-theme is never "
        f"set and the light block above can never match")


@pytest.mark.parametrize("page", _page_templates(), ids=lambda p: p.name)
def test_theme_boot_runs_before_the_body(mod, page):
    """Setting data-theme after first paint would flash the wrong theme."""
    html = mod._read_template(f"pages/{page.name}")
    boot = html.index("pixcull_theme")
    head_end = html.index("</head>")
    assert boot < head_end, f"{page.name}: theme boot is not inside <head>"


def test_boot_mirrors_the_toggle_contract(mod):
    """The standalone pages must resolve the preference exactly the way
    results.js's toggle does, or the two disagree."""
    boot = mod._THEME_BOOT_HTML
    toggle = (REPO / "pixcull" / "report" / "templates" / "src" / "modules"
              / "29-theme-toggle.js").read_text(encoding="utf-8")
    for token in ('"pixcull_theme"', "prefers-color-scheme: light",
                  '"data-theme"'):
        assert token in boot, f"boot script lost {token}"
        assert token in toggle, (
            f"{token} no longer in the toggle — the two theme paths have "
            f"diverged; update both together")


def test_boot_is_not_injected_twice(mod):
    """_read_template is called on every request for some pages; a second
    injection would run the script twice."""
    html = mod._read_template("pages/library.html")
    assert html.count("pixcull_theme") == 1


def test_pages_without_a_head_are_left_alone(mod, tmp_path, monkeypatch):
    """Fragment templates must not get a <script> stapled to them."""
    frag = PAGES_DIR.parent / "_theming_probe_fragment.html"
    frag.write_text("<div>just a fragment</div>", encoding="utf-8")
    try:
        out = mod._read_template("_theming_probe_fragment.html")
        assert out == "<div>just a fragment</div>"
    finally:
        frag.unlink()


# ── v2.37 — the three inline-HTML builders ─────────────────────────────
#
# These never went through _read_template (they are f-string builders, a
# deliberate v2.27 call), so v2.35's roll-up missed them entirely: the
# client-facing share page was still on a THIRD palette (--bg #0a0a1e /
# --bg-soft #1a1230, purple-navy) with `color-scheme: dark` hard-locked,
# and the other two were on the pre-v2.21 gold.  They now interpolate
# _DESIGN_TOKENS_CSS + _THEME_BOOT_HTML directly.

import ast

_INLINE_BUILDERS = ("_render_share_html", "_serve_bias_audit_page",
                    "_serve_companion_page")

# Colour literals that are deliberately theme-independent:
#   * the photo lightbox is always dark — a light lightbox would wash out
#     the photo being judged, so its scrim and its white-on-dark controls
#     are correct as literals;
#   * plain black drop shadows read correctly on both themes;
#   * the brand logo gradient must NOT invert with the theme.
_ALLOWED_LITERALS = {
    "rgba(0,0,0,0.94)", "rgba(0,0,0,0.7)", "rgba(0,0,0,0.6)",
    "rgba(255,255,255,0.08)", "rgba(255,255,255,0.18)",
    "rgba(255,255,255,0.06)", "rgba(255,255,255,0.15)",
    "#d5b584", "#93743f",          # <stop> colours of the SVG logo
    "#161616",                     # documented var() fallback
}


def _builder_source(mod_src, name):
    """Source of one builder, with comments stripped.

    Comments must go before linting, and not for tidiness: the comment
    explaining *why* the share page dropped its old palette necessarily
    quotes that palette (#1a1230) and the `color-scheme: dark` it
    removed.  A lint that reads comments flags its own documentation —
    which is exactly what happened the first time these ran.
    """
    tree = ast.parse(mod_src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert fn is not None, f"{name} not found — renamed?"
    end = max(getattr(n, "lineno", fn.lineno) for n in ast.walk(fn))
    src = "\n".join(mod_src.splitlines()[fn.lineno - 1:end])
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)          # CSS comments
    return "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))       # py comments


@pytest.fixture(scope="module")
def impl_src():
    return (REPO / "pixcull" / "report" / "serve_app.py").read_text("utf-8")


@pytest.mark.parametrize("name", _INLINE_BUILDERS)
def test_inline_builder_uses_shared_tokens_and_theme_boot(impl_src, name):
    src = _builder_source(impl_src, name)
    assert "_DESIGN_TOKENS_CSS" in src, (
        f"{name} does not interpolate the shared design tokens — it will "
        f"drift from the design system as /share once did")
    assert "_THEME_BOOT_HTML" in src, (
        f"{name} never sets data-theme, so the light block cannot match")


@pytest.mark.parametrize("name", _INLINE_BUILDERS)
def test_inline_builder_has_no_theme_breaking_colour_literals(impl_src, name):
    """Catches BOTH notations.

    v2.3.1 was caused by a leaked palette hiding in decimal rgba() where a
    hex grep could not see it, and the same thing happened again here: the
    share page's navy brand bar was `rgba(10,10,30,0.85)` and survived the
    first hex-only sweep of this very change.
    """
    src = _builder_source(impl_src, name)
    found = set()
    for m in re.finditer(r"rgba?\([^)]*\)", src):
        lit = re.sub(r"\s+", "", m.group(0))
        if re.match(r"rgba?\(\d+,\d+,\d+", lit) and lit not in _ALLOWED_LITERALS:
            found.add(lit)
    for m in re.finditer(r"#[0-9a-fA-F]{6}\b", src):
        if m.group(0) not in _ALLOWED_LITERALS:
            found.add(m.group(0))
    assert not found, (
        f"{name} carries theme-breaking colour literals {sorted(found)}; "
        f"use a design token so light theme reaches it (or add to "
        f"_ALLOWED_LITERALS with a reason if genuinely theme-independent)")


def test_share_page_is_not_locked_to_dark(impl_src):
    """`color-scheme: dark` on the client delivery page overrode the whole
    point of the theme system."""
    src = _builder_source(impl_src, "_render_share_html")
    assert "color-scheme: dark" not in src, (
        "share page is hard-locked to dark again")
