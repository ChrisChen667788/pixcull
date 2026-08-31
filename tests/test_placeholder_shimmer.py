"""v2.78 — nothing animates off-screen, forever, for nobody.

`.card-placeholder` carried `animation: ... infinite`. A 5,069-photo run
has 4,969 placeholders, and background-position is not compositable, so
every frame recalculated style for all of them.

Measured on a 5,069-row run:
  page load     style recalc  856 ms -> 114 ms, main thread 2685 -> 1810 ms
  6s idle       style recalc 2420 ms ->  30 ms, main thread 6003 -> 2680 ms

The idle figure is the one that matters. 2420 ms of style recalc in 6 s
of doing nothing is roughly 40% of a core, held for as long as the page
is open — a photographer culling all afternoon paid that in battery.

And the shimmer was never visible. The materialising observer runs
40-200% ahead of the viewport, so a placeholder becomes a real card
before it can be seen; with the materialiser disconnected the mechanism
lights 12 of 12 on-screen placeholders, and with it connected, zero,
through instant jumps to 35/70/95% of the page. The cost was real and
the effect was not.
"""
import re
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "templates"
CSS = TPL / "src" / "results.css"
JS = TPL / "src" / "results.js"
BUILT = TPL / "results.html"


def _css_no_comments(text: str) -> str:
    """Strip /* ... */ so a rule's own explanation cannot satisfy a check."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _js_no_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        s = line.lstrip()
        out.append("" if s.startswith("//") else line.split("//", 1)[0])
    return "\n".join(out)


def _rule_bodies(css: str, selector: str) -> list[str]:
    """Every rule whose selector list contains exactly this selector.

    All of them, not the last one: the last is the
    prefers-reduced-motion override, whose body is `animation: none`,
    so "the last rule mentions animation" is true of a page where the
    shimmer never runs at all.
    """
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sels = [s.strip() for s in m.group(1).split(",")]
        if selector in sels:
            out.append(m.group(2))
    return out


def test_bare_placeholder_does_not_animate():
    css = _css_no_comments(CSS.read_text(encoding="utf-8"))
    bodies = _rule_bodies(css, ".card-placeholder")
    assert bodies, "the .card-placeholder rule vanished"
    assert not any("animation" in b for b in bodies), (
        "an infinite animation on .card-placeholder runs on every "
        "off-screen placeholder — 4,969 of them on a 5k run, 2.4 s of "
        "style recalc per 6 s of idle"
    )


def test_the_shimmer_is_scoped_to_on_screen_placeholders():
    css = _css_no_comments(CSS.read_text(encoding="utf-8"))
    bodies = _rule_bodies(css, ".card-placeholder.pc-ph-onscreen")
    assert bodies, "the scoped shimmer rule is missing"
    assert any("pcPlaceholderShimmer" in b for b in bodies), (
        "the only scoped rule is the reduced-motion override, so the "
        "shimmer never runs for anyone")


def test_something_actually_sets_the_class():
    """CSS alone is a silent removal of the affordance, not a fix."""
    js = _js_no_comments(JS.read_text(encoding="utf-8"))
    assert "pc-ph-onscreen" in js, (
        "no JavaScript sets pc-ph-onscreen, so the shimmer can never "
        "appear — the CSS half of the change landed alone"
    )
    assert "IntersectionObserver" in js


def test_the_shimmer_observer_has_no_root_margin():
    """A generous margin would light hundreds of off-screen placeholders
    and put most of the cost straight back."""
    js = _js_no_comments(JS.read_text(encoding="utf-8"))
    i = js.find("pc-ph-onscreen")
    assert i > 0
    # Forward only. Searching backwards finds the MATERIALISING
    # observer's rootMargin (500%/40%), which is correct for its job and
    # would make this test pass while the shimmer observer used any
    # margin at all.
    m = re.search(r"rootMargin:\s*[\"']([^\"']*)[\"']", js[i:i + 800])
    assert m, "could not find the shimmer observer's rootMargin"
    margin = m.group(1)
    assert re.fullmatch(r"0(px)?( 0(px)?)*", margin.strip()), \
        f"shimmer observer uses rootMargin {margin!r}; it must be 0"


def test_the_built_template_carries_both_halves():
    """results.html is a build artifact. Editing the sources without
    rebuilding ships the old page — the failure this repo has hit by
    landing one half of a two-file change."""
    built = BUILT.read_text(encoding="utf-8")
    assert "pc-ph-onscreen" in built, "results.html was not rebuilt"
    assert built.count("pc-ph-onscreen") >= 3, (
        "results.html has the class but not both the CSS rules and the "
        "JavaScript that sets it"
    )
    css_part = _css_no_comments(built)
    assert not any("animation" in b
                   for b in _rule_bodies(css_part, ".card-placeholder")), \
        "the built page still animates every placeholder"
