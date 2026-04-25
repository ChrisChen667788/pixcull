from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import ExifTags, Image


def read_exif_time(path: Path) -> Optional[datetime]:
    """Best-effort EXIF DateTimeOriginal read. Returns None on failure."""
    try:
        with Image.open(path) as im:
            exif = im._getexif() or {}
        for k, v in exif.items():
            if ExifTags.TAGS.get(k) == "DateTimeOriginal":
                return datetime.strptime(v, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None
