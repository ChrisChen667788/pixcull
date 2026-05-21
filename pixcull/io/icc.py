"""P-PRO-6 — ICC profile / color-space extraction helpers.

Used by the unified CLI audit (scripts/cli_audit.py) to flag color
space inconsistency across a delivery folder.  Photographers often
end up with mixed sRGB + Display P3 + Adobe RGB in the same album
when frames came from different sources (Lr export, direct Canon
JPG, iPhone photo). On a Display P3 monitor a "mixed sRGB album"
ships out duller than intended; on an sRGB monitor a Display P3
file can show shifted reds.

This module:
  · reads the embedded ICC profile from a file (PIL → ImageCms)
  · maps the profile description to a normalized name (one of
    sRGB / Display P3 / Adobe RGB / ProPhoto RGB / unknown)
  · also reads the EXIF ColorSpace tag (0xa001) as a fallback
    when there's no ICC (some Canon JPGs)

Pure Python — no ImageMagick / lcms binary required.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional


# Map fragments seen in real ICC profile descriptions → canonical
# names.  Built from observed descriptions in Lr 13+ / C1 / Mac
# Preview / iPhone exports.  Matching is case-insensitive substring.
_ICC_NAME_FRAGMENTS: list[tuple[str, str]] = [
    # most specific first
    ("display p3",     "Display P3"),
    ("display-p3",     "Display P3"),
    ("displayp3",      "Display P3"),
    ("prophoto",       "ProPhoto RGB"),
    ("pro photo",      "ProPhoto RGB"),
    ("rommrgb",        "ProPhoto RGB"),
    ("adobe rgb",      "Adobe RGB"),
    ("adobergb",       "Adobe RGB"),
    ("rec. 2020",      "Rec. 2020"),
    ("rec2020",        "Rec. 2020"),
    ("bt.2020",        "Rec. 2020"),
    ("rec. 709",       "Rec. 709"),
    ("dci-p3",         "DCI-P3"),
    ("dcip3",          "DCI-P3"),
    # least specific last so srgb doesn't snag P3
    ("srgb",           "sRGB"),
    ("iec61966",       "sRGB"),
]

# EXIF ColorSpace tag (0xa001) values per the spec
_EXIF_COLOR_SPACE_MAP = {
    1:      "sRGB",          # standard sRGB
    2:      "Adobe RGB",     # Adobe RGB (1998) — Canon-specific extension
    65535:  "Uncalibrated",  # no profile
}


@dataclass
class ColorProfile:
    """Result of profiling a single image."""
    filename:        str
    icc_description: Optional[str]    # raw description from the ICC tag
    canonical_name:  str              # one of "sRGB" / "Display P3" / ...
    has_icc:         bool             # True if an ICC profile was embedded
    exif_color_space: Optional[str]   # parsed EXIF ColorSpace tag (0xa001)

    @property
    def is_unknown(self) -> bool:
        return self.canonical_name == "unknown"


def _normalize_icc_name(description: str) -> str:
    """Normalize an ICC description into a canonical name.

    Robust to whitespace variants ("ROMM RGB" vs "rommrgb", "IEC
    61966" vs "iec61966") by stripping spaces before substring
    matching.  Case-insensitive.
    """
    if not description:
        return "unknown"
    # Lowercase + drop spaces / punctuation so "Standard RGB IEC
    # 61966" / "iec61966" / "iec-61966" all collapse to "iec61966".
    d = re.sub(r"[\s\-_\.]", "", description.lower())
    for frag, canonical in _ICC_NAME_FRAGMENTS:
        if re.sub(r"[\s\-_\.]", "", frag) in d:
            return canonical
    return "unknown"


def read_color_profile(path: Path) -> ColorProfile:
    """Open ``path`` and read its ICC profile + EXIF color space tag.

    Never raises — returns a ColorProfile with all unknown fields if
    the file isn't a parseable image.  The audit is best-effort
    metadata extraction; a single broken file shouldn't break the
    whole batch.
    """
    fn = path.name
    icc_desc: Optional[str] = None
    canonical = "unknown"
    has_icc = False
    exif_cs: Optional[str] = None

    try:
        # Lazy-import PIL/ImageCms so non-image callers don't pay
        # the import cost.
        from PIL import Image, ImageCms

        with Image.open(path) as img:
            icc_bytes = img.info.get("icc_profile")
            if icc_bytes:
                has_icc = True
                try:
                    prof = ImageCms.ImageCmsProfile(BytesIO(icc_bytes))
                    icc_desc = ImageCms.getProfileDescription(prof).strip()
                    canonical = _normalize_icc_name(icc_desc)
                except (OSError, ValueError, AttributeError):
                    # malformed ICC blob; fall through to EXIF check
                    icc_desc = "(unreadable ICC)"
                    canonical = "unknown"

            try:
                exif = img.getexif()
                cs = exif.get(0xa001)
                if cs is not None:
                    exif_cs = _EXIF_COLOR_SPACE_MAP.get(int(cs), str(cs))
            except (OSError, ValueError, AttributeError):
                pass

        # Fallback: no ICC → use EXIF ColorSpace
        if canonical == "unknown" and exif_cs and exif_cs != "Uncalibrated":
            canonical = exif_cs
    except (OSError, ValueError, AttributeError, ImportError):
        # File isn't an image / PIL not installed.  Return the
        # "all unknown" profile.
        pass

    return ColorProfile(
        filename=fn,
        icc_description=icc_desc,
        canonical_name=canonical,
        has_icc=has_icc,
        exif_color_space=exif_cs,
    )


@dataclass
class ColorSpaceAudit:
    """Aggregate audit across many files."""
    n_files:        int
    counts:         dict[str, int]
    n_no_icc:       int
    canonical_majority: Optional[str]      # most-common canonical name
    is_consistent:  bool                    # ≥ 95% same canonical name
    minority_files: list[str]               # filenames NOT in the majority

    @property
    def consistency_pct(self) -> float:
        if self.n_files == 0:
            return 0.0
        if self.canonical_majority is None:
            return 0.0
        return round(
            100.0 * self.counts.get(self.canonical_majority, 0)
                  / self.n_files, 1)


def audit_color_space(
    profiles: list[ColorProfile],
    consistency_threshold: float = 0.95,
) -> ColorSpaceAudit:
    """Build the aggregate audit from a list of ColorProfile objects.

    "Consistent" means ``consistency_threshold`` (default 95%) of
    files share the same canonical color space.  Below that, the
    photographer will see color shifts in some viewers and the
    audit surfaces the minority files for them to re-export.
    """
    n = len(profiles)
    counts: dict[str, int] = {}
    n_no_icc = 0
    for p in profiles:
        counts[p.canonical_name] = counts.get(p.canonical_name, 0) + 1
        if not p.has_icc:
            n_no_icc += 1
    majority = max(counts.items(), key=lambda kv: kv[1])[0] if counts else None
    is_consistent = False
    minority_files: list[str] = []
    if majority and n > 0:
        share = counts[majority] / n
        is_consistent = share >= consistency_threshold
        if not is_consistent:
            minority_files = [p.filename for p in profiles
                              if p.canonical_name != majority]
    return ColorSpaceAudit(
        n_files=n,
        counts=counts,
        n_no_icc=n_no_icc,
        canonical_majority=majority,
        is_consistent=is_consistent,
        minority_files=minority_files,
    )
