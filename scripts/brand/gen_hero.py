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
SAMPLES = ROOT / "samples" / "input"
BRAND_FILE = Path(__file__).resolve().parent / "pixcull-brand.json"
OUT_DIR = ROOT / "docs" / "brand"

W, H = 1280, 540

#: Six frames from `samples/input`, with the score PixCull actually
#: gave them. Reproduce with:
#:
#:     pixcull run samples/input -o /tmp/run --vlm-mode off
#:
#: The pair is 7235 and 7237: the same valley from the same spot, five
#: seconds apart — 15:26:50 and 15:26:55 by the EXIF. The first took
#: 0.84 and the second 0.76, and the run **does** fold them into one
#: cluster, so the hero is showing a grouping the product actually
#: makes rather than an illustration of one.
#:
#: v3.64 replaced the previous pair (7089/7090) for exactly that
#: reason — those two are the same view but the tool does not group
#: them, so the picture claimed something the product would not do.
#: 3J0A9410 came out at the same time: a girl runs across the field at
#: its right edge and her face is legible at native resolution.
FRAMES = [
    ("3J0A9972", "0.90", False),   # highest of the set
    ("3J0A7615", "0.88", False),
    ("3J0A9858", "0.87", False),
    ("3J0A7235", "0.84", True),    # kept — the sharper of the two
    ("3J0A7237", "0.76", False),   # same view, five seconds later
    ("3J0A7090", "0.87", False),
]

#: The chosen frame's index — the fourth of six, near the golden-ratio
#: point rather than dead centre.
CHOSEN = 3
#: The other attempt at the same view, immediately to its right.
TWIN = 4

THUMB_W = 200
JPEG_QUALITY = 62


def brand() -> dict:
    data = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
    return {**data["palette"],
            **{f"decision_{k}": v for k, v in data["decision"].items()}}


def _thumbs() -> dict[str, str]:
    """Downscale each frame and base64 it. Returns name -> data URI."""
    from PIL import Image

    out = {}
    for name, _score, _chosen in FRAMES:
        src = SAMPLES / f"{name}.jpg"
        if not src.is_file():
            raise SystemExit(f"missing {src} — is samples/input intact?")
        im = Image.open(src).convert("RGB")
        h = round(im.height * THUMB_W / im.width)
        buf = io.BytesIO()
        im.resize((THUMB_W, h), Image.LANCZOS).save(
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
    for i, (name, score, _chosen) in enumerate(FRAMES):
        chosen = i == CHOSEN
        x = x0 + i * (fw + gap)
        # The marked frame stands slightly proud of the strip.
        y = y0 - 10 if chosen else y0
        h = fh + 20 if chosen else fh
        w = fw + 14 if chosen else fw
        cx = x - 7 if chosen else x
        # v3.64 — the twin sits between the two treatments. At the
        # strip's normal dimming it is unreadable as "the same view
        # again", which is the one thing it is there to say.
        twin = i == TWIN
        op = 1.0 if chosen else (dim + (1 - dim) * 0.55 if twin else dim)
        cells.append(f'''
    <g>
      <clipPath id="clip{i}">
        <rect x="{cx:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="5"/>
      </clipPath>
      {f'<rect x="{cx:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="5" fill="#000" filter="url(#lift)" opacity="0.9"/>' if chosen else ''}
      <image href="{thumbs[name]}" x="{cx:.0f}" y="{y:.0f}"
             width="{w}" height="{h}" opacity="{op}"
             preserveAspectRatio="xMidYMid slice" clip-path="url(#clip{i})"
             {'' if chosen else ('filter="url(#twin)"' if twin else 'filter="url(#rest)"')}/>
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
        elif i == TWIN:
            # Only the pair carries a number. Three of the other four
            # frames scored higher than the one that was chosen — 0.90,
            # 0.88, 0.87 against 0.84 — because the choice being shown
            # is which of TWO near-duplicates is the peak of its
            # cluster, not which frame is best overall. Printing all six
            # scores invites the comparison the picture is not making.
            # The number sits ON a photograph, so it takes its
            # contrast from the picture and not from the theme:
            # `text_lo` vanished into the light theme's bright hillside
            # while reading fine on the dark one.
            cells.append(f'''
      <text x="{cx+w-8:.0f}" y="{y+h-9:.0f}" text-anchor="end"
            font-family="ui-monospace,'SF Mono',Menlo,monospace"
            font-size="11.5" fill="#ffffff" stroke="rgba(0,0,0,0.55)"
            stroke-width="2.5" paint-order="stroke"
            opacity="0.95">{score}</text>''')
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
            font-size="11.5" fill="{text_lo}">same view, 5s apart · 同一处 · 相隔 5 秒</text>''')
        cells.append("    </g>")

    # The rest of the take, pushed back: desaturated as well as dimmed.
    # Opacity alone reads as "underexposed"; dropping the colour reads as
    # "not the one", which is what the picture is about.
    unchosen_filter = (
        '  <filter id="rest" x="0" y="0" width="100%" height="100%">\n'
        '    <feColorMatrix type="saturate" values="0.25"/>\n'
        '  </filter>\n'
        # The twin keeps most of its colour. It has to look like the
        # frame beside it, or "you framed it twice" is a caption with
        # nothing under it.
        '  <filter id="twin" x="0" y="0" width="100%" height="100%">\n'
        '    <feColorMatrix type="saturate" values="0.75"/>\n'
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
        font-size="18.5" fill="{text_hi}">You framed it twice. It picks one — and writes down why.</text>
  <text x="{W/2}" y="226" text-anchor="middle"
        font-family="Inter,-apple-system,'PingFang SC','Microsoft Yahei UI',sans-serif"
        font-size="16" fill="{text_lo}">同一处你拍了两张。它挑出一张,并把理由写下来。</text>
{''.join(cells)}

  <text x="{W/2}" y="{H-22}" text-anchor="middle"
        font-family="ui-monospace,'SF Mono',Menlo,monospace"
        font-size="11.5" fill="{text_lo}" opacity="0.75"
        letter-spacing="0.6">real frames · scored on this machine · MIT</text>
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
