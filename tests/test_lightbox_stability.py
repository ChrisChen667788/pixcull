"""v2.6 — Playwright regression for the lightbox-freeze fix + near-dup fold.

Two things the hermetic suite couldn't catch and a real-photo dogfood did:
  * the first-open rubric-intro veil ate Escape via ``{once:true}`` — any
    keystroke killed it and the UI froze (the v2.6 stability sweep);
  * the v2.6-P1 near-dup fold UI (≈ pill → fold → ≈N badge → compare).

Uses the same launch-a-real-chromium path as ``test_visual_smoke`` (which
is green in CI), with a private demo root: the committed fixture run plus
a synthetic ``embeddings.npz`` so the near-dup endpoint needs no model.
Skips cleanly when Playwright / chromium aren't available.
"""
from __future__ import annotations

import csv
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = ROOT / "tests" / "fixtures" / "smoke_run"


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    if not (_FIXTURE / "output" / "scores.csv").is_file():
        pytest.skip("smoke fixture missing")
    root = tmp_path_factory.mktemp("demoroot")
    shutil.copytree(_FIXTURE, root / "demo")
    out = root / "demo" / "output"
    fns = sorted(r["filename"] for r in csv.DictReader(open(out / "scores.csv")))
    eye = np.eye(8, dtype=np.float32)
    base = np.zeros(8, np.float32); base[0] = 1.0
    v = [base,
         base + np.array([0, .05, 0, 0, 0, 0, 0, 0], np.float32),
         base + np.array([0, 0, .07, 0, 0, 0, 0, 0], np.float32),
         eye[3], eye[4], eye[5]][:len(fns)]
    vecs = np.stack(v); vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    with open(out / "embeddings.npz", "wb") as fh:
        np.savez(fh, filenames=np.array(fns), vectors=vecs,
                 model=np.array("clip"))
    env = {**os.environ, "PIXCULL_DEMO_ROOT": str(root)}
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
            urllib.request.urlopen(f"{base}/results/demo", timeout=1)
            up = True; break
        except Exception:
            time.sleep(0.5)
    if not up:
        proc.terminate(); pytest.skip("serve_demo did not come up")
    yield base
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()


def _page(pw, base):
    br = pw.chromium.launch()
    ctx = br.new_context(viewport={"width": 1600, "height": 950})
    ctx.add_init_script(
        "try{for(const k of ['pixcull_onboarded_v1',"
        "'pixcull_seen_lightbox_keys_v0_13','pixcull_tour_pulse_v1'])"
        "localStorage.setItem(k,'1');"
        # deliberately DO NOT set seen_rubric_intro → the veil shows
        "localStorage.removeItem('pixcull_seen_rubric_intro_v1');}catch(e){}")
    pg = ctx.new_page()
    pg.goto(f"{base}/results/demo", wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_function("document.querySelectorAll('#grid .card').length>3",
                         timeout=30000)
    pg.wait_for_timeout(700)
    return br, pg


def test_rubric_veil_escape_chain(server):
    """The freeze repro: lightbox open + annotation modal open + the
    first-open rubric-intro veil over it. The veil must swallow stray
    keys (not annotate behind it) and Escape must peel the layers in
    order: veil → annotation modal → lightbox.

    We drive the modal open via its ``.show`` class (what the veil's
    MutationObserver actually keys on) rather than the keyboard path,
    since ``openLightbox`` deliberately doesn't set the grid's
    ``focusedFn`` and the open route varies — the bug being verified is
    purely the veil's Escape handling + the global Escape ordering.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            br, pg = _page(pw, server)
        except Exception as exc:                       # noqa: BLE001
            pytest.skip(f"chromium unavailable: {exc}")
        try:
            fn = pg.eval_on_selector("#grid .card", "c => c.dataset.fn")
            pg.evaluate(f"window.openLightbox({fn!r})"); pg.wait_for_timeout(500)
            assert pg.evaluate("!!document.querySelector('.lightbox.show,#lightbox.show')")
            # open the annotation modal → its MutationObserver injects the veil
            pg.evaluate("document.getElementById('annModal').classList.add('show')")
            pg.wait_for_function("!!document.getElementById('rubricIntroLayer')",
                                 timeout=5000)
            # a stray keyboard-flow key (the freeze trigger) must be eaten
            # by the veil and leave it standing — NOT consume the one-shot
            # Escape handler the old {once:true} bug burned.
            pg.keyboard.press("3"); pg.wait_for_timeout(200)
            assert pg.evaluate("!!document.getElementById('rubricIntroLayer')")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
            assert not pg.evaluate("!!document.getElementById('rubricIntroLayer')")
            assert pg.evaluate("document.getElementById('annModal').classList.contains('show')")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(350)
            assert not pg.evaluate("document.getElementById('annModal').classList.contains('show')")
            assert pg.evaluate("!!document.querySelector('.lightbox.show,#lightbox.show')")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(350)
            assert not pg.evaluate("!!document.querySelector('.lightbox.show,#lightbox.show')")
        finally:
            br.close()


def test_neardup_fold_flow(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            br, pg = _page(pw, server)
        except Exception as exc:                       # noqa: BLE001
            pytest.skip(f"chromium unavailable: {exc}")
        try:
            n0 = pg.evaluate("document.querySelectorAll('#grid .card').length")
            assert pg.query_selector(".neardup-toggle") is not None
            pg.eval_on_selector(".neardup-toggle", "el => el.click()")
            pg.wait_for_function(
                "document.querySelector('.neardup-toggle')?.classList.contains('active')",
                timeout=30000)
            pg.wait_for_timeout(400)
            n1 = pg.evaluate("document.querySelectorAll('#grid .card').length")
            badges = pg.eval_on_selector_all(
                ".burst-stack-badge[data-neardup]",
                "els => els.map(e => e.textContent.trim())")
            assert n1 == n0 - 2                          # 3-photo group → fold 2
            assert any("3" in b for b in badges)        # hero shows ≈3
            pg.eval_on_selector(".burst-stack-badge[data-neardup]", "el => el.click()")
            pg.wait_for_timeout(500)
            assert pg.is_visible("#cmpModal")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(250)
            pg.eval_on_selector(".neardup-toggle", "el => el.click()")
            pg.wait_for_timeout(400)
            assert pg.evaluate("document.querySelectorAll('#grid .card').length") == n0
        finally:
            br.close()
