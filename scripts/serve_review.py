"""Local web viewer for PixCull pipeline output on a labeled golden set.

Purpose (V1.0, see eval_findings.md §V1.0): V0.9 concluded the rule-based
layer has hit its ceiling at 66.4%/87.5% on a 128-photo golden set. The
concrete V1.0 path is to grow labels past ~500 and train a rescorer. To
collect labels efficiently the user needs to eyeball pipeline decisions
against their own memory of each shot — a per-image review UI, not a
spreadsheet.

What this ships:
  - Grid of every analyzed image with pipeline decision + GT label
  - Color-coded match / mismatch indicators
  - Per-photo: scores, flags, photographer's notes
  - Filter by decision, scene, match status, scene-classifier disagreement
  - Click to zoom (full-size from the original or RAW-decoded preview)

Design choices:
  - stdlib http.server only. FastAPI/Flask aren't in the pipeline's venv
    and adding them for a local viewer is overkill.
  - Thumbnails generated lazily through `pixcull.io.loader.load_image`
    (handles CR3 via embedded JPEG) and cached to disk.
  - Everything served over localhost on an uncommon port (default 8765)
    to avoid clashing with the user's other dev servers. See
    `_pick_port()` for auto-fallback.
  - Data is embedded as JSON in the HTML — no separate /api endpoints.
    The page is a 300-row dataset, not an application; we don't need SPA
    plumbing.

Usage:
    python scripts/serve_review.py tests/fixtures/
    python scripts/serve_review.py tests/fixtures/ --port 9321 --no-open
"""

from __future__ import annotations

import argparse
import io
import json
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
import pandas as pd
from PIL import Image

from pixcull.io.loader import load_image

# Port 8765 is uncommon (not in the Node / Vite / Django / Flask / Jupyter
# defaults the user likely has running). If busy we scan the next few.
_DEFAULT_PORT = 8765
_FALLBACK_PORTS = (8765, 8766, 8767, 9321, 7788)

_THUMB_SIZE = 420       # card display is ~200px; 420 is retina-ready
_FULL_SIZE = 1600       # lightbox-quality
_LABELS = ("keep", "maybe", "cull")

# V1.1 integration: load the learned rescorer artifact if present and
# display its predictions alongside the rule decisions. Not wired into
# runtime decide — this is display-only, the A/B validation surface the
# user needs before V1.2 runtime integration ships.
_REPO_ROOT = Path(__file__).parent.parent
_RESCORER_PATH = _REPO_ROOT / "models" / "rescorer_v1.joblib"
_TRAINING_CSV = _REPO_ROOT / "training.csv"

# V1.2 trigger thresholds — kept in lock-step with
# scripts/check_v1_2_trigger.py and eval_findings.md V1.1 §"Decision".
_GATE_MIN_ROWS = 400
_GATE_MIN_LANDSCAPE_AUC = 0.70
_GATE_MIN_DELTA_ACC = 0.03


def _pick_port() -> int:
    """Return the first free port from the fallback list, else raise."""
    for p in _FALLBACK_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(
        f"All preferred ports busy: {_FALLBACK_PORTS}. Pass --port to choose."
    )


def _load_rescorer_artifact(path: Path) -> dict | None:
    """Load the V1.1 rescorer joblib if present. Returns None on any error.

    Errors are intentionally swallowed: the viewer stays useful on machines
    that never trained a rescorer, and a stale/incompatible joblib just
    hides the rescorer UI instead of crashing the server.
    """
    if not path.exists():
        return None
    try:
        import joblib
        art = joblib.load(path)
        # Sanity: required keys
        if "pipeline" not in art or "feature_cols" not in art:
            print(f"  [rescorer] {path.name} missing keys — skipping", file=sys.stderr)
            return None
        return art
    except Exception as exc:  # numpy pickle drift, sklearn version drift, …
        print(f"  [rescorer] failed to load {path.name}: {exc}", file=sys.stderr)
        return None


def _apply_rescorer(scores_df: pd.DataFrame,
                    artifact: dict) -> pd.DataFrame:
    """Return a DataFrame keyed by filename with rescorer pred + prob.

    The rescorer only adjudicates keep-vs-maybe (cull is a hard-flag
    concern); but to keep the display simple we score every row, and the
    frontend decides whether to show the prediction given the rule
    decision.
    """
    # Reuse the feature builder from train_rescorer.py so the "missing"
    # indicator columns end up exactly as at training time.
    sys.path.insert(0, str(Path(__file__).parent))
    from train_rescorer import build_feature_matrix  # type: ignore

    aug, _present = build_feature_matrix(scores_df)
    X = aug[artifact["feature_cols"]]
    pipe = artifact["pipeline"]
    proba = pipe.predict_proba(X)[:, 1]  # P(keep)
    pred = pipe.predict(X)
    return pd.DataFrame({
        "filename": aug["filename"].values,
        "rescorer_pred": ["keep" if p == 1 else "maybe" for p in pred],
        "rescorer_prob_keep": [round(float(p), 3) for p in proba],
    })


