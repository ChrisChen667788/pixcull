"""v0.9-P1-3 — executive-summary PDF renderer.

The v0.4 P2 (4/4) cli_audit `--pdf` flag already produces a clean
audit PDF (cover-less, just markdown→HTML→Chrome).  This module
turns that into something a photographer is proud to *send* to a
client:

  Page 1   Cover       brand mark + client + event + date + key stats
  Page 2   Contents    linked ToC pointing at all sections + page nums
  Page 3   Dashboard   Strava-style key-numbers card grid
  Page 4   Best 5      thumbnail wall of the top-scoring photos
  Page 5   Inconsisten thumbnail wall of borderline / disagreement rows
  Page 6   Cull top    horizontal-bar of the 5 most-used cull reasons
  Page 7+  Sections    the existing audit body (scene / face / wedding)

Two design goals:

  * Pure-function — every cell of the dashboard is computed from
    scores.csv + annotations.jsonl, no Chrome required, so the
    module tests in isolation (see tests/test_executive_pdf.py).
  * Print-first — every block carries `page-break-before: always`
    where needed so Chrome headless lays out pages exactly the way
    we'd lay them out in InDesign.

The module exposes one entry point — :func:`build_executive_html` —
which the cli_audit `--executive` flag calls right before passing
the assembled HTML to Chrome.  Everything else is a private helper
that the unit tests can poke at via the module-level symbol.
"""

from __future__ import annotations

import base64
import html as _html
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Photographers shoot 100+ MP RAW; Pillow's default 89 MP guard
# treats those as decompression-bomb attacks and warns on every
# Image.open.  Bump the ceiling at module-import time so the warning
# never fires for user-trusted local files the pipeline has already
# read once.  Local-import to keep Pillow optional.
try:
    from PIL import Image as _PILImage  # type: ignore
    _PILImage.MAX_IMAGE_PIXELS = 256_000_000  # ~256 MP
except Exception:
    pass


# ----------------------------------------------------------------------
# Brand constants — keep in sync with docs/brand/* + results.html CSS.
# Inlined here (rather than imported from a styles module) so the PDF
# generator stays a leaf-level utility with no GUI dependencies.
# ----------------------------------------------------------------------

BRAND_INDIGO = "#6E56CF"
BRAND_VIOLET = "#A855F7"
BRAND_PINK   = "#EC4899"
BRAND_GRADIENT = (
    f"linear-gradient(135deg, {BRAND_INDIGO} 0%, "
    f"{BRAND_VIOLET} 55%, {BRAND_PINK} 100%)"
)
SERIF_STACK = (
    "Charter, 'Iowan Old Style', 'PT Serif', "
    "'Source Serif Pro', Georgia, serif"
)
SANS_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', "
    "'PingFang SC', 'Hiragino Sans', sans-serif"
)


# ----------------------------------------------------------------------
# Data extraction — operates on the same scores.csv shape that
# results.html + cli_audit already speak.  Pure functions; the
# Chrome-headless rendering happens at the call site.
# ----------------------------------------------------------------------


