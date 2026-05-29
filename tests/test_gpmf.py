"""v2.0-P1-5 — tests for pixcull.io.gpmf (GPMF KLV + HiLight tags)."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from pixcull.io import gpmf as G


# --------------------------------------------------------------------------
# synthetic blob builders
# --------------------------------------------------------------------------

def _klv(fourcc, tchar, ssize, repeat, body):
    pad = (-len(body)) % 4
    head = fourcc.encode() + bytes([ord(tchar) if tchar else 0, ssize])
    return head + struct.pack(">H", repeat) + body + b"\x00" * pad


def _atom(t, body):
    return struct.pack(">I", 8 + len(body)) + t.encode() + body


def _gps_blob():
    scal = _klv("SCAL", "l", 4, 5,
                struct.pack(">5i", 10000000, 10000000, 1000, 1000, 100))
    gps5 = _klv("GPS5", "l", 20, 1,
                struct.pack(">5i", 377749000, -1224194000, 10000, 1500, 1600))
    # Nested containers (type 0x00): sample_size=1, repeat=len(payload).
    strm = _klv("STRM", "", 1, len(scal + gps5), scal + gps5)
    return _klv("DEVC", "", 1, len(strm), strm)


# --------------------------------------------------------------------------
# parse_gpmf / extract_gps
# --------------------------------------------------------------------------

def test_parse_gpmf_nested():
    els = G.parse_gpmf(_gps_blob())
    assert len(els) == 1 and els[0].fourcc == "DEVC"
    assert els[0].children  # STRM nested
    gps5 = G._walk(els, "GPS5")
    assert gps5 and len(gps5[0].values) == 5


def test_extract_gps_scaled():
    gps = G.extract_gps(G.parse_gpmf(_gps_blob()))
    assert len(gps) == 1
    p = gps[0]
    assert p["lat"] == pytest.approx(37.7749, abs=1e-4)
    assert p["lon"] == pytest.approx(-122.4194, abs=1e-4)
    assert p["alt_m"] == pytest.approx(10.0)
    assert p["speed_3d"] == pytest.approx(16.0)


def test_parse_gpmf_typed_floats():
    blob = _klv("SHUT", "f", 4, 3, struct.pack(">3f", 1.0, 2.5, 0.25))
    els = G.parse_gpmf(blob)
    assert els[0].fourcc == "SHUT"
    assert els[0].values == pytest.approx([1.0, 2.5, 0.25])


def test_parse_gpmf_empty():
    assert G.parse_gpmf(b"") == []
    assert G.parse_gpmf(b"\x00\x00\x00") == []   # truncated


def test_extract_gps_none_when_absent():
    blob = _klv("SHUT", "f", 4, 1, struct.pack(">f", 1.0))
    assert G.extract_gps(G.parse_gpmf(blob)) == []


# --------------------------------------------------------------------------
# HMMT HiLight tags
# --------------------------------------------------------------------------

def test_parse_hmmt_moov_udta():
    hmmt = struct.pack(">I", 2) + struct.pack(">I", 1500) + struct.pack(">I", 3200)
    mp4 = _atom("moov", _atom("udta", _atom("HMMT", hmmt)))
    assert G.parse_hmmt_atom(mp4) == [1.5, 3.2]


def test_parse_hmmt_toplevel_udta():
    hmmt = struct.pack(">I", 1) + struct.pack(">I", 5000)
    mp4 = _atom("udta", _atom("HMMT", hmmt))
    assert G.parse_hmmt_atom(mp4) == [5.0]


def test_parse_hmmt_drops_zero_terminator():
    hmmt = struct.pack(">I", 3) + struct.pack(">3I", 2000, 4000, 0)
    mp4 = _atom("moov", _atom("udta", _atom("HMMT", hmmt)))
    assert G.parse_hmmt_atom(mp4) == [2.0, 4.0]


def test_parse_hmmt_absent():
    mp4 = _atom("ftyp", b"isom" + b"\x00" * 8)
    assert G.parse_hmmt_atom(mp4) == []


def test_parse_hmmt_garbage_safe():
    assert G.parse_hmmt_atom(b"not an mp4 at all") == []
    assert G.parse_hmmt_atom(b"") == []


# --------------------------------------------------------------------------
# highlight_boost
# --------------------------------------------------------------------------

def test_highlight_boost_triangular():
    b = G.highlight_boost([0, 1, 2, 3, 4], [2.0], window_s=1.5)
    assert b[2] == pytest.approx(1.0)
    assert b[1] == pytest.approx(1 - 1 / 1.5, abs=1e-3)
    assert b[0] == 0.0 and b[4] == 0.0


def test_highlight_boost_multiple_marks_take_max():
    b = G.highlight_boost([0, 1, 2, 3], [0.0, 3.0], window_s=1.0)
    assert b[0] == pytest.approx(1.0)
    assert b[3] == pytest.approx(1.0)
    assert b[1] == pytest.approx(0.0, abs=1e-9)


def test_highlight_boost_no_marks():
    assert np.allclose(G.highlight_boost([0, 1, 2], []), 0.0)


# --------------------------------------------------------------------------
# parse_video_metadata (graceful on a non-GoPro file)
# --------------------------------------------------------------------------

def test_parse_video_metadata_non_gopro(tmp_path):
    # A plain file with no HMMT / GPMF ⇒ has_gpmf False, no crash.
    f = tmp_path / "plain.mp4"
    f.write_bytes(_atom("ftyp", b"isom" + b"\x00" * 8) + _atom("free", b"\x00" * 16))
    meta = G.parse_video_metadata(f)
    assert meta.has_gpmf is False
    assert meta.highlights_s == []
    d = meta.to_dict()
    assert d["highlight_count"] == 0 and d["gps_sample_count"] == 0


def test_parse_video_metadata_with_hmmt(tmp_path):
    hmmt = struct.pack(">I", 2) + struct.pack(">2I", 1000, 7000)
    f = tmp_path / "gopro.mp4"
    f.write_bytes(_atom("moov", _atom("udta", _atom("HMMT", hmmt))))
    meta = G.parse_video_metadata(f)
    assert meta.highlights_s == [1.0, 7.0]
    assert meta.has_gpmf is True
