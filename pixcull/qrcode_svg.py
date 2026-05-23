"""v0.8-P1-3 — pure-Python QR code → SVG.

Minimal QR Code encoder supporting:
  * byte mode (works for any ASCII / UTF-8 URL)
  * error-correction level L (~7% redundancy — fine for ≤200-char URLs
    rendered on a screen in good lighting)
  * versions 1-10 (21x21 → 57x57); auto-picks the smallest that fits

That covers every URL we mint here.  Notably out of scope: numeric /
alphanumeric mode (smaller encodings for digits-only / uppercase data),
versions >10 (would need alignment-pattern tables for 9 more sizes),
ECC levels M/Q/H (we use L exclusively).

Why pure-Python instead of `pip install qrcode`:
  * Zero new runtime deps (pyproject.toml stays clean).
  * Reproducible across Python versions (no cffi / Pillow hops).
  * The encoder is ~250 lines and exercises only basic int ops, so
    it's faster to read than to pull a dep.

Reference: ISO/IEC 18004 + Nayuki's QR Code Generator (public domain,
algorithmic structure inspiration only; this code was re-implemented
from the spec).
"""

from __future__ import annotations

from typing import List

# --------------------------------------------------------------------
# Spec tables
# --------------------------------------------------------------------

# Byte-mode capacity (in bytes) per version at error level L.
# Source: QR Code spec, table 7.
_CAPACITY_BYTES_L = {
    1: 17, 2: 32, 3: 53, 4: 78, 5: 106,
    6: 134, 7: 154, 8: 192, 9: 230, 10: 271,
}

# Number of ECC codewords per block at error level L (version 1-10).
# Each version at L has either 1 or 2 EC blocks.  Table 9.
# Layout: (ec_per_block, [(num_blocks, data_per_block), ...])
_BLOCK_LAYOUT_L = {
    1:  (7,  [(1, 19)]),
    2:  (10, [(1, 34)]),
    3:  (15, [(1, 55)]),
    4:  (20, [(1, 80)]),
    5:  (26, [(1, 108)]),
    6:  (18, [(2, 68)]),
    7:  (20, [(2, 78)]),
    8:  (24, [(2, 97)]),
    9:  (30, [(2, 116)]),
    10: (18, [(2, 68), (2, 69)]),
}

# Alignment-pattern centre coordinates per version (table E.1).
# Empty list means none (version 1).
_ALIGNMENT_CENTRES = {
    1:  [],
    2:  [6, 18],
    3:  [6, 22],
    4:  [6, 26],
    5:  [6, 30],
    6:  [6, 34],
    7:  [6, 22, 38],
    8:  [6, 24, 42],
    9:  [6, 26, 46],
    10: [6, 28, 50],
}

# Format-info bit table (table C.1).
# Index = (ec_indicator << 3) | mask_pattern, where ec_indicator for L=01.
# Pre-computed 15-bit format info XOR'd with 0x5412.
_FORMAT_INFO_L = {
    0: 0x77C4, 1: 0x72F3, 2: 0x7DAA, 3: 0x789D,
    4: 0x662F, 5: 0x6318, 6: 0x6C41, 7: 0x6976,
}


# --------------------------------------------------------------------
# GF(2^8) arithmetic for Reed-Solomon
# --------------------------------------------------------------------

_GF_EXP = [1] * 256
_GF_LOG = [0] * 256


def _init_gf():
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    # 255 entries used; extend exp to 512 for easy wrap-around mul
    for i in range(255, 512):
        _GF_EXP[i % 256] = _GF_EXP[i % 255]