def compute_dashboard(
    rows: list[dict],
) -> dict:
    """Roll up scores.csv rows into the dashboard numbers.

    ``rows`` is a list of dicts (one per photo) carrying at least
    ``filename``, ``decision``, ``score_final``.  Additional columns
    (``scene``, ``cull_reason``, ``wedding_moment``,
    ``rubric_human_labeled``, ``rubric_stars``) light up more of
    the dashboard but are all optional — the function tolerates
    csv schemas missing any of them.
    """
    n_total = len(rows)
    decisions = Counter()
    scenes    = Counter()
    moments   = Counter()
    cull_rs   = Counter()
    score_acc = []
    human_n   = 0
    for r in rows:
        d = (r.get("decision") or "").strip()
        if d:
            decisions[d] += 1
        s = (r.get("scene") or "").strip()
        if s and s != "unknown":
            scenes[s] += 1
        m = (r.get("wedding_moment") or "").strip()
        if m:
            moments[m] += 1
        cr = (r.get("cull_reason") or "").strip()
        if cr and d == "cull":
            cull_rs[cr] += 1
        sf = r.get("score_final")
        try:
            sf_n = float(sf)
            if not math.isnan(sf_n):
                score_acc.append(sf_n)
        except (TypeError, ValueError):
            pass
        if str(r.get("rubric_human_labeled") or "").lower() in ("true", "1"):
            human_n += 1
    n_keep  = decisions.get("keep", 0)
    n_maybe = decisions.get("maybe", 0)
    n_cull  = decisions.get("cull", 0)
    keep_ratio = (n_keep / n_total) if n_total else 0.0
    score_median = _median(score_acc) if score_acc else None
    return {
        "n_total":         n_total,
        "n_keep":          n_keep,
        "n_maybe":         n_maybe,
        "n_cull":          n_cull,
        "keep_ratio":      keep_ratio,
        "score_median":    score_median,
        "n_with_human":    human_n,
        "scenes_top":      scenes.most_common(5),
        "moments_top":     moments.most_common(5),
        "cull_reasons_top": cull_rs.most_common(5),
    }


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2


def pick_best_n(rows: list[dict], n: int = 5) -> list[dict]:
    """Top-N keep rows by score_final."""
    keeps = [r for r in rows if (r.get("decision") or "") == "keep"]
    def _key(r):
        try: return -float(r.get("score_final") or 0)
        except (TypeError, ValueError): return 0
    return sorted(keeps, key=_key)[:n]


def pick_inconsistencies(rows: list[dict], n: int = 3) -> list[dict]:
    """Best-effort "watch out for these" picks.

    Two heuristics, in order of preference:
      1. rubric_human_labeled disagrees with the model decision
         (e.g. human said keep but score_final < 0.5, or vice versa)
      2. score_final right at the keep/maybe threshold (≈ 0.65 ± 0.05)
         — these are the closest calls the model made.
    """
    flagged = []
    for r in rows:
        sf = r.get("score_final")
        try: sf_n = float(sf)
        except (TypeError, ValueError): continue
        d = (r.get("decision") or "").strip()
        # H1: human-labeled but mismatched against decision band
        if str(r.get("rubric_human_labeled") or "").lower() in ("true", "1"):
            if d == "keep" and sf_n < 0.55:
                flagged.append((0, r))
                continue
            if d == "cull" and sf_n > 0.55:
                flagged.append((0, r))
                continue
        # H2: borderline against the typical keep threshold
        delta = abs(sf_n - 0.65)
        if delta < 0.06:
            flagged.append((1 + delta, r))
    flagged.sort(key=lambda kv: kv[0])
    return [r for _, r in flagged[:n]]


# ----------------------------------------------------------------------
# Image inlining — the PDF needs to stand on its own, so we embed
# thumbnails as data: URIs rather than referencing local file paths
# (which Chrome would resolve via file:// but which break the moment
# the user emails the .pdf to the client).
# ----------------------------------------------------------------------


def inline_thumb(
    image_path: Path | None,
    *,
    max_side: int = 360,
) -> str:
    """Return a data: URI for the given image, downsized to roughly
    ``max_side`` on the long edge.  Falls back to an empty data URI
    when the image is unreadable so the layout still composes.
    """
    if image_path is None or not image_path.is_file():
        return _empty_data_uri()
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        # Pillow is a core dep but tests run minimal envs occasionally.
        return _empty_data_uri()
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            from io import BytesIO
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=82, optimize=True)
            data = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{data}"
    except Exception:
        return _empty_data_uri()


def _empty_data_uri() -> str:
    """A 1×1 transparent PNG — placeholder when a thumb can't be read."""
    return (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "AAIAAAoAAv/lxKUAAAAASUVORK5CYII="
    )


# ----------------------------------------------------------------------
# HTML rendering — each "page" returns a fragment we concatenate
# inside the final document.  The shared print stylesheet (page
# breaks, A4 sizing) lives in build_executive_html below.
# ----------------------------------------------------------------------


