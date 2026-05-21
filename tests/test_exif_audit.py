"""P-PRO-7 — tests for the EXIF completeness audit helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.io.exif_audit import (
    EXIF_FIELDS_TO_AUDIT,
    ExifFields,
    audit_exif_completeness,
    read_exif_fields,
)


def _make(name: str, **kwargs) -> ExifFields:
    return ExifFields(filename=name, **kwargs)


# ---------- audit aggregation ----------

def test_audit_all_complete():
    full = [_make(f"IMG_{i}.jpg",
                  gps=True, lens=True, focal_length=True,
                  aperture=True, shutter=True, iso=True,
                  datetime=True, camera_body=True)
            for i in range(50)]
    rpt = audit_exif_completeness(full)
    assert rpt.n_files == 50
    assert rpt.missing_critical == []
    for k in EXIF_FIELDS_TO_AUDIT:
        assert rpt.presence_pct(k) == 100.0


def test_audit_no_gps_flagged():
    profiles = [_make(f"IMG_{i}.jpg",
                      gps=False, lens=True, datetime=True)
                for i in range(20)]
    rpt = audit_exif_completeness(profiles)
    assert rpt.presence_pct("gps") == 0.0
    # All 20 files surface as missing the critical GPS field
    assert len(rpt.missing_critical) == 20
    for fn, missing in rpt.missing_critical:
        assert "gps" in missing


def test_audit_per_field_counts_independent():
    """Different files missing different fields shouldn't conflate."""
    profiles = [
        _make("a.jpg", gps=True,  lens=True,  datetime=True),
        _make("b.jpg", gps=False, lens=True,  datetime=True),
        _make("c.jpg", gps=True,  lens=False, datetime=True),
        _make("d.jpg", gps=True,  lens=True,  datetime=False),
    ]
    rpt = audit_exif_completeness(profiles)
    assert rpt.presence_pct("gps")      == 75.0   # 3/4
    assert rpt.presence_pct("lens")     == 75.0
    assert rpt.presence_pct("datetime") == 75.0
    # Each missing-field file shows up
    missing_lookup = {fn: m for fn, m in rpt.missing_critical}
    assert "gps" in missing_lookup["b.jpg"]
    assert "lens" in missing_lookup["c.jpg"]
    assert "datetime" in missing_lookup["d.jpg"]


def test_audit_critical_fields_customizable():
    """Caller can ignore GPS but require ISO + shutter."""
    profiles = [
        _make("a.jpg", gps=False, lens=True,  iso=True, shutter=True),
        _make("b.jpg", gps=False, lens=True,  iso=False, shutter=True),
    ]
    rpt = audit_exif_completeness(
        profiles, critical_fields=["iso", "shutter"])
    # a.jpg has both → not in missing_critical
    # b.jpg missing iso → in missing_critical
    fnames = [fn for fn, _ in rpt.missing_critical]
    assert "a.jpg" not in fnames
    assert "b.jpg" in fnames


def test_audit_worst_offenders_sorted_first():
    profiles = [
        _make("one_missing.jpg",  gps=True,  lens=True, datetime=False),
        _make("three_missing.jpg",gps=False, lens=False, datetime=False),
        _make("two_missing.jpg",  gps=False, lens=False, datetime=True),
    ]
    rpt = audit_exif_completeness(profiles)
    # Worst (3 missing) should be first
    assert rpt.missing_critical[0][0] == "three_missing.jpg"
    assert len(rpt.missing_critical[0][1]) == 3


def test_audit_empty_input_safe():
    rpt = audit_exif_completeness([])
    assert rpt.n_files == 0
    assert rpt.missing_critical == []
    for k in EXIF_FIELDS_TO_AUDIT:
        assert rpt.presence_pct(k) == 0.0


def test_missing_fields_returns_only_falsy():
    p = _make("x.jpg", gps=True, lens=False, datetime=True)
    missing = p.missing_fields()
    assert "lens" in missing
    assert "gps" not in missing
    assert "datetime" not in missing


# ---------- read_exif_fields (file-level) ----------

def test_read_exif_fields_nonexistent_safe(tmp_path):
    """Missing file → all-False ExifFields, doesn't raise."""
    rpt = read_exif_fields(tmp_path / "ghost.jpg")
    assert rpt.gps is False
    assert rpt.lens is False


def test_read_exif_fields_garbage_safe(tmp_path):
    """Non-image content → all-False, doesn't raise."""
    p = tmp_path / "fake.jpg"
    p.write_text("totally not an image", encoding="utf-8")
    rpt = read_exif_fields(p)
    assert rpt.gps is False
    assert all(not getattr(rpt, k) for k in EXIF_FIELDS_TO_AUDIT)


def test_read_exif_fields_minimal_jpeg(tmp_path):
    """A PIL-generated minimal JPEG has no EXIF → all-False."""
    from PIL import Image
    p = tmp_path / "blank.jpg"
    Image.new("RGB", (10, 10)).save(p, "JPEG")
    rpt = read_exif_fields(p)
    # No camera, no GPS, no datetime → everything False
    assert rpt.gps is False
    assert rpt.lens is False
    assert rpt.iso is False
