"""v2.90 — evaluate burst-peak selection over bursts, not over photographs.

Every rival claims burst grouping, and PixCull has never put a number on
its own. This is the harness, and the first thing it produced was a
reason not to publish one yet.

Counting `is_burst_peak` across a run gives 405 of 415 on the labelled
set — 97.6%, which sounds excellent and means nothing. A cluster of one
photograph has one peak by arithmetic. The real question is only asked
where a choice was made:

    batch_1   81 clusters, 2 with more than one frame
    batch_2   80 clusters, 2 with more than one frame

Four real decisions across 166 photographs. Any figure computed from
that is a figure about four photographs.

So `evaluate_peaks` counts only clusters of two or more, refuses below a
floor, and reports the denominator it used — the number that makes 97.6%
readable as what it is.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

MIN_REAL_BURSTS = 20


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


@dataclass
class BurstInventory:
    clusters: int = 0
    real_bursts: int = 0          # clusters with >= 2 frames
    singletons: int = 0
    frames_in_real_bursts: int = 0
    flagged_peaks: int = 0        # rows with is_burst_peak true, ANY cluster
    peaks_in_real_bursts: int = 0
    malformed: list[str] = field(default_factory=list)

    @property
    def decisions(self) -> int:
        """How many times the picker actually chose. The only honest
        denominator for a peak-selection claim."""
        return self.real_bursts


def inventory(rows: list[dict], *, cluster_key: str = "cluster_id",
              peak_key: str = "is_burst_peak") -> BurstInventory:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cid = r.get(cluster_key)
        if cid is None or str(cid) == "":
            continue
        groups[str(cid)].append(r)

    inv = BurstInventory(clusters=len(groups))
    for cid, members in groups.items():
        peaks = [m for m in members if _truthy(m.get(peak_key))]
        if len(members) < 2:
            inv.singletons += 1
        else:
            inv.real_bursts += 1
            inv.frames_in_real_bursts += len(members)
            inv.peaks_in_real_bursts += len(peaks)
            if len(peaks) != 1:
                # Exactly one hero per burst, or the collapse view either
                # hides every frame or shows two.
                inv.malformed.append(f"{cid}: {len(peaks)} peaks in "
                                     f"{len(members)} frames")
        inv.flagged_peaks += len(peaks)
    return inv


def evaluate_peaks(rows: list[dict], truth: dict[str, str], *,
                   min_bursts: int = MIN_REAL_BURSTS) -> dict:
    """Agreement with a human's chosen peak, over real bursts only.

    ``truth`` maps cluster id -> the filename the human picked. Clusters
    absent from it are not counted either way: a burst nobody judged is
    not evidence, and treating it as agreement is how a peak picker
    scores 97.6%.
    """
    inv = inventory(rows)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cid = str(r.get("cluster_id") or "")
        if cid:
            groups[cid].append(r)

    judged = {c: t for c, t in truth.items()
              if c in groups and len(groups[c]) >= 2}
    if len(judged) < min_bursts:
        return {
            "refused": (f"{len(judged)} judged bursts of two or more frames, "
                        f"below the floor of {min_bursts}. The run has "
                        f"{inv.real_bursts} real bursts among {inv.clusters} "
                        f"clusters; {inv.singletons} are single photographs, "
                        f"which have a peak by arithmetic."),
            "inventory": inv,
        }
    agree = 0
    for cid, want in judged.items():
        chosen = [m for m in groups[cid] if _truthy(m.get("is_burst_peak"))]
        if len(chosen) == 1 and chosen[0].get("filename") == want:
            agree += 1
    return {
        "n_bursts": len(judged),
        "agreement": agree / len(judged),
        "inventory": inv,
        "refused": None,
    }
