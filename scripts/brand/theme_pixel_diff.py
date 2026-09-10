#!/usr/bin/env python3
"""v3.72 — screenshot the review page in both themes, for before/after.

Built for the token migration, and kept because the migration is the
kind of change that cannot be reasoned about safely. Replacing a literal
`#d5b584` with `var(--accent)` is a no-op in the dark theme, where the
token holds exactly that value, and a real change in the light theme,
where `--accent` is `#6c501f` deep bronze. Those are the two outcomes to
tell apart, and only a render can.

    scripts/brand/theme_pixel_diff.py --out /tmp/before
    …edit the CSS, rebuild results.html…
    scripts/brand/theme_pixel_diff.py --out /tmp/after
    scripts/brand/theme_pixel_diff.py --compare /tmp/before /tmp/after

Boots serve_demo on its own port, so it does not collide with a server
left running from a capture session — that has cost a whole run before,
appearing as a JSONDecodeError from a stale process on the usual port.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SHOTS = ("dark", "light")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _capture(out: Path, run_id: str | None = None) -> str:
    """Capture both themes. Returns the run id used.

    v3.72 — `--run` exists because the first cut created a fresh sample
    run per capture, and the run id is printed in the page header. The
    before/after diff therefore always showed a few hundred changed
    pixels of greyscale text, which I was about to report as the effect
    of a colour change. Same run on both sides, or the comparison is
    measuring the harness.
    """
    from playwright.sync_api import sync_playwright
    import urllib.request

    out.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    log = open("/tmp/theme_diff_serve.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "scripts/serve_demo.py", "--host", "127.0.0.1",
         "--port", str(port)],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                urllib.request.urlopen(base, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("server never came up; see /tmp/theme_diff_serve.log")

        req = urllib.request.Request(
            base + "/sample_demo", data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        if run_id:
            run = run_id
            print(f"[diff] reusing run {run} on :{port}")
        else:
            run = json.loads(urllib.request.urlopen(req, timeout=300).read())["run_id"]
            print(f"[diff] run {run} on :{port}")

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for theme in SHOTS:
                ctx = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    device_scale_factor=1,
                    color_scheme=theme)
                ctx.add_init_script(
                    "localStorage.setItem('pixcull_theme', %r);"
                    "localStorage.setItem('pixcull_client_present','0');"
                    % theme)
                page = ctx.new_page()
                page.goto(f"{base}/results/{run}", wait_until="networkidle",
                          timeout=180_000)
                page.wait_for_timeout(4000)
                page.screenshot(path=str(out / f"results-{theme}.png"),
                                full_page=False)
                print(f"[diff]   {theme} -> {out / f'results-{theme}.png'}")
                ctx.close()
            browser.close()
        return run
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


#: The champagne ramp — the dark theme's accent. Any of it appearing in a
#: light-theme render is a dark-theme literal that escaped its theme.
CHAMPAGNE = {"#d5b584": (213, 181, 132),
             "#eaca98": (234, 202, 152),
             "#93743f": (147, 116, 63)}
#: The light theme's own accent, for the same question in reverse.
BRONZE = {"#6c501f": (108, 80, 31), "#866939": (134, 105, 57)}


def _count(path: Path, palette: dict, tol: int = 6) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    out = dict.fromkeys(palette, 0)
    for r, g, b in im.get_flattened_data() if hasattr(im, "get_flattened_data") \
            else list(im.getdata()):
        for name, (tr, tg, tb) in palette.items():
            if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
                out[name] += 1
    return out


#: The header row carries `耗时 <n>s`, a per-load timing readout, and it
#: sits in a flex row — so one value changing width re-lays-out the whole
#: row and every glyph in it lands a pixel over. It produced ~4,400
#: changed pixels between two captures of identical CSS, spread across
#: the full width, which is exactly what a real regression would look
#: like. Excluded, and named here rather than silently cropped.
HEADER_ROWS = 90
#: A channel delta this small is gradient/anti-alias rounding, not a
#: colour anyone can see.
IMPERCEPTIBLE = 2


def _compare(before: Path, after: Path) -> int:
    from PIL import Image, ImageChops

    bad = 0
    for theme in SHOTS:
        b, a = before / f"results-{theme}.png", after / f"results-{theme}.png"
        if not (b.exists() and a.exists()):
            print(f"[diff] {theme}: missing capture")
            bad += 1
            continue
        ib, ia = Image.open(b).convert("RGB"), Image.open(a).convert("RGB")
        if ib.size != ia.size:
            print(f"[diff] {theme}: size changed {ib.size} -> {ia.size}")
            bad += 1
            continue
        diff = ImageChops.difference(ib, ia)
        w, h = diff.size
        px = diff.load()
        changed = sum(1 for y in range(HEADER_ROWS, h) for x in range(w)
                      if max(px[x, y]) > IMPERCEPTIBLE)
        total = w * (h - HEADER_ROWS)
        pct = 100.0 * changed / total
        cb = _count(b, CHAMPAGNE)
        ca = _count(a, CHAMPAGNE)
        print(f"\n[diff] {theme}: {changed:,} / {total:,} px changed below the "
              f"header ({pct:.2f}%)")
        print(f"        champagne pixels before: {sum(cb.values()):,}  {cb}")
        print(f"        champagne pixels after : {sum(ca.values()):,}  {ca}")
        if theme == "dark" and changed:
            print("        ^ the dark theme should be identical: the token "
                  "holds the same value the literal did")
            bad += 1
        if theme == "light" and sum(ca.values()) >= sum(cb.values()):
            print("        ^ the light theme should have LOST champagne: "
                  "that is the defect being fixed")
            bad += 1
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--run", help="reuse an existing run id — required for "
                                  "a sound before/after, since the id is "
                                  "printed in the page header")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    a = ap.parse_args()
    if a.compare:
        return 1 if _compare(*a.compare) else 0
    if not a.out:
        ap.error("pass --out DIR or --compare BEFORE AFTER")
    run = _capture(a.out, a.run)
    print(f"[diff] run id: {run}   (pass --run {run} for the other side)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
