"""v3.16 — stop re-running yesterday's detectors.

`orchestrator.py`'s own module docstring has said since V0.1 that "V0.3
will add multi-process workers and incremental runs via the cache layer".
The workers shipped in `parallel.py`. The cache layer did not. Grepping
the analysis path for a content hash, a skip, a fingerprint or a stamp
returns nothing, so re-running a folder re-executes CLIP, DINOv2,
MediaPipe, the aesthetic head and segmentation on every frame that has
not changed — which, on a re-run, is all of them.

WHY THE KEY IS THE FILE'S CONTENT

Path and mtime are the cheap answer and the wrong one. A stale row
returned for an edited file is worse than a slow run: it is a verdict
about a photograph that no longer exists, delivered with no sign that
anything is wrong. `touch -r` is enough to defeat mtime, and photographers
rename and re-export constantly, which defeats path.

Content keying also buys the thing that makes this worth having: the same
photograph analysed in a different folder, or in a second run directory,
is a hit. That is the actual re-run.

The hash function is `m3._content_hash`, imported rather than
reimplemented. Two hash implementations in one repository is a bug
waiting for one of them to be improved.

DETECTOR_VERSION IS PART OF THE KEY

A detector change must invalidate, the way `PROMPT_VERSION` invalidates
the verdict cache. Without it, editing a threshold in `blur.py` would
leave every cached row in place and the change would appear to do
nothing — the most confusing possible failure.

ONE FILE PER ENTRY, NOT ONE JSONL

A row carries a 768-d DINOv2 vector, a 512-d CLIP vector and a face
embedding per face — roughly 25 KB of JSON. A single append-only log
would mean parsing 125 MB to answer 5,000 point lookups. Entries live in
their own files, sharded by the first two hex characters, so a lookup
reads exactly one of them and a worker process needs no shared index and
no lock.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

#: Bump when a detector's OUTPUT changes for the same input. This is the
#: analogue of `m3.PROMPT_VERSION` and it has the same failure mode when
#: forgotten: a code change that appears to do nothing.
DETECTOR_VERSION = "v3.16.0"

ENV_FLAG = "PIXCULL_DETECTOR_CACHE"

#: Keys copied from the current file over a cached row.
#:
#: The point of content keying is that the same photograph in a different
#: folder is a hit — and then the row must describe THIS file, not the
#: one that happened to be analysed first. Returning the old path would
#: send every downstream consumer, including the thumbnailer and the
#: exporter, at a file that may not exist.
_PATH_KEYS = ("path", "filename")


def enabled() -> bool:
    """On by default.

    Unlike the other switches added in this block, this one changes no
    verdict: a hit returns the row the detectors would have produced. The
    risk it carries is staleness, and the content key is what answers
    that. `PIXCULL_DETECTOR_CACHE=0` turns it off.
    """
    return os.environ.get(ENV_FLAG, "1") != "0"


def cache_dir() -> Path:
    override = os.environ.get("PIXCULL_DETECTOR_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".pixcull" / "cache" / "detectors"


def key_for(path: Path | str) -> str | None:
    """Content hash of the file plus the detector version, or None."""
    from pixcull.scoring.m3 import _content_hash
    try:
        return _content_hash(Path(path), DETECTOR_VERSION)
    except OSError:
        return None


def _entry_path(key: str) -> Path:
    return cache_dir() / key[:2] / f"{key}.json"


#: Marker for a numpy array inside a cached row.
#:
#: Storing vectors as plain lists is the obvious thing and it is wrong in
#: a way nothing would have reported. `orchestrator.py` builds the CLIP
#: embeddings file with `if emb is None or not hasattr(emb, "shape"):
#: continue` — a list has no `.shape`, so every warm-run photograph would
#: have been dropped from semantic search and the library index, silently,
#: while the run itself looked perfect.
_ND = "__ndarray__"


def _encode(value):
    """Row values -> JSON, preserving which ones were numpy arrays."""
    try:
        import numpy as np
    except ImportError:
        return value
    if isinstance(value, np.ndarray):
        return {_ND: value.tolist(), "dtype": str(value.dtype)}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value):
    """The inverse. An array comes back an array, dtype included."""
    if isinstance(value, dict):
        if _ND in value:
            import numpy as np
            return np.asarray(value[_ND],
                              dtype=value.get("dtype") or None)
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def get(key: str, path: Path | str) -> dict | None:
    """A cached row for this key, re-pointed at ``path``.

    Any read failure is a miss. A cache that raises is worse than no
    cache, because the run it kills produced nothing.
    """
    try:
        raw = _entry_path(key).read_text(encoding="utf-8")
        row = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict):
        return None
    row = _decode(row)
    p = Path(path)
    row["path"] = str(p)
    row["filename"] = p.name
    # A hit cost no wall-clock. Leaving the original timing in would make
    # every performance report of a warm run a report of a cold one.
    row["elapsed_s"] = 0.0
    return row


def put(key: str, row: dict[str, Any]) -> bool:
    """Store one row. Returns whether it was written.

    Written to a temporary file and renamed, so a run killed mid-write
    leaves no half-entry that would later be read as a valid row.
    """
    if not isinstance(row, dict):
        return False
    dest = _entry_path(key)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = _encode(row)
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except (OSError, TypeError, ValueError):
        # TypeError/ValueError: a row carrying something json cannot
        # serialise. Not fatal — the frame was analysed, it just will not
        # be cached, and a run that dies over its own cache is worse.
        return False


def analyze_one_cached(path: Path, analyze) -> dict | None:
    """``analyze`` with a content-keyed cache in front of it."""
    if not enabled():
        return analyze(path)
    key = key_for(path)
    if key is None:
        return analyze(path)
    hit = get(key, path)
    if hit is not None:
        return hit
    row = analyze(path)
    if row is not None:
        put(key, row)
    return row
