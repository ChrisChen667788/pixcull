"""v2.5-P1 (reach) — client-ready contact-sheet / gallery PDF export.

The deliverable a photographer hands a client: a printable grid of the
run's selects, one thumbnail + filename + score per cell, paginated with
a title and page numbers.  Dependency-light on purpose — pure Pillow's
multi-page ``save(..., save_all=True)``, no reportlab — so it stays within
the project's vanilla-stack rule and needs nothing new installed.

Two layers:
  * :func:`render_contact_sheet` — pure layout: ``[(image_path, caption)]``
    → a multi-page PDF.  Independently unit-testable.
  * :func:`contact_sheet_from_run` — convenience wrapper that reads a run's
    ``scores.csv``, filters by decision, resolves each thumbnail, and calls
    the renderer.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

# Editorial-warm ink, matching the rest of the brand.
_INK = (22, 19, 16)        # espresso
_MUTED = (106, 96, 82)     # graphite
_BG = (250, 248, 245)      # warm paper
_A4_150DPI = (1240, 1754)  # A4 portrait @ ~150 dpi — readable, modest file size

# TrueType candidates (macOS / Linux); falls back to Pillow's bitmap font.
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def render_contact_sheet(
    items: Sequence[tuple],
    out_pdf: Path | str,
    *,
    title: str = "PixCull — Selects",
    cols: int = 4,
    rows_per_page: int = 5,
    page: tuple[int, int] = _A4_150DPI,
    margin: int = 60,
    gutter: int = 18,
) -> int:
    """Render ``items`` (``(image_path, caption)`` tuples) into a grid PDF.

    Lays out ``cols × rows_per_page`` cells per page (thumbnail fit into the
    cell, caption below), a title band on top and a ``n / total`` footer.
    Unreadable / missing images are drawn as an outlined "missing" cell so
    one bad file never aborts the sheet.  Returns the page count.
    """
    from PIL import Image, ImageDraw

    items = list(items)
    W, H = page
    title_h = 64
    cap_h = 30
    title_font = _font(30)
    cap_font = _font(16)
    foot_font = _font(15)

    cell_w = (W - 2 * margin - (cols - 1) * gutter) // cols
    avail_h = H - 2 * margin - title_h
    cell_h = (avail_h - (rows_per_page - 1) * gutter) // rows_per_page
    thumb_h = cell_h - cap_h
    per_page = cols * rows_per_page
    n_pages = max(1, (len(items) + per_page - 1) // per_page)

    pages: list = []
    for pi in range(n_pages):
        canvas = Image.new("RGB", page, _BG)
        d = ImageDraw.Draw(canvas)
        d.text((margin, margin - 6), title, font=title_font, fill=_INK)
        d.line([(margin, margin + title_h - 14),
                (W - margin, margin + title_h - 14)], fill=_MUTED, width=1)
        chunk = items[pi * per_page:(pi + 1) * per_page]
        for idx, item in enumerate(chunk):
            img_path, caption = item[0], (item[1] if len(item) > 1 else "")
            r, c = divmod(idx, cols)
            x = margin + c * (cell_w + gutter)
            y = margin + title_h + r * (cell_h + gutter)
            try:
                im = Image.open(img_path).convert("RGB")
                im.thumbnail((cell_w, thumb_h))
                canvas.paste(im, (x + (cell_w - im.width) // 2,
                                  y + (thumb_h - im.height) // 2))
            except Exception:                              # noqa: BLE001
                d.rectangle((x, y, x + cell_w, y + thumb_h),
                            outline=_MUTED, width=1)
                d.text((x + 8, y + 8), "(image unavailable)",
                       font=cap_font, fill=_MUTED)
            d.text((x, y + thumb_h + 6), str(caption)[:46],
                   font=cap_font, fill=_MUTED)
        d.text((W - margin - 70, H - margin + 4),
               f"{pi + 1} / {n_pages}", font=foot_font, fill=_MUTED)
        pages.append(canvas)

    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out_pdf, "PDF", save_all=True,
                  append_images=pages[1:], resolution=150.0)
    return n_pages


def _is_num(v) -> bool:
    try:
        x = float(v)
        return x == x
    except (TypeError, ValueError):
        return False


def _resolve_thumb(images_dir: Path, filename: str, row: dict) -> Path | str:
    """Best-effort path to a row's image: the run's thumbs dir first, then
    its recorded source path, else the raw join (renderer handles misses)."""
    if filename:
        cand = images_dir / filename
        if cand.is_file():
            return cand
        stem = images_dir / (Path(filename).stem + ".jpg")
        if stem.is_file():
            return stem
    src = row.get("src_path") or row.get("source_path")
    if src and Path(src).is_file():
        return Path(src)
    return images_dir / filename


def contact_sheet_from_run(
    run_dir: Path | str,
    out_pdf: Path | str,
    *,
    decision: str = "keep",
    images_dir: Path | str | None = None,
    title: str | None = None,
    **kw,
) -> tuple[int, int]:
    """Build a contact-sheet PDF from a run's ``scores.csv``.

    ``decision`` filters rows (``keep`` / ``maybe`` / ``cull`` / ``all``).
    Returns ``(n_pages, n_photos)``.
    """
    run_dir = Path(run_dir)
    csv_path = run_dir / "scores.csv"
    if not csv_path.is_file() and (run_dir / "output" / "scores.csv").is_file():
        csv_path = run_dir / "output" / "scores.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"no scores.csv under {run_dir}")

    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if decision and decision.lower() != "all":
        rows = [r for r in rows
                if (r.get("decision") or "").strip().lower() == decision.lower()]

    img_dir = Path(images_dir) if images_dir else (csv_path.parent / "thumbs")
    items: list[tuple] = []
    for r in rows:
        fn = r.get("filename", "") or ""
        sc = r.get("score_final")
        cap = f"{fn}   {float(sc):.2f}" if _is_num(sc) else fn
        items.append((_resolve_thumb(img_dir, fn, r), cap))

    if title is None:
        title = f"PixCull — {run_dir.name} — {len(items)} {decision} selects"
    n_pages = render_contact_sheet(items, out_pdf, title=title, **kw)
    return n_pages, len(items)
