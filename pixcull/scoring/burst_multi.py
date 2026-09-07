"""v3.18 — show the judge two frames of the burst at once.

The local Qwen3-VL path called the model with `num_images=1` under a
comment saying "we pass the image path as a list since some templates
support multi-image". The capability was considered and not built, so the
model that could say "this one, because the eyes are open here and not
there" was never shown both frames. Burst demotion ran afterwards, on
scores produced independently.

WHY THIS IS BOUNDED HARD

A forty-frame sports burst cannot go into one prompt. Beyond a few
images the context is mostly pixels, the schema gets harder to hold, and
the answer degrades in a way that looks like a model problem rather than
a prompt problem. Three peers is a comparison; forty is a slideshow.

WHY IT IS OFF BY DEFAULT

The local path already has a repair-or-fall-back contract for replies
that miss the schema, and multi-image prompts are markedly harder to keep
on schema. Turning this on trades a known failure mode for an unmeasured
one, so it is a flag until the charter's measure — burst-winner agreement
with the photographer, single versus multi — has run.
"""
from __future__ import annotations

import os
from typing import Any, Sequence

ENV_FLAG = "PIXCULL_BURST_MULTI_IMAGE"

#: Peers sent alongside the frame under judgement.
MAX_PEERS = 3


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "0") == "1"


def peer_prompt_note(n_peers: int) -> str:
    """The sentence that tells the model what the extra frames are.

    Without it the model is handed four photographs and no reason to
    treat one differently — and will happily average them into a single
    verdict about a burst rather than a verdict about a frame.
    """
    if n_peers <= 0:
        return ""
    return (
        f"【同组参考】随后附上的 {n_peers} 张是同一连拍组的其他帧。"
        "第一张才是要评的那张,评分只针对它。"
        "其余几张只用来做对比 —— 比如眼睛在哪一张是睁开的、"
        "动作在哪一张到了峰值。"
        "如果这一张在组里明显不是最好的,在 rationale 里直说;"
        "但不要给其他帧打分,也不要把它们的优点算到这一张头上。"
    )


def burst_peers(filename: str, cluster_members: Sequence[dict],
                *, max_peers: int = MAX_PEERS) -> list[str]:
    """Which siblings to send with ``filename``, best first.

    The burst peak goes first when this frame is not it: the comparison
    that matters to a photographer reviewing a loser is against the frame
    the tool chose, not against another loser.

    Returns filenames, not paths — the caller knows where the run's
    images live and this module should not have to.
    """
    others = [m for m in cluster_members
              if str(m.get("filename") or "") != str(filename)]
    if not others:
        return []

    def _key(m: dict[str, Any]):
        try:
            score = float(m.get("score_final"))
        except (TypeError, ValueError):
            score = float("-inf")
        return (0 if m.get("is_burst_peak") else 1, -score)

    others.sort(key=_key)
    return [str(m.get("filename")) for m in others[:max(0, int(max_peers))]]
