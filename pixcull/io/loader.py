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
