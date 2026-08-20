"""v2.53 — a self-contained page for judging a model against your own eye.

Built ad-hoc to review 18 frames M3 rescued from a hard cull, and kept
because it did the one thing this project could not otherwise do: turn
"the model disagrees with the rules" into a number somebody can act on.
The owner went through it in a few minutes and agreed with M3 on 17 of
18 — the first genuinely independent labels this repo has ever had, and
the thing that promoted the eval from INVALID to usable.

Design constraints, each one learned:

**The photos never leave the machine.** Thumbnails are embedded as data
URIs in a local HTML file. Reviewing your own client work must not
require uploading it anywhere, including to us.

**The verdicts are written to disk, not just the clipboard.** The first
version only offered "copy result", so closing the tab lost the work.
Ten minutes of a photographer's judgement is the scarcest input this
whole system has; it does not get to live in a paste buffer.

**One question per card.** Not a rating, not a form — "was the model
right about this frame". A reviewer who has to think about scale
calibration is no longer looking at the photograph.
"""

from __future__ import annotations

import base64
import html
import io
import json
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

#: Long edge for the embedded preview. Big enough to judge a moment on,
#: small enough that 200 of them stay a file you can open.
THUMB_PX = 760
THUMB_QUALITY = 82

_AXES = (("technical", "技术"), ("subject", "主体"), ("composition", "构图"),
         ("light", "光线"), ("moment", "时刻"), ("aesthetic", "美感"))


