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
