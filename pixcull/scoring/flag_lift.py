"""v2.70 — is each detector flag evidence at all?

v2.68 asked what a flag should *do* when it fires and answered: demote,
never delete, because the flags together carry 0.9x lift against this
photographer's culls — worse than chance. This asks the prior question,
one flag at a time. A flag with no lift should not be costing anyone a
second look either.

**Lift** is the cull rate among frames the flag fired on, divided by the
cull rate overall. 1.0x means the flag tells you nothing you did not
already know from the base rate; below 1.0x means a frame it fires on is
*less* likely to be culled than a frame picked at random.

Two things this module refuses to do:

* **Conclude from a handful of firings.** Three of the eight flags in the
  blind set fired fewer than ten times. A 0.00x lift on four firings is
  not evidence that a flag is useless; it is four frames.
* **Confuse "no lift" with "never fired".** Three flags in the shipped
  hard-cull set did not fire once on 494 frames. Nothing here licenses
  an opinion about them, and saying so is the result.

Counts are weighted by the stratified sample's inverse-probability
weights, because the second batch was not drawn uniformly. The Wilson
interval uses the RAW firing count: a weight multiplies the influence of
an observation, it does not create observations, and an interval that
treats 100 stratified frames as 894 would be a fabrication.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

#: Below this many raw firings a flag is reported, never judged. Chosen
#: before looking at the per-flag counts.
MIN_FIRINGS = 20


@dataclass(frozen=True)
class FlagStat:
    flag: str
    n_raw: int                 # frames the flag fired on
    w_fired: float             # ... weighted
    w_culled: float            # of those, how many the photographer culled
    base_rate: float           # cull rate over the whole set

    @property
    def rate(self) -> float:
        return self.w_culled / self.w_fired if self.w_fired else 0.0

    @property
    def lift(self) -> float:
        return self.rate / self.base_rate if self.base_rate else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        """Wilson interval for the cull rate, on the RAW count."""
        return _wilson(self.rate, self.n_raw)

    @property
    def lift_ci(self) -> tuple[float, float]:
        lo, hi = self.ci
        if not self.base_rate:
            return (0.0, 0.0)
        return (lo / self.base_rate, hi / self.base_rate)

    @property
    def verdict(self) -> str:
        """What may honestly be said about this flag."""
        if self.n_raw < MIN_FIRINGS:
            return "unmeasured"
        lo, hi = self.lift_ci
        if hi < 1.0:
            return "no-lift"        # reliably worse than the base rate
        if lo > 1.0:
            return "informative"
        return "inconclusive"


def _wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n)))
    return (max(0.0, (c - s) / d), min(1.0, (c + s) / d))


def measure(rows: Iterable[tuple[Sequence[str], str, float]]) -> dict[str, FlagStat]:
    """``rows`` is (flags, truth, weight) per frame. Truth is keep/cull."""
    rows = list(rows)
    total = sum(w for _, _, w in rows)
    culled = sum(w for _, t, w in rows if t == "cull")
    base = culled / total if total else 0.0

    n_raw: dict[str, int] = {}
    fired: dict[str, float] = {}
    hit: dict[str, float] = {}
    for flags, truth, w in rows:
        for f in set(flags):
            n_raw[f] = n_raw.get(f, 0) + 1
            fired[f] = fired.get(f, 0.0) + w
            if truth == "cull":
                hit[f] = hit.get(f, 0.0) + w
    return {
        f: FlagStat(flag=f, n_raw=n_raw[f], w_fired=fired[f],
                    w_culled=hit.get(f, 0.0), base_rate=base)
        for f in sorted(fired, key=lambda x: -fired[x])
    }


def flags_worth_acting_on(stats: dict[str, FlagStat],
                          shipped: Iterable[str]) -> tuple[set[str], list[str]]:
    """Which of the shipped flags the evidence supports keeping.

    Returns ``(keep, notes)``. A flag is dropped ONLY on a measured
    absence of lift — never on never having fired, which is a fact about
    the sample rather than about the flag.
    """
    keep, notes = set(), []
    for f in shipped:
        st = stats.get(f)
        if st is None:
            keep.add(f)
            notes.append(f"{f}: never fired on this set — kept, unmeasured")
            continue
        if st.verdict == "no-lift":
            notes.append(
                f"{f}: {st.n_raw} firings, {st.lift:.2f}x "
                f"[{st.lift_ci[0]:.2f}, {st.lift_ci[1]:.2f}] — dropped")
            continue
        keep.add(f)
        notes.append(
            f"{f}: {st.n_raw} firings, {st.lift:.2f}x "
            f"[{st.lift_ci[0]:.2f}, {st.lift_ci[1]:.2f}] — {st.verdict}")
    return keep, notes


@dataclass(frozen=True)
class MarginalStat:
    """What a flag buys ON TOP of the decision already taken."""

    flag: str
    n_fired: int
    n_already_flagged_by_score: int
    n_changed: int          # frames the flag alone moves off KEEP
    n_changed_culls: int    # ... of which the photographer culled
    base_rate: float

    @property
    def rate(self) -> float:
        return self.n_changed_culls / self.n_changed if self.n_changed else 0.0

    @property
    def lift(self) -> float:
        return self.rate / self.base_rate if self.base_rate else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return _wilson(self.rate, self.n_changed)


def marginal(rows: Iterable[tuple[Sequence[str], str, str, float]],
             flag: str, base_rate: float) -> MarginalStat:
    """``rows`` is (flags, truth, current_decision, weight) per frame.

    v2.70 — the number that decides whether a flag belongs in the
    attention set, and it is NOT the raw lift.

    Raw lift asks "are flagged frames worse than average". Every
    informative flag passes that, because a flag fires on frames whose
    score is already low, and a low score is already sending them to
    MAYBE. Measured on 494 blind frames: `severely_underexposed` fires
    63 times, and 52 of those are non-KEEP before the flag is consulted.

    So the question is the marginal one — of the frames the flag ALONE
    moves off KEEP, how many did the photographer actually cull. For
    `shadows_clipped` that is 2 of 22, which is 9.1%: the base rate
    exactly. Twenty-two extra second looks bought nothing.

    macro-F1 cannot answer this at all. It scores MAYBE as KEEP (97% of
    `maybe`s on kept frames were recoverable — v2.63), so moving a frame
    between them is invisible to it: adding either flag changed macro-F1
    by 0.0. The same identifiability trap as v2.68's `keep_min`, one
    parameter over.
    """
    n_fired = n_already = n_changed = n_changed_culls = 0
    for flags, truth, decision, _w in rows:
        if flag not in set(flags):
            continue
        n_fired += 1
        if decision != "keep":
            n_already += 1
            continue
        n_changed += 1
        if truth == "cull":
            n_changed_culls += 1
    return MarginalStat(flag=flag, n_fired=n_fired,
                        n_already_flagged_by_score=n_already,
                        n_changed=n_changed, n_changed_culls=n_changed_culls,
                        base_rate=base_rate)
