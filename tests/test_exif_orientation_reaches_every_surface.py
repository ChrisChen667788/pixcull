"""v2.56.2 — the orientation promise, checked instead of trusted.

``pixcull/io/loader.py`` states that "every code path now goes through
``ImageOps.exif_transpose``" (V16.1).  Four presentation modules opened
PIL directly and were not among them, and the newest of them showed 67
of 150 frames sideways to a photographer during a blind labelling pass.

Nothing in the resulting numbers revealed it — the cull rate on the
sideways frames was 6.0% against 7.2% upright, which is noise. It was
found by looking at the photographs.

So this is a mechanical check over first-party source, not a behavioural
test of one module: a rule about "every code path" has to be enforced
over every code path, or it is a comment.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "pixcull"

# Vendored trees and the venv are not ours to police.
_SKIP_PARTS = {"dist", ".venv", "venv", "node_modules", "__pycache__"}

# `loader.py` is the module that DOES the transposing; `face_clustering`
# already calls it explicitly. Anything else opening PIL directly is
# either a bug or an exception someone has to write down here.
_ALLOWED_WITHOUT: dict[str, str] = {
    "pixcull/io/loader.py": "this is the module that applies it",
    # These open the file to READ metadata, never to show pixels.
    # Transposing would cost a decode and change nothing they return —
    # and `exif.py` in particular is where the orientation tag itself is
    # read, so rotating first would be circular.
    "pixcull/io/exif.py": "reads tags, including Orientation itself",
    "pixcull/io/exif_audit.py": "reads tags, renders nothing",
    "pixcull/io/icc.py": "reads the colour profile, renders nothing",

    # ---- NOT blessed. Recorded debt, v2.56.2. -------------------------
    # These open pixels for ANALYSIS and do not transpose, so on a
    # portrait frame they see the photograph on its side. Measured on a
    # real 150-frame shoot: 67 frames (45%) carry Orientation 8, and the
    # 128x128 tensor the composition classifier receives differs by a
    # mean absolute 0.18 per channel between the two — not a rounding
    # difference, a different picture.
    #
    # Composition especially is orientation-dependent by definition
    # (thirds, lead room, horizon, diagonal energy), and `score_
    # composition` was the strongest single discriminator in the owner's
    # own culls. So this is very likely a real scoring bug.
    #
    # It is listed rather than fixed because fixing it changes every
    # score in the library and invalidates cached embeddings — an
    # owner's decision, not a drive-by. Deleting an entry here without
    # fixing the module is how this becomes a rubber stamp.
    "pixcull/scoring/composition_classifier.py": "UNREVIEWED analysis path",
    "pixcull/scoring/temporal.py": "UNREVIEWED analysis path",
    "pixcull/scoring/dup_frames.py": "UNREVIEWED analysis path",
    "pixcull/scoring/counterfactual.py": "UNREVIEWED analysis path",
    "pixcull/scoring/attribution.py": "UNREVIEWED analysis path",
    "pixcull/scoring/reel_caption.py": "UNREVIEWED analysis path",
    "pixcull/scoring/color_grade.py": "UNREVIEWED analysis path",
    "pixcull/scoring/semantic_search.py": "UNREVIEWED analysis path",
}


def _first_party_sources() -> list[Path]:
    out = []
    for p in PKG.rglob("*.py"):
        if any(part in _SKIP_PARTS for part in p.parts):
            continue
        out.append(p)
    assert out, "walked no source files — the glob is broken"
    return out


def _opens_images(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "open"
                and isinstance(fn.value, ast.Name) and fn.value.id == "Image"):
            return True
    return False


def test_every_module_that_opens_an_image_honours_its_orientation():
    offenders = []
    for path in _first_party_sources():
        rel = path.relative_to(ROOT).as_posix()
        if rel in _ALLOWED_WITHOUT:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "Image.open" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        if not _opens_images(tree):
            continue
        if "exif_transpose" in src or "load_image" in src:
            continue
        offenders.append(rel)
    assert not offenders, (
        "these modules call Image.open without honouring EXIF orientation, "
        "so portrait frames render sideways:\n  " + "\n  ".join(offenders)
        + "\nEither route through pixcull.io.loader or apply "
          "ImageOps.exif_transpose, or record an exception in "
          "_ALLOWED_WITHOUT with the reason.")


def test_a_rotated_thumbnail_comes_out_upright(tmp_path):
    """End-to-end on the surface that actually bit: the review sheet."""
    from PIL import Image

    from pixcull.report.review_sheet import thumbnail_data_uri

    # 1200x600 landscape pixels, tagged "rotate 90° CCW to display".
    src = tmp_path / "sideways.jpg"
    exif = Image.Exif()
    exif[0x0112] = 8                       # Orientation: rotate 90° CCW
    Image.new("RGB", (1200, 600), (120, 90, 60)).save(
        src, "JPEG", exif=exif)

    import base64
    import io as _io
    raw = thumbnail_data_uri(src, px=300)
    img = Image.open(_io.BytesIO(base64.b64decode(raw.split(",", 1)[1])))
    assert img.height > img.width, (
        f"orientation 8 must render as a portrait, got {img.size}")


def test_the_allowlist_stays_honest():
    """An exception that no longer exists is an exception nobody reviews."""
    for rel in _ALLOWED_WITHOUT:
        assert (ROOT / rel).is_file(), f"stale exception: {rel}"


def test_the_unreviewed_debt_stays_visible():
    """`UNREVIEWED` entries are debt, not permission.

    They exist so a known-probable scoring bug is written down where the
    gate reads it, instead of living in one commit message. If someone
    fixes a module they should delete its line; if the count drifts
    upward, something new was added to the pile without a decision.
    """
    unreviewed = {k for k, v in _ALLOWED_WITHOUT.items()
                  if v.startswith("UNREVIEWED")}
    assert len(unreviewed) == 8, (
        f"the unreviewed-orientation pile changed size ({len(unreviewed)}). "
        f"If a module was fixed, drop its entry. If one was added, that is "
        f"a new instance of a bug we already know about: {sorted(unreviewed)}")
    for rel in unreviewed:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "exif_transpose" not in src, (
            f"{rel} now transposes — delete its _ALLOWED_WITHOUT entry")
