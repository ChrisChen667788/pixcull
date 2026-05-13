"""V17.16 — multi-folder rule-stack scan, one Python process.

scan_for_bad.py spins up a fresh process per folder, re-loading
~1.5 GB of detector models each time. For the 2025-* + 101EOSR5
scan (6 folders, 4508 images) that'd be 6× model warm-up overhead.

This script walks multiple folders in a single process, sharing
the model singletons via the existing ``@cache`` on _detectors().
Writes one JSON per folder + a combined index pointing to them.

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
import json
import sys
import time
from pathlib import Path


def scan_folder(folder: Path, output: Path, config) -> dict:
    """Walk + analyze + fuse one folder. Returns summary dict."""
    from pixcull.io.loader import list_images
    from pixcull.pipeline.worker import analyze_one
    from pixcull.scoring.fusion import fuse_score
    from pixcull.scoring.decision import decide

    paths = list_images(folder)
    n = len(paths)
    print(f"\n[{folder.name}] {n} images · est ~{n*2/60:.0f} min",
          file=sys.stderr)
    if n == 0:
        return {"folder": str(folder), "n": 0, "items": []}

    results: list[dict] = []
    t0 = time.time()
    last_print = t0
    for i, fp in enumerate(paths, start=1):
        try:
            row = analyze_one(fp)
            if row is None:
                continue
            scene = str(row.get("scene") or "")
            flags = list(row.get("flags") or [])
            dims = fuse_score(row, flags, scene, config)
            dec, _ = decide(dims["final"], flags, config, scene=scene)
            results.append({
                "filename":  fp.name,
                "src_path":  str(fp),
                "score":     round(float(dims["final"]), 3),
                "decision":  dec.value,
                "scene":     scene,
                "flags":     flags,
                # V17.16 — also surface face_count so portrait/kids
                # filtering downstream is one less JSON pass.
                "face_count": int(row.get("face_count") or 0),
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  {fp.name}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
        now = time.time()
        if i % 50 == 0 or now - last_print > 30:
            pct = i * 100 / n
            elapsed = now - t0
            eta = elapsed * (n - i) / max(1, i)
            print(f"  {i}/{n} ({pct:.1f}%) · "
                  f"elapsed {elapsed/60:.1f}m · ETA {eta/60:.1f}m",
                  file=sys.stderr)
            last_print = now

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
    print(f"[{folder.name}] done · {len(results)} rows → {output}",
          file=sys.stderr)
    return {"folder": str(folder), "n": len(results),
            "output": str(output)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("folders", nargs="+",
                    help="One or more folders to scan (in order)")
    p.add_argument("--output-dir", default="/tmp/pixcull_scan_multi",
                    help="Where to write per-folder JSONs")
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
        summary = scan_folder(folder, out_p, config)
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
