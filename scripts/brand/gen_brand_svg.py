#!/usr/bin/env python3
"""Brand kit — fallback SVG variant generator (no AI, no Playwright).

This is the "I don't have MINIMAX_API_KEY yet but I still want a polished
hero banner today" path of the brand-banner-kit recipe.  Instead of an
AI-generated mascot we use the project's signature gradient + the v0.9-P0-3
logo SVG ("spotlight on one in a crowd") + wordmark — all SVG primitives,
zero external dependencies, deterministic output that round-trips through
git diffs.

Reads scripts/brand/pixcull-brand.json (same shape the upstream
gen_mascot.mjs / overlay_wordmark.mjs scripts read) and writes three
SVG variants into ``brand.outputDir``:

  <slug>-horizontal-lockup.svg   1280×720   GitHub README hero / Notion / Slack
  <slug>-vertical-poster.svg     720×1280   小红书 / 抖音 / 手机壁纸
  <slug>-mark-only.svg           1024×1024  Sticker die-cut / monogram / favicon

SVG is the right format here because:
  * lossless at any size (1280→3840px upscale stays crisp)
  * tiny file size (each variant is 3-5 KB)
  * GitHub renders inline as <img> in markdown
  * editable in any text editor — change a hex code, all three update
  * no font rendering surprises (uses system serif stack)

When the user later gets a MINIMAX_API_KEY they can run the upstream
``gen_mascot.mjs`` + ``overlay_wordmark.mjs`` scripts (also in this
directory) to produce the raster + AI-mascot variants.  Both paths share
the same brand.json so they coexist.

Usage:
    python scripts/brand/gen_brand_svg.py
    # or with a custom brand JSON:
    python scripts/brand/gen_brand_svg.py path/to/my-brand.json
"""

from __future__ import annotations

import json
import sys
from html import escape as _esc
from pathlib import Path
from typing import Tuple


def _gradient_defs(palette: dict, gradient_id: str = "brandGrad") -> str:
    """Emit a <linearGradient> from palette wordmark stops.  Two-stop
    when no mid, three-stop with mid."""
    start = palette.get("wordmarkStart", "#6E56CF")
    end   = palette.get("wordmarkEnd",   "#EC4899")
    mid   = palette.get("wordmarkMid")
    stops = [f'<stop offset="0%" stop-color="{start}"/>']
    if mid:
        stops.append(f'<stop offset="55%" stop-color="{mid}"/>')
    stops.append(f'<stop offset="100%" stop-color="{end}"/>')
    return (
        f'<linearGradient id="{gradient_id}" x1="0" y1="0" x2="1" y2="1">'
        + "".join(stops) + "</linearGradient>"
    )


def _cosmic_bg_defs(palette: dict, w: int, h: int,
                    radial_id: str = "cosmicBg") -> str:
    """Emit a radial-gradient background — deep edge fading to cosmic
    center.  Cinematic look identical across all 3 variants."""
    deep   = palette.get("bgDeep",   "#0b0d10")
    mid    = palette.get("bgMid",    "#1a1230")
    cosmic = palette.get("bgCosmic", "#3d1b69")
    # Radial centred at 30% width × 35% height (rule-of-thirds-ish
    # — keeps the bright spot off-centre, looks intentional).
    return (
        f'<radialGradient id="{radial_id}" cx="30%" cy="35%" r="80%">'
        f'<stop offset="0%"  stop-color="{cosmic}"/>'
        f'<stop offset="55%" stop-color="{mid}"/>'
        f'<stop offset="100%" stop-color="{deep}"/>'
        f'</radialGradient>'
    )