def render_cover_html(
    *,
    photographer: str,
    client: str,
    event: str,
    event_date: str,
    n_total: int,
    n_keep: int,
    keep_ratio: float,
) -> str:
    """Render the cover page — the visual moment that sells the
    whole experience to the client opening the file.
    """
    # When the cover fields are blank (CI smoke), the cover should
    # still render — degrade to the photographer's brand without the
    # personalised hero.
    title = event or "PixCull Delivery Report"
    sub   = client or "client name placeholder"
    by    = photographer or "—"
    date_str = event_date or datetime.now().strftime("%Y-%m-%d")
    ratio_pct = round(100 * keep_ratio) if n_total else 0
    return f"""
<section class="exec-cover">
  <div class="exec-cover-bar">
    <span class="exec-cover-mark">
      <svg viewBox="0 0 80 32" width="100" height="40" aria-hidden="true">
        <defs>
          <linearGradient id="brandGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%"  stop-color="{BRAND_INDIGO}"/>
            <stop offset="55%" stop-color="{BRAND_VIOLET}"/>
            <stop offset="100%" stop-color="{BRAND_PINK}"/>
          </linearGradient>
        </defs>
        <circle cx="10" cy="16" r="3"   fill="#cbd5e1" opacity="0.55"/>
        <circle cx="22" cy="20" r="3.2" fill="#cbd5e1" opacity="0.65"/>
        <circle cx="34" cy="14" r="3.6" fill="#cbd5e1" opacity="0.75"/>
        <circle cx="46" cy="22" r="3.2" fill="#cbd5e1" opacity="0.65"/>
        <circle cx="62" cy="16" r="9"   fill="url(#brandGrad)"/>
      </svg>
    </span>
    <span class="exec-cover-wordmark">Pix<b>Cull</b></span>
    <span class="exec-cover-meta">delivery report</span>
  </div>

  <div class="exec-cover-hero">
    <div class="exec-cover-eyebrow">{_e(by)} · 摄影作品交付</div>
    <h1 class="exec-cover-title">{_e(title)}</h1>
    <div class="exec-cover-sub">{_e(sub)}</div>
    <div class="exec-cover-date">{_e(date_str)}</div>
  </div>

  <div class="exec-cover-keynums">
    <div class="exec-keynum">
      <div class="exec-keynum-v">{n_total}</div>
      <div class="exec-keynum-l">提交张数</div>
    </div>
    <div class="exec-keynum">
      <div class="exec-keynum-v">{n_keep}</div>
      <div class="exec-keynum-l">入选张数</div>
    </div>
    <div class="exec-keynum">
      <div class="exec-keynum-v">{ratio_pct}<span class="exec-keynum-suf">%</span></div>
      <div class="exec-keynum-l">入选率</div>
    </div>
  </div>

  <div class="exec-cover-foot">
    本报告由 PixCull 本地生成 · 照片永远不出本机
  </div>
</section>
""".strip()


def render_toc_html(sections: list[tuple[str, str]]) -> str:
    """``sections`` = [(anchor_id, label), ...]."""
    items = "\n".join(
        f'<li><a href="#{anchor}"><span>{_e(label)}</span>'
        f'<span class="exec-toc-dot"></span></a></li>'
        for anchor, label in sections
    )
    return f"""
<section class="exec-toc">
  <h2 class="exec-h2">目录</h2>
  <ol class="exec-toc-list">
    {items}
  </ol>
  <div class="exec-toc-foot">报告由 PixCull · 本地 AI 选片 生成</div>
</section>
""".strip()


