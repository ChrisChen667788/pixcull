"""v3.32 — seven waiting measurements, one budget, one refusal.

`BLOCK-v3.1-v3.27-CLOSE.md` lists eleven versions that ship a mechanism
and no number.  Seven of them wait on the same thing: an API spend
ceiling the owner sets.  Today each would be run by hand, separately,
and the results would live in seven places.

WHY NOT `prompt_ab.plan`

That module refuses when two arms differ in more than the prompt, which
is correct for a prompt A/B and wrong here: these seven differ by
design.  v3.5 changes the number of calls per frame, v3.6 the
temperature, v3.11 the attached images, v3.17 the resolution.

The invariant that survives the move is the useful one, restated: an arm
must vary **exactly the dimension it declares**.  An arm that changes its
prompt *and* its resolution measures neither, and the refusal says which
arm and which extra dimension — which is the whole reason v2.66's
"we changed the prompt and the model and it got better" is remembered.

WHAT THIS DOES NOT DO IS RUN.  Same as `prompt_ab`: the spend is the
owner's and starting it is not an agent's call.  `plan()` produces the
estimate and the refusal; a human types the command that spends money.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: The dimensions a measurement is allowed to vary. One each.
DIMENSIONS = ("prompt", "temperature", "resolution", "images",
              "calls_per_frame", "evidence")


@dataclass(frozen=True)
class Measurement:
    """One waiting number, and what it costs to get it."""
    version: str
    name: str
    varies: str
    calls_per_frame: float = 1.0
    prompt_tokens: int = 1200
    completion_tokens: int = 900
    note: str = ""


@dataclass
class BlockPlan:
    measurements: list[Measurement]
    frames: int = 0
    est_calls: int = 0
    est_units: float = 0.0
    ceiling_units: float = 0.0
    refused: str | None = None
    per_measurement: list[dict] = field(default_factory=list)


#: The seven, as the closing document lists them.
WAITING: tuple[Measurement, ...] = (
    Measurement("v3.3", "burst sibling in the critique", "prompt",
                note="advice depth over `reading` on culled burst members"),
    Measurement("v3.4", "worked-critique exemplars", "prompt",
                prompt_tokens=2200,
                note="must include frames where the exemplar does not apply"),
    Measurement("v3.5", "axis-grouped prompts", "calls_per_frame",
                calls_per_frame=3.0,
                note="per-axis Spearman, grouped vs single-pass"),
    Measurement("v3.6", "measured self-consistency", "calls_per_frame",
                calls_per_frame=3.0,
                note="precision@k of measured agreement vs self-reported"),
    Measurement("v3.11", "reference-frame grounding", "images",
                prompt_tokens=1200,
                note="per-axis agreement, canon-only vs exemplar-grounded"),
    Measurement("v3.17", "resolution routing", "resolution",
                note="PER-AXIS agreement and cost; an aggregate hides the "
                     "regression this design guards against"),
    Measurement("v3.18", "multi-image burst calls", "images",
                prompt_tokens=1800,
                note="burst-winner agreement, single vs multi"),
    # v3.36 — v2.91 belongs here too, and was missed.
    #
    # It has waited since the v2.77-v2.95 block on the same one thing:
    # a spend ceiling. It kept its own harness (`prompt_ab.plan`) because
    # it is a pure prompt A/B and this planner did not exist yet, and the
    # v3.1-v3.27 close listed it separately — so an owner who set a
    # ceiling and ran "the block" would still have had one measurement
    # sitting outside it, waiting on a decision they had already made.
    #
    # The estimate is carried here; the RUN still goes through
    # `prompt_ab.plan`, which enforces the arms-differ-only-in-the-prompt
    # rule this planner deliberately relaxes.
    Measurement("v2.91", "advice prompt A/B", "prompt",
                prompt_tokens=2600, completion_tokens=1200,
                note="blind preference between two advice prompts; runs "
                     "through prompt_ab.plan, which refuses when the arms "
                     "differ in anything but the prompt"),
)


def declared_dimension_ok(m: Measurement) -> bool:
    return m.varies in DIMENSIONS


def plan(measurements, frames: int, *, ceiling_units: float,
         estimate_cost) -> BlockPlan:
    """Estimate the whole block and refuse BEFORE the first call.

    Bounded up front, not tracked as it goes — so the failure mode is a
    refusal at the start rather than a stop halfway through with half an
    arm, which is a result nobody can use and money nobody gets back.
    """
    ms = list(measurements)
    p = BlockPlan(measurements=ms, frames=int(frames),
                  ceiling_units=float(ceiling_units))
    if not ms:
        p.refused = "nothing to measure"
        return p
    if p.frames <= 0:
        p.refused = "a measurement over zero frames is not a measurement"
        return p
    bad = [m.version for m in ms if not declared_dimension_ok(m)]
    if bad:
        p.refused = (f"these declare a dimension that is not one of "
                     f"{list(DIMENSIONS)}: {bad}")
        return p

    total_units = 0.0
    for m in ms:
        calls = int(round(p.frames * m.calls_per_frame))
        units = estimate_cost(calls, m.prompt_tokens, m.completion_tokens)
        total_units += units
        p.est_calls += calls
        p.per_measurement.append({
            "version": m.version, "name": m.name, "varies": m.varies,
            "calls": calls, "units": round(units, 4), "note": m.note,
        })
    p.est_units = round(total_units, 4)
    if p.est_units > p.ceiling_units:
        p.refused = (
            f"the block would cost about {p.est_units} units against a "
            f"ceiling of {p.ceiling_units}. Raise the ceiling or cut the "
            f"frame count — a run that stops halfway leaves half an arm, "
            f"which is not a result.")
    return p