_init_gf()
# Extend with mod-255 wrap so we can multiply without taking mod.
_GF_EXP_DBL = _GF_EXP + _GF_EXP


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP_DBL[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(n_ec: int) -> List[int]:
    poly = [1]
    for i in range(n_ec):
        poly = _poly_mul(poly, [1, _GF_EXP[i]])
    return poly


def _poly_mul(a: List[int], b: List[int]) -> List[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, av in enumerate(a):
        if av == 0:
            continue
        for j, bv in enumerate(b):
            out[i + j] ^= _gf_mul(av, bv)
    return out


def _rs_encode(data: bytes, n_ec: int) -> bytes:
    """Reed-Solomon encode: return n_ec EC bytes for ``data``."""
    gen = _rs_generator_poly(n_ec)
    buf = list(data) + [0] * n_ec
    for i in range(len(data)):
        lead = buf[i]
        if lead == 0:
            continue
        for j, g in enumerate(gen):
            buf[i + j] ^= _gf_mul(g, lead)
    return bytes(buf[len(data):])


# --------------------------------------------------------------------
# Encode → matrix
# --------------------------------------------------------------------


def _pick_version(n_bytes: int) -> int:
    for v in range(1, 11):
        if n_bytes <= _CAPACITY_BYTES_L[v]:
            return v
    raise ValueError(f"text too long for QR version ≤10 at level L: {n_bytes}B")


def _bitstream(data: bytes, version: int) -> bytes:
    """Build the data codewords (with mode + length + terminator +
    padding) for byte-mode at error level L."""
    # Bit buffer
    bits = []

    def put(value: int, n: int):
        for i in range(n - 1, -1, -1):
            bits.append((value >> i) & 1)

    # Mode indicator: 0100 (byte)
    put(0b0100, 4)
    # Character count: 8 bits for V1-9, 16 bits for V10-40
    count_len = 8 if version < 10 else 16
    put(len(data), count_len)
    # Data
    for b in data:
        put(b, 8)
    # Terminator (up to 4 zero bits, only as many as fit)
    capacity_bits = _CAPACITY_BYTES_L[version] * 8
    term = min(4, capacity_bits - len(bits))
    put(0, max(0, term))
    # Pad to byte boundary
    while len(bits) % 8:
        bits.append(0)
    # Pad with 0xEC, 0x11 alternating until full
    pads = [0xEC, 0x11]
    pi = 0
    while len(bits) // 8 < _CAPACITY_BYTES_L[version]:
        put(pads[pi % 2], 8)
        pi += 1
    # Pack bits into bytes
    out = bytearray()
    for i in range(0, len(bits), 8):
        v = 0
        for b in bits[i:i + 8]:
            v = (v << 1) | b
        out.append(v)
    return bytes(out)


def _build_codewords(data_codewords: bytes, version: int) -> bytes:
    """Interleave data + EC blocks per the spec.  For V1-9 there's
    one EC block at L so this collapses to ``data + ec``; V10 has
    two blocks of different sizes so requires real interleaving."""
    ec_per_block, layout = _BLOCK_LAYOUT_L[version]
    blocks = []
    ec_blocks = []
    offset = 0
    for count, data_size in layout:
        for _ in range(count):
            block = data_codewords[offset:offset + data_size]
            offset += data_size
            blocks.append(block)
            ec_blocks.append(_rs_encode(block, ec_per_block))
    # Interleave: column-major within data, then column-major within ec
    out = bytearray()
    max_data_len = max(len(b) for b in blocks)
    for i in range(max_data_len):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    max_ec_len = max(len(b) for b in ec_blocks)
    for i in range(max_ec_len):
        for b in ec_blocks:
            if i < len(b):
                out.append(b[i])
    return bytes(out)


def _place_finder(m: List[List[int]], r: int, c: int) -> None:
    """Place a 7x7 finder pattern + the surrounding 1-module separator."""
    size = len(m)
    for dr in range(-1, 8):
        for dc in range(-1, 8):
            rr, cc = r + dr, c + dc
            if 0 <= rr < size and 0 <= cc < size:
                # Edge of the surround = 0 (separator)
                if dr == -1 or dr == 7 or dc == -1 or dc == 7:
                    m[rr][cc] = 0
                elif (0 <= dr <= 6 and 0 <= dc <= 6
                      and (dr in (0, 6) or dc in (0, 6)
                           or (2 <= dr <= 4 and 2 <= dc <= 4))):
                    m[rr][cc] = 1
                else:
                    m[rr][cc] = 0


def _place_alignment(m: List[List[int]], version: int) -> None:
    centres = _ALIGNMENT_CENTRES[version]
    for r in centres:
        for c in centres:
            # Skip alignment patterns that overlap the three finder
            # patterns (top-left, top-right, bottom-left corners).
            if (r, c) in ((6, 6), (6, centres[-1]), (centres[-1], 6)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    if (abs(dr) == 2 or abs(dc) == 2
                            or (dr == 0 and dc == 0)):
                        m[r + dr][c + dc] = 1
                    else:
                        m[r + dr][c + dc] = 0


def _place_timing(m: List[List[int]]) -> None:
    size = len(m)
    for i in range(8, size - 8):
        v = 1 if i % 2 == 0 else 0
        m[6][i] = v
        m[i][6] = v


def _reserve_format(reserved: List[List[bool]]) -> None:
    """Mark the format-info modules so the data-laying pass skips them."""
    size = len(reserved)
    for i in range(9):
        reserved[i][8] = True
        reserved[8][i] = True
    for i in range(size - 8, size):
        reserved[8][i] = True
        reserved[i][8] = True


def _mask_func(idx: int):
    """Return the mask predicate for index 0-7."""
    return [
        lambda r, c: (r + c) % 2 == 0,
        lambda r, c: r % 2 == 0,
        lambda r, c: c % 3 == 0,
        lambda r, c: (r + c) % 3 == 0,
        lambda r, c: ((r // 2) + (c // 3)) % 2 == 0,
        lambda r, c: ((r * c) % 2 + (r * c) % 3) == 0,
        lambda r, c: (((r * c) % 2 + (r * c) % 3) % 2) == 0,
        lambda r, c: (((r + c) % 2 + (r * c) % 3) % 2) == 0,
    ][idx]


def _place_data(m: List[List[int]],
                reserved: List[List[bool]],
                codewords: bytes,
                mask_idx: int) -> None:
    """Walk the matrix in 2-col zig-zag from bottom-right + lay data."""
    size = len(m)
    mask = _mask_func(mask_idx)
    bit_iter = iter(((b >> (7 - i)) & 1)
                    for b in codewords for i in range(8))
    c = size - 1
    upward = True
    while c >= 0:
        if c == 6:    # timing column
            c -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for dc in (0, 1):
                cc = c - dc
                if reserved[r][cc]:
                    continue
                try:
                    b = next(bit_iter)
                except StopIteration:
                    b = 0
                if mask(r, cc):
                    b ^= 1
                m[r][cc] = b
        c -= 2
        upward = not upward


def _place_format(m: List[List[int]], mask_idx: int) -> None:
    bits = _FORMAT_INFO_L[mask_idx]
    size = len(m)
    # 15 bits → positions split between (row 8) + (col 8)
    for i in range(15):
        b = (bits >> i) & 1
        # Around top-left
        if i < 6:
            m[8][i] = b
        elif i == 6:
            m[8][7] = b
        elif i == 7:
            m[8][8] = b
        elif i == 8:
            m[7][8] = b
        else:
            m[14 - i][8] = b
        # Around top-right + bottom-left
        if i < 8:
            m[size - 1 - i][8] = b
        else:
            m[8][size - 15 + i] = b
    m[size - 8][8] = 1   # always-dark module


def _score_mask(m: List[List[int]]) -> int:
    """Apply the four QR mask-penalty rules + return total score
    (lower = better)."""
    size = len(m)
    score = 0
    # Rule 1: runs of 5+ same-colour modules in a row/col
    for r in range(size):
        run = 1
        for c in range(1, size):
            if m[r][c] == m[r][c - 1]:
                run += 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            else:
                run = 1
    for c in range(size):
        run = 1
        for r in range(1, size):
            if m[r][c] == m[r - 1][c]:
                run += 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            else:
                run = 1
    # Rule 2: 2x2 blocks of same colour
    for r in range(size - 1):
        for c in range(size - 1):
            if (m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]):
                score += 3
    # Rules 3 + 4 omitted in the slim variant — score difference is
    # marginal for typical URLs and we get an honest layout either way.
    return score


def _encode(text: str) -> tuple[List[List[int]], int]:
    """Return (matrix, version) for the given text in byte mode at L."""
    data = text.encode("utf-8")
    version = _pick_version(len(data))
    data_codewords = _bitstream(data, version)
    full = _build_codewords(data_codewords, version)

    size = 17 + version * 4
    m = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    # Function patterns
    _place_finder(m, 0, 0)
    _place_finder(m, 0, size - 7)
    _place_finder(m, size - 7, 0)
    # Mark finder + separator + format areas as reserved
    for r in range(9):
        for c in range(9):
            reserved[r][c] = True
    for r in range(9):
        for c in range(size - 8, size):
            reserved[r][c] = True
    for r in range(size - 8, size):
        for c in range(9):
            reserved[r][c] = True
    if version >= 2:
        _place_alignment(m, version)
        for cr in _ALIGNMENT_CENTRES[version]:
            for cc in _ALIGNMENT_CENTRES[version]:
                if (cr, cc) in ((6, 6), (6, _ALIGNMENT_CENTRES[version][-1]),
                                 (_ALIGNMENT_CENTRES[version][-1], 6)):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        reserved[cr + dr][cc + dc] = True
    _place_timing(m)
    for i in range(8, size - 8):
        reserved[6][i] = True
        reserved[i][6] = True
    _reserve_format(reserved)
    # Always-dark module
    m[size - 8][8] = 1
    reserved[size - 8][8] = True

    # Try all 8 masks, keep the lowest-scoring
    best = None
    best_score = None
    for mi in range(8):
        candidate = [row[:] for row in m]
        _place_data(candidate, reserved, full, mi)
        _place_format(candidate, mi)
        s = _score_mask(candidate)
        if best_score is None or s < best_score:
            best = candidate
            best_score = s
    assert best is not None
    return best, version


# --------------------------------------------------------------------
# SVG output
# --------------------------------------------------------------------


def to_svg(text: str, scale: int = 8, border: int = 4) -> str:
    """Encode ``text`` and return an SVG string.

    Parameters
    ----------
    scale    : pixels per module (default 8 → ~200px QR for v3-4)
    border   : quiet-zone modules around the matrix (spec says ≥4)
    """
    matrix, _version = _encode(text)
    size = len(matrix)
    box = (size + border * 2) * scale
    # Build a single <path> with M / h sub-paths per run of black
    # modules — way smaller SVG than one <rect> per module.
    parts: List[str] = []
    for r in range(size):
        c = 0
        while c < size:
            if matrix[r][c] == 1:
                start = c
                while c < size and matrix[r][c] == 1:
                    c += 1
                x = (border + start) * scale
                y = (border + r) * scale
                w = (c - start) * scale
                parts.append(f"M{x} {y}h{w}v{scale}h-{w}z")
            else:
                c += 1
    path = "".join(parts) or "M0 0"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{box}" height="{box}" viewBox="0 0 {box} {box}" '
        f'shape-rendering="crispEdges">'
        f'<rect width="{box}" height="{box}" fill="#ffffff"/>'
        f'<path d="{path}" fill="#000000"/>'
        f'</svg>'
    )


__all__ = ["to_svg"]
