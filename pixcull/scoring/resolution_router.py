"""v3.17 — send the frames that need pixels at full size, and only those.

`VLM_RESIZE_LONG_EDGE = 1024` is applied to every image the judge sees.
The charter said `resize_long_edge` was already a per-call argument on
both judges; it is a CONSTRUCTOR argument, so the per-call path had to be
built before any routing could exist. Third premise in this block that
needed re-deriving.

The principle comes from InternVL3.5's Visual Resolution Router, whose
~50% visual-token reduction survived fact-check — and whose benchmark and
Apple-Silicon deployability claims did not. Lightroom's Assisted Culling
runs inference on Smart Previews rather than full RAW for the same
reason. Only the principle is borrowed.

WHICH WAY THE ROUTER IS ALLOWED TO BE WRONG

Downgrading the wrong frame is not a cost saving, it is a worse verdict.
The axes that live in pixels are exactly the ones a naive router would
strip: whether the eyes are sharp inside a face that is 3% of the frame,
whether the focus landed on the eyelashes or the ear. So the rules are
asymmetric on purpose:

  * a frame with any detected face NEVER goes below the default. Eye
    sharpness is the single most decision-relevant thing in portrait,
    wedding and event work, and it is measured in pixels.
  * a frame whose sharpness sits anywhere near the boundary NEVER goes
    below the default. Those are the frames where the answer is not
    already known.
  * everything else — a frame that is unambiguously sharp or
    unambiguously soft, with nobody in it — can go down.

So the router only ever downgrades frames whose verdict the cheap local
detectors already agree on. It cannot save anything on the hard cases,
which is the correct shape: the hard cases are what the judge is for.

Off unless PIXCULL_RESOLUTION_ROUTER=1. It changes what the model sees,
and the measure that would earn the default is per-axis — an aggregate
would hide the exact regression this design is built to avoid.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from pixcull.scoring.vlm_judge import VLM_RESIZE_LONG_EDGE

ENV_FLAG = "PIXCULL_RESOLUTION_ROUTER"

#: The only sizes the router may pick. A closed set, so a cache keyed on
#: the chosen edge has a bounded number of slots per frame rather than
#: one per arbitrary integer.
LOW = 640
DEFAULT = VLM_RESIZE_LONG_EDGE          # 1024
SIZES = (LOW, DEFAULT)

#: Laplacian variance below which a frame is unambiguously soft, and
#: above which it is unambiguously sharp. Between them the frame is a
#: judgement call and keeps its pixels.
#:
#: The gap is deliberately wide. A narrow band would route most frames
#: down and save the most, which is the temptation this whole module is
#: shaped against.
SOFT_BELOW = 40.0
SHARP_ABOVE = 600.0


@dataclass(frozen=True)
class Route:
    long_edge: int
    reason: str

    @property
    def downgraded(self) -> bool:
        return self.long_edge < DEFAULT


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "0") == "1"


def route(row: dict[str, Any] | None) -> Route:
    """Pick a long edge for one frame, with the reason it was picked.

    The reason is not decoration. A router whose decisions cannot be
    explained cannot be reviewed when a per-axis number moves, and
    "the router did it" is not a diagnosis.
    """
    if not enabled():
        return Route(DEFAULT, "router off")
    row = row or {}

    faces = row.get("face_count")
    if faces is not None:
        # A face_count that is PRESENT but unreadable — NaN from a
        # DataFrame, a string from a hand-edited CSV — is not "nobody
        # here". Reading it as zero is how a portrait gets stripped of
        # the pixels its eyes live in, and it is a one-line difference
        # from the correct behaviour.
        try:
            n_faces = int(faces)
        except (TypeError, ValueError):
            return Route(DEFAULT, "face count unreadable")
        if n_faces != n_faces:              # NaN survived int()
            return Route(DEFAULT, "face count unreadable")
        if n_faces > 0:
            return Route(DEFAULT,
                         f"{n_faces} face(s): eye sharpness is pixels")

    lap = row.get("laplacian_subject")
    if lap is None:
        lap = row.get("laplacian_global")
    try:
        lap_f = float(lap)
    except (TypeError, ValueError):
        # No sharpness reading at all. Unknown is not "easy" — a frame
        # the detectors could not measure is the last one to strip.
        return Route(DEFAULT, "no sharpness reading")
    if lap_f != lap_f:                       # NaN
        return Route(DEFAULT, "sharpness is NaN")

    if lap_f < SOFT_BELOW:
        return Route(LOW, f"unambiguously soft ({lap_f:.0f} < {SOFT_BELOW:.0f})")
    if lap_f > SHARP_ABOVE:
        return Route(LOW, f"unambiguously sharp ({lap_f:.0f} > {SHARP_ABOVE:.0f})")
    return Route(DEFAULT, f"sharpness near the boundary ({lap_f:.0f})")
