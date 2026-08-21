"""v2.51 — M3 writes the per-photo advice, looking at the actual photo.

``photo_advice.build_advice`` is 1576 lines of templates and **zero** LLM
calls.  It is the weakest surface in the product and the one M3 most
obviously improves: a template can say "主体锐利,焦平面到位(σ²=300)"
because it read a number, but it cannot say "新娘的手被前景虚化挡住了"
because it has never seen the frame.

The constraint that shapes this module is the **output contract**, not the
prompt.  ``build_advice`` returns nine keys, and three separate consumers
read them in ways that fail *silently* when the shape drifts:

* ``caption_gen.compose_caption`` does ``strengths[0]`` and then a regex —
  a dict there does not raise, it just drops the caption fragment.
* the lightbox info pane renders ``strengths_detail[i].source`` as the
  canon citation ("Adams · Zone System"); a missing ``source`` blanks the
  citation UI with no error anywhere.
* the XMP/IPTC exporter builds Caption-Abstract from the same dict, so a
  drift here reaches Lightroom.

So :func:`advice_from_m3` validates and repairs into the template shape
rather than trusting the model, and anything it cannot repair falls back
to the template engine.  A photographer with a broken key gets the v2.50
advice, not an empty pane.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The nine keys ``build_advice`` returns.  Pinned here so a drift is a
#: test failure rather than three silent UI regressions.
ADVICE_KEYS = (
    "verdict", "verdict_short", "rationale",
    "strengths", "weaknesses", "suggestions",
    "strengths_detail", "weaknesses_detail", "inconsistencies",
)

_AXES = ("technical", "subject", "composition", "light", "moment", "aesthetic")

PROMPT = """\
你是一位资深摄影指导,正在帮摄影师复盘一张照片。

先看照片本身,再读下面这些**本机实测数值**——它们比目视判断准,
但它们不知道画面里发生了什么,而你知道。把两者结合起来。

{evidence}

判定:{decision}(六轴评分:{stars})

请只输出 JSON,不要任何其他文字:

