"""v2.6-P1 — CLIP near-duplicate grouping (the deferred half of v2.4-P1-1).

Burst collapse folds *time-bucketed* clusters; this folds **visual**
near-duplicates regardless of capture time — the re-shot composition ten
minutes later, the second pass over the same scene.  Groups are connected
components over the pairwise cosine-similarity graph of the run's CLIP
image embeddings (the same ``embeddings.npz`` cache the semantic search
lazily builds), thresholded high enough that only true near-dups link.

Pure numpy + union-find; no model load here — callers hand in vectors.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

# Default similarity floor. CLIP ViT-B/32 cosine between two frames of
# the same composition is typically 0.93-0.99; distinct compositions of
# the same scene land 0.75-0.90. 0.92 keeps groups tight (precision over
# recall — wrongly folding two DIFFERENT photos is the costly error).
DEFAULT_THRESHOLD = 0.92


class _DSU:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def group_near_dups(
    filenames: Sequence[str],
    vectors: np.ndarray,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_group: int = 2,
    block: int = 1024,
) -> list[list[str]]:
    """Connected components of the cosine-similarity graph ≥ ``threshold``.

    ``vectors`` is ``[N, D]`` (L2-normalised or not — normalised here for
    safety).  Pairwise similarity is computed in ``block``-row chunks so a
    5k-photo run peaks at ~``block × N`` floats instead of ``N × N``.
    Returns groups of ``min_group``+ filenames, largest first; singletons
    are dropped (nothing to fold).
    """
    n = len(filenames)
    if n == 0 or vectors.shape[0] != n:
        return []
    v = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    v = v / np.where(norms == 0, 1.0, norms)

    dsu = _DSU(n)
    for start in range(0, n, block):
        stop = min(start + block, n)
        b = stop - start
        # v2.35 — compute the UPPER TRIANGLE only.  The previous version
        # did `v[block] @ v.T`, i.e. every pair twice, then threw half
        # away with an `if gi < c` test *after* paying for it.  Columns
        # below `start` were already covered when that earlier row-block
        # was scanned, so slicing them off halves both the matmul and —
        # this was the surprise — the mask scan.  Profiled at N=20,000:
        # matmul 1.35s, np.nonzero 1.15s, the Python union loop only
        # 0.01s (25k pairs).  np.nonzero costs nearly as much as the
        # matmul because it walks all N**2 booleans, so shrinking the
        # array matters as much as shrinking the multiply.
        sims = v[start:stop] @ v[start:].T            # [b, n-start]
        # Zero out the diagonal and below within the leading [b, b]
        # square (a view, so this edits sims in place). -2 can never
        # clear a cosine threshold.
        sims[:, :b][np.tril_indices(b)] = -2.0
        rows, cols = np.nonzero(sims >= threshold)
        for r, c in zip(rows, cols):
            dsu.union(start + int(r), start + int(c))

    groups: dict[int, list[str]] = {}
    for i in range(n):
        groups.setdefault(dsu.find(i), []).append(str(filenames[i]))
    out = [g for g in groups.values() if len(g) >= min_group]
    out.sort(key=len, reverse=True)
    return out


def pick_heroes(
    groups: Sequence[Sequence[str]],
    scores: dict[str, float] | None = None,
) -> list[dict]:
    """Attach the keep-worthy representative per group.

    Hero = highest ``score_final`` (ties / missing scores → first member,
    which preserves the run's existing sort).  Returns
    ``[{"hero": fn, "members": [fn, ...]}, ...]``.
    """
    scores = scores or {}
    out = []
    for g in groups:
        hero = max(g, key=lambda fn: (scores.get(fn) or 0.0))
        out.append({"hero": hero, "members": list(g)})
    return out


def group_cross_shoot(
    shoots: Sequence[tuple[str, Sequence[str], np.ndarray]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_shoots: int = 2,
    block: int = 1024,
) -> list[list[tuple[str, str]]]:
    """v2.7 — visual near-duplicates that recur ACROSS shoots.

    ``shoots`` is ``[(shoot_id, filenames, vectors), ...]`` — one entry per
    run/folder, ``vectors`` shaped ``[N_i, D]``.  Every photo is stacked into
    one global index space and grouped by the same connected-components rule
    as :func:`group_near_dups`; then only groups whose members span
    ``>= min_shoots`` DISTINCT shoots are kept — i.e. the same frame the
    photographer re-delivered across sessions (single-shoot dups are already
    handled by :func:`group_near_dups`).  Each member is ``(shoot_id,
    filename)``; groups largest first.
    """
    keys: list[tuple[str, str]] = []
    mats: list[np.ndarray] = []
    for sid, fns, vecs in shoots:
        vecs = np.asarray(vecs, dtype=np.float32)
        if vecs.ndim != 2 or vecs.shape[0] != len(fns):
            continue                              # skip malformed shoot
        keys.extend((str(sid), str(fn)) for fn in fns)
        mats.append(vecs)
    if not keys:
        return []
    vectors = np.vstack(mats)
    # Reuse the single-run grouping over a synthetic global index, then map
    # the index strings back to (shoot_id, filename).
    idx_groups = group_near_dups(
        [str(i) for i in range(len(keys))], vectors,
        threshold=threshold, min_group=2, block=block)
    out: list[list[tuple[str, str]]] = []
    for g in idx_groups:
        members = [keys[int(i)] for i in g]
        if len({sid for sid, _ in members}) >= min_shoots:
            out.append(members)
    out.sort(key=len, reverse=True)
    return out


def pick_cross_shoot_heroes(
    groups: Sequence[Sequence[tuple[str, str]]],
    scores: dict[tuple[str, str], float] | None = None,
) -> list[dict]:
    """Per cross-shoot group: hero = highest ``score_final`` (``scores`` keyed
    by ``(shoot_id, filename)``; ties / missing → first member).  The other
    members are the cross-shoot duplicates safe to cull.  Returns
    ``[{"hero": (sid, fn), "members": [...], "duplicates": [...]}, ...]``.
    """
    scores = scores or {}
    out = []
    for g in groups:
        hero = max(g, key=lambda k: (scores.get(k) or 0.0))
        out.append({
            "hero": hero,
            "members": list(g),
            "duplicates": [m for m in g if m != hero],
        })
    return out


# ---------------------------------------------------------------------------
# v3.14 — a tighter crop is not a duplicate
# ---------------------------------------------------------------------------
#
# `group_near_dups` collapses on CLIP cosine alone. CLIP is largely
# invariant to framing — that is what makes it good at "same subject" and
# what makes it unable to tell the same frame twice from a deliberate
# reframe of it. A 16:9 crop of a 3:2 original is a decision the
# photographer made, and collapsing it into the original hides one of the
# two things they wanted to compare.
#
# THIS IS PIXCULL'S OWN HYPOTHESIS. The fact-check on the competitive
# research confirmed only Aftershoot's headline claim of tighter
# duplicate detection; the mechanism behind it was not confirmed and this
# is not a reimplementation of it. Off unless PIXCULL_ASPECT_GUARD=1
# until the measurement below has run.
#
# MEASURE: on a set containing known intentional crop variants, how many
# survive grouping with the guard on versus off.

#: Relative difference in aspect ratio above which two frames are treated
#: as differently framed rather than as the same frame twice.
#:
#: 6% is chosen to sit well below any real reframe and well above noise.
#: 3:2 (1.500) against 16:9 (1.778) is 18.5%; 3:2 against 4:3 (1.333) is
#: 11%. A few pixels of lens-correction crop is under 1%.
ASPECT_TOL = 0.06

ASPECT_ENV = "PIXCULL_ASPECT_GUARD"


def aspect_guard_enabled() -> bool:
    import os
    return os.environ.get(ASPECT_ENV, "0") == "1"


#: EXIF orientation values that mean the frame is stored rotated a
#: quarter turn, so its stored width is its displayed height.
_QUARTER_TURN = frozenset({5, 6, 7, 8})


def aspect_of(path) -> float | None:
    """Displayed width / height from the image header, or None.

    ORIENTATION MATTERS HERE AND ALMOST BROKE THIS. A portrait frame from
    most cameras is stored landscape with an EXIF orientation tag, so raw
    `im.size` reports 3:2 for a photograph the photographer sees as 2:3.
    Compared against a true landscape frame that is a 125% difference —
    the guard would have split every portrait frame away from its own
    duplicates and called it a reframe.

    The orientation tag is read and the dimensions swapped, rather than
    running `ImageOps.exif_transpose`: that decodes the pixels, and this
    function wants a ratio, not an image. Registered in the repo-wide
    orientation guard with that reason.

    Header only — PIL does not decode for `.size` or `.getexif()` — so
    this is cheap enough to run over the members of a group. None on any
    failure: a frame whose dimensions cannot be read must not be split
    away from its group on a guess.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            try:
                orientation = int(im.getexif().get(0x0112) or 1)
            except Exception:  # noqa: BLE001
                orientation = 1
        if orientation in _QUARTER_TURN:
            w, h = h, w
        return (float(w) / float(h)) if h else None
    except Exception:  # noqa: BLE001
        return None


def split_by_aspect(groups, aspect_by_fn: dict, *,
                    tol: float = ASPECT_TOL) -> list[list[str]]:
    """Split each group into runs of similar aspect ratio.

    Members whose aspect is unknown stay with the FIRST subgroup rather
    than forming an "unknown" one of their own: an unreadable header is
    missing information, not evidence of a different framing, and
    inventing a group out of it would be worse than the collapse this
    guards against.

    Subgroups of one are dropped, matching `group_near_dups` — a group of
    one is not a duplicate group. So a pair that splits cleanly into two
    differently-framed singletons disappears from the near-dup list
    entirely, which is the correct outcome: they were never duplicates.
    """
    out: list[list[str]] = []
    for group in groups:
        buckets: list[tuple[float, list[str]]] = []
        unknown: list[str] = []
        for fn in group:
            a = aspect_by_fn.get(fn)
            if a is None or a <= 0:
                unknown.append(fn)
                continue
            for ref, members in buckets:
                if abs(a - ref) / ref <= tol:
                    members.append(fn)
                    break
            else:
                buckets.append((a, [fn]))
        if unknown:
            if buckets:
                buckets[0][1].extend(unknown)
            else:
                buckets.append((0.0, unknown))
        for _, members in buckets:
            if len(members) >= 2:
                out.append(members)
    out.sort(key=len, reverse=True)
    return out
