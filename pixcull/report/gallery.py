"""V23.x — standalone HTML gallery export.

Wedding / travel / event photographers deliver "the top N photos" to
clients. Pre-V23.x PixCull's output dies at the results page — useful
for the photographer but not shareable. The browser results page won't
open without the PixCull server running, and clients don't run servers.

V23.x produces a single zip containing:
    index.html         — self-contained HTML, opens in any browser,
                         no server needed
    thumbs/<fn>.jpg    — JPEG thumbnails sized for the gallery grid
    full/<fn>.jpg      — 1600px JPEGs for the in-browser lightbox

The HTML embeds all CSS / JS inline so the user can email or upload
just the unzipped folder.

Design choices
==============
* Default: only ``keep`` photos. Add ``include`` arg to widen.
* JPEG re-encode at quality=85 for thumbnails (saves ~70% vs raw),
  quality=92 for full (lightbox needs to look good).
* In-browser lightbox is vanilla JS — keyboard nav (←/→/Esc), no
  external libs. Mobile-friendly via CSS touch handling.
* Score badges (5★ / 综合分 0.92) shown by default; client can hide
  via a URL param if they want a clean view.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Iterable

from PIL import Image


_THUMB_WIDTH = 600
_FULL_WIDTH = 1600
_THUMB_QUALITY = 85
_FULL_QUALITY = 92


_GALLERY_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0f1115; --fg: #e8e8ec; --muted: #8b8f99;
    --card-bg: #1a1d24; --border: #262932; --accent: #6cf;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font-family: -apple-system, "PingFang SC", "Helvetica Neue",
                      Arial, sans-serif; }
  header { padding: 24px 20px; border-bottom: 1px solid var(--border); }
  h1 { margin: 0 0 6px; font-size: 24px; font-weight: 500; }
  .meta { color: var(--muted); font-size: 13px; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 4px; padding: 4px;
  }
  .card {
    position: relative; background: var(--card-bg);
    overflow: hidden; cursor: pointer;
    aspect-ratio: 4 / 3;
  }
  .card img {
    width: 100%; height: 100%; object-fit: cover;
    display: block; transition: transform 0.2s;
  }
  .card:hover img { transform: scale(1.02); }
  .card .badge {
    position: absolute; top: 6px; right: 6px;
    background: rgba(0,0,0,0.6); color: var(--fg);
    padding: 2px 6px; border-radius: 3px;
    font-size: 11px; font-family: ui-monospace, monospace;
    backdrop-filter: blur(4px);
  }
  .card .fn {
    position: absolute; bottom: 6px; left: 6px;
    background: rgba(0,0,0,0.6); color: var(--fg);
    padding: 2px 6px; border-radius: 3px;
    font-size: 10px; font-family: ui-monospace, monospace;
    backdrop-filter: blur(4px); max-width: calc(100% - 24px);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  /* Lightbox */
  .lightbox {
    position: fixed; inset: 0; background: rgba(0,0,0,0.95);
    display: none; align-items: center; justify-content: center;
    z-index: 100; padding: 20px;
  }
  .lightbox.show { display: flex; }
  .lightbox img {
    max-width: 100%; max-height: 100%; object-fit: contain;
  }
  .lightbox .close, .lightbox .nav {
    position: absolute; background: rgba(255,255,255,0.1);
    color: var(--fg); border: none; padding: 8px 12px;
    cursor: pointer; font-size: 16px; border-radius: 4px;
  }
  .lightbox .close { top: 16px; right: 16px; }
  .lightbox .nav.prev { left: 16px; top: 50%; transform: translateY(-50%); }
  .lightbox .nav.next { right: 16px; top: 50%; transform: translateY(-50%); }
  .lightbox .info {
    position: absolute; bottom: 16px; left: 50%;
    transform: translateX(-50%); background: rgba(0,0,0,0.7);
    padding: 6px 12px; border-radius: 4px; font-size: 12px;
    backdrop-filter: blur(8px);
  }
  footer { padding: 20px; text-align: center; color: var(--muted);
            font-size: 11px; border-top: 1px solid var(--border); }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="meta">__META__</div>
</header>
<div class="grid" id="grid"></div>
<div class="lightbox" id="lightbox">
  <button class="close" id="closeBtn">✕</button>
  <button class="nav prev" id="prevBtn">◀</button>
  <img id="lbImg" alt="">
  <button class="nav next" id="nextBtn">▶</button>
  <div class="info" id="lbInfo"></div>
</div>
<footer>由 PixCull 生成 · __FOOTER__</footer>
<script>
  const PHOTOS = __PHOTOS_JSON__;
  const grid = document.getElementById("grid");
  PHOTOS.forEach((p, i) => {
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML =
      `<img loading="lazy" src="thumbs/${p.fn}" alt="${p.fn}">` +
      `<div class="badge">${(p.score * 5).toFixed(1)}★</div>` +
      `<div class="fn">${p.fn}</div>`;
    c.addEventListener("click", () => openLightbox(i));
    grid.appendChild(c);
  });

  const lb = document.getElementById("lightbox");
  const lbImg = document.getElementById("lbImg");
  const lbInfo = document.getElementById("lbInfo");
  let lbIdx = 0;

  function openLightbox(i) {
    lbIdx = i;
    const p = PHOTOS[i];
    lbImg.src = `full/${p.fn}`;
    lbInfo.textContent = `${i + 1} / ${PHOTOS.length} · ${p.fn} · ` +
                         `${(p.score * 5).toFixed(2)}★`;
    lb.classList.add("show");
  }
  function nav(delta) {
    lbIdx = (lbIdx + delta + PHOTOS.length) % PHOTOS.length;
    openLightbox(lbIdx);
  }
  document.getElementById("closeBtn").onclick = () => lb.classList.remove("show");
  document.getElementById("prevBtn").onclick = () => nav(-1);
  document.getElementById("nextBtn").onclick = () => nav(1);
  document.addEventListener("keydown", e => {
    if (!lb.classList.contains("show")) return;
    if (e.key === "Escape") lb.classList.remove("show");
    else if (e.key === "ArrowLeft") nav(-1);
    else if (e.key === "ArrowRight") nav(1);
  });
  lb.addEventListener("click", e => {
    if (e.target === lb) lb.classList.remove("show");
  });
</script>
</body>
</html>
"""


