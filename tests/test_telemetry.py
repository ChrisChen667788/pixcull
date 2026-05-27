"""Tests for pixcull.telemetry — v0.10-P2-3 opt-in crash reporting.

The hard contract: telemetry must be OFF by default, must scrub
filenames + tokens + API keys before send, and must be a no-op
when sentry_sdk isn't installed.
"""

from __future__ import annotations

import importlib

import pytest


def _fresh():
    """Return a freshly-imported telemetry module so the global
    _INITIALIZED state doesn't leak between tests."""
    import pixcull.telemetry as t
    importlib.reload(t)
    return t


def test_default_is_off(monkeypatch):
    monkeypatch.delenv("PIXCULL_TELEMETRY", raising=False)
    t = _fresh()
    assert t._get_tier() == "off"
    assert t.init() is False
    assert t.is_active() is False
    assert t.get_tier() == "off"


def test_unknown_tier_treated_as_off(monkeypatch):
    monkeypatch.setenv("PIXCULL_TELEMETRY", "all-the-things")
    t = _fresh()
    assert t._get_tier() == "off"
    assert t.init() is False


def test_init_is_idempotent(monkeypatch):
    """A second init() call returns the cached state, not a fresh
    Sentry init.  Lets serve_demo + cli + worker subprocesses
    all call init() at boot without spinning up multiple SDKs."""
    monkeypatch.delenv("PIXCULL_TELEMETRY", raising=False)
    t = _fresh()
    t.init()
    t.init()
    assert t.get_tier() == "off"


def test_empty_dsn_keeps_telemetry_off(monkeypatch):
    """Even with PIXCULL_TELEMETRY=share, telemetry stays off
    until the user (or operator) provides a non-empty DSN —
    final layer of defence against accidental opt-in."""
    monkeypatch.setenv("PIXCULL_TELEMETRY", "share")
    monkeypatch.delenv("PIXCULL_SENTRY_DSN", raising=False)
    t = _fresh()
    assert t.init() is False
    assert t.is_active() is False


def test_init_returns_false_when_sentry_sdk_missing(monkeypatch):
    """When the user opts in but sentry-sdk isn't installed,
    we degrade gracefully (no ImportError leaking out)."""
    monkeypatch.setenv("PIXCULL_TELEMETRY", "share")
    monkeypatch.setenv("PIXCULL_SENTRY_DSN", "https://fake@example/1")
    # Best-effort: force-blank the sentry_sdk import to simulate
    # the missing-dep environment.  This only works if sentry_sdk
    # isn't actually installed — otherwise we accept that the
    # real init runs (which is harmless because the DSN is fake).
    import sys
    if "sentry_sdk" in sys.modules:
        pytest.skip("sentry_sdk installed; can't simulate missing dep")
    t = _fresh()
    # init returns False (graceful no-op) when the dep is gone.
    assert t.init() is False


# ---------------------------------------------------------------------------
# Scrubbing
# ---------------------------------------------------------------------------


def test_scrub_removes_user_keys(monkeypatch):
    monkeypatch.delenv("PIXCULL_TELEMETRY", raising=False)
    t = _fresh()
    event = {
        "extra": {
            "filename":         "IMG_001.jpg",
            "share_token":      "abcdef",
            "deepseek_api_key": "sk-XYZ",
            "harmless_field":   42,
        }
    }
    out = t._scrub_event(event, None)
    assert out is not None
    assert out["extra"]["filename"] == "<scrubbed>"
    assert out["extra"]["share_token"] == "<scrubbed>"
    assert out["extra"]["deepseek_api_key"] == "<scrubbed>"
    # Harmless fields untouched
    assert out["extra"]["harmless_field"] == 42


def test_scrub_drops_request_body():
    """POST bodies could carry photographer notes / annotations —
    drop wholesale rather than try to inspect them."""
    t = _fresh()
    event = {
        "request": {
            "data":    "rubric_stars=5",   # private!
            "cookies": "session=abc",       # ditto
            "headers": {
                "User-Agent":           "PixCull/0.10",
                "X-PixCull-API-Key":    "secret-key",
            },
        }
    }
    out = t._scrub_event(event, None)
    assert "data" not in out["request"]
    assert "cookies" not in out["request"]
    # User-Agent kept (useful for crash debugging)
    assert out["request"]["headers"] == {"User-Agent": "PixCull/0.10"}


def test_scrub_drops_stack_locals():
    """Local variable dumps from each stack frame would expose
    filenames + image arrays + face embeddings."""
    t = _fresh()
    event = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "analyze_one",
                                "vars": {
                                    "filename":      "secret.jpg",
                                    "image_data":    [1, 2, 3],
                                    "face_embedding": [0.1, 0.2],
                                },
                            }
                        ]
                    }
                }
            ]
        }
    }
    out = t._scrub_event(event, None)
    frame = out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame
    assert frame["function"] == "analyze_one"


def test_scrub_returns_none_for_non_dict():
    """Hostile input → drop the whole event."""
    t = _fresh()
    assert t._scrub_event("not-a-dict", None) is None  # type: ignore[arg-type]
    assert t._scrub_event(None, None) is None
    assert t._scrub_event([], None) is None  # type: ignore[arg-type]


def test_scrub_walks_nested_dicts():
    t = _fresh()
    event = {
        "tags": {
            "deeply": {
                "nested": {
                    "client_id": "user-abc",
                }
            }
        }
    }
    out = t._scrub_event(event, None)
    assert out["tags"]["deeply"]["nested"]["client_id"] == "<scrubbed>"


def test_scrub_walks_list_of_dicts():
    """request.frames or breadcrumbs are often lists of dicts."""
    t = _fresh()
    event = {
        "breadcrumbs": {
            "values": [
                {"category": "http", "data": {"filename": "x.jpg"}},
                {"category": "ui",   "data": {"event_token": "abc"}},
            ]
        }
    }
    out = t._scrub_event(event, None)
    crumbs = out["breadcrumbs"]["values"]
    assert crumbs[0]["data"]["filename"] == "<scrubbed>"
    assert crumbs[1]["data"]["event_token"] == "<scrubbed>"
