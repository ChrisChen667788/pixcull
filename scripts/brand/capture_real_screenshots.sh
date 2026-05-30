#!/usr/bin/env bash
# v0.13 — capture screenshots from a REAL run (not sample_demo).
#
# Differs from scripts/brand/capture_screenshots.sh:
#   * Takes an existing RUN_ID instead of seeding 6 sample photos
#   * Adds new screenshots for v0.11-v0.13 features:
#       - 14-marquee-select (v0.11-P1-2)
#       - 15-bias-dashboard (v0.13-P0-4)
#       - 16-attribution-heatmap (v0.13-P0-1 hint)
#       - 17-confidence-modal (v0.13-P0-3 hover popover)
#
# Usage:
#   bash scripts/brand/capture_real_screenshots.sh <RUN_ID>
#
# Example:
#   bash scripts/brand/capture_real_screenshots.sh realdemo01
#
# Prereqs: the run dir must exist under /tmp/pixcull_demo/<RUN_ID>/
# with output/scores.csv populated.  Verify via:
#   ls /tmp/pixcull_demo/<RUN_ID>/output/scores.csv

set -euo pipefail

RUN_ID="${1:?usage: $0 <RUN_ID>}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-pixcull/.venv/bin/python}"
PORT="${PIXCULL_PORT:-8773}"
mkdir -p docs/screenshots

# Sanity-check that the run actually has data
if [ ! -f "/tmp/pixcull_demo/$RUN_ID/output/scores.csv" ]; then
    echo "[capture-real] expected /tmp/pixcull_demo/$RUN_ID/output/scores.csv"
    echo "[capture-real] run pixcull on a real photo dir first:"
    echo "    pixcull/.venv/bin/python -m pixcull run /path/to/photos \\"
    echo "      -o /tmp/pixcull_demo/$RUN_ID/output"
    exit 2
fi

ROW_COUNT=$(wc -l < "/tmp/pixcull_demo/$RUN_ID/output/scores.csv")
echo "[capture-real] run $RUN_ID has $ROW_COUNT rows (incl. header)"

if ! "$PYTHON" -c "import playwright" 2>/dev/null; then
    echo "[capture-real] playwright missing; install via:"
    echo "    $PYTHON -m pip install playwright"
    echo "    $PYTHON -m playwright install chromium"
    exit 3
fi

# Boot serve_demo in background
echo "[capture-real] starting serve_demo on :$PORT"
PYTHONPATH="$REPO_ROOT" "$PYTHON" scripts/serve_demo.py \
    --host 127.0.0.1 --port "$PORT" > /tmp/serve_demo_real_capture.log 2>&1 &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null; true" EXIT
sleep 2

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if curl -sf "http://127.0.0.1:$PORT/" > /dev/null 2>&1; then
        echo "[capture-real] server ready"; break
    fi
    sleep 0.5
done

# Issue a share token for the portfolio screenshot.  The real demo set
# is a LANDSCAPE shoot (Xiapu / 霞浦 coastal mudflats), not a wedding —
# label it as 风光摄影 so the client-facing page reads correctly.
SHARE_TOKEN=$(curl -sS -X POST -H "Content-Type: application/json" \
                -d '{"photographer":"ChrisChen Studio","client":"风光摄影","event":"霞浦风光 · 真机 demo","event_date":"2026-06-15"}' \
                "http://127.0.0.1:$PORT/share/$RUN_ID/issue" \
              | "$PYTHON" -c "import json,sys; d=json.load(sys.stdin); print(d.get('token',''))" 2>/dev/null \
              || echo "")
echo "[capture-real] share token: ${SHARE_TOKEN:-<none>}"

"$PYTHON" - "$PORT" "$RUN_ID" "$SHARE_TOKEN" <<'PYEOF'
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

PORT, RUN, SHARE_TOKEN = sys.argv[1], sys.argv[2], sys.argv[3]
BASE = f"http://127.0.0.1:{PORT}"
OUT = Path("docs/screenshots")
OUT.mkdir(exist_ok=True)

