"""v2.7 — duplicate / near-static frame trimming for on-device video.

A locked-off tripod shot, a paused subject, or a re-export with dropped
motion leaves long runs of near-identical frames. We perceptual-hash each
frame (dHash) and walk consecutive frames: a run whose neighbour-to-neighbour
Hamming distance stays small is a near-static stretch that collapses to one
representative frame — the rest are trim candidates.

Pure-python hashing + run detection (no numpy needed); PIL is imported lazily
only for the optional image→hash helper, so the run/plan logic stays trivially
unit-testable on synthetic hash sequences.
"""

from __future__ import annotations

from typing import Sequence

# Hamming distance over a 64-bit dHash. Two frames of a static shot land
# 0-4; a slow pan neighbour ~5-12; a cut jumps 20+. 6 keeps "near-static"
# tight (we'd rather keep a frame than silently drop real motion).
DEFAULT_MAX_DISTANCE = 6
DEFAULT_MIN_RUN = 2


def dhash(image, hash_size: int = 8) -> int:
    """64-bit difference hash of a PIL image (or a path/file).

    Resizes to ``(hash_size+1, hash_size)`` grayscale and emits one bit per
    adjacent-column comparison (left brighter than right).  Robust to scale,
    light compression and small exposure shifts — what we want for "is this
    the same frame".
    """
    from PIL import Image

    if not hasattr(image, "convert"):
        image = Image.open(image)
    img = image.convert("L").resize((hash_size + 1, hash_size))
    px = list(img.tobytes())   # L mode → one 0-255 byte per pixel, row-major
    w = hash_size + 1
    bits = 0
    for r in range(hash_size):
        row = r * w
        for c in range(hash_size):
            bits = (bits << 1) | (1 if px[row + c] > px[row + c + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    """Bit difference between two hashes."""
    return bin(a ^ b).count("1")


def find_duplicate_runs(
    hashes: Sequence[int],
    *,
    max_distance: int = DEFAULT_MAX_DISTANCE,
    min_run: int = DEFAULT_MIN_RUN,
) -> list[tuple[int, int]]:
    """Inclusive index ranges ``[start, end]`` of consecutive frames whose
    neighbour-to-neighbour dHash Hamming distance stays ``<= max_distance`` —
    i.e. near-static runs of ``>= min_run`` frames.  Non-overlapping, in
    capture order.
    """
    n = len(hashes)
    runs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and hamming(hashes[j], hashes[j + 1]) <= max_distance:
            j += 1
        if j - i + 1 >= min_run:
            runs.append((i, j))
        i = j + 1
    return runs


def trim_plan(
    frame_ids: Sequence[str],
    hashes: Sequence[int],
    *,
    max_distance: int = DEFAULT_MAX_DISTANCE,
    min_run: int = DEFAULT_MIN_RUN,
    keep: str = "first",
) -> dict:
    """Collapse near-static runs to one representative each.

    ``keep`` ∈ {``first``, ``middle``, ``last``} picks the kept frame per run.
    Returns ``{"runs": [{"start","end","keep","drop":[ids]}],
    "keep_ids": [...], "drop_ids": [...]}``.  A mismatched input length is a
    no-op (keep everything) rather than an error.
    """
    if len(frame_ids) != len(hashes):
        return {"runs": [], "keep_ids": list(frame_ids), "drop_ids": []}
    runs = find_duplicate_runs(hashes, max_distance=max_distance, min_run=min_run)
    drop: set[int] = set()
    detail = []
    for (s, e) in runs:
        if keep == "last":
            rep = e
        elif keep == "middle":
            rep = (s + e) // 2
        else:
            rep = s
        for k in range(s, e + 1):
            if k != rep:
                drop.add(k)
        detail.append({
            "start": s, "end": e, "keep": frame_ids[rep],
            "drop": [frame_ids[k] for k in range(s, e + 1) if k != rep],
        })
    keep_ids = [fid for k, fid in enumerate(frame_ids) if k not in drop]
    drop_ids = [frame_ids[k] for k in sorted(drop)]
    return {"runs": detail, "keep_ids": keep_ids, "drop_ids": drop_ids}
