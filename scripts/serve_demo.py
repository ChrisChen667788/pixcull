"""Web demo for PixCull: upload images → auto detect / sort / score.

This is the V1.2 user-facing demo. It complements ``scripts/serve_review.py``
(which compares pipeline output against a labeled golden set) by letting a
user drop in a *fresh* batch of images they've never labeled and see the
pipeline's keep / maybe / cull verdict in their browser.

Architecture (single-file, stdlib http.server only):

  GET   /                  upload page (HTML + drag-drop input)
  POST  /analyze           multipart upload of N images → returns {run_id}
                           (background thread starts the pipeline)
  GET   /status/<run_id>   JSON {state, done, total, message}
  GET   /results/<run_id>  rendered HTML grid of decisions for that run
  POST  /export/<run_id>   write XMP sidecars next to uploaded images
                           → JSON {written, paths_zip_url} (V1.2)
  GET   /xmp_zip/<run_id>  download all sidecars as a single .zip
  GET   /thumb/<run_id>/<filename>  thumbnail (lazy-built, cached on disk)
  GET   /full/<run_id>/<filename>   full-size preview

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
import socket
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

_DEFAULT_PORT = 8770
_FALLBACK_PORTS = (8770, 8771, 8772, 9322, 7799)
_DEMO_ROOT = Path("/tmp/pixcull_demo")  # base dir for upload + output trees
_THUMB_SIZE = 420
_FULL_SIZE = 1600
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB safety cap per request


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
) -> None:
    """Worker thread: run the pipeline on the run's input dir.

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
    input_dir = Path(run["input_dir"])
    output_dir = Path(run["output_dir"])

    def progress_cb(done: int, total: int, message: str) -> None:
        _set_run(run_id, done=done, total=total, message=message)

    _set_run(run_id, state="running", started_at=time.time())
    try:
        run_pipeline(
            input_dir,
            output_dir,
            rescorer_mode=rescorer_mode,
            rescorer_path=rescorer_path,
            progress_cb=progress_cb,
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
    run = _get_run(run_id)
    if run is None:
        return None
    output_dir = Path(run["output_dir"])
    scores_path = output_dir / "scores.csv"
    if not scores_path.exists():
        return None

    import pandas as pd  # local import to keep startup light

    df = pd.read_csv(scores_path)

    rows: list[dict] = []
    for _, r in df.iterrows():
        fn = str(r["filename"])
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
            "rescorer_pred": (
                str(r.get("rescorer_pred"))
                if "rescorer_pred" in df.columns
                and r.get("rescorer_pred") not in (None, "", float("nan"))
                and str(r.get("rescorer_pred")) != "nan"
                else None
            ),
            "rescorer_prob_keep": _f(r.get("rescorer_prob_keep"))
            if "rescorer_prob_keep" in df.columns else None,
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
    summary = {
        "n_total": len(rows),
        "n_keep": counts.get("keep", 0),
        "n_maybe": counts.get("maybe", 0),
        "n_cull": counts.get("cull", 0),
        "rescorer_active": len(rescored) > 0,
        "rescorer_n_scored": len(rescored),
        "rescorer_n_disagrees": len(disagrees),
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
# HTTP handler.
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "PixCullDemo/1.2"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            return self._serve_upload_page()
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
        self.send_error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/analyze":
            return self._handle_analyze_post()
        if path.startswith("/export/"):
            return self._handle_export(path[len("/export/"):])
        self.send_error(404, "not found")

    # --- handlers ----------------------------------------------------------
    def _serve_upload_page(self) -> None:
        body = _UPLOAD_HTML.encode("utf-8")
        self._send_html(200, body)

    def _handle_analyze_post(self) -> None:
        # Read multipart payload
        clen = int(self.headers.get("Content-Length", "0") or "0")
        if clen <= 0 or clen > _MAX_UPLOAD_BYTES:
            self.send_error(413, f"upload too large or empty: {clen} bytes")
            return
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self.send_error(400, "expected multipart/form-data")
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
            self.send_error(400, f"multipart parse failed: {exc}")
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
        if "files" in form:
            files = form["files"]
            items = files if isinstance(files, list) else [files]
            for item in items:
                fn = getattr(item, "filename", None) or ""
                if not fn:
                    continue
                # Strip any path components from the upload filename
                safe_name = Path(fn).name
                if Path(safe_name).suffix.lower() not in ok_exts:
                    continue
                dst = input_dir / safe_name
                with open(dst, "wb") as f:
                    f.write(item.file.read())
                n_saved += 1

        if n_saved == 0:
            self.send_error(400, "no usable images in upload")
            return

        rescorer_mode = self.server.rescorer_mode  # type: ignore[attr-defined]
        rescorer_path = self.server.rescorer_path  # type: ignore[attr-defined]

        _set_run(
            run_id,
            state="queued",
            done=0,
            total=n_saved,
            message=f"已收到 {n_saved} 张图,正在排队…",
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            n_uploaded=n_saved,
        )
        threading.Thread(
            target=_analyze_in_background,
            args=(run_id, rescorer_mode, rescorer_path),
            daemon=True,
        ).start()

        body = json.dumps({"run_id": run_id, "n": n_saved}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            self.send_error(
                404,
                "no scores.csv yet — run not finished or invalid run_id",
            )
            return
        rows, summary = result
        payload = {"run_id": run_id, "rows": rows, "summary": summary}
        html = _RESULTS_HTML.replace(
            "__PAYLOAD__",
            json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
        )
        self._send_html(200, html.encode("utf-8"))

    def _serve_image(self, rel: str, size: int) -> None:
        # Format: <run_id>/<filename>
        rel = unquote(rel)
        if "/" not in rel:
            self.send_error(400, "expected run_id/filename")
            return
        run_id, fn = rel.split("/", 1)
        run = _get_run(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        src = Path(run["input_dir"]) / Path(fn).name
        if not src.exists():
            self.send_error(404, f"not found: {fn}")
            return

        cache_dir = Path(run["output_dir"]) / "thumbs"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{src.name}.{size}.jpg"
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

        Output sits in ``<run_id>/xmp/<filename>.xmp`` (alongside the
        thumbnail cache, never overwriting the original uploads). The
        response includes a count + the URL of a zip bundle so the
        browser can download all sidecars at once.
        """
        run = _get_run(run_id)
        if run is None:
            self.send_error(404, "no such run")
            return
        if run.get("state") != "done":
            self.send_error(409, "run not finished yet")
            return

        result = _build_results(run_id)
        if result is None:
            self.send_error(500, "no results to export")
            return
        rows, _ = result

        from pixcull.io.xmp import write_xmp, decision_to_xmp

        input_dir = Path(run["input_dir"])
        output_dir = Path(run["output_dir"])
        xmp_dir = output_dir / "xmp"
        xmp_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        per_decision: Counter[str] = Counter()
        for r in rows:
            fn = r["filename"]
            decision = r["decision"]
            stars, label = decision_to_xmp(decision)
            # Use a "virtual" image_path inside xmp_dir so write_xmp's
            # with_suffix(.xmp) lands the file there rather than next to
            # the upload (we never modify the user's original uploads —
            # that's a privacy/safety boundary).
            virtual = xmp_dir / Path(fn).name
            write_xmp(virtual, stars, label)
            written += 1
            per_decision[decision] += 1

        body = json.dumps({
            "written": written,
            "per_decision": dict(per_decision),
            "zip_url": f"/xmp_zip/{run_id}",
            "xmp_dir": str(xmp_dir),
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_xmp_zip(self, run_id: str) -> None:
        """Stream all sidecars + a README into a single zip download."""
        import zipfile

        run = _get_run(run_id)
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

    # --- utilities ---------------------------------------------------------
    def _send_html(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


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
    args = parser.parse_args()

    _DEMO_ROOT.mkdir(parents=True, exist_ok=True)

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
# HTML — kept inline for single-file shippability. Two pages:
#   _UPLOAD_HTML   GET /          drag-drop + status panel
#   _RESULTS_HTML  GET /results/  decision grid (data inlined as __PAYLOAD__)
# ---------------------------------------------------------------------------
_UPLOAD_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — 一键分拣</title>
  <style>
    :root {
      --bg: #111418;
      --bg-card: #1a1e24;
      --fg: #e5e7eb;
      --muted: #8892a0;
      --border: #2a2f38;
      --accent: #3b82f6;
      --keep: #2ea84a;
      --maybe: #d9a30c;
      --cull: #d95050;
      --error: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: var(--bg); color: var(--fg);
      font: 14px/1.5 -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
      display: flex; flex-direction: column; align-items: center;
      padding: 60px 20px 40px;
    }
    h1 { margin: 0 0 6px; font-size: 22px; font-weight: 600; }
    .subtitle { color: var(--muted); margin-bottom: 28px; max-width: 540px; text-align: center; }
    .card {
      width: 100%; max-width: 600px; background: var(--bg-card);
      border: 1px solid var(--border); border-radius: 10px; padding: 24px;
    }
    .drop-zone {
      border: 2px dashed var(--border); border-radius: 8px;
      padding: 40px 20px; text-align: center;
      cursor: pointer; transition: border-color 0.15s, background 0.15s;
    }
    .drop-zone:hover, .drop-zone.dragover {
      border-color: var(--accent); background: rgba(59, 130, 246, 0.08);
    }
    .drop-zone .big { font-size: 28px; margin-bottom: 10px; opacity: 0.7; }
    .drop-zone .hint { color: var(--muted); font-size: 12px; margin-top: 8px; }
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
      background: var(--accent); color: white; border: 0;
      padding: 10px 20px; font-size: 13px; font-weight: 500;
      border-radius: 6px; cursor: pointer;
    }
    button:disabled { opacity: 0.4; cursor: not-allowed; }
    button.secondary { background: transparent; color: var(--muted); border: 1px solid var(--border); }
    .status { margin-top: 18px; padding: 14px; border-radius: 6px;
              background: rgba(255,255,255,0.03); border: 1px solid var(--border);
              display: none; }
    .status.show { display: block; }
    .status .label { color: var(--muted); font-size: 11px;
                     text-transform: uppercase; letter-spacing: 0.5px;
                     margin-bottom: 6px; }
    .progress {
      height: 6px; background: var(--border); border-radius: 3px;
      overflow: hidden; margin-top: 10px;
    }
    .progress-bar {
      height: 100%; background: var(--accent); width: 0%;
      transition: width 0.3s; border-radius: 3px;
    }
    .progress-bar.error { background: var(--error); }
    .progress-bar.done { background: var(--keep); }
    a.results-link {
      display: inline-block; margin-top: 12px;
      color: var(--accent); text-decoration: none;
      font-weight: 500;
    }
    a.results-link:hover { text-decoration: underline; }
    .footer {
      margin-top: 36px; color: var(--muted); font-size: 11px;
      text-align: center; max-width: 600px; line-height: 1.6;
    }
    .footer code {
      background: rgba(255,255,255,0.06);
      padding: 1px 6px; border-radius: 3px;
    }
  </style>
</head>
<body>
  <h1>PixCull</h1>
  <div class="subtitle">
    上传一批照片,自动判断 <span style="color:var(--keep)">●keep</span>
    / <span style="color:var(--maybe)">●maybe</span>
    / <span style="color:var(--cull)">●cull</span>,并给出场景与各维度评分。
  </div>

  <div class="card">
    <div class="drop-zone" id="dropZone">
      <div class="big">⇪</div>
      <div>拖拽照片到这里,或<u>点击选择</u></div>
      <div class="hint">支持 JPG / PNG / RAW (CR3/CR2/NEF/ARW/DNG)</div>
    </div>
    <input id="fileInput" type="file" multiple accept=".jpg,.jpeg,.png,.cr3,.cr2,.nef,.arw,.dng,.tif,.tiff" style="display:none">
    <div class="file-list" id="fileList" style="display:none"></div>

    <div class="actions">
      <button id="uploadBtn" disabled>开始分析</button>
      <button id="clearBtn" class="secondary">清空</button>
      <span id="hint" style="color:var(--muted);font-size:12px"></span>
    </div>

    <div class="status" id="status">
      <div class="label" id="stateLabel">就绪</div>
      <div id="message">--</div>
      <div class="progress"><div class="progress-bar" id="progressBar"></div></div>
      <a class="results-link" id="resultsLink" style="display:none">查看结果 →</a>
    </div>
  </div>

  <div class="footer">
    本地服务,所有数据存在 <code>/tmp/pixcull_demo/&lt;run_id&gt;/</code>,
    页面关掉就没了。第一次跑某种照片时模型加载需 ~10 秒,后续每张约 2-10 秒。
  </div>

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

  function refreshList() {
    if (!pickedFiles.length) {
      fileList.style.display = "none";
      uploadBtn.disabled = true;
      hint.textContent = "";
      return;
    }
    fileList.style.display = "block";
    fileList.innerHTML = pickedFiles.map(f =>
      `<div class="item">• ${f.name} <span style="opacity:0.5">(${(f.size/1024).toFixed(0)} KB)</span></div>`
    ).join("");
    uploadBtn.disabled = false;
    hint.textContent = `${pickedFiles.length} 张已选`;
  }

  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", e => {
    pickedFiles = pickedFiles.concat(Array.from(e.target.files));
    refreshList();
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach(ev =>
    dropZone.addEventListener(ev, e => {
      e.preventDefault(); dropZone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach(ev =>
    dropZone.addEventListener(ev, e => {
      e.preventDefault(); dropZone.classList.remove("dragover");
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

  uploadBtn.addEventListener("click", async () => {
    if (!pickedFiles.length) return;
    uploadBtn.disabled = true;
    clearBtn.disabled = true;
    statusEl.classList.add("show");
    stateLabel.textContent = "上传中";
    messageEl.textContent = `正在上传 ${pickedFiles.length} 张图片…`;
    progressBar.style.width = "5%";
    progressBar.classList.remove("error", "done");

    const fd = new FormData();
    pickedFiles.forEach(f => fd.append("files", f));

    let runId = null;
    try {
      const res = await fetch("/analyze", { method: "POST", body: fd });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${await res.text()}`);
      }
      const data = await res.json();
      runId = data.run_id;
    } catch (err) {
      stateLabel.textContent = "上传失败";
      messageEl.textContent = String(err);
      progressBar.classList.add("error");
      progressBar.style.width = "100%";
      uploadBtn.disabled = false;
      clearBtn.disabled = false;
      return;
    }

    stateLabel.textContent = "分析中";
    pollStatus(runId);
  });

  async function pollStatus(runId) {
    let stalled = 0;
    let lastDone = 0;
    while (true) {
      let s;
      try {
        const res = await fetch(`/status/${runId}`);
        s = await res.json();
      } catch (e) {
        await new Promise(r => setTimeout(r, 1500));
        continue;
      }

      messageEl.textContent = s.message || "处理中…";
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
      --bg: #111418;
      --bg-card: #1a1e24;
      --bg-card-hi: #232830;
      --fg: #e5e7eb;
      --muted: #8892a0;
      --border: #2a2f38;
      --keep: #2ea84a;
      --maybe: #d9a30c;
      --cull: #d95050;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--bg); color: var(--fg);
      font: 13px/1.45 -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
    }
    header {
      position: sticky; top: 0; z-index: 5;
      background: rgba(17, 20, 24, 0.92);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 14px 20px 12px;
    }
    h1 { font-size: 15px; margin: 0 0 8px; font-weight: 600; }
    h1 a { color: var(--muted); text-decoration: none; font-weight: 400; margin-left: 12px; }
    h1 a:hover { color: var(--fg); }
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
      border-radius: 6px; overflow: hidden;
      display: flex; flex-direction: column;
    }
    .card.keep { border-left: 3px solid var(--keep); }
    .card.maybe { border-left: 3px solid var(--maybe); }
    .card.cull { border-left: 3px solid var(--cull); opacity: 0.75; }
    .card .thumb {
      width: 100%; aspect-ratio: 4/3; object-fit: cover;
      background: #000; cursor: zoom-in;
    }
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
      font-family: ui-monospace, monospace;
    }
    .row1 .rs.dis { background: var(--maybe); color: white; }
    .row2 { display: flex; align-items: center; justify-content: space-between;
            margin-top: 4px; font-size: 11px; color: var(--muted); }
    .row2 .scene { color: var(--fg); }
    .row3 {
      display: grid; grid-template-columns: repeat(4, 1fr);
      gap: 4px; margin-top: 6px; font-size: 10px;
    }
    .row3 .dim { background: rgba(255,255,255,0.04); padding: 2px 4px; border-radius: 2px; }
    .row3 .dim .k { color: var(--muted); }
    .row3 .dim .v { color: var(--fg); font-weight: 600; margin-left: 2px; }
    .row4 { font-size: 10px; color: var(--muted); margin-top: 6px;
            text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }
    .lightbox {
      position: fixed; inset: 0; background: rgba(0,0,0,0.92);
      display: none; align-items: center; justify-content: center; z-index: 9;
      cursor: zoom-out;
    }
    .lightbox.show { display: flex; }
    .lightbox img { max-width: 95vw; max-height: 95vh; }
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
      <span style="flex:1"></span>
      <button class="export-btn" id="exportBtn" title="导出 XMP 评级 (Lightroom / Capture One)">导出 XMP ▾</button>
      <span class="export-status" id="exportStatus"></span>
    </div>
  </header>
  <div class="grid" id="grid"></div>
  <div class="lightbox" id="lightbox"><img id="lbImg" alt=""></div>

<script>
(() => {
  const PAYLOAD = __PAYLOAD__;
  const { run_id, rows, summary } = PAYLOAD;

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
  statsEl.innerHTML = stats.join("");

  // Grid
  const grid = document.getElementById("grid");
  function render(filter) {
    const filtered = filter === "all" ? rows : rows.filter(r => r.decision === filter);
    grid.innerHTML = filtered.map(r => {
      const thumb = `/thumb/${run_id}/${encodeURIComponent(r.filename)}`;
      const full = `/full/${run_id}/${encodeURIComponent(r.filename)}`;
      const dim = (k, v) => v == null
        ? `<div class="dim"><span class="k">${k}</span><span class="v">--</span></div>`
        : `<div class="dim"><span class="k">${k}</span><span class="v">${v.toFixed(2)}</span></div>`;
      const reasonShort = r.reason && r.reason.length > 60
        ? r.reason.slice(0, 60) + "…" : r.reason;
      // V1.2 shadow-mode badge: shows the rescorer's verdict + P(keep) when
      // present. Disagrees-with-rule cases get a yellow ring so they pop.
      let rescorerBadge = "";
      if (r.rescorer_pred) {
        const dis = r.rescorer_pred !== r.decision;
        const probTxt = r.rescorer_prob_keep == null ? "--" :
          r.rescorer_prob_keep.toFixed(2);
        rescorerBadge = `<span class="rs ${dis ? 'dis' : ''}" title="V1.1 rescorer: ${r.rescorer_pred} (P=${probTxt})">${r.rescorer_pred==='keep'?'✓':'?'} ${probTxt}</span>`;
      }
      return `
        <div class="card ${r.decision}">
          <img class="thumb" src="${thumb}" data-full="${full}" loading="lazy" alt="${r.filename}">
          <div class="body">
            <div class="row1">
              <span class="badge ${r.decision}">${r.decision}</span>
              <span class="fn" title="${r.filename}">${r.filename}</span>
              ${rescorerBadge}
            </div>
            <div class="row2">
              <span class="scene">${r.scene || "?"}</span>
              <span>final ${r.score_final == null ? "--" : r.score_final.toFixed(2)}</span>
            </div>
            <div class="row3">
              ${dim("锐度", r.score_sharpness)}
              ${dim("曝光", r.score_exposure)}
              ${dim("构图", r.score_composition)}
              ${dim("美感", r.score_aesthetic)}
            </div>
            <div class="row4" title="${(r.reason || '').replace(/"/g,'&quot;')}">${reasonShort || ""}</div>
          </div>
        </div>
      `;
    }).join("") || `<div style="color:var(--muted);padding:20px">没有符合的图片</div>`;
  }
  render("all");

  // Filter pills
  document.querySelectorAll("#filters .pill").forEach(el => {
    el.addEventListener("click", () => {
      document.querySelectorAll("#filters .pill").forEach(x => x.classList.remove("active"));
      el.classList.add("active");
      render(el.dataset.d);
    });
  });

  // Lightbox
  const lb = document.getElementById("lightbox");
  const lbImg = document.getElementById("lbImg");
  grid.addEventListener("click", e => {
    const t = e.target;
    if (t.tagName === "IMG" && t.classList.contains("thumb")) {
      lbImg.src = t.dataset.full;
      lb.classList.add("show");
    }
  });
  lb.addEventListener("click", () => lb.classList.remove("show"));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") lb.classList.remove("show");
  });

  // XMP export — POST /export/<run_id>, then offer the zip URL.
  const exportBtn = document.getElementById("exportBtn");
  const exportStatus = document.getElementById("exportStatus");
  exportBtn.addEventListener("click", async () => {
    exportBtn.disabled = true;
    exportStatus.textContent = "生成 XMP …";
    try {
      const res = await fetch(`/export/${run_id}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      exportStatus.innerHTML = `已生成 <b>${data.written}</b> 个 sidecar &nbsp;`
        + `<a href="${data.zip_url}" download>下载 zip ↓</a>`;
    } catch (err) {
      exportStatus.textContent = "导出失败: " + err;
    } finally {
      exportBtn.disabled = false;
    }
  });
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