def _compute_gate_status(training_csv: Path,
                         scores_csv: Path) -> dict:
    """V1.2 ship gate: three conditions, each a bool.

    Recomputes the same three checks as scripts/check_v1_2_trigger.py,
    inlined here so the viewer header can show a live banner. Heavy
    (~10–20s) — caller decides whether to skip.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from train_rescorer import (  # type: ignore
        build_feature_matrix, build_pipeline, cv_report, rule_baseline_score,
    )
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    out: dict = {
        "available": False,
        "rows": None, "rows_gate": False,
        "landscape_auc": None, "landscape_gate": False,
        "delta_acc": None, "delta_gate": False,
        "all_green": False,
        "computed_at": None,
        "computation_seconds": None,
    }

    if not training_csv.exists():
        return out
    t0 = time.time()
    try:
        raw = pd.read_csv(training_csv)
    except Exception:
        return out
    out["rows"] = int(len(raw))
    out["rows_gate"] = out["rows"] >= _GATE_MIN_ROWS

    sub = raw[raw["manual_label"].isin(["keep", "maybe"])].copy()
    if len(sub) < 30:
        out["computed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        out["computation_seconds"] = round(time.time() - t0, 2)
        return out
    df, feature_cols = build_feature_matrix(sub)
    numeric_cols = [c for c in feature_cols if c != "scene"]
    categorical_cols = ["scene"] if "scene" in feature_cols else []
    X = df[feature_cols]
    y_binary = (df["manual_label"] == "keep").astype(int).values
    scenes = df["scene"].fillna("unknown")

    # Global 5-fold GBM CV
    pipe = build_pipeline(numeric_cols, categorical_cols, model="gbm")
    metrics, _, _ = cv_report(pipe, X, y_binary, scenes, cv=5, seed=42)
    global_acc = metrics["accuracy"]
    out["available"] = True

    # Landscape-only sweep
    ls_mask = (scenes == "landscape").values
    n_keep_ls = int(y_binary[ls_mask].sum())
    n_maybe_ls = int(ls_mask.sum() - n_keep_ls)
    if n_keep_ls >= 3 and n_maybe_ls >= 3:
        try:
            ls_pipe = build_pipeline(numeric_cols, categorical_cols, model="gbm")
            skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
            proba = cross_val_predict(ls_pipe, X.iloc[ls_mask], y_binary[ls_mask],
                                      cv=skf, n_jobs=-1, method="predict_proba")[:, 1]
            out["landscape_auc"] = round(float(roc_auc_score(y_binary[ls_mask], proba)), 3)
            out["landscape_gate"] = out["landscape_auc"] >= _GATE_MIN_LANDSCAPE_AUC
        except Exception:
            pass

    # Rule baseline on same non-cull rows
    if scores_csv.exists():
        try:
            runs = pd.read_csv(scores_csv)[["filename", "decision"]]
            merged = df[["filename", "manual_label"]].merge(runs, on="filename", how="left")
            non_cull = merged[merged["decision"].isin(["keep", "maybe"])]
            if len(non_cull):
                rm = rule_baseline_score(non_cull["decision"], non_cull["manual_label"])
                delta = global_acc - rm["accuracy"]
                out["delta_acc"] = round(float(delta), 3)
                out["delta_gate"] = delta >= _GATE_MIN_DELTA_ACC
        except Exception:
            pass

    out["all_green"] = (out["rows_gate"] and out["landscape_gate"]
                       and out["delta_gate"])
    out["computed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    out["computation_seconds"] = round(time.time() - t0, 2)
    return out


def _build_dataset(golden_dir: Path) -> tuple[list[dict], dict, Path]:
    """Merge GT + scores.csv, compute per-photo metadata and a summary.

    Returns (rows, summary, images_root).
    """
    gt_path = golden_dir / "ground_truth.csv"
    scores_path = golden_dir / "_eval_output" / "scores.csv"
    images_root = golden_dir / "images"

    if not gt_path.exists():
        sys.exit(f"ERROR: {gt_path} not found")
    if not scores_path.exists():
        sys.exit(
            f"ERROR: {scores_path} not found — run "
            f"scripts/eval_on_golden_set.py first."
        )
    if not images_root.exists():
        sys.exit(f"ERROR: {images_root} not found")

    gt = pd.read_csv(gt_path, comment="#")
    gt = gt[gt["manual_label"].isin(_LABELS)].copy()
    gt = gt.rename(columns={"scene": "gt_scene"})
    scores = pd.read_csv(scores_path)

    # Map filename → absolute path on disk (images live in scene subfolders)
    index: dict[str, Path] = {}
    for p in images_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in (
            ".jpg", ".jpeg", ".png", ".cr3", ".cr2", ".nef", ".arw", ".dng"
        ):
            index[p.name] = p.resolve()

    df = scores.merge(gt[["filename", "gt_scene", "manual_label", "notes"]],
                      on="filename", how="left")

    # V1.1 integration: apply the learned rescorer to every row (display-only)
    artifact = _load_rescorer_artifact(_RESCORER_PATH)
    if artifact is not None:
        try:
            rescorer_df = _apply_rescorer(scores, artifact)
            df = df.merge(rescorer_df, on="filename", how="left")
        except Exception as exc:
            print(f"  [rescorer] apply failed: {exc}", file=sys.stderr)
            df["rescorer_pred"] = None
            df["rescorer_prob_keep"] = None
    else:
        df["rescorer_pred"] = None
        df["rescorer_prob_keep"] = None

    df = df.sort_values(["manual_label", "gt_scene", "filename"], na_position="last")

    rows: list[dict] = []
    for _, r in df.iterrows():
        fn = str(r["filename"])
        abs_path = index.get(fn)
        if abs_path is None:
            continue
        decision = str(r.get("decision", "") or "")
        gt_label = str(r.get("manual_label", "") or "")
        match = (decision == gt_label) if gt_label else None
        # within-one: cull↔keep mismatches are the "2-class-distance" errors
        big_miss = bool(
            gt_label and decision and (
                (gt_label == "keep" and decision == "cull")
                or (gt_label == "cull" and decision == "keep")
            )
        )
        # V1.1 rescorer fields. Only meaningful when the rule decision is
        # non-cull — cull rows go through the hard-flag layer which the
        # rescorer doesn't touch. Leave as None on cull rows so the frontend
        # can hide the display.
        rp = r.get("rescorer_pred")
        if decision == "cull" or rp is None or (isinstance(rp, float) and np.isnan(rp)):
            rescorer_pred: str | None = None
            rescorer_prob_keep: float | None = None
            rescorer_disagrees = False
        else:
            rescorer_pred = str(rp)
            rescorer_prob_keep = _f(r.get("rescorer_prob_keep"))
            rescorer_disagrees = (rescorer_pred != decision)

        rows.append({
            "filename": fn,
            "pipeline_scene": str(r.get("scene", "") or ""),
            "gt_scene": str(r.get("gt_scene", "") or ""),
            "decision": decision,
            "gt_label": gt_label,
            "match": match,
            "big_miss": big_miss,
            "score_final": _f(r.get("score_final")),
            "score_sharpness": _f(r.get("score_sharpness")),
            "score_exposure": _f(r.get("score_exposure")),
            "score_aesthetic": _f(r.get("score_aesthetic")),
            "score_composition": _f(r.get("score_composition")),
            "clipiqa": _f(r.get("clipiqa")),
            "laion_aes": _f(r.get("laion_aes")),
            "flags": str(r.get("flags", "") or ""),
            "reason": str(r.get("reason", "") or ""),
            "notes": str(r.get("notes", "") or ""),
            "scene_mismatch": (
                bool(r.get("scene") and r.get("gt_scene")
                     and r["scene"] != r["gt_scene"])
            ),
            "rescorer_pred": rescorer_pred,
            "rescorer_prob_keep": rescorer_prob_keep,
            "rescorer_disagrees": rescorer_disagrees,
        })

    # Summary for the header strip
    labeled = [r for r in rows if r["gt_label"]]
    n = len(labeled)
    exact = sum(1 for r in labeled if r["match"])
    big = sum(1 for r in labeled if r["big_miss"])
    within_one = n - big
    cull_pred = [r for r in labeled if r["decision"] == "cull"]
    cull_tp = sum(1 for r in cull_pred if r["gt_label"] == "cull")

    # Rescorer summary: how many non-cull rows have a prediction, how many
    # disagree with the rule. Surfaces the V1.1 A/B gap in one line.
    rescored = [r for r in rows if r["rescorer_pred"] is not None]
    disagrees = [r for r in rescored if r["rescorer_disagrees"]]

    summary = {
        "n_total": len(rows),
        "n_labeled": n,
        "exact": exact,
        "exact_pct": round(100 * exact / n, 1) if n else 0.0,
        "within_one_pct": round(100 * within_one / n, 1) if n else 0.0,
        "cull_precision": round(cull_tp / len(cull_pred), 2) if cull_pred else 0.0,
        "n_cull_pred": len(cull_pred),
        "n_cull_correct": cull_tp,
        "rescorer_active": artifact is not None,
        "rescorer_n_scored": len(rescored),
        "rescorer_n_disagrees": len(disagrees),
        "rescorer_pct_disagrees": (
            round(100 * len(disagrees) / len(rescored), 1) if rescored else 0.0
        ),
        "gate_status": None,   # filled in by caller — see main()
    }
    return rows, summary, images_root


def _f(v: object) -> float | None:
    """Coerce to float or None for NaN/empty."""
    try:
        x = float(v)  # type: ignore[arg-type]
        if x != x:  # NaN
            return None
        return round(x, 3)
    except (TypeError, ValueError):
        return None


class _Handler(BaseHTTPRequestHandler):
    rows: list[dict]
    summary: dict
    images_root: Path
    cache_dir: Path
    by_name: dict[str, Path]

    def log_message(self, fmt: str, *args: object) -> None:
        # Silence the per-request access log; we only care about errors.
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
        path = urlparse(self.path).path
        if path == "/":
            return self._serve_index()
        if path.startswith("/thumb/"):
            return self._serve_image(path[len("/thumb/"):], _THUMB_SIZE)
        if path.startswith("/full/"):
            return self._serve_image(path[len("/full/"):], _FULL_SIZE)
        self.send_error(404)

    def _serve_index(self) -> None:
        payload = {"rows": self.rows, "summary": self.summary}
        html = _HTML_TEMPLATE.replace(
            "__PAYLOAD__",
            json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
        )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_image(self, filename: str, size: int) -> None:
        fn = unquote(filename)
        src = self.by_name.get(fn)
        if src is None:
            self.send_error(404, f"not in index: {fn}")
            return
        # V26 — cache key bump (v2) parallels serve_demo: the display
        # loader gives sharper RAW previews at sizes ≥ 1600, so old
        # caches built from the analysis loader are invalidated.
        cache_name = f"{fn}.{size}.v2.jpg"
        cache_path = self.cache_dir / cache_name
        if not cache_path.exists():
            # V26: route large requests to the quality-preserving loader.
            if size >= 1600:
                from pixcull.io.loader import load_image_for_display
                img = load_image_for_display(src, max_side=size)
            else:
                img = load_image(src, max_side=size)
            if img is None:
                self.send_error(500, "image decode failed")
                return
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Reduce JPEG quality on thumbs — grid-size images don't need 95
            quality = 78 if size <= _THUMB_SIZE else 88
            img.save(cache_path, "JPEG", quality=quality, optimize=True)
        data = cache_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        # Thumbnails are content-addressed by filename+size → cacheable forever
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(data)


# --- HTML / JS viewer. Single-page, data inlined as JSON into __PAYLOAD__. -----
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>PixCull — review</title>
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
      --hit: #2ea84a;
      --near: #d9a30c;
      --miss: #d95050;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--bg); color: var(--fg);
      font: 13px/1.45 -apple-system, "Helvetica Neue", sans-serif;
    }
    header {
      position: sticky; top: 0; z-index: 5;
      background: rgba(17, 20, 24, 0.92);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 14px 20px 12px;
    }
    h1 { font-size: 15px; margin: 0 0 8px; font-weight: 600; letter-spacing: 0.3px; }
    h1 .v { color: var(--muted); font-weight: 400; margin-left: 8px; }
    .stats { display: flex; gap: 18px; color: var(--muted); font-size: 12px; flex-wrap: wrap; }
    .stats b { color: var(--fg); font-weight: 600; }
    .filters { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; align-items: center; }
    .filters label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; margin-right: 4px; }
    .chip {
      padding: 4px 10px; border-radius: 999px;
      background: var(--bg-card); border: 1px solid var(--border);
      color: var(--fg); cursor: pointer; font-size: 12px;
      user-select: none; transition: background 0.12s;
    }
    .chip:hover { background: var(--bg-card-hi); }
    .chip.on { background: #2a3240; border-color: #3a4759; color: #fff; }
    .chip .count { color: var(--muted); margin-left: 4px; font-variant-numeric: tabular-nums; }
    main { padding: 18px 20px 60px; }
    .grid {
      display: grid; gap: 14px;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    }
    .card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; overflow: hidden; position: relative;
      cursor: zoom-in;
    }
    .card:hover { border-color: #3b4352; }
    .card .img-wrap {
      aspect-ratio: 3 / 2; background: #0a0c0f; overflow: hidden;
      display: flex; align-items: center; justify-content: center;
    }
    .card img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .badges {
      position: absolute; top: 8px; left: 8px; right: 8px;
      display: flex; justify-content: space-between; gap: 6px;
      pointer-events: none;
    }
    .b {
      padding: 2px 7px; border-radius: 4px;
      font-size: 11px; font-weight: 600; letter-spacing: 0.5px;
      text-transform: uppercase;
      background: rgba(0, 0, 0, 0.55);
    }
    .b.keep  { color: var(--keep); }
    .b.maybe { color: var(--maybe); }
    .b.cull  { color: var(--cull); }
    .b.hit   { background: rgba(46, 168, 74, 0.18); color: #7fd194; }
    .b.near  { background: rgba(217, 163, 12, 0.18); color: #f1c24f; }
    .b.miss  { background: rgba(217, 80, 80, 0.20); color: #f08b8b; }
    .meta { padding: 8px 10px 10px; }
    .meta .fn {
      font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      margin-bottom: 4px;
    }
    .scores {
      display: flex; gap: 8px; color: var(--muted); font-size: 11px;
      font-variant-numeric: tabular-nums;
    }
    .scores .s { color: var(--fg); }
    .flags { color: var(--muted); font-size: 11px; margin-top: 4px; min-height: 14px; }
    .flags .warn { color: var(--maybe); }
    .notes { color: var(--muted); font-size: 11px; margin-top: 4px; font-style: italic; }
    .no-results { color: var(--muted); text-align: center; padding: 40px; }

    /* V1.1 rescorer display */
    .rescorer {
      font-size: 11px; margin-top: 4px; color: var(--muted);
      font-variant-numeric: tabular-nums;
      display: flex; align-items: center; gap: 6px;
    }
    .rescorer .agree { color: var(--muted); }
    .rescorer .disagree {
      color: #f1c24f; font-weight: 600;
    }
    .rescorer .rarrow { color: var(--border); }
    .card.rescorer-disagrees { box-shadow: inset 0 0 0 1px rgba(217, 163, 12, 0.22); }

    /* V1.2 trigger gate banner */
    .gate {
      display: flex; align-items: center; gap: 8px;
      margin-top: 8px; padding: 6px 10px;
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 6px; font-size: 11px;
      font-variant-numeric: tabular-nums; width: fit-content;
    }
    .gate .g-label { color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; font-size: 10px; }
    .gate .g-status { font-weight: 600; padding: 1px 7px; border-radius: 3px; }
    .gate .g-status.ready    { color: var(--keep); background: rgba(46,168,74,0.12); }
    .gate .g-status.notready { color: var(--muted); background: rgba(136,146,160,0.10); }
    .gate .g-status.unknown  { color: var(--muted); background: transparent; }
    .gate .g-pill {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 2px 8px; border-radius: 3px;
      background: rgba(217, 80, 80, 0.08);
      color: #d99090;
    }
    .gate .g-pill.on {
      background: rgba(46, 168, 74, 0.14);
      color: #7fd194;
    }
    .gate .g-pill .g-check { font-weight: 700; }
    .gate .g-sep { color: var(--border); }
    .gate .g-meta { color: var(--muted); margin-left: 4px; font-size: 10px; }

    /* Lightbox */
    .lb {
      position: fixed; inset: 0; z-index: 10;
      background: rgba(0, 0, 0, 0.9); display: none;
      grid-template-columns: 1fr 340px;
    }
    .lb.open { display: grid; }
    .lb .lb-img {
      display: flex; align-items: center; justify-content: center;
      padding: 24px; overflow: hidden; cursor: zoom-out;
    }
    .lb .lb-img img { max-width: 100%; max-height: 100%; object-fit: contain; }
    .lb .lb-side {
      background: var(--bg-card); border-left: 1px solid var(--border);
      overflow-y: auto; padding: 18px 20px;
    }
    .lb .lb-side h2 {
      font-size: 14px; margin: 0 0 12px;
      font-variant-numeric: tabular-nums; font-weight: 600;
    }
    .kv { display: flex; font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--border); }
    .kv .k { color: var(--muted); width: 120px; flex-shrink: 0; text-transform: uppercase; letter-spacing: 0.4px; font-size: 10px; }
    .kv .v { color: var(--fg); font-variant-numeric: tabular-nums; word-break: break-word; }
    .lb-close {
      position: absolute; top: 12px; right: 360px;
      color: var(--muted); background: transparent; border: none;
      font-size: 22px; cursor: pointer;
    }
    .lb-close:hover { color: var(--fg); }
  </style>
</head>
<body>
<header>
  <h1>PixCull<span class="v">golden-set review</span></h1>
  <div class="stats" id="stats"></div>
  <div class="gate" id="gate" style="display:none"></div>
  <div class="filters" id="filters"></div>
</header>
<main>
  <div class="grid" id="grid"></div>
  <div class="no-results" id="noresults" style="display:none">No photos match the current filters.</div>
</main>
<div class="lb" id="lb">
  <button class="lb-close" onclick="closeLB()">&times;</button>
  <div class="lb-img" id="lb-img" onclick="closeLB()"></div>
  <div class="lb-side" id="lb-side"></div>
</div>
<script>
const DATA = __PAYLOAD__;
const ROWS = DATA.rows;
const SUM  = DATA.summary;

const filters = {
  decision: 'all',
  scene:    'all',
  match:    'all',     // all | exact | within | big | unlabeled
  rescorer: 'all',     // all | disagree
};

function chip(id, label, count, group, active) {
  return `<span class="chip ${active?'on':''}" data-group="${group}" data-id="${id}">${label}<span class="count">${count}</span></span>`;
}

function renderGate() {
  const el = document.getElementById('gate');
  const g = SUM.gate_status;
  if (!g || g.skipped) { el.style.display = 'none'; return; }
  if (!g.available) {
    el.style.display = 'flex';
    el.innerHTML = `
      <span class="g-label">V1.2 gate</span>
      <span class="g-status unknown">N/A</span>
      <span class="g-meta">training.csv missing or unusable</span>`;
    return;
  }
  const pill = (label, on, actual, target) => `
    <span class="g-pill ${on ? 'on' : ''}" title="threshold ${target}  ·  actual ${actual}">
      <span class="g-check">${on ? '✓' : '✗'}</span>
      <span>${label}</span>
    </span>`;
  const statusCls = g.all_green ? 'ready' : 'notready';
  const statusLbl = g.all_green ? 'READY' : 'NOT READY';
  el.style.display = 'flex';
  el.innerHTML = `
    <span class="g-label">V1.2 gate</span>
    <span class="g-status ${statusCls}">${statusLbl}</span>
    ${pill(`${g.rows}/${400} rows`, g.rows_gate, g.rows, '≥ 400')}
    <span class="g-sep">·</span>
    ${pill(`lsAUC ${g.landscape_auc ?? '—'}`, g.landscape_gate, g.landscape_auc ?? '—', '≥ 0.70')}
    <span class="g-sep">·</span>
    ${pill(`Δacc ${g.delta_acc != null ? (g.delta_acc >= 0 ? '+' : '') + g.delta_acc : '—'}`,
           g.delta_gate, g.delta_acc ?? '—', '≥ +0.03')}
    <span class="g-meta">computed ${g.computed_at || '?'}</span>`;
}

function renderHeader() {
  const statsLines = [
    `<span><b>${SUM.n_total}</b> photos</span>`,
    `<span>labeled <b>${SUM.n_labeled}</b></span>`,
    `<span>exact <b>${SUM.exact_pct}%</b></span>`,
    `<span>within-one <b>${SUM.within_one_pct}%</b></span>`,
    `<span>cull precision <b>${SUM.cull_precision}</b> (${SUM.n_cull_correct}/${SUM.n_cull_pred})</span>`,
  ];
  if (SUM.rescorer_active) {
    statsLines.push(
      `<span>rescorer: <b>${SUM.rescorer_n_disagrees}</b>/${SUM.rescorer_n_scored}`
      + ` disagree (${SUM.rescorer_pct_disagrees}%)</span>`
    );
  }
  document.getElementById('stats').innerHTML = statsLines.join('');

  // Count rows by facet
  const byDec = {keep:0, maybe:0, cull:0};
  const byScene = {};
  const byMatch = {exact:0, within:0, big:0, unlabeled:0};
  for (const r of ROWS) {
    if (r.decision) byDec[r.decision] = (byDec[r.decision]||0) + 1;
    if (r.pipeline_scene) byScene[r.pipeline_scene] = (byScene[r.pipeline_scene]||0) + 1;
    if (!r.gt_label) byMatch.unlabeled++;
    else if (r.match) byMatch.exact++;
    else if (r.big_miss) byMatch.big++;
    else byMatch.within++;
  }

  const rows = [];
  rows.push(`<label>decision</label>`);
  rows.push(chip('all', 'all', ROWS.length, 'decision', filters.decision==='all'));
  for (const d of ['keep','maybe','cull']) rows.push(chip(d, d, byDec[d]||0, 'decision', filters.decision===d));
  rows.push(`<label style="margin-left:14px">match</label>`);
  for (const [k, lbl] of [['all','all'],['exact','✓ exact'],['within','~ within-one'],['big','✗ keep↔cull'],['unlabeled','no GT']]) {
    rows.push(chip(k, lbl, k==='all'?ROWS.length:byMatch[k]||0, 'match', filters.match===k));
  }
  rows.push(`<label style="margin-left:14px">scene</label>`);
  rows.push(chip('all', 'all', ROWS.length, 'scene', filters.scene==='all'));
  for (const s of Object.keys(byScene).sort()) rows.push(chip(s, s, byScene[s], 'scene', filters.scene===s));

  // V1.1: rescorer disagreement filter
  if (SUM.rescorer_active) {
    const nDis = SUM.rescorer_n_disagrees;
    rows.push(`<label style="margin-left:14px">rescorer</label>`);
    rows.push(chip('all', 'all', ROWS.length, 'rescorer', filters.rescorer==='all'));
    rows.push(chip('disagree', '≠ rule', nDis, 'rescorer', filters.rescorer==='disagree'));
  }

  document.getElementById('filters').innerHTML = rows.join('');
  document.getElementById('filters').querySelectorAll('.chip').forEach(el => {
    el.addEventListener('click', () => {
      filters[el.dataset.group] = el.dataset.id;
      renderHeader(); renderGrid();
    });
  });
}

function matchesFilters(r) {
  if (filters.decision !== 'all' && r.decision !== filters.decision) return false;
  if (filters.scene    !== 'all' && r.pipeline_scene !== filters.scene) return false;
  if (filters.match === 'exact'     && !r.match)             return false;
  if (filters.match === 'within'    && (r.match || r.big_miss || !r.gt_label)) return false;
  if (filters.match === 'big'       && !r.big_miss)          return false;
  if (filters.match === 'unlabeled' && r.gt_label)           return false;
  if (filters.rescorer === 'disagree' && !r.rescorer_disagrees) return false;
  return true;
}

function cardHTML(r) {
  const badgeLeft = r.decision
    ? `<span class="b ${r.decision}">${r.decision}</span>`
    : `<span class="b" style="color:var(--muted)">—</span>`;
  let badgeRight = '';
  if (r.gt_label) {
    const cls = r.match ? 'hit' : (r.big_miss ? 'miss' : 'near');
    const prefix = r.match ? '✓' : (r.big_miss ? '✗' : '~');
    badgeRight = `<span class="b ${cls}">${prefix} ${r.gt_label}</span>`;
  } else {
    badgeRight = `<span class="b" style="color:var(--muted)">no gt</span>`;
  }
  const flags = r.flags && r.flags !== 'nan'
    ? `<div class="flags"><span class="warn">⚑</span> ${escape(r.flags)}</div>`
    : `<div class="flags"></div>`;
  const notes = r.notes && r.notes !== 'nan'
    ? `<div class="notes">${escape(r.notes)}</div>` : '';
  const scores = [
    ['final',  r.score_final],
    ['sharp',  r.score_sharpness],
    ['expo',   r.score_exposure],
    ['aes',    r.score_aesthetic],
  ].map(([k,v]) => `<span>${k}=<span class="s">${v??'—'}</span></span>`).join(' ');

  // V1.1 rescorer row: only when active + this row has a prediction
  let rescorerRow = '';
  const cardCls = r.rescorer_disagrees ? 'card rescorer-disagrees' : 'card';
  if (SUM.rescorer_active && r.rescorer_pred) {
    const rCls = r.rescorer_disagrees ? 'disagree' : 'agree';
    const verdict = r.rescorer_disagrees
      ? `<span class="${rCls}">${r.rescorer_pred} (P<sub>keep</sub>=${r.rescorer_prob_keep})</span>`
      : `<span class="${rCls}">agrees (P<sub>keep</sub>=${r.rescorer_prob_keep})</span>`;
    rescorerRow = `<div class="rescorer">rescorer <span class="rarrow">→</span> ${verdict}</div>`;
  }
  return `<div class="${cardCls}" data-fn="${r.filename}">
    <div class="img-wrap"><img loading="lazy" src="/thumb/${encodeURIComponent(r.filename)}"></div>
    <div class="badges">${badgeLeft}${badgeRight}</div>
    <div class="meta">
      <div class="fn">${escape(r.filename)} · ${escape(r.pipeline_scene||'?')}</div>
      <div class="scores">${scores}</div>
      ${rescorerRow}${flags}${notes}
    </div>
  </div>`;
}

function renderGrid() {
  const filtered = ROWS.filter(matchesFilters);
  document.getElementById('grid').innerHTML = filtered.map(cardHTML).join('');
  document.getElementById('noresults').style.display = filtered.length ? 'none' : 'block';
  document.querySelectorAll('.card').forEach(el => {
    el.addEventListener('click', () => openLB(el.dataset.fn));
  });
}

function openLB(fn) {
  const r = ROWS.find(x => x.filename === fn);
  if (!r) return;
  document.getElementById('lb-img').innerHTML =
    `<img src="/full/${encodeURIComponent(r.filename)}">`;
  const kv = (k, v) => `<div class="kv"><div class="k">${k}</div><div class="v">${v??'—'}</div></div>`;
  const matchTxt = r.gt_label
    ? (r.match ? `✓ exact (${r.gt_label})` : r.big_miss ? `✗ keep↔cull miss (GT=${r.gt_label})` : `~ within-one (GT=${r.gt_label})`)
    : 'no ground truth';
  // V1.1 rescorer info, only when available
  let rescorerBlock = '';
  if (SUM.rescorer_active && r.rescorer_pred) {
    const tag = r.rescorer_disagrees
      ? `<span style="color:#f1c24f;font-weight:600">${r.rescorer_pred}</span>`
      : `<span style="color:var(--muted)">agrees → ${r.rescorer_pred}</span>`;
    rescorerBlock = `
      ${kv('rescorer pred', tag)}
      ${kv('P(keep)', r.rescorer_prob_keep)}
    `;
  }

  document.getElementById('lb-side').innerHTML = `
    <h2>${escape(r.filename)}</h2>
    ${kv('decision', `<span class="b ${r.decision}">${r.decision||'—'}</span>`)}
    ${kv('ground truth', matchTxt)}
    ${rescorerBlock}
    ${kv('pipeline scene', r.pipeline_scene)}
    ${kv('gt scene', r.gt_scene)}
    ${kv('score_final', r.score_final)}
    ${kv('sharpness', r.score_sharpness)}
    ${kv('exposure', r.score_exposure)}
    ${kv('aesthetic', r.score_aesthetic)}
    ${kv('composition', r.score_composition)}
    ${kv('clipiqa', r.clipiqa)}
    ${kv('laion_aes', r.laion_aes)}
    ${kv('flags', r.flags && r.flags!=='nan' ? r.flags : '—')}
    ${kv('reason', r.reason && r.reason!=='nan' ? r.reason : '—')}
    ${kv('photographer notes', r.notes && r.notes!=='nan' ? r.notes : '—')}
  `;
  document.getElementById('lb').classList.add('open');
}
function closeLB() { document.getElementById('lb').classList.remove('open'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLB(); });

function escape(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'
  }[c]));
}

renderGate();
renderHeader();
renderGrid();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("golden_dir", type=Path)
    ap.add_argument("--port", type=int, default=0,
                    help=f"port to bind (default: first free in {_FALLBACK_PORTS})")
    ap.add_argument("--no-open", action="store_true",
                    help="don't auto-open the browser")
    ap.add_argument("--no-gate-check", action="store_true",
                    help="skip the V1.2 trigger audit at startup (~10–20s saved)")
    args = ap.parse_args()

    golden_dir = args.golden_dir.expanduser().resolve()
    rows, summary, images_root = _build_dataset(golden_dir)

    # V1.2 gate status — one synchronous check at startup (default). Reuses
    # scripts/check_v1_2_trigger.py's thresholds via inline computation.
    if args.no_gate_check:
        summary["gate_status"] = {"available": False, "skipped": True}
        print("  [gate check] skipped (--no-gate-check)")
    else:
        print("  [gate check] running V1.2 trigger audit...", flush=True)
        scores_path = golden_dir / "_eval_output" / "scores.csv"
        gate = _compute_gate_status(_TRAINING_CSV, scores_path)
        summary["gate_status"] = gate
        if gate.get("available"):
            print(f"  [gate check] rows={gate['rows']}  "
                  f"landscape_AUC={gate['landscape_auc']}  "
                  f"Δ_acc={gate['delta_acc']:+.3f}  "
                  f"all_green={gate['all_green']}  "
                  f"({gate['computation_seconds']}s)")
        else:
            print(f"  [gate check] training.csv missing or unusable — "
                  f"banner will show 'N/A'")

    port = args.port or _pick_port()
    cache_dir = golden_dir / "_review_cache"

    # Build filename → path index for image serving.
    by_name: dict[str, Path] = {}
    for p in images_root.rglob("*"):
        if p.is_file():
            by_name[p.name] = p.resolve()

    handler = _Handler
    handler.rows = rows
    handler.summary = summary
    handler.images_root = images_root
    handler.cache_dir = cache_dir
    handler.by_name = by_name

    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"PixCull review viewer ready")
    print(f"  {len(rows)} photos ({summary['n_labeled']} labeled, "
          f"{summary['exact_pct']}% exact, {summary['within_one_pct']}% within-one)")
    if summary.get("rescorer_active"):
        print(f"  rescorer: {summary['rescorer_n_scored']} rows scored, "
              f"{summary['rescorer_n_disagrees']} disagree with rule "
              f"({summary['rescorer_pct_disagrees']}%)")
    print(f"  thumbnail cache: {cache_dir}")
    print(f"  → {url}")
    print(f"  Ctrl-C to stop")

    if not args.no_open:
        # Open after a beat so the server is ready to answer the first request.
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
