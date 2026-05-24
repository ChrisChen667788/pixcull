#!/usr/bin/env bash
# v0.9-MARKETING — capture fresh real-UI screenshots for README + ModelScope.
#
# Walks the live serve_demo through each major surface and saves PNG
# screenshots into docs/screenshots/.  Uses Playwright headless so the
# capture is deterministic (no manual window-resize, no human jitter).
#
# Prereqs (one-time):
#   pip install playwright
#   playwright install chromium     # ~200 MB download
#
# Usage:
#   bash scripts/brand/capture_screenshots.sh
#
# Output (overwrites existing):
#   docs/screenshots/
#     01-results-grid.png        — main grid with v0.9 brand gradient
#     02-cmdk-palette.png        — Cmd+K command palette (v0.9-P0-4)
#     03-lightbox.png            — Inspector pane + RGB readout
#     04-ab-compare.png          — A/B compare with sync zoom
#     05-upload-page.png         — Hero with new logo + gradient
#     06-share-url-modal.png     — Share link modal with QR (v0.7-P1-4 + v0.8-P1-3)
#     07-history.png             — /history timeline (v0.7-P2-4)
#     08-mobile-grid.png         — 390-wide viewport, bottom sheet inspector
#     09-tether.png              — /tether control panel
#     10-cull-reason-pie.png     — pie chart of cull reasons

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python}"
PORT="${PIXCULL_PORT:-8771}"
mkdir -p docs/screenshots

# Make sure Playwright is here
if ! "$PYTHON" -c "import playwright" 2>/dev/null; then
    echo "[capture] playwright missing — install via:"
    echo "    pip install playwright && playwright install chromium"
    exit 2
fi

# Boot serve_demo in background
echo "[capture] starting serve_demo on :$PORT"
PYTHONPATH="$REPO_ROOT" "$PYTHON" scripts/serve_demo.py \
    --host 127.0.0.1 --port "$PORT" > /tmp/serve_demo_capture.log 2>&1 &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null; true" EXIT
sleep 2

# Pump in sample data so the results page is non-empty
echo "[capture] seeding sample run..."
RUN=$(curl -sS -X POST -H "Content-Type: application/json" -d '{}' \
        "http://127.0.0.1:$PORT/sample_demo" \
      | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['run_id'])")
echo "[capture] sample run: $RUN"

# Run the Playwright capture script (Python inline so dev never has to
# learn the JS API).
"$PYTHON" - "$PORT" "$RUN" <<'PYEOF'
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

PORT, RUN = sys.argv[1], sys.argv[2]
BASE = f"http://127.0.0.1:{PORT}"
OUT = Path("docs/screenshots")

# (path, viewport, action, file)
TARGETS = [
    (f"/results/{RUN}",  (1440, 900),  None,                   "01-results-grid.png"),
    (f"/results/{RUN}",  (1440, 900),  ["press", "Meta+k"],    "02-cmdk-palette.png"),
    (f"/results/{RUN}",  (1440, 900),  ["click", ".card"],     "03-lightbox.png"),
    # 04-ab-compare requires pinning two photos via JS — covered by existing
    (f"/",               (1440, 900),  None,                   "05-upload-page.png"),
    (f"/history",        (1440, 900),  None,                   "07-history.png"),
    (f"/results/{RUN}",  (390, 844),   None,                   "08-mobile-grid.png"),
    (f"/tether",         (1440, 900),  None,                   "09-tether.png"),
]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for path, vp, action, name in TARGETS:
            ctx = await browser.new_context(
                viewport={"width": vp[0], "height": vp[1]},
                device_scale_factor=2,
            )
            page = await ctx.new_page()
            await page.goto(BASE + path, wait_until="networkidle")
            await page.wait_for_timeout(2500)  # let hero reveal finish
            if action:
                if action[0] == "click":
                    await page.locator(action[1]).first.click()
                    await page.wait_for_timeout(800)
                elif action[0] == "press":
                    await page.keyboard.press(action[1])
                    await page.wait_for_timeout(400)
            await page.screenshot(path=OUT / name, full_page=False)
            print(f"[capture] {OUT / name} {vp}")
            await ctx.close()
        await browser.close()

asyncio.run(main())
PYEOF

echo "[capture] done"
ls -la docs/screenshots/