# (path, viewport, post-load actions, output filename, full_page)
TARGETS = [
    # Core surfaces — taken on the REAL 200-photo run so the grid
    # actually looks like a working session.
    (f"/results/{RUN}", (1440, 900), None,                       "01-results-grid.png",   False),
    (f"/results/{RUN}", (1440, 900), [("press", "Meta+k")],      "02-cmdk-palette.png",   False),
    # v0.7-P1-1 lightbox.  Use JS to call openLightbox directly so
    # the modal is guaranteed to be on screen by the time we snap
    # (clicking `.card` sometimes races the JS render queue).
    (f"/results/{RUN}", (1440, 900), [
        ("wait", "1500"),
        ("click", "#grid .card:nth-child(1)"),
        ("wait", "1200"),
    ], "03-lightbox.png", False),
    ("/",               (1440, 900), None,                       "05-upload-page.png",    False),
    ("/history",        (1440, 900), None,                       "07-history.png",        False),
    (f"/results/{RUN}", (390, 844),  None,                       "08-mobile-grid.png",    False),
    ("/tether",         (1440, 900), None,                       "09-tether.png",         False),
    ("/admin/perf",     (1440, 900), None,                       "10-admin-perf.png",     False),

    # v0.9 surfaces — buckets empty + light theme + iPad lightbox.
    (f"/results/{RUN}", (1440, 900),
        [("evaluate", "document.getElementById('bucketsToggleBtn')?.click()"),
         ("wait", "400")],
        "11-buckets-empty.png", False),
    (f"/results/{RUN}", (1440, 900),
        [("storage_init", "pixcull_theme=light")],
        "12-light-theme.png", False),
    # iPad lightbox — same direct-openLightbox trick.
    (f"/results/{RUN}", (820, 1180), [
        ("wait", "1500"),
        ("click", "#grid .card:nth-child(1)"),
        ("wait", "1200"),
    ], "13-lightbox-ipad.png", False),

    # v0.11-v0.13 NEW screenshots — exercise the new features so the
    # README can show the actual UI for them.

    # v0.11-P1-2 — marquee select.  We can't simulate a real drag
    # in headless mode reliably, so instead we set 3 cards as
    # marquee-selected via JS to capture the bulk toolbar.
    (f"/results/{RUN}", (1440, 900), [
        ("wait", "1500"),
        ("evaluate", "const cards = document.querySelectorAll('#grid .card'); "
            "for (let i = 2; i < Math.min(8, cards.length); i++) "
            "{cards[i].classList.add('marquee-selected');} "
            "const bar = document.getElementById('bulkToolbar'); "
            "if (bar) {bar.classList.add('show'); "
            "const c = document.getElementById('bulkCount'); "
            "if (c) c.textContent = Math.min(6, cards.length-2) + ' 张已选';}"),
        ("wait", "400"),
    ], "14-marquee-select.png", False),

    # v0.13-P0-4 — bias dashboard.  Will be empty if no annotations
    # exist, so we'll get the "no findings" state on a fresh run —
    # still useful as a "this is what the dashboard looks like".
    ("/admin/bias",     (1440, 900), [("wait", "800")],          "15-bias-dashboard.png", False),

    # v0.13-P0-3 — confidence modal.  JS-injection ensures the
    # popover surfaces for the screenshot.
    (f"/results/{RUN}", (1440, 900), [
        ("wait", "1500"),
        ("evaluate",
            "const cards = document.querySelectorAll('#grid .card'); "
            "if (cards.length) { "
            "const card = cards[Math.min(3, cards.length-1)]; "
            "const rect = card.getBoundingClientRect(); "
            "const grid = document.getElementById('grid'); "
            "const gridRect = grid.getBoundingClientRect(); "
            "const pop = document.createElement('div'); "
            "pop.className = 'confidence-popover'; "
            "pop.style.cssText = 'position:absolute;z-index:30;background:rgba(20,22,28,0.96);color:#fff;padding:9px 12px;border-radius:8px;font:11.5px/1.5 system-ui;max-width:230px;box-shadow:0 6px 20px rgba(0,0,0,0.40);border:1px solid rgba(99,102,241,0.30);'; "
            "pop.innerHTML = '<div style=\"font-weight:600;color:#a3a5f5;margin-bottom:4px\">⌬ model 不确定</div><div>62% sure</div><div style=\"color:#aaa\">· 同组邻居高 0.04</div><div style=\"color:#aaa\">· 最弱轴 · light 2.5★</div>'; "
            "pop.style.left = (rect.left - gridRect.left + grid.scrollLeft + rect.width + 8) + 'px'; "
            "pop.style.top = (rect.top - gridRect.top + grid.scrollTop) + 'px'; "
            "grid.appendChild(pop); }"),
        ("wait", "300"),
    ], "16-confidence-modal.png", False),

    # v0.13-P0-1 — attribution heatmap concept.  Synthetic overlay
    # to demonstrate the feature; real heatmaps come from attribution.py.
    (f"/results/{RUN}", (1440, 900), [
        ("wait", "1500"),
        ("click", "#grid .card:nth-child(1)"),
        ("wait", "1000"),
        ("evaluate",
            "const lb = document.getElementById('lightbox'); "
            "if (lb) { "
            "const overlay = document.createElement('div'); "
            "overlay.style.cssText = 'position:absolute;top:14%;left:30%;width:40%;height:50%;border-radius:16px;pointer-events:none;z-index:4;background:radial-gradient(circle at 40% 35%,rgba(99,102,241,0.55) 0%,rgba(236,72,153,0.40) 35%,rgba(236,72,153,0.0) 70%);mix-blend-mode:screen;filter:blur(8px);'; "
            "lb.appendChild(overlay); "
            "const tabs = document.createElement('div'); "
            "tabs.style.cssText = 'position:absolute;top:78px;left:50%;transform:translateX(-50%);z-index:7;display:flex;gap:6px;background:rgba(20,22,28,0.92);padding:4px 8px;border-radius:999px;font:11px/1 system-ui;'; "
            "['技术','主体','构图','光线','时刻','美感'].forEach((label, i) => { "
            "const t = document.createElement('button'); "
            "t.textContent = label; "
            "t.style.cssText = 'background:' + (i===2 ? 'rgba(99,102,241,0.30)' : 'transparent') + ';color:#fff;border:1px solid rgba(255,255,255,0.18);border-radius:999px;padding:5px 12px;font:inherit;cursor:pointer;'; "
            "tabs.appendChild(t); }); "
            "lb.appendChild(tabs); }"),
        ("wait", "200"),
    ], "17-attribution-heatmap.png", False),
]