def render_dashboard_html(dash: dict) -> str:
    """Strava-annual-review-flavoured key-numbers dashboard."""
    n_total = dash["n_total"]
    n_keep  = dash["n_keep"]
    n_maybe = dash["n_maybe"]
    n_cull  = dash["n_cull"]
    ratio_pct = round(100 * dash["keep_ratio"]) if n_total else 0
    score_med = dash["score_median"]
    score_med_pct = (round(score_med * 100) if score_med is not None else None)
    scenes   = dash.get("scenes_top") or []
    moments  = dash.get("moments_top") or []
    human_n  = dash.get("n_with_human") or 0

    top_scene = scenes[0][0] if scenes else "—"
    top_scene_n = scenes[0][1] if scenes else 0
    top_moment = moments[0][0] if moments else "—"
    top_moment_n = moments[0][1] if moments else 0

    scene_chips = "".join(
        f'<span class="exec-chip">{_e(s)} <b>{n}</b></span>'
        for s, n in scenes
    ) or '<span class="exec-chip exec-chip-empty">—</span>'

    return f"""
<section class="exec-page" id="dashboard">
  <h2 class="exec-h2">关键数据</h2>
  <p class="exec-sub">一张 dashboard 把整场拍摄的结构看完。</p>

  <div class="exec-dash-grid">
    <div class="exec-card exec-card-hero">
      <div class="exec-card-eyebrow">入选率</div>
      <div class="exec-card-big">{ratio_pct}<span class="exec-card-suf">%</span></div>
      <div class="exec-card-foot">
        {n_keep} 张 keep / {n_total} 张原片
      </div>
    </div>

    <div class="exec-card">
      <div class="exec-card-eyebrow">提交张数</div>
      <div class="exec-card-mid">{n_total}</div>
      <div class="exec-card-foot">本场原片总量</div>
    </div>

    <div class="exec-card">
      <div class="exec-card-eyebrow">需复核</div>
      <div class="exec-card-mid">{n_maybe}</div>
      <div class="exec-card-foot">maybe 桶</div>
    </div>

    <div class="exec-card">
      <div class="exec-card-eyebrow">已剔除</div>
      <div class="exec-card-mid">{n_cull}</div>
      <div class="exec-card-foot">cull 桶</div>
    </div>

    <div class="exec-card">
      <div class="exec-card-eyebrow">综合分中位</div>
      <div class="exec-card-mid">{
        f'{score_med_pct}<span class="exec-card-suf">%</span>'
        if score_med_pct is not None else '—'
      }</div>
      <div class="exec-card-foot">score_final · 0..1</div>
    </div>

    <div class="exec-card">
      <div class="exec-card-eyebrow">人工标注</div>
      <div class="exec-card-mid">{human_n}</div>
      <div class="exec-card-foot">摄影师亲自标的 rubric 行</div>
    </div>

    <div class="exec-card exec-card-wide">
      <div class="exec-card-eyebrow">主要场景</div>
      <div class="exec-card-row exec-card-row-chips">{scene_chips}</div>
      <div class="exec-card-foot">
        最多: <b>{_e(top_scene)}</b> ({top_scene_n}) ·
        婚礼瞬间最多: <b>{_e(top_moment)}</b> ({top_moment_n})
      </div>
    </div>
  </div>
</section>
""".strip()


def render_wall_html(
    title: str,
    cards: list[dict],
    sub: str = "",
    *,
    anchor: str = "",
    empty_msg: str = "本场没有匹配的照片。",
) -> str:
    """A page-break-before wall of up to 5 thumbnails + captions.

    ``cards`` shape: [{thumb: <data uri>, fn: str, badge?: str,
                       score?: float | None, note?: str}, ...]
    """
    if not cards:
        return f"""
<section class="exec-page"{(' id="' + anchor + '"') if anchor else ''}>
  <h2 class="exec-h2">{_e(title)}</h2>
  {f'<p class="exec-sub">{_e(sub)}</p>' if sub else ""}
  <div class="exec-empty">{_e(empty_msg)}</div>
</section>
""".strip()
    figs = "\n".join(_render_wall_card(c) for c in cards)
    return f"""
<section class="exec-page"{(' id="' + anchor + '"') if anchor else ''}>
  <h2 class="exec-h2">{_e(title)}</h2>
  {f'<p class="exec-sub">{_e(sub)}</p>' if sub else ""}
  <div class="exec-wall">{figs}</div>
</section>
""".strip()


