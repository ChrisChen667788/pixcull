"""EXIF readers for fields PixCull's pipeline cares about.

Pre-V23 only ``read_exif_time`` existed (for date sorting). V23 adds
``read_exif_gps`` for the travel-persona location clustering pass.

Both are best-effort: PIL's EXIF reader returns ``None`` for almost
any decoder failure (corrupted EXIF block, unrecognized tag schemas,
proprietary maker notes). We swallow exceptions and return None
rather than killing the pipeline on the first quirky file.
"""

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


# ---------------------------------------------------------------------------
# V23 — GPS for the location-cluster + "one per location" travel feature.
# ---------------------------------------------------------------------------

# PIL exposes GPS data nested under the GPSInfo tag (index 34853 in the
# IFD0). Inside that block the GPS-specific sub-tags use a separate
# numeric scheme; we look them up via GPSTAGS:
#   1: GPSLatitudeRef  ("N" or "S")
#   2: GPSLatitude     ((deg, min, sec) rationals)
#   3: GPSLongitudeRef ("E" or "W")
#   4: GPSLongitude    ((deg, min, sec) rationals)
_GPSINFO_TAG_NAME = "GPSInfo"


def _dms_to_decimal(dms, ref: str) -> Optional[float]:
    """Convert (deg, min, sec) rationals into a signed decimal degree.

    PIL exposes the rationals as ``(numerator, denominator)`` tuples on
    older Pillow versions and as ``IFDRational`` objects on newer ones.
    Both support ``float()`` so a plain conversion works.

    Returns None when:
      * The input shape doesn't match (deg, min, sec)
      * Any component fails to convert
      * Ref direction isn't N/S/E/W (malformed EXIF)
    """
    try:
        if dms is None or len(dms) < 3:
            return None
        deg = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    decimal = deg + minutes / 60.0 + seconds / 3600.0
    ref_u = (ref or "").upper()
    if ref_u in ("S", "W"):
        return -decimal
    if ref_u in ("N", "E"):
        return decimal
    return None


def read_exif_gps(path: Path) -> Optional[tuple[float, float]]:
    """Best-effort EXIF GPS read. Returns ``(lat, lon)`` in decimal
    degrees (positive N/E, negative S/W) or None on failure / absence.

    A meaningful fraction of pro shots are made on a Canon/Nikon/Sony
    with no GPS module, so "None" is common and not an error — callers
    should treat it as "photo has no location metadata."
    """
    try:
        with Image.open(path) as im:
            exif = im._getexif() or {}
    except Exception:
        return None

    # Find the GPSInfo sub-block.
    gps_block = None
    for k, v in exif.items():
        if ExifTags.TAGS.get(k) == _GPSINFO_TAG_NAME:
            gps_block = v
            break
    if not gps_block:
        return None

    # The keys inside gps_block are integers — map them through GPSTAGS.
    by_name: dict = {}
    for k, v in gps_block.items():
        name = ExifTags.GPSTAGS.get(k)
        if name:
            by_name[name] = v

    lat = _dms_to_decimal(by_name.get("GPSLatitude"),
                            str(by_name.get("GPSLatitudeRef") or ""))
    lon = _dms_to_decimal(by_name.get("GPSLongitude"),
                            str(by_name.get("GPSLongitudeRef") or ""))
    if lat is None or lon is None:
        return None
    # Sanity: valid latitude is [-90, 90], longitude is [-180, 180].
    # Corrupted EXIF sometimes gives degrees=999. Reject silently.
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None
    return (lat, lon)
