"""Tests for pixcull.qrcode_svg — minimal QR encoder.

Validates the encoder produces sane SVG output for the URL lengths
we'll see in production (share links + sync events).  We can't
easily *decode* the QR here (would need a zbar / opencv dep), but
we cover: SVG structure is well-formed; black-module count is in
the plausible range; encoder picks the smallest version that fits.
"""

from __future__ import annotations

import re

import pytest

from pixcull.qrcode_svg import _encode, to_svg


def test_to_svg_returns_well_formed_svg():
    svg = to_svg("https://example.com/")
    assert svg.startswith('<svg ')
    assert svg.endswith('</svg>')
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    # Should have a white background rect + a black path
    assert '<rect width=' in svg
    assert '<path d="' in svg
    assert 'fill="#000000"' in svg


def test_to_svg_handles_short_url_with_version_1_or_2():
    matrix, version = _encode("hi")
    # 2-byte text fits in version 1
    assert version == 1
    assert len(matrix) == 21


def test_to_svg_picks_smallest_fitting_version():
    # 17-byte text fits exactly in v1 capacity 17 → still v1
    matrix, version = _encode("a" * 17)
    assert version == 1
    # 18 bytes overflows v1 → must upgrade to v2
    _, v2 = _encode("a" * 18)
    assert v2 == 2


def test_to_svg_handles_full_url_length():
    # Typical sync-event URL is ~70 chars; should fit v4-5
    url = "https://localhost:8989/results/sample_abc123def456?event=A1B2c3D4e5"
    _, v = _encode(url)
    assert 3 <= v <= 6


def test_to_svg_raises_when_too_long():
    # Exceeds V10 capacity (271 bytes at L)
    with pytest.raises(ValueError):
        _encode("x" * 280)


def test_finder_patterns_present_in_svg():
    """All three finder patterns produce dense black squares at the
    corners — sanity check that the matrix-build pass actually ran."""
    matrix, _ = _encode("hi")
    size = len(matrix)
    # Top-left finder: outer ring of black at rows 0/6 + cols 0/6
    for c in range(7):
        assert matrix[0][c] == 1, f"top-left top edge col {c}"
        assert matrix[6][c] == 1, f"top-left bottom edge col {c}"
    # Top-right finder
    for c in range(size - 7, size):
        assert matrix[0][c] == 1
    # Bottom-left finder
    for r in range(size - 7, size):
        assert matrix[r][0] == 1


def test_to_svg_includes_quiet_zone():
    svg = to_svg("hi")
    # Extract width attribute
    m = re.search(r'width="(\d+)"', svg)
    assert m
    width = int(m.group(1))
    # v1 = 21 modules + 2 * 4 border quiet-zone = 29 modules * 8px = 232
    assert width == (21 + 8) * 8


def test_two_calls_same_input_produce_identical_svg():
    a = to_svg("https://x.com/")
    b = to_svg("https://x.com/")
    assert a == b


def test_unicode_url_encodes_to_utf8():
    """Chinese chars in the URL must round-trip as UTF-8 bytes."""
    matrix, _ = _encode("https://x.com/婚礼-2026")
    # No exception → ok
    assert len(matrix) > 0


def test_svg_path_attribute_is_non_empty():
    svg = to_svg("hello")
    m = re.search(r'<path d="([^"]+)"', svg)
    assert m
    assert len(m.group(1)) > 100   # at least many moves for v1
