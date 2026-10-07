"""v3.45 — the constructs that make a README image render as nothing.

The hero demo shipped in the README as 921,600 pixels of pure black, and
it had been that way since it was written. Nobody was checking, because
an SVG that parses is not an SVG that paints.

These are source-level checks, so they run in the hermetic lane with no
browser. `tests/test_readme_images_render.py` does the other half — it
actually rasterizes each image and looks at the pixels — and lives in
the browser lane because it needs chromium.

Three rules, each from a defect that was live in the published README:

1. Never animate a paint keyword. `<animate attributeName="fill"
   values="none;none">` on a full-canvas rect made Chrome resolve the
   interpolated `none` to an invalid colour and composite it as opaque
   black over everything, forever, because of `repeatCount="indefinite"`.

2. `textContent` is not animatable. Four counters were animated that way
   and every one sat at its authored `0`, so a culling demo advertised a
   shoot with zero keeps.

3. A group that is invisible without animation is invisible wherever
   animation does not run. `<img>`-embedded SVG is an isolated document
   and plenty of renderers drop SMIL; the base attributes have to be the
   finished frame, with the animation running *from* the hidden state.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READMES = ("README.md", "modelscope/README.md")

#: v3.62 — `srcset` as well as `src`. The light half of a <picture> pair
#: is only ever named in a srcset, so a src-only scanner rendered the
#: dark hero, passed, and shipped the light one unlooked-at. Half a
#: theme-aware image is exactly the kind of thing nobody opens until a
#: reader on a light system opens it.
LOCAL_IMG = re.compile(
    r'(?:src|srcset)="(\.?/?(?:docs|assets)/[^"]+\.(?:svg|png|jpg|jpeg|gif))"')


def referenced_images() -> list[Path]:
    """Every local image the READMEs embed. Deduped, order kept."""
    seen, out = set(), []
    for name in READMES:
        f = ROOT / name
        if not f.is_file():
            continue
        for rel in LOCAL_IMG.findall(f.read_text(encoding="utf-8")):
            rel = rel.lstrip("./")
            if rel not in seen:
                seen.add(rel)
                out.append(ROOT / rel)
    return out


def svgs() -> list[Path]:
    return [p for p in referenced_images() if p.suffix == ".svg"]


def test_the_readmes_reference_images_and_they_all_exist():
    """A scanner that matches nothing passes for the wrong reason, and a
    broken link is its own defect."""
    imgs = referenced_images()
    assert len(imgs) >= 4, f"only found {len(imgs)} local README images"
    missing = [str(p.relative_to(ROOT)) for p in imgs if not p.is_file()]
    assert not missing, f"README references images that do not exist: {missing}"


def test_no_image_animates_a_paint_keyword():
    """`none` and `currentColor` are keywords, not colours. Asking SMIL
    to interpolate one gives you an invalid paint, and Chrome paints
    invalid as opaque black across the element's whole area."""
    bad = []
    for p in svgs():
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"<animate\b[^>]*>", src):
            tag = m.group(0)
            if not re.search(r'attributeName="(fill|stroke)"', tag):
                continue
            vals = re.search(r'(?:values|from|to)="([^"]*)"', tag)
            if vals and re.search(r"\b(none|currentColor|inherit)\b", vals.group(1)):
                bad.append(f"{p.relative_to(ROOT)}: {tag[:110]}")
    assert not bad, (
        "these animate a paint keyword, which renders as opaque black in "
        f"Chrome: {bad}")


def test_no_image_animates_text_content():
    """Not an SVG attribute. The number stays at whatever is authored,
    which for a count-up starting at zero means it reads zero forever."""
    bad = [str(p.relative_to(ROOT)) for p in svgs()
           if 'attributeName="textContent"' in p.read_text(encoding="utf-8")]
    assert not bad, (
        "textContent is a DOM property and is not animatable via SMIL; "
        f"author the final value instead: {bad}")


def test_nothing_depends_on_animation_to_be_visible():
    """The robustness rule. An element authored at `opacity="0"` that
    fades itself in with SMIL shows as nothing wherever SMIL does not
    run — and that includes several Markdown renderers, feed readers and
    PDF export. Author the finished frame; animate from hidden to it."""
    bad = []
    for p in svgs():
        src = p.read_text(encoding="utf-8")
        # An element is at risk when its own start tag sets opacity 0 and
        # it carries an opacity animation before its next start tag.
        for m in re.finditer(r'<(g|rect|circle|text|path|image)\b[^>]*opacity="0"[^>]*>',
                             src):
            tail = src[m.end():m.end() + 4000]
            if re.search(r'<animate\b[^>]*attributeName="opacity"', tail):
                bad.append(f"{p.relative_to(ROOT)}: {m.group(0)[:90]}")
    assert not bad, (
        "these are invisible unless SMIL runs — make the base state the "
        f"finished one: {bad}")


