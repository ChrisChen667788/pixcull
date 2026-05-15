import io
from pathlib import Path
from typing import Optional

import rawpy
from PIL import Image, ImageOps

from pixcull.io.formats import ALL_EXTS, RAW_EXTS


def load_image(path: Path, max_side: int = 2048) -> Optional[Image.Image]:
    """Load image; for RAW, prefer embedded JPEG thumbnail (20-40x faster than full decode).

    V16.1: every code path now goes through ``ImageOps.exif_transpose``
    so the returned PIL image has its EXIF Orientation baked into the
    pixel layout. Without this, phone-shot JPEGs (and many camera
    portrait-mode shots) come back in on-disk landscape orientation
    even when EXIF tag 0x0112 says "rotate 90° to display".

    The RAW path also runs through exif_transpose because some camera
    embedded thumbnails carry their own orientation tag (Canon CR3 in
    portrait mode is the canonical case — same shot the user reported
    showing 90°-rotated in the lightbox). The pyiqa / detector
    pipelines downstream get correct orientation too, so e.g.
    Lead-Room and horizon-tilt detectors aren't computed against a
    flipped frame.
    """
    ext = path.suffix.lower()
    try:
        if ext in RAW_EXTS:
            with rawpy.imread(str(path)) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        img = Image.open(io.BytesIO(thumb.data))
                    else:
                        img = Image.fromarray(thumb.data)
                except rawpy.LibRawNoThumbnailError:
                    img = Image.fromarray(
                        raw.postprocess(use_camera_wb=True, half_size=True)
                    )
        else:
            img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        return img
    except Exception:
        return None


# V26 — display-quality loader for the /full/ endpoint + gallery export.
#
# Pre-V26 ``load_image`` was the only entry point: it preferred the RAW
# file's embedded JPEG thumbnail because that's 20-40× faster than a full
# rawpy postprocess. For DETECTOR analysis that's fine (a 1620px preview
# is more than blur / face / scene need), but for the lightbox + gallery
# the user is comparing the RAW shot against same-shot JPGs, and the
# embedded preview is visibly softer + has the camera's in-cam JPEG
# rendering rather than rawpy's neutral decode.
#
# V26 splits the two:
#   ``load_image``               — analysis path (unchanged, fast).
#   ``load_image_for_display``   — quality-preserving. Used by:
#                                   * scripts/serve_demo.py ``/full/``
#                                     when the request asks for ≥ 1600px
#                                   * pixcull/report/gallery.py
#                                     full-quality image baking
#
# Strategy for RAW:
#   1. Try the embedded JPEG. If it's at least as wide as the target,
#      use it (camera previews are usually 1620×1080 on Canon, 1620
#      on Sony, 1620 on Nikon — already plenty for 1600-px lightbox).
#      Cost: ~30 ms decode.
#   2. Otherwise postprocess the full RAW with camera WB + 8-bit
#      output. Cost: ~500 ms - 2 sec per RAW depending on resolution.
#
# Result: at the typical lightbox size (1600-2400 px) the embedded JPEG
# path wins on Canon / Sony shoots (camera preview already covers it)
# and the postprocess path kicks in only when the user zooms past the
# preview's resolution. JPG / HEIC / TIFF paths are identical to
# ``load_image`` but with the higher max_side cap.
def _apply_develop_settings(img: Image.Image, settings: dict) -> Image.Image:
    """V26.1 — apply a subset of Lr develop settings to a decoded image.

    Approximations (Lr's pipeline is proprietary; we do NOT match it
    pixel-perfect, just get close enough that the lightbox preview
    looks like the user expects):

      * exposure (EV)   → multiply pixel values by 2**exposure
      * contrast        → PIL ImageEnhance.Contrast (1 + 0.5*c) where
                          c in -1..+1
      * saturation/
        vibrance        → PIL ImageEnhance.Color (1 + 0.5*max(s,v))
      * highlights/
        shadows         → PIL.ImageOps.autocontrast cut-points
                          (we shift the histogram tails inward)

    Temperature/tint/whites/blacks not applied — they'd need a proper
    color-temperature transform that PIL doesn't expose. The big four
    above cover ~80% of typical Lr edits.

    Skips silently when ``settings`` is empty.
    """
    if not settings:
        return img
    from PIL import ImageEnhance
    import numpy as np

    # Exposure: multiplicative in linear-light space. PIL doesn't
    # de-gamma for us; we apply the multiplier in sRGB which is
    # imperfect but very close to what Lr displays for small shifts.
    if "exposure" in settings:
        ev = settings["exposure"]
        if abs(ev) > 0.01:
            arr = np.asarray(img, dtype=np.float32)
            arr *= (2.0 ** ev)
            arr = np.clip(arr, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr)

    if "contrast" in settings:
        c = settings["contrast"]
        if abs(c) > 0.01:
            img = ImageEnhance.Contrast(img).enhance(1.0 + 0.5 * c)

    # Saturation + Vibrance share the PIL.ImageEnhance.Color knob.
    # Take whichever is bigger so the user's intent (saturated /
    # desaturated) is preserved when both are set.
    s = settings.get("saturation", 0.0) or 0.0
    v = settings.get("vibrance", 0.0) or 0.0
    sv = s if abs(s) > abs(v) else v
    if abs(sv) > 0.01:
        img = ImageEnhance.Color(img).enhance(1.0 + 0.5 * sv)

    # Highlights/shadows: shift the histogram tails inward / outward.
    # Negative highlights recover blown areas; positive shadows lift
    # the darks. Approximate via a piecewise linear curve.
    hi = settings.get("highlights", 0.0) or 0.0
    sh = settings.get("shadows", 0.0) or 0.0
    if abs(hi) > 0.01 or abs(sh) > 0.01:
        arr = np.asarray(img, dtype=np.float32) / 255.0
        if abs(hi) > 0.01:
            # hi < 0 → compress highlights; hi > 0 → expand
            mask = arr > 0.6
            arr[mask] = arr[mask] - (arr[mask] - 0.6) * (-hi * 0.5)
        if abs(sh) > 0.01:
            mask = arr < 0.4
            arr[mask] = arr[mask] + (0.4 - arr[mask]) * (sh * 0.5)
        arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)

    return img


