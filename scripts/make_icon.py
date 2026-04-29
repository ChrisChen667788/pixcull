"""V7.0: generate app/PixCull.icns from a programmatic vector design.

The .app currently ships with PyInstaller's default icon — fine for
dev, ugly for distribution. This script makes a clean PIL-rendered
icon (gradient camera-aperture shape on a brand-coded background)
and writes it as a multi-resolution .icns macOS expects.

Output: app/PixCull.icns

Run once before release:
    python scripts/make_icon.py

The resulting .icns is referenced from app/pixcull.spec via the
``icon=`` argument; build_app.sh picks it up automatically.

Why programmatic and not a designer file
========================================
The user explicitly wants a working .app today, not a 2-week
design cycle. A clean geometric icon — concentric circles
suggesting an aperture, on a deep teal-to-amber gradient
(matching the demo's keep / cull palette) — is recognizable
and ships immediately.

Replace this script's output with a designed .icns later by
just dropping a different ``app/PixCull.icns`` in place; the
build pipeline doesn't care about origin.
"""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


# Apple icon-set requires these specific sizes for a complete .icns.
# iconutil packages a folder of PNGs at these resolutions.
ICONSET_SIZES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

# Color palette mirrors the demo CSS: deep teal background fading to
# amber, with the keep-green accent on the aperture blade highlights.
BG_TOP = (24, 38, 50)        # near-black teal (matches --bg)
BG_BOT = (217, 163, 12)      # amber (matches --maybe)
BLADE_FILL = (46, 168, 74)   # keep green
BLADE_HIGHLIGHT = (255, 255, 255)


def _gradient_bg(size: int) -> Image.Image:
    """Vertical linear gradient from BG_TOP to BG_BOT."""
    img = Image.new("RGB", (size, size), BG_TOP)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def _aperture(size: int, blades: int = 6) -> Image.Image:
    """Camera aperture rendered as a 6-blade iris on transparent bg.

    Each blade is an isoceles triangle pointed inward from the
    perimeter. Blades overlap at the center to form a small hexagonal
    opening. RGBA so we can composite onto the gradient.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    outer_r = size * 0.42
    inner_r = size * 0.07     # how big the central opening is

    # Draw blades as polygons. Each is a triangle from two perimeter
    # angles to a single inner point offset from center.
    for i in range(blades):
        a0 = (2 * math.pi / blades) * i - math.pi / blades
        a1 = (2 * math.pi / blades) * (i + 1) - math.pi / blades
        # Outer two points
        p0 = (cx + outer_r * math.cos(a0), cy + outer_r * math.sin(a0))
        p1 = (cx + outer_r * math.cos(a1), cy + outer_r * math.sin(a1))
        # Inner point — offset from the bisector to give the
        # signature curved-iris look
        bisector = (a0 + a1) / 2
        p2 = (cx + inner_r * math.cos(bisector + math.pi / 8),
              cy + inner_r * math.sin(bisector + math.pi / 8))
        d.polygon([p0, p1, p2], fill=BLADE_FILL + (220,))

    # Outline ring
    d.ellipse(
        (cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r),
        outline=BLADE_HIGHLIGHT, width=max(1, size // 80),
    )
    # Soft glow around the aperture
    glow = img.filter(ImageFilter.GaussianBlur(radius=size / 64))
    return Image.alpha_composite(glow, img)


def _build_one(size: int) -> Image.Image:
    """One PNG of size×size."""
    bg = _gradient_bg(size).convert("RGBA")
    iris = _aperture(size)
    return Image.alpha_composite(bg, iris)


def _iconutil_available() -> bool:
    return shutil.which("iconutil") is not None


def main() -> int:
    out = Path("app/PixCull.icns")
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "PixCull.iconset"
        iconset.mkdir()
        # Render one PNG per Apple-required size
        cache: dict[int, Image.Image] = {}
        for size, fn in ICONSET_SIZES:
            if size not in cache:
                cache[size] = _build_one(size)
            cache[size].save(iconset / fn, "PNG", optimize=True)
        print(f"  rendered {len(cache)} unique sizes "
              f"into {iconset}")

        if not _iconutil_available():
            print("WARNING: iconutil not found (Xcode CLI tools missing). "
                  "Saving the largest PNG only.", file=sys.stderr)
            # Fall back to a single 1024 PNG renamed .icns — PyInstaller
            # accepts both, though the system shows a slightly worse
            # rendition at small sizes.
            cache[1024].save(out)
            return 0

        # iconutil is preferred — produces a real Apple .icns
        proc = subprocess.run(
            ["iconutil", "-c", "icns", "-o", str(out), str(iconset)],
            check=True,
        )

    sz = out.stat().st_size
    print(f"✓ Wrote {out}  ({sz // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
