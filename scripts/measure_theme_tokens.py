#!/usr/bin/env python3
"""v3.73 (Phase A.1) — read the shipped palette out of a rendered page.

`design-system/tokens.json` is supposed to say what the product's colours
are. It did not, and could not have been fixed by reading the CSS: the
product computes its palette with relative colour —

    --accent-hi: oklch(from var(--accent) calc(l + 0.064) c h);

— so the source contains arithmetic, not values, and a second theme
recomputes the same arithmetic from a different base. Working it out by
hand produces numbers that look right and are not what ships. Measured
here instead: open the built page in each theme, resolve every custom
property, and paint it into a 1x1 canvas so the answer comes back as the
sRGB bytes a screen would actually receive.

What that found the first time it ran: fifteen of the sixteen role
tokens in the design system held a value the product had stopped
shipping. The pattern was one change — v2.21 made the surfaces
achromatic so the photo surround could not tint colour judgment, and the
design system kept the warm set (`#161310` against the shipped
`#161616`, `#f3ede1` against `#e6e6e6`). Phase A.1 was going to add a
light theme to a file that was wrong about the dark one.

    scripts/measure_theme_tokens.py            # print the table
    scripts/measure_theme_tokens.py --write    # update tokens.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "pixcull" / "report" / "templates" / "results.html"
TOKENS = ROOT / "design-system" / "tokens.json"

#: token path -> the custom property the product renders for that role.
#: The brand ramp was matched by value; the rest by role, then checked
#: against the render. A pair that stops matching is a real question, so
#: this map is asserted in tests/test_design_system_matches_the_product.py
#: rather than left as a comment.
ROLE = {
    "color.brand.champagne": "--accent",
    "color.brand.champagne-hi": "--accent-hi",
    "color.brand.champagne-mid": "--accent-mid",
    "color.brand.champagne-deep": "--accent-deep",
    "color.surface.bg": "--bg",
    "color.surface.bg-card": "--bg-card",
    "color.surface.bg-card-hi": "--bg-card-hi",
    "color.surface.surface-2": "--surface-2",
    "color.surface.surface-3": "--surface-3",
    "color.surface.chrome": "--chrome",
    "color.fg.primary": "--fg",
    "color.fg.secondary": "--fg-2",
    "color.fg.muted": "--muted",
    "color.fg.muted-soft": "--muted-soft",
    "color.border.default": "--border",
    "color.border.hi": "--border-hi",
    "color.accent.default": "--accent",
    "color.accent.hi": "--accent-hi",
    "color.semantic.success": "--c-success",
    "color.semantic.warn": "--c-warn",
    "color.semantic.danger": "--c-danger",
    "color.semantic.info": "--c-info",
    "color.semantic.neutral": "--c-neutral",
    "color.decision.keep-cb": "--keep-cb",
    "color.decision.maybe-cb": "--maybe-cb",
    "color.decision.cull-cb": "--cull-cb",
}

_READ_PROPERTIES = """(names) => {
    const cs = getComputedStyle(document.documentElement);
    const probe = document.createElement('div');
    document.body.appendChild(probe);
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    const g = cv.getContext('2d', {willReadFrequently: true});
    const hex = v => '#' + [...v].map(x => x.toString(16).padStart(2, '0')).join('');
    const out = {};
    for (const n of names) {
        probe.style.color = '';
        probe.style.color = `var(${n})`;
        // getComputedStyle keeps oklch() as oklch(), and so does canvas
        // fillStyle. Painting one pixel and reading it back is the only
        // step that actually forces the sRGB conversion a screen does.
        const computed = getComputedStyle(probe).color;
        let srgb = null, alpha = 1;
        try {
            g.clearRect(0, 0, 1, 1);
            g.fillStyle = computed;
            g.fillRect(0, 0, 1, 1);
            const d = g.getImageData(0, 0, 1, 1).data;
            alpha = d[3] / 255;
            srgb = hex([d[0], d[1], d[2]]);
        } catch (e) {}
        out[n] = {srgb, alpha: Math.round(alpha * 1000) / 1000};
    }
    probe.remove();
    return out;
}"""


def measure(properties: list[str]) -> dict:
    from playwright.sync_api import sync_playwright

    url = "file://" + str(PAGE.resolve())
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ("dark", "light"):
            ctx = browser.new_context(color_scheme=theme)
            page = ctx.new_page()
            page.add_init_script(
                f"localStorage.setItem('pixcull_theme','{theme}')")
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(1200)
            # Both signals, because the page honours the stored choice and
            # the OS preference through different paths.
            page.evaluate(
                f"document.documentElement.setAttribute('data-theme','{theme}')")
            page.wait_for_timeout(300)
            out[theme] = page.evaluate(_READ_PROPERTIES, properties)
            ctx.close()
        browser.close()
    return out


def _flat(doc) -> dict:
    flat = {}

    def walk(n, p=""):
        if isinstance(n, dict):
            if "value" in n and isinstance(n["value"], str):
                flat[p] = n["value"]
            else:
                for k, v in n.items():
                    walk(v, f"{p}.{k}" if p else k)
    walk(doc)
    return flat


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="update design-system/tokens.json in place")
    args = ap.parse_args()

    doc = json.loads(TOKENS.read_text(encoding="utf-8"),
                     object_pairs_hook=collections.OrderedDict)
    flat = _flat(doc)
    meas = measure(sorted(set(ROLE.values())))

    print(f"{'token':32}{'declared':11}{'dark':11}{'light':11}")
    stale = []
    for path, prop in ROLE.items():
        got = meas["dark"].get(prop)
        if not got or not got["srgb"]:
            print(f"{path:32}{'':11}{'UNRESOLVED':11}  ({prop})")
            stale.append(path)
            continue
        declared = flat.get(path, "?")
        mark = "" if declared.lower() == got["srgb"].lower() else "  STALE"
        print(f"{path:32}{declared:11}{got['srgb']:11}"
              f"{meas['light'][prop]['srgb']:11}{mark}")
        if mark:
            stale.append(path)

    if not args.write:
        print(f"\n{len(stale)} of {len(ROLE)} disagree with the render. "
              "Pass --write to correct them and refresh the light theme.")
        return 1 if stale else 0

    def node_at(path):
        n = doc
        for part in path.split("."):
            if part not in n:
                return None
            n = n[part]
        return n if isinstance(n, dict) and "value" in n else None

    light = collections.OrderedDict()
    for path, prop in ROLE.items():
        node, got = node_at(path), meas["dark"].get(prop)
        if node is None or not got or not got["srgb"]:
            continue
        node["value"] = got["srgb"]
        light[path] = meas["light"][prop]["srgb"]
    doc["_themes"]["light"] = light
    TOKENS.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"\nwrote {TOKENS}: {len(light)} light entries, dark corrected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