def _resize_jpeg(src_path: Path, target_width: int, quality: int) -> bytes:
    """Open + resize + re-encode an image as JPEG bytes. Returns the
    raw bytes ready for inclusion in the zip.

    Resize is "fit width" — the height adjusts to preserve aspect.
    Photos narrower than ``target_width`` are NOT upscaled (clients
    don't want stretched pixels in their delivered gallery).

    V26 — uses ``load_image_for_display`` so RAW (CR3/DNG/etc) gets a
    quality-preserving decode (full rawpy postprocess if the embedded
    JPEG is too small) instead of the soft camera-thumbnail preview.
    For JPG / HEIC paths this behaves identically to the previous
    ``Image.open + thumbnail`` path.
    """
    from pixcull.io.loader import load_image_for_display
    # max_side at 2× target gives headroom for portrait-orientation
    # photos (where the long side is the height); we re-crop to the
    # exact target width below.
    im = load_image_for_display(src_path, max_side=max(target_width * 2,
                                                          target_width))
    if im is None:
        # Last-resort fallback to the pre-V26 PIL path so the gallery
        # doesn't lose a frame on an unusual RAW format.
        with Image.open(src_path) as fallback:
            im = fallback.convert("RGB")
    w, h = im.size
    if w > target_width:
        new_h = int(h * target_width / w)
        im = im.resize((target_width, new_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True,
            progressive=True)
    return buf.getvalue()


def build_gallery_zip(
    run_id: str,
    rows: Iterable[dict],
    *,
    include_decisions: Iterable[str] = ("keep",),
    title: str | None = None,
) -> bytes:
    """Assemble a self-contained gallery zip from a run's row data.

    ``rows`` must be the same shape ``_build_results`` returns (each
    has ``filename``, ``decision``, ``score_final``, ``src_path``).
    Photos whose ``decision`` isn't in ``include_decisions`` are
    silently skipped — so the default produces a clean keep-only
    gallery. To get a "everything" gallery, pass
    ``include_decisions=("keep", "maybe", "cull")``.

    Returns raw zip bytes for the caller to stream / write.
    """
    keep_decisions = set(include_decisions)
    selected = [r for r in rows
                if r.get("decision") in keep_decisions
                and r.get("src_path")]
    # Sort by score_final desc so the best shot lands first in the
    # client's view (gallery feels stronger when opening).
    selected.sort(key=lambda r: -(r.get("score_final") or 0))

    photo_records = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in selected:
            src = Path(r["src_path"])
            if not src.exists():
                continue
            fn = r["filename"]
            try:
                thumb_bytes = _resize_jpeg(src, _THUMB_WIDTH, _THUMB_QUALITY)
                full_bytes = _resize_jpeg(src, _FULL_WIDTH, _FULL_QUALITY)
            except Exception:
                # Skip unreadable / corrupt source photos rather than
                # killing the whole export.
                continue
            zf.writestr(f"thumbs/{fn}", thumb_bytes)
            zf.writestr(f"full/{fn}", full_bytes)
            photo_records.append({
                "fn":    fn,
                "score": float(r.get("score_final") or 0),
            })

        if title is None:
            title = f"PixCull 精选 · {len(photo_records)} 张"
        meta_str = (
            f"run_id: {run_id} · "
            f"{len(photo_records)} / {len(selected)} 张照片 · "
            f"包含决策: {', '.join(sorted(keep_decisions))}"
        )
        footer = (
            f"run_id={run_id} · 单文件可发客户(双击 index.html 即可浏览)"
        )
        html = (
            _GALLERY_HTML
            .replace("__TITLE__", title)
            .replace("__META__", meta_str)
            .replace("__FOOTER__", footer)
            .replace(
                "__PHOTOS_JSON__",
                # </ escape so a stray filename can't break out of <script>
                json.dumps(photo_records, ensure_ascii=False)
                    .replace("</", "<\\/"),
            )
        )
        zf.writestr("index.html", html.encode("utf-8"))
        zf.writestr(
            "README.txt",
            f"PixCull Gallery export\n"
            f"======================\n"
            f"run_id: {run_id}\n"
            f"photos: {len(photo_records)}\n"
            f"included: {', '.join(sorted(keep_decisions))}\n\n"
            f"Open index.html in any browser. Keyboard: ← → 翻页, Esc 关闭.\n"
            f"No server required — fully self-contained.\n",
        )
    return buf.getvalue()


__all__ = ["build_gallery_zip"]