def thumbnail_data_uri(path: Path, px: int = THUMB_PX) -> str:
    """Embed one photo as a JPEG data URI.

    ``draft()`` before ``thumbnail()`` lets the JPEG decoder skip most of
    the file: a 45 MP RAW-derived JPEG decodes at 1/8 scale in a fraction
    of the time, and the result is downscaled anyway.
    """
    from PIL import Image, ImageOps
    im = Image.open(path)
    im.draft("RGB", (px * 2, px * 2))
    # v2.56.2 — `io/loader.py` says "every code path now goes through
    # ImageOps.exif_transpose" (V16.1). This module opened PIL directly
    # and was not one of them: 67 of 150 frames in a blind labelling pass
    # were shown to the reviewer lying on their side. The aggregate cull
    # rate happened not to move (6.0% sideways vs 7.2% upright), so
    # nothing in the numbers would ever have revealed it — I found it by
    # looking at the photographs.
    im = ImageOps.exif_transpose(im)
    im = im.convert("RGB")
    im.thumbnail((px, px), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=THUMB_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _blind_card(i: int, it: dict[str, Any]) -> str:
    """A photograph and one question. Nothing else on the card.

    v2.56 — every circular label set this project has produced was
    formed by a person looking at a decision and agreeing with it. Four
    times, in four disguises: labels copied from the rule stack; a
    sample drawn where the systems disagreed; a sample with no `cull`
    ground truth; and a shoot whose `manual_label` WAS the pipeline's
    output. Each was caught after the fact by a guard written for the
    previous one.

    A blind card cannot produce those labels. No decision, no rationale,
    no axis scores, no flags, no filename hint of what a detector
    thought — because a reviewer who can see the answer is no longer an
    independent source of it. This is the only fix in the family that is
    structural rather than a check applied afterwards.
    """
    # v2.63.1 — the QUESTION is configurable; the blindness is not.
    #
    # The 60-frame `maybe` batch asks "is this worth a second look after
    # a crop", and the buttons still read "留下 · keep / 删掉 · cull"
    # because they were hardcoded. The lede explained the
    # reinterpretation and the buttons contradicted it — the reviewer
    # would have answered a different question from the one recorded.
    # That is v2.53.1's bug wearing a new hat, and the fix is the same:
    # the answer travels with the card.
    yes_v = html.escape(str(it.get("yes_value") or "keep"))
    no_v = html.escape(str(it.get("no_value") or "cull"))
    yes_t = html.escape(str(it.get("yes") or "留下 · keep"))
    no_t = html.escape(str(it.get("no") or "删掉 · cull"))
    return f'''<article class="card blind" data-fn="{html.escape(it['fn'])}"
         data-yes="{yes_v}" data-no="{no_v}">
  <img src="{thumbnail_data_uri(Path(it['path']))}" alt="">
  <div class="meta">
    <div class="hd"><code>#{i + 1}</code></div>
    <div class="judge">
      <button class="ok"  onclick="mark({i},1)">{yes_t}</button>
      <button class="bad" onclick="mark({i},0)">{no_t}</button>
      <span class="mk" id="mk{i}"></span>
    </div>
  </div>
</article>'''


def _card(i: int, it: dict[str, Any]) -> str:
    axes = it.get("axes") or {}
    stars = "".join(
        f'<div class="ax"><span>{zh}</span><b>{"★" * int(axes.get(k) or 0)}'
        f'<i>{"☆" * (5 - int(axes.get(k) or 0))}</i></b></div>'
        for k, zh in _AXES)
    note = html.escape(str(it.get("note") or ""))
    # v2.53.1 — the answer differs per card, so it travels with the card.
    #
    # The first batch was entirely cull→keep, so one fixed pair of labels
    # worked and I wrote it that way. The second batch is 88% keep→maybe,
    # where "M3 was right" means `maybe` — and a page-level pair silently
    # recorded `keep`/`cull` for every one of them. A whole review pass
    # would have produced labels for a question nobody was asked.
    yes_v = html.escape(str(it.get("yes_value") or it.get("b") or "keep"))
    no_v = html.escape(str(it.get("no_value") or it.get("a") or "cull"))
    return f'''<article class="card" data-fn="{html.escape(it['fn'])}"
         data-yes="{yes_v}" data-no="{no_v}">
  <img src="{thumbnail_data_uri(Path(it['path']))}" alt="">
  <div class="meta">
    <div class="hd"><code>{html.escape(it['fn'])}</code>
      <span class="scene">{html.escape(str(it.get('scene') or ''))}</span></div>
    <div class="verdicts">
      <span class="v a">{html.escape(str(it.get('a_label', '规则')))}
        <b>{html.escape(str(it.get('a', '')))}</b></span>
      <span class="arrow">→</span>
      <span class="v b">{html.escape(str(it.get('b_label', 'M3')))}
        <b>{html.escape(str(it.get('b', '')))}</b></span>
      {f'<span class="flag">{note}</span>' if note else ''}
    </div>
    <p class="why">{html.escape(str(it.get('why') or ''))}</p>
    <div class="axes">{stars}</div>
    <div class="judge">
      <button class="ok"  onclick="mark({i},1)">{html.escape(str(it.get('yes') or f"M3 对了 · {it.get('b','')}"))}</button>
      <button class="bad" onclick="mark({i},0)">{html.escape(str(it.get('no') or f"规则对了 · {it.get('a','')}"))}</button>
      <span class="mk" id="mk{i}"></span>
    </div>
  </div>
</article>'''


_CSS = """
:root{--bg:#faf8f5;--ink:#1a1614;--dim:#7d746b;--line:#e0d9d0;--card:#fffdfa;
--ok:#3f6b4e;--bad:#a8521f;--brass:#9c6f33}
@media(prefers-color-scheme:dark){:root{--bg:#141110;--ink:#ece6de;--dim:#8a8177;
--line:#2c2724;--card:#1c1817;--ok:#7fb693;--bad:#dd8b57;--brass:#d3a464}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,
"PingFang SC",sans-serif;padding:28px 20px 84px}
header{max-width:1000px;margin:0 auto 26px;border-bottom:1.5px solid var(--ink);
padding-bottom:14px}
h1{font:600 25px/1.3 Charter,"Songti SC",serif;margin:0 0 8px}
.lede{color:var(--dim);max-width:70ch;margin:0}.lede b{color:var(--ink)}
.card{max-width:1000px;margin:0 auto 20px;background:var(--card);
border:1px solid var(--line);border-radius:9px;overflow:hidden;
display:grid;grid-template-columns:minmax(0,420px) 1fr}
@media(max-width:820px){.card{grid-template-columns:1fr}}
/* v2.57 — fixed aspect, not `height:100%`. Once EXIF orientation was
   honoured, portrait frames rendered at their true aspect and stretched
   the card to ~630px with a void beside the text; the bug had been
   hiding the layout problem.
   `max-height` did not fix it: `height:100%` inside an auto-height grid
   row resolves to auto, so the row was sized by the image's intrinsic
   height and the cap never bound. Pinning the ratio makes every card the
   same height and lets `cover` centre-crop a tall frame. */
.card img{width:100%;aspect-ratio:4/3;height:auto;object-fit:cover;
display:block;background:#000}
.meta{padding:16px 18px;display:flex;flex-direction:column;gap:11px}
.hd{display:flex;gap:10px;align-items:baseline}
.hd code{font:12px ui-monospace,monospace;color:var(--brass)}
.scene{font-size:11px;color:var(--dim);border:1px solid var(--line);
border-radius:3px;padding:1px 6px}
.verdicts{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}
.v{padding:3px 8px;border-radius:4px;border:1px solid var(--line)}
.v.a b{color:var(--bad)}.v.b b{color:var(--ok)}
.arrow{color:var(--dim)}
.flag{font-size:11.5px;color:var(--dim)}
.why{margin:0;font-size:14px;line-height:1.6}
.axes{display:grid;grid-template-columns:repeat(3,1fr);gap:4px 14px;
font-size:11.5px;color:var(--dim);margin-top:auto}
.ax{display:flex;justify-content:space-between}
.ax b{color:var(--brass);letter-spacing:1px}.ax i{opacity:.3;font-style:normal}
.judge{display:flex;gap:8px;align-items:center;padding-top:10px;
border-top:1px solid var(--line)}
button{font:13px/1 inherit;padding:8px 13px;border-radius:5px;cursor:pointer;
border:1px solid var(--line);background:transparent;color:var(--ink)}
button.ok:hover{border-color:var(--ok);color:var(--ok)}
button.bad:hover{border-color:var(--bad);color:var(--bad)}
.mk{font-size:12.5px;font-weight:600}
.card.done-ok{border-color:var(--ok)}.card.done-bad{border-color:var(--bad)}
#bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);
border-top:1px solid var(--line);padding:11px 20px;display:flex;gap:14px;
align-items:center;justify-content:center;font-size:13px}
#hint{color:var(--dim);font-size:12px;max-width:52ch;line-height:1.45}
#pos{color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
#prog{flex:1;max-width:220px;height:4px;border-radius:2px;background:var(--line);
overflow:hidden}
#prog>i{display:block;height:100%;background:var(--brass);width:0;
transition:width .18s ease}
#keys{color:var(--dim);font-size:11.5px}
#keys kbd{border:1px solid var(--line);border-radius:3px;padding:0 4px;
font:11px ui-monospace,monospace;color:var(--ink)}
.card.cur{box-shadow:0 0 0 2px var(--brass)}
.card.blind{grid-template-columns:minmax(0,1fr) 210px}
.card.blind .meta{justify-content:space-between}
.card.blind .hd code{font-size:13px;color:var(--dim)}
.card.blind .judge{border-top:none;flex-direction:column;align-items:stretch;gap:9px}
.card.blind button{padding:13px}
#out{width:100%;max-width:1000px;margin:0 auto;font:12px ui-monospace,monospace;
white-space:pre-wrap;background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:14px;display:none;cursor:copy}
"""

# Verdicts are mirrored into localStorage on every click. The reviewer's
# judgement is the scarcest input this system has; a closed tab, a reload
# or a stray ⌘W must not cost them the pass they already did.
_JS = """
const N=%(n)d, KEY='pixcull-review-%(slug)s', FILE='%(slug)s-review.json';
const SELECTION=%(selection)s;
// v2.65 — the strata travel with the verdicts. A stratified sample
// whose weights live in a side file is a number waiting to be computed
// wrong: `m3 eval --labels` had no way to ask for them and silently
// produced an UNWEIGHTED figure from an over-sampled tail.
const STRATA=%(strata)s;
const R=JSON.parse(localStorage.getItem(KEY)||'{}');
function paint(i){
  const ok=R[i], c=document.querySelectorAll('.card')[i], m=document.getElementById('mk'+i);
  if(ok===undefined) return;
  c.classList.remove('done-ok','done-bad'); c.classList.add(ok?'done-ok':'done-bad');
  m.textContent=(ok?'\\u2713 ':'\\u2717 ')+(ok?c.dataset.yes:c.dataset.no);
  m.style.color=ok?'var(--ok)':'var(--bad)';
}
function tick(){
  const done=Object.keys(R).length;
  document.getElementById('cnt').textContent='\\u5df2\\u5224 '+done+' / '+N;
  const bar=document.querySelector('#prog>i');
  // v2.61.1 — a 1250-frame pass spans days. "312 / 1250" is a number;
  // a bar is a sense of whether this sitting is worth starting.
  if(bar) bar.style.width=(N?100*done/N:0)+'%%';
}
function mark(i,ok){
  R[i]=ok; localStorage.setItem(KEY,JSON.stringify(R)); paint(i); tick();
}
function payload(){
  const cards=document.querySelectorAll('.card');
  // `selection` rides along because a verdict file is read months later
  // by a program deciding whether these rows can rank two systems. Rows
  // picked BECAUSE the systems disagreed cannot: they sample the rule
  // stack only where it is weakest. Without this field the reader has to
  // guess, and the flattering guess is the wrong one.
  const out={reviewed_at:new Date().toISOString(),
             selection:SELECTION,strata:STRATA,verdicts:{}};
  cards.forEach((c,i)=>{ if(i in R) out.verdicts[c.dataset.fn]=R[i]?c.dataset.yes:c.dataset.no; });
  return out;
}
// The download is best-effort and the visible copy is the guarantee.
// v2.53.2: the anchor was never inserted into the document, which
// Firefox ignores outright, and a blob download from a file:// page is
// blocked in Safari regardless. Both fail SILENTLY — the reviewer saw
// the panel open, assumed a file had landed, and the eval command then
// said the path did not exist. Forty judgements sat unreachable in
// localStorage while the page looked like it had saved them.
function save(){
  const text=JSON.stringify(payload(),null,2), n=Object.keys(R).length;
  const o=document.getElementById('out'), h=document.getElementById('hint');
  o.style.display='block'; o.textContent=text;
  let ok=false;
  try{
    const url=URL.createObjectURL(
      new Blob([text],{type:'application/json'}));
    const a=document.createElement('a');
    a.href=url; a.download=FILE;
    document.body.appendChild(a);   // Firefox will not click a detached node
    a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),4000);
    ok=true;
  }catch(e){ ok=false; }
  if(navigator.clipboard) navigator.clipboard.writeText(text).catch(()=>{});
  h.textContent=(ok? '已下载 '+FILE+'(若浏览器拦截,下方内容已复制到剪贴板,'
                     +'粘贴存成该文件名即可)'
                   : '浏览器拦截了下载 — 下方内容已复制到剪贴板,'
                     +'粘贴存成 '+FILE)+' · 共 '+n+' 条';
  o.scrollIntoView({behavior:'smooth'});
}
// Triple-click selects one line; the reviewer needs all of it.
function selectAll(el){
  const r=document.createRange(); r.selectNodeContents(el);
  const s=getSelection(); s.removeAllRanges(); s.addRange(r);
}
// v2.61 — keyboard labelling. 150 blind frames yielded 10 cull
// positives, and the interval needs roughly 84 scoreable rows with both
// classes present; at this photographer's 6.7%% rate that is ~1250
// frames. Mouse-and-scroll does not get anyone to 1250. One keystroke
// per frame, and the page walks itself.
let CUR = 0;
function focusCard(i){
  const cards=document.querySelectorAll('.card');
  if(!cards.length) return;
  CUR = Math.max(0, Math.min(cards.length-1, i));
  cards.forEach((c,n)=>c.classList.toggle('cur', n===CUR));
  cards[CUR].scrollIntoView({block:'center', behavior:'smooth'});
  const bar=document.getElementById('pos');
  if(bar) bar.textContent = '第 '+(CUR+1)+' / '+cards.length;
}
function judge(ok){
  mark(CUR, ok);
  // Advance to the next UNJUDGED card, not merely the next one: coming
  // back to a half-finished batch should resume, not replay.
  const cards=document.querySelectorAll('.card');
  for(let d=1; d<=cards.length; d++){
    // NB `%%`: this block is fed through Python %%-formatting, so a bare
    // `%%` here silently breaks the whole page render.
    const n=(CUR+d)%%cards.length;
    if(!(n in R)){ focusCard(n); return; }
  }
  focusCard(Math.min(CUR+1, cards.length-1));
}
document.addEventListener('keydown', e=>{
  if(e.metaKey||e.ctrlKey||e.altKey) return;
  const k=e.key;
  if(k==='k'||k==='K'||k==='ArrowRight'){ e.preventDefault(); judge(1); }
  else if(k==='x'||k==='X'||k==='ArrowLeft'){ e.preventDefault(); judge(0); }
  else if(k==='j'||k==='J'||k==='ArrowDown'){ e.preventDefault(); focusCard(CUR+1); }
  else if(k==='ArrowUp'){ e.preventDefault(); focusCard(CUR-1); }
  else if(k==='u'||k==='U'){
    // Undo means "the one I just did", not "the one I am looking at".
    // Judging advances the focus, so by the time a mis-key registers the
    // cursor has already moved on and `delete R[CUR]` removes nothing.
    // Step back to the most recent judged card instead — this is what
    // makes fast keyboard labelling safe to do quickly.
    e.preventDefault();
    if(!(CUR in R)){
      for(let d=1; d<=N; d++){
        const n=(CUR-d+N)%%N;
        if(n in R){ focusCard(n); break; }
      }
    }
    delete R[CUR];
    localStorage.setItem(KEY,JSON.stringify(R));
    const c=document.querySelectorAll('.card')[CUR];
    c.classList.remove('done-ok','done-bad');
    document.getElementById('mk'+CUR).textContent='';
    document.getElementById('cnt').textContent='\u5df2\u5224 '+Object.keys(R).length+' / '+N;
  }
  else if(k==='s'||k==='S'){ e.preventDefault(); save(); }
});
window.addEventListener('DOMContentLoaded',()=>{
  for(const i in R) paint(i);
  tick();
  let first=0; while(first<N && (first in R)) first++;
  focusCard(Math.min(first, N-1));
});
"""


def render(items: Sequence[dict[str, Any]], *, title: str, lede: str,
           slug: str, yes_key: str = "b", no_key: str = "a",
           selection: str = "disagreements", blind: bool = False,
           strata: dict[str, Any] | None = None) -> str:
    """Build the whole page as one self-contained HTML string."""
    yes = items[0].get("yes", "B 对了") if items else "B 对了"
    no = items[0].get("no", "A 对了") if items else "A 对了"
    render_one = _blind_card if blind else _card
    cards = "".join(render_one(i, it) for i, it in enumerate(items))
    js = _JS % {"n": len(items), "slug": slug,
                "yes_key": yes_key, "no_key": no_key,
                "selection": json.dumps(selection),
                "strata": json.dumps(strata or {})}
    return (f'<!doctype html><html lang="zh"><meta charset="utf-8">'
            f'<title>{html.escape(title)}</title><style>{_CSS}</style>'
            f'<header><h1>{html.escape(title)}</h1>'
            f'<p class="lede">{lede}</p></header>{cards}'
            f'<div id="bar"><span id="cnt">已判 0 / {len(items)}</span>'
            f'<button onclick="save()">保存结果</button>'
            f'<span id="hint"></span></div>'
            f'<pre id="out" onclick="selectAll(this)" '
            f'title="点一下全选,便于复制"></pre>'
            f'<script>const YES={json.dumps(yes)},NO={json.dumps(no)};{js}</script>')


def write(items: Sequence[dict[str, Any]], dest: Path, **kw) -> Path:
    """Render and save, skipping frames whose pixels will not load.

    A folder of originals reliably contains something that is not an
    image — a resource fork, a truncated copy, a sidecar. Losing the
    whole batch to one of them wastes the reviewer's time, and silently
    dropping it would misstate how many frames were actually offered.
    """
    items = list(items)
    good, skipped = [], []
    for it in items:
        try:
            thumbnail_data_uri(Path(it["path"]))
            good.append(it)
        except Exception as exc:                       # noqa: BLE001
            skipped.append(f"{it.get('fn')}: {type(exc).__name__}")
    if skipped:
        print(f"[review] skipped {len(skipped)} unreadable file(s): "
              + ", ".join(skipped[:5])
              + (" …" if len(skipped) > 5 else ""))
    items = good
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(list(items), **kw), encoding="utf-8")
    return dest


