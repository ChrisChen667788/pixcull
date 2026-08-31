"""v2.91 — the harness for a prompt A/B, and the guards it needs first.

Changing the advice prompt is the obvious response to v2.79's numbers.
It is also the change most likely to produce a confident wrong answer,
because every arm costs real money and the temptation is to run few
frames, look at the delta, and stop.

Three things have to be true before a prompt A/B means anything, and
each of them has gone wrong in this repository already:

THE ARMS MUST DIFFER ONLY IN THE PROMPT. Same frames, same model, same
temperature, same evidence block. `plan()` refuses when anything else
moves, because "we changed the prompt and the model and it got better"
is not a finding about a prompt.

THE CACHE KEY MUST CARRY THE ARM. v2.66 changed a cache key and
invalidated an entire pass without noticing; the mirror of that bug is
worse — arm B reading arm A's cached answers and reporting them as its
own, which looks like a perfect tie. `cache_key()` includes the arm and
a test proves two arms cannot collide.

THE SPEND MUST BE BOUNDED BEFORE THE FIRST CALL. Not tracked as it goes:
bounded. `plan()` estimates the whole run and refuses if it would exceed
the ceiling the owner set, so the failure mode is a refusal at the start
rather than a stop halfway through with half an arm.

WHAT THIS MODULE DOES NOT DO is run. That needs an API budget the owner
controls, and spending it on my own initiative is not mine to decide.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Arm:
    name: str
    prompt: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 3000


@dataclass
class Plan:
    arms: list[Arm]
    frames: list[str]
    est_calls: int = 0
    est_prompt_tokens: int = 0
    est_completion_tokens: int = 0
    refused: str | None = None
    differences: list[str] = field(default_factory=list)


def arm_differences(a: Arm, b: Arm) -> list[str]:
    """Everything that differs besides the prompt."""
    out = []
    for field_name in ("model", "temperature", "max_tokens"):
        if getattr(a, field_name) != getattr(b, field_name):
            out.append(f"{field_name}: {getattr(a, field_name)!r} vs "
                       f"{getattr(b, field_name)!r}")
    return out


def cache_key(arm: Arm, frame: str, *, prompt_version: str) -> str:
    """A key that cannot be shared between arms.

    The prompt text itself is hashed in, not just the arm's name: two
    arms called "a" and "b" that were edited between runs would otherwise
    read each other's answers across sessions.
    """
    h = hashlib.sha256()
    h.update(f"{arm.name}\x00{arm.model}\x00{arm.temperature}\x00"
             f"{arm.max_tokens}\x00{prompt_version}\x00{frame}\x00".encode())
    h.update(arm.prompt.encode())
    return h.hexdigest()


def plan(arms: list[Arm], frames: list[str], *,
         ceiling_units: float, estimate_cost, min_frames: int = 100) -> Plan:
    """Decide whether this A/B may run at all.

    ``estimate_cost(model, prompt_tokens, completion_tokens) -> float``
    is injected rather than imported so the ceiling can be checked
    without this module knowing what a unit is. No monetary figure
    appears in this file or in its tests.
    """
    p = Plan(arms=list(arms), frames=list(frames))
    if len(arms) < 2:
        p.refused = "an A/B needs at least two arms"
        return p

    for other in arms[1:]:
        diff = arm_differences(arms[0], other)
        if diff:
            p.differences.extend(diff)
    if p.differences:
        p.refused = ("the arms differ in more than the prompt "
                     f"({'; '.join(p.differences)}). A result would not be "
                     "about the prompt.")
        return p

    if len(set(a.prompt for a in arms)) != len(arms):
        p.refused = "two arms carry the same prompt text"
        return p

    if len(frames) < min_frames:
        p.refused = (f"{len(frames)} frames, below the floor of {min_frames}; "
                     "a delta measured on fewer is a delta about those frames")
        return p

    p.est_calls = len(arms) * len(frames)
    p.est_prompt_tokens = p.est_calls * 900     # evidence block plus prompt
    p.est_completion_tokens = p.est_calls * arms[0].max_tokens // 3
    est = estimate_cost(arms[0].model,
                        p.est_prompt_tokens, p.est_completion_tokens)
    if est > ceiling_units:
        p.refused = (f"the run is estimated at {est:.4g} against a ceiling of "
                     f"{ceiling_units:.4g}. Lower the frame count or raise "
                     "the ceiling deliberately; do not start and see.")
    return p