def _logo_group(cx: float, cy: float, scale: float,
                gradient_id: str = "brandGrad") -> str:
    """The v0.9-P0-3 "spotlight on one in a crowd" logo, drawn at
    (cx, cy) with the given uniform scale (1.0 = the 24×24 native size).

    Four small muted circles surround a large gradient-filled circle
    — the visual narrative of culling.
    """
    # Native viewBox is 0..24; we transform so cx,cy is the centre.
    s = scale
    # 12 12 is the centre of the original viewBox
    tx = cx - 12 * s
    ty = cy - 12 * s
    return f'''
<g transform="translate({tx:.2f},{ty:.2f}) scale({s})">
  <!-- the crowd: 4 small muted circles -->
  <circle cx="4"  cy="5"  r="1.6" fill="#ffffff" opacity="0.32"/>
  <circle cx="20" cy="6"  r="1.4" fill="#ffffff" opacity="0.28"/>
  <circle cx="3"  cy="19" r="1.8" fill="#ffffff" opacity="0.30"/>
  <circle cx="21" cy="20" r="1.3" fill="#ffffff" opacity="0.28"/>
  <!-- the picked one — large gradient + soft outer ring -->
  <circle cx="12" cy="12" r="7"  fill="url(#{gradient_id})"/>
  <circle cx="12" cy="12" r="7.5" fill="none"
          stroke="url(#{gradient_id})" stroke-width="0.6" opacity="0.5"/>
</g>'''


_SERIF_STACK = (
    '"Charter","Iowan Old Style","PT Serif","Source Serif Pro",'
    '"Cambria",Georgia,"Songti SC","STZhongsong",serif'
)
_SANS_STACK = (
    '-apple-system,"Inter","Segoe UI Variable","Segoe UI",'
    '"PingFang SC","Microsoft Yahei UI",system-ui,sans-serif'
)