def load_verdicts(path: Path) -> dict[str, str]:
    """Read back what the reviewer saved. Tolerates the clipboard form too."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        d = json.loads(raw)
        return {k: str(v) for k, v in (d.get("verdicts") or d).items()}
    except json.JSONDecodeError:
        # The plain-text shape the first version produced.
        out: dict[str, str] = {}
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "." in parts[-1]:
                out[parts[-1]] = parts[0]
        return out


def stratify(items: Sequence[dict[str, Any]], limit: int, *,
             priority: Iterable[str] = (),
             group: str = "scene") -> list[dict[str, Any]]:
    """Pick ``limit`` items that represent the pool, not its first page.

    ``--limit`` used to truncate, which is a prefix and not a sample: the
    first 40 rows of a shoot are the first 40 rows of a shoot. Measured on
    the real disagreement pool, a prefix would have drawn most of its 40
    from one scene while a whole failure mode sat further down the file.

    Two rules, in order:

    **Priority buckets are taken whole.** Some disagreements matter more
    per row than others. When M3 wants to CULL what the rule keeps, being
    wrong destroys a keeper; when it wants to demote a keep to maybe,
    being wrong costs a second look. There were 19 of the first kind and
    166 of the second, so proportional sampling would have shown 4 of the
    19 — covering the cheap failure well and the expensive one barely.

    **The rest is spread across groups**, round-robin, so a scene with
    49 rows and one with 8 both get looked at. A correction set drawn
    entirely from landscapes teaches you about landscapes.
    """
    pri = set(priority)
    chosen = [it for it in items if it.get("bucket") in pri][:limit]

    rest: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        if it.get("bucket") in pri:
            continue
        rest.setdefault(str(it.get(group) or "—"), []).append(it)

    # Round-robin across groups until the quota is met or the pool is dry.
    while len(chosen) < limit and any(rest.values()):
        for key in sorted(rest, key=lambda k: (-len(rest[k]), k)):
            if not rest[key]:
                continue
            chosen.append(rest[key].pop(0))
            if len(chosen) >= limit:
                break
    return chosen


def load_strata(path: Path) -> dict:
    """filename -> {"stratum", "pop", "sampled"} from a verdict file.

    v2.65 — a stratified sample states its own weights or it cannot be
    scored. Keeping them in a side file meant `m3 eval --labels` had no
    way to ask, and produced an unweighted number from a deliberately
    over-sampled tail without saying so. That figure happened to
    UNDERSTATE the effect (+32.6 unweighted vs +37.1 weighted), which is
    luck rather than a mechanism.
    """
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return (d.get("strata") or {}) if isinstance(d, dict) else {}


def load_selection(path: Path) -> str:
    """How the frames in a saved verdict file were chosen.

    Files written before v2.54 carry no such field.  They are treated as
    ``"disagreements"``, because that is what every batch built so far
    actually was — and because the safe default when provenance is
    missing is the one that refuses to rank, not the one that produces a
    flattering number.
    """
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "disagreements"
    sel = d.get("selection") if isinstance(d, dict) else None
    return str(sel) if sel else "disagreements"