def _render_wall_card(c: dict) -> str:
    thumb = c.get("thumb") or _empty_data_uri()
    fn    = c.get("fn") or ""
    note  = c.get("note") or ""
    badge = c.get("badge") or ""
    sf    = c.get("score")
    score_chip = ""
    if sf is not None:
        try:
            sf_n = float(sf)
            score_chip = (
                f'<span class="exec-wall-score">'
                f'综合分 <b>{round(sf_n * 100)}%</b></span>'
            )
        except (TypeError, ValueError):
            pass
    badge_html = (
        f'<span class="exec-wall-badge">{_e(badge)}</span>' if badge else ""
    )
    note_html = (
        f'<div class="exec-wall-note">{_e(note)}</div>' if note else ""
    )
    return f"""
<figure class="exec-wall-card">
  <div class="exec-wall-thumb-wrap">
    <img class="exec-wall-thumb" src="{thumb}" alt="{_e(fn)}"/>
    {badge_html}
  </div>
  <figcaption class="exec-wall-cap">
    <div class="exec-wall-fn">{_e(fn)}</div>
    {score_chip}
    {note_html}
  </figcaption>
</figure>
""".strip()


def render_cull_bars_html(cull_top: list[tuple[str, int]]) -> str:
    """Horizontal-bar visual of the top cull reasons.

    Visually similar to /share's "top cull reasons" — restated here
    because the PDF audience is a *client*, not the photographer,
    so the framing is "why some shots didn't make the cut" rather
    than "your culling habits".
    """
    if not cull_top:
        return f"""
<section class="exec-page" id="cull-reasons">
  <h2 class="exec-h2">为什么有些照片没入选</h2>
  <p class="exec-sub">本场没有标注 cull 原因 — 全部入选 / 待复核。</p>
</section>
""".strip()
    max_n = max(n for _, n in cull_top) or 1
    rows = []
    cull_zh = {
        "focus": "对焦不准",
        "blur":  "模糊抖动",
        "blink": "闭眼 / 表情",
        "exposure": "曝光",
        "composition": "构图",
        "duplicate": "重复",
        "other": "其他",
    }
    for reason, n in cull_top:
        label = cull_zh.get(reason, reason)
        pct = round(100 * n / max_n)
        rows.append(f"""
<div class="exec-bar-row">
  <div class="exec-bar-lab">{_e(label)}</div>
  <div class="exec-bar-track">
    <div class="exec-bar-fill" style="width:{pct}%;"></div>
  </div>
  <div class="exec-bar-n">{n} 张</div>
</div>
""".strip())
    return f"""
<section class="exec-page" id="cull-reasons">
  <h2 class="exec-h2">为什么有些照片没入选</h2>
  <p class="exec-sub">
    本场 cull 桶中,出现频率最高的 5 个原因。
  </p>
  <div class="exec-bars">{chr(10).join(rows)}</div>
</section>
""".strip()


# ----------------------------------------------------------------------
# Top-level entry point
# ----------------------------------------------------------------------


def build_executive_html(
    *,
    cover: dict,
    dashboard: dict,
    best_cards: list[dict],
    inconsistency_cards: list[dict],
    cull_top: list[tuple[str, int]],
    body_html: str,
    run_id: str,
) -> str:
    """Assemble the full executive HTML.

    ``cover`` and ``dashboard`` come from the caller (cli_audit).
    ``body_html`` is the existing markdown-rendered audit body
    (the v0.4 P2 (4/4) HTML).  We wrap it all in a single document
    with print-first CSS.
    """
    cover_html = render_cover_html(
        photographer=cover.get("photographer", ""),
        client=cover.get("client", ""),
        event=cover.get("event", ""),
        event_date=cover.get("event_date", ""),
        n_total=dashboard["n_total"],
        n_keep=dashboard["n_keep"],
        keep_ratio=dashboard["keep_ratio"],
    )
    toc = render_toc_html([
        ("dashboard",     "关键数据 · 一页 dashboard"),
        ("best-5",        "最佳 5 张 · 本场代表作"),
        ("inconsistency", "需要复核的 3 张 · 模型边界"),
        ("cull-reasons",  "未入选原因 · top 5"),
        ("audit",         "技术质量审计 · 场景 / 人脸 / EXIF"),
    ])
    dashboard_html  = render_dashboard_html(dashboard)
    best_wall       = render_wall_html(
        "最佳 5 张",
        best_cards,
        sub="按综合分排序 — 本场最值得展示的代表作。",
        anchor="best-5",
        empty_msg="本场没有 keep 行,无法挑选最佳 5 张。",
    )
    incon_wall      = render_wall_html(
        "需要复核的 3 张",
        inconsistency_cards,
        sub="模型给出的分数与摄影师判定之间存在张力 — 值得人工再看一眼。",
        anchor="inconsistency",
        empty_msg="本场没有标注上的不一致 — 选片信号干净。",
    )
    cull_bars       = render_cull_bars_html(cull_top)
    css             = _print_css()
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8"/>
  <title>PixCull Executive Summary · {_e(run_id)}</title>
  <style>{css}</style>
