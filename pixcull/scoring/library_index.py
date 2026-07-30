"""v2.32-P0 — cross-run library index: search every shoot at once.

Per-run semantic search (``semantic_search.py``) answers "in THIS shoot,
where is the backlit hand-holding shot".  This module answers it across
the photographer's whole history — "in ANY of my shoots".

Design decisions, all measured (see docs/ROADMAP-v2.32-library-search-plan.md):

* **No ANN.**  Brute-force ``vectors @ q`` is 8ms at 100k photos and
  34.5ms at 1M — still only ~2x the 17.4ms CLIP text encoding that
  precedes it.  Memory is the wall that arrives first (1M photos =
  1.9GB), so compression (int8/PQ) is the eventual optimisation, not
  an ANN graph.  Keeping pure numpy also protects the zero-compiled-
  dependency ``pip install pixcull`` that v2.31 unblocked.
* **One merged ``vectors.npy`` opened with mmap**, not N per-run npz
  files loaded and stacked: measured 18ms vs 174ms to open at 100k
  photos, and mmap keeps them off the resident heap.
* **Rows are append-only and parallel**: ``manifest.jsonl`` line *i*
  describes ``vectors.npy`` row *i*.  Each entry carries its own ``row``
  as a redundant self-check.
* **Incremental by reusing each run's existing ``embeddings.npz``** —
  indexing is a copy, not a re-encode (re-encoding 100k photos would
  take hours).
* **Liveness is a first-class state.**  Shoots get deleted and external
  drives go offline.  A hit whose file is missing is reported as
  ``stale`` — the photographer needs to know "found it, but the file
  moved", which is very different from silently dropping the result.

The index lives in ``~/.pixcull/library/`` — never in the repo, never in
any sync path: it records real absolute paths, which are private data.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

logger = logging.getLogger(__name__)

SCHEMA = "pixcull.library_index/v1"
DIM = 512

# Default location. Overridable for tests + for users who keep their
# library on another volume.
LIBRARY_DIR = Path(
    os.environ.get("PIXCULL_LIBRARY_DIR",
                   str(Path.home() / ".pixcull" / "library"))
)


def _paths(library_dir: Path) -> tuple[Path, Path, Path]:
    """Legacy triple (``vectors.npy``, manifest, meta).

    Kept because ``prune``/``status`` and the tests still speak in these
    terms; ``vectors.npy`` is now only the *legacy* store — see
    :data:`_VEC_RAW` and :func:`_migrate_legacy_vectors`.
    """
    return (library_dir / "vectors.npy",
            library_dir / "manifest.jsonl",
            library_dir / "meta.json")


# v2.39 — vectors live in a HEADERLESS float32 file so appends are O(new)
# instead of O(library).
#
# The .npy store this replaces carries its shape in a header, so adding
# rows meant np.vstack of the whole array and rewriting the file.
# Measured, appending one 2,000-photo shoot:
#
#     library  50,000 photos (102 MB)  →  0.37s
#     library 150,000 photos (307 MB)  →  1.08s
#     library 300,000 photos (614 MB)  →  3.30s
#
# i.e. linear in everything already indexed, rewriting the entire library
# every time a shoot finishes — and with auto-index on (v2.34) that is
# after every cull.  A raw file appends in O(new bytes).
#
# The row count lives in meta.json, NOT in the vector file, and that is
# what makes the append crash-safe: bytes are appended and fsynced first,
# then the manifest, and meta.json is swapped in last by atomic rename.
# A crash at any point leaves a tail that no reader counts, because every
# reader takes its row count from meta.
_VEC_RAW = "vectors.f32"


def _raw_path(library_dir: Path) -> Path:
    return library_dir / _VEC_RAW


def _fsync(fh) -> None:
    fh.flush()
    os.fsync(fh.fileno())


def _write_meta(library_dir: Path, meta: dict) -> None:
    """Atomically publish meta.json — this is the commit point."""
    meta_path = library_dir / "meta.json"
    tmp = meta_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
        _fsync(fh)
    os.replace(tmp, meta_path)


def _migrate_legacy_vectors(library_dir: Path) -> Optional[int]:
    """One-shot ``vectors.npy`` → ``vectors.f32``.

    Returns the row count written, or None when there was nothing to
    migrate.  The legacy file is left in place: it costs disk but means a
    downgrade still finds a working library, and :func:`load_vectors`
    prefers the raw store once it exists.
    """
    vec_path, _, _ = _paths(library_dir)
    raw = _raw_path(library_dir)
    if raw.is_file() or not vec_path.is_file():
        return None
    try:
        old = np.load(vec_path, mmap_mode="r")
    except (OSError, ValueError) as exc:
        logger.warning("library: legacy vectors unreadable, not migrating: %s",
                       exc)
        return None
    arr = np.ascontiguousarray(np.asarray(old), dtype=np.float32)
    tmp = raw.with_suffix(".f32.tmp")
    with tmp.open("wb") as fh:
        fh.write(arr.tobytes())
        _fsync(fh)
    os.replace(tmp, raw)
    meta = read_meta(library_dir)
    meta.update({"schema": SCHEMA, "n_rows": int(arr.shape[0]),
                 "dim": int(arr.shape[1]), "store": _VEC_RAW})
    _write_meta(library_dir, meta)
    logger.info("library: migrated %d vectors to %s", arr.shape[0], _VEC_RAW)
    return int(arr.shape[0])


def _norm_rows(v: np.ndarray) -> np.ndarray:
    """L2-normalize rows; zero rows stay zero (never divide by 0)."""
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n == 0, 1.0, n)


def entry_key(run_id: str, filename: str, mtime: float) -> str:
    """Identity of an indexed photo.

    mtime is part of the key on purpose: a re-run (or an edited file)
    produces a different vector, so the old row must not be treated as
    still valid.  Rounded to whole seconds — filesystems disagree about
    sub-second precision across copies.
    """
    return f"{run_id}\x1f{filename}\x1f{int(mtime)}"


def load_manifest(library_dir: Path = LIBRARY_DIR) -> list[dict]:
    """Read manifest.jsonl. Returns [] when the library doesn't exist.

    Malformed lines are skipped rather than fatal — a half-written line
    from an interrupted append must not make the whole library
    unreadable.
    """
    _, man_path, _ = _paths(library_dir)
    if not man_path.is_file():
        return []
    out: list[dict] = []
    with man_path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("library manifest: skipping malformed line %d",
                               line_no + 1)
    return out


def load_vectors(library_dir: Path = LIBRARY_DIR,
                 mmap: bool = True) -> Optional[np.ndarray]:
    """Open the vector store (mmap by default — see module docstring).

    Prefers the append-only ``vectors.f32``; falls back to a legacy
    ``vectors.npy`` so an index built before v2.39 keeps working without
    a migration step.

    Only ``meta["n_rows"]`` rows are exposed.  Any bytes past that are an
    interrupted append and are deliberately invisible.
    """
    raw = _raw_path(library_dir)
    if raw.is_file():
        meta = read_meta(library_dir)
        dim = int(meta.get("dim") or DIM)
        try:
            on_disk = raw.stat().st_size // (4 * dim)
            n = int(meta.get("n_rows", on_disk))
            n = max(0, min(n, on_disk))     # never read past the file
            if n == 0:
                return np.zeros((0, dim), np.float32)
            mode = "r" if mmap else None
            arr = np.memmap(raw, dtype=np.float32, mode="r",
                            shape=(n, dim))
            return arr if mode else np.array(arr)
        except (OSError, ValueError) as exc:
            logger.warning("library vectors unreadable: %s", exc)
            return None

    vec_path, _, _ = _paths(library_dir)
    if not vec_path.is_file():
        return None
    try:
        return np.load(vec_path, mmap_mode="r" if mmap else None)
    except (OSError, ValueError) as exc:
        logger.warning("library vectors unreadable: %s", exc)
        return None


def read_meta(library_dir: Path = LIBRARY_DIR) -> dict:
    _, _, meta_path = _paths(library_dir)
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def append_run(
    run_id: str,
    entries: Iterable[tuple[str, str, float]],
    vectors: np.ndarray,
    *,
    library_dir: Path = LIBRARY_DIR,
    model: str = "",
) -> dict:
    """Append one run's photos to the library index.

    ``entries`` is ``[(filename, abs_path, mtime), ...]`` aligned with
    ``vectors`` rows.  Already-indexed entries (same run_id + filename +
    mtime) are skipped, so re-running this is idempotent and a re-scored
    run only re-indexes the photos that actually changed.

    Returns ``{"added": n, "skipped": n, "total": n}``.
    """
    vectors = np.asarray(vectors, dtype=np.float32)
    entries = list(entries)
    if vectors.ndim != 2 or vectors.shape[0] != len(entries):
        raise ValueError(
            f"vectors {vectors.shape} do not align with {len(entries)} entries")

    library_dir.mkdir(parents=True, exist_ok=True)
    vec_path, man_path, meta_path = _paths(library_dir)

    existing = load_manifest(library_dir)
    seen = {entry_key(e["run_id"], e["filename"], e.get("mtime", 0))
            for e in existing}

    keep_rows, keep_entries = [], []
    skipped = 0
    for i, (filename, abs_path, mtime) in enumerate(entries):
        if entry_key(run_id, filename, mtime) in seen:
            skipped += 1
            continue
        keep_rows.append(i)
        keep_entries.append((filename, abs_path, mtime))

    if not keep_rows:
        return {"added": 0, "skipped": skipped, "total": len(existing)}

    new_vecs = np.ascontiguousarray(_norm_rows(vectors[keep_rows]),
                                    dtype=np.float32)

    # Fold any pre-v2.39 vectors.npy into the raw store first, so the
    # append below has a single format to extend.
    _migrate_legacy_vectors(library_dir)

    raw = _raw_path(library_dir)
    old = load_vectors(library_dir, mmap=True)
    if old is not None and old.shape[0]:
        if old.shape[1] != new_vecs.shape[1]:
            raise ValueError(
                f"dimension mismatch: library has {old.shape[1]}, "
                f"incoming has {new_vecs.shape[1]}")
        base_row = int(old.shape[0])
    else:
        base_row = 0
    del old                       # drop the mmap before extending the file

    # ---- commit protocol -------------------------------------------
    # 1. append + fsync the vectors   (invisible: meta still says base_row)
    # 2. append + fsync the manifest  (still invisible for the same reason)
    # 3. atomically publish meta.json (the single commit point)
    #
    # Crash before 3 and every reader still sees exactly base_row rows —
    # load_vectors clamps to meta's n_rows, and search() further clamps to
    # the manifest length — so a torn tail is inert rather than corrupt.
    with raw.open("ab") as fh:
        fh.write(new_vecs.tobytes())
        _fsync(fh)

    now = time.time()
    with man_path.open("a", encoding="utf-8") as fh:
        for offset, (filename, abs_path, mtime) in enumerate(keep_entries):
            fh.write(json.dumps({
                "run_id": run_id,
                "filename": filename,
                "abs_path": str(abs_path),
                "mtime": float(mtime),
                "row": base_row + offset,
                "indexed_at": now,
            }, ensure_ascii=False) + "\n")
        _fsync(fh)

    total_rows = base_row + int(new_vecs.shape[0])
    _write_meta(library_dir, {
        "schema": SCHEMA,
        "model": model or read_meta(library_dir).get("model", ""),
        "dim": int(new_vecs.shape[1]),
        "n_rows": total_rows,
        "store": _VEC_RAW,
        "built_at": now,
    })
    return {"added": len(keep_rows), "skipped": skipped,
            "total": total_rows}


def search(
    query_vec: np.ndarray,
    *,
    k: int = 20,
    library_dir: Path = LIBRARY_DIR,
    check_liveness: bool = True,
) -> list[dict]:
    """Top-k across the whole library.

    Returns ``[{run_id, filename, abs_path, similarity, stale}, ...]``
    ranked by cosine similarity.  ``stale=True`` means the row is indexed
    but the file is not on disk right now (deleted, moved, or an external
    drive is offline) — reported, never silently dropped, because "found
    it but the file is gone" is information the user needs.
    """
    vecs = load_vectors(library_dir, mmap=True)
    manifest = load_manifest(library_dir)
    if vecs is None or not manifest or vecs.shape[0] == 0:
        return []

    n = min(vecs.shape[0], len(manifest))   # tolerate a torn tail
    q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    sims = np.asarray(vecs[:n]) @ q

    k = max(1, min(k, n))
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]

    out = []
    for row in top:
        e = manifest[int(row)]
        abs_path = e.get("abs_path", "")
        stale = (not Path(abs_path).is_file()) if check_liveness else False
        out.append({
            "run_id": e.get("run_id", ""),
            "filename": e.get("filename", ""),
            "abs_path": abs_path,
            "similarity": float(sims[int(row)]),
            "stale": bool(stale),
        })
    return out


def status(library_dir: Path = LIBRARY_DIR) -> dict:
    """Library health: size, run coverage, and how many rows went stale."""
    manifest = load_manifest(library_dir)
    vec_path, man_path, _ = _paths(library_dir)
    runs = sorted({e.get("run_id", "") for e in manifest})
    stale = sum(1 for e in manifest
                if not Path(e.get("abs_path", "")).is_file())
    disk = sum(p.stat().st_size
               for p in (_raw_path(library_dir), vec_path, man_path)
               if p.is_file())
    meta = read_meta(library_dir)
    return {
        "n_photos": len(manifest),
        "n_runs": len(runs),
        "runs": runs,
        "n_stale": stale,
        "disk_bytes": disk,
        "dim": meta.get("dim", DIM),
        "model": meta.get("model", ""),
        "library_dir": str(library_dir),
    }


def prune(library_dir: Path = LIBRARY_DIR,
          *, run_id: Optional[str] = None) -> dict:
    """Drop stale rows (missing files), or every row of one run.

    Rewrites both files together so rows stay parallel.  NOTE: pruning
    stale rows is destructive when a drive is merely offline — the CLI
    warns about that; a plain re-index restores them.
    """
    manifest = load_manifest(library_dir)
    vecs = load_vectors(library_dir, mmap=False)
    if not manifest or vecs is None:
        return {"removed": 0, "remaining": 0}

    n = min(len(manifest), vecs.shape[0])
    if run_id is not None:
        # drop one run wholesale (it was deleted / re-scored from scratch)
        keep = [i for i in range(n) if manifest[i].get("run_id") != run_id]
    else:
        # drop rows whose file is gone
        keep = [i for i in range(n)
                if Path(manifest[i].get("abs_path", "")).is_file()]
    removed = n - len(keep)
    if removed == 0:
        return {"removed": 0, "remaining": len(keep)}

    vec_path, man_path, _ = _paths(library_dir)
    dim = int(vecs.shape[1])
    new_vecs = np.ascontiguousarray(
        vecs[keep] if keep else np.zeros((0, dim), np.float32),
        dtype=np.float32)

    # Pruning is inherently a rewrite (rows move), so unlike append_run
    # this one still costs O(library) — but it is a rare, explicit,
    # user-invoked operation, not something every cull triggers.
    raw = _raw_path(library_dir)
    tmp_vec = raw.with_suffix(".f32.tmp")
    with tmp_vec.open("wb") as fh:
        fh.write(new_vecs.tobytes())
        _fsync(fh)
    os.replace(tmp_vec, raw)
    # A legacy store left over from before v2.39 would otherwise still be
    # there with the *unpruned* rows, and a downgrade would resurrect
    # exactly the entries the user asked to remove.
    vec_path.unlink(missing_ok=True)

    tmp_man = man_path.with_suffix(".jsonl.tmp")
    with tmp_man.open("w", encoding="utf-8") as fh:
        for new_row, i in enumerate(keep):
            e = dict(manifest[i])
            e["row"] = new_row
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        _fsync(fh)
    os.replace(tmp_man, man_path)

    meta = read_meta(library_dir)
    meta.update({"n_rows": len(keep), "dim": dim, "store": _VEC_RAW,
                 "built_at": time.time()})
    _write_meta(library_dir, meta)
    return {"removed": removed, "remaining": len(keep)}
