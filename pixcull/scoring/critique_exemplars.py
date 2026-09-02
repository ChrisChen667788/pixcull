"""v3.4 — show the model a finished critique, not only principles.

The advice prompt grounds itself in the photography canon as abstract
text: the Zone System, the decisive moment. It tells the model what good
work looks like in words and has never shown it one.

That is the half of AtelierJudge's dual-process design that transfers
here — System 1 retrieves concrete exemplars before System 2 checks
against criteria. This module is the retrieval half.

PROVENANCE IS ENFORCED, NOT DOCUMENTED

Every exemplar declares where it came from, and an exemplar whose
provenance is not one of the known values is dropped rather than
injected. The reason is specific: a critique written by someone who is
not a working photographer, injected as an example of photographic
expertise, would teach the model to imitate a non-expert — and it would
do so invisibly, inside a prompt nobody reads. This project refuses
fabricated labels; a fabricated exemplar is the same act one layer up.

    cache-selected  the tool's own output, ranked by advice_depth.
                    Best-of-N distilled back into the prompt. Reduces
                    variance; cannot raise the ceiling.
    photographer    written or approved by a working photographer.
                    The only value that makes the bank an upgrade rather
                    than a stabiliser. Nothing carries it yet.
    authored        written by a non-photographer, kept for form only.

WHAT THIS CANNOT DO

Exemplars are a strong stylistic attractor. A model given three critiques
that all open by naming the subject will open by naming the subject, on
photographs where that is the wrong move. The measure for this version
has to include frames where the exemplar does not apply, or it measures
conformity and calls it depth.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data" / "critique_exemplars.json"

#: Provenance values an exemplar may declare. Anything else is dropped.
KNOWN_PROVENANCE = frozenset({"cache-selected", "photographer", "authored"})

#: The bank used when a vertical has none of its own.
DEFAULT_KEY = "_default"

#: How many exemplars reach the prompt. Three is enough to show a form;
#: more starts to crowd the evidence block the critique is supposed to
#: be reasoning about.
MAX_IN_PROMPT = 3


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 0, "exemplars": {}}


def _clean(items: Any) -> list[dict]:
    out: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        text = str(it.get("reading") or "").strip()
        prov = str(it.get("provenance") or "").strip()
        if not text or prov not in KNOWN_PROVENANCE:
            continue          # undeclared provenance never reaches a prompt
        out.append({"reading": text, "provenance": prov})
    return out


def for_vertical(vertical: str | None) -> list[dict]:
    """Exemplars for one shoot type, falling back to the default bank."""
    banks = _load().get("exemplars") or {}
    key = (vertical or "").strip()
    got = _clean(banks.get(key)) if key else []
    if not got:
        got = _clean(banks.get(DEFAULT_KEY))
    return got[:MAX_IN_PROMPT]


def prompt_section(vertical: str | None) -> str:
    """The block injected into the advice prompt, or "" when empty.

    Returns "" and not None: a missing section must not be able to render
    the string "None" into a prompt, which reaches a model and is never
    noticed.
    """
    items = for_vertical(vertical)
    if not items:
        return ""
    # The framing matters as much as the text. These are examples of the
    # FORM — an observation carried through to a consequence — and calling
    # them anything more would be a claim about quality that the
    # provenance does not support.
    lines = [
        "下面是几段**写法示范**,只示范形式:把看到的东西一路带到判断和后果,"
        "而不是三句互不相干的话。不要模仿它们的内容,也不要套用它们的开头 —— "
        "如果这张照片不适合那样开口,就换一种。",
    ]
    for i, it in enumerate(items, 1):
        lines.append(f"示范 {i}({it['provenance']}):{it['reading']}")
    return "\n".join(lines)