</head>
<body class="exec-body">
  {cover_html}
  {toc}
  {dashboard_html}
  {best_wall}
  {incon_wall}
  {cull_bars}
  <section class="exec-page" id="audit">
    <h2 class="exec-h2">技术质量审计</h2>
    <p class="exec-sub">下列各小节由 cli_audit 本地计算 — 无任何照片数据离机。</p>
    <div class="exec-audit-body">{body_html}</div>
  </section>
</body>
</html>"""


def _print_css() -> str:
    """Single concatenated print stylesheet — page breaks, brand,
    grid math.  Inlined so the PDF is fully self-contained.
    """
    return f"""
@page {{ size: A4; margin: 16mm 14mm 16mm; }}
* {{ box-sizing: border-box; }}
.exec-body {{
  margin: 0;
  font-family: {SANS_STACK};
  font-size: 10.5pt;
  line-height: 1.55;
  color: #1a1d24;
  background: #ffffff;
}}
@media print {{
  .exec-body {{ background: white !important; }}
  .exec-page, .exec-cover, .exec-toc {{ page-break-before: always; }}
  .exec-cover {{ page-break-before: avoid; }}
  .exec-card, .exec-wall-card, .exec-bar-row {{ page-break-inside: avoid; }}
  h1, h2, h3 {{ page-break-after: avoid; }}
}}

/* Cover page ============================================== */
.exec-cover {{
  min-height: 265mm;             /* A4 less margins */
  display: flex; flex-direction: column;
  padding: 4mm 0;
  position: relative;
}}
.exec-cover-bar {{
  display: flex; align-items: center; gap: 10px;
  padding-bottom: 14mm;
  border-bottom: 1px solid #e5e7eb;
}}
.exec-cover-wordmark {{
  font-weight: 700; font-size: 14pt; letter-spacing: -0.02em;
}}
.exec-cover-wordmark b {{
  background: {BRAND_GRADIENT};
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}}
.exec-cover-meta {{
  margin-left: auto; font-size: 9.5pt;
  color: #6b7280; text-transform: uppercase; letter-spacing: 0.06em;
}}
.exec-cover-hero {{
  flex: 1; display: flex; flex-direction: column; justify-content: center;
  padding: 12mm 4mm 6mm;
}}
.exec-cover-eyebrow {{
  font-size: 10pt; letter-spacing: 0.16em;
  text-transform: uppercase; color: #6b7280;
  margin-bottom: 6mm;
}}
.exec-cover-title {{
  font-family: {SERIF_STACK};
  font-size: 44pt; line-height: 1.05;
  font-weight: 600; letter-spacing: -0.015em;
  margin: 0 0 6mm;
  background: {BRAND_GRADIENT};
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}}
.exec-cover-sub {{
  font-size: 16pt; color: #1a1d24; margin-bottom: 4mm;
  font-weight: 500;
}}
.exec-cover-date {{
  font-size: 11pt; color: #6b7280;
}}
.exec-cover-keynums {{
  display: flex; gap: 8mm;
  padding: 8mm 4mm 0;
  border-top: 1px solid #e5e7eb;
  margin-top: 4mm;
}}
.exec-keynum-v {{
  font-family: {SERIF_STACK};
  font-size: 32pt; font-weight: 600;
  background: {BRAND_GRADIENT};
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
  line-height: 1;
}}
.exec-keynum-suf {{ font-size: 18pt; }}
.exec-keynum-l {{
  font-size: 9pt; color: #6b7280;
  text-transform: uppercase; letter-spacing: 0.10em;
  margin-top: 2mm;
}}
.exec-cover-foot {{
  position: absolute; left: 0; right: 0; bottom: 0;
  font-size: 8.5pt; color: #9ca3af;
}}

