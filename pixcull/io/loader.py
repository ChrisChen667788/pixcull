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
def load_image_for_display(path: Path,
                              max_side: int = 4800) -> Optional[Image.Image]:
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
    """
    ext = path.suffix.lower()
    try:
        if ext in RAW_EXTS:
            with rawpy.imread(str(path)) as raw:
                img: Optional[Image.Image] = None
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        candidate = Image.open(io.BytesIO(thumb.data))
                    else:
                        candidate = Image.fromarray(thumb.data)
                    # Only accept the embedded preview if it's already
                    # at least the target resolution. Otherwise we'd
                    # ship a 1620-px upscale on a 5K monitor → blurry.
                    if max(candidate.size) >= max_side:
                        img = candidate
                except rawpy.LibRawNoThumbnailError:
                    img = None
                if img is None:
                    # Full demosaic. ``no_auto_bright=False`` lets
                    # rawpy stretch the histogram for a pleasing preview
                    # (similar to camera-jpeg behavior); turn off if
                    # you want clinical exposure.
                    img = Image.fromarray(
                        raw.postprocess(
                            use_camera_wb=True,
                            half_size=False,
                            output_bps=8,
                            no_auto_bright=False,
                        )
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
