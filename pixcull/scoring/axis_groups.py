"""v3.5 — ask about two axes at a time instead of six at once.

`vlm_judge.build_prompt` asks a single prompt for all six axes in one
reply. The NTIRE 2026 second-place IQA architecture routed each dimension
to a specialist model instead. This is the prompt-only derivation of that
idea: two or three grouped calls, each with the axes that share evidence,
consolidated afterwards.

THIS IS A DERIVATION, NOT THE PAPER'S METHOD. The Pi Group used separate
specialist sub-models. Whether grouping prompts buys the same per-axis
attention is an open engineering question and must not be described as
implementing their result.

WHY GROUPED AND NOT ONE CALL PER AXIS

Six calls per frame is six times the spend for a benefit nobody has
measured. The groups pair axes that read the same evidence, so each call
has a coherent evidence block rather than the generic all-six one:

    technical + light        exposure, dynamic range, clipping, focus
    subject + moment         faces, expressions, eyes, action, peak
    composition + aesthetic  geometry, balance, colour, the whole frame

WHY THE MERGE REFUSES TO PRODUCE AN OVERALL LABEL

A group that fails leaves its axes unscored. Filling them in — or worse,
computing an overall verdict from the groups that happened to answer —
would produce a confident judgement built on two thirds of the evidence,
with nothing anywhere saying so. `merge()` returns the axes it actually
got and the list of groups that failed, and the caller decides.

OFF BY DEFAULT. `PIXCULL_AXIS_GROUPS=1` turns it on. It multiplies the
per-frame VLM spend by three against an unproven benefit, so it ships as
an arm to measure, not as the path.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Sequence

#: Axes that read the same evidence, grouped. Order is stable so a cache
#: key or an A/B arm name built from it does not drift between runs.
AXIS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("technical", "light"),
    ("subject", "moment"),
    ("composition", "aesthetic"),
)

ENV_FLAG = "PIXCULL_AXIS_GROUPS"


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "0") == "1"


def group_name(group: Sequence[str]) -> str:
    return "+".join(group)


def build_group_prompt(group: Sequence[str], scene: str | None = None,
                       style_section: str = "",
                       vertical: str | None = None) -> str:
    """A prompt asking for exactly the axes in ``group``.

    Built from the same canon, vertical and genre blocks as the six-axis
    prompt — the arms have to differ only in which axes are asked for,
    or the comparison measures two changes at once.
    """
    from pixcull.scoring.vlm_judge import build_prompt

    unknown = [a for a in group if a not in _ALL_AXES]
    if unknown:
        raise ValueError(f"unknown axes: {unknown}")

    full = build_prompt(scene, style_section=style_section,
                        vertical=vertical)
    # Keep everything above the axis list (canon, vertical, genre, style,
    # the comment-quality rules) and replace the schema tail.
    head = full.split("\n★ 含义:", 1)[0]
    lines = "\n".join(f'    "{a}": {{"stars": <1-5>, '
                      f'"rationale": "<基于这张图的具体观察>"}}'
                      + ("," if a != group[-1] else "")
                      for a in group)
    named = "、".join(group)
    return (
        head
        + "\n★ 含义: 1=废片  2=问题明显  3=合格平庸  4=优秀  5=顶级\n\n"
        + f"【这一轮只看 {named}】\n"
        + f"这次只评 {named} 这{len(group)}个维度,其他维度由另一轮单独评,"
          "不要在这里给它们打分,也不要给总判。\n"
          "把注意力全部放在这两个维度上,比一次评六个更仔细。\n\n"
        + "返回 JSON,不要任何额外文字。schema:\n"
        + "{\n  \"axes\": {\n" + lines + "\n  }\n}\n"
    )


def merge(partials: Iterable[tuple[Sequence[str], Any]]) -> dict[str, Any]:
    """Combine per-group replies into one axes dict.

    ``partials`` is ``(group, parsed_or_None)`` pairs. A group whose call
    failed contributes nothing and is named in ``failed_groups``.

    Deliberately returns no ``overall_label``. Two thirds of the axes is
    not a verdict, and a merge that quietly produced one would be the
    exact defect this project keeps finding: a confident answer resting
    on evidence that was never gathered, with nothing saying so.
    """
    axes: dict[str, Any] = {}
    failed: list[str] = []
    for group, parsed in partials:
        got = (parsed or {}).get("axes") if isinstance(parsed, dict) else None
        if not isinstance(got, dict):
            failed.append(group_name(group))
            continue
        wanted = {a: got.get(a) for a in group
                  if isinstance(got.get(a), dict)}
        if len(wanted) != len(group):
            # A group that answered for one of its two axes is a partial
            # answer, not a success. Take what it gave and still record
            # the group, so the caller cannot read this as complete.
            failed.append(group_name(group))
        axes.update(wanted)
    return {
        "axes": axes,
        "failed_groups": failed,
        "complete": not failed and len(axes) == len(_ALL_AXES),
    }


def _all_axes() -> tuple[str, ...]:
    from pixcull.scoring.rubric import RUBRIC_AXES
    return tuple(a.name for a in RUBRIC_AXES)


_ALL_AXES = _all_axes()


def covers_every_axis() -> bool:
    """The groups must partition the rubric — no axis dropped, none twice.

    A silently dropped axis would score every photograph on five axes and
    look exactly like a working system.
    """
    flat = [a for g in AXIS_GROUPS for a in g]
    return sorted(flat) == sorted(_ALL_AXES) and len(flat) == len(set(flat))
