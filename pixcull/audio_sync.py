"""v0.10-P1-4 — audio-photo sync for the wedding tether flow.

Experimental.  Wedding-day shooters often want photos that
correspond to specific ceremony moments (vows / ring exchange /
first kiss / cake cutting) auto-flagged with the right
``wedding_moment`` so the post-shoot delivery groups them
cleanly.  The hard part is *detecting* the moment in real time —
we offload that to a client (iOS PixCullCompanion with
WhisperKit, or an external CLI hooked to the venue's PA system)
which sends us transcripts.

Wire model
==========
Client posts transcript chunks via:

    POST /api/v1/runs/<run_id>/audio_sync
    body: {
      "transcripts": [
        {"ts_ms": 1700000000000, "text": "I now pronounce you...",
         "confidence": 0.92},
        ...
      ]
    }

We:

1. Run keyword matching against a built-in vocabulary
   (CEREMONY_KEYWORDS below).  Returns the matched moments
   each transcript hit.
2. Correlate transcript ts_ms ± window_s with photo capture
   times (read from scores.csv's mtime column).
3. Boost the wedding_moment field on matched rows.

The keyword vocabulary is intentionally conservative — we want
high precision (false moment tags would mislead the delivery)
at the cost of recall.  A photographer who wants more moments
matched can extend CEREMONY_KEYWORDS in their own deployment.

Opt-in only.  PIXCULL_AUDIO_SYNC=1 env var required to enable
the route; otherwise the POST returns 403.  Privacy guarantee:
audio bytes are NEVER sent to the server — only the transcript
text + timestamps.  WhisperKit on iOS does all the STT locally.
"""

from __future__ import annotations

import os
import re
from typing import Iterable


# Keyword → wedding_moment vocabulary.  Lowercased ASCII keys
# only — clients normalise transcripts to ASCII before sending.
# Format: phrase → moment_id.  ``moment_id`` matches the
# canonical wedding_moment vocabulary used by
# pixcull.scoring.wedding_moment.WEDDING_MOMENTS.
#
# Conservative — only phrases that are extremely unlikely to
# appear outside the corresponding moment.  "ring" alone is
# excluded (it shows up in too many other contexts).  "the
# rings" / "exchange rings" are included because those phrasings
# are strongly ceremony-bound.
CEREMONY_KEYWORDS: dict[str, str] = {
    # Vows
    "i, take you to be my":      "vows",
    "to have and to hold":       "vows",
    "from this day forward":     "vows",
    "for better or for worse":   "vows",
    "till death do us part":     "vows",
    "vows":                       "vows",
    "我愿意":                     "vows",       # Chinese ceremony

    # Ring exchange
    "exchange rings":             "ring_exchange",
    "with this ring":             "ring_exchange",
    "place this ring":            "ring_exchange",
    "the rings":                  "ring_exchange",
    "交换戒指":                   "ring_exchange",

    # First kiss
    "you may now kiss":           "kiss",
    "you may kiss the bride":     "kiss",
    "kiss the bride":             "kiss",
    "kiss the partner":           "kiss",
    "first kiss as":              "kiss",

    # Pronouncement
    "i now pronounce you":        "pronouncement",
    "by the power vested in me":  "pronouncement",
    "husband and wife":           "pronouncement",
    "wife and wife":              "pronouncement",
    "husband and husband":        "pronouncement",

    # First dance
    "first dance":                "first_dance",
    "their first dance":          "first_dance",
    "请新郎新娘跳第一支舞":         "first_dance",

    # Cake cutting
    "cake cutting":               "cake_cutting",
    "cut the cake":               "cake_cutting",
    "cutting the cake":           "cake_cutting",
    "切蛋糕":                     "cake_cutting",

    # Toasts
    "to the bride and groom":     "toast",
    "raise a glass":              "toast",
    "raise our glasses":          "toast",
    "举杯":                       "toast",

    # Chinese-tradition moments
    "敬茶":                       "tea_ceremony",
    "tea ceremony":               "tea_ceremony",
    "三鞠躬":                     "bow",
    "跪拜":                       "bow",
}


# Default time window: when a transcript matches at ts, photos
# whose mtime falls within ±window_s get the wedding_moment
# boost.  90 s is a Goldilocks default — large enough to cover
# "celebrant says 'I now pronounce you...' then 60s of kiss +
# applause" but small enough that consecutive ceremony moments
# (vows then ring then pronouncement) don't all get the same
# tag.  Override via the POST body's `window_s` field.
DEFAULT_WINDOW_S = 90.0


