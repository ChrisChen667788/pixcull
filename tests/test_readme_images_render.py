"""v3.45 — rasterize every README image and look at the pixels.

The hero demo was published as a solid black rectangle. It parsed as
valid XML, it had a title and a desc, its source read plausibly, and
every element was present in the DOM with a computed opacity of 1. None
of that is the same as painting anything: a single sibling rect
animating the paint keyword `none` composited opaque black over the
whole canvas on every tick.

The only check that would have caught it is the one that renders the
image and counts the colours, so that is what this does. It needs
chromium, so it runs in the `browser` job added in v3.42 — before that
job existed a test like this would have skipped in CI and reported green.

`tests/test_readme_image_sources.py` holds the source-level half, which
runs everywhere with no browser.
"""
import base64
import importlib.util as _ilu
import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
PIL = pytest.importorskip("PIL.Image")

# The source-level half is a sibling file, not an installed module.
_spec = _ilu.spec_from_file_location(
    "_readme_image_sources", Path(__file__).resolve().parent
    / "test_readme_image_sources.py")
_srcmod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_srcmod)
ROOT, referenced_images, svgs = (
    _srcmod.ROOT, _srcmod.referenced_images, _srcmod.svgs)

#: Below this many distinct colours the "image" is a flat rectangle.
MIN_DISTINCT_COLOURS = 64
#: Above this share for one colour it is a flat rectangle with a speck.
MAX_DOMINANT_SHARE = 97.0


def _render(page, svg_bytes: bytes, width: int, wait_ms: int, tmp_path: Path):
    """Rasterize the way GitHub embeds it: an <img>, isolated document."""
    b64 = base64.b64encode(svg_bytes).decode()
    page.set_content(
        f'<body style="margin:0;background:#0d1117">'
        f'<img id="i" src="data:image/svg+xml;base64,{b64}" width="{width}">')
    page.wait_for_selector("#i")
    nat = page.evaluate(
        "() => {const i = document.getElementById('i');"
        " return [i.naturalWidth, i.naturalHeight];}")
    page.wait_for_timeout(wait_ms)
    shot = tmp_path / "shot.png"
    # `animations="disabled"` freezes CSS animation and transition to
    # their end state, and the explicit timeout is because this suite
    # shares a machine with the rest of the run: the default 30s screenshot
    # deadline is reachable under load on a page whose SVG animates
    # continuously (the dataflow diagram's dashed pipes), and a gate that
    # goes red for that reason teaches people to ignore it.
    page.screenshot(path=str(shot), animations="disabled", timeout=120_000)
    im = PIL.open(shot).convert("RGB")
    h = min(im.height, int(width * nat[1] / nat[0])) if nat[0] else im.height
    colours = sorted(im.crop((0, 0, min(width, im.width), h))
                     .getcolors(maxcolors=500_000), reverse=True)
    total = sum(c for c, _ in colours)
    return len(colours), colours[0][1], 100.0 * colours[0][0] / total


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception as exc:                        # noqa: BLE001
            pytest.skip(f"chromium unavailable: {exc}")
        ctx = br.new_context(viewport={"width": 1280, "height": 800})
        yield ctx.new_page()
        br.close()


@pytest.mark.parametrize("rel", [p.relative_to(ROOT).as_posix()
                                 for p in referenced_images()])
def test_every_readme_image_actually_paints_something(rel, page, tmp_path):
    """The check that would have caught it. Not "does it parse" — does it
    put more than one colour on the screen."""
    p = ROOT / rel
    n, dominant, share = _render(page, p.read_bytes(), 1280, 4000, tmp_path)
    assert n >= MIN_DISTINCT_COLOURS and share <= MAX_DOMINANT_SHARE, (
        f"{rel} renders as a flat rectangle: {n} distinct colours, "
        f"{share:.1f}% of pixels are {dominant}. It parses; it does not paint.")


@pytest.mark.parametrize("rel", [p.relative_to(ROOT).as_posix() for p in svgs()])
def test_every_svg_is_legible_without_animation(rel, page, tmp_path):
    """An <img>-embedded SVG is an isolated document, and plenty of
    renderers drop SMIL. The static frame has to be the finished one, so
    strip every animation element and check it still paints."""
    src = (ROOT / rel).read_text(encoding="utf-8")
    stripped = re.sub(r"<animate[\s\S]*?/>", "", src)
    stripped = re.sub(r"<animate[A-Za-z]*\b[\s\S]*?</animate[A-Za-z]*>", "",
                      stripped)
    n, dominant, share = _render(page, stripped.encode(), 1280, 300, tmp_path)
    assert n >= MIN_DISTINCT_COLOURS and share <= MAX_DOMINANT_SHARE, (
        f"{rel} is blank without SMIL: {n} distinct colours, {share:.1f}% "
        f"{dominant}. Author the finished frame and animate from hidden to it.")


def test_the_original_defect_still_reproduces(page, tmp_path):
    """The regression test proper. Put the deleted construct back and
    confirm it still blacks the canvas out — if a browser ever stops
    doing this, the rule above is protecting against nothing and should
    say so out loud rather than passing quietly."""
    hero = ROOT / "docs" / "brand" / "pixcull-hero-reveal-demo.svg"
    poisoned = hero.read_text(encoding="utf-8").replace(
        "</svg>",
        '  <rect width="1280" height="720" fill="none">\n'
        '    <animate attributeName="fill" values="none;none" dur="6s"\n'
        '             repeatCount="indefinite"/>\n'
        '  </rect>\n</svg>')
    n, dominant, share = _render(page, poisoned.encode(), 1280, 1500, tmp_path)
    assert n < MIN_DISTINCT_COLOURS or share > MAX_DOMINANT_SHARE, (
        "animating the paint keyword `none` no longer blacks out the "
        f"canvas here ({n} colours, {share:.1f}% {dominant}) — the source "
        "rule in test_readme_image_sources.py may now be guarding nothing")
