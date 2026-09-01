"""v2.97 — 客户在场模式: hide the verdicts while a client is beside you.

Measured before this existed, on one screen of a 5,069-photo run:

    539 pieces of judgement text
    every card:  "保留"  and  "综合分 0.95"
    stats bar:   "保留 4152 · 待定 244 · 剔除 673"

A client sitting next to the photographer reads the machine's verdict on
their own wedding photographs, with a number on each one, and a count of
how many were marked for deletion along the top. It turns choosing
pictures into defending them.

THE GUARD IS THE PROBE, NOT THE CSS. A badge added next year would leak
straight through a stylesheet rule. `test_no_judgement_survives` walks
the live DOM with the mode on and requires the count to be zero. If it
fails, something new is showing a verdict to a client — that is the
signal, and no CSS change makes it pass by accident.
"""
import ast
import os
import re
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "pixcull" / "report" / "templates" / "src" / "results.css"
MOD = (REPO / "pixcull" / "report" / "templates" / "src" / "modules"
       / "33-client-present.js")
BUILT = REPO / "pixcull" / "report" / "templates" / "results.html"
PY = REPO / "pixcull" / ".venv" / "bin" / "python"

# Anything a client could read as a verdict on their own photographs.
JUDGEMENT = r"剔除|保留|拿不准|建议留|综合分|★|☆|\d\.\d\d"

# The one allowed survivor: a toolbar control, not a statement about any
# photograph. Named explicitly so a second exception has to be argued for.
ALLOWED = {"export-btn"}


# ------------------------------------------------------------ static


def test_the_module_is_wired_into_the_build():
    """results.html is a build artifact; editing sources without
    rebuilding ships a page with no client mode in it."""
    built = BUILT.read_text(encoding="utf-8")
    assert "clientPresentBtn" in built
    assert "clientPresentIndicator" in built
    assert "pc-client" in built


def test_the_burst_peak_badge_is_not_a_verdict_badge():
    """It borrowed `.badge.keep` and would vanish with the verdicts.
    "this is the best frame of the burst" is exactly what a photographer
    wants to say to a client."""
    js = (REPO / "pixcull" / "report" / "templates" / "src"
          / "results.js").read_text(encoding="utf-8")
    assert 'class="badge keep peak"' in js
    css = CSS.read_text(encoding="utf-8")
    assert ".badge.keep:not(.peak)" in css


def test_the_mode_persists_across_a_reload():
    src = MOD.read_text(encoding="utf-8")
    assert "localStorage" in src
    assert "pixcull_client_present" in src


def test_the_shortcut_is_not_a_bare_letter():
    """The cull loop binds single keys. A stray keystroke in front of a
    client must not put the verdicts back on screen."""
    src = MOD.read_text(encoding="utf-8")
    i = src.find("addEventListener(\"keydown\"")
    assert i > 0
    block = src[i:i + 500]
    assert "shiftKey" in block


# ------------------------------------------------------- the live probe


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def served():
    pytest.importorskip("playwright.sync_api")
    demo = os.environ.get("PIXCULL_TEST_DEMO_ROOT") or "/tmp/pixcull_perf"
    run = os.environ.get("PIXCULL_TEST_RUN") or "perf5069"
    if not (Path(demo) / run / "output" / "scores.csv").is_file():
        pytest.skip(f"no run at {demo}/{run} — see docs/FIRST-SCREEN-MEASUREMENT.md")
    env = dict(os.environ, PIXCULL_DEMO_ROOT=demo)
    log = Path(f"/tmp/pixcull_cp_test_{os.getpid()}.log")
    proc = subprocess.Popen(
        [str(PY), "-u", "-m", "pixcull.report.serve_app", "--no-open",
         "--port", str(_free_port()), "--vlm-mode", "off"],
        cwd=REPO, stdout=log.open("w"), stderr=subprocess.STDOUT,
        env=env, preexec_fn=os.setsid)
    port = None
    for _ in range(120):
        time.sleep(0.5)
        if proc.poll() is not None:
            pytest.skip("server exited")
        m = re.search(r"serving on\s+[\d.]+:(\d+)", log.read_text(encoding="utf-8"))
        if m:
            port = int(m.group(1))
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
                break
            except Exception:  # noqa: BLE001
                pass
    else:
        pytest.skip("server did not come up")
    yield f"http://127.0.0.1:{port}/results/{run}"
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        pass


_PROBE = r"""(pattern) => {
  const pat = new RegExp(pattern);
  const shown = (el) => {
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0')
      return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const hits = [];
  const walk = (el) => {
    if (el.nodeType === 1 && !shown(el)) return;
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && pat.test(n.textContent)) {
        const p = n.parentElement;
        if (p && shown(p))
          hits.push({cls: (p.className || '').toString(),
                     txt: n.textContent.trim().slice(0, 24)});
      } else if (n.nodeType === 1) walk(n);
    }
  };
  walk(document.body);
  return hits;
}"""


def _hits(page):
    raw = page.evaluate(_PROBE, JUDGEMENT)
    return [h for h in raw
            if not any(a in str(h["cls"]).split() for a in ALLOWED)]


@pytest.fixture(scope="module")
def page(served):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
        pg.goto(served, wait_until="load", timeout=900_000)
        pg.wait_for_timeout(4000)
        yield pg
        b.close()


def test_the_default_really_does_show_verdicts(page):
    """If this ever reads zero, the probe has stopped working and the
    test below is passing on nothing."""
    assert len(_hits(page)) > 50


def test_no_judgement_survives(page):
    page.keyboard.press("Shift+C")
    page.wait_for_timeout(1000)
    try:
        leaks = _hits(page)
        assert leaks == [], (
            "a client can read these off the screen: "
            + "; ".join(f"{h['cls'] or '(no class)'}={h['txt']!r}"
                        for h in leaks[:8]))
    finally:
        page.keyboard.press("Shift+C")
        page.wait_for_timeout(500)


def test_the_photographer_keeps_what_they_need(page):
    """Judgement goes; information stays. A mode that hides the filename
    is not usable for the person driving."""
    page.keyboard.press("Shift+C")
    page.wait_for_timeout(1000)
    try:
        card = page.evaluate(
            "() => (document.querySelector('.card')||{}).innerText || ''")
        assert re.search(r"\.(jpg|jpeg|png)", card, re.I), \
            f"the filename is gone from the card: {card!r}"
        assert page.evaluate(
            "() => document.querySelectorAll('.card').length") > 10
    finally:
        page.keyboard.press("Shift+C")
        page.wait_for_timeout(500)


def test_the_indicator_survives_a_reload(page):
    """The mode persisting without the indicator is the worse half: the
    photographer loses the only sign their numbers are hidden on purpose.
    It failed exactly this way on the first attempt — the script runs
    before the indicator element exists in the document."""
    page.keyboard.press("Shift+C")
    page.wait_for_timeout(800)
    page.reload(wait_until="load")
    page.wait_for_timeout(3000)
    try:
        state = page.evaluate("""() => ({
            mode: document.documentElement.classList.contains('pc-client'),
            indicator: !document.getElementById('clientPresentIndicator').hidden,
        })""")
        assert state["mode"] is True
        assert state["indicator"] is True
    finally:
        page.keyboard.press("Shift+C")
        page.wait_for_timeout(500)
