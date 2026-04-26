"""Side-by-side VLM backend comparison on the same images.

Usage:
    # Compare local Qwen3-VL-4B against Deepseek + MiniMax APIs:
    DEEPSEEK_API_KEY=sk-... MINIMAX_API_KEY=... \\
      python scripts/compare_vlm_backends.py /tmp/pixcull_demo_in/ \\
        --backends local,deepseek,minimax

    # Just the local model (no keys needed):
    python scripts/compare_vlm_backends.py /tmp/pixcull_demo_in/ \\
        --backends local

Output:
  Per-image table showing each backend's per-axis stars + overall verdict
  side by side. Useful for picking the right backend for production use,
  or for catching when the local 4B parrots itself vs APIs that don't.

Cost note:
  API backends tally token usage when reported by the provider; total cost
  is estimated at the end. Local backend is free (uses your CPU/GPU).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.vlm_judge import load_judge


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Folder of images")
    parser.add_argument("--backends", default="local",
                        help="Comma-separated: local,deepseek,minimax,openai")
    parser.add_argument("--limit", type=int, default=3,
                        help="Max images to score (default 3 — VLMs are slow)")
    parser.add_argument("--scene", default=None,
                        help="Optional scene hint to pass to all backends")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"ERROR: not a folder: {args.folder}", file=sys.stderr)
        return 2

    image_exts = {".jpg", ".jpeg", ".png", ".cr3", ".cr2", ".nef", ".arw", ".dng"}
    images = [
        p for p in sorted(args.folder.iterdir())
        if p.suffix.lower() in image_exts
    ][: args.limit]
    if not images:
        print(f"ERROR: no images in {args.folder}", file=sys.stderr)
        return 2

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    judges = []
    for b in backends:
        print(f"Loading backend: {b} …")
        j = load_judge(b)
        if j is None:
            print(f"  ✗ failed — skipping", file=sys.stderr)
            continue
        judges.append((b, j))
    if not judges:
        print("ERROR: no backends loaded", file=sys.stderr)
        return 2

    print(f"\nScoring {len(images)} images × {len(judges)} backends "
          f"= {len(images) * len(judges)} VLM calls\n")

    axis_short = {
        "technical": "技术", "subject": "主体", "composition": "构图",
        "light": "光线", "moment": "瞬间", "aesthetic": "美感"
    }

    for img in images:
        print(f"━━━ {img.name} ━━━")
        for backend_name, judge in judges:
            t = time.time()
            v = judge.score(img, scene=args.scene)
            elapsed = time.time() - t
            tag = f"{backend_name:10s}"
            if v.error:
                print(f"  {tag} ❌  {v.error[:80]}")
                continue
            stars = "  ".join(
                f"{axis_short[a.name]}:{v.axes[a.name].stars or '--'}★"
                for a in RUBRIC_AXES
            )
            print(f"  {tag} {elapsed:5.1f}s  overall={v.overall_label:5s}  {stars}")
            print(f"               {v.overall_rationale[:100]}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
