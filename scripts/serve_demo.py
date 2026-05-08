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
from datetime import datetime
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

# V11.2 auto-retrain trigger:
# Increments on every human annotation save; once it crosses
# AUTO_RETRAIN_THRESHOLD, the next /annotation save will spawn a
# background retrain (debounced — won't fire while one is already
# running) then reset the counter. Small enough to feel
# 'continuously learning', large enough that we don't burn CPU
# on every single click.
_AUTO_RETRAIN_THRESHOLD = 10
_annotations_since_retrain = 0

_DEFAULT_PORT = 8770
_FALLBACK_PORTS = (8770, 8771, 8772, 9322, 7799)
_DEMO_ROOT = Path("/tmp/pixcull_demo")  # base dir for upload + output trees
_THUMB_SIZE = 420
_FULL_SIZE = 1600

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
        run_pipeline(
            source_dir,
            output_dir,
            rescorer_mode=rescorer_mode,
            rescorer_path=rescorer_path,
            progress_cb=progress_cb,
            vlm_mode=vlm_mode,
            meta_mode=meta_mode,
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
            "scene": str(r.get("scene", "") or ""),
            "decision": str(r.get("decision", "") or ""),
            "score_final": _f(r.get("score_final")),
            "score_sharpness": _f(r.get("score_sharpness")),
            "score_exposure": _f(r.get("score_exposure")),
            "score_aesthetic": _f(r.get("score_aesthetic")),
            "score_composition": _f(r.get("score_composition")),
            "flags": str(r.get("flags", "") or ""),
            "reason": str(r.get("reason", "") or ""),
            "advice": advice,
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
            "rubric_overall_rationale": (
                human_rec.get("overall_rationale") if human_rec else ""
            ),
            # V3.x rationales for the modal's 4-way comparison
            "vlm_overall_rationale": str(r.get("vlm_overall_rationale", "") or ""),
            "vlm_overall_label": str(r.get("vlm_overall_label", "") or ""),
            "meta_overall_rationale": str(r.get("meta_overall_rationale", "") or ""),
            "meta_overall_label": str(r.get("meta_overall_label", "") or ""),
            "meta_confidence": _f(r.get("meta_confidence")),
            "meta_inconsistencies": str(r.get("meta_inconsistencies", "") or ""),
        })

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
    axis_means: dict[str, float | None] = {}
    for name in rubric_axis_names:
        vals = [r["rubric_stars"][name] for r in rows
                if r["rubric_stars"].get(name) is not None]
        axis_means[name] = round(sum(vals) / len(vals), 2) if vals else None
    summary = {
        "n_total": len(rows),
        "n_keep": counts.get("keep", 0),
        "n_maybe": counts.get("maybe", 0),
        "n_cull": counts.get("cull", 0),
        "rescorer_active": len(rescored) > 0,
        "rescorer_n_scored": len(rescored),
        "rescorer_n_disagrees": len(disagrees),
        "n_human_labeled": n_human_labeled,
        "rubric_axis_means": axis_means,
        "mode": run.get("mode", "upload"),
        "origin_folder": run.get("origin_folder"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "elapsed_s": (
            round(run["finished_at"] - run["started_at"], 1)
            if run.get("finished_at") and run.get("started_at") else None
        ),
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

    # --- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
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
        if path == "/":
            return self._serve_upload_page()
        if path == "/admin":
            return self._serve_admin_page()
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
        if path.startswith("/thumb/"):
            return self._serve_image(path[len("/thumb/"):], _THUMB_SIZE)
        if path.startswith("/full/"):
            return self._serve_image(path[len("/full/"):], _FULL_SIZE)
        if path.startswith("/xmp_zip/"):
            return self._serve_xmp_zip(path[len("/xmp_zip/"):])
        # V9.3: scores.csv direct download
        if path.startswith("/scores_csv/"):
            return self._serve_scores_csv(path[len("/scores_csv/"):])
        if path.startswith("/rubric/"):
            return self._serve_rubric(path[len("/rubric/"):])
        if path.startswith("/annotation/"):
            return self._serve_annotation(path[len("/annotation/"):])
        if path.startswith("/next_to_label/"):
            return self._serve_next_to_label(path[len("/next_to_label/"):])
        self.send_error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/analyze":
            return self._handle_analyze_post()
        if path == "/scan_local":
            return self._handle_scan_local()
        if path == "/browse":
            return self._handle_browse()
        if path.startswith("/export/"):
            return self._handle_export(path[len("/export/"):])
        if path == "/runs/cleanup":
            return self._handle_runs_cleanup()
        if path.startswith("/annotation/"):
            return self._handle_save_annotation(path[len("/annotation/"):])
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
        self.send_error(404, "not found")

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/runs/"):
            return self._handle_run_delete(path[len("/runs/"):])
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
        payload = {"run_id": run_id, "rows": rows, "summary": summary}
        # _safe_dumps strips NaN/Infinity (V14.0) so JS JSON.parse never
        # blows up on a stray inf in score_final or a NaN in axis stars.
        html = _RESULTS_HTML.replace(
            "__PAYLOAD__",
            _safe_dumps(payload).replace("</", "<\\/"),
        )
        self._send_html(200, html.encode("utf-8"))

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
        if req_w > 0:
            buckets = [800, 1200, 1600, 2000, 2400, 3200, 4000]
            chosen = next((b for b in buckets if req_w <= b), buckets[-1])
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
        cache_path = cache_dir / f"{src.name}.{size}.v2.jpg"
        if not cache_path.exists():
            from pixcull.io.loader import load_image  # local import
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
        if target_mode not in ("tmp", "alongside"):
            self._reject_upload(400, "target must be 'tmp' or 'alongside'")
            return
        if target_mode == "alongside" and run.get("mode") != "scan":
            self._reject_upload(
                400,
                "'alongside' 模式只在扫描本地文件夹时可用 —— 上传模式没有原图位置可写。",
            )
            return

        result = _build_results(run_id)
        if result is None:
            self.send_error(500, "no results to export")
            return
        rows, _ = result

        from pixcull.io.xmp import write_xmp, decision_to_xmp

        output_dir = Path(run["output_dir"])
        xmp_dir = output_dir / "xmp"
        xmp_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        skipped = 0
        per_decision: Counter[str] = Counter()
        for r in rows:
            fn = r["filename"]
            decision = r["decision"]
            stars, label = decision_to_xmp(decision)
            if target_mode == "alongside":
                src = _resolve_image_source(run, fn)
                if src is None:
                    skipped += 1
                    continue
                # Sidecar lands at <orig_dir>/<stem>.xmp
                write_xmp(src, stars, label)
            else:
                virtual = xmp_dir / Path(fn).name
                write_xmp(virtual, stars, label)
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

        record = {
            "filename": fn,
            "axes": clean_axes,
            "overall_label": str(params.get("overall_label", ""))[:32],
            "overall_rationale": str(params.get("overall_rationale", ""))[:1000],
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
        """
        run_id = unquote(rel)
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
        chosen = candidates[0]
        # Why we picked this one — surface for the UI tooltip.
        reasons = []
        if (chosen.get("rescorer_pred") is not None
                and chosen["rescorer_pred"] != chosen["decision"]):
            reasons.append(
                f"规则=={chosen['decision']} 但 rescorer=={chosen['rescorer_pred']} (P={chosen.get('rescorer_prob_keep'):.2f})"
            )
        if (chosen.get("rescorer_prob_keep") is not None
                and 0.40 <= chosen["rescorer_prob_keep"] <= 0.70):
            reasons.append(
                f"rescorer 不确定区 (P={chosen['rescorer_prob_keep']:.2f})"
            )
        score = chosen.get("score_final")
        if score is not None and 0.35 <= score <= 0.65:
            reasons.append(f"score_final={score:.2f} 临界")
        if not reasons:
            reasons.append("queue 中未标注的下一张")

        self._send_json(200, json.dumps({
            "filename": chosen["filename"],
            "n_total": len(rows),
            "n_labeled": len(labeled),
            "n_remaining": len(candidates),
            "why": "; ".join(reasons),
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

    # --- storage admin -----------------------------------------------------
    def _serve_admin_page(self) -> None:
        body = _ADMIN_HTML.encode("utf-8")
        self._send_html(200, body)

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
def main() -> None:
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
# HTML — kept inline for single-file shippability. Pages:
#   _UPLOAD_HTML     GET /            drag-drop + status panel
#   _RESULTS_HTML    GET /results/    decision grid (data inlined as __PAYLOAD__)
#   _FIRST_RUN_HTML  GET /first_run   model-warming progress (V14.6)
#   _ADMIN_HTML      GET /admin       storage / runs admin
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


_UPLOAD_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — AI 摄影分拣</title>
  <style>
    :root {
      --bg: #0b0d10;
      --bg-grad: radial-gradient(1200px 600px at 50% -200px, rgba(59,130,246,0.08), transparent 60%),
                 radial-gradient(900px 500px at 90% 110%, rgba(168,85,247,0.05), transparent 60%);
      --bg-card: #14171c;
      --bg-card-hi: #1a1e25;
      --fg: #e9ecf2;
      /* V14.2 — bumped from #8892a0 (5.4:1 on --bg) to #a8b2c1
         (~7.2:1) so muted body text comfortably passes WCAG AA Large
         and approaches AAA. The old value was technically passing
         but felt dim during testing. */
      --muted: #a8b2c1;
      --muted-soft: #7a8696;  /* still-quieter level for tertiary chrome */
      --border: #232830;
      --border-hi: #2f3742;
      --accent: #3b82f6;
      --accent-hi: #60a5fa;
      --accent-glow: rgba(59,130,246,0.18);
      --focus-ring: rgba(96,165,250,0.55);  /* V14.2 — focus-visible color */
      --keep: #34d399;
      --maybe: #fbbf24;
      --cull: #ef6363;
      --error: #ef4444;
      --shadow-sm: 0 1px 2px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.02);
      --shadow-md: 0 4px 16px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.03);
      --shadow-lg: 0 16px 60px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.04);
      /* V14.2 — design tokens. Use these everywhere instead of magic
         pixels so spacing/sizing stays on a 4px grid. */
      --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
      --space-4: 16px; --space-5: 20px; --space-6: 24px;
      --radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px;
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
  <h1>PixCull</h1>
  <div class="subtitle">
    AI 摄影分拣 · 6 轴 rubric · 风格感知评分<br>
    <span style="display:inline-flex;gap:6px;margin-top:8px;flex-wrap:wrap;justify-content:center">
      <span class="pill k">● keep</span>
      <span class="pill m">● maybe</span>
      <span class="pill c">● cull</span>
    </span>
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

  // Auto-show on first visit, OR if URL has ?tour=1
  const forced = location.search.includes("tour=1");
  let done = false;
  try { done = localStorage.getItem("pixcull_tour_done") === "1"; } catch (e) {}
  if (forced || !done) {
    paint();
    overlay.classList.add("show");
  }
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
      const res = await fetch("/scan_local", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder: p }),
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
"""


_RESULTS_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 分析结果</title>
  <style>
    :root {
      --bg: #0b0d10;
      --bg-card: #14171c;
      --bg-card-hi: #1a1e25;
      --fg: #e9ecf2;
      /* V14.2 — same contrast bump as upload page */
      --muted: #a8b2c1;
      --muted-soft: #7a8696;
      --border: #232830;
      --border-hi: #2f3742;
      --keep: #34d399;
      --maybe: #fbbf24;
      --cull: #ef6363;
      --accent: #3b82f6;
      --accent-glow: rgba(59,130,246,0.18);
      --focus-ring: rgba(96,165,250,0.55);
      --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
      --space-4: 16px; --space-5: 20px; --space-6: 24px;
      --radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--bg); color: var(--fg);
      font: 13px/1.5 "Inter", -apple-system, BlinkMacSystemFont,
            "Segoe UI Variable", "Segoe UI", "PingFang SC",
            "Microsoft Yahei UI", "Microsoft Yahei",
            "Helvetica Neue", sans-serif;
      letter-spacing: 0.01em;
    }
    /* V14.2 — visible focus ring */
    *:focus-visible {
      outline: 2px solid var(--focus-ring);
      outline-offset: 2px;
      border-radius: var(--radius-sm);
    }
    button, input, select, a, [tabindex] { outline: none; }
    header {
      position: sticky; top: 0; z-index: 5;
      background: rgba(11, 13, 16, 0.85);
      backdrop-filter: blur(14px) saturate(180%);
      -webkit-backdrop-filter: blur(14px) saturate(180%);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px 14px;
    }
    h1 {
      font-size: 16px; margin: 0 0 10px; font-weight: 700;
      letter-spacing: -0.01em;
      background: linear-gradient(180deg, #ffffff, #c8d0db);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    h1 a { color: var(--muted); text-decoration: none; font-weight: 400; margin-left: 12px; font-size: 12px;
           -webkit-text-fill-color: var(--muted); }
    h1 a:hover { color: var(--fg); -webkit-text-fill-color: var(--fg); }
    .stats { display: flex; gap: 18px; color: var(--muted); font-size: 12px; flex-wrap: wrap; }
    .stats b { color: var(--fg); font-weight: 600; }
    .stats .keep b { color: var(--keep); }
    .stats .maybe b { color: var(--maybe); }
    .stats .cull b { color: var(--cull); }
    .filters { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
    .filters .pill {
      padding: 4px 10px; border: 1px solid var(--border); border-radius: 4px;
      background: var(--bg-card); color: var(--muted); cursor: pointer;
      font-size: 11px; user-select: none;
    }
    .filters .pill.active { color: var(--fg); border-color: var(--fg); background: var(--bg-card-hi); }
    /* V9.0 sort + filter UI */
    .filters .filter-divider {
      width: 1px; align-self: stretch; background: var(--border);
      margin: 2px 4px;
    }
    .filters .filter-group {
      display: flex; gap: 4px; flex-wrap: wrap; align-items: center;
    }
    .filters .filter-group .pill { font-size: 10.5px; padding: 3px 8px; }
    .filters .filter-group .pill .x {
      margin-left: 4px; opacity: 0.5; font-size: 11px;
    }
    .filters .sort-select {
      background: var(--bg-card); color: var(--fg);
      border: 1px solid var(--border); border-radius: 4px;
      padding: 4px 8px; font-size: 11px; font-family: inherit;
      cursor: pointer; outline: none;
    }
    .filters .sort-select:hover { border-color: var(--border-hi); }
    /* V9.0 cluster grouping */
    .grid { row-gap: 12px; }
    .cluster-divider {
      grid-column: 1 / -1; margin: 14px 4px 4px;
      display: flex; align-items: center; gap: 10px;
      color: var(--muted); font-size: 11px;
      letter-spacing: 0.05em; text-transform: uppercase;
    }
    .cluster-divider::before, .cluster-divider::after {
      content: ""; flex: 1; height: 1px;
      background: linear-gradient(90deg, transparent, var(--border), transparent);
    }
    .cluster-divider .compare-btn {
      cursor: pointer; padding: 2px 8px; border-radius: 4px;
      background: rgba(59,130,246,0.15); color: #4b9aff;
      border: 1px solid rgba(59,130,246,0.3);
      font-size: 10px; text-transform: none; letter-spacing: 0;
      user-select: none;
    }
    .cluster-divider .compare-btn:hover { background: rgba(59,130,246,0.25); }

    /* V14.0 — empty-state placeholders */
    .empty-state {
      grid-column: 1 / -1;
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 10px;
      padding: 56px 24px; margin: 16px 0;
      background: rgba(255,255,255,0.02);
      border: 1px dashed var(--border);
      border-radius: 12px;
      text-align: center;
    }
    .empty-icon { font-size: 38px; opacity: 0.7; line-height: 1; }
    .empty-title {
      font-size: 16px; font-weight: 600; color: var(--fg);
    }
    .empty-hint {
      color: var(--muted); font-size: 13px; max-width: 420px;
      line-height: 1.55;
    }
    .empty-actions {
      display: flex; gap: 10px; margin-top: 12px;
      flex-wrap: wrap; justify-content: center;
    }

    /* V14.2 — toast notification stack. Replaces native alert() for
       non-blocking ops (annotation save, export ack, retry trigger).
       Stacks bottom-right; auto-dismisses after 3-5s; click to remove. */
    .toast-stack {
      position: fixed;
      right: 18px; bottom: 18px;
      display: flex; flex-direction: column-reverse; gap: 8px;
      z-index: 50; pointer-events: none;
    }
    .toast {
      pointer-events: auto;
      min-width: 240px; max-width: 380px;
      padding: 10px 14px;
      background: rgba(20,23,28,0.96);
      border: 1px solid var(--border);
      border-left: 3px solid var(--accent);
      border-radius: 6px;
      color: var(--fg); font-size: 13px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.45);
      backdrop-filter: blur(8px);
      animation: toastIn 180ms ease-out;
      cursor: pointer;
    }
    .toast.success { border-left-color: var(--keep); }
    .toast.error   { border-left-color: var(--cull); }
    .toast.warning { border-left-color: var(--maybe); }
    .toast.fading { animation: toastOut 220ms ease-in forwards; }
    @keyframes toastIn {
      from { transform: translateX(20px); opacity: 0; }
      to   { transform: translateX(0);    opacity: 1; }
    }
    @keyframes toastOut {
      from { transform: translateX(0);    opacity: 1; }
      to   { transform: translateX(20px); opacity: 0; }
    }

    /* V14.4 — unified modal animation. Every modal that uses
       ``.show`` now fades the backdrop and translates+scales the
       content. ``prefers-reduced-motion`` cuts the duration to
       almost-instant for users who set that OS preference. */
    @keyframes modalBackdropIn {
      from { opacity: 0; }
      to   { opacity: 1; }
    }
    @keyframes modalContentIn {
      from { opacity: 0; transform: translateY(8px) scale(0.985); }
      to   { opacity: 1; transform: translateY(0)   scale(1);     }
    }
    .lightbox.show, .ann-modal.show, .cmp-modal.show {
      animation: modalBackdropIn 160ms ease-out;
    }
    .lightbox.show .img-pane,
    .lightbox.show .info-pane,
    .ann-modal.show .ann-card,
    .cmp-modal.show .cmp-header,
    .cmp-modal.show .cmp-body {
      animation: modalContentIn 200ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    @media (prefers-reduced-motion: reduce) {
      .lightbox.show, .ann-modal.show, .cmp-modal.show,
      .lightbox.show .img-pane, .lightbox.show .info-pane,
      .ann-modal.show .ann-card,
      .cmp-modal.show .cmp-header, .cmp-modal.show .cmp-body {
        animation-duration: 0.01ms;
      }
    }

    /* V9.2 cluster compare modal */
    .cmp-modal {
      position: fixed; inset: 0; background: rgba(0,0,0,0.92);
      display: none; flex-direction: column; z-index: 12;
      backdrop-filter: blur(8px);
    }
    .cmp-modal.show { display: flex; }
    .cmp-header {
      padding: 14px 24px; display: flex; gap: 16px; align-items: center;
      border-bottom: 1px solid var(--border);
      background: rgba(0,0,0,0.5);
    }
    .cmp-header h3 { margin: 0; font-size: 15px; font-weight: 600; }
    .cmp-header .muted { color: var(--muted); font-size: 12px; }
    .cmp-header .close {
      margin-left: auto; cursor: pointer; padding: 6px 12px;
      border: 1px solid var(--border); border-radius: 5px;
      color: var(--muted);
    }
    .cmp-header .close:hover { color: var(--fg); border-color: var(--border-hi); }
    .cmp-body {
      flex: 1; overflow: auto;
      display: grid; gap: 10px; padding: 14px;
      grid-auto-flow: column; grid-auto-columns: minmax(280px, 1fr);
      align-items: stretch;
    }
    .cmp-cell {
      display: flex; flex-direction: column;
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; overflow: hidden;
    }
    .cmp-cell.best { border: 2px solid var(--keep); }
    .cmp-cell .img-wrap {
      flex: 1; min-height: 280px;
      display: flex; align-items: center; justify-content: center;
      background: #000; cursor: zoom-in;
    }
    .cmp-cell .img-wrap img { max-width: 100%; max-height: 100%; object-fit: contain; }
    .cmp-cell .meta {
      padding: 10px 12px; font-size: 11px;
      border-top: 1px solid var(--border);
    }
    .cmp-cell .meta .fn {
      font-family: ui-monospace, monospace; font-size: 10.5px;
      color: var(--muted); display: block; margin-bottom: 6px;
      text-overflow: ellipsis; overflow: hidden; white-space: nowrap;
    }
    .cmp-cell .meta .stars {
      display: grid; grid-template-columns: repeat(6, 1fr); gap: 3px;
      margin: 4px 0;
    }
    .cmp-cell .meta .stars .a {
      background: rgba(255,255,255,0.04); padding: 2px 4px;
      border-radius: 2px; text-align: center; font-size: 9.5px;
    }
    .cmp-cell .meta .pick-btn {
      width: 100%; margin-top: 6px;
      background: rgba(46,168,74,0.15); color: var(--keep);
      border: 1px solid rgba(46,168,74,0.3);
      padding: 5px; border-radius: 4px; font-size: 11px; cursor: pointer;
    }
    .cmp-cell.best .pick-btn {
      background: var(--keep); color: white;
      border-color: var(--keep);
    }
    /* V9.0 style chip in card */
    .row1 .style-chip {
      font-size: 9px; padding: 1px 5px; border-radius: 2px;
      background: rgba(168, 85, 247, 0.18); color: #c4b5fd;
      letter-spacing: 0.02em;
    }
    .filters button.export-btn {
      padding: 4px 10px; border: 1px solid var(--border); border-radius: 4px;
      background: var(--bg-card); color: var(--fg); cursor: pointer;
      font-size: 11px; font-weight: 500;
    }
    .filters button.export-btn:hover { border-color: var(--fg); }
    .filters button.export-btn:disabled { opacity: 0.5; cursor: wait; }
    .filters .export-status { font-size: 11px; color: var(--muted); }
    .filters .export-status a { color: #4b9aff; text-decoration: none; }
    .filters .export-status a:hover { text-decoration: underline; }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 12px;
      padding: 16px 20px 40px;
    }
    .card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 10px; overflow: hidden;
      display: flex; flex-direction: column;
      transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
      box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    }
    .card:hover {
      transform: translateY(-2px);
      border-color: var(--border-hi);
      box-shadow: 0 8px 24px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.04);
    }
    .card.keep { border-left: 3px solid var(--keep); }
    .card.maybe { border-left: 3px solid var(--maybe); }
    .card.cull { border-left: 3px solid var(--cull); opacity: 0.65; }
    .card.cull:hover { opacity: 1; }
    /* V9.1 keyboard focus ring */
    .card.focused {
      outline: 2px solid var(--accent);
      outline-offset: 1px;
      box-shadow: 0 0 0 4px var(--accent-glow), 0 8px 24px rgba(0,0,0,0.5);
    }
    .card .thumb {
      width: 100%; aspect-ratio: 4/3; object-fit: cover;
      background: #000; cursor: zoom-in;
      transition: filter 0.18s;
    }
    .card:hover .thumb { filter: brightness(1.04); }
    .card .body { padding: 8px 10px 10px; }
    .row1 { display: flex; align-items: baseline; gap: 6px; }
    .row1 .fn {
      font-size: 11px; color: var(--muted); text-overflow: ellipsis;
      overflow: hidden; white-space: nowrap; flex: 1;
    }
    .badge {
      display: inline-block; padding: 1px 6px; font-size: 10px; font-weight: 600;
      border-radius: 3px; text-transform: uppercase; letter-spacing: 0.5px;
    }
    .badge.keep { background: var(--keep); color: white; }
    .badge.maybe { background: var(--maybe); color: white; }
    .badge.cull { background: var(--cull); color: white; }
    .row1 .rs {
      font-size: 9px; padding: 1px 5px; border-radius: 2px;
      background: rgba(255,255,255,0.07); color: var(--muted);
      font-family: ui-monospace, monospace; cursor: help;
    }
    .row1 .rs.dis { background: var(--maybe); color: white; }
    .row1 .rs.meta { background: rgba(168, 85, 247, 0.18); color: #c4b5fd; }
    .row1 .rs.meta.dis { background: var(--maybe); color: white; }
    .row2 { display: flex; align-items: center; justify-content: space-between;
            margin-top: 4px; font-size: 11px; color: var(--muted); }
    .row2 .scene { color: var(--fg); }
    .row3 {
      display: grid; grid-template-columns: repeat(6, 1fr);
      gap: 3px; margin-top: 6px; font-size: 10px;
    }
    .row3 .ax {
      background: rgba(255,255,255,0.04); padding: 3px 5px;
      border-radius: 2px; text-align: center; cursor: help;
    }
    .row3 .ax .k { color: var(--muted); display: block; font-size: 9px; }
    .row3 .ax .v { color: var(--fg); font-weight: 600; }
    .row3 .ax.human { background: rgba(74, 222, 128, 0.18); }
    .row3 .ax.s1 { color: var(--cull); }
    .row3 .ax.s2 { color: #ee8888; }
    .row3 .ax.s3 { color: var(--muted); }
    .row3 .ax.s4 { color: #88cc88; }
    .row3 .ax.s5 { color: var(--keep); }
    .row4 { font-size: 10px; color: var(--muted); margin-top: 6px;
            text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }
    .row5 { font-size: 10px; margin-top: 4px; line-height: 1.35;
            text-overflow: ellipsis; overflow: hidden; white-space: nowrap; cursor: help; }
    .row5.strengths { color: var(--keep); }
    .row5.fixes { color: var(--maybe); }
    /* V14.3 — "why maybe" rationale on the card. Subtle accent so it
       doesn't compete with strengths/fixes. */
    .row5.rationale-line {
      color: var(--accent-hi);
      font-style: italic;
      opacity: 0.92;
    }
    .annotate-btn {
      position: absolute; top: 6px; right: 6px;
      background: rgba(0,0,0,0.65); color: white; border: 0;
      border-radius: 3px; padding: 3px 7px; font-size: 10px;
      cursor: pointer; opacity: 0; transition: opacity 0.15s;
    }
    .card { position: relative; }
    .card:hover .annotate-btn { opacity: 1; }
    .annotate-btn:hover { background: var(--accent); }
    .card.has-human .annotate-btn { opacity: 1; background: rgba(74,222,128,0.5); }
    /* V16.2 — manual rotate button on each card. Mirrors annotate-btn
       but lives on the LEFT so it doesn't collide with 标注 / ✓ 已标.
       Hidden until card hover (same affordance pattern). */
    .card-rot-btn {
      position: absolute; top: 6px; left: 6px;
      width: 26px; height: 22px;
      background: rgba(0,0,0,0.65); color: white; border: 0;
      border-radius: 3px; font-size: 13px; line-height: 1;
      cursor: pointer; opacity: 0; transition: opacity 0.15s;
      display: inline-flex; align-items: center; justify-content: center;
    }
    .card:hover .card-rot-btn { opacity: 1; }
    .card-rot-btn:hover { background: var(--accent); }
    /* Smooth thumbnail rotation — same easing as the lightbox img
       so they feel like the same gesture. */
    .card .thumb { transition: transform 220ms cubic-bezier(0.16, 1, 0.3, 1); }
    @media (prefers-reduced-motion: reduce) {
      .card .thumb { transition-duration: 0.01ms; }
    }
    /* Annotation modal */
    .ann-modal {
      position: fixed; inset: 0; background: rgba(0,0,0,0.85);
      display: none; align-items: flex-start; justify-content: center; z-index: 11;
      overflow-y: auto; padding: 20px;
    }
    .ann-modal.show { display: flex; }
    /* V14.5 — cross-fade between save → next image. The .ann-card
       briefly drops to ~40% opacity while the form is rebuilt and
       the next thumbnail pre-loads, then fades back to full. Avoids
       the "modal flashes blank then snaps in" feel of the old
       hard-reset path. */
    .ann-card {
      transition: opacity 200ms ease-out, transform 200ms ease-out;
    }
    .ann-card.transitioning {
      opacity: 0.4;
      transform: translateY(2px) scale(0.998);
    }
    @media (prefers-reduced-motion: reduce) {
      .ann-card { transition-duration: 0.01ms; }
      .ann-card.transitioning { opacity: 1; transform: none; }
    }

    /* V14.5 — shortcuts cheat sheet overlay */
    .shortcuts-modal {
      position: fixed; inset: 0; background: rgba(0,0,0,0.78);
      display: none; align-items: center; justify-content: center;
      z-index: 13; backdrop-filter: blur(6px); padding: 20px;
    }
    .shortcuts-modal.show {
      display: flex; animation: modalBackdropIn 160ms ease-out;
    }
    .shortcuts-modal.show .shortcuts-card {
      animation: modalContentIn 200ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    @media (prefers-reduced-motion: reduce) {
      .shortcuts-modal.show, .shortcuts-modal.show .shortcuts-card {
        animation-duration: 0.01ms;
      }
    }
    .shortcuts-card {
      background: var(--bg-card); border: 1px solid var(--border-hi);
      border-radius: 12px; padding: 0;
      max-width: 540px; width: 100%; max-height: 86vh;
      overflow: hidden; display: flex; flex-direction: column;
      box-shadow: 0 24px 80px rgba(0,0,0,0.6);
    }
    .shortcuts-header {
      padding: 16px 20px; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 12px; flex-shrink: 0;
    }
    .shortcuts-header h3 {
      margin: 0; font-size: 15px; font-weight: 600; flex: 1;
    }
    .shortcuts-header .close {
      width: 28px; height: 28px; border-radius: 6px;
      display: inline-flex; align-items: center; justify-content: center;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      color: var(--muted); cursor: pointer; font-size: 14px;
    }
    .shortcuts-header .close:hover {
      color: var(--fg); border-color: var(--border-hi);
    }
    .shortcuts-body {
      padding: 14px 20px; overflow-y: auto; flex: 1 1 auto;
    }
    .shortcut-section { margin-bottom: 14px; }
    .shortcut-section:last-child { margin-bottom: 0; }
    .shortcut-section-title {
      font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--muted); margin-bottom: 6px; font-weight: 600;
    }
    .shortcut-row {
      display: flex; align-items: center; gap: 16px;
      padding: 5px 0; font-size: 13px;
    }
    .shortcut-row .keys {
      flex: 0 0 130px; display: flex; gap: 4px; align-items: center;
      font-size: 11px; color: var(--muted);
    }
    .shortcut-row .desc {
      flex: 1 1 auto; color: var(--fg);
    }
    .shortcut-row kbd {
      display: inline-flex; align-items: center; justify-content: center;
      min-width: 22px; height: 22px; padding: 0 6px;
      background: rgba(255,255,255,0.06);
      border: 1px solid var(--border);
      border-bottom-width: 2px;
      border-radius: 4px;
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 11px; color: var(--fg); font-weight: 500;
    }
    .shortcut-row .tag {
      display: inline-block; padding: 1px 6px; border-radius: 3px;
      font-size: 11px; font-weight: 500;
      margin-left: 4px;
    }
    .shortcut-row .tag.keep  { background: rgba(74,222,128,0.15); color: var(--keep); }
    .shortcut-row .tag.maybe { background: rgba(217,163,12,0.18); color: var(--maybe); }
    .shortcut-row .tag.cull  { background: rgba(248,113,113,0.15); color: var(--cull); }
    .shortcuts-foot {
      padding: 10px 20px; border-top: 1px solid var(--border);
      font-size: 11px; color: var(--muted);
      flex-shrink: 0;
    }

    /* Floating "? 快捷键" discoverability pill */
    .shortcuts-hint {
      position: fixed; bottom: 16px; right: 16px;
      background: rgba(0,0,0,0.55);
      border: 1px solid var(--border);
      color: var(--muted);
      padding: 6px 12px; border-radius: 20px;
      font: inherit; font-size: 11px; line-height: 1;
      cursor: pointer; user-select: none;
      backdrop-filter: blur(8px);
      z-index: 7;
      transition: color 120ms, border-color 120ms, background 120ms;
      display: inline-flex; align-items: center; gap: 6px;
    }
    .shortcuts-hint:hover {
      color: var(--fg);
      border-color: var(--border-hi);
      background: rgba(0,0,0,0.7);
    }
    .shortcuts-hint kbd {
      display: inline-flex; align-items: center; justify-content: center;
      min-width: 18px; height: 18px; padding: 0 4px;
      background: rgba(255,255,255,0.08);
      border: 1px solid var(--border);
      border-radius: 3px;
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 10px; color: var(--fg);
    }
    @media (max-width: 640px) {
      .shortcuts-hint {
        bottom: 12px; right: 12px;
        padding: 8px 14px; font-size: 12px;
      }
    }
    .ann-card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; max-width: 920px; width: 100%; padding: 18px;
      display: grid; grid-template-columns: 280px 1fr; gap: 18px;
    }
    .ann-thumb {
      width: 100%; aspect-ratio: 4/3; object-fit: contain;
      background: #000; border-radius: 4px;
    }
    .ann-side h3 { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
    .ann-side .why {
      background: rgba(217, 163, 12, 0.15); border-left: 3px solid var(--maybe);
      padding: 6px 10px; border-radius: 3px; font-size: 11px; margin-bottom: 12px;
    }
    .axis-row { margin-bottom: 14px; }
    .axis-row .axis-name {
      font-size: 12px; font-weight: 600; color: var(--fg); margin-bottom: 2px;
    }
    .axis-row .axis-desc { font-size: 11px; color: var(--muted); margin-bottom: 6px; }
    .stars {
      display: flex; gap: 4px; margin-bottom: 4px;
      font-size: 18px; color: var(--muted); cursor: pointer; user-select: none;
    }
    .stars .star { transition: color 0.1s; }
    .stars .star:hover, .stars .star.on { color: var(--maybe); }
    .stars .star.locked { color: var(--keep); }
    .axis-row textarea {
      width: 100%; min-height: 32px; resize: vertical;
      background: rgba(0,0,0,0.3); border: 1px solid var(--border);
      color: var(--fg); padding: 5px 8px; border-radius: 3px;
      font: inherit; font-size: 11px;
    }
    .axis-row .descriptor {
      font-size: 11px; color: var(--keep); margin-top: 2px; min-height: 14px;
    }
    .ann-foot {
      grid-column: 1 / -1; display: flex; gap: 10px; align-items: center;
      border-top: 1px solid var(--border); padding-top: 12px; margin-top: 6px;
    }
    .ann-foot select, .ann-foot input {
      background: rgba(0,0,0,0.3); border: 1px solid var(--border);
      color: var(--fg); padding: 6px 10px; border-radius: 3px;
    }
    .ann-foot input { flex: 1; }
    .ann-foot button { padding: 7px 14px; font-size: 12px; }
    .ann-foot button.primary { background: var(--accent); color: white; border: 0; }
    .ann-foot button.primary:hover { opacity: 0.9; }
    .ann-foot button.skip {
      background: transparent; color: var(--muted); border: 1px solid var(--border);
    }
    /* V10.1 Lightbox upgrade: image + full evaluation panel side-by-side. */
    .lightbox {
      position: fixed; inset: 0; background: rgba(0,0,0,0.94);
      display: none; z-index: 9; backdrop-filter: blur(4px);
    }
    .lightbox.show { display: grid; grid-template-columns: 1fr 380px; }
    @media (max-width: 900px) {
      .lightbox.show { grid-template-columns: 1fr; }
    }
    .lightbox .img-pane {
      display: flex; align-items: center; justify-content: center;
      padding: 28px 24px; cursor: zoom-out; min-height: 0;
    }
    .lightbox .img-pane img {
      max-width: 100%; max-height: 100%; object-fit: contain;
      border-radius: 6px; box-shadow: 0 12px 40px rgba(0,0,0,0.7);
    }
    .lightbox .info-pane {
      background: var(--bg-card); border-left: 1px solid var(--border);
      overflow-y: auto; padding: 20px 22px;
      font-size: 12.5px; line-height: 1.55;
    }
    .lightbox .info-pane::-webkit-scrollbar { width: 8px; }
    .lightbox .info-pane::-webkit-scrollbar-thumb {
      background: var(--border-hi); border-radius: 4px;
    }
    .lightbox .info-pane h2 {
      margin: 0 0 4px; font-size: 14px; font-weight: 600;
      font-family: ui-monospace, monospace;
      word-break: break-all;
    }
    .lightbox .info-pane .meta-line {
      color: var(--muted); font-size: 11px; margin-bottom: 14px;
      display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
    }
    .lightbox .info-pane .meta-line .badge {
      padding: 2px 7px; font-size: 10px; border-radius: 3px;
      font-weight: 600; text-transform: uppercase;
    }
    .lightbox .info-pane .meta-line .badge.keep { background: var(--keep); color: #fff; }
    .lightbox .info-pane .meta-line .badge.maybe { background: var(--maybe); color: #fff; }
    .lightbox .info-pane .meta-line .badge.cull { background: var(--cull); color: #fff; }
    .lightbox .info-pane .section {
      margin-bottom: 14px; padding-bottom: 14px;
      border-bottom: 1px solid var(--border);
    }
    .lightbox .info-pane .section:last-child {
      border-bottom: 0; margin-bottom: 0;
    }
    .lightbox .info-pane .section-title {
      font-size: 10.5px; color: var(--muted); margin-bottom: 6px;
      text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
    }
    .lightbox .axis-grid {
      display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px;
      margin-bottom: 8px;
    }
    .lightbox .axis-grid .ax {
      background: rgba(255,255,255,0.04); padding: 6px 4px;
      border-radius: 4px; text-align: center;
    }
    .lightbox .axis-grid .ax .k {
      font-size: 9.5px; color: var(--muted); display: block;
    }
    .lightbox .axis-grid .ax .v {
      font-size: 14px; font-weight: 600; margin-top: 2px;
    }
    .lightbox .axis-grid .ax.s1 .v { color: var(--cull); }
    .lightbox .axis-grid .ax.s2 .v { color: #ee8888; }
    .lightbox .axis-grid .ax.s3 .v { color: var(--muted); }
    .lightbox .axis-grid .ax.s4 .v { color: #88cc88; }
    .lightbox .axis-grid .ax.s5 .v { color: var(--keep); }
    .lightbox .axis-grid-detail {
      font-size: 10.5px; color: var(--muted); line-height: 1.5;
    }
    .lightbox .axis-grid-detail .row {
      padding: 4px 0; border-top: 1px dashed rgba(255,255,255,0.06);
      display: flex; gap: 8px;
    }
    .lightbox .axis-grid-detail .row .name {
      flex: 0 0 36px; color: var(--fg);
    }
    .lightbox .rationale {
      font-size: 11.5px; color: var(--fg); line-height: 1.65;
      background: rgba(255,255,255,0.025);
      padding: 8px 10px; border-radius: 4px;
      border-left: 2px solid var(--accent);
    }
    .lightbox .rationale.warn {
      border-left-color: var(--maybe);
      color: var(--maybe);
    }
    .lightbox .strengths-list, .lightbox .weak-list {
      list-style: none; margin: 0; padding: 0;
      font-size: 11.5px;
    }
    .lightbox .strengths-list li {
      color: var(--keep); padding: 3px 0; line-height: 1.5;
    }
    .lightbox .strengths-list li::before { content: "✓ "; }
    .lightbox .weak-list li {
      color: var(--maybe); padding: 3px 0; line-height: 1.5;
    }
    .lightbox .weak-list li::before { content: "△ "; }
    /* V14.3 — canon citation suffix on a strength/weakness phrase. */
    .lightbox .canon-cite {
      display: inline-block;
      margin-left: 6px;
      font-size: 10.5px;
      font-style: italic;
      color: var(--muted);
      opacity: 0.85;
    }
    .lightbox .canon-cite::before { content: ""; }
    /* V14.3 — fix tip below a weakness. */
    .lightbox .fix-line {
      margin-left: 14px;
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 400;
    }
    .lightbox .info-pane .style-tag {
      display: inline-block; margin-right: 4px;
      font-size: 10px; padding: 1px 6px; border-radius: 2px;
      background: rgba(168,85,247,0.18); color: #c4b5fd;
    }
    .lightbox .close-btn {
      position: absolute; top: 18px; right: 408px;
      width: 32px; height: 32px; border-radius: 6px;
      background: rgba(0,0,0,0.6); color: #fff;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer; font-size: 18px; user-select: none;
      border: 1px solid rgba(255,255,255,0.15);
    }
    .lightbox .close-btn:hover { background: rgba(0,0,0,0.85); }
    /* V14.2 — prev/next chevrons. Keyboard ←→ already works; chevrons
       expose the affordance for mouse users (audit flagged this). */
    .lightbox .nav-btn {
      position: absolute; top: 50%; transform: translateY(-50%);
      width: 44px; height: 60px; border-radius: 6px;
      background: rgba(0,0,0,0.55); color: #fff;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer; font-size: 22px; user-select: none;
      border: 1px solid rgba(255,255,255,0.15);
      z-index: 11;
      transition: background 120ms;
    }
    .lightbox .nav-btn:hover { background: rgba(0,0,0,0.85); }
    .lightbox .nav-prev { left: 18px; }
    .lightbox .nav-next { right: 18px; }
    /* V16.1 — manual rotate group, sits to the LEFT of the close
       button. Three buttons: ↺ (CCW), ↻ (CW), ⟲ (reset to EXIF). */
    .lightbox .rotate-grp {
      position: absolute; top: 18px; right: 452px;
      display: flex; gap: 4px; z-index: 11;
    }
    .lightbox .rot-btn {
      width: 32px; height: 32px; border-radius: 6px;
      background: rgba(0,0,0,0.6); color: #fff;
      border: 1px solid rgba(255,255,255,0.15);
      display: inline-flex; align-items: center; justify-content: center;
      font-size: 16px; cursor: pointer;
      transition: background 120ms;
    }
    .lightbox .rot-btn:hover { background: rgba(0,0,0,0.85); }
    /* lbImg gets transformed via inline style; transition for the
       rotation feel (ease-out, 220 ms — fast enough not to feel slow,
       slow enough to read direction). */
    .lightbox .img-pane img {
      transition: transform 220ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    @media (prefers-reduced-motion: reduce) {
      .lightbox .img-pane img { transition-duration: 0.01ms; }
    }
    @media (max-width: 900px) {
      .lightbox .close-btn { right: 18px; }
      .lightbox .nav-btn { width: 38px; height: 50px; }
      .lightbox .rotate-grp { top: 18px; right: 60px; }
      .lightbox .rot-btn { width: 28px; height: 28px; font-size: 14px; }
    }
  </style>
</head>
<body>
  <header>
    <h1 id="title">分析结果 <a href="/">← 上传新一批</a></h1>
    <div class="stats" id="stats"></div>
    <div class="filters" id="filters">
      <span class="pill active" data-d="all">全部</span>
      <span class="pill" data-d="keep">keep</span>
      <span class="pill" data-d="maybe">maybe</span>
      <span class="pill" data-d="cull">cull</span>

      <!-- V9.0: scene + style filter chips populated dynamically from rows -->
      <span class="filter-divider"></span>
      <span class="filter-group" id="sceneFilters"></span>
      <span class="filter-group" id="styleFilters"></span>

      <span style="flex:1"></span>

      <!-- V9.0: sort + group dropdowns -->
      <select id="sortBy" class="sort-select" title="排序方式">
        <option value="default">默认 (keep > maybe > cull)</option>
        <option value="score_desc">总分高 → 低</option>
        <option value="score_asc">总分低 → 高</option>
        <option value="datetime_asc">拍摄时间(早→晚)</option>
        <option value="datetime_desc">拍摄时间(晚→早)</option>
        <option value="cluster">按连拍聚类</option>
      </select>

      <button class="export-btn" id="kbdHelpBtn" title="键盘快捷键 (?)" style="font-family:ui-monospace,monospace">?</button>
      <button class="export-btn" id="annNextBtn" title="按 active learning 优先级标注 — 优先暴露规则与 rescorer 不一致、概率临界、聚类分裂的图">▸ 标注下一张</button>
      <button class="export-btn" id="exportZipBtn" title="导出 XMP 评级到 zip 包(Lightroom / Capture One)">下载 XMP</button>
      <button class="export-btn" id="exportAlongsideBtn" style="display:none" title="把 XMP sidecar 写到原图旁边">写到原图旁边</button>
      <a class="export-btn" id="csvBtn" title="下载完整 scores.csv (Excel/Numbers 友好)" style="text-decoration:none">下载 CSV</a>
      <button class="export-btn" id="batchBtn" title="按总分批量打 keep/cull 标签">批量打分</button>
      <span class="export-status" id="exportStatus"></span>
    </div>
  </header>
  <div class="grid" id="grid"></div>
  <!-- V14.2 — toast container; populated by ``toast(msg, kind)`` in JS -->
  <div class="toast-stack" id="toastStack" aria-live="polite"></div>
  <div class="lightbox" id="lightbox">
    <span class="close-btn" id="lbClose" title="关闭 (Esc)">×</span>
    <!-- V14.2 — prev/next chevrons; keyboard ←→ also works -->
    <span class="nav-btn nav-prev" id="lbPrev" title="上一张 (← / k)" aria-label="上一张">‹</span>
    <span class="nav-btn nav-next" id="lbNext" title="下一张 (→ / j)" aria-label="下一张">›</span>
    <!-- V16.1 — manual rotate buttons. Backend already runs
         ImageOps.exif_transpose so most images come out right; these
         are an override for the rare camera that wrote no EXIF tag,
         or the user who specifically wants a different framing.
         Override is persisted per (run_id, filename) in localStorage. -->
    <div class="rotate-grp" role="group" aria-label="旋转">
      <button class="rot-btn" id="lbRotL" type="button"
              title="逆时针旋转 90°">↺</button>
      <button class="rot-btn" id="lbRotR" type="button"
              title="顺时针旋转 90°">↻</button>
      <button class="rot-btn" id="lbRotReset" type="button"
              title="恢复 EXIF 默认方向">⟲</button>
    </div>
    <div class="img-pane"><img id="lbImg" alt=""></div>
    <div class="info-pane" id="lbInfo"></div>
  </div>

  <!-- V9.2 cluster compare modal -->
  <div class="cmp-modal" id="cmpModal">
    <div class="cmp-header">
      <h3 id="cmpTitle">连拍组比较</h3>
      <span class="muted" id="cmpMeta"></span>
      <span class="close" id="cmpClose">关闭 (Esc)</span>
    </div>
    <div class="cmp-body" id="cmpBody"></div>
  </div>

  <!-- V2.0 annotation modal: rubric form + active-learning queue -->
  <div class="ann-modal" id="annModal">
    <div class="ann-card">
      <div>
        <img class="ann-thumb" id="annThumb" alt="">
        <div style="margin-top:10px;font-size:11px;color:var(--muted)" id="annMeta"></div>
        <div class="why" id="annWhy" style="display:none;margin-top:10px"></div>
      </div>
      <div class="ann-side">
        <h3 id="annTitle">标注</h3>
        <div style="font-size:11px;color:var(--muted);margin-bottom:12px">
          每个轴 1-5★ + 一句"为什么"。这种 rubric 风格的标注比单一的 keep/maybe/cull 给 rescorer 提供 ~6× 的训练信号。
        </div>
        <div id="axesContainer"></div>
        <div class="ann-foot">
          <select id="annOverall">
            <option value="">总体决策…</option>
            <option value="keep">keep</option>
            <option value="maybe">maybe</option>
            <option value="cull">cull</option>
          </select>
          <input id="annOverallRationale" type="text" placeholder="一句话总结(可选)" maxlength="200">
          <button class="skip" id="annClose">关闭</button>
          <button class="skip" id="annNext">跳过 →</button>
          <button class="primary" id="annSave">保存 + 下一张</button>
        </div>
      </div>
    </div>
  </div>

  <!-- V14.5 shortcuts overlay — opens with `?`. Replaces a native
       alert() that was ugly + non-dismissible-on-Esc. Auto-discoverable
       via the floating "? 快捷键" pill in the bottom-right corner. -->
  <div class="shortcuts-modal" id="shortcutsModal">
    <div class="shortcuts-card">
      <div class="shortcuts-header">
        <h3 class="modal-title">键盘快捷键</h3>
        <button class="close" id="shortcutsClose" aria-label="关闭快捷键面板">✕</button>
      </div>
      <div class="shortcuts-body">
        <div class="shortcut-section">
          <div class="shortcut-section-title">浏览</div>
          <div class="shortcut-row"><span class="keys"><kbd>j</kbd> 或 <kbd>→</kbd></span><span class="desc">下一张</span></div>
          <div class="shortcut-row"><span class="keys"><kbd>k</kbd> 或 <kbd>←</kbd></span><span class="desc">上一张</span></div>
          <div class="shortcut-row"><span class="keys"><kbd>Space</kbd></span><span class="desc">放大查看完整评分</span></div>
        </div>
        <div class="shortcut-section">
          <div class="shortcut-section-title">快速标注</div>
          <div class="shortcut-row"><span class="keys"><kbd>1</kbd></span><span class="desc">标 <span class="tag keep">keep</span></span></div>
          <div class="shortcut-row"><span class="keys"><kbd>2</kbd></span><span class="desc">标 <span class="tag maybe">maybe</span></span></div>
          <div class="shortcut-row"><span class="keys"><kbd>3</kbd></span><span class="desc">标 <span class="tag cull">cull</span></span></div>
          <div class="shortcut-row"><span class="keys"><kbd>Enter</kbd></span><span class="desc">打开 rubric 详细标注</span></div>
        </div>
        <div class="shortcut-section">
          <div class="shortcut-section-title">编辑</div>
          <div class="shortcut-row"><span class="keys"><kbd>⌘</kbd>+<kbd>Z</kbd></span><span class="desc">撤销最近一次标注</span></div>
        </div>
        <div class="shortcut-section">
          <div class="shortcut-section-title">放大窗内</div>
          <div class="shortcut-row"><span class="keys"><kbd>r</kbd></span><span class="desc">顺时针旋转 90°</span></div>
          <div class="shortcut-row"><span class="keys"><kbd>R</kbd></span><span class="desc">逆时针旋转 90°</span></div>
        </div>
        <div class="shortcut-section">
          <div class="shortcut-section-title">通用</div>
          <div class="shortcut-row"><span class="keys"><kbd>Esc</kbd></span><span class="desc">关闭当前面板</span></div>
          <div class="shortcut-row"><span class="keys"><kbd>?</kbd></span><span class="desc">显示本面板</span></div>
        </div>
      </div>
      <div class="shortcuts-foot">
        <span class="muted">在输入框中输入时,这些快捷键会自动让位 — 安全粘贴文本不会触发标注</span>
      </div>
    </div>
  </div>

  <!-- V14.5 floating "? 快捷键" hint — discoverability. Hidden in
       the bottom-right corner, low contrast so it doesn't compete
       with the main UI. -->
  <button class="shortcuts-hint" id="shortcutsHint" type="button"
          aria-label="打开键盘快捷键面板">
    <kbd>?</kbd> 快捷键
  </button>

<script>
(() => {
  const PAYLOAD = __PAYLOAD__;
  const { run_id, rows, summary } = PAYLOAD;

  // V14.0 — shared HTML escape. Used everywhere a server-supplied
  // string (filename, scene name, rationale text) lands in innerHTML
  // or an attribute. Prevents a filename like ``"><script>alert(1)`` from
  // breaking the lightbox or the cluster header.
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
  ));

  // V16.0 — i18n display map. Keep token IDs (snake_case English) as
  // the wire format because (a) they're stable across versions and (b)
  // the rescorer / golden-set CSV tooling expects them. We translate
  // ONLY at render time so the data layer stays untouched.
  //
  // Strategy: every map falls back to the original token if the key
  // isn't found, so a new flag emitted by a future detector still
  // shows up (just in English) instead of vanishing — fail open, not
  // fail invisible.
  const I18N_GENRE = {
    portrait: "人像", wildlife: "野生", landscape: "风光",
    architecture: "建筑", street: "街拍", event: "事件",
    documentary: "纪实", fashion: "时尚", macro: "微距",
    food: "美食", sports: "运动", astro: "天文",
    abstract: "抽象", stilllife: "静物",
  };
  const I18N_STYLE = {
    mono: "黑白", low_key: "低调", high_key: "高调",
    silhouette: "剪影", long_exposure: "长曝光",
    rear_curtain_sync: "后帘同步", night: "夜景",
  };
  const I18N_FLAG = {
    severely_blurry:        "严重模糊",
    subject_blur:           "主体模糊",
    global_blur:            "整体偏软",
    blurred_subject:        "主体模糊",
    soft_subject:           "主体偏软",
    closed_eyes:            "闭眼帧",
    blink:                  "闭眼帧",
    motion_blur_on_face:    "脸部动态模糊",
    face_occluded:          "脸部遮挡",
    no_clear_subject:       "无明确主体",
    highlights_clipped:     "高光剪切",
    shadows_clipped:        "阴影剪切",
    severely_underexposed:  "严重欠曝",
    severely_overexposed:   "严重过曝",
    highlight_clip:         "高光剪切",
    horizon_tilt:           "地平线倾斜",
    duplicate_in_cluster:   "连拍组重复",
  };
  const I18N_SOURCE = {
    auto:   "自动规则",
    AUTO:   "自动规则",
    model:  "训练模型",
    MODEL:  "训练模型",
    vlm:    "本地 VLM",
    VLM:    "本地 VLM",
    meta:   "DeepSeek",
    META:   "DeepSeek",
    human:  "人工",
    HUMAN:  "人工",
  };
  const I18N_DECISION = {
    keep: "保留", maybe: "待定", cull: "剔除",
  };

  function tr(token, table) {
    if (token == null) return "";
    return (table && table[token]) || token;
  }
  function trGenre(g)  { return tr(g, I18N_GENRE); }
  function trStyle(s)  { return tr(s, I18N_STYLE); }
  function trFlag(f)   { return tr(f, I18N_FLAG); }
  function trSource(s) { return tr(s, I18N_SOURCE); }

  // Reasons + flags arrive as strings like "severely_blurry" or
  // "score=0.57 · severely_blurry · highlight_clip". Split on common
  // separators, translate each token, rejoin with a Chinese-friendly
  // middle dot. ``score=0.57`` → ``综合分=0.57``;
  // ``rescorer_promoted(P=0.85)`` → ``模型上调(P=0.85)``.
  const _REASON_PREFIX_MAP = [
    ["low_score=",            "综合分偏低="],
    ["score=",                "综合分="],
    ["rescorer_promoted(P=",  "模型上调(P="],
    ["rescorer_demoted(P=",   "模型下调(P="],
  ];
  function trToken(t) {
    if (!t) return "";
    for (const [prefix, zh] of _REASON_PREFIX_MAP) {
      if (t.startsWith(prefix)) return zh + t.slice(prefix.length);
    }
    if (I18N_FLAG[t])  return I18N_FLAG[t];
    if (I18N_STYLE[t]) return I18N_STYLE[t];
    if (I18N_GENRE[t]) return I18N_GENRE[t];
    return t;
  }
  function trReason(s) {
    if (!s) return "";
    // Pipeline emits ``a · b · c`` (Chinese middle dot) or ``a, b`` or
    // space-separated. Try each; replace whitespace runs with the
    // middle dot for visual consistency.
    return String(s)
      .split(/[·,\s]+/)
      .filter(x => x.length)
      .map(trToken)
      .join(" · ");
  }

  // V14.4 — modal a11y wiring via MutationObserver. The existing
  // results page has 16+ ``classList.add/remove("show")`` call sites
  // for lightbox / annotation / cluster-compare; rather than rewrite
  // them all, we observe the class attribute on each registered modal
  // and apply ARIA + focus trap reactively. The same observer also
  // restores focus to the opener on close.
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
  // Convenience wrappers that bookend a class toggle with a11y.
  // (Used by the new browser-modal call sites; legacy sites benefit
  // automatically via the observer.)
  function openModal(el) {
    if (!el) return;
    registerModal(el);
    el.classList.add("show");
  }
  function closeModal(el) {
    if (!el) return;
    el.classList.remove("show");
  }

  // V14.2 — non-blocking toast. Replaces native alert() for ack
  // messages where you don't actually need to interrupt the user.
  // ``kind`` is one of: '' (info, blue), 'success', 'error', 'warning'.
  // Auto-dismisses after `ms` (default 3500); click to dismiss early.
  function toast(message, kind = "", ms = 3500) {
    const stack = document.getElementById("toastStack");
    if (!stack) { console.log("[toast]", message); return; }
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = message;
    el.addEventListener("click", () => removeToast(el));
    stack.appendChild(el);
    setTimeout(() => removeToast(el), ms);
  }
  function removeToast(el) {
    if (!el || !el.parentNode) return;
    el.classList.add("fading");
    setTimeout(() => el.remove(), 220);
  }
  // expose for any inline-script / debugging callers
  window.pcToast = toast;

  // Header stats
  const statsEl = document.getElementById("stats");
  const ela = summary.elapsed_s != null ? summary.elapsed_s + "s" : "--";
  const stats = [
    `<span>共 <b>${summary.n_total}</b> 张</span>`,
    `<span class="keep">keep <b>${summary.n_keep}</b></span>`,
    `<span class="maybe">maybe <b>${summary.n_maybe}</b></span>`,
    `<span class="cull">cull <b>${summary.n_cull}</b></span>`,
    `<span>耗时 <b>${ela}</b></span>`,
  ];
  if (summary.rescorer_active) {
    stats.push(`<span title="V1.1 学习重打分器:在 ${summary.rescorer_n_scored} 张非 cull 图上给出 keep/maybe 预测">rescorer <b>${summary.rescorer_n_scored}</b> 评分 / <b>${summary.rescorer_n_disagrees}</b> 与规则不一致</span>`);
  }
  // V2.0 rubric annotation progress
  if (summary.n_human_labeled != null) {
    stats.push(`<span title="人工 rubric 标注进度,这些标注会喂入下一轮 rescorer 训练">人工标注 <b>${summary.n_human_labeled}</b>/${summary.n_total}</span>`);
  }
  statsEl.innerHTML = stats.join("");

  // V9.0 — sort + scene filter + style filter + cluster grouping
  // Active filter state. activeDecision is one of all/keep/maybe/cull.
  // activeScenes is a Set of scene names; empty = no filter (all scenes).
  // activeStyles is a Set of style mode names; empty = no filter.
  const filterState = {
    decision: "all",
    scenes: new Set(),
    styles: new Set(),
    sort: "default",
  };

  // Build dynamic scene + style filter chips from data
  function buildDynamicFilters() {
    const sceneCounts = {};
    const styleCounts = {};
    rows.forEach(r => {
      if (r.scene) sceneCounts[r.scene] = (sceneCounts[r.scene] || 0) + 1;
      (r.style_modes || []).forEach(s => {
        styleCounts[s] = (styleCounts[s] || 0) + 1;
      });
    });
    const sceneEl = document.getElementById("sceneFilters");
    sceneEl.innerHTML = Object.entries(sceneCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([s, n]) => `<span class="pill" data-scene="${esc(s)}">${esc(s)} <span style="opacity:0.5">${n}</span></span>`)
      .join("");
    const styleEl = document.getElementById("styleFilters");
    styleEl.innerHTML = Object.entries(styleCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([s, n]) => `<span class="pill" data-style="${esc(s)}">${esc(s)} <span style="opacity:0.5">${n}</span></span>`)
      .join("");
    sceneEl.querySelectorAll(".pill").forEach(el => {
      el.addEventListener("click", () => {
        const s = el.dataset.scene;
        if (filterState.scenes.has(s)) { filterState.scenes.delete(s); el.classList.remove("active"); }
        else { filterState.scenes.add(s); el.classList.add("active"); }
        render();
      });
    });
    styleEl.querySelectorAll(".pill").forEach(el => {
      el.addEventListener("click", () => {
        const s = el.dataset.style;
        if (filterState.styles.has(s)) { filterState.styles.delete(s); el.classList.remove("active"); }
        else { filterState.styles.add(s); el.classList.add("active"); }
        render();
      });
    });
  }
  buildDynamicFilters();

  // Sort key function
  function sortRows(arr) {
    const order = { keep: 0, maybe: 1, cull: 2, "": 3 };
    const a = [...arr];
    const s = filterState.sort;
    if (s === "score_desc")   a.sort((x, y) => (y.score_final ?? -1) - (x.score_final ?? -1));
    else if (s === "score_asc")  a.sort((x, y) => (x.score_final ?? 999) - (y.score_final ?? 999));
    else if (s === "datetime_asc")  a.sort((x, y) => (x.datetime || "").localeCompare(y.datetime || ""));
    else if (s === "datetime_desc") a.sort((x, y) => (y.datetime || "").localeCompare(x.datetime || ""));
    else if (s === "cluster") {
      a.sort((x, y) => {
        const cx = x.cluster_id ?? 1e9, cy = y.cluster_id ?? 1e9;
        if (cx !== cy) return cx - cy;
        // within cluster: best first (descending final score)
        return (y.score_final ?? 0) - (x.score_final ?? 0);
      });
    } else {
      // default: keep > maybe > cull, then descending score
      a.sort((x, y) => {
        const dx = order[x.decision] ?? 4, dy = order[y.decision] ?? 4;
        if (dx !== dy) return dx - dy;
        return (y.score_final ?? 0) - (x.score_final ?? 0);
      });
    }
    return a;
  }

  // Grid
  const grid = document.getElementById("grid");
  function render() {
    let filtered = rows;
    if (filterState.decision !== "all") {
      filtered = filtered.filter(r => r.decision === filterState.decision);
    }
    if (filterState.scenes.size > 0) {
      filtered = filtered.filter(r => filterState.scenes.has(r.scene));
    }
    if (filterState.styles.size > 0) {
      filtered = filtered.filter(r =>
        (r.style_modes || []).some(s => filterState.styles.has(s))
      );
    }
    const sorted = sortRows(filtered);

    // Card renderer (extracted)
    function renderCard(r) {
      const thumb = `/thumb/${run_id}/${encodeURIComponent(r.filename)}`;
      const full = `/full/${run_id}/${encodeURIComponent(r.filename)}`;
      const dim = (k, v) => v == null
        ? `<div class="dim"><span class="k">${k}</span><span class="v">--</span></div>`
        : `<div class="dim"><span class="k">${k}</span><span class="v">${v.toFixed(2)}</span></div>`;
      // V16.0 — translate reason tokens for the card display.
      // Keep the raw value in the title attr so power users can still
      // grep for the underlying token if needed.
      const reasonI18N = trReason(r.reason);
      const reasonShort = reasonI18N && reasonI18N.length > 60
        ? reasonI18N.slice(0, 60) + "…" : reasonI18N;
      // V1.2 shadow-mode badge: shows the rescorer's verdict + P(keep) when
      // present. Disagrees-with-rule cases get a yellow ring so they pop.
      let rescorerBadge = "";
      if (r.rescorer_pred) {
        const dis = r.rescorer_pred !== r.decision;
        const probTxt = r.rescorer_prob_keep == null ? "--" :
          r.rescorer_prob_keep.toFixed(2);
        rescorerBadge = `<span class="rs ${dis ? 'dis' : ''}" title="V1.1 rescorer: ${r.rescorer_pred} (P=${probTxt})">${r.rescorer_pred==='keep'?'✓':'?'} ${probTxt}</span>`;
      }
      // V3.1 meta-judge badge: shows overall verdict + confidence and
      // a tooltip with inconsistencies. When meta disagrees with rule,
      // pop a yellow ring like the rescorer-disagreement marker.
      let metaBadge = "";
      if (r.meta_overall_label) {
        const dis = r.meta_overall_label !== r.decision;
        const conf = r.meta_confidence == null ? "" : ` ${(r.meta_confidence*100).toFixed(0)}%`;
        const inc = r.meta_inconsistencies || "";
        const tip = `DeepSeek meta-judge: ${r.meta_overall_label}${conf}\n${r.meta_overall_rationale}\n${inc ? '矛盾: '+inc : ''}`.replace(/"/g,'&quot;');
        metaBadge = `<span class="rs meta ${dis?'dis':''}" title="${tip}">⌬ ${r.meta_overall_label[0].toUpperCase()}${conf}</span>`;
      }
      // V2.0 rubric stars per axis. Only show shorter labels on each
      // card (full descriptors live in the annotation modal).
      const axisAbbr = {
        technical: "技", subject: "主", composition: "构",
        light: "光", moment: "瞬", aesthetic: "美"
      };
      const ax = (name) => {
        const stars = r.rubric_stars && r.rubric_stars[name];
        if (stars == null) return `<div class="ax"><span class="k">${axisAbbr[name]}</span><span class="v">--</span></div>`;
        const s = Math.round(stars);
        const cls = `s${s}` + (r.rubric_human_labeled ? " human" : "");
        return `<div class="ax ${cls}" title="${name}: ${stars.toFixed(1)}★${r.rubric_human_labeled?' (human)':''}"><span class="k">${axisAbbr[name]}</span><span class="v">${stars.toFixed(1)}</span></div>`;
      };
      const cardCls = r.decision + (r.rubric_human_labeled ? " has-human" : "");
      // V9.0 style chip — V16.0 localized to Chinese label, raw token
      // still in tooltip so users can map to the wire format.
      const styleChips = (r.style_modes || []).map(
        s => `<span class="style-chip" title="检测到风格: ${esc(s)}">${esc(trStyle(s))}</span>`
      ).join("");
      // V14.0 — escape filename for every interpolation site. Filenames
      // can contain quotes/angle brackets on macOS+APFS, and an injected
      // attribute would break the whole card.
      const fnEsc = esc(r.filename);
      // V16.2 — read any persisted manual rotation override (set
      // either from the lightbox or from the card hover button).
      // Same localStorage key as lightbox (_lbRotKey), so the two
      // views share state — rotate once, both update.
      const rotDeg = _lbRotGet(r.filename);
      const rotStyle = rotDeg ? `style="transform: rotate(${rotDeg}deg)"` : "";
      return `
        <div class="card ${cardCls}" data-fn="${fnEsc}">
          <img class="thumb" src="${thumb}" data-full="${full}" loading="lazy" alt="${fnEsc}" ${rotStyle}>
          <button class="annotate-btn" data-fn="${fnEsc}" title="人工标注 (rubric)">${r.rubric_human_labeled ? "✓ 已标" : "标注"}</button>
          <button class="card-rot-btn" data-fn="${fnEsc}" type="button" title="顺时针旋转 90°(在放大窗中可继续微调)">↻</button>
          <div class="body">
            <div class="row1">
              <span class="badge ${r.decision}" title="${esc(r.decision)}">${esc(tr(r.decision, I18N_DECISION) || r.decision)}</span>
              <span class="fn" title="${fnEsc}">${fnEsc}</span>
              ${rescorerBadge}
              ${metaBadge}
              ${styleChips}
            </div>
            <div class="row2">
              <span class="scene" title="${esc(r.scene || '')}">${esc(trGenre(r.scene) || "?")}</span>
              <span>综合分 ${r.score_final == null ? "--" : r.score_final.toFixed(2)}</span>
            </div>
            <div class="row3">
              ${ax("technical")}${ax("subject")}${ax("composition")}
              ${ax("light")}${ax("moment")}${ax("aesthetic")}
            </div>
            <div class="row4" title="${esc(r.reason || '')}">${esc(reasonShort || "")}</div>
            ${(r.advice && r.advice.rationale) ? `<div class="row5 rationale-line" title="V14.3 — 为何 maybe">⊕ ${esc(r.advice.rationale)}</div>` : ''}
            ${(r.advice && r.advice.strengths && r.advice.strengths.length) ? `<div class="row5 strengths" title="V5.2 摄影正典优点">✓ ${r.advice.strengths.slice(0,2).map(esc).join(' · ')}</div>` : ''}
            ${(r.advice && r.advice.suggestions && r.advice.suggestions.length) ? `<div class="row5 fixes" title="V5.2 改进建议">→ ${esc(r.advice.suggestions[0])}</div>` : ''}
          </div>
        </div>
      `;
    }
    // End of renderCard

    // V9.0: when sorting by cluster, insert visual dividers for each
    // multi-image cluster so the user sees burst groupings explicitly.
    //
    // V14.1 — produce *segments* (HTML strings) rather than one giant
    // string so the renderer below can flush them to the DOM in
    // batches. For ≤200 cards we still render in one shot (no point
    // batching when it's all visible at once).
    const segments = [];
    if (filterState.sort === "cluster") {
      // Group rows by cluster_id
      const groups = new Map();
      sorted.forEach(r => {
        const c = r.cluster_id == null ? `solo-${r.filename}` : `c${r.cluster_id}`;
        if (!groups.has(c)) groups.set(c, []);
        groups.get(c).push(r);
      });
      // Render: only show divider for clusters with >1 member
      groups.forEach((members, key) => {
        if (members.length > 1) {
          const best = members[0];
          segments.push(`<div class="cluster-divider">
            <span>连拍组 (${members.length} 张) · 最佳: ${esc(best.filename)}</span>
            <span class="compare-btn" data-cluster="${esc(key)}">⊞ 并排比较</span>
          </div>`);
        }
        members.forEach(r => { segments.push(renderCard(r)); });
      });
    } else {
      sorted.forEach(r => { segments.push(renderCard(r)); });
    }
    let html = segments.join("");
    // V14.1 — progressive rendering for big batches. Inserting 1500
    // cards at once janks the main thread for ~300 ms on a mid laptop.
    // Render the first 100 immediately (above-fold), then chunk the
    // remainder in 80-card slices via requestAnimationFrame so the page
    // becomes interactive while the rest streams in. Skip the dance
    // entirely below the threshold — it's already imperceptible there.
    const BATCH_THRESHOLD = 200;
    const FIRST_BATCH = 100;
    const CHUNK = 80;

    // Cancel any in-flight progressive render from a previous filter
    // change so we don't double-insert cards.
    if (window._pcProgressiveToken) window._pcProgressiveToken.cancelled = true;
    const token = { cancelled: false };
    window._pcProgressiveToken = token;

    // V14.0 — richer empty states. Three cases:
    //   1) rows.length === 0           → pipeline produced nothing
    //   2) filtered.length === 0       → user's filter excluded everything
    //   3) html === ""                 → defensive (shouldn't happen)
    if (!html) {
      let emptyHtml;
      if (rows.length === 0) {
        emptyHtml = `
          <div class="empty-state">
            <div class="empty-icon">📭</div>
            <div class="empty-title">这个 run 没有产出任何结果</div>
            <div class="empty-hint">
              可能原因:全部图片解码失败 / 文件夹为空 / 仅含非图片文件。
            </div>
            <div class="empty-actions">
              <a class="btn primary" href="/">返回上传新批次</a>
              <button class="btn" onclick="window.location.reload()">刷新此页</button>
            </div>
          </div>`;
      } else {
        const totalFilters = filterState.scenes.size + filterState.styles.size +
                             (filterState.decision !== "all" ? 1 : 0);
        emptyHtml = `
          <div class="empty-state">
            <div class="empty-icon">🔍</div>
            <div class="empty-title">当前筛选下没有图片</div>
            <div class="empty-hint">
              ${totalFilters} 个筛选条件正在过滤这个 ${rows.length} 张图的批次。
            </div>
            <div class="empty-actions">
              <button class="btn primary" id="resetFiltersBtn">重置所有筛选</button>
            </div>
          </div>`;
      }
      grid.innerHTML = emptyHtml;
      const reset = document.getElementById("resetFiltersBtn");
      if (reset) reset.addEventListener("click", () => {
        filterState.decision = "all";
        filterState.scenes.clear();
        filterState.styles.clear();
        document.querySelectorAll("#filters .pill, #sceneFilters .pill, #styleFilters .pill")
          .forEach(el => el.classList.remove("active"));
        document.querySelector('#filters .pill[data-d="all"]')?.classList.add("active");
        render();
      });
    } else if (segments.length <= BATCH_THRESHOLD) {
      // Small batch: one shot, fastest path.
      grid.innerHTML = html;
    } else {
      // Big batch: paint the above-fold portion, then stream the rest
      // in chunks so the user can scroll/click immediately.
      grid.innerHTML = segments.slice(0, FIRST_BATCH).join("");
      const remaining = segments.slice(FIRST_BATCH);
      let idx = 0;
      function step() {
        if (token.cancelled) return;
        const slice = remaining.slice(idx, idx + CHUNK);
        if (!slice.length) return;
        const tmp = document.createElement("div");
        tmp.innerHTML = slice.join("");
        // Move children directly — appendChild detaches from tmp,
        // so we don't pay the cost of re-parsing.
        const frag = document.createDocumentFragment();
        while (tmp.firstChild) frag.appendChild(tmp.firstChild);
        grid.appendChild(frag);
        idx += CHUNK;
        if (idx < remaining.length) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    }
  }
  render();

  // V9.0 sort dropdown
  document.getElementById("sortBy").addEventListener("change", e => {
    filterState.sort = e.target.value;
    render();
  });

  // Decision filter pills (the original keep/maybe/cull/all set)
  document.querySelectorAll("#filters > .pill").forEach(el => {
    el.addEventListener("click", () => {
      document.querySelectorAll("#filters > .pill").forEach(x => x.classList.remove("active"));
      el.classList.add("active");
      filterState.decision = el.dataset.d;
      render();
    });
  });

  // V10.1 Lightbox — image + full evaluation panel
  const lb = document.getElementById("lightbox");
  const lbImg = document.getElementById("lbImg");
  const lbInfo = document.getElementById("lbInfo");
  const lbClose = document.getElementById("lbClose");
  // V14.4 — register for ARIA + focus trap. Existing call sites that
  // do ``lb.classList.add("show")`` continue to work; the observer
  // handles a11y reactively.
  registerModal(lb);

  // V14.2 — track the current lightbox row so keyboard nav can step
  // through the *visible* card order (whatever filters/sort are
  // applied), not just the raw `rows` array.
  let _lbCurrentFn = null;

  function _lbVisibleFns() {
    return Array.from(grid.querySelectorAll(".card")).map(c => c.dataset.fn);
  }

  function openLightbox(fn) {
    const r = rows.find(x => x.filename === fn);
    if (!r) return;
    _lbCurrentFn = fn;
    // V14.1 — tell the server how big our viewport actually is so it
    // can serve a viewport-bucketed cache (800/1200/1600/...) instead
    // of always 1600 even on a 13" laptop. devicePixelRatio handles
    // retina (a 2× display wants 2× pixels for crispness).
    const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
    const w = Math.round(Math.min(window.innerWidth || 1280, 2400) * dpr);
    lbImg.src = `/full/${run_id}/${encodeURIComponent(fn)}?w=${w}`;
    lbInfo.innerHTML = renderInfoPane(r);
    // V16.1 — apply any persisted manual rotation override for this
    // image. EXIF auto-rotate (server-side ImageOps.exif_transpose)
    // already gets 99% of cases right; this is the fallback for
    // images with no orientation tag, or rare cases where the user
    // wants a different framing than EXIF intended.
    _applyLbRotation();
    lb.classList.add("show");
  }

  // V16.1 — manual rotation override. Persisted per (run_id, filename)
  // in localStorage as a degree value (0/90/180/270). 0 = honor EXIF.
  function _lbRotKey(fn)   { return `pixcull-rot:${run_id}:${fn}`; }
  function _lbRotGet(fn)   {
    const v = parseInt(localStorage.getItem(_lbRotKey(fn)) || "0", 10);
    return ((v % 360) + 360) % 360;
  }
  function _lbRotSet(fn, deg) {
    deg = ((deg % 360) + 360) % 360;
    if (deg === 0) localStorage.removeItem(_lbRotKey(fn));
    else localStorage.setItem(_lbRotKey(fn), String(deg));
  }
  function _applyLbRotation() {
    if (!_lbCurrentFn) return;
    const deg = _lbRotGet(_lbCurrentFn);
    lbImg.style.transform = deg ? `rotate(${deg}deg)` : "";
  }
  function _lbRotateBy(delta) {
    if (!_lbCurrentFn) return;
    const next = _lbRotGet(_lbCurrentFn) + delta;
    _lbRotSet(_lbCurrentFn, next);
    _applyLbRotation();
    // V16.2 — keep the matching grid card's thumbnail in sync.
    _syncCardRotation(_lbCurrentFn);
  }
  function _lbRotateReset() {
    if (!_lbCurrentFn) return;
    _lbRotSet(_lbCurrentFn, 0);
    _applyLbRotation();
    _syncCardRotation(_lbCurrentFn);
  }
  // V16.2 — push the current localStorage rotation onto every visible
  // card matching this filename. Cheap query, runs only on rotate.
  function _syncCardRotation(fn) {
    const deg = _lbRotGet(fn);
    if (!grid) return;
    grid.querySelectorAll(`.card[data-fn]`).forEach(card => {
      if (card.dataset.fn !== fn) return;
      const img = card.querySelector("img.thumb");
      if (img) img.style.transform = deg ? `rotate(${deg}deg)` : "";
    });
  }

  // V14.2 — step within the visible card order. Wraps around the ends.
  function lightboxStep(delta) {
    const visible = _lbVisibleFns();
    if (!visible.length) return;
    let i = visible.indexOf(_lbCurrentFn);
    if (i < 0) i = 0;
    const nextI = (i + delta + visible.length) % visible.length;
    openLightbox(visible[nextI]);
    // Also move card focus so closing the lightbox lands on the
    // matching card (consistent with mouse behavior).
    if (typeof focusCard === "function") focusCard(visible[nextI], false);
  }

  function renderInfoPane(r) {
    const axisNames = ["technical","subject","composition","light","moment","aesthetic"];
    const axisAbbr = {technical:"技术", subject:"主体", composition:"构图",
                       light:"光线", moment:"瞬间", aesthetic:"美感"};
    // Final star strip + per-source detail rows
    const finalStars = axisNames.map(n => {
      const s = r.rubric_stars && r.rubric_stars[n];
      const cls = s == null ? "" : `s${Math.round(s)}`;
      return `<div class="ax ${cls}"><span class="k">${axisAbbr[n]}</span><span class="v">${s == null ? '--' : s.toFixed(1)}</span></div>`;
    }).join("");
    // Per-source comparison (auto / model / vlm / human if present)
    // V16.0 — labels translated through I18N_SOURCE so users see
    // "自动规则 / 训练模型 / 本地 VLM / DeepSeek / 人工" not the
    // raw English tokens.
    const sourceRows = [
      ["auto",   r.rubric_auto_stars],
      ["model",  r.rubric_model_stars],
      ["vlm",    r.rubric_vlm_stars],
      ["meta",   r.rubric_meta_stars],
      ["human",  r.rubric_human_stars],
    ].filter(([_, m]) => m && Object.values(m).some(v => v != null));
    const detailHtml = sourceRows.map(([label, m]) => {
      const vals = axisNames.map(n => m[n] == null ? '·' : m[n].toFixed(1)).join(' / ');
      return `<div class="row"><span class="name">${trSource(label)}</span><span>${vals}</span></div>`;
    }).join("");

    // Style chips + scene + decision header — V16.0 localized.
    const styleChips = (r.style_modes || []).map(
      s => `<span class="style-tag" title="${esc(s)}">${esc(trStyle(s))}</span>`
    ).join("");
    const dec = r.decision || "?";
    const decLabel = tr(dec, I18N_DECISION);
    const scoreLine = r.score_final == null ? "--" : r.score_final.toFixed(2);

    // Strengths + suggestions
    const strengths = (r.advice && r.advice.strengths) || [];
    const weaknesses = (r.advice && r.advice.weaknesses) || [];
    const suggestions = (r.advice && r.advice.suggestions) || [];
    const inconsistencies = (r.advice && r.advice.inconsistencies) || [];
    // V14.3 — detail arrays carry per-phrase canon source attribution
    // ("Adams · Zone System" etc). Falls back to flat-string render
    // when detail isn't populated (older runs / API-fed data).
    const strengthsDetail = (r.advice && r.advice.strengths_detail) || null;
    const weaknessesDetail = (r.advice && r.advice.weaknesses_detail) || null;
    const rationale = (r.advice && r.advice.rationale) || "";

    // Esc-safe HTML escape
    const esc = s => String(s || '').replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));

    return `
      <h2>${esc(r.filename)}</h2>
      <div class="meta-line">
        <span class="badge ${dec}" title="${esc(dec)}">${esc(decLabel)}</span>
        <span title="${esc(r.scene || '')}">${esc(trGenre(r.scene) || '?')}</span>
        <span>综合分 ${scoreLine}</span>
        ${styleChips}
        ${r.cluster_id != null ? `<span title="连拍组 ID">连拍组 ${r.cluster_id}</span>` : ''}
        ${r.rubric_human_labeled ? '<span style="color:var(--keep)">✓ 人工已标</span>' : ''}
      </div>

      <div class="section">
        <div class="section-title">最终评分(优先级:人工 → DeepSeek → VLM → 模型 → 自动)</div>
        <div class="axis-grid">${finalStars}</div>
        ${detailHtml ? `<div class="axis-grid-detail">${detailHtml}</div>` : ''}
      </div>

      ${r.meta_overall_rationale ? `
      <div class="section">
        <div class="section-title">⌬ DeepSeek meta-judge ${r.meta_confidence != null ? `(置信 ${(r.meta_confidence*100).toFixed(0)}%)` : ''}</div>
        <div class="rationale">${esc(r.meta_overall_rationale)}</div>
      </div>
      ` : ''}

      ${r.vlm_overall_rationale ? `
      <div class="section">
        <div class="section-title">VLM 视觉判断</div>
        <div class="rationale">${esc(r.vlm_overall_rationale)}</div>
      </div>
      ` : ''}

      ${inconsistencies.length ? `
      <div class="section">
        <div class="section-title">⚠ 矛盾警示</div>
        <div class="rationale warn">${inconsistencies.map(esc).join('<br>')}</div>
      </div>
      ` : ''}

      ${rationale ? `
      <div class="section">
        <div class="section-title">⊕ 为何 maybe</div>
        <div class="rationale">${esc(rationale)}</div>
      </div>
      ` : ''}

      ${strengths.length ? `
      <div class="section">
        <div class="section-title">优点</div>
        <ul class="strengths-list">${(strengthsDetail || strengths.map(s => ({phrase: s}))).map(d => `
          <li>
            ${esc(d.phrase || d)}
            ${d.source ? `<span class="canon-cite" title="正典出处">— ${esc(d.source)}</span>` : ''}
          </li>
        `).join('')}</ul>
      </div>
      ` : ''}

      ${(weaknesses.length || suggestions.length) ? `
      <div class="section">
        <div class="section-title">改进建议</div>
        <ul class="weak-list">${
          weaknessesDetail
            ? weaknessesDetail.map(d => `
                <li>
                  ${esc(d.phrase)}
                  ${d.source ? `<span class="canon-cite">— ${esc(d.source)}</span>` : ''}
                  ${d.fix ? `<div class="fix-line">→ ${esc(d.fix)}</div>` : ''}
                </li>`).join('')
            : [...weaknesses, ...suggestions].map(s => `<li>${esc(s)}</li>`).join('')
        }</ul>
      </div>
      ` : ''}

      ${r.flags ? `
      <div class="section">
        <div class="section-title">检测器旗标</div>
        <div class="rationale" title="${esc(r.flags)}">${esc(trReason(r.flags))}</div>
      </div>
      ` : ''}

      ${r.reason ? `
      <div class="section">
        <div class="section-title">规则栈说明</div>
        <div class="rationale" title="${esc(r.reason)}">${esc(trReason(r.reason))}</div>
      </div>
      ` : ''}
    `;
  }

  grid.addEventListener("click", e => {
    const t = e.target;
    // V16.2 — card-hover rotate button. Bumps rotation by +90° and
    // updates BOTH the inline transform on the matching <img.thumb>
    // AND the localStorage state, so a subsequent lightbox open
    // picks up the change. Stops propagation so the underlying
    // thumb click (which would open lightbox) doesn't fire.
    const rotBtn = t.closest(".card-rot-btn");
    if (rotBtn) {
      e.stopPropagation();
      const fn = rotBtn.dataset.fn;
      if (!fn) return;
      _lbRotateCard(fn, +90);
      return;
    }
    if (t.tagName === "IMG" && t.classList.contains("thumb")) {
      // climb to find data-fn on the .card
      const card = t.closest(".card");
      if (card && card.dataset.fn) openLightbox(card.dataset.fn);
    }
  });

  // V16.2 — card-side helper: rotate the thumbnail on a single card,
  // share state with the lightbox via the same localStorage key.
  function _lbRotateCard(fn, delta) {
    const next = _lbRotGet(fn) + delta;
    _lbRotSet(fn, next);
    const deg = _lbRotGet(fn);
    // Update every visible card matching this filename (cards may
    // appear once per render; safe to query-all-and-set).
    grid.querySelectorAll(`.card[data-fn]`).forEach(card => {
      if (card.dataset.fn !== fn) return;
      const img = card.querySelector("img.thumb");
      if (img) img.style.transform = deg ? `rotate(${deg}deg)` : "";
    });
    // If the lightbox is currently showing this image, sync its
    // rotation too — same state in both views.
    if (_lbCurrentFn === fn) _applyLbRotation();
  }
  lbClose.addEventListener("click", () => lb.classList.remove("show"));
  // V14.2 — wire chevron clicks for mouse users; keyboard already
  // covered by the document-level keydown handler above.
  const lbPrev = document.getElementById("lbPrev");
  const lbNext = document.getElementById("lbNext");
  if (lbPrev) lbPrev.addEventListener("click", e => {
    e.stopPropagation(); lightboxStep(-1);
  });
  if (lbNext) lbNext.addEventListener("click", e => {
    e.stopPropagation(); lightboxStep(+1);
  });
  // V16.1 — manual rotate button handlers
  const lbRotL = document.getElementById("lbRotL");
  const lbRotR = document.getElementById("lbRotR");
  const lbRotReset = document.getElementById("lbRotReset");
  if (lbRotL) lbRotL.addEventListener("click", e => {
    e.stopPropagation(); _lbRotateBy(-90);
  });
  if (lbRotR) lbRotR.addEventListener("click", e => {
    e.stopPropagation(); _lbRotateBy(+90);
  });
  if (lbRotReset) lbRotReset.addEventListener("click", e => {
    e.stopPropagation(); _lbRotateReset();
  });
  lb.addEventListener("click", e => {
    // Only close on backdrop or img-pane click — not on info-pane,
    // close button, or nav buttons, or rotate buttons.
    if (e.target.closest(".info-pane")) return;
    if (e.target === lbClose) return;
    if (e.target.closest(".nav-btn")) return;
    if (e.target.closest(".rotate-grp")) return;
    lb.classList.remove("show");
  });

  // ==================================================================
  // V9.1 — keyboard navigation + quick labeling
  //   j / k / ←→        prev / next card
  //   1 / 2 / 3        label current as keep/maybe/cull (saves human anno)
  //   space / enter    open lightbox (zoom)
  //   ?                show shortcut cheat sheet
  //   Esc              close any modal
  // Active card is the one that has class .focused (visually outlined).
  // ==================================================================
  let focusedFn = null;
  // V10.1 toast (single-element, bottom-center). V14.2 — keep the
  // signature, delegate to the new stack-based ``toast()`` so we get
  // multi-toast support for free without rewriting all callers.
  function showToast(msg, kind = "info") {
    toast(msg, kind === "info" ? "" : kind);
  }
  // V10.1 — undo stack for batch / quick-label actions
  // Each entry: array of {filename, prev_decision, prev_human_labeled}
  const undoStack = [];
  const UNDO_LIMIT = 20;
  function pushUndo(snapshots) {
    if (!snapshots || !snapshots.length) return;
    undoStack.push(snapshots);
    if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  }
  async function performUndo() {
    const snap = undoStack.pop();
    if (!snap) return;
    let n = 0;
    for (const item of snap) {
      try {
        // Re-post annotation with the old decision (or a special clear)
        await fetch(`/annotation/${run_id}/${encodeURIComponent(item.filename)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            axes: {},
            overall_label: item.prev_decision || "",
            overall_rationale: "撤销",
          }),
        });
        const r = rows.find(x => x.filename === item.filename);
        if (r) {
          r.decision = item.prev_decision;
          r.rubric_human_labeled = item.prev_human_labeled;
        }
        n++;
      } catch (e) { /* ignore */ }
    }
    render();
    return n;
  }

  function visibleCards() {
    return Array.from(grid.querySelectorAll('.card[data-fn]'));
  }
  function focusCard(fn, scrollInto = true) {
    visibleCards().forEach(c => c.classList.remove('focused'));
    const t = grid.querySelector(`.card[data-fn="${CSS.escape(fn)}"]`);
    if (t) {
      t.classList.add('focused');
      if (scrollInto) t.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      focusedFn = fn;
    }
  }
  function moveFocus(delta) {
    const cards = visibleCards();
    if (!cards.length) return;
    const idx = cards.findIndex(c => c.dataset.fn === focusedFn);
    const next = (idx === -1) ? 0 : Math.max(0, Math.min(cards.length - 1, idx + delta));
    focusCard(cards[next].dataset.fn);
  }
  // Save a quick label for the focused card by POSTing /annotation
  // with overall_label only — same endpoint the modal uses.
  async function quickLabel(label) {
    if (!focusedFn) return;
    const r = rows.find(x => x.filename === focusedFn);
    if (r) {
      pushUndo([{
        filename: focusedFn,
        prev_decision: r.decision,
        prev_human_labeled: r.rubric_human_labeled,
      }]);
    }
    try {
      await fetch(`/annotation/${run_id}/${encodeURIComponent(focusedFn)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          axes: {},
          overall_label: label,
          overall_rationale: `quick-labeled ${label} via keyboard`,
        }),
      });
      if (r) {
        r.rubric_human_labeled = true;
        r.decision = label;
      }
      // Quick visual feedback: flash a label badge near the card.
      const card = grid.querySelector(`.card[data-fn="${CSS.escape(focusedFn)}"]`);
      if (card) {
        card.classList.remove('keep','maybe','cull');
        card.classList.add(label, 'has-human');
      }
      summary.n_human_labeled = (summary.n_human_labeled || 0) + 1;
    } catch (e) { /* ignore quick errors */ }
  }
  // V14.5 — shortcuts cheat sheet replaces the old alert(). The
  // overlay HTML is statically rendered; JS just toggles .show
  // and the registerModal observer handles ARIA + focus trap.
  const shortcutsModal = document.getElementById("shortcutsModal");
  const shortcutsClose = document.getElementById("shortcutsClose");
  const shortcutsHint = document.getElementById("shortcutsHint");
  if (shortcutsModal) registerModal(shortcutsModal);

  function showShortcuts() {
    if (!shortcutsModal) return;
    shortcutsModal.classList.add("show");
  }
  function hideShortcuts() {
    if (shortcutsModal) shortcutsModal.classList.remove("show");
  }
  if (shortcutsClose) {
    shortcutsClose.addEventListener("click", hideShortcuts);
  }
  if (shortcutsHint) {
    shortcutsHint.addEventListener("click", showShortcuts);
  }
  if (shortcutsModal) {
    shortcutsModal.addEventListener("click", e => {
      if (e.target === shortcutsModal) hideShortcuts();
    });
  }

  document.addEventListener("keydown", e => {
    // Ignore when typing in inputs / textareas
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    // V10.1: Cmd+Z / Ctrl+Z → undo (allow modifier passthrough)
    if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) {
      e.preventDefault();
      performUndo().then(n => { if (n) showToast(`已撤销 ${n} 个标注`); });
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    // Modal-aware: Esc closes any open modal first. V14.5 also
    // routes Esc to the shortcuts overlay; ordering matters because
    // multiple modals can stack (e.g. shortcuts opened over the
    // lightbox should close shortcuts first, leaving the lightbox).
    if (e.key === "Escape") {
      if (shortcutsModal && shortcutsModal.classList.contains("show")) {
        hideShortcuts(); return;
      }
      if (lb.classList.contains("show")) { lb.classList.remove("show"); return; }
      const am = document.getElementById("annModal");
      if (am && am.classList.contains("show")) { am.classList.remove("show"); return; }
      const bm = document.getElementById("browserModal");
      if (bm && bm.classList.contains("show")) { bm.classList.remove("show"); return; }
      return;
    }
    // Don't act when an annotation modal is open — let modal own input
    const am = document.getElementById("annModal");
    if (am && am.classList.contains("show")) return;

    // V14.2 — when the lightbox is open, j/k/← →/PageUp/PageDown
    // navigate between filtered+sorted rows *within* the lightbox so
    // the user can flip through the keep/maybe/cull batch without
    // closing and re-opening. Falls back to card focus only when the
    // lightbox is closed.
    if (lb.classList.contains("show")) {
      if (e.key === "j" || e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault(); lightboxStep(+1); return;
      }
      if (e.key === "k" || e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault(); lightboxStep(-1); return;
      }
      // V16.1 — r / R inside lightbox = rotate CW / CCW (manual override)
      if (e.key === "r") { e.preventDefault(); _lbRotateBy(+90);  return; }
      if (e.key === "R") { e.preventDefault(); _lbRotateBy(-90);  return; }
    }

    if (e.key === "j" || e.key === "ArrowRight") { e.preventDefault(); moveFocus(+1); }
    else if (e.key === "k" || e.key === "ArrowLeft") { e.preventDefault(); moveFocus(-1); }
    else if (e.key === "1") { e.preventDefault(); quickLabel("keep"); }
    else if (e.key === "2") { e.preventDefault(); quickLabel("maybe"); }
    else if (e.key === "3") { e.preventDefault(); quickLabel("cull"); }
    else if (e.key === " " || e.key === "Spacebar") {
      // toggle lightbox (with info pane) on focused card
      e.preventDefault();
      if (lb.classList.contains("show")) {
        lb.classList.remove("show");
      } else if (focusedFn) {
        openLightbox(focusedFn);
      }
    }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (focusedFn && typeof openAnnotation === "function") {
        openAnnotation(focusedFn);
      }
    }
    else if (e.key === "?") {
      e.preventDefault();
      showShortcuts();
    }
  });

  // Auto-focus the first visible card after each render
  const _origRender = render;
  render = function () {
    _origRender();
    const cards = visibleCards();
    if (cards.length) focusCard(cards[0].dataset.fn, false);
  };
  render();

  // ==================================================================
  // V2.0 rubric annotation flow.
  //   1. fetch /rubric_meta once → build the form skeleton
  //   2. clicking 标注 on a card opens the modal pre-filled with the
  //      auto-decomposed rubric for that image (or the existing human
  //      labels if it's already been rated)
  //   3. saving POSTs /annotation/<run_id>/<filename> and immediately
  //      navigates to the next active-learning candidate
  // ==================================================================
  const annModal = document.getElementById("annModal");
  registerModal(annModal);  // V14.4 — ARIA dialog + focus trap
  const annThumb = document.getElementById("annThumb");
  const annMeta = document.getElementById("annMeta");
  const annWhy = document.getElementById("annWhy");
  const annTitle = document.getElementById("annTitle");
  const annOverall = document.getElementById("annOverall");
  const annOverallRationale = document.getElementById("annOverallRationale");
  const annClose = document.getElementById("annClose");
  const annNext = document.getElementById("annNext");
  const annSave = document.getElementById("annSave");
  const axesContainer = document.getElementById("axesContainer");

  let rubricMeta = null;
  let currentFn = null;

  async function loadRubricMeta() {
    if (rubricMeta) return rubricMeta;
    const res = await fetch("/rubric_meta");
    const data = await res.json();
    rubricMeta = data.axes;
    // Build static form skeleton once
    axesContainer.innerHTML = rubricMeta.map(ax => `
      <div class="axis-row" data-axis="${ax.name}">
        <div class="axis-name">${ax.label_zh} <span style="opacity:0.5;font-weight:400;font-size:10px">(${ax.label_en})</span></div>
        <div class="axis-desc">${ax.description_zh}</div>
        <div class="stars" data-stars data-axis="${ax.name}">
          ${[1,2,3,4,5].map(i => `<span class="star" data-v="${i}">★</span>`).join("")}
        </div>
        <div class="descriptor" data-descriptor></div>
        <textarea data-rationale rows="1" placeholder="为什么是这个分?(可选,但越多越有用)"></textarea>
      </div>
    `).join("");
    // Wire up star click handlers
    axesContainer.querySelectorAll(".stars").forEach(starsEl => {
      const axisName = starsEl.dataset.axis;
      starsEl.querySelectorAll(".star").forEach(starEl => {
        starEl.addEventListener("click", () => {
          const v = parseInt(starEl.dataset.v);
          setStars(axisName, v);
          // Show descriptor for the chosen level
          const ax = rubricMeta.find(a => a.name === axisName);
          starsEl.parentElement.querySelector("[data-descriptor]").textContent =
            v + "★: " + ax.rubric_descriptors[v - 1];
        });
        starEl.addEventListener("mouseenter", () => {
          const v = parseInt(starEl.dataset.v);
          starsEl.querySelectorAll(".star").forEach((s, i) => {
            s.classList.toggle("on", i < v);
          });
        });
      });
      starsEl.addEventListener("mouseleave", () => {
        const locked = parseInt(starsEl.dataset.locked || "0");
        starsEl.querySelectorAll(".star").forEach((s, i) => {
          s.classList.remove("on");
          s.classList.toggle("locked", i < locked);
        });
      });
    });
    return rubricMeta;
  }

  function setStars(axisName, v) {
    const starsEl = axesContainer.querySelector(`.stars[data-axis="${axisName}"]`);
    starsEl.dataset.locked = String(v);
    starsEl.querySelectorAll(".star").forEach((s, i) => {
      s.classList.toggle("locked", i < v);
    });
  }

  function clearForm() {
    axesContainer.querySelectorAll(".stars").forEach(s => {
      s.dataset.locked = "0";
      s.querySelectorAll(".star").forEach(x => x.classList.remove("locked", "on"));
    });
    axesContainer.querySelectorAll("textarea").forEach(t => t.value = "");
    axesContainer.querySelectorAll("[data-descriptor]").forEach(d => d.textContent = "");
    annOverall.value = "";
    annOverallRationale.value = "";
    annWhy.style.display = "none";
  }

  // V14.5 — when openAnnotation is called via openNextToLabel right
  // after a save, we want a smooth cross-fade rather than a jarring
  // hard reset. Pre-loading the next thumbnail before the swap kills
  // the broken-image flash; the .ann-card .transitioning class fades
  // form fields during the rebuild.
  async function openAnnotation(fn, why, opts = {}) {
    const transition = !!opts.transition;
    await loadRubricMeta();
    currentFn = fn;

    const annCard = annModal.querySelector(".ann-card");
    if (transition && annCard) annCard.classList.add("transitioning");

    clearForm();

    // Pre-load the next image so we never show a broken/empty <img>.
    const nextSrc = `/full/${run_id}/${encodeURIComponent(fn)}`;
    if (transition) {
      try {
        await new Promise((resolve) => {
          const probe = new Image();
          probe.onload = probe.onerror = resolve;
          probe.src = nextSrc;
          // Don't block forever if the image is huge / slow.
          setTimeout(resolve, 800);
        });
      } catch (e) { /* fall through anyway */ }
    }
    annThumb.src = nextSrc;

    const r = rows.find(x => x.filename === fn);
    annTitle.textContent = `${fn}`;
    annMeta.innerHTML = r
      ? `场景:<b>${esc(trGenre(r.scene) || "?")}</b> · 规则:<b>${esc(tr(r.decision, I18N_DECISION) || r.decision)}</b> · 综合分 ${r.score_final?.toFixed(2) || "--"}`
      : "";
    if (why) {
      annWhy.style.display = "block";
      annWhy.innerHTML = `<b>为什么挑这张?</b> ${why}`;
    }
    // Pre-fill from /annotation endpoint (auto or human)
    try {
      const res = await fetch(`/annotation/${run_id}/${encodeURIComponent(fn)}`);
      const data = await res.json();
      const rec = data.data || {};
      const axes = rec.axes || {};
      Object.keys(axes).forEach(axisName => {
        const ax = axes[axisName];
        if (ax.stars != null) {
          setStars(axisName, Math.round(ax.stars));
          const meta = rubricMeta.find(a => a.name === axisName);
          const starsEl = axesContainer.querySelector(`.stars[data-axis="${axisName}"]`);
          if (starsEl && meta) {
            starsEl.parentElement.querySelector("[data-descriptor]").textContent =
              Math.round(ax.stars) + "★: " + meta.rubric_descriptors[Math.round(ax.stars) - 1];
          }
        }
        if (ax.rationale) {
          const ta = axesContainer.querySelector(`.axis-row[data-axis="${axisName}"] textarea`);
          if (ta) ta.value = ax.rationale;
        }
      });
      if (rec.overall_label) annOverall.value = rec.overall_label;
      if (rec.overall_rationale) annOverallRationale.value = rec.overall_rationale;
    } catch (e) { /* no prior — leave blank */ }
    annModal.classList.add("show");
    // V14.5 — clear the cross-fade veil one frame after the modal
    // is visible so the new content renders fully opaque.
    if (transition && annCard) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          annCard.classList.remove("transitioning");
        });
      });
    }
  }

  async function saveAnnotation(thenAdvance) {
    if (!currentFn) return;
    const axes = {};
    rubricMeta.forEach(ax => {
      const starsEl = axesContainer.querySelector(`.stars[data-axis="${ax.name}"]`);
      const stars = parseInt(starsEl.dataset.locked || "0");
      const ta = axesContainer.querySelector(`.axis-row[data-axis="${ax.name}"] textarea`);
      const rationale = ta ? ta.value.trim() : "";
      if (stars > 0 || rationale) {
        axes[ax.name] = { stars: stars || null, rationale };
      }
    });
    if (Object.keys(axes).length === 0 && !annOverall.value) {
      toast("至少打 1 颗星 或 选 keep/maybe/cull", "warning");
      return;
    }
    const body = {
      axes,
      overall_label: annOverall.value,
      overall_rationale: annOverallRationale.value,
    };
    annSave.disabled = true;
    try {
      const res = await fetch(`/annotation/${run_id}/${encodeURIComponent(currentFn)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        toast("保存失败:" + (e.error || res.status), "error");
        return;
      }
      // Update local rows so the card re-render reflects the save
      const r = rows.find(x => x.filename === currentFn);
      if (r) {
        r.rubric_human_labeled = true;
        Object.keys(axes).forEach(k => {
          if (axes[k].stars) r.rubric_stars[k] = axes[k].stars;
        });
        if (annOverall.value) r.decision = annOverall.value;
      }
      const activeFilter = document.querySelector("#filters .pill.active").dataset.d;
      render(activeFilter);
      summary.n_human_labeled = (summary.n_human_labeled || 0) + (r && !rows._wasLabeled ? 1 : 0);
      if (thenAdvance) {
        // V14.5 — toast confirmation + smooth cross-fade to next.
        // The modal stays open the whole time; only the contents
        // morph, so the user keeps their flow without a page-jump.
        toast("已保存 ✓ — 加载下一张", "success", 1800);
        await openNextToLabel({ transition: true });
      } else {
        toast("已保存 ✓", "success", 1500);
        annModal.classList.remove("show");
      }
    } finally {
      annSave.disabled = false;
    }
  }

  async function openNextToLabel(opts = {}) {
    try {
      const res = await fetch(`/next_to_label/${run_id}`);
      const data = await res.json();
      if (data.done) {
        annModal.classList.remove("show");
        toast(data.message || "已标完本批所有图片 ✓", "success");
        return;
      }
      openAnnotation(data.filename, data.why, opts);
    } catch (e) {
      annModal.classList.remove("show");
      toast("active learning 队列失败:" + e, "error");
    }
  }

  // Wire up
  grid.addEventListener("click", e => {
    const btn = e.target.closest(".annotate-btn");
    if (btn) {
      e.stopPropagation();
      openAnnotation(btn.dataset.fn);
    }
  });
  annClose.addEventListener("click", () => annModal.classList.remove("show"));
  annNext.addEventListener("click", () => openNextToLabel());
  annSave.addEventListener("click", () => saveAnnotation(true));
  annModal.addEventListener("click", e => {
    if (e.target === annModal) annModal.classList.remove("show");
  });
  document.getElementById("annNextBtn").addEventListener("click", () => openNextToLabel());
  document.getElementById("kbdHelpBtn").addEventListener("click", () => showShortcuts());

  // V9.3 — CSV download is just a link
  const csvBtn = document.getElementById("csvBtn");
  csvBtn.href = `/scores_csv/${run_id}`;
  csvBtn.setAttribute("download", "");

  // V9.3 — batch label by score threshold
  document.getElementById("batchBtn").addEventListener("click", async () => {
    const keepThreshStr = prompt(
      "把 final score ≥ X 的全部标 keep,< Y 的全部标 cull (中间不动)。\n" +
      "格式: keep_min,cull_max  (例: 0.65,0.4)",
      "0.65,0.4"
    );
    if (!keepThreshStr) return;
    const parts = keepThreshStr.split(",").map(s => parseFloat(s.trim()));
    if (parts.length !== 2 || isNaN(parts[0]) || isNaN(parts[1])) {
      alert("格式错误,需要两个数字以逗号分隔。");
      return;
    }
    const [keepMin, cullMax] = parts;
    const keepRows = rows.filter(r => (r.score_final ?? -1) >= keepMin);
    const cullRows = rows.filter(r => (r.score_final ?? -1) > -1 && (r.score_final ?? 999) < cullMax);
    const ok = confirm(
      `批量打标:\n  ${keepRows.length} 张 → keep (score ≥ ${keepMin})\n` +
      `  ${cullRows.length} 张 → cull (score < ${cullMax})\n` +
      `共写 ${keepRows.length + cullRows.length} 个 annotation,会立刻反映到 UI。继续?`
    );
    if (!ok) return;
    // V10.1 — capture undo snapshot BEFORE mutating
    const snap = [];
    [...keepRows, ...cullRows].forEach(r => snap.push({
      filename: r.filename,
      prev_decision: r.decision,
      prev_human_labeled: r.rubric_human_labeled,
    }));
    pushUndo(snap);
    let n = 0;
    for (const [list, label] of [[keepRows, "keep"], [cullRows, "cull"]]) {
      for (const r of list) {
        try {
          await fetch(`/annotation/${run_id}/${encodeURIComponent(r.filename)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              axes: {},
              overall_label: label,
              overall_rationale: `batch: score ${label === 'keep' ? '≥' : '<'} ${label === 'keep' ? keepMin : cullMax}`,
            }),
          });
          r.rubric_human_labeled = true;
          r.decision = label;
          n++;
        } catch (e) { /* ignore */ }
      }
    }
    summary.n_human_labeled = (summary.n_human_labeled || 0) + n;
    showToast(`已批量标注 ${n} 张 · Cmd+Z 撤销`, "success");
    render();
  });

  // ==================================================================
  // V9.2 cluster compare modal — open via "⊞ 并排比较" on dividers
  // ==================================================================
  const cmpModal = document.getElementById("cmpModal");
  registerModal(cmpModal);  // V14.4 — ARIA dialog + focus trap
  const cmpTitle = document.getElementById("cmpTitle");
  const cmpMeta = document.getElementById("cmpMeta");
  const cmpBody = document.getElementById("cmpBody");
  const cmpClose = document.getElementById("cmpClose");

  function openCompare(clusterKey) {
    // Pull all rows in this cluster
    const members = rows.filter(r => {
      const ck = r.cluster_id == null ? `solo-${r.filename}` : `c${r.cluster_id}`;
      return ck === clusterKey;
    });
    if (members.length < 2) return;
    // Sort by score_final descending so best is first / left-most
    members.sort((a, b) => (b.score_final ?? 0) - (a.score_final ?? 0));
    const best = members[0];
    cmpTitle.textContent = `连拍组 ${clusterKey} (${members.length} 张)`;
    cmpMeta.textContent = `按 score_final 降序;左为最佳。空格键查看大图。`;

    const axisAbbr = {technical:"技", subject:"主", composition:"构",
                       light:"光", moment:"瞬", aesthetic:"美"};
    cmpBody.innerHTML = members.map(r => {
      const isBest = (r === best);
      const stars = ["technical","subject","composition","light","moment","aesthetic"].map(name => {
        const s = r.rubric_stars && r.rubric_stars[name];
        return `<div class="a">${axisAbbr[name]} ${s == null ? "--" : s.toFixed(1)}</div>`;
      }).join("");
      const dec = r.decision || "";
      return `
        <div class="cmp-cell ${isBest?'best':''}" data-fn="${r.filename}">
          <div class="img-wrap" data-full="/full/${run_id}/${encodeURIComponent(r.filename)}">
            <img src="/thumb/${run_id}/${encodeURIComponent(r.filename)}" alt="${r.filename}">
          </div>
          <div class="meta">
            <span class="fn" title="${r.filename}">${r.filename}</span>
            <div>
              <span class="badge ${dec}" style="font-size:9px;padding:1px 5px">${dec || '?'}</span>
              <span style="margin-left:6px">final ${r.score_final == null ? "--" : r.score_final.toFixed(2)}</span>
            </div>
            <div class="stars">${stars}</div>
            <button class="pick-btn" data-fn="${r.filename}">${isBest?'✓ 已选最佳':'选这张'}</button>
          </div>
        </div>
      `;
    }).join("");
    cmpModal.classList.add("show");

    // Click to zoom inside cmp
    cmpBody.querySelectorAll(".img-wrap").forEach(el => {
      el.addEventListener("click", () => {
        lbImg.src = el.dataset.full;
        lb.classList.add("show");
      });
    });
    // Pick handler — keep this one, cull the others
    cmpBody.querySelectorAll(".pick-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pickFn = btn.dataset.fn;
        const ok = confirm(`选 ${pickFn} 为最佳,其余 ${members.length - 1} 张标 cull?`);
        if (!ok) return;
        // V10.1 — undo snapshot
        pushUndo(members.map(m => ({
          filename: m.filename,
          prev_decision: m.decision,
          prev_human_labeled: m.rubric_human_labeled,
        })));
        for (const m of members) {
          const lbl = (m.filename === pickFn) ? "keep" : "cull";
          try {
            await fetch(`/annotation/${run_id}/${encodeURIComponent(m.filename)}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                axes: {},
                overall_label: lbl,
                overall_rationale: `cluster compare: ${lbl === 'keep' ? 'picked as best' : 'rejected sibling'}`,
              }),
            });
            const local = rows.find(x => x.filename === m.filename);
            if (local) {
              local.rubric_human_labeled = true;
              local.decision = lbl;
            }
          } catch (e) { /* ignore */ }
        }
        summary.n_human_labeled = (summary.n_human_labeled || 0) + members.length;
        cmpModal.classList.remove("show");
        showToast(`已选 ${pickFn},其余 ${members.length-1} 张标 cull · Cmd+Z 撤销`, "success");
        render();
      });
    });
  }

  // Wire compare buttons (inside cluster dividers — they're rebuilt
  // on each render(), so use event delegation on the grid).
  grid.addEventListener("click", e => {
    const btn = e.target.closest(".compare-btn");
    if (btn && btn.dataset.cluster) {
      openCompare(btn.dataset.cluster);
    }
  });
  cmpClose.addEventListener("click", () => cmpModal.classList.remove("show"));
  cmpModal.addEventListener("click", e => {
    if (e.target === cmpModal) cmpModal.classList.remove("show");
  });

  // XMP export — POST /export/<run_id>.
  // Two buttons:
  //   '下载 XMP zip'        → target=tmp,       always available
  //   '写到原图旁边'         → target=alongside,  only in scan mode
  const exportZipBtn = document.getElementById("exportZipBtn");
  const exportAlongsideBtn = document.getElementById("exportAlongsideBtn");
  const exportStatus = document.getElementById("exportStatus");

  if (summary.mode === "scan") {
    exportAlongsideBtn.style.display = "inline-block";
  }

  async function doExport(target, btn, successHtml) {
    btn.disabled = true;
    exportZipBtn.disabled = exportAlongsideBtn.disabled = true;
    exportStatus.textContent = "生成 XMP …";
    try {
      const res = await fetch(`/export/${run_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      const data = await res.json();
      exportStatus.innerHTML = successHtml(data);
    } catch (err) {
      exportStatus.textContent = "导出失败: " + (err.message || err);
    } finally {
      exportZipBtn.disabled = false;
      if (summary.mode === "scan") exportAlongsideBtn.disabled = false;
    }
  }

  exportZipBtn.addEventListener("click", () =>
    doExport("tmp", exportZipBtn, data =>
      `已生成 <b>${data.written}</b> 个 sidecar &nbsp;<a href="${data.zip_url}" download>下载 zip ↓</a>`
    )
  );
  exportAlongsideBtn.addEventListener("click", () => {
    if (!confirm(`将 ${summary.n_keep + summary.n_maybe + summary.n_cull} 个 .xmp 写到原图所在文件夹(${summary.origin_folder || "原位置"})?同名文件会被覆盖。`)) return;
    doExport("alongside", exportAlongsideBtn, data =>
      `已写入 <b>${data.written}</b> 个 .xmp 到原图旁边${data.skipped ? `,跳过 ${data.skipped} 个找不到原图的` : ''} · ${summary.origin_folder || ''}`
    );
  });
})();
</script>
</body>
</html>
"""


_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 存储管理</title>
  <style>
    :root {
      --bg: #111418;
      --bg-card: #1a1e24;
      --bg-card-hi: #232830;
      --fg: #e5e7eb;
      /* V14.2 — contrast bump */
      --muted: #a8b2c1;
      --border: #2a2f38;
      --accent: #3b82f6;
      --keep: #2ea84a;
      --maybe: #d9a30c;
      --cull: #d95050;
      --danger: #ef4444;
      --focus-ring: rgba(96,165,250,0.55);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
      font: 13px/1.5 "Inter", -apple-system, BlinkMacSystemFont,
            "Segoe UI Variable", "Segoe UI", "PingFang SC",
            "Microsoft Yahei UI", "Microsoft Yahei",
            "Helvetica Neue", sans-serif;
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
    <h1>存储管理 <a href="/">← 返回上传</a></h1>
    <div class="muted" id="rootHint">--</div>
  </header>
  <main>
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
"""


if __name__ == "__main__":
    main()
