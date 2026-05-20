"""P-PRO-2 — tests for the unified sidecar reader (Lr .xmp + C1 .cos)."""
from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.io.xmp import read_xmp, read_c1_session_sidecar, read_sidecar_any


# Realistic Lightroom-emitted .xmp (truncated to the tags we care about)
LR_XMP = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.6">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmp:Rating="5"
    xmp:Label="Green">
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

# Capture One Session .cos sample
C1_COS = """<?xml version="1.0" encoding="UTF-8"?>
<SL>
  <ImageMetadata>
    <Rating>4</Rating>
    <ColorTag>3</ColorTag>
  </ImageMetadata>
</SL>"""


def test_read_xmp_lr(tmp_path: Path):
    img = tmp_path / "IMG_001.jpg"
    img.write_bytes(b"")
    sidecar = tmp_path / "IMG_001.xmp"
    sidecar.write_text(LR_XMP, encoding="utf-8")
    out = read_xmp(img)
    assert out["rating"] == 5
    assert out["color_label"] == "Green"
    assert out["source"] == "xmp"


def test_read_xmp_no_sidecar(tmp_path: Path):
    img = tmp_path / "missing.jpg"
    out = read_xmp(img)
    assert out["rating"] == 0
    assert out["color_label"] == ""
    assert out["source"] == ""


def test_read_c1_session_sidecar(tmp_path: Path):
    img = tmp_path / "IMG_002.jpg"
    img.write_bytes(b"")
    # C1 session layout: CaptureOne/Settings12/<image>.cos
    settings = tmp_path / "CaptureOne" / "Settings12"
    settings.mkdir(parents=True)
    cos_path = settings / "IMG_002.jpg.cos"
    cos_path.write_text(C1_COS, encoding="utf-8")
    out = read_c1_session_sidecar(img)
    assert out["rating"] == 4
    assert out["color_label"] == "Green"   # ColorTag 3 → Green
    assert out["source"] == "c1_session"


def test_read_c1_session_color_tag_mapping(tmp_path: Path):
    """All 8 C1 color tags map to the right label names."""
    cases = [
        (0, ""), (1, "Red"), (2, "Yellow"), (3, "Green"),
        (4, "Blue"), (5, "Purple"), (6, "Pink"), (7, "Orange"),
    ]
    for tag_int, expected in cases:
        img = tmp_path / f"img_{tag_int}.jpg"; img.write_bytes(b"")
        settings = tmp_path / "CaptureOne" / "Settings12"
        settings.mkdir(parents=True, exist_ok=True)
        (settings / f"img_{tag_int}.jpg.cos").write_text(
            f"<SL><Rating>5</Rating><ColorTag>{tag_int}</ColorTag></SL>",
            encoding="utf-8")
        out = read_c1_session_sidecar(img)
        assert out["color_label"] == expected, \
            f"tag {tag_int}: expected {expected!r}, got {out['color_label']!r}"


def test_read_sidecar_any_prefers_xmp(tmp_path: Path):
    """When BOTH .xmp and .cos exist, .xmp wins (it's the universal format)."""
    img = tmp_path / "IMG_003.jpg"; img.write_bytes(b"")
    (tmp_path / "IMG_003.xmp").write_text(LR_XMP, encoding="utf-8")
    settings = tmp_path / "CaptureOne" / "Settings12"; settings.mkdir(parents=True)
    (settings / "IMG_003.jpg.cos").write_text(C1_COS, encoding="utf-8")
    out = read_sidecar_any(img)
    assert out["rating"] == 5            # xmp rating wins
    assert out["color_label"] == "Green"  # xmp label
    assert out["source"] == "xmp"


def test_read_sidecar_any_falls_back_to_cos(tmp_path: Path):
    """When .xmp is missing, .cos is the next fallback."""
    img = tmp_path / "IMG_004.jpg"; img.write_bytes(b"")
    settings = tmp_path / "CaptureOne" / "Settings12"; settings.mkdir(parents=True)
    (settings / "IMG_004.jpg.cos").write_text(C1_COS, encoding="utf-8")
    out = read_sidecar_any(img)
    assert out["rating"] == 4
    assert out["color_label"] == "Green"
    assert out["source"] == "c1_session"


def test_read_sidecar_any_no_sidecar(tmp_path: Path):
    """No sidecars anywhere → zero rating, no source."""
    img = tmp_path / "naked.jpg"; img.write_bytes(b"")
    out = read_sidecar_any(img)
    assert out["rating"] == 0
    assert out["source"] == ""
