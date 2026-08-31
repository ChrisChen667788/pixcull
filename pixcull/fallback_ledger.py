"""v2.71 — a silent fallback has to be counted.

`_m3_advice_pass` returned 0 on every run for seventeen versions and
nothing noticed. The reason it could hide is worth stating plainly,
because it is a property of the design rather than an oversight:

**Falling back is the correct behaviour.** Advice is commentary on a
decision already made; a photographer's cull must not get worse because
a key expired or a model truncated. So every one of these passes catches
broadly, returns the template, and logs nothing. Which means a pass that
is working and a pass that has never executed produce *identical*
output: template advice, no error, no line anywhere.

The distinction that matters is not "did it fail" — failures are
expected and handled. It is:

* **fell back** — tried, and the fallback took over. A rate, not an
  alarm. 9% is life; 100% is a bug wearing life's clothes.
* **never attempted, with work available** — the v2.68.6 signature
  exactly. `todo` filtered on a key the rows do not carry, so the pass
  saw 200 candidate rows and attempted none. That is the one condition
  that is never normal, and it is what `structural_failures()` names.

Nothing here raises. A ledger that can break a run would be a worse
bug than the one it exists to catch.
"""

from __future__ import annotations

import threading
import dataclasses
from dataclasses import dataclass, field

#: Reason buckets, so two runs are comparable. `other` keeps the first
#: raw string it sees — an unbucketed reason must not vanish, or this
#: module reintroduces the problem it exists to solve one level up.
REASONS = (
    "no_api_key", "no_consent", "budget_exhausted", "truncated",
    "parse_failed", "no_image", "request_failed", "other",
)


@dataclass
class PassStat:
    name: str
    candidates: int = 0          # rows this pass considered its business
    attempted: int = 0           # ... that it actually tried
    succeeded: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    examples: dict[str, str] = field(default_factory=dict)
    withheld: int = 0            # ... that policy excluded before it began
    withheld_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def fell_back(self) -> int:
        return max(0, self.attempted - self.succeeded)

    @property
    def fallback_rate(self) -> float:
        return self.fell_back / self.attempted if self.attempted else 0.0

    @property
    def structural(self) -> bool:
        """Had work, did none. Never a normal state."""
        return self.candidates > 0 and self.attempted == 0

    @property
    def total_fallback(self) -> bool:
        """Tried everything and nothing worked."""
        return self.attempted > 0 and self.succeeded == 0

    def summary(self) -> str:
        if self.structural:
            return (f"{self.name}: {self.candidates} candidate rows, "
                    f"0 attempted — the pass had work and did none")
        if not self.attempted:
            return f"{self.name}: nothing to do"
        top = sorted(self.by_reason.items(), key=lambda kv: -kv[1])[:2]
        why = ", ".join(f"{k}×{v}" for k, v in top)
        return (f"{self.name}: {self.succeeded}/{self.attempted} ok, "
                f"{self.fallback_rate:.0%} fell back"
                + (f" ({why})" if why else ""))


class FallbackLedger:
    """Process-local, thread-safe. The advice pass runs 8 workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._passes: dict[str, PassStat] = {}

    def _get(self, name: str) -> PassStat:
        st = self._passes.get(name)
        if st is None:
            st = PassStat(name=name)
            self._passes[name] = st
        return st

    def candidates(self, name: str, n: int) -> None:
        """How many rows this pass considers its business, BEFORE any
        eligibility filtering. The gap between this and `attempted` is
        where v2.68.6 lived."""
        with self._lock:
            self._get(name).candidates += max(0, int(n))

    def withheld(self, name: str, n: int, reason: str) -> None:
        """Rows this pass was never going to touch, and why.

        v2.81 — distinct from `fell_back`, which means "tried and could
        not", and from the candidates/attempted gap, which means "should
        have tried and did not". This is a POLICY: the pass declined by
        design. Recording it turns an implicit rule into a number, which
        is the difference between a decision and an omission — the deep
        critique was withheld from every culled frame for many versions
        and nothing anywhere said so.
        """
        with self._lock:
            st = self._get(name)
            st.withheld += max(0, int(n))
            if reason:
                st.withheld_reasons[reason] = (
                    st.withheld_reasons.get(reason, 0) + max(0, int(n)))

    def attempt(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._get(name).attempted += n

    def ok(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._get(name).succeeded += n

    def fell_back(self, name: str, reason: str) -> None:
        bucket = reason if reason in REASONS else "other"
        with self._lock:
            st = self._get(name)
            st.by_reason[bucket] = st.by_reason.get(bucket, 0) + 1
            if bucket == "other" and "other" not in st.examples:
                st.examples["other"] = str(reason)[:120]

    def snapshot(self) -> dict[str, PassStat]:
        """A detached copy of every pass.

        v2.81 — copied field-by-field until this version, which meant a
        field added to PassStat was silently dropped here and read back
        as its default. `withheld` was added, recorded correctly, and
        came out of to_json() as 0. Enumerating the dataclass's own
        fields makes the next addition impossible to forget; a test holds
        it.
        """
        with self._lock:
            out: dict[str, PassStat] = {}
            for k, v in self._passes.items():
                kw = {}
                for f in dataclasses.fields(PassStat):
                    val = getattr(v, f.name)
                    kw[f.name] = dict(val) if isinstance(val, dict) else val
                out[k] = PassStat(**kw)
            return out

    def structural_failures(self) -> list[str]:
        """Passes that had work and did none — the condition that is
        never normal, and the one a run's self-check should fail on."""
        return [st.summary() for st in self.snapshot().values()
                if st.structural or st.total_fallback]

    def to_json(self) -> dict:
        return {
            "schema": "pixcull.fallback_ledger/v1",
            "passes": {
                st.name: {
                    "candidates": st.candidates,
                    "attempted": st.attempted,
                    "succeeded": st.succeeded,
                    "fell_back": st.fell_back,
                    "fallback_rate": round(st.fallback_rate, 4),
                    "by_reason": st.by_reason,
                    "examples": st.examples,
                    "structural": st.structural,
                    "withheld": st.withheld,
                    "withheld_reasons": st.withheld_reasons,
                } for st in self.snapshot().values()
            },
        }

    def reset(self) -> None:
        with self._lock:
            self._passes.clear()


#: One per process. Runs are sequential in the server, and a ledger that
#: needed threading through six call sites would not get adopted.
LEDGER = FallbackLedger()
