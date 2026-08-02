"""v2.45.1 — capture the transcript / edit-by-text panel for the README.

Kept as a script rather than done by hand because the panel's screenshot
has to be *re-takeable*: it shows live state (a struck line, a
word-level cut, the kept-duration readout), and a screenshot of state
that nobody can reproduce is a screenshot nobody can refresh when the
UI moves.

The clip is synthetic throughout — an ffmpeg test pattern with macOS TTS
speaking four on-set directions. No client footage, no real voices, no
PII. That is a hard requirement for anything that ships in the README.

Usage::

    pixcull video  <clip.mp4> -o /tmp/pixcull_demo/txdemo --interval-s 0.6
    pixcull transcribe <clip.mp4> -o /tmp/pixcull_demo/txdemo --no-shots -l zh
    pixcull serve --port 8770 --no-open &
    python scripts/brand/capture_transcript_edit.py --run txdemo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DEST = REPO / "docs" / "screenshots" / "24-transcript-edit.png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="txdemo")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--out", type=Path, default=DEST)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed: pip install playwright && "
              "playwright install chromium", file=sys.stderr)
        return 2

    url = f"http://127.0.0.1:{args.port}/video/{args.run}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width,
                                          "height": args.height},
                                device_scale_factor=2)
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".tx-line", timeout=30_000)

        # Drive the panel into the state worth showing: one line struck
        # out whole, one line cut at word level, and the playhead parked
        # on a line so the active highlight is visible.
        page.evaluate("""async () => {
          const w = ms => new Promise(r => setTimeout(r, ms));
          // word-level cut inside line 0, chosen to avoid straddling a
          // comma — char_spans index non-punctuation characters, so a
          // selection across one deletes fewer characters than it looks.
          const line = document.querySelector('.tx-line[data-i="0"]');
          const tn = line.lastElementChild.firstChild;
          const txt = tn.textContent;
          const at = txt.indexOf('机位');
          if (at >= 0) {
            const r = document.createRange();
            r.setStart(tn, at); r.setEnd(tn, at + 2);
            const sel = window.getSelection();
            sel.removeAllRanges(); sel.addRange(r);
            document.dispatchEvent(new Event('selectionchange'));
            await w(400);
            const btn = document.querySelector('.tx-sel');
            if (btn) btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
            await w(900);
            sel.removeAllRanges();
          }
          const cut = document.querySelector('.tx-cut[data-cut="2"]');
          if (cut) { cut.click(); await w(900); }
          const jump = document.querySelector('.tx-line[data-i="3"]');
          if (jump) { jump.click(); await w(900); }
        }""")
        page.wait_for_timeout(1200)

        stat = page.text_content("#txStat") or ""
        if "保留" not in stat:
            print(f"panel never showed a kept-duration readout: {stat!r}",
                  file=sys.stderr)
            browser.close()
            return 1

        args.out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.out))
        browser.close()

    kb = args.out.stat().st_size / 1024
    print(f"✓ {args.out.relative_to(REPO)}  {kb:.0f} KB")
    print(f"  panel state: {stat.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