{{
  "reading": "2-4 句,连起来说:这张照片在做什么(主体、光、瞬间),
              它成立或不成立的关键在哪,以及这为什么导致了上面那个判定。
              这是整段点评里最重要的一项——把观察、判断、后果连成一条线,
              而不是三句互不相干的话。",
  "rationale": "一句话概括 reading,给只看一行的人",
  "strengths": ["最多 3 条优点,每条一句,必须指出画面里的具体东西"],
  "weaknesses": ["最多 3 条问题,同上;没有就给空数组"],
  "alternative": "换你来拍/来裁,你会怎么改这一张——机位、时机、
                  取景、光位,挑最要紧的一条,要具体到可执行。
                  如果这张已经没什么可改的,就给空字符串",
  "suggestions": ["最多 2 条更一般的下次注意事项"],
  "strengths_detail": [
    {{"axis": "六轴之一", "phrase": "同 strengths 里那条",
      "source": "只在你真能指名一条摄影正典时才填,如 Adams · Zone System;
                 拿不准就留空字符串——硬凑的出处比没有出处更糟"}}
  ],
  "weaknesses_detail": [同上结构]
}}

要求:
- 说画面,不说数字。"σ²=300" 是数据,"睫毛清晰可数" 才是观察。
- 不要在两个可能之间打太极。"捕捉到动物的神情或动作" 是模板腔,
  你看得见画面,就说清楚是神情还是动作、是哪一个。
- 中文,不要客套话,不要"这张照片展现了……"这种开头。
- 如果测量值和你看到的冲突(比如数值说糊但画面是有意的动态模糊),
  在 reading 里点出来——那种冲突往往是这张照片最值得说的地方。
"""


def build_prompt(row: dict[str, Any], final_stars: dict[str, Any],
                 decision: str) -> str:
    from pixcull.scoring.m3 import build_evidence_block
    evidence = build_evidence_block(row) or "(本机检测器没有可用读数)"
    stars = " ".join(
        f"{a}={final_stars.get(a)}" for a in _AXES
        if final_stars.get(a) is not None) or "无"
    return PROMPT.format(evidence=evidence, decision=decision, stars=stars)


def _strings(v: Any, limit: int) -> list[str]:
    """Coerce whatever the model returned into ``list[str]``.

    ``compose_caption`` runs a regex over ``strengths[0]``. A dict there
    raises nothing — it silently drops the caption fragment — so the
    repair happens here, once, rather than as a defensive check in three
    consumers.
    """
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out: list[str] = []
    for item in v:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            s = item.get("phrase") or item.get("text") or ""
            if isinstance(s, str) and s.strip():
                out.append(s.strip())
    return out[:limit]


def _details(v: Any, phrases: list[str], limit: int) -> list[dict[str, str]]:
    """Normalise the citation rows the lightbox renders.

    Every entry must carry ``axis`` / ``phrase`` / ``source``; the pane
    reads ``.source`` directly, so a missing key blanks the citation with
    no error. When the model omits the detail list entirely we synthesise
    one from the phrases — an uncited strength is still a strength, and
    an empty pane looks like a bug.

    v2.68.5 — what we do NOT do is invent the citation. The prompt used
    to require a `source` on every line, and a model asked to cite
    something for a claim that has no canon behind it will produce one:
    "作品塔 · 图底关系" arrived that way, in a photographer's inspector,
    attached to a sentence about contrast. A citation nobody can look up
    costs more than the blank it replaces, because it is the part of the
    pane that is supposed to be checkable.
    """
    out: list[dict[str, str]] = []
    if isinstance(v, (list, tuple)):
        for item in v:
            if not isinstance(item, dict):
                continue
            phrase = str(item.get("phrase") or "").strip()
            if not phrase:
                continue
            axis = str(item.get("axis") or "").strip()
            out.append({
                "axis": axis if axis in _AXES else "",
                "phrase": phrase,
                "source": str(item.get("source") or "").strip(),
            })
    seen = {d["phrase"] for d in out}
    for p in phrases:
        if len(out) >= limit:
            break
        if p not in seen:
            out.append({"axis": "", "phrase": p, "source": ""})
    return out[:limit]


def advice_from_m3(raw_text: str, *, decision: str,
                   fallback: dict[str, Any]) -> dict[str, Any] | None:
    """Parse M3's reply into the exact shape ``build_advice`` returns.

    Returns ``None`` when the reply is unusable, so the caller keeps the
    template advice. Partial output is repaired rather than rejected: a
    model that gave good strengths and forgot ``suggestions`` is still
    more useful than a template, and the missing key is filled from the
    fallback so no consumer sees an absent key.
    """
    from pixcull.scoring.vlm_judge import parse_vlm_response

    parsed = parse_vlm_response(raw_text or "")
    if not isinstance(parsed, dict):
        return None

    strengths = _strings(parsed.get("strengths"), 3)
    weaknesses = _strings(parsed.get("weaknesses"), 3)
    rationale = str(parsed.get("rationale") or "").strip()
    if not (rationale or strengths or weaknesses):
        # Valid JSON carrying nothing. Template advice beats a blank pane.
        return None

    out = dict(fallback)          # every key present, always
    out["rationale"] = rationale or fallback.get("rationale", "")
    out["strengths"] = strengths or list(fallback.get("strengths") or [])
    out["weaknesses"] = weaknesses or list(fallback.get("weaknesses") or [])
    sug = _strings(parsed.get("suggestions"), 2)
    if sug:
        out["suggestions"] = sug
    out["strengths_detail"] = _details(
        parsed.get("strengths_detail"), out["strengths"], 3)
    out["weaknesses_detail"] = _details(
        parsed.get("weaknesses_detail"), out["weaknesses"], 3)
    out["verdict"] = fallback.get("verdict", decision)
    out["verdict_short"] = fallback.get("verdict_short", decision)
    # v2.68.5 — the two keys that let a critique be a critique.
    #
    # ADDED, never substituted. `build_advice` returns nine keys and
    # three consumers read them in ways that fail silently when the shape
    # drifts, so the old shape stays exactly as it was and the depth
    # arrives beside it. A template row simply has neither key, and the
    # pane renders what is there.
    #
    # `reading` is the point. The old schema asked for three detached
    # one-line strengths, three weaknesses, two suggestions — and the
    # connection between an observation, the judgement it supports and
    # what you would do instead is most of what a senior director is
    # actually paid for. The schema forbade the connection, so no prompt
    # wording could have produced it.
    out["reading"] = str(parsed.get("reading") or "").strip()
    out["alternative"] = str(parsed.get("alternative") or "").strip()
    out["advice_source"] = "minimax-m3"
    return out


def enrich_advice(row: dict[str, Any], final_stars: dict[str, Any],
                  decision: str, fallback: dict[str, Any],
                  judge: Any, *, image_path: Path | None = None,
                  max_tokens: int = 3000) -> dict[str, Any]:
    """Template advice in, M3 advice out — or the template again.

    Never raises. Advice is decoration on a decision that has already
    been made; a failure here must not cost the photographer their cull.
    """
    if judge is None or image_path is None or not Path(image_path).exists():
        return fallback
    try:
        verdict = judge.score(
            Path(image_path),
            scene=str(row.get("scene") or ""),
            max_tokens=max_tokens,
            row=row,
            prompt_override=build_prompt(row, final_stars, decision),
        )
    except TypeError:
        # A judge without prompt_override cannot write advice; its axis
        # scores answer a different question.
        return fallback
    except Exception:  # noqa: BLE001
        return fallback
    if getattr(verdict, "error", None):
        return fallback
    got = advice_from_m3(getattr(verdict, "raw_text", "") or "",
                         decision=decision, fallback=fallback)
    return got if got is not None else fallback
