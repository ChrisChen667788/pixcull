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
import csv
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "pixcull" / "report" / "templates" / "src" / "results.css"
MOD = (REPO / "pixcull" / "report" / "templates" / "src" / "modules"
       / "33-client-present.js")
BUILT = REPO / "pixcull" / "report" / "templates" / "results.html"
# v3.47 — the repo venv exists on a maintainer's laptop and nowhere
# else, so on CI this pointed at a file that is not there and the server
# never started. `sys.executable` is the interpreter already running the
# suite, which is the right one anyway.
_VENV_PY = REPO / "pixcull" / ".venv" / "bin" / "python"
PY = _VENV_PY if _VENV_PY.is_file() else Path(sys.executable)

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
    # v3.47 — the 5,069-row perf run is the realistic subject and it
    # lives on one laptop, so these four tests skipped everywhere else,
    # including CI. That is the fourth time this repository has shipped
    # a test that reports green by not running (ffmpeg v2.45, exiftool
    # v3.41, the whole browser lane v3.42). The committed 24-row fixture
    # is the floor; the real run still wins when it is present.
    demo = os.environ.get("PIXCULL_TEST_DEMO_ROOT") or "/tmp/pixcull_perf"
    run = os.environ.get("PIXCULL_TEST_RUN") or "perf5069"
    if not (Path(demo) / run / "output" / "scores.csv").is_file():
        demo = str(REPO / "tests" / "fixtures")
        run = "present_run"
    if not (Path(demo) / run / "output" / "scores.csv").is_file():
        pytest.skip(f"no run at {demo}/{run} and no committed fixture — "
                    "run scripts/make_present_fixture.py")
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


# ---------------------------------------------------------------------------
# v3.47 — keeping the four live tests above from going back to skipping.
# ---------------------------------------------------------------------------

def test_the_fixture_exists_so_the_live_tests_cannot_skip():
    """The four tests above assert that no verdict, score or star is
    readable in client-present mode. That is the one screen a
    photographer turns toward someone who is not paying to see the
    machine's opinion of their work, and it had no CI coverage at all
    because the run it needed lived on one laptop."""
    csv_path = (REPO / "tests" / "fixtures" / "present_run"
                / "output" / "scores.csv")
    assert csv_path.is_file(), (
        "the committed fixture is gone — run scripts/make_present_fixture.py")
    rows = list(csv.DictReader(csv_path.open()))
    # The live tests need >10 cards and >50 visible judgement strings.
    assert len(rows) > 10, f"only {len(rows)} rows; the grid tests need >10"
    assert len({r["decision"] for r in rows}) == 3, \
        "the fixture must carry keep, maybe and cull — one of each colour"


def test_the_fixture_matches_its_generator():
    """A hand-edited fixture drifts from the script that explains it,
    and then nobody can tell which one is right."""
    import subprocess
    import sys as _sys
    target = REPO / "tests" / "fixtures" / "present_run" / "output" / "scores.csv"
    before = target.read_bytes()
    try:
        subprocess.run([_sys.executable,
                        str(REPO / "scripts" / "make_present_fixture.py")],
                       check=True, capture_output=True)
        after = target.read_bytes()
    finally:
        target.write_bytes(before)
    assert before == after, (
        "tests/fixtures/present_run does not match "
        "scripts/make_present_fixture.py — regenerate it")


def test_the_interpreter_the_server_runs_under_actually_exists():
    """It used to be a hard-coded path into the maintainer's venv. On any
    other machine the server never started, and the fixture skipped with
    'server did not come up' — a sentence that reads like a flake."""
    assert Path(PY).is_file(), PY


def test_the_fixture_is_actually_tracked_by_git():
    """v3.51 — existing on disk is not the same as being in the commit.

    `.gitignore` carries a bare `output/`, which matches a directory of
    that name at any depth, and the exception under it named `smoke_run`
    specifically. So the fixture v3.47 added lived happily on one machine,
    passed every local run, and was never committed — CI failed on a file
    that had never existed there. A per-name exception to a glob is a trap
    with a delay on it; the rule is a glob now, and this is the check that
    would have caught it before the push.
    """
    import subprocess
    out = subprocess.run(["git", "ls-files", "tests/fixtures/present_run"],
                         cwd=REPO, capture_output=True, text=True).stdout
    tracked = [l for l in out.splitlines() if l.strip()]
    assert any(l.endswith("scores.csv") for l in tracked), (
        "the present-mode fixture is not tracked by git — check .gitignore; "
        f"git ls-files returned {tracked}")


def test_the_indicator_can_actually_be_hidden():
    """v3.64 — `hidden` has to win, and an ID selector beats it.

    `#clientPresentIndicator { display: flex }` outranks the browser's
    own `[hidden] { display: none }`, so `ind.hidden = true` in
    33-client-present.js changed nothing: the bar sat on screen for
    every user, permanently, reading 客户在场模式 · 判决与评分已隐藏
    while the verdicts and the scores were plainly visible behind it.

    A status bar that is always there is a status bar nobody reads,
    which is why it survived. It turned up in a screenshot — in all
    twelve of them.
    """
    css = (REPO / "pixcull" / "report" / "templates" / "src"
           / "results.css").read_text(encoding="utf-8")
    assert "#clientPresentIndicator[hidden]" in css, (
        "nothing overrides the display rule, so el.hidden is inert")

    built = BUILT.read_text(encoding="utf-8")
    assert "#clientPresentIndicator[hidden]" in built, (
        "the fix is in the source but not in the built results.html — "
        "run scripts/build_results_html.py")


def test_the_indicator_starts_hidden_on_a_fresh_page(page):
    """The live half: load a run with the mode off and look."""
    state = page.evaluate("""() => {
        const el = document.getElementById('clientPresentIndicator');
        if (!el) return {missing: true};
        return {hidden: el.hidden,
                display: getComputedStyle(el).display,
                mode: document.documentElement.classList.contains('pc-client')};
    }""")
    assert not state.get("missing"), "the indicator element is gone"
    assert state["mode"] is False, "the fixture started in client-present mode"
    assert state["display"] == "none", (
        f"client-present mode is off and the bar is still rendered: {state}")
