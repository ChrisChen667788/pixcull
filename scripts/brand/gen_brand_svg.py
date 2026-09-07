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
    """The chosen frame's fill: warm paper under a lamp.

    The old ramp ended at #6a6052, a mud brown that dragged every asset
    it touched. This one stays in the light half so the marked frame
    reads as lit rather than as another dark shape on a dark ground.
    """
    return (
        f'<linearGradient id="{gradient_id}" x1="0" y1="0" x2="0.6" y2="1">'
        f'<stop offset="0%" stop-color="{palette["wordmarkStart"]}"/>'
        f'<stop offset="55%" stop-color="{palette["wordmarkMid"]}"/>'
        f'<stop offset="100%" stop-color="{palette["wordmarkEnd"]}"/>'
        f'</linearGradient>'
    )


def _cosmic_bg_defs(palette: dict, w: int, h: int,
                    radial_id: str = "cosmicBg") -> str:
    """Emit a radial-gradient background — deep edge fading to cosmic
    center.  Cinematic look identical across all 3 variants."""
    deep   = palette.get("bgDeep",   "#110e0b")
    mid    = palette.get("bgMid",    "#1e1a14")
    cosmic = palette.get("bgCosmic", "#33291a")
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
                gradient_id: str = "brandGrad", palette: dict | None = None
                ) -> str:
    """The mark: the frame you marked, drawn at (cx, cy).

    Replaces the v0.9 "spotlight on one in a crowd" — a glowing orb among
    small circles, which was the house style of every generated logo and
    said nothing about photographs.

    A photo editor culling a take marks the frames they want on a contact
    sheet, and the mark is a corner bracket: the same shape as a
    viewfinder and as a crop mark. Behind the marked frame sit the rest
    of the take, dimmed, because culling is choosing one out of many that
    look alike.

    Native box is 0..24, same as before, so every call site keeps its
    scale arithmetic. Legibility at 16px drove the composition: the
    brackets carry the silhouette, and the stack is two offset edges
    rather than drawn frames, because a contact-sheet grid turns to mush
    at favicon size.
    """
    pal = palette or {}
    accent = pal.get("accent", "#e8a33c")
    near = pal.get("stackNear", "#5b5f68")
    far = pal.get("stackFar", "#43464d")
    s_ = scale
    tx = cx - 12 * s_
    ty = cy - 12 * s_
    return f'''
<g transform="translate({tx:.2f},{ty:.2f}) scale({s_})">
  <!-- the rest of the take, kept inside the bracket box: a stack that
       pokes out past the crop marks reads as untidy, not as depth -->
  <rect x="7.4" y="6.6" width="12" height="8" rx="0.6"
        fill="none" stroke="{far}" stroke-width="0.28"/>
  <rect x="6.7" y="7.3" width="12" height="8" rx="0.6"
        fill="none" stroke="{near}" stroke-width="0.28"/>
  <!-- the frame that was chosen -->
  <rect x="6" y="8" width="12" height="8" rx="0.6"
        fill="url(#{gradient_id})"/>
  <!-- crop brackets, outside the frame edge so the mark never covers
       the picture; centred on 12,12 so it sits level in a round avatar -->
  <g fill="none" stroke="{accent}" stroke-width="0.66"
     stroke-linecap="square">
    <path d="M4 9.8 V6.4 H7.4"/>
    <path d="M20 9.8 V6.4 H16.6"/>
    <path d="M4 14.2 V17.6 H7.4"/>
    <path d="M20 14.2 V17.6 H16.6"/>
  </g>
</g>'''


# BUGFIX (image-failure): SVG `font-family="{_SERIF_STACK}"` substitutes
# the stack inside double-quoted attribute, so any inner " terminates
# the attribute early and breaks parsing (GitHub renderer rejects with
# a broken-image icon).  Use single-quotes for inner family names —
# valid in CSS / SVG font-family lists and avoids the nesting issue.
_SERIF_STACK = (
    "'Charter','Iowan Old Style','PT Serif','Source Serif Pro',"
    "'Cambria',Georgia,'Songti SC','STZhongsong',serif"
)
_SANS_STACK = (
    "-apple-system,'Inter','Segoe UI Variable','Segoe UI',"
    "'PingFang SC','Microsoft Yahei UI',system-ui,sans-serif"
)


