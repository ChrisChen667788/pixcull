#!/usr/bin/env python3
"""v0.13.14 — Painter-quality empty-state illustrations via MiniMax.

Replaces the placeholder line-art SVG sprites in
``pixcull/report/templates/results.html`` (and the inline copy in
``scripts/serve_demo.py`` for /history) with rendered illustrations
that match PixCull's editorial design language: muted-indigo /
brand-gradient palette, line-art with watercolor wash, photography
metaphors.

Each empty state gets its own prompt tuned to the surface's tone:

  * art-empty-inbox       — "no run yet" hero
  * art-no-match          — "no photos match these filters"
  * art-analyzing         — "analyzing your photos" busy state
  * art-empty-buckets     — "no delivery buckets created"
  * art-empty-history     — "no past runs"
  * art-no-peer           — "no LAN collaborators visible"
  * art-no-annotations    — "you haven't labeled anything"
  * art-no-search         — "semantic search found nothing"

Output: ``docs/illustrations/<id>.png`` (1024×768, indigo
watercolor palette).  results.html + serve_demo.py reference these
via standard `<img>` tags;  fallback to existing SVG sprites on
404 / older browsers.

Key handling
============
* MINIMAX_API_KEY env var (preferred), or
* ~/.minimax_key_tmp file (chmod 600, outside repo)
The key is NEVER persisted to the repo, NEVER echoed in output,
and NEVER committed to git.  Rotate after use.

Usage
=====

    # one-shot generate all 8 illustrations
    MINIMAX_API_KEY=sk-... python scripts/brand/gen_empty_state_art.py

    # regenerate just one
    python scripts/brand/gen_empty_state_art.py --only art-empty-history

    # dry-run (print prompts, no API call)
    python scripts/brand/gen_empty_state_art.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "illustrations"

ENDPOINT = "https://api.minimaxi.com/v1/image_generation"

# Shared style prefix applied to every prompt for consistent aesthetic.
_STYLE_BASE = (
    "Editorial illustration in soft watercolor wash style, "
    "muted indigo and dusty pink palette (#6E56CF and #EC4899 as "
    "accent colors), minimalist line art with delicate ink strokes, "
    "dark gradient background (#0a0b0d to #1a1d24), "
    "photography studio aesthetic, no text, no people's faces, "
    "single subject centered, generous negative space, "
    "fits as a feature illustration in a SaaS application's "
    "empty-state card."
)

# Each illustration: (id, prompt, what surface it appears on)
ILLUSTRATIONS = [
    {
        "id": "art-empty-inbox",
        "prompt": _STYLE_BASE + " A weathered SD camera memory card on a "
                                "drafting desk, dust softly settling on it, "
                                "a single ray of warm light from the upper "
                                "left.  Symbol of \"nothing has been uploaded yet\".",
        "surface": "/upload + first run empty state",
    },
    {
        "id": "art-no-match",
        "prompt": _STYLE_BASE + " A vintage magnifying glass hovering over "
                                "an empty proof sheet, the proof sheet "
                                "showing only faint pencil cropmarks but no "
                                "photographs.  Symbol of \"your filters "
                                "matched zero photos\".",
        "surface": "filter result empty state",
    },
    {
        "id": "art-analyzing",
        "prompt": _STYLE_BASE + " A film strip moving through an old "
                                "darkroom enlarger, individual frames "
                                "glowing softly with indigo light.  Each "
                                "frame is being inspected one by one.  "
                                "Symbol of \"analyzing your photos\".",
        "surface": "pipeline-running state",
    },
    {
        "id": "art-empty-buckets",
        "prompt": _STYLE_BASE + " Three empty wooden chest-of-drawers "
                                "labeled with tiny ribbon tags, hovering "
                                "in mid-air, all drawers slightly ajar to "
                                "show they're empty.  Symbol of \"no "
                                "delivery buckets yet\".",
        "surface": "buckets panel before any bucket",
    },
    {
        "id": "art-empty-history",
        "prompt": _STYLE_BASE + " A vintage brass compass placed on a "
                                "blank journal page, no marks made yet, "
                                "the compass needle pointing toward an "
                                "empty horizon.  Symbol of \"no past "
                                "runs in history\".  Time and direction.",
        "surface": "/history before any run",
    },
    {
        "id": "art-no-peer",
        "prompt": _STYLE_BASE + " A single empty studio chair facing an "
                                "old film projector that's casting a "
                                "vertical beam of light into emptiness.  "
                                "Symbol of \"no LAN collaborators detected\".",
        "surface": "presence empty state",
    },
    {
        "id": "art-no-annotations",
        "prompt": _STYLE_BASE + " An open editor's notebook with the "
                                "pages completely blank, a fountain pen "
                                "resting beside it, the pen's nib pristine "
                                "and ink-less.  Symbol of \"you haven't "
                                "labeled any photos yet\".",
        "surface": "annotations panel before first label",
    },
    {
        "id": "art-no-search",
        "prompt": _STYLE_BASE + " A loupe magnifier on a dark velvet "
                                "background, casting a deep circular "
                                "shadow.  The loupe lens is clear but "
                                "shows nothing — no photo beneath it.  "
                                "Symbol of \"semantic search found nothing\".",
        "surface": "semantic search empty result",
    },
]


def _load_api_key() -> str:
    """Resolve the API key from env var or sibling tmp file.  Never
    written to the repo or echoed in output."""
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if key:
        return key
    tmp = Path.home() / ".minimax_key_tmp"
    if tmp.exists():
        try:
            return tmp.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ""


def _generate_one(api_key: str, spec: dict, dry_run: bool) -> Path | None:
    """Hit the MiniMax API, save the result PNG.  Returns the
    output path or None on dry-run / failure."""
    target = OUTPUT_DIR / f"{spec['id']}.png"
    if dry_run:
        print(f"[gen] would generate {spec['id']!r} → {target}")
        print(f"      surface: {spec['surface']}")
        print(f"      prompt (first 120 chars): "
              f"{spec['prompt'][:120]}…")
        return None

    print(f"[gen] {spec['id']!r}… ", end="", flush=True)
    body = json.dumps({
        "model": "image-01",
        "prompt": spec["prompt"],
        "aspect_ratio": "4:3",         # 1024×768
        "n": 1,
        "response_format": "url",
        "prompt_optimizer": True,
        "aigc_watermark": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:400]
        print(f"\n[gen] HTTP {exc.code}: {body_text}")
        return None
    except urllib.error.URLError as exc:
        print(f"\n[gen] network: {exc}")
        return None
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code") != 0:
        print(f"\n[gen] api error {base_resp.get('status_code')}: "
              f"{base_resp.get('status_msg')}")
        return None
    urls = data.get("data", {}).get("image_urls", []) or []
    if not urls:
        print(f"\n[gen] no urls in response: {data}")
        return None
    img_url = urls[0]
    # Download
    try:
        with urllib.request.urlopen(img_url, timeout=60) as resp:
            img_bytes = resp.read()
    except urllib.error.URLError as exc:
        print(f"\n[gen] download failed: {exc}")
        return None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(img_bytes)
    print(f"✓ {len(img_bytes):,} bytes → {target.relative_to(REPO_ROOT)}")
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate empty-state illustrations via MiniMax."
    )
    p.add_argument("--only", metavar="ID",
                   help="Generate only this illustration ID "
                        "(default: all 8)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print prompts; don't call the API")
    args = p.parse_args(argv)

    api_key = "" if args.dry_run else _load_api_key()
    if not args.dry_run and not api_key:
        print("[gen] no MINIMAX_API_KEY env var and no "
              "~/.minimax_key_tmp file. Set one and retry.",
              file=sys.stderr)
        return 2

    specs = ILLUSTRATIONS
    if args.only:
        specs = [s for s in ILLUSTRATIONS if s["id"] == args.only]
        if not specs:
            print(f"[gen] no spec with id {args.only!r}. Valid ids:",
                  file=sys.stderr)
            for s in ILLUSTRATIONS:
                print(f"  - {s['id']}", file=sys.stderr)
            return 2

    n_ok = 0
    for spec in specs:
        result = _generate_one(api_key, spec, args.dry_run)
        if result is not None:
            n_ok += 1
        # Polite rate-limit gap
        if not args.dry_run:
            time.sleep(1.5)

    if args.dry_run:
        print(f"\n[gen] DRY RUN — would have generated {len(specs)} "
              f"illustrations")
    else:
        print(f"\n[gen] ✓ generated {n_ok}/{len(specs)} illustrations")
    return 0 if n_ok or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
