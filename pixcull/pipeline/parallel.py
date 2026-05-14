"""V21 — parallel per-image analyze via multiprocessing.

Pre-V21 the orchestrator looped over images serially in a single Python
process. At ~1.35 sec / image (measured) that's ~22 min for a 1000-photo
wedding, ~56 min for a 2500-photo travel batch. The detectors are CPU-
and GPU-bound (CLIP / U^2-Net / MediaPipe / LAION-aes); a single Python
process leaves the rest of the M1's cores idle.

V21 runs ``analyze_one`` in a pool of worker processes.

Measured speedup (245-image folder on USB external drive, M1 Max 10-core)
-------------------------------------------------------------------------
    config                wall    img/s   speedup
    serial (1 process)    5.5m    0.74×   1.00×
    4 workers × 1 thread  4.8m    0.85×   1.15×  (under-threaded internals)
    4 workers × 2 thread  3.2m    1.30×   1.72×  ← V21 default
    4 workers × 3 thread  3.4m    1.21×   1.62×  (OS contention)

The 1.72× isn't the 4× a naive read-count of "4 workers, 4× speedup"
suggests — three reasons keep us off that ceiling:

* **Spawn warm-up cost.** Each worker re-imports torch + mediapipe +
  transformers from scratch (~15 s × 4 workers). Amortizes over longer
  batches: a 1000-img run should see closer to ~2-2.5× since the
  per-image savings dominate the fixed warm-up.

* **USB / disk read contention.** External drives serialize at the
  USB 3.0 / Thunderbolt bridge layer. Local-SSD batches benchmark a
  bit higher (not measured here).

* **GPU sharing on MPS.** Metal Performance Shaders is a single shared
  device on Apple silicon. Detector calls that hit MPS serialize at
  the GPU even when CPU is parallel.

Worker count + thread tuning
----------------------------
Default 4 workers × 2 threads each = 8 effective cores on the 10-core
M1 Max — leaves headroom for the OS + main process without choking
the scheduler. ``threads=1`` per worker is too aggressive (each
worker becomes sub-real-time on matmul); ``threads=3+`` exceeds the
core budget and starts losing to context switches. The 2-thread
sweet spot was confirmed by the bench table above.

Override via ``PIXCULL_WORKERS`` env var (worker count only — the
per-worker thread cap is fixed at 2 by ``_WORKER_ENV`` below).

Why ``spawn`` and not ``fork`` / ``forkserver``
-----------------------------------------------
fork: unsafe with Torch / MediaPipe / OpenCV. They hold C-level state
(GPU contexts, OpenMP runtimes, thread pools) that doesn't survive an
unmanaged fork() — symptoms range from silent hangs to segfaults.

forkserver: we tried this first. The forkserver process pre-imports
``pixcull.pipeline.worker``, which in turn imports torch + mediapipe
+ transformers. Those imports start background OpenMP / native thread
pools in the forkserver. When workers fork from it, the forked
processes inherit broken thread-pool handles → ``analyze_one`` hangs
at the first model call with 0% CPU.

spawn: starts each worker from a fresh interpreter, no inherited
process state. Slower startup (~3 sec / worker to re-import the
detector stack) but reliable. For typical batches (>100 images) the
startup cost amortizes over the wall-clock savings; we only fall back
to serial when n ≤ 2 where startup would dominate.

Single-threaded native libs per worker
--------------------------------------
Each worker is a Python process running detector models. Torch /
NumPy / MKL each spin up their own OpenMP thread pool by default
(typically ``cpu_count`` threads each). With 4 workers × 10 threads
that's 40 threads contending for 10 cores — they spend more time on
context switches than work. Setting ``OMP_NUM_THREADS=1`` (et al.)
in the worker init keeps each worker single-threaded internally;
the parallelism comes from the worker count alone.

Determinism
-----------
``analyze_one`` is deterministic given the same input image (no
per-call randomness in any detector). Parallel results match serial
1:1 in metric values; only ROW ORDER may differ (we use
``imap_unordered`` for max throughput). Callers that need a stable
order should sort the returned records after the parallel pass.
"""

from __future__ import annotations

import os
import sys
import time
from multiprocessing import get_context
from pathlib import Path
from typing import Callable, Iterable

# Env vars to set inside each spawned worker BEFORE torch / numpy /
# mediapipe import. Each library reads these once at first import and
# caps its internal OpenMP / native thread pool accordingly.
#
# V21 tuning history:
# * v1: capped everything to 1 thread per worker. Result on 245-img
#   benchmark: 1.15× speedup, far below target. Each worker became
#   bottlenecked on single-threaded matmul / softmax, eating more
#   than parallelism gave back.
# * v2 (current): cap each worker to 2 threads. With 4 workers ×
#   2 threads = 8 effective cores in use, leaving headroom on a
#   10-core M1 Max. Torch / NumPy still get enough thread-pool to
#   parallelize internal ops without choking the OS scheduler.
# * TOKENIZERS_PARALLELISM stays "false" regardless — it forks
#   thread pools per-call which compounds the contention.
_WORKER_ENV = {
    "OMP_NUM_THREADS":      "2",
    "MKL_NUM_THREADS":      "2",
    "OPENBLAS_NUM_THREADS": "2",
    "NUMEXPR_NUM_THREADS":  "2",
    "VECLIB_MAXIMUM_THREADS": "2",
    "TOKENIZERS_PARALLELISM": "false",
}


