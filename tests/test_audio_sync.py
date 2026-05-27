"""Tests for pixcull.audio_sync — v0.10-P1-4 audio-photo sync."""

from __future__ import annotations

import os

import pytest

from pixcull.audio_sync import (
    CEREMONY_KEYWORDS,
    DEFAULT_WINDOW_S,
    apply_audio_sync,
    correlate_with_rows,
    is_enabled,
    match_transcript,
    match_transcripts,
)


# ---------------------------------------------------------------------------
# is_enabled
# ---------------------------------------------------------------------------


def test_is_enabled_default_off(monkeypatch):
    monkeypatch.delenv("PIXCULL_AUDIO_SYNC", raising=False)
    assert is_enabled() is False


def test_is_enabled_truthy_values(monkeypatch):
    for val in ("1", "true", "yes"):
        monkeypatch.setenv("PIXCULL_AUDIO_SYNC", val)
        assert is_enabled() is True


def test_is_enabled_falsy_values(monkeypatch):
    for val in ("0", "false", "no", "", "maybe"):
        monkeypatch.setenv("PIXCULL_AUDIO_SYNC", val)
        assert is_enabled() is False


# ---------------------------------------------------------------------------
# match_transcript
# ---------------------------------------------------------------------------


def test_match_transcript_vows_phrasings():
    assert match_transcript("I, take you to be my wedded husband") == "vows"
    assert match_transcript("To have and to hold from this day forward") == "vows"
    assert match_transcript("Till death do us part") == "vows"


def test_match_transcript_kiss():
    assert match_transcript("You may now kiss the bride") == "kiss"
    assert match_transcript("KISS THE BRIDE") == "kiss"  # case-insensitive


def test_match_transcript_chinese_ceremony():
    assert match_transcript("我愿意") == "vows"
    assert match_transcript("交换戒指") == "ring_exchange"
    assert match_transcript("敬茶环节") == "tea_ceremony"


def test_match_transcript_returns_none_for_noise():
    assert match_transcript("Welcome everyone please be seated") is None
    assert match_transcript("") is None


def test_match_transcript_first_match_wins():
    # "the rings" should match before "ring exchange" because
    # the vocab is scanned in insertion order, but both map to
    # ring_exchange so the order is harmless here.
    text = "now we exchange rings"
    assert match_transcript(text) == "ring_exchange"


# ---------------------------------------------------------------------------
# match_transcripts (batch + confidence gate)
# ---------------------------------------------------------------------------


def test_match_transcripts_filters_low_confidence():
    out = match_transcripts([
        {"ts_ms": 1000, "text": "you may now kiss", "confidence": 0.95},
        {"ts_ms": 2000, "text": "you may now kiss", "confidence": 0.45},  # below default 0.6
    ])
    assert len(out) == 1
    assert out[0]["confidence"] == 0.95


def test_match_transcripts_preserves_input_order():
    out = match_transcripts([
        {"ts_ms": 1000, "text": "i now pronounce you",   "confidence": 0.9},
        {"ts_ms": 2000, "text": "irrelevant",            "confidence": 0.9},
        {"ts_ms": 3000, "text": "you may now kiss",      "confidence": 0.9},
    ])
    assert [m["ts_ms"] for m in out] == [1000, 3000]
    assert [m["moment"] for m in out] == ["pronouncement", "kiss"]


def test_match_transcripts_drops_non_dict_entries():
    out = match_transcripts([
        None,
        "string",
        {"ts_ms": 1000, "text": "you may kiss the bride", "confidence": 0.9},
    ])
    assert len(out) == 1


# ---------------------------------------------------------------------------
# correlate_with_rows
# ---------------------------------------------------------------------------


def test_correlate_assigns_moment_within_window():
    matches = [
        {"ts_ms": 1_700_000_000_000, "moment": "kiss",
         "text": "you may now kiss"},
    ]
    rows = [
        # 30s before the transcript — within ±90s window
        {"filename": "before.jpg",
         "mtime": 1_700_000_000.0 - 30.0},
        # 60s after — within ±90s window
        {"filename": "after.jpg",
         "mtime": 1_700_000_000.0 + 60.0},
        # 120s after — outside ±90s window
        {"filename": "way_after.jpg",
         "mtime": 1_700_000_000.0 + 120.0},
    ]
    out = correlate_with_rows(matches, rows)
    assert out == {"before.jpg": "kiss", "after.jpg": "kiss"}


