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
    #: v3.79 — the other limit. `ceiling_units` is what the owner set;
    #: this is what the API budget will actually enforce, and when the
    #: owner sets no ceiling it is the only thing standing between the
    #: block and a run that stops halfway.
    daily_cap_units: float | None = None
    #: Which limit the estimate was measured against: "ceiling",
    #: "daily-cap", or None when nothing bound it.
    bound_by: str | None = None
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
         estimate_cost, daily_cap_units: float | None = None) -> BlockPlan:
    """Estimate the whole block and refuse BEFORE the first call.

    Bounded up front, not tracked as it goes — so the failure mode is a
    refusal at the start rather than a stop halfway through with half an
    arm, which is a result nobody can use and money nobody gets back.

    **v3.79 — "no ceiling" was not the same as "unbounded".** An owner
    who sets `ceiling_units=inf`, meaning run the block to completion, is
    still behind `llm_budget`'s daily cap, which is set by default and
    stops calls *as they happen*. So the exact failure this function
    exists to prevent — a stop halfway through, half an arm, nothing
    usable — was reachable by setting no ceiling at all, and it arrived
    silently, because a call that cannot be afforded is declined
    downstream rather than refused here.

    Pass `daily_cap_units` and the estimate is measured against whichever
    limit is smaller, and the refusal says which one it was. Leave it
    None and the plan records that it could not see the downstream limit
    rather than implying there is none.
    """
    ms = list(measurements)
    p = BlockPlan(measurements=ms, frames=int(frames),
                  ceiling_units=float(ceiling_units),
                  daily_cap_units=(None if daily_cap_units is None
                                   else float(daily_cap_units)))
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

    # Whichever limit binds first is the one worth naming. An owner who
    # raised the ceiling to infinity and still gets refused needs to be
    # told it was the daily cap, not left to re-read their own setting.
    limits = [("ceiling", p.ceiling_units)]
    if p.daily_cap_units is not None:
        limits.append(("daily-cap", p.daily_cap_units))
    name, limit = min(limits, key=lambda kv: kv[1])
    p.bound_by = name

    if p.est_units > limit:
        if name == "daily-cap":
            p.refused = (
                f"the block would cost about {p.est_units} units and the "
                f"daily API cap is {limit}. The ceiling is "
                f"{p.ceiling_units}, so it is the cap that binds: raise "
                f"PIXCULL_LLM_BUDGET_YUAN, or split the block across "
                f"days deliberately. Left alone this does not refuse — it "
                f"stops partway through, which leaves half an arm.")
        else:
            p.refused = (
                f"the block would cost about {p.est_units} units against a "
                f"ceiling of {p.ceiling_units}. Raise the ceiling or cut the "
                f"frame count — a run that stops halfway leaves half an arm, "
                f"which is not a result.")
    elif p.daily_cap_units is None:
        # Not a refusal. A plan that was never measured against the limit
        # that will actually stop it should not read like one that was.
        p.bound_by = None
    return p
