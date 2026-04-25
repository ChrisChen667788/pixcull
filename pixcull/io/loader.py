import io
from pathlib import Path
from typing import Optional

import rawpy
from PIL import Image

from pixcull.io.formats import ALL_EXTS, RAW_EXTS


def load_image(path: Path, max_side: int = 2048) -> Optional[Image.Image]:
    """Load image; for RAW, prefer embedded JPEG thumbnail (20-40x faster than full decode)."""
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
        img = img.convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        return img
    except Exception:
        return None


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in ALL_EXTS)