/* ToC ============================================== */
.exec-toc {{
  padding: 6mm 0;
}}
.exec-toc-list {{
  list-style: none; margin: 0; padding: 0;
  counter-reset: tocCounter;
}}
.exec-toc-list li {{
  counter-increment: tocCounter;
  margin: 8mm 0;
  border-bottom: 1px dashed #d1d5db;
  padding-bottom: 4mm;
}}
.exec-toc-list li a {{
  display: flex; align-items: baseline; gap: 6mm;
  text-decoration: none; color: #1a1d24;
  font-size: 13pt;
}}
.exec-toc-list li a::before {{
  content: counter(tocCounter, decimal-leading-zero);
  font-family: {SERIF_STACK};
  font-size: 18pt; font-weight: 600;
  background: {BRAND_GRADIENT};
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
  min-width: 18mm;
}}
.exec-toc-list li a > span:first-of-type {{ flex: 1; }}
.exec-toc-foot {{
  margin-top: 12mm;
  font-size: 8.5pt; color: #9ca3af;
}}

/* Section heads ============================================== */
.exec-page {{ padding: 4mm 0; }}
.exec-h2 {{
  font-family: {SERIF_STACK};
  font-size: 24pt; font-weight: 600;
  letter-spacing: -0.01em;
  margin: 0 0 2mm;
  background: {BRAND_GRADIENT};
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}}
.exec-sub {{
  font-size: 10pt; color: #6b7280;
  margin: 0 0 6mm;
}}

