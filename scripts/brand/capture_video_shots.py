"""v3.87 — capture the three video screenshots: 18, 19 and 23.

They are one script because they are one setup: all three need a video
run on disk, and `pixcull video` runs on a clip that cannot live in the
repo (41 MB, and it is the owner's own footage).  That is the same
reason `capture_transcript_edit.py` is separate from
`capture_screenshots.sh`, which only ever needs `POST /sample_demo`.

Each shot verifies the thing its README caption claims before it writes
a file.  v3.86's first attempt at `20-scenes-navigator` photographed the
photo grid because the element it wanted ships `hidden` — a screenshot
of the wrong surface under the right caption is worse than no
screenshot, because nothing downstream can tell.

  18-video-review   the reel candidate list, the score_temporal curve
                    and the J/K/L transport.  Verified: candidates
                    rendered, the curve has a path, the HUD reads a
                    temporal value rather than an em dash, and the
                    playhead is parked inside a candidate so the
                    ★ reel 候选 badge is in frame.
  19-video-grade    a LUT applied to the main frame AND to the
                    candidate thumbnails.  Verified by DECODING both
                    frames and comparing mean channel values — a URL
                    carrying `grade=` proves the request was made, not
                    that anything came back different.
  23-video-timeline photographs and a video segment on one axis.
                    Verified: at least one photo strip, at least one
                    video card, and more than one time row — one row is
                    a list, not a timeline.

Prereqs::

    pixcull video  <clip.mp4> -o /tmp/pixcull_demo/<run> --interval-s 0.6
    pixcull serve  --port 8771 --no-open &
    python scripts/brand/capture_video_shots.py --video-run <run>

The clip must be owner-authorised and screened by eye at full size;
`face_count == 0` is not evidence of no face.  See CLAUDE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SHOTS = REPO / "docs" / "screenshots"
SCREENED = REPO / "docs" / "demo-clip-frames.tsv"

#: Kept in step with `capture_screenshots.sh`, and asserted by
#: `tests/test_image_weight.py` over every committed PNG — the first cut
#: of this script wrote 2880 px files and that gate is what said so.
SHOT_MAX_WIDTH = 1660


def save_shot(page, out: Path, *, full_page: bool = False) -> None:
    """Screenshot, then cap the width the way every other capture does."""
    from PIL import Image
    page.screenshot(path=str(out), full_page=full_page)
    im = Image.open(out)
    w, h = im.size
    if w > SHOT_MAX_WIDTH:
        im = im.resize((SHOT_MAX_WIDTH, round(h * SHOT_MAX_WIDTH / w)),
                       Image.LANCZOS)
    im.save(out, "PNG", optimize=True)


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


# --- the pixel check shot 19 turns on -------------------------------------
#
# Decode both frames in the page and compare them PER PIXEL. A `grade=`
# query string only says the browser asked for a graded frame, and the
# first version of this check compared the two frames' mean channel
# values, which is the wrong statistic twice over: a grade that moves
# colour around without moving the average reads as "changed nothing",
# and a snow-filled frame damps every real grade toward zero. On this
# clip B&W — which removes colour entirely — shifts the mean by 16/255
# and Kodak Vision3 by 9, a ratio that says nothing about how different
# the two pictures look. Mean and max absolute per-pixel difference do.
_DIFF_JS = """
async ([a, b]) => {
  const load = async (url) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    await new Promise((ok, no) => { img.onload = ok; img.onerror = no; img.src = url; });
    const c = document.createElement('canvas');
    c.width = 160; c.height = Math.max(1, Math.round(160 * img.height / img.width));
    const x = c.getContext('2d');
    x.drawImage(img, 0, 0, c.width, c.height);
    return x.getImageData(0, 0, c.width, c.height).data;
  };
  const [p, q] = [await load(a), await load(b)];
  if (p.length !== q.length) return [255, 255];
  let sum = 0, max = 0, n = 0;
  for (let i = 0; i < p.length; i += 4) {
    for (let k = 0; k < 3; k++) {
      const d = Math.abs(p[i+k] - q[i+k]);
      sum += d; if (d > max) max = d; n++;
    }
  }
  return [sum / n, max];
}
"""



# --- the gate that decides what may be photographed -----------------------
#
# v3.87. The demo clip is footage of a real person, and the automatic
# face check in `make_demo_clip.py` cannot certify it — on the v3.77
# clip it returned two boxes on the subject's coat, none on her face,
# and reported full containment while the face was legible and
# unfrosted. So the gate is not "did a detector clear the clip", it is
# "has a person looked at this exact image": every frame this script
# puts on screen must be listed, by content hash, in
# docs/demo-clip-frames.tsv.
#
# Hash, not frame id: a re-cut clip renumbers its frames, so
# `frame_000019` from one cut and the next are different pictures under
# the same name. The hash moves with the picture.


def _screened() -> dict[str, str]:
    """sha256[:16] -> note, for every frame a person has cleared."""
    out: dict[str, str] = {}
    if not SCREENED.is_file():
        return out
    for line in SCREENED.read_text("utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            out[parts[0].strip()] = parts[-1].strip()
    return out


def _frame_sha(run_dir: Path, frame_id: str) -> str | None:
    for jpg in sorted(run_dir.glob(f"video_frames/*/{frame_id}.jpg")):
        return hashlib.sha256(jpg.read_bytes()).hexdigest()[:16]
    return None


_VISIBLE_JS = """() => {
  const ids = [];
  const hud = (document.getElementById('hudF') || {}).textContent || '';
  const m = hud.match(/frame_\\d+/);
  if (m) ids.push(m[0]);
  const h = window.innerHeight, w = window.innerWidth;
  document.querySelectorAll('.cand').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.bottom > 0 && r.top < h && r.right > 0 && r.left < w
        && el.querySelector('img.thumb') && el.dataset.frame) {
      ids.push(el.dataset.frame);
    }
  });
  return [...new Set(ids)];
}"""


def gate_visible_frames(page, run_dir: Path, shot: str) -> list[str]:
    """Refuse to write `shot` unless every frame in view has been screened.

    Returns the frame ids that are on screen, so the caller can say what
    the picture actually contains.
    """
    ids = page.evaluate(_VISIBLE_JS)
    if not ids:
        raise AssertionError(f"{shot}: could not tell which frames are on "
                             f"screen — refusing rather than guessing")
    ok = _screened()
    unscreened = []
    for fid in ids:
        sha = _frame_sha(run_dir, fid)
        if sha is None:
            unscreened.append(f"{fid} (no file under {run_dir})")
        elif sha not in ok:
            unscreened.append(f"{fid} sha {sha}")
    if unscreened:
        raise AssertionError(
            f"{shot}: {len(unscreened)} frame(s) on screen are not in "
            f"{SCREENED.relative_to(REPO)} — look at them at full size and "
            f"add them, or move the playhead: " + "; ".join(unscreened))
    return ids


def shot_18(page, run_dir: Path, out: Path) -> str:
    page.wait_for_selector(".cand", timeout=30_000)
    # Park the playhead inside the top candidate: clicking the card seeks
    # to its best frame, which lights the badge and the active band.
    page.eval_on_selector(".cand", "el => el.click()")
    page.wait_for_timeout(1500)

    cands = page.eval_on_selector_all(".cand", "els => els.length")
    if cands < 1:
        raise AssertionError("no reel candidates rendered")
    paths = page.eval_on_selector_all("#tl path", "els => els.length")
    if paths < 1:
        raise AssertionError("the score_temporal curve drew no path")
    vt = (page.text_content("#vT") or "").strip()
    if vt in ("", "—"):
        raise AssertionError(f"HUD shows no temporal score: {vt!r}")
    for bid in ("bJ", "bK", "bL"):
        if not page.is_visible(f"#{bid}"):
            raise AssertionError(f"transport button #{bid} is not visible")
    ids = gate_visible_frames(page, run_dir, out.name)
    save_shot(page, out)
    return f"{cands} 候选 · temporal {vt} · J/K/L present · 画面内 {len(ids)} 帧全部已过目"


def shot_19(page, run_dir: Path, out: Path, want: str) -> str:
    page.wait_for_selector(".cand img.thumb", timeout=30_000)
    opts = page.eval_on_selector_all(
        "#grade option", "els => els.map(e => [e.value, e.textContent])")
    pick = next((v for v, _ in opts if v == want),
                next((v for v, _ in opts if v != "none"), None))
    if pick is None:
        raise AssertionError(f"no LUT to pick from: {opts}")
    label = next(t for v, t in opts if v == pick)

    plain = page.get_attribute("#viewer", "src")
    page.select_option("#grade", pick)
    page.wait_for_timeout(2500)
    graded = page.get_attribute("#viewer", "src")
    if "grade=" not in (graded or ""):
        raise AssertionError(f"main frame did not ask for a grade: {graded}")
    thumb = page.get_attribute(".cand img.thumb", "src") or ""
    if "grade=" not in thumb:
        raise AssertionError(
            f"candidate thumbnails are not previewing the LUT: {thumb}")

    avg, peak = page.evaluate(_DIFF_JS, [plain, graded])
    if avg < 3.0 or peak < 24:
        raise AssertionError(
            f"{label} barely changes the picture (per-pixel mean "
            f"{avg:.1f}, max {peak:.0f} of 255) — the caption claims a "
            f"visible preview, so this would be a screenshot of a "
            f"dropdown, not of a grade")
    page.wait_for_timeout(600)
    ids = gate_visible_frames(page, run_dir, out.name)
    save_shot(page, out)
    return (f"{label} · 逐像素差 均值 {avg:.1f} / 峰值 {peak:.0f} (255) · "
            f"画面内 {len(ids)} 帧全部已过目")


def _in_viewport(page, selector: str) -> int:
    return page.eval_on_selector_all(selector, """els => {
      const h = window.innerHeight, w = window.innerWidth;
      return els.filter(e => { const r = e.getBoundingClientRect();
        return r.bottom > 0 && r.top < h && r.right > 0 && r.left < w
               && r.width > 0 && r.height > 0; }).length;
    }""")


def shot_23(page, out: Path) -> str:
    page.wait_for_selector(".row", timeout=30_000)
    rows = page.eval_on_selector_all(".row", "els => els.length")
    if rows < 2:
        raise AssertionError(
            f"{rows} row — a timeline with one time point is a list")
    # A year of a photographer's work is 28 rows and ~6700 px tall; the
    # whole page is honest and unreadable at README width. The video
    # segment sorts last (it was imported today, and the clip carries no
    # capture time of its own), so the bottom of the axis is where the
    # two kinds actually meet. The header is sticky, so the counts stay
    # in frame.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1200)
    vcards = _in_viewport(page, ".vcard")
    photos = _in_viewport(page, ".photos img")
    visible_rows = _in_viewport(page, ".row")
    if vcards < 1:
        raise AssertionError("no video segment in frame")
    if photos < 1:
        raise AssertionError("no photographs in frame")
    if visible_rows < 2:
        raise AssertionError(f"{visible_rows} row in frame")
    meta = (page.text_content("#meta") or "").strip()
    tally = (page.text_content("#tally") or "").strip()
    save_shot(page, out)
    return (f"{rows} 行(在画面内 {visible_rows}) · 缩略图 {photos} · "
            f"视频卡 {vcards} · {meta} · {tally}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-run", default="txdemo")
    ap.add_argument("--photo-run", default="",
                    help="run id for shot 23; default: POST /sample_demo")
    ap.add_argument("--port", type=int, default=8771)
    ap.add_argument("--lut", default="bw")
    ap.add_argument("--demo-root", type=Path,
                    default=Path(os.environ.get("PIXCULL_DEMO_ROOT",
                                                "/tmp/pixcull_demo")))
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()

    base = f"http://127.0.0.1:{args.port}"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed: pip install playwright && "
              "playwright install chromium", file=sys.stderr)
        return 2

    # The video run has to be real. A missing one would otherwise render
    # the 404 page and be photographed as if it were the product.
    try:
        vd = _get(f"{base}/video/data/{args.video_run}")
    except (urllib.error.URLError, OSError) as exc:
        print(f"cannot reach {base}: {exc}", file=sys.stderr)
        return 2
    if not vd.get("ok") or not vd.get("reel"):
        print(f"run {args.video_run!r} is not a usable video run — run "
              f"`pixcull video <clip> -o /tmp/pixcull_demo/{args.video_run}` "
              f"first", file=sys.stderr)
        return 1

    photo_run = args.photo_run
    if not photo_run:
        photo_run = _post(f"{base}/sample_demo", {})["run_id"]
    tl = _get(f"{base}/timeline/data/{photo_run}")
    if not tl.get("photo_count"):
        print(f"run {photo_run!r} has no photographs on its timeline",
              file=sys.stderr)
        return 1

    SHOTS.mkdir(parents=True, exist_ok=True)
    notes: list[tuple[str, str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width,
                                          "height": args.height},
                                device_scale_factor=2)
        try:
            page.goto(f"{base}/video/{args.video_run}",
                      wait_until="networkidle", timeout=60_000)
            run_dir = args.demo_root / args.video_run
            out = SHOTS / "18-video-review.png"
            notes.append((out.name, shot_18(page, run_dir, out)))
            out = SHOTS / "19-video-grade.png"
            notes.append((out.name, shot_19(page, run_dir, out, args.lut)))

            page.goto(f"{base}/timeline/{photo_run}",
                      wait_until="networkidle", timeout=60_000)
            out = SHOTS / "23-video-timeline.png"
            notes.append((out.name, shot_23(page, out)))
        finally:
            browser.close()

    for name, note in notes:
        kb = (SHOTS / name).stat().st_size / 1024
        print(f"✓ docs/screenshots/{name}  {kb:.0f} KB")
        print(f"    {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
