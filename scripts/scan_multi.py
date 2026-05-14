"""V17.16 — multi-folder rule-stack scan, one Python process.

scan_for_bad.py spins up a fresh process per folder, re-loading
~1.5 GB of detector models each time. For the 2025-* + 101EOSR5
scan (6 folders, 4508 images) that'd be 6× model warm-up overhead.

This script walks multiple folders in a single process, sharing
the model singletons via the existing ``@cache`` on _detectors().
Writes one JSON per folder + a combined index pointing to them.

V19.2 — also writes a sister ``<basename>.features.csv`` per folder
containing the full numeric feature vector (laplacian_*, mean_luma,
clipiqa, face_*, score_*, ...) that ``train_axis_rescorers.py``
expects. The original V17.16 JSON dropped the feature vector to keep
output small, which made the scan output unusable for retraining the
rescorer. The CSV is opt-in via ``--dump-features`` (default True
from V19.2 onward) so existing callers that only want the slim JSON
can pass ``--no-dump-features``.

Usage:
  PYTHONPATH=. python scripts/scan_multi.py --output-dir /tmp/scan_2025 \\
      "/Volumes/One Touch/佳能JPG原片/2025/2025-10" \\
      "/Volumes/One Touch/佳能JPG原片/2025/2025-09" \\
      "/Volumes/One Touch/佳能JPG原片/2025/2025-11" \\
      "/Volumes/One Touch/佳能JPG原片/2025/2025-08" \\
      "/Volumes/One Touch/佳能JPG原片/2025/2025-07" \\
      "/Volumes/EOS_DIGITAL/DCIM/101EOSR5"

Each folder's result lands at OUTPUT_DIR/<basename>.json (same
schema as scan_for_bad.py). The combined index at
OUTPUT_DIR/_index.json points to per-folder files for offline
processing later.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

# Mirror of FEATURE_COLS_NUMERIC from scripts/build_axis_training_set.py,
# kept verbatim so the CSV emitted here can be appended to training_axis.csv
# without column-shape drift. Also include 'scene' (categorical) since
# the rescorer one-hot-encodes it.
_FEATURE_COLS_NUMERIC = [
    # sharpness
    "laplacian_global", "laplacian_subject", "face_region_lap_var",
    # exposure
    "mean_luma", "highlight_clip_pct", "shadow_clip_pct",
    # aesthetic
    "laion_aes", "clipiqa",
    # scene confidence
    "scene_confidence",
    # face
    "face_count", "face_max_blink", "face_min_ear",
    # composition
    "horizon_tilt_deg", "rule_of_thirds_offset", "composition_score",
    # subject
    "subject_fraction",
    # fusion outputs
    "score_sharpness", "score_composition", "score_exposure",
    "score_aesthetic", "score_moment", "score_final",
]


def scan_folder(folder: Path, output: Path, config,
                  features_csv: Path | None = None,
                  workers: int | None = None) -> dict:
    """Walk + analyze + fuse one folder. Returns summary dict.

    If ``features_csv`` is given, additionally writes a CSV with one
    row per analyzed image containing the full _FEATURE_COLS_NUMERIC
    vector + scene + decision. That CSV is what
    train_axis_rescorers.py consumes once the rows are appended to
    training_axis.csv (with a coarse decision→stars mapping).

    V21 — ``workers`` controls multiprocess parallelism. When None,
    defaults to ``min(4, cpu-1)`` (override via ``PIXCULL_WORKERS``).
    Pre-V21 this was a serial loop; the V19.3 scan of 2492 photos
    across 4 folders took 71 min. With 4 workers the same scan
    should finish in ~18-20 min on an M1 Max.
    """
    from pixcull.io.loader import list_images
    from pixcull.pipeline.parallel import parallel_analyze
    from pixcull.scoring.fusion import fuse_score
    from pixcull.scoring.decision import decide

    paths = list_images(folder)
    n = len(paths)
    print(f"\n[{folder.name}] {n} images · est ~{n*2/60:.0f} min serial "
          f"(parallel: ~{max(1, n*2/60/4):.0f} min)",
          file=sys.stderr)
    if n == 0:
        return {"folder": str(folder), "n": 0, "items": []}

    def _progress(done: int, total: int, msg: str) -> None:
        # Throttled progress — every 50 images or every 30 seconds,
        # same cadence as the V17.16 serial loop.
        nonlocal _last_print
        now = time.time()
        if done % 50 == 0 or now - _last_print > 30:
            pct = done * 100 / max(1, total)
            elapsed = now - t0
            eta = elapsed * (total - done) / max(1, done)
            print(f"  {done}/{total} ({pct:.1f}%) · "
                  f"elapsed {elapsed/60:.1f}m · ETA {eta/60:.1f}m",
                  file=sys.stderr)
            _last_print = now

    t0 = time.time()
    _last_print = t0
    # V21 parallel pass. ``parallel_analyze`` returns row dicts for
    # successfully analyzed images. We then run fuse_score + decide
    # back in the main process — those are sub-millisecond per row
    # so no benefit to pushing them into workers.
    rows = parallel_analyze(
        paths, workers=workers, progress_cb=_progress, desc=f"[{folder.name}]",
    )

    results: list[dict] = []
    feature_rows: list[dict] = []
    for row in rows:
        try:
            scene = str(row.get("scene") or "")
            flags = list(row.get("flags") or [])
            dims = fuse_score(row, flags, scene, config)
            dec, _ = decide(dims["final"], flags, config, scene=scene)
            fn = row.get("filename", "")
            results.append({
                "filename":  fn,
                "src_path":  row.get("path", ""),
                "score":     round(float(dims["final"]), 3),
                "decision":  dec.value,
                "scene":     scene,
                "flags":     flags,
                "face_count": int(row.get("face_count") or 0),
            })
            if features_csv is not None:
                merged: dict = dict(row)
                for k, v in dims.items():
                    merged[f"score_{k}"] = v
                merged["score_final"] = dims["final"]
                feat: dict = {
                    "filename": fn,
                    "scene":    scene,
                    "decision": dec.value,
                }
                for col in _FEATURE_COLS_NUMERIC:
                    feat[col] = merged.get(col)
                feature_rows.append(feat)
        except Exception as exc:  # noqa: BLE001
            print(f"  fuse/decide failed for "
                  f"{row.get('filename', '?')}: "
                  f"{type(exc).__name__}: {exc}",
                  file=sys.stderr)

    results.sort(key=lambda r: r["score"])
    out = {
        "schema":      "pixcull.scan.v1",
        "folder":      str(folder),
        "n_input":     n,
        "n_analyzed":  len(results),
        "items":       results,
    }
    output.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    if features_csv is not None and feature_rows:
        cols = ["filename", "scene", "decision"] + _FEATURE_COLS_NUMERIC
        with features_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for fr in feature_rows:
                w.writerow({c: fr.get(c) for c in cols})
        print(f"[{folder.name}] features → {features_csv}",
              file=sys.stderr)
    print(f"[{folder.name}] done · {len(results)} rows → {output}",
          file=sys.stderr)
    return {"folder": str(folder), "n": len(results),
            "output": str(output),
            "features_csv": str(features_csv) if features_csv else None}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("folders", nargs="+",
                    help="One or more folders to scan (in order)")
    p.add_argument("--output-dir", default="/tmp/pixcull_scan_multi",
                    help="Where to write per-folder JSONs")
    # V19.2 — default ON; pass --no-dump-features to skip if you only
    # want the slim JSON (e.g. for the bad-sample router, which only
    # reads decision/score/scene/flags/face_count).
    p.add_argument("--dump-features", dest="dump_features",
                    action="store_true", default=True,
                    help="Also write <basename>.features.csv with the "
                         "full feature vector (default: on)")
    p.add_argument("--no-dump-features", dest="dump_features",
                    action="store_false",
                    help="Skip per-folder features.csv (slim JSON only)")
    p.add_argument("--workers", type=int, default=None,
                    help="V21 — multiprocess worker count. Default: "
                         "min(4, cpu-1). Override via PIXCULL_WORKERS "
                         "env var. Pass 1 to force serial fallback.")
    args = p.parse_args()

    from pixcull.config import PixCullConfig
    config = PixCullConfig.load()

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"output → {out_dir}", file=sys.stderr)

    index = []
    t0_total = time.time()
    for folder_str in args.folders:
        folder = Path(folder_str).expanduser().resolve()
        if not folder.is_dir():
            print(f"SKIP not a folder: {folder}", file=sys.stderr)
            continue
        # Sanitize: use last-2 path components for the filename to
        # disambiguate "2025-07" across 佳能JPG/佳能RAW siblings.
        slug = "_".join(folder.parts[-2:]).replace("/", "_")
        out_p = out_dir / f"{slug}.json"
        feat_csv = (out_dir / f"{slug}.features.csv") if args.dump_features else None
        summary = scan_folder(folder, out_p, config, features_csv=feat_csv,
                               workers=args.workers)
        index.append(summary)

    (out_dir / "_index.json").write_text(
        json.dumps({
            "schema":       "pixcull.scan.multi.v1",
            "elapsed_s":    round(time.time() - t0_total, 1),
            "folders":      index,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nall done · total elapsed {(time.time()-t0_total)/60:.1f}m",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