def is_enabled() -> bool:
    """v0.10-P1-4 is opt-in to keep privacy posture conservative.

    Photographers who want it set PIXCULL_AUDIO_SYNC=1 in their
    shell env; the server route returns 403 otherwise so a
    runaway client doesn't accidentally boost wedding moments
    on a run that should have stayed scene-only.
    """
    return os.environ.get("PIXCULL_AUDIO_SYNC", "").strip() in ("1", "true", "yes")


def match_transcript(text: str) -> str | None:
    """Return the wedding_moment matched by this transcript, or None.

    Lowercases the input before matching so the vocab keys can
    stay lowercase.  Uses substring match (not regex) for both
    speed and to keep the vocab obvious to a human auditor.
    Matches the FIRST keyword found scanning the vocab in
    insertion order — most-specific phrases first by convention.
    """
    if not text:
        return None
    t = text.lower()
    for kw, moment in CEREMONY_KEYWORDS.items():
        if kw in t:
            return moment
    return None


def match_transcripts(
    transcripts: Iterable[dict],
    *,
    min_confidence: float = 0.6,
) -> list[dict]:
    """Apply match_transcript to a batch, with confidence gate.

    Returns the SUBSET of transcripts that matched, each enriched
    with the inferred ``moment``.  Drops anything below
    min_confidence (defensive against noisy STT environments;
    weddings are loud).  Order is preserved from the input.
    """
    out = []
    for t in transcripts:
        if not isinstance(t, dict):
            continue
        try:
            ts_ms = int(t.get("ts_ms") or 0)
        except (TypeError, ValueError):
            continue
        try:
            conf = float(t.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        text = str(t.get("text") or "")
        if conf < min_confidence:
            continue
        moment = match_transcript(text)
        if moment is None:
            continue
        out.append({
            "ts_ms":     ts_ms,
            "text":      text,
            "moment":    moment,
            "confidence": conf,
        })
    return out


def correlate_with_rows(
    matches: list[dict],
    rows: list[dict],
    *,
    window_s: float = DEFAULT_WINDOW_S,
) -> dict[str, str]:
    """Assign wedding_moment to photo rows whose mtime falls
    within ±window_s of any transcript match.

    Returns a {filename: moment} dict — caller persists.  Rows
    that fall inside multiple moments' windows take the LATEST
    match (the transcript chronologically closest "before" the
    photo wins, because the photographer typically captures
    AFTER the celebrant says the words).

    Defensive against rows missing mtime: those are skipped
    silently.
    """
    if not matches or not rows:
        return {}
    window_ms = window_s * 1000.0
    sorted_matches = sorted(matches, key=lambda m: m["ts_ms"])
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        fn = row.get("filename")
        if not isinstance(fn, str) or not fn:
            continue
        try:
            # rows store seconds-since-epoch; transcripts ms.
            mtime_ms = float(row.get("mtime") or 0) * 1000.0
        except (TypeError, ValueError):
            continue
        if mtime_ms <= 0:
            continue
        # Walk matches from latest-before to earliest-before so
        # the first valid window wins.
        best: str | None = None
        for m in reversed(sorted_matches):
            if m["ts_ms"] - window_ms <= mtime_ms <= m["ts_ms"] + window_ms:
                best = m["moment"]
                break
        if best is not None:
            out[fn] = best
    return out


def apply_audio_sync(
    transcripts: Iterable[dict],
    rows: list[dict],
    *,
    window_s: float = DEFAULT_WINDOW_S,
    min_confidence: float = 0.6,
) -> dict:
    """Top-level — what the HTTP handler calls.

    Returns the summary the client renders + the suggested
    wedding_moment overrides.  The actual write-back to
    scores.csv / annotations.jsonl is the caller's job (the
    server-side handler decides whether to persist or just
    preview).
    """
    matches = match_transcripts(transcripts, min_confidence=min_confidence)
    suggestions = correlate_with_rows(matches, rows, window_s=window_s)
    return {
        "n_transcripts":  len(list(transcripts) if not isinstance(transcripts, list) else transcripts),
        "n_matched":      len(matches),
        "matches":        matches,
        "n_suggestions":  len(suggestions),
        "suggestions":    suggestions,
        "window_s":       window_s,
    }
