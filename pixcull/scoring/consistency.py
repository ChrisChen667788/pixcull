"""v3.6 — measure whether the model agrees with itself, instead of asking it.

The report grid renders a `⌬ K 85%` badge on every card. That number is
`meta_judge.confidence`, which the text model reports *about itself* —
`meta_judge.py` reads `parsed['confidence']` straight out of the reply.
Nothing has ever checked whether it predicts anything. A model that says
85% on frames it is wrong about sends the photographer to review the
clear cases and past the ambiguous ones, which is worse than no signal.

The measured alternative is old and boring: draw the same frame N times
and see whether the answers agree. It was not merely unimplemented here —
it was impossible, twice over, and both blockers had to be removed first:

  v3.2  temperature was not in the cache key, so N draws returned one
        cached answer and agreement was 1.0 on every image in the library.
  v3.6  numbering the draws, because N draws at the *same* temperature
        still collided — the same bug one level in.

WHAT THIS COSTS, AND WHY IT IS A GATE

N draws per frame is N times the spend. On a 2,000-frame wedding at N=3
that is 6,000 calls to answer a question about maybe 200 of them. So
sampling is gated: it fires only on frames the cheap signals have already
flagged, and `should_sample` is the whole of that policy in one place.

WHAT AGREEMENT IS NOT

It is not accuracy. Three draws that all say "keep" agree perfectly and
may all be wrong; a confidently wrong model looks identical to a
confidently right one. Agreement measures stability, which is a *lower
bound* on how much a verdict should be trusted, and this module says so
rather than letting a caller read it as quality.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence

ENV_FLAG = "PIXCULL_CONSISTENCY_DRAWS"

#: Temperature for a consistency draw. Zero would defeat the purpose —
#: the point is to see whether the answer is stable under sampling.
DRAW_TEMPERATURE = 0.7

#: Below this self-reported confidence a frame is worth sampling. The
#: threshold is a gate on spend, not a claim that the number is good —
#: measuring whether it is good is what this module exists for.
CONFIDENCE_GATE = 0.7


@dataclass(frozen=True)
class Agreement:
    """The result of N draws on one frame."""
    n: int
    labels: tuple[str, ...]
    modal_label: str
    agreement: float          # share of draws that chose the modal label
    unanimous: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "consistency_n": self.n,
            "consistency_labels": list(self.labels),
            "consistency_modal": self.modal_label,
            # Named `measured_` so it can never be confused in a CSV
            # column or a JSON payload with the self-reported one.
            "measured_agreement": self.agreement,
            "consistency_unanimous": self.unanimous,
        }


def draws_requested() -> int:
    """How many draws, from the environment. 0 means the pass is off.

    Off by default: this multiplies spend, and it is the owner's money.
    """
    try:
        n = int(os.environ.get(ENV_FLAG, "0"))
    except ValueError:
        return 0
    return n if n >= 2 else 0     # one draw measures nothing


def should_sample(row: dict[str, Any]) -> bool:
    """Whether this frame is worth N calls.

    Only frames the cheap signals already doubt. A frame the meta-judge
    was confident about and flagged no contradictions in does not get
    resampled, because the point of the gate is that most frames are not
    the question.
    """
    inc = row.get("meta_inconsistencies")
    if isinstance(inc, str) and inc.strip():
        return True
    if isinstance(inc, (list, tuple)) and len(inc):
        return True
    conf = row.get("meta_confidence")
    if isinstance(conf, (int, float)):
        return bool(conf < CONFIDENCE_GATE)
    # No meta signal at all: the frame was never judged by the meta pass,
    # so there is nothing to doubt and nothing to confirm. Not sampled —
    # sampling everything unjudged is how a gate becomes a full pass.
    return False


def agreement_of(labels: Sequence[str | None]) -> Agreement | None:
    """Agreement over N draws, or None when there is nothing to measure.

    Returns None rather than 1.0 for a single usable draw. A lone draw
    agrees with itself trivially, and reporting that as perfect stability
    is the exact shape of the bug v3.2 and this version removed from the
    cache — a number that looks like a measurement and is an artefact.
    """
    got = tuple(str(x).strip() for x in labels if x and str(x).strip())
    if len(got) < 2:
        return None
    counts = Counter(got)
    modal, hits = counts.most_common(1)[0]
    return Agreement(
        n=len(got),
        labels=got,
        modal_label=modal,
        agreement=hits / len(got),
        unanimous=len(counts) == 1,
    )


def sample(judge: Any, image_path: Any, *, n: int, row: dict[str, Any] | None = None,
           scene: str | None = None, vertical: str | None = None,
           temperature: float = DRAW_TEMPERATURE) -> Agreement | None:
    """Draw ``n`` verdicts for one frame and report their agreement.

    Each draw carries its own `sample` index so it gets its own cache
    slot — without that the second and third draws read the first one
    back and the whole measurement is a tautology.

    Draws that error contribute nothing rather than counting as a
    disagreement: an API timeout is not the model changing its mind.
    """
    labels: list[str | None] = []
    for i in range(1, max(int(n), 0) + 1):
        try:
            v = judge.score(image_path, scene=scene, vertical=vertical,
                            row=row, temperature=temperature, sample=i)
        except TypeError:
            # A judge that cannot be sampled cannot be measured this way.
            return None
        except Exception:  # noqa: BLE001
            continue
        if getattr(v, "error", None):
            continue
        labels.append(getattr(v, "overall_label", None))
    return agreement_of(labels)
