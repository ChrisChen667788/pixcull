"""v2.5-P0-2 — live visual-regression smoke (Playwright).

Loads the grid + lightbox and asserts, on the *rendered* page:
  • no legacy-"AI"-palette computed colour (pink / indigo / violet /
    generic blue) on any element,
  • no console errors / uncaught page errors,
  • the grid onboarding coachmark does not leak into the lightbox
    (the v2.3.1-C overlap regression).

Skips cleanly when Playwright, a chromium build, or a demo run aren't
available — so CI without those still passes; the deterministic half is
``test_palette_guard.py`` (always runs).  On a dev box with a demo run it
catches runtime-computed leaks the static guard can't see.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
# Default to the committed hermetic fixture run so this smoke never depends
# on the mutable / OS-reaped /tmp/pixcull_demo — a sibling test clobbering
# that shared run was silently skipping this regression net.  Env overrides
# let a maintainer point the server at a richer real run instead.
_FIXTURE = ROOT / "tests" / "fixtures" / "smoke_run"
_ENV_ROOT = os.environ.get("PIXCULL_DEMO_ROOT")
RUN = os.environ.get("PIXCULL_SMOKE_RUN", "smoke_run")

# JS: walk every element, flag any computed colour in the legacy family.
# Editorial-warm colours never have blue-dominant-low-green or
# high-red-low-green-with-blue, so this isolates the old palette.
_SCAN = r"""
() => {
  const isLegacy = (s) => {
    const m = (s || '').match(/rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+/g) || [];
    for (const tok of m) {
      const p = tok.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
      const r = +p[1], g = +p[2], b = +p[3];
      const pink   = (r > 180 && g < 110 && b > 110);          // #ec4899
      const bluish = (b > 180 && g < 170 && b > r + 20);       // indigo/violet/blue
      if (pink || bluish) return tok;
    }
    return null;
  };
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    for (const prop of ['color', 'backgroundColor', 'backgroundImage',
                        'borderTopColor', 'borderLeftColor', 'boxShadow']) {
      const hit = isLegacy(s[prop]);
      if (hit) { out.push((el.className || el.tagName) + ' ' + prop + ' ' + hit); break; }
    }
  }
  return [...new Set(out)].slice(0, 25);
}
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    env = dict(os.environ)
    if _ENV_ROOT:
        demo_root = Path(_ENV_ROOT)
    else:
        # Hermetic default: copy the committed fixture run into a private
        # DEMO_ROOT and point the server at it via the env override.
        if not (_FIXTURE / "output" / "scores.csv").is_file():
            pytest.skip("smoke fixture missing")
        demo_root = tmp_path_factory.mktemp("demo_root")
        shutil.copytree(_FIXTURE, demo_root / RUN)
        env["PIXCULL_DEMO_ROOT"] = str(demo_root)
    if not (demo_root / RUN).is_dir():
        pytest.skip(f"no demo run at {demo_root / RUN}")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve_demo.py"),
         "--port", str(port), "--host", "127.0.0.1", "--no-open"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    base = f"http://127.0.0.1:{port}"
    up = False
    for _ in range(40):
        if proc.poll() is not None:
            break
        try:
            urllib.request.urlopen(f"{base}/results/{RUN}", timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.5)
    if not up:
        proc.terminate()
        pytest.skip("serve_demo did not come up on the chosen port")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def test_grid_and_lightbox_have_no_legacy_palette(base_url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:                      # browser not installed
            pytest.skip(f"chromium unavailable: {exc}")
        # reduced-motion so the scan can't catch a mid-transition colour
        # (the hero-reveal animates through intermediate values).
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  reduced_motion="reduce")
        ctx.add_init_script(
            "try{localStorage.setItem('pixcull_theme','dark');"
            "localStorage.setItem('pixcull_onboarded_v1','1');"
            "localStorage.setItem('pixcull_seen_lightbox_keys_v0_13','1');"
            "localStorage.setItem('pixcull_seen_rubric_intro_v1','1');}catch(e){}")
        pg = ctx.new_page()
        errs = []
        # Guard JS errors + uncaught exceptions, NOT demo-asset availability:
        # a CI run has the scores/manifest but not the photographer's source
        # photos, so the lazy /thumb/ + /full/ images 404. results.html is
        # self-contained (inline CSS/JS), so there are no external JS/CSS to
        # 404 — filtering resource-load failures only drops the missing-image
        # noise, never a real regression.
        def _on_console(m):
            if m.type == "error" and "Failed to load resource" not in m.text:
                errs.append(m.text)
        pg.on("console", _on_console)
        pg.on("pageerror", lambda e: errs.append(str(e)))

        pg.goto(f"{base_url}/results/{RUN}", wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_function("document.querySelectorAll('#grid .card').length>3", timeout=30000)
        # Scan the STEADY state: the one-shot hero-reveal animates elements
        # through intermediate values, and a bare <a> momentarily shows the
        # browser's dark-mode UA link colour. Wait for the reveal to clear
        # (fall back to clearing it) before asserting.
        try:
            pg.wait_for_function(
                "!document.body.classList.contains('hero-revealing')", timeout=5000)
        except Exception:
            pg.evaluate("document.body.classList.remove('hero-revealing')")
        pg.wait_for_timeout(600)
        bad_grid = pg.evaluate(_SCAN)

        fn = pg.eval_on_selector("#grid .card", "c => c.dataset.fn")
        pg.evaluate(f"window.openLightbox({json.dumps(fn)})")
        pg.wait_for_timeout(1200)
        bad_lb = pg.evaluate(_SCAN)
        # v2.3.1-C: the grid coachmark must not survive into the lightbox.
        n_tips = pg.evaluate("() => document.querySelectorAll('.onboard-tip').length")
        # v2.5 hotfix guard — the lightbox panes must hold their grid
        # cells (image stage = the wide 1fr column starting at y=0, info
        # panel = the right rail).  The unstyled .companion-grp once
        # auto-flowed into cell (1,1) and shoved the image into the
        # 380px column; this assertion is layout-driven (pane geometry,
        # not image pixels) so it works on the imageless fixture too.
        panes = pg.evaluate(
            "() => {const g = s => {const e = document.querySelector(s);"
            "  if (!e) return null; const r = e.getBoundingClientRect();"
            "  return [Math.round(r.x), Math.round(r.y),"
            "          Math.round(r.width), Math.round(r.height)];};"
            "  return {img: g('.lightbox .img-pane'),"
            "          info: g('.lightbox .info-pane'), vw: innerWidth};}")
        browser.close()

    assert not errs, f"console / page errors: {errs[:6]}"
    assert not bad_grid, f"legacy palette on grid: {bad_grid}"
    assert not bad_lb, f"legacy palette in lightbox: {bad_lb}"
    assert n_tips == 0, f"grid coachmark leaked into the lightbox: {n_tips} tip(s)"
    img_pane, info_pane = panes["img"], panes["info"]
    assert img_pane and info_pane, f"lightbox panes missing: {panes}"
    assert img_pane[2] > panes["vw"] * 0.5, \
        f"lightbox image stage collapsed (companion-grp regression?): {panes}"
    assert img_pane[1] >= 0, f"image stage shoved above the viewport: {panes}"
    assert info_pane[0] >= img_pane[2] - 5, \
        f"info panel not in the right rail: {panes}"
