# The incremental cache, measured — v3.16

`orchestrator.py`'s module docstring has said since the first commit that "V0.3
will add multi-process workers and incremental runs via the cache layer". The
workers shipped in `parallel.py`. The cache layer did not.

## The first measurement was wrong, and how

Cold and warm were first run in **one process**, back to back. That reported a
3.0× speed-up. It was measuring model warm-up: the detector singletons load on
first use, and the second call inherited them. Zero cache entries had been
written at all — every `put` was failing on a `TypeError`, because the row
carries numpy vectors and `json.dump` will not serialise them, and `put` returns
False rather than raising.

So the number looked like a result, was produced by the thing under test, and
was entirely an artefact of the harness. It is recorded here because the same
shape — a plausible figure from a measurement that never ran — is what v3.1,
v3.2 and v3.6 in this same block exist to prevent.

## The measurement

Separate processes, detectors warmed on one frame before the clock starts, 24
synthetic frames (53 KB each) on an M1 Max, `workers=1`:

| run | wall clock | cache hits |
|---|---|---|
| cold (empty cache) | **16.41 s** | 1 of 24 |
| warm (new process) | **0.01 s** | 24 of 24 |

0.68 s per frame of detector work, against a warm path that is a content hash
and a JSON read.

**Synthetic frames, and that is fine for this number.** What the cache skips is
detector execution, which does not care whether the pixels came from a camera.
What synthetic frames *cannot* tell you is the warm-path cost on real files,
because that cost is the content hash and the hash is O(bytes).

## The warm path costs one hash per file

Measured on this machine: **1,549 MB/s** for `_content_hash` (32 MB in 21 ms).

So for a 2,000-frame shoot of 40 MB RAWs, the warm path is roughly **52 s of
hashing** against a cold run of about 2,700 s at the V21 figure of ~1.35 s per
frame. That is a projection from two measured constants, not a measurement —
there are no RAW files on this machine to run it against.

The hash is not negotiable. Path and mtime are the cheap key and the wrong one:
`touch -r` restores an mtime, photographers rename and re-export constantly, and
a stale row returned for an edited file is a verdict about a photograph that no
longer exists, delivered with nothing saying anything is wrong.

## What nearly shipped instead

Storing the vectors as plain JSON lists. `orchestrator.py` builds the CLIP
embeddings file with:

```python
if emb is None or not hasattr(emb, "shape"):
    continue
```

A list has no `.shape`. Every warm-run photograph would have been dropped out of
semantic search and the library index, silently, while the run itself looked
perfect and finished in a tenth of the time. Arrays now round-trip as arrays,
dtype included, and a test asserts `.shape` survives.

## Re-running it

```
PIXCULL_DETECTOR_CACHE_DIR=<tmp> python -c "…parallel_analyze(paths, workers=1)…"
```

`PIXCULL_DETECTOR_CACHE=0` disables the cache entirely. `DETECTOR_VERSION` in
`pixcull/pipeline/detector_cache.py` must be bumped whenever a detector's output
changes for the same input — it is part of the key, for the same reason
`PROMPT_VERSION` is part of the verdict cache key, and forgetting it produces the
most confusing failure available: a code change that appears to do nothing.
