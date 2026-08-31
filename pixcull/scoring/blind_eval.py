"""v2.80 — blind pairwise evaluation of written critique.

v2.79 measured what a critique *could not possibly* be — text that never
names anything in the frame is not expert, whatever else it is. Whether
critique *is* expert is a different question and only a photographer can
answer it. This module is the machinery for asking them properly.

WHY PAIRWISE, NOT A SCORE

Asking "rate this critique 1-5 for expertise" produces numbers whose
meaning drifts between raters and within a rater over an afternoon.
Asking "which of these two says more about this photograph" is a
judgement people make consistently. The cost is that the result is
relative — it says arm B beat arm A, never that either is good.

WHAT MAKES IT BLIND

The rater sees the photograph and two critiques, labelled left and
right. They do not see which arm wrote which, and the side each arm
appears on is decided by a seeded shuffle so it is reproducible without
being guessable. `Ballot` carries no arm names; the mapping lives in the
sheet and is applied only when votes are counted.

THE REFUSAL

Agreement on written critique is historically poor. If raters do not
agree with each other, a margin between arms is noise wearing a
percentage sign. `verdict()` refuses to declare a winner when observed
agreement is at or below chance, and refuses again when the interval
spans zero. Publishing a low-agreement result as a finding would be
worse than publishing nothing, because this project would then cite it.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Item:
    """One photograph with one critique from each arm."""
    photo_id: str
    left: str
    right: str
    left_arm: str          # never shown to the rater
    right_arm: str


@dataclass(frozen=True)
class Ballot:
    """One rater's answer. Deliberately carries no arm names."""
    photo_id: str
    rater: str
    choice: str            # "left" | "right" | "neither"


def build_sheet(pairs: list[tuple[str, str, str]], arm_a: str, arm_b: str,
                *, seed: int) -> list[Item]:
    """``pairs`` is [(photo_id, critique_from_arm_a, critique_from_arm_b)].

    Side assignment is per-photograph and seeded, so the sheet is
    reproducible from the seed alone and a rater cannot learn "arm A is
    always on the left" halfway through.
    """
    rnd = random.Random(seed)
    out: list[Item] = []
    for pid, a, b in pairs:
        if rnd.random() < 0.5:
            out.append(Item(pid, a, b, arm_a, arm_b))
        else:
            out.append(Item(pid, b, a, arm_b, arm_a))
    return out


def sheet_digest(sheet: list[Item]) -> str:
    """Fingerprint of the sheet as shown, for pre-registration.

    Recorded before any ballot is cast. If the sheet is regenerated with
    different content or a different seed afterwards, the digest changes
    and the ballots no longer belong to it — which is the mechanism that
    stops a disappointing result from being quietly re-run.
    """
    h = hashlib.sha256()
    for it in sheet:
        h.update(f"{it.photo_id}\x00{it.left}\x00{it.right}\x00".encode())
    return h.hexdigest()[:16]


def _pairwise_agreement(votes: dict[str, dict[str, str]]) -> tuple[float, int]:
    """Observed agreement across every rater pair on shared photographs.

    Returns (agreement, n_comparisons). Not Krippendorff's alpha: with
    two or three raters and a three-way choice, alpha's expected-agreement
    term is estimated from so little data that it swings wildly. Observed
    agreement against the chance level of the choice set is blunter and
    harder to fool.
    """
    raters = sorted(votes)
    agree = total = 0
    for i, r1 in enumerate(raters):
        for r2 in raters[i + 1:]:
            shared = set(votes[r1]) & set(votes[r2])
            for pid in shared:
                total += 1
                if votes[r1][pid] == votes[r2][pid]:
                    agree += 1
    return (agree / total if total else 0.0), total


@dataclass
class Verdict:
    winner: str | None
    margin: float
    n: int
    agreement: float
    n_comparisons: int
    refused: str | None = None
    per_arm: dict[str, int] = field(default_factory=dict)


def verdict(sheet: list[Item], ballots: list[Ballot], *,
            min_agreement: float = 0.55,
            min_items: int = 100) -> Verdict:
    """Count the votes, or refuse to.

    ``min_agreement`` is above the 1/3 chance level of a three-way choice
    by a margin, not at it: raters who agree barely more often than coin
    flips have not measured anything, and a winner declared from their
    votes would be this project quoting its own noise.
    """
    by_photo = {it.photo_id: it for it in sheet}
    votes: dict[str, dict[str, str]] = {}
    tally: dict[str, int] = {}
    for b in ballots:
        it = by_photo.get(b.photo_id)
        if it is None:
            continue                      # a ballot for a photo not on this sheet
        votes.setdefault(b.rater, {})[b.photo_id] = b.choice
        if b.choice == "left":
            tally[it.left_arm] = tally.get(it.left_arm, 0) + 1
        elif b.choice == "right":
            tally[it.right_arm] = tally.get(it.right_arm, 0) + 1

    agreement, n_cmp = _pairwise_agreement(votes)
    rated = len({b.photo_id for b in ballots if b.photo_id in by_photo})
    total = sum(tally.values())
    ranked = sorted(tally.items(), key=lambda kv: -kv[1])
    # An arm that received no votes at all is absent from `tally`, not
    # present with a zero. Requiring two entries here made a unanimous
    # sweep — the strongest possible result — come back as "the arms
    # tied", which is the reading least like what happened.
    top = ranked[0][1] if ranked else 0
    second = ranked[1][1] if len(ranked) > 1 else 0
    margin = ((top - second) / total) if total else 0.0

    v = Verdict(None, margin, rated, agreement, n_cmp, per_arm=dict(tally))
    if len(votes) < 2:
        v.refused = "fewer than two raters — agreement is unmeasurable"
    elif rated < min_items:
        v.refused = f"only {rated} photographs rated, below the {min_items} floor"
    elif n_cmp == 0:
        v.refused = "no photograph was rated by more than one rater"
    elif agreement < min_agreement:
        v.refused = (f"raters agreed on {agreement:.0%} of shared photographs, "
                     f"below {min_agreement:.0%} — a margin between arms here "
                     f"is noise, not a result")
    elif total == 0:
        v.refused = ("every rater chose neither on every photograph — the "
                     "arms are not distinguishable, which is a result")
    elif margin == 0.0:
        v.refused = "the arms tied"
    else:
        v.winner = ranked[0][0]
    return v


def write_sheet(sheet: list[Item], path: Path, *, seed: int) -> str:
    """Write the rater-facing sheet and return its digest.

    Arm names go to a sidecar, not the sheet, so opening the file a rater
    is given cannot reveal them.
    """
    digest = sheet_digest(sheet)
    path.write_text(json.dumps(
        {"digest": digest,
         "items": [{"photo_id": i.photo_id, "left": i.left, "right": i.right}
                   for i in sheet]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    path.with_suffix(".key.json").write_text(json.dumps(
        {"digest": digest, "seed": seed,
         "key": {i.photo_id: {"left": i.left_arm, "right": i.right_arm}
                 for i in sheet}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return digest
