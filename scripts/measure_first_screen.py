#!/usr/bin/env python3
"""Measure how long the review page takes to become usable.

    pixcull/.venv/bin/python scripts/measure_first_screen.py <run_id> [--cold N] [--warm N]

THE METRIC: **first-screen ready** — the moment every image intersecting
the initial 1440x900 viewport has arrived. Not LCP: on a lazy-loading
gallery LCP keeps moving as more images paint below the fold, so it
measures when the last big image landed rather than when the
photographer can start working. Two consecutive LCP readings on the same
page differed by 900 ms while the page behaved identically.

COLD MEANS COLD. Each cold sample restarts the server. Anything else
measures the in-process results cache, which is how "1.8 seconds" was
believed for several versions while the first open actually took 3.4.

THE PORT IS READ BACK, NEVER ASSUMED. `_pick_port` silently falls back
when the requested port cannot be bound, and a SIGKILLed predecessor
leaves the socket in TIME_WAIT long enough for that to happen. Polling
the port we asked for then reports "server did not come up" about a
server that came up perfectly well somewhere else.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / "pixcull" / ".venv" / "bin" / "python"

PROBE = """
window.__lt = 0; window.__ltn = 0;
new PerformanceObserver(l => { for (const e of l.getEntries()) {
  window.__lt += e.duration; window.__ltn++; } })
  .observe({type:'longtask', buffered:true});
"""

READ = """() => {
  const r = x => Math.round(x||0);
  const nav = performance.getEntriesByType('navigation')[0]||{};
  const H = window.innerHeight;
  const inView = [...document.images].filter(i => {
    const b = i.getBoundingClientRect();
    return b.bottom > 0 && b.top < H && b.width > 0;
  });
  const byUrl = new Map();
  for (const e of performance.getEntriesByType('resource')) byUrl.set(e.name, e);
  let ready = 0, painted = 0;
  for (const i of inView) {
    if (i.complete && i.naturalWidth > 0) painted++;
    const e = byUrl.get(i.currentSrc || i.src);
    if (e) ready = Math.max(ready, Math.round(e.responseEnd));
  }
  return {
    ttfb: r(nav.responseStart - nav.requestStart),
    fcp: r((performance.getEntriesByType('paint')
            .find(p => p.name === 'first-contentful-paint') || {}).startTime),
    dcl: r(nav.domContentLoadedEventEnd),
    load: r(nav.loadEventEnd),
    firstScreenReady: ready,
    inViewport: inView.length, painted,
    longtaskMs: r(window.__lt), longtasks: window.__ltn,
    reqs: performance.getEntriesByType('resource').length,
    gridChildren: (document.getElementById('grid') || {children: []}).children.length,
  };
}"""


def boot(port: int, demo_root: str | None) -> tuple[subprocess.Popen, int]:
    env = dict(os.environ)
    if demo_root:
        env["PIXCULL_DEMO_ROOT"] = demo_root
    log_path = f"/tmp/pixcull_measure_{port}.log"
    log = open(log_path, "w")
    p = subprocess.Popen(
        [str(PY), "-u", "-m", "pixcull.report.serve_app", "--no-open",
         "--port", str(port), "--vlm-mode", "off"],
        cwd=REPO, stdout=log, stderr=subprocess.STDOUT, env=env,
        preexec_fn=os.setsid)
    actual = None
    for _ in range(240):
        time.sleep(0.5)
        if p.poll() is not None:
            log.flush()
            raise SystemExit(f"server exited rc={p.returncode}: "
                             f"{open(log_path).read()[-800:]}")
        if actual is None:
            m = re.search(r"serving on\s+[\d.]+:(\d+)", open(log_path).read())
            if m:
                actual = int(m.group(1))
        if actual is not None:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{actual}/", timeout=3)
                return p, actual
            except Exception:
                pass
    log.flush()
    raise SystemExit(f"server did not come up: {open(log_path).read()[-800:]}")


def kill(p: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        pass
    time.sleep(1.5)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--cold", type=int, default=3)
    ap.add_argument("--warm", type=int, default=5)
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--demo-root", default=os.environ.get("PIXCULL_DEMO_ROOT"))
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright

    def visit(br, port):
        pg = br.new_context(viewport={"width": 1440, "height": 900}).new_page()
        pg.add_init_script(PROBE)
        pg.goto(f"http://127.0.0.1:{port}/results/{a.run_id}",
                wait_until="load", timeout=900_000)
        pg.wait_for_timeout(3000)
        m = pg.evaluate(READ)
        pg.context.close()
        return m

    cold, warm = [], []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for _ in range(a.cold):
            srv, port = boot(a.port, a.demo_root)
            try:
                cold.append(visit(br, port))
            finally:
                kill(srv)
        if a.warm:
            srv, port = boot(a.port, a.demo_root)
            try:
                visit(br, port)                 # discarded: warms the cache
                for _ in range(a.warm):
                    warm.append(visit(br, port))
            finally:
                kill(srv)
        br.close()

    def agg(rows):
        if not rows:
            return {}
        return {k: {"med": round(statistics.median(r[k] for r in rows)),
                    "min": min(r[k] for r in rows),
                    "max": max(r[k] for r in rows)} for k in rows[0]}

    print(json.dumps({"run": a.run_id, "cold_n": a.cold, "warm_n": a.warm,
                      "cold": agg(cold), "warm": agg(warm)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
