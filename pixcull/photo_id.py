"""v2.76 — a photograph's name has to be unique, or it is not a name.

v2.75 measured the damage: every map from a photo to its bytes in this
product is keyed on the basename — `manifest.json`, `/thumb/<run>/<fn>`,
`data-fn`, the annotation index, `library index` — and on a recursively
scanned folder 738 names were used by more than one file, leaving 774
photographs with a card that displayed a DIFFERENT photograph.

The fix is not a new identifier threaded through 81 front-end call sites
and 239 server references. It is to make the existing one true: give
colliding files a name that distinguishes them, and everything
downstream keeps working because nothing downstream changes.

Two properties matter more than elegance:

**Stable.** The disambiguated name must not depend on scan order, or
re-scanning the same folder renames photographs and the photographer's
annotations — keyed by name — attach to the wrong frames. So the
suffixing scheme is not `a.jpg` / `a (2).jpg`; it is the file's own
position on disk, which does not move when the scanner's order does.

**Symmetric.** Of two files called `a.jpg`, neither keeps the bare name.
If one did, which one is decided by scan order, and the instability
comes back through the side door.

**Narrow.** A run with no collisions is bit-identical to before. The
overwhelming majority of shoots are one folder of uniquely-named
exports, and they must not pay for this.
"""

from __future__ import annotations

import os
from collections import defaultdict


def _common_root(paths: list[str]) -> str:
    real = [p for p in paths if p]
    if not real:
        return ""
    try:
        root = os.path.commonpath(real)
    except ValueError:          # different drives, or a mix of rel/abs
        return ""
    return root if os.path.isdir(root) or len(real) > 1 else os.path.dirname(root)


def _rel(path: str, root: str) -> str:
    if not path:
        return ""
    try:
        rel = os.path.relpath(path, root) if root else path
    except ValueError:
        rel = path
    return rel.replace(os.sep, "/").lstrip("./")


def unique_names(items: list[tuple[str, str]]) -> dict[int, str]:
    """``items`` is [(filename, path), ...] in row order.

    Returns {row index: name}. A name that only one path claims is
    returned unchanged; a name several paths claim becomes each path's
    location relative to the run's common root.
    """
    by_name: dict[str, set] = defaultdict(set)
    for name, path in items:
        if name:
            by_name[name].add(path or "")
    collided = {n for n, ps in by_name.items() if len(ps) > 1}
    if not collided:
        return {i: n for i, (n, _p) in enumerate(items)}

    root = _common_root([p for _n, p in items])
    out: dict[int, str] = {}
    used: dict[str, int] = {}
    for i, (name, path) in enumerate(items):
        if name not in collided:
            out[i] = name
            continue
        cand = _rel(path, root) or name
        # Two different files can still land on the same relative name
        # when a path is missing entirely. Last resort, and it IS
        # order-dependent — which is why it is last, and why it is
        # counted rather than hidden.
        if cand in used:
            used[cand] += 1
            cand = f"{cand}#{used[cand]}"
        else:
            used[cand] = 1
        out[i] = cand
    return out


def apply_unique_names(rows: list[dict], *, name_key: str = "filename",
                       path_key: str = "path",
                       keep_original_as: str = "orig_filename") -> int:
    """Rewrite colliding names in place. Returns how many were changed.

    The original basename is preserved under ``keep_original_as`` — it is
    what an XMP sidecar has to be written next to, and what a
    photographer recognises. It is stamped ONLY on rows that actually
    changed: a run with no colliding names has to come out byte-identical,
    or every collision-free library silently grows a column the moment
    this ships.
    """
    items = [(str(r.get(name_key) or ""), str(r.get(path_key) or ""))
             for r in rows]
    names = unique_names(items)
    changed = 0
    for i, r in enumerate(rows):
        new = names.get(i)
        if new and new != r.get(name_key):
            r[keep_original_as] = r.get(name_key)
            r[name_key] = new
            changed += 1
    return changed


def migrate_legacy_annotations(
    index: dict[str, dict],
    rows: list[dict],
    manifest: dict[str, str] | None,
    *,
    name_key: str = "filename",
    orig_key: str = "orig_filename",
    path_key: str = "path",
) -> tuple[dict[str, dict], int, int]:
    """Re-key annotations written before names were disambiguated.

    Returns ``(index, migrated, dropped)``.

    Annotations are saved under whatever name the card showed. Before
    v2.76 that was the bare basename, so an annotation on a colliding
    name does not say *which* of the files it describes — the question
    is genuinely ambiguous and guessing would attach a human's keep/cull
    verdict to a photograph they never saw.

    It is, however, exactly recoverable. The old resolver displayed
    whichever path won ``manifest.json`` — one entry per basename — so
    that entry names the file the person actually looked at. Rows whose
    path matches inherit the annotation; the rest are left alone.

    Without a manifest nothing is attributable, and the count comes back
    as ``dropped`` rather than being quietly spread over every copy.
    """
    renamed = [r for r in rows if r.get(orig_key) and r.get(orig_key) != r.get(name_key)]
    if not renamed:
        return index, 0, 0

    out = dict(index)
    migrated = 0
    claimed: set[str] = set()
    for r in renamed:
        legacy = str(r.get(orig_key) or "")
        if legacy not in index or str(r.get(name_key) or "") in index:
            continue
        winner = (manifest or {}).get(legacy)
        if winner and str(r.get(path_key) or "") == str(winner):
            out[str(r[name_key])] = index[legacy]
            claimed.add(legacy)
            migrated += 1

    orphaned = {str(r.get(orig_key) or "") for r in renamed} & set(index)
    dropped = len(orphaned - claimed)
    for legacy in claimed:
        out.pop(legacy, None)
    return out, migrated, dropped
