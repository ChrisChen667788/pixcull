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
    return (library_dir / "vectors.npy",
            library_dir / "manifest.jsonl",
            library_dir / "meta.json")


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
    """Open vectors.npy (mmap by default — see module docstring)."""
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

    new_vecs = _norm_rows(vectors[keep_rows])
    old = load_vectors(library_dir, mmap=True)
    if old is not None and old.shape[0]:
        if old.shape[1] != new_vecs.shape[1]:
            raise ValueError(
                f"dimension mismatch: library has {old.shape[1]}, "
                f"incoming has {new_vecs.shape[1]}")
        merged = np.vstack([np.asarray(old), new_vecs])
    else:
        merged = new_vecs

    # Atomic: write temp then rename, so an interrupted append can never
    # leave vectors.npy and manifest.jsonl disagreeing about row count.
    # NB: np.save() APPENDS ".npy" to a target that doesn't already end in
    # it, so writing to "vectors.npy.tmp" would silently land at
    # "vectors.npy.tmp.npy" and the rename below would FileNotFound.
    # Same trap semantic_search.py documents; write through a handle.
    tmp_vec = vec_path.with_suffix(".npy.tmp")
    with tmp_vec.open("wb") as fh:
        np.save(fh, merged)
    os.replace(tmp_vec, vec_path)

    base_row = len(existing)
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

    meta_path.write_text(json.dumps({
        "schema": SCHEMA,
        "model": model or read_meta(library_dir).get("model", ""),
        "dim": int(merged.shape[1]),
        "n_rows": int(merged.shape[0]),
        "built_at": now,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"added": len(keep_rows), "skipped": skipped,
            "total": int(merged.shape[0])}


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
    disk = sum(p.stat().st_size for p in (vec_path, man_path) if p.is_file())
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

    vec_path, man_path, meta_path = _paths(library_dir)
    new_vecs = vecs[keep] if keep else np.zeros((0, vecs.shape[1]), np.float32)
    tmp_vec = vec_path.with_suffix(".npy.tmp")
    with tmp_vec.open("wb") as fh:      # see append_run: np.save appends .npy
        np.save(fh, new_vecs)
    os.replace(tmp_vec, vec_path)

    tmp_man = man_path.with_suffix(".jsonl.tmp")
    with tmp_man.open("w", encoding="utf-8") as fh:
        for new_row, i in enumerate(keep):
            e = dict(manifest[i])
            e["row"] = new_row
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp_man, man_path)

    meta = read_meta(library_dir)
    meta.update({"n_rows": len(keep), "built_at": time.time()})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return {"removed": removed, "remaining": len(keep)}
