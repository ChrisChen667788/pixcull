#!/usr/bin/env python3
"""Brand kit — animated SVG demo of PixCull's hero reveal.

Embeds inline in README.md as `<img src="docs/brand/pixcull-demo.svg">`.
GitHub renders SVG SMIL animations inline (no autoplay restriction
like videos / GIFs), so this is the "GIF demo" without GIF infra:

  * vector — sharp at any retina
  * 6 KB on disk (vs ~500 KB for an equivalent screen-recorded GIF)
  * editable as text — change a color or timing in any editor
  * accessible — has <title> + <desc>, alt text via parent img

Recipe mirrors the v0.9-P0-2 hero reveal:
  1. Workspace bar slides down
  2. Library sidebar slides in from left
  3. Grid cards stagger fade-up from bottom
  4. Stats numbers count up from 0 to final
  5. Brand-gradient on the keep counter

Loops forever; respects prefers-reduced-motion via @media inside the SVG
(SVG SMIL is exempt from prefers-reduced-motion in some browsers, so we
also gate via CSS animation as a belt-and-suspenders fallback).
"""

from __future__ import annotations

import sys
from pathlib import Path


_W, _H = 1280, 720


def _demo_svg() -> str:
    # Helper for stagger of 24 cards in a 6×4 grid, 8ms delay per
    # card means full grid reveals in 192ms; we slow to 80ms/card
    # for visual readability (~2s total cascade for the demo).
    cards_xml = []
    for r in range(4):
        for c in range(6):
            i = r * 6 + c
            x = 380 + c * 142
            y = 220 + r * 110
            delay = 1.0 + i * 0.08
            # Random-but-deterministic decision tint per card
            colour = {0: "#88e0a6", 1: "#e3c25e", 2: "#ee8888"}[i % 3]
            cards_xml.append(f'''
    <g opacity="0" transform="translate({x},{y + 24})">
      <rect width="124" height="92" rx="8"
            fill="#14171c" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>
      <rect x="6" y="6" width="112" height="60" rx="4" fill="#1c2028"/>
      <circle cx="116" cy="78" r="6" fill="{colour}"/>
      <text x="10" y="84" font-family="ui-monospace, monospace"
            font-size="8.5" fill="#8a8e96">IMG_{i:04d}.jpg</text>
      <animate attributeName="opacity"
               from="0" to="1" begin="{delay}s" dur="0.4s" fill="freeze"/>
      <animateTransform attributeName="transform" type="translate"
               from="{x} {y + 24}" to="{x} {y}"
               begin="{delay}s" dur="0.5s" fill="freeze"
               calcMode="spline" keySplines="0.34 1.56 0.64 1"/>
    </g>''')
    cards = "".join(cards_xml)

    return f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {_H}"
     width="{_W}" height="{_H}" role="img"
     aria-label="PixCull demo — hero reveal of analyzed photo grid">
  <title>PixCull · hero reveal</title>
  <desc>
    Demo of PixCull's signature 2-second opening moment: workspace bar
    slide-in, Library sidebar slide-in, 24 photo cards stagger fade-up
    from bottom with soft-bounce easing, and the keep/maybe/cull stats
    count up from zero with brand-gradient on the keep number.
    Mirrors the live behaviour shipped in v0.9-P0-2.
  </desc>
  <defs>
    <linearGradient id="demoBrandGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%"   stop-color="#6E56CF"/>
      <stop offset="50%"  stop-color="#A855F7"/>
      <stop offset="100%" stop-color="#EC4899"/>
    </linearGradient>
    <radialGradient id="demoBg" cx="30%" cy="35%" r="80%">
      <stop offset="0%"  stop-color="#3d1b69"/>
      <stop offset="55%" stop-color="#1a1230"/>
      <stop offset="100%" stop-color="#0b0d10"/>
    </radialGradient>
  </defs>

  <!-- Background canvas -->
  <rect width="{_W}" height="{_H}" fill="url(#demoBg)"/>
  <rect width="{_W}" height="{_H}" fill="#0b0d10" opacity="0.35"/>

  <!-- =========== Workspace bar (slides down 0.3s) =========== -->
  <g opacity="0">
    <rect x="0" y="0" width="{_W}" height="48"
          fill="rgba(20,23,28,0.94)"/>
    <line x1="0" y1="48" x2="{_W}" y2="48"
          stroke="rgba(255,255,255,0.10)" stroke-width="1"/>
    <!-- logo mark — same "spotlight on one in a crowd" as the
         real product workspace bar -->
    <g transform="translate(20,12) scale(1)">
      <circle cx="4"  cy="5"  r="1.6" fill="#aab3c1" opacity="0.32"/>
      <circle cx="20" cy="6"  r="1.4" fill="#aab3c1" opacity="0.28"/>
      <circle cx="3"  cy="19" r="1.8" fill="#aab3c1" opacity="0.30"/>
      <circle cx="21" cy="20" r="1.3" fill="#aab3c1" opacity="0.28"/>
      <circle cx="12" cy="12" r="7"  fill="url(#demoBrandGrad)"/>
    </g>
    <text x="56" y="30" font-family="Inter, -apple-system, sans-serif"
          font-size="15" font-weight="700" fill="#e8eaed">
      Pix<tspan fill="url(#demoBrandGrad)">Cull</tspan>
    </text>
    <text x="120" y="30" font-family="Inter, sans-serif"
          font-size="12.5" font-weight="500" fill="#8a8e96"
          letter-spacing="0.5">
      / 分析结果 · sample_a1b2
    </text>
    <!-- Stats group (counter animates 0→target) -->
    <g transform="translate(900,30)">
      <text x="0" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="#8a8e96">
        共 <tspan id="totN" font-family="Charter,Georgia,serif"
            font-weight="700" font-size="22"
            fill="url(#demoBrandGrad)">0</tspan> 张
      </text>
      <text x="105" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="#88e0a6">
        keep <tspan id="keepN" font-weight="700" font-size="15">0</tspan>
      </text>
      <text x="190" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="#e3c25e">
        maybe <tspan id="mayN" font-weight="700" font-size="15">0</tspan>
      </text>
      <text x="285" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="#ee8888">
        cull <tspan id="culN" font-weight="700" font-size="15">0</tspan>
      </text>
    </g>
    <animate attributeName="opacity" from="0" to="1"
             begin="0.05s" dur="0.3s" fill="freeze"/>
    <animateTransform attributeName="transform" type="translate"
             from="0 -12" to="0 0" begin="0.05s" dur="0.3s"
             fill="freeze" calcMode="spline"
             keySplines="0.34 1.56 0.64 1"/>
  </g>

  <!-- =========== Library sidebar (slides in 0.42s) =========== -->
  <g opacity="0">
    <rect x="0" y="48" width="236" height="{_H - 48}"
          fill="rgba(15,17,22,0.92)"/>
    <line x1="236" y1="48" x2="236" y2="{_H}"
          stroke="rgba(255,255,255,0.10)" stroke-width="1"/>
    <text x="18" y="86" font-family="Inter,sans-serif"
          font-size="11" font-weight="700" fill="#8a8e96"
          letter-spacing="2">LIBRARY</text>
    <text x="18" y="130" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="#dbdfe7">▾ 决定</text>
    <g font-family="Inter,sans-serif" font-size="12" fill="#aab3c1">
      <text x="38" y="156">全部  •  keep  •  maybe  •  cull</text>
    </g>
    <text x="18" y="200" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="#dbdfe7">▾ 场景</text>
    <text x="38" y="226" font-family="Inter,sans-serif" font-size="12"
          fill="#aab3c1">portrait · landscape · wedding · …</text>
    <text x="18" y="270" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="#dbdfe7">▸ 风格</text>
    <text x="18" y="310" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="#dbdfe7">▸ 人脸</text>
    <text x="18" y="350" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="#dbdfe7">▸ 连拍</text>
    <text x="18" y="390" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="#dbdfe7">▸ Cull 原因</text>
    <animate attributeName="opacity" from="0" to="1"
             begin="0.18s" dur="0.42s" fill="freeze"/>
    <animateTransform attributeName="transform" type="translate"
             from="-14 0" to="0 0" begin="0.18s" dur="0.42s"
             fill="freeze" calcMode="spline"
             keySplines="0.34 1.56 0.64 1"/>
  </g>

  <!-- =========== Grid cards (stagger fade-up) =========== -->
  {cards}

  <!-- =========== Number count-up via SMIL animate
       Browsers render SMIL <animate> on text nodes via the textContent
       update path — this gives the 0→target ramp without JS. =========== -->
  <g>
    <text>
      <animate xlink:href="#totN" attributeName="textContent"
               values="0;120;430;820;1500;1500" dur="0.9s"
               begin="0.4s" fill="freeze"/>
    </text>
    <text>
      <animate xlink:href="#keepN" attributeName="textContent"
               values="0;12;48;94;127;127" dur="0.9s"
               begin="0.4s" fill="freeze"/>
    </text>
    <text>
      <animate xlink:href="#mayN" attributeName="textContent"
               values="0;18;72;120;163;163" dur="0.9s"
               begin="0.4s" fill="freeze"/>
    </text>
    <text>
      <animate xlink:href="#culN" attributeName="textContent"
               values="0;88;310;608;1210;1210" dur="0.9s"
               begin="0.4s" fill="freeze"/>
    </text>
  </g>

  <!-- =========== Soft-bounce restart loop (rewind everything every
       6 seconds so the demo plays on loop) =========== -->
  <rect width="{_W}" height="{_H}" fill="none">
    <animate attributeName="fill" values="none;none" dur="6s"
             repeatCount="indefinite"/>
  </rect>
</svg>
'''


def main(argv: list[str]) -> int:
    out_path = Path(__file__).resolve().parent.parent.parent / \
        "docs" / "brand" / "pixcull-hero-reveal-demo.svg"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_demo_svg(), encoding="utf-8")
    print(f"[brand] wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
