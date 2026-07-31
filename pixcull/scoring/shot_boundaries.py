"""v2.41-P1 — shot-boundary detection, so a reel clip never spans a cut.

DESIGN-AUDIT-2031Q1 flagged this after checking what the video stack
actually does: ``pixcull.detectors.scene.SceneDetector`` is CLIP **scene
classification** (landscape / portrait / event / …).  It answers "what
kind of picture is this", not "did the camera cut here".  Nothing in the
stack detected shot changes.

The consequence is concrete: :func:`pixcull.scoring.reel.sliding_windows`
sweeps fixed-length windows across the whole clip, so a candidate can
straddle a hard cut.  Cut that candidate into a reel and it jumps in the
middle — the single most obvious way an auto-assembled reel looks wrong.

**Optional dependency.**  ``pip install pixcull`` stayed free of
compiled extras when v2.31 unblocked it, and that is worth keeping, so
PySceneDetect (BSD-3-Clause) lives behind ``pixcull[shots]``.  With it
absent every function here degrades to "no cuts found", which makes the
reel behave exactly as it did before — the same contract the audio
tagger (ONNX → DSP) and reel captions (VLM → template) already follow.

Licence note, recorded because it was the deciding factor in the survey:
PySceneDetect is BSD-3 and OpenCV-based, so it composes with PixCull's
MIT licence and adds no new heavy dependency (OpenCV is already
required).  The AGPL-3.0 alternatives surveyed alongside it could not be
vendored without relicensing all of PixCull.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

# PySceneDetect's own default for ContentDetector.  Lower = more cuts.
DEFAULT_THRESHOLD = 27.0
# Below this, two "shots" are really one — a flash, a person crossing
# frame, a one-frame compression artefact.  Merging them keeps a reel
# candidate from being chopped into unusable slivers.
MIN_SHOT_S = 0.6


def available() -> bool:
    """Is the optional shot-detection extra installed?"""
    try:
        import scenedetect  # noqa: F401
        return True
    except Exception:      # noqa: BLE001 — any import failure means "no"
        return False


def detect_cuts(
    video_path: Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_shot_s: float = MIN_SHOT_S,
) -> list[float]:
    """Timestamps (seconds) where the camera cuts.

    Returns the *interior* boundaries only — never 0.0 and never the end
    of the clip — because callers use them to split a timeline, and a
    split at either end is a no-op that only complicates the arithmetic.

    Returns ``[]`` when the extra isn't installed or the video can't be
    read.  A reel with no cut information is the pre-v2.41 behaviour, not
    an error: this is an enhancement, and it must never be the reason a
    cull fails.
    """
    if not available():
        return []
    try:
        from scenedetect import ContentDetector, detect

        scenes = detect(str(video_path), ContentDetector(threshold=threshold))
    except Exception as exc:  # noqa: BLE001
        logger.warning("shot detection failed for %s: %s", video_path, exc)
        return []

    cuts: list[float] = []
    for start, _end in scenes:
        # `.seconds` property; get_seconds() is deprecated in 0.7.x
        t = float(getattr(start, "seconds", None)
                  if getattr(start, "seconds", None) is not None
                  else start.get_seconds())
        if t <= 1e-6:
            continue                      # start of clip, not a cut
        cuts.append(t)
    return merge_close_cuts(cuts, min_shot_s=min_shot_s)


def merge_close_cuts(cuts: Sequence[float], *,
                     min_shot_s: float = MIN_SHOT_S) -> list[float]:
    """Drop cuts that would carve out a shot shorter than ``min_shot_s``.

    Kept separate from :func:`detect_cuts` so it is testable without a
    video file, and so a caller with cuts from another source (a GoPro
    HiLight track, an EDL) can reuse the same smoothing.
    """
    out: list[float] = []
    for t in sorted(float(c) for c in cuts):
        if out and t - out[-1] < min_shot_s:
            continue
        out.append(t)
    return out


def segments_from_cuts(t0: float, t_end: float,
                       cuts: Sequence[float]) -> list[tuple[float, float]]:
    """Turn interior cut points into ``[(start, end), …]`` shot spans.

    With no cuts this returns exactly ``[(t0, t_end)]``, which is what
    makes the reel behaviour identical to pre-v2.41 when the extra isn't
    installed.
    """
    if t_end <= t0:
        return [(t0, t_end)]
    bounds = [t0]
    for c in sorted(float(c) for c in cuts):
        if t0 < c < t_end and c > bounds[-1]:
            bounds.append(c)
    bounds.append(t_end)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