def test_the_hero_demo_stats_add_up():
    """It is a picture of a product doing arithmetic in front of a
    photographer. keep + maybe + cull has to equal the total, or the
    demo is quietly making a claim that is wrong."""
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location(
        "gen_animated_demo", ROOT / "scripts" / "brand" / "gen_animated_demo.py")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._KEEP + mod._MAYBE + mod._CULL == mod._TOTAL
    svg = (ROOT / "docs" / "brand" / "pixcull-hero-reveal-demo.svg").read_text("utf-8")
    for n in (mod._TOTAL, mod._KEEP, mod._MAYBE, mod._CULL):
        assert f">{n}</tspan>" in svg, f"{n} is not in the rendered demo"


def test_the_generator_and_the_committed_file_agree():
    """The palette was redesigned, the SVG was updated, the generator was
    not — so the "regenerate with…" line in the README would have
    silently reverted the brand. The generator reads the shared token
    file now; this is what keeps it that way."""
    import subprocess
    import sys
    target = ROOT / "docs" / "brand" / "pixcull-hero-reveal-demo.svg"
    before = target.read_bytes()
    try:
        subprocess.run([sys.executable,
                        str(ROOT / "scripts" / "brand" / "gen_animated_demo.py")],
                       check=True, capture_output=True)
        after = target.read_bytes()
    finally:
        target.write_bytes(before)
    assert before == after, (
        "docs/brand/pixcull-hero-reveal-demo.svg does not match what its "
        "generator produces — regenerate it, or port the hand edit into "
        "scripts/brand/gen_animated_demo.py")


def test_the_hero_ships_both_themes_and_they_agree():
    """v3.62 — a <picture> pair is two files that have to stay a pair.

    `prefers-color-scheme` inside an `<img>`-embedded SVG reads the
    operating system's setting rather than GitHub's own theme toggle, so
    `<picture>` with `media=` on each `<source>` is the only mechanism
    that follows the toggle. That means two files, and two files drift:
    one gets regenerated, the other does not, and the half nobody looks
    at is the half a reader on the other theme sees.
    """
    dark = ROOT / "docs" / "brand" / "pixcull-hero-dark.svg"
    light = ROOT / "docs" / "brand" / "pixcull-hero-light.svg"
    for f in (dark, light):
        assert f.is_file(), f"{f.name} is missing — run scripts/brand/gen_hero.py"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'media="(prefers-color-scheme: dark)"' in readme
    assert "pixcull-hero-dark.svg" in readme and "pixcull-hero-light.svg" in readme

    # Same composition, different palette: the frame count and the
    # decision they show must not diverge.
    d, l = dark.read_text("utf-8"), light.read_text("utf-8")
    # The score comes from the generator rather than being written down
    # here. The first cut pinned the literal "保留 0.85", which was the
    # figure at the time; when the hero moved to the real sunset take
    # and the real run scored the kept frame 0.71, the gate failed for a
    # change that was correct. Pin the shape, read the number.
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "_gen_hero", ROOT / "scripts" / "brand" / "gen_hero.py")
    _gen = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_gen)
    chosen_score = _gen.FRAMES[_gen.CHOSEN][1]
    twin_score = _gen.FRAMES[_gen.TWIN][1]
    assert chosen_score != twin_score, (
        "the hero's whole point is that the pair scored differently")

    for needle in (f"保留 {chosen_score}", twin_score, _gen.TIE_LABEL,
                   "data:image/jpeg;base64"):
        assert needle in d and needle in l, f"{needle!r} is in only one theme"
    assert d.count("<image ") == l.count("<image "), (
        "the two themes show a different number of photographs")

    # v3.65 fixup — this list used to hold the literal "same moment",
    # and that is how the picture's own description went stale twice
    # without failing. The phrase survived in the SVG's `aria-label` and
    # in the README's `alt` long after the drawn label stopped saying
    # it, so the assertion passed *because* of the text that was wrong.
    # A retired phrase is now a failure rather than a pass.
    for retired in ("same moment", "museum shoot", "scissors"):
        assert retired not in d and retired not in l, (
            f"the hero still says {retired!r} somewhere — it describes a "
            "picture this is not any more")


