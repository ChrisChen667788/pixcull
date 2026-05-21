"""P-PRO-7 — EXIF completeness audit.

Parallel to pixcull/io/icc.py (color-space audit).  Photographers
that deliver to archives / stock libraries / clients are often
contractually required to include certain EXIF fields:

  - GPS coords (for travel albums + stock libraries that require
    geotagging)
  - Lens model (for analytics + lens-specific catalog filters)
  - Focal length, aperture, shutter, ISO (the "exposure triangle"
    every viewer expects to see in the EXIF panel)
  - DateTimeOriginal (for chronological sorting + archive metadata)

A delivery folder with missing fields gets flagged by the client
in the worst case ("the GPS is missing on every photo so I can't
sort by location") or just silently degrades the catalog
experience.  This audit surfaces the missing-field rates BEFORE
delivery.

Reads via PIL.ExifTags.IFD (Python 3.12+) so no external libraries
needed.  Returns counts + per-field presence rates + per-file
missing-field details for the worst offenders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Map of fields we care about → human-readable label.  The
# extractor below pulls from either the top-level IFD or the
# Exif sub-IFD depending on the field; this list is the union.
EXIF_FIELDS_TO_AUDIT: dict[str, str] = {
    "gps":            "GPS 坐标",
    "lens":           "镜头型号",
    "focal_length":   "焦段",
    "aperture":       "光圈",
    "shutter":        "快门",
    "iso":            "ISO",
    "datetime":       "拍摄时间",
    "camera_body":    "机身型号",
}


@dataclass
class ExifFields:
    """Result of profiling a single image's EXIF for the audit."""
    filename:      str
    gps:           bool = False    # has GPSLatitude/Longitude
    lens:          bool = False    # has LensModel
    focal_length:  bool = False
    aperture:      bool = False    # FNumber or ApertureValue
    shutter:       bool = False    # ExposureTime
    iso:           bool = False    # ISOSpeedRatings
    datetime:      bool = False    # DateTimeOriginal
    camera_body:   bool = False    # Model

    def missing_fields(self) -> list[str]:
        return [k for k in EXIF_FIELDS_TO_AUDIT
                if not getattr(self, k)]


def read_exif_fields(path: Path) -> ExifFields:
    """Open ``path`` and check which audit fields are populated.

    Never raises — returns an all-False ExifFields for unparseable
    files.  This is best-effort metadata extraction; a single
    broken file shouldn't break the whole batch.
    """
    out = ExifFields(filename=path.name)
    try:
        from PIL import Image, ExifTags
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return out
            # Top-level IFD
            out.camera_body = bool((exif.get(0x010F) or "").strip()
                                   if exif.get(0x010F) else False) \
                              or bool((exif.get(0x0110) or "").strip()
                                      if exif.get(0x0110) else False)
            # Exif sub-IFD — focal / aperture / shutter / iso / lens /
            # datetime live here.
            try:
                sub = exif.get_ifd(ExifTags.IFD.Exif)
            except (AttributeError, KeyError, OSError):
                sub = {}
            # LensModel tag is 0xa434
            lens = sub.get(0xa434) if sub else None
            out.lens = bool(lens and (lens if not isinstance(lens, bytes)
                                            else lens.decode("utf-8",
                                                "ignore")).strip())
            # FocalLength 0x920a
            out.focal_length = sub.get(0x920a) is not None
            # FNumber 0x829d OR ApertureValue 0x9202
            out.aperture = (sub.get(0x829d) is not None
                            or sub.get(0x9202) is not None)
            # ExposureTime 0x829a
            out.shutter = sub.get(0x829a) is not None
            # ISOSpeedRatings 0x8827
            out.iso = sub.get(0x8827) is not None
            # DateTimeOriginal 0x9003
            dt = sub.get(0x9003)
            out.datetime = bool(dt and str(dt).strip()) \
                           or bool(exif.get(0x0132)
                                   and str(exif.get(0x0132)).strip())
            # GPS — top-level GPSInfo tag (0x8825) is just the offset;
            # the actual lat/lon live in the GPS IFD.
            try:
                gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            except (AttributeError, KeyError, OSError):
                gps_ifd = {}
            # GPSLatitude tag = 2, GPSLongitude tag = 4
            out.gps = bool(gps_ifd) and \
                      (gps_ifd.get(2) is not None
                       and gps_ifd.get(4) is not None)
    except (OSError, ValueError, AttributeError, ImportError):
        pass
    return out


@dataclass
class ExifCompletenessAudit:
    """Aggregate EXIF completeness across an album."""
    n_files:          int
    per_field_present: dict[str, int]    # field → count present
    missing_critical:  list[tuple[str, list[str]]]
        # filename → list of missing field keys
        # truncated to worst 30 in the report

    def presence_pct(self, field: str) -> float:
        """% of files that have the given field populated."""
        if self.n_files == 0:
            return 0.0
        n = self.per_field_present.get(field, 0)
        return round(100.0 * n / self.n_files, 1)


def audit_exif_completeness(
    profiles: list[ExifFields],
    critical_fields: Optional[list[str]] = None,
) -> ExifCompletenessAudit:
    """Aggregate across an album.

    ``critical_fields`` defaults to GPS + lens + datetime — the
    contract-grade ones whose absence usually breaks downstream
    workflow.  Files missing ANY critical field surface in
    missing_critical so the photographer can re-export.
    """
    if critical_fields is None:
        critical_fields = ["gps", "lens", "datetime"]
    per_field_present: dict[str, int] = {
        k: 0 for k in EXIF_FIELDS_TO_AUDIT
    }
    missing_critical: list[tuple[str, list[str]]] = []
    for p in profiles:
        for k in EXIF_FIELDS_TO_AUDIT:
            if getattr(p, k):
                per_field_present[k] += 1
        missing = [k for k in critical_fields if not getattr(p, k)]
        if missing:
            missing_critical.append((p.filename, missing))
    # Sort worst offenders first (most missing fields)
    missing_critical.sort(key=lambda kv: -len(kv[1]))
    return ExifCompletenessAudit(
        n_files=len(profiles),
        per_field_present=per_field_present,
        missing_critical=missing_critical,
    )
