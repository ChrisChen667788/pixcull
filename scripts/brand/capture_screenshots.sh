#!/usr/bin/env bash
# v0.10 — capture fresh real-UI screenshots for README + ModelScope.
#
# Walks the live serve_demo through each major surface and saves PNG
# screenshots into docs/screenshots/.  Uses Playwright headless so the
# capture is deterministic (no manual window-resize, no human jitter).
#
# Prereqs (one-time):
#   pip install playwright
#   python -m playwright install chromium     # ~200 MB
#
# Usage:
#   bash scripts/brand/capture_screenshots.sh
#
# Output (overwrites existing):
#   docs/screenshots/
#     01-results-grid.png        — main grid with v0.9 brand gradient
#     02-cmdk-palette.png        — Cmd+K palette (v0.9-P0-4)
#     03-lightbox.png            — Inspector + sparkline + radial (v0.9-P1-4)
#     05-upload-page.png         — Hero with new logo + gradient
#     06-share-portfolio.png     — /share/<token> portfolio (v0.9-P0-5)
#     07-history.png             — /history timeline (v0.7-P2-4)
#     08-mobile-grid.png         — 390-wide viewport
#     09-tether.png              — /tether control panel
#     10-admin-perf.png          — /admin/perf data table (v0.9-P2-2)
#     11-buckets-empty.png       — empty-state SVG (v0.9-P2-3)
#     12-light-theme.png         — light theme V2 sand palette (v0.9-P2-1)
#     13-lightbox-ipad.png       — iPad-width lightbox + gestures (v0.9-P1-5)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python}"
PORT="${PIXCULL_PORT:-8771}"
mkdir -p docs/screenshots

if ! "$PYTHON" -c "import playwright" 2>/dev/null; then
    echo "[capture] playwright missing — install via:"
    echo "    pip install playwright"
    echo "    python -m playwright install chromium"
    exit 2
fi

# Boot serve_demo in background
echo "[capture] starting serve_demo on :$PORT"
PYTHONPATH="$REPO_ROOT" "$PYTHON" scripts/serve_demo.py \
    --host 127.0.0.1 --port "$PORT" > /tmp/serve_demo_capture.log 2>&1 &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null; true" EXIT
sleep 2

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if curl -sf "http://127.0.0.1:$PORT/" > /dev/null 2>&1; then
        echo "[capture] server ready"; break
    fi
    sleep 0.5
done

echo "[capture] seeding sample run..."
RUN=$(curl -sS -X POST -H "Content-Type: application/json" -d '{}' \
        "http://127.0.0.1:$PORT/sample_demo" \
      | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['run_id'])")
echo "[capture] sample run: $RUN"

# Issue a share token for the portfolio screenshot
SHARE_TOKEN=$(curl -sS -X POST -H "Content-Type: application/json" \
                -d '{"photographer":"ChrisChen Studio","client":"李慧 & 李翔","event":"川西风光 · 婚礼","event_date":"2026-06-15"}' \
                "http://127.0.0.1:$PORT/share/$RUN/issue" \
              | "$PYTHON" -c "import json,sys; d=json.load(sys.stdin); print(d.get('token',''))" 2>/dev/null \
              || echo "")
echo "[capture] share token: ${SHARE_TOKEN:-<none>}"

"$PYTHON" - "$PORT" "$RUN" "$SHARE_TOKEN" <<'PYEOF'
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

PORT, RUN, SHARE_TOKEN = sys.argv[1], sys.argv[2], sys.argv[3]
BASE = f"http://127.0.0.1:{PORT}"
OUT = Path("docs/screenshots")
OUT.mkdir(exist_ok=True)