def _horizontal_lockup(brand: dict) -> str:
    """16:9 — GitHub README hero / Notion / Slack header."""
    w, h = 1280, 720
    palette  = brand.get("palette", {})
    name     = brand.get("projectName", "Project")
    subtitle = brand.get("subtitle", "")
    tagline  = brand.get("tagline", "")
    footer   = brand.get("footerLine", "")
    # Split wordmark into 2 halves for the gradient-on-second-half pattern
    # we ship in the workspace bar (matches results.html .wordmark span).
    half = max(1, len(name) // 2)
    name_a, name_b = name[:half], name[half:]
    return f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     width="{w}" height="{h}" role="img"
     aria-label="{_esc(name)} — {_esc(subtitle)}">
  <defs>
    {_gradient_defs(palette)}
    {_cosmic_bg_defs(palette, w, h)}
  </defs>
  <!-- Cosmic background -->
  <rect width="{w}" height="{h}" fill="url(#cosmicBg)"/>
  <!-- Soft glow blob centred behind the logo to lift it off the bg -->
  <ellipse cx="320" cy="360" rx="280" ry="200"
           fill="url(#brandGrad)" opacity="0.18"/>
  <!-- Logo: ~280px wide, centred on the left third -->
  {_logo_group(cx=320, cy=360, scale=11.5)}
  <!-- Wordmark + subtitle + tagline column, right two-thirds -->
  <text x="600" y="330" font-family="{_SERIF_STACK}"
        font-size="120" font-weight="700" letter-spacing="-2"
        fill="#ffffff">
    {_esc(name_a)}<tspan fill="url(#brandGrad)">{_esc(name_b)}</tspan>
  </text>
  <text x="600" y="380" font-family="{_SANS_STACK}"
        font-size="22" font-weight="600" letter-spacing="3"
        fill="#aab3c1">
    {_esc(subtitle)}
  </text>
  <text x="600" y="440" font-family="{_SANS_STACK}"
        font-size="24" font-weight="400" fill="#dbdfe7" opacity="0.92">
    {_esc(tagline)}
  </text>
  <text x="600" y="640" font-family="{_SANS_STACK}"
        font-size="14" font-weight="500" fill="#7b8597"
        letter-spacing="1.5">
    {_esc(footer)}
  </text>
</svg>
'''


def _vertical_poster(brand: dict) -> str:
    """9:16 — 小红书 / 抖音 / 手机壁纸."""
    w, h = 720, 1280
    palette  = brand.get("palette", {})
    name     = brand.get("projectName", "Project")
    subtitle = brand.get("subtitle", "")
    tagline  = brand.get("tagline", "")
    footer   = brand.get("footerLine", "")
    half = max(1, len(name) // 2)
    name_a, name_b = name[:half], name[half:]
    return f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     width="{w}" height="{h}" role="img"
     aria-label="{_esc(name)} — {_esc(tagline)}">
  <defs>
    {_gradient_defs(palette)}
    {_cosmic_bg_defs(palette, w, h)}
  </defs>
  <rect width="{w}" height="{h}" fill="url(#cosmicBg)"/>
  <!-- Big centred glow behind the logo -->
  <ellipse cx="360" cy="500" rx="320" ry="320"
           fill="url(#brandGrad)" opacity="0.20"/>
  <!-- Logo centred upper third -->
  {_logo_group(cx=360, cy=500, scale=18)}
  <!-- Wordmark centred lower third (giant) -->
  <text x="360" y="940" font-family="{_SERIF_STACK}"
        font-size="120" font-weight="700" text-anchor="middle"
        letter-spacing="-2" fill="#ffffff">
    {_esc(name_a)}<tspan fill="url(#brandGrad)">{_esc(name_b)}</tspan>
  </text>
  <text x="360" y="990" font-family="{_SANS_STACK}"
        font-size="20" font-weight="600" text-anchor="middle"
        letter-spacing="4" fill="#aab3c1">
    {_esc(subtitle)}
  </text>
  <!-- Tagline near bottom, broken if Chinese is long -->
  <text x="360" y="1130" font-family="{_SANS_STACK}"
        font-size="28" font-weight="500" text-anchor="middle"
        fill="#dbdfe7" opacity="0.92">
    {_esc(tagline)}
  </text>
  <text x="360" y="1220" font-family="{_SANS_STACK}"
        font-size="13" font-weight="500" text-anchor="middle"
        fill="#7b8597" letter-spacing="2">
    {_esc(footer)}
  </text>
</svg>
'''


def _mark_only(brand: dict) -> str:
    """1:1 — sticker / monogram / favicon backup."""
    w = h = 1024
    palette = brand.get("palette", {})
    return f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     width="{w}" height="{h}" role="img"
     aria-label="{_esc(brand.get("projectName", "Project"))}">
  <defs>
    {_gradient_defs(palette)}
    {_cosmic_bg_defs(palette, w, h)}
  </defs>
  <rect width="{w}" height="{h}" fill="url(#cosmicBg)"/>
  <ellipse cx="512" cy="512" rx="360" ry="360"
           fill="url(#brandGrad)" opacity="0.18"/>
  {_logo_group(cx=512, cy=512, scale=28)}
</svg>
'''


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        brand_path = Path(argv[1])
    else:
        brand_path = (
            Path(__file__).resolve().parent / "pixcull-brand.json"
        )
    if not brand_path.exists():
        print(f"[brand] not found: {brand_path}", file=sys.stderr)
        return 1
    try:
        brand = json.loads(brand_path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[brand] bad JSON: {exc}", file=sys.stderr)
        return 1

    slug = brand.get("slug") or "project"
    out_rel = brand.get("outputDir") or "docs/brand"
    # Resolve relative to the repo root (which is brand JSON's grand-
    # parent when brand.json lives in scripts/brand/) rather than CWD.
    repo_root = brand_path.resolve().parent.parent.parent
    out_dir = (repo_root / out_rel).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    variants: list[Tuple[str, str]] = [
        (f"{slug}-horizontal-lockup.svg", _horizontal_lockup(brand)),
        (f"{slug}-vertical-poster.svg",   _vertical_poster(brand)),
        (f"{slug}-mark-only.svg",         _mark_only(brand)),
    ]
    for name, svg in variants:
        path = out_dir / name
        path.write_text(svg, encoding="utf-8")
        print(f"[brand] wrote {path.relative_to(repo_root)} "
              f"({len(svg):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
