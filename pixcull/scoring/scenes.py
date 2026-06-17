"""v2.9-P1-1 — Scenes 时序叙事分组 (Narrative Select's Scenes View).

Segment a run's photos into chronological *scenes* by capture-time gaps: a
scene boundary falls where the gap to the next frame is anomalously large
versus the run's own cadence.  The threshold is adaptive — ``median + k·MAD``
of the inter-frame gaps, floored at a minimum — so a wedding's continuous
shooting rhythm doesn't fragment into hundreds of scenes, while the genuine
jump (bus ride → ceremony → reception) does start a new one.

Design notes
------------
* **Robust, not parametric.**  Median + MAD (median absolute deviation) is
  outlier-resistant; one huge gap won't inflate the threshold the way mean+σ
  would, so the very boundary we want to detect can't hide itself.
* **Honest fallbacks.**  Photos without a parseable timestamp never vanish —
  they collect into a trailing "未记录时间" scene.  A run with <2 timestamps
  is a single scene (nothing to segment on).
* **Pure + deterministic.**  No I/O, no clock reads; the serve layer hands in
  ``{filename, timestamp}`` dicts and gets back ``Scene`` objects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

# Capture-time strings we may see: pipeline writes ``str(datetime)`` →
# "YYYY-MM-DD HH:MM:SS"; raw EXIF uses colons in the date; ISO-T also appears.
_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)

# Defaults tuned for event/wedding cadence: a ≥3·MAD gap *and* at least 2 min
# of silence starts a new scene.
DEFAULT_K = 3.0
DEFAULT_MIN_GAP_S = 120.0
_MAD_TO_SIGMA = 1.4826   # scales MAD to σ for a normal distribution


def parse_timestamp(value) -> Optional[float]:
    """Best-effort conversion to epoch seconds. Accepts ``datetime``, an epoch
    number, or a common date string; returns ``None`` when unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    s = str(value).strip()
    if not s:
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    try:                       # last resort: 3.7+ flexible ISO parser
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


@dataclass
class Scene:
    """A chronological cluster of frames.  ``start_ts`` / ``end_ts`` are epoch
    seconds (None for the untimed trailing scene)."""
    index: int
    filenames: list
    start_ts: Optional[float]
    end_ts: Optional[float]

    @property
    def n(self) -> int:
        return len(self.filenames)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


def adaptive_gap_threshold(gaps: Sequence[float], k: float = DEFAULT_K,
                           min_gap_s: float = DEFAULT_MIN_GAP_S) -> float:
    """``max(min_gap_s, median + k·1.4826·MAD)`` over the inter-frame gaps.

    With a perfectly uniform cadence (MAD = 0) this collapses to the median,
    floored at ``min_gap_s`` — so only a gap longer than typical *and* longer
    than the floor breaks a scene.
    """
    gaps = list(gaps)
    if not gaps:
        return min_gap_s
    med = _median(gaps)
    mad = _median([abs(g - med) for g in gaps])
    return max(min_gap_s, med + k * _MAD_TO_SIGMA * mad)


def segment_scenes(items: Sequence[dict], *, k: float = DEFAULT_K,
                   min_gap_s: float = DEFAULT_MIN_GAP_S) -> list[Scene]:
    """Group ``items`` (dicts with ``filename`` + ``timestamp``) into scenes.

    ``timestamp`` may be a ``datetime``, epoch number, date string, or None.
    Output scenes are chronological; untimed frames form a trailing scene so
    nothing is dropped.
    """
    timed: list[tuple[float, str]] = []
    untimed: list[str] = []
    for it in items:
        fn = it.get("filename")
        if not fn:
            continue
        ts = parse_timestamp(it.get("timestamp"))
        if ts is None:
            untimed.append(fn)
        else:
            timed.append((ts, fn))

    scenes: list[Scene] = []
    if len(timed) < 2:
        # Nothing to segment on — one scene of everything, input order kept.
        fns = [fn for _, fn in timed] + untimed
        if fns:
            ts0 = timed[0][0] if timed else None
            scenes.append(Scene(0, fns, ts0, ts0))
        return scenes

    timed.sort(key=lambda t: t[0])
    gaps = [timed[i + 1][0] - timed[i][0] for i in range(len(timed) - 1)]
    thr = adaptive_gap_threshold(gaps, k=k, min_gap_s=min_gap_s)

    current: list[tuple[float, str]] = [timed[0]]
    groups: list[list[tuple[float, str]]] = []
    for i in range(1, len(timed)):
        if timed[i][0] - timed[i - 1][0] > thr:
            groups.append(current)
            current = [timed[i]]
        else:
            current.append(timed[i])
    groups.append(current)

    for idx, grp in enumerate(groups):
        scenes.append(Scene(
            index=idx,
            filenames=[fn for _, fn in grp],
            start_ts=grp[0][0],
            end_ts=grp[-1][0],
        ))
    if untimed:
        scenes.append(Scene(len(scenes), untimed, None, None))
    return scenes
