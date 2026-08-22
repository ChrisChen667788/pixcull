"""v2.74 — name a stretch of a shoot from what is measurably in it.

Narrative Select's Scenes view is the one competitor capability this
product lacked outright, and reviewers single it out: you cull in story
order — ceremony, cocktail hour, reception — rather than image by image.

PixCull already segments on capture-time gaps and already renders a
strip of chips. The chips said `场景 1` … `场景 28`. An index is not a
name; it tells you nothing you could not get by counting.

**What this module will not do is invent the event.** It has EXIF
timestamps and a scene classifier, and neither of those knows that the
17:00 stretch is the ceremony. Guessing would be the most useful-looking
and least honest thing available, and this repo has a name for a claim
nothing checks.

So a label is built from two things that are actually known:

* **when** — the hour band, from capture time.
* **what** — the dominant scene, but only when it really dominates.
  Plurality is not dominance: one real stretch here is 10 `fashion`
  frames out of 29, and calling that "时尚" would describe a third of
  the photographs and mislead about the rest. Below the threshold the
  label says the time and stops.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

#: A scene name goes on the chip only if it covers at least this much of
#: the stretch. 10 of 29 is a plurality and not a description.
DOMINANT_SHARE = 0.5

#: A stretch shorter than this is a stray frame between two sessions, not
#: a beat of the shoot. It keeps its frames and its place; it just does
#: not get announced as a chapter.
MIN_STRETCH = 3

_HOUR_BANDS = (
    (5, "清晨"), (8, "上午"), (11, "中午"), (14, "下午"),
    (17, "傍晚"), (20, "夜晚"),
)


@dataclass(frozen=True)
class SceneLabel:
    hour_band: str
    dominant_scene: str        # "" when nothing dominates
    dominant_share: float
    n: int
    is_stray: bool             # too short to announce as a chapter

    @property
    def key(self) -> str:
        """i18n key for the scene half, or "" when there is no name."""
        return f"scene.{self.dominant_scene}" if self.dominant_scene else ""


def hour_band(hour: int | None) -> str:
    if hour is None:
        return ""
    band = _HOUR_BANDS[-1][1]
    for start, name in _HOUR_BANDS:
        if hour < start:
            break
        band = name
    return band


def label_stretch(scenes: list[str], hour: int | None, n: int) -> SceneLabel:
    """``scenes`` is the per-frame scene classification for one stretch."""
    named = [s for s in scenes if s and s != "unknown"]
    dom, share = "", 0.0
    if named:
        top, count = Counter(named).most_common(1)[0]
        share = count / max(1, n)
        if share >= DOMINANT_SHARE:
            dom = top
    return SceneLabel(hour_band=hour_band(hour), dominant_scene=dom,
                      dominant_share=round(share, 3), n=n,
                      is_stray=n < MIN_STRETCH)
