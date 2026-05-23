"""Web demo for PixCull: upload images → auto detect / sort / score.

This is the V1.2 user-facing demo. It complements ``scripts/serve_review.py``
(which compares pipeline output against a labeled golden set) by letting a
user drop in a *fresh* batch of images they've never labeled and see the
pipeline's keep / maybe / cull verdict in their browser.

Architecture (single-file, stdlib http.server only):

  GET    /                  upload page (HTML + drag-drop input)
  POST   /analyze           multipart upload of N images → returns {run_id}
                            (background thread starts the pipeline)
  POST   /scan_local        analyze a local folder *in place* (no copy)
                            body: {folder: "/path/to/photos"} → {run_id, n}
                            For users with GB-scale RAW collections: only
                            scores.csv / thumbs / XMP land in /tmp; the
                            originals stay where they live.
  POST   /browse            list a server-side directory (file picker UX)
                            body: {path?: str} → {entries, parent}
  GET    /status/<run_id>   JSON {state, done, total, message}
  GET    /results/<run_id>  rendered HTML grid of decisions for that run
  POST   /export/<run_id>   write XMP sidecars
                            body: {target?: "tmp"|"alongside"} (V1.2)
                            'alongside' (scan mode only) writes next to the
                            originals where Lightroom expects them
  GET    /xmp_zip/<run_id>  download all sidecars as a single .zip
  GET    /thumb/<run_id>/<filename>  thumbnail (lazy-built, cached on disk)
  GET    /full/<run_id>/<filename>   full-size preview
  GET    /runs              admin: list every run with size + age + decisions
  GET    /storage_info      admin: total disk usage + model cache breakdown
  DELETE /runs/<run_id>     admin: remove one run's input + output dir
                            (scan-mode runs ONLY touch /tmp output;
                             originals are never deleted)
  POST   /runs/cleanup      admin: bulk delete by policy
                            JSON body: {older_than_hours?: int, keep_last?: int}

Why a separate file from serve_review.py:

  - serve_review needs ground_truth.csv to exist; demo uploads have no GT
  - The demo flow has an extra "uploading → analyzing → done" lifecycle
    that doesn't apply to the static review viewer
  - Keeping the review viewer untouched preserves its label-collection role

Reuses from the project: pixcull.pipeline.orchestrator.run_pipeline (with
its progress_cb hook), pixcull.io.loader.load_image (for thumbnail decode),
pixcull.io.xmp.write_xmp + decision_to_xmp (for the LR/C1 export).

Defaults:
  --host 127.0.0.1   localhost only (safe; LAN exposure must be opt-in)
  --rescorer-mode off  works on machines without a trained rescorer.

LAN sharing: ``--host 0.0.0.0`` opens the port to your LAN. The CLI
prints both ``127.0.0.1`` and the machine's first non-loopback v4 IP
so you (or someone on your wifi) can hit it from a phone or laptop.
File uploads up to 200 MB; no auth — only run on networks you trust.
"""

from __future__ import annotations

import argparse
import cgi  # noqa: DEP002 — deprecated but present in 3.12; we control runtime
import io
import json
import shutil
import socket
import os
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# Module-level state. _RUNS is keyed by short hex IDs; each run tracks its
# own input/output dirs + progress so the upload page can poll status.
#
# Threading model: each upload spawns one background thread that runs the
# pipeline; the HTTP server is a ThreadingHTTPServer so polls don't block on
# the analyzer thread. We never share dataframes across threads — the
# results page reads scores.csv off disk after the run finishes.
# ---------------------------------------------------------------------------
_RUNS: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()

# V2.1 retrain state — one global slot since you only ever want one
# training job running at a time. Guarded by _RUNS_LOCK to keep the
# /retrain handler simple.
_RETRAIN_STATE: dict = {"state": "idle"}

# V14.6 — first-run model-download state. The launcher kicks off
# ``run_first_setup`` in a thread after starting the server; that
# thread updates this dict via ``first_run_set`` between targets.
# The browser polls /first_run_status every 1.5 s to drive a progress
# UI, so the user sees something happening during the 5-10 minute
# initial download instead of an eerily silent dock icon.
#
# Phases:
#   "idle"     — first run already completed, page should redirect
#   "warming"  — actively downloading; ``current`` / ``total`` /
#                ``step_label`` populated
#   "done"     — completed (with or without errors); page redirects
#                to / after a 1 s celebration
#   "skipped"  — first-run was cancelled by the user (no setup ran)
_FIRST_RUN_STATE: dict = {
    "phase":      "idle",
    "current":    0,
    "total":      0,
    "step_label": "",
    "errors":     [],
    "include_vlm": False,
    "started_at": 0.0,
}
_FIRST_RUN_LOCK = threading.Lock()


def first_run_set(**kwargs) -> None:
    """Thread-safe state update from the launcher's setup thread.

    Call from the launcher between warming steps to surface progress
    to any browser tab pointed at /first_run. Unknown keys are
    accepted so we can extend the schema without coordinating
    cross-module bumps.
    """
    with _FIRST_RUN_LOCK:
        _FIRST_RUN_STATE.update(kwargs)


def first_run_snapshot() -> dict:
    """Read-only copy for the /first_run_status endpoint."""
    with _FIRST_RUN_LOCK:
        out = dict(_FIRST_RUN_STATE)
        # ``errors`` is a list — return a copy so the caller can
        # mutate freely without racing the writer.
        out["errors"] = list(out.get("errors", []))
        return out


def first_run_append_error(label: str, msg: str) -> None:
    """Add a single warming-step failure to the error list."""
    with _FIRST_RUN_LOCK:
        _FIRST_RUN_STATE.setdefault("errors", []).append(
            {"label": label, "message": msg}
        )


# V17.7 — bulk-classify whitelist. The bulk-classify endpoint scans
# a user-supplied folder; subsequent /verticals/bulk_thumb requests
# need to validate the requested path against what we just saw so
# users can't probe arbitrary parts of the filesystem via the
# thumbnail server. Keyed by abs-path string; value is the (mtime,
# size) we measured at scan time so a swapped-out file is rejected.
_BULK_PATHS: dict[str, tuple[float, int]] = {}
_BULK_LOCK = threading.Lock()


def _bulk_register_paths(paths: list[Path]) -> None:
    with _BULK_LOCK:
        for p in paths:
            try:
                st = p.stat()
                _BULK_PATHS[str(p.resolve())] = (st.st_mtime, st.st_size)
            except OSError:
                continue


def _bulk_path_allowed(p: Path) -> bool:
    try:
        rp = str(p.resolve())
    except OSError:
        return False
    with _BULK_LOCK:
        return rp in _BULK_PATHS


# V14.7 — config helpers. The launcher's app_data_dir / config_path /
# load_config also handle this (more robustly with corruption backups),
# but we can't import from app/launcher.py here without creating a
# circular import. Lightweight duplicates good enough for the
# settings-toggle endpoints; first_read_config falls back to {} on
# any error rather than corrupting the file.
def _app_data_dir() -> Path:
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        p = Path.home() / ".pixcull"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _dbg("_app_data_dir", exc, str(p))
    return p


def _user_config_path() -> Path:
    return _app_data_dir() / "config.json"


def _load_user_config() -> dict:
    p = _user_config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _dbg("_load_user_config", exc, str(p))
        return {}


def _save_user_config(cfg: dict) -> None:
    """Atomic write to config.json with 0600 perms.

    Atomic via temp-file + rename so a crash mid-write can't leave a
    half-truncated config that ``_load_user_config`` then has to
    salvage.
    """
    p = _user_config_path()
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(p)
    except OSError as exc:
        _dbg("_save_user_config", exc, str(p))


# V17.12 — global error capture. Two entry points:
#
#   _capture_exception(label, exc, extra)
#       Wrap server-side handler's broad except blocks. Submits the
#       redacted traceback + label to the V14.7 reporter on a daemon
#       thread (must never block / re-raise — error path must stay
#       errorless).
#
#   _capture_client_event(payload)
#       Receives the browser-side window.onerror payload, fires
#       through the same submit pipeline.
#
# Both respect the V14.7 opt-in: if ``error_reports_enabled`` is
# False in config.json, both no-op silently. Even on opt-in, an
# empty / missing endpoint means dry-run (the report is built +
# redacted but not sent over the network) — useful for debugging.
def _capture_exception(label: str, exc: BaseException,
                         extra: dict | None = None) -> None:
    """Server-side hook for unexpected handler failures.

    Designed to be called from inside a broad ``except`` block:

        try:
            ...
        except Exception as exc:
            _capture_exception("verticals.tune", exc, {"key": key})
            traceback.print_exc(file=sys.stderr)
            self._reject_upload(500, ...)

    Never raises. Fire-and-forget on a daemon thread so the user's
    HTTP response isn't blocked by a slow reporter endpoint.
    """
    try:
        from pixcull import error_reporting as er
        cfg = _load_user_config()
        if not er.is_enabled(cfg):
            return
        import traceback as _tb
        full_extra = {
            "label":          label,
            "exception_type": type(exc).__name__,
            "exception_msg":  er.redact(str(exc)),
            "traceback":      er.redact(_tb.format_exc()),
        }
        if extra:
            # Redact every string value in caller-supplied extra fields
            # so a careless extra={"path": "/Users/alice/photos"} can't
            # leak.
            for k, v in extra.items():
                if isinstance(v, str):
                    full_extra[k] = er.redact(v)
                else:
                    full_extra[k] = v

        def _submit_worker():
            try:
                er.submit_report(
                    cfg, app_version=str(cfg.get("app_version", "dev")),
                    log_dir=_app_data_dir() / "logs",
                    reason="auto_exception",
                    extra=full_extra,
                )
            except Exception:
                pass   # reporter MUST be silent on its own failures

        threading.Thread(target=_submit_worker, daemon=True,
                          name="pixcull-error-reporter").start()
    except Exception:
        # Capture path itself must never raise.
        pass


def _capture_client_event(payload: dict) -> None:
    """Receive a window.onerror / unhandledrejection event from the
    browser, route through the V14.7 reporter.

    Caller-supplied fields are bounded + redacted (filenames in
    stack traces, /Users/<name> in source URLs, etc).
    """
    try:
        from pixcull import error_reporting as er
        cfg = _load_user_config()
        if not er.is_enabled(cfg):
            return
        # Bound payload sizes — a runaway page could spam giant stacks.
        def _clip(s, n=2000):
            s = str(s or "")
            return s[:n] if len(s) > n else s
        full_extra = {
            "kind":     _clip(payload.get("kind"), 64),
            "message":  er.redact(_clip(payload.get("message"))),
            "source":   er.redact(_clip(payload.get("source"), 200)),
            "lineno":   payload.get("lineno"),
            "colno":    payload.get("colno"),
            "stack":    er.redact(_clip(payload.get("stack"), 4000)),
            "url":      er.redact(_clip(payload.get("url"), 200)),
            "ua":       _clip(payload.get("ua"), 200),
        }

        def _submit_worker():
            try:
                er.submit_report(
                    cfg, app_version=str(cfg.get("app_version", "dev")),
                    log_dir=_app_data_dir() / "logs",
                    reason="client_event",
                    extra=full_extra,
                )
            except Exception:
                pass

        threading.Thread(target=_submit_worker, daemon=True,
                          name="pixcull-client-error-reporter").start()
    except Exception:
        pass


# V11.2 auto-retrain trigger:
# Increments on every human annotation save; once it crosses
# AUTO_RETRAIN_THRESHOLD, the next /annotation save will spawn a
# background retrain (debounced — won't fire while one is already
# running) then reset the counter. Small enough to feel
# 'continuously learning', large enough that we don't burn CPU
# on every single click.
_AUTO_RETRAIN_THRESHOLD = 10
_annotations_since_retrain = 0

# P-UX-4 — reject-reason taxonomy. When a photographer marks a photo
# ``cull``, they can optionally tag *why* via a small overlay. Tokens
# are snake_case ASCII for stability across versions + CSV/training
# tools; the UI translates them to localized labels at render time
# (same convention as the genre/scene taxonomy). Adding a new token
# here is enough to surface it in the picker — the server validates
# against this list to silently drop typos.
_CULL_REASONS: tuple[str, ...] = (
    "focus_miss",       # 焦点不准  — the AF locked on the wrong plane
    "eyes_closed",      # 闭眼/表情 — subject blinked / awkward expression
    "motion_blur",      # 模糊抖动 — handshake or subject motion blur
    "framing",          # 构图差   — bad composition / crop / framing
    "duplicate",        # 与更佳重复 — kept a better near-duplicate
    "exposure",         # 曝光问题 — under/overexposed beyond recovery
    "other",            # 其他    — catch-all for everything else
)

_DEFAULT_PORT = 8770
_FALLBACK_PORTS = (8770, 8771, 8772, 9322, 7799)
_DEMO_ROOT = Path("/tmp/pixcull_demo")  # base dir for upload + output trees
_THUMB_SIZE = 420
_FULL_SIZE = 1600


# V19.4.1 — hot-reloadable results page template.
#
# Pre-V19.4.1 the entire 2600-line ``_RESULTS_HTML`` template was a
# module-level ``r"""..."""`` constant baked into memory at import. Any
# fix to its HTML/JS — like the V19.4 TDZ on shadowed ``const esc`` —
# required killing + restarting the long-running server. That made
# the bug feel worse than it was (fix in code, still broken in users'
# browsers because the running process was holding stale bytes).
#
# Moving the template to ``pixcull/report/templates/results.html`` and
# loading it per-request with an mtime cache means: edit the .html,
# next hit picks it up. The mtime check is a couple of microseconds
# vs. the ~10 ms cost of re-parsing 2.5 MB of template, so the cache
# pays for itself on the typical reload-debug loop.
_RESULTS_HTML_PATH = (
    Path(__file__).resolve().parent.parent
    / "pixcull" / "report" / "templates" / "results.html"
)
_RESULTS_HTML_CACHE: tuple[int, str] | None = None


def _results_html_template() -> str:
    """Return the current ``results.html`` template body.

    Cached by mtime — repeat hits at the same revision skip the
    file read. On first request after a template edit the mtime
    differs and we re-load.

    Raises FileNotFoundError if the template is missing — that's a
    deployment bug (template not bundled), surface loudly.
    """
    global _RESULTS_HTML_CACHE
    p = _RESULTS_HTML_PATH
    mt = p.stat().st_mtime_ns  # FileNotFoundError propagates
    if _RESULTS_HTML_CACHE and _RESULTS_HTML_CACHE[0] == mt:
        return _RESULTS_HTML_CACHE[1]
    content = p.read_text(encoding="utf-8")
    _RESULTS_HTML_CACHE = (mt, content)
    return content

# Upload limits. The byte cap is a real safety boundary (multipart parsing
# spools to disk above ~1 KB per field anyway, but unbounded uploads still
# let an attacker fill /tmp). The file-count cap mostly protects the
# multipart parser from pathological tiny-file storms. Both can be
# overridden at startup via --max-upload-mb / --max-upload-files.
#
# 8 GB default is sized for typical pro photo workflows: a Canon R5 / R6
# burst is ~30-60 MB per CR3, so 8 GB ≈ 130-260 RAW shots in one upload.
# If you need bigger, raise --max-upload-mb. Pipeline throughput then
# becomes the user-visible bottleneck (1-10 s per image) — not this cap.
_MAX_UPLOAD_BYTES_DEFAULT = 8 * 1024 * 1024 * 1024  # 8 GB
_MAX_UPLOAD_FILES_DEFAULT = 500
# Refuse the upload if it would push /tmp below this much free space after
# landing on disk. Keeps the system usable even if the user hands us a
# batch that exactly fills the disk.
_MIN_FREE_SPACE_AFTER_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB


# V14.0 — replace silent ``except: pass`` with traceable debug logs.
# We don't want noisy stderr in normal operation, but every "we tried, it
# failed, we kept going" path should leave a fingerprint for the rare bug
# report ("my run shows 0 images though there's a manifest"). One-line
# DEBUG-level breadcrumbs make those reproducible.
_DEBUG_LOG = "PIXCULL_DEBUG" in __import__("os").environ


def _dbg(where: str, exc: BaseException | None = None, extra: str = "") -> None:
    """One-line breadcrumb to stderr for a non-fatal failure path.

    Always writes when PIXCULL_DEBUG is set; otherwise stays quiet to keep
    happy-path output clean. The point isn't user-facing logs — it's that
    when a bug report comes in we can ask the user to re-run with
    PIXCULL_DEBUG=1 and immediately see *which* fallback fired.
    """
    if not _DEBUG_LOG:
        return
    msg = f"[pixcull.dbg] {where}"
    if exc is not None:
        msg += f" :: {type(exc).__name__}: {exc}"
    if extra:
        msg += f" :: {extra}"
    sys.stderr.write(msg + "\n")


# V14.0 — JSON encoder that turns NaN/Infinity into null instead of writing
# literal "NaN" / "Infinity" tokens (which are not valid JSON and crash
# strict parsers like the JS frontend's JSON.parse). Use anywhere a
# pandas-derived value might be NaN.
class _SafeJSONEncoder(json.JSONEncoder):
    def __init__(self, *a, **kw):
        # allow_nan=False would raise — we want a quiet substitution instead
        kw.setdefault("ensure_ascii", False)
        super().__init__(*a, **kw)

    def iterencode(self, o, _one_shot=False):
        # JSONEncoder.iterencode emits "NaN"/"Infinity" by default. We
        # walk the object first and substitute, which is cheap relative
        # to the network cost of sending the response.
        return super().iterencode(_scrub_nan(o), _one_shot=_one_shot)


def _scrub_nan(o):
    """Recursively replace float NaN/inf with None; everything else unchanged."""
    import math
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        return o
    if isinstance(o, dict):
        return {k: _scrub_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_scrub_nan(v) for v in o]
    return o


def _safe_dumps(obj, **kwargs) -> str:
    """``json.dumps`` that never emits invalid NaN/Infinity tokens."""
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(_scrub_nan(obj), **kwargs)


# V14.1 — JSONL cache. rubric.jsonl + annotations.jsonl get re-parsed
# from disk on every result render, every annotation modal open, every
# rubric API hit. For a 1000-image batch where the user clicks through
# 200 thumbnails this is 200 full re-parses of a multi-MB file.
#
# This is a tiny mtime-keyed LRU. Files are invalidated whenever their
# mtime moves forward (annotation save bumps mtime, so the cache stays
# fresh without explicit invalidation calls). Bounded to 16 entries to
# survive aggressive admin tools without memory growth.
class _MtimeLRUCache:
    """Tiny thread-safe LRU keyed by (path, mtime).

    Why not functools.lru_cache: we need to invalidate when the file
    changes on disk, and lru_cache has no eviction by anything other
    than its arg tuple. Keying on mtime makes a write naturally bust
    the entry without needing to touch the cache from the writer.
    """

    def __init__(self, maxsize: int = 16):
        self._max = maxsize
        self._d: "dict[tuple, object]" = {}
        self._lock = threading.Lock()

    def get_or_load(self, path: Path, loader):
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return loader()  # path gone; let loader handle
        key = (str(path), mtime)
        with self._lock:
            if key in self._d:
                # Touch by re-inserting to keep MRU at the end (Py 3.7+
                # dicts preserve insertion order)
                v = self._d.pop(key)
                self._d[key] = v
                return v
        v = loader()
        with self._lock:
            self._d[key] = v
            # Evict any older entries for this same path AND drop oldest
            # entries past the bound.
            for k in list(self._d.keys()):
                if k[0] == str(path) and k != key:
                    self._d.pop(k, None)
            while len(self._d) > self._max:
                self._d.pop(next(iter(self._d)))
        return v


_JSONL_CACHE = _MtimeLRUCache(maxsize=16)


def _read_jsonl_cached(path: Path) -> list[dict]:
    """Return a parsed list of records from a JSONL file, cached by
    (path, mtime). Lines that fail to parse are skipped (matches the
    historic behavior — bad lines never aborted the read)."""
    def _load() -> list[dict]:
        out: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        _dbg("_read_jsonl_cached/parse", exc, str(path))
        except OSError as exc:
            _dbg("_read_jsonl_cached/open", exc, str(path))
        return out
    return _JSONL_CACHE.get_or_load(path, _load)


def _read_human_by_fn_cached(ann_path: Path) -> dict[str, dict]:
    """Latest-wins index of human annotations keyed by filename. Built
    on top of ``_read_jsonl_cached`` so it benefits from the same mtime
    cache (with negligible extra memory — same dicts, different shape).
    """
    if not ann_path.exists():
        return {}
    out: dict[str, dict] = {}
    for rec in _read_jsonl_cached(ann_path):
        fn = rec.get("filename")
        if fn:
            out[fn] = rec  # later wins
    return out


def _html_escape(s) -> str:
    """Minimal HTML escape for filename / alt-text interpolation. Returns
    ``""`` on None so f-strings stay safe. We don't import the ``html``
    module here because we want explicit control over which characters
    matter for the very narrow cases we hit (alt attribute, data-*).
    """
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _pick_port(preferred: int, host: str) -> int:
    """Return the preferred port if free on ``host``, else first free fallback."""
    candidates = (preferred, *_FALLBACK_PORTS)
    for p in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise RuntimeError(
        f"All preferred ports busy: {candidates}. Pass --port to choose."
    )


def _local_ipv4() -> str | None:
    """Best-effort guess at the LAN-visible IPv4. Returns None if offline.

    Tries the "connect-to-public-IP-then-read-our-source-IP" trick that
    works on every macOS/Linux without parsing ifconfig output. We never
    actually send any packets — UDP socket connect just sets the kernel's
    routing table, no traffic leaves the machine.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            # Cloudflare 1.1.1.1 — any reachable v4 address works
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _new_run_id() -> str:
    return uuid.uuid4().hex[:10]


def _run_dir(run_id: str) -> Path:
    return _DEMO_ROOT / run_id


def _set_run(run_id: str, **fields: object) -> None:
    """Thread-safe partial update of a run's state dict."""
    with _RUNS_LOCK:
        run = _RUNS.setdefault(run_id, {})
        run.update(fields)


def _get_run(run_id: str) -> dict | None:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        return dict(run) if run is not None else None


def _analyze_in_background(
    run_id: str,
    rescorer_mode: str,
    rescorer_path: str | None,
    vlm_mode: str = "off",
    meta_mode: str = "off",
) -> None:
    """Worker thread: run the pipeline on the run's source dir.

    Two modes, both go through the same ``run_pipeline()``:
      * mode="upload"  source = run_dir/input/    (we copied bytes in)
      * mode="scan"    source = an arbitrary local path (originals untouched)

    The orchestrator doesn't care which — it just walks the path. The
    difference shows up later in thumbnail serving (manifest lookup) and
    cleanup (scan mode never deletes originals).

    Never raises out of the thread — fills run["state"]="error" and
    run["message"] with the exception summary instead.
    """
    # Imported here, not at module scope, so a missing-deps environment can
    # still serve the upload page and return a friendly error rather than
    # crashing on startup.
    from pixcull.pipeline.orchestrator import run_pipeline

    run = _get_run(run_id)
    if run is None:
        return
    source_dir = Path(run.get("source_dir") or run["input_dir"])
    output_dir = Path(run["output_dir"])

    def progress_cb(done: int, total: int, message: str) -> None:
        _set_run(run_id, done=done, total=total, message=message)

    _set_run(run_id, state="running", started_at=time.time(),
             vlm_mode=vlm_mode, meta_mode=meta_mode)
    try:
        # V17.2 — pass the run's vertical (set by /scan_local) into
        # the pipeline so decide() can apply per-vertical thresholds
        # + tolerated flags. None / unknown vertical = unchanged behavior.
        run_pipeline(
            source_dir,
            output_dir,
            rescorer_mode=rescorer_mode,
            rescorer_path=rescorer_path,
            progress_cb=progress_cb,
            vlm_mode=vlm_mode,
            meta_mode=meta_mode,
            vertical=run.get("vertical"),
        )
        _set_run(
            run_id,
            state="done",
            finished_at=time.time(),
            message="完成",
        )
    except Exception as exc:  # noqa: BLE001
        # Surface any pipeline failure to the browser instead of a silent
        # spinner. Full traceback goes to the server stderr for debugging.
        traceback.print_exc(file=sys.stderr)
        _set_run(
            run_id,
            state="error",
            finished_at=time.time(),
            message=f"分析失败: {type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Result rendering: read scores.csv off disk, build the rows the HTML grid
# expects. Mirrors serve_review's row schema (subset) so the same CSS works.
# ---------------------------------------------------------------------------

# P-UX-10 — inconsistency thresholds. The 4 scoring sources
# (auto / model / vlm / meta) ought to broadly agree on a frame's
# rubric stars; large disagreement usually means the frame sits in
# a corner the rubric isn't calibrated for ("ambiguous moment",
# "unusual composition") and is worth a human glance.
#
# Numbers below picked empirically from the V25 batch:
#   stddev > 0.7 stars per axis  → call it noisy on that axis
#   sum of per-axis stddevs > 2.0 → call the whole row noisy
# A row with no human label yet AND a noisy total → "review me".
_INCONSISTENCY_AXIS_THRESH = 0.7
_INCONSISTENCY_TOTAL_THRESH = 2.0


def _compute_inconsistency(auto_stars: dict, model_stars: dict,
                            vlm_stars: dict, meta_stars: dict,
                            axis_names: list[str],
                            has_human: bool) -> dict:
    """Compute per-axis + total stddev across the available scoring
    sources for one row. Returns a dict with three keys ready to
    splat into the row payload.

    ``inconsistency_total``     float, sum of per-axis stddevs
    ``inconsistency_per_axis``  {axis: stddev | None}
    ``needs_review``            bool — True iff total > threshold
                                AND no human annotation exists yet
    """
    import math
    per_axis: dict[str, float | None] = {}
    total = 0.0
    n_with_signal = 0
    for axis in axis_names:
        vals = []
        for src in (auto_stars, model_stars, vlm_stars, meta_stars):
            v = src.get(axis) if isinstance(src, dict) else None
            if v is not None:
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    pass
        if len(vals) < 2:
            per_axis[axis] = None
            continue
        mean = sum(vals) / len(vals)
        var = sum((x - mean) ** 2 for x in vals) / len(vals)
        std = math.sqrt(var)
        per_axis[axis] = round(std, 3)
        total += std
        n_with_signal += 1
    total = round(total, 3)
    return {
        "inconsistency_total":    total,
        "inconsistency_per_axis": per_axis,
        # Only flag for review when the noise is real *and* the user
        # hasn't already decided. We trust their judgment over the
        # rubric's stddev.
        "needs_review": (
            n_with_signal >= 1
            and total >= _INCONSISTENCY_TOTAL_THRESH
            and not has_human
        ),
    }


# P-UX-14 — within-burst exposure-consistency thresholds.
#   mean_luma deviation ≥ 18 (on 0..255 scale ≈ ~⅓ stop)
#   OR  highlight_clip_pct delta ≥ 4%  (visible blown highlights)
# Cluster needs ≥ 3 members for the median to be meaningful;
# singleton "clusters" (cluster_id None) skip the check entirely.
_EXPOSURE_LUMA_DELTA   = 18.0
_EXPOSURE_HIGHLIGHT_DELTA = 4.0
_EXPOSURE_MIN_CLUSTER = 3


def _exposure_consistency_pass(rows: list[dict]) -> None:
    """Mutates rows in place: adds ``exposure_outlier`` (bool) and
    ``exposure_deviation`` (dict) to each row that's part of a
    real burst cluster (size ≥ 3) AND deviates from the cluster
    median by ≥ the thresholds above.

    The cluster_id comes from V9.0's near-duplicate / burst grouping,
    so "cluster" here means "photos the photographer took within
    seconds of each other of essentially the same scene" — the
    only place where exposure consistency is meaningful (totally
    different scenes will have different luma by design).
    """
    from collections import defaultdict
    import statistics

    by_cluster: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        cid = r.get("cluster_id")
        if cid is None:
            continue
        by_cluster[cid].append(r)

    for cid, members in by_cluster.items():
        if len(members) < _EXPOSURE_MIN_CLUSTER:
            continue
        lumas = [m["mean_luma"] for m in members if m.get("mean_luma") is not None]
        highs = [m["highlight_clip_pct"] for m in members if m.get("highlight_clip_pct") is not None]
        if len(lumas) < _EXPOSURE_MIN_CLUSTER:
            continue
        med_luma = statistics.median(lumas)
        med_high = statistics.median(highs) if len(highs) >= _EXPOSURE_MIN_CLUSTER else None
        for m in members:
            ml = m.get("mean_luma")
            mh = m.get("highlight_clip_pct")
            if ml is None:
                continue
            luma_delta = ml - med_luma
            high_delta = (mh - med_high) if (mh is not None and med_high is not None) else 0.0
            is_outlier = (
                abs(luma_delta) >= _EXPOSURE_LUMA_DELTA
                or abs(high_delta) >= _EXPOSURE_HIGHLIGHT_DELTA
            )
            if is_outlier:
                m["exposure_outlier"] = True
                m["exposure_deviation"] = {
                    "luma_delta":      round(luma_delta, 1),
                    "highlight_delta": round(high_delta, 2),
                    "cluster_median_luma":  round(med_luma, 1),
                    "cluster_size":    len(members),
                }


def _row_has_develop_settings(r) -> bool:
    """P-PRO-1 — check whether a row's source image has Lr develop
    edits (crs:*) in its XMP sidecar.

    Lazy + best-effort: returns False whenever the source path is
    unknown or the sidecar can't be parsed. The actual develop
    application happens in load_image_for_display via
    pixcull.io.xmp.read_develop_settings — we just expose a "yes/no"
    flag on the row so the lightbox can show a "已应用 Lr 调色" badge.
    """
    src = r.get("path")
    if not src:
        return False
    try:
        from pixcull.io.xmp import read_develop_settings
        dev = read_develop_settings(Path(str(src)))
        return bool(dev)
    except Exception:
        return False


def _build_results(run_id: str) -> tuple[list[dict], dict] | None:
    # V8.5: fall back to disk-reload if the run isn't in memory
    # (e.g. server restarted, or the .app and dev server share runs
    # via a symlink). Without this fallback /results/<run_id> is
    # 404 even when scores.csv exists on disk.
    run = _get_run(run_id) or _reload_run_from_disk(run_id)
    if run is None:
        return None
    output_dir = Path(run["output_dir"])
    scores_path = output_dir / "scores.csv"
    if not scores_path.exists():
        return None

    import pandas as pd  # local import to keep startup light

    df = pd.read_csv(scores_path)

    # V2.0: pull human annotations off disk (latest line wins per fn).
    # V14.1: cached via _MtimeLRUCache so repeat renders / API hits in
    # the same session don't re-parse the same multi-MB file.
    output_dir = Path(run["output_dir"])
    ann_path = output_dir / "annotations.jsonl"
    human_by_fn: dict[str, dict] = _read_human_by_fn_cached(ann_path)

    from pixcull.scoring.rubric import RUBRIC_AXES
    from pixcull.scoring.photo_advice import build_advice
    rubric_axis_names = [a.name for a in RUBRIC_AXES]

    # V17.3 — read the run's vertical override (set by /scan_local from
    # the dropdown) once up front. Passed into build_advice for every
    # row so wedding/bird/kids/etc tagged batches get business-flavored
    # phrasing instead of generic.
    run_vertical = run.get("vertical") or None

    rows: list[dict] = []
    # V14.3 — enumerate so build_advice can pick phrases by batch index
    # rather than filename hash. Renaming a JPG no longer rotates its
    # review text (which the user found confusing).
    for _idx, (_, r) in enumerate(df.iterrows()):
        fn = str(r["filename"])
        # Auto rubric stars from CSV columns ('rubric_<axis>_stars')
        auto_stars = {
            name: _f(r.get(f"rubric_{name}_stars"))
            for name in rubric_axis_names
        }
        # V2.1 model predictions ('model_<axis>_stars') if rescorer
        # was loaded at run time. Absent for pre-V2.1 runs.
        model_stars = {
            name: _f(r.get(f"model_{name}_stars"))
            for name in rubric_axis_names
        }
        # V3.0 VLM predictions ('vlm_<axis>_stars') if VLM was on.
        vlm_stars = {
            name: _f(r.get(f"vlm_{name}_stars"))
            for name in rubric_axis_names
        }
        # V3.1 Meta-judge predictions ('meta_<axis>_stars') if meta on.
        meta_stars = {
            name: _f(r.get(f"meta_{name}_stars"))
            for name in rubric_axis_names
        }
        # Human override if present — last save per filename wins.
        human_rec = human_by_fn.get(fn)
        human_stars: dict[str, float | None] = {}
        if human_rec:
            for name in rubric_axis_names:
                axis_data = (human_rec.get("axes") or {}).get(name) or {}
                human_stars[name] = axis_data.get("stars")
        # Final stars per axis: human → meta → vlm → model → auto.
        # Trustworthiness order: humans always win, meta-judge calibrated
        # against multi-source > raw VLM > V2.1 regressor > heuristic.
        def _pick(name: str) -> float | None:
            for src in (human_stars, meta_stars, vlm_stars, model_stars, auto_stars):
                v = src.get(name) if isinstance(src, dict) else None
                if v is not None:
                    return v
            return None
        final_stars = {name: _pick(name) for name in rubric_axis_names}
        # V5.2: build photographer-friendly advice from final stars +
        # raw row metrics + meta inconsistencies. V14.3: idx is the
        # row's position in the batch — used as the deterministic
        # phrase-rotation anchor (rename-stable, unlike old filename
        # hash) and fed into _synthesize_maybe_rationale for the
        # 'why is this maybe?' summary line.
        advice = build_advice(
            row=r.to_dict(),
            final_stars=final_stars,
            decision=str(r.get("decision", "") or ""),
            meta_inconsistencies=str(r.get("meta_inconsistencies", "") or ""),
            idx=_idx,
            vertical=run_vertical,        # V17.3 — business-flavored phrases
        )
        # V9.0: detected style modes for the UI tag chip
        from pixcull.scoring.style_modes import detect_style_modes
        sp = detect_style_modes(r.to_dict())
        # cluster_id from duplicate detector — used by V9.0 grouping
        cluster_id = r.get("cluster_id")
        try:
            cluster_id = int(cluster_id) if cluster_id is not None else None
        except (TypeError, ValueError):
            cluster_id = None
        # take time of capture for date sorting
        dt_str = str(r.get("datetime", "") or "")
        rows.append({
            "filename": fn,
            # V21.2 — surface the absolute source path so the LR plugin
            # write-back (GET /decisions/<run_id>) can match photos by
            # path rather than basename (different shoots reuse the same
            # IMG_NNNN.jpg filename — basename matching is ambiguous).
            "src_path": str(r.get("path", "") or ""),
            "scene": str(r.get("scene", "") or ""),
            "decision": str(r.get("decision", "") or ""),
            "score_final": _f(r.get("score_final")),
            "score_sharpness": _f(r.get("score_sharpness")),
            "score_exposure": _f(r.get("score_exposure")),
            "score_aesthetic": _f(r.get("score_aesthetic")),
            "score_composition": _f(r.get("score_composition")),
            # V20 — flags was emitting the literal string "nan" whenever
            # the underlying CSV cell was empty / pandas-NaN. The lightbox
            # template renders the "检测器旗标" section as ${r.flags ?
            # … : ''}, so "nan" (truthy non-empty string) showed up as
            # a useless "nan" line on tens of thousands of clean photos.
            # Coerce to empty so the section is hidden when there's
            # nothing to report.
            "flags": _clean_csv_string(r.get("flags")),
            "reason": str(r.get("reason", "") or ""),
            "advice": advice,
            # V22.0 — per-face cluster IDs (list[int], one per
            # meaningful face). -1 = noise / unique-ish face. Empty
            # list = no faces in this photo. The CSV stores this as
            # a string repr; parse it back if non-empty.
            "face_clusters": _parse_int_list(r.get("face_clusters")),
            # V23 — GPS coords + location cluster id. None when EXIF
            # had no GPS / failed lock; the UI groups those under
            # "未知位置". gps_lat/lon are surfaced so the UI can show
            # a map pin in the lightbox info pane (V23.1+).
            "gps_lat":        _f(r.get("gps_lat")),
            "gps_lon":        _f(r.get("gps_lon")),
            "gps_cluster_id": _opt_int(r.get("gps_cluster_id")),
            # P-UX-14 — raw luma + clip-pct surfaced so we can detect
            # within-burst exposure outliers after all rows are built.
            # These are the same metrics the per-photo scorer already
            # computed; we just plumb them through so a downstream
            # pass can flag inconsistencies.
            "mean_luma":          _f(r.get("mean_luma")),
            "highlight_clip_pct": _f(r.get("highlight_clip_pct")),
            "shadow_clip_pct":    _f(r.get("shadow_clip_pct")),
            # V27 — per-burst peak rank. peak_rank=0 means "THE peak"
            # in this row's burst cluster; is_burst_peak is the same
            # signal as a bool for cheaper JS access. Singleton
            # clusters (no real burst) all get rank=0 + is_peak=True
            # but the UI ignores them by checking cluster size.
            "peak_rank":      _opt_int(r.get("peak_rank")),
            "is_burst_peak":  bool(r.get("is_burst_peak"))
                              if r.get("is_burst_peak") not in
                                 (None, "", float("nan"))
                              else False,
            # P-AI-5.1 — per-component reason string for the cluster's
            # winner ("眼睛睁开 95%" / "簇内最锐 100%" / "动作差异
            # 最大 85%"). None on non-peak rows + on singletons;
            # surfaced as a tooltip on the 🏆 badge in the lightbox.
            "burst_peak_reason": (str(r["burst_peak_reason"])
                                  if r.get("burst_peak_reason") not in
                                     (None, "", float("nan"))
                                  else None),
            # P-PRO-4.1 — wedding moment (only set on rows where
            # scene == wedding).  "unknown" means the classifier
            # abstained on a tight-margin top-2.  None on non-wedding.
            "wedding_moment": (str(r["wedding_moment"])
                               if r.get("wedding_moment") not in
                                  (None, "", float("nan"))
                               else None),
            "wedding_moment_confidence": _f(r.get("wedding_moment_confidence")),
            # V9.0 sort/filter/group fields
            "cluster_id": cluster_id,
            "datetime": dt_str,
            "style_modes": sorted(sp.modes),
            "rescorer_pred": (
                str(r.get("rescorer_pred"))
                if "rescorer_pred" in df.columns
                and r.get("rescorer_pred") not in (None, "", float("nan"))
                and str(r.get("rescorer_pred")) != "nan"
                else None
            ),
            "rescorer_prob_keep": _f(r.get("rescorer_prob_keep"))
            if "rescorer_prob_keep" in df.columns else None,
            # Rubric: per-axis stars (the visible 1-5) plus the human
            # override marker so the UI can show a 'human-graded' badge.
            "rubric_stars": final_stars,
            # V2.1: keep auto/model/human as separate dicts so the modal
            # can render a 3-way comparison ("auto says 4, model says 3,
            # human says 5 — interesting!"). Tooltips on the result
            # cards use these to surface disagreements at a glance.
            "rubric_auto_stars": auto_stars,
            "rubric_model_stars": model_stars,
            "rubric_vlm_stars": vlm_stars,
            "rubric_meta_stars": meta_stars,
            "rubric_human_stars": {k: human_stars.get(k) for k in rubric_axis_names},
            "rubric_human_labeled": human_rec is not None,
            # P-UX-10 — disagreement among the available scoring
            # sources. For each axis, take the stddev across
            # (auto / model / vlm / meta) wherever a value is present
            # (skip None). Max across axes is the "noisy axis"; sum
            # is the row's overall inconsistency. Surfaced as a card
            # chip + a "review me" hint when ≥ 1.0 stars and no
            # human annotation has settled the matter yet.
            **_compute_inconsistency(
                auto_stars, model_stars, vlm_stars, meta_stars,
                rubric_axis_names,
                has_human=(human_rec is not None),
            ),
            "rubric_overall_rationale": (
                human_rec.get("overall_rationale") if human_rec else ""
            ),
            # P-UX-4 — optional reject reason (one of _CULL_REASONS or "").
            # Only surfaced when the LATEST human annotation actually
            # culled the photo — otherwise a stale "focus_miss" from a
            # since-revised verdict would mislead the UI chip + filter.
            "cull_reason": (
                str(human_rec.get("cull_reason") or "")
                if (human_rec and
                    str(human_rec.get("overall_label", "")).strip().lower() == "cull")
                else ""
            ),
            # P-PRO-1 — has the user edited develop settings in Lr?
            # If yes, the lightbox shows a "已应用 Lr 调色" badge so
            # the user knows the displayed preview reflects their
            # edit (load_image_for_display picks up crs:* settings
            # automatically; scoring still uses the RAW for now).
            "has_develop_settings": _row_has_develop_settings(r),
            # V3.x rationales for the modal's 4-way comparison
            "vlm_overall_rationale": str(r.get("vlm_overall_rationale", "") or ""),
            "vlm_overall_label": str(r.get("vlm_overall_label", "") or ""),
            "meta_overall_rationale": str(r.get("meta_overall_rationale", "") or ""),
            "meta_overall_label": str(r.get("meta_overall_label", "") or ""),
            "meta_confidence": _f(r.get("meta_confidence")),
            "meta_inconsistencies": str(r.get("meta_inconsistencies", "") or ""),
        })

    # P-UX-14 — within-burst exposure-consistency check. For each
    # cluster of ≥ 3 photos, take the median mean_luma + median
    # highlight_clip_pct, then flag rows whose deviation exceeds
    # the (light-relative) threshold. Catches the situation where
    # a wedding/event series has one frame at +1 stop because the
    # photographer's finger drifted off the dial — uniquely worth
    # flagging because the user often hasn't NOTICED themselves.
    _exposure_consistency_pass(rows)

    # Sort: keep first, then maybe, then cull, by score within group.
    order = {"keep": 0, "maybe": 1, "cull": 2, "": 3}
    rows.sort(key=lambda x: (order.get(x["decision"], 4),
                              -(x["score_final"] or 0)))

    counts = Counter(r["decision"] for r in rows)
    # V1.2 rescorer summary: "the model agrees with the rule on N out of M
    # non-cull rows; disagrees on D." Shown in the header so the user sees
    # immediately whether the learned head is contributing signal.
    rescored = [r for r in rows if r["rescorer_pred"] is not None]
    disagrees = [r for r in rescored if r["rescorer_pred"] != r["decision"]]
    # V2.0 rubric summary: how many images have any human label, mean
    # stars per axis (auto+human pooled). Surfaces "did the human
    # contribute signal yet" at a glance.
    n_human_labeled = sum(1 for r in rows if r["rubric_human_labeled"])
    # V17.8 — count of human annotations with overall_label in
    # (keep, cull) — these are the candidates the "📥 灌入 sample
    # bank" button promotes. We surface only when the run also
    # carries a vertical tag (set by /scan_local from the dropdown).
    n_promotable = 0
    if run.get("vertical"):
        for r in rows:
            rec = human_by_fn.get(r["filename"]) or {}
            lbl = (rec.get("overall_label") or "").strip().lower()
            if lbl in ("keep", "cull"):
                n_promotable += 1
    axis_means: dict[str, float | None] = {}
    for name in rubric_axis_names:
        vals = [r["rubric_stars"][name] for r in rows
                if r["rubric_stars"].get(name) is not None]
        axis_means[name] = round(sum(vals) / len(vals), 2) if vals else None
    # V17.2 — surface the vertical override + policy notes so the
    # results page can render a small badge ("应用了垂类: kids ·
    # keep -5pp / cull -5pp"). Falls back to None for runs that
    # didn't pick a vertical (most existing runs).
    vertical_key = run.get("vertical")
    vertical_info: dict | None = None
    if vertical_key:
        try:
            from pixcull.verticals import get_vertical
            v = get_vertical(vertical_key)
            if v is not None:
                vertical_info = {
                    "key":   v.key,
                    "zh":    v.zh,
                    "icon":  v.icon,
                    "policy_notes": v.policy.notes,
                    "keep_min_delta": v.policy.keep_min_delta,
                    "cull_max_delta": v.policy.cull_max_delta,
                    "tolerated_flags": sorted(v.policy.tolerated_flags),
                }
        except Exception:
            vertical_info = None

    summary = {
        "n_total": len(rows),
        "n_keep": counts.get("keep", 0),
        "n_maybe": counts.get("maybe", 0),
        "n_cull": counts.get("cull", 0),
        "rescorer_active": len(rescored) > 0,
        "rescorer_n_scored": len(rescored),
        "rescorer_n_disagrees": len(disagrees),
        "n_human_labeled": n_human_labeled,
        "n_promotable": n_promotable,    # V17.8 — promote-to-bank count
        "rubric_axis_means": axis_means,
        "mode": run.get("mode", "upload"),
        "origin_folder": run.get("origin_folder"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "elapsed_s": (
            round(run["finished_at"] - run["started_at"], 1)
            if run.get("finished_at") and run.get("started_at") else None
        ),
        "vertical": vertical_info,
    }
    return rows, summary


def _f(v: object) -> float | None:
    """Coerce to float or None for NaN/empty."""
    try:
        x = float(v)  # type: ignore[arg-type]
        if x != x:
            return None
        return round(x, 3)
    except (TypeError, ValueError):
        return None


def _clean_csv_string(v: object) -> str:
    """V20 — return empty string for CSV cells that round-tripped through
    pandas as NaN.

    pandas reads an empty CSV cell as ``float('nan')``, and ``str(NaN)``
    returns the literal string ``"nan"``. Naive ``str(r.get(col, "") or "")``
    therefore emits ``"nan"`` for missing values, which the JS template
    happily renders as a real-looking "nan" line.

    Treats the following as empty:
      * ``None``
      * ``float('nan')`` (and any value whose ``str`` is exactly ``"nan"``)
      * empty string / whitespace
    """
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    return s


def _opt_int(v: object) -> int | None:
    """V23 — coerce a CSV cell to int-or-None, NaN-safe.

    pandas reads missing CSV cells as ``float('nan')``. Naive
    ``int(NaN)`` raises ValueError; naive ``int(v) if v is not None``
    converts NaN to a junk integer on some platforms (NaN → 0 or
    -9223372036854775808 depending on libc). This helper rejects
    NaN explicitly.
    """
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _parse_int_list(v: object) -> list[int]:
    """V22.0 — parse a CSV cell that round-tripped a Python list of ints
    back into a list.

    pandas writes ``[0, 1, -1]`` as the string ``"[0, 1, -1]"`` and reads
    it back as that same string. We use ``ast.literal_eval`` for safe
    parsing (only accepts literal Python expressions — no code
    execution) and fall through to empty list for any malformed input.
    """
    if v is None:
        return []
    if isinstance(v, list):
        # Already-parsed (e.g. when called inline before CSV write)
        return [int(x) for x in v if x is not None]
    if isinstance(v, float) and v != v:
        return []
    s = str(v).strip()
    if not s or s.lower() == "nan" or s in ("[]", "()"):
        return []
    try:
        import ast
        parsed = ast.literal_eval(s)
        if isinstance(parsed, (list, tuple)):
            return [int(x) for x in parsed]
    except (ValueError, SyntaxError, TypeError):
        pass
    return []


# ---------------------------------------------------------------------------
# V22.1 — face cluster summary + per-run label persistence.
# Labels are user-edited names for cluster IDs ("Bride", "Groom",
# "Child A"). Stored per-run at ``<output_dir>/face_labels.json``;
# cross-run inheritance (so "Bride" label sticks across multiple
# weddings) is V22.2+.
# ---------------------------------------------------------------------------

def _face_labels_path(run_id: str) -> Path | None:
    """Resolve the on-disk label file for a run, or None if the run
    has no output dir on disk."""
    run = _get_run(run_id) or _reload_run_from_disk(run_id)
    if run is None:
        return None
    od = run.get("output_dir")
    if not od:
        return None
    return Path(od) / "face_labels.json"


def _load_face_labels(run_id: str) -> dict[int, str]:
    """Read the run's label file. Returns {cluster_id: label}.
    Empty dict when no file or parse error — never raises."""
    p = _face_labels_path(run_id)
    if p is None or not p.exists():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    labels = data.get("labels") or {}
    out: dict[int, str] = {}
    for k, v in labels.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return out


def _save_face_labels(run_id: str, labels: dict[int, str]) -> bool:
    """Persist labels for a run. Returns True on success."""
    p = _face_labels_path(run_id)
    if p is None:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema":      "pixcull.face_labels.v1",
        "run_id":      run_id,
        "updated_at":  time.time(),
        "labels":      {str(k): v for k, v in labels.items()},
    }
    try:
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _build_face_clusters_info(run_id: str, rows: list[dict]) -> dict:
    """Build the {clusters: [...], labels: {...}} block for the
    results-page payload.

    Each cluster entry has:
        id           run-scoped int (>= 0 for real clusters, -1 = noise)
        n_photos     distinct photos that contain at least one face
                     with this cluster id
        n_faces      total face count across the batch with this id
        sample_filenames  up to 5 filenames for thumbnail samples
        label        user-supplied label (may be "")
        suggested_label   V22.2 — auto-inherited from prior runs when
                          this cluster's centroid matches a labeled
                          library entry. Shape: {label, similarity}
                          or None.
    """
    labels = _load_face_labels(run_id)
    # Build distinct-photo + total-face counts per cluster.
    cluster_counts: dict[int, dict] = {}
    for r in rows:
        cs = r.get("face_clusters") or []
        if not cs:
            continue
        # First record total face count
        for cid in cs:
            d = cluster_counts.setdefault(cid, {
                "id":               cid,
                "n_photos":         0,
                "n_faces":          0,
                "sample_filenames": [],
            })
            d["n_faces"] += 1
        # Then distinct-photo counting (use a set per row to dedupe
        # photos that contain the same person twice — siblings, mirror
        # shots — from inflating n_photos)
        fn = r.get("filename", "")
        for cid in set(cs):
            d = cluster_counts.setdefault(cid, {
                "id":               cid,
                "n_photos":         0,
                "n_faces":          0,
                "sample_filenames": [],
            })
            d["n_photos"] += 1
            if fn and len(d["sample_filenames"]) < 5:
                d["sample_filenames"].append(fn)

    # V22.2 — attempt cross-run label inheritance via centroid match.
    # Loads this run's per-cluster centroids (saved by face_clustering
    # post-pass), compares against the active user's face library,
    # and emits a suggested_label when sim >= SUGGEST_THRESHOLD.
    suggestions: dict[int, dict] = {}
    try:
        from pixcull.pipeline.face_library import (
            load_run_centroids, suggest_labels,
        )
        from pixcull.users import get_active_user, user_root
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run and run.get("output_dir"):
            run_centroids = load_run_centroids(Path(run["output_dir"]))
            if run_centroids is not None:
                cluster_ids_arr, centroids = run_centroids
                ulib = user_root(get_active_user())
                suggs = suggest_labels(centroids, ulib)
                for cid_int, sugg in zip(cluster_ids_arr.tolist(), suggs):
                    if sugg is not None:
                        suggestions[int(cid_int)] = {
                            "label":      sugg[0],
                            "similarity": float(round(sugg[1], 3)),
                        }
    except Exception as exc:  # noqa: BLE001
        # Non-essential. Surface but don't fail the request.
        print(f"[face_clusters_info] V22.2 suggest skipped: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)

    # Attach labels + sort by n_photos desc (noise/-1 always last).
    out: list[dict] = []
    for cid, d in cluster_counts.items():
        d["label"] = labels.get(cid, "")
        # V22.2 — suggested_label from cross-run centroid match.
        # Only shown when there's no user-set label for this cluster
        # (user override always wins).
        if cid >= 0 and not d["label"] and cid in suggestions:
            d["suggested_label"] = suggestions[cid]
        out.append(d)
    out.sort(key=lambda d: (d["id"] < 0, -d["n_photos"]))
    return {
        "clusters": out,
        "n_noise":  cluster_counts.get(-1, {}).get("n_photos", 0),
    }


# ---------------------------------------------------------------------------
# V23 — location cluster summary for the travel-persona UI.
# Reads gps_cluster_id from already-loaded rows, computes centroid +
# n_photos + per-cluster "best" filename. No persistence layer yet
# (location labels — "Notre Dame" / "我家" — are V23.1 work; reverse
# geocoding goes beyond V23 scope).
# ---------------------------------------------------------------------------

# V23.1 — per-run location labels. Same shape as face labels (V22.1):
# {cluster_id: "Notre Dame" / "我家" / ...}, stored at
# <output_dir>/location_labels.json. Pattern mirrors face labels
# exactly so the UI code can reuse the same inline-edit flow.

def _location_labels_path(run_id: str) -> Path | None:
    run = _get_run(run_id) or _reload_run_from_disk(run_id)
    if run is None:
        return None
    od = run.get("output_dir")
    if not od:
        return None
    return Path(od) / "location_labels.json"


def _load_location_labels(run_id: str) -> dict[int, str]:
    p = _location_labels_path(run_id)
    if p is None or not p.exists():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    labels = data.get("labels") or {}
    out: dict[int, str] = {}
    for k, v in labels.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return out


def _save_location_labels(run_id: str, labels: dict[int, str]) -> bool:
    p = _location_labels_path(run_id)
    if p is None:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema":     "pixcull.location_labels.v1",
        "run_id":     run_id,
        "updated_at": time.time(),
        "labels":     {str(k): v for k, v in labels.items()},
    }
    try:
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _build_locations_info(rows: list[dict],
                              run_id: str | None = None) -> dict:
    """Build the {clusters: [...], n_no_gps} block for the results
    payload + the /locations endpoint.

    Each cluster entry:
        id              run-scoped int
        n_photos        photos in this cluster
        center_lat,
        center_lon      unweighted mean of member coords
        best_filename   highest score_final photo in the cluster
        best_score      that photo's final score
        sample_filenames first up-to-5 filenames (for thumbnails)
        label           V23.1 — user-supplied location name (may be "")
    """
    cluster_acc: dict[int, dict] = {}
    n_no_gps = 0
    for r in rows:
        cid = r.get("gps_cluster_id")
        if cid is None:
            n_no_gps += 1
            continue
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            n_no_gps += 1
            continue
        d = cluster_acc.setdefault(cid_int, {
            "id":               cid_int,
            "n_photos":         0,
            "lats":             [],
            "lons":             [],
            "sample_filenames": [],
            "best_score":       -1.0,
            "best_filename":    "",
        })
        d["n_photos"] += 1
        lat = r.get("gps_lat")
        lon = r.get("gps_lon")
        if lat is not None and lon is not None:
            d["lats"].append(float(lat))
            d["lons"].append(float(lon))
        fn = r.get("filename", "")
        if fn and len(d["sample_filenames"]) < 5:
            d["sample_filenames"].append(fn)
        sf = r.get("score_final")
        if sf is not None:
            try:
                sf_f = float(sf)
            except (TypeError, ValueError):
                sf_f = -1.0
            if sf_f > d["best_score"]:
                d["best_score"] = sf_f
                d["best_filename"] = fn

    # V23.1 — attach user-supplied location labels.
    labels = _load_location_labels(run_id) if run_id else {}

    clusters: list[dict] = []
    for d in cluster_acc.values():
        if d["lats"]:
            d["center_lat"] = sum(d["lats"]) / len(d["lats"])
            d["center_lon"] = sum(d["lons"]) / len(d["lons"])
        else:
            d["center_lat"] = None
            d["center_lon"] = None
        d.pop("lats", None)
        d.pop("lons", None)
        d["label"] = labels.get(d["id"], "")
        clusters.append(d)
    clusters.sort(key=lambda d: -d["n_photos"])
    return {
        "clusters":  clusters,
        "n_no_gps":  n_no_gps,
        "n_total":   len(rows),
    }


# ---------------------------------------------------------------------------
# V2.1 retrain worker — invokes build_axis_training_set + train_axis_rescorers
# as Python imports (faster than shelling out, and we get exceptions back).
# Updates _RETRAIN_STATE so the admin UI can poll progress.
# ---------------------------------------------------------------------------
def _retrain_in_background(include_auto: bool, also_goldenset: bool) -> None:
    """Background worker for /retrain. Never raises."""
    global _RETRAIN_STATE
    try:
        with _RUNS_LOCK:
            _RETRAIN_STATE = {
                "state": "running",
                "phase": "collecting training data",
                "started_at": time.time(),
            }

        # Step 1: build training_axis.csv. Reuse the script's main-style
        # logic by calling its helpers directly.
        import sys as _sys
        scripts_dir = Path(__file__).parent.resolve()
        if str(scripts_dir) not in _sys.path:
            _sys.path.insert(0, str(scripts_dir))
        # Defer imports until inside the worker so we don't block startup
        # on sklearn loading. ImportError here is reported via state.
        from build_axis_training_set import _gather_run, AXIS_NAMES  # type: ignore
        import pandas as pd

        all_rows: list[dict] = []
        n_with_human = 0
        for run_dir in sorted(_DEMO_ROOT.iterdir()):
            if not run_dir.is_dir():
                continue
            if not (len(run_dir.name) == 10 and
                    all(c in "0123456789abcdef" for c in run_dir.name)):
                continue
            rows = _gather_run(run_dir)
            if not rows:
                continue
            had_human = any(
                any(r.get(f"target_{ax}_source") == "human" for ax in AXIS_NAMES)
                for r in rows
            )
            if had_human:
                n_with_human += 1
            all_rows.extend(rows)

        # Optional goldenset warm-start
        gs_csv = Path.home() / "Pictures/pixcull-goldenset/_eval_output/scores.csv"
        gt_csv = Path.home() / "Pictures/pixcull-goldenset/ground_truth.csv"
        if also_goldenset and gs_csv.exists() and gt_csv.exists():
            with _RUNS_LOCK:
                _RETRAIN_STATE["phase"] = "loading goldenset warm-start"
            gs = pd.read_csv(gs_csv)
            gt = pd.read_csv(gt_csv, comment="#")
            gt = gt[gt["manual_label"].isin(["keep", "maybe", "cull"])]
            merged = gs.merge(gt[["filename", "manual_label"]],
                              on="filename", how="inner")
            from build_axis_training_set import (  # type: ignore
                FEATURE_COLS_NUMERIC, FEATURE_COLS_CATEGORICAL,
            )
            for _, r in merged.iterrows():
                row: dict = {
                    "filename": r["filename"],
                    "_run_id": "goldenset_warmstart",
                }
                for col in FEATURE_COLS_NUMERIC + FEATURE_COLS_CATEGORICAL:
                    row[col] = r.get(col)
                # Prefer per-axis stars from V2.0 columns; fall back to
                # the coarse keep/maybe/cull → 5/3/1 mapping.
                label_to_stars = {"keep": 5.0, "maybe": 3.0, "cull": 1.0}
                fallback = label_to_stars.get(r["manual_label"], 3.0)
                for axis in AXIS_NAMES:
                    auto_v = r.get(f"rubric_{axis}_stars")
                    row[f"target_{axis}"] = (
                        float(auto_v) if pd.notna(auto_v) else fallback
                    )
                    row[f"target_{axis}_source"] = (
                        "goldenset_v2" if pd.notna(auto_v) else "goldenset"
                    )
                all_rows.append(row)

        if not all_rows:
            with _RUNS_LOCK:
                _RETRAIN_STATE = {
                    "state": "error",
                    "message": "没有训练数据 — 先标几张或开 also_goldenset",
                    "finished_at": time.time(),
                }
            return

        df = pd.DataFrame(all_rows)
        if not include_auto:
            human_mask = pd.Series(False, index=df.index)
            for axis in AXIS_NAMES:
                human_mask |= (df[f"target_{axis}_source"] == "human")
            df = df[human_mask]
        if df.empty:
            with _RUNS_LOCK:
                _RETRAIN_STATE = {
                    "state": "error",
                    "message": "过滤后无训练数据,试试 include_auto=true",
                    "finished_at": time.time(),
                }
            return

        # Persist + train
        with _RUNS_LOCK:
            _RETRAIN_STATE.update({
                "phase": f"training on {len(df)} rows",
                "n_rows": len(df),
            })

        # Use a stable on-disk path so the user can inspect what was
        # trained — keeps the audit story straight.
        repo_root = Path(__file__).parent.parent
        training_csv = repo_root / "training_axis.csv"
        df.to_csv(training_csv, index=False)

        # Now train. Import the trainer's helpers and invoke per axis.
        from train_axis_rescorers import train_one_axis  # type: ignore
        out_dir = repo_root / "models"
        results = []
        for axis in AXIS_NAMES:
            with _RUNS_LOCK:
                _RETRAIN_STATE["phase"] = f"training axis: {axis}"
            r = train_one_axis(df, axis, out_dir, cv=5, seed=42, min_rows=20)
            if r is not None:
                results.append(r)

        # Save meta JSON (matches train_axis_rescorers.py)
        from pixcull.scoring.axis_rescorer import axis_meta_path
        meta = {
            "created_at": pd.Timestamp.now("UTC").isoformat(),
            "training_csv": str(training_csv.resolve()),
            "n_rows_in_csv": len(df),
            "axes": results,
            "seed": 42,
            "cv": 5,
            "n_runs_with_human": n_with_human,
        }
        axis_meta_path(out_dir).write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        with _RUNS_LOCK:
            _RETRAIN_STATE = {
                "state": "done",
                "started_at": _RETRAIN_STATE.get("started_at"),
                "finished_at": time.time(),
                "axes": results,
                "n_rows": len(df),
                "message": f"训练完成 {len(results)}/{len(AXIS_NAMES)} 轴",
            }

    except Exception as exc:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        with _RUNS_LOCK:
            _RETRAIN_STATE = {
                "state": "error",
                "message": f"训练失败: {type(exc).__name__}: {exc}",
                "finished_at": time.time(),
            }


# ---------------------------------------------------------------------------
# Storage admin: enumerate runs on disk, compute sizes, delete safely.
#
# We always derive the run list from the filesystem (not _RUNS) so that
# runs from a previous server session — which never made it into the
# in-memory dict — are still listed and prunable. The dict's metadata
# (started/finished_at, decisions) is layered in when present.
# ---------------------------------------------------------------------------
def _dir_size_bytes(p: Path) -> int:
    total = 0
    try:
        for f in p.rglob("*"):
            try:
                if f.is_file() and not f.is_symlink():
                    total += f.stat().st_size
            except OSError as exc:
                _dbg("_dir_size_bytes/stat", exc, str(f))
                continue
    except OSError as exc:
        _dbg("_dir_size_bytes/rglob", exc, str(p))
    return total


def _enumerate_runs() -> list[dict]:
    """List every directory under ``_DEMO_ROOT`` that looks like a run.

    A "run" is any first-level subdir whose name is a 10-char hex string
    (matches our ``_new_run_id()`` format). Anything else under
    ``_DEMO_ROOT`` is left alone — we never delete what we didn't create.
    """
    out: list[dict] = []
    if not _DEMO_ROOT.exists():
        return out
    for child in sorted(_DEMO_ROOT.iterdir(), key=lambda x: x.name):
        if not child.is_dir():
            continue
        # Heuristic: 10-char hex matches our run_id pattern.
        if not (len(child.name) == 10 and all(c in "0123456789abcdef" for c in child.name)):
            continue

        run_id = child.name
        input_dir = child / "input"
        output_dir = child / "output"
        scores_csv = output_dir / "scores.csv"

        n_input = 0
        if input_dir.exists():
            n_input = sum(1 for f in input_dir.iterdir() if f.is_file())

        # Pull decision counts from scores.csv (cheap CSV parse, no pandas)
        decisions = {"keep": 0, "maybe": 0, "cull": 0}
        if scores_csv.exists():
            try:
                import csv
                with open(scores_csv, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        d = row.get("decision", "")
                        if d in decisions:
                            decisions[d] += 1
            except (OSError, csv.Error) as exc:
                _dbg("_enumerate_runs/scores.csv", exc, str(scores_csv))

        # Modification time of the run dir = "last touched"; useful for
        # the older-than-N-hours policy.
        try:
            mtime = child.stat().st_mtime
        except OSError:
            mtime = 0

        # Pick up live state from the in-memory dict if this run is from
        # the current server session.
        live = _get_run(run_id) or {}

        # Detect mode from manifest.json — scan-mode runs leave one
        # behind, upload-mode runs don't. Lets the admin UI distinguish
        # "delete this also wipes uploaded copies" from "delete only
        # touches our /tmp output, originals stay put".
        manifest_path = output_dir / "manifest.json"
        mode = live.get("mode")
        if mode is None:
            mode = "scan" if manifest_path.exists() else "upload"

        # In scan mode n_input doesn't exist on disk (we don't copy);
        # pull the count from the manifest instead so the admin table
        # still has something useful to show.
        if mode == "scan" and manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text("utf-8"))
                n_input = len(manifest)
            except (OSError, json.JSONDecodeError) as exc:
                _dbg("_enumerate_runs/manifest", exc, str(manifest_path))

        out.append({
            "run_id": run_id,
            "mode": mode,
            "size_bytes": _dir_size_bytes(child),
            "n_input": n_input,
            "decisions": decisions,
            "state": live.get("state", "stale" if not scores_csv.exists() else "done"),
            "mtime": mtime,
            "age_seconds": max(0, int(time.time() - mtime)) if mtime else None,
            "started_at": live.get("started_at"),
            "finished_at": live.get("finished_at"),
        })
    # Newest first — that's what the user will scan visually.
    out.sort(key=lambda r: -(r["mtime"] or 0))
    return out


def _reload_run_from_disk(run_id: str) -> dict | None:
    """Reconstruct minimal run metadata when a thumbnail is requested
    after a server restart. Reads ``output/manifest.json`` if present
    (scan mode) and the basic dir layout otherwise.
    """
    if not run_id or not run_id.replace("_", "").replace("-", "").isalnum():
        return None
    run_root = _DEMO_ROOT / run_id
    if not run_root.is_dir():
        return None
    output_dir = run_root / "output"
    input_dir = run_root / "input"
    manifest_path = output_dir / "manifest.json"
    info: dict = {
        "output_dir": str(output_dir),
    }
    if manifest_path.exists():
        info["mode"] = "scan"
        info["input_dir"] = ""  # n/a in scan mode
        try:
            info["files_manifest"] = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            info["files_manifest"] = {}
    elif input_dir.is_dir():
        info["mode"] = "upload"
        info["input_dir"] = str(input_dir)
    else:
        return None
    return info


def _resolve_image_source(run: dict, filename: str) -> Path | None:
    """Find the absolute on-disk path of ``filename`` within a run.

    In upload mode the file lives under ``input_dir/<filename>``. In scan
    mode we consult the manifest (preferred — exact original location)
    or fall back to scanning ``source_dir`` for a basename match.
    """
    mode = run.get("mode")
    if mode == "scan":
        # Try the in-memory dict first (set when run started this session)
        manifest = run.get("files_manifest")
        if not manifest:
            # Fall through to disk
            mp = Path(run["output_dir"]) / "manifest.json"
            if mp.exists():
                try:
                    manifest = json.loads(mp.read_text("utf-8"))
                except (OSError, json.JSONDecodeError):
                    manifest = {}
        if manifest:
            p = manifest.get(filename)
            if p:
                return Path(p)
        # Last resort: walk source_dir looking for the filename
        src_dir = Path(run.get("source_dir") or run.get("origin_folder") or "")
        if src_dir.is_dir():
            for f in src_dir.rglob(filename):
                return f
        return None
    # upload mode (default)
    input_dir = run.get("input_dir") or ""
    if input_dir:
        candidate = Path(input_dir) / filename
        return candidate if candidate.exists() else None
    return None


def _delete_run(run_id: str) -> tuple[bool, str]:
    """Best-effort delete of a single run dir. Returns (ok, message).

    Refuses to touch anything outside ``_DEMO_ROOT`` — defense in depth
    against a maliciously crafted run_id like ``../etc``. Also drops the
    in-memory state so a subsequent ``/status/<id>`` reports 404.
    """
    if not run_id or not run_id.replace("_", "").replace("-", "").isalnum():
        return False, "invalid run_id"
    target = (_DEMO_ROOT / run_id).resolve()
    try:
        # Refuse if resolution escaped _DEMO_ROOT (symlink trickery, etc.)
        target.relative_to(_DEMO_ROOT.resolve())
    except ValueError:
        return False, "run_id resolves outside demo root"
    if not target.exists():
        return False, "no such run"

    try:
        shutil.rmtree(target)
    except OSError as exc:
        return False, f"rmtree failed: {exc}"

    with _RUNS_LOCK:
        _RUNS.pop(run_id, None)
    return True, "deleted"


# Global model cache directories the user might want to know about — these
# are *machine-wide* and not deleted by run cleanup, but listing them on
# the storage page makes the "where's my disk going" question answerable.
_GLOBAL_CACHES = [
    ("torch hub", Path.home() / ".cache" / "torch"),
    ("HuggingFace", Path.home() / ".cache" / "huggingface"),
]


def _storage_info() -> dict:
    runs = _enumerate_runs()
    runs_total = sum(r["size_bytes"] for r in runs)
    caches = []
    for label, path in _GLOBAL_CACHES:
        if path.exists():
            caches.append({
                "label": label,
                "path": str(path),
                "size_bytes": _dir_size_bytes(path),
            })
    return {
        "demo_root": str(_DEMO_ROOT),
        "runs_total_bytes": runs_total,
        "n_runs": len(runs),
        "runs": runs,
        "global_caches": caches,
    }


# ---------------------------------------------------------------------------
# HTTP handler.
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "PixCullDemo/1.2"

    def send_error(self, code: int, message: str | None = None,
                    explain: str | None = None) -> None:
        """Override stdlib send_error to handle non-ASCII messages.

        BaseHTTPRequestHandler.send_response_only() encodes the HTTP
        status line as latin-1; any em-dash / Chinese / etc. character
        crashes the request thread mid-response with UnicodeEncodeError,
        which has cascaded into '查看结果按钮整个崩溃' before this fix.
        We strip the message to ASCII for the status line and stash the
        original (Unicode-safe) text in the JSON body that's already
        ASCII-only HTTP-headers + utf-8 payload.
        """
        if message is None:
            message = "error"
        # ASCII-safe status reason phrase (per RFC 7230 §3.1.2)
        ascii_msg = message.encode("ascii", "ignore").decode("ascii") or "error"
        # Body carries the original message in UTF-8 JSON
        try:
            body = json.dumps(
                {"code": code, "error": message, "explain": explain or ""},
                ensure_ascii=False,
            ).encode("utf-8")
        except Exception:
            body = json.dumps({"code": code, "error": ascii_msg}).encode("utf-8")
        try:
            self.send_response(code, ascii_msg)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception:
            # Last-resort: don't let secondary failures crash the worker
            pass

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- V25 /api/v1/ dispatch ---------------------------------------------
    # Routes under /api/v1/ are designed for programmatic consumption:
    # mobile apps, third-party tools, the Lightroom plugin's future
    # cross-machine support. All return clean JSON (no HTML) and carry
    # CORS headers from end_headers() above.
    #
    # Most routes are thin aliases over the existing handlers; the
    # unique additions are the discovery endpoint and the mobile-friendly
    # summary endpoints (``/runs/<id>`` returns a single JSON doc
    # describing the run + linking to its specific assets).
    def _dispatch_api_v1_get(self, path: str) -> bool:
        """Returns True if the request was handled. Caller falls through
        to legacy routes (or 404) when this returns False."""
        sub = path[len("/api/v1"):]
        if sub in ("", "/"):
            return self._serve_api_v1_index()
        if sub == "/runs":
            return self._serve_runs_list_json_api()
        if sub == "/verticals":
            self._serve_verticals_json(); return True
        if sub == "/storage_info":
            self._serve_storage_info(); return True
        if sub == "/rubric_meta":
            self._serve_rubric_meta(); return True
        # P-UX-4 — stable enum advertisement so clients (iOS,
        # third-party) populate the reject-reason picker without
        # hardcoding the token list. Currently exposes cull_reasons
        # + their default zh-CN labels; will grow as more taxonomies
        # appear (style_modes, scenes, etc.).
        if sub == "/taxonomy":
            return self._serve_api_v1_taxonomy()
        # v0.8-P0-1 — i18n locale fetcher.
        # GET /api/v1/locale?lang=en_US → {lang, strings: {...}}
        if sub == "/locale":
            return self._serve_api_v1_locale()
        # v0.8-P0-2 — LAN sync change-list polling.
        # GET /api/v1/sync/event/<token>/changes?since=<ms>
        #   → {schema, run_id, server_ts, annotations: [...]}
        if sub.startswith("/sync/event/") and sub.endswith("/changes"):
            token = sub[len("/sync/event/"):-len("/changes")]
            return self._serve_sync_event_changes(token)
        # P-UX-9 — accumulated cull-reason counts so the picker can
        # sort by user frequency + admin can show "your cull habits".
        if sub == "/cull_reasons/stats":
            return self._serve_api_v1_cull_reason_stats()
        # P-UX-12 — per-user taste profile (scene preferences, axis
        # weights inferred from history, cull-reason distribution).
        if sub == "/users/preferences":
            return self._serve_api_v1_user_preferences()
        # P-AI-1 — personalized keep/maybe threshold profile.
        # Reads /users/preferences then derives a small shift to the
        # global thresholds based on the user's historical keep-rate
        # vs the baseline 0.65.
        if sub == "/users/profile":
            return self._serve_api_v1_user_profile()
        # INFRA-4 — daily LLM spend ledger
        if sub == "/llm_budget":
            return self._serve_llm_budget()
        # INFRA-2 — multi-machine sync status
        if sub == "/sync_status":
            return self._serve_sync_status()
        # P2.2 — list active tether sessions
        if sub == "/tether":
            return self._serve_tether_list()
        # V28 — user / team profile endpoints
        if sub == "/users":
            return self._serve_users_list()
        if sub == "/users/active":
            return self._serve_users_active()
        # /runs/<id> and its sub-resources
        if sub.startswith("/runs/"):
            tail = sub[len("/runs/"):]
            # /runs/<id> (no further path) → run summary
            if "/" not in tail:
                return self._serve_api_v1_run_summary(tail)
            run_id, rest = tail.split("/", 1)
            if rest == "decisions":
                self._serve_decisions(run_id); return True
            if rest == "face_clusters":
                self._serve_face_clusters(run_id); return True
            if rest == "locations":
                self._serve_locations(run_id); return True
            if rest == "status":
                self._serve_status(run_id); return True
            if rest == "scores.csv":
                self._serve_scores_csv(run_id); return True
            if rest == "gallery.zip" or rest.startswith("gallery.zip?"):
                # Strip /api/v1/runs/<id>/gallery.zip → ``run_id`` +
                # optional ``?include=keep,maybe``. Re-attach the query
                # string the way ``_serve_gallery_zip`` expects.
                qs = ""
                if "?" in rest:
                    _, qs = rest.split("?", 1)
                self._serve_gallery_zip(f"{run_id}?{qs}" if qs else run_id)
                return True
            if rest == "xmp.zip":
                self._serve_xmp_zip(run_id); return True
            # P2.1 V0.2 — paginated rows for the mobile photo grid.
            # ``?limit=N&offset=K`` (defaults 200 / 0). Slim row shape
            # — only the fields the iOS grid + lightbox render —
            # so a 1500-photo wedding doesn't ship 5MB of advice text
            # the mobile UI doesn't use.
            if rest == "rows":
                qs = urlparse(self.path).query
                return self._serve_api_v1_rows(run_id, qs)
            # V0.3 — single rich row for the iOS lightbox info panel.
            # Strips nothing, so callers see advice + rubric_stars +
            # gps_lat/lon + face_clusters etc. URL-encoded filename
            # because mobile-shot photos often have spaces / non-ASCII.
            if rest.startswith("row/"):
                fn = rest[len("row/"):]
                return self._serve_api_v1_row(run_id, fn)
            # P-AI-2 — text→image CLIP semantic search
            if rest == "semantic_search":
                qs = urlparse(self.path).query
                return self._serve_api_v1_semantic_search(run_id, qs)
            # P-UX-5 — composite-similarity nearest-neighbor lookup
            # ("show me photos like this one") for the lightbox's
            # similar-photos row. Returns up to k=5 by default.
            if rest.startswith("similar/"):
                fn = rest[len("similar/"):]
                qs = urlparse(self.path).query
                return self._serve_api_v1_similar(run_id, fn, qs)
            # P2.4 — active-learning queue (batch). Accepts ?n=N.
            # urlparse already stripped the query string from ``path``
            # in the caller; read it back off ``self.path`` so we
            # forward it to _serve_next_to_label.
            if rest == "next_to_label":
                qs = urlparse(self.path).query
                rel = f"{run_id}?{qs}" if qs else run_id
                self._serve_next_to_label(rel); return True
        return False

    def _dispatch_api_v1_post(self, path: str) -> bool:
        sub = path[len("/api/v1"):]
        if sub == "/scan_local":
            self._handle_scan_local(); return True
        if sub == "/analyze":
            self._handle_analyze_post(); return True
        # V28 — user management
        if sub == "/users":
            return self._handle_users_create()
        # INFRA-2 — explicit "configure sync now" trigger
        if sub == "/sync_configure":
            return self._handle_sync_configure()
        # INFRA-3 — multi-shooter event merge
        if sub == "/events/merge":
            return self._handle_event_merge()
        # P2.2 — tether session start / stop
        if sub == "/tether/start":
            return self._handle_tether_start()
        if sub.startswith("/tether/") and sub.endswith("/stop"):
            sid = sub[len("/tether/"):-len("/stop")]
            return self._handle_tether_stop(sid)
        # V28.2 — switch active user via cookie (no restart needed)
        if sub == "/users/active":
            return self._handle_users_active_post()
        if sub.startswith("/users/") and sub.endswith("/team_subscribe"):
            uid = sub[len("/users/"):-len("/team_subscribe")]
            return self._handle_team_subscribe(uid)
        if sub.startswith("/runs/"):
            tail = sub[len("/runs/"):]
            if "/" in tail:
                run_id, rest = tail.split("/", 1)
                if rest == "face_clusters/label":
                    self._handle_face_label_post(run_id); return True
                if rest == "locations/label":
                    self._handle_location_label_post(run_id); return True
                if rest == "export":
                    self._handle_export(run_id); return True
                if rest == "auto_caption":
                    self._handle_auto_caption(run_id); return True
                # P-UX-15 — pull edits from Lr/C1 XMP sidecars back
                # into PixCull annotations (round-trip).
                if rest == "lr_sync":
                    return self._handle_lr_sync(run_id)
                # P2.1 V0.2 — annotation alias for the iOS swipe-to-
                # label flow. Forwards to the existing
                # ``_handle_save_annotation`` which takes "run/filename".
                if rest.startswith("annotate/"):
                    fn = rest[len("annotate/"):]
                    self._handle_save_annotation(f"{run_id}/{fn}")
                    return True
        return False

    def _serve_api_v1_index(self) -> bool:
        """V25 discovery endpoint. Returns the route map + version info
        so mobile / third-party clients can introspect without scraping
        the source.
        """
        body = _safe_dumps({
            "schema":   "pixcull.api.v1.index",
            "version":  "v1",
            "server":   "PixCull",
            "auth": {
                "model":            "localhost-free + optional API key",
                "api_key_header":   "X-PixCull-API-Key",
                "api_key_env":      "PIXCULL_API_KEY",
                "is_localhost":     self.client_address[0] in
                                     ("127.0.0.1", "::1", "localhost"),
            },
            "cors": {
                "origins_env": "PIXCULL_API_CORS_ORIGINS",
                "current":     (os.environ.get("PIXCULL_API_CORS_ORIGINS")
                                or "*"),
            },
            "endpoints": [
                {"method": "GET",  "path": "/api/v1/",
                 "doc":    "this discovery index"},
                {"method": "GET",  "path": "/api/v1/runs",
                 "doc":    "list runs with summary"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>",
                 "doc":    "summary of one run + asset URLs"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/rows",
                 "params": {"limit": "200 (default)", "offset": "0 (default)"},
                 "doc":    "paginated slim row list for mobile photo grid"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/row/<filename>",
                 "doc":    "single rich row (V20 advice + rubric stars + "
                          "GPS + face clusters) for the iOS lightbox"},
                # P-AI-2 — CLIP-backed text→image semantic search
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/semantic_search",
                 "params": {"q":  "free-text query (e.g. 'flying bird' / 'long-exposure waterfall' / 飞鸟展翅)",
                            "k":  "10 (default), max 50"},
                 "doc":    "rank photos by CLIP cosine similarity to "
                          "the query. Lazy-builds embeddings.npz "
                          "on first hit (slow first call, fast after)."},
                # P-UX-5 — composite-similarity nearest-neighbor
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/similar/<filename>",
                 "params": {"k": "5 (default), max 20"},
                 "doc":    "top-k visually-similar photos for the "
                          "lightbox 'similar' row. Composite score "
                          "over burst+scene+face+GPS+rubric."},
                # INFRA-3 — multi-shooter event merge (MVP)
                {"method": "POST", "path": "/api/v1/events/merge",
                 "body":   "{source_runs: [run_id, ...], name?: str}",
                 "doc":    "concatenate ≥ 2 source runs into a merged "
                          "event run; reuses /results UI"},
                # P-UX-15 — read Lr/C1 XMP edits back into annotations
                {"method": "POST", "path": "/api/v1/runs/<run_id>/lr_sync",
                 "doc":    "scan each photo's XMP sidecar; treat "
                          "xmp:Rating as authoritative human verdict "
                          "(5/4→keep, 3→maybe, 2/1→cull, 0→skip); "
                          "append per-row annotations for changes"},
                {"method": "POST", "path": "/api/v1/runs/<run_id>/annotate/<filename>",
                 "body":   "{overall_label: keep|maybe|cull, "
                          "axes?: {}, overall_rationale?: str, "
                          "cull_reason?: <token from /api/v1/taxonomy>}",
                 "doc":    "save a human annotation for a single photo "
                          "(append-only; latest wins on read)"},
                # P-UX-4 — taxonomy advertisement so iOS / future clients
                # can populate the cull-reason picker without hardcoding
                # the token list. ASCII tokens are stable; localized
                # labels live in the UI layer.
                {"method": "GET",  "path": "/api/v1/taxonomy",
                 "doc":    "stable enums: cull_reasons (+future labels)"},
                # P-UX-9 — usage stats over the user's annotations history
                {"method": "GET",  "path": "/api/v1/cull_reasons/stats",
                 "doc":    "accumulated cull-reason counts across all runs"},
                # P-UX-12 — per-user taste profile
                {"method": "GET",  "path": "/api/v1/users/preferences",
                 "doc":    "scene + axis + cull-reason profile derived "
                          "from your annotation history (admin page card)"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/decisions",
                 "doc":    "{filename: keep|maybe|cull} + src_paths"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/face_clusters",
                 "doc":    "face cluster summary + labels"},
                {"method": "POST", "path": "/api/v1/runs/<run_id>/face_clusters/label",
                 "body":   "{cluster_id: int, label: str}",
                 "doc":    "rename a face cluster"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/locations",
                 "doc":    "GPS location cluster summary"},
                {"method": "POST", "path": "/api/v1/runs/<run_id>/locations/label",
                 "body":   "{cluster_id: int, label: str}",
                 "doc":    "rename a GPS location cluster (V23.1)"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/status",
                 "doc":    "pipeline progress JSON"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/scores.csv",
                 "doc":    "scores.csv download"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/gallery.zip",
                 "params": {"include": "keep | keep,maybe | keep,maybe,cull"},
                 "doc":    "standalone HTML gallery zip"},
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/xmp.zip",
                 "doc":    "XMP sidecar zip (run /export first)"},
                {"method": "POST", "path": "/api/v1/runs/<run_id>/export",
                 "doc":    "render XMP sidecars to disk"},
                {"method": "POST", "path": "/api/v1/runs/<run_id>/auto_caption",
                 "body":   "{polish?: bool, decisions?: [keep,...]}",
                 "doc":    "P2.5 — generate IPTC captions per photo. "
                          "compose (free) or polish (DeepSeek, "
                          "INFRA-4-budgeted). Persisted to "
                          "auto_captions.json; next /export uses them."},
                {"method": "POST", "path": "/api/v1/scan_local",
                 "body":   "{folder: abs_path, vertical?: str}",
                 "doc":    "kick off a scan of a local folder"},
                {"method": "POST", "path": "/api/v1/analyze",
                 "doc":    "upload + analyze a multipart batch"},
                {"method": "GET",  "path": "/api/v1/verticals",
                 "doc":    "vertical registry + sample bank progress"},
                {"method": "GET",  "path": "/api/v1/storage_info",
                 "doc":    "disk usage + run count summary"},
                {"method": "GET",  "path": "/api/v1/rubric_meta",
                 "doc":    "rubric axes definition (for annotation UI)"},
                # INFRA-4 — LLM cost ledger
                {"method": "GET",  "path": "/api/v1/llm_budget",
                 "doc":    "daily LLM spend (yuan) + cap from "
                          "PIXCULL_LLM_BUDGET_YUAN env (default 10)"},
                # INFRA-2 — multi-machine sync
                {"method": "GET",  "path": "/api/v1/sync_status",
                 "doc":    "sync target + per-subtree state for "
                          "the active user"},
                {"method": "POST", "path": "/api/v1/sync_configure",
                 "body":   "{user_id?: str, team_id?: str}",
                 "doc":    "wire sync subtrees (symlinks) for a user "
                          "or team to the PIXCULL_SYNC_DIR target"},
                # P2.2 — Lr/C1 tether live-cull
                {"method": "GET",  "path": "/api/v1/tether",
                 "doc":    "list active tether sessions"},
                {"method": "POST", "path": "/api/v1/tether/start",
                 "body":   "{folder: abs_path, vertical?: str}",
                 "doc":    "start a watcher that auto-analyzes new "
                          "files in the tether folder (Lr/C1 tether dest)"},
                {"method": "POST", "path": "/api/v1/tether/<session>/stop",
                 "doc":    "stop a tether session"},
                # P2.4 — active-learning queue
                {"method": "GET",  "path": "/api/v1/runs/<run_id>/next_to_label",
                 "params": {"n": "1 (default) | N for batch queue"},
                 "doc":    "active-learning queue: highest-info-gain "
                          "photos to label next, ranked by rescorer "
                          "disagreement + uncertainty"},
                # V28 multi-user
                {"method": "GET",  "path": "/api/v1/users",
                 "doc":    "list user profiles + active user"},
                {"method": "GET",  "path": "/api/v1/users/active",
                 "doc":    "just the active user id"},
                {"method": "POST", "path": "/api/v1/users",
                 "body":   "{user_id: str}",
                 "doc":    "create user profile (idempotent)"},
                {"method": "POST", "path": "/api/v1/users/<uid>/team_subscribe",
                 "body":   "{vertical: str, team_id: str|''}",
                 "doc":    "redirect a user's vertical bank to a team's; "
                          "empty team_id unsubscribes"},
            ],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_runs_list_json_api(self) -> bool:
        """V25 — clean JSON run list (no HTML). The pre-existing
        ``/runs`` endpoint already returns JSON (via _enumerate_runs);
        this is the versioned alias with the standard envelope shape.
        """
        runs = _enumerate_runs()
        body = _safe_dumps({
            "schema":  "pixcull.api.v1.runs.list",
            "n_runs":  len(runs),
            "runs":    runs,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_rows(self, run_id: str, qs: str) -> bool:
        """P2.1 V0.2 — paginated rows for the iOS photo grid.

        URL: GET /api/v1/runs/<run_id>/rows[?limit=N&offset=K]
        Default ``limit=200``, ``offset=0``. Hard-capped at 1000 so
        a typo can't ship a 50MB blob.

        Slim row shape — strip the heavy ``advice`` blob (~2 KB/row),
        ``rubric_stars``, ``scene_probs``, etc. The iOS V0.2 grid + swipe
        annotator only needs filename, decision, score_final, scene,
        cluster_id, is_burst_peak. When the user opens the lightbox
        we re-fetch a single row via /results JSON (already implemented).
        """
        result = _build_results(run_id)
        if result is None:
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(404, "no such run"); return True
            self.send_error(425, "results not ready"); return True
        rows, _summary = result

        from urllib.parse import parse_qs
        qparams = parse_qs(qs) if qs else {}
        try:
            limit = int(qparams.get("limit", ["200"])[0])
            offset = int(qparams.get("offset", ["0"])[0])
        except (ValueError, TypeError):
            limit, offset = 200, 0
        limit = max(1, min(1000, limit))
        offset = max(0, offset)

        # Slim each row to the iOS-grid essentials. ``filename`` is
        # the primary key the grid renders; the rest is decoration.
        page = []
        for r in rows[offset:offset + limit]:
            page.append({
                "filename":      r.get("filename"),
                "decision":      r.get("decision"),
                "score_final":   r.get("score_final"),
                "scene":         r.get("scene"),
                "cluster_id":    r.get("cluster_id"),
                "is_burst_peak": bool(r.get("is_burst_peak")),
                "rubric_human_labeled": bool(r.get("rubric_human_labeled")),
                # P-UX-4 — empty unless the row carries an annotated
                # reject reason. iOS V0.4+ can show this as a small
                # chip on the swipe card without re-fetching the row.
                "cull_reason":   str(r.get("cull_reason") or ""),
            })

        body = _safe_dumps({
            "schema":  "pixcull.api.v1.rows.v1",
            "run_id":  run_id,
            "n_total": len(rows),
            "offset":  offset,
            "limit":   limit,
            "rows":    page,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_semantic_search(self, run_id: str, qs: str) -> bool:
        """P-AI-2 — CLIP text→image semantic search.

        URL: GET /api/v1/runs/<run_id>/semantic_search?q=<text>&k=10

        On first call for a given run, walks every photo, CLIP-encodes
        it, and persists ``output/embeddings.npz`` (~512 floats/photo
        ≈ 2 KB/photo). Subsequent calls reuse the cache and complete
        in single-digit ms.

        Returns ranked list of (filename, similarity) plus a build_ms
        + cached flags so the UI can show "first search builds the
        cache — ~X seconds" feedback.
        """
        from urllib.parse import parse_qs

        result = _build_results(run_id)
        if result is None:
            self.send_error(404, "no such run"); return True
        rows, _ = result

        qparams = parse_qs(qs) if qs else {}
        query = (qparams.get("q", [""])[0] or "").strip()
        if not query:
            self._reject_upload(400, "q (query) is required"); return True
        try:
            k = int(qparams.get("k", ["10"])[0])
        except (ValueError, TypeError):
            k = 10
        k = max(1, min(50, k))

        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run"); return True
        cache_path = Path(run["output_dir"]) / "embeddings.npz"

        from pixcull.scoring.semantic_search import (
            load_embeddings_cache, build_embeddings_cache, search as _semsearch,
        )
        cache = load_embeddings_cache(cache_path)
        was_cached = cache is not None
        build_ms = 0.0
        if cache is None:
            # Resolve absolute image paths from each row's manifest /
            # src_path. We only encode photos whose path is reachable;
            # missing files just get skipped.
            paths: list[Path] = []
            for r in rows:
                fn = r.get("filename")
                src = r.get("src_path")
                if src and Path(src).is_file():
                    paths.append(Path(src))
                else:
                    p = _resolve_image_source(run, fn) if fn else None
                    if p and p.is_file():
                        paths.append(p)
            if not paths:
                self._reject_upload(425,
                    "no reachable photos to build embeddings cache"); return True
            t0 = time.time()
            cache = build_embeddings_cache(paths, cache_path)
            build_ms = (time.time() - t0) * 1000.0

        try:
            ranked = _semsearch(query, cache=cache, k=k)
        except Exception as e:
            self._reject_upload(500, f"search failed: {e}"); return True

        # Enrich with each match's decision + score_final so the UI
        # can show context next to the result rows.
        by_fn = {r.get("filename"): r for r in rows}
        results = []
        for fn, sim in ranked:
            r = by_fn.get(fn) or {}
            results.append({
                "filename":     fn,
                "similarity":   round(sim, 4),
                "decision":     r.get("decision"),
                "score_final":  r.get("score_final"),
                "scene":        r.get("scene"),
            })

        body = _safe_dumps({
            "schema":      "pixcull.api.v1.semantic_search.v1",
            "run_id":      run_id,
            "query":       query,
            "k":           k,
            "cached":      was_cached,
            "build_ms":    round(build_ms, 1),
            "n_photos":    int(cache["vectors"].shape[0]),
            "results":     results,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_similar(self, run_id: str, filename: str, qs: str) -> bool:
        """P-UX-5 — "show me photos like this one" for the lightbox.

        We don't keep raw CLIP embeddings on disk (would be GB-scale
        across runs), but the rubric / scene / cluster / face / GPS
        columns already carry a rich perceptual signature per photo.
        This composes them into a single 0..1 similarity score with
        named reasons so the lightbox can show "why" each match
        surfaced ("same burst", "same person + same scene", etc).

        URL: GET /api/v1/runs/<run_id>/similar/<filename>?k=5

        Response:
          {
            "schema": "pixcull.api.v1.similar.v1",
            "target": "<filename>",
            "k": 5,
            "similar": [
              {"filename": ..., "similarity": 0.87,
               "reasons": ["burst", "same_scene"],
               "decision": "keep", "score_final": 0.72},
              ...
            ]
          }
        """
        result = _build_results(run_id)
        if result is None:
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(404, "no such run"); return True
            self.send_error(425, "results not ready"); return True
        rows, _ = result
        fn = unquote(filename)
        target = next((r for r in rows if r.get("filename") == fn), None)
        if target is None:
            self.send_error(404, f"no such filename: {fn}"); return True

        from urllib.parse import parse_qs
        qparams = parse_qs(qs) if qs else {}
        try:
            k = int(qparams.get("k", ["5"])[0])
        except (ValueError, TypeError):
            k = 5
        k = max(1, min(20, k))

        # Build the perceptual signature for the target then score every
        # OTHER row by composite similarity. Weights chosen so a burst
        # neighbor dominates (it's almost certainly a near-dupe), then
        # face+scene match, then rubric proximity (the long tail).
        t_cluster = target.get("cluster_id")
        t_scene   = (target.get("scene") or "").strip()
        t_faces   = set(target.get("face_clusters") or [])
        t_gps_cid = target.get("gps_cluster_id")
        t_rubric  = target.get("rubric_stars") or {}
        t_aest    = target.get("score_aesthetic")

        def _rubric_proximity(other_rubric: dict) -> float:
            """L1 distance over present axes, mapped to 0..1 similarity."""
            if not other_rubric or not t_rubric:
                return 0.0
            axes = [a for a in t_rubric.keys()
                    if t_rubric.get(a) is not None
                    and other_rubric.get(a) is not None]
            if not axes:
                return 0.0
            dist = sum(
                abs(float(t_rubric[a]) - float(other_rubric[a]))
                for a in axes
            ) / (len(axes) * 4.0)  # max single-axis diff is 5-1 = 4
            return max(0.0, 1.0 - dist)

        candidates: list[tuple[float, list[str], dict]] = []
        for r in rows:
            if r.get("filename") == fn:
                continue
            sim = 0.0
            reasons: list[str] = []
            # Burst neighbor — strongest signal. cluster_id is the
            # already-validated photo-level dedup grouping.
            if (t_cluster is not None
                    and r.get("cluster_id") == t_cluster):
                sim += 0.55
                reasons.append("burst")
            # Same scene token — caps at 0.25 alone, stacks with face/GPS
            o_scene = (r.get("scene") or "").strip()
            if t_scene and o_scene == t_scene:
                sim += 0.18
                reasons.append("same_scene")
            # Face overlap (Jaccard) — same subject across non-burst frames
            o_faces = set(r.get("face_clusters") or [])
            if t_faces and o_faces:
                jacc = len(t_faces & o_faces) / max(1, len(t_faces | o_faces))
                if jacc > 0:
                    sim += 0.22 * jacc
                    reasons.append("same_person")
            # GPS location cluster — same physical spot at this batch
            if (t_gps_cid is not None
                    and r.get("gps_cluster_id") == t_gps_cid):
                sim += 0.10
                reasons.append("same_location")
            # Rubric proximity — the perceptual long tail (composition,
            # light, moment, etc. similar feel).
            r_prox = _rubric_proximity(r.get("rubric_stars") or {})
            if r_prox > 0.5:
                sim += 0.10 * r_prox
                if r_prox > 0.75:
                    reasons.append("similar_rubric")
            # Aesthetic-score proximity — finer-grained tie-breaker.
            o_aest = r.get("score_aesthetic")
            if t_aest is not None and o_aest is not None:
                delta = abs(float(t_aest) - float(o_aest))
                sim += 0.05 * max(0.0, 1.0 - delta)
            if sim > 0.10:  # noise floor — don't surface random matches
                candidates.append((sim, reasons, r))

        candidates.sort(key=lambda c: c[0], reverse=True)
        top = candidates[:k]
        similar = [
            {
                "filename":    r.get("filename"),
                "similarity":  round(sim, 3),
                "reasons":     reasons,
                "decision":    r.get("decision"),
                "score_final": r.get("score_final"),
            }
            for (sim, reasons, r) in top
        ]
        body = _safe_dumps({
            "schema":  "pixcull.api.v1.similar.v1",
            "run_id":  run_id,
            "target":  fn,
            "k":       k,
            "similar": similar,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_locale(self) -> bool:
        """v0.8-P0-1 — return the requested locale's {key: string} map.

        The client (results.html JS shim) calls this when the user
        toggles language; the response is then merged into the
        in-memory I18N map and every ``[data-i18n]`` element is
        re-painted. Cached 5 minutes — locales don't change often.

        Query string: ``?lang=en_US`` (or ``zh-CN`` etc; the i18n
        module normalises). Falls back to zh_CN if unknown.
        """
        from urllib.parse import parse_qs, urlparse as _up
        from pixcull.i18n import (
            DEFAULT_LOCALE,
            SUPPORTED_LOCALES,
            load_locale,
        )

        qs = parse_qs(_up(self.path).query)
        lang_arg = (qs.get("lang") or [DEFAULT_LOCALE])[0]
        strings = load_locale(lang_arg)
        body = _safe_dumps({
            "schema":     "pixcull.api.v1.locale/v1",
            "lang":       lang_arg,
            "supported":  list(SUPPORTED_LOCALES),
            "strings":    strings,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_taxonomy(self) -> bool:
        """P-UX-4 — stable enum advertisement.

        Returns the cull-reason taxonomy (snake_case tokens + zh-CN
        labels) so clients can render a picker without hardcoding
        the list. Adding a token to ``_CULL_REASONS`` and a label
        below is the full change needed for both the web UI and any
        future iOS/CLI client to pick it up.
        """
        labels_zh = {
            "focus_miss":   "焦点不准",
            "eyes_closed":  "闭眼/表情",
            "motion_blur":  "模糊抖动",
            "framing":      "构图差",
            "duplicate":    "与更佳重复",
            "exposure":     "曝光问题",
            "other":        "其他",
        }
        body = _safe_dumps({
            "schema":  "pixcull.api.v1.taxonomy.v1",
            "cull_reasons": [
                {"token": t, "label_zh": labels_zh.get(t, t)}
                for t in _CULL_REASONS
            ],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=300")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _handle_event_merge(self) -> bool:
        """INFRA-3 — combine two or more runs into a merged event.

        POST /api/v1/events/merge
          body: {source_runs: [run_id, ...], name?: str}
          → {ok, merged_run_id, source_runs, name}

        The merged run lives in /tmp/pixcull_demo/event_XXXX/ and
        reuses the existing /results/<run> infrastructure (it just
        IS a normal run, with an event_meta.json sidecar).
        """
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 65536:
            self._reject_upload(400, "expected JSON body"); return True
        try:
            params = json.loads(self.rfile.read(clen).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}"); return True
        source_runs = params.get("source_runs") or []
        name = str(params.get("name") or "") or None
        if (not isinstance(source_runs, list) or len(source_runs) < 2 or
                not all(isinstance(s, str) and s for s in source_runs)):
            self._reject_upload(400, "source_runs must be a list of ≥ 2 run IDs")
            return True
        try:
            from pixcull.events import merge_runs
            merged_id = merge_runs(source_runs, name=name, demo_root=_DEMO_ROOT)
        except FileNotFoundError as exc:
            self._reject_upload(404, str(exc)); return True
        except (ValueError, OSError) as exc:
            self._reject_upload(400, str(exc)); return True

        body = _safe_dumps({
            "ok":             True,
            "merged_run_id":  merged_id,
            "source_runs":    source_runs,
            "name":           name,
            "url":            f"/results/{merged_id}",
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _handle_lr_sync(self, run_id: str) -> bool:
        """P-UX-15 — Lr / Capture One round-trip.

        Walks every photo in the run, looks for its XMP sidecar next
        to the source image, and treats the sidecar's xmp:Rating as
        an authoritative human verdict (Lr / C1 are the source of
        truth once the photographer edits there).

        Mapping (mirrors decision_to_xmp inverted):
          5★, 4★ → keep
          3★      → maybe
          2★, 1★ → cull
          0★      → no signal, skip

        Writes a human annotation per row whose sidecar rating
        differs from our current decision. Append-only, latest-wins,
        same shape as a manual /annotation POST.

        POST body: empty / ignored.
        Response: {ok, run_id, sidecars_seen, applied, skipped, unchanged}
        """
        # P-PRO-2 — read_sidecar_any tries .xmp first (Lr + C1 sync-xmp +
        # Bridge) then falls back to .cos (Capture One session-only).
        from pixcull.io.xmp import read_sidecar_any as read_xmp_sidecar  # type: ignore

        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self._reject_upload(404, f"no such run: {run_id}")
            return True
        result = _build_results(run_id)
        if result is None:
            self._reject_upload(425, "results not ready"); return True
        rows, _summary = result

        rating_to_decision = {
            5: "keep", 4: "keep",
            3: "maybe",
            2: "cull", 1: "cull",
        }
        applied: list[dict] = []
        unchanged: list[str] = []
        skipped: list[str] = []
        sidecars_seen = 0

        ann_path = Path(run["output_dir"]) / "annotations.jsonl"
        ann_path.parent.mkdir(parents=True, exist_ok=True)
        ts = time.time()

        for r in rows:
            src = r.get("src_path") or ""
            if not src:
                # Upload-mode runs without a recoverable source path
                # can't have an Lr/C1 sidecar to read.
                skipped.append(r.get("filename") or "")
                continue
            try:
                xmp = read_xmp_sidecar(Path(src))
            except Exception:
                skipped.append(r.get("filename") or "")
                continue
            rating = xmp.get("rating", 0) or 0
            if rating == 0:
                skipped.append(r.get("filename") or "")
                continue
            sidecars_seen += 1
            new_decision = rating_to_decision.get(rating)
            if new_decision is None:
                skipped.append(r.get("filename") or "")
                continue
            # Skip if PixCull already agrees with Lr
            if r.get("decision") == new_decision:
                unchanged.append(r.get("filename") or "")
                continue
            label_hint = xmp.get("color_label") or ""
            sidecar_source = xmp.get("source") or "xmp"   # P-PRO-2
            tool_label = {
                "xmp":         "Lr/C1",
                "c1_session":  "Capture One",
            }.get(sidecar_source, "sidecar")
            rationale = f"{tool_label} round-trip: rating={rating}★ label={label_hint!r}"
            record = {
                "filename":          r.get("filename"),
                "axes":              {},
                "overall_label":     new_decision,
                "overall_rationale": rationale,
                "cull_reason":       "",
                "source":            "lr_round_trip",
                "lr_rating":         rating,
                "lr_color_label":    label_hint,
                "sidecar_format":    sidecar_source,        # P-PRO-2
                "timestamp":         ts,
            }
            with open(ann_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            applied.append({
                "filename":        r.get("filename"),
                "from":            r.get("decision"),
                "to":              new_decision,
                "rating":          rating,
                "label":           label_hint,
                "sidecar_format":  sidecar_source,
            })

        body = _safe_dumps({
            "ok":              True,
            "run_id":          run_id,
            "sidecars_seen":   sidecars_seen,
            "applied":         len(applied),
            "applied_detail":  applied[:50],
            "unchanged":       len(unchanged),
            "skipped":         len(skipped),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_user_profile(self) -> bool:
        """P-AI-1 — derived personalization profile.

        Same source data as /users/preferences but distilled to the
        runtime-relevant shape: keep_threshold_shift, axis priorities,
        is_active. Reuses _serve_api_v1_user_preferences's aggregation
        logic by calling profile_from_preferences() on the same
        in-memory dict.

        GET /api/v1/users/profile  → personalized.PersonalProfile json
        """
        from pixcull.scoring.personalized import profile_from_preferences

        prefs = self._aggregate_user_preferences()
        profile = profile_from_preferences(prefs)
        payload = {
            "schema":  "pixcull.api.v1.user_profile.v1",
            "user_id": profile.user_id,
            "n_annotations":      profile.n_annotations,
            "is_active":          profile.is_active(),
            "keep_rate":          profile.keep_rate,
            "cull_rate":          profile.cull_rate,
            "keep_threshold_shift": profile.keep_threshold_shift,
            "axis_keep_means":    profile.axis_keep_means,
            "axis_cull_means":    profile.axis_cull_means,
            "most_cared_axis":    profile.most_cared_axis,
        }
        body = _safe_dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=30")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _aggregate_user_preferences(self) -> dict:
        """Shared aggregation logic used by both /users/preferences
        and /users/profile so they don't fork."""
        from collections import Counter, defaultdict
        cull_reasons: Counter[str] = Counter()
        scene_decision: dict[str, Counter[str]] = defaultdict(Counter)
        per_dec_stars: dict[str, dict[str, list[float]]] = {
            "keep": defaultdict(list),
            "maybe": defaultdict(list),
            "cull": defaultdict(list),
        }
        n_human = 0
        for run_dir in sorted(_DEMO_ROOT.glob("*/")):
            ann_path = run_dir / "output" / "annotations.jsonl"
            csv_path = run_dir / "output" / "scores.csv"
            if not ann_path.is_file():
                continue
            scene_by_fn: dict[str, str] = {}
            if csv_path.is_file():
                try:
                    import csv as _csv
                    with open(csv_path, encoding="utf-8") as f:
                        rdr = _csv.DictReader(f)
                        for row in rdr:
                            fn = (row.get("filename") or "").strip()
                            if fn:
                                scene_by_fn[fn] = (row.get("scene") or "unknown").strip()
                except OSError:
                    pass
            latest: dict[str, dict] = {}
            try:
                with open(ann_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        fn = rec.get("filename")
                        if fn:
                            latest[fn] = rec
            except OSError:
                continue
            for fn, rec in latest.items():
                label = str(rec.get("overall_label", "")).strip().lower()
                if label not in ("keep", "maybe", "cull"):
                    continue
                n_human += 1
                scene = scene_by_fn.get(fn, "unknown")
                scene_decision[scene][label] += 1
                if label == "cull":
                    reason = str(rec.get("cull_reason") or "").strip().lower()
                    if reason and reason in _CULL_REASONS:
                        cull_reasons[reason] += 1
                axes = rec.get("axes") or {}
                for axis_name, ax in axes.items():
                    if isinstance(ax, dict):
                        stars = ax.get("stars")
                        if stars is not None:
                            try:
                                per_dec_stars[label][axis_name].append(float(stars))
                            except (TypeError, ValueError):
                                continue

        def _mean(xs):
            return round(sum(xs) / len(xs), 2) if xs else None

        return {
            "total_human_annotations": n_human,
            "cull_reasons": dict(cull_reasons),
            "scene_decision_counts": {
                s: dict(c) for s, c in scene_decision.items()
            },
            "avg_rubric_when": {
                label: {ax: _mean(vals) for ax, vals in d.items()}
                for label, d in per_dec_stars.items()
            },
        }

    def _serve_api_v1_user_preferences(self) -> bool:
        """P-UX-12 — per-user taste profile.

        Walks every ``annotations.jsonl`` across all runs and the
        matching ``scores.csv`` for scene context, then summarizes:

          - cull_reasons:        which reasons you tag most often
          - scene_decision_counts: keep/maybe/cull breakdown per scene
          - avg_rubric_when_keep:  for kept photos, the mean star per axis
          - avg_rubric_when_cull:  same, for culled photos
          - total_human_annotations

        These let the admin page show "your taste profile" — which
        kinds of frames you reward vs reject, and what axes you
        seem to care about most. Feeds an honest "the rescorer
        could adapt these weights for you" pitch (P-UX-12 v0.2).
        """
        from collections import Counter, defaultdict
        cull_reasons: Counter[str] = Counter()
        scene_decision: dict[str, Counter[str]] = defaultdict(Counter)
        # Per-axis stars accumulators, split by user verdict.
        # Structure: {"keep": {axis: [stars, ...]}, "cull": {...}}
        per_dec_stars: dict[str, dict[str, list[float]]] = {
            "keep": defaultdict(list),
            "maybe": defaultdict(list),
            "cull": defaultdict(list),
        }
        n_human = 0

        # Cache scene lookups so we don't re-parse a scores.csv per
        # annotation — read once per run into a {filename: scene} dict.
        for run_dir in sorted(_DEMO_ROOT.glob("*/")):
            ann_path = run_dir / "output" / "annotations.jsonl"
            csv_path = run_dir / "output" / "scores.csv"
            if not ann_path.is_file():
                continue
            scene_by_fn: dict[str, str] = {}
            if csv_path.is_file():
                try:
                    import csv as _csv
                    with open(csv_path, encoding="utf-8") as f:
                        rdr = _csv.DictReader(f)
                        for row in rdr:
                            fn = (row.get("filename") or "").strip()
                            if fn:
                                scene_by_fn[fn] = (row.get("scene") or "unknown").strip()
                except OSError:
                    pass

            # Latest-wins reducer over annotations
            latest: dict[str, dict] = {}
            try:
                with open(ann_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        fn = rec.get("filename")
                        if fn:
                            latest[fn] = rec
            except OSError:
                continue

            for fn, rec in latest.items():
                label = str(rec.get("overall_label", "")).strip().lower()
                if label not in ("keep", "maybe", "cull"):
                    continue
                n_human += 1
                scene = scene_by_fn.get(fn, "unknown")
                scene_decision[scene][label] += 1
                if label == "cull":
                    reason = str(rec.get("cull_reason") or "").strip().lower()
                    if reason and reason in _CULL_REASONS:
                        cull_reasons[reason] += 1
                # Per-axis stars from the human's rubric
                axes = rec.get("axes") or {}
                for axis_name, ax in axes.items():
                    if not isinstance(ax, dict):
                        continue
                    stars = ax.get("stars")
                    if stars is None:
                        continue
                    try:
                        per_dec_stars[label][axis_name].append(float(stars))
                    except (TypeError, ValueError):
                        continue

        def _mean(xs: list[float]) -> float | None:
            return round(sum(xs) / len(xs), 2) if xs else None

        avg_when = {
            label: {ax: _mean(vals) for ax, vals in d.items()}
            for label, d in per_dec_stars.items()
        }

        body = _safe_dumps({
            "schema":  "pixcull.api.v1.user_preferences.v1",
            "total_human_annotations": n_human,
            "cull_reasons": dict(cull_reasons),
            "scene_decision_counts": {
                scene: dict(counts) for scene, counts in scene_decision.items()
            },
            "avg_rubric_when": avg_when,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=30")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_cull_reason_stats(self) -> bool:
        """P-UX-9 — accumulated cull-reason counts across the user's
        runs. Drives two things on the client:

          1. Reorder the cull-reason picker so the tokens you reach
             for most are listed first (less mouse travel).
          2. Power a "your cull habits" card on /admin so the user
             can see their own bias over time.

        Read-only aggregate: walks every ``annotations.jsonl`` under
        ``/tmp/pixcull_demo/<run_id>/output/``, tallies the
        ``cull_reason`` field on rows whose latest annotation was
        ``cull``. Latest-wins per (run, filename) so a row that was
        first marked cull/focus_miss then later flipped to keep
        contributes zero.
        """
        from collections import Counter
        counts: Counter[str] = Counter()
        n_scanned = 0
        n_with_reason = 0
        for run_dir in sorted(_DEMO_ROOT.glob("*/")):
            ann_path = run_dir / "output" / "annotations.jsonl"
            if not ann_path.is_file():
                continue
            # Latest-wins reducer
            latest: dict[str, dict] = {}
            try:
                with open(ann_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        fn = rec.get("filename")
                        if not fn:
                            continue
                        latest[fn] = rec
                        n_scanned += 1
            except OSError:
                continue
            for rec in latest.values():
                if str(rec.get("overall_label", "")).strip().lower() != "cull":
                    continue
                reason = str(rec.get("cull_reason") or "").strip().lower()
                if reason and reason in _CULL_REASONS:
                    counts[reason] += 1
                    n_with_reason += 1

        # Stable order: same taxonomy order as /taxonomy; clients
        # combine this with the count to sort their picker.
        body = _safe_dumps({
            "schema":   "pixcull.api.v1.cull_reason_stats.v1",
            "counts":   {t: counts.get(t, 0) for t in _CULL_REASONS},
            "total_culls_with_reason": n_with_reason,
            "total_annotations_scanned": n_scanned,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=30")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_row(self, run_id: str, filename: str) -> bool:
        """V0.3 — full single-row dict for the iOS lightbox.

        Includes ``advice`` (verdict + strengths + weaknesses +
        suggestions, all from V20), ``rubric_stars`` (per-axis 1-5★),
        ``gps_lat`` / ``gps_lon``, ``face_clusters`` (per-face cluster
        ids; iOS resolves to names via the face_clusters endpoint),
        and any meta-judge / VLM rationale present.

        Looks the row up by filename in the result rows. 404 if not
        found — typically because the filename was URL-encoded wrong,
        but the message says so the iOS UI can tell.
        """
        result = _build_results(run_id)
        if result is None:
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(404, "no such run"); return True
            self.send_error(425, "results not ready"); return True
        rows, _ = result
        fn = unquote(filename)
        match = next((r for r in rows if r.get("filename") == fn), None)
        if match is None:
            self.send_error(404, f"no such filename in this run: {fn}")
            return True
        # Wrap in a schema envelope; the row itself is passthrough so
        # all fields the row builder produced are visible.
        body = _safe_dumps({
            "schema": "pixcull.api.v1.row.v1",
            "run_id": run_id,
            "row":    match,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_api_v1_run_summary(self, run_id: str) -> bool:
        """V25 — single-run summary doc designed for a mobile app's
        run-detail page. Returns counts + the URL paths to fetch the
        run's various asset endpoints. The mobile client follows the
        embedded paths rather than constructing them — that lets us
        rename or version routes without breaking apps.
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return True
        result = _build_results(run_id)
        summary = result[1] if result else {}
        face_clusters_info = (_build_face_clusters_info(run_id, result[0])
                               if result else {"clusters": [], "n_noise": 0})
        locations_info = (_build_locations_info(result[0], run_id) if result
                          else {"clusters": [], "n_no_gps": 0, "n_total": 0})
        body = _safe_dumps({
            "schema":   "pixcull.api.v1.run",
            "run_id":   run_id,
            "summary":  summary,
            "face_clusters_n":  len(face_clusters_info.get("clusters") or []),
            "locations_n":      len(locations_info.get("clusters") or []),
            "links": {
                "results_html":   f"/results/{run_id}",
                "status":         f"/api/v1/runs/{run_id}/status",
                "decisions":      f"/api/v1/runs/{run_id}/decisions",
                "face_clusters":  f"/api/v1/runs/{run_id}/face_clusters",
                "locations":      f"/api/v1/runs/{run_id}/locations",
                "scores_csv":     f"/api/v1/runs/{run_id}/scores.csv",
                "gallery_zip":    f"/api/v1/runs/{run_id}/gallery.zip",
                "xmp_zip":        f"/api/v1/runs/{run_id}/xmp.zip",
            },
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    # --- V25 CORS + API auth shims -----------------------------------------
    # We override ``end_headers`` so every response under ``/api/v1/`` gets
    # CORS headers without per-handler bookkeeping. Browser-hosted apps
    # served from a different origin (or running off ``file://`` like the
    # V23.x gallery) can fetch the JSON endpoints directly.
    #
    # Auth model:
    #   * Localhost (127.0.0.1 / ::1): no auth required — PixCull is a
    #     local-first app and the existing CLI / browser flows assume
    #     trusted same-machine access.
    #   * Non-localhost: requires ``X-PixCull-API-Key`` matching the
    #     ``PIXCULL_API_KEY`` env var if that var is set. If unset, the
    #     server still accepts non-localhost calls (preserves the V14.0
    #     "LAN demo" behavior); admin can set it to lock down.
    def _api_v1_auth_ok(self) -> bool:
        """V25 — return True if the current request is allowed to hit
        /api/v1 endpoints. See class header comment for the model."""
        client_host = (self.client_address[0] if self.client_address
                       else "")
        if client_host in ("127.0.0.1", "::1", "localhost"):
            return True
        required = os.environ.get("PIXCULL_API_KEY") or ""
        if not required:
            return True
        got = self.headers.get("X-PixCull-API-Key") or ""
        return got == required

    def end_headers(self) -> None:  # noqa: N802 — stdlib override
        path = urlparse(self.path).path
        if path.startswith("/api/v1"):
            # V25.1 — CORS origin allowlist via env var.
            # PIXCULL_API_CORS_ORIGINS is a comma-separated list:
            #   "https://app.example.com,https://staging.example.com"
            # The special value "*" (default when env var unset)
            # echoes the wild-open V25 behavior — fine for localhost
            # development, NOT recommended for any server reachable
            # from the public internet.
            #
            # When the env var is set, we ECHO the matching Origin
            # back in Access-Control-Allow-Origin (per CORS spec —
            # browsers reject "*" when credentials are involved, and
            # an echoed value is the proper way to allow a specific
            # origin). Unknown origins get no CORS header at all,
            # which the browser correctly rejects as a CORS failure.
            allowlist_raw = (os.environ.get("PIXCULL_API_CORS_ORIGINS")
                              or "*").strip()
            allowlist = [s.strip() for s in allowlist_raw.split(",")
                          if s.strip()]
            req_origin = self.headers.get("Origin", "")
            if "*" in allowlist:
                self.send_header("Access-Control-Allow-Origin", "*")
            elif req_origin and req_origin in allowlist:
                self.send_header("Access-Control-Allow-Origin", req_origin)
                # When echoing a specific origin we must also send
                # Vary: Origin so intermediate caches don't serve the
                # wrong-origin response to another origin's preflight.
                self.send_header("Vary", "Origin")
            # else: no Allow-Origin header → browser blocks the
            # request. Servers don't need to send a 403 — silence is
            # the spec-correct rejection.
            self.send_header("Access-Control-Allow-Methods",
                              "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-PixCull-API-Key",
            )
            self.send_header("Access-Control-Max-Age", "86400")
        return BaseHTTPRequestHandler.end_headers(self)

    def do_OPTIONS(self) -> None:  # noqa: N802 — CORS preflight
        # Always respond 204 No Content for OPTIONS on /api/v1/* so the
        # browser's preflight succeeds. Auth not required for preflight
        # (CORS spec — the actual request gets auth-checked).
        path = urlparse(self.path).path
        if not path.startswith("/api/v1"):
            self.send_error(404, "preflight only valid on /api/v1/*")
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- routes ------------------------------------------------------------
    def _read_request_user(self) -> None:
        """V28.2 — set the active user for this request from either:
        1. ``X-PixCull-User`` request header (third-party / mobile)
        2. ``pixcull_user`` cookie (browser session, set by
           ``POST /api/v1/users/active``)

        Falls through (no-op) when neither is set, in which case
        ``get_active_user()`` returns the env-var default.
        """
        from pixcull.users import set_request_user
        uid = self.headers.get("X-PixCull-User") or ""
        if not uid:
            cookie_hdr = self.headers.get("Cookie") or ""
            for part in cookie_hdr.split(";"):
                k, _, v = part.strip().partition("=")
                if k == "pixcull_user":
                    uid = v.strip()
                    break
        if uid:
            set_request_user(uid)
        else:
            set_request_user(None)

    def do_GET(self) -> None:  # noqa: N802
        self._read_request_user()       # V28.2
        path = urlparse(self.path).path
        # V25 — versioned API namespace. Auth-gated, CORS-friendly,
        # discoverable via ``GET /api/v1/``. Most routes are aliases to
        # existing handlers; the discovery endpoint + a couple of
        # mobile-friendly summary endpoints are unique to /api/v1/.
        if path.startswith("/api/v1"):
            if not self._api_v1_auth_ok():
                self.send_error(401, "missing or wrong X-PixCull-API-Key")
                return
            if self._dispatch_api_v1_get(path):
                return
        # V14.6 — first-run setup endpoints. Available always (idempotent
        # snapshot when no setup is running) so the launcher can spin
        # up the server BEFORE warming starts and the browser can sit
        # on /first_run polling status.
        if path == "/first_run":
            return self._serve_first_run_page()
        if path == "/first_run_status":
            return self._serve_first_run_status()
        # V14.7 — opt-in error reporting + privacy disclosure
        if path == "/privacy":
            return self._serve_privacy_page()
        if path == "/settings/error_reports":
            return self._serve_error_reports_settings()
        # V17.0 — vertical registry + per-vertical sample bank
        if path == "/verticals":
            return self._serve_verticals_page()
        if path == "/verticals.json":
            return self._serve_verticals_json()
        if path.startswith("/verticals/list/"):
            return self._serve_vertical_list(path[len("/verticals/list/"):])
        if path.startswith("/verticals/sample/"):
            return self._serve_vertical_sample(path[len("/verticals/sample/"):])
        # V17.7 — bulk-classify page + on-the-fly thumbnail for the
        # original-folder paths (constrained to the in-process whitelist
        # built by the most recent bulk_classify call).
        if path.startswith("/verticals/bulk/"):
            return self._serve_vertical_bulk_page(path[len("/verticals/bulk/"):])
        if path == "/verticals/bulk_thumb":
            return self._serve_vertical_bulk_thumb()
        if path == "/":
            return self._serve_upload_page()
        if path == "/admin":
            return self._serve_admin_page()
        # v0.7-P0-3 — large-batch (5k+) performance debug page.
        # Surfaces: process RSS, # of active runs, /tmp/pixcull_demo
        # disk usage, per-run row count, observer throttle stats
        # (relayed client-side via window.PixCullStorage / _pcBucketsObsFn).
        if path == "/admin/perf":
            return self._serve_admin_perf_page()
        if path == "/admin/perf.json":
            return self._serve_admin_perf_json()
        # P-AI-4.1 — face library quality audit page (HTML + JSON).
        if path.startswith("/admin/face_audit/"):
            return self._serve_face_audit(path[len("/admin/face_audit/"):])
        # P-PRO-7.1 — full delivery audit page (scene + face + wedding
        # + ICC + EXIF).  Re-uses scripts/cli_audit.py via subprocess
        # so the markdown output is the single source of truth across
        # CLI + web.
        if path.startswith("/admin/delivery/"):
            return self._serve_delivery_audit(path[len("/admin/delivery/"):])
        if path == "/runs":
            return self._serve_runs_list()
        if path == "/storage_info":
            return self._serve_storage_info()
        if path == "/rubric_meta":
            return self._serve_rubric_meta()
        if path == "/retrain_status":
            return self._serve_retrain_status()
        if path == "/license":
            return self._serve_license_status()
        if path == "/license/refresh":
            return self._handle_license_refresh()
        if path == "/sync/download":
            return self._handle_sync_download()
        if path.startswith("/status/"):
            return self._serve_status(path[len("/status/"):])
        if path.startswith("/results/"):
            return self._serve_results(path[len("/results/"):])
        if path.startswith("/decisions/"):
            # V21.2 — Lightroom plugin write-back endpoint. Returns
            # {filename: decision} for a run so the LR Lua script can
            # propagate decisions to star ratings / reject flags.
            return self._serve_decisions(path[len("/decisions/"):])
        if path.startswith("/face_clusters/"):
            # V22.1 — face cluster summary + labels for a run.
            return self._serve_face_clusters(path[len("/face_clusters/"):])
        if path.startswith("/face_avatar/"):
            # V22.3 — mini-avatar JPEG for a (run_id, cluster_id) pair.
            return self._serve_face_avatar(path[len("/face_avatar/"):])
        if path.startswith("/locations/"):
            # V23 — GPS location cluster summary for a run.
            return self._serve_locations(path[len("/locations/"):])
        if path.startswith("/thumb/"):
            # v0.6 (4/5) — pass self.path (query string intact) so the
            # ``?w=<bucket>`` clamp inside _serve_image actually fires.
            # The original V14.1 wiring used the already-query-stripped
            # `path` variable, which silently dropped every viewport
            # hint we ever sent (only the 420 default was ever cached).
            return self._serve_image(
                self.path[len("/thumb/"):], _THUMB_SIZE
            )
        if path.startswith("/full/"):
            return self._serve_image(
                self.path[len("/full/"):], _FULL_SIZE
            )
        if path.startswith("/xmp_zip/"):
            return self._serve_xmp_zip(path[len("/xmp_zip/"):])
        # v0.7-P1-4 — token-gated client delivery share page.
        # /share/<run_id>/<token>  → static-ish HTML showing keeps
        if path.startswith("/share/"):
            return self._serve_share_page(path[len("/share/"):])
        # v0.7-P2-1 — fetch learned style distances for a run.
        # GET /style/distances/<run_id>  → {filename: distance}
        if path.startswith("/style/distances/"):
            return self._serve_style_distances(
                path[len("/style/distances/"):]
            )
        # v0.7-P2-4 — history timeline page (all past runs)
        if path == "/history":
            return self._serve_history_page()
        # v0.8-P1-3 — short link resolver + QR SVG.
        # GET /s/<code>      → 302 redirect to long URL (or 404/410)
        # GET /s/<code>.svg  → inline QR SVG for the long URL
        if path.startswith("/s/"):
            tail = path[len("/s/"):]
            if tail.endswith(".svg"):
                return self._serve_shortlink_qr(tail[:-4])
            return self._serve_shortlink_redirect(tail)
        # v0.7-P2-2 — tethered live scoring.
        if path == "/tether":
            return self._serve_tether_page()
        if path == "/tether/sessions":
            return self._serve_tether_sessions()
        if path.startswith("/tether/status/"):
            return self._serve_tether_status(
                path[len("/tether/status/"):]
            )
        if path.startswith("/gallery_zip/"):
            # V23.x — standalone HTML gallery export. Returns a zip
            # the user can email/upload as-is; index.html opens in
            # any browser, no PixCull server needed.
            return self._serve_gallery_zip(path[len("/gallery_zip/"):])
        # V9.3: scores.csv direct download
        if path.startswith("/scores_csv/"):
            return self._serve_scores_csv(path[len("/scores_csv/"):])
        # v0.8-P2-2 — structured export (CSV / JSON, all fields)
        if path.startswith("/export/structured/"):
            tail = path[len("/export/structured/"):]
            if tail.endswith(".json"):
                return self._serve_export_structured_json(tail[:-5])
            if tail.endswith(".csv"):
                return self._serve_export_structured_csv(tail[:-4])
            self.send_error(404, "expected .json or .csv suffix")
            return
        if path.startswith("/rubric/"):
            return self._serve_rubric(path[len("/rubric/"):])
        if path.startswith("/annotation/"):
            return self._serve_annotation(path[len("/annotation/"):])
        if path.startswith("/next_to_label/"):
            return self._serve_next_to_label(path[len("/next_to_label/"):])
        self.send_error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        self._read_request_user()       # V28.2
        path = urlparse(self.path).path
        # V25 — versioned API namespace (POST side).
        if path.startswith("/api/v1"):
            if not self._api_v1_auth_ok():
                self.send_error(401, "missing or wrong X-PixCull-API-Key")
                return
            if self._dispatch_api_v1_post(path):
                return
        if path == "/analyze":
            return self._handle_analyze_post()
        if path == "/scan_local":
            return self._handle_scan_local()
        # P-UX-21 — sample-data quick-try. Copies the bundled
        # samples/ tree into a fresh demo run + returns the
        # new run_id so the upload page can redirect directly
        # into /results without any model warm-up.
        if path == "/sample_demo":
            return self._handle_sample_demo()
        # P-UX-22 — deliverable buckets export. Body: {name, filenames}
        # → server zips the matching photos + returns a downloadable URL.
        if path.startswith("/buckets/export/"):
            run_id = path[len("/buckets/export/"):]
            return self._handle_bucket_export(run_id)
        # v0.7-P1-4 — issue a fresh share token for the run.
        # POST /share/<run_id>/issue  body: {photographer?, client?}
        # → {ok, token, url}
        if path.startswith("/share/") and path.endswith("/issue"):
            rid = path[len("/share/"):-len("/issue")]
            return self._handle_share_issue(rid)
        # v0.7-P2-1 — train (or retrain) a style-clone profile.
        # POST /style/train/<run_id>  body: {refs: [filename,...]}
        # → {ok, n_refs, profile_summary}
        if path.startswith("/style/train/"):
            rid = path[len("/style/train/"):]
            return self._handle_style_train(rid)
        # v0.8-P0-2 — issue a sync event token for a run.
        # POST /sync/event/issue/<run_id>  body: {label?, ttl_hours?}
        # → {ok, event_id, token, url, qr_url}
        if path.startswith("/sync/event/issue/"):
            rid = path[len("/sync/event/issue/"):]
            return self._handle_sync_event_issue(rid)
        # v0.8-P1-3 — short-link issuer.
        # POST /s/issue  body: {long_url, ttl_hours?, label?}
        # → {ok, short_code, short_url, qr_url, long_url, expires_at}
        if path == "/s/issue":
            return self._handle_shortlink_issue()
        # v0.8-P0-2 — revoke an event
        # POST /sync/event/revoke/<run_id>/<event_id>
        if path.startswith("/sync/event/revoke/"):
            tail = path[len("/sync/event/revoke/"):]
            if "/" in tail:
                rid, eid = tail.split("/", 1)
                return self._handle_sync_event_revoke(rid, eid)
        # v0.7-P2-2 — tethered live scoring (top-level shortcut routes
        # that call into the canonical P2.2 handlers defined further
        # down in this class).
        if path == "/tether/start":
            return self._handle_tether_start()
        if path.startswith("/tether/") and path.endswith("/stop"):
            sid = path[len("/tether/"):-len("/stop")]
            return self._handle_tether_stop(sid)
        if path == "/browse":
            return self._handle_browse()
        if path.startswith("/export/"):
            return self._handle_export(path[len("/export/"):])
        if path == "/runs/cleanup":
            return self._handle_runs_cleanup()
        # P0.4 — re-run SceneDetector on a run's cached scores.csv,
        # applying V20's "face_count > 0 → not stilllife" correction
        # to existing rows without re-running the full pipeline.
        if path.startswith("/runs/") and path.endswith("/rescan_scene"):
            mid = path[len("/runs/"):-len("/rescan_scene")]
            return self._handle_rescan_scene(mid)
        # P2.3 — apply the active style guide to a run's rows
        # (post-decision; can knock keep → maybe/cull).
        if path.startswith("/runs/") and path.endswith("/apply_style_guide"):
            mid = path[len("/runs/"):-len("/apply_style_guide")]
            return self._handle_apply_style_guide(mid)
        if path.startswith("/annotation/"):
            return self._handle_save_annotation(path[len("/annotation/"):])
        if path.startswith("/face_clusters/") and path.endswith("/label"):
            # V22.1 — update a per-cluster label for a run.
            mid = path[len("/face_clusters/"):-len("/label")]
            return self._handle_face_label_post(mid)
        if path.startswith("/locations/") and path.endswith("/label"):
            # V23.1 — update a per-location label for a run.
            mid = path[len("/locations/"):-len("/label")]
            return self._handle_location_label_post(mid)
        if path == "/retrain":
            return self._handle_retrain()
        if path == "/license":
            return self._handle_license_install()
        if path == "/sync/upload":
            return self._handle_sync_upload()
        # V14.7 — opt-in error reporting
        if path == "/settings/error_reports":
            return self._handle_save_error_reports_settings()
        if path == "/error_reports/submit":
            return self._handle_submit_error_report()
        # V17.12 — browser-side window.onerror / unhandledrejection
        if path == "/error_reports/client_event":
            return self._handle_client_error_event()
        # V17.0 — vertical sample upload
        if path.startswith("/verticals/upload/"):
            return self._handle_vertical_upload(path[len("/verticals/upload/"):])
        # V17.4 — vertical policy tuning + apply / revert
        if path.startswith("/verticals/tune/"):
            return self._handle_vertical_tune(path[len("/verticals/tune/"):])
        if path.startswith("/verticals/apply_override/"):
            return self._handle_vertical_apply_override(
                path[len("/verticals/apply_override/"):])
        if path.startswith("/verticals/revert_override/"):
            return self._handle_vertical_revert_override(
                path[len("/verticals/revert_override/"):])
        # V17.5 — DeepSeek phrase generation
        if path.startswith("/verticals/llm_phrases/"):
            return self._handle_vertical_llm_phrases(
                path[len("/verticals/llm_phrases/"):])
        if path.startswith("/verticals/revert_phrases/"):
            return self._handle_vertical_revert_phrases(
                path[len("/verticals/revert_phrases/"):])
        # V17.6 — per-vertical eval report
        if path.startswith("/verticals/eval/"):
            return self._handle_vertical_eval(
                path[len("/verticals/eval/"):])
        # V17.7 — bulk-classify-from-folder
        if path.startswith("/verticals/bulk_classify/"):
            return self._handle_vertical_bulk_classify(
                path[len("/verticals/bulk_classify/"):])
        if path.startswith("/verticals/bulk_commit/"):
            return self._handle_vertical_bulk_commit(
                path[len("/verticals/bulk_commit/"):])
        # V17.8 — auto-promote human-annotated keep/cull from a
        # vertical-tagged batch into that vertical's sample bank.
        if path.startswith("/verticals/promote_run/"):
            return self._handle_vertical_promote_run(
                path[len("/verticals/promote_run/"):])
        # V17.13 — Unsplash CC0 reference fetcher
        if path.startswith("/verticals/unsplash_fetch/"):
            return self._handle_vertical_unsplash_fetch(
                path[len("/verticals/unsplash_fetch/"):])
        self.send_error(404, "not found")

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/runs/"):
            return self._handle_run_delete(path[len("/runs/"):])
        # V17.0 — DELETE /verticals/sample/<key>/<bucket>/<filename>
        if path.startswith("/verticals/sample/"):
            return self._handle_vertical_sample_delete(
                path[len("/verticals/sample/"):])
        self.send_error(404, "not found")

    # --- handlers ----------------------------------------------------------
    def _serve_upload_page(self) -> None:
        body = _UPLOAD_HTML.encode("utf-8")
        self._send_html(200, body)

    def _handle_analyze_post(self) -> None:
        # Read multipart payload. Limits live on the server instance so the
        # operator can tune them at startup without editing the source.
        max_bytes = self.server.max_upload_bytes  # type: ignore[attr-defined]
        max_files = self.server.max_upload_files  # type: ignore[attr-defined]

        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0:
            self._reject_upload(400, "upload is empty (no Content-Length)")
            return
        if clen > max_bytes:
            mb = clen / 1024 / 1024
            cap_mb = max_bytes / 1024 / 1024
            self._reject_upload(
                413,
                f"上传 {mb:.0f} MB 超过单次上限 {cap_mb:.0f} MB。"
                f"分批上传,或启动时加 --max-upload-mb {int(mb*1.2)} 提升上限。",
            )
            return

        # Disk-space pre-check: refuse if landing this upload would push
        # /tmp under the safety threshold. shutil.disk_usage queries the
        # filesystem of the path's mount; tmpfs / APFS both return real
        # numbers here.
        try:
            disk = shutil.disk_usage(_DEMO_ROOT)
            if disk.free - clen < _MIN_FREE_SPACE_AFTER_BYTES:
                free_mb = disk.free / 1024 / 1024
                need_mb = (clen + _MIN_FREE_SPACE_AFTER_BYTES) / 1024 / 1024
                self._reject_upload(
                    507,
                    f"磁盘空间不足: {_DEMO_ROOT.parent} 当前剩 {free_mb:.0f} MB,"
                    f"这次上传需要 ~{need_mb:.0f} MB。先去 /admin 清理或腾盘。",
                )
                return
        except OSError:
            pass  # disk_usage failure is non-fatal; let the upload try

        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self._reject_upload(400, "expected multipart/form-data")
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": ctype,
                    "CONTENT_LENGTH": str(clen),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._reject_upload(400, f"multipart parse failed: {exc}")
            return

        run_id = _new_run_id()
        run_root = _run_dir(run_id)
        input_dir = run_root / "input"
        output_dir = run_root / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save every uploaded file under the "files" field. Reject non-image
        # extensions silently — keep upload UX permissive but pipeline strict.
        ok_exts = {".jpg", ".jpeg", ".png", ".cr3", ".cr2", ".nef", ".arw", ".dng", ".tif", ".tiff"}
        n_saved = 0
        n_skipped_ext = 0
        if "files" in form:
            files = form["files"]
            items = files if isinstance(files, list) else [files]
            if len(items) > max_files:
                self._reject_upload(
                    413,
                    f"一次上传 {len(items)} 个文件超过上限 {max_files}。"
                    f"分批上传,或启动时加 --max-upload-files {len(items)+50}。",
                )
                # Note: we already drained the request body via FieldStorage;
                # nothing to clean up. Run dirs were created above but are
                # empty — leave them for /admin to sweep.
                return
            for item in items:
                fn = getattr(item, "filename", None) or ""
                if not fn:
                    continue
                # Strip any path components from the upload filename
                safe_name = Path(fn).name
                if Path(safe_name).suffix.lower() not in ok_exts:
                    n_skipped_ext += 1
                    continue
                dst = input_dir / safe_name
                with open(dst, "wb") as f:
                    f.write(item.file.read())
                n_saved += 1

        if n_saved == 0:
            hint = (
                f" {n_skipped_ext} 个文件因后缀不受支持被跳过(只接受 "
                f"{', '.join(sorted(e[1:] for e in ok_exts))})"
                if n_skipped_ext else ""
            )
            self._reject_upload(400, f"上传里没有可用图片。{hint}")
            return

        # V12.0 — license + quota gate
        from pixcull.license import check_quota, increment_usage
        ok, msg = check_quota(n_saved)
        if not ok:
            self._reject_upload(402, msg)
            return
        increment_usage(n_saved)

        rescorer_mode = self.server.rescorer_mode  # type: ignore[attr-defined]
        rescorer_path = self.server.rescorer_path  # type: ignore[attr-defined]
        vlm_mode = self.server.vlm_mode  # type: ignore[attr-defined]
        meta_mode = self.server.meta_mode  # type: ignore[attr-defined]

        _set_run(
            run_id,
            state="queued",
            mode="upload",
            done=0,
            total=n_saved,
            message=f"已收到 {n_saved} 张图,正在排队…",
            input_dir=str(input_dir),
            source_dir=str(input_dir),  # alias used by analyze_in_background
            output_dir=str(output_dir),
            n_uploaded=n_saved,
        )
        threading.Thread(
            target=_analyze_in_background,
            args=(run_id, rescorer_mode, rescorer_path, vlm_mode, meta_mode),
            daemon=True,
        ).start()

        body = json.dumps({"run_id": run_id, "n": n_saved}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- scan-local mode --------------------------------------------------
    def _handle_bucket_export(self, run_id: str) -> bool:
        """P-UX-22 — bundle a deliverable bucket into a single zip.

        Body: {name: str, filenames: [str, ...]}
          - name:      the bucket name (for the zip filename)
          - filenames: which photos to include (from the user's
                       localStorage bucket-assignment state)

        Response: {ok, zip_url, zip_filename, n_files, n_skipped}

        The user-side bucket state lives in localStorage so we don't
        store it on the server — every call is stateless and just
        zips the explicit filename list against the run's resolved
        on-disk source paths.
        """
        import io
        import zipfile

        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self._reject_upload(404, "no such run"); return True

        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 1_000_000:
            self._reject_upload(400, "expected JSON body"); return True
        try:
            body_raw = self.rfile.read(clen).decode("utf-8")
            params = json.loads(body_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}"); return True

        bucket_name = str(params.get("name") or "bucket").strip()
        filenames   = params.get("filenames") or []
        if not isinstance(filenames, list) or not filenames:
            self._reject_upload(400, "filenames must be a non-empty list")
            return True

        # Sanitize the bucket name for the zip filename
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_"
                            for c in bucket_name)[:64] or "bucket"

        # Resolve each filename to an on-disk source. We accept either
        # the run's manifest (scan mode) or input_dir (upload mode).
        zip_buf = io.BytesIO()
        n_files = 0
        n_skipped = 0
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED, allowZip64=False) as zf:
            for fn in filenames:
                if not isinstance(fn, str):
                    n_skipped += 1
                    continue
                src = _resolve_image_source(run, fn)
                if src is None or not src.is_file():
                    n_skipped += 1
                    continue
                try:
                    zf.write(src, arcname=fn)
                    n_files += 1
                except OSError:
                    n_skipped += 1
        zip_bytes = zip_buf.getvalue()

        # Stash the zip under the run's output_dir so /tmp_zip can
        # serve it; same pattern V1.2's XMP-export uses.
        out_dir = Path(run["output_dir"])
        zip_path = out_dir / f"bucket-{safe_name}-{int(time.time())}.zip"
        zip_path.write_bytes(zip_bytes)

        body = _safe_dumps({
            "ok":            True,
            "zip_url":       f"/tmp_zip/{run_id}/{zip_path.name}",
            "zip_filename":  f"{safe_name}.zip",
            "n_files":       n_files,
            "n_skipped":     n_skipped,
            "size_bytes":    len(zip_bytes),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    # ============================================================
    # v0.7-P1-4 — client delivery share link.
    # POST /share/<run_id>/issue            → mint a new token
    # GET  /share/<run_id>/<token>          → render the read-only
    #                                          delivery page
    # Tokens are persisted to <output_dir>/share_tokens.json so they
    # survive server restarts. The page shows only photos the user
    # marked "keep" (decision == "keep") plus a header with
    # photographer + client labels. Clients open the URL in any
    # browser — no PixCull install required.
    # ============================================================
    def _share_token_path(self, run: dict):
        return Path(run["output_dir"]) / "share_tokens.json"

    def _read_share_tokens(self, run: dict) -> dict:
        p = self._share_token_path(run)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_share_tokens(self, run: dict, data: dict) -> None:
        p = self._share_token_path(run)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        except OSError as exc:
            _dbg("share/write_tokens", exc, str(p))

    def _handle_share_issue(self, run_id: str) -> None:
        """POST /share/<run_id>/issue
        body: {photographer?, client?, expires_days?}
        → {ok, token, url}
        """
        import secrets

        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        token = secrets.token_urlsafe(16)
        record = {
            "token":        token,
            "photographer": str(body.get("photographer") or "").strip()[:80],
            "client":       str(body.get("client") or "").strip()[:80],
            "issued_at":    datetime.now(timezone.utc).isoformat(),
        }
        try:
            days = int(body.get("expires_days") or 0)
        except (TypeError, ValueError):
            days = 0
        if days > 0:
            from datetime import timedelta
            record["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(days=days)
            ).isoformat()
        tokens = self._read_share_tokens(run)
        tokens[token] = record
        self._write_share_tokens(run, tokens)
        payload = {
            "ok":   True,
            "token": token,
            "url":  f"/share/{run_id}/{token}",
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)

    def _serve_share_page(self, rel: str) -> None:
        """GET /share/<run_id>/<token> → minimal client-delivery HTML.

        The page is self-contained (inline CSS + <img> referring back to
        /thumb/<run>/<file>). The token is validated against the
        on-disk share_tokens.json; expired or unknown tokens 404.
        """
        rel = unquote(rel).strip("/")
        parts = rel.split("/", 1)
        if len(parts) != 2:
            self.send_error(400, "expected /share/<run_id>/<token>")
            return
        run_id, token = parts
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        tokens = self._read_share_tokens(run)
        rec = tokens.get(token)
        if not rec:
            self.send_error(404, "share link not found or revoked")
            return
        # Optional expiry check
        exp = rec.get("expires_at")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp)
                if exp_dt < datetime.now(timezone.utc):
                    self.send_error(410, "share link expired")
                    return
            except ValueError:
                pass

        # Load keeps only from scores.csv. We deliberately filter
        # *server-side* so a client can't toggle off the filter from
        # the page (the share contract is "you see what I picked").
        try:
            keeps = self._share_collect_keeps(run)
        except Exception as exc:
            _dbg("share/collect_keeps", exc, run_id)
            self.send_error(500, "failed to read run")
            return

        photographer = rec.get("photographer") or ""
        client = rec.get("client") or ""
        html = self._render_share_html(
            run_id, token, photographer, client, keeps
        )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Don't index the page; keep it private-by-obscurity (token).
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Cache-Control", "private, max-age=60")
        self.end_headers()
        self.wfile.write(body)

    def _share_collect_keeps(self, run: dict) -> list:
        """Return [(filename, score_final), ...] for keep rows only."""
        import csv as _csv

        scores_path = Path(run["output_dir"]) / "scores.csv"
        if not scores_path.exists():
            return []
        # Honor annotation/* overrides — a photo annotated as keep
        # after the fact should appear too.
        ann_dir = Path(run["output_dir"]) / "annotation"
        ann_overrides = {}
        if ann_dir.is_dir():
            for f in ann_dir.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    fn = f.stem
                    dec = d.get("decision")
                    if dec in {"keep", "maybe", "cull"}:
                        ann_overrides[fn] = dec
                except (OSError, ValueError):
                    continue
        keeps = []
        with open(scores_path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = _csv.DictReader(fh)
            for row in reader:
                fn = row.get("filename") or ""
                if not fn:
                    continue
                dec = ann_overrides.get(fn) or row.get("decision") or ""
                if dec != "keep":
                    continue
                try:
                    score = float(row.get("score_final") or 0)
                except ValueError:
                    score = 0.0
                keeps.append((fn, score))
        # Sort by score desc — best-first delivery
        keeps.sort(key=lambda t: t[1], reverse=True)
        return keeps

    def _render_share_html(
        self,
        run_id: str,
        token: str,
        photographer: str,
        client: str,
        keeps: list,
    ) -> str:
        """Render the minimal client-delivery page (self-contained)."""
        from html import escape as _esc

        cards = []
        for fn, score in keeps:
            cards.append(
                f'''<a class="card" href="/full/{run_id}/{_esc(fn)}" target="_blank" rel="noopener">
                  <img loading="lazy" src="/thumb/{run_id}/{_esc(fn)}?w=420" alt="{_esc(fn)}">
                  <div class="cap">{_esc(fn)}</div>
                </a>'''
            )
        cards_html = "\n".join(cards) if cards else (
            '<div class="empty">摄影师还没有挑出片 — 请稍后再来。</div>'
        )
        header_lines = []
        if photographer:
            header_lines.append(
                f'<span class="lbl">摄影师</span><span class="val">{_esc(photographer)}</span>'
            )
        if client:
            header_lines.append(
                f'<span class="lbl">客户</span><span class="val">{_esc(client)}</span>'
            )
        header_html = (
            f'<div class="head-meta">{"".join(header_lines)}</div>'
            if header_lines else ""
        )
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{_esc(photographer or "PixCull")} · 精选交付</title>
<style>
  :root {{
    color-scheme: dark;
    --bg: #0b0d10; --bg-card: #14171c;
    --fg: #e8eaed; --fg-2: #c6c9cf; --muted: #8a8e96;
    --border: rgba(255,255,255,0.10);
    --accent: #6366f1;
  }}
  *,*::before,*::after {{ box-sizing: border-box; }}
  html,body {{ margin: 0; padding: 0; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased; }}
  header {{
    padding: 36px 24px 24px;
    border-bottom: 1px solid var(--border);
    text-align: center;
  }}
  header h1 {{ margin: 0 0 6px; font-size: 24px; font-weight: 700; letter-spacing: 0.02em; }}
  header .sub {{ margin: 0; color: var(--muted); font-size: 13px; }}
  .head-meta {{
    display: inline-flex; flex-wrap: wrap; justify-content: center;
    gap: 6px 14px; margin-top: 14px;
    font-size: 12px;
  }}
  .head-meta .lbl {{ color: var(--muted); margin-right: 4px; }}
  .head-meta .val {{ color: var(--fg-2); font-weight: 600; }}
  main {{ padding: 24px; max-width: 1280px; margin: 0 auto; }}
  .count {{ color: var(--muted); font-size: 12px; margin: 0 0 16px;
            text-align: center; letter-spacing: 0.04em; text-transform: uppercase; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
  }}
  .card {{
    display: block; text-decoration: none; color: inherit;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden;
    transition: transform 160ms ease-out, border-color 160ms ease-out;
  }}
  .card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
  .card img {{ display: block; width: 100%; aspect-ratio: 3/2; object-fit: cover; background: #1c1f24; }}
  .card .cap {{
    padding: 8px 10px; font-size: 11px; color: var(--muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .empty {{ text-align: center; color: var(--muted); padding: 48px 12px; font-size: 13px; }}
  footer {{
    margin-top: 32px; padding: 18px 24px;
    border-top: 1px solid var(--border);
    text-align: center; color: var(--muted); font-size: 11px;
    letter-spacing: 0.04em;
  }}
  footer a {{ color: var(--fg-2); text-decoration: none; }}
  @media (max-width: 640px) {{
    header {{ padding: 24px 14px 16px; }}
    header h1 {{ font-size: 19px; }}
    main {{ padding: 16px 12px; }}
    .grid {{ grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }}
  }}
</style>
</head>
<body>
  <header>
    <h1>{_esc(photographer or "精选交付")}</h1>
    <p class="sub">PixCull · 客户交付预览</p>
    {header_html}
  </header>
  <main>
    <p class="count">{len(keeps)} 张精选</p>
    <div class="grid">
      {cards_html}
    </div>
  </main>
  <footer>
    Powered by <a href="https://github.com/haozi667788/pixcull" rel="noopener" target="_blank">PixCull</a>
  </footer>
</body>
</html>"""

    # ============================================================
    # v0.7-P2-1 — style-clone V1 endpoints
    # ============================================================
    def _style_profile_path(self, run: dict):
        return Path(run["output_dir"]) / "style_profile.json"

    def _style_distances_path(self, run: dict):
        return Path(run["output_dir"]) / "style_distances.json"

    def _load_scores_rows(self, run: dict) -> list:
        """Read scores.csv into a list of dicts.  Best-effort — a
        missing / unreadable file yields [] (caller treats that as
        "nothing learnable yet", which is the right v1 fallback).
        """
        import csv as _csv

        p = Path(run["output_dir"]) / "scores.csv"
        if not p.exists():
            return []
        rows = []
        try:
            with open(p, "r", encoding="utf-8-sig", newline="") as fh:
                for r in _csv.DictReader(fh):
                    rows.append(dict(r))
        except OSError as exc:
            _dbg("style/load_scores", exc, str(p))
        return rows

    def _handle_style_train(self, run_id: str) -> None:
        """POST /style/train/<run_id>  body: {refs: [filename,...]}
        → {ok, n_refs, profile_summary}

        Pulls the matching rows out of scores.csv, hands them to
        ``learn_style_profile``, persists the resulting profile +
        a full distance map to the run's output dir.  Subsequent
        GET /style/distances/<run_id> calls just read the cached
        map — no re-computation unless retrained.
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        try:
            from pixcull.style.clone import (
                compute_distances,
                learn_style_profile,
            )
        except Exception as exc:
            _dbg("style/train/import", exc, run_id)
            self.send_error(500, "style module import failed")
            return
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        refs = body.get("refs") if isinstance(body, dict) else None
        if not isinstance(refs, list) or not refs:
            self.send_error(400, "expected {refs: [filename, ...]}")
            return
        ref_set = {str(x) for x in refs}
        all_rows = self._load_scores_rows(run)
        if not all_rows:
            self.send_error(409, "no scores.csv to train from")
            return
        ref_rows = [r for r in all_rows if r.get("filename") in ref_set]
        if not ref_rows:
            self.send_error(409, "none of the refs matched a scores.csv row")
            return
        profile = learn_style_profile(ref_rows)
        # Persist the profile JSON
        try:
            self._style_profile_path(run).write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _dbg("style/train/write_profile", exc, run_id)
            self.send_error(500, "failed to write profile")
            return
        # V1 distances (axis-MAD + scene penalty)
        v1_dists = compute_distances(all_rows, profile)

        # v0.8-P1-1 — V2 (CLIP centroid) layered on top of V1.
        # If the embeddings cache built by P-AI-2 semantic search
        # exists, learn the visual centroid + score every row.
        # Otherwise gracefully fall back to V1 only.
        v2_dists: dict = {}
        v2_summary: dict = {}
        try:
            from pixcull.style import (
                blend, compute_visual_distances, DEFAULT_LAMBDA,
                learn_visual_profile,
            )
            cache_path = Path(run["output_dir"]) / "embeddings.npz"
            v2_profile = learn_visual_profile(list(ref_set), cache_path)
            if v2_profile is not None:
                v2_dists = compute_visual_distances(v2_profile, cache_path)
                # Persist the V2 profile next to V1 (same dir, distinct name)
                try:
                    (Path(run["output_dir"]) / "style_profile_v2.json").write_text(
                        json.dumps(v2_profile, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    _dbg("style/train/write_v2_profile", exc, run_id)
                v2_summary = {
                    "n_refs": v2_profile.get("n_refs", 0),
                    "dim":    v2_profile.get("dim", 0),
                    "model":  v2_profile.get("model", ""),
                }
        except Exception as exc:
            # V2 is best-effort — log + continue with V1 only so a
            # stale cache / missing numpy doesn't fail the whole
            # training call.
            _dbg("style/train/v2_compute", exc, run_id)
            v2_dists = {}
            v2_summary = {}
        # Rich distances map: {filename: {v1, v2?, blend}} so the
        # UI can render dual chips + the client can re-blend
        # without a server round-trip when the user tunes λ.
        try:
            from pixcull.style import blend as _blend, DEFAULT_LAMBDA as _LAM
            blend_fn = _blend
            lam = _LAM
        except Exception:
            blend_fn = None
            lam = 0.3
        all_fns = set(v1_dists) | set(v2_dists)
        rich: dict = {}
        for fn in all_fns:
            entry = {"v1": v1_dists.get(fn)}
            if fn in v2_dists:
                entry["v2"] = v2_dists[fn]
            if blend_fn is not None:
                b = blend_fn(entry.get("v1"), entry.get("v2"), lam)
                if b is not None:
                    entry["blend"] = b
            # Drop any None values so the JSON file stays tidy
            entry = {k: v for k, v in entry.items() if v is not None}
            if entry:
                rich[fn] = entry
        try:
            self._style_distances_path(run).write_text(
                json.dumps(rich, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            _dbg("style/train/write_distances", exc, run_id)
            # Distances are cacheable but not required to save —
            # the profile is the durable artifact.
        payload = {
            "ok":            True,
            "n_refs":        profile.get("n_refs", 0),
            "n_scored":      len(rich),
            "n_scored_v2":   len(v2_dists),
            "axis_median":   profile.get("axis_median", {}),
            "scene_modes":   profile.get("scene_modes", {}),
            "v2":            v2_summary,
            "lambda_default": lam,
        }
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)

    # ============================================================
    # v0.8-P0-2 — LAN sync event endpoints
    # ============================================================
    def _handle_sync_event_issue(self, run_id: str) -> None:
        """POST /sync/event/issue/<run_id>
        body: {label?, ttl_hours?, issued_by?}
        → {ok, event_id, token, url, expires_at}
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        try:
            from pixcull.sync import issue_event
        except Exception as exc:
            _dbg("sync/import", exc, run_id)
            self.send_error(500, "sync module import failed")
            return
        body = self._read_json_body()
        label = str(body.get("label") or "")
        issued_by = str(body.get("issued_by") or "")
        try:
            ttl = int(body.get("ttl_hours") or 12)
        except (TypeError, ValueError):
            ttl = 12
        run_output_dir = Path(run["output_dir"])
        try:
            sess = issue_event(
                run_output_dir, run_id,
                label=label, issued_by=issued_by, ttl_hours=ttl,
            )
        except Exception as exc:
            _dbg("sync/issue", exc, run_id)
            self.send_error(500, "failed to issue event")
            return
        # Join URL is the existing /results/<run_id> page with ?event=<token>
        # query param; the JS shim detects the param and switches into
        # collaborative-polling mode.
        self._json_ok({
            "ok":          True,
            "event_id":    sess.event_id,
            "token":       sess.token,
            "url":         f"/results/{run_id}?event={sess.token}",
            "expires_at":  sess.expires_at,
        })

    def _handle_sync_event_revoke(self, run_id: str, event_id: str) -> None:
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        try:
            from pixcull.sync import revoke_event
        except Exception as exc:
            _dbg("sync/import", exc, run_id)
            self.send_error(500, "sync module import failed")
            return
        run_output_dir = Path(run["output_dir"])
        changed = revoke_event(run_output_dir, event_id)
        self._json_ok({"ok": True, "changed": bool(changed)})

    def _serve_sync_event_changes(self, token: str) -> bool:
        """GET /api/v1/sync/event/<token>/changes?since=<ms>

        We scan ALL runs' events/ dirs for a matching token because
        the client only knows the token, not the run_id.  Linear
        scan is fine for the v1 single-host model — at most a few
        runs per machine.
        """
        from urllib.parse import parse_qs, urlparse as _up
        try:
            from pixcull.sync import (
                compute_changes_since, find_event_by_token,
            )
        except Exception as exc:
            _dbg("sync/import", exc, "changes")
            self.send_error(500, "sync module import failed")
            return True
        # Walk demo root for runs and look for a matching token.
        # In a busy server this would be cached; v1 prioritises
        # correctness over speed.
        sess = None
        run_dir_match = None
        if _DEMO_ROOT.is_dir():
            for child in _DEMO_ROOT.iterdir():
                if not child.is_dir():
                    continue
                out_dir = child / "output"
                if not out_dir.is_dir():
                    continue
                found = find_event_by_token(out_dir, token)
                if found is not None:
                    sess = found
                    run_dir_match = out_dir
                    break
        if sess is None or run_dir_match is None:
            self.send_error(404, "no such event")
            return True
        if not sess.is_active():
            self.send_error(410, "event revoked or expired")
            return True
        qs = parse_qs(_up(self.path).query)
        try:
            since_ms = int((qs.get("since") or ["0"])[0])
        except (TypeError, ValueError):
            since_ms = 0
        # Try the canonical v0.5+ JSONL file first; fall back to the
        # legacy directory of *.json files (older runs, manual edits).
        ann_jsonl = run_dir_match / "annotations.jsonl"
        ann_dir = run_dir_match / "annotation"
        src = ann_jsonl if ann_jsonl.exists() else ann_dir
        annotations, server_ts = compute_changes_since(src, since_ms)
        body = _safe_dumps({
            "schema":      "pixcull.sync.changes/v1",
            "run_id":      sess.run_id,
            "event_id":    sess.event_id,
            "server_ts":   server_ts,
            "annotations": annotations,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    # ============================================================
    # v0.8-P1-3 — short links + QR
    # ============================================================
    def _handle_shortlink_issue(self) -> None:
        """POST /s/issue  body: {long_url, ttl_hours?, label?}

        Long URL can be either an absolute URL the client has in
        hand (e.g. from /share/issue or /sync/event/issue), or a
        relative path starting with "/" — in which case the
        response wraps it as origin-relative so the QR encodes a
        complete URL the recipient's phone can open.

        Idempotent: same long_url → same short_code (see
        pixcull.shortlink.issue).
        """
        try:
            from pixcull.shortlink import issue as _issue
        except Exception as exc:
            _dbg("shortlink/import", exc, "issue")
            self.send_error(500, "shortlink module import failed")
            return
        body = self._read_json_body()
        long_url = body.get("long_url") or ""
        if not isinstance(long_url, str) or not long_url.strip():
            self.send_error(400, "missing 'long_url'")
            return
        try:
            ttl = int(body.get("ttl_hours") or (24 * 30))
        except (TypeError, ValueError):
            ttl = 24 * 30
        label = str(body.get("label") or "")[:120]
        try:
            rec = _issue(_DEMO_ROOT, long_url, ttl_hours=ttl, label=label)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        except Exception as exc:
            _dbg("shortlink/issue", exc, long_url[:60])
            self.send_error(500, "failed to issue short link")
            return
        code = rec["short_code"]
        self._json_ok({
            "ok":         True,
            "short_code": code,
            "short_url":  f"/s/{code}",
            "qr_url":     f"/s/{code}.svg",
            "long_url":   rec["long_url"],
            "expires_at": rec.get("expires_at"),
        })

    def _serve_shortlink_redirect(self, code: str) -> None:
        """GET /s/<code> → 302 → long URL (404 missing, 410 expired)."""
        try:
            from pixcull.shortlink import resolve as _resolve
        except Exception as exc:
            _dbg("shortlink/import", exc, "redirect")
            self.send_error(500, "shortlink module import failed")
            return
        rec = _resolve(_DEMO_ROOT, code)
        if rec is None:
            self.send_error(404, "unknown short code")
            return
        if rec.get("expired"):
            self.send_error(410, "short link expired")
            return
        long_url = str(rec.get("long_url") or "")
        if not long_url:
            self.send_error(500, "store missing long_url")
            return
        self.send_response(302)
        self.send_header("Location", long_url)
        # noindex so search engines don't follow + index shared links
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        # Don't cache redirects — short link store can be revoked
        # at any time.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_shortlink_qr(self, code: str) -> None:
        """GET /s/<code>.svg → inline QR pointing at the LONG url.

        The QR encodes the full origin-prefixed URL so the recipient's
        phone camera can scan it directly without depending on
        /s/<code> resolving correctly on their network (e.g. a guest
        on a different Wi-Fi.  We still default to /s/<code> as the
        href but the QR carries the absolute long_url.)
        """
        try:
            from pixcull.shortlink import resolve as _resolve
            from pixcull.qrcode_svg import to_svg
        except Exception as exc:
            _dbg("shortlink/qr/import", exc, "qr")
            self.send_error(500, "shortlink/qr import failed")
            return
        rec = _resolve(_DEMO_ROOT, code)
        if rec is None:
            self.send_error(404, "unknown short code")
            return
        if rec.get("expired"):
            self.send_error(410, "short link expired")
            return
        long_url = str(rec.get("long_url") or "")
        if not long_url:
            self.send_error(500, "store missing long_url")
            return
        # If long_url is origin-relative ("/..."), prepend the host
        # so the QR resolves to a complete absolute URL.  Use the
        # Host header so behind-proxy installs still produce the
        # right user-facing origin.
        if long_url.startswith("/"):
            host = self.headers.get("Host") or "localhost"
            scheme = "https" if self.headers.get(
                "X-Forwarded-Proto", "").lower() == "https" else "http"
            long_url = f"{scheme}://{host}{long_url}"
        try:
            svg = to_svg(long_url)
        except ValueError as exc:
            # URL too long for v10 — degrade with a tiny "URL too long"
            # placeholder rather than 500.
            _dbg("shortlink/qr/encode", exc, code)
            self.send_error(400, "url too long for QR")
            return
        body = svg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # QRs are deterministic per (code, host) → cache aggressively
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _serve_style_distances(self, run_id: str) -> None:
        """GET /style/distances/<run_id> → {filename: distance, ...}

        Returns the persisted distance map or an empty {} when no
        profile has been trained yet.  We never re-derive on the
        fly — train explicitly via POST /style/train/<run_id>.
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        path = self._style_distances_path(run)
        if not path.exists():
            body = b"{}"
        else:
            try:
                body = path.read_bytes()
            except OSError as exc:
                _dbg("style/serve_distances", exc, run_id)
                body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ============================================================
    # v0.7-P2-2 — tethered live scoring HTTP wiring
    # ============================================================
    def _json_ok(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            d = json.loads(raw or b"{}")
        except ValueError:
            d = {}
        return d if isinstance(d, dict) else {}

    # ============================================================
    # v0.7-P2-4 — history timeline page (/history)
    #
    # Walks _DEMO_ROOT for every run dir, harvests:
    #   - run_id (folder name)
    #   - last-modified mtime (for sorting)
    #   - scores.csv summary (count by decision, first thumb)
    #   - manifest.json (for source label) when present
    # Renders a date-sorted card grid. Each card links to
    # /results/<run_id>. Self-contained HTML — reuses
    # _DESIGN_TOKENS_CSS for visual consistency.
    # ============================================================
    def _collect_history_entries(self) -> list[dict]:
        """Scan _DEMO_ROOT for runs, summarise each.

        Best-effort: a missing scores.csv or manifest never throws
        — we just emit a card with zeros and let the user click
        through to see the (possibly broken) results page.
        """
        import csv as _csv

        entries: list[dict] = []
        if not _DEMO_ROOT.is_dir():
            return entries
        for child in _DEMO_ROOT.iterdir():
            if not child.is_dir():
                continue
            run_id = child.name
            if run_id.startswith("."):
                continue
            output_dir = child / "output"
            scores = output_dir / "scores.csv"
            manifest = output_dir / "manifest.json"
            # Use the most recently-touched file in the dir as a
            # proxy for "when did this run finish" — robust to
            # systems where dir mtime is misleading.
            try:
                mtime = child.stat().st_mtime
                for sub in (scores, manifest, output_dir):
                    if sub.exists():
                        m = sub.stat().st_mtime
                        if m > mtime:
                            mtime = m
            except OSError:
                continue

            n_total = n_keep = n_maybe = n_cull = 0
            first_filename: str | None = None
            if scores.exists():
                try:
                    with open(scores, "r", encoding="utf-8-sig",
                              newline="") as fh:
                        for row in _csv.DictReader(fh):
                            n_total += 1
                            d = row.get("decision") or ""
                            if d == "keep":
                                n_keep += 1
                            elif d == "maybe":
                                n_maybe += 1
                            elif d == "cull":
                                n_cull += 1
                            if first_filename is None:
                                first_filename = row.get("filename") or None
                except OSError as exc:
                    _dbg("history/scores_read", exc, str(scores))

            source_label = ""
            if manifest.exists():
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    # Manifest schema varies — try the most common
                    # fields. Fall back to "scan" if any are set.
                    if isinstance(m, dict):
                        source_label = (
                            m.get("source_dir")
                            or m.get("input_dir")
                            or "scan"
                        )
                except (OSError, ValueError):
                    pass
            elif (child / "input").is_dir():
                source_label = "上传"

            entries.append({
                "run_id":          run_id,
                "mtime":           mtime,
                "n_total":         n_total,
                "n_keep":          n_keep,
                "n_maybe":         n_maybe,
                "n_cull":          n_cull,
                "first_filename":  first_filename,
                "source_label":    source_label,
            })
        # Newest first
        entries.sort(key=lambda e: e["mtime"], reverse=True)
        return entries

    def _serve_history_page(self) -> None:
        entries = self._collect_history_entries()
        # Build the cards
        from html import escape as _esc

        def _fmt_mtime(t: float) -> str:
            try:
                return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                return ""

        def _decision_bar(e: dict) -> str:
            tot = max(e["n_total"], 1)
            kw = round(e["n_keep"] / tot * 100, 1)
            mw = round(e["n_maybe"] / tot * 100, 1)
            cw = round(e["n_cull"] / tot * 100, 1)
            return (
                '<div class="bar" title="' +
                _esc(f"keep {e['n_keep']} · maybe {e['n_maybe']} · cull {e['n_cull']}") +
                f'"><span class="seg k" style="width:{kw}%"></span>'
                f'<span class="seg m" style="width:{mw}%"></span>'
                f'<span class="seg c" style="width:{cw}%"></span></div>'
            )

        cards = []
        for e in entries:
            thumb = ""
            if e["first_filename"]:
                thumb = (
                    f'<img loading="lazy" '
                    f'src="/thumb/{_esc(e["run_id"])}/{_esc(e["first_filename"])}?w=420" '
                    f'alt="thumbnail">'
                )
            else:
                thumb = '<div class="no-thumb">·</div>'
            cards.append(
                f'<a class="card" href="/results/{_esc(e["run_id"])}">'
                f'<div class="thumb">{thumb}</div>'
                f'<div class="meta">'
                f'<div class="rid" title="{_esc(e["run_id"])}">{_esc(e["run_id"])}</div>'
                f'<div class="when">{_fmt_mtime(e["mtime"])}'
                + (f' · <span class="src">{_esc(str(e["source_label"]))}</span>' if e["source_label"] else "")
                + f'</div>'
                f'{_decision_bar(e)}'
                f'<div class="counts">{e["n_total"]} 张 · '
                f'<span class="k">{e["n_keep"]}</span> · '
                f'<span class="m">{e["n_maybe"]}</span> · '
                f'<span class="c">{e["n_cull"]}</span></div>'
                f'</div>'
                f'</a>'
            )
        cards_html = "\n".join(cards) if cards else (
            '<div class="empty">还没有跑过任何 run。<br>'
            '<a href="/" style="color:var(--accent)">回上传页 →</a></div>'
        )

        page = (
            r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PixCull · 历史时间线</title>
<style>
"""
            + _DESIGN_TOKENS_CSS
            + r"""
  *,*::before,*::after { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  header {
    padding: 36px 24px 18px; border-bottom: 1px solid var(--border);
    text-align: center;
  }
  header h1 { margin: 0 0 4px; font-size: 26px; font-weight: 700; }
  header .sub { color: var(--muted); margin: 0; font-size: 13px; }
  header a.back { color: var(--muted); font-size: 12px;
                  text-decoration: none; margin-right: 12px; }
  header a.back:hover { color: var(--fg); }
  main { padding: 28px 24px; max-width: 1280px; margin: 0 auto; }
  .count { text-align: center; color: var(--muted); font-size: 12px;
           margin: 0 0 18px; letter-spacing: 0.04em; text-transform: uppercase; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
  }
  .card {
    display: block; background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius-lg, 10px); overflow: hidden;
    color: inherit; text-decoration: none;
    transition: transform var(--duration-fast, 160ms) var(--ease-out),
                border-color var(--duration-fast, 160ms) var(--ease-out);
  }
  .card:hover { transform: translateY(-2px); border-color: var(--accent); }
  .thumb { aspect-ratio: 4/3; background: var(--surface-2, #1a1d22);
           display: flex; align-items: center; justify-content: center; overflow: hidden; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; }
  .no-thumb { color: var(--muted); font-size: 32px; opacity: 0.4; }
  .meta { padding: 12px 14px; }
  .rid {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 11.5px; color: var(--fg);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .when { color: var(--muted); font-size: 11px; margin-top: 2px; }
  .when .src { color: var(--fg-2, var(--fg)); }
  .bar {
    display: flex; height: 6px; margin: 10px 0 6px;
    border-radius: 3px; overflow: hidden; background: var(--surface-2, #2a2d33);
  }
  .bar .seg { display: inline-block; min-width: 0; height: 100%; }
  .bar .seg.k { background: var(--c-success); }
  .bar .seg.m { background: var(--c-warn); }
  .bar .seg.c { background: var(--c-danger); }
  .counts { font-size: 11px; color: var(--muted);
            font-family: ui-monospace, "SF Mono", Menlo, monospace; }
  .counts .k { color: var(--c-success); }
  .counts .m { color: var(--c-warn); }
  .counts .c { color: var(--c-danger); }
  .empty { text-align: center; color: var(--muted); padding: 60px 12px;
           font-size: 14px; line-height: 1.6; }
  @media (max-width: 640px) {
    header { padding: 22px 14px 14px; }
    header h1 { font-size: 19px; }
    main { padding: 16px 12px; }
    .grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
  }
</style>
</head>
<body>
  <header>
    <a class="back" href="/">← 上传页</a>
    <h1>历史时间线</h1>
    <p class="sub">所有跑过的 run · 按时间排序 · 点卡片跳回 grid</p>
  </header>
  <main>
    <p class="count">"""
            + f"{len(entries)} 个 run"
            + r"""</p>
    <div class="grid">
"""
            + cards_html
            + r"""
    </div>
  </main>
</body>
</html>
"""
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # NOTE — _handle_tether_start / _handle_tether_stop already exist
    # further down (P2.2 base implementation). Top-level /tether/start
    # + /tether/<sid>/stop POST routes (above, in do_POST) call those
    # canonical handlers — we deliberately don't redefine them here.

    def _serve_tether_sessions(self) -> None:
        """GET /tether/sessions → {sessions: [...]}.

        Mirrors the /api/v1/tether GET endpoint but at the top level
        so the v0.7-P2-2 control panel (/tether) can fetch without
        the auth/cors layer.
        """
        try:
            from pixcull import tether as _tether_mod
            payload = {"sessions": _tether_mod.list_sessions()}
        except Exception as exc:
            _dbg("tether/list", exc, "")
            payload = {"sessions": [], "error": str(exc)}
        self._json_ok(payload)

    def _serve_tether_status(self, session_id: str) -> None:
        """GET /tether/status/<session_id> → status snapshot."""
        try:
            from pixcull import tether as _tether_mod
        except Exception as exc:
            _dbg("tether/import", exc, "status")
            self.send_error(500, "tether module import failed")
            return
        s = _tether_mod.get_session(session_id)
        if s is None:
            self.send_error(404, "no such tether session")
            return
        self._json_ok(s.status())

    def _serve_tether_page(self) -> None:
        """GET /tether → minimal control panel for tethered live scoring.

        Self-contained; reuses the upload-page dark palette via
        _DESIGN_TOKENS_CSS so the page stays consistent with the
        rest of the product.
        """
        page = (
            r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PixCull · Tethered Live</title>
<style>
"""
            + _DESIGN_TOKENS_CSS
            + r"""
  *,*::before,*::after { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  main { max-width: 880px; margin: 0 auto; padding: 48px 24px; }
  h1 { font-size: 28px; font-weight: 700; margin: 0 0 4px; }
  h1 .live-dot {
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    background: var(--c-danger); margin-left: 10px;
    box-shadow: 0 0 0 0 rgba(248,113,113,0.6);
    animation: pulse 1.6s var(--ease-out) infinite;
    vertical-align: middle;
  }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(248,113,113,0.55); }
    70%  { box-shadow: 0 0 0 12px rgba(248,113,113,0); }
    100% { box-shadow: 0 0 0 0 rgba(248,113,113,0); }
  }
  .sub { color: var(--muted); margin: 0 0 24px; font-size: 13px; }
  .panel { background: var(--bg-card); border: 1px solid var(--border);
           border-radius: var(--radius-lg, 10px); padding: 18px 22px; margin-bottom: 16px; }
  .panel h2 { font-size: 15px; margin: 0 0 12px; letter-spacing: 0.03em;
              text-transform: uppercase; color: var(--muted); font-weight: 600; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .row label { color: var(--muted); font-size: 12px; min-width: 92px; }
  input[type=text], select {
    flex: 1; padding: 8px 12px; background: var(--surface-2, rgba(255,255,255,0.06));
    border: 1px solid var(--border); border-radius: 6px; color: var(--fg);
    font-size: 13px; font-family: inherit; min-width: 260px;
  }
  button {
    padding: 8px 18px; border: 1px solid var(--accent); background: var(--accent);
    color: #fff; border-radius: 6px; cursor: pointer; font-size: 13px;
    font-weight: 600; font-family: inherit;
    transition: transform 120ms var(--ease-out), background 120ms var(--ease-out);
  }
  button:hover { transform: translateY(-1px); }
  button.ghost { background: transparent; color: var(--fg); border-color: var(--border); }
  button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
  .status-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: 10px;
    margin-top: 10px;
  }
  .stat { background: var(--surface-2, rgba(255,255,255,0.04)); padding: 10px 12px;
          border-radius: 6px; border: 1px solid var(--border); }
  .stat .k { color: var(--muted); font-size: 10.5px; letter-spacing: 0.05em;
             text-transform: uppercase; }
  .stat .v { color: var(--fg); font-size: 18px; font-weight: 700; margin-top: 2px;
             font-family: ui-monospace, "SF Mono", Menlo, monospace; }
  .live-row {
    background: var(--surface-2, rgba(255,255,255,0.04));
    border: 1px solid var(--border); border-radius: 6px;
    padding: 10px 14px; font-size: 12px; color: var(--fg-2, var(--fg));
    display: flex; gap: 12px; align-items: center;
  }
  .live-row .dec {
    padding: 2px 8px; border-radius: 4px; font-weight: 600;
    font-size: 10.5px; letter-spacing: 0.04em; text-transform: uppercase;
  }
  .live-row .dec.keep  { background: var(--c-success); color: #fff; }
  .live-row .dec.maybe { background: var(--c-warn);    color: #fff; }
  .live-row .dec.cull  { background: var(--c-danger);  color: #fff; }
  .live-row .fn { font-family: ui-monospace, "SF Mono", Menlo, monospace; flex: 1; }
  .live-row .when { color: var(--muted); font-size: 10.5px; }
  .empty { color: var(--muted); font-size: 12px; padding: 20px; text-align: center; }
  a.openrun {
    display: inline-block; margin-top: 12px; padding: 8px 14px;
    background: transparent; border: 1px solid var(--border); border-radius: 6px;
    color: var(--fg); text-decoration: none; font-size: 12px;
  }
  a.openrun:hover { border-color: var(--accent); }
  .note { color: var(--muted); font-size: 11.5px; margin-top: 12px; line-height: 1.5; }
</style>
</head>
<body>
  <main>
    <h1>Tethered Live <span class="live-dot" id="liveDot" style="display:none"></span></h1>
    <p class="sub">监听某个 tether 文件夹 — 新照片落地即刻分析,grid 实时刷新。</p>

    <section class="panel">
      <h2>开始监听</h2>
      <div class="row">
        <label for="tetherFolder">文件夹路径</label>
        <input type="text" id="tetherFolder" placeholder="/Users/you/Pictures/tether 或 拖文件夹到这里"/>
        <button id="startBtn" type="button">▶ 开始</button>
      </div>
      <p class="note">支持本地任意文件夹。session 启动时会快照当前已有文件,只对新增的文件分析(不会重新分析已有照片)。</p>
    </section>

    <section class="panel">
      <h2>会话状态</h2>
      <div id="sessionsWrap"><div class="empty">还没有正在运行的会话。</div></div>
    </section>
  </main>

<script>
  const startBtn = document.getElementById("startBtn");
  const folderInput = document.getElementById("tetherFolder");
  const sessionsWrap = document.getElementById("sessionsWrap");
  const liveDot = document.getElementById("liveDot");

  startBtn.addEventListener("click", async () => {
    const folder = folderInput.value.trim();
    if (!folder) { alert("请输入或粘贴文件夹路径"); return; }
    startBtn.disabled = true; const orig = startBtn.textContent;
    startBtn.textContent = "启动中…";
    try {
      const r = await fetch("/tether/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({folder}),
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(`HTTP ${r.status} ${t.slice(0,80)}`);
      }
      const d = await r.json();
      folderInput.value = "";
      await refresh();
      // Open the run in a new tab so the user has the live grid
      // beside this control panel.
      window.open(d.url, "_blank");
    } catch (err) {
      alert("启动失败: " + err.message);
    } finally {
      startBtn.disabled = false; startBtn.textContent = orig;
    }
  });

  function fmtAge(epochSec) {
    if (!epochSec) return "—";
    const ageSec = Math.max(0, Math.floor(Date.now()/1000 - epochSec));
    if (ageSec < 5)    return "刚刚";
    if (ageSec < 60)   return `${ageSec} 秒前`;
    if (ageSec < 3600) return `${Math.floor(ageSec/60)} 分前`;
    return `${Math.floor(ageSec/3600)} 时前`;
  }

  async function refresh() {
    try {
      const r = await fetch("/tether/sessions");
      const d = await r.json();
      const sessions = d.sessions || [];
      if (!sessions.length) {
        sessionsWrap.innerHTML = `<div class="empty">还没有正在运行的会话。</div>`;
        liveDot.style.display = "none";
        return;
      }
      liveDot.style.display = "";
      sessionsWrap.innerHTML = sessions.map(s => {
        const last = s.last || {};
        return `
        <div class="panel" style="margin-top:8px;padding:14px 18px" data-sid="${s.session_id}">
          <div style="display:flex;gap:10px;align-items:baseline;justify-content:space-between">
            <div>
              <div style="font-weight:600">${escapeHtml(s.folder)}</div>
              <div style="color:var(--muted);font-size:11px;margin-top:2px">${s.session_id}${s.vertical ? ' · ' + s.vertical : ''}${s.running ? '' : ' · <span style="color:var(--c-warn)">已停止</span>'}</div>
            </div>
            <div style="display:flex;gap:6px">
              <button class="ghost stop-btn" data-sid="${s.session_id}" type="button" ${s.running ? '' : 'disabled'}>⏹ 停止</button>
              <a class="openrun" href="/results/${s.run_id}" target="_blank">查看 grid →</a>
            </div>
          </div>
          <div class="status-grid">
            <div class="stat"><div class="k">已分析</div><div class="v">${s.n_analyzed || 0}</div></div>
            <div class="stat"><div class="k">失败</div><div class="v">${s.n_failed || 0}</div></div>
            <div class="stat"><div class="k">运行时长</div><div class="v">${fmtDuration(s.elapsed_s)}</div></div>
            <div class="stat"><div class="k">最后事件</div><div class="v">${fmtAge(last.at)}</div></div>
          </div>
          ${last.filename ? `
          <div class="live-row" style="margin-top:10px">
            <span class="dec ${last.decision || 'maybe'}">${last.decision || '—'}</span>
            <span class="fn">${escapeHtml(last.filename)}</span>
            <span class="when">${fmtAge(last.at)}</span>
          </div>` : ''}
        </div>
      `;
      }).join("");
      // Wire stop buttons
      sessionsWrap.querySelectorAll(".stop-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
          if (!confirm("停止这个 tether 会话?")) return;
          await fetch(`/tether/${btn.dataset.sid}/stop`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
          });
          refresh();
        });
      });
    } catch (_e) { /* offline / temp error — keep last render */ }
  }
  function fmtDuration(sec) {
    if (!sec) return "—";
    sec = Math.floor(sec);
    if (sec < 60) return `${sec}s`;
    if (sec < 3600) return `${Math.floor(sec/60)}m ${sec%60}s`;
    return `${Math.floor(sec/3600)}h ${Math.floor((sec%3600)/60)}m`;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  // Poll every 2s — tight enough to feel live, slack enough to
  // not drown the server on a long shoot.
  refresh();
  setInterval(refresh, 2000);
</script>
</body>
</html>
"""
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_sample_demo(self) -> None:
        """P-UX-21 — instant sample-data path.

        Copies the bundled ``samples/`` directory (pre-scored 6-photo
        landscape + wildlife set) into a fresh demo run so visitors
        can hit /results without uploading anything or waiting on
        model warm-up.

        The sample scores.csv was generated procedurally with realistic
        rubric stars per scene. The 6 input JPGs are 1280×853 gradients
        (~40 KB each) — small enough to ship in the repo, varied enough
        to demonstrate keep/maybe/cull across landscape + wildlife +
        architecture verticals.

        POST /sample_demo  → {ok, run_id, url}
        """
        import shutil
        import secrets as _secrets

        # Project root contains a samples/ tree we ship in-repo
        proj_root = Path(__file__).resolve().parent.parent
        src = proj_root / "samples" / "output"
        if not (src / "scores.csv").is_file():
            self._reject_upload(500, "samples/ not bundled with this build")
            return
        run_id = "sample_" + _secrets.token_hex(4)
        dst = _DEMO_ROOT / run_id / "output"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)

        # Manifest in samples/output points at samples/input/*.jpg with
        # absolute paths. Those paths were computed at sample-generation
        # time and may not match this checkout — rewrite them based on
        # the actual on-disk location now.
        manifest_path = dst / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text("utf-8"))
                samples_input = proj_root / "samples" / "input"
                fixed = {
                    fn: str(samples_input / fn)
                    for fn in manifest.keys()
                    if (samples_input / fn).is_file()
                }
                manifest_path.write_text(
                    json.dumps(fixed, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except (OSError, json.JSONDecodeError):
                pass

        # Register the run with the in-memory store as a "scan-mode"
        # run so /thumb + /full + /results work without a re-analysis.
        with _RUNS_LOCK:
            _RUNS[run_id] = {
                "run_id":     run_id,
                "output_dir": str(dst),
                "input_dir":  "",
                "mode":       "scan",
                "source_dir": str(proj_root / "samples" / "input"),
                "state":      "done",
                "started_at": time.time(),
                "finished_at": time.time(),
                "vertical":   None,
            }

        body = _safe_dumps({
            "ok":     True,
            "run_id": run_id,
            "url":    f"/results/{run_id}",
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_scan_local(self) -> None:
        """Analyze a local folder *in place*. No file copy, no upload.

        Body: {folder: "/abs/path"} — the path is interpreted on the
        SERVER's filesystem. This is the right mode for users who already
        have their RAW collection organized on disk and don't want to
        duplicate gigabytes into /tmp.

        We import list_images here too so the file count + sample list
        is available immediately (no need to wait for the analyzer thread
        to start). The pipeline thread re-walks the dir; that walk is
        cheap relative to the actual analysis.
        """
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 65536:
            self._reject_upload(400, "expected small JSON body with {folder}")
            return
        try:
            params = json.loads(self.rfile.read(clen).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}")
            return
        folder_str = (params.get("folder") or "").strip()
        if not folder_str:
            self._reject_upload(400, "需要 folder 字段:服务端的绝对文件夹路径")
            return
        # V17.0 — optional vertical override. Empty / unknown key is
        # treated as "auto detect" (no override), matching the
        # dropdown's first option.
        vertical = (params.get("vertical") or "").strip().lower()
        if vertical:
            from pixcull import verticals as vmod
            if vmod.get_vertical(vertical) is None:
                vertical = ""  # silently fall back to auto-detect

        # Expand ~/ and resolve symlinks so the user can paste either an
        # absolute path or a tilde-relative one.
        folder = Path(folder_str).expanduser()
        try:
            folder = folder.resolve()
        except OSError as exc:
            self._reject_upload(400, f"路径解析失败: {exc}")
            return
        if not folder.exists():
            self._reject_upload(404, f"路径不存在: {folder}")
            return
        if not folder.is_dir():
            self._reject_upload(400, f"不是文件夹: {folder}")
            return

        # Count images. Reuse the project's loader so we apply the exact
        # same suffix filter the pipeline will use — no surprises like
        # "browser saw 50 files but pipeline only analyzed 32".
        from pixcull.io.loader import list_images
        try:
            paths = list_images(folder)
        except Exception as exc:  # noqa: BLE001
            self._reject_upload(500, f"扫描失败: {exc}")
            return
        if not paths:
            self._reject_upload(
                400,
                f"在 {folder} 下没找到可分析的图片(支持 jpg/png/cr3/cr2/nef/arw/dng/tif)",
            )
            return

        n = len(paths)
        # V12.0 — license + monthly quota gate. Free tier 100/月.
        from pixcull.license import check_quota, increment_usage
        ok, msg = check_quota(n)
        if not ok:
            self._reject_upload(402, msg)
            return
        increment_usage(n)

        run_id = _new_run_id()
        run_root = _run_dir(run_id)
        output_dir = run_root / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Persist the file manifest so /thumb/<run_id>/<filename> can
        # resolve "filename → absolute original path" later, even if the
        # server restarts mid-run. Plain JSON, one entry per analyzed
        # image. Names are basename-only — pipeline's CSV uses bare names
        # too.
        manifest = {p.name: str(p) for p in paths}
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        rescorer_mode = self.server.rescorer_mode  # type: ignore[attr-defined]
        rescorer_path = self.server.rescorer_path  # type: ignore[attr-defined]
        vlm_mode = self.server.vlm_mode  # type: ignore[attr-defined]
        meta_mode = self.server.meta_mode  # type: ignore[attr-defined]

        _set_run(
            run_id,
            state="queued",
            mode="scan",
            done=0,
            total=n,
            message=f"已索引 {n} 张图,准备分析(原图不复制)…",
            source_dir=str(folder),
            output_dir=str(output_dir),
            n_uploaded=n,
            origin_folder=str(folder),
            vertical=vertical or None,   # V17.0 — None = auto-detect
        )
        threading.Thread(
            target=_analyze_in_background,
            args=(run_id, rescorer_mode, rescorer_path, vlm_mode, meta_mode),
            daemon=True,
        ).start()

        body = json.dumps({
            "run_id": run_id,
            "n": n,
            "folder": str(folder),
            "sample": [p.name for p in paths[:5]],
        }, ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    def _handle_browse(self) -> None:
        """Server-side directory listing for the folder picker.

        Body: {path?: str}  (omit or empty = $HOME)

        Returns: {path, parent, entries: [{name, is_dir, n_images}]}

        We only list directories + show an image-count hint per dir. Files
        themselves aren't listed (pipeline doesn't operate on individual
        files, only folders). Hidden dirs (.*) are skipped to keep the
        UI clean — pose a folder explicitly if you need to scan one.
        """
        clen = int(self.headers.get("Content-Length", "0") or "0")
        body_bytes = self.rfile.read(clen) if clen > 0 else b"{}"
        try:
            params = json.loads(body_bytes.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}")
            return

        target_str = (params.get("path") or "").strip() or str(Path.home())
        target = Path(target_str).expanduser()
        try:
            target = target.resolve()
        except OSError as exc:
            self._reject_upload(400, f"路径解析失败: {exc}")
            return
        if not target.is_dir():
            self._reject_upload(404, f"不是文件夹: {target}")
            return

        # Quick image counter — same suffix set as the pipeline. Counting
        # one level down is cheap; recursive count would scale poorly
        # for deep trees.
        IMG_EXTS = {".jpg", ".jpeg", ".png", ".cr3", ".cr2", ".nef", ".arw", ".dng", ".tif", ".tiff"}
        entries = []
        try:
            for child in sorted(target.iterdir(), key=lambda x: x.name.lower()):
                # Skip hidden + system dirs unless target itself is hidden
                if child.name.startswith(".") and not target.name.startswith("."):
                    continue
                if child.is_dir():
                    n_imgs = 0
                    try:
                        for f in child.iterdir():
                            if f.is_file() and f.suffix.lower() in IMG_EXTS:
                                n_imgs += 1
                    except (OSError, PermissionError):
                        n_imgs = -1  # signal "couldn't read"
                    entries.append({
                        "name": child.name,
                        "is_dir": True,
                        "n_images": n_imgs,
                    })
        except PermissionError:
            self._reject_upload(403, f"没有权限读取: {target}")
            return

        # Top-level direct image count — useful when the user lands on
        # a folder that already holds images at its root.
        n_imgs_here = 0
        try:
            for f in target.iterdir():
                if f.is_file() and f.suffix.lower() in IMG_EXTS:
                    n_imgs_here += 1
        except OSError as exc:
            _dbg("browse/iterdir", exc, str(target))

        body = json.dumps({
            "path": str(target),
            "parent": str(target.parent) if target.parent != target else None,
            "n_images_here": n_imgs_here,
            "entries": entries,
        }, ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    def _serve_status(self, run_id: str) -> None:
        run = _get_run(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        # Strip path fields that the browser doesn't need
        view = {
            k: v for k, v in run.items()
            if k not in ("input_dir", "output_dir")
        }
        body = json.dumps(view, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_results(self, run_id: str) -> None:
        result = _build_results(run_id)
        if result is None:
            # V14.0 — distinguish "run hasn't started/doesn't exist" from
            # "run finished but produced no analyzable images". The first
            # is a real 404; the second is a polite "your batch contained
            # 0 valid images, here's why" page.
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(
                    404,
                    "no such run — run_id may be wrong or expired",
                )
                return
            # Run exists but no scores.csv yet — pipeline still running
            self.send_error(
                425,  # Too Early — semantically correct for "not done yet"
                "results not ready — pipeline may still be running. "
                "Refresh in a few seconds.",
            )
            return
        rows, summary = result
        # V22.1 — assemble per-cluster summary + per-run labels for the
        # UI filter pill row. Labels live in <output_dir>/face_labels.json
        # so they survive server restarts (V22.0's clusters are
        # run-scoped; V22.2+ will add cross-run inheritance).
        face_clusters_info = _build_face_clusters_info(run_id, rows)
        # V23 — GPS location clusters + per-cluster "best" picker.
        locations_info = _build_locations_info(rows, run_id)
        payload = {
            "run_id": run_id,
            "rows": rows,
            "summary": summary,
            "face_clusters": face_clusters_info,
            "locations": locations_info,
        }
        # _safe_dumps strips NaN/Infinity (V14.0) so JS JSON.parse never
        # blows up on a stray inf in score_final or a NaN in axis stars.
        # V19.4.1 — hot-reloadable template (loaded from disk per request,
        # mtime-cached). Editing pixcull/report/templates/results.html
        # picks up on the next /results hit; no server restart required.
        html = _results_html_template().replace(
            "__PAYLOAD__",
            _safe_dumps(payload).replace("</", "<\\/"),
        )
        self._send_html(200, html.encode("utf-8"))

    def _serve_decisions(self, run_id: str) -> None:
        """V21.2 — minimal JSON for the Lightroom plugin write-back.

        Lightroom Lua plugins want as little to parse as possible; this
        endpoint returns ``{filename: decision, ...}`` plus a small
        summary block. The Lr ``WriteBackDecisions.lua`` script reads
        it, maps decisions to star ratings + reject flags
        (keep → 5★, maybe → 3★, cull → reject), and applies them via
        ``LrPhoto:setRawMetadata``.

        Schema:
            {
              "run_id":   str,
              "schema":   "pixcull.decisions.v1",
              "decisions": {filename: "keep"|"maybe"|"cull", ...},
              "summary":  {keep: N, maybe: N, cull: N, total: N},
              "src_paths": {filename: "/abs/path", ...}   # optional
            }

        ``src_paths`` is included so the Lr plugin can match its
        catalog photos by absolute path rather than basename (basename
        collisions across folders are real: every Canon shoot has
        an IMG_0001.jpg). The plugin falls back to basename matching
        if abs paths don't appear in the catalog.
        """
        result = _build_results(run_id)
        if result is None:
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(404, "no such run")
                return
            self.send_error(425, "results not ready — pipeline still running")
            return
        rows, summary = result
        decisions: dict[str, str] = {}
        src_paths: dict[str, str] = {}
        for r in rows:
            fn = r.get("filename")
            dec = r.get("decision")
            if not fn or not dec:
                continue
            decisions[fn] = dec
            # Read src_path from the run's scores.csv if available — we
            # already have it in the row builder via ``path``.
            p = r.get("src_path") or r.get("path")
            if p:
                src_paths[fn] = p
        payload = {
            "run_id":    run_id,
            "schema":    "pixcull.decisions.v1",
            "decisions": decisions,
            "summary":   {
                "keep":  sum(1 for v in decisions.values() if v == "keep"),
                "maybe": sum(1 for v in decisions.values() if v == "maybe"),
                "cull":  sum(1 for v in decisions.values() if v == "cull"),
                "total": len(decisions),
            },
            "src_paths": src_paths,
        }
        body = _safe_dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_locations(self, run_id: str) -> None:
        """V23 — GPS location cluster summary for a run.

        Returns the same block we inline into the results-page payload,
        but available as a standalone JSON endpoint for refresh after
        the user picks "select per-location best" so the UI can show
        an updated decision summary.
        """
        result = _build_results(run_id)
        if result is None:
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(404, "no such run")
                return
            self.send_error(425, "results not ready")
            return
        rows, _summary = result
        info = _build_locations_info(rows, run_id)
        info["run_id"] = run_id
        info["schema"] = "pixcull.locations.v1"
        body = _safe_dumps(info).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # --- V28 multi-user / team endpoints ----------------------------------
    def _serve_tether_list(self) -> bool:
        """P2.2 — list active tether sessions."""
        from pixcull.tether import list_sessions
        body = _safe_dumps({
            "schema":   "pixcull.tether.list.v1",
            "sessions": list_sessions(),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _handle_tether_start(self) -> bool:
        """P2.2 — POST /api/v1/tether/start with body
        ``{folder: str, vertical?: str}``. Starts a watcher thread
        that polls the folder for new images and auto-analyzes them.
        Returns the session_id (= run_id) so the caller can hit
        /api/v1/runs/<id>/rows to watch results stream in.
        """
        n = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "invalid JSON")
            return True
        folder = str(body.get("folder") or "").strip()
        if not folder:
            self.send_error(400, "missing 'folder'")
            return True
        vertical = body.get("vertical") or None
        from pixcull.tether import start_session
        try:
            session = start_session(Path(folder), vertical=vertical)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return True
        out = _safe_dumps({
            "ok":          True,
            "session_id":  session.session_id,
            "run_id":      session.run_id,
            "status":      session.status(),
            "results_url": f"/results/{session.run_id}",
        }).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out)
        return True

    def _handle_tether_stop(self, session_id: str) -> bool:
        """P2.2 — POST /api/v1/tether/<session>/stop. Idempotent."""
        from pixcull.tether import stop_session
        ok = stop_session(session_id)
        body = _safe_dumps({
            "ok":         ok,
            "session_id": session_id,
        }).encode("utf-8")
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_sync_status(self) -> bool:
        """INFRA-2 — sync configuration + per-subtree state for the
        active user. See pixcull.sync.status() for the shape."""
        from pixcull.sync import status as sync_status
        body = _safe_dumps(sync_status()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _handle_sync_configure(self) -> bool:
        """INFRA-2 — POST /api/v1/sync_configure with body
        ``{user_id?: str, team_id?: str}`` (one of). Wires the
        sync subtrees for that user/team (symlinks them through
        the shared target). Idempotent.
        """
        n = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "invalid JSON")
            return True
        uid = str(body.get("user_id") or "").strip()
        tid = str(body.get("team_id") or "").strip()
        if not uid and not tid:
            self.send_error(400, "expected user_id or team_id")
            return True
        from pixcull.sync import (
            configure_sync_for_user, configure_sync_for_team,
        )
        if uid:
            result = configure_sync_for_user(uid)
        else:
            result = configure_sync_for_team(tid)
        out = _safe_dumps(result).encode("utf-8")
        self.send_response(200 if result.get("ok") else 400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out)
        return True

    def _serve_llm_budget(self) -> bool:
        """INFRA-4 — daily LLM spend ledger snapshot.

        Returns ``{date_utc, today_yuan, cap_yuan, remaining_yuan,
        calls_today, over_cap, by_model, all_dates[:30]}``. Cap is
        from ``PIXCULL_LLM_BUDGET_YUAN`` env (default 10 yuan/day).
        """
        from pixcull.llm_budget import snapshot
        body = _safe_dumps(snapshot()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_users_list(self) -> bool:
        """V28 — list all user profiles + which one is active."""
        from pixcull.users import list_users, get_active_user
        body = _safe_dumps({
            "schema":   "pixcull.api.v1.users.list",
            "active":   get_active_user(),
            "users":    list_users(),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_users_active(self) -> bool:
        """V28 — just the active user id. Useful for the UI to show
        ``Logged in as: <id>`` in the corner.
        """
        from pixcull.users import get_active_user
        body = _safe_dumps({"active": get_active_user()}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _handle_users_active_post(self) -> bool:
        """V28.2 — POST /api/v1/users/active with body
        ``{user_id: str}`` sets the ``pixcull_user`` cookie. The
        cookie applies only to this browser session; the env var
        baseline is unchanged. Pass empty string / no body to
        clear the cookie (revert to env-var default).

        The cookie is HttpOnly so JS can't read it (mitigates the
        XSS-leaks-active-user attack vector), SameSite=Lax so it
        survives cross-tab navigation but not cross-site requests.
        """
        from pixcull.users import _USER_ID_RE
        n = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "invalid JSON")
            return True
        uid = str(body.get("user_id") or "").strip()
        # Validate against the same allowlist as create_user. Empty
        # input is OK — that's the "clear cookie" signal.
        if uid and not _USER_ID_RE.match(uid):
            self.send_error(400, "invalid user_id format")
            return True
        out_body = _safe_dumps({
            "ok":     True,
            "active": uid or "default",
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out_body)))
        # Cookie management: set when uid is non-empty, expire (Max-Age=0)
        # when it's the empty "clear" signal.
        if uid:
            self.send_header(
                "Set-Cookie",
                f"pixcull_user={uid}; Path=/; HttpOnly; "
                f"SameSite=Lax; Max-Age=2592000",   # 30 days
            )
        else:
            self.send_header(
                "Set-Cookie",
                "pixcull_user=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
            )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out_body)
        return True

    def _handle_users_create(self) -> bool:
        """V28 — POST /api/v1/users with body {user_id: str}.
        Creates a new profile dir. Idempotent.
        """
        from pixcull.users import create_user
        n = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "invalid JSON")
            return True
        try:
            result = create_user(str(body.get("user_id") or ""))
        except ValueError as exc:
            self.send_error(400, str(exc))
            return True
        # INFRA-2 — auto-wire sync if a shared target is configured.
        # No-op (and no error) when PIXCULL_SYNC_DIR isn't set, so
        # single-machine installs are unaffected.
        sync_result = None
        try:
            from pixcull.sync import configure_sync_for_user
            sync_result = configure_sync_for_user(result["user_id"])
        except Exception as exc:  # noqa: BLE001
            sync_result = {"ok": False, "error": str(exc)}
        out_body: dict = {"ok": True, **result}
        if sync_result and sync_result.get("ok"):
            out_body["sync"] = "configured"
        out = _safe_dumps(out_body).encode("utf-8")
        self.send_response(201 if result["created"] else 200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out)
        return True

    def _handle_team_subscribe(self, user_id: str) -> bool:
        """V28 — POST /api/v1/users/<uid>/team_subscribe with body
        {vertical: str, team_id: str|""}.
        Empty team_id = unsubscribe (restore personal bank).
        """
        from pixcull.users import subscribe_to_team_vertical
        n = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "invalid JSON")
            return True
        try:
            result = subscribe_to_team_vertical(
                user_id,
                str(body.get("vertical") or ""),
                str(body.get("team_id") or ""),
            )
        except (ValueError, KeyError) as exc:
            self.send_error(400, str(exc))
            return True
        out = _safe_dumps({"ok": True, **result}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out)
        return True

    def _handle_auto_caption(self, run_id: str) -> None:
        """P2.5 — generate per-photo IPTC captions for a run.

        Body (all optional):
            ``{polish: bool, decisions: ["keep", ...]}``

        Default: ``polish=false`` (compose mode, zero API cost,
        offline). ``decisions`` defaults to ``["keep"]`` — we don't
        waste captions on rows the photographer is going to discard.

        The generated captions land at
        ``<output>/auto_captions.json`` and the next /export run
        picks them up automatically (V29 sidecar / V29.1 embedded).
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        result = _build_results(run_id)
        if result is None:
            self.send_error(425, "results not ready")
            return
        rows, _summary = result
        n = int(self.headers.get("Content-Length") or "0")
        params: dict = {}
        if n > 0:
            try:
                params = json.loads(self.rfile.read(n).decode("utf-8")
                                      or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_error(400, "invalid JSON body")
                return
        polish = bool(params.get("polish") or False)
        decisions = tuple(params.get("decisions") or ["keep"])

        from pixcull.scoring.caption_gen import generate_for_run
        face_labels = _load_face_labels(run_id)
        location_labels = _load_location_labels(run_id)
        output_dir = Path(run["output_dir"])
        info = generate_for_run(
            rows, output_dir,
            face_labels=face_labels,
            location_labels=location_labels,
            polish=polish,
            decisions=decisions,
        )
        body = _safe_dumps({
            "ok":          True,
            "run_id":      run_id,
            "polish":      polish,
            "decisions":   list(decisions),
            **info,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_location_label_post(self, run_id: str) -> None:
        """V23.1 — POST /locations/<run_id>/label with body
        ``{cluster_id: int, label: str}``. Empty label = remove.
        Mirrors V22.1's face-label handler.
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        n = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "invalid JSON body")
            return
        try:
            cid = int(body.get("cluster_id"))
        except (TypeError, ValueError):
            self.send_error(400, "cluster_id must be int")
            return
        label = str(body.get("label") or "").strip()
        if len(label) > 60:        # locations get a bit more room
            label = label[:60]
        labels = _load_location_labels(run_id)
        if label:
            labels[cid] = label
        else:
            labels.pop(cid, None)
        if not _save_location_labels(run_id, labels):
            self.send_error(500, "failed to persist labels")
            return
        out_body = _safe_dumps({
            "ok":     True,
            "run_id": run_id,
            "labels": {str(k): v for k, v in labels.items()},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out_body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out_body)

    def _serve_face_avatar(self, rel: str) -> None:
        """V22.3 — serve a per-cluster face crop JPEG.

        URL: /face_avatar/<run_id>/<cluster_id>
        File: <output_dir>/face_avatars/cluster_<cluster_id>.jpg

        Returns 404 if the avatar doesn't exist (no faces in run, or
        run pre-dates V22.3 — UI falls back to text-only pill).
        """
        parts = unquote(rel).split("/", 1)
        if len(parts) != 2:
            self.send_error(400, "expected /<run_id>/<cluster_id>")
            return
        run_id, cid_str = parts
        try:
            cid = int(cid_str)
        except ValueError:
            self.send_error(400, "cluster_id must be int")
            return
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        p = Path(run["output_dir"]) / "face_avatars" / f"cluster_{cid}.jpg"
        if not p.exists():
            self.send_error(404, "no avatar for this cluster")
            return
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        # Long cache — avatars are content-stable per (run_id, cluster_id)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _serve_face_clusters(self, run_id: str) -> None:
        """V22.1 — face cluster summary + labels for a run.

        Returns the same block we inline into the results-page payload,
        but available as a standalone JSON endpoint so the UI can
        refresh after a label edit without re-rendering the whole
        results page.
        """
        result = _build_results(run_id)
        if result is None:
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(404, "no such run")
                return
            self.send_error(425, "results not ready")
            return
        rows, _summary = result
        info = _build_face_clusters_info(run_id, rows)
        info["run_id"] = run_id
        info["schema"] = "pixcull.face_clusters.v1"
        body = _safe_dumps(info).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_face_label_post(self, run_id: str) -> None:
        """V22.1 — POST /face_clusters/<run_id>/label with body
        {cluster_id: int, label: str} to set a cluster's label.

        Empty / whitespace-only label removes the entry (treat as "unlabel").
        Returns {ok: true, labels: {...latest...}} on success.
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        n = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "invalid JSON body")
            return
        try:
            cid = int(body.get("cluster_id"))
        except (TypeError, ValueError):
            self.send_error(400, "cluster_id must be int")
            return
        label = str(body.get("label") or "").strip()
        # Length cap so a typo doesn't write a megabyte filename.
        if len(label) > 40:
            label = label[:40]

        labels = _load_face_labels(run_id)
        if label:
            labels[cid] = label
        else:
            labels.pop(cid, None)
        if not _save_face_labels(run_id, labels):
            self.send_error(500, "failed to persist labels")
            return

        # V22.2 — when a cluster gets a non-empty label, promote its
        # centroid into the active user's global face library so the
        # label can be auto-inherited in future runs. Unsubscribe
        # (empty label) is a no-op on the library — we don't try to
        # remove past centroids, since the user might re-label later.
        if label:
            try:
                from pixcull.pipeline.face_library import (
                    load_run_centroids, add_to_library,
                )
                from pixcull.users import get_active_user, user_root
                run_dir = Path(run["output_dir"])
                cents = load_run_centroids(run_dir)
                if cents is not None:
                    cluster_ids_arr, centroids = cents
                    # Find the centroid for this specific cluster id
                    matches = (cluster_ids_arr == cid).nonzero()[0]
                    if len(matches) > 0:
                        idx = int(matches[0])
                        add_to_library(
                            user_root(get_active_user()),
                            label,
                            centroids[idx],
                        )
            except Exception as exc:  # noqa: BLE001
                # Library promotion failed — log but don't error the
                # label save (the label is still saved per-run).
                print(f"[label_post] library promotion skipped: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
        out_body = _safe_dumps({
            "ok":     True,
            "run_id": run_id,
            "labels": {str(k): v for k, v in labels.items()},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out_body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out_body)

    def _serve_image(self, rel: str, size: int) -> None:
        # Format: <run_id>/<filename>[?w=N]
        # V14.1 — the client may pass ?w=<viewport_width> so we cap
        # decode at that pixel size. On a 1280-wide laptop a 50-MP
        # JPEG used to materialize 6720×4480 RGB pixels in RAM before
        # downsizing to 1600 — about 90 MB of intermediate data per
        # lightbox click. With ?w= we serve a cache bucket sized to
        # what the client can actually display.
        rel = unquote(rel)
        # Strip + parse query string before run/fn split
        from urllib.parse import parse_qs, urlsplit
        sp = urlsplit("/" + rel)  # path-shaped helper, not a real URL
        rel_path = sp.path.lstrip("/")
        qs = parse_qs(sp.query) if sp.query else {}
        try:
            req_w = int(qs.get("w", ["0"])[0])
        except (TypeError, ValueError):
            req_w = 0
        # Clamp to a sane range. Below 600 isn't worth caching (smaller
        # than every lightbox); above 4096 is past 5K monitors. We round
        # to a few buckets so caches can be reused across slightly
        # different client widths (1280 + 1300 + 1320 all hit the same
        # 1280 bucket).
        #
        # v0.6 (4/5) — also support sub-_THUMB_SIZE buckets [200, 280,
        # 420] so callers that already know they need a tiny thumb
        # (filmstrip strip is 64px tall = ~120-180px wide; similar-
        # photos row is similar) can pull a 200px JPEG instead of the
        # default 420. Halves the bytes per filmstrip photo and cuts
        # decode time on long batches; the new cache key (".200.v3.jpg")
        # never collides with the existing 420 cache.
        if req_w > 0:
            if req_w <= _THUMB_SIZE:
                small_buckets = [200, 280, _THUMB_SIZE]
                chosen = next(
                    (b for b in small_buckets if req_w <= b),
                    small_buckets[-1],
                )
                size = min(chosen, size)
            else:
                buckets = [800, 1200, 1600, 2000, 2400, 3200, 4000]
                chosen = next(
                    (b for b in buckets if req_w <= b), buckets[-1]
                )
                size = min(chosen, size) if size > _THUMB_SIZE else size
        if "/" not in rel_path:
            self.send_error(400, "expected run_id/filename")
            return
        run_id, fn = rel_path.split("/", 1)
        run = _get_run(run_id)
        if run is None:
            # Fall back to disk: maybe the run is from a previous session.
            # Pull mode + source from the on-disk manifest if present.
            run = _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return

        # Resolve filename to a real on-disk source. In upload mode the
        # answer is ``input_dir/<filename>``; in scan mode we look it up
        # in the manifest written when the run started, since the
        # originals live in an arbitrary user folder.
        src = _resolve_image_source(run, Path(fn).name)
        if src is None or not src.exists():
            self.send_error(404, f"not found: {fn}")
            return

        cache_dir = Path(run["output_dir"]) / "thumbs"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # V16.1 — cache key bumped to v2 so stale caches generated
        # before EXIF auto-rotate (which displayed phone-shot portrait
        # JPEGs in their on-disk landscape orientation) are invalidated
        # without a manual ``rm -rf /tmp/pixcull_demo``. Old .jpg files
        # remain on disk but aren't read; admin-page "清理" still
        # cleans them.
        # V26 — cache key bumped to v3 because the loader logic
        # changed: for RAW files at sizes ≥ 1600 we now use
        # ``load_image_for_display`` (quality-preserving full
        # postprocess when the embedded JPEG is too small) instead
        # of the fast ``load_image`` (which always took the
        # embedded thumbnail). Existing v2 caches for RAW would
        # serve a soft preview where the user expects a sharp one.
        cache_path = cache_dir / f"{src.name}.{size}.v3.jpg"
        if not cache_path.exists():
            # V26: large requests get the display loader, small
            # ones (thumbnail grid) keep the fast path.
            if size >= 1600:
                from pixcull.io.loader import load_image_for_display
                img = load_image_for_display(src, max_side=size)
            else:
                from pixcull.io.loader import load_image
                img = load_image(src, max_side=size)
            if img is None:
                self.send_error(500, "image decode failed")
                return
            quality = 78 if size <= _THUMB_SIZE else 88
            img.save(cache_path, "JPEG", quality=quality, optimize=True)
        data = cache_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Cache-Control", "public, max-age=31536000, immutable"
        )
        self.end_headers()
        self.wfile.write(data)

    def _handle_export(self, run_id: str) -> None:
        """Write XMP sidecars for every analyzed image in the run.

        Body: {target?: "tmp" | "alongside"}  (default "tmp")

        ``tmp``        — Write to ``<run_id>/output/xmp/`` and zip up.
                         Always available. User downloads + manually
                         drops next to originals on the LR/C1 side.
        ``alongside``  — Scan-mode only. Write each <name>.xmp directly
                         next to its original image. Lightroom picks it
                         up on next "Read Metadata from File" without
                         any manual file moving.

        We never touch the user's originals' bytes — only write a new
        sibling .xmp file. If a sidecar already exists with the same
        name, ``write_xmp`` overwrites it (documented behavior).
        """
        run = _get_run(run_id)
        if run is None:
            run = _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        # State check uses live dict; reloaded runs are assumed "done"
        # because the only way to get here without state=done is a
        # session restart, which by definition can only happen after
        # the previous analyzer thread exited.
        live = _get_run(run_id)
        if live and live.get("state") not in ("done", None):
            self.send_error(409, "run not finished yet")
            return

        # Read optional body for target mode
        clen = int(self.headers.get("Content-Length", "0") or "0")
        target_mode = "tmp"
        if clen > 0:
            try:
                params = json.loads(self.rfile.read(clen).decode("utf-8") or "{}")
                target_mode = params.get("target", "tmp")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                _dbg("export/parse_body", exc)
        # V29.1 — new "embedded" mode writes IPTC INTO the original
        # file via exiftool. Same scope rules as "alongside": only
        # works for scanned runs where we know the originals.
        if target_mode not in ("tmp", "alongside", "embedded"):
            self._reject_upload(
                400,
                "target must be 'tmp' / 'alongside' / 'embedded'",
            )
            return
        if target_mode in ("alongside", "embedded") and run.get("mode") != "scan":
            self._reject_upload(
                400,
                "'alongside' / 'embedded' 模式只在扫描本地文件夹时可用 —— "
                "上传模式没有原图位置可写。",
            )
            return
        if target_mode == "embedded":
            from pixcull.io.iptc_embed import is_available, install_hint
            if not is_available():
                self._reject_upload(
                    500,
                    "embedded 模式需要 exiftool。\n" + install_hint(),
                )
                return

        result = _build_results(run_id)
        if result is None:
            self.send_error(500, "no results to export")
            return
        rows, _ = result

        from pixcull.io.xmp import (
            write_xmp, decision_to_xmp, build_iptc_fields_from_row,
        )

        output_dir = Path(run["output_dir"])
        xmp_dir = output_dir / "xmp"
        xmp_dir.mkdir(parents=True, exist_ok=True)

        # V29 — surface face cluster labels + run vertical for IPTC
        # keyword generation. ``face_labels`` is {cluster_id: label};
        # ``vertical`` is the per-run scoring override (V17.0+).
        face_labels = _load_face_labels(run_id)
        run_vertical = run.get("vertical") or None
        # P2.5 — load any pre-computed auto-captions for this run.
        # When present, ``build_iptc_fields_from_row`` uses them as
        # IPTC:Caption-Abstract instead of the V20-advice bullets.
        from pixcull.scoring.caption_gen import load_captions
        auto_captions_map = load_captions(output_dir)

        written = 0
        skipped = 0
        per_decision: Counter[str] = Counter()
        for r in rows:
            fn = r["filename"]
            decision = r["decision"]
            stars, label = decision_to_xmp(decision)
            # V29 — IPTC fields (keywords / description / headline)
            # derived from the row + advice + face labels.
            iptc = build_iptc_fields_from_row(
                r,
                advice=r.get("advice") or None,
                face_labels=face_labels,
                vertical=run_vertical,
                run_id=run_id,
                auto_caption=auto_captions_map.get(fn),
            )
            if target_mode == "alongside":
                src = _resolve_image_source(run, fn)
                if src is None:
                    skipped += 1
                    continue
                # Sidecar lands at <orig_dir>/<stem>.xmp
                write_xmp(src, stars, label,
                          keywords=iptc["keywords"],
                          description=iptc["description"],
                          headline=iptc["headline"])
            elif target_mode == "embedded":
                # V29.1 — write IPTC into the original via exiftool.
                # No sidecar; metadata travels with the file.
                src = _resolve_image_source(run, fn)
                if src is None:
                    skipped += 1
                    continue
                from pixcull.io.iptc_embed import write_iptc_to_file
                ok = write_iptc_to_file(
                    src,
                    rating=stars, color_label=label,
                    keywords=iptc["keywords"],
                    description=iptc["description"],
                    headline=iptc["headline"],
                )
                if not ok:
                    skipped += 1
                    continue
            else:
                virtual = xmp_dir / Path(fn).name
                write_xmp(virtual, stars, label,
                          keywords=iptc["keywords"],
                          description=iptc["description"],
                          headline=iptc["headline"])
            written += 1
            per_decision[decision] += 1

        response = {
            "written": written,
            "skipped": skipped,
            "per_decision": dict(per_decision),
            "target": target_mode,
        }
        if target_mode == "tmp":
            response["zip_url"] = f"/xmp_zip/{run_id}"
            response["xmp_dir"] = str(xmp_dir)
        else:
            response["origin_folder"] = run.get("origin_folder") or run.get("source_dir")

        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_scores_csv(self, run_id: str) -> None:
        """V9.3: download scores.csv directly. Includes the BOM for
        Excel-friendly Chinese display + an attachment Content-Disposition
        so the browser saves it instead of rendering."""
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        csv_path = Path(run["output_dir"]) / "scores.csv"
        if not csv_path.exists():
            self.send_error(404, "scores.csv not generated yet")
            return
        # Prepend a UTF-8 BOM so Excel doesn't show 中文 as garbled.
        data = b"\xef\xbb\xbf" + csv_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="pixcull_{run_id}_scores.csv"',
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ============================================================
    # v0.8-P2-2 — structured CSV / JSON export
    #
    # Goes BEYOND the legacy scores.csv (which is just the analyser's
    # native dump) by joining in:
    #   * latest annotation per filename (decision / cull_reason /
    #     rubric_human_stars / overall_label)
    #   * bucket assignments (which delivery buckets a filename
    #     belongs to — but those live in localStorage, so we surface
    #     server-side annotations only)
    #   * style distance map (v0.7-P2-1 + v0.8-P1-1) — v1, v2, blend
    #
    # The "Lr Catalog import template" (.lrcat-ready SQLite) is a
    # bigger lift (LR's catalog schema is undocumented, reverse-
    # engineered binary) → deferred to v0.9 / v1.0.  V1 here gives
    # pros a clean JSON pipe into their own Lr-import scripts.
    # ============================================================
    def _collect_structured_rows(self, run: dict) -> list[dict]:
        """Merge scores.csv + annotations.jsonl + style_distances.json
        into one list of per-filename dicts.

        Returns rows in scores.csv order so existing pipelines that
        rely on row ordering keep working.
        """
        import csv as _csv

        output_dir = Path(run["output_dir"])
        scores_path = output_dir / "scores.csv"
        if not scores_path.exists():
            return []
        rows: list[dict] = []
        try:
            with open(scores_path, "r", encoding="utf-8-sig", newline="") as fh:
                for r in _csv.DictReader(fh):
                    rows.append(dict(r))
        except OSError as exc:
            _dbg("export/structured/scores_read", exc, str(scores_path))
            return []
        # Latest annotation per filename (annotations.jsonl is
        # append-only, last line wins).
        ann_by_fn: dict = {}
        ann_path = output_dir / "annotations.jsonl"
        if ann_path.exists():
            try:
                with open(ann_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(row, dict):
                            continue
                        fn = row.get("filename")
                        if isinstance(fn, str) and fn:
                            ann_by_fn[fn] = row
            except OSError as exc:
                _dbg("export/structured/ann_read", exc, str(ann_path))
        # Style distances (rich shape {v1, v2?, blend})
        style_path = output_dir / "style_distances.json"
        style_map: dict = {}
        if style_path.exists():
            try:
                style_map = json.loads(style_path.read_text("utf-8"))
                if not isinstance(style_map, dict):
                    style_map = {}
            except (OSError, ValueError):
                style_map = {}
        # Merge
        for r in rows:
            fn = r.get("filename") or ""
            ann = ann_by_fn.get(fn) or {}
            # Annotation overrides win for decision / cull_reason
            if ann.get("overall_label"):
                r["decision_human"] = ann.get("overall_label")
            if ann.get("cull_reason"):
                r["cull_reason_human"] = ann.get("cull_reason")
            r["annotation_timestamp"] = ann.get("timestamp")
            r["annotation_source"] = ann.get("source")
            # Style distances
            sd = style_map.get(fn)
            if isinstance(sd, (int, float)):
                r["style_distance"] = sd
                r["style_distance_v1"] = sd
            elif isinstance(sd, dict):
                if "v1" in sd:    r["style_distance_v1"] = sd["v1"]
                if "v2" in sd:    r["style_distance_v2"] = sd["v2"]
                if "blend" in sd: r["style_distance"] = sd["blend"]
        return rows

    def _serve_export_structured_json(self, run_id: str) -> None:
        """GET /export/structured/<run>.json → {schema, run_id, rows: [...]}

        Schema is pixcull.export.structured/v1 — every row carries
        every scores.csv column plus annotation + style-distance
        overlays.  Useful for users writing their own LR-import
        scripts or feeding the data into a separate analytics
        pipeline.
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        rows = self._collect_structured_rows(run)
        payload = {
            "schema":      "pixcull.export.structured/v1",
            "run_id":      run_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "n_rows":      len(rows),
            "rows":        rows,
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="pixcull_{run_id}_structured.json"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_export_structured_csv(self, run_id: str) -> None:
        """GET /export/structured/<run>.csv → same data as JSON variant
        but in a flat CSV (one row per filename, union of all keys
        as columns; missing → empty cell).
        """
        import csv as _csv
        import io

        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        rows = self._collect_structured_rows(run)
        if not rows:
            self.send_error(404, "no rows to export")
            return
        # Union of columns, preserving the order: scores.csv-natural
        # columns first (taken from the first row), then any
        # additional keys appended in encounter order.
        seen: dict = {}
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen[k] = True
        fieldnames = list(seen.keys())
        buf = io.StringIO()
        # BOM for Excel
        buf.write("﻿")
        writer = _csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
        body = buf.getvalue().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="pixcull_{run_id}_structured.csv"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_gallery_zip(self, rel: str) -> None:
        """V23.x — standalone HTML gallery export for a run.

        URL: /gallery_zip/<run_id>?include=keep[,maybe[,cull]]

        Default is keep-only (the typical client deliverable). Pass
        ``include=keep,maybe`` to also surface ambiguous shots, or
        ``include=keep,maybe,cull`` to dump everything.

        Streams the assembled zip as ``Content-Disposition: attachment``
        so the browser saves it instead of opening it.
        """
        # Split run_id from query string
        if "?" in rel:
            run_id, qs = rel.split("?", 1)
        else:
            run_id, qs = rel, ""
        from urllib.parse import parse_qs
        qparams = parse_qs(qs)
        include_raw = qparams.get("include", ["keep"])[0]
        include = tuple(
            x.strip() for x in include_raw.split(",")
            if x.strip() in ("keep", "maybe", "cull")
        ) or ("keep",)

        result = _build_results(run_id)
        if result is None:
            run = _get_run(run_id) or _reload_run_from_disk(run_id)
            if run is None:
                self.send_error(404, "no such run")
                return
            self.send_error(425, "results not ready")
            return
        rows, _summary = result

        from pixcull.report.gallery import build_gallery_zip
        try:
            data = build_gallery_zip(
                run_id, rows, include_decisions=include,
            )
        except Exception as exc:  # noqa: BLE001
            self.send_error(500, f"gallery build failed: {exc}")
            return

        title_decisions = "_".join(include)
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="pixcull_{run_id}_gallery_{title_decisions}.zip"',
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_xmp_zip(self, run_id: str) -> None:
        """Stream all sidecars + a README into a single zip download."""
        import zipfile

        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        xmp_dir = Path(run["output_dir"]) / "xmp"
        if not xmp_dir.exists():
            self.send_error(404, "no xmp exported yet — POST /export first")
            return

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for sidecar in sorted(xmp_dir.glob("*.xmp")):
                zf.write(sidecar, arcname=sidecar.name)
            zf.writestr(
                "README.txt",
                _XMP_README.format(
                    run_id=run_id,
                    n=len(list(xmp_dir.glob("*.xmp"))),
                ),
            )
        data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="pixcull_{run_id}_xmp.zip"',
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # --- rubric / annotation (V2.0) ---------------------------------------
    def _serve_rubric_meta(self) -> None:
        """Static rubric definition: axis names + descriptors + checklist.

        Sent once on results-page load so the client can render the
        annotation form locally without re-requesting on every image.
        """
        from pixcull.scoring.rubric import RUBRIC_AXES
        meta = [
            {
                "name": a.name,
                "label_zh": a.label_zh,
                "label_en": a.label_en,
                "description_zh": a.description_zh,
                "rubric_descriptors": list(a.rubric_descriptors),
                "checklist": [{"key": k, "weight": w} for k, w in a.checklist],
            }
            for a in RUBRIC_AXES
        ]
        self._send_json(200, json.dumps(
            {"axes": meta}, ensure_ascii=False
        ).encode("utf-8"))

    def _serve_rubric(self, rel: str) -> None:
        """GET /rubric/<run_id> → all auto-decomposed rubric scores
        for this run. Read straight off rubric.jsonl on disk so the
        client can sort/filter without holding everything in memory.
        """
        run_id = unquote(rel)
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        rubric_path = Path(run["output_dir"]) / "rubric.jsonl"
        if not rubric_path.exists():
            self.send_error(404, "rubric.jsonl missing — pre-V2 run?")
            return
        # V14.1: cached read. Both files keyed by (path, mtime) so
        # they're invalidated as soon as a new annotation lands.
        rows = list(_read_jsonl_cached(rubric_path))
        ann_path = Path(run["output_dir"]) / "annotations.jsonl"
        human_by_fn = _read_human_by_fn_cached(ann_path)
        for r in rows:
            fn = r.get("filename")
            if fn in human_by_fn:
                r["human"] = human_by_fn[fn]
        self._send_json(200, _safe_dumps(
            {"run_id": run_id, "rows": rows}
        ).encode("utf-8"))

    def _serve_annotation(self, rel: str) -> None:
        """GET /annotation/<run_id>/<filename> → the latest human
        rubric for that one image, or the auto-decomposed one if no
        human label exists yet. Used by the annotation modal to
        pre-fill the form.
        """
        rel = unquote(rel)
        if "/" not in rel:
            self.send_error(400, "expected run_id/filename")
            return
        run_id, fn = rel.split("/", 1)
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        # V14.1: cached. Walk in reverse for latest-wins on the human
        # side; auto rubric is keyed by filename so we just dict-lookup.
        ann_path = Path(run["output_dir"]) / "annotations.jsonl"
        latest_human = _read_human_by_fn_cached(ann_path).get(fn)
        if latest_human is not None:
            self._send_json(200, _safe_dumps(
                {"source": "human", "data": latest_human},
            ).encode("utf-8"))
            return
        # Fall back to auto from rubric.jsonl
        rubric_path = Path(run["output_dir"]) / "rubric.jsonl"
        if rubric_path.exists():
            for rec in _read_jsonl_cached(rubric_path):
                if rec.get("filename") == fn:
                    self._send_json(200, _safe_dumps(
                        {"source": "auto", "data": rec},
                    ).encode("utf-8"))
                    return
        self.send_error(404, f"no rubric for {fn}")

    def _handle_save_annotation(self, rel: str) -> None:
        """POST /annotation/<run_id>/<filename> with body
        {axes: {name: {stars, rationale}}, overall_label, overall_rationale}.

        Append-only: every save creates a new line. Latest wins on read.
        This makes the annotation file replayable, audit-friendly, and
        merge-safe across multiple annotators on a LAN deploy.
        """
        rel = unquote(rel)
        if "/" not in rel:
            self._reject_upload(400, "expected run_id/filename")
            return
        run_id, fn = rel.split("/", 1)
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self._reject_upload(404, "no such run")
            return
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 65536:
            self._reject_upload(400, "expected JSON body")
            return
        try:
            params = json.loads(self.rfile.read(clen).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}")
            return

        from pixcull.scoring.rubric import RUBRIC_AXES, get_axis
        valid_axes = {a.name for a in RUBRIC_AXES}

        axes_in = params.get("axes") or {}
        clean_axes: dict[str, dict] = {}
        for name, axis_data in axes_in.items():
            if name not in valid_axes:
                continue  # silently drop typos
            try:
                _ = get_axis(name)
            except KeyError:
                continue
            stars = axis_data.get("stars")
            if stars is not None:
                try:
                    stars_f = float(stars)
                    if not 1.0 <= stars_f <= 5.0:
                        stars_f = max(1.0, min(5.0, stars_f))
                except (TypeError, ValueError):
                    stars_f = None
            else:
                stars_f = None
            clean_axes[name] = {
                "stars": stars_f,
                "checklist_pass": None,  # human override; recompute on display
                "rationale": str(axis_data.get("rationale", ""))[:1000],
                "source": "human",
            }

        # P-UX-4 — optional cull_reason. Only meaningful when
        # overall_label == "cull"; silently dropped otherwise so a
        # later relabel to keep doesn't carry a stale reason. Tokens
        # outside the taxonomy are dropped (treated same as "no
        # reason given") rather than rejected — keeps the wire format
        # forgiving for old clients sending free-form text.
        overall_label_clean = str(params.get("overall_label", ""))[:32]
        cull_reason_in = str(params.get("cull_reason", "") or "").strip().lower()
        cull_reason_clean = (
            cull_reason_in if (
                overall_label_clean == "cull"
                and cull_reason_in in _CULL_REASONS
            ) else ""
        )

        record = {
            "filename": fn,
            "axes": clean_axes,
            "overall_label": overall_label_clean,
            "overall_rationale": str(params.get("overall_rationale", ""))[:1000],
            "cull_reason": cull_reason_clean,
            "source": "human",
            "timestamp": time.time(),
        }
        ann_path = Path(run["output_dir"]) / "annotations.jsonl"
        ann_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ann_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # V11.2 — auto-retrain trigger. Each annotation increments a
        # global counter; once the threshold is crossed AND no retrain
        # is currently running, spawn one. The user gets a personalized
        # picking model that improves silently as they label.
        global _annotations_since_retrain
        with _RUNS_LOCK:
            _annotations_since_retrain += 1
            should_train = (
                _annotations_since_retrain >= _AUTO_RETRAIN_THRESHOLD
                and _RETRAIN_STATE.get("state") != "running"
            )
            if should_train:
                _annotations_since_retrain = 0

        if should_train:
            print(f"[auto-retrain] threshold reached, spawning retrain",
                  file=sys.stderr)
            threading.Thread(
                target=_retrain_in_background,
                args=(True, True),
                daemon=True,
            ).start()

        self._send_json(200, json.dumps(
            {
                "ok": True, "filename": fn,
                "auto_retrain_spawned": should_train,
                "annotations_since_retrain": _annotations_since_retrain,
            },
            ensure_ascii=False,
        ).encode("utf-8"))

    def _serve_next_to_label(self, rel: str) -> None:
        """Active-learning queue: pick the next most-informative image
        for this run that hasn't been human-labeled yet.

        Priority (decreasing):
          1. rule decision and rescorer disagree (the article's
             "where is the model wrong?" — highest signal)
          2. rescorer prob_keep in [0.4, 0.7] (uncertain region)
          3. burst clusters where decisions split (peer-comparable)
          4. rubric axes near the median (a 3★ that could go either
             way is a strong train-time signal)
          5. fallback: lowest score_final among unlabeled

        P2.4 — also accepts ``?n=<N>`` to return the TOP-N queue at
        once instead of just the single next item. When ``n > 1``
        the response shape switches to a ``queue`` array of
        ``{filename, why, priority_rank}`` entries.
        """
        # P2.4 — split rel into run_id + query string. Most callers
        # pass just the run_id; the new "?n=N" form supports batch.
        path_q = rel.split("?", 1)
        run_id = unquote(path_q[0])
        from urllib.parse import parse_qs
        qparams = parse_qs(path_q[1]) if len(path_q) > 1 else {}
        try:
            n_requested = int(qparams.get("n", ["1"])[0])
        except (ValueError, TypeError):
            n_requested = 1
        n_requested = max(1, min(200, n_requested))   # clamp to sane range

        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return

        result = _build_results(run_id)
        if result is None:
            self.send_error(404, "no results yet")
            return
        rows, _ = result

        # Filter out images already human-labeled (V14.1: cached read)
        ann_path = Path(run["output_dir"]) / "annotations.jsonl"
        labeled = set(_read_human_by_fn_cached(ann_path).keys())
        candidates = [r for r in rows if r["filename"] not in labeled]
        if not candidates:
            self._send_json(200, json.dumps(
                {"done": True, "n_labeled": len(labeled),
                 "message": "已标完本批所有图片"},
                ensure_ascii=False,
            ).encode("utf-8"))
            return

        def priority(r: dict) -> tuple:
            # Lower tuple = higher priority. -bool flips True→0 (top).
            rescorer_disagrees = (
                r.get("rescorer_pred") is not None
                and r["rescorer_pred"] != r["decision"]
            )
            prob = r.get("rescorer_prob_keep")
            uncertainty = (
                abs(0.55 - prob)
                if prob is not None else 1.0
            )
            score = r.get("score_final") or 0.5
            return (
                -int(rescorer_disagrees),  # disagreement first
                uncertainty,                # then most uncertain
                abs(score - 0.5),           # then score near 0.5
            )

        candidates.sort(key=priority)

        # P2.4 — helper to assemble a per-candidate explanation string.
        # Returns a list of short reason fragments suitable for the UI
        # tooltip. Identical logic to the legacy single-item path, just
        # factored out so the batch path can reuse it.
        def _reasons_for(c: dict) -> list[str]:
            reasons: list[str] = []
            if (c.get("rescorer_pred") is not None
                    and c["rescorer_pred"] != c["decision"]):
                prob = c.get("rescorer_prob_keep")
                prob_str = f" (P={prob:.2f})" if prob is not None else ""
                reasons.append(
                    f"规则=={c['decision']} 但 rescorer=={c['rescorer_pred']}{prob_str}"
                )
            if (c.get("rescorer_prob_keep") is not None
                    and 0.40 <= c["rescorer_prob_keep"] <= 0.70):
                reasons.append(
                    f"rescorer 不确定区 (P={c['rescorer_prob_keep']:.2f})"
                )
            score = c.get("score_final")
            if score is not None and 0.35 <= score <= 0.65:
                reasons.append(f"score_final={score:.2f} 临界")
            if not reasons:
                reasons.append("queue 中未标注的下一张")
            return reasons

        # P2.4 — batch mode returns the top-N as a queue array. Used
        # by the "🎯 主动学习" filter pill in the results page. Each
        # entry carries its priority_rank (1-based) for the UI badge.
        if n_requested > 1:
            queue = []
            for i, c in enumerate(candidates[:n_requested]):
                queue.append({
                    "filename":       c["filename"],
                    "priority_rank":  i + 1,
                    "why":            "; ".join(_reasons_for(c)),
                    "decision":       c.get("decision"),
                    "score_final":    c.get("score_final"),
                    "rescorer_pred":  c.get("rescorer_pred"),
                })
            self._send_json(200, json.dumps({
                "schema":      "pixcull.next_to_label.queue.v1",
                "run_id":      run_id,
                "n_total":     len(rows),
                "n_labeled":   len(labeled),
                "n_remaining": len(candidates),
                "n_returned":  len(queue),
                "queue":       queue,
            }, ensure_ascii=False).encode("utf-8"))
            return

        # Legacy single-item path
        chosen = candidates[0]
        self._send_json(200, json.dumps({
            "filename": chosen["filename"],
            "n_total": len(rows),
            "n_labeled": len(labeled),
            "n_remaining": len(candidates),
            "why": "; ".join(_reasons_for(chosen)),
            "row": chosen,
        }, ensure_ascii=False).encode("utf-8"))

    # --- V2.1 retrain ------------------------------------------------------
    def _handle_retrain(self) -> None:
        """Trigger a per-axis rescorer retrain in a background thread.

        Does the same job as ``scripts/build_axis_training_set.py +
        scripts/train_axis_rescorers.py`` but as a one-click admin op.
        Read-only by design — the existing models stay loaded by the
        orchestrator until the next ``run_pipeline`` call rebinds them.

        Body (all optional): {include_auto: bool, also_goldenset: bool}
        """
        clen = int(self.headers.get("Content-Length", "0") or "0")
        params: dict = {}
        if clen > 0:
            try:
                params = json.loads(self.rfile.read(clen).decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                _dbg("retrain/parse_body", exc)

        global _RETRAIN_STATE
        with _RUNS_LOCK:
            if _RETRAIN_STATE.get("state") == "running":
                self._reject_upload(409, "已有训练任务在跑,等完成再来")
                return
            _RETRAIN_STATE = {
                "state": "queued",
                "started_at": time.time(),
                "message": "排队中",
            }

        threading.Thread(
            target=_retrain_in_background,
            args=(bool(params.get("include_auto", True)),
                  bool(params.get("also_goldenset", True))),
            daemon=True,
        ).start()
        self._send_json(200, json.dumps(
            {"ok": True, "message": "训练已启动,GET /retrain_status 看进度"},
            ensure_ascii=False,
        ).encode("utf-8"))

    def _serve_license_status(self) -> None:
        """V12.0: GET license + quota status JSON.

        V15.1: when the dev-mode kill switch is on, advertise unlimited
        + zero-used so the frontend badge stops rendering "FREE 0/100"
        for the duration of testing. ``dev_mode: true`` lets a future
        UI render a distinct chip ("DEV") if needed.
        """
        from pixcull.license import (
            load_license, usage_this_month, status_line,
            _quota_disabled,
        )
        lic = load_license()
        dev = _quota_disabled()
        body = json.dumps({
            "tier": "dev" if dev else lic.tier,
            "is_pro": True if dev else lic.is_pro,
            "is_unlimited": True if dev else lic.is_unlimited,
            "monthly_quota": -1 if dev else lic.monthly_quota,
            "used_this_month": 0 if dev else usage_this_month(),
            "expires_at": None if dev else lic.expires_at,
            "days_remaining": None if dev else lic.days_remaining,
            "email": lic.email,
            "status_line": status_line(),
            "dev_mode": dev,
        }, ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    def _handle_license_install(self) -> None:
        """V12.0: POST {token: '...'} to install a license token."""
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 65536:
            self._reject_upload(400, "expected JSON body with token")
            return
        try:
            params = json.loads(self.rfile.read(clen).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}")
            return
        token = (params.get("token") or "").strip()
        if not token:
            self._reject_upload(400, "缺少 token 字段")
            return
        from pixcull.license import install_license
        lic = install_license(token)
        if lic is None:
            self._reject_upload(400, "license token 验证失败 — 已过期或被篡改")
            return
        body = json.dumps({
            "ok": True,
            "tier": lic.tier,
            "expires_at": lic.expires_at,
            "monthly_quota": lic.monthly_quota,
            "message": f"已激活 {lic.tier.upper()} · 重启服务后立即生效",
        }, ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    def _handle_license_refresh(self) -> None:
        """V12.1: trigger a cloud-side license refresh.

        Useful after the user pays for renewal — they hit this and
        the server pushes the rotated token back. Also called daily
        in the background by maybe_cloud_refresh's debouncer.
        """
        from pixcull.license import maybe_cloud_refresh
        result = maybe_cloud_refresh(force=True)
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    def _handle_sync_upload(self) -> None:
        """V12.1: push all annotations from all local runs to cloud.

        Pro+ only. Walks every run's annotations.jsonl, joins them
        into a single payload, posts to the cloud sync endpoint.
        """
        from pixcull.license import cloud_sync_upload
        records: list[dict] = []
        for run_dir in sorted(_DEMO_ROOT.iterdir()):
            if not run_dir.is_dir():
                continue
            ann = run_dir / "output" / "annotations.jsonl"
            if not ann.exists():
                continue
            with open(ann, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rec["__run_id"] = run_dir.name
                    records.append(rec)
        result = cloud_sync_upload(records)
        result["uploaded"] = len(records)
        self._send_json(200 if result.get("ok") else 402,
                         json.dumps(result, ensure_ascii=False).encode("utf-8"))

    def _handle_sync_download(self) -> None:
        """V12.1: pull annotations from cloud + merge into local runs.

        Annotations from cloud arrive with __run_id; for each, append
        to the matching local run's annotations.jsonl (or skip if the
        run isn't on this machine — the user can re-scan to materialize).
        """
        from pixcull.license import cloud_sync_download
        result = cloud_sync_download()
        if not result.get("ok"):
            self._send_json(402,
                json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return

        merged = 0
        skipped_unknown_run = 0
        for rec in result.get("annotations", []):
            run_id = rec.get("__run_id", "")
            if not run_id:
                continue
            run_dir = _DEMO_ROOT / run_id
            if not run_dir.exists():
                skipped_unknown_run += 1
                continue
            ann_path = run_dir / "output" / "annotations.jsonl"
            ann_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ann_path, "a", encoding="utf-8") as f:
                # Strip the sync-only field before writing
                clean = {k: v for k, v in rec.items() if k != "__run_id"}
                f.write(json.dumps(clean, ensure_ascii=False) + "\n")
            merged += 1
        result["merged"] = merged
        result["skipped_unknown_run"] = skipped_unknown_run
        self._send_json(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))

    def _serve_retrain_status(self) -> None:
        """Return the latest retrain run's state + per-axis CV metrics."""
        with _RUNS_LOCK:
            state = dict(_RETRAIN_STATE)
            # V11.2 — surface auto-retrain progress for admin UI
            state["auto_retrain"] = {
                "threshold": _AUTO_RETRAIN_THRESHOLD,
                "annotations_since_last": _annotations_since_retrain,
                "remaining_until_trigger":
                    max(0, _AUTO_RETRAIN_THRESHOLD - _annotations_since_retrain),
            }
        # Augment with on-disk meta if available (last-completed run)
        meta_path = Path("models/rescorer_axis_meta.json")
        if meta_path.exists():
            try:
                state["last_meta"] = json.loads(meta_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                _dbg("retrain_status/meta", exc, str(meta_path))
        self._send_json(200, json.dumps(state, ensure_ascii=False).encode("utf-8"))

    # --- V14.6 first-run page + status ------------------------------------
    def _serve_first_run_page(self) -> None:
        body = _FIRST_RUN_HTML.encode("utf-8")
        self._send_html(200, body)

    def _serve_first_run_status(self) -> None:
        body = _safe_dumps(first_run_snapshot()).encode("utf-8")
        self._send_json(200, body)

    # --- V17.0 verticals --------------------------------------------------
    def _serve_verticals_page(self) -> None:
        body = _VERTICALS_HTML.encode("utf-8")
        self._send_html(200, body)

    def _serve_verticals_json(self) -> None:
        from pixcull import verticals as vmod
        body = _safe_dumps(vmod.registry_with_progress()).encode("utf-8")
        self._send_json(200, body)

    def _serve_vertical_list(self, rel: str) -> None:
        """V17.1: GET /verticals/list/<key>/<bucket> → sample listing.

        Drives the /verticals drawer's sample grid. Returns the same
        shape verticals.list_samples produces ({filename, size, mtime})
        plus the bucket counts so the UI can update the tab labels
        ("好片 (12)" / "待剔除 (5)") without a second roundtrip.
        """
        from pixcull import verticals as vmod
        rel = unquote(rel)
        parts = rel.split("/", 1)
        if len(parts) != 2:
            self.send_error(404, "expected key/bucket")
            return
        key, bucket = parts
        if vmod.get_vertical(key) is None:
            self.send_error(404, f"unknown vertical: {key}")
            return
        if bucket not in vmod.ALLOWED_BUCKETS:
            self.send_error(400, "bucket must be 'good' or 'bad'")
            return
        try:
            samples = vmod.list_samples(key, bucket)
        except ValueError as exc:
            # Defensive — get_vertical already vetted the key, but if a
            # future refactor diverges the two paths this catches it.
            self.send_error(404, str(exc))
            return
        body = _safe_dumps({
            "key":     key,
            "bucket":  bucket,
            "samples": samples,
            "counts":  vmod.count_samples(key),
        }).encode("utf-8")
        self._send_json(200, body)

    def _serve_vertical_sample(self, rel: str) -> None:
        """GET /verticals/sample/<key>/<bucket>/<filename> → image bytes.

        Path-shaped (not query string) so we can ``<img src="...">``
        directly in the verticals page sample grid.
        """
        from pixcull import verticals as vmod
        rel = unquote(rel)
        parts = rel.split("/", 2)
        if len(parts) != 3:
            self.send_error(404, "expected key/bucket/filename")
            return
        key, bucket, fn = parts
        p = vmod.sample_path(key, bucket, fn)
        if p is None:
            self.send_error(404, "no such sample")
            return
        try:
            data = p.read_bytes()
        except OSError as exc:
            _dbg("vertical_sample/read", exc, str(p))
            self.send_error(500, "read failed")
            return
        ext = p.suffix.lower()
        ctype = ("image/jpeg" if ext in (".jpg", ".jpeg") else
                 "image/png" if ext == ".png" else
                 "image/heic" if ext in (".heic", ".heif") else
                 "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _handle_vertical_upload(self, key: str) -> None:
        """POST /verticals/upload/<key>?bucket=good|bad

        Multipart upload — same machinery as /analyze, but persists into
        the vertical sample bank instead of /tmp.

        V17.5 fix — ``key`` is delivered already path-stripped (do_POST
        called urlparse(self.path).path). To read ``?bucket=...`` we go
        back to ``self.path`` itself, not the ``key`` slice.
        """
        from pixcull import verticals as vmod
        from urllib.parse import parse_qs, urlsplit
        key = unquote(key.strip("/"))
        full = urlsplit(self.path)
        qs = parse_qs(full.query) if full.query else {}
        bucket = (qs.get("bucket", ["good"])[0] or "good").lower()
        if bucket not in vmod.ALLOWED_BUCKETS:
            self._reject_upload(400, "bucket must be 'good' or 'bad'")
            return
        if vmod.get_vertical(key) is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self._reject_upload(400, "expected multipart/form-data")
            return
        try:
            form = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype},
                keep_blank_values=True,
            )
        except Exception as exc:
            self._reject_upload(400, f"multipart parse failed: {exc}")
            return
        saved: list[dict] = []
        for field_name in form.keys():
            field = form[field_name]
            for item in (field if isinstance(field, list) else [field]):
                if not getattr(item, "filename", None):
                    continue
                content = item.file.read()
                if not content:
                    continue
                # Cap each upload at 32 MB so a runaway can't fill the
                # vertical bank.
                if len(content) > 32 * 1024 * 1024:
                    continue
                saved.append(vmod.save_sample(
                    key, bucket, item.filename, content,
                ))
        body = _safe_dumps({
            "ok": True, "key": key, "bucket": bucket,
            "saved": saved,
            "counts": vmod.count_samples(key),
        }).encode("utf-8")
        self._send_json(200, body)

    def _handle_vertical_tune(self, key: str) -> None:
        """V17.4 — POST /verticals/tune/<key>

        Run policy_tuner.tune_vertical(key) → return JSON result.
        Does NOT persist the override (user reviews before applying).

        Body is empty / ignored.
        """
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        if vmod.get_vertical(key) is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        try:
            from pixcull import policy_tuner as pt
            from dataclasses import asdict
            result = pt.tune_vertical(key)
            payload = asdict(result)
            # V17.10 — keep the FULL grid (~5KB for 121 cells) so the
            # tune modal can render the F1 heatmap. Also expose
            # ``grid_top12`` sorted-by-F1 for tabular display.
            full_grid = payload.get("grid", [])
            payload["grid_top12"] = sorted(full_grid,
                                              key=lambda x: -x["f1"])[:12]
            # ``grid`` stays as-is (full 11×11)
        except ValueError as exc:
            # Predictable user errors (no samples / unknown key) → 400
            self._reject_upload(400, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            _capture_exception("verticals.tune", exc, {"key": key})  # V17.12
            self._reject_upload(500, f"调参失败: {type(exc).__name__}: {exc}")
            return
        self._send_json(200, _safe_dumps(payload).encode("utf-8"))

    def _handle_vertical_apply_override(self, key: str) -> None:
        """V17.4 — POST /verticals/apply_override/<key>

        Body: ``{keep_min_delta, cull_max_delta, baseline, tuned, ...}``
        — typically the result of a prior /verticals/tune call. Saves
        the override so subsequent runs of decide() pick it up.
        """
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        if vmod.get_vertical(key) is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 1024 * 1024:
            self._reject_upload(400, "expected JSON body with tune result")
            return
        try:
            params = json.loads(self.rfile.read(clen).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}")
            return
        try:
            from pixcull import policy_tuner as pt
            # Reconstruct just enough of TuneResult for save_override.
            res = pt.TuneResult(
                vertical=key,
                n_good=int(params.get("n_good", 0)),
                n_bad=int(params.get("n_bad", 0)),
                base_keep_min=float(params.get("base_keep_min", 0.65)),
                base_cull_max=float(params.get("base_cull_max", 0.40)),
                baseline_delta_keep=float(params.get("baseline_delta_keep", 0.0)),
                baseline_delta_cull=float(params.get("baseline_delta_cull", 0.0)),
                baseline=params.get("baseline") or {},
                tuned_delta_keep=float(params["tuned_delta_keep"]),
                tuned_delta_cull=float(params["tuned_delta_cull"]),
                tuned=params.get("tuned") or {},
            )
            pt.save_override(key, res)
        except (KeyError, TypeError, ValueError) as exc:
            self._reject_upload(400, f"参数错误: {exc}")
            return
        body = _safe_dumps({
            "ok": True,
            "key": key,
            "override_path": str(__import__("pixcull.policy_tuner",
                                              fromlist=["override_path"])
                                  .override_path(key)),
        }).encode("utf-8")
        self._send_json(200, body)

    def _handle_vertical_revert_override(self, key: str) -> None:
        """V17.4 — POST /verticals/revert_override/<key>

        Deletes the override file so the registry default takes over.
        """
        from pixcull import verticals as vmod
        from pixcull import policy_tuner as pt
        key = unquote(key.strip("/"))
        if vmod.get_vertical(key) is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        ok = pt.delete_override(key)
        body = _safe_dumps({"ok": ok, "key": key,
                              "had_override": ok}).encode("utf-8")
        self._send_json(200, body)

    # ---------- V17.5 phrase generator ----------
    def _handle_vertical_llm_phrases(self, key: str) -> None:
        """POST /verticals/llm_phrases/<key>

        Profile good samples → DeepSeek V4-Flash → save phrase override.
        Returns the result so the UI can show what was generated for
        review. Failure modes:
          400 — no DeepSeek key, no samples, malformed LLM JSON
          404 — unknown vertical
          500 — unexpected DeepSeek/network error
        """
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        if vmod.get_vertical(key) is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        try:
            from pixcull import phrase_generator as pg
            from dataclasses import asdict
            result = pg.generate_phrases(key)
            pg.save_phrase_override(key, result)
            payload = asdict(result)
            payload["ok"] = True
        except ValueError as exc:
            self._reject_upload(400, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            _capture_exception("verticals.llm_phrases", exc, {"key": key})  # V17.12
            self._reject_upload(500,
                f"DeepSeek 调用失败: {type(exc).__name__}: {exc}")
            return
        self._send_json(200, _safe_dumps(payload).encode("utf-8"))

    def _handle_vertical_revert_phrases(self, key: str) -> None:
        """POST /verticals/revert_phrases/<key> — delete phrase override."""
        from pixcull import verticals as vmod
        from pixcull import phrase_generator as pg
        key = unquote(key.strip("/"))
        if vmod.get_vertical(key) is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        ok = pg.delete_phrase_override(key)
        body = _safe_dumps({"ok": ok, "key": key,
                              "had_override": ok}).encode("utf-8")
        self._send_json(200, body)

    # ---------- V17.6 per-vertical eval report ----------
    def _handle_vertical_eval(self, key: str) -> None:
        """POST /verticals/eval/<key>

        Runs the rule pipeline + (effective) policy on every sample
        of the vertical, returns:
          * confusion matrix (good→keep/maybe/cull, bad→...)
          * F1 / precision / recall / accuracy
          * per-axis metric distributions
          * lists of misclassified filenames (false-keep + false-cull)
            so the user can click into them to investigate

        Body is empty / ignored.
        """
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        v = vmod.get_vertical(key)
        if v is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        counts = vmod.count_samples(key)
        if counts["total"] < 1:
            self._reject_upload(400,
                f"vertical '{key}' has no samples — upload some via /verticals first")
            return
        try:
            from pixcull import policy_tuner as pt
            from pixcull.scoring.decision import Decision
            from pixcull.config import PixCullConfig

            samples = pt.analyze_samples(key)
            if not samples:
                self._reject_upload(500,
                    "0 samples could be analyzed — check launcher log for errors")
                return

            # Use the EFFECTIVE policy (override-merged) so the report
            # reflects what `decide()` would actually do at scoring time.
            config = PixCullConfig.load()
            base_keep, base_cull = pt._baseline_thresholds(config)
            eff = vmod.get_effective_policy(key)
            kmin = max(0.0, min(1.0, base_keep + (eff.keep_min_delta if eff else 0)))
            cmax = max(0.0, min(1.0, base_cull + (eff.cull_max_delta if eff else 0)))
            tol = frozenset(eff.tolerated_flags) if eff else frozenset()

            preds = [pt._apply_thresholds(
                s.final_score, s.flags, s.scene,
                keep_min=kmin, cull_max=cmax,
                tolerated_flags=tol,
            ) for s in samples]

            # Confusion: (truth_bucket → {keep, maybe, cull})
            confusion = {
                "good": {"keep": 0, "maybe": 0, "cull": 0},
                "bad":  {"keep": 0, "maybe": 0, "cull": 0},
            }
            misclassified_keep: list[dict] = []   # bad shots that survived
            misclassified_cull: list[dict] = []   # good shots wrongly culled
            for s, p in zip(samples, preds):
                pname = "keep" if p is Decision.KEEP else \
                        "maybe" if p is Decision.MAYBE else "cull"
                confusion[s.bucket][pname] += 1
                # Misclassifications: bad-shot kept = false-positive;
                # good-shot culled = false-negative.
                if s.bucket == "bad" and p is not Decision.CULL:
                    misclassified_keep.append({
                        "filename": s.filename,
                        "score":    round(s.final_score, 3),
                        "pred":     pname,
                        "scene":    s.scene,
                        "flags":    s.flags,
                    })
                elif s.bucket == "good" and p is Decision.CULL:
                    misclassified_cull.append({
                        "filename": s.filename,
                        "score":    round(s.final_score, 3),
                        "pred":     pname,
                        "scene":    s.scene,
                        "flags":    s.flags,
                    })

            metrics = pt.binary_metrics(preds, [s.bucket for s in samples])

            # Per-axis metric averages — useful diagnostic ("user's good
            # shots avg subject_fraction=0.18, low compared to default
            # 0.30 threshold").
            metric_names = ("subject_fraction", "canon_lead_room",
                              "canon_thirds_concentration",
                              "canon_figure_ground", "score_moment",
                              "laion_aes", "laplacian_subject")
            axis_distrib: dict[str, dict] = {}
            # We only have final_score on SamplePoint; deeper metrics
            # require re-fetching. For V17.6 we keep this lean — just
            # the score distribution by bucket.
            from statistics import mean, median
            for bucket in ("good", "bad"):
                vs = [s.final_score for s in samples if s.bucket == bucket]
                axis_distrib[bucket] = {
                    "n":      len(vs),
                    "score_mean":   round(mean(vs), 3) if vs else 0.0,
                    "score_median": round(median(vs), 3) if vs else 0.0,
                    "score_min":    round(min(vs), 3) if vs else 0.0,
                    "score_max":    round(max(vs), 3) if vs else 0.0,
                }
            payload = {
                "ok":        True,
                "vertical":  key,
                "vertical_zh": v.zh,
                "vertical_icon": v.icon,
                "n_total":   len(samples),
                "n_good":    sum(1 for s in samples if s.bucket == "good"),
                "n_bad":     sum(1 for s in samples if s.bucket == "bad"),
                "thresholds_used": {
                    "keep_min":         round(kmin, 3),
                    "cull_max":         round(cmax, 3),
                    "tolerated_flags":  sorted(tol),
                    "is_override":      bool(eff and (
                        eff.keep_min_delta != v.policy.keep_min_delta
                        or eff.cull_max_delta != v.policy.cull_max_delta
                    )),
                },
                "confusion":     confusion,
                "metrics":       metrics,
                "score_distrib": axis_distrib,
                "misclassified_keep": misclassified_keep[:20],
                "misclassified_cull": misclassified_cull[:20],
            }
        except ValueError as exc:
            self._reject_upload(400, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            _capture_exception("verticals.eval", exc, {"key": key})  # V17.12
            self._reject_upload(500, f"评估失败: {type(exc).__name__}: {exc}")
            return
        self._send_json(200, _safe_dumps(payload).encode("utf-8"))

    # ---------- V17.7 bulk classify from folder ----------
    def _serve_vertical_bulk_page(self, key: str) -> None:
        """GET /verticals/bulk/<key> — full-page bulk classifier UI."""
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        v = vmod.get_vertical(key)
        if v is None:
            self.send_error(404, f"unknown vertical: {key}")
            return
        html = _VERTICAL_BULK_HTML.replace(
            "__VKEY__", key
        ).replace(
            "__VICON__", v.icon
        ).replace(
            "__VZH__", v.zh
        )
        self._send_html(200, html.encode("utf-8"))

    def _serve_vertical_bulk_thumb(self) -> None:
        """GET /verticals/bulk_thumb?path=<abs>&size=<px>

        Serves a JPEG thumbnail of a file the user just scanned via
        bulk_classify. Path is whitelisted against the in-process
        scan registry so this can't be used to probe random parts
        of the filesystem.
        """
        from urllib.parse import parse_qs, urlsplit
        full = urlsplit(self.path)
        qs = parse_qs(full.query) if full.query else {}
        raw_path = (qs.get("path", [""])[0] or "").strip()
        try:
            size = int(qs.get("size", ["240"])[0])
        except (TypeError, ValueError):
            size = 240
        size = max(80, min(800, size))
        if not raw_path:
            self.send_error(400, "missing path")
            return
        p = Path(unquote(raw_path))
        if not _bulk_path_allowed(p):
            self.send_error(403, "path not in scan whitelist")
            return
        if not p.is_file():
            self.send_error(404, "no such file")
            return
        try:
            from pixcull.io.loader import load_image
            img = load_image(p, max_side=size)
        except Exception as exc:
            _dbg("bulk_thumb/load_image", exc, str(p))
            img = None
        if img is None:
            self.send_error(500, "decode failed")
            return
        from io import BytesIO
        buf = BytesIO()
        img.save(buf, "JPEG", quality=78, optimize=True)
        data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _handle_vertical_bulk_classify(self, key: str) -> None:
        """POST /verticals/bulk_classify/<key>

        Body: {folder: "/abs/path", limit?: int (default 100)}

        Walks the folder, runs the rule pipeline (analyze_one +
        fuse_score + decide with the vertical's effective policy),
        returns one row per image with the SUGGESTED bucket so the
        user can review + adjust before committing.

        Capped at ``limit`` images to keep the response time bounded
        (~1-5s per image for the heavy detectors).
        """
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        v = vmod.get_vertical(key)
        if v is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 65536:
            self._reject_upload(400, "expected JSON body with {folder, limit?}")
            return
        try:
            params = json.loads(self.rfile.read(clen).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}")
            return
        folder_str = (params.get("folder") or "").strip()
        if not folder_str:
            self._reject_upload(400, "需要 folder 字段")
            return
        folder = Path(folder_str).expanduser()
        try:
            folder = folder.resolve()
        except OSError as exc:
            self._reject_upload(400, f"路径解析失败: {exc}")
            return
        if not folder.is_dir():
            self._reject_upload(400, f"不是文件夹: {folder}")
            return
        try:
            limit = int(params.get("limit", 100))
        except (TypeError, ValueError):
            limit = 100
        limit = max(1, min(500, limit))

        try:
            from pixcull.io.loader import list_images
            from pixcull.pipeline.worker import analyze_one
            from pixcull.scoring.fusion import fuse_score
            from pixcull.scoring.decision import decide, Decision
            from pixcull.scoring.style_modes import detect_style_modes
            from pixcull.config import PixCullConfig

            paths = list_images(folder)[:limit]
            if not paths:
                self._reject_upload(
                    400, f"在 {folder} 找不到可分析图片(支持 jpg/png/cr3/cr2/nef/arw)")
                return

            # Register the paths in the bulk whitelist so the
            # subsequent /verticals/bulk_thumb calls can resolve them.
            _bulk_register_paths(paths)

            config = PixCullConfig.load()
            items: list[dict] = []
            for p in paths:
                try:
                    row = analyze_one(p)
                except Exception as exc:
                    _dbg("bulk_classify/analyze", exc, str(p))
                    continue
                if row is None:
                    continue
                scene = str(row.get("scene") or "")
                flags = list(row.get("flags") or [])
                try:
                    dims = fuse_score(row, flags, scene, config)
                except Exception:
                    continue
                dec, _r = decide(
                    dims["final"], flags, config,
                    scene=scene, vertical=key,
                )
                # Suggested bucket — keep → good, cull → bad,
                # maybe → skip (user decides).
                suggested = "good" if dec is Decision.KEEP \
                       else "bad"  if dec is Decision.CULL \
                       else "skip"
                try:
                    sp = detect_style_modes(row)
                    styles = sorted(sp.modes)
                except Exception:
                    styles = []
                items.append({
                    "src_path":      str(p),
                    "filename":      p.name,
                    "score":         round(float(dims["final"]), 3),
                    "decision":      dec.value,
                    "suggested":     suggested,
                    "scene":         scene,
                    "styles":        styles,
                    "flags":         flags,
                })
            # Sort by score desc so highest-confidence keeps land first
            items.sort(key=lambda x: -x["score"])
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            _capture_exception("verticals.bulk_classify", exc,
                                 {"key": key, "folder": str(folder)})  # V17.12
            self._reject_upload(500, f"分析失败: {type(exc).__name__}: {exc}")
            return

        body = _safe_dumps({
            "ok":           True,
            "key":          key,
            "folder":       str(folder),
            "n_total":      len(items),
            "items":        items,
        }).encode("utf-8")
        self._send_json(200, body)

    def _handle_vertical_bulk_commit(self, key: str) -> None:
        """POST /verticals/bulk_commit/<key>

        Body: {assignments: [{src_path, bucket}, ...]}
        Where bucket ∈ {good, bad}. Anything else is silently skipped
        (the frontend uses "skip" to mean "don't commit this one").

        Each assignment's src_path must be in the bulk whitelist set
        by the most recent bulk_classify call. Bytes are READ from
        disk and saved into the vertical's good/bad dir via the
        existing ``save_sample`` helper (which hashes filenames to
        avoid collisions).
        """
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        v = vmod.get_vertical(key)
        if v is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > 4 * 1024 * 1024:
            self._reject_upload(400, "expected JSON body with assignments[]")
            return
        try:
            params = json.loads(self.rfile.read(clen).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"JSON parse failed: {exc}")
            return
        assigns = params.get("assignments")
        if not isinstance(assigns, list):
            self._reject_upload(400, "assignments must be a list")
            return

        saved: list[dict] = []
        skipped: list[dict] = []
        for a in assigns:
            if not isinstance(a, dict):
                continue
            src = (a.get("src_path") or "").strip()
            bucket = (a.get("bucket") or "").strip().lower()
            if bucket not in vmod.ALLOWED_BUCKETS:
                skipped.append({"src_path": src, "reason": f"bad bucket={bucket}"})
                continue
            p = Path(src)
            if not _bulk_path_allowed(p):
                skipped.append({"src_path": src, "reason": "not in whitelist"})
                continue
            if not p.is_file():
                skipped.append({"src_path": src, "reason": "no such file"})
                continue
            try:
                # Cap individual files at 32 MB (same as direct upload)
                data = p.read_bytes()
                if len(data) > 32 * 1024 * 1024:
                    skipped.append({"src_path": src, "reason": "file > 32 MB"})
                    continue
                info = vmod.save_sample(key, bucket, p.name, data)
                saved.append({"src_path": src, "bucket": bucket, **info})
            except Exception as exc:
                skipped.append({"src_path": src,
                                  "reason": f"{type(exc).__name__}: {exc}"})

        body = _safe_dumps({
            "ok":      True,
            "key":     key,
            "saved":   saved,
            "skipped": skipped,
            "counts":  vmod.count_samples(key),
        }).encode("utf-8")
        self._send_json(200, body)

    # ---------- V17.13 Unsplash CC0 reference fetcher ----------
    def _handle_vertical_unsplash_fetch(self, key: str) -> None:
        """POST /verticals/unsplash_fetch/<key>

        Body: {query?, bucket? (default "good"), count? (default 15,
        cap 30), orientation? (landscape/portrait/squarish)}

        Pulls top-relevant CC0 photos from Unsplash for the requested
        query, downloads them into the vertical's sample bank.
        Photographer credits saved to ``unsplash_attributions.json``
        sidecar.
        """
        from pixcull import verticals as vmod
        key = unquote(key.strip("/"))
        v = vmod.get_vertical(key)
        if v is None:
            self._reject_upload(404, f"unknown vertical: {key}")
            return
        clen = int(self.headers.get("Content-Length", "0") or "0")
        params: dict = {}
        if clen > 0 and clen < 8192:
            try:
                params = json.loads(self.rfile.read(clen).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._reject_upload(400, f"JSON parse failed: {exc}")
                return
        try:
            from pixcull import unsplash as up
            from dataclasses import asdict
            # Resolve defaults — let the caller override piecewise.
            defaults = up.default_query_for(key)
            query = (params.get("query") or defaults["query"]).strip()
            orientation = (params.get("orientation")
                              or defaults.get("orientation") or "landscape")
            bucket = (params.get("bucket") or "good").strip().lower()
            try:
                count = int(params.get("count", 15))
            except (TypeError, ValueError):
                count = 15
            result = up.populate_vertical(
                key, query=query, bucket=bucket,
                count=count, orientation=orientation,
            )
            payload = asdict(result)
            payload["counts"] = vmod.count_samples(key)
            payload["ok"] = True
        except ValueError as exc:
            # Predictable user errors: no key, no vertical, bad bucket
            self._reject_upload(400, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            _capture_exception("verticals.unsplash_fetch", exc,
                                 {"key": key})
            self._reject_upload(500,
                f"Unsplash 拉取失败: {type(exc).__name__}: {exc}")
            return
        self._send_json(200, _safe_dumps(payload).encode("utf-8"))

    # ---------- V17.8 auto-promote run's human keep/cull ----------
    def _handle_vertical_promote_run(self, run_id: str) -> None:
        """POST /verticals/promote_run/<run_id>

        Reads the run's annotations.jsonl, picks every entry whose
        ``overall_label`` is keep / cull (the user's human verdict),
        looks up the run's ``vertical`` tag, then copies each
        annotated file's bytes into that vertical's good/bad bank.

        Why this matters
        ----------------
        The annotation flow (rubric modal → save → next-to-label)
        produces a high-signal dataset every time the user labels a
        batch. Without V17.8 those labels live only in the run's
        ``annotations.jsonl`` and never feed back into the vertical's
        sample bank — so the V17.4 tuner / V17.5 LLM never see them.
        Promoting closes the loop: run → label → sample bank → next
        run's policy is shaped by what the user just taught us.

        Idempotency
        -----------
        ``save_sample`` names files by SHA-256 of the content. Re-
        promoting the same run silently overwrites with identical
        bytes; no duplicates.

        Body is empty / ignored.
        """
        from pixcull import verticals as vmod
        run_id = unquote(run_id.strip("/"))
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self._reject_upload(404, f"unknown run: {run_id}")
            return
        vertical_key = run.get("vertical")
        if not vertical_key:
            self._reject_upload(
                400,
                "this run wasn't tagged with a vertical — "
                "rerun the batch with the vertical dropdown set",
            )
            return
        v = vmod.get_vertical(vertical_key)
        if v is None:
            self._reject_upload(404, f"unknown vertical: {vertical_key}")
            return

        # Walk annotations.jsonl, build {filename: overall_label}
        output_dir = Path(run["output_dir"])
        ann_path = output_dir / "annotations.jsonl"
        if not ann_path.exists():
            self._reject_upload(400,
                "this run has no human annotations to promote")
            return
        human_by_fn: dict[str, str] = {}   # filename → keep/cull
        try:
            for line in ann_path.read_text("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fn = rec.get("filename")
                lbl = (rec.get("overall_label") or "").strip().lower()
                if fn and lbl in ("keep", "cull"):
                    human_by_fn[fn] = lbl   # latest line wins
        except OSError as exc:
            self._reject_upload(500, f"无法读 annotations.jsonl: {exc}")
            return

        if not human_by_fn:
            self._reject_upload(
                400,
                "no human keep/cull annotations found — label some "
                "images with overall_label first",
            )
            return

        # Resolve filename → original-bytes source path. In scan mode
        # we have a manifest.json; in upload mode files live under
        # the run's input dir. Use the existing helper.
        saved: list[dict] = []
        skipped: list[dict] = []
        for fn, lbl in human_by_fn.items():
            src = _resolve_image_source(run, Path(fn).name)
            if src is None or not src.exists():
                skipped.append({"filename": fn, "reason": "source missing"})
                continue
            bucket = "good" if lbl == "keep" else "bad"
            try:
                data = src.read_bytes()
                if len(data) > 32 * 1024 * 1024:
                    skipped.append({"filename": fn, "reason": "> 32 MB"})
                    continue
                info = vmod.save_sample(vertical_key, bucket, src.name, data)
                saved.append({
                    "filename": fn, "bucket": bucket, **info,
                })
            except Exception as exc:  # noqa: BLE001
                skipped.append({
                    "filename": fn,
                    "reason": f"{type(exc).__name__}: {exc}",
                })

        body = _safe_dumps({
            "ok":           True,
            "run_id":       run_id,
            "vertical":     vertical_key,
            "vertical_zh":  v.zh,
            "n_promoted":   len(saved),
            "n_skipped":    len(skipped),
            "saved":        saved,
            "skipped":      skipped,
            "counts":       vmod.count_samples(vertical_key),
        }).encode("utf-8")
        self._send_json(200, body)

    def _handle_vertical_sample_delete(self, rel: str) -> None:
        from pixcull import verticals as vmod
        rel = unquote(rel)
        parts = rel.split("/", 2)
        if len(parts) != 3:
            self._reject_upload(400, "expected key/bucket/filename")
            return
        key, bucket, fn = parts
        ok = vmod.delete_sample(key, bucket, fn)
        body = _safe_dumps({
            "ok": ok,
            "counts": vmod.count_samples(key) if ok else None,
        }).encode("utf-8")
        self._send_json(200 if ok else 404, body)

    # --- V14.7 opt-in error reporting -------------------------------------
    def _serve_privacy_page(self) -> None:
        body = _PRIVACY_HTML.encode("utf-8")
        self._send_html(200, body)

    def _serve_error_reports_settings(self) -> None:
        """GET — read current opt-in state from config.json. Default OFF."""
        cfg = _load_user_config()
        body = _safe_dumps({
            "enabled":  bool(cfg.get("error_reports_enabled")),
            "endpoint": str(cfg.get("error_reports_endpoint", "") or ""),
        }).encode("utf-8")
        self._send_json(200, body)

    def _handle_save_error_reports_settings(self) -> None:
        """POST {enabled, endpoint?} — persist opt-in toggle to config.json."""
        clen = int(self.headers.get("Content-Length", "0") or "0")
        try:
            data = json.loads(self.rfile.read(clen).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._reject_upload(400, f"invalid JSON: {exc}")
            return
        enabled = bool(data.get("enabled"))
        endpoint = str(data.get("endpoint", "") or "").strip()
        cfg = _load_user_config()
        cfg["error_reports_enabled"] = enabled
        if endpoint:
            cfg["error_reports_endpoint"] = endpoint
        elif "error_reports_endpoint" in cfg:
            # Clear stale endpoint when user blanks it
            cfg["error_reports_endpoint"] = ""
        _save_user_config(cfg)
        body = _safe_dumps({
            "ok": True, "enabled": enabled, "endpoint": endpoint,
        }).encode("utf-8")
        self._send_json(200, body)

    def _handle_submit_error_report(self) -> None:
        """POST — manually submit a redacted report payload now."""
        clen = int(self.headers.get("Content-Length", "0") or "0")
        try:
            data = json.loads(self.rfile.read(clen).decode("utf-8") or "{}") if clen else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        from pixcull import error_reporting as er
        cfg = _load_user_config()
        result = er.submit_report(
            cfg,
            app_version="14.7.0",
            log_dir=_app_data_dir() / "logs",
            reason=str(data.get("reason", "manual")),
            extra={"trigger": "user-clicked-submit"},
        )
        body = _safe_dumps(result).encode("utf-8")
        # 200 even on dry-run / disabled — the result body explains.
        self._send_json(200, body)

    def _handle_client_error_event(self) -> None:
        """V17.12 — POST /error_reports/client_event

        Browser-side window.onerror / unhandledrejection hits this.
        Captured fields are bounded + redacted before going through
        the V14.7 submit pipeline. Respects opt-in (200 always; body
        explains).

        Body: {message, source, lineno, colno, stack?, kind?,
               url?, ua?}
        """
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen > 32 * 1024:
            self._reject_upload(400, "client-event payload too large")
            return
        try:
            data = json.loads(self.rfile.read(clen).decode("utf-8") or "{}") if clen else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        _capture_client_event(data)
        self._send_json(200, _safe_dumps({"ok": True}).encode("utf-8"))

    # --- storage admin -----------------------------------------------------
    def _serve_admin_page(self) -> None:
        body = _ADMIN_HTML.encode("utf-8")
        self._send_html(200, body)

    # v0.7-P0-3 — performance debug page.  Lightweight: same template
    # frame as /admin, but populated with process RSS, # active runs,
    # /tmp/pixcull_demo size, and per-run row counts. Refreshes every
    # 4 s via fetch() to /admin/perf.json so the operator can watch
    # how big-batch runs grow over time.
    def _serve_admin_perf_page(self) -> None:
        body = _ADMIN_PERF_HTML.encode("utf-8")
        self._send_html(200, body)

    def _serve_admin_perf_json(self) -> None:
        import resource
        import shutil
        snap: dict = {}
        # Process RSS (Linux: KB; macOS: bytes).
        try:
            r = resource.getrusage(resource.RUSAGE_SELF)
            rss = r.ru_maxrss
            if sys.platform != "darwin":
                rss *= 1024  # KB → bytes on Linux
            snap["rss_bytes"] = rss
        except Exception:
            snap["rss_bytes"] = None
        # /tmp/pixcull_demo total bytes (cap shallow-walk depth so
        # this stays fast even on 5k-photo runs).
        demo_root = Path("/tmp/pixcull_demo")
        try:
            total = 0
            run_sizes: dict = {}
            if demo_root.exists():
                for entry in demo_root.iterdir():
                    if not entry.is_dir():
                        continue
                    sz = sum(
                        f.stat().st_size for f in entry.rglob("*")
                        if f.is_file()
                    )
                    total += sz
                    run_sizes[entry.name] = sz
            snap["disk_total_bytes"] = total
            snap["disk_per_run"] = run_sizes
        except Exception:
            snap["disk_total_bytes"] = None
            snap["disk_per_run"] = {}
        # Active runs in memory.
        try:
            with _RUNS_LOCK:
                snap["active_runs"] = len(_RUNS)
                snap["run_row_counts"] = {
                    rid: int(r.get("summary", {}).get("n_total", 0))
                    for rid, r in _RUNS.items()
                }
        except Exception:
            snap["active_runs"] = None
            snap["run_row_counts"] = {}
        # Free disk on the demo partition.
        try:
            du = shutil.disk_usage(demo_root if demo_root.exists() else "/tmp")
            snap["disk_free_bytes"] = du.free
            snap["disk_total_partition_bytes"] = du.total
        except Exception:
            snap["disk_free_bytes"] = None
            snap["disk_total_partition_bytes"] = None
        self._send_json(
            200, _safe_dumps(snap).encode("utf-8")
        )

    # P-AI-4.1 — face library quality audit page.  Loads the run's
    # face_centroids.npz + the user-root library, applies the three
    # P-AI-4 audits (cluster precision, fragmentation, cross-run
    # continuity), renders an HTML report.  ``?format=json`` returns
    # the same data as JSON for tooling.
    def _serve_face_audit(self, run_id: str) -> bool:
        run_id = unquote(run_id).split("?")[0]
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self._reject_upload(404, f"no such run {run_id!r}")
            return True
        # Parse the optional ?format=json query string
        want_json = "format=json" in (self.path or "")

        try:
            import numpy as np
            from pixcull.pipeline.face_audit import (
                CLUSTER_PAIR_OUTLIER_SIM,
                cluster_precision_audit,
                cross_run_continuity_audit,
                library_fragmentation_audit,
            )
            from pixcull.pipeline.face_library import (
                load_library,
                load_run_centroids,
            )
            from pixcull.users import get_active_user, user_root as _user_root_fn
        except ImportError as exc:
            self._reject_upload(500, f"face audit imports failed: {exc}")
            return True

        out_dir = Path(run["output_dir"])
        user_root = _user_root_fn(get_active_user())

        # ---- Cluster precision ----------------------------------
        # Need per-cluster member embeddings.  Read rows.parquet /
        # scores.csv to assemble {cluster_id: [face_embeddings...]}.
        cluster_reports: list[dict] = []
        try:
            scores_path = out_dir / "scores.csv"
            if scores_path.exists():
                import pandas as pd
                df = pd.read_csv(scores_path)
                if "face_cluster_id" in df.columns \
                   and "face_embeddings" in df.columns:
                    import json as _json
                    by_cluster: dict[int, list[list[float]]] = {}
                    for _, row in df.iterrows():
                        cid = row.get("face_cluster_id")
                        if cid is None or pd.isna(cid):
                            continue
                        embs_raw = row.get("face_embeddings")
                        try:
                            embs = _json.loads(embs_raw) \
                                if isinstance(embs_raw, str) else []
                        except (ValueError, TypeError):
                            embs = []
                        # face_embeddings is list-of-list (one per face);
                        # take all of them
                        for e in embs:
                            if isinstance(e, list) and e:
                                by_cluster.setdefault(int(cid), []).append(e)
                    for cid, embs in by_cluster.items():
                        rpt = cluster_precision_audit(embs, cluster_id=cid)
                        cluster_reports.append({
                            "cluster_id":      rpt.cluster_id,
                            "n_members":       rpt.n_members,
                            "min_pair_sim":    round(rpt.min_pair_sim, 3),
                            "mean_pair_sim":   round(rpt.mean_pair_sim, 3),
                            "n_outliers":      len(rpt.outlier_indices),
                            "polluted":        rpt.polluted,
                        })
        except (OSError, ValueError, KeyError):
            cluster_reports = []

        # ---- Library fragmentation ------------------------------
        frag_reports: list[dict] = []
        try:
            labels, lib_centroids = load_library(user_root)
            if len(labels) > 0:
                by_label: dict[str, list[list[float]]] = {}
                for lab, c in zip(labels, lib_centroids):
                    by_label.setdefault(str(lab), []).append(list(c))
                for r in library_fragmentation_audit(by_label):
                    frag_reports.append({
                        "label":       r.label,
                        "n_centroids": r.n_centroids,
                        "fragmented":  r.fragmented,
                    })
        except (OSError, ValueError):
            frag_reports = []

        # ---- Cross-run continuity -------------------------------
        continuity: dict = {"n_current_clusters": 0,
                            "n_matched_to_library": 0,
                            "match_rate": 0.0}
        try:
            this_run = load_run_centroids(out_dir)
            labels, lib_centroids = load_library(user_root)
            if this_run is not None and len(lib_centroids) > 0:
                _, cur_centroids = this_run
                cur_list = [list(c) for c in cur_centroids]
                lib_list = [list(c) for c in lib_centroids]
                cont = cross_run_continuity_audit(cur_list, lib_list)
                continuity = {
                    "n_current_clusters":   cont.n_current_clusters,
                    "n_matched_to_library": cont.n_matched_to_library,
                    "match_rate":           cont.match_rate,
                }
        except (OSError, ValueError):
            pass

        payload = {
            "run_id":            run_id,
            "outlier_threshold": CLUSTER_PAIR_OUTLIER_SIM,
            "cluster_precision": cluster_reports,
            "library_fragmentation": frag_reports,
            "continuity":        continuity,
        }

        if want_json:
            self._send_json(200,
                _safe_dumps(payload).encode("utf-8"))
            return True

        # ---- HTML render ----------------------------------------
        html = _render_face_audit_html(payload)
        self._send_html(200, html.encode("utf-8"))
        return True

    # P-PRO-7.1 — full delivery audit page.  Subprocess-runs
    # ``scripts/cli_audit.py`` on the run's scores.csv + image input
    # dir, then wraps the resulting Markdown report in a minimal
    # HTML chrome so the photographer can read it in the browser
    # without dropping to a terminal.  ``?format=md`` returns the
    # raw markdown for piping into a PR / issue.
    def _serve_delivery_audit(self, run_id: str) -> bool:
        import shlex
        import subprocess
        run_id = unquote(run_id).split("?")[0]
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self._reject_upload(404, f"no such run {run_id!r}")
            return True
        want_md = "format=md" in (self.path or "")
        preset = "western"
        if "preset=chinese" in (self.path or ""):
            preset = "chinese"

        out_dir = Path(run["output_dir"])
        scores_csv = out_dir / "scores.csv"
        if not scores_csv.exists():
            self._reject_upload(404,
                f"no scores.csv at {scores_csv} — run hasn't completed?")
            return True
        # Image root: prefer input/ for upload-mode runs; scan-mode
        # runs carry absolute paths in scores.csv so leave None.
        input_dir = out_dir.parent / "input"
        cli_path = Path(__file__).resolve().parent / "cli_audit.py"

        cmd = [
            sys.executable, str(cli_path),
            "--scores-csv", str(scores_csv),
            "--mandatory-preset", preset,
        ]
        if input_dir.is_dir():
            cmd += ["--image-root", str(input_dir)]
        # User-root for the face library audit
        try:
            from pixcull.users import get_active_user, user_root as _ur
            uroot = _ur(get_active_user())
            if uroot:
                cmd += ["--user-root", str(uroot)]
        except ImportError:
            pass

        # Time-bound the subprocess so a stuck audit doesn't hang the
        # server.  60s is generous (real audits land in <30s).
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90,
                env={**os.environ, "PYTHONPATH":
                     str(Path(__file__).resolve().parent.parent) +
                     ":" + os.environ.get("PYTHONPATH", "")},
            )
        except subprocess.TimeoutExpired:
            self._reject_upload(504, "audit timed out (>90s)")
            return True
        if proc.returncode != 0:
            self._reject_upload(500,
                f"cli_audit failed (exit {proc.returncode}): "
                f"{proc.stderr[:500]}")
            return True
        md = proc.stdout

        if want_md:
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/markdown; charset=utf-8")
            self.send_header("Content-Length",
                             str(len(md.encode("utf-8"))))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(md.encode("utf-8"))
            return True

        html = _render_delivery_audit_html(run_id, md, preset)
        self._send_html(200, html.encode("utf-8"))
        return True

    def _serve_runs_list(self) -> None:
        body = json.dumps({"runs": _enumerate_runs()},
                          ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    def _serve_storage_info(self) -> None:
        body = json.dumps(_storage_info(),
                          ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    def _handle_run_delete(self, run_id: str) -> None:
        ok, msg = _delete_run(unquote(run_id))
        status = 200 if ok else 404 if msg == "no such run" else 400
        body = json.dumps({"ok": ok, "message": msg, "run_id": run_id},
                          ensure_ascii=False).encode("utf-8")
        self._send_json(status, body)

    def _handle_rescan_scene(self, run_id: str) -> None:
        """P0.4 — re-run SceneDetector on the cached scores.csv rows
        of a run, applying V20's face-aware stilllife correction.

        Pre-V20 SceneDetector mis-tagged a meaningful fraction of
        indoor portrait / event shots as ``stilllife`` (CLIP's
        "product in studio" prompt is a magnet for warm indoor lighting
        with a centered subject). V20's worker.py added a correction
        path — "if face_count > 0 and scene == stilllife, walk
        scene_probs in descending order and pick the next non-
        stilllife class". That fix only takes effect on NEW scans;
        existing cached runs still carry the bad tags.

        This endpoint applies the correction to cached scores.csv
        rows IN-PLACE without re-running the full pipeline. Only
        rows with face_count > 0 are touched; the corrected scene
        is whichever non-stilllife class scored second-best in
        scene_probs. When ``scene_probs`` isn't preserved on disk
        (pre-V8.2 scans), we fall back to "portrait" as a safe
        default since face_count > 0 strongly suggests that scene.

        Method: POST so the action is deliberate (admin button only).
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        scores_path = Path(run["output_dir"]) / "scores.csv"
        if not scores_path.exists():
            self.send_error(404, "no scores.csv to re-scene")
            return
        import pandas as pd
        df = pd.read_csv(scores_path)
        if "scene" not in df.columns or "face_count" not in df.columns:
            self.send_error(
                400,
                "scores.csv schema doesn't have scene + face_count — "
                "this run is too old to re-scene cheaply. Re-scan the "
                "folder instead.",
            )
            return

        # Backup the existing scores.csv before mutating
        backup = scores_path.with_suffix(
            f".csv.bak.{int(time.time())}"
        )
        try:
            scores_path.rename(backup)
        except OSError as exc:
            self.send_error(500, f"backup failed: {exc}")
            return

        # The set of "bad" stilllife tags we want to correct
        mask = (
            (df["scene"].astype(str) == "stilllife")
            & (df["face_count"].fillna(0).astype(float) > 0)
        )
        n_candidates = int(mask.sum())

        # Try to read the per-row scene_probs (a JSON string column
        # since V8.2). When present, parse it and pick the
        # highest-probability non-stilllife class. Otherwise default
        # to "portrait" since face_count > 0 strongly suggests that.
        corrected: list[tuple[int, str]] = []
        if "scene_probs" in df.columns:
            import ast
            for idx in df.index[mask].tolist():
                raw = df.at[idx, "scene_probs"]
                pick = "portrait"
                if isinstance(raw, str) and raw:
                    try:
                        probs = ast.literal_eval(raw)
                        if isinstance(probs, dict):
                            ranked = sorted(
                                probs.items(), key=lambda kv: -float(kv[1]),
                            )
                            for name, _p in ranked:
                                if name != "stilllife":
                                    pick = name
                                    break
                    except (ValueError, SyntaxError, TypeError):
                        pass
                corrected.append((idx, pick))
        else:
            for idx in df.index[mask].tolist():
                corrected.append((idx, "portrait"))

        for idx, new_scene in corrected:
            df.at[idx, "scene"] = new_scene
        df.to_csv(scores_path, index=False)

        body = _safe_dumps({
            "ok":         True,
            "run_id":     run_id,
            "n_total":    int(len(df)),
            "n_corrected": len(corrected),
            "scene_redistribution":
                {k: int(v) for k, v in
                 pd.Series([c[1] for c in corrected]).value_counts().items()}
                if corrected else {},
            "backup_path": str(backup),
            "note": "scores.csv 已更新;刷新结果页即可看到新的 scene 分布。",
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_apply_style_guide(self, run_id: str) -> None:
        """P2.3 — apply the active user's style guide to a run.

        Runs every rule against every row, tallies violations, and
        OPTIONALLY adjusts the decision column when a rule's
        ``on_violation`` is ``maybe`` or ``cull``. Reports a per-
        rule violation count + total adjustments back.

        Body (optional):
            {dry_run: bool}   — when True, don't mutate scores.csv,
                                just report what WOULD change.
        """
        run = _get_run(run_id) or _reload_run_from_disk(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        n = int(self.headers.get("Content-Length") or "0")
        params: dict = {}
        if n > 0:
            try:
                params = json.loads(self.rfile.read(n).decode("utf-8")
                                      or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_error(400, "invalid JSON body")
                return
        dry_run = bool(params.get("dry_run") or False)

        from pixcull.scoring.style_guide import (
            load_style_guide, apply_style_guide,
        )
        guide = load_style_guide()
        if not guide:
            body = _safe_dumps({
                "ok": True, "run_id": run_id,
                "message": "no style guide configured for active user "
                           "(no <user_root>/style_guide.yaml and no "
                           "subscribed team guide)",
                "violations_n": 0, "decision_changes": 0,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",
                              "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        result = _build_results(run_id)
        if result is None:
            self.send_error(425, "results not ready")
            return
        rows, _summary = result

        scores_path = Path(run["output_dir"]) / "scores.csv"
        import pandas as pd
        df = pd.read_csv(scores_path)

        per_rule_count: dict[str, int] = {}
        decision_changes = 0
        sample_violations: list[dict] = []
        for i, r in enumerate(rows):
            src = r.get("src_path") or r.get("path")
            res = apply_style_guide(
                r, guide,
                image_path=Path(src) if src else None,
            )
            for v in res["violations"]:
                per_rule_count[v["rule_id"]] = (
                    per_rule_count.get(v["rule_id"], 0) + 1
                )
                if len(sample_violations) < 8:
                    sample_violations.append({
                        "filename": r["filename"],
                        **v,
                    })
            new_dec = res["new_decision"]
            if new_dec and new_dec != r["decision"]:
                decision_changes += 1
                if not dry_run:
                    # Update scores.csv in place
                    match = df["filename"] == r["filename"]
                    df.loc[match, "decision"] = new_dec

        if not dry_run and decision_changes > 0:
            backup = scores_path.with_suffix(
                f".csv.bak.{int(time.time())}"
            )
            try:
                scores_path.rename(backup)
                df.to_csv(scores_path, index=False)
            except OSError as exc:
                self.send_error(500, f"write failed: {exc}")
                return

        body = _safe_dumps({
            "ok":               True,
            "run_id":           run_id,
            "dry_run":          dry_run,
            "guide_name":       guide.get("name") or "(unnamed)",
            "n_rows":           int(len(df)),
            "violations_n":     sum(per_rule_count.values()),
            "per_rule_count":   per_rule_count,
            "decision_changes": decision_changes,
            "sample_violations": sample_violations,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_runs_cleanup(self) -> None:
        """Bulk delete by policy. Body: {older_than_hours?, keep_last?}.

        Both filters are optional; if both are provided we apply them as
        an intersection ("older than X AND not in newest K").

        Per-run busy state: a run still marked ``running`` is never
        deleted (would corrupt the analyzing thread). The user can wait
        or kill the server and retry.
        """
        clen = int(self.headers.get("Content-Length", "0") or "0")
        body_bytes = self.rfile.read(clen) if clen > 0 else b"{}"
        try:
            params = json.loads(body_bytes.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "expected JSON body")
            return

        older = params.get("older_than_hours")
        keep_last = params.get("keep_last")

        runs = _enumerate_runs()  # newest first
        candidates: list[dict] = list(runs)

        # Skip in-progress runs unconditionally; they own files we'd corrupt.
        candidates = [r for r in candidates if r.get("state") != "running"]

        # "Keep last K" — preserve the K newest, mark the rest as candidates.
        if isinstance(keep_last, int) and keep_last >= 0:
            candidates = candidates[keep_last:]

        # "Older than N hours" — must be older than the cutoff.
        if isinstance(older, (int, float)) and older >= 0:
            cutoff = time.time() - float(older) * 3600
            candidates = [r for r in candidates if (r["mtime"] or 0) < cutoff]

        results = []
        freed_bytes = 0
        for r in candidates:
            ok, msg = _delete_run(r["run_id"])
            results.append({
                "run_id": r["run_id"],
                "ok": ok,
                "message": msg,
                "size_bytes": r["size_bytes"],
            })
            if ok:
                freed_bytes += r["size_bytes"]

        body = json.dumps({
            "candidates_considered": len(candidates),
            "deleted": sum(1 for r in results if r["ok"]),
            "freed_bytes": freed_bytes,
            "results": results,
        }, ensure_ascii=False).encode("utf-8")
        self._send_json(200, body)

    # --- utilities ---------------------------------------------------------
    def _send_html(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _reject_upload(self, status: int, message: str) -> None:
        """Send a JSON error reply for an /analyze failure.

        Replaces the default ``send_error`` HTML stub — the upload page's
        JS surfaces ``data.error`` directly, so a clean string beats a
        BaseHTTPRequestHandler error page being scraped into a textbox.
        """
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self._send_json(status, body)


# ---------------------------------------------------------------------------
# Server bootstrap.
# ---------------------------------------------------------------------------
def _load_app_config_into_env() -> None:
    """V17.5 — when serve_demo is launched directly (not via the .app),
    ``DEEPSEEK_API_KEY`` won't be set even if the user previously
    configured it via the launcher menu. Read the same config.json the
    launcher writes to so dev-mode runs match production behavior.
    """
    if os.environ.get("DEEPSEEK_API_KEY"):
        return  # already set, don't override
    import sys as _sys
    if _sys.platform == "darwin":
        cfg_path = Path.home() / "Library" / "Application Support" / "PixCull" / "config.json"
    else:
        cfg_path = Path.home() / ".pixcull" / "config.json"
    if not cfg_path.exists():
        return
    try:
        cfg = json.loads(cfg_path.read_text("utf-8"))
        if cfg.get("deepseek_api_key"):
            os.environ["DEEPSEEK_API_KEY"] = cfg["deepseek_api_key"]
            print(f"  config: loaded DeepSeek key from {cfg_path}",
                  file=sys.stderr)
    except (OSError, json.JSONDecodeError) as exc:
        _dbg("load_app_config", exc, str(cfg_path))


def main() -> None:
    _load_app_config_into_env()
    parser = argparse.ArgumentParser(
        description="PixCull web demo — upload images and see decisions."
    )
    parser.add_argument(
        "--port", type=int, default=_DEFAULT_PORT,
        help=f"Preferred port (default {_DEFAULT_PORT}; auto-fallback if busy)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default 127.0.0.1 — localhost only). "
             "Use 0.0.0.0 to expose to LAN. WARNING: no auth, only do this "
             "on networks you trust.",
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="Don't open a browser tab on startup",
    )
    parser.add_argument(
        "--rescorer-mode", default="auto",
        choices=("auto", "off", "shadow", "adjudicate"),
        help="V1.2 rescorer mode. 'auto' (default) uses 'shadow' if "
             "models/rescorer_v1.joblib exists, else 'off'. 'shadow' shows "
             "the model's keep/maybe prediction next to each card without "
             "changing decisions; 'adjudicate' lets the model promote "
             "rule-maybe rows to keep when confident.",
    )
    parser.add_argument(
        "--rescorer-path", default=None,
        help="Path to rescorer joblib (default: models/rescorer_v1.joblib)",
    )
    parser.add_argument(
        "--auto-prune-hours", type=float, default=None,
        help="On startup, delete every existing run dir older than N hours. "
             "Off by default — admin panel does the same job interactively.",
    )
    parser.add_argument(
        "--max-upload-mb", type=int,
        default=_MAX_UPLOAD_BYTES_DEFAULT // 1024 // 1024,
        help=f"Per-request upload size cap in MB. Default "
             f"{_MAX_UPLOAD_BYTES_DEFAULT // 1024 // 1024} MB "
             f"(≈130-260 RAW shots). Raise for bigger batches.",
    )
    parser.add_argument(
        "--max-upload-files", type=int, default=_MAX_UPLOAD_FILES_DEFAULT,
        help=f"Per-request file count cap. Default {_MAX_UPLOAD_FILES_DEFAULT}.",
    )
    parser.add_argument(
        "--vlm-mode", default="off",
        help="V3.0 VLM-as-judge backend (sees pixels). Default off. "
             "Values: 'off' | 'local' | 'local:<repo>' | 'deepseek' | "
             "'minimax' | 'openai'. Note: as of 2026-04 DeepSeek's API is "
             "TEXT ONLY — use 'local' for vision and 'deepseek' for the "
             "meta judge below.",
    )
    parser.add_argument(
        "--meta-mode", default="off",
        help="V3.1 meta-judge: text LLM consolidates all signals "
             "(rule + V2.1 model + VLM + detector metrics) into a "
             "calibrated final verdict. Off by default. Values: "
             "'off' | 'deepseek' (V4-Flash) | 'deepseek:deepseek-v4-pro'. "
             "Requires DEEPSEEK_API_KEY env var. ~¥0.003/image.",
    )
    args = parser.parse_args()

    _DEMO_ROOT.mkdir(parents=True, exist_ok=True)

    if args.auto_prune_hours is not None and args.auto_prune_hours >= 0:
        cutoff = time.time() - args.auto_prune_hours * 3600
        pruned = 0
        freed = 0
        for r in _enumerate_runs():
            if (r["mtime"] or 0) < cutoff and r.get("state") != "running":
                ok, _ = _delete_run(r["run_id"])
                if ok:
                    pruned += 1
                    freed += r["size_bytes"]
        if pruned:
            mb = freed / 1024 / 1024
            print(f"  auto-prune: deleted {pruned} run(s) older than "
                  f"{args.auto_prune_hours}h, freed {mb:.1f} MB")

    # Resolve rescorer 'auto': use shadow if a model file is present at the
    # default (or user-specified) location, else fall through to off. This
    # makes the demo "self-tuning" — fresh checkouts work, trained
    # checkouts get the V1.1 head turned on for free.
    rescorer_path = args.rescorer_path or "models/rescorer_v1.joblib"
    rescorer_mode = args.rescorer_mode
    if rescorer_mode == "auto":
        rescorer_mode = "shadow" if Path(rescorer_path).exists() else "off"

    port = _pick_port(args.port, args.host)
    server = ThreadingHTTPServer((args.host, port), _Handler)
    server.rescorer_mode = rescorer_mode  # type: ignore[attr-defined]
    server.rescorer_path = rescorer_path  # type: ignore[attr-defined]
    server.max_upload_bytes = args.max_upload_mb * 1024 * 1024  # type: ignore[attr-defined]
    server.max_upload_files = args.max_upload_files  # type: ignore[attr-defined]
    server.vlm_mode = args.vlm_mode  # type: ignore[attr-defined]
    server.meta_mode = args.meta_mode  # type: ignore[attr-defined]

    # Print URLs the user can paste into a browser. On 0.0.0.0 we also
    # show the LAN IP so the operator knows the address to share rather
    # than running ifconfig themselves.
    local_url = f"http://127.0.0.1:{port}/"
    print(f"PixCull demo serving on {args.host}:{port}")
    print(f"  local:   {local_url}")
    if args.host == "0.0.0.0":
        ip = _local_ipv4()
        if ip:
            print(f"  LAN:     http://{ip}:{port}/  (share this with phones / other laptops)")
        else:
            print("  LAN:     <couldn't detect IP — run `ipconfig getifaddr en0`>")
        print("  ⚠  exposed to LAN with no auth — only run on trusted networks")
    print(f"  output:  {_DEMO_ROOT}/<run_id>/")
    if args.rescorer_mode == "auto":
        print(f"  rescorer: {rescorer_mode} (auto-resolved; model at {rescorer_path})")
    else:
        print(f"  rescorer: {rescorer_mode} (forced; model at {rescorer_path})")
    print(f"  upload limits: {args.max_upload_mb} MB / {args.max_upload_files} files per request")
    if args.vlm_mode != "off":
        print(f"  VLM mode: {args.vlm_mode} (V3.0 — adds ~10s/img local, ~2s/img API)")
    if args.meta_mode != "off":
        print(f"  Meta-judge: {args.meta_mode} (V3.1 — adds ~5-10s/img · ~¥0.003/img)")
    if not args.no_open and args.host in ("127.0.0.1", "localhost"):
        threading.Timer(0.4, lambda: webbrowser.open(local_url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


# README that ships inside the XMP zip download. Tells the user what to
# do with the sidecars on the Lightroom / Capture One side.
_XMP_README = """PixCull XMP sidecar export — run {run_id}

This zip contains {n} XMP sidecar files, one per analyzed image.
Each <filename>.xmp encodes the pipeline's decision as:

  keep   →  5 stars + Green label
  maybe  →  3 stars + Yellow label
  cull   →  1 star  + Red label

How to apply (Lightroom Classic):
  1. Place each .xmp next to its image (same stem, same folder)
  2. In LR Library → Metadata → Read Metadata from File
  3. Or set Edit → Catalog Settings → "Automatically write changes into XMP"

How to apply (Capture One):
  1. Place each .xmp next to its image
  2. C1 reads on import; if already imported, right-click → Sync Metadata

The sidecar files only carry rating + label. Develop adjustments, keywords,
and other Lightroom metadata are untouched.
"""


# ---------------------------------------------------------------------------
# HTML — kept inline for single-file shippability, except results.html
# which V19.4.1 split out to support hot-reloadable edits without restart:
#   _UPLOAD_HTML            GET /            drag-drop + status panel
#   results.html [external] GET /results/    decision grid (data → __PAYLOAD__)
#   _FIRST_RUN_HTML         GET /first_run   model-warming progress (V14.6)
#   _ADMIN_HTML             GET /admin       storage / runs admin
# ---------------------------------------------------------------------------

# V14.6 — first-run progress page. Polls /first_run_status every
# 1.5 s to drive a progress bar with per-step labels. On phase ==
# "done" it celebrates briefly, then redirects to "/". On phase ==
# "skipped" or "idle" (i.e. user opened this URL after first-run
# already completed), it auto-redirects so the page is harmless.
#
# Visual style mirrors the upload page: same dark bg, same accent
# blue, same Inter/SF stack — feels like the same app, not a
# bootstrap loader.
_FIRST_RUN_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 首次设置</title>
  <style>
    :root {
      --bg: #0b0d10;
      --bg-card: #14171c;
      --fg: #e9ecf2;
      --muted: #a8b2c1;
      --accent: #3b82f6;
      --accent-hi: #60a5fa;
      --border: #232830;
      --keep: #4ade80;
      --maybe: #d9a30c;
      --cull: #f87171;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font: 14px/1.5 -apple-system, "SF Pro Text", "Inter", "Segoe UI Variable",
            "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--fg);
      min-height: 100vh;
      display: grid; place-items: center;
      padding: 24px;
    }
    .stage {
      width: 100%; max-width: 560px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 32px 36px;
      box-shadow: 0 24px 60px rgba(0,0,0,0.4);
    }
    .stage h1 {
      margin: 0 0 6px; font-size: 22px; font-weight: 600;
      letter-spacing: -0.01em;
    }
    .stage .subtitle {
      color: var(--muted); font-size: 13px; margin-bottom: 24px;
    }
    .stage .step-label {
      font-size: 13px; color: var(--fg); margin-bottom: 8px;
      min-height: 19px;
    }
    .stage .progress-shell {
      width: 100%; height: 8px;
      background: rgba(255,255,255,0.06);
      border-radius: 999px; overflow: hidden;
      position: relative;
    }
    .stage .progress-bar {
      height: 100%; background: linear-gradient(
        90deg, var(--accent), var(--accent-hi)
      );
      border-radius: 999px;
      transition: width 320ms cubic-bezier(0.16, 1, 0.3, 1);
      box-shadow: 0 0 12px rgba(59,130,246,0.4);
      width: 0%;
    }
    /* Indeterminate shimmer while a step is in flight (we know
       the count of steps but each one is opaque to us — pyiqa
       might take 30 s, U²-Net 90 s). */
    .stage .progress-bar.indeterminate {
      background: linear-gradient(
        90deg, transparent, rgba(96,165,250,0.6), transparent
      );
      background-size: 200% 100%;
      animation: shimmer 1.4s linear infinite;
    }
    @keyframes shimmer {
      from { background-position: 200% 0; }
      to   { background-position: -200% 0; }
    }
    .stage .meta {
      display: flex; gap: 16px; align-items: center;
      margin-top: 12px;
      font-size: 12px; color: var(--muted);
    }
    .stage .meta .count { font-variant-numeric: tabular-nums; }
    .stage .errors {
      margin-top: 16px;
      padding: 10px 12px;
      background: rgba(248,113,113,0.08);
      border-left: 3px solid var(--cull);
      border-radius: 4px;
      font-size: 12px; color: #fca5a5;
      display: none;
    }
    .stage .errors.show { display: block; }
    .stage .errors h4 { margin: 0 0 4px; font-size: 12px; color: #fca5a5; }
    .stage .errors li { margin: 2px 0 0 16px; }
    .stage .done {
      display: none;
      color: var(--keep);
      font-size: 14px; margin-top: 16px;
    }
    .stage .done.show { display: block; }
    .stage .footnote {
      margin-top: 22px; padding-top: 18px;
      border-top: 1px solid var(--border);
      font-size: 11.5px; color: var(--muted);
      line-height: 1.55;
    }
    @media (prefers-reduced-motion: reduce) {
      .stage .progress-bar { transition-duration: 0.01ms; }
      .stage .progress-bar.indeterminate { animation: none;
        background: rgba(96,165,250,0.3); }
    }
  </style>
</head>
<body>
  <main class="stage" role="status" aria-live="polite">
    <h1>正在准备 PixCull</h1>
    <div class="subtitle" id="subtitle">下载 ~2 GB 预训练模型(完成后所有功能离线可用)…</div>

    <div class="step-label" id="stepLabel">连接 Hugging Face…</div>
    <div class="progress-shell">
      <div class="progress-bar indeterminate" id="progressBar"></div>
    </div>
    <div class="meta">
      <span class="count" id="counter"></span>
      <span id="elapsed"></span>
    </div>

    <div class="errors" id="errorsBox" role="alert">
      <h4>部分模型下载失败,降级运行(影响有限)</h4>
      <ul id="errorsList"></ul>
    </div>

    <div class="done" id="doneBox">
      ✓ 准备完成 — 跳转至主界面…
    </div>

    <div class="footnote">
      首次启动需要下载 CLIP / DINOv2 / U²-Net / pyiqa,大约 5–10 分钟。<br>
      下载使用 Hugging Face 的全球 CDN — 如果速度异常慢,可以
      <kbd>Ctrl+C</kbd> 后用国内代理重启。完成后 PixCull 全离线运行。
    </div>
  </main>

  <script>
    const startedAt = Date.now();
    const stepLabel = document.getElementById("stepLabel");
    const progressBar = document.getElementById("progressBar");
    const counter = document.getElementById("counter");
    const elapsed = document.getElementById("elapsed");
    const errorsBox = document.getElementById("errorsBox");
    const errorsList = document.getElementById("errorsList");
    const doneBox = document.getElementById("doneBox");

    function fmtElapsed(ms) {
      const s = Math.round(ms / 1000);
      if (s < 60) return s + "s";
      const m = Math.floor(s / 60), r = s % 60;
      return m + "m " + (r < 10 ? "0" + r : r) + "s";
    }

    let lastPhase = null;
    async function poll() {
      try {
        const res = await fetch("/first_run_status");
        const s = await res.json();
        elapsed.textContent = fmtElapsed(Date.now() - startedAt);

        if (s.phase === "warming") {
          if (s.total > 0) {
            const pct = Math.min(100, Math.round((s.current / s.total) * 100));
            progressBar.style.width = pct + "%";
            progressBar.classList.remove("indeterminate");
            counter.textContent = `第 ${s.current} / ${s.total} 个`;
          }
          if (s.step_label) stepLabel.textContent = s.step_label;
        } else if (s.phase === "done") {
          progressBar.style.width = "100%";
          progressBar.classList.remove("indeterminate");
          counter.textContent = `完成 ${s.current} / ${s.total}`;
          stepLabel.textContent = "全部就绪";
          doneBox.classList.add("show");
          if (s.errors && s.errors.length) {
            errorsList.innerHTML = s.errors.map(
              e => "<li>" + escapeHtml(e.label) + ": " + escapeHtml(e.message) + "</li>"
            ).join("");
            errorsBox.classList.add("show");
          }
          // Give the user 1.2 s to see "✓ 准备完成", then redirect.
          if (lastPhase !== "done") {
            lastPhase = "done";
            setTimeout(() => { window.location.href = "/"; }, 1200);
          }
          return;  // stop polling
        } else if (s.phase === "skipped" || s.phase === "idle") {
          // First-run already completed (or was skipped); the
          // launcher pointed us here by mistake or we were opened
          // directly. Redirect immediately.
          window.location.href = "/";
          return;
        }
      } catch (e) {
        // Server briefly unavailable — keep trying.
        stepLabel.textContent = "重连中…";
      }
      setTimeout(poll, 1500);
    }
    function escapeHtml(s) {
      return String(s == null ? "" : s).replace(/[&<>"']/g, c => (
        {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
      ));
    }
    poll();
  </script>
</body>
</html>
"""


# V14.7 — privacy disclosure page. Linked from the admin opt-in toggle
# so the user knows EXACTLY what gets collected before flipping it on.
# Hard-coded list mirrors the redaction patterns in
# pixcull/error_reporting.py — keep them in sync if you add more.
_PRIVACY_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 隐私 / 错误上报政策</title>
  <style>
    :root {
      --bg: #0b0d10; --bg-card: #14171c; --fg: #e9ecf2;
      --muted: #a8b2c1; --accent: #3b82f6; --border: #232830;
      --keep: #4ade80; --cull: #f87171;
    }
    body {
      margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
      font: 14px/1.65 -apple-system, "SF Pro Text", Inter,
            "Segoe UI Variable", "PingFang SC", sans-serif;
      padding: 32px 24px;
    }
    main { max-width: 720px; margin: 0 auto; }
    h1 { font-size: 22px; font-weight: 600; margin: 0 0 6px; }
    .subtitle { color: var(--muted); margin-bottom: 24px; }
    h2 {
      font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--muted); font-weight: 600;
      margin: 28px 0 8px;
    }
    .card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; padding: 16px 20px; margin-bottom: 14px;
    }
    .card.good { border-left: 3px solid var(--keep); }
    .card.bad  { border-left: 3px solid var(--cull); }
    ul { padding-left: 20px; margin: 6px 0; }
    li { margin: 4px 0; }
    code {
      background: rgba(255,255,255,0.06); padding: 1px 5px;
      border-radius: 3px; font-family: ui-monospace, monospace;
      font-size: 12.5px;
    }
    .back {
      display: inline-block; margin-top: 32px;
      color: var(--accent); text-decoration: none;
    }
    .back:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <main>
    <h1>错误上报政策</h1>
    <p class="subtitle">
      默认<b>关闭</b>。开启后,只在你点 “立即提交一次错误报告”
      或者(将来)程序崩溃时才会把数据外发。每次发送什么、发到哪里都对你透明。
    </p>

    <h2>会上报的内容</h2>
    <div class="card good">
      <ul>
        <li>App 版本号</li>
        <li>操作系统类别 / 版本(如 <code>Darwin · arm64 · 24.x</code>)</li>
        <li>Python 版本</li>
        <li>最近一次 stderr 日志的<b>末尾 200 行</b>(脱敏后)</li>
      </ul>
    </div>

    <h2>脱敏规则(发送前自动应用)</h2>
    <div class="card">
      <ul>
        <li><code>/Users/&lt;name&gt;</code> → <code>/Users/&lt;redacted&gt;</code></li>
        <li><code>/home/&lt;name&gt;</code> → <code>/home/&lt;redacted&gt;</code></li>
        <li><code>C:\Users\&lt;name&gt;</code> → <code>C:\Users\&lt;redacted&gt;</code></li>
        <li><code>sk-...</code> DeepSeek / OpenAI API key → <code>sk-***</code></li>
        <li><code>Bearer &lt;token&gt;</code> → <code>Bearer ***</code></li>
        <li><code>hf_...</code> Hugging Face token → <code>hf_***</code></li>
        <li><code>AKIA...</code> AWS access key → <code>AKIA***</code></li>
        <li>邮箱地址 → <code>&lt;email&gt;</code></li>
      </ul>
    </div>

    <h2>绝不会上报</h2>
    <div class="card bad">
      <ul>
        <li>你的图片或图片路径</li>
        <li>图片字节数据</li>
        <li>License token</li>
        <li>你写的 rubric 标注 / 评注文字</li>
        <li><code>/annotation</code> 或 <code>/export</code> 的请求体</li>
      </ul>
    </div>

    <h2>上报地址</h2>
    <div class="card">
      你在管理面板里自己填一个 endpoint URL。如果留空,即便 “开启” 也只是
      dry-run(本地拼好 payload 但不发送),你能在浏览器里看到完整内容。
      <br><br>
      官方目前<b>没有共享 endpoint</b> — 这是骨架,等真正的 Sentry / PostHog
      搭建好了才会启用。
    </div>

    <h2>关闭后</h2>
    <div class="card">
      改回开关或者把 endpoint 留空都立即生效。设置存在
      <code>~/Library/Application Support/PixCull/config.json</code> 里,
      你可以直接编辑或删除。
    </div>

    <a class="back" href="/admin">← 返回管理面板</a>
  </main>
</body>
</html>
"""


# V17.0 — verticals page. Photographers seed each of 10 verticals
# (风光 / 拍鸟 / 婚纱 / cosplay / 儿童 / 宠物 / 旅拍 / 活动 / 运动 / 野生)
# with reference shots they consider "good" or "bad" so per-vertical
# eval and tuning have ground truth to work from.
_VERTICALS_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 垂类样本采集</title>
  <style>
    :root {
      --bg: #0b0d10; --bg-card: #14171c; --bg-card-hi: #1a1e25;
      --fg: #e9ecf2; --muted: #a8b2c1; --accent: #3b82f6;
      --accent-hi: #60a5fa; --border: #232830;
      --keep: #4ade80; --maybe: #d9a30c; --cull: #f87171;
      --focus-ring: rgba(96,165,250,0.55);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
      font: 14px/1.55 -apple-system, "SF Pro Text", Inter,
            "Segoe UI Variable", "PingFang SC", sans-serif;
    }
    *:focus-visible {
      outline: 2px solid var(--focus-ring); outline-offset: 2px; border-radius: 4px;
    }
    header {
      padding: 18px 28px; border-bottom: 1px solid var(--border);
      display: flex; align-items: baseline; gap: 16px;
    }
    header h1 { margin: 0; font-size: 18px; font-weight: 600; }
    header a { color: var(--muted); text-decoration: none; font-size: 13px; }
    header a:hover { color: var(--fg); }
    main { padding: 18px 28px 60px; max-width: 1080px; margin: 0 auto; }
    .intro {
      background: var(--bg-card); border-left: 3px solid var(--accent);
      border-radius: 4px; padding: 12px 16px; margin-bottom: 22px;
      font-size: 13px; color: var(--muted);
    }
    .intro b { color: var(--fg); }
    /* V17.9 — filter + sort toolbar */
    .vtoolbar {
      display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
      margin-bottom: 14px; padding: 10px 12px;
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px;
    }
    .vtabs { display: flex; gap: 4px; flex-wrap: wrap; }
    .vtab {
      background: transparent; color: var(--muted);
      border: 1px solid transparent; padding: 5px 12px;
      border-radius: 999px; font: inherit; font-size: 12px;
      cursor: pointer; transition: all 120ms;
    }
    .vtab:hover { color: var(--fg); background: rgba(255,255,255,0.04); }
    .vtab.active {
      color: var(--accent-hi); background: rgba(59,130,246,0.12);
      border-color: rgba(59,130,246,0.30);
    }
    .vsort { display: inline-flex; align-items: center; gap: 6px;
              font-size: 12px; color: var(--muted); }
    .vsort select {
      padding: 5px 8px; background: rgba(0,0,0,0.3); color: var(--fg);
      border: 1px solid var(--border); border-radius: 4px;
      font: inherit; font-size: 12px;
    }
    #vsearch {
      margin-left: auto;
      padding: 5px 12px; min-width: 200px;
      background: rgba(0,0,0,0.3); color: var(--fg);
      border: 1px solid var(--border); border-radius: 999px;
      font: inherit; font-size: 12px;
    }
    .vempty {
      text-align: center; color: var(--muted);
      padding: 40px; font-size: 13px;
    }

    .vlist {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 14px;
    }
    .vcard {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 10px; padding: 14px 14px 12px;
      transition: border-color 120ms;
      display: flex; flex-direction: column;
    }
    .vcard:hover { border-color: var(--accent); }
    .vcard .vhead {
      display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px;
    }
    .vcard .vicon { font-size: 20px; line-height: 1; }
    .vcard .vname { font-size: 14.5px; font-weight: 600; letter-spacing: -0.01em; }
    .vcard .vdesc {
      font-size: 11.5px; color: var(--muted); line-height: 1.55;
      margin-bottom: 10px;
      /* clamp to 2 lines so cards align consistently */
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .progress-shell {
      width: 100%; height: 4px; background: rgba(255,255,255,0.06);
      border-radius: 999px; overflow: hidden; margin-bottom: 6px;
    }
    .progress-bar {
      height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-hi));
      border-radius: 999px; transition: width 240ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .vstats {
      display: flex; gap: 8px; align-items: center;
      flex-wrap: wrap;
      font-size: 11px; color: var(--muted); margin-bottom: 10px;
    }
    .vstats .pill {
      background: rgba(255,255,255,0.04); border: 1px solid var(--border);
      padding: 2px 8px; border-radius: 999px; font-variant-numeric: tabular-nums;
    }
    .vstats .target-label {
      margin-left: auto;
      font-size: 10.5px; color: var(--muted);
    }
    /* V17.7 — empty-state hint shown when 0/0 samples. Subtle prompt
       so empty cards don't just look broken. */
    .empty-hint {
      font-size: 11.5px; color: var(--muted);
      padding: 8px 12px; margin-bottom: 10px;
      background: rgba(255,255,255,0.025);
      border: 1px dashed var(--border);
      border-radius: 6px;
      line-height: 1.5;
    }
    .empty-hint b { color: var(--fg); font-weight: 600; }
    .vstats .pill.good { color: var(--keep); border-color: rgba(74,222,128,0.3); }
    .vstats .pill.bad  { color: var(--cull); border-color: rgba(248,113,113,0.3); }
    /* V17.15 — counts pills are now clickable shortcuts to the
       sample drawer. Hover state reveals the affordance. */
    .vstats .pill.clickable {
      cursor: pointer;
      transition: background 120ms, transform 80ms;
    }
    .vstats .pill.clickable:hover {
      background: rgba(255,255,255,0.08);
      transform: scale(1.05);
    }
    /* V17.4 — auto-tuned indicator */
    .vstats .pill.tuned {
      color: var(--accent-hi);
      border-color: rgba(96,165,250,0.4);
      background: rgba(59,130,246,0.10);
      cursor: help;
    }
    /* V17.5 — AI phrase override pill */
    .vstats .pill.phrased {
      color: #c4b5fd;
      border-color: rgba(168,85,247,0.40);
      background: rgba(168,85,247,0.10);
      cursor: help;
    }
    /* V17.7 — two-row button layout. The previous flex:1 / 6-buttons
       single row crushed every label to single-char vertical wrap on
       320px cards. Now: primary uploads on row 1 (green/red coded),
       tool actions on row 2 (icon-led, smaller). */
    .vactions {
      display: flex; flex-direction: column; gap: 6px;
    }
    .vactions .row {
      display: flex; gap: 6px;
    }
    .vactions button {
      flex: 1; background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      color: var(--fg); padding: 6px 10px; border-radius: 5px;
      font: inherit; font-size: 12px; cursor: pointer;
      white-space: nowrap;
      display: inline-flex; align-items: center; justify-content: center;
      gap: 4px;
      transition: border-color 120ms, background 120ms, color 120ms;
    }
    .vactions button:hover {
      border-color: var(--accent); background: rgba(59,130,246,0.08);
    }
    /* Row 1 — primary action buttons. Coded green / red so the user
       immediately reads "add good / add bad" from color alone. */
    .vactions .row.primary button {
      padding: 8px 12px; font-size: 13px; font-weight: 500;
    }
    .vactions .row.primary button.good {
      background: rgba(74,222,128,0.08);
      border-color: rgba(74,222,128,0.30);
      color: var(--keep);
    }
    .vactions .row.primary button.good:hover {
      background: rgba(74,222,128,0.16);
      border-color: var(--keep);
    }
    .vactions .row.primary button.bad {
      background: rgba(248,113,113,0.06);
      border-color: rgba(248,113,113,0.25);
      color: var(--cull);
    }
    .vactions .row.primary button.bad:hover {
      background: rgba(248,113,113,0.14);
      border-color: var(--cull);
    }
    /* Row 2 — secondary tools. Icon-led, smaller. Each gets a
       distinct hover-color hint matching its function. */
    .vactions .row.secondary button {
      padding: 5px 6px; font-size: 11.5px;
      color: var(--muted);
    }
    .vactions .row.secondary button .ic {
      font-size: 13px;
    }
    .vactions .row.secondary button:hover { color: var(--fg); }
    .vactions .row.secondary button.tune:hover {
      border-color: var(--accent); color: var(--accent-hi);
    }
    .vactions .row.secondary button.llm-phrases:hover {
      border-color: #c4b5fd; color: #c4b5fd;
    }
    .vactions .row.secondary button.eval:hover {
      border-color: var(--keep); color: var(--keep);
    }
    /* V17.7 — bulk-import link styled to match secondary buttons */
    .vactions .row.secondary .bulk-link {
      flex: 1; padding: 5px 6px; font-size: 11.5px;
      color: var(--muted); background: rgba(255,255,255,0.04);
      border: 1px solid var(--border); border-radius: 5px;
      text-decoration: none; white-space: nowrap;
      display: inline-flex; align-items: center; justify-content: center;
      gap: 4px;
      transition: border-color 120ms, color 120ms;
    }
    .vactions .row.secondary .bulk-link:hover {
      border-color: var(--accent-hi); color: var(--accent-hi);
    }
    .vactions .row.secondary .bulk-link .ic { font-size: 13px; }
    /* V17.13 — Unsplash button uses Unsplash-y warm-orange accent */
    .vactions .row.secondary button.unsplash:hover {
      border-color: #f59e0b; color: #fbbf24;
    }
    /* Disabled state — when there are no samples, secondary tools
       can't do anything useful. Make that obvious. */
    .vactions button:disabled {
      opacity: 0.4; cursor: not-allowed;
    }
    .vactions button:disabled:hover {
      border-color: var(--border); background: rgba(255,255,255,0.04);
      color: var(--muted);
    }

    /* Per-vertical detail drawer (opens inside the card) */
    .vdetail {
      display: none; margin-top: 12px; padding-top: 12px;
      border-top: 1px solid var(--border);
    }
    .vdetail.show { display: block; }
    .vdetail-tabs {
      display: flex; gap: 4px; margin-bottom: 8px;
    }
    .vdetail-tabs button {
      background: transparent; color: var(--muted); border: 0;
      padding: 4px 10px; border-radius: 4px; font-size: 12px; cursor: pointer;
    }
    .vdetail-tabs button.active {
      background: rgba(255,255,255,0.08); color: var(--fg);
    }
    .drop-zone {
      border: 2px dashed var(--border); border-radius: 6px;
      padding: 14px; text-align: center; font-size: 12px; color: var(--muted);
      cursor: pointer; transition: border-color 120ms, background 120ms;
    }
    .drop-zone:hover, .drop-zone.over {
      border-color: var(--accent); background: rgba(59,130,246,0.05);
      color: var(--fg);
    }
    .sample-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
      gap: 4px; margin-top: 10px;
    }
    .sample {
      position: relative; aspect-ratio: 1/1; background: #000;
      border-radius: 4px; overflow: hidden; cursor: pointer;
    }
    .sample img {
      width: 100%; height: 100%; object-fit: cover;
    }
    .sample .rm {
      position: absolute; top: 2px; right: 2px;
      width: 18px; height: 18px; border-radius: 4px;
      background: rgba(0,0,0,0.7); color: #fff; border: 0;
      font-size: 11px; cursor: pointer; opacity: 0;
      transition: opacity 120ms;
    }
    .sample:hover .rm { opacity: 1; }
    .sample .rm:hover { background: var(--cull); }

    /* V17.4 — tune result modal */
    .tune-modal {
      position: fixed; inset: 0; background: rgba(0,0,0,0.85);
      display: none; align-items: center; justify-content: center;
      z-index: 25; padding: 20px; backdrop-filter: blur(6px);
    }
    .tune-modal.show { display: flex; }
    .tune-card {
      background: var(--bg-card); border: 1px solid var(--border-hi);
      border-radius: 12px; padding: 22px;
      max-width: 560px; width: 100%;
    }
    .tune-card h3 { margin: 0 0 12px; font-size: 16px; }
    .tune-card .compare {
      display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
      margin: 16px 0;
    }
    .tune-card .stat-card {
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      border-radius: 8px; padding: 12px;
    }
    .tune-card .stat-card.tuned { border-color: rgba(74,222,128,0.4); }
    .tune-card .stat-card .label {
      font-size: 11px; color: var(--muted); margin-bottom: 6px;
    }
    .tune-card .stat-card .f1 {
      font-size: 26px; font-weight: 600;
      font-variant-numeric: tabular-nums;
      color: var(--fg);
    }
    .tune-card .stat-card.tuned .f1 { color: var(--keep); }
    .tune-card .stat-card .row {
      font-size: 11.5px; color: var(--muted);
      margin-top: 4px; font-variant-numeric: tabular-nums;
    }
    .tune-card .deltas {
      font-size: 12px; color: var(--muted);
      margin-bottom: 14px; padding: 8px 10px;
      background: rgba(255,255,255,0.03);
      border-radius: 6px; border: 1px solid var(--border);
    }
    .tune-card .deltas b { color: var(--fg); }
    .tune-card .actions {
      display: flex; gap: 10px; justify-content: flex-end;
      margin-top: 14px;
    }
    .tune-card .actions button {
      padding: 8px 18px; font-size: 13px; border-radius: 6px;
      border: 1px solid var(--border); cursor: pointer;
      background: rgba(255,255,255,0.04); color: var(--fg);
      font: inherit;
    }
    .tune-card .actions button.primary {
      background: var(--accent); border-color: var(--accent);
      color: #fff;
    }
    .tune-card .actions button.primary:hover { opacity: 0.9; }
    .tune-card .actions button:hover { border-color: var(--accent); }

    /* V17.10 — F1 surface heatmap inside the tune modal */
    .heatmap-wrap[open] summary { color: var(--fg); }
    .heatmap-grid {
      display: grid; grid-template-columns: 36px repeat(11, 1fr);
      gap: 2px;
      font-variant-numeric: tabular-nums;
    }
    .heatmap-grid .hcorner,
    .heatmap-grid .haxis-x,
    .heatmap-grid .haxis-y {
      display: flex; align-items: center; justify-content: center;
      font-size: 9.5px; color: var(--muted); padding: 2px;
    }
    .heatmap-grid .haxis-x { font-size: 9px; }
    .heatmap-grid .haxis-y { justify-content: flex-end; padding-right: 6px; }
    .heatmap-grid .hcell {
      aspect-ratio: 1/1; min-height: 16px;
      border-radius: 2px; cursor: help;
      display: flex; align-items: center; justify-content: center;
      font-size: 9px; color: rgba(255,255,255,0.85);
      transition: transform 80ms;
    }
    .heatmap-grid .hcell:hover { transform: scale(1.15); z-index: 2;
                                   box-shadow: 0 0 0 1px var(--fg); }
    .heatmap-grid .hcell.best {
      outline: 2px solid var(--keep);
      outline-offset: -2px;
    }
    .heatmap-grid .hcell.current {
      outline: 2px dashed var(--accent);
      outline-offset: -2px;
    }
    .heatmap-axis-label {
      margin-top: 6px; font-size: 9.5px; color: var(--muted);
      text-align: center;
    }

    /* V17.1 — sample zoom overlay. Tiny lightbox-of-its-own for the
       /verticals page, doesn't share the results-page lightbox JS. */
    /* V17.11 — first-run guide overlay */
    .guide-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.78);
      display: none; align-items: center; justify-content: center;
      z-index: 30; padding: 24px; backdrop-filter: blur(8px);
    }
    .guide-overlay.show { display: flex;
      animation: guideIn 240ms cubic-bezier(0.16, 1, 0.3, 1); }
    @keyframes guideIn {
      from { opacity: 0; }
      to   { opacity: 1; }
    }
    .guide-card {
      background: var(--bg-card); border: 1px solid var(--border-hi);
      border-radius: 14px; padding: 28px 32px;
      max-width: 540px; width: 100%;
      box-shadow: 0 24px 80px rgba(0,0,0,0.6);
    }
    .guide-step {
      font-size: 11px; color: var(--accent-hi);
      text-transform: uppercase; letter-spacing: 0.08em;
      margin-bottom: 8px;
    }
    .guide-title {
      margin: 0 0 12px; font-size: 20px; font-weight: 600;
      letter-spacing: -0.01em;
    }
    .guide-body {
      font-size: 13.5px; line-height: 1.65;
      color: var(--fg); margin-bottom: 18px;
      min-height: 100px;
    }
    .guide-body b { color: var(--accent-hi); }
    .guide-body code {
      background: rgba(255,255,255,0.06);
      padding: 1px 6px; border-radius: 3px;
      font-family: ui-monospace, monospace; font-size: 12px;
    }
    .guide-progress {
      display: flex; gap: 6px; margin-bottom: 16px;
    }
    .guide-dot {
      width: 28px; height: 3px; border-radius: 999px;
      background: rgba(255,255,255,0.10);
    }
    .guide-dot.active { background: var(--accent); }
    .guide-actions {
      display: flex; gap: 10px; justify-content: flex-end;
    }
    .guide-actions button {
      padding: 8px 18px; font-size: 13px; border-radius: 6px;
      border: 1px solid var(--border); background: rgba(255,255,255,0.04);
      color: var(--fg); font: inherit; cursor: pointer;
    }
    .guide-actions button.primary {
      background: var(--accent); border-color: var(--accent); color: #fff;
    }
    .guide-actions button.primary:hover { opacity: 0.9; }

    .sample-zoom {
      position: fixed; inset: 0; background: rgba(0,0,0,0.92);
      display: none; align-items: center; justify-content: center;
      z-index: 20; padding: 24px;
      backdrop-filter: blur(6px);
    }
    .sample-zoom.show { display: flex; }
    .sample-zoom img {
      max-width: 100%; max-height: 100%; object-fit: contain;
      border-radius: 8px; box-shadow: 0 12px 40px rgba(0,0,0,0.7);
    }
    .sample-zoom .caption {
      position: absolute; bottom: 16px; left: 50%;
      transform: translateX(-50%);
      background: rgba(0,0,0,0.72); color: var(--fg);
      padding: 6px 14px; border-radius: 4px; font-size: 12px;
      max-width: 80%; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    /* V17.16 — chevron + close buttons */
    .sample-zoom .sz-nav, .sample-zoom .sz-close {
      position: absolute;
      background: rgba(0,0,0,0.55); color: #fff;
      border: 1px solid rgba(255,255,255,0.15);
      cursor: pointer; user-select: none;
      transition: background 120ms, transform 80ms;
    }
    .sample-zoom .sz-nav:hover, .sample-zoom .sz-close:hover {
      background: rgba(0,0,0,0.85); transform: scale(1.06);
    }
    .sample-zoom .sz-nav {
      top: 50%; transform: translateY(-50%);
      width: 44px; height: 60px; border-radius: 6px;
      display: flex; align-items: center; justify-content: center;
      font-size: 26px; z-index: 21;
    }
    .sample-zoom .sz-nav:hover { transform: translateY(-50%) scale(1.06); }
    .sample-zoom .sz-prev { left: 24px; }
    .sample-zoom .sz-next { right: 24px; }
    .sample-zoom .sz-close {
      top: 24px; right: 24px;
      width: 32px; height: 32px; border-radius: 6px;
      display: flex; align-items: center; justify-content: center;
      font-size: 18px;
    }
    @media (max-width: 640px) {
      .sample-zoom .sz-nav { width: 36px; height: 50px; font-size: 22px; }
      .sample-zoom .sz-prev { left: 12px; }
      .sample-zoom .sz-next { right: 12px; }
    }

    .toast-stack {
      position: fixed; bottom: 16px; right: 16px; z-index: 10;
      display: flex; flex-direction: column; gap: 6px;
    }
    .toast {
      background: var(--bg-card); color: var(--fg);
      border: 1px solid var(--border); border-left: 3px solid var(--accent);
      padding: 8px 14px; border-radius: 4px; font-size: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }
    .toast.error { border-left-color: var(--cull); }
    .toast.success { border-left-color: var(--keep); }
  </style>
</head>
<body>
  <header>
    <h1>垂类样本采集</h1>
    <a href="/">← 返回上传</a>
    <a href="/admin">管理面板 →</a>
    <a href="#" onclick="window._pcShowGuide(); return false;">📖 再看教程</a>
  </header>
  <main>
    <div class="intro">
      为下面 10 类摄影各上传一些<b>你自己拍过 / 你欣赏的样片</b>,
      标记 <span style="color:var(--keep)">👍 好片</span> 或
      <span style="color:var(--cull)">👎 该剔除</span>。
      之后 PixCull 在评分这类照片时会自动倾向你的审美 —
      建议每类各上传 20+ 张,样本越多越精准。
      <br>所有样本都<b>留在你本机</b>:
      <code>~/Library/Application Support/PixCull/verticals/</code>。
    </div>

    <!-- V17.9 — filter + sort toolbar -->
    <div class="vtoolbar" id="vtoolbar">
      <div class="vtabs" id="vtabs" role="tablist">
        <button class="vtab active" data-filter="all" role="tab">全部</button>
        <button class="vtab" data-filter="has-samples" role="tab">已有样本</button>
        <button class="vtab" data-filter="tuned" role="tab">🎯 已调参</button>
        <button class="vtab" data-filter="phrased" role="tab">✨ 有 AI 话术</button>
        <button class="vtab" data-filter="empty" role="tab">未开始</button>
      </div>
      <label class="vsort">
        <span>排序:</span>
        <select id="vsort">
          <option value="default">默认</option>
          <option value="progress-desc">进度高 → 低</option>
          <option value="progress-asc">进度低 → 高</option>
          <option value="samples-desc">样本数多 → 少</option>
          <option value="samples-asc">样本数少 → 多</option>
          <option value="zh">中文名 A-Z</option>
        </select>
      </label>
      <input type="search" id="vsearch" placeholder="搜索 (婚纱 / bird / 风光 …)">
    </div>
    <div class="vlist" id="vlist"></div>
    <div class="vempty" id="vempty" style="display:none">
      没有符合筛选条件的垂类。
    </div>
  </main>
  <div class="sample-zoom" id="sampleZoom" role="dialog" aria-modal="true">
    <button class="sz-nav sz-prev" id="szPrev"
            title="上一张 (←)" aria-label="上一张">‹</button>
    <img id="sampleZoomImg" alt="">
    <button class="sz-nav sz-next" id="szNext"
            title="下一张 (→)" aria-label="下一张">›</button>
    <button class="sz-close" id="szClose"
            title="关闭 (Esc)" aria-label="关闭">×</button>
    <div class="caption" id="sampleZoomCaption"></div>
  </div>

  <!-- V17.11 — first-run guide overlay. 3 steps, dismissable. -->
  <div class="guide-overlay" id="guideOverlay" role="dialog" aria-modal="true"
       aria-labelledby="guideTitle">
    <div class="guide-card">
      <div class="guide-step" id="guideStepCount">第 1 / 3 步</div>
      <h2 id="guideTitle" class="guide-title">为常拍的题材定制评分</h2>
      <div class="guide-body" id="guideBody"></div>
      <div class="guide-progress">
        <div class="guide-dot active"></div>
        <div class="guide-dot"></div>
        <div class="guide-dot"></div>
      </div>
      <div class="guide-actions">
        <button id="guideSkip">跳过</button>
        <button class="primary" id="guideNext">下一步</button>
      </div>
    </div>
  </div>
  <!-- V17.5 — DeepSeek phrase generation result modal -->
  <div class="tune-modal" id="llmPhrasesModal" role="dialog" aria-modal="true"
       aria-labelledby="llmPhrasesTitle">
    <div class="tune-card" style="max-width: 640px">
      <h3 id="llmPhrasesTitle">AI 专属话术生成</h3>
      <div id="llmPhrasesSubtitle" style="font-size: 12px;
              color: var(--muted); margin-bottom: 12px"></div>
      <div id="llmPhrasesBody" style="font-size: 13px; max-height: 50vh;
              overflow-y: auto; padding-right: 4px"></div>
      <div class="actions">
        <button id="llmPhrasesClose">关闭</button>
        <button id="llmPhrasesRevert" style="display: none">恢复默认话术</button>
        <button class="primary" id="llmPhrasesRegen">再生成一次</button>
      </div>
    </div>
  </div>

  <!-- V17.13 — Unsplash fetch modal: query + count + bucket -->
  <div class="tune-modal" id="unsplashModal" role="dialog" aria-modal="true"
       aria-labelledby="unsplashTitle">
    <div class="tune-card" style="max-width: 560px">
      <h3 id="unsplashTitle">从 Unsplash 拉取 CC0 参考样本</h3>
      <div style="font-size: 12px; color: var(--muted); margin-bottom: 14px;
              line-height: 1.55">
        Unsplash License 允许任意商用 / ML 训练用,
        无需署名(我们仍会保存摄影师 credit 到 sidecar)。
        免费 API 限额 50 次/小时。
      </div>
      <div style="margin-bottom: 10px">
        <label style="display: block; font-size: 11px; color: var(--muted);
                margin-bottom: 4px">搜索词</label>
        <input id="unsplashQuery" type="text"
               style="width: 100%; padding: 7px 10px;
                       background: rgba(0,0,0,0.3); color: var(--fg);
                       border: 1px solid var(--border); border-radius: 4px;
                       font: inherit; font-size: 13px;">
      </div>
      <div style="display: flex; gap: 10px; margin-bottom: 10px">
        <div style="flex: 1">
          <label style="display: block; font-size: 11px; color: var(--muted);
                  margin-bottom: 4px">朝向</label>
          <select id="unsplashOrient" style="width: 100%; padding: 7px;
                  background: rgba(0,0,0,0.3); color: var(--fg);
                  border: 1px solid var(--border); border-radius: 4px;
                  font: inherit; font-size: 13px">
            <option value="landscape">横向</option>
            <option value="portrait">竖向</option>
            <option value="squarish">方形</option>
          </select>
        </div>
        <div style="flex: 1">
          <label style="display: block; font-size: 11px; color: var(--muted);
                  margin-bottom: 4px">桶</label>
          <select id="unsplashBucket" style="width: 100%; padding: 7px;
                  background: rgba(0,0,0,0.3); color: var(--fg);
                  border: 1px solid var(--border); border-radius: 4px;
                  font: inherit; font-size: 13px">
            <option value="good">👍 好片(参考)</option>
            <option value="bad">👎 待剔除</option>
          </select>
        </div>
        <div style="width: 90px">
          <label style="display: block; font-size: 11px; color: var(--muted);
                  margin-bottom: 4px">张数</label>
          <input id="unsplashCount" type="number" value="15" min="1" max="100"
                 style="width: 100%; padding: 7px;
                         background: rgba(0,0,0,0.3); color: var(--fg);
                         border: 1px solid var(--border); border-radius: 4px;
                         font: inherit; font-size: 13px">
        </div>
      </div>
      <div id="unsplashResult" style="font-size: 12px; color: var(--muted);
              margin: 14px 0; min-height: 24px"></div>
      <div class="actions">
        <button id="unsplashClose">关闭</button>
        <button class="primary" id="unsplashFetch">拉取</button>
      </div>
    </div>
  </div>

  <!-- V17.6 — per-vertical eval report modal -->
  <div class="tune-modal" id="evalModal" role="dialog" aria-modal="true"
       aria-labelledby="evalTitle">
    <div class="tune-card" style="max-width: 720px">
      <h3 id="evalTitle">本垂类评估报告</h3>
      <div id="evalSubtitle" style="font-size: 12px;
              color: var(--muted); margin-bottom: 12px"></div>
      <div id="evalBody" style="font-size: 13px; max-height: 56vh;
              overflow-y: auto; padding-right: 4px"></div>
      <div class="actions">
        <button id="evalClose">关闭</button>
      </div>
    </div>
  </div>

  <!-- V17.4 — tune result modal -->
  <div class="tune-modal" id="tuneModal" role="dialog" aria-modal="true"
       aria-labelledby="tuneTitle">
    <div class="tune-card">
      <h3 id="tuneTitle">自动调参结果</h3>
      <div id="tuneSubtitle" class="muted" style="font-size: 12px;
              color: var(--muted); margin-bottom: 4px"></div>
      <div class="compare">
        <div class="stat-card baseline">
          <div class="label">当前 (V17.2 默认)</div>
          <div class="f1" id="tuneBaseF1">--</div>
          <div class="row" id="tuneBaseRow">--</div>
        </div>
        <div class="stat-card tuned">
          <div class="label">建议 (自动调参)</div>
          <div class="f1" id="tuneNewF1">--</div>
          <div class="row" id="tuneNewRow">--</div>
        </div>
      </div>
      <div class="deltas" id="tuneDeltas">--</div>
      <!-- V17.10 — F1 surface heatmap. Y-axis is keep_min_delta
           (-0.10 top to +0.10 bottom in 0.02 steps), X-axis is
           cull_max_delta. Cell color = F1 (red→yellow→green). The
           current "best" cell is outlined. -->
      <details class="heatmap-wrap" id="tuneHeatmapWrap"
                style="margin-top: 14px; display: none">
        <summary style="cursor: pointer; font-size: 11.5px;
                color: var(--muted); padding: 4px 0">
          📈 F1 surface — keep_min_delta × cull_max_delta
        </summary>
        <div id="tuneHeatmap" style="margin-top: 8px;
                font-size: 10px; color: var(--muted)"></div>
      </details>
      <div class="actions">
        <button id="tuneCancel">关闭</button>
        <button id="tuneRevert" style="display: none">恢复默认</button>
        <button class="primary" id="tuneApply">应用建议</button>
      </div>
    </div>
  </div>
  <div class="toast-stack" id="toastStack"></div>

  <script>
    const vlist = document.getElementById("vlist");
    const toastStack = document.getElementById("toastStack");

    function toast(message, kind = "") {
      const el = document.createElement("div");
      el.className = "toast " + kind;
      el.textContent = message;
      toastStack.appendChild(el);
      setTimeout(() => el.remove(), 3500);
    }
    const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));

    let registry = [];
    // V17.9 — filter / sort / search state.
    const viewState = {
      filter: "all", sort: "default", search: ""
    };
    async function loadRegistry() {
      const res = await fetch("/verticals.json");
      registry = await res.json();
      render();
      // V17.11 — show first-run guide once registry has loaded so
      // the user sees what verticals exist behind the overlay.
      if (typeof maybeShowGuide === "function") maybeShowGuide();
    }

    // V17.9 — apply filter + sort + search to the registry view
    function applyView(reg) {
      let out = reg.slice();
      // Filter
      if (viewState.filter === "has-samples") {
        out = out.filter(v => v.counts.total > 0);
      } else if (viewState.filter === "tuned") {
        out = out.filter(v => v.policy && v.policy.is_override);
      } else if (viewState.filter === "phrased") {
        out = out.filter(v => v.phrases && v.phrases.is_override);
      } else if (viewState.filter === "empty") {
        out = out.filter(v => v.counts.total === 0);
      }
      // Search — match against key / zh / description
      if (viewState.search.trim()) {
        const q = viewState.search.trim().toLowerCase();
        out = out.filter(v =>
          v.key.toLowerCase().includes(q)
          || v.zh.toLowerCase().includes(q)
          || (v.description||"").toLowerCase().includes(q)
        );
      }
      // Sort
      const s = viewState.sort;
      if (s === "progress-desc") out.sort((a,b) => b.progress - a.progress);
      else if (s === "progress-asc")  out.sort((a,b) => a.progress - b.progress);
      else if (s === "samples-desc")  out.sort((a,b) => b.counts.total - a.counts.total);
      else if (s === "samples-asc")   out.sort((a,b) => a.counts.total - b.counts.total);
      else if (s === "zh") out.sort((a,b) => a.zh.localeCompare(b.zh, "zh"));
      // "default" = original registry order
      return out;
    }

    // V17.1 + V17.16 — sample-zoom overlay. Click any sample tile →
    // fullscreen image. V17.16: ← / → navigate within the same
    // bucket; "12 / 55" position indicator; chevron + close buttons;
    // backdrop-click closes but image-click doesn't.
    const sampleZoom = document.getElementById("sampleZoom");
    const sampleZoomImg = document.getElementById("sampleZoomImg");
    const sampleZoomCaption = document.getElementById("sampleZoomCaption");
    const szPrev = document.getElementById("szPrev");
    const szNext = document.getElementById("szNext");
    const szClose = document.getElementById("szClose");

    let _zoomState = null;   // {samples, index, urlBuilder}

    function openSampleZoom(samples, idx, urlBuilder) {
      if (!samples || !samples.length) return;
      _zoomState = {samples, index: idx, urlBuilder};
      _paintZoom();
      sampleZoom.classList.add("show");
    }
    function _paintZoom() {
      if (!_zoomState) return;
      const {samples, index, urlBuilder} = _zoomState;
      const s = samples[index];
      sampleZoomImg.src = urlBuilder(s.filename);
      sampleZoomCaption.textContent =
        `${s.filename} · ${index + 1} / ${samples.length}`;
      // Hide chevrons when only 1 image to avoid noise
      szPrev.style.display = samples.length > 1 ? "" : "none";
      szNext.style.display = samples.length > 1 ? "" : "none";
    }
    function zoomStep(delta) {
      if (!_zoomState) return;
      const n = _zoomState.samples.length;
      _zoomState.index = (_zoomState.index + delta + n) % n;   // wrap
      _paintZoom();
    }
    function closeSampleZoom() {
      sampleZoom.classList.remove("show");
      sampleZoomImg.src = "";
      _zoomState = null;
    }

    // Wire controls
    szClose.addEventListener("click", e => { e.stopPropagation(); closeSampleZoom(); });
    szPrev.addEventListener("click", e => { e.stopPropagation(); zoomStep(-1); });
    szNext.addEventListener("click", e => { e.stopPropagation(); zoomStep(+1); });
    // V17.16 — only close on backdrop click. Click on img / nav / close
    // (handled above) doesn't bubble to here.
    sampleZoom.addEventListener("click", e => {
      if (e.target === sampleZoom) closeSampleZoom();
    });

    document.addEventListener("keydown", e => {
      if (sampleZoom.classList.contains("show")) {
        if (e.key === "Escape") { closeSampleZoom(); return; }
        if (e.key === "ArrowLeft" || e.key === "k") {
          e.preventDefault(); zoomStep(-1); return;
        }
        if (e.key === "ArrowRight" || e.key === "j") {
          e.preventDefault(); zoomStep(+1); return;
        }
      }
      if (e.key === "Escape" && tuneModal.classList.contains("show")) {
        closeTune();
      }
    });

    // V17.4 — tune flow.
    //   tuneFor(key)  → POST /verticals/tune/<key>, render result
    //   applyTune(key, result) → POST /verticals/apply_override/<key>
    //   revertTune(key) → POST /verticals/revert_override/<key>
    const tuneModal = document.getElementById("tuneModal");
    const tuneTitle = document.getElementById("tuneTitle");
    const tuneSubtitle = document.getElementById("tuneSubtitle");
    const tuneBaseF1 = document.getElementById("tuneBaseF1");
    const tuneBaseRow = document.getElementById("tuneBaseRow");
    const tuneNewF1 = document.getElementById("tuneNewF1");
    const tuneNewRow = document.getElementById("tuneNewRow");
    const tuneDeltas = document.getElementById("tuneDeltas");
    const tuneCancel = document.getElementById("tuneCancel");
    const tuneApply  = document.getElementById("tuneApply");
    const tuneRevert = document.getElementById("tuneRevert");
    let _currentTune = null;   // last result, keyed for the apply button

    function fmtPP(v) {
      if (v == null) return "0";
      const sign = v > 0 ? "+" : "";
      return sign + (v * 100).toFixed(1) + "pp";
    }

    function renderTune(key, vert, result) {
      tuneTitle.textContent = `${vert.icon}  ${vert.zh} · 自动调参结果`;
      tuneSubtitle.textContent =
        `分析了 ${result.n_samples_analyzed} 张样本(👍 ${result.n_good} · 👎 ${result.n_bad}) · `
        + `耗时 ${result.elapsed_s}s`;

      const b = result.baseline || {};
      const t = result.tuned || {};
      tuneBaseF1.textContent = (b.f1 || 0).toFixed(3);
      tuneBaseRow.textContent =
        `precision ${(b.precision || 0).toFixed(2)} · recall ${(b.recall || 0).toFixed(2)} · acc ${(b.accuracy || 0).toFixed(2)}`;
      tuneNewF1.textContent = (t.f1 || 0).toFixed(3);
      tuneNewRow.textContent =
        `precision ${(t.precision || 0).toFixed(2)} · recall ${(t.recall || 0).toFixed(2)} · acc ${(t.accuracy || 0).toFixed(2)}`;

      const dF1 = (t.f1 || 0) - (b.f1 || 0);
      const sign = dF1 >= 0 ? "+" : "";
      tuneDeltas.innerHTML =
        `keep_min_delta: <b>${fmtPP(result.baseline_delta_keep)}</b> → <b>${fmtPP(result.tuned_delta_keep)}</b>`
        + ` &nbsp;·&nbsp; cull_max_delta: <b>${fmtPP(result.baseline_delta_cull)}</b> → <b>${fmtPP(result.tuned_delta_cull)}</b>`
        + ` &nbsp;·&nbsp; F1 提升 <b style="color:${dF1 > 0 ? 'var(--keep)' : (dF1 < 0 ? 'var(--cull)' : 'var(--muted)')}">${sign}${dF1.toFixed(3)}</b>`;

      // Show "revert" button only if an override is already in effect
      tuneRevert.style.display = vert.policy && vert.policy.is_override ? "" : "none";
      // Disable apply when the suggestion would worsen things
      tuneApply.disabled = dF1 < 0;
      tuneApply.textContent = dF1 >= 0 ? "应用建议" : "建议反而变差,不应用";

      // V17.10 — F1 surface heatmap.
      renderHeatmap(result);

      _currentTune = {key, vert, result};
      tuneModal.classList.add("show");
    }

    // V17.10 — render the F1 surface as an 11×11 grid. Color scale
    // is red(0) → amber(0.5) → green(1.0). Hover any cell to see
    // the exact (Δk, Δc) → F1 / P / R / acc. Best cell outlined
    // green; current registry default outlined blue dashed.
    function renderHeatmap(result) {
      const wrap = document.getElementById("tuneHeatmapWrap");
      const grid = document.getElementById("tuneHeatmap");
      if (!wrap || !grid) return;
      const cells = result.grid || [];
      if (cells.length < 9) {   // tuner couldn't run (no samples)
        wrap.style.display = "none";
        return;
      }
      wrap.style.display = "";

      // Build the [-0.10..+0.10 step 0.02] axis.
      const axis = [];
      for (let i = 0; i < 11; i++) axis.push(Math.round((-0.10 + i * 0.02) * 100) / 100);

      // Map cells into 11×11 dict for O(1) lookup
      const byKey = {};
      let maxF1 = 0, bestKey = null;
      for (const c of cells) {
        const k = `${c.keep_delta.toFixed(2)},${c.cull_delta.toFixed(2)}`;
        byKey[k] = c;
        if (c.f1 > maxF1) { maxF1 = c.f1; bestKey = k; }
      }
      const tunedKey = `${result.tuned_delta_keep.toFixed(2)},${result.tuned_delta_cull.toFixed(2)}`;
      const baselineKey = `${result.baseline_delta_keep.toFixed(2)},${result.baseline_delta_cull.toFixed(2)}`;

      function f1Color(f1) {
        if (f1 == null) return "rgb(40,40,40)";
        // Red→Yellow→Green linear in HSL hue
        const hue = Math.max(0, Math.min(120, f1 * 120));
        const sat = 60 + f1 * 20;
        const lig = 30 + f1 * 25;
        return `hsl(${hue}, ${sat}%, ${lig}%)`;
      }

      const parts = [`<div class="heatmap-grid">`];
      // Header row: corner + cull_delta axis
      parts.push(`<div class="hcorner">Δkeep \\ Δcull</div>`);
      for (const cd of axis) {
        const sign = cd > 0 ? "+" : "";
        parts.push(`<div class="haxis-x">${sign}${(cd*100).toFixed(0)}</div>`);
      }
      // Body rows
      for (const kd of axis) {
        const sign = kd > 0 ? "+" : "";
        parts.push(`<div class="haxis-y">${sign}${(kd*100).toFixed(0)}</div>`);
        for (const cd of axis) {
          const key = `${kd.toFixed(2)},${cd.toFixed(2)}`;
          const c = byKey[key];
          if (!c) {
            parts.push(`<div class="hcell" style="background: rgba(255,255,255,0.02)"
                             title="跳过 (keep_min ≤ cull_max,非法)"></div>`);
            continue;
          }
          const isBest = key === bestKey;
          const isBaseline = key === baselineKey;
          const cls = ["hcell"];
          if (isBest) cls.push("best");
          if (isBaseline && !isBest) cls.push("current");
          const f1txt = (c.f1 * 100).toFixed(0);
          parts.push(
            `<div class="${cls.join(' ')}" style="background: ${f1Color(c.f1)}"`
            + ` title="Δk=${sign}${(kd*100).toFixed(0)}pp · Δc=${cd > 0 ? '+' : ''}${(cd*100).toFixed(0)}pp\nF1=${c.f1.toFixed(3)} · P=${c.precision.toFixed(2)} · R=${c.recall.toFixed(2)} · acc=${c.accuracy.toFixed(2)}">${f1txt}</div>`
          );
        }
      }
      parts.push(`</div>`);
      parts.push(`<div class="heatmap-axis-label">F1 = 颜色(红 0 → 绿 1) · `
        + `数字 = F1×100 · <span style="color:var(--keep)">绿框</span>=最优 · `
        + `<span style="color:var(--accent-hi)">蓝虚框</span>=V17.2 默认 · hover 看详情</div>`);
      grid.innerHTML = parts.join("");
    }

    function closeTune() {
      tuneModal.classList.remove("show");
      _currentTune = null;
    }
    tuneCancel.addEventListener("click", closeTune);
    tuneModal.addEventListener("click", e => {
      if (e.target === tuneModal) closeTune();
    });

    async function tuneFor(key, vert) {
      const v = vert || registry.find(x => x.key === key);
      if (!v) return;
      // Need at least 1 good + 1 bad
      if ((v.counts.good || 0) < 1 || (v.counts.bad || 0) < 1) {
        toast(`需要先在 ${v.zh} 中各上传至少 1 张好片 / 待剔除`, "error");
        return;
      }
      toast(`正在分析 ${v.zh} 的 ${v.counts.total} 张样本…`, "");
      try {
        const res = await fetch(`/verticals/tune/${encodeURIComponent(key)}`,
                                  {method: "POST"});
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          toast(`调参失败: ${e.error || res.status}`, "error");
          return;
        }
        const result = await res.json();
        renderTune(key, v, result);
      } catch (e) {
        toast(`调参出错: ${e}`, "error");
      }
    }

    tuneApply.addEventListener("click", async () => {
      if (!_currentTune) return;
      const {key, result} = _currentTune;
      try {
        const res = await fetch(`/verticals/apply_override/${encodeURIComponent(key)}`,
                                  {method: "POST",
                                   headers: {"Content-Type": "application/json"},
                                   body: JSON.stringify({
                                     n_good: result.n_good, n_bad: result.n_bad,
                                     base_keep_min: result.base_keep_min,
                                     base_cull_max: result.base_cull_max,
                                     baseline_delta_keep: result.baseline_delta_keep,
                                     baseline_delta_cull: result.baseline_delta_cull,
                                     baseline: result.baseline,
                                     tuned_delta_keep: result.tuned_delta_keep,
                                     tuned_delta_cull: result.tuned_delta_cull,
                                     tuned: result.tuned,
                                   })});
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          toast(`应用失败: ${e.error || res.status}`, "error");
          return;
        }
        toast("已应用,新的 keep/maybe/cull 阈值即刻生效", "success");
        closeTune();
        loadRegistry();   // refresh the 🎯 已调参 pill
      } catch (e) {
        toast(`应用出错: ${e}`, "error");
      }
    });

    tuneRevert.addEventListener("click", async () => {
      if (!_currentTune) return;
      const {key} = _currentTune;
      if (!confirm("恢复到 V17.2 默认 policy?(自动调参的 override 文件会被删除)")) return;
      try {
        const res = await fetch(`/verticals/revert_override/${encodeURIComponent(key)}`,
                                  {method: "POST"});
        if (!res.ok) {
          toast("撤销失败", "error");
          return;
        }
        toast("已恢复默认", "success");
        closeTune();
        loadRegistry();
      } catch (e) {
        toast(`撤销出错: ${e}`, "error");
      }
    });

    // ─────────────────────── V17.5 LLM phrases ──────────────────────
    const llmPhrasesModal    = document.getElementById("llmPhrasesModal");
    const llmPhrasesTitle    = document.getElementById("llmPhrasesTitle");
    const llmPhrasesSubtitle = document.getElementById("llmPhrasesSubtitle");
    const llmPhrasesBody     = document.getElementById("llmPhrasesBody");
    const llmPhrasesClose    = document.getElementById("llmPhrasesClose");
    const llmPhrasesRegen    = document.getElementById("llmPhrasesRegen");
    const llmPhrasesRevert   = document.getElementById("llmPhrasesRevert");
    let _currentLlm = null;

    document.addEventListener("keydown", e => {
      if (e.key === "Escape") {
        if (llmPhrasesModal.classList.contains("show")) closeLlm();
        if (evalModal.classList.contains("show")) closeEval();
      }
    });

    function closeLlm() {
      llmPhrasesModal.classList.remove("show");
      _currentLlm = null;
    }
    llmPhrasesClose.addEventListener("click", closeLlm);
    llmPhrasesModal.addEventListener("click", e => {
      if (e.target === llmPhrasesModal) closeLlm();
    });

    function renderLlmPhrases(vert, result) {
      llmPhrasesTitle.textContent =
        `${vert.icon}  ${vert.zh} · AI 专属话术`;
      const tokens = (result.prompt_tokens || 0)
                   + (result.completion_tokens || 0);
      llmPhrasesSubtitle.innerHTML =
        `基于 <b>${result.n_samples_seen}</b> 张好样本生成 · ` +
        `主场景 <b>${esc(result.scene_mode||'(混合)')}</b> · ` +
        `top 风格 ${(result.style_modes||[]).slice(0,3).map(esc).join(' / ') || '(无)'} · ` +
        `${tokens} tokens · ${result.elapsed_s}s`;
      const axisLabels = {
        subject:     '主体', composition: '构图',
        light:       '光线', moment:      '瞬间',
        aesthetic:   '美感', technical:   '技术',
      };
      const blocks = Object.entries(result.axes || {}).map(([axis, phrases]) => `
        <div style="margin-bottom: 14px; padding: 10px;
                background: rgba(255,255,255,0.03);
                border: 1px solid var(--border); border-radius: 6px">
          <div style="font-size: 11px; text-transform: uppercase;
                  letter-spacing: 0.05em; color: var(--muted);
                  margin-bottom: 6px;">
            ${axisLabels[axis] || axis}
          </div>
          <ul style="margin: 0; padding-left: 18px; color: var(--fg);">
            ${phrases.map(p => `<li style="line-height: 1.8">${esc(p)}</li>`).join("")}
          </ul>
        </div>
      `).join("");
      llmPhrasesBody.innerHTML = blocks
        || `<div style="color: var(--muted)">LLM 没生成有效短语,重试一次?</div>`;
      llmPhrasesRevert.style.display =
        (vert.phrases && vert.phrases.is_override) ? "" : "none";
      _currentLlm = {key: vert.key, vert, result};
      llmPhrasesModal.classList.add("show");
    }

    async function llmPhrasesFor(key) {
      const v = registry.find(x => x.key === key);
      if (!v) return;
      if ((v.counts.good || 0) < 3) {
        toast(`${v.zh} 至少需要 3 张好样本才能生成 AI 话术`, "error");
        return;
      }
      toast(`正在用 DeepSeek 分析 ${v.counts.good} 张好样本…`, "");
      try {
        const res = await fetch(
          `/verticals/llm_phrases/${encodeURIComponent(key)}`,
          {method: "POST"});
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          toast(`生成失败: ${e.error || res.status}`, "error");
          return;
        }
        const result = await res.json();
        renderLlmPhrases(v, result);
        loadRegistry();
        toast("AI 话术已应用,下次跑该垂类 batch 时生效", "success");
      } catch (e) {
        toast(`出错: ${e}`, "error");
      }
    }
    llmPhrasesRegen.addEventListener("click", () => {
      if (!_currentLlm) return;
      llmPhrasesFor(_currentLlm.key);
    });
    llmPhrasesRevert.addEventListener("click", async () => {
      if (!_currentLlm) return;
      if (!confirm("恢复 V17.3 默认 phrase 池?")) return;
      try {
        const res = await fetch(
          `/verticals/revert_phrases/${encodeURIComponent(_currentLlm.key)}`,
          {method: "POST"});
        if (res.ok) {
          toast("已恢复默认话术", "success");
          closeLlm();
          loadRegistry();
        }
      } catch (e) { toast(`撤销出错: ${e}`, "error"); }
    });

    // ─────────────────────── V17.6 eval report ──────────────────────
    const evalModal    = document.getElementById("evalModal");
    const evalTitle    = document.getElementById("evalTitle");
    const evalSubtitle = document.getElementById("evalSubtitle");
    const evalBody     = document.getElementById("evalBody");
    const evalCloseBtn = document.getElementById("evalClose");
    function closeEval() { evalModal.classList.remove("show"); }
    evalCloseBtn.addEventListener("click", closeEval);
    evalModal.addEventListener("click", e => {
      if (e.target === evalModal) closeEval();
    });

    function renderEval(report) {
      evalTitle.textContent =
        `${esc(report.vertical_icon)}  ${esc(report.vertical_zh)} · 评估报告`;
      const thr = report.thresholds_used;
      const m = report.metrics;
      const isOv = thr.is_override ? "(已应用 V17.4 自动调参 override)" : "(V17.2 默认 policy)";
      evalSubtitle.innerHTML =
        `分析了 <b>${report.n_total}</b> 张样本(👍 ${report.n_good} · 👎 ${report.n_bad}) ` +
        `· keep ≥ <b>${thr.keep_min}</b> / cull ≤ <b>${thr.cull_max}</b> ` +
        `<span style="color: var(--muted)">${esc(isOv)}</span>`;

      const confRows = ["good","bad"].map(b => {
        const c = report.confusion[b];
        const total = c.keep + c.maybe + c.cull;
        const pct = v => total ? Math.round(100 * v / total) + "%" : "0%";
        return `<tr>
          <th style="text-align: left; padding: 4px 8px">${b === "good" ? "👍 好片" : "👎 待剔除"} (${total})</th>
          <td style="padding: 4px 8px; color: var(--keep)">${c.keep} <span class="muted">${pct(c.keep)}</span></td>
          <td style="padding: 4px 8px; color: var(--maybe)">${c.maybe} <span class="muted">${pct(c.maybe)}</span></td>
          <td style="padding: 4px 8px; color: var(--cull)">${c.cull} <span class="muted">${pct(c.cull)}</span></td>
        </tr>`;
      }).join("");

      const f1Color = m.f1 >= 0.85 ? "var(--keep)" :
                       m.f1 >= 0.70 ? "var(--maybe)" : "var(--cull)";

      const fp = report.misclassified_keep || [];
      const fn = report.misclassified_cull || [];
      const renderList = (list, color) => list.length
        ? list.map(x => `<li style="line-height: 1.6">
            <code style="color: ${color}">${esc(x.filename)}</code>
            <span class="muted"> · score ${x.score} · pred <b>${esc(x.pred)}</b> · scene ${esc(x.scene||'?')} ${(x.flags||[]).length ? '· flags: ' + x.flags.map(esc).join(',') : ''}</span>
          </li>`).join("")
        : `<li style="color: var(--muted)">无</li>`;

      evalBody.innerHTML = `
        <!-- F1 banner -->
        <div style="background: rgba(255,255,255,0.04); border: 1px solid var(--border);
                border-radius: 6px; padding: 12px 16px; margin-bottom: 14px;">
          <div style="font-size: 11px; color: var(--muted); margin-bottom: 4px">F1 (positive class = "kept")</div>
          <div style="font-size: 28px; font-weight: 600; color: ${f1Color}; font-variant-numeric: tabular-nums">
            ${(m.f1 || 0).toFixed(3)}
          </div>
          <div style="font-size: 12px; color: var(--muted); margin-top: 4px;
                  font-variant-numeric: tabular-nums">
            precision <b>${(m.precision||0).toFixed(2)}</b> ·
            recall <b>${(m.recall||0).toFixed(2)}</b> ·
            accuracy <b>${(m.accuracy||0).toFixed(2)}</b> ·
            tp/fp/tn/fn <b>${m.tp}/${m.fp}/${m.tn}/${m.fn}</b>
          </div>
        </div>

        <!-- Confusion -->
        <div style="font-size: 11px; text-transform: uppercase;
                letter-spacing: 0.05em; color: var(--muted);
                margin-bottom: 6px;">混淆矩阵</div>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;
                background: var(--bg-card); border: 1px solid var(--border);
                border-radius: 6px; overflow: hidden;">
          <thead><tr style="background: rgba(255,255,255,0.04)">
            <th style="text-align: left; padding: 6px 8px">真实 \\ 预测</th>
            <th style="text-align: left; padding: 6px 8px">keep</th>
            <th style="text-align: left; padding: 6px 8px">maybe</th>
            <th style="text-align: left; padding: 6px 8px">cull</th>
          </tr></thead>
          <tbody>${confRows}</tbody>
        </table>

        <!-- Misclassified -->
        ${fp.length || fn.length ? `
          <div style="font-size: 11px; text-transform: uppercase;
                  letter-spacing: 0.05em; color: var(--muted);
                  margin-bottom: 6px;">误判样本(点击文件名可在 Finder 中查看)</div>
          ${fp.length ? `
            <div style="margin-bottom: 8px">
              <div style="color: var(--cull); font-size: 12px; margin-bottom: 4px">
                ✗ 应该 cull 但被保留 (${fp.length})
              </div>
              <ul style="margin: 0; padding-left: 18px; font-size: 11.5px">
                ${renderList(fp, 'var(--cull)')}
              </ul>
            </div>
          ` : ''}
          ${fn.length ? `
            <div>
              <div style="color: var(--keep); font-size: 12px; margin-bottom: 4px">
                ✗ 应该 keep 但被 cull (${fn.length})
              </div>
              <ul style="margin: 0; padding-left: 18px; font-size: 11.5px">
                ${renderList(fn, 'var(--keep)')}
              </ul>
            </div>
          ` : ''}
        ` : `<div style="color: var(--keep); font-size: 12px">✓ 所有样本分类正确</div>`}

        <div style="margin-top: 14px; padding-top: 10px;
                border-top: 1px solid var(--border);
                font-size: 11px; color: var(--muted)">
          score 分布:好片 ${report.score_distrib.good.score_mean} (${report.score_distrib.good.score_min}~${report.score_distrib.good.score_max}) ·
          待剔除 ${report.score_distrib.bad.score_mean} (${report.score_distrib.bad.score_min}~${report.score_distrib.bad.score_max})
        </div>
      `;
      evalModal.classList.add("show");
    }

    // V17.13 — Unsplash CC0 fetcher
    const unsplashModal    = document.getElementById("unsplashModal");
    const unsplashQuery    = document.getElementById("unsplashQuery");
    const unsplashOrient   = document.getElementById("unsplashOrient");
    const unsplashBucket   = document.getElementById("unsplashBucket");
    const unsplashCount    = document.getElementById("unsplashCount");
    const unsplashResult   = document.getElementById("unsplashResult");
    const unsplashCloseBtn = document.getElementById("unsplashClose");
    const unsplashFetchBtn = document.getElementById("unsplashFetch");
    const UNSPLASH_DEFAULTS = {
      wedding:   {query: "wedding bride groom",   orientation: "portrait"},
      bird:      {query: "bird in flight nature", orientation: "landscape"},
      wildlife:  {query: "wildlife animal nature",orientation: "landscape"},
      kids:      {query: "happy child portrait",  orientation: "portrait"},
      pet:       {query: "dog cat portrait pet",  orientation: "squarish"},
      cosplay:   {query: "cosplay anime costume", orientation: "portrait"},
      landscape: {query: "landscape mountains",   orientation: "landscape"},
      travel:    {query: "travel destination",    orientation: "landscape"},
      event:     {query: "concert event crowd",   orientation: "landscape"},
      sports:    {query: "sports action peak",    orientation: "landscape"},
    };
    let _currentUnsplashKey = null;
    function closeUnsplash() { unsplashModal.classList.remove("show"); }
    unsplashCloseBtn.addEventListener("click", closeUnsplash);
    unsplashModal.addEventListener("click", e => {
      if (e.target === unsplashModal) closeUnsplash();
    });
    function unsplashFor(key) {
      const v = registry.find(x => x.key === key);
      if (!v) return;
      _currentUnsplashKey = key;
      const d = UNSPLASH_DEFAULTS[key] || {query: key, orientation: "landscape"};
      unsplashQuery.value = d.query;
      unsplashOrient.value = d.orientation;
      unsplashBucket.value = "good";
      unsplashCount.value = "15";
      unsplashResult.innerHTML = `<span style="color:var(--muted)">点 "拉取" → Unsplash API 搜索 → 下载入桶</span>`;
      unsplashFetchBtn.disabled = false;
      document.getElementById("unsplashTitle").textContent =
        `${v.icon}  ${v.zh} · 从 Unsplash 拉取`;
      unsplashModal.classList.add("show");
      setTimeout(() => unsplashQuery.focus(), 50);
    }
    unsplashFetchBtn.addEventListener("click", async () => {
      if (!_currentUnsplashKey) return;
      const query = unsplashQuery.value.trim();
      if (!query) { toast("请输入搜索词", "error"); return; }
      const body = {
        query,
        orientation: unsplashOrient.value,
        bucket: unsplashBucket.value,
        count: parseInt(unsplashCount.value) || 15,
      };
      unsplashFetchBtn.disabled = true;
      unsplashResult.innerHTML = `<span style="color:var(--muted)">正在搜索 + 下载…(每张 1-3s,可能要等一会)</span>`;
      try {
        const res = await fetch(
          `/verticals/unsplash_fetch/${encodeURIComponent(_currentUnsplashKey)}`,
          {method: "POST",
           headers: {"Content-Type": "application/json"},
           body: JSON.stringify(body)});
        const d = await res.json();
        if (!res.ok) {
          unsplashResult.innerHTML =
            `<span style="color:var(--cull)">失败: ${esc(d.error || res.status)}</span>`;
          unsplashFetchBtn.disabled = false;
          return;
        }
        unsplashResult.innerHTML =
          `<div style="color:var(--keep)">已下载 <b>${d.saved.length}</b> 张到
            ${esc(d.bucket)} 桶 · 跳过 ${d.skipped.length}</div>
          <div style="margin-top:8px;font-size:11px;color:var(--muted)">
            当前 sample bank: 👍 ${d.counts.good} · 👎 ${d.counts.bad}<br>
            credit (示例 3 位):
            ${d.saved.slice(0,3).map(s =>
              `<a href="${esc(s.url)}" target="_blank" style="color:var(--accent-hi)">${esc(s.photographer)}</a>`
            ).join(" · ")}
          </div>`;
        loadRegistry();
        toast(`已从 Unsplash 拉取 ${d.saved.length} 张`, "success");
      } catch (e) {
        unsplashResult.innerHTML =
          `<span style="color:var(--cull)">网络错误: ${esc(e)}</span>`;
      } finally {
        unsplashFetchBtn.disabled = false;
      }
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && unsplashModal.classList.contains("show")) {
        closeUnsplash();
      }
    });

    async function evalFor(key) {
      const v = registry.find(x => x.key === key);
      if (!v) return;
      if ((v.counts.total || 0) < 1) {
        toast(`${v.zh} 没有样本可以评估`, "error");
        return;
      }
      toast(`正在评估 ${v.zh} 的 ${v.counts.total} 张样本…`, "");
      try {
        const res = await fetch(`/verticals/eval/${encodeURIComponent(key)}`,
                                  {method: "POST"});
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          toast(`评估失败: ${e.error || res.status}`, "error");
          return;
        }
        const report = await res.json();
        renderEval(report);
      } catch (e) { toast(`评估出错: ${e}`, "error"); }
    }

    function render() {
      const filtered = applyView(registry);
      const vempty = document.getElementById("vempty");
      if (!filtered.length) {
        vlist.innerHTML = "";
        if (vempty) vempty.style.display = "block";
        return;
      }
      if (vempty) vempty.style.display = "none";
      vlist.innerHTML = filtered.map(v => `
        <div class="vcard" data-key="${esc(v.key)}">
          <div class="vhead">
            <span class="vicon">${esc(v.icon)}</span>
            <span class="vname">${esc(v.zh)}</span>
          </div>
          <div class="vdesc">${esc(v.description)}</div>
          <div class="progress-shell">
            <div class="progress-bar" style="width: ${(v.progress*100).toFixed(0)}%"></div>
          </div>
          <div class="vstats">
            <span class="pill good clickable" data-bucket="good" data-key="${esc(v.key)}"
                  title="点击查看好片样本">👍 ${v.counts.good}</span>
            <span class="pill bad clickable" data-bucket="bad" data-key="${esc(v.key)}"
                  title="点击查看待剔除样本">👎 ${v.counts.bad}</span>
            ${v.policy && v.policy.is_override ?
              `<span class="pill tuned" title="已自动调参 · F1 ${(v.policy.baseline_f1||0).toFixed(2)} → ${(v.policy.tuned_f1||0).toFixed(2)}">🎯 已调参</span>`
              : ''}
            ${v.phrases && v.phrases.is_override ?
              `<span class="pill phrased" title="已生成 AI 专属话术,样本 n=${v.phrases.n_samples_seen||0}">✨ AI 话术</span>`
              : ''}
            <span class="target-label">目标各 ${v.sample_target} 张</span>
          </div>
          ${v.counts.total === 0 ? `
            <div class="empty-hint">
              先点 <b>+ 好片</b> 上传几张你欣赏的 <b>${esc(v.zh)}</b> 样片 → 自动获得专属评分
            </div>
          ` : ''}
          <div class="vactions">
            <!-- Row 1: primary upload actions, green/red coded -->
            <div class="row primary">
              <button class="good" data-key="${esc(v.key)}" data-bucket="good"
                      title="上传一张这个垂类的好片(参考样本)">
                <span class="ic">👍</span>+ 好片
              </button>
              <button class="bad" data-key="${esc(v.key)}" data-bucket="bad"
                      title="上传一张该被剔除的样本(反例)">
                <span class="ic">👎</span>+ 待剔除
              </button>
            </div>
            <!-- Row 2: secondary tools — disabled until samples exist -->
            <div class="row secondary">
              <a class="bulk-link" href="/verticals/bulk/${encodeURIComponent(v.key)}"
                 title="选个文件夹 → pipeline 自动分类 → 一键灌入 sample bank">
                <span class="ic">📥</span>批量导入
              </a>
              <button class="unsplash" data-key="${esc(v.key)}"
                      title="从 Unsplash (CC0) 拉取参考样本(婚纱/拍鸟/cosplay/儿童 这些没有第一方素材时用)">
                <span class="ic">🌐</span>Unsplash
              </button>
              <button class="tune" data-key="${esc(v.key)}"
                      title="用收集的好/坏样本自动调阈值"
                      ${(v.counts.good < 1 || v.counts.bad < 1) ? 'disabled' : ''}>
                <span class="ic">🎯</span>调参
              </button>
              <button class="llm-phrases" data-key="${esc(v.key)}"
                      title="用 DeepSeek 基于好样本生成业务话术"
                      ${v.counts.good < 3 ? 'disabled' : ''}>
                <span class="ic">✨</span>AI 话术
              </button>
              <button class="eval" data-key="${esc(v.key)}"
                      title="看当前 policy 在你样本上的 F1 / 混淆矩阵"
                      ${v.counts.total < 1 ? 'disabled' : ''}>
                <span class="ic">📊</span>报告
              </button>
              <button class="manage" data-key="${esc(v.key)}"
                      title="管理已上传的样本(查看/删除)">
                <span class="ic">⋯</span>管理
              </button>
            </div>
          </div>
          <div class="vdetail" data-key="${esc(v.key)}">
            <div class="vdetail-tabs">
              <button data-bucket="good" class="active">好片 (${v.counts.good})</button>
              <button data-bucket="bad">待剔除 (${v.counts.bad})</button>
            </div>
            <div class="drop-zone" data-key="${esc(v.key)}">
              拖拽文件到此 · 或点击选择
              <input type="file" hidden accept="image/*" multiple>
            </div>
            <div class="sample-grid"></div>
          </div>
        </div>
      `).join("");
      // Wire each card
      vlist.querySelectorAll(".vcard").forEach(card => wireCard(card));
    }

    function wireCard(card) {
      const key = card.dataset.key;
      const detail = card.querySelector(".vdetail");
      const tabs = card.querySelectorAll(".vdetail-tabs button");
      const dropZone = card.querySelector(".drop-zone");
      const fileInput = dropZone.querySelector("input[type=file]");
      const grid = card.querySelector(".sample-grid");

      let currentBucket = "good";

      function setBucket(b) {
        currentBucket = b;
        tabs.forEach(t => t.classList.toggle("active", t.dataset.bucket === b));
        loadSamples();
      }

      // V17.1 — fetch the per-bucket sample list and render thumbnails.
      // Hover ✕ deletes; click pops the full image in a lightbox.
      async function loadSamples() {
        grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 8px;
          color: var(--muted); font-size: 11px">加载中…</div>`;
        try {
          const res = await fetch(
            `/verticals/list/${encodeURIComponent(key)}/${currentBucket}`
          );
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const d = await res.json();
          // Update tab counts inline (no re-fetch of full registry)
          tabs.forEach(t => {
            const b = t.dataset.bucket;
            t.textContent = (b === "good" ? "好片 " : "待剔除 ")
              + `(${d.counts[b]})`;
            t.classList.toggle("active", b === currentBucket);
          });
          if (!d.samples.length) {
            grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 8px;
              color: var(--muted); font-size: 11px">
              空 — 拖文件到上方区域开始
            </div>`;
            return;
          }
          grid.innerHTML = d.samples.map(s => {
            const url = `/verticals/sample/${encodeURIComponent(key)}/${currentBucket}/${encodeURIComponent(s.filename)}`;
            return `
              <div class="sample" data-fn="${esc(s.filename)}">
                <img src="${url}" alt="${esc(s.filename)}" loading="lazy">
                <button class="rm" data-fn="${esc(s.filename)}"
                  title="删除这张样本">✕</button>
              </div>`;
          }).join("");
          // Wire each sample's delete + zoom
          grid.querySelectorAll(".sample").forEach(s => {
            const fn = s.dataset.fn;
            const rmBtn = s.querySelector(".rm");
            rmBtn.addEventListener("click", async (e) => {
              e.stopPropagation();
              if (!confirm("删除这张样本?(只删除你机上的样本库,不会动原图)")) return;
              try {
                const r = await fetch(
                  `/verticals/sample/${encodeURIComponent(key)}/${currentBucket}/${encodeURIComponent(fn)}`,
                  {method: "DELETE"}
                );
                if (r.ok) {
                  toast("已删除", "success");
                  loadSamples();
                  loadRegistry();   // progress bar refresh
                } else {
                  toast("删除失败", "error");
                }
              } catch (err) { toast("删除出错: " + err, "error"); }
            });
            // Click anywhere else on the tile → zoom
            // V17.16 — pass the full samples list so ← / → navigates
            // within the bucket without closing + re-opening.
            s.addEventListener("click", () => {
              const idx = d.samples.findIndex(x => x.filename === fn);
              openSampleZoom(
                d.samples, Math.max(0, idx),
                (filename) =>
                  `/verticals/sample/${encodeURIComponent(key)}/${currentBucket}/${encodeURIComponent(filename)}`
              );
            });
          });
        } catch (err) {
          grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 8px;
            color: var(--cull); font-size: 11px">加载失败: ${esc(err.message || err)}</div>`;
        }
      }

      tabs.forEach(t => {
        t.addEventListener("click", () => setBucket(t.dataset.bucket));
      });

      // V17.15 — counts pills double as drawer-shortcuts. Click the
      // 👍 N pill to see the good-bucket grid, 👎 N for bad.
      card.querySelectorAll(".vstats .pill.clickable").forEach(pill => {
        pill.addEventListener("click", () => {
          const b = pill.dataset.bucket;
          if (b) {
            setBucket(b);
            // Always show drawer on pill click (don't toggle —
            // user pressed the pill to look at samples)
            if (!detail.classList.contains("show")) {
              detail.classList.add("show");
            }
          }
        });
      });

      // Action buttons (+ 好片 / + 待剔除 / 🎯 自动调参 /
      //  ✨ AI 话术 / 📊 看报告 / 🌐 Unsplash / 管理…)
      card.querySelectorAll(".vactions button").forEach(btn => {
        btn.addEventListener("click", () => {
          // V17.4-13 — non-drawer buttons intercept first
          if (btn.classList.contains("tune")) {
            tuneFor(btn.dataset.key);
            return;
          }
          if (btn.classList.contains("llm-phrases")) {
            llmPhrasesFor(btn.dataset.key);
            return;
          }
          if (btn.classList.contains("eval")) {
            evalFor(btn.dataset.key);
            return;
          }
          if (btn.classList.contains("unsplash")) {
            unsplashFor(btn.dataset.key);
            return;
          }
          const b = btn.dataset.bucket;
          if (b) setBucket(b);
          else loadSamples();   // 管理… → just load current bucket
          detail.classList.toggle("show");
        });
      });

      // Drop zone
      dropZone.addEventListener("click", () => fileInput.click());
      ["dragenter", "dragover"].forEach(ev => {
        dropZone.addEventListener(ev, e => {
          e.preventDefault(); dropZone.classList.add("over");
        });
      });
      ["dragleave", "drop"].forEach(ev => {
        dropZone.addEventListener(ev, e => {
          e.preventDefault(); dropZone.classList.remove("over");
        });
      });
      dropZone.addEventListener("drop", e => {
        e.preventDefault();
        upload(e.dataTransfer.files);
      });
      fileInput.addEventListener("change", e => upload(e.target.files));

      async function upload(files) {
        if (!files || !files.length) return;
        const fd = new FormData();
        for (const f of files) fd.append("files", f, f.name);
        const url = `/verticals/upload/${encodeURIComponent(key)}?bucket=${currentBucket}`;
        try {
          const res = await fetch(url, {method: "POST", body: fd});
          const d = await res.json();
          if (!res.ok) {
            toast(`上传失败: ${d.error || res.status}`, "error");
            return;
          }
          toast(`已上传 ${d.saved.length} 张到 ${key} · ${currentBucket}`, "success");
          loadRegistry();   // refresh counts + progress bar
        } catch (e) {
          toast(`上传出错: ${e}`, "error");
        }
      }
    }

    // V17.11 — first-run guide. 3 steps walk the user through the
    // core flow: pick a vertical → upload reference shots →
    // benefit. Dismissable; "已看过" stored in localStorage so it
    // never returns after the user has been onboarded.
    // V17.12 — browser-side error capture. Best-effort POST to
    // /error_reports/client_event for window.onerror +
    // unhandledrejection. The server respects the V14.7 opt-in so
    // this is a no-op when error reporting is disabled. We bound
    // payloads so a runaway page can't spam huge stacks.
    (function() {
      const _seen = new Set();   // de-dup within a page life
      function _capture(payload) {
        // De-dup by message + source + lineno to avoid 100 toasts
        // when the same broken loop fires every frame.
        const key = (payload.message||"") + "|"
                  + (payload.source||"") + "|"
                  + (payload.lineno||"");
        if (_seen.has(key)) return;
        _seen.add(key);
        if (_seen.size > 20) return;   // hard cap per page
        try {
          fetch("/error_reports/client_event", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              ...payload,
              url: location.pathname,
              ua: navigator.userAgent.slice(0, 200),
            }),
            keepalive: true,   // survive page unload
          }).catch(() => {});
        } catch (e) {}
      }
      window.addEventListener("error", e => _capture({
        kind: "error",
        message: e.message || "",
        source: e.filename || "",
        lineno: e.lineno || 0,
        colno: e.colno || 0,
        stack: (e.error && e.error.stack) || "",
      }));
      window.addEventListener("unhandledrejection", e => _capture({
        kind: "unhandledrejection",
        message: String((e.reason && e.reason.message) || e.reason || ""),
        stack: (e.reason && e.reason.stack) || "",
      }));
    })();

    const GUIDE_KEY = "pixcull.verticals_guide_seen.v1";
    const GUIDE_STEPS = [
      {
        title: "为常拍的题材定制评分",
        body: `PixCull 默认有 14 类内置题材识别 — 但 <b>婚纱</b> /
          <b>拍鸟</b> / <b>儿童</b> / <b>风光</b> 这些<b>业务垂类</b>
          的评分标准非常不同。<br><br>
          这页面让你为 <b>10 个垂类</b>各上传一批参考样片(👍 好片 /
          👎 待剔除),PixCull 学完之后,你下次跑这类批次会用上
          你的审美 — 而不是我手写的"通用 sport 模板"。`
      },
      {
        title: "三个层次的\"定制\"",
        body: `每个垂类卡有 3 个工具:<br><br>
          <b>🎯 调参</b> · 用你的好/坏样本网格搜索最优 keep/cull 阈值,
            实时显示 F1 提升<br>
          <b>✨ AI 话术</b> · DeepSeek 根据你的样本生成<b>专属点评</b>,
            告别"主体占画 30%+"这种通用句<br>
          <b>📊 报告</b> · 看当前 policy 在你样本上的混淆矩阵 + 误判清单`
      },
      {
        title: "三种灌样本的方式",
        body: `<b>📥 批量导入</b> · 选一个文件夹(<code>~/摄影/某次拍摄</code>)
            → PixCull 自动分类 → 你确认后一键灌入<br>
          <b>+ 好片 / + 待剔除</b> · 手动拖拽单张<br>
          <b>跑完批次自动 promote</b> · 在主页扫描时选了垂类 + 标注过
            keep/cull,结果页有"📥 灌入 sample bank"按钮一键写入<br><br>
          所有样本都<b>留在你本机</b> · 不上云。`
      },
    ];
    let _guideIdx = 0;
    const guideOverlay = document.getElementById("guideOverlay");
    const guideStepCount = document.getElementById("guideStepCount");
    const guideTitle = document.getElementById("guideTitle");
    const guideBody = document.getElementById("guideBody");
    const guideNext = document.getElementById("guideNext");
    const guideSkip = document.getElementById("guideSkip");
    const guideDots = document.querySelectorAll(".guide-dot");
    function paintGuide() {
      const s = GUIDE_STEPS[_guideIdx];
      guideStepCount.textContent = `第 ${_guideIdx + 1} / ${GUIDE_STEPS.length} 步`;
      guideTitle.textContent = s.title;
      guideBody.innerHTML = s.body;
      guideNext.textContent = (_guideIdx === GUIDE_STEPS.length - 1)
        ? "开始使用" : "下一步";
      guideDots.forEach((d, i) => {
        d.classList.toggle("active", i <= _guideIdx);
      });
    }
    function dismissGuide() {
      guideOverlay.classList.remove("show");
      try { localStorage.setItem(GUIDE_KEY, "1"); } catch (e) {}
    }
    function maybeShowGuide() {
      try {
        if (localStorage.getItem(GUIDE_KEY)) return;
      } catch (e) {}
      _guideIdx = 0;
      paintGuide();
      guideOverlay.classList.add("show");
    }
    guideNext.addEventListener("click", () => {
      if (_guideIdx >= GUIDE_STEPS.length - 1) {
        dismissGuide();
      } else {
        _guideIdx++;
        paintGuide();
      }
    });
    guideSkip.addEventListener("click", dismissGuide);
    guideOverlay.addEventListener("click", e => {
      if (e.target === guideOverlay) dismissGuide();
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && guideOverlay.classList.contains("show")) {
        dismissGuide();
      }
    });

    // Expose a re-launcher for the header link "再看一次"
    window._pcShowGuide = () => {
      try { localStorage.removeItem(GUIDE_KEY); } catch (e) {}
      maybeShowGuide();
    };

    // V17.9 — wire filter / sort / search controls
    document.querySelectorAll(".vtab").forEach(tab => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".vtab").forEach(t =>
          t.classList.toggle("active", t === tab));
        viewState.filter = tab.dataset.filter;
        render();
      });
    });
    const vsort = document.getElementById("vsort");
    if (vsort) vsort.addEventListener("change", () => {
      viewState.sort = vsort.value;
      render();
    });
    const vsearch = document.getElementById("vsearch");
    if (vsearch) {
      let _searchTimer;
      vsearch.addEventListener("input", () => {
        clearTimeout(_searchTimer);
        _searchTimer = setTimeout(() => {
          viewState.search = vsearch.value;
          render();
        }, 150);
      });
    }

    loadRegistry();
  </script>
</body>
</html>
"""


# V17.7 — bulk-classify-from-folder UI. Placeholders __VKEY__,
# __VICON__, __VZH__ are substituted server-side per vertical.
_VERTICAL_BULK_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 批量分类 · __VZH__</title>
  <style>
    :root {
      --bg: #0b0d10; --bg-card: #14171c; --bg-card-hi: #1a1e25;
      --fg: #e9ecf2; --muted: #a8b2c1; --accent: #3b82f6;
      --accent-hi: #60a5fa; --border: #232830;
      --keep: #4ade80; --maybe: #d9a30c; --cull: #f87171;
      --focus-ring: rgba(96,165,250,0.55);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
      font: 14px/1.55 -apple-system, "SF Pro Text", Inter,
            "Segoe UI Variable", "PingFang SC", sans-serif;
    }
    *:focus-visible {
      outline: 2px solid var(--focus-ring); outline-offset: 2px; border-radius: 4px;
    }
    header {
      padding: 16px 24px; border-bottom: 1px solid var(--border);
      display: flex; align-items: baseline; gap: 16px;
    }
    header h1 { margin: 0; font-size: 17px; font-weight: 600; }
    header a { color: var(--muted); text-decoration: none; font-size: 13px; }
    header a:hover { color: var(--fg); }
    main { padding: 18px 24px 60px; max-width: 1280px; margin: 0 auto; }

    .controls {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; padding: 14px 16px; margin-bottom: 18px;
      display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    }
    .controls input[type=text] {
      flex: 1; min-width: 320px;
      padding: 8px 12px; background: rgba(0,0,0,0.3); color: var(--fg);
      border: 1px solid var(--border); border-radius: 4px;
      font: inherit; font-size: 13px;
    }
    .controls input[type=number] {
      width: 80px; padding: 8px 10px;
      background: rgba(0,0,0,0.3); color: var(--fg);
      border: 1px solid var(--border); border-radius: 4px;
      font: inherit; font-size: 13px;
    }
    .controls button {
      padding: 8px 16px; font-size: 13px; border-radius: 5px;
      border: 1px solid var(--accent); background: var(--accent);
      color: #fff; cursor: pointer; font: inherit;
    }
    .controls button.secondary {
      background: rgba(255,255,255,0.04); color: var(--fg);
      border-color: var(--border);
    }
    .controls button:disabled { opacity: 0.4; cursor: not-allowed; }

    .summary {
      display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 14px;
      font-size: 12px; color: var(--muted);
    }
    .summary .chip {
      padding: 4px 10px; border-radius: 999px;
      border: 1px solid var(--border); background: rgba(255,255,255,0.04);
      font-variant-numeric: tabular-nums;
    }
    .summary .chip.good {
      color: var(--keep); border-color: rgba(74,222,128,0.30);
    }
    .summary .chip.bad {
      color: var(--cull); border-color: rgba(248,113,113,0.25);
    }
    .summary .chip.skip { color: var(--muted); }

    .bulk-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 12px;
    }
    .bulk-card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; overflow: hidden;
      transition: border-color 120ms;
      display: flex; flex-direction: column;
    }
    .bulk-card.good   { border-color: rgba(74,222,128,0.40); }
    .bulk-card.bad    { border-color: rgba(248,113,113,0.35); }
    .bulk-card.skip   { opacity: 0.55; }
    .bulk-card .thumb-wrap {
      aspect-ratio: 1/1; background: #000; position: relative;
    }
    .bulk-card .thumb-wrap img {
      width: 100%; height: 100%; object-fit: cover;
    }
    .bulk-card .badge {
      position: absolute; top: 6px; left: 6px;
      padding: 2px 7px; border-radius: 3px; font-size: 10.5px;
      background: rgba(0,0,0,0.75); font-weight: 500;
    }
    .bulk-card .badge.keep  { color: var(--keep); }
    .bulk-card .badge.maybe { color: var(--maybe); }
    .bulk-card .badge.cull  { color: var(--cull); }
    .bulk-card .score {
      position: absolute; top: 6px; right: 6px;
      padding: 2px 7px; border-radius: 3px; font-size: 10.5px;
      background: rgba(0,0,0,0.75); color: var(--fg);
      font-variant-numeric: tabular-nums;
    }
    .bulk-card .meta {
      padding: 6px 8px; font-size: 10.5px; color: var(--muted);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .bulk-card .vote-row {
      display: flex; gap: 0; border-top: 1px solid var(--border);
    }
    .bulk-card .vote-row button {
      flex: 1; padding: 6px 0; font-size: 12px;
      background: transparent; color: var(--muted);
      border: 0; border-right: 1px solid var(--border);
      cursor: pointer; font: inherit; transition: all 120ms;
    }
    .bulk-card .vote-row button:last-child { border-right: 0; }
    .bulk-card .vote-row button:hover { background: rgba(255,255,255,0.04); }
    .bulk-card .vote-row button.active {
      color: var(--fg); font-weight: 600;
    }
    .bulk-card.good .vote-row button.active.v-good {
      background: rgba(74,222,128,0.18); color: var(--keep);
    }
    .bulk-card.bad .vote-row button.active.v-bad {
      background: rgba(248,113,113,0.18); color: var(--cull);
    }
    .bulk-card.skip .vote-row button.active.v-skip {
      background: rgba(255,255,255,0.05);
    }

    .empty {
      padding: 40px; text-align: center; color: var(--muted);
    }
    .toast-stack {
      position: fixed; bottom: 16px; right: 16px; z-index: 10;
      display: flex; flex-direction: column; gap: 6px;
    }
    .toast {
      background: var(--bg-card); color: var(--fg);
      border: 1px solid var(--border); border-left: 3px solid var(--accent);
      padding: 8px 14px; border-radius: 4px; font-size: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }
    .toast.error   { border-left-color: var(--cull); }
    .toast.success { border-left-color: var(--keep); }
  </style>
</head>
<body>
  <header>
    <h1><span style="font-size: 22px; margin-right: 6px">__VICON__</span>批量分类 · __VZH__</h1>
    <a href="/verticals">← 返回垂类</a>
  </header>
  <main>
    <div class="controls">
      <input type="text" id="folder" placeholder="例如 ~/摄影/上海赛艇公开赛 或 /Volumes/SSD/RAW">
      <label style="font-size:12px;color:var(--muted)">最多:
        <input type="number" id="limit" value="100" min="1" max="500">
      </label>
      <button id="scan">扫描 + 自动分类</button>
    </div>
    <div class="summary" id="summary" style="display:none">
      <span class="chip">共 <b id="sumTotal">0</b></span>
      <span class="chip good">👍 好片 <b id="sumGood">0</b></span>
      <span class="chip bad">👎 待剔除 <b id="sumBad">0</b></span>
      <span class="chip skip">跳过 <b id="sumSkip">0</b></span>
      <span style="margin-left: auto">
        <button class="secondary" id="setAllGood">全部 👍</button>
        <button class="secondary" id="setAllBad">全部 👎</button>
        <button class="secondary" id="setAllSkip">全部跳过</button>
        <button id="commit" style="margin-left:6px">导入 sample bank</button>
      </span>
    </div>
    <div id="grid" class="bulk-grid"></div>
    <div id="empty" class="empty" style="display:none">
      没找到可分析的图片(支持 jpg/png/cr3/cr2/nef/arw)
    </div>
  </main>
  <div class="toast-stack" id="toastStack"></div>

  <script>
    const VKEY = "__VKEY__";
    const folderEl = document.getElementById("folder");
    const limitEl  = document.getElementById("limit");
    const scanBtn  = document.getElementById("scan");
    const commitBtn = document.getElementById("commit");
    const grid = document.getElementById("grid");
    const summary = document.getElementById("summary");
    const emptyEl = document.getElementById("empty");
    const sumTotal = document.getElementById("sumTotal");
    const sumGood = document.getElementById("sumGood");
    const sumBad = document.getElementById("sumBad");
    const sumSkip = document.getElementById("sumSkip");
    const toastStack = document.getElementById("toastStack");

    const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
    function toast(message, kind="") {
      const el = document.createElement("div");
      el.className = "toast " + kind;
      el.textContent = message;
      toastStack.appendChild(el);
      setTimeout(() => el.remove(), 3500);
    }

    let items = [];   // each: {src_path, filename, score, decision, suggested, scene, styles, flags, _bucket}

    function updateSummary() {
      const g = items.filter(x => x._bucket === "good").length;
      const b = items.filter(x => x._bucket === "bad").length;
      const s = items.filter(x => x._bucket === "skip").length;
      sumTotal.textContent = items.length;
      sumGood.textContent = g;
      sumBad.textContent = b;
      sumSkip.textContent = s;
      commitBtn.disabled = !(g || b);
      commitBtn.textContent = `导入 sample bank (${g}+${b})`;
    }

    function render() {
      if (!items.length) {
        summary.style.display = "none";
        grid.innerHTML = "";
        emptyEl.style.display = "block";
        return;
      }
      emptyEl.style.display = "none";
      summary.style.display = "flex";
      grid.innerHTML = items.map((it, i) => {
        const thumbUrl = `/verticals/bulk_thumb?path=${encodeURIComponent(it.src_path)}&size=300`;
        return `
          <div class="bulk-card ${it._bucket}" data-i="${i}">
            <div class="thumb-wrap">
              <img src="${esc(thumbUrl)}" alt="${esc(it.filename)}" loading="lazy">
              <span class="badge ${it.decision}">${esc(it.decision)}</span>
              <span class="score">${it.score.toFixed(2)}</span>
            </div>
            <div class="meta" title="${esc(it.filename)}">
              ${esc(it.filename)}
            </div>
            <div class="vote-row">
              <button class="v-good ${it._bucket === 'good' ? 'active' : ''}" data-i="${i}" data-bucket="good">👍 好</button>
              <button class="v-skip ${it._bucket === 'skip' ? 'active' : ''}" data-i="${i}" data-bucket="skip">跳过</button>
              <button class="v-bad ${it._bucket === 'bad' ? 'active' : ''}" data-i="${i}" data-bucket="bad">👎 坏</button>
            </div>
          </div>`;
      }).join("");
      grid.querySelectorAll(".vote-row button").forEach(b => {
        b.addEventListener("click", () => {
          const i = parseInt(b.dataset.i);
          items[i]._bucket = b.dataset.bucket;
          render();   // re-render to update color
        });
      });
      updateSummary();
    }

    function setAll(bucket) {
      items.forEach(it => it._bucket = bucket);
      render();
    }
    document.getElementById("setAllGood").addEventListener("click", () => setAll("good"));
    document.getElementById("setAllBad").addEventListener("click", () => setAll("bad"));
    document.getElementById("setAllSkip").addEventListener("click", () => setAll("skip"));

    scanBtn.addEventListener("click", async () => {
      const folder = folderEl.value.trim();
      if (!folder) { toast("请输入文件夹路径", "error"); return; }
      const limit = parseInt(limitEl.value) || 100;
      scanBtn.disabled = true;
      scanBtn.textContent = "分析中…(每张 1-5s)";
      try {
        const res = await fetch(`/verticals/bulk_classify/${encodeURIComponent(VKEY)}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({folder, limit}),
        });
        const data = await res.json();
        if (!res.ok) {
          toast(`扫描失败: ${data.error || res.status}`, "error");
          return;
        }
        // Default _bucket to the server's suggestion
        items = (data.items || []).map(x => ({...x, _bucket: x.suggested}));
        render();
        toast(`完成 · ${data.n_total} 张已分类`, "success");
      } catch (e) {
        toast(`扫描出错: ${e}`, "error");
      } finally {
        scanBtn.disabled = false;
        scanBtn.textContent = "扫描 + 自动分类";
      }
    });

    commitBtn.addEventListener("click", async () => {
      const assigns = items
        .filter(it => it._bucket === "good" || it._bucket === "bad")
        .map(it => ({src_path: it.src_path, bucket: it._bucket}));
      if (!assigns.length) { toast("没有要导入的图片", "error"); return; }
      if (!confirm(`确认把 ${assigns.length} 张图导入 __VZH__ sample bank?`)) return;
      commitBtn.disabled = true;
      try {
        const res = await fetch(`/verticals/bulk_commit/${encodeURIComponent(VKEY)}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({assignments: assigns}),
        });
        const data = await res.json();
        if (!res.ok) {
          toast(`导入失败: ${data.error || res.status}`, "error");
          return;
        }
        toast(`导入 ${data.saved.length} 张 · 当前 sample bank: 👍 ${data.counts.good} · 👎 ${data.counts.bad}`, "success");
        if (data.skipped && data.skipped.length) {
          toast(`跳过 ${data.skipped.length} 张(详见控制台)`, "");
          console.log("skipped:", data.skipped);
        }
      } catch (e) {
        toast(`导入出错: ${e}`, "error");
      } finally {
        commitBtn.disabled = false;
        updateSummary();
      }
    });
  </script>
</body>
</html>
"""


# v0.6 (3/5) — shared design tokens.
# Single source of truth for the v0.4 P0 + v0.5 LR-grade palette
# that previously lived only inside pixcull/report/templates/
# results.html.  Interpolated into the inline <style> blocks of
# the upload page, admin page, face-audit page, and delivery-
# audit page so /, /admin, /admin/face_audit/<id>, and
# /admin/delivery/<id> all share the same visual language.
_DESIGN_TOKENS_CSS = r"""
  :root {
    /* surfaces — v0.5 LR-grade workspace gray */
    --bg:           #1a1c20;
    --bg-card:      #23262c;
    --bg-card-hi:   #2a2e35;
    --surface-2:    #2a2e35;
    --surface-3:    #34383f;
    --chrome:       #14161a;
    /* text */
    --fg:           #f1f3f7;
    --fg-2:         #c5cad4;
    --muted:        #a8b2c1;
    --muted-soft:   #7a8696;
    /* borders */
    --border:       #232830;
    --border-hi:    #2f3742;
    /* accent — indigo */
    --accent:       #6366f1;
    --accent-hi:    #818cf8;
    --accent-soft:  rgba(99,102,241,0.14);
    --accent-glow:  rgba(99,102,241,0.40);
    --focus-ring:   rgba(129,140,248,0.55);
    /* semantic palette */
    --c-success:        #34d399;
    --c-success-tint:   rgba(52,211,153,0.14);
    --c-success-border: rgba(52,211,153,0.40);
    --c-warn:           #fbbf24;
    --c-warn-tint:      rgba(251,191,36,0.14);
    --c-warn-border:    rgba(251,191,36,0.40);
    --c-danger:         #ef6363;
    --c-danger-tint:    rgba(239,99,99,0.14);
    --c-danger-border:  rgba(239,99,99,0.40);
    --c-info:           #38bdf8;
    --c-info-tint:      rgba(56,189,248,0.14);
    --c-info-border:    rgba(56,189,248,0.40);
    --c-neutral:        #a8b2c1;
    --c-neutral-tint:   rgba(168,178,193,0.10);
    --c-neutral-border: rgba(168,178,193,0.30);
    /* legacy alias for V14 callers */
    --keep:  var(--c-success);
    --maybe: var(--c-warn);
    --cull:  var(--c-danger);
    --error: var(--c-danger);
    /* typography */
    --font-display: "Inter Display", "Inter", -apple-system,
                    BlinkMacSystemFont, "Segoe UI Variable", "Segoe UI",
                    "PingFang SC", "Microsoft Yahei UI", sans-serif;
    --font-body:    "Inter", -apple-system, BlinkMacSystemFont,
                    "Segoe UI Variable", "Segoe UI", "PingFang SC",
                    "Microsoft Yahei UI", sans-serif;
    --font-mono:    ui-monospace, "SF Mono", "JetBrains Mono", Menlo,
                    monospace;
    --t-hero:    28px;  --t-h2:    18px;  --t-h3:    14px;
    --t-body:    13px;  --t-small: 11.5px; --t-tiny:  10.5px;
    --lh-tight:  1.25;  --lh-normal: 1.55; --lh-loose: 1.7;
    /* spacing */
    --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
    --space-4: 16px; --space-5: 20px; --space-6: 24px;
    --space-7: 32px; --space-8: 48px;
    /* radius */
    --radius-sm: 4px;  --radius-md: 6px;  --radius-lg: 10px;
    --radius-xl: 14px; --radius-pill: 999px;
    /* shadows */
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.30);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.40);
    --shadow-lg: 0 12px 32px rgba(0,0,0,0.50);
    --shadow-xl: 0 24px 56px rgba(0,0,0,0.55);
    /* motion */
    --duration-fast: 120ms; --duration-normal: 220ms; --duration-slow: 320ms;
    --ease-out:    cubic-bezier(0.16, 1, 0.3, 1);
    --ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
    --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  /* Light theme override — same shape as results.html */
  html[data-theme="light"] {
    --bg:           #f5f6f8;
    --bg-card:      #ffffff;
    --bg-card-hi:   #f0f2f5;
    --surface-2:    #ebedf0;
    --surface-3:    #e0e3e8;
    --chrome:       #ffffff;
    --fg:           #1a1d24;
    --fg-2:         #3c4250;
    --muted:        #5b6473;
    --muted-soft:   #8c95a3;
    --border:       #e0e3e8;
    --border-hi:    #c8cdd5;
    --accent:       #4f46e5;
    --accent-hi:    #6366f1;
    --accent-soft:  rgba(79,70,229,0.10);
    --accent-glow:  rgba(79,70,229,0.30);
    --focus-ring:   rgba(79,70,229,0.45);
    --shadow-sm: 0 1px 2px rgba(15,23,42,0.06);
    --shadow-md: 0 4px 12px rgba(15,23,42,0.08);
    --shadow-lg: 0 12px 32px rgba(15,23,42,0.10);
    --shadow-xl: 0 24px 56px rgba(15,23,42,0.12);
  }
  @media (prefers-reduced-motion: reduce) {
    :root {
      --duration-fast: 1ms; --duration-normal: 1ms; --duration-slow: 1ms;
    }
  }
"""


_UPLOAD_HTML = (r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — AI 摄影分拣</title>
  <style>
""" + _DESIGN_TOKENS_CSS + r"""
    /* v0.6 (3/5) — upload-page-specific tokens.
       The hero gradient backdrop was the V14 visual signature;
       remap it to the new --accent (indigo) color. */
    :root {
      --bg-grad: radial-gradient(1200px 600px at 50% -200px,
                 rgba(99,102,241,0.10), transparent 60%),
                 radial-gradient(900px 500px at 90% 110%,
                 rgba(99,102,241,0.05), transparent 60%);
      /* legacy button paddings kept; existing buttons reference them */
      --btn-pad-s: 4px 10px;
      --btn-pad-m: 7px 14px;
      --btn-pad-l: 10px 22px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh;
      background: var(--bg);
      background-image: var(--bg-grad);
      background-attachment: fixed;
      color: var(--fg);
      /* V14.2 — Windows-friendly system fallback chain. The old chain
         pinned to PingFang SC (macOS-only) before Yahei; Inter was
         last. Now: Inter → SF on macOS → Segoe UI Variable on Win11
         → Microsoft Yahei UI for CJK on Windows → fallbacks. */
      font: 14px/1.55 "Inter", -apple-system, BlinkMacSystemFont,
            "Segoe UI Variable", "Segoe UI", "PingFang SC",
            "Microsoft Yahei UI", "Microsoft Yahei",
            "Helvetica Neue", sans-serif;
      letter-spacing: 0.01em;
      display: flex; flex-direction: column; align-items: center;
      padding: 80px 20px 60px;
    }
    /* V14.2 — visible focus ring for keyboard users on every
       interactive element. ``focus-visible`` doesn't fire on mouse
       click, so this is invisible to mouse users (matching the
       intent: a11y for keyboard nav without aesthetic tax on
       pointer use). */
    *:focus-visible {
      outline: 2px solid var(--focus-ring);
      outline-offset: 2px;
      border-radius: var(--radius-sm);
    }
    button, input, select, a {
      /* belt-and-braces: nuke the default browser focus then let
         our :focus-visible above re-add a consistent ring */
      outline: none;
    }
    h1 {
      margin: 0 0 8px; font-size: 28px; font-weight: 700;
      letter-spacing: -0.02em;
      background: linear-gradient(180deg, #ffffff 0%, #c8d0db 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .subtitle {
      color: var(--muted); margin-bottom: 36px; max-width: 540px;
      text-align: center; font-size: 13.5px;
    }

    /* v0.4 P1 (4/4) — hero landing rules.  Replaces the single
       cramped title with a brand mark + huge hero title + value-
       prop subtitle + 3-column feature strip.  Same hero pattern
       the results page header uses, so the visual continuity
       between /upload and /results is now obvious. */
    .hero-brand {
      display: inline-flex; align-items: center; gap: 10px;
      margin-bottom: 28px;
      text-decoration: none;
      color: var(--fg);
      transition: transform 220ms cubic-bezier(0.16,1,0.3,1);
    }
    .hero-brand:hover { transform: translateY(-2px); }
    .hero-brand:hover svg { transform: rotate(-12deg); }
    .hero-brand svg { transition: transform 220ms cubic-bezier(0.34,1.56,0.64,1); }
    .hero-wordmark {
      font-size: 17px; font-weight: 700; letter-spacing: -0.02em;
      color: var(--fg);
    }
    .hero-wordmark b { color: #818cf8; font-weight: 700; }
    .hero-title {
      margin: 0 0 14px;
      font-size: 44px;
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.1;
      text-align: center;
      max-width: 720px;
      background: linear-gradient(180deg, #ffffff 0%, #aab3c1 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .hero-subtitle {
      color: var(--muted); max-width: 560px; text-align: center;
      font-size: 14px; line-height: 1.7;
      margin-bottom: 36px;
    }
    .hero-subtitle .pill {
      display: inline-flex; align-items: center;
      padding: 1px 8px; border-radius: 999px; font-size: 11px;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      margin: 0 2px;
    }
    .hero-features {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
      max-width: 720px; width: 100%;
      margin-bottom: 36px;
    }
    .hero-feature {
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 18px;
      text-align: left;
      transition: border-color 180ms ease-out,
                  background 180ms ease-out,
                  transform 180ms cubic-bezier(0.16,1,0.3,1);
    }
    .hero-feature:hover {
      border-color: #4f55e8;
      background: rgba(99,102,241,0.06);
      transform: translateY(-2px);
    }
    .hero-feature-icon {
      display: inline-flex; align-items: center; justify-content: center;
      width: 32px; height: 32px;
      border-radius: 8px;
      background: rgba(99,102,241,0.14);
      color: #818cf8;
      margin-bottom: 10px;
    }
    .hero-feature-title {
      font-size: 13px; font-weight: 600;
      color: var(--fg);
      margin-bottom: 4px;
    }
    .hero-feature-text {
      font-size: 11.5px; color: var(--muted);
      line-height: 1.55;
    }
    /* On narrow screens the 3-col strip collapses to a single column */
    @media (max-width: 640px) {
      .hero-features { grid-template-columns: 1fr; }
      .hero-title { font-size: 32px; }
    }
    .subtitle .pill {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 2px 7px; border-radius: 999px; font-size: 11px;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
    }
    .subtitle .pill.k { color: var(--keep); }
    .subtitle .pill.m { color: var(--maybe); }
    .subtitle .pill.c { color: var(--cull); }
    .card {
      width: 100%; max-width: 620px; background: var(--bg-card);
      border: 1px solid var(--border); border-radius: 14px;
      padding: 24px; box-shadow: var(--shadow-lg);
      backdrop-filter: blur(8px);
    }
    .drop-zone {
      border: 1.5px dashed var(--border-hi); border-radius: 10px;
      padding: 48px 20px; text-align: center;
      cursor: pointer;
      transition: border-color 0.18s, background 0.18s, box-shadow 0.18s;
      background: linear-gradient(180deg, rgba(255,255,255,0.015), transparent);
    }
    .drop-zone:hover, .drop-zone.dragover {
      border-color: var(--accent);
      background: linear-gradient(180deg, rgba(59,130,246,0.06), transparent);
      box-shadow: 0 0 0 4px var(--accent-glow);
    }
    .drop-zone .big {
      font-size: 32px; margin-bottom: 12px; opacity: 0.55;
      transition: opacity 0.15s;
    }
    .drop-zone:hover .big { opacity: 0.9; }
    .drop-zone .hint { color: var(--muted); font-size: 12px; margin-top: 10px; }
    .file-list {
      margin-top: 14px; max-height: 160px; overflow-y: auto;
      border-top: 1px solid var(--border);
      padding-top: 10px; font-size: 12px; color: var(--muted);
    }
    .file-list .item { padding: 2px 0; }
    .actions {
      margin-top: 16px; display: flex; gap: 10px; align-items: center;
    }
    button {
      background: linear-gradient(180deg, var(--accent-hi), var(--accent));
      color: white; border: 0; padding: 10px 22px;
      font-size: 13px; font-weight: 600; letter-spacing: 0.02em;
      border-radius: 7px; cursor: pointer;
      box-shadow: 0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px var(--accent-glow);
      transition: transform 0.06s, box-shadow 0.15s, opacity 0.15s;
    }
    button:hover { box-shadow: 0 1px 0 rgba(255,255,255,0.25) inset, 0 6px 18px var(--accent-glow); }
    button:active { transform: translateY(1px); }
    button:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
    button.secondary {
      background: transparent; color: var(--muted);
      border: 1px solid var(--border); box-shadow: none;
    }
    button.secondary:hover { color: var(--fg); border-color: var(--border-hi); }
    .status { margin-top: 18px; padding: 14px; border-radius: 6px;
              background: rgba(255,255,255,0.03); border: 1px solid var(--border);
              display: none; }
    .status.show { display: block; }
    .status .label { color: var(--muted); font-size: 11px;
                     text-transform: uppercase; letter-spacing: 0.5px;
                     margin-bottom: 6px; }
    .progress {
      height: 6px; background: rgba(255,255,255,0.04);
      border-radius: 999px; overflow: hidden; margin-top: 12px;
      border: 1px solid var(--border);
    }
    .progress-bar {
      height: 100%; width: 0%;
      background: linear-gradient(90deg, var(--accent), var(--accent-hi));
      transition: width 0.3s; border-radius: 999px;
      box-shadow: 0 0 18px var(--accent-glow);
      animation: shimmer 2s ease-in-out infinite;
    }
    @keyframes shimmer {
      0%, 100% { box-shadow: 0 0 12px var(--accent-glow); }
      50%      { box-shadow: 0 0 24px var(--accent-glow); }
    }
    .progress-bar.error {
      background: linear-gradient(90deg, #dc2626, var(--error));
      animation: none;
    }
    .progress-bar.done {
      background: linear-gradient(90deg, #10b981, var(--keep));
      animation: none;
    }
    a.results-link {
      display: inline-block; margin-top: 12px;
      color: var(--accent); text-decoration: none;
      font-weight: 500;
    }
    a.results-link:hover { text-decoration: underline; }
    /* V14.0 — Retry CTA. Stylistically secondary so it doesn't shout
       at the user — but obvious enough to discover after a failure. */
    .retry-btn {
      display: inline-block; margin-top: 12px; margin-left: 8px;
      padding: 6px 14px;
      border: 1px solid var(--border); border-radius: 6px;
      background: rgba(255,255,255,0.04); color: var(--fg);
      font-size: 13px; cursor: pointer;
      transition: background 120ms, border-color 120ms;
    }
    .retry-btn:hover {
      background: rgba(255,255,255,0.08);
      border-color: var(--border-hi);
    }
    .footer {
      margin-top: 36px; color: var(--muted); font-size: 11px;
      text-align: center; max-width: 600px; line-height: 1.6;
    }
    .footer code {
      background: rgba(255,255,255,0.06);
      padding: 1px 6px; border-radius: 3px;
    }
    /* V12.2 onboarding tour overlays */
    .tour-overlay {
      position: fixed; inset: 0; z-index: 100;
      background: rgba(0,0,0,0.7);
      display: none; align-items: center; justify-content: center;
      backdrop-filter: blur(4px);
    }
    .tour-overlay.show { display: flex; }
    .tour-card {
      background: var(--bg-card); border: 1px solid var(--border-hi);
      border-radius: 12px; padding: 28px 32px;
      width: min(520px, 92vw);
      box-shadow: 0 24px 80px rgba(0,0,0,0.7);
      position: relative;
    }
    .tour-card .step-num {
      position: absolute; top: 12px; right: 16px;
      color: var(--muted); font-size: 11px;
      font-family: ui-monospace, monospace;
    }
    .tour-card h2 {
      margin: 0 0 12px; font-size: 20px;
      background: linear-gradient(180deg, #fff, #c8d0db);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .tour-card .body {
      color: var(--fg); font-size: 14px; line-height: 1.7;
      margin-bottom: 18px;
    }
    .tour-card .body code {
      background: rgba(255,255,255,0.06); padding: 2px 7px;
      border-radius: 3px; font-size: 12px;
    }
    .tour-card .body kbd {
      display: inline-block;
      background: rgba(255,255,255,0.08); border: 1px solid var(--border-hi);
      border-bottom-width: 2px;
      padding: 1px 7px; border-radius: 4px;
      font-family: ui-monospace, monospace; font-size: 11px;
      color: var(--accent-hi);
    }
    .tour-card .actions {
      display: flex; gap: 8px; align-items: center;
      border-top: 1px solid var(--border); padding-top: 16px;
    }
    .tour-card .skip {
      background: transparent; color: var(--muted);
      border: 1px solid var(--border);
    }
    .tour-card .next {
      margin-left: auto;
    }
    .tour-card .progress-dots {
      display: flex; gap: 6px;
    }
    .tour-card .dot {
      width: 6px; height: 6px; border-radius: 50%;
      background: var(--border);
    }
    .tour-card .dot.active { background: var(--accent); }
    .tabs {
      display: flex; gap: 4px; margin-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    .tabs .tab {
      padding: 8px 12px; font-size: 12px; cursor: pointer;
      color: var(--muted); border-bottom: 2px solid transparent;
      margin-bottom: -1px; user-select: none;
    }
    .tabs .tab.active { color: var(--fg); border-bottom-color: var(--accent); }
    .tabs .tab:hover { color: var(--fg); }

    .scan-explain {
      background: rgba(59, 130, 246, 0.08);
      border-left: 3px solid var(--accent);
      padding: 10px 14px; border-radius: 4px;
      font-size: 12px; color: var(--fg); line-height: 1.6;
      margin-bottom: 14px;
    }
    .path-input { display: flex; gap: 8px; margin-bottom: 8px; }
    .path-input input {
      flex: 1; background: rgba(0,0,0,0.3); border: 1px solid var(--border);
      color: var(--fg); padding: 8px 12px; border-radius: 4px; font: inherit;
      font-family: ui-monospace, monospace; font-size: 12px;
    }
    .path-input input:focus { border-color: var(--accent); outline: none; }
    .folder-info {
      font-size: 11px; color: var(--muted); min-height: 16px;
      padding: 4px 0;
    }
    .folder-info b { color: var(--fg); }

    /* V8.3: folder browser was breaking when the listing was long
       (>15 entries) — the modal-card's max-height: 80vh combined
       with absent inner scrolling pushed header + footer offscreen.
       Lock to a fixed viewport-relative size, scroll only the body,
       sticky header + footer. */
    /* V14.4 — flip browser modal from style.display to .show class
       so it can share the modalBackdropIn / modalContentIn keyframes
       and ARIA helpers below. The legacy ``style.display=flex|none``
       call sites have been migrated to ``classList.add/remove("show")``. */
    .browser-modal {
      position: fixed; inset: 0; background: rgba(0,0,0,0.78);
      display: none; align-items: center; justify-content: center;
      z-index: 10; backdrop-filter: blur(6px);
    }
    .browser-modal.show { display: flex; animation: modalBackdropIn 160ms ease-out; }
    .browser-modal.show .browser-card {
      animation: modalContentIn 200ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    @media (prefers-reduced-motion: reduce) {
      .browser-modal.show, .browser-modal.show .browser-card {
        animation-duration: 0.01ms;
      }
    }
    .browser-card {
      background: var(--bg-card); border: 1px solid var(--border-hi);
      border-radius: 12px;
      width: min(640px, 94vw);
      height: min(78vh, 720px);
      display: flex; flex-direction: column;
      box-shadow: 0 24px 80px rgba(0,0,0,0.6);
      overflow: hidden;     /* contain the inner scroll */
    }
    .browser-header {
      display: flex; align-items: center; gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;       /* never collapse */
      background: rgba(255,255,255,0.02);
    }
    .browser-header code {
      flex: 1; min-width: 0;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      font-family: ui-monospace, monospace;
      color: var(--fg); font-size: 12px;
    }
    .browser-header .quick {
      display: flex; gap: 4px; flex-wrap: wrap;
    }
    .browser-header .quick a {
      color: var(--muted); font-size: 11px;
      padding: 3px 8px; border-radius: 4px;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      text-decoration: none; cursor: pointer; user-select: none;
    }
    .browser-header .quick a:hover {
      color: var(--fg); border-color: var(--border-hi);
    }
    .browser-header .close {
      width: 28px; height: 28px; border-radius: 6px;
      display: inline-flex; align-items: center; justify-content: center;
      cursor: pointer; user-select: none; font-size: 16px;
      color: var(--muted);
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      flex-shrink: 0;
    }
    .browser-header .close:hover {
      color: var(--fg); border-color: var(--border-hi);
    }
    /* V14.4 — at narrow widths, the breadcrumb path + quick-jump
       chips + close button compress into a tiny illegible row. Stack
       vertically with bigger tap targets (≥36 px). The quick chips
       stay flex-wrap'd so they drop to a second row instead of
       horizontally scrolling. */
    @media (max-width: 640px) {
      .browser-header {
        flex-direction: column;
        align-items: stretch;
        gap: 8px;
        padding: 12px;
      }
      .browser-header code {
        order: 1;
        font-size: 13px;
        word-break: break-all;
        white-space: normal;
        overflow: visible;
        text-overflow: clip;
      }
      .browser-header .quick {
        order: 2;
        gap: 6px;
      }
      .browser-header .quick a {
        padding: 6px 10px;
        font-size: 12px;
        min-height: 32px;
        display: inline-flex;
        align-items: center;
      }
      .browser-header .close {
        order: 0;
        align-self: flex-end;
        width: 36px; height: 36px;
        font-size: 18px;
      }
      .browser-card {
        height: 92vh;
        width: 96vw;
      }
    }
    .browser-body {
      overflow-y: auto;     /* THIS scrolls when content overflows */
      flex: 1 1 auto; min-height: 0;
      padding: 6px 0;
    }
    .browser-body::-webkit-scrollbar { width: 8px; }
    .browser-body::-webkit-scrollbar-track { background: transparent; }
    .browser-body::-webkit-scrollbar-thumb {
      background: var(--border-hi); border-radius: 4px;
    }
    .browser-body .row {
      display: flex; align-items: center; gap: 10px;
      padding: 6px 14px; cursor: pointer; user-select: none;
    }
    .browser-body .row:hover { background: rgba(255,255,255,0.05); }
    .browser-body .row.parent { color: var(--muted); }
    .browser-body .icon { width: 16px; opacity: 0.7; }
    .browser-body .name { flex: 1; min-width: 0;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .browser-body .badge {
      background: rgba(59,130,246,0.15); color: #4b9aff;
      padding: 1px 6px; font-size: 10px; border-radius: 2px;
      flex-shrink: 0;
    }
    .browser-footer {
      padding: 12px 14px; border-top: 1px solid var(--border);
      display: flex; align-items: center; gap: 10px;
      flex-shrink: 0; background: rgba(255,255,255,0.02);
    }
    .browser-footer button { padding: 6px 14px; }
  </style>
</head>
<body>
  <!-- V28.1 — active user pill in the top-right corner. Click to open
       the user-management modal. Updates from /api/v1/users/active on
       page load. Renders empty initially so the layout doesn't jump. -->
  <div id="userPill" style="position:fixed;top:14px;right:18px;z-index:50;
       padding:6px 14px;border:1px solid var(--border);border-radius:20px;
       background:var(--bg-card);color:var(--muted);font-size:11px;
       cursor:pointer;user-select:none;display:none">
    <span style="opacity:0.7">用户</span>
    <span id="userPillName" style="color:var(--fg);font-weight:500">···</span>
    <span style="opacity:0.5;margin-left:4px">▾</span>
  </div>
  <div id="userModal" style="display:none;position:fixed;inset:0;
       background:rgba(0,0,0,0.7);z-index:200;align-items:center;
       justify-content:center" onclick="if(event.target===this)closeUserModal()">
    <div style="background:var(--bg-card);border:1px solid var(--border);
         border-radius:8px;padding:24px;width:min(440px,90vw);
         box-shadow:var(--shadow-lg)">
      <h3 style="margin:0 0 14px;font-size:16px">用户配置</h3>
      <div style="color:var(--muted-soft);font-size:11px;margin-bottom:14px">
        当前活动用户: <span id="userModalActive" style="color:var(--fg)">···</span>
        <br>每个用户独立维护垂类样本桶 / 策略 / phrase 覆盖。
      </div>
      <div id="userModalList" style="margin-bottom:18px"></div>
      <div style="border-top:1px solid var(--border);padding-top:14px">
        <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
          新建用户:
        </div>
        <div style="display:flex;gap:8px">
          <input id="userCreateInput" type="text" placeholder="alice / bob ..."
            style="flex:1;background:transparent;color:var(--fg);border:1px solid var(--border);
                   border-radius:4px;padding:6px 10px;font:inherit;outline:none"
            maxlength="39">
          <button id="userCreateBtn" style="padding:6px 14px;
            background:var(--accent);color:#fff;border:none;border-radius:4px;
            font:inherit;cursor:pointer">创建</button>
        </div>
        <div id="userCreateMsg" style="font-size:10px;color:var(--muted-soft);margin-top:6px"></div>
      </div>
      <div style="border-top:1px solid var(--border);padding-top:14px;
           margin-top:14px;font-size:10px;color:var(--muted-soft);line-height:1.5">
        <b style="color:var(--fg)">V28.2:</b> 点击上面任一非当前用户的行 → 直接切换(本浏览器
        会话内,通过 cookie 标记;不需要重启服务)。<br>
        <span style="opacity:0.8">如果要 PERMANENTLY 改默认用户(全局),启动前设
        <code style="background:rgba(0,0,0,0.3);padding:1px 5px;border-radius:3px;
              font-family:ui-monospace,monospace">PIXCULL_USER=&lt;id&gt;</code></span>
      </div>
      <div style="text-align:right;margin-top:14px">
        <button onclick="closeUserModal()" style="padding:6px 14px;
          background:transparent;color:var(--muted);border:1px solid var(--border);
          border-radius:4px;font:inherit;cursor:pointer">关闭</button>
      </div>
    </div>
  </div>

  <!-- v0.4 P1 (4/4) — hero landing.
       Replaces the V14.2 single-line "PixCull" title + tagline
       with a proper product hero: brand mark, big gradient
       title, value-prop subtitle, and a 3-column "why this
       tool exists" feature strip.  Designed to read as a real
       product instead of a tool that needs context. -->
  <a href="#" class="hero-brand" aria-label="PixCull">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="1.6" stroke-linecap="round"
         stroke-linejoin="round" aria-hidden="true"
         style="width:32px;height:32px;color:#818cf8">
      <circle cx="12" cy="12" r="10"/>
      <path d="M14.31 8 20.05 17.94"/>
      <path d="M9.69 8h11.48"/>
      <path d="M7.38 12 13.12 2.06"/>
      <path d="M9.69 16 3.95 6.06"/>
      <path d="M14.31 16H2.83"/>
      <path d="M16.62 12 10.88 21.94"/>
    </svg>
    <span class="hero-wordmark">Pix<b>Cull</b></span>
  </a>

  <h1 class="hero-title">本地优先的 AI 摄影分拣</h1>
  <div class="hero-subtitle">
    6 轴 rubric · 风格感知 · Lr / C1 双向 round-trip<br>
    <span style="opacity:0.75">在你的电脑上一键评估上千张照片,自动给出
    <span class="pill k">● keep</span> ·
    <span class="pill m">● maybe</span> ·
    <span class="pill c">● cull</span>
    建议。所有计算本地完成,原图永远不离开你的硬盘。</span>
  </div>

  <div class="hero-features">
    <div class="hero-feature">
      <div class="hero-feature-icon">
        <!-- shield / lock — local privacy -->
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.8" stroke-linecap="round"
             stroke-linejoin="round" style="width:18px;height:18px">
          <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1Z"/>
          <path d="m9 12 2 2 4-4"/>
        </svg>
      </div>
      <div class="hero-feature-title">本地优先</div>
      <div class="hero-feature-text">原图不上传 · CLIP / 模型缓存本地</div>
    </div>
    <div class="hero-feature">
      <div class="hero-feature-icon">
        <!-- target — precision -->
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.8" stroke-linecap="round"
             stroke-linejoin="round" style="width:18px;height:18px">
          <circle cx="12" cy="12" r="10"/>
          <circle cx="12" cy="12" r="6"/>
          <circle cx="12" cy="12" r="2"/>
        </svg>
      </div>
      <div class="hero-feature-title">6 轴 rubric</div>
      <div class="hero-feature-text">技术 · 主体 · 构图 · 光线 · 瞬间 · 美学</div>
    </div>
    <div class="hero-feature">
      <div class="hero-feature-icon">
        <!-- workflow — round-trip -->
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.8" stroke-linecap="round"
             stroke-linejoin="round" style="width:18px;height:18px">
          <path d="M3 7v6h6"/>
          <path d="M21 17a9 9 0 0 0-15-6.7L3 13"/>
          <path d="M21 17v-6h-6"/>
          <path d="M3 7a9 9 0 0 1 15 6.7l3-2.7"/>
        </svg>
      </div>
      <div class="hero-feature-title">Lr / C1 双向</div>
      <div class="hero-feature-text">XMP / .cos sidecar 直接读写</div>
    </div>
  </div>

  <div class="card">
    <div class="tabs">
      <span class="tab active" data-tab="upload">上传模式 (复制到 /tmp)</span>
      <span class="tab" data-tab="scan">扫描本地文件夹 (零拷贝,推荐)</span>
    </div>

    <div class="tab-pane" data-pane="upload">
    <div class="drop-zone" id="dropZone">
      <div class="big" id="dropIcon">⇪</div>
      <div id="dropMain">拖拽照片到这里,或<u>点击选择</u></div>
      <div class="hint" id="dropHint">支持 JPG / PNG / RAW (CR3/CR2/NEF/ARW/DNG)</div>
    </div>
    <input id="fileInput" type="file" multiple accept=".jpg,.jpeg,.png,.cr3,.cr2,.nef,.arw,.dng,.tif,.tiff" style="display:none">
    <div class="file-list" id="fileList" style="display:none"></div>

    <div class="actions">
      <button id="uploadBtn" disabled>开始分析</button>
      <button id="clearBtn" class="secondary">清空</button>
      <!-- P-UX-21: zero-friction sample data button. Skips upload +
           model warm-up, drops the visitor straight into a /results
           view with 6 pre-scored sample images. The single biggest
           OSS-discoverability win — most visitors never make it past
           the "wait, do I need to install something first" gate. -->
      <button id="sampleBtn" class="secondary"
              title="用 6 张示例数据立刻进入 /results 体验,不需要装环境"
              style="margin-left:auto;background:rgba(59,130,246,0.15);border-color:#3b82f6;color:#a5c5ff">
        ⚡ 用示例数据立刻体验
      </button>
      <span id="hint" style="color:var(--muted);font-size:12px"></span>
    </div>
    </div>

    <div class="tab-pane" data-pane="scan" style="display:none">
      <div class="scan-explain">
        直接告诉服务器照片在哪个文件夹 — <b>不复制原图</b>,只把分析结果(scores.csv / 缩略图 / XMP)写到 /tmp。
        适合 GB 级 RAW 工作流。
      </div>
      <div class="path-input">
        <input id="folderPath" type="text" placeholder="例如 ~/Pictures/2024-shoot 或 /Volumes/SSD/RAW">
        <button id="browseBtn" class="secondary" type="button">浏览…</button>
      </div>
      <div id="folderInfo" class="folder-info"></div>
      <!-- V17.0 — vertical override. Optional. When set, the run is
           tagged with this vertical so per-vertical eval can filter
           and (V17.1+) scoring can adjust thresholds. -->
      <div class="vertical-pick" style="margin-top:10px; display:flex; align-items:center; gap:8px; flex-wrap:wrap">
        <label style="font-size:12px; color:var(--muted)">这批照片的垂类(可选):</label>
        <select id="scanVertical" style="background: rgba(0,0,0,0.3); color: var(--fg);
                  border: 1px solid var(--border); padding: 5px 10px;
                  border-radius: 4px; font: inherit; font-size: 12px;">
          <option value="">— 自动检测 —</option>
        </select>
        <a href="/verticals" style="font-size: 11px; color: var(--accent); text-decoration: none">
          管理样本库 →
        </a>
      </div>
      <div class="actions">
        <button id="scanBtn" disabled>开始分析</button>
        <span id="scanHint" style="color:var(--muted);font-size:12px"></span>
      </div>

      <!-- Folder browser modal — V8.3 with sticky header + quick jumps -->
      <div class="browser-modal" id="browserModal">
        <div class="browser-card">
          <div class="browser-header">
            <code id="browserPath" title="当前位置"></code>
            <span class="quick" id="browserQuick">
              <a data-go="~">~</a>
              <a data-go="~/Pictures">Pictures</a>
              <a data-go="~/Desktop">Desktop</a>
              <a data-go="~/Downloads">Downloads</a>
              <a data-go="/Volumes">Volumes</a>
            </span>
            <span class="close" id="browserClose" title="关闭 (Esc)">×</span>
          </div>
          <div class="browser-body" id="browserBody"></div>
          <div class="browser-footer">
            <button id="browserUseHere" type="button">用这个位置(图片在当前层级)</button>
            <span id="browserHereCount" class="muted"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="status" id="status">
      <div class="label" id="stateLabel">就绪</div>
      <div id="message">--</div>
      <div class="progress"><div class="progress-bar" id="progressBar"></div></div>
      <a class="results-link" id="resultsLink" style="display:none">查看结果 →</a>
      <!-- V14.0: explicit Retry affordance when the run errored. Hidden
           by default; pollStatus / catch-blocks reveal it. -->
      <button class="retry-btn" id="retryBtn" type="button" style="display:none">↻ 重试</button>
    </div>
  </div>

  <div class="footer">
    本地服务,所有数据存在 <code>/tmp/pixcull_demo/&lt;run_id&gt;/</code>。
    第一次跑某种照片时模型加载需 ~10 秒,后续每张约 2-10 秒。
    <span id="storageHint" style="display:none">
      已积累 <b id="storageBytes">--</b> 本地缓存 ·
      <a href="/admin">查看 / 清理 →</a>
    </span>
    <span id="storageHintEmpty">
      · <a href="/admin" style="color:var(--muted)">存储管理</a>
    </span>
    · <a href="/tether" style="color:var(--muted)" title="监听文件夹,新照片落地即刻分析">📡 Tethered live</a>
    · <a href="/history" style="color:var(--muted)" title="所有跑过的 run">🕒 历史</a>
    <span id="licenseHint" style="margin-left:8px"></span>
    · <a href="?tour=1" style="color:var(--muted)">再看一次教程</a>
  </div>

<script>
  // Background poll for storage size — only visible when there's
  // actually data to clean. Cheap, hits stdlib http.server which
  // doesn't care about an extra request every page load.
  fetch("/storage_info").then(r => r.json()).then(s => {
    if (s.runs_total_bytes > 0) {
      const mb = s.runs_total_bytes >= 1e9
        ? (s.runs_total_bytes / 1e9).toFixed(1) + " GB"
        : (s.runs_total_bytes / 1024 / 1024).toFixed(0) + " MB";
      document.getElementById("storageBytes").textContent =
        `${mb} · ${s.n_runs} 次记录`;
      document.getElementById("storageHint").style.display = "inline";
      document.getElementById("storageHintEmpty").style.display = "none";
    }
  }).catch(() => {});

  // V12.0 — license + monthly quota status badge
  fetch("/license").then(r => r.json()).then(L => {
    const el = document.getElementById("licenseHint");
    if (!el) return;
    if (L.is_pro) {
      el.innerHTML = `· <span style="color:var(--keep)">⚡ ${L.tier.toUpperCase()}</span>`;
    } else {
      const used = L.used_this_month, q = L.monthly_quota;
      const pct = q > 0 ? Math.round(100 * used / q) : 0;
      const color = pct >= 90 ? "var(--cull)" : pct >= 70 ? "var(--maybe)" : "var(--muted)";
      el.innerHTML = `· <span style="color:${color}">FREE ${used}/${q}</span> · `
        + `<a id="upgradeLink" style="color:var(--accent);cursor:pointer">升级 Pro</a>`;
      const up = document.getElementById("upgradeLink");
      if (up) up.addEventListener("click", () => {
        const tok = prompt("贴上 Pro license token (可在 https://pixcull.dev 获取):");
        if (!tok) return;
        fetch("/license", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: tok.trim() }),
        }).then(r => r.json()).then(d => {
          alert(d.ok ? d.message : ("失败: " + (d.error || "未知")));
          if (d.ok) location.reload();
        });
      });
    }
  }).catch(() => {});
</script>

<!-- V12.2 Onboarding tour overlay -->
<div class="tour-overlay" id="tourOverlay">
  <div class="tour-card">
    <span class="step-num" id="tourStep">1 / 5</span>
    <h2 id="tourTitle"></h2>
    <div class="body" id="tourBody"></div>
    <div class="actions">
      <div class="progress-dots" id="tourDots"></div>
      <button class="skip" id="tourSkip">跳过</button>
      <button class="next" id="tourNext">下一步</button>
    </div>
  </div>
</div>
<script>
// V12.2 — first-run onboarding tour. 5 steps. Skippable.
// Sets localStorage 'pixcull_tour_done' so it doesn't re-fire.
(() => {
  const STEPS = [
    {
      title: "欢迎使用 PixCull",
      body: `<p>1.3 GB 的本地 AI 摄影分拣器。30 秒带你看完核心用法。</p>
        <p style="color:var(--muted);font-size:12px">基于 Cartier-Bresson《决定性瞬间》、
        Ansel Adams Zone System、14 类摄影题材定制评分,搭配本地 VLM (Qwen3-VL) +
        DeepSeek meta-judge 的混合判断流。</p>`
    },
    {
      title: "两种导入照片的方式",
      body: `<p>顶部两个 tab:</p>
        <p>📤 <b>上传模式</b>:把照片复制到 <code>/tmp/pixcull_demo</code> 处理(适合小批量、跨机)</p>
        <p>📁 <b>扫描本地文件夹</b> ⭐:零拷贝索引,只把 score / 缩略图写到本地。
        适合 GB 级 RAW(推荐)。</p>
        <p style="color:var(--muted);font-size:12px">"浏览…" 模态顶部有 <code>~</code> /
        <code>Pictures</code> / <code>Volumes</code> 等一键跳转,外置硬盘也能直接选。</p>`
    },
    {
      title: "结果页的关键操作",
      body: `<p>分析跑完进结果页:</p>
        <p>🖱 点缩略图 → <b>大图 + 完整评分面板</b>(右侧 380px 信息栏)</p>
        <p>⌨ <kbd>j</kbd> / <kbd>k</kbd> 切换 · <kbd>1</kbd>/<kbd>2</kbd>/<kbd>3</kbd> 标 keep/maybe/cull</p>
        <p>⌨ <kbd>space</kbd> 大图 · <kbd>Cmd+Z</kbd> 撤销 · <kbd>?</kbd> 完整快捷键</p>
        <p>顶部下拉可按 <b>分数 / 时间 / 连拍聚类</b> 排序,聚类后每组有"⊞ 并排比较"按钮。</p>`
    },
    {
      title: "DeepSeek meta-judge 看不见的英雄",
      body: `<p>每张图分析后都会被 <b>4 路评分</b>:</p>
        <p>① 规则栈 (canon check list) ② V2.1 多轴回归模型 ③ 本地 Qwen3-VL 视觉</p>
        <p>④ <b>DeepSeek V4-Flash 综合</b> ⌬ — 读 ①②③ + detector 数值,产生最终判断 + 矛盾警示</p>
        <p style="color:var(--muted);font-size:12px">紫色 ⌬ 标的卡片是 meta 给出的判断;
        悬浮可看完整 rationale 和"VLM 给 5★ 但 detector 显示 subject_fraction=0.005"这种校准。</p>`
    },
    {
      title: "导出 + 学习闭环",
      body: `<p>📤 <b>下载 XMP</b> → Lightroom / Capture One 直接读 5★/3★/1★ 评级</p>
        <p>📊 <b>下载 CSV</b> → Excel/Numbers 友好</p>
        <p>🎯 <b>批量打分</b> → 输 <code>0.7,0.4</code> 自动按分数分桶</p>
        <p>🔥 <b>每标 10 张系统自动重训练个性化模型</b> — 你的判断会被学进去,越用越准。</p>
        <p style="color:var(--muted);font-size:12px;margin-top:14px">
        现在你已经掌握了 90% 的功能。开始拖照片或选文件夹 →</p>`
    },
  ];
  let cur = 0;
  const overlay = document.getElementById("tourOverlay");
  const stepEl = document.getElementById("tourStep");
  const titleEl = document.getElementById("tourTitle");
  const bodyEl = document.getElementById("tourBody");
  const nextBtn = document.getElementById("tourNext");
  const skipBtn = document.getElementById("tourSkip");
  const dotsEl = document.getElementById("tourDots");

  function paint() {
    const s = STEPS[cur];
    stepEl.textContent = `${cur + 1} / ${STEPS.length}`;
    titleEl.textContent = s.title;
    bodyEl.innerHTML = s.body;
    nextBtn.textContent = (cur === STEPS.length - 1) ? "开始使用" : "下一步";
    dotsEl.innerHTML = STEPS.map((_, i) =>
      `<span class="dot ${i === cur ? 'active' : ''}"></span>`
    ).join("");
  }
  function close() {
    overlay.classList.remove("show");
    try { localStorage.setItem("pixcull_tour_done", "1"); } catch (e) {}
  }
  nextBtn.addEventListener("click", () => {
    if (cur < STEPS.length - 1) { cur++; paint(); }
    else close();
  });
  skipBtn.addEventListener("click", close);
  // Keyboard: → next, Esc skip
  document.addEventListener("keydown", e => {
    if (!overlay.classList.contains("show")) return;
    if (e.key === "ArrowRight" || e.key === "Enter") {
      e.preventDefault(); nextBtn.click();
    } else if (e.key === "ArrowLeft") {
      if (cur > 0) { cur--; paint(); }
    } else if (e.key === "Escape") {
      e.preventDefault(); close();
    }
  });
  // Click backdrop = skip
  overlay.addEventListener("click", e => {
    if (e.target === overlay) close();
  });

  // P-UX-19 — onboarding tour is now OPT-IN. The previous behavior
  // (auto-show on first visit + modal-block the whole page) was
  // friction for the 80% of users who'd rather click around than
  // sit through a tour. New flow:
  //
  //   1. First-time visitors see a small dismissible 👋 tip pill
  //      at the bottom-right of the page. NO modal blocking.
  //   2. Click the pill → fires the full 5-step tour.
  //   3. Dismiss the pill → localStorage remembers; pill never
  //      reappears. The tour stays reachable via ?tour=1.
  //   4. Returning users see nothing extra.
  const forced = location.search.includes("tour=1");
  let done = false;
  try { done = localStorage.getItem("pixcull_tour_done") === "1"; } catch (e) {}

  if (forced) {
    paint();
    overlay.classList.add("show");
  } else if (!done) {
    // Float a small 👋 pill — non-blocking, dismissible.
    const pill = document.createElement("button");
    pill.className = "shortcuts-hint";   // reuse existing floating-pill style
    pill.style.cssText = "bottom: 60px; right: 18px; cursor: pointer; border: 0; background: rgba(59,130,246,0.92); color: white;";
    pill.type = "button";
    pill.setAttribute("aria-label", "打开新手引导");
    pill.innerHTML = "👋 30 秒看完核心用法 <span style=\"opacity:0.6;margin-left:8px;font-size:11px\">✕</span>";
    document.body.appendChild(pill);

    const dismissAndRemember = () => {
      pill.remove();
      try { localStorage.setItem("pixcull_tour_done", "1"); } catch (e) {}
    };
    pill.addEventListener("click", e => {
      // X icon (the trailing ✕) dismisses without showing the tour.
      // Anything else opens the tour AND marks dismissed.
      const rect = pill.getBoundingClientRect();
      const xZone = rect.right - 24;
      if (e.clientX >= xZone) {
        dismissAndRemember();
        return;
      }
      paint();
      overlay.classList.add("show");
      dismissAndRemember();
    });
  }
})();
</script>

<!-- V28.1 — active-user pill + modal wiring. Reads /api/v1/users to
     populate; lets the user create new profiles inline. Switching is
     env-var-based (documented in the modal); changing on-the-fly
     would need a process restart which we can't do from JS. -->
<script>
(() => {
  const pill = document.getElementById("userPill");
  const pillName = document.getElementById("userPillName");
  const modal = document.getElementById("userModal");
  const modalActive = document.getElementById("userModalActive");
  const modalList = document.getElementById("userModalList");
  const createInput = document.getElementById("userCreateInput");
  const createBtn = document.getElementById("userCreateBtn");
  const createMsg = document.getElementById("userCreateMsg");

  async function refreshUsers() {
    try {
      const r = await fetch("/api/v1/users");
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      pillName.textContent = data.active || "default";
      pill.style.display = "block";
      modalActive.textContent = data.active || "default";
      modalList.innerHTML = (data.users || []).map(u => {
        const tag = u.is_active
          ? '<span style="color:var(--keep);margin-left:6px;font-size:10px">← 当前</span>'
          : '<span style="color:var(--muted-soft);margin-left:6px;font-size:10px">点击切换</span>';
        return `<div data-uid="${u.user_id}" class="user-row"
                style="padding:8px 10px;border-radius:4px;
                ${u.is_active ? 'background:rgba(52,211,153,0.08);' : 'cursor:pointer;'}
                margin-bottom:4px;display:flex;justify-content:space-between;
                align-items:center;font-size:12px">
          <span><b>${u.user_id}</b>${tag}</span>
          <span style="color:var(--muted-soft);font-size:10px">
            ${u.vertical_count} 个垂类已填样本
          </span>
        </div>`;
      }).join("");
      // V28.2 — click a (non-active) row to switch via cookie
      modalList.querySelectorAll(".user-row").forEach(row => {
        row.addEventListener("click", async () => {
          const targetUid = row.dataset.uid;
          if (!targetUid) return;
          if (targetUid === pillName.textContent) return;  // already active
          try {
            const res = await fetch("/api/v1/users/active", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({user_id: targetUid}),
            });
            if (!res.ok) throw new Error("HTTP " + res.status);
            // V28.2: the cookie set means subsequent requests load
            // the new user. Refresh to pick up everything.
            location.reload();
          } catch (e) {
            createMsg.textContent = "切换失败: " + e.message;
          }
        });
      });
    } catch (e) {
      console.warn("userPill: refresh failed", e);
      pill.style.display = "none";
    }
  }

  pill.addEventListener("click", () => {
    refreshUsers();
    modal.style.display = "flex";
  });
  window.closeUserModal = () => { modal.style.display = "none"; };

  createBtn.addEventListener("click", async () => {
    const id = (createInput.value || "").trim();
    if (!id) {
      createMsg.textContent = "请输入 user_id";
      return;
    }
    createBtn.disabled = true;
    try {
      const r = await fetch("/api/v1/users", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({user_id: id}),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok) {
        createMsg.textContent = data.created
          ? `已创建 '${id}'。切换需要 export PIXCULL_USER=${id} + 重启。`
          : `'${id}' 已存在(无新建)。`;
        createInput.value = "";
        refreshUsers();
      } else {
        createMsg.textContent = "失败: " + (data.error || ("HTTP " + r.status));
      }
    } catch (e) {
      createMsg.textContent = "网络错误: " + e.message;
    } finally {
      createBtn.disabled = false;
    }
  });

  // Initial load
  refreshUsers();
})();
</script>

<script>
(() => {
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const fileList = document.getElementById("fileList");
  const uploadBtn = document.getElementById("uploadBtn");
  const clearBtn = document.getElementById("clearBtn");
  const hint = document.getElementById("hint");
  const statusEl = document.getElementById("status");
  const stateLabel = document.getElementById("stateLabel");
  const messageEl = document.getElementById("message");
  const progressBar = document.getElementById("progressBar");
  const resultsLink = document.getElementById("resultsLink");

  let pickedFiles = [];

  // V17.12 — browser-side error capture (same as /verticals page).
  // Best-effort POST; server respects V14.7 opt-in.
  (function() {
    const _seen = new Set();
    function _capture(payload) {
      const key = (payload.message||"") + "|" + (payload.source||"") + "|" + (payload.lineno||"");
      if (_seen.has(key)) return;
      _seen.add(key);
      if (_seen.size > 20) return;
      try {
        fetch("/error_reports/client_event", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({...payload,
            url: location.pathname,
            ua: navigator.userAgent.slice(0, 200)}),
          keepalive: true,
        }).catch(() => {});
      } catch (e) {}
    }
    window.addEventListener("error", e => _capture({
      kind: "error", message: e.message || "",
      source: e.filename || "", lineno: e.lineno || 0,
      colno: e.colno || 0,
      stack: (e.error && e.error.stack) || "",
    }));
    window.addEventListener("unhandledrejection", e => _capture({
      kind: "unhandledrejection",
      message: String((e.reason && e.reason.message) || e.reason || ""),
      stack: (e.reason && e.reason.stack) || "",
    }));
  })();

  // V14.4 — modal a11y. Each modal registered with ``registerModal``
  // gets ARIA role=dialog, aria-modal, aria-labelledby (auto-derived),
  // a Tab focus trap, and focus restore on close. Toggle visibility
  // via ``classList.add/remove("show")`` exactly like before — the
  // observer handles the ARIA/focus side reactively.
  function _modalFocusables(el) {
    return Array.from(el.querySelectorAll(
      'a[href], button, input, textarea, select, [tabindex]:not([tabindex="-1"])'
    )).filter(x => !x.disabled && x.offsetParent !== null);
  }
  function _attachTrap(el) {
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    if (!el.getAttribute("aria-labelledby")) {
      const head = el.querySelector("h1, h2, h3, .modal-title");
      if (head) {
        if (!head.id) head.id = "modal-title-" + Math.random().toString(36).slice(2, 8);
        el.setAttribute("aria-labelledby", head.id);
      }
    }
    el._previouslyFocused = document.activeElement;
    setTimeout(() => {
      const f = _modalFocusables(el);
      if (f.length) f[0].focus();
    }, 0);
    el._trapHandler = (e) => {
      if (e.key !== "Tab") return;
      const f = _modalFocusables(el);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    };
    el.addEventListener("keydown", el._trapHandler);
  }
  function _detachTrap(el) {
    if (el._trapHandler) {
      el.removeEventListener("keydown", el._trapHandler);
      el._trapHandler = null;
    }
    const prev = el._previouslyFocused;
    el._previouslyFocused = null;
    if (prev && typeof prev.focus === "function" && document.body.contains(prev)) {
      prev.focus();
    }
  }
  function registerModal(el) {
    if (!el || el._a11yWired) return;
    el._a11yWired = true;
    el._isOpen = el.classList.contains("show");
    if (el._isOpen) _attachTrap(el);
    const obs = new MutationObserver(() => {
      const open = el.classList.contains("show");
      if (open && !el._isOpen) {
        el._isOpen = true;
        _attachTrap(el);
      } else if (!open && el._isOpen) {
        el._isOpen = false;
        _detachTrap(el);
      }
    });
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
  }
  function openModal(el) {
    if (!el) return;
    registerModal(el);
    el.classList.add("show");
  }
  function closeModal(el) {
    if (!el) return;
    el.classList.remove("show");
  }

  function fmtBytes(b) {
    if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
    if (b >= 1e6) return (b / 1e6).toFixed(0) + " MB";
    return (b / 1024).toFixed(0) + " KB";
  }

  function refreshList() {
    if (!pickedFiles.length) {
      fileList.style.display = "none";
      uploadBtn.disabled = true;
      hint.textContent = "";
      return;
    }
    fileList.style.display = "block";
    fileList.innerHTML = pickedFiles.map(f =>
      `<div class="item">• ${f.name} <span style="opacity:0.5">(${fmtBytes(f.size)})</span></div>`
    ).join("");
    uploadBtn.disabled = false;
    const total = pickedFiles.reduce((s, f) => s + f.size, 0);
    let warn = "";
    if (total > 1.5e9) {
      warn = ` <span style="color:var(--maybe)">· 较大,上传会慢</span>`;
    }
    hint.innerHTML = `${pickedFiles.length} 张 · 共 ${fmtBytes(total)}${warn}`;
  }

  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", e => {
    pickedFiles = pickedFiles.concat(Array.from(e.target.files));
    refreshList();
    fileInput.value = "";
  });

  // V14.2 — live drag feedback. We can read e.dataTransfer.items
  // count during dragover (the actual File objects are sealed until
  // drop) so the user gets "丢下 N 张" instead of just a glow.
  const dropMain = document.getElementById("dropMain");
  const dropHint = document.getElementById("dropHint");
  const dropIcon = document.getElementById("dropIcon");
  const _dropDefaults = {
    main: dropMain.innerHTML,
    hint: dropHint.innerHTML,
    icon: dropIcon.innerHTML,
  };
  ["dragenter", "dragover"].forEach(ev =>
    dropZone.addEventListener(ev, e => {
      e.preventDefault(); dropZone.classList.add("dragover");
      // dataTransfer.items is the live count even during drag
      const n = e.dataTransfer && e.dataTransfer.items
        ? Array.from(e.dataTransfer.items).filter(i => i.kind === "file").length
        : 0;
      if (n > 0) {
        dropIcon.innerHTML = "⤓";
        dropMain.innerHTML = `松开以加入 <b>${n}</b> 张图片`;
        dropHint.innerHTML = `已选 ${pickedFiles.length} · 加上将共 ${pickedFiles.length + n} 张`;
      }
    })
  );
  ["dragleave", "drop"].forEach(ev =>
    dropZone.addEventListener(ev, e => {
      e.preventDefault(); dropZone.classList.remove("dragover");
      dropMain.innerHTML = _dropDefaults.main;
      dropHint.innerHTML = _dropDefaults.hint;
      dropIcon.innerHTML = _dropDefaults.icon;
    })
  );
  dropZone.addEventListener("drop", e => {
    pickedFiles = pickedFiles.concat(Array.from(e.dataTransfer.files));
    refreshList();
  });

  clearBtn.addEventListener("click", () => {
    pickedFiles = [];
    refreshList();
    statusEl.classList.remove("show");
  });

  // ---------------------- Tab switching --------------------------------
  document.querySelectorAll(".tab").forEach(t => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
      const which = t.dataset.tab;
      document.querySelectorAll(".tab-pane").forEach(p => {
        p.style.display = p.dataset.pane === which ? "" : "none";
      });
      statusEl.classList.remove("show");
    });
  });

  // ---------------------- Scan local folder ----------------------------
  const folderPath = document.getElementById("folderPath");
  const scanBtn = document.getElementById("scanBtn");
  const folderInfo = document.getElementById("folderInfo");
  const scanHint = document.getElementById("scanHint");
  const browseBtn = document.getElementById("browseBtn");

  // V17.0 — populate the vertical dropdown from /verticals.json on
  // page load. Falls back to a no-op if the registry is unreachable
  // (then the user's choice is just ``""`` = auto-detect).
  (async () => {
    const sel = document.getElementById("scanVertical");
    if (!sel) return;
    try {
      const res = await fetch("/verticals.json");
      if (!res.ok) return;
      const reg = await res.json();
      for (const v of reg) {
        const opt = document.createElement("option");
        opt.value = v.key;
        opt.textContent = `${v.icon}  ${v.zh}`;
        sel.appendChild(opt);
      }
    } catch (_) { /* offline → auto-detect default fine */ }
  })();

  let lastFolderCheck = "";
  async function inspectFolder() {
    const p = folderPath.value.trim();
    if (!p) {
      folderInfo.textContent = "";
      scanBtn.disabled = true;
      lastFolderCheck = "";
      return;
    }
    if (p === lastFolderCheck) return;
    lastFolderCheck = p;
    folderInfo.textContent = "检查中…";
    try {
      const res = await fetch("/browse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: p }),
      });
      const data = await res.json();
      if (!res.ok) {
        folderInfo.textContent = data.error || "路径无效";
        scanBtn.disabled = true;
        return;
      }
      const subN = data.entries.filter(e => e.n_images > 0).length;
      folderInfo.innerHTML =
        `当前层级 <b>${data.n_images_here}</b> 张图`
        + (subN ? ` · 子文件夹 <b>${subN}</b> 个含图(扫描时会递归)` : "")
        + ` · <span style="opacity:0.7">${data.path}</span>`;
      scanBtn.disabled = data.n_images_here === 0 && subN === 0;
    } catch (e) {
      folderInfo.textContent = "检查失败: " + e;
      scanBtn.disabled = true;
    }
  }
  folderPath.addEventListener("input", () => {
    clearTimeout(folderPath._t);
    folderPath._t = setTimeout(inspectFolder, 350);
  });

  // V14.0 — Retry support. We remember the last fired action (scan or
  // upload) so the user can re-trigger it without re-picking files or
  // re-typing a folder path. ``lastAction`` is set on success path,
  // re-fired on retry click.
  let lastAction = null;  // { kind: 'scan'|'upload', run: () => Promise }
  const retryBtn = document.getElementById("retryBtn");

  function showRetry(visible) {
    if (retryBtn) retryBtn.style.display = visible ? "inline-block" : "none";
  }

  if (retryBtn) {
    retryBtn.addEventListener("click", () => {
      if (!lastAction) return;
      showRetry(false);
      lastAction.run();
    });
  }

  async function runScan(p) {
    scanBtn.disabled = true;
    showRetry(false);
    statusEl.classList.add("show");
    stateLabel.textContent = "索引中";
    messageEl.textContent = "扫描文件夹…";
    progressBar.style.width = "5%";
    progressBar.classList.remove("error", "done");

    try {
      // V17.0 — pull the optional vertical override from the dropdown.
      // Sent as ``vertical`` in the body; server stores it in run
      // metadata so per-vertical eval / tuning can filter on it.
      const verticalSel = document.getElementById("scanVertical");
      const vertical = (verticalSel && verticalSel.value) || "";
      const res = await fetch("/scan_local", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder: p, vertical }),
      });
      if (!res.ok) {
        let msg;
        try { msg = (await res.json()).error || `HTTP ${res.status}`; }
        catch (_) { msg = `HTTP ${res.status}`; }
        throw new Error(msg);
      }
      const data = await res.json();
      stateLabel.textContent = "分析中";
      messageEl.textContent = `已索引 ${data.n} 张图,正在分析…`;
      pollStatus(data.run_id);
    } catch (err) {
      stateLabel.textContent = "失败";
      messageEl.textContent = err.message || String(err);
      progressBar.classList.add("error");
      progressBar.style.width = "100%";
      scanBtn.disabled = false;
      showRetry(true);  // V14.0 — let user retry without re-entering path
    }
  }

  scanBtn.addEventListener("click", () => {
    const p = folderPath.value.trim();
    if (!p) return;
    lastAction = { kind: "scan", run: () => runScan(p) };
    runScan(p);
  });

  // ---------------------- Folder browser modal -------------------------
  const browserModal = document.getElementById("browserModal");
  const browserPath = document.getElementById("browserPath");
  const browserBody = document.getElementById("browserBody");
  const browserClose = document.getElementById("browserClose");
  const browserUseHere = document.getElementById("browserUseHere");
  const browserHereCount = document.getElementById("browserHereCount");
  let browserCurrent = "";

  async function loadBrowser(path) {
    browserBody.textContent = "加载中…";
    try {
      const res = await fetch("/browse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path || "" }),
      });
      const data = await res.json();
      if (!res.ok) {
        browserBody.innerHTML = `<div class="muted" style="padding:14px">${data.error || "失败"}</div>`;
        return;
      }
      browserCurrent = data.path;
      browserPath.textContent = data.path;
      browserHereCount.textContent =
        data.n_images_here ? `当前层 ${data.n_images_here} 张` : "(当前层无图)";
      const rows = [];
      if (data.parent) {
        rows.push(`<div class="row parent" data-go="${data.parent}"><span class="icon">⬆</span><span class="name">..</span></div>`);
      }
      data.entries.forEach(e => {
        const badge = e.n_images > 0
          ? `<span class="badge">${e.n_images} 张</span>`
          : (e.n_images === -1 ? `<span class="muted">⊘</span>` : "");
        const childPath = data.path === "/" ? `/${e.name}` : `${data.path}/${e.name}`;
        rows.push(`<div class="row" data-go="${childPath}"><span class="icon">▸</span><span class="name">${e.name}</span>${badge}</div>`);
      });
      browserBody.innerHTML = rows.join("") || `<div class="muted" style="padding:14px">空文件夹</div>`;
      browserBody.querySelectorAll(".row").forEach(r => {
        r.addEventListener("click", () => loadBrowser(r.dataset.go));
      });
    } catch (e) {
      browserBody.innerHTML = `<div class="muted" style="padding:14px">${e}</div>`;
    }
  }
  // V14.4 — flipped from style.display to .show class so the modal
  // can share the global animation keyframes + ARIA helpers below.
  // Pre-register so the observer wires up focus trap + restoration
  // even on the very first open.
  registerModal(browserModal);
  browseBtn.addEventListener("click", () => {
    openModal(browserModal);
    loadBrowser(folderPath.value.trim() || "");
  });
  browserClose.addEventListener("click", () => closeModal(browserModal));
  browserUseHere.addEventListener("click", () => {
    folderPath.value = browserCurrent;
    closeModal(browserModal);
    inspectFolder();
  });
  // V8.3: quick-jump shortcut buttons in the modal header.
  document.querySelectorAll("#browserQuick a").forEach(a => {
    a.addEventListener("click", () => loadBrowser(a.dataset.go));
  });
  // V8.3 + V14.4: Esc to close, click on backdrop to close.
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && browserModal.classList.contains("show")) {
      closeModal(browserModal);
    }
  });
  browserModal.addEventListener("click", e => {
    if (e.target === browserModal) closeModal(browserModal);
  });

  // ---------------------- Upload (existing path) -----------------------
  async function runUpload(files) {
    if (!files.length) return;
    uploadBtn.disabled = true;
    clearBtn.disabled = true;
    showRetry(false);
    statusEl.classList.add("show");
    stateLabel.textContent = "上传中";
    messageEl.textContent = `正在上传 ${files.length} 张图片…`;
    progressBar.style.width = "5%";
    progressBar.classList.remove("error", "done");

    const fd = new FormData();
    files.forEach(f => fd.append("files", f));

    let runId = null;
    try {
      const res = await fetch("/analyze", { method: "POST", body: fd });
      if (!res.ok) {
        // Server now returns JSON {error: "..."} on rejection; fall back
        // to raw text only if that's not what we got.
        let msg;
        try {
          const data = await res.json();
          msg = data.error || `HTTP ${res.status}`;
        } catch (_) {
          msg = `HTTP ${res.status}`;
        }
        throw new Error(msg);
      }
      const data = await res.json();
      runId = data.run_id;
    } catch (err) {
      stateLabel.textContent = "上传失败";
      messageEl.textContent = err.message || String(err);
      progressBar.classList.add("error");
      progressBar.style.width = "100%";
      uploadBtn.disabled = false;
      clearBtn.disabled = false;
      // V14.0 — Retry will re-upload the same File objects. The
      // browser keeps them alive in memory as long as the input
      // hasn't been re-clicked, so this works without re-picking.
      showRetry(true);
      return;
    }

    stateLabel.textContent = "分析中";
    pollStatus(runId);
  }

  uploadBtn.addEventListener("click", () => {
    if (!pickedFiles.length) return;
    const snapshot = pickedFiles.slice();
    lastAction = { kind: "upload", run: () => runUpload(snapshot) };
    runUpload(snapshot);
  });

  // P-UX-21 — zero-friction sample-data path. POSTs to a server
  // endpoint that copies samples/output/ → /tmp/pixcull_demo/<id>/
  // (already pre-scored) + serves the 6 sample input files in place
  // via the manifest's absolute paths. Visitor goes from "click" to
  // "interactive /results page" in under 1 second.
  const sampleBtn = document.getElementById("sampleBtn");
  if (sampleBtn) sampleBtn.addEventListener("click", async () => {
    sampleBtn.disabled = true; const orig = sampleBtn.textContent;
    sampleBtn.textContent = "⚡ 加载中…";
    try {
      const r = await fetch("/sample_demo", { method: "POST" });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error || `HTTP ${r.status}`);
      location.href = `/results/${d.run_id}`;
    } catch (e) {
      sampleBtn.textContent = orig;
      sampleBtn.disabled = false;
      alert("加载示例数据失败: " + e.message);
    }
  });

  // V14.2 — rolling-window ETA. We collect (timestamp, done) samples
  // for the last ~25 polls and compute "items per second" from the
  // tail. Smoother than naive total-elapsed/done because per-image
  // cost varies (RAW decode is slower for the first image, model
  // warming, occasional API stalls).
  function fmtEta(secs) {
    if (!isFinite(secs) || secs < 1) return "<1s";
    if (secs < 60) return `${Math.round(secs)}s`;
    const m = Math.floor(secs / 60), s = Math.round(secs % 60);
    return s ? `${m}m${s}s` : `${m}m`;
  }

  async function pollStatus(runId) {
    let stalled = 0;
    let lastDone = 0;
    const samples = [];   // [{t, done}, ...] up to 25
    while (true) {
      let s;
      try {
        const res = await fetch(`/status/${runId}`);
        s = await res.json();
      } catch (e) {
        await new Promise(r => setTimeout(r, 1500));
        continue;
      }

      // Update rolling samples for ETA
      const now = Date.now() / 1000;
      samples.push({ t: now, done: s.done || 0 });
      while (samples.length > 25) samples.shift();

      let etaTxt = "";
      if (s.total && s.done > 0 && samples.length >= 4) {
        // Use only the most recent half of the window so the rate
        // tracks current pace, not the cold-start spike.
        const tail = samples.slice(-Math.max(4, Math.floor(samples.length / 2)));
        const dt = tail[tail.length - 1].t - tail[0].t;
        const dn = tail[tail.length - 1].done - tail[0].done;
        if (dt > 0 && dn > 0) {
          const rate = dn / dt;  // items/sec
          const remain = s.total - s.done;
          if (remain > 0) etaTxt = ` · 预计 ${fmtEta(remain / rate)}`;
        }
      }
      messageEl.textContent = (s.message || "处理中…") + etaTxt;
      if (s.total) {
        const pct = Math.max(5, Math.round(100 * s.done / s.total));
        progressBar.style.width = pct + "%";
      }

      if (s.state === "done") {
        progressBar.classList.add("done");
        progressBar.style.width = "100%";
        stateLabel.textContent = "完成";
        resultsLink.href = `/results/${runId}`;
        resultsLink.style.display = "inline-block";
        clearBtn.disabled = false;
        return;
      }
      if (s.state === "error") {
        progressBar.classList.add("error");
        stateLabel.textContent = "失败";
        clearBtn.disabled = false;
        // V14.0 — pipeline-side error → user can retry the same files
        if (lastAction) {
          uploadBtn.disabled = false;
          scanBtn.disabled = false;
          showRetry(true);
        }
        return;
      }
      // stall detector — purely cosmetic, doesn't abort
      if (s.done === lastDone) stalled++; else { stalled = 0; lastDone = s.done; }

      await new Promise(r => setTimeout(r, 800));
    }
  }
})();
</script>
</body>
</html>
""")


# V19.4.1 — _RESULTS_HTML moved to pixcull/report/templates/results.html.
# Loaded via _results_html_template() above; hot-reloadable on edit.


def _render_delivery_audit_html(run_id: str, md: str, preset: str) -> str:
    """P-PRO-7.1 — wrap the cli_audit Markdown output in browser
    HTML.  Lightweight Markdown→HTML conversion (regex-based) so we
    don't pull in a markdown library; the CLI output uses a stable
    subset (## headings, | tables |, ``- bullets``, **bold**).
    """
    import html as _html
    import re as _re

    def _md_to_html(text: str) -> str:
        # Escape first
        out = _html.escape(text)
        # ## Headings → <h2>
        out = _re.sub(r"^## +(.+)$",
                      r"<h2>\1</h2>", out, flags=_re.MULTILINE)
        # # Heading → <h1>
        out = _re.sub(r"^# +(.+)$",
                      r"<h1>\1</h1>", out, flags=_re.MULTILINE)
        # **bold**
        out = _re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
        # `inline code`
        out = _re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
        # _italic_ for the timestamp line + similar
        out = _re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", out)

        # Tables: blocks of | … | lines.  Convert each contiguous
        # block by detecting the separator line ``| --- | --- |`` etc.
        def _tablize(block: str) -> str:
            lines = block.strip().splitlines()
            if len(lines) < 2:
                return block
            head_cells = [c.strip() for c in lines[0].strip("|").split("|")]
            rows_html = []
            for ln in lines[2:]:                       # skip separator
                cells = [c.strip() for c in ln.strip("|").split("|")]
                tds = "".join(f"<td>{c}</td>" for c in cells)
                rows_html.append(f"<tr>{tds}</tr>")
            ths = "".join(f"<th>{c}</th>" for c in head_cells)
            return ("<table><thead><tr>" + ths + "</tr></thead>"
                    "<tbody>" + "".join(rows_html) + "</tbody></table>")

        # Find tables (any 2+ consecutive lines starting with |)
        def _table_repl(m: _re.Match) -> str:
            return _tablize(m.group(0))
        out = _re.sub(
            r"(?:^\|.*\|$\n){2,}",
            _table_repl, out, flags=_re.MULTILINE,
        )

        # Bullets:  "  - foo" or "- foo"
        out = _re.sub(r"^( {0,4})- +(.+)$",
                      r"\1<li>\2</li>", out, flags=_re.MULTILINE)
        # Wrap consecutive <li> in <ul>
        out = _re.sub(r"(?:<li>.+</li>\n)+",
                      lambda m: "<ul>" + m.group(0) + "</ul>", out)

        # Paragraph break: double newline → </p><p>
        # (cheap; the markdown is short enough that we just wrap
        # the whole thing in a div with white-space: pre-line)
        return out

    body = _md_to_html(md)
    preset_label = "中式" if preset == "chinese" else "西式"
    preset_url = ("?preset=western" if preset == "chinese"
                  else "?preset=chinese")
    preset_alt = "西式" if preset == "chinese" else "中式"

    return (
        "<!DOCTYPE html><html lang='zh'><head>"
        "<meta charset='utf-8'>"
        f"<title>交付审计 · {_html.escape(run_id)}</title>"
        "<style>"
        "body{margin:0;background:#0b0d10;color:#e9ecf2;"
        "font:13px/1.6 -apple-system,Segoe UI,PingFang SC,sans-serif}"
        "header{padding:18px 24px;border-bottom:1px solid #232830;"
        "display:flex;align-items:center;gap:12px;flex-wrap:wrap}"
        "header h1{margin:0;font-size:16px;font-weight:700;flex:1}"
        "header a,header span.preset{font-size:11.5px;color:#a8b2c1;"
        "text-decoration:none;padding:4px 10px;border-radius:6px;"
        "border:1px solid #232830}"
        "header a:hover{color:#fff}"
        "main{padding:18px 24px;max-width:920px;line-height:1.7}"
        "h1{font-size:20px;margin:0 0 4px}"
        "h2{font-size:13px;margin:32px 0 12px;color:#a8b2c1;"
        "text-transform:uppercase;letter-spacing:.04em;"
        "padding-bottom:6px;border-bottom:1px solid #1c2027}"
        "b{color:#fff}"
        "i{color:#7a8696;font-style:normal;font-size:11.5px}"
        "code{font-family:ui-monospace,monospace;font-size:11.5px;"
        "padding:1px 5px;background:#11141a;border-radius:3px;"
        "color:#79c8ff}"
        "table{width:100%;border-collapse:collapse;font-size:12px;"
        "background:#11141a;border:1px solid #232830;border-radius:6px;"
        "overflow:hidden;margin:6px 0 16px}"
        "th{text-align:left;padding:8px 12px;background:#161a21;"
        "color:#a8b2c1;font-weight:600;font-size:11px;"
        "letter-spacing:.04em;text-transform:uppercase;"
        "border-bottom:1px solid #232830}"
        "td{padding:7px 12px;border-bottom:1px solid #1c2027}"
        "tr:last-child td{border-bottom:none}"
        "ul{margin:6px 0 16px;padding-left:18px}"
        "li{margin:2px 0}"
        "footer{padding:18px 24px;color:#7a8696;font-size:11.5px;"
        "border-top:1px solid #232830}"
        "</style></head><body>"
        f"<header><h1>📋 交付审计 · run "
        f"<code>{_html.escape(run_id)}</code></h1>"
        f"<span class='preset'>mandatory: {preset_label}</span>"
        f"<a href='/admin/delivery/{_html.escape(run_id)}{preset_url}'"
        f">切换 {preset_alt} 预设</a>"
        f"<a href='/admin/delivery/{_html.escape(run_id)}?format=md'>原 Markdown</a>"
        "<a href='/admin'>← 返回 admin</a>"
        "</header>"
        f"<main>{body}</main>"
        "<footer>P-PRO-7.1 · 数据来源:scripts/cli_audit.py · 包含 P-CORE-2 / "
        "P-AI-4 / P-PRO-4 / P-PRO-6 / P-PRO-7 五段审计</footer>"
        "</body></html>"
    )


def _render_face_audit_html(payload: dict) -> str:
    """P-AI-4.1 — minimal HTML report for the face library audit page.

    Inline CSS / no external dependencies so it works behind the
    same single-binary serve_demo.py as everything else.  Renders
    three sections: per-cluster precision, library fragmentation,
    cross-run continuity.
    """
    import html as _html
    run_id = _html.escape(str(payload.get("run_id", "")))
    threshold = float(payload.get("outlier_threshold", 0.0))
    cont = payload.get("continuity", {}) or {}
    clusters = payload.get("cluster_precision", []) or []
    frags    = payload.get("library_fragmentation", []) or []

    # --- per-cluster precision rows ---
    cluster_rows = ""
    polluted_n = sum(1 for c in clusters if c.get("polluted"))
    if not clusters:
        cluster_rows = "<tr><td colspan='5' class='muted'>没有可审计的 face 簇(运行中没有人脸或 face_embeddings 列缺失)</td></tr>"
    else:
        for c in clusters:
            cls = "polluted" if c.get("polluted") else "clean"
            cluster_rows += (
                f"<tr class='{cls}'>"
                f"<td>{_html.escape(str(c.get('cluster_id', '?')))}</td>"
                f"<td>{c.get('n_members', 0)}</td>"
                f"<td>{c.get('min_pair_sim', 0):.3f}</td>"
                f"<td>{c.get('mean_pair_sim', 0):.3f}</td>"
                f"<td>{'⚠ 污染' if c.get('polluted') else '✓ 干净'} ({c.get('n_outliers', 0)} 离群)</td>"
                f"</tr>"
            )

    # --- fragmentation rows ---
    frag_rows = ""
    frag_n = sum(1 for f in frags if f.get("fragmented"))
    if not frags:
        frag_rows = "<tr><td colspan='3' class='muted'>face library 是空的 —— 还没标注过身份</td></tr>"
    else:
        for f in frags:
            cls = "polluted" if f.get("fragmented") else "clean"
            frag_rows += (
                f"<tr class='{cls}'>"
                f"<td>{_html.escape(str(f.get('label', '')))}</td>"
                f"<td>{f.get('n_centroids', 0)}</td>"
                f"<td>{'⚠ 接近上限' if f.get('fragmented') else '✓ 充裕'}</td>"
                f"</tr>"
            )

    return (
        "<!DOCTYPE html><html lang='zh'><head>"
        "<meta charset='utf-8'>"
        f"<title>face 库审计 · {run_id}</title>"
        "<style>"
        "body{margin:0;background:#0b0d10;color:#e9ecf2;"
        "font:13px/1.5 -apple-system,Segoe UI,PingFang SC,sans-serif}"
        "header{padding:18px 24px;border-bottom:1px solid #232830}"
        "h1{margin:0;font-size:16px;font-weight:700}"
        "h1 a{color:#a8b2c1;font-weight:400;text-decoration:none;"
        "margin-left:12px;font-size:12px}"
        ".muted{color:#7a8696}"
        "main{padding:18px 24px;max-width:960px}"
        "section{margin-bottom:28px}"
        "h2{font-size:13px;font-weight:600;letter-spacing:.04em;"
        "text-transform:uppercase;color:#a8b2c1;margin:0 0 10px}"
        ".kpis{display:flex;gap:18px;margin-bottom:10px;flex-wrap:wrap}"
        ".kpi{padding:8px 12px;background:#11141a;border:1px solid #232830;"
        "border-radius:6px;font-size:11.5px}"
        ".kpi b{font-size:14px;color:#fff;display:block;line-height:1.1}"
        ".kpi.warn b{color:#fbbf24}"
        ".kpi.bad b{color:#ef6363}"
        ".kpi.good b{color:#34d399}"
        "table{width:100%;border-collapse:collapse;font-size:12px;"
        "background:#11141a;border:1px solid #232830;border-radius:6px;"
        "overflow:hidden}"
        "th{text-align:left;padding:8px 12px;background:#161a21;"
        "color:#a8b2c1;font-weight:600;font-size:11px;"
        "letter-spacing:.04em;text-transform:uppercase;"
        "border-bottom:1px solid #232830}"
        "td{padding:7px 12px;border-bottom:1px solid #1c2027}"
        "tr:last-child td{border-bottom:none}"
        "tr.polluted{background:rgba(239,99,99,0.06)}"
        "tr.polluted td:last-child{color:#ff9a9a}"
        "tr.clean td:last-child{color:#7fe1b8}"
        "footer{padding:18px 24px;color:#7a8696;font-size:11.5px;"
        "border-top:1px solid #232830}"
        "</style></head><body>"
        f"<header><h1>👤 face 库审计 · run <code>{run_id}</code>"
        f"  <a href='/admin'>← 返回 admin</a>"
        f"  <a href='/admin/face_audit/{run_id}?format=json'>JSON</a>"
        f"</h1></header>"
        "<main>"
        "<section><h2>跨 run 连续性</h2>"
        "<div class='kpis'>"
        f"<div class='kpi'>本 run 的 face 簇 <b>{cont.get('n_current_clusters', 0)}</b></div>"
        f"<div class='kpi'>匹配到历史身份 <b>{cont.get('n_matched_to_library', 0)}</b></div>"
        f"<div class='kpi {'good' if cont.get('match_rate', 0) >= 70 else 'warn' if cont.get('match_rate', 0) >= 40 else 'bad'}'>"
        f"匹配率 <b>{cont.get('match_rate', 0):.1f}%</b></div>"
        "</div>"
        "<p class='muted'>跨 run 匹配率持续下降是身份漂移的信号 —— 检查光线 / 嵌入模型变更。</p>"
        "</section>"
        "<section><h2>本 run 簇精度</h2>"
        f"<div class='kpis'><div class='kpi {'bad' if polluted_n else 'good'}'>"
        f"污染簇 <b>{polluted_n}</b></div>"
        f"<div class='kpi'>总簇数 <b>{len(clusters)}</b></div>"
        f"<div class='kpi'>离群阈值 <b>{threshold:.2f}</b></div>"
        "</div>"
        "<table><thead><tr><th>cluster id</th><th>成员</th>"
        "<th>最低对相似度</th><th>平均对相似度</th><th>状态</th></tr></thead>"
        f"<tbody>{cluster_rows}</tbody></table>"
        "</section>"
        "<section><h2>身份库碎片化(每标签 ≤ 16 centroid)</h2>"
        f"<div class='kpis'><div class='kpi {'warn' if frag_n else 'good'}'>"
        f"接近上限的标签 <b>{frag_n}</b></div>"
        f"<div class='kpi'>已知标签 <b>{len(frags)}</b></div>"
        "</div>"
        "<table><thead><tr><th>标签</th><th>centroid 数</th><th>状态</th></tr></thead>"
        f"<tbody>{frag_rows}</tbody></table>"
        "</section>"
        "</main>"
        "<footer>P-AI-4.1 · 报表数据来源:本 run 的 face_centroids.npz + 用户 root 下的 face_library</footer>"
        "</body></html>"
    )


_ADMIN_HTML = (r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 存储管理</title>
  <style>
""" + _DESIGN_TOKENS_CSS + r"""
    /* v0.6 (3/5) — admin-page aliases.
       Legacy --danger was a separate token; alias to --c-danger. */
    :root { --danger: var(--c-danger); }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
      font-family: var(--font-body);
      font-size: var(--t-body);
      line-height: var(--lh-normal);
      -webkit-font-smoothing: antialiased;
    }
    *:focus-visible {
      outline: 2px solid var(--focus-ring);
      outline-offset: 2px;
      border-radius: 4px;
    }
    header {
      padding: 18px 24px 12px; border-bottom: 1px solid var(--border);
    }
    header h1 { margin: 0 0 4px; font-size: 16px; font-weight: 600; }
    header h1 a { color: var(--muted); text-decoration: none; font-weight: 400; margin-left: 12px; font-size: 13px; }
    header h1 a:hover { color: var(--fg); }
    main { padding: 16px 24px 40px; max-width: 1100px; }
    .card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; padding: 16px; margin-bottom: 18px;
    }
    .card h2 { margin: 0 0 10px; font-size: 13px; font-weight: 600;
               color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
    .summary-row { display: flex; gap: 24px; flex-wrap: wrap; }
    .summary-row .stat { min-width: 100px; }
    .summary-row .stat .v { font-size: 22px; font-weight: 600; }
    .summary-row .stat .k { color: var(--muted); font-size: 11px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    button {
      background: var(--bg-card-hi); color: var(--fg); border: 1px solid var(--border);
      padding: 6px 12px; font-size: 12px; border-radius: 4px; cursor: pointer;
    }
    button:hover { border-color: var(--fg); }
    button.danger { color: var(--danger); border-color: var(--danger); }
    button.danger:hover { background: rgba(239, 68, 68, 0.1); }
    button:disabled { opacity: 0.4; cursor: not-allowed; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }
    th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); }
    th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; }
    tr:hover td { background: rgba(255,255,255,0.025); }
    td.size { font-family: ui-monospace, monospace; }
    .pill { display: inline-block; padding: 1px 6px; font-size: 10px; border-radius: 2px; margin-right: 3px; }
    .pill.keep { background: var(--keep); color: white; }
    .pill.maybe { background: var(--maybe); color: white; }
    .pill.cull { background: var(--cull); color: white; }
    .pill.stale { background: rgba(255,255,255,0.08); color: var(--muted); }
    .pill.running { background: var(--accent); color: white; }
    a.btn { display: inline-block; padding: 4px 10px; font-size: 11px;
            color: var(--accent); text-decoration: none;
            border: 1px solid var(--border); border-radius: 3px; }
    a.btn:hover { border-color: var(--accent); }
    .muted { color: var(--muted); font-size: 11px; }
    .global-cache td { font-family: ui-monospace, monospace; font-size: 11px; }
    .toast {
      position: fixed; bottom: 20px; right: 20px;
      background: var(--bg-card-hi); border: 1px solid var(--border);
      border-radius: 6px; padding: 10px 14px; font-size: 12px;
      max-width: 360px; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      transform: translateX(120%); transition: transform 0.2s;
    }
    .toast.show { transform: translateX(0); }
    .toast.error { border-color: var(--danger); }
  </style>
</head>
<body>
  <header>
    <h1>存储管理
      <a href="/">← 返回上传</a>
      <a href="/verticals" style="color: var(--accent)">垂类样本采集 →</a>
    </h1>
    <div class="muted" id="rootHint">--</div>
  </header>
  <main>
    <!-- P-UX-12 — your taste profile, derived from accumulated
         human annotations. Helps you see your own selection bias
         + sets up data-driven rescorer adaptation later. -->
    <div class="card" id="prefsCard" style="display:none">
      <h2>你的选片偏好(基于人工标注历史)</h2>
      <div class="summary-row">
        <div class="stat"><div class="v" id="prefsTotal">--</div><div class="k">累计人工标注</div></div>
        <div class="stat"><div class="v" id="prefsKeepRate">--</div><div class="k">人工 keep 占比</div></div>
        <div class="stat"><div class="v" id="prefsTopScene">--</div><div class="k">最常 keep 的题材</div></div>
        <div class="stat"><div class="v" id="prefsTopReason">--</div><div class="k">最常 cull 的原因</div></div>
      </div>
      <div style="margin-top:14px">
        <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">题材分布</div>
        <table id="prefsSceneTable" class="global-cache" style="margin-top:4px">
          <thead><tr><th>场景</th><th>keep</th><th>maybe</th><th>cull</th><th>keep 占比</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div style="margin-top:14px">
        <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">你 keep 时 vs cull 时,各维度的平均星级</div>
        <table id="prefsAxisTable" class="global-cache" style="margin-top:4px">
          <thead><tr><th>维度</th><th>keep 时 ★</th><th>cull 时 ★</th><th>差值(你的偏好权重)</th></tr></thead>
          <tbody></tbody>
        </table>
        <div class="muted" style="margin-top:6px">
          差值越大说明你越在乎这一维 —— 例如 "构图 keep 4.5 / cull 1.8 = +2.7" 表示你对构图非常严格。
          未来 PixCull 可以按这些权重自动调整 keep/cull 阈值(P-UX-12 v0.2)。
        </div>
      </div>
    </div>

    <div class="card">
      <h2>V2.1 多轴 rescorer 训练</h2>
      <div class="muted" style="margin-bottom: 10px">
        把累计的人工 rubric 标注 + auto/goldenset 数据训成 6 个 per-axis 回归模型。
        训完后下次跑 pipeline 自动启用,与 auto rubric 并排显示。
      </div>
      <div id="retrainStatus" style="margin-bottom:10px;font-size:12px"></div>
      <table class="global-cache" id="axisModelsTable" style="margin-bottom:8px">
        <thead><tr><th>轴</th><th>训练行数</th><th>含人工</th><th>CV R²</th><th>CV MAE (★)</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="actions">
        <button id="retrainBtn">立即训练</button>
        <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px">
          <input type="checkbox" id="retrainGoldenset" checked> 含 goldenset 冷启动数据
        </label>
        <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px">
          <input type="checkbox" id="retrainIncludeAuto" checked> 含 auto rubric 数据
        </label>
      </div>
    </div>

    <div class="card">
      <h2>本 demo 占用</h2>
      <div class="summary-row">
        <div class="stat"><div class="v" id="totalSize">--</div><div class="k">总占用</div></div>
        <div class="stat"><div class="v" id="totalRuns">--</div><div class="k">分析记录数</div></div>
        <div class="stat"><div class="v" id="totalImages">--</div><div class="k">累计图片</div></div>
      </div>
      <div class="actions">
        <button id="cleanupOlder">清理 1 小时前的</button>
        <button id="cleanupKeepLast">仅保留最近 3 次</button>
        <button id="cleanupAll" class="danger">全部清空</button>
        <button id="refresh">刷新</button>
      </div>
    </div>

    <div class="card">
      <h2>每次分析记录</h2>
      <table id="runsTable">
        <thead><tr>
          <th>run_id</th>
          <th>大小</th>
          <th>图片</th>
          <th>分类</th>
          <th>状态</th>
          <th>距今</th>
          <th></th>
        </tr></thead>
        <tbody></tbody>
      </table>
      <div class="muted" id="emptyHint" style="display:none; padding: 12px 0">没有记录。回到主页上传一批就有了。</div>
    </div>

    <div class="card">
      <h2>机器全局模型缓存</h2>
      <div class="muted" style="margin-bottom: 8px">这些是 PyTorch / HuggingFace 等下载的预训练模型。删除后<b>第一次重新分析</b>会下载,之后照旧。本面板<b>不会</b>动它们,需要清的话执行下方命令。</div>
      <table class="global-cache" id="cachesTable">
        <thead><tr><th>缓存</th><th>路径</th><th>大小</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <!-- V15 — pointer to the goldenset eval workflow. The script
         is CLI-only for now (running the pipeline programmatically
         + writing reports to disk); we just surface the recipe so
         the admin page is the discoverable entry point. -->
    <div class="card">
      <h2>评估 rescorer · 对照真实数据集</h2>
      <div class="muted" style="margin-bottom: 10px">
        把一组带 <code>manual_label</code>(keep / maybe / cull)的图作为 ground truth,
        让 pipeline 跑一遍,出 confusion matrix · macro-F1 · Cohen κ · 逐轴 MAE。
        如果你之前评过一版,把那次的 <code>eval_*.json</code> 喂回去 (<code>--baseline</code>)
        就能告诉你新模型究竟是否变好。
      </div>
      <pre style="background: rgba(0,0,0,0.3); padding: 10px 12px; border-radius: 6px;
                  border: 1px solid var(--border); font-size: 11px; overflow-x:auto;
                  margin-bottom: 10px">
# 数据布局
golden/
  ground_truth.csv          # filename, scene, manual_label
                            #   + 可选 gt_&lt;axis&gt;_stars 列做逐轴评估
  images/*.jpg

# 单次评估(CLI)
PYTHONPATH=. python scripts/eval_on_golden_set.py golden/ \
  --report --label v1

# V1 vs V2 对比 — 哪个 rescorer 更好?
PYTHONPATH=. python scripts/eval_on_golden_set.py golden/ \
  --report --label v2 \
  --baseline golden/_eval_output/eval_v1.json
</pre>
      <div class="muted" style="font-size: 11px">
        输出位置:<code>&lt;golden&gt;/_eval_output/eval_&lt;label&gt;.{json,html}</code>。
        HTML 是自包含的,可以直接发给搭档看。
        阈值约定见 <code>pixcull.scoring.eval_metrics._improvement_verdict</code>:
        macro-F1 +2pp 才算"推荐替换"。
      </div>
    </div>

    <!-- V14.7 — opt-in error reporting toggle. Defaults OFF. Hard
         requirement: nothing leaves the user's machine until they
         explicitly flip the switch + click "submit". -->
    <div class="card">
      <h2>错误上报(opt-in,默认关闭)</h2>
      <div class="muted" style="margin-bottom: 10px">
        开启后,只在你<b>主动点击</b>"立即提交"时会把日志(已脱敏)上传到指定 endpoint。
        <a href="/privacy" target="_blank" style="color:var(--accent)">完整政策 →</a>
      </div>
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:10px">
        <label style="display:flex; align-items:center; gap:6px; font-size:13px; cursor:pointer">
          <input type="checkbox" id="erEnabled"> 开启
        </label>
        <span style="color:var(--muted); font-size:11px" id="erStatusBadge"></span>
      </div>
      <div style="margin-bottom:10px">
        <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px">
          Endpoint URL(留空则只 dry-run 不发送):
        </label>
        <input id="erEndpoint" type="url" placeholder="https://your-sentry-or-server.example/report"
               style="width:100%; max-width:520px; background: rgba(0,0,0,0.3); color: var(--fg);
                      border: 1px solid var(--border); padding: 6px 10px; border-radius: 4px;
                      font: inherit; font-size:12px">
      </div>
      <div class="actions">
        <button id="erSaveBtn">保存设置</button>
        <button id="erSubmitBtn">立即提交一次报告</button>
        <button id="erPreviewBtn">预览将发送的内容</button>
      </div>
      <pre id="erOut" style="margin-top:12px; padding:12px; background: rgba(0,0,0,0.3);
            border: 1px solid var(--border); border-radius: 4px; font-size:11px;
            max-height: 320px; overflow:auto; display:none; white-space: pre-wrap;
            color: var(--muted)"></pre>
    </div>
  </main>
  <div class="toast" id="toast"></div>

<script>
(() => {
  const fmt = b => {
    if (b == null) return "--";
    if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
    if (b >= 1e6) return (b / 1e6).toFixed(1) + " MB";
    if (b >= 1e3) return (b / 1e3).toFixed(0) + " KB";
    return b + " B";
  };
  const fmtAge = s => {
    if (s == null) return "--";
    if (s < 60) return s + "秒前";
    if (s < 3600) return Math.round(s/60) + "分钟前";
    if (s < 86400) return (s/3600).toFixed(1) + "小时前";
    return (s/86400).toFixed(1) + "天前";
  };
  const toast = (msg, isErr = false) => {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.toggle("error", isErr);
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 3000);
  };

  // P-UX-12 — fetch + render the user preference profile card.
  // Independent of the storage refresh, fires once on page load.
  async function loadPreferenceProfile() {
    let p;
    try {
      const res = await fetch("/api/v1/users/preferences");
      if (!res.ok) return;
      p = await res.json();
    } catch (_e) { return; }
    if (!p || !p.total_human_annotations) return;  // nothing to show yet
    const card = document.getElementById("prefsCard");
    if (!card) return;
    card.style.display = "";

    // Summary row
    const total = p.total_human_annotations || 0;
    const scenes = p.scene_decision_counts || {};
    let keepTotal = 0, allTotal = 0;
    for (const sc of Object.values(scenes)) {
      keepTotal += (sc.keep || 0);
      allTotal  += (sc.keep || 0) + (sc.maybe || 0) + (sc.cull || 0);
    }
    document.getElementById("prefsTotal").textContent = total;
    document.getElementById("prefsKeepRate").textContent =
      allTotal > 0 ? Math.round(100 * keepTotal / allTotal) + "%" : "--";

    // Top scene by keep count
    const sceneEntries = Object.entries(scenes).sort(
      (a, b) => (b[1].keep || 0) - (a[1].keep || 0));
    document.getElementById("prefsTopScene").textContent =
      sceneEntries.length > 0
        ? `${sceneEntries[0][0]} (${sceneEntries[0][1].keep || 0})`
        : "--";

    // Top cull reason
    const reasons = p.cull_reasons || {};
    const topReason = Object.entries(reasons).sort((a, b) => b[1] - a[1])[0];
    document.getElementById("prefsTopReason").textContent =
      topReason ? `${topReason[0]} (${topReason[1]})` : "--";

    // Scene table
    const sceneTbody = document.querySelector("#prefsSceneTable tbody");
    sceneTbody.innerHTML = sceneEntries.slice(0, 12).map(([scene, c]) => {
      const k = c.keep || 0, m = c.maybe || 0, x = c.cull || 0;
      const sum = k + m + x;
      const pct = sum > 0 ? Math.round(100 * k / sum) + "%" : "--";
      return `<tr><td>${scene}</td><td>${k}</td><td>${m}</td><td>${x}</td><td>${pct}</td></tr>`;
    }).join("");

    // Axis table — keep avg vs cull avg + difference (your weight)
    const ax = p.avg_rubric_when || {};
    const keepAxes = ax.keep || {};
    const cullAxes = ax.cull || {};
    const axisLabels = {
      technical: "技术", subject: "主体", composition: "构图",
      light: "光线", moment: "瞬间", aesthetic: "美感",
    };
    const axisRows = Object.keys(axisLabels).map(name => {
      const kv = keepAxes[name], cv = cullAxes[name];
      const diff = (kv != null && cv != null) ? (kv - cv) : null;
      return {
        name, label: axisLabels[name], kv, cv, diff,
      };
    }).filter(r => r.kv != null || r.cv != null);
    // Sort by diff descending so the axis you care about most is at top
    axisRows.sort((a, b) => (b.diff ?? -99) - (a.diff ?? -99));
    const axisTbody = document.querySelector("#prefsAxisTable tbody");
    axisTbody.innerHTML = axisRows.map(r => {
      const k = r.kv != null ? r.kv.toFixed(2) : "--";
      const c = r.cv != null ? r.cv.toFixed(2) : "--";
      const d = r.diff != null
        ? `<b style="color:${r.diff > 1.5 ? '#34d399' : r.diff > 0.5 ? '#fbbf24' : 'var(--muted)'}">${r.diff >= 0 ? '+' : ''}${r.diff.toFixed(2)}</b>`
        : "--";
      return `<tr><td>${r.label}</td><td>${k}</td><td>${c}</td><td>${d}</td></tr>`;
    }).join("");
  }
  loadPreferenceProfile();

  async function refresh() {
    let info;
    try {
      const res = await fetch("/storage_info");
      info = await res.json();
    } catch (e) {
      toast("加载失败: " + e, true); return;
    }
    document.getElementById("rootHint").textContent =
      `数据目录: ${info.demo_root}`;
    document.getElementById("totalSize").textContent = fmt(info.runs_total_bytes);
    document.getElementById("totalRuns").textContent = info.n_runs;
    document.getElementById("totalImages").textContent =
      info.runs.reduce((s, r) => s + r.n_input, 0);

    const tbody = document.querySelector("#runsTable tbody");
    if (!info.runs.length) {
      tbody.innerHTML = "";
      document.getElementById("emptyHint").style.display = "block";
    } else {
      document.getElementById("emptyHint").style.display = "none";
      tbody.innerHTML = info.runs.map(r => {
        const pills = ["keep","maybe","cull"]
          .filter(d => r.decisions[d])
          .map(d => `<span class="pill ${d}">${d} ${r.decisions[d]}</span>`)
          .join("");
        const stateP = r.state === "running"
          ? `<span class="pill running">running</span>`
          : r.state === "stale" ? `<span class="pill stale">stale</span>` : "";
        // Mode tag: 'scan' = no copies, only derived data. Reassures
        // the user that deleting a scan run won't touch their originals.
        const modeP = r.mode === "scan"
          ? `<span class="pill" style="background:rgba(59,130,246,0.18);color:#4b9aff" title="扫描模式 — 只存派生数据,删除不影响原图">scan</span>`
          : `<span class="pill" style="background:rgba(255,255,255,0.06);color:var(--muted)" title="上传模式 — 原图副本存在 input/">upload</span>`;
        const isRunning = r.state === "running";
        return `<tr data-id="${r.run_id}">
          <td><code>${r.run_id}</code> ${modeP}</td>
          <td class="size">${fmt(r.size_bytes)}</td>
          <td>${r.n_input}</td>
          <td>${pills || '<span class="muted">--</span>'}</td>
          <td>${stateP}</td>
          <td class="muted">${fmtAge(r.age_seconds)}</td>
          <td>
            <a class="btn" href="/results/${r.run_id}">查看</a>
            <button class="btn rescan-scene" ${isRunning ? "disabled title='running 中'" : "title='重判 stilllife → portrait 等(face_count>0 校正)'"}>重判场景</button>
            <a class="btn" href="/admin/delivery/${r.run_id}" ${isRunning ? "style='pointer-events:none;opacity:0.4'" : "title='P-PRO-7.1 · 完整交付审计(场景 + 人脸 + 婚礼 + ICC + EXIF)'"}>📋 交付审计</a>
            <button class="danger del" ${isRunning ? "disabled title='running 中,等完成再删'" : ""}>删除</button>
          </td>
        </tr>`;
      }).join("");
      tbody.querySelectorAll("button.del").forEach(btn => {
        btn.addEventListener("click", async e => {
          const tr = btn.closest("tr");
          const id = tr.dataset.id;
          if (!confirm(`删除 run ${id}?这会移除该次的上传图片、缩略图、scores.csv 和 XMP 输出。`)) return;
          btn.disabled = true;
          try {
            const res = await fetch(`/runs/${id}`, { method: "DELETE" });
            const data = await res.json();
            if (data.ok) {
              toast(`已删除 ${id}`);
              refresh();
            } else {
              toast("删除失败: " + data.message, true);
              btn.disabled = false;
            }
          } catch (e) {
            toast("删除失败: " + e, true);
            btn.disabled = false;
          }
        });
      });
    }

    const cBody = document.querySelector("#cachesTable tbody");
    cBody.innerHTML = (info.global_caches || []).map(c =>
      `<tr><td>${c.label}</td><td>${c.path}</td><td class="size">${fmt(c.size_bytes)}</td></tr>`
    ).join("") || `<tr><td colspan="3" class="muted">没有发现已知模型缓存</td></tr>`;
  }

  async function cleanup(params, label) {
    if (!confirm(`确认 ${label}?`)) return;
    try {
      const res = await fetch("/runs/cleanup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      const data = await res.json();
      const mb = data.freed_bytes >= 1e9
        ? (data.freed_bytes/1e9).toFixed(2) + " GB"
        : (data.freed_bytes/1024/1024).toFixed(1) + " MB";
      toast(`已清理 ${data.deleted} 项,释放 ${mb}`);
      refresh();
    } catch (e) {
      toast("清理失败: " + e, true);
    }
  }

  document.getElementById("refresh").addEventListener("click", refresh);
  document.getElementById("cleanupOlder").addEventListener("click",
    () => cleanup({ older_than_hours: 1 }, "清理 1 小时前的全部 run"));
  document.getElementById("cleanupKeepLast").addEventListener("click",
    () => cleanup({ keep_last: 3 }, "保留最近 3 次,删除其余"));
  document.getElementById("cleanupAll").addEventListener("click",
    () => cleanup({ keep_last: 0 }, "全部清空(不含正在运行)"));

  // P0.4 — re-judge scenes via /runs/<id>/rescan_scene. Targets the
  // V20 stilllife-with-face mistag in older cached runs.
  document.querySelector("#runsTable tbody").addEventListener("click", async e => {
    const btn = e.target.closest(".rescan-scene");
    if (!btn) return;
    const row = btn.closest("tr");
    const rid = row && row.dataset.id;
    if (!rid) return;
    if (!confirm(`重判 ${rid} 的场景? (face_count>0 的 stilllife → 改为次高概率类)`)) return;
    btn.disabled = true; btn.textContent = "…";
    try {
      const res = await fetch(`/runs/${rid}/rescan_scene`, {method: "POST"});
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || ("HTTP " + res.status));
      const redistro = data.scene_redistribution
        ? Object.entries(data.scene_redistribution)
            .map(([k, v]) => `${k}:${v}`).join(", ")
        : "(无)";
      toast(`已修正 ${data.n_corrected}/${data.n_total} 张 · 新分布: ${redistro}`);
    } catch (e) {
      toast("重判失败: " + e.message, true);
    } finally {
      btn.disabled = false; btn.textContent = "重判场景";
    }
  });

  // V2.1 retrain panel
  const retrainBtn = document.getElementById("retrainBtn");
  const retrainStatus = document.getElementById("retrainStatus");
  const axisTable = document.querySelector("#axisModelsTable tbody");

  async function refreshRetrain() {
    try {
      const res = await fetch("/retrain_status");
      const s = await res.json();
      const meta = s.last_meta || {};
      const axes = (s.axes || meta.axes || []);
      // Status pill
      let statusHtml = "";
      if (s.state === "running") {
        statusHtml = `<span style="color:var(--accent)">▶ 训练中</span> · ${s.phase || "..."}`;
      } else if (s.state === "queued") {
        statusHtml = `<span style="color:var(--muted)">排队中</span>`;
      } else if (s.state === "error") {
        statusHtml = `<span style="color:var(--danger)">✗ ${s.message}</span>`;
      } else if (s.state === "done") {
        const dur = ((s.finished_at - s.started_at)).toFixed(1);
        statusHtml = `<span style="color:var(--keep)">✓ ${s.message}</span> · ${dur}s`;
      }
      if (meta.created_at) {
        statusHtml += ` <span class="muted">(上次训练 ${meta.created_at.slice(0,16)})</span>`;
      }
      retrainStatus.innerHTML = statusHtml || `<span class="muted">尚未训练 · 点"立即训练"开始</span>`;
      // Table
      if (axes.length) {
        axisTable.innerHTML = axes.map(a =>
          `<tr><td><b>${a.axis}</b></td><td>${a.rows}</td><td>${a.n_human}</td><td>${a.cv_r2.toFixed(3)}</td><td>${a.cv_mae.toFixed(3)}</td></tr>`
        ).join("");
      } else {
        axisTable.innerHTML = `<tr><td colspan="5" class="muted">无</td></tr>`;
      }
      // Keep polling while running
      if (s.state === "running" || s.state === "queued") {
        setTimeout(refreshRetrain, 1500);
      }
    } catch (e) {
      retrainStatus.textContent = "状态读取失败: " + e;
    }
  }

  retrainBtn.addEventListener("click", async () => {
    if (!confirm("开始训练?会用累计的所有人工标注 + 选定的辅助数据集。预计 < 1 分钟。")) return;
    retrainBtn.disabled = true;
    try {
      const res = await fetch("/retrain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          include_auto: document.getElementById("retrainIncludeAuto").checked,
          also_goldenset: document.getElementById("retrainGoldenset").checked,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        alert("启动失败: " + (data.error || res.status));
      }
    } finally {
      setTimeout(() => { retrainBtn.disabled = false; }, 1000);
      refreshRetrain();
    }
  });

  // V14.7 — opt-in error reporting toggle wiring
  const erEnabled = document.getElementById("erEnabled");
  const erEndpoint = document.getElementById("erEndpoint");
  const erSaveBtn = document.getElementById("erSaveBtn");
  const erSubmitBtn = document.getElementById("erSubmitBtn");
  const erPreviewBtn = document.getElementById("erPreviewBtn");
  const erStatusBadge = document.getElementById("erStatusBadge");
  const erOut = document.getElementById("erOut");

  async function loadErrorReportSettings() {
    try {
      const res = await fetch("/settings/error_reports");
      const s = await res.json();
      erEnabled.checked = !!s.enabled;
      erEndpoint.value = s.endpoint || "";
      erStatusBadge.textContent = s.enabled
        ? (s.endpoint ? "状态:已开启 + 已配置" : "状态:已开启(dry-run)")
        : "状态:关闭";
    } catch (e) {
      erStatusBadge.textContent = "状态:加载失败";
    }
  }

  erSaveBtn.addEventListener("click", async () => {
    erSaveBtn.disabled = true;
    try {
      const res = await fetch("/settings/error_reports", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          enabled: erEnabled.checked,
          endpoint: erEndpoint.value.trim(),
        }),
      });
      const d = await res.json();
      showToast(d.ok ? "已保存" : "保存失败");
      loadErrorReportSettings();
    } finally {
      erSaveBtn.disabled = false;
    }
  });

  async function callSubmit() {
    const res = await fetch("/error_reports/submit", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({reason: "manual"}),
    });
    return await res.json();
  }

  erSubmitBtn.addEventListener("click", async () => {
    erSubmitBtn.disabled = true;
    try {
      const d = await callSubmit();
      erOut.style.display = "block";
      erOut.textContent = JSON.stringify(d, null, 2);
      showToast(d.sent ? `已发送 (HTTP ${d.status})` : (d.message || "未发送"));
    } finally {
      erSubmitBtn.disabled = false;
    }
  });

  erPreviewBtn.addEventListener("click", async () => {
    // Preview = same submit path, just shows the payload locally.
    // If user is disabled, callSubmit returns no payload; flip on
    // briefly to render preview, then restore.
    const wasOff = !erEnabled.checked;
    if (wasOff) {
      // Don't actually toggle the persisted setting — call a
      // "what would happen if enabled" by temporarily flipping
      // and restoring. In the common case where there's no endpoint,
      // submit_report does dry-run anyway.
      erEnabled.checked = true;
      await fetch("/settings/error_reports", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enabled: true, endpoint: ""}),
      });
    }
    try {
      const d = await callSubmit();
      erOut.style.display = "block";
      erOut.textContent = JSON.stringify(d.payload || d, null, 2);
    } finally {
      if (wasOff) {
        erEnabled.checked = false;
        await fetch("/settings/error_reports", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({enabled: false, endpoint: erEndpoint.value.trim()}),
        });
        loadErrorReportSettings();
      }
    }
  });

  loadErrorReportSettings();

  refresh();
  refreshRetrain();
})();
</script>
</body>
</html>
""")


# v0.7-P0-3 — performance debug page.  Self-contained HTML with the
# same _DESIGN_TOKENS_CSS palette as upload/admin so light/dark
# themes apply uniformly.  Auto-refreshes every 4 s via /admin/perf.json.
_ADMIN_PERF_HTML = (r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<title>PixCull · 性能监控</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
""" + _DESIGN_TOKENS_CSS + r"""
  body {
    background: var(--bg);
    color: var(--fg);
    font: var(--t-body, 13px)/1.55 -apple-system, "PingFang SC",
          "Hiragino Sans", "Microsoft YaHei", sans-serif;
    margin: 0; padding: 28px 32px;
  }
  h1 { font-size: var(--t-hero, 22px); margin: 0 0 4px; }
  .lead { color: var(--muted); margin-bottom: 22px; font-size: var(--t-small); }
  .panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    padding: 18px 22px;
    margin-bottom: 16px;
  }
  .panel h2 {
    font-size: var(--t-h3); margin: 0 0 14px;
    display: flex; align-items: center; gap: 10px;
  }
  .panel h2 .dot {
    width: 8px; height: 8px; border-radius: 999px;
    background: var(--keep);
    box-shadow: 0 0 6px var(--keep);
  }
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
  }
  .stat {
    background: var(--surface-2); padding: 12px 14px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border);
  }
  .stat .label {
    color: var(--muted); font-size: var(--t-small);
    text-transform: uppercase; letter-spacing: 0.05em;
    margin-bottom: 4px;
  }
  .stat .val {
    font-size: 20px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    color: var(--fg);
  }
  .stat .sub {
    font-size: var(--t-small); color: var(--muted-soft, var(--muted));
    margin-top: 2px;
  }
  table {
    width: 100%; border-collapse: collapse;
    font-size: var(--t-small);
  }
  th, td {
    padding: 6px 10px; text-align: left;
    border-bottom: 1px solid var(--border);
  }
  th {
    color: var(--muted); font-weight: 600;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
  }
  tr:last-child td { border-bottom: 0; }
  .back {
    color: var(--muted); text-decoration: none;
    font-size: var(--t-small); margin-bottom: 12px; display: inline-block;
  }
  .back:hover { color: var(--fg); }
  .mono {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    color: var(--fg-2, var(--fg));
  }
  .gauge {
    height: 4px; border-radius: 2px;
    background: var(--surface-3);
    overflow: hidden; margin-top: 6px;
  }
  .gauge .fill {
    height: 100%; background: var(--accent);
    box-shadow: 0 0 6px var(--accent-soft);
  }
  .gauge .fill.warn { background: var(--maybe); box-shadow: 0 0 6px var(--maybe); }
  .gauge .fill.bad  { background: var(--cull);  box-shadow: 0 0 6px var(--cull);  }
</style>
</head>
<body>
<a class="back" href="/admin">← 返回管理面板</a>
<h1>性能监控 · /admin/perf</h1>
<p class="lead">每 4 秒刷新。打开开发者控制台后输入 <span class="mono">window.PixCullStorage._stats()</span> 可查看 localStorage 容量。</p>

<div class="panel">
  <h2><span class="dot"></span>进程状态</h2>
  <div class="stat-grid" id="processGrid">
    <div class="stat"><div class="label">Resident memory</div><div class="val" id="rssVal">…</div><div class="sub" id="rssSub"></div></div>
    <div class="stat"><div class="label">Active runs</div><div class="val" id="runsVal">…</div></div>
  </div>
</div>

<div class="panel">
  <h2><span class="dot"></span>磁盘 · /tmp/pixcull_demo</h2>
  <div class="stat-grid">
    <div class="stat"><div class="label">Cache total</div><div class="val" id="diskTotal">…</div></div>
    <div class="stat"><div class="label">Partition free</div><div class="val" id="diskFree">…</div>
      <div class="gauge"><div class="fill" id="diskGauge" style="width:0%"></div></div>
    </div>
  </div>
</div>

<div class="panel">
  <h2><span class="dot"></span>Per-run 行数 + 缓存大小</h2>
  <table id="runsTable">
    <thead>
      <tr><th>run_id</th><th style="text-align:right">行数</th><th style="text-align:right">缓存</th></tr>
    </thead>
    <tbody></tbody>
  </table>
</div>

<script>
function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  return (n / 1024 / 1024 / 1024).toFixed(2) + " GB";
}
async function refresh() {
  try {
    const res = await fetch("/admin/perf.json");
    const d = await res.json();
    document.getElementById("rssVal").textContent = fmtBytes(d.rss_bytes);
    document.getElementById("runsVal").textContent = String(d.active_runs ?? "—");
    document.getElementById("diskTotal").textContent = fmtBytes(d.disk_total_bytes);
    document.getElementById("diskFree").textContent  = fmtBytes(d.disk_free_bytes);
    const tot = d.disk_total_partition_bytes;
    const free = d.disk_free_bytes;
    const usedPct = (tot && free != null) ? Math.min(100, ((tot - free) / tot) * 100) : 0;
    const g = document.getElementById("diskGauge");
    g.style.width = usedPct.toFixed(1) + "%";
    g.classList.remove("warn", "bad");
    if (usedPct > 90) g.classList.add("bad");
    else if (usedPct > 75) g.classList.add("warn");
    const rows = Object.entries(d.run_row_counts || {})
      .sort((a, b) => (b[1] || 0) - (a[1] || 0));
    const sizes = d.disk_per_run || {};
    document.querySelector("#runsTable tbody").innerHTML = rows.length
      ? rows.map(([rid, n]) => `
          <tr>
            <td class="mono">${rid}</td>
            <td class="mono" style="text-align:right">${n}</td>
            <td class="mono" style="text-align:right">${fmtBytes(sizes[rid])}</td>
          </tr>`).join("")
      : `<tr><td colspan="3" style="color:var(--muted);text-align:center;padding:14px">(无活跃 run)</td></tr>`;
  } catch (_e) {}
}
refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
""")


if __name__ == "__main__":
    main()
