#!/usr/bin/env python3
"""Brand kit — animated SVG demo of PixCull's hero reveal.

Embedded in README.md as
``<img src="docs/brand/pixcull-hero-reveal-demo.svg">``.

Recipe mirrors the v0.9-P0-2 hero reveal:
  1. Workspace bar slides down
  2. Library sidebar slides in from the left
  3. Grid cards stagger fade-up from the bottom

Three things this file gets wrong easily, all of them learned the hard
way — read them before editing.

**1. The static frame has to be the FINISHED one.**  Every group used to
be authored ``opacity="0"`` and to depend on SMIL to become visible.  An
``<img>``-embedded SVG is an isolated document, and any renderer that
strips or does not run SMIL — some Markdown pipelines, feed readers, PDF
export — then shows a black rectangle where the demo should be.  So the
base attributes below are the END state, and each ``<animate>`` runs
*from* the hidden state *to* the state already authored.  With SMIL you
get the reveal; without it you get the finished screen.  Never author a
group at ``opacity="0"`` here.

**2. Do not animate a paint keyword.**  This file used to end with

    <rect width="1280" height="720" fill="none">
      <animate attributeName="fill" values="none;none" dur="6s"
               repeatCount="indefinite"/>
    </rect>

labelled a "restart loop".  It never looped anything — SMIL cannot rewind
unrelated animations from a sibling rect — and Chrome resolves the
interpolated paint keyword ``none`` to an invalid colour and composites
it as OPAQUE BLACK across the rect's whole area, forever, because of the
``repeatCount``.  The published README image was 921,600 pixels of pure
#000000.  Measured: 1 distinct colour before removing that rect, 1,704
after.  There is no loop now; the intro plays once and freezes.

**3. ``textContent`` is not animatable.**  The stat counters used to be

    <animate xlink:href="#keepN" attributeName="textContent"
             values="0;12;48;94;127;127" .../>

with a comment asserting browsers honour it.  They do not — it is a DOM
property, not an SVG attribute — so every counter sat at its authored
``0`` and the demo advertised a shoot with zero keeps.  The totals are
authored directly now, and ``<desc>`` no longer claims a count-up.

The palette is read from ``pixcull-brand.json``, the same source
``gen_brand_svg.py`` uses.  It used to be hard-coded here, and when the
brand was redesigned the committed SVG was updated and this generator was
not — so the "regenerate with…" line in the README would have silently
reverted the brand.  Do not paste hex values back into this file.

Regenerate with:  python scripts/brand/gen_animated_demo.py
Checked by:       tests/test_readme_image_sources.py
                  tests/test_readme_images_render.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_W, _H = 1280, 720

_BRAND_FILE = Path(__file__).resolve().parent / "pixcull-brand.json"


def _brand() -> dict:
    """Palette + decision colours, from the shared brand token file."""
    data = json.loads(_BRAND_FILE.read_text(encoding="utf-8"))
    return {**data["palette"], **{f"decision_{k}": v
                                  for k, v in data["decision"].items()}}


#: What the demo says the shoot came to. These are the numbers a reader
#: sees, so they have to add up: keep + maybe + cull == total.
_TOTAL, _KEEP, _MAYBE, _CULL = 1500, 127, 163, 1210
assert _KEEP + _MAYBE + _CULL == _TOTAL, "the demo's stats must add up"


def _demo_svg() -> str:
    b = _brand()

    # 24 cards in a 6×4 grid. 80ms of stagger per card reads as a
    # cascade rather than a pop; the whole grid is in by ~2.9s.
    #
    # Each card is authored AT its final position with full opacity —
    # see note 1 in the module docstring — and animates up into it.
    cards_xml = []
    decision_cycle = (b["decision_keep"], b["decision_maybe"],
                      b["decision_cull"])
    for r in range(4):
        for c in range(6):
            i = r * 6 + c
            x = 380 + c * 142
            y = 220 + r * 110
            delay = 1.0 + i * 0.08
            colour = decision_cycle[i % 3]
            cards_xml.append(f'''
    <g transform="translate({x},{y})">
      <rect width="124" height="92" rx="8"
            fill="#1a1611" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>
      <rect x="6" y="6" width="112" height="60" rx="4" fill="#241f17"/>
      <circle cx="116" cy="78" r="6" fill="{colour}"/>
      <text x="10" y="84" font-family="ui-monospace, monospace"
            font-size="8.5" fill="{b['textMuted']}">IMG_{i:04d}.jpg</text>
      <animate attributeName="opacity"
               from="0" to="1" begin="{delay}s" dur="0.4s" fill="freeze"/>
      <animateTransform attributeName="transform" type="translate"
               from="{x} {y + 24}" to="{x} {y}"
               begin="{delay}s" dur="0.5s" fill="freeze"
               calcMode="spline" keySplines="0.34 1.56 0.64 1"/>
    </g>''')
    cards = "".join(cards_xml)

    return f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {_W} {_H}"
     width="{_W}" height="{_H}" role="img"
     aria-label="PixCull review screen — workspace bar, Library sidebar and a grid of 24 analyzed photos, each tagged keep, maybe or cull">
  <title>PixCull · hero reveal</title>
  <desc>
    PixCull's opening moment: the workspace bar slides down, the Library
    sidebar slides in from the left, and 24 photo cards stagger up from
    below with soft-bounce easing, each carrying a keep / maybe / cull
    dot. The shoot header reads {_TOTAL} frames — {_KEEP} keep,
    {_MAYBE} maybe, {_CULL} cull. Mirrors the live behaviour shipped in
    v0.9-P0-2. Where SMIL animation is unavailable this renders as the
    finished screen rather than an empty one.
  </desc>
  <defs>
    <linearGradient id="demoBrandGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%"   stop-color="{b['wordmarkStart']}"/>
      <stop offset="50%"  stop-color="{b['wordmarkMid']}"/>
      <stop offset="100%" stop-color="{b['wordmarkEnd']}"/>
    </linearGradient>
    <radialGradient id="demoBg" cx="30%" cy="35%" r="80%">
      <stop offset="0%"  stop-color="{b['bgCosmic']}"/>
      <stop offset="55%" stop-color="{b['bgMid']}"/>
      <stop offset="100%" stop-color="{b['bgDeep']}"/>
    </radialGradient>
  </defs>

  <!-- Background canvas -->
  <rect width="{_W}" height="{_H}" fill="url(#demoBg)"/>
  <rect width="{_W}" height="{_H}" fill="{b['bgDeep']}" opacity="0.35"/>

  <!-- =========== Workspace bar (slides down 0.3s) =========== -->
  <g>
    <rect x="0" y="0" width="{_W}" height="48"
          fill="rgba(20,23,28,0.94)"/>
    <line x1="0" y1="48" x2="{_W}" y2="48"
          stroke="rgba(255,255,255,0.10)" stroke-width="1"/>
    <!-- logo mark — same "spotlight on one in a crowd" as the
         real product workspace bar -->
    <g transform="translate(20,12) scale(1)">
      <circle cx="4"  cy="5"  r="1.6" fill="{b['wordmarkStart']}" opacity="0.32"/>
      <circle cx="20" cy="6"  r="1.4" fill="{b['wordmarkStart']}" opacity="0.28"/>
      <circle cx="3"  cy="19" r="1.8" fill="{b['wordmarkStart']}" opacity="0.30"/>
      <circle cx="21" cy="20" r="1.3" fill="{b['wordmarkStart']}" opacity="0.28"/>
      <circle cx="12" cy="12" r="7"  fill="url(#demoBrandGrad)"/>
    </g>
    <text x="56" y="30" font-family="Inter, -apple-system, sans-serif"
          font-size="15" font-weight="700" fill="{b['textBody']}">
      Pix<tspan fill="url(#demoBrandGrad)">Cull</tspan>
    </text>
    <text x="120" y="30" font-family="Inter, sans-serif"
          font-size="12.5" font-weight="500" fill="{b['textMuted']}"
          letter-spacing="0.5">
      / 分析结果 · sample_a1b2
    </text>
    <!-- Shoot header. Authored values, not animated — see note 3. -->
    <g transform="translate(880,30)">
      <text x="0" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="{b['textMuted']}">
        共 <tspan font-family="Charter,Georgia,serif"
            font-weight="700" font-size="22"
            fill="url(#demoBrandGrad)">{_TOTAL}</tspan> 张
      </text>
      <text x="120" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="{b['decision_keep']}">
        keep <tspan font-weight="700" font-size="15">{_KEEP}</tspan>
      </text>
      <text x="215" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="{b['decision_maybe']}">
        maybe <tspan font-weight="700" font-size="15">{_MAYBE}</tspan>
      </text>
      <text x="320" y="0" font-family="Inter,sans-serif"
            font-size="13" fill="{b['decision_cull']}">
        cull <tspan font-weight="700" font-size="15">{_CULL}</tspan>
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
  <g>
    <rect x="0" y="48" width="236" height="{_H - 48}"
          fill="rgba(15,17,22,0.92)"/>
    <line x1="236" y1="48" x2="236" y2="{_H}"
          stroke="rgba(255,255,255,0.10)" stroke-width="1"/>
    <text x="18" y="86" font-family="Inter,sans-serif"
          font-size="11" font-weight="700" fill="{b['textMuted']}"
          letter-spacing="2">LIBRARY</text>
    <text x="18" y="130" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="{b['textBody']}">▾ 决定</text>
    <g font-family="Inter,sans-serif" font-size="12" fill="{b['wordmarkStart']}">
      <text x="38" y="156">全部  •  keep  •  maybe  •  cull</text>
    </g>
    <text x="18" y="200" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="{b['textBody']}">▾ 场景</text>
    <text x="38" y="226" font-family="Inter,sans-serif" font-size="12"
          fill="{b['wordmarkStart']}">portrait · landscape · wedding · …</text>
    <text x="18" y="270" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="{b['textBody']}">▸ 风格</text>
    <text x="18" y="310" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="{b['textBody']}">▸ 人脸</text>
    <text x="18" y="350" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="{b['textBody']}">▸ 连拍</text>
    <text x="18" y="390" font-family="Inter,sans-serif"
          font-size="12.5" font-weight="600" fill="{b['textBody']}">▸ Cull 原因</text>
    <animate attributeName="opacity" from="0" to="1"
             begin="0.18s" dur="0.42s" fill="freeze"/>
    <animateTransform attributeName="transform" type="translate"
             from="-14 0" to="0 0" begin="0.18s" dur="0.42s"
             fill="freeze" calcMode="spline"
             keySplines="0.34 1.56 0.64 1"/>
  </g>

  <!-- =========== Grid cards (stagger fade-up) =========== -->
  {cards}
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
