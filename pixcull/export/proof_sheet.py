"""v2.87 — a proof sheet the client can open, with no account anywhere.

The largest product gap the 2026 Q3 competitive refresh found: between
the photographer's cull and the client's own selection there is a step
PixCull does not address at all. Every Chinese studio product addresses
it, and for that market its absence makes the tool incomplete however
good the culling is.

This is deliberately the smallest thing that closes the gap, and it is
NOT a delivery platform. No database, no accounts, no payments, no
hosting. It writes a folder. The photographer sends the folder, or drops
it on any static host, or zips it — and the client opens one HTML file.

WHY NOT MORE. The charter declines to build a client-selection commerce
platform: WeChat mini-programs, payment, revision tracking, against
incumbents with years of production and regulatory experience. A
photographer already on such a platform will not move, and should not.
This exists for the one who has none.

THE ORIGINALS NEVER GO IN. Derivatives are downsized and watermarked.
A proof sheet is for choosing, and a client who can lift a full-size
unwatermarked frame out of it has been sent the delivery, not the proof.

THE SELECTION COMES BACK AS TEXT. The gallery stores picks in the
client's own browser and produces a plain list they send back however
they already talk to the photographer. An optional webhook posts the
same list. There is no server here to receive anything, which is the
point: nothing to run, nothing to pay for, nothing to leak.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

PROOF_WIDTH = 1024
# Legible without obscuring the photograph. A client has to be able to
# judge the frame through it, or they cannot choose; a mark they can see
# and not read is texture, not a watermark.
WATERMARK_OPACITY = 0.20


@dataclass(frozen=True)
class ProofItem:
    filename: str          # the run-unique name (see pixcull.photo_id)
    label: str             # what the client sees
    rel: str               # path to the derivative, relative to the sheet
    index: int = 0         # v2.98 — 1-based reference number. Burned into the
                           # picture when number=True, and ALWAYS shown in the
                           # caption, left of the filename. Same numbering as
                           # picks_manifest.json by_index: the client quotes
                           # this number back.


def safe_slug(name: str) -> str:
    """A filename safe to write and safe to put in a URL.

    v2.76 made photo names relative paths, so they contain "/" — writing
    one straight into the output folder would create directories, or
    escape it. Everything outside a small allowlist becomes "_", and the
    result can never be empty, "." or "..".
    """
    s = re.sub(r"[^A-Za-z0-9._-]", "_", (name or "").strip())
    s = s.lstrip(".") or "photo"
    # Drop an existing image extension: the derivative is always a JPEG
    # and the caller appends ".jpg", so without this a photo arrives at
    # the client as "IMG_0042.jpg.jpg".
    s = re.sub(r"\.(jpe?g|png|tiff?|heic|webp|cr[23]|nef|arw|dng|raf|orf)$",
               "", s, flags=re.I) or "photo"
    return s[:120]


def build_items(rows: list[dict], *, only: str = "keep") -> list[ProofItem]:
    """Which frames go to the client.

    Default is the keepers. A proof sheet of everything is the contact
    sheet the photographer already has, and it asks the client to redo
    the cull that was just paid for.
    """
    out: list[ProofItem] = []
    seen: set[str] = set()
    for r in rows:
        if only and str(r.get("decision", "")) != only:
            continue
        fn = str(r.get("filename") or "")
        if not fn:
            continue
        slug = safe_slug(fn)
        base, n = slug, 1
        while slug in seen:            # two names slugging to one file
            n += 1
            slug = f"{base}~{n}"
        seen.add(slug)
        out.append(ProofItem(filename=fn,
                             label=str(r.get("orig_filename") or fn),
                             rel=f"photos/{slug}.jpg",
                             index=len(out) + 1))
    return out


def render_gallery(items: list[ProofItem], *, title: str,
                   contact: str = "", webhook: str = "") -> str:
    """The single HTML file the client opens. No network needed."""
    # The reference number has to travel with the item: the caption badge,
    # the full-screen view's title and the copyable list all read it, and
    # all three must agree with picks_manifest.json by_index — the client
    # quotes that number back.
    data = json.dumps([{"f": i.filename, "l": i.label, "r": i.rel,
                        "i": i.index}
                       for i in items], ensure_ascii=False)
    esc_title = html.escape(title or "Proof sheet")
    esc_contact = html.escape(contact or "")
    esc_hook = html.escape(webhook or "")
    return _TEMPLATE.replace("__TITLE__", esc_title) \
                    .replace("__CONTACT__", esc_contact) \
                    .replace("__WEBHOOK__", esc_hook) \
                    .replace("__DATA__", data)


def write_proof_sheet(rows: list[dict], dest: Path, *, resolve,
                      title: str = "", contact: str = "", webhook: str = "",
                      only: str = "keep", number: bool = True,
                      run_output: str = "") -> dict:
    """Write the whole sheet. ``resolve(filename) -> Path | None``.

    Returns counts. A frame whose original cannot be found is REPORTED,
    never skipped quietly: a proof sheet silently missing four
    photographs is a client conversation nobody wants to have, and this
    repository has shipped that shape of bug three times.
    """
    from PIL import Image, ImageDraw, ImageOps

    items = build_items(rows, only=only)
    photos = dest / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    written, missing = 0, []
    for it in items:
        src = resolve(it.filename)
        if not src or not Path(src).is_file():
            missing.append(it.filename)
            continue
        try:
            with Image.open(src) as im:
                # v2.87 — a camera writes portrait frames rotated with an
                # EXIF flag saying so. Skipping this sends the client
                # every vertical photograph on its side, and the repo has
                # a guard for exactly this because it has happened before.
                im = ImageOps.exif_transpose(im).convert("RGB")
                if im.width > PROOF_WIDTH:
                    h = round(im.height * PROOF_WIDTH / im.width)
                    im = im.resize((PROOF_WIDTH, h), Image.LANCZOS)
                _stamp(im, ImageDraw, title or "PROOF")
                if number:
                    _burn_index(im, ImageDraw, it.index)
                im.save(dest / it.rel, "JPEG", quality=82, optimize=True)
            written += 1
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{it.filename}: {type(exc).__name__}")

    kept = [i for i in items if not any(str(m).startswith(i.filename)
                                        for m in missing)]
    (dest / "index.html").write_text(
        render_gallery(kept, title=title or dest.name,
                       contact=contact, webhook=webhook), encoding="utf-8")

    # v2.98 — the manifest is the authority on what number means what.
    #
    # It must never be recomputed from the run: cull one more frame, or
    # re-export after a correction, and every number after that point
    # shifts by one. The client is looking at the pictures they were
    # sent, which carry the OLD numbers burned into them, and a
    # recomputed mapping would silently hand back the wrong photographs.
    #
    # `digest` fingerprints the exported set so a reply can be checked
    # against the export it actually came from.
    manifest = {
        "schema": "pixcull.proof_manifest/v1",
        "title": title or dest.name,
        "digest": _digest(kept),
        "n": len(kept),
        # v3.0 — where the picks go when the client replies. Recorded at
        # export time because the reply arrives days later, in WeChat,
        # with nothing but numbers in it.
        "run_output": str(run_output or ""),
        "by_index": {str(i.index): i.filename for i in kept},
        "labels": {str(i.index): i.label for i in kept},
    }
    (dest / "picks_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"selected": len(items), "written": written,
            "missing": missing, "dest": str(dest),
            "manifest": str(dest / "picks_manifest.json"),
            "digest": manifest["digest"]}


def _digest(items: list[ProofItem]) -> str:
    import hashlib
    h = hashlib.sha256()
    for i in items:
        h.update(f"{i.index}\x00{i.filename}\x00".encode())
    return h.hexdigest()[:12]


_SEP = re.compile(r"[\s,，、;;；/|]+")
_RANGE = re.compile(r"^(\d+)\s*[-~—–至到]\s*(\d+)$")
_NOISE = re.compile(r"第|张|号|图|片|no\.?|#", re.I)


def parse_picks(text: str, *, n: int) -> tuple[list[int], list[str]]:
    """Turn what the client actually typed into indices.

    Returns (indices, problems). Clients write "3、7、12", "第3张 第7张",
    "3-7", "3,7,12。" and every mixture. The parser is forgiving about
    shape and strict about range: a number outside 1..n is REPORTED, not
    dropped, because a silently ignored "17" on a 12-photo set is a
    photograph the client asked for and will not get.
    """
    problems: list[str] = []
    out: list[int] = []
    seen: set[int] = set()
    cleaned = _NOISE.sub(" ", str(text or ""))
    for tok in _SEP.split(cleaned):
        tok = tok.strip().strip(".。()()[]【】")
        if not tok:
            continue
        m = _RANGE.match(tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            span = list(range(a, b + 1))
            if len(span) > n:
                problems.append(f"{tok!r} spans more than the {n} sent")
                continue
            for v in span:
                if 1 <= v <= n:
                    if v not in seen:
                        seen.add(v)
                        out.append(v)
                else:
                    problems.append(f"{v} is outside 1..{n}")
            continue
        if tok.isdigit():
            v = int(tok)
            if 1 <= v <= n:
                if v not in seen:
                    seen.add(v)
                    out.append(v)
            else:
                problems.append(f"{v} is outside 1..{n}")
        else:
            problems.append(f"could not read {tok!r}")
    return out, problems


def _watermark_font(px: int):
    """A font big enough to read at the size the image is displayed.

    PIL's default bitmap font is about 11px. Tiled across a 1024px proof
    it produced marks a client could see and not read, which is not a
    watermark — it is texture. Sized to the image, and looked up on the
    system **first**: the bundled default carries no CJK glyphs, so a
    Chinese/Japanese/Korean title rendered through it came out as tofu
    boxes. The bundled default is kept as the last resort so a machine
    with no fonts still exports.

    (Bug: this function used to return ``ImageFont.load_default()`` on
    its first line, which made the whole system-font loop below dead code
    — every CJK watermark was tofu. The Windows path was missing too.)
    """
    from PIL import ImageFont
    for path in ("C:/Windows/Fonts/msyh.ttc",                     # 微软雅黑
                 "C:/Windows/Fonts/msyhbd.ttc",                   # 微软雅黑 Bold
                 "C:/Windows/Fonts/simhei.ttf",                   # 黑体
                 "C:/Windows/Fonts/simsun.ttc",                   # 宋体
                 "/System/Library/Fonts/PingFang.ttc",            # 苹方
                 "/System/Library/Fonts/Hiragino Sans GB.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                 # Latin-only last resorts, never ahead of a CJK font:
                 # Pillow opens a font by *name* even when the path does
                 # not exist — on a Mac "C:/Windows/Fonts/arial.ttf" loads
                 # as Arial, which has no CJK glyphs, so a Latin-only font
                 # placed above the CJK entries stops the loop there and
                 # every watermark below it renders tofu (PR #4 review).
                 "C:/Windows/Fonts/arial.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, px)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        pass
    return ImageFont.load_default()


def _burn_index(im, ImageDraw, n: int) -> None:
    """Burn the reference number into the picture, top-left.

    v2.98 — the client refers to a photograph by SOMETHING, and over
    WeChat the only things that survive are the pixels. A filename in a
    caption is lost the moment the album reorders, the client screenshots
    a subset, forwards a few to their mother, or two of the sends fail.
    Position is not an identifier; a number burned into the frame is.

    Sized to the image (about 9% of its height) so it is still readable
    in a chat thumbnail, on a dark plate so it survives on a bright sky,
    and top-left because that is where both Chinese and English readers
    start.
    """
    d = ImageDraw.Draw(im, "RGBA")
    size = max(28, int(im.height * 0.09))
    font = _watermark_font(size)
    label = str(n)
    try:
        box = d.textbbox((0, 0), label, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
    except Exception:  # noqa: BLE001
        tw, th = size * len(label), size
    pad = max(8, size // 4)
    inset = max(6, size // 5)
    # Fully opaque, and drawn after the watermark. At alpha 190 the
    # tiled mark showed through and ran across the digits, which is
    # exactly the legibility this exists to guarantee. Inset from the
    # corner so it reads as a badge rather than a crop artifact.
    d.rectangle([inset, inset,
                 inset + tw + pad * 2, inset + th + pad * 2],
                fill=(0, 0, 0, 255))
    d.text((inset + pad, inset + pad), label, font=font,
           fill=(255, 255, 255, 255))


def _stamp(im, ImageDraw, text: str) -> None:
    """A watermark that survives a crop of the middle.

    Tiled rather than placed once: a single corner mark is cropped off in
    one gesture, and the point of a proof is that what comes back is a
    choice, not a deliverable.
    """
    d = ImageDraw.Draw(im, "RGBA")
    size = max(18, im.width // 22)
    font = _watermark_font(size)
    try:
        box = d.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
    except Exception:  # noqa: BLE001
        tw, th = size * len(text) // 2, size
    step_x = max(tw + size * 3, im.width // 3)
    step_y = max(th + size * 3, im.height // 4)
    alpha = int(255 * WATERMARK_OPACITY)
    row = 0
    for y in range(0, im.height + step_y, step_y):
        offset = (step_x // 2) if row % 2 else 0    # brick, not grid
        for x in range(-step_x, im.width + step_x, step_x):
            d.text((x + offset + 1, y + 1), text, font=font,
                   fill=(0, 0, 0, alpha // 2))
            d.text((x + offset, y), text, font=font,
                   fill=(255, 255, 255, alpha))
        row += 1


_TEMPLATE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
 :root{--bg:#111214;--fg:#e9e9ea;--dim:#8b8d92;--pick:#4ea1ff;--line:#2a2c31;--star:#f5b301}
 @media (prefers-color-scheme: light){
   :root{--bg:#fbfbfc;--fg:#17181b;--dim:#6c6e74;--line:#e3e4e8;--star:#e09600}}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:15px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
 header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
        padding:14px 18px;display:flex;gap:14px;align-items:center;flex-wrap:wrap;z-index:2}
 h1{font-size:17px;margin:0;font-weight:600}
 .count{color:var(--dim);font-variant-numeric:tabular-nums}
 button{font:inherit;padding:7px 14px;border-radius:8px;border:1px solid var(--line);
        background:transparent;color:var(--fg);cursor:pointer}
 button.primary{background:var(--pick);border-color:var(--pick);color:#fff}
 main{display:grid;gap:12px;padding:18px;
      grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
 figure{margin:0;position:relative;cursor:pointer;border-radius:10px;overflow:hidden;
        border:2px solid transparent;background:#0000000d}
 figure.on{border-color:var(--pick)}
 .shot{position:relative}
 figure img{width:100%;display:block;aspect-ratio:3/2;object-fit:cover}
 /* The reference number is now shown in the caption, left of the filename:
    a monospace pill on var(--line) with a var(--dim) outline, so it reads
    as a number and not as part of the name in either theme. .fn alone owns
    the ellipsis and .idx never shrinks, so a long filename still truncates
    without ever squeezing the number away. */
 figcaption{padding:6px 8px;font-size:12px;color:var(--dim);
            display:flex;align-items:center;gap:8px;min-width:0}
 .idx{flex:0 0 auto;font:700 11px/1.35 ui-monospace,SFMono-Regular,Menlo,
      Consolas,"Courier New",monospace;color:var(--fg);background:var(--line);
      border:1px solid var(--dim);border-radius:999px;padding:1px 7px;
      min-width:24px;text-align:center;font-variant-numeric:tabular-nums;
      letter-spacing:.03em}
 .fn{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;
     white-space:nowrap}
 .tick{position:absolute;top:8px;right:8px;width:24px;height:24px;border-radius:50%;
       background:var(--pick);color:#fff;display:none;align-items:center;justify-content:center;
       font-size:14px}
 figure.on .tick{display:flex}
 .zoom{position:absolute;right:8px;bottom:8px;width:32px;height:32px;padding:0;
       border-radius:50%;background:#000000a6;color:#fff;border:1px solid #ffffff40;
       font-size:15px;line-height:1;display:flex;align-items:center;justify-content:center;
       cursor:zoom-in;opacity:.85}
 .zoom:hover{opacity:1}
 .stars{display:flex;gap:2px;padding:3px 7px 0;line-height:1;user-select:none}
 .star{font-size:20px;line-height:1;padding:0 3px;color:var(--dim);cursor:pointer}
 .star.on{color:var(--star)}
 dialog{max-width:min(680px,92vw);border:1px solid var(--line);border-radius:12px;
        background:var(--bg);color:var(--fg);padding:18px}
 textarea{width:100%;min-height:180px;background:transparent;color:var(--fg);
          border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.5 ui-monospace,monospace}
 .hint{color:var(--dim);font-size:13px;margin:8px 0 0}
 /* The full-screen view. Hidden until .open, and it fetches nothing: the
    client may be looking at this sheet from a USB stick on a train. */
 .viewer{position:fixed;inset:0;z-index:50;display:none;align-items:center;justify-content:center;
         background:#000000f2;padding:52px 12px 112px;box-sizing:border-box}
 .viewer.open{display:flex}
 .viewer img{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block}
 .vnav{position:absolute;top:calc(50% - 30px);transform:translateY(-50%);width:48px;height:48px;padding:0;
       border-radius:50%;background:#ffffff1f;color:#fff;border:1px solid #ffffff38;
       font-size:26px;line-height:1;cursor:pointer}
 .vnav:hover{background:#ffffff38}
 #vprev{left:14px}
 #vnext{right:14px}
 .vclose{position:absolute;top:14px;right:14px;width:40px;height:40px;padding:0;
         border-radius:50%;background:#ffffff1f;color:#fff;border:1px solid #ffffff38;
         font-size:18px;line-height:1;cursor:pointer}
 .vclose:hover{background:#ffffff38}
 .vbar{position:absolute;left:0;right:0;bottom:72px;display:flex;justify-content:center;
       gap:16px;color:#fff;font-size:13px;pointer-events:none;padding:0 18px;
       text-align:center;text-shadow:0 1px 3px #000}
 /* The view's control bar: pick and rate without leaving the picture.
    It is one strip at the bottom, and the picture keeps clear of it
    through the layer's own padding-bottom. The strip itself is
    pointer-events:none so a click on blank space still closes the layer;
    only the controls take clicks. Buttons and stars are at least 44px
    tall, so a finger hits them on a phone. */
 .vctl{position:absolute;left:0;right:0;bottom:12px;display:flex;justify-content:center;
       align-items:center;gap:12px;flex-wrap:nowrap;padding:0 12px;
       box-sizing:border-box;pointer-events:none}
 .vbtn{min-height:46px;padding:0 16px;border-radius:999px;font-size:15px;font-weight:600;
       cursor:pointer;background:#ffffff1f;color:#fff;border:1px solid #ffffff59;
       white-space:nowrap;flex:0 0 auto;pointer-events:auto;
       -webkit-tap-highlight-color:transparent}
 .vbtn:hover{background:#ffffff38}
 .vbtn.on{background:var(--pick);border-color:var(--pick);color:#fff}
 .vstars{display:flex;align-items:center;background:#ffffff14;border:1px solid #ffffff40;
         border-radius:999px;padding:0 6px;height:46px;box-sizing:border-box;
         flex:0 1 auto;pointer-events:auto}
 .vstar{font-size:24px;line-height:1;color:#ffffff8c;cursor:pointer;width:38px;height:46px;
        display:flex;align-items:center;justify-content:center;user-select:none;
        -webkit-tap-highlight-color:transparent}
 .vstar.on{color:var(--star)}
 @media (max-width:560px){
   .vctl{gap:8px;padding:0 8px}
   .vbtn{padding:0 12px;font-size:14px;min-height:44px}
   .vstars{height:44px;padding:0 4px}
   .vstar{width:32px;height:44px;font-size:22px}}

 /* Touch: no tap delay, and every new control keeps a finger-sized target
    on a narrow screen. */
 figure, button, .star, .stars, .zoom, .vbtn, .vstar, .tick, .vnav, .vclose,
 .idx, .fn { touch-action: manipulation; }
 @media (pointer: coarse) {
   button { min-height: 44px; padding: 10px 18px; }
   .star { font-size: 28px; padding: 4px 5px; min-width: 40px; min-height: 40px; }
   .stars { gap: 2px; }
   .zoom { width: 42px; height: 42px; font-size: 20px; }
   .vbtn { min-height: 48px; padding: 0 18px; }
   .vstar { width: 44px; height: 48px; font-size: 26px; }
   .vnav { width: 48px; height: 48px; font-size: 26px; }
   .vclose { width: 46px; height: 46px; }
 }
 @media (max-width: 560px) {
   main { padding: 10px; gap: 10px;
          grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
   header { padding: 10px 12px; gap: 10px; }
   h1 { font-size: 16px; }
   button { padding: 9px 14px; }
   .vctl { flex-wrap: wrap; gap: 8px; }   /* wrap rather than overflow */
   .vbtn { font-size: 14px; padding: 0 14px; }
   .vstar { width: 34px; height: 44px; font-size: 22px; }
 }
</style></head><body>
<header>
  <h1>__TITLE__</h1>
  <span class="count" id="count">0 selected</span>
  <span class="count" id="rated">0 rated</span>
  <span style="flex:1"></span>
  <button id="clear">Clear</button>
  <button class="primary" id="send">Send my picks</button>
</header>
<main id="grid"></main>
<dialog id="out">
  <p>Copy this list and send it back:</p>
  <textarea id="list" readonly></textarea>
  <p class="hint" id="hint"></p>
  <p style="text-align:right;margin-bottom:0">
    <button id="copy">Copy</button>
    <button class="primary" id="close">Close</button></p>
</dialog>
<div id="viewer" class="viewer" role="dialog" aria-modal="true" aria-label="Larger view">
  <img id="vimg" alt="">
  <button id="vprev" class="vnav" title="Previous (←)" aria-label="Previous">‹</button>
  <button id="vnext" class="vnav" title="Next (→)" aria-label="Next">›</button>
  <button id="vclose" class="vclose" title="Close (Esc)" aria-label="Close">✕</button>
  <div class="vbar"><span id="vlabel"></span><span id="vcount"></span></div>
  <div class="vctl" id="vctl">
    <button id="vpick" class="vbtn vpick" type="button" aria-pressed="false">Pick this one</button>
    <span id="vstars" class="vstars" role="group" aria-label="Rate 1 to 5 stars"></span>
  </div>
</div>
<script>
(function(){
  var ITEMS = __DATA__, CONTACT = "__CONTACT__", WEBHOOK = "__WEBHOOK__";
  var KEY = "pixcull.proof." + location.pathname;
  var RKEY = KEY + ".ratings";
  var picked = new Set();
  try { picked = new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); }
  catch (e) { picked = new Set(); }
  // Stars are kept apart from picks: a client may rate a frame they did
  // not pick, and Clear (which means "clear my picks") must not wipe them.
  var ratings = {};
  try { ratings = JSON.parse(localStorage.getItem(RKEY) || "{}") || {}; }
  catch (e) { ratings = {}; }
  if (typeof ratings !== "object" || ratings === null) ratings = {};
  // A re-export to the same path leaves stars behind for frames this
  // sheet no longer has. Only the photographs on this page count, or the
  // counter and the webhook would report the previous export's ratings.
  var KNOWN = {};
  ITEMS.forEach(function(i){ KNOWN[i.f] = 1; });
  Object.keys(ratings).forEach(function(k){ if (!KNOWN[k]) delete ratings[k]; });
  var grid = document.getElementById("grid");
  var countEl = document.getElementById("count");
  var ratedEl = document.getElementById("rated");

  // Zooming opens a full-screen layer over the grid. A plain click is
  // already the pick gesture, so zoom has its own button and swallows the
  // click, and opening it never picks or unpicks the frame.
  var viewer = document.getElementById("viewer");
  var vimg = document.getElementById("vimg");
  var vlabel = document.getElementById("vlabel");
  var vcount = document.getElementById("vcount");
  var vIdx = -1;

  // The layer keeps NO state of its own: picked and ratings above are the
  // only copies, and every change goes through togglePickAt() / rateAt().
  // Those update the state, repaint that frame in the grid and call
  // save(), which writes localStorage, refreshes the header counts and
  // repaints the layer. The grid's own click and star handlers call the
  // same two functions, so the two views cannot disagree, and closing the
  // layer always reveals a grid that is already up to date.
  var vpick = document.getElementById("vpick");
  var vstars = document.getElementById("vstars");
  var vctl = document.getElementById("vctl");
  var vStarEls = [];
  var figs = [], paints = [];   // grid figure / star repainter, by ITEMS index

  function paintPick(i){
    var it = ITEMS[i], f = figs[i];
    if (!it || !f) return;
    if (picked.has(it.f)) f.classList.add("on"); else f.classList.remove("on");
  }
  function togglePickAt(i){
    var it = ITEMS[i];
    if (!it) return;
    if (picked.has(it.f)) picked.delete(it.f); else picked.add(it.f);
    paintPick(i);      // the grid frame's .on class and its ✓
    save();            // header count, localStorage, the layer's button
  }
  function rateAt(i, v){
    var it = ITEMS[i];
    if (!it) return;
    v = parseInt(v, 10) || 0;
    if (v < 1 || v > 5) { delete ratings[it.f]; }                  // 0 or out of range clears
    else if ((ratings[it.f] || 0) === v) { delete ratings[it.f]; } // the same star again clears
    else { ratings[it.f] = v; }
    if (paints[i]) paints[i]();   // repaint that frame's stars in the grid
    save();                       // header count, localStorage, the layer's stars
  }

  // The layer is a display of picked / ratings and nothing else.
  function vPaint(){
    if (vIdx < 0 || !ITEMS.length) return;
    var it = ITEMS[vIdx];
    var on = picked.has(it.f);
    vpick.textContent = on ? "✓ Picked — click to clear" : "Pick this one";
    vpick.className = on ? "vbtn vpick on" : "vbtn vpick";
    vpick.title = on ? "Clear this pick (space)" : "Pick this one (space)";
    vpick.setAttribute("aria-pressed", on ? "true" : "false");
    var cur = ratings[it.f] || 0;
    for (var k = 0; k < vStarEls.length; k++) {
      var lit = (k + 1) <= cur;
      vStarEls[k].textContent = lit ? "★" : "☆";
      vStarEls[k].className = lit ? "vstar on" : "vstar";
    }
    vstars.title = cur ? ("Rated " + cur + " of 5 — click the same star to clear (0 also clears)")
                       : "Rate 1 to 5 stars (keys 1-5, 0 clears)";
  }

  function vShow(i){
    if (!ITEMS.length) return;
    vIdx = ((i % ITEMS.length) + ITEMS.length) % ITEMS.length;   // wraps around
    var it = ITEMS[vIdx];
    vimg.src = it.r; vimg.alt = it.l;
    vlabel.textContent = it.i + ". " + it.l;   // the caption's number, the same one
    vcount.textContent = (vIdx + 1) + " / " + ITEMS.length;
    vPaint();   // the frame now shown keeps its own pick and stars
  }
  function vOpen(i){
    vShow(i);
    viewer.classList.add("open");
    viewer.setAttribute("aria-hidden", "false");
    try { document.body.style.overflow = "hidden"; } catch (e) {}
  }
  function vClose(){
    viewer.classList.remove("open");
    viewer.setAttribute("aria-hidden", "true");
    try { document.body.style.overflow = ""; } catch (e) {}
  }
  function isOpen(){ return viewer.classList.contains("open"); }

  // A click on the blank space (the layer itself, not the picture and not
  // a control) closes it.
  viewer.addEventListener("click", function(ev){
    if (ev.target === viewer) { vClose(); }
  });
  document.getElementById("vclose").addEventListener("click", function(ev){
    ev.stopPropagation(); ev.preventDefault(); vClose();
  });
  document.getElementById("vprev").addEventListener("click", function(ev){
    ev.stopPropagation(); ev.preventDefault(); vShow(vIdx - 1);
  });
  document.getElementById("vnext").addEventListener("click", function(ev){
    ev.stopPropagation(); ev.preventDefault(); vShow(vIdx + 1);
  });

  // The controls live inside .vctl and swallow their own clicks too, so
  // pressing one can never count as a click on the layer's blank space.
  vctl.addEventListener("click", function(ev){ ev.stopPropagation(); });
  vpick.addEventListener("click", function(ev){
    ev.stopPropagation(); ev.preventDefault(); togglePickAt(vIdx);
  });
  for (var q = 1; q <= 5; q++) {
    (function(v){
      var st = document.createElement("span");
      st.className = "vstar"; st.setAttribute("data-v", String(v));
      st.textContent = "☆"; st.title = v + " star" + (v > 1 ? "s" : "");
      st.setAttribute("aria-label", v + " star" + (v > 1 ? "s" : ""));
      st.addEventListener("click", function(ev){
        ev.stopPropagation(); ev.preventDefault(); rateAt(vIdx, v);
      });
      vstars.appendChild(st); vStarEls.push(st);
    })(q);
  }

  // Keys, while the layer is open: Esc closes, ←/→ page, space picks,
  // 1-5 rate and 0 clears the rating. Anything carrying Ctrl / Cmd / Alt
  // is left alone, so the browser keeps its own shortcuts.
  document.addEventListener("keydown", function(ev){
    if (!isOpen()) return;
    var k = ev.key;
    if (k === "Escape" || k === "Esc") { vClose(); }
    else if (k === "ArrowLeft") { vShow(vIdx - 1); }
    else if (k === "ArrowRight") { vShow(vIdx + 1); }
    else if (ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
    else if (k === " " || k === "Spacebar") { togglePickAt(vIdx); }
    else if (typeof k === "string" && k.length === 1 && k >= "1" && k <= "5") { rateAt(vIdx, k); }
    else if (k === "0") { rateAt(vIdx, 0); }
    else { return; }
    if (ev.preventDefault) ev.preventDefault();
  });

  function save(){
    try { localStorage.setItem(KEY, JSON.stringify([...picked])); } catch (e) {}
    try { localStorage.setItem(RKEY, JSON.stringify(ratings)); } catch (e) {}
    countEl.textContent = picked.size + " selected";
    ratedEl.textContent = Object.keys(ratings).length + " rated";
    vPaint();   // repaint the layer from the same state
  }
  ITEMS.forEach(function(it, idx){
    var fig = document.createElement("figure");
    figs[idx] = fig;                 // the layer repaints the grid through this
    if (picked.has(it.f)) fig.className = "on";
    var shot = document.createElement("div"); shot.className = "shot";
    var img = document.createElement("img");
    img.loading = "lazy"; img.src = it.r; img.alt = it.l;
    // The number and the name are two separate elements, so the number is
    // told apart by structure and not merely by looking different: .idx is
    // the pill, .fn is the filename.
    var cap = document.createElement("figcaption");
    var idxEl = document.createElement("span");
    idxEl.className = "idx"; idxEl.textContent = String(it.i);
    idxEl.title = "Number " + it.i;
    var fnEl = document.createElement("span");
    fnEl.className = "fn"; fnEl.textContent = it.l; fnEl.title = it.l;
    cap.appendChild(idxEl); cap.appendChild(fnEl);
    var tick = document.createElement("span"); tick.className = "tick"; tick.textContent = "✓";
    var zbtn = document.createElement("button");
    zbtn.type = "button"; zbtn.className = "zoom"; zbtn.textContent = "🔍";
    zbtn.title = "View larger"; zbtn.setAttribute("aria-label", "View larger");
    zbtn.addEventListener("click", function(ev){
      ev.stopPropagation(); ev.preventDefault();   // never picks or unpicks
      vOpen(idx);
    });
    shot.appendChild(img); shot.appendChild(tick); shot.appendChild(zbtn);
    var stars = document.createElement("span");
    stars.className = "stars"; stars.title = "Click a star to rate 1 to 5; the same star again clears it";
    function paint(){
      var cur = ratings[it.f] || 0;
      for (var k = 0; k < stars.children.length; k++) {
        var on = k < cur;
        stars.children[k].textContent = on ? "★" : "☆";
        stars.children[k].className = on ? "star on" : "star";
      }
    }
    paints[idx] = paint;             // the layer repaints the grid through this
    for (var s = 1; s <= 5; s++) {
      var st = document.createElement("span");
      st.className = "star"; st.setAttribute("data-v", String(s));
      st.textContent = "☆";
      st.setAttribute("aria-label", "Rate " + s + " star" + (s > 1 ? "s" : ""));
      st.addEventListener("click", function(ev){
        ev.stopPropagation();          // rating never picks or unpicks
        ev.preventDefault();
        // the one entry point, shared with the layer's stars
        rateAt(idx, this.getAttribute("data-v"));
      });
      stars.appendChild(st);
    }
    paint();
    fig.appendChild(shot);
    fig.appendChild(stars); fig.appendChild(cap);
    fig.addEventListener("click", function(){
      // the one entry point, shared with the layer's Pick button
      togglePickAt(idx);
    });
    grid.appendChild(fig);
  });
  save();
  document.getElementById("clear").addEventListener("click", function(){
    picked.clear();   // picks only: the stars are the client's own, kept
    for (var c = 0; c < ITEMS.length; c++) paintPick(c);
    save();           // header count and the layer's button follow
  });
  document.getElementById("send").addEventListener("click", function(){
    var chosen = ITEMS.filter(function(i){ return picked.has(i.f); });
    var text = chosen.map(function(i){
      var r = ratings[i.f] || 0;
      // The copyable list carries the number too, so what the client
      // pastes back is the same number as the pill and the manifest.
      return i.i + ". " + i.l + (r ? " " + "★★★★★".slice(0, r) : "");
    }).join("\\n");
    document.getElementById("list").value = text || "(nothing selected)";
    var hint = document.getElementById("hint");
    hint.textContent = CONTACT ? ("Send to " + CONTACT) : "";
    var rated = {};
    Object.keys(ratings).forEach(function(k){
      var n = parseInt(ratings[k], 10) || 0;
      if (n >= 1 && n <= 5) rated[k] = n;      // only real 1-5 star ratings
    });
    if (WEBHOOK && chosen.length) {
      fetch(WEBHOOK, {method:"POST", mode:"no-cors",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({picks: chosen.map(function(i){ return i.f; }),
                              ratings: rated})
      }).catch(function(){});
    }
    document.getElementById("out").showModal();
  });
  document.getElementById("copy").addEventListener("click", function(){
    var t = document.getElementById("list");
    t.select();
    try { navigator.clipboard.writeText(t.value); } catch (e) { document.execCommand("copy"); }
  });
  document.getElementById("close").addEventListener("click", function(){
    document.getElementById("out").close();
  });
})();
</script></body></html>
"""
