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

    # ---- Recorded debt, traced in v2.56.3. ---------------------------
    # These open pixels without transposing. v2.56.2 called that "very
    # likely a real scoring bug"; tracing it, that was WRONG and the
    # correction matters more than the original alarm:
    #
    #   worker.py:47 loads through `io.loader.load_image`, which DOES
    #   transpose, and every scoring detector is fed from there —
    #   including CompositionDetector, which has no Image.open of its
    #   own. So `score_final`, `decision`, `composition_score`,
    #   `rule_of_thirds_offset` and all eleven `canon_*` metrics are
    #   computed on upright pixels. **No score is affected.**
    #
    # What IS affected, measured on the 67 rotated frames of a real
    # 150-frame shoot:
    #
    #   composition_classifier — 17% of rotated frames classify to a
    #     different composition rule. Reaches only counterfactual.py's
    #     "how to improve this shot" advice; no score column.
    #   semantic_search — FIXED v2.56.4. Was embedding untransposed
    #     pixels on the photo library, so portrait frames landed near
    #     the wrong neighbours in search and in the CLIP near-dup
    #     collapse. Any embeddings cache built before that is stale.
    #   attribution — FIXED v2.56.4. The heatmap is drawn back over the
    #     photograph, so a sideways input produced a sideways overlay.
    #   temporal / dup_frames / reel_caption — video frames, which
    #     ffmpeg writes without an EXIF orientation tag at all.
    #   color_grade — receives bytes from its caller, and grading is
    #     channel statistics; orientation-independent.
    #
    # Kept as entries rather than fixed because the remaining fixes are
    # the owner's call on cache rebuild cost. Deleting a line here
    # without fixing the module is how this becomes a rubber stamp.
    "pixcull/scoring/composition_classifier.py": "UNREVIEWED advice path",
    "pixcull/scoring/counterfactual.py": "UNREVIEWED advice path",
    "pixcull/scoring/temporal.py": "UNREVIEWED video frames (no EXIF)",
    "pixcull/scoring/dup_frames.py": "UNREVIEWED video frames (no EXIF)",
    "pixcull/scoring/reel_caption.py": "UNREVIEWED video frames (no EXIF)",
    "pixcull/scoring/color_grade.py": "UNREVIEWED bytes from caller",
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
    assert len(unreviewed) == 6, (
        f"the unreviewed-orientation pile changed size ({len(unreviewed)}). "
        f"If a module was fixed, drop its entry. If one was added, that is "
        f"a new instance of a bug we already know about: {sorted(unreviewed)}")
    # The claim that matters: none of these reach a score. Asserted so a
    # future change that routes one of them into scoring trips the gate
    # instead of quietly making the note above false.
    # Parsed, not grepped: the first version of this asserted that the
    # string "load_image" appeared in worker.py, which a mutation
    # satisfied with `from PIL import Image as load_image`. An assertion
    # that a rename can satisfy is not an assertion.
    worker = ast.parse(
        (ROOT / "pixcull/pipeline/worker.py").read_text(encoding="utf-8"))
    routed = any(
        isinstance(n, ast.ImportFrom) and n.module == "pixcull.io.loader"
        and any(a.name == "load_image" for a in n.names)
        for n in ast.walk(worker))
    assert routed, (
        "worker.py no longer imports load_image from pixcull.io.loader — "
        "the note above claims every scoring detector gets upright "
        "pixels, and that claim now needs re-deriving")
    comp = (ROOT / "pixcull/detectors/composition.py").read_text("utf-8")
    assert "Image.open" not in comp, (
        "detectors/composition.py now opens files itself, so composition "
        "scores are no longer guaranteed upright")
    for rel in unreviewed:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "exif_transpose" not in src, (
            f"{rel} now transposes — delete its _ALLOWED_WITHOUT entry")


def _sideways(tmp_path, name="portrait.jpg"):
    """A landscape-pixel file tagged 'rotate 90° CCW to display'."""
    from PIL import Image
    p = tmp_path / name
    exif = Image.Exif()
    exif[0x0112] = 8
    im = Image.new("RGB", (400, 200), (30, 30, 30))
    # A bright bar along one long edge, so orientation is detectable in
    # the output rather than inferred from the aspect ratio alone.
    for x in range(400):
        for y in range(0, 20):
            im.putpixel((x, y), (250, 250, 250))
    im.save(p, "JPEG", exif=exif, quality=95)
    return p