/* Dashboard grid ============================================== */
.exec-dash-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 4mm;
}}
.exec-card {{
  background: #f8f9fb;
  border: 1px solid #eef0f4;
  border-radius: 4mm;
  padding: 6mm;
  position: relative;
  overflow: hidden;
}}
.exec-card::before {{
  content: "";
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 2mm;
  background: {BRAND_GRADIENT};
  opacity: 0.55;
}}
.exec-card-hero {{
  grid-column: span 2;
  background: linear-gradient(135deg,
    rgba(110, 86, 207, 0.06) 0%,
    rgba(232, 72, 153, 0.06) 100%);
  border-color: rgba(110, 86, 207, 0.25);
}}
.exec-card-wide {{ grid-column: span 3; }}
.exec-card-eyebrow {{
  font-size: 8.5pt; color: #6b7280;
  text-transform: uppercase; letter-spacing: 0.12em;
  margin-bottom: 3mm;
}}
.exec-card-big {{
  font-family: {SERIF_STACK};
  font-size: 56pt; font-weight: 600; line-height: 1;
  background: {BRAND_GRADIENT};
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}}
.exec-card-mid {{
  font-family: {SERIF_STACK};
  font-size: 28pt; font-weight: 600; line-height: 1.1;
  color: #1a1d24;
}}
.exec-card-suf {{ font-size: 50%; opacity: 0.6; margin-left: 1mm; }}
.exec-card-foot {{
  margin-top: 3mm; font-size: 9pt; color: #6b7280;
}}
.exec-card-row-chips {{
  display: flex; flex-wrap: wrap; gap: 2mm; margin-top: 1mm;
}}
.exec-chip {{
  background: white;
  border: 1px solid #e5e7eb;
  padding: 1mm 3mm;
  border-radius: 999px;
  font-size: 9pt;
}}
.exec-chip b {{ color: {BRAND_VIOLET}; }}
.exec-chip-empty {{ color: #9ca3af; }}

/* Thumbnail walls ============================================== */
.exec-wall {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr 1fr;
  gap: 3mm;
}}
.exec-wall-card {{
  margin: 0;
  background: white;
  border: 1px solid #eef0f4;
  border-radius: 3mm;
  overflow: hidden;
}}
.exec-wall-thumb-wrap {{
  position: relative;
  background: #0f0f12;
  aspect-ratio: 3 / 2;
}}
.exec-wall-thumb {{
  width: 100%; height: 100%; object-fit: cover; display: block;
}}
.exec-wall-badge {{
  position: absolute; top: 2mm; left: 2mm;
  background: {BRAND_GRADIENT};
  color: white;
  font-size: 7.5pt; font-weight: 700;
  padding: 0.5mm 2mm;
  border-radius: 999px;
  letter-spacing: 0.04em;
}}
.exec-wall-cap {{ padding: 2.5mm 3mm 3mm; }}
.exec-wall-fn {{
  font-family: ui-monospace, Menlo, monospace;
  font-size: 7.5pt; color: #1a1d24;
  word-break: break-all;
}}
.exec-wall-score {{
  display: inline-block; margin-top: 1.5mm;
  font-size: 8pt; color: #6b7280;
}}
.exec-wall-score b {{ color: {BRAND_VIOLET}; }}
.exec-wall-note {{
  margin-top: 1.5mm; font-size: 8pt; color: #6b7280;
  line-height: 1.45;
}}
.exec-empty {{
  margin: 8mm 0;
  padding: 8mm; border-radius: 4mm;
  background: #f8f9fb; border: 1px dashed #d1d5db;
  text-align: center; color: #6b7280; font-size: 10pt;
}}

/* Cull-reason bars ============================================== */
.exec-bars {{
  display: flex; flex-direction: column; gap: 4mm; margin-top: 4mm;
}}
.exec-bar-row {{
  display: grid; grid-template-columns: 32mm 1fr 22mm;
  gap: 4mm; align-items: center;
}}
.exec-bar-lab {{ font-size: 10pt; font-weight: 500; }}
.exec-bar-track {{
  height: 5mm; background: #eef0f4; border-radius: 999px;
  overflow: hidden;
}}
.exec-bar-fill {{
  height: 100%; background: {BRAND_GRADIENT}; border-radius: 999px;
}}
.exec-bar-n {{
  font-size: 9.5pt; color: #6b7280; text-align: right;
}}

/* Embedded audit body ============================================== */
.exec-audit-body table {{
  width: 100%; border-collapse: collapse; font-size: 9.5pt;
  margin: 2mm 0 4mm;
}}
.exec-audit-body th, .exec-audit-body td {{
  padding: 2mm 3mm; border-bottom: 1px solid #e5e7eb;
  text-align: left;
}}
.exec-audit-body th {{
  background: #f8f9fb; color: #6b7280;
  text-transform: uppercase; letter-spacing: 0.06em;
  font-size: 8pt; font-weight: 600;
}}
.exec-audit-body h1 {{ display: none; }}
.exec-audit-body h2 {{
  font-family: {SERIF_STACK};
  font-size: 14pt; margin: 8mm 0 2mm;
  color: #1a1d24;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 2mm;
}}
.exec-audit-body code {{
  font-family: ui-monospace, Menlo, monospace;
  font-size: 9pt; padding: 0.5mm 1.5mm;
  background: #f0f2f5; border-radius: 1.5mm;
  color: {BRAND_INDIGO};
}}
""".strip()


def _e(s) -> str:
    """HTML-escape a value, coercing None / numbers / lists to strings."""
    if s is None:
        return ""
    return _html.escape(str(s), quote=True)


__all__ = [
    "build_executive_html",
    "compute_dashboard",
    "inline_thumb",
    "pick_best_n",
    "pick_inconsistencies",
    "render_cover_html",
    "render_dashboard_html",
    "render_toc_html",
    "render_wall_html",
    "render_cull_bars_html",
]
