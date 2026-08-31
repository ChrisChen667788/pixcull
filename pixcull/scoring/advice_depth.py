"""v2.79 — measure how deep a written critique actually is.

The owner's complaint was that the critique is "too shallow, does not
show photographic expertise". That is a real problem and it was not a
measurable one, so it could not be fixed, defended, or regressed against.

This module turns it into four numbers that need no human rater and no
API spend. It deliberately does NOT produce a single quality score:
"is this critique good" is a judgement that belongs to a photographer,
and a composite number would let a change claim victory by moving the
easy component. Each signal is reported separately and each says what it
cannot see.

WHAT THESE MEASURE, AND WHAT THEY DO NOT

  sees_the_picture   Does the text name something that is IN the frame —
                     a subject, a part of the body, a material, a piece
                     of the scene? A critique that never does could have
                     been written from the numbers alone, which is
                     exactly what the template path does. This is the
                     signal that separates "looked at the photograph"
                     from "read the histogram".
                     It CANNOT tell whether the naming is correct. A
                     model that hallucinates a bird scores well here.

  argues             Does the text connect an observation to a
                     consequence — "because", "so", "which makes",
                     "although"? Three unconnected assertions are a list,
                     not a critique. This is the difference between
                     describing and reasoning.
                     It CANNOT tell whether the reasoning is sound.

  hedges             Template tells: offering two possibilities instead
                     of looking ("expression or movement"), opening
                     formulae, and filler that survives any photograph.
                     Higher is worse. This is the one that catches the
                     specific failure the advice prompt already forbids
                     in words and which shipped anyway.

  length             Characters. Blunt, but the cached corpus has a
                     median of 71 — one sentence — against a 3,000-token
                     budget, which says the constraint was never the
                     budget.

A baseline over the 3,929 cached rationales is in
`docs/ADVICE-DEPTH-BASELINE.md`. The point of the baseline is that any
future change to a prompt or a model has something to beat, and a
regression has something to trip over.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# Things that exist in photographs. Deliberately concrete nouns: if a
# critique names one, it is talking about the picture rather than about
# the measurements of the picture.
_SUBJECT = re.compile(
    r"人物|人像|面孔|脸|表情|眼神|眼睛|睫毛|嘴|手|手指|手臂|头发|发丝|"
    r"身影|背影|侧脸|新娘|新郎|孩子|老人|运动员|舞者|"
    r"鸟|翅膀|羽毛|animal|猫|狗|马|鹿|昆虫|花|叶|树|枝|草|"
    r"山|海|浪|水|河|湖|雪|冰|沙|石|云|天空|夕阳|日落|日出|星|月|"
    r"建筑|楼|墙|柱|窗|门|桥|路|台阶|屋顶|穹顶|桁架|廊|"
    r"车|船|灯|烟|雾|雨|服装|裙|礼服|西装|帽|首饰|桌|椅|杯|book|书"
)
# Reasoning connectives — the text argues rather than lists.
_ARGUES = re.compile(
    r"因为|所以|因此|导致|使得|以致|从而|由于|正是|之所以|"
    r"但|但是|然而|虽然|尽管|不过|反而|却|换来|牺牲|代价|"
    r"这让|这使|这意味|说明|结果是|才|反之"
)
# Template tells. Higher is worse.
_HEDGES = [
    (re.compile(r"[^,,。;]{2,8}或[^,,。;]{2,8}(?=[,,。;]|$)"), "两可并列"),
    (re.compile(r"这张(照片|图)?(展现|展示|呈现|体现)了?"), "套话开头"),
    (re.compile(r"整体(来说|而言|上)|总的来说|总体来看"), "总结套话"),
    (re.compile(r"(具有|拥有|富有)一定的?"), "程度虚化"),
    (re.compile(r"值得(一提|注意)的是"), "填充语"),
    (re.compile(r"较为|比较|相对|略微|稍微"), "模糊限定"),
]


@dataclass(frozen=True)
class Depth:
    length: int
    sees_the_picture: bool
    n_subjects: int
    argues: bool
    n_connectives: int
    hedges: int
    hedge_kinds: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def measure(text: str | None) -> Depth:
    """Measure one critique. Empty text is not an error — it is a zero."""
    t = (text or "").strip()
    if not t:
        return Depth(0, False, 0, False, 0, 0, ())
    subs = _SUBJECT.findall(t)
    cons = _ARGUES.findall(t)
    kinds: list[str] = []
    n_h = 0
    for rx, name in _HEDGES:
        hits = rx.findall(t)
        if hits:
            n_h += len(hits)
            kinds.append(name)
    return Depth(
        length=len(t),
        sees_the_picture=bool(subs),
        n_subjects=len(set(subs)),
        argues=bool(cons),
        n_connectives=len(cons),
        hedges=n_h,
        hedge_kinds=tuple(kinds),
    )


def summarise(texts: list[str | None]) -> dict:
    """Corpus-level figures. Rates, not a score.

    ``n`` counts every text handed in, including empty ones: reporting
    rates over only the non-empty texts would hide a pass that stopped
    producing output, which is the failure most worth catching.
    """
    ms = [measure(t) for t in texts]
    n = len(ms) or 1
    lens = sorted(m.length for m in ms)
    return {
        "n": len(ms),
        "empty": sum(1 for m in ms if m.length == 0),
        "median_length": lens[len(lens) // 2] if lens else 0,
        "sees_the_picture_rate": sum(m.sees_the_picture for m in ms) / n,
        "argues_rate": sum(m.argues for m in ms) / n,
        "both_rate": sum(m.sees_the_picture and m.argues for m in ms) / n,
        "hedged_rate": sum(m.hedges > 0 for m in ms) / n,
        "mean_subjects": sum(m.n_subjects for m in ms) / n,
    }
