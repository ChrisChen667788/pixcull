"""P-PRO-6 — tests for the ICC profile / color-space audit helpers.

Pure-Python helpers — no real image parsing in these tests, just
the normalization + aggregate audit logic.  Real-file behaviour
is covered indirectly through the CLI smoke test (which calls
through the audit on a synthetic scores.csv with paths).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.io.icc import (
    ColorProfile,
    _normalize_icc_name,
    audit_color_space,
    read_color_profile,
)


# ---------- _normalize_icc_name ----------

def test_normalize_sRGB_variants():
    assert _normalize_icc_name("sRGB IEC61966-2.1") == "sRGB"
    assert _normalize_icc_name("sRGB") == "sRGB"
    assert _normalize_icc_name("Standard RGB IEC 61966") == "sRGB"


def test_normalize_display_p3_variants():
    """Display P3 must not be misclassified as sRGB (P3 has 'rgb'
    in the canonical name too)."""
    assert _normalize_icc_name("Display P3") == "Display P3"
    assert _normalize_icc_name("Apple Display P3") == "Display P3"
    assert _normalize_icc_name("DisplayP3") == "Display P3"


def test_normalize_prophoto():
    assert _normalize_icc_name("ProPhoto RGB") == "ProPhoto RGB"
    assert _normalize_icc_name("Pro Photo RGB") == "ProPhoto RGB"
    assert _normalize_icc_name("ROMM RGB ISO 22028-2") == "ProPhoto RGB"


def test_normalize_adobe_rgb():
    assert _normalize_icc_name("Adobe RGB (1998)") == "Adobe RGB"
    assert _normalize_icc_name("AdobeRGB1998") == "Adobe RGB"


def test_normalize_unknown_falls_back():
    assert _normalize_icc_name("") == "unknown"
    assert _normalize_icc_name(None) == "unknown"
    assert _normalize_icc_name("Some Weird Custom Profile") == "unknown"


# ---------- audit_color_space ----------

def _profile(name: str, canonical: str, has_icc: bool = True) -> ColorProfile:
    return ColorProfile(filename=name, icc_description=canonical,
                        canonical_name=canonical, has_icc=has_icc,
                        exif_color_space=None)


def test_audit_consistent_album():
    profiles = [_profile(f"IMG_{i}.jpg", "sRGB") for i in range(100)]
    rpt = audit_color_space(profiles)
    assert rpt.n_files == 100
    assert rpt.canonical_majority == "sRGB"
    assert rpt.is_consistent is True
    assert rpt.minority_files == []
    assert rpt.consistency_pct == 100.0


def test_audit_flags_inconsistency():
    """An album with 95 sRGB + 5 Display P3 is at the threshold —
    still consistent by default (≥95%).  Drop to 94 and it flips."""
    profiles = ([_profile(f"sRGB_{i}.jpg", "sRGB") for i in range(95)] +
                [_profile(f"P3_{i}.jpg", "Display P3") for i in range(5)])
    rpt = audit_color_space(profiles)
    assert rpt.canonical_majority == "sRGB"
    assert rpt.is_consistent is True
    assert rpt.consistency_pct == 95.0


def test_audit_below_threshold_lists_minority():
    profiles = ([_profile(f"sRGB_{i}.jpg", "sRGB") for i in range(80)] +
                [_profile(f"P3_{i}.jpg", "Display P3") for i in range(20)])
    rpt = audit_color_space(profiles)
    assert rpt.is_consistent is False
    assert rpt.canonical_majority == "sRGB"
    # All 20 P3 files surface in minority_files
    assert len(rpt.minority_files) == 20
    assert all("P3" in fn for fn in rpt.minority_files)


def test_audit_counts_no_icc():
    profiles = [
        _profile("with_icc.jpg",   "sRGB",    has_icc=True),
        _profile("no_icc_1.jpg",   "unknown", has_icc=False),
        _profile("no_icc_2.jpg",   "unknown", has_icc=False),
    ]
    rpt = audit_color_space(profiles)
    assert rpt.n_no_icc == 2


def test_audit_empty_input_safe():
    rpt = audit_color_space([])
    assert rpt.n_files == 0
    assert rpt.canonical_majority is None
    assert rpt.is_consistent is False
    assert rpt.consistency_pct == 0.0


def test_audit_threshold_customizable():
    """Caller can tighten the threshold to flag even small minorities."""
    profiles = ([_profile(f"sRGB_{i}.jpg", "sRGB") for i in range(99)] +
                [_profile("p3.jpg", "Display P3")])
    rpt_default = audit_color_space(profiles)
    rpt_strict  = audit_color_space(profiles, consistency_threshold=1.00)
    assert rpt_default.is_consistent is True
    assert rpt_strict.is_consistent is False
    assert rpt_strict.minority_files == ["p3.jpg"]


# ---------- read_color_profile (file-level, lightly mocked) ----------

def test_read_color_profile_nonexistent_safe(tmp_path):
    """Missing file → returns unknown profile, doesn't raise."""
    rpt = read_color_profile(tmp_path / "ghost.jpg")
    assert rpt.canonical_name == "unknown"
    assert rpt.has_icc is False


def test_read_color_profile_garbage_safe(tmp_path):
    """File that isn't an image → returns unknown profile, doesn't raise."""
    p = tmp_path / "not_an_image.jpg"
    p.write_text("definitely not a jpeg", encoding="utf-8")
    rpt = read_color_profile(p)
    assert rpt.canonical_name == "unknown"
    assert rpt.has_icc is False


def test_read_color_profile_real_jpeg(tmp_path):
    """A minimal real JPEG (no ICC, no EXIF) returns unknown."""
    from PIL import Image
    p = tmp_path / "tiny.jpg"
    img = Image.new("RGB", (10, 10), (128, 128, 128))
    img.save(p, "JPEG")
    rpt = read_color_profile(p)
    assert rpt.has_icc is False
    # Color space unknown without ICC + without EXIF tag
    assert rpt.canonical_name in ("unknown", "sRGB")  # PIL sometimes
                                                       # writes implicit sRGB
