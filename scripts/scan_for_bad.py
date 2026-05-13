"""V17.13 helper — analyze a folder, surface low-score "bad sample"
candidates for the V17 vertical sample banks.

Why this exists
---------------
The V17.7 bulk-classify endpoint caps at 500 images and blocks the
HTTP connection for the duration. For a 1858-image RAW dump like
``/Volumes/One Touch/100CANON`` (~62 minutes at 2s/image) we want:

  * Streamable progress (this script writes a line to stderr every 50
    images so you can ``tail -f`` it).
  * Output to a file you can grep / sort later, not a transient HTTP
    response.
  * No path whitelisting — this is a developer tool, not exposed via
    the web server.

Usage
-----
    PYTHONPATH=. python scripts/scan_for_bad.py \\
        "/Volumes/One Touch/100CANON" \\
        --output /tmp/100CANON_scan.json \\
        [--limit 2500] [--bad-threshold 0.40] [--top-bad 50]

Outputs:
  * ``/tmp/100CANON_scan.json``  — full per-image result
  * Top N lowest-scoring filenames printed to stdout for quick review.

You then paste those filenames into the V17.7 bulk-classify page's
bad bucket (or use the JSON to drive a future auto-commit feature).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", help="Folder to scan (recurses into subdirs)")
    p.add_argument("--output", default="/tmp/pixcull_scan.json",
                    help="Where to write the full JSON result")
    p.add_argument("--limit", type=int, default=2500,
                    help="Max images to analyze (default 2500)")
    p.add_argument("--bad-threshold", type=float, default=0.40,
                    help="score <= this is a bad candidate (default 0.40)")
    p.add_argument("--top-bad", type=int, default=50,
                    help="Print this many lowest-scoring filenames")
    p.add_argument("--vertical", default=None,
                    help="If set, apply this vertical's effective policy "
                         "to the decision (just affects the 'decision' "
                         "field; the SCORE is policy-independent).")
    args = p.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"ERROR: not a folder: {folder}", file=sys.stderr)
        return 1

    # Late imports — keep --help fast on a machine without torch/etc.
    from pixcull.io.loader import list_images
    from pixcull.pipeline.worker import analyze_one
    from pixcull.scoring.fusion import fuse_score
    from pixcull.scoring.decision import decide, Decision
    from pixcull.config import PixCullConfig

    config = PixCullConfig.load()
    paths = list_images(folder)[:args.limit]
    n = len(paths)
    if not n:
        print(f"ERROR: no images in {folder}", file=sys.stderr)
        return 2

    print(f"[scan] folder={folder} · n={n} · est ~{n*2/60:.0f} min",
          file=sys.stderr)
    if args.vertical:
        print(f"[scan] vertical={args.vertical}", file=sys.stderr)

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
            dec, _r = decide(
                dims["final"], flags, config,
                scene=scene, vertical=args.vertical,
            )
            results.append({
                "filename":  fp.name,
                "src_path":  str(fp),
                "score":     round(float(dims["final"]), 3),
                "decision":  dec.value,
                "scene":     scene,
                "flags":     flags,
            })
        except Exception as exc:  # noqa: BLE001
            print(f"[scan] {fp.name}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
        # Progress every 50 images or 30s
        now = time.time()
        if i % 50 == 0 or now - last_print > 30:
            pct = i * 100 / n
            elapsed = now - t0
            eta = elapsed * (n - i) / max(1, i)
            print(f"[scan] {i}/{n} ({pct:.1f}%) · "
                  f"elapsed {elapsed/60:.1f}m · ETA {eta/60:.1f}m",
                  file=sys.stderr)
            last_print = now

    # Sort by score ascending so bad candidates float to top
    results.sort(key=lambda x: x["score"])

    # Write full result
    out_p = Path(args.output)
    out_p.write_text(
        json.dumps({
            "schema":         "pixcull.scan.v1",
            "folder":         str(folder),
            "n_analyzed":     len(results),
            "n_input":        n,
            "vertical":       args.vertical,
            "bad_threshold":  args.bad_threshold,
            "items":          results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[scan] done · wrote {out_p} ({len(results)} rows)",
          file=sys.stderr)

    # Stdout: the bad candidates
    bad_pool = [r for r in results if r["score"] <= args.bad_threshold]
    print(f"\n=== {len(bad_pool)} 张 score ≤ {args.bad_threshold} ===")
    for r in results[:args.top_bad]:
        print(f"  score={r['score']:.3f} · {r['decision']:5} · "
              f"{r['scene']:12} · {r['filename']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