def test_clip_embeds_the_upright_frame(tmp_path):
    """Behaviour, not the presence of a call.

    CLIP embeds pixels. A portrait frame stored sideways embeds as a
    sideways photograph, so it lands near the wrong neighbours in both
    semantic search and the CLIP near-dup collapse — silently, because
    the results still look like results.
    """
    from pixcull.scoring.semantic_search import load_for_clip

    src = _sideways(tmp_path)
    got = load_for_clip(src)
    assert got.height > got.width, (
        f"the encoder receives a landscape frame, got {got.size}")
    # The bright bar lives on one long edge; after an upright transpose
    # it must be down a SIDE, not across the top.
    left = sum(got.getpixel((2, y))[0] for y in range(got.height))
    top = sum(got.getpixel((x, 2))[0] for x in range(got.width))
    assert left > top, ("the frame is the right shape but the wrong way "
                        "round — transposed with the wrong operation")


def test_the_attribution_heatmap_matches_the_displayed_frame(tmp_path):
    """A sideways heatmap over an upright photo points at nothing.

    Also pins the ORDER: transposing after the square resize would hand
    the model a frame whose aspect ratio never existed.
    """
    from PIL import Image, ImageOps

    from pixcull.scoring.attribution import load_for_attribution

    src = _sideways(tmp_path)
    got = load_for_attribution(src, size=64)
    assert got.size == (64, 64), "the model input must stay square"

    upright = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    want = upright.resize((64, 64))
    diff = sum(abs(a - b)
               for a, b in zip(list(got.convert("L").tobytes()),
                               list(want.convert("L").tobytes())))
    assert diff == 0, (
        "the resized frame does not match transpose-then-resize, so the "
        "model sees a different picture than the viewer")

    wrong = Image.open(src).convert("RGB").resize((64, 64))
    wrong_diff = sum(abs(a - b)
                     for a, b in zip(list(got.convert("L").tobytes()),
                                     list(wrong.convert("L").tobytes())))
    assert wrong_diff > 0, (
        "transposing changed nothing — the fixture is not actually "
        "rotated and this test proves nothing")


def test_an_embeddings_cache_from_before_the_fix_is_discarded(tmp_path):
    """Fixing the encoder does nothing if the old vectors are reused.

    A cache written before v2.56.4 holds portrait frames embedded on
    their side. It loads cleanly, has the right shape, and describes
    different pictures — so `load_embeddings_cache` has to reject it on
    provenance, not on age or readability.
    """
    import numpy as np

    from pixcull.scoring.semantic_search import (
        PREPROC_VERSION, load_embeddings_cache,
    )

    cur = tmp_path / "cur.npz"
    with open(cur, "wb") as fh:
        np.savez(fh, filenames=np.array(["a.jpg"]),
                 vectors=np.zeros((1, 4), dtype=np.float32),
                 model=np.array("clip-vit-base-patch32"),
                 preproc=np.array(PREPROC_VERSION))
    assert load_embeddings_cache(cur) is not None, "a current cache must load"

    old = tmp_path / "old.npz"
    with open(old, "wb") as fh:       # no `preproc` key at all
        np.savez(fh, filenames=np.array(["a.jpg"]),
                 vectors=np.zeros((1, 4), dtype=np.float32),
                 model=np.array("clip-vit-base-patch32"))
    assert load_embeddings_cache(old) is None, (
        "a pre-v2.56.4 cache was reused — every portrait vector in it "
        "was built from a sideways frame")

    stale = tmp_path / "stale.npz"
    with open(stale, "wb") as fh:
        np.savez(fh, filenames=np.array(["a.jpg"]),
                 vectors=np.zeros((1, 4), dtype=np.float32),
                 model=np.array("clip-vit-base-patch32"),
                 preproc=np.array("something-else"))
    assert load_embeddings_cache(stale) is None
