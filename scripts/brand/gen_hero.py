#!/usr/bin/env python3
"""Brand kit — the README hero.

What it shows, and why that and not something else.

The hero this replaces was a hand-drawn SVG of the product UI in which
every photograph was an empty grey rectangle. A photo-culling tool whose
opening image contains no photographs has already failed the two-second
test. Every image-handling project worth copying — PhotoPrism, Immich,
Darktable, RawTherapee — puts real pictures in the hero, and so does
this now.

The frames are real. They come from `docs/screenshots/01-results-grid.png`,
already committed and already published: the owner's own museum shoot,
with the scores the product actually gave them. Two of them —
`3J0A9496` at 0.85 and `3J0A9494` at 0.72 — are the same scissors shot
twice, seconds apart. That pair is the whole product in one picture: two
frames of one moment, and a reason to keep one.

So the composition is the brand mark at scale. Crop brackets around the
frame that was marked, the rest of the take dimmed behind it — the same
idea as `gen_brand_svg.py`'s logo, drawn large enough to see what the
frames are.

Two people are deliberately not in it. `3J0A9665` has a visitor's
silhouette in the corner, and although it is already published inside
that screenshot, a hero is a different kind of prominence for somebody
who did not agree to be in it. `3J0A9541`'s neighbour is behind the
onboarding popup and unusable.

Constraints this is built to, all verified rather than assumed:

* GitHub renders SVG only through `<img>`/`<picture>`, never inline, and
  camo's CSP is `default-src 'none'; img-src data:` — so every pixel has
  to be in the file. The photographs are base64 JPEG at 200 px wide,
  quality 62, which is about 6 KB each.
* `prefers-color-scheme` inside an `<img>`-embedded SVG reads the
  operating system's setting, NOT GitHub's own theme toggle. The
  `<picture>` element with `media=` on `<source>` is the only thing that
  follows the toggle, so this writes two files rather than one clever
  one.
* No SMIL. v3.45 shipped a hero that was 921,600 pixels of black because
  a SMIL animation interpolated a paint keyword, and the lesson stuck:
  the static frame is the only frame.
* No fixed `width` on the root, so it scales from GitHub's ~830 px
  column down to a phone without clipping.

Regenerate with:  python scripts/brand/gen_hero.py
Checked by:       tests/test_readme_image_sources.py
                  tests/test_readme_images_render.py
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOT = ROOT / "docs" / "screenshots" / "01-results-grid.png"
BRAND_FILE = Path(__file__).resolve().parent / "pixcull-brand.json"
OUT_DIR = ROOT / "docs" / "brand"

W, H = 1280, 540

#: Where each frame sits in the source screenshot, and what the product
#: scored it. Crops start 48 px below the card's top edge to leave the
#: UI's own tick badge out of the picture.
FRAMES = [
    # (name, x0, x1, y0, score, chosen)
    ("3J0A9822", 522, 1078, 351, "0.88", False),
    ("3J0A9601", 1690, 2246, 351, "0.77", False),
    ("3J0A9893", 522, 1078, 958, "0.73", False),
    ("3J0A9496", 1106, 1662, 351, "0.85", True),    # kept
    ("3J0A9494", 1690, 2246, 958, "0.72", False),   # its near-duplicate
    ("3J0A9541", 1106, 1662, 958, "0.73", False),
]

#: The chosen frame's index in FRAMES — the fourth of six, near the
#: golden-ratio point rather than dead centre.
CHOSEN = 3
#: Its near-duplicate, which sits immediately to the right.
TWIN = 4

THUMB_W = 200
JPEG_QUALITY = 62


def brand() -> dict:
    data = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
    return {**data["palette"],
            **{f"decision_{k}": v for k, v in data["decision"].items()}}


def _thumbs() -> dict[str, str]:
    """Crop, downscale and base64 each frame. Returns name -> data URI."""
    from PIL import Image

    if not SCREENSHOT.is_file():
        raise SystemExit(f"missing {SCREENSHOT}")
    src = Image.open(SCREENSHOT).convert("RGB")
    out = {}
    for name, x0, x1, y0, _score, _chosen in FRAMES:
        # +48 clears the UI tick badge; the card's photo area is 339 tall.
        crop = src.crop((x0 + 8, y0 + 48, x1 - 8, y0 + 339))
        h = round(crop.height * THUMB_W / crop.width)
        buf = io.BytesIO()
        crop.resize((THUMB_W, h), Image.LANCZOS).save(
            buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
        out[name] = ("data:image/jpeg;base64,"
                     + base64.b64encode(buf.getvalue()).decode())
    return out


def _svg(theme: str, thumbs: dict[str, str]) -> str:
    b = brand()
    dark = theme == "dark"

    ground_a = b["bgCosmic"] if dark else "#faf8f4"
    ground_b = b["bgMid"] if dark else "#f2eee6"
    ground_c = b["bgDeep"] if dark else "#e9e3d7"
    text_hi = b["textBody"] if dark else "#23201b"
    text_lo = b["textMuted"] if dark else "#6f6a61"
    frame_edge = "rgba(255,255,255,0.10)" if dark else "rgba(20,18,15,0.12)"
    # An unchosen frame is present, not hidden: enough to read as a
    # photograph, not enough to compete with the one that was marked.
    dim = 0.44 if dark else 0.5

    fw, fh, gap = 190, 150, 15
    strip_w = len(FRAMES) * fw + (len(FRAMES) - 1) * gap
    x0 = (W - strip_w) / 2
    y0 = 292

    cells = []
    for i, (name, *_rest) in enumerate(FRAMES):
        score = FRAMES[i][4]
        chosen = i == CHOSEN
        x = x0 + i * (fw + gap)
        # The marked frame stands slightly proud of the strip.
        y = y0 - 10 if chosen else y0
        h = fh + 20 if chosen else fh
        w = fw + 14 if chosen else fw
        cx = x - 7 if chosen else x
        op = 1.0 if chosen else dim
        cells.append(f'''
    <g>
      <clipPath id="clip{i}">
        <rect x="{cx:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="5"/>
      </clipPath>
      {f'<rect x="{cx:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="5" fill="#000" filter="url(#lift)" opacity="0.9"/>' if chosen else ''}
      <image href="{thumbs[name]}" x="{cx:.0f}" y="{y:.0f}"
             width="{w}" height="{h}" opacity="{op}"
             preserveAspectRatio="xMidYMid slice" clip-path="url(#clip{i})"
             {'' if chosen else 'filter="url(#rest)"'}/>
      <rect x="{cx:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="5"
            fill="none" stroke="{frame_edge}" stroke-width="1"/>''')
        if chosen:
            # Crop brackets — the mark, at the size where you can see
            # what it is bracketing.
            L, T, R, B = cx, y, cx + w, y + h
            a, arm = b["accent"], 22
            cells.append(f'''
      <g stroke="{a}" stroke-width="2.5" fill="none" stroke-linecap="square">
        <path d="M{L-3} {T+arm} L{L-3} {T-3} L{L+arm} {T-3}"/>
        <path d="M{R-arm} {T-3} L{R+3} {T-3} L{R+3} {T+arm}"/>
        <path d="M{R+3} {B-arm} L{R+3} {B+3} L{R-arm} {B+3}"/>
        <path d="M{L+arm} {B+3} L{L-3} {B+3} L{L-3} {B-arm}"/>
      </g>
      <g transform="translate({cx+8:.0f},{y+h-26:.0f})">
        <rect width="86" height="19" rx="9.5"
              fill="{b['decision_keep']}" opacity="0.92"/>
        <text x="43" y="13.5" text-anchor="middle"
              font-family="Inter,-apple-system,'PingFang SC',sans-serif"
              font-size="11" font-weight="700" fill="#0d1a12">保留 {score}</text>
      </g>''')
        else:
            cells.append(f'''
      <text x="{cx+w-8:.0f}" y="{y+h-9:.0f}" text-anchor="end"
            font-family="ui-monospace,'SF Mono',Menlo,monospace"
            font-size="10.5" fill="{text_lo}" opacity="0.85">{score}</text>''')
        if i == TWIN:
            # Tie the pair together explicitly. "same moment" floating
            # under one frame reads as a caption for that frame; a line
            # spanning both says which two it is talking about, which is
            # the entire point of the picture.
            cl = x0 + CHOSEN * (fw + gap) - 7
            cr = cx + w
            mid = (cl + cr) / 2
            ty = y0 + fh + 26
            cells.append(f'''
      <g stroke="{text_lo}" stroke-width="1" opacity="0.5" fill="none">
        <path d="M{cl:.0f} {ty-7:.0f} L{cl:.0f} {ty:.0f} L{mid-62:.0f} {ty:.0f}"/>
        <path d="M{mid+62:.0f} {ty:.0f} L{cr:.0f} {ty:.0f} L{cr:.0f} {ty-7:.0f}"/>
      </g>
      <text x="{mid:.0f}" y="{ty+4:.0f}" text-anchor="middle"
            font-family="Inter,-apple-system,'PingFang SC',sans-serif"
            font-size="11.5" fill="{text_lo}">same moment · 同一瞬间</text>''')
        cells.append("    </g>")

    # The rest of the take, pushed back: desaturated as well as dimmed.
    # Opacity alone reads as "underexposed"; dropping the colour reads as
    # "not the one", which is what the picture is about.
    unchosen_filter = (
        '  <filter id="rest" x="0" y="0" width="100%" height="100%">\n'
        '    <feColorMatrix type="saturate" values="0.25"/>\n'
        '  </filter>')

    grain = ""
    if dark:
        grain = '''
  <filter id="grain" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="0.85"
                  numOctaves="2" stitchTiles="stitch"/>
    <feColorMatrix type="saturate" values="0"/>
  </filter>'''

    grain_rect = ('  <rect width="{w}" height="{h}" filter="url(#grain)" '
                  'opacity="0.035"/>'.format(w=W, h=H)) if dark else ""

    return f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"
     role="img"
     aria-label="Six frames from one museum shoot. The fourth is bracketed and marked keep at 0.85; the frame beside it is the same moment at 0.72.">
  <title>PixCull — the frame you marked</title>
  <desc>
    Six photographs from one shoot, laid out as a strip on a dark warm
    ground. Five are dimmed. The fourth stands slightly proud, at full
    brightness, inside amber crop brackets and carrying a green keep
    badge reading 0.85. The frame immediately to its right is the same
    subject photographed seconds apart, dimmed, scored 0.72 and labelled
    "same moment" — the choice this tool exists to make and to explain.
  </desc>
  <defs>
    <radialGradient id="ground" cx="32%" cy="22%" r="92%">
      <stop offset="0%"   stop-color="{ground_a}"/>
      <stop offset="55%"  stop-color="{ground_b}"/>
      <stop offset="100%" stop-color="{ground_c}"/>
    </radialGradient>
    <linearGradient id="wm" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%"   stop-color="{b['wordmarkStart'] if dark else '#a8894e'}"/>
      <stop offset="55%"  stop-color="{b['wordmarkMid'] if dark else '#8d7340'}"/>
      <stop offset="100%" stop-color="{b['wordmarkEnd'] if dark else '#6f5a31'}"/>
    </linearGradient>{grain}
{unchosen_filter}
    <filter id="lift" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="10" stdDeviation="14"
                    flood-color="#000" flood-opacity="{0.55 if dark else 0.22}"/>
    </filter>
  </defs>

  <rect width="{W}" height="{H}" fill="url(#ground)"/>
{grain_rect}

  <text x="{W/2}" y="104" text-anchor="middle"
        font-family="Charter,'Iowan Old Style','PT Serif',Georgia,serif"
        font-size="56" font-weight="700" fill="{text_hi}">Pix<tspan
        fill="url(#wm)">Cull</tspan></text>

  <text x="{W/2}" y="146" text-anchor="middle"
        font-family="Inter,-apple-system,'Segoe UI',sans-serif"
        font-size="14.5" font-weight="600" fill="{b['accent']}"
        letter-spacing="3.4">AI PHOTO CULLING THAT EXPLAINS THE CULL</text>

  <text x="{W/2}" y="196" text-anchor="middle"
        font-family="Inter,-apple-system,'PingFang SC',sans-serif"
        font-size="18.5" fill="{text_hi}">Two frames of one moment. It picks one — and writes down why.</text>
  <text x="{W/2}" y="226" text-anchor="middle"
        font-family="Inter,-apple-system,'PingFang SC','Microsoft Yahei UI',sans-serif"
        font-size="16" fill="{text_lo}">同一个瞬间拍了两张。它挑出一张,并把理由写下来。</text>
{''.join(cells)}

  <text x="{W/2}" y="{H-22}" text-anchor="middle"
        font-family="ui-monospace,'SF Mono',Menlo,monospace"
        font-size="11.5" fill="{text_lo}" opacity="0.75"
        letter-spacing="0.6">six frames from one shoot · scored on this machine · MIT</text>
</svg>
'''


def main(argv: list[str]) -> int:
    thumbs = _thumbs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for theme in ("dark", "light"):
        path = OUT_DIR / f"pixcull-hero-{theme}.svg"
        path.write_text(_svg(theme, thumbs), encoding="utf-8")
        print(f"[brand] wrote {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
