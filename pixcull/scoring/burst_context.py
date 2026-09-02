"""v3.3 — tell the critique that a sibling frame exists, and what it won on.

Before this, a frame that lost to its burst sibling was told so as a
float. `nl_explain` rendered "the next burst frame is 0.31 sharper;
consider it instead", and the M3 advice prompt — the one that writes the
2-4 sentence critique — had no burst section at all, so the model writing
"why is this frame being discarded" did not know the frame was one of
seven near-identical exposures of the same moment.

That is the whole reason the critique on a burst loser reads thin. There
is often nothing wrong with the photograph on its own terms; it lost a
comparison. A critique that cannot mention the comparison has to invent
some other reason, and inventing reasons is exactly what this project
spends its refusal guards preventing elsewhere.

WHAT THIS DELIBERATELY DOES NOT DO

The winning frame's *pixels* are not attached. The model is told a
sibling exists, that it won, and on what measured grounds — and is then
told, in the prompt, not to describe a frame it cannot see. Sending both
images is a different and larger change (multi-image judging), and doing
half of it — naming the other frame and letting the model imagine it —
would produce confident sentences about a photograph nobody showed it.

The measured grounds are `burst_peak_reason`, which the ranker already
writes on the winner row ("最锐 +1.6σ" and similar). It is a local
measurement, not a model opinion, which is why it is safe to relay.
"""
from __future__ import annotations

from typing import Any, Iterable

#: Below this the cluster is not a burst worth mentioning — a "cluster"
#: of one is just a photograph, and the note would be noise on every row.
MIN_CLUSTER = 2


def index_clusters(records: Iterable[dict[str, Any]]) -> dict[Any, dict]:
    """Map cluster_id -> {n, peak_filename, peak_reason}.

    Built once per run from the whole frame; the per-photo note needs to
    know about siblings, and a single row cannot know about its own
    cluster. Rows with no cluster_id are skipped rather than pooled under
    a shared ``None`` key — pooling them would invent one enormous burst.
    """
    out: dict[Any, dict] = {}
    for rec in records:
        cid = rec.get("cluster_id")
        if cid is None or (isinstance(cid, str) and not cid.strip()):
            continue
        try:
            if cid != cid:            # NaN
                continue
        except Exception:             # noqa: BLE001
            pass
        slot = out.setdefault(cid, {"n": 0, "peak_filename": "",
                                    "peak_reason": ""})
        slot["n"] += 1
        if rec.get("is_burst_peak"):
            slot["peak_filename"] = str(rec.get("filename") or "")
            reason = rec.get("burst_peak_reason")
            slot["peak_reason"] = str(reason).strip() if reason else ""
    return out


def burst_note(rec: dict[str, Any], clusters: dict[Any, dict]) -> str:
    """One Chinese paragraph for the prompt, or "" when there is no burst.

    Returns "" rather than None so callers can concatenate without a
    branch — a missing note must not be able to render the string "None"
    into a prompt, which is the kind of thing that reaches a model and is
    never noticed.
    """
    cid = rec.get("cluster_id")
    if cid is None:
        return ""
    slot = clusters.get(cid)
    if not slot or slot["n"] < MIN_CLUSTER:
        return ""

    n = slot["n"]
    reason = slot["peak_reason"]
    if rec.get("is_burst_peak"):
        head = f"连拍组:这张是一个 {n} 张连拍组里被选中的那一帧。"
        if reason:
            head += f"选中理由(本机实测):{reason}。"
        return head + (
            "请在 reading 里说清楚这一帧本身成立在哪里 —— "
            "不要只是重复它比同组其他帧好。"
        )

    head = f"连拍组:这张属于一个 {n} 张的连拍组,而且不是被选中的那一帧。"
    if reason:
        head += f"组内胜出的是另一帧,胜出理由(本机实测):{reason}。"
    return head + (
        "你看不到那一帧,所以不要描述它、不要猜它长什么样。"
        "请在 reading 里说清楚:这一张自己有什么、缺什么,"
        "以及在一组几乎相同的照片里,为什么落选的是它。"
        "如果它本身其实是成立的、只是输在比较上,就直接这么说 —— "
        "那比硬找一个缺点诚实。"
    )