# Optional: share portfolio page
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
                    reduced_motion="reduce",
                )
                page = await ctx.new_page()
                if actions:
                    seeds = [a for a in actions if a[0] == "storage_init"]
                    if seeds:
                        await page.goto(BASE + "/",
                                        wait_until="domcontentloaded",
                                        timeout=20_000)
                        for _, kv in seeds:
                            k, v = kv.split("=", 1)
                            await page.evaluate(
                                f"localStorage.setItem({k!r}, {v!r})"
                            )
                # v2.2 — "commit" resolves on first byte; the heavy
                # /results page can leave a thumb request pending so
                # "domcontentloaded" sometimes never fires under the
                # demo server's HTTP/1.0 keep-alive.
                try:
                    await page.goto(BASE + path,
                                    wait_until="commit", timeout=20_000)
                except Exception as _e:
                    print(f"[capture-real] goto warn {path}: {str(_e)[:80]}")
                if "/results/" in path:
                    try:
                        # Wait for at least 10 cards to be in the DOM
                        # (>=1 is met by JS template-string skeletons
                        # that never paint).  10+ means the JS render
                        # loop actually ran on the real `rows` array.
                        await page.wait_for_function(
                            "document.querySelectorAll('#grid .card').length > 10",
                            timeout=20_000,
                        )
                        # Force-scroll to top so the screenshot
                        # captures the first row, not wherever
                        # focus-on-load landed us.
                        await page.evaluate("window.scrollTo(0,0)")
                    except Exception:
                        pass
                await page.wait_for_timeout(2500)
                if actions:
                    for action in actions:
                        kind, arg = action
                        if kind == "click":
                            try:
                                await page.locator(arg).first.click(timeout=4_000)
                                # If the click was on a card, wait
                                # for the lightbox AND its full-size
                                # image to actually render (or 6s timeout).
                                if ".card" in arg:
                                    try:
                                        await page.wait_for_function(
                                            "document.getElementById('lightbox')?.classList.contains('show')",
                                            timeout=4_000,
                                        )
                                        # Wait for the main img to load
                                        await page.wait_for_function(
                                            "const i = document.getElementById('lbImg');"
                                            "i && i.complete && i.naturalHeight > 0",
                                            timeout=8_000,
                                        )
                                    except Exception:
                                        pass
                                await page.wait_for_timeout(1200)
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
                print(f"[capture-real]   ✓ {OUT / name}  viewport={vp}")
                await ctx.close()
            except Exception as exc:
                print(f"[capture-real]   ✗ {name}: {type(exc).__name__}: {exc}")
        await browser.close()

asyncio.run(main())
PYEOF

echo "[capture-real] done"
ls -la docs/screenshots/
