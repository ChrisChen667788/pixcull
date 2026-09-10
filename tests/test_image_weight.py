"""v3.66 — the size question was asked about the wrong directory.

The open item asked whether `samples/input` should drop from 1600 px to
1200 px to halve its ~9 MB. Measured, that is the wrong lever twice over.

**Shrinking the samples would break the lightbox.** `scripts/serve_review.py`
sets `_FULL_SIZE = 1600` and the lightbox opens `/full/<name>` with no
width parameter, so the server caps at 1600 and `Image.thumbnail` never
upscales: a 1200 px source is delivered at 1200 and the browser stretches
it. That is v2.86 exactly — "a sharpness tool was serving soft thumbnails
to Retina screens" — reintroduced for every visitor who clicks a demo
photograph in a tool whose job is deciding whether a frame is sharp.

**And samples were never the weight.** `docs/screenshots` was 61.8 MB to
`samples/input`'s 9.0 MB, and one file — `06-share-portfolio.png`, a
full-page capture at 2560x6960 — was 12 MB by itself, larger than all 32
photographs together.

The captures are taken at `device_scale_factor=2` on a 1440-wide viewport,
so they arrive 2880 px wide. Every consumer is a README or a model card
rendering in a column near 830 CSS px, where 1660 is already 2x. Capping
width at 1660 took the directory to 31.5 MB with no visible change, and
the cap now lives in the capture script so the next re-shoot is born small
rather than shrunk afterwards.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
CAPTURE = ROOT / "scripts" / "brand" / "capture_screenshots.sh"

#: Long-edge floor for the demo photographs, and the reason it exists.
SAMPLE_LONG_EDGE = 1600


def _cap_from_capture_script() -> int:
    m = re.search(r"^SHOT_MAX_WIDTH\s*=\s*(\d+)",
                  CAPTURE.read_text(encoding="utf-8"), re.M)
    assert m, "capture_screenshots.sh no longer declares SHOT_MAX_WIDTH"
    return int(m.group(1))


def test_no_committed_screenshot_is_wider_than_the_capture_cap():
    """The cap is only a cap if the committed files obey it. A capture
    taken before the cap existed, or by hand, is how the directory got to
    61.8 MB in the first place."""
    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    cap = _cap_from_capture_script()
    too_wide = []
    for p in sorted(SHOTS.glob("*.png")):
        w, _ = Image.open(p).size
        if w > cap:
            too_wide.append(f"{p.name} is {w}px wide (cap {cap})")
    assert not too_wide, (
        "these exceed the capture cap — re-run "
        "scripts/brand/capture_screenshots.sh, which applies it on save:\n  "
        + "\n  ".join(too_wide))


def test_the_capture_script_applies_the_cap_on_save():
    """A constant nothing reads is a comment. The first cut of this
    change declared SHOT_MAX_WIDTH and left `page.screenshot` writing the
    file untouched, which would have been a cap that capped nothing."""
    # Line-based rather than one regex over the whole file: the call is
    # `page.screenshot(path=str(OUT / name), ...)` and a `\([^)]*\)` group
    # stops at the `)` closing `str(`, which is how the first cut of this
    # assertion failed against correct code.
    lines = [l.split("#", 1)[0] for l in CAPTURE.read_text(encoding="utf-8").splitlines()]
    assert any("def _shrink(" in l for l in lines), (
        "capture_screenshots.sh no longer defines _shrink")
    saves = [i for i, l in enumerate(lines) if "page.screenshot(" in l]
    assert saves, "capture_screenshots.sh no longer takes a screenshot"
    unguarded = [i + 1 for i in saves
                 if not any("_shrink(" in l for l in lines[i + 1:i + 3])]
    assert not unguarded, (
        f"the screenshot written at line(s) {unguarded} is not passed "
        "through _shrink, so the cap caps nothing for that capture")


def test_the_sample_photographs_stay_at_the_lightbox_size():
    """The other half of the finding: shrinking these is the change that
    looks like a saving and is a regression. `_FULL_SIZE` is what the
    lightbox asks for; a source below it is delivered as-is and upscaled
    by the browser."""
    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    serve = (ROOT / "scripts" / "serve_review.py").read_text(encoding="utf-8")
    m = re.search(r"^_FULL_SIZE\s*=\s*(\d+)", serve, re.M)
    assert m, "serve_review.py no longer declares _FULL_SIZE"
    full = int(m.group(1))
    assert full == SAMPLE_LONG_EDGE, (
        f"_FULL_SIZE moved to {full}; the sample photographs are prepared "
        f"at {SAMPLE_LONG_EDGE}. Keep them equal or the lightbox upscales.")

    small = []
    for p in sorted((ROOT / "samples" / "input").glob("*.jpg")):
        w, h = Image.open(p).size
        if max(w, h) < full:
            small.append(f"{p.name} {w}x{h}")
    assert not small, (
        f"these are below the lightbox's {full}px request, so a demo "
        "visitor who opens them sees an upscale — the v2.86 defect:\n  "
        + "\n  ".join(small))
