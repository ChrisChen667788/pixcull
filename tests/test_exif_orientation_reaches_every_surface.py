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
    #   semantic_search — CLIP vectors built from untransposed pixels
    #     (cli.py, serve_app.py, on the photo library). Degrades search
    #     and the CLIP near-dup collapse for portrait frames. Fixing it
    #     means rebuilding embeddings, not rescoring.
    #   attribution — the heatmap is rendered to the user sideways.
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
    "pixcull/scoring/attribution.py": "UNREVIEWED heatmap orientation",
    "pixcull/scoring/semantic_search.py": "UNREVIEWED CLIP embeddings",
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
    assert len(unreviewed) == 8, (
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