def test_correlate_picks_latest_match_when_multiple_in_window():
    """Within overlapping windows, the chronologically-latest
    BEFORE the photo wins (the celebrant says the words, photo
    captures the reaction shortly after)."""
    matches = [
        {"ts_ms": 1_700_000_000_000, "moment": "vows",
         "text": "...vows..."},
        {"ts_ms": 1_700_000_060_000, "moment": "kiss",
         "text": "...kiss..."},
    ]
    # Photo captured 65s after vows (5s after kiss) — both within
    # ±90s, but kiss is the latest match BEFORE the photo (closest)
    rows = [{"filename": "p.jpg", "mtime": 1_700_000_065.0}]
    out = correlate_with_rows(matches, rows)
    assert out == {"p.jpg": "kiss"}


def test_correlate_skips_rows_without_mtime():
    matches = [{"ts_ms": 1_700_000_000_000, "moment": "kiss", "text": "x"}]
    rows = [
        {"filename": "no_mtime.jpg"},
        {"filename": "zero_mtime.jpg", "mtime": 0},
        {"filename": "bad_mtime.jpg", "mtime": "not-a-number"},
    ]
    out = correlate_with_rows(matches, rows)
    assert out == {}


def test_correlate_custom_window():
    """A tighter window changes which photos get tagged."""
    matches = [
        {"ts_ms": 1_700_000_000_000, "moment": "kiss", "text": "x"},
    ]
    rows = [
        # 30s after — should land in default 90s window, miss 10s window
        {"filename": "p1.jpg", "mtime": 1_700_000_000.0 + 30.0},
    ]
    assert correlate_with_rows(matches, rows, window_s=90) == {"p1.jpg": "kiss"}
    assert correlate_with_rows(matches, rows, window_s=10) == {}


# ---------------------------------------------------------------------------
# apply_audio_sync — full pipeline
# ---------------------------------------------------------------------------


def test_apply_audio_sync_end_to_end():
    transcripts = [
        {"ts_ms": 1_700_000_000_000, "text": "you may now kiss",
         "confidence": 0.9},
        {"ts_ms": 1_700_000_120_000, "text": "first dance",
         "confidence": 0.85},
        # Below confidence — dropped
        {"ts_ms": 1_700_000_200_000, "text": "kiss the bride",
         "confidence": 0.3},
    ]
    rows = [
        # Within kiss window
        {"filename": "k1.jpg", "mtime": 1_700_000_005.0},
        # Within first_dance window
        {"filename": "d1.jpg", "mtime": 1_700_000_125.0},
        # Far from both
        {"filename": "noise.jpg", "mtime": 1_701_000_000.0},
    ]
    out = apply_audio_sync(transcripts, rows)
    assert out["n_transcripts"] == 3
    assert out["n_matched"] == 2       # 1 dropped by confidence
    assert out["suggestions"]["k1.jpg"] == "kiss"
    assert out["suggestions"]["d1.jpg"] == "first_dance"
    assert "noise.jpg" not in out["suggestions"]
    assert out["window_s"] == DEFAULT_WINDOW_S


# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


def test_vocabulary_keys_lowercase_or_chinese():
    """Mixed-case English keys would silently fail the match
    (we lowercase the input before scanning the vocab)."""
    for kw in CEREMONY_KEYWORDS:
        # Allow CJK; reject mixed-case Latin
        latin = "".join(c for c in kw if c.isascii())
        if latin:
            assert latin.lower() == latin, f"non-lowercase vocab key: {kw!r}"


def test_vocabulary_values_are_canonical_moment_ids():
    """The wedding_moment vocabulary used elsewhere in the
    pipeline (rubric, share page, executive PDF) speaks a
    closed set of IDs — keep our audio mapping inside it."""
    canonical = {
        "vows", "ring_exchange", "kiss", "pronouncement",
        "first_dance", "cake_cutting", "toast",
        "tea_ceremony", "bow",
    }
    for moment in CEREMONY_KEYWORDS.values():
        assert moment in canonical, f"unknown moment id: {moment!r}"