def load_image_for_display(path: Path,
                              max_side: int = 4800,
                              *,
                              apply_xmp_develop: bool = True,
                              ) -> Optional[Image.Image]:
    """V26 — quality-preserving loader.

    Differences from ``load_image``:
      * For RAW: only uses embedded JPEG when it's >= max_side wide.
        Otherwise falls back to full rawpy postprocess
        (``half_size=False`` — defaults to full bayer demosaic + camera
        WB applied). Costs ~10-50× longer than the thumbnail path but
        produces a sharp display image.
      * Default ``max_side`` is 4800 (vs 2048 for the analysis loader).
        This is the upper bound the lightbox / 5K monitor would ask
        for; smaller targets pass through ``thumbnail()`` as before.

    V26.1 — when ``apply_xmp_develop`` is True (default) and the file
    is a RAW with a sibling ``<stem>.xmp`` carrying Lr ``crs:*``
    develop settings, we go through the rawpy postprocess path AND
    apply the approximate develop settings via PIL. This makes the
    lightbox show roughly what Lr would render for an edited DNG /
    CR3 instead of the neutral rawpy decode.

    The embedded-JPEG path is unchanged — if Lr re-saved the
    embedded preview those edits already bake into the preview.
    """
    ext = path.suffix.lower()
    try:
        if ext in RAW_EXTS:
            # V26.1 — read XMP develop settings up front. If present
            # AND non-trivial, prefer the postprocess path so we can
            # apply them (the embedded preview won't reflect them
            # unless Lr re-rendered, which it often doesn't).
            develop_settings: dict = {}
            if apply_xmp_develop:
                try:
                    from pixcull.io.xmp import read_develop_settings
                    develop_settings = read_develop_settings(path) or {}
                except Exception:
                    develop_settings = {}

            with rawpy.imread(str(path)) as raw:
                img: Optional[Image.Image] = None
                # When Lr develop settings are present, skip the
                # embedded-preview shortcut and decode from bayer so
                # we can apply the settings on a clean image. Without
                # this branch, an edited DNG would render its STALE
                # embedded preview (= pre-edit) for any size ≥ preview.
                if not develop_settings:
                    try:
                        thumb = raw.extract_thumb()
                        if thumb.format == rawpy.ThumbFormat.JPEG:
                            candidate = Image.open(io.BytesIO(thumb.data))
                        else:
                            candidate = Image.fromarray(thumb.data)
                        if max(candidate.size) >= max_side:
                            img = candidate
                    except rawpy.LibRawNoThumbnailError:
                        img = None
                if img is None:
                    img = Image.fromarray(
                        raw.postprocess(
                            use_camera_wb=True,
                            half_size=False,
                            output_bps=8,
                            no_auto_bright=False,
                        )
                    )
                # Apply Lr develop settings on the decoded array
                if develop_settings:
                    img = _apply_develop_settings(img, develop_settings)
        else:
            img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        return img
    except Exception:
        return None


def read_exif_orientation(path: Path) -> int:
    """Return the EXIF Orientation tag value (1..8); defaults to 1 if absent.

    Useful for the frontend manual-rotate UI that wants to show
    "auto-rotated" vs "as-shot" toggles. We don't currently expose
    this in the API, but it's here for the V16.1+ rotation override.
    """
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            return int(exif.get(0x0112, 1))  # 0x0112 = Orientation
    except Exception:
        return 1


def list_images(folder: Path) -> list[Path]:
    """Walk ``folder`` recursively, return image files only.

    V17.13 — filter out hidden files (``.DS_Store`` etc) AND macOS
    AppleDouble sidecars (``._*``) which appear on non-HFS+ external
    drives like exFAT/NTFS. These match ``.jpg`` extension but
    aren't real images; decoding them returns None silently and was
    causing bulk_classify to "lose" most of a folder's images
    (556 paths found in a 67-image folder → only 11 successfully
    analyzed because the rest were ``._*.jpg`` AppleDouble metadata).
    """
    out = []
    for p in folder.rglob("*"):
        if p.suffix.lower() not in ALL_EXTS:
            continue
        if p.name.startswith("."):       # .DS_Store, ._foo.jpg, .hidden
            continue
        out.append(p)
    return sorted(out)
