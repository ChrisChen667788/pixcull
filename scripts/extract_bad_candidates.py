"""V17.13 follow-up — extract bad-sample candidates from a scan
result + (optionally) commit them to a vertical's bad bucket.

Designed to consume the JSON output of ``scan_for_bad.py``. Splits
by scene so each detected scene can feed its appropriate vertical.

Usage examples:

  # Just print the lowest 50 scores (no commit):
  python scripts/extract_bad_candidates.py \\
      --scan /tmp/100CANON_scan.json --top 50

  # Auto-commit lowest 30 with score ≤ 0.35 to landscape's bad bucket,
  # only files with scene=landscape:
  python scripts/extract_bad_candidates.py \\
      --scan /tmp/100CANON_scan.json \\
      --vertical landscape --bucket bad \\
      --max-score 0.35 --top 30 \\
      --scene-filter landscape \\
      --commit

  # Cross-vertical distribution by scene (one pass, multiple sinks):
  python scripts/extract_bad_candidates.py \\
      --scan /tmp/100CANON_scan.json \\
      --auto-map --max-score 0.40 --per-vertical 15 --commit
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


# Scene → vertical mapping for --auto-map mode. Mirrors
# pixcull/verticals.py's parent_genres but pivoted: scene → first
# matching vertical.
_SCENE_TO_VERTICAL = {
    "landscape":   "landscape",
    "astro":       "landscape",
    "wildlife":    "wildlife",
    "portrait":    "kids",       # generic portrait → kids is most tolerant
    "event":       "event",
    "documentary": "event",
    "fashion":     "wedding",
    "macro":       "wildlife",
    "stilllife":   "pet",        # closest fit for indoor still subjects
    "street":      "travel",
    "architecture": "travel",
    "food":        "travel",
    "sports":      "sports",
    "abstract":    "landscape",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scan", required=True,
                    help="Path to scan JSON written by scan_for_bad.py")
    p.add_argument("--top", type=int, default=30,
                    help="How many lowest-score rows to surface per vertical")
    p.add_argument("--max-score", type=float, default=0.40,
                    help="Drop rows with score > this (default 0.40)")
    p.add_argument("--scene-filter",
                    help="Only consider rows with this scene tag")
    p.add_argument("--vertical",
                    help="Single-vertical mode: commit candidates here")
    p.add_argument("--bucket", default="bad",
                    choices=("good", "bad"),
                    help="Single-vertical mode bucket")
    p.add_argument("--auto-map", action="store_true",
                    help="Cross-vertical: scene → mapped vertical (mutually "
                         "exclusive with --vertical)")
    p.add_argument("--per-vertical", type=int, default=15,
                    help="In --auto-map mode, per-vertical cap")
    p.add_argument("--commit", action="store_true",
                    help="Actually copy bytes into sample banks (default: "
                         "dry-run printing only)")
    args = p.parse_args()

    scan_p = Path(args.scan).expanduser().resolve()
    if not scan_p.exists():
        print(f"ERROR: {scan_p} not found", file=sys.stderr)
        return 1
    data = json.loads(scan_p.read_text("utf-8"))
    items = data.get("items", [])
    if not items:
        print("scan JSON has 0 items", file=sys.stderr)
        return 2

    print(f"loaded {len(items)} rows from {scan_p}", file=sys.stderr)
    print(f"score distribution:", file=sys.stderr)
    scores = [r["score"] for r in items]
    print(f"  min={min(scores):.3f}  median={sorted(scores)[len(scores)//2]:.3f}  "
          f"max={max(scores):.3f}", file=sys.stderr)
    print(f"scene distribution:", file=sys.stderr)
    for scene, n in Counter(r["scene"] for r in items).most_common():
        print(f"  {n:4d}  {scene}", file=sys.stderr)

    # Filter to bad pool
    candidates = [r for r in items if r["score"] <= args.max_score]
    if args.scene_filter:
        candidates = [r for r in candidates if r["scene"] == args.scene_filter]
    candidates.sort(key=lambda r: r["score"])
    print(f"\n{len(candidates)} candidates with score ≤ {args.max_score}",
          file=sys.stderr)

    # Routing
    if args.vertical and args.auto_map:
        print("ERROR: --vertical and --auto-map are mutually exclusive",
              file=sys.stderr)
        return 3

    if args.auto_map:
        per_v: dict[str, list] = defaultdict(list)
        for r in candidates:
            v = _SCENE_TO_VERTICAL.get(r["scene"])
            if v is None:
                continue
            if len(per_v[v]) >= args.per_vertical:
                continue
            per_v[v].append(r)
        print(f"\nauto-map distribution:")
        for v, rs in sorted(per_v.items()):
            print(f"  {v:12s}  {len(rs):3d} (scenes: "
                  f"{sorted(set(r['scene'] for r in rs))})")
    else:
        target_v = args.vertical
        if target_v is None:
            # Dry-run preview only
            print(f"\nTop {min(args.top, len(candidates))} lowest scores:")
            for r in candidates[:args.top]:
                print(f"  score={r['score']:.3f}  {r['decision']:5}  "
                      f"{r['scene']:12s}  {r['filename']}")
            return 0
        per_v = {target_v: candidates[:args.top]}

    # Commit?
    if not args.commit:
        print(f"\n(dry-run; pass --commit to actually copy bytes)")
        for v, rs in per_v.items():
            print(f"\n{v} ({len(rs)} candidates):")
            for r in rs[:10]:
                print(f"  score={r['score']:.3f}  {r['filename']}")
            if len(rs) > 10:
                print(f"  ... +{len(rs)-10} more")
        return 0

    # Real commit
    try:
        from pixcull import verticals as vmod
    except Exception as exc:
        print(f"ERROR: can't import verticals: {exc}", file=sys.stderr)
        return 4

    bucket = args.bucket
    n_saved = 0
    n_skipped = 0
    for v, rs in per_v.items():
        if vmod.get_vertical(v) is None:
            print(f"  skip unknown vertical: {v}", file=sys.stderr)
            continue
        for r in rs:
            src = Path(r["src_path"])
            if not src.is_file():
                n_skipped += 1
                continue
            try:
                data = src.read_bytes()
                if len(data) > 32 * 1024 * 1024:
                    n_skipped += 1
                    continue
                vmod.save_sample(v, bucket, src.name, data)
                n_saved += 1
            except Exception as exc:
                print(f"  {src.name} → {v}: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                n_skipped += 1
    print(f"\ncommitted {n_saved} (skipped {n_skipped}) into bucket={bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