# (path, viewport, post-load action(s), output filename, full_page)
TARGETS = [
    (f"/results/{RUN}", (1440, 900), None,                       "01-results-grid.png",   False),
    (f"/results/{RUN}", (1440, 900), [("press", "Meta+k")],       "02-cmdk-palette.png",   False),
    (f"/results/{RUN}", (1440, 900), [("click", ".card")],        "03-lightbox.png",       False),
    ("/",               (1440, 900), None,                        "05-upload-page.png",    False),
    ("/history",        (1440, 900), None,                        "07-history.png",        False),
    (f"/results/{RUN}", (390, 844),  None,                        "08-mobile-grid.png",    False),
    ("/tether",         (1440, 900), None,                        "09-tether.png",         False),
    # v0.9-P2-2 — admin perf data table
    ("/admin/perf",     (1440, 900), None,                        "10-admin-perf.png",     False),
    # v0.9-P2-3 — empty-state SVG (open buckets panel before any bucket)
    (f"/results/{RUN}", (1440, 900),
        [("evaluate", "document.getElementById('bucketsToggleBtn')?.click()"),
         ("wait", "400")],
        "11-buckets-empty.png", False),
    # v0.9-P2-1 — light theme V2 sand palette.  Set localStorage
    # pref BEFORE navigation so the on-load _renderTheme() picks
    # up "light" instead of auto-detecting from the OS pref.
    (f"/results/{RUN}", (1440, 900),
        [("storage_init", "pixcull_theme=light")],
        "12-light-theme.png", False),
    # v0.9-P1-5 — iPad-width lightbox
    (f"/results/{RUN}", (820, 1180),
        [("click", ".card")],
        "13-lightbox-ipad.png", False),
]

# Optional: share portfolio page (v0.9-P0-5)
if SHARE_TOKEN:
    TARGETS.append(
        (f"/share/{RUN}/{SHARE_TOKEN}", (1280, 1600),
         [("wait", "1800")],
         "06-share-portfolio.png", True),
    )

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for path, vp, actions, name, full_page in TARGETS:
            try:
                ctx = await browser.new_context(
                    viewport={"width": vp[0], "height": vp[1]},
                    device_scale_factor=2,
                    # Emulate prefers-reduced-motion so the v0.9-P0-2
                    # hero reveal collapses to its final frame
                    # immediately — needed for interactive screenshots
                    # (Cmd+K / card-click) to fire reliably.  Use the
                    # exception list TARGETS_KEEP_MOTION below for
                    # frames we WANT animated.
                    reduced_motion="reduce",
                )
                page = await ctx.new_page()
                # Apply any localStorage seed BEFORE the first nav so
                # the page's on-load code reads our value.  Used for
                # the light-theme screenshot (pixcull_theme=light).
                if actions:
                    seeds = [a for a in actions if a[0] == "storage_init"]
                    if seeds:
                        # localStorage isn't writable until SOME origin
                        # exists, so visit the homepage first, set the
                        # key, then navigate to the real target.
                        await page.goto(BASE + "/",
                                        wait_until="domcontentloaded",
                                        timeout=20_000)
                        for _, kv in seeds:
                            k, v = kv.split("=", 1)
                            await page.evaluate(
                                f"localStorage.setItem({k!r}, {v!r})"
                            )
                # `networkidle` hangs forever on /results/ because of
                # the v0.9-P1-2 presence + v0.8-P0-2 sync poll loops.
                # `domcontentloaded` returns when HTML is parsed but
                # before the JS that builds `.grid .card[data-fn]`
                # has run — the script template literals (class="card
                # ${cardCls}") give a fake `data-fn` count.  Wait for
                # the rendered cards to actually appear.
                await page.goto(BASE + path,
                                wait_until="domcontentloaded",
                                timeout=20_000)
                # For /results/ — wait for the JS-rendered cards to
                # exist before screenshotting; otherwise we capture
                # the un-hydrated template-string skeleton.
                if "/results/" in path:
                    try:
                        await page.wait_for_selector(
                            "#grid .card",
                            timeout=15_000,
                            state="attached",
                        )
                    except Exception:
                        pass  # fall through, capture whatever we have
                await page.wait_for_timeout(1500)  # let JS settle
                if actions:
                    for action in actions:
                        kind, arg = action
                        if kind == "click":
                            try:
                                await page.locator(arg).first.click(timeout=4_000)
                                await page.wait_for_timeout(800)
                            except Exception:
                                pass
                        elif kind == "press":
                            await page.keyboard.press(arg)
                            await page.wait_for_timeout(400)
                        elif kind == "evaluate":
                            await page.evaluate(arg)
                            await page.wait_for_timeout(200)
                        elif kind == "wait":
                            await page.wait_for_timeout(int(arg))
                await page.screenshot(path=str(OUT / name), full_page=full_page)
                print(f"[capture]   ✓ {OUT / name}  viewport={vp}")
                await ctx.close()
            except Exception as exc:
                print(f"[capture]   ✗ {name}: {type(exc).__name__}: {exc}")
        await browser.close()

asyncio.run(main())
PYEOF

echo "[capture] done"
ls -la docs/screenshots/
