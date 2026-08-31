"""v2.86 — a sharpness tool was serving soft thumbnails to Retina screens.

The grid draws a thumbnail at ~278 CSS pixels. On a Retina display that
is 556 device pixels. The /thumb/ route served 420 whatever `?w=` asked
for — w=560, w=840 and w=1200 all returned the same 420px image, byte
for byte, with no error and no header saying so.

So a photographer deciding whether a frame is in focus was looking at a
420px image upscaled to 556, in the product whose entire job is that
decision. Measured before: 0 of 12 viewport thumbnails carried enough
pixels for the screen. After: 12 of 12, with first-screen ready
unchanged (337 ms at DPR 1, 329 ms at DPR 2).

The naive version of this "optimisation" goes the other way — the
displayed width is 278 and the served width is 420, so shrink to 280 —
and ships blur to every Retina user, which is all of them.
"""
import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRV = REPO / "pixcull" / "report" / "serve_app.py"
JS = REPO / "pixcull" / "report" / "templates" / "src" / "results.js"
BUILT = REPO / "pixcull" / "report" / "templates" / "results.html"

from pixcull.report.serve_app import _RETINA_THUMB, _THUMB_SIZE


def _code_only(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        docs = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                d = ast.get_docstring(node, clean=False)
                if d:
                    docs.add(d)
        body = "\n".join("" if l.lstrip().startswith("#") else l.split("#", 1)[0]
                         for l in text.splitlines())
        for d in docs:
            body = body.replace(d, "")
        return body
    return "\n".join("" if l.lstrip().startswith("//") else l.split("//", 1)[0]
                     for l in text.splitlines())


def test_the_retina_bucket_is_twice_the_thumbnail():
    """Anything else and a 2x screen is either short of pixels or paying
    for ones it cannot draw."""
    assert _RETINA_THUMB == _THUMB_SIZE * 2


def test_the_thumb_route_can_exceed_the_default_size():
    code = _code_only(SRV)
    i = code.find("small_buckets = [200, 280, _THUMB_SIZE]")
    assert i > 0
    block = code[i:i + 1200]
    assert "_RETINA_THUMB" in block, (
        "the thumb route cannot serve above _THUMB_SIZE, so no ?w= "
        "can ever produce a Retina-sharp grid")


def test_an_oversized_request_is_clamped_not_dropped():
    """w=1200 used to return 420 — the same silent ignoring, one bucket
    further along. It must come back as the cap."""
    code = _code_only(SRV)
    i = code.find("elif size <= _THUMB_SIZE:")
    assert i > 0, "the retina branch is gated on the request size again"
    block = code[i:i + 900]
    assert "size = _RETINA_THUMB" in block
    assert "req_w <= _RETINA_THUMB" not in block, (
        "requests above the cap fall through to the large-bucket branch "
        "and silently return a 420px image")


def test_the_grid_asks_for_the_pixels_its_screen_has():
    js = _code_only(JS)
    i = js.find("const thumb = `/thumb/${run_id}/")
    assert i > 0
    block = js[i:i + 400]
    assert "devicePixelRatio" in block, (
        "the grid requests one fixed size regardless of the display")
    assert "?w=840" in block


def test_only_two_buckets_are_requested():
    """A bucket per client width multiplies the thumbnail cache by the
    number of screen sizes instead of by two."""
    js = _code_only(JS)
    i = js.find("const thumb = `/thumb/${run_id}/")
    block = js[i:i + 400]
    widths = set(re.findall(r"\?w=(\d+)", block))
    assert widths <= {"840"}, f"more than one extra bucket requested: {widths}"


def test_the_built_template_carries_it():
    built = _code_only(BUILT)
    assert "devicePixelRatio" in built and "?w=840" in built, \
        "results.html was not rebuilt"