def test_the_hero_is_described_the_same_way_everywhere():
    """A screen-reader user meets this picture through the README's `alt`
    and the SVG's `aria-label`, and until v3.65 both of them described a
    different photograph from the one on screen: "one museum shoot", "the
    same scissors", "keep at 0.85", "0.72". The frames had been replaced
    twice underneath, and nothing read the description.

    So there is one description, `gen_hero.alt_text()`, built from
    `FRAMES`. Both copies have to match it exactly.
    """
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "_gen_hero", ROOT / "scripts" / "brand" / "gen_hero.py")
    _gen = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_gen)
    alt = _gen.alt_text()

    for theme in ("dark", "light"):
        svg = (ROOT / "docs" / "brand" / f"pixcull-hero-{theme}.svg").read_text("utf-8")
        assert f'aria-label="{alt}"' in svg, (
            f"pixcull-hero-{theme}.svg's aria-label is not the generated "
            "one — regenerate with scripts/brand/gen_hero.py")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r'<img src="docs/brand/pixcull-hero-dark\.svg"\s+alt="([^"]*)"',
                  readme)
    assert m, "README has no hero <img> with an alt"
    assert m.group(1) == alt, (
        "the README's hero alt text has drifted from the generator.\n"
        f"  README: {m.group(1)[:90]}...\n"
        f"  should be: {alt[:90]}...")


def test_the_hero_matches_its_generator():
    import subprocess
    import sys
    targets = [ROOT / "docs" / "brand" / f"pixcull-hero-{t}.svg"
               for t in ("dark", "light")]
    before = [t.read_bytes() for t in targets]
    try:
        subprocess.run([sys.executable,
                        str(ROOT / "scripts" / "brand" / "gen_hero.py")],
                       check=True, capture_output=True)
        after = [t.read_bytes() for t in targets]
    finally:
        for t, b in zip(targets, before):
            t.write_bytes(b)
    assert before == after, (
        "the hero SVGs do not match scripts/brand/gen_hero.py — regenerate")


# ---------------------------------------------------------------------------
# 2026-10-07 — the film's poster has to open something that plays.
# ---------------------------------------------------------------------------

FILM = "docs/video/pixcull-30s.mp4"
#: Measured when the film went in. GitHub's own file page does not play a
#: 4 MB mp4 — it says the file is too big to show — and
#: raw.githubusercontent.com serves it as application/octet-stream with
#: `nosniff`, so the browser downloads it. jsDelivr serves the same bytes
#: as video/mp4; ModelScope's resolve URL is sniffed as video and plays.
#: A relative link, the obvious thing to write, is the one that fails.
PLAYABLE_FILM = {
    "README.md":
        f"https://cdn.jsdelivr.net/gh/ChrisChen667788/pixcull@main/{FILM}",
    "modelscope/README.md":
        f"https://www.modelscope.cn/models/haozi667788/pixcull/resolve/master/{FILM}",
}


def test_the_film_is_linked_where_a_browser_will_play_it():
    assert (ROOT / FILM).is_file(), f"{FILM} is gone; the links below are dead"
    for name, url in PLAYABLE_FILM.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        links = re.findall(r'(?:href="|\]\()([^")\s]*pixcull-30s\.mp4)', text)
        assert links, f"{name} no longer links the film"
        wrong = sorted(set(l for l in links if l != url))
        assert not wrong, (
            f"{name} links the film somewhere a browser will not play it: "
            f"{wrong} — use {url}")


#: The film as a GitHub attachment — the one form GitHub plays inline in a
#: README, as a URL alone on its line. Uploaded 2026-10-07 from the file
#: below; GitHub does not re-read the repository, so if the mp4 is
#: re-rendered this attachment keeps showing the old cut until someone
#: uploads the new one and replaces both constants.
FILM_ATTACHMENT = ("https://github.com/user-attachments/assets/"
                   "69eddc6b-24d3-406a-ace5-2ed3a5b44e67")
FILM_ATTACHMENT_SHA256 = (
    "f49b81a2fc5a880f92b241c2676a5c737a3e6d047eb00f6c4095ef4f625e68da")


def test_the_readme_plays_the_film_inline():
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    assert FILM_ATTACHMENT in (l.strip() for l in lines), (
        "README.md no longer has the film's attachment URL on a line of its "
        "own, which is what makes GitHub render a player")


def test_the_attachment_is_never_a_link():
    """Opened directly, the attachment URL answers 404 to anyone signed
    out (measured 2026-10-07; only the README's rendered player is signed
    for them). As an href it would be a dead link for most readers."""
    for name in READMES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(
            r'(?:href="|\]\()https://github\.com/user-attachments/', text), (
            f"{name} links a GitHub attachment; signed-out readers get a 404")


def test_the_attachment_still_holds_the_committed_film():
    import hashlib
    got = hashlib.sha256((ROOT / FILM).read_bytes()).hexdigest()
    assert got == FILM_ATTACHMENT_SHA256, (
        f"{FILM} changed (sha256 {got[:12]}…) but the README still embeds the "
        "attachment uploaded from the old file. Upload the new mp4 to a "
        "GitHub comment box and replace FILM_ATTACHMENT and its hash.")