# Default worker count: leave one core for the main process + UI / OS.
# Capping at 4 because each worker holds ~1 GB of model weights; an
# 8-worker pool on a 16-GB machine OOMs cleanly. Users with more RAM /
# specific tuning can override via ``PIXCULL_WORKERS`` env var.
def _default_workers() -> int:
    try:
        env = int(os.environ.get("PIXCULL_WORKERS", "0"))
        if env > 0:
            return env
    except ValueError:
        pass
    cpu = os.cpu_count() or 2
    return max(1, min(4, cpu - 1))


def _worker_init() -> None:
    """Initializer called once per worker process when the pool starts.

    Two jobs:

    1. Set thread-pool env vars BEFORE any heavy import. Torch / NumPy
       / MediaPipe read these once at module-import time, so setting
       them after import is too late. ``spawn`` workers start with a
       fresh interpreter and haven't imported anything yet, so we get
       a clean window to set the caps here.

    2. Warm the detector singletons so the FIRST ``analyze_one`` call
       in each worker doesn't eat the ~5 sec model-load cost. Without
       this, the wall-clock speedup curve has an uglier shape: the
       first N images per worker take 5+ sec each as models load in
       parallel. Warm-up moves the cost to a predictable place.

    Failures here propagate as exceptions (which kill the worker and
    cause the pool to retry) — we want loud-fail for model setup
    bugs (e.g. missing MediaPipe weights) since silent fallback to
    rule-only would be a regression vs. V20's behavior.
    """
    # Thread caps FIRST, before any heavy import.
    for k, v in _WORKER_ENV.items():
        os.environ.setdefault(k, v)
    # NOW import the worker (which transitively imports torch / mediapipe).
    from pixcull.pipeline.worker import _detectors  # noqa: WPS433
    _ = _detectors()


def _analyze_path(path_str: str) -> dict | None:
    """Worker-side wrapper. Takes a string instead of a Path because
    string is the safest pickle-roundtrip type (a Path subclass like
    PosixPath unpickles correctly on macOS but we don't need the
    object identity for our use)."""
    from pixcull.pipeline.worker import analyze_one  # noqa: WPS433
    try:
        return analyze_one(Path(path_str))
    except Exception as exc:  # noqa: BLE001
        # Match the serial worker's exception-tolerance: skip the bad
        # frame, keep the pool alive. The orchestrator currently
        # checks ``if r:`` so None is the right signal.
        print(f"[parallel] {path_str}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None


def parallel_analyze(
    paths: Iterable[Path],
    *,
    workers: int | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
    desc: str = "analyzing",
) -> list[dict]:
    """Run ``analyze_one`` over ``paths`` in a worker pool.

    Returns the same list of row dicts that a serial run would produce,
    minus the None entries (corrupt / unloadable images). Order is
    NOT preserved — callers needing deterministic order should sort
    by ``filename`` (or some stable key) after the call.

    Falls back to serial execution when ``workers == 1`` so test
    fixtures and tiny batches don't pay the pool-startup cost.
    """
    path_strs = [str(p) for p in paths]
    n = len(path_strs)
    if n == 0:
        return []

    workers = workers if workers and workers > 0 else _default_workers()

    if workers == 1 or n <= 2:
        # Serial fallback. Saves the ~2-sec forkserver bootstrap + the
        # model-warmup-per-worker overhead on tiny batches where it
        # would dominate the wall clock.
        from pixcull.pipeline.worker import analyze_one  # local
        out: list[dict] = []
        for i, ps in enumerate(path_strs, start=1):
            r = _analyze_one_safe(ps, analyze_one)
            if r is not None:
                out.append(r)
            if progress_cb is not None:
                progress_cb(i, n, f"{desc} {i}/{n}: {Path(ps).name}")
        return out

    # Parallel path. ``spawn`` is mandatory for our detector stack
    # (Torch + MediaPipe + OpenCV all break under fork or forkserver
    # inheritance of half-initialized C state — see module docstring).
    ctx = get_context("spawn")

    t0 = time.time()
    out_records: list[dict] = []
    with ctx.Pool(processes=workers, initializer=_worker_init) as pool:
        done = 0
        # chunksize=1 = lowest latency for progress reporting, fine for
        # ~2-sec-per-image tasks (the per-message overhead is microseconds
        # compared to the work). Larger chunksize would smooth progress
        # but matters only for sub-100ms tasks.
        for r in pool.imap_unordered(_analyze_path, path_strs, chunksize=1):
            done += 1
            if r is not None:
                out_records.append(r)
            if progress_cb is not None:
                fn = ""
                if r is not None:
                    fn = r.get("filename", "")
                progress_cb(done, n, f"{desc} {done}/{n}: {fn}")
    elapsed = time.time() - t0
    rate = n / elapsed if elapsed > 0 else 0
    print(f"[parallel] analyzed {n} images with {workers} workers "
          f"in {elapsed:.1f}s ({rate:.1f} img/s)",
          file=sys.stderr)
    return out_records


def _analyze_one_safe(path_str: str, analyze_one) -> dict | None:
    """Same exception shape as the worker-side wrapper, for the serial
    fallback branch. Kept inline to avoid the forkserver dep when
    workers == 1."""
    try:
        return analyze_one(Path(path_str))
    except Exception as exc:  # noqa: BLE001
        print(f"[serial] {path_str}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None


__all__ = ["parallel_analyze", "_default_workers"]