def _horizontal_lockup(brand: dict) -> str:
    """The README banner.

    Was 1280x720 — a 16:9 slide with the wordmark on the right and 200px
    of nothing between the tagline and the footer. At `width="100%"` in a
    README that is most of a screen before a reader has seen a sentence
    of the project.

    Now a banner: 1280x420, one horizontal rhythm, the mark and the type
    on the same optical centre line. No radial glow behind the logo —
    that blob is the tell of a generated asset and it was doing nothing
    a considered background could not do better.
    """
    w, h = 1280, 420
    palette = brand.get("palette", {})
    name = brand.get("projectName", "PixCull")
    subtitle = brand.get("subtitle", "")
    tagline = brand.get("tagline", "")
    footer = brand.get("footerLine", "")
    half = max(1, len(name) // 2)
    name_a, name_b = name[:half], name[half:]
    accent = palette.get("accent", "#e8a33c")
    body = palette.get("textBody", "#d6d3cd")
    muted = palette.get("textMuted", "#8b8f97")
    return f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     width="{w}" height="{h}" role="img"
     aria-label="{_esc(name)} — {_esc(subtitle)}">
  <defs>
    {_gradient_defs(palette)}
    <linearGradient id="ground" x1="0" y1="0" x2="0.35" y2="1">
      <stop offset="0%"   stop-color="{palette.get("bgCosmic", "#1e2024")}"/>
      <stop offset="100%" stop-color="{palette.get("bgDeep", "#101113")}"/>
    </linearGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#ground)"/>

  <!-- Film-edge rule along the bottom. One accent, the same one the
       crop brackets use, so the colour keeps meaning "chosen". -->
  <rect x="0" y="{h - 5}" width="{w}" height="5" fill="{accent}"
        opacity="0.85"/>

  {_logo_group(cx=196, cy=196, scale=7.2, palette=palette)}

  <!-- A hairline between the mark and the type: the two halves are one
       lockup, not a logo that happens to sit near some words. -->
  <rect x="330" y="104" width="2" height="184" fill="{muted}"
        opacity="0.30"/>

  <text x="382" y="196" font-family="{_SERIF_STACK}"
        font-size="96" font-weight="700" letter-spacing="-2"
        fill="{palette.get("wordmarkStart", "#f2ead9")}">
    {_esc(name_a)}<tspan fill="url(#brandGrad)">{_esc(name_b)}</tspan>
  </text>
  <text x="386" y="238" font-family="{_SANS_STACK}"
        font-size="19" font-weight="600" letter-spacing="3.4"
        fill="{accent}">
    {_esc(subtitle)}
  </text>
  <text x="386" y="278" font-family="{_SANS_STACK}"
        font-size="22" font-weight="400" fill="{body}">
    {_esc(tagline)}
  </text>
  <text x="{w - 44}" y="{h - 34}" text-anchor="end"
        font-family="{_SANS_STACK}" font-size="13" font-weight="500"
        fill="{muted}" letter-spacing="1.4">
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
  {_logo_group(cx=360, cy=500, scale=18, palette=palette)}
  <!-- Wordmark centred lower third (giant) -->
  <text x="360" y="940" font-family="{_SERIF_STACK}"
        font-size="120" font-weight="700" text-anchor="middle"
        letter-spacing="-2" fill="#ffffff">
    {_esc(name_a)}<tspan fill="url(#brandGrad)">{_esc(name_b)}</tspan>
  </text>
  <text x="360" y="990" font-family="{_SANS_STACK}"
        font-size="20" font-weight="600" text-anchor="middle"
        letter-spacing="4" fill="#c4b9a9">
    {_esc(subtitle)}
  </text>
  <!-- Tagline near bottom, broken if Chinese is long -->
  <text x="360" y="1130" font-family="{_SANS_STACK}"
        font-size="28" font-weight="500" text-anchor="middle"
        fill="#e8e0d4" opacity="0.92">
    {_esc(tagline)}
  </text>
  <text x="360" y="1220" font-family="{_SANS_STACK}"
        font-size="13" font-weight="500" text-anchor="middle"
        fill="#8a7d6a" letter-spacing="2">
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
  {_logo_group(cx=512, cy=512, scale=28, palette=palette)}
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
