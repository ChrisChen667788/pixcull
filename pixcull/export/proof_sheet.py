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
    index: int = 0         # v2.98 — burned into the picture, 1-based


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
    data = json.dumps([{"f": i.filename, "l": i.label, "r": i.rel}
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
    watermark — it is texture. Sized to the image, with the plain default
    as the last resort so a machine with no fonts still exports.
    """
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        pass
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, px)
        except Exception:  # noqa: BLE001
            continue
    from PIL import ImageFont as _IF
    return _IF.load_default()


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
 :root{--bg:#111214;--fg:#e9e9ea;--dim:#8b8d92;--pick:#4ea1ff;--line:#2a2c31}
 @media (prefers-color-scheme: light){
   :root{--bg:#fbfbfc;--fg:#17181b;--dim:#6c6e74;--line:#e3e4e8}}
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
 figure img{width:100%;display:block;aspect-ratio:3/2;object-fit:cover}
 figcaption{padding:6px 8px;font-size:12px;color:var(--dim);
            overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .tick{position:absolute;top:8px;right:8px;width:24px;height:24px;border-radius:50%;
       background:var(--pick);color:#fff;display:none;align-items:center;justify-content:center;
       font-size:14px}
 figure.on .tick{display:flex}
 dialog{max-width:min(680px,92vw);border:1px solid var(--line);border-radius:12px;
        background:var(--bg);color:var(--fg);padding:18px}
 textarea{width:100%;min-height:180px;background:transparent;color:var(--fg);
          border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.5 ui-monospace,monospace}
 .hint{color:var(--dim);font-size:13px;margin:8px 0 0}
</style></head><body>
<header>
  <h1>__TITLE__</h1>
  <span class="count" id="count">0 selected</span>
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
<script>
(function(){
  var ITEMS = __DATA__, CONTACT = "__CONTACT__", WEBHOOK = "__WEBHOOK__";
  var KEY = "pixcull.proof." + location.pathname;
  var picked = new Set();
  try { picked = new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); }
  catch (e) { picked = new Set(); }
  var grid = document.getElementById("grid");
  var countEl = document.getElementById("count");

  function save(){
    try { localStorage.setItem(KEY, JSON.stringify([...picked])); } catch (e) {}
    countEl.textContent = picked.size + " selected";
  }
  ITEMS.forEach(function(it){
    var fig = document.createElement("figure");
    if (picked.has(it.f)) fig.className = "on";
    var img = document.createElement("img");
    img.loading = "lazy"; img.src = it.r; img.alt = it.l;
    var cap = document.createElement("figcaption"); cap.textContent = it.l;
    var tick = document.createElement("span"); tick.className = "tick"; tick.textContent = "✓";
    fig.appendChild(img); fig.appendChild(tick); fig.appendChild(cap);
    fig.addEventListener("click", function(){
      if (picked.has(it.f)) { picked.delete(it.f); fig.classList.remove("on"); }
      else { picked.add(it.f); fig.classList.add("on"); }
      save();
    });
    grid.appendChild(fig);
  });
  save();
  document.getElementById("clear").addEventListener("click", function(){
    picked.clear(); save();
    [...grid.children].forEach(function(f){ f.classList.remove("on"); });
  });
  document.getElementById("send").addEventListener("click", function(){
    var chosen = ITEMS.filter(function(i){ return picked.has(i.f); });
    var text = chosen.map(function(i){ return i.l; }).join("\\n");
    document.getElementById("list").value = text || "(nothing selected)";
    var hint = document.getElementById("hint");
    hint.textContent = CONTACT ? ("Send to " + CONTACT) : "";
    if (WEBHOOK && chosen.length) {
      fetch(WEBHOOK, {method:"POST", mode:"no-cors",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({picks: chosen.map(function(i){ return i.f; })})
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
