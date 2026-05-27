"""v0.10-P2-3 — opt-in crash reporting via Sentry.

Default: **OFF**.  Photographers' photos never leave the machine
— the same posture extends to telemetry.  This module is a
thin shim around the optional ``sentry-sdk`` package so:

  * No telemetry fires unless ``PIXCULL_TELEMETRY=share`` or
    ``=minimal`` is set in the environment.
  * Filename / image-bytes / API-key / DeepSeek-key / share-token
    payloads are scrubbed from every event before send.
  * The before-send hook is the only safety net — but it's a
    HARD safety net (returns None → event dropped).

Three opt-in tiers
==================

  * ``off`` — default; no events anywhere.
  * ``minimal`` — only crashes (uncaught exceptions in serve_demo,
    ONNX runtime errors, Sparkle update failures).  No
    breadcrumbs, no transaction sampling.
  * ``share`` — crashes + 1% transaction sampling for the
    photo-pipeline hot paths (analyze_one, face cluster,
    rubric_decompose).  Used by the project owner only.

The tier is read from the ``PIXCULL_TELEMETRY`` env var at first
``init()`` call; subsequent calls are no-ops so the tier can't
be silently bumped mid-session.
"""

from __future__ import annotations

import os
from typing import Any


# Sentry DSN — public, since the project is OSS and the DSN is
# just an event-ingestion endpoint (no auth secret).  Override
# via PIXCULL_SENTRY_DSN if you want to point at your own
# self-hosted Sentry; we keep the default empty so nothing
# accidentally ships to a 3rd-party endpoint without the user
# opting in twice (env var + non-empty DSN).
DEFAULT_DSN = ""


_INITIALIZED = False
_TIER = "off"


def _get_tier() -> str:
    raw = os.environ.get("PIXCULL_TELEMETRY", "").strip().lower()
    return raw if raw in ("off", "minimal", "share") else "off"


def _scrub_event(event: dict, hint: Any) -> dict | None:
    """Before-send hook.  HARD safety net: anything that smells
    private gets dropped or scrubbed.

    Returns None → Sentry drops the event entirely.  Returns
    the (mutated) dict → ships.
    """
    if not isinstance(event, dict):
        return None

    # 1. Strip user-data fields we never want to ship — filenames,
    # paths, image hashes, API keys.  Walk request + extra payloads.
    SCRUB_KEYS = {
        "filename", "filenames", "path", "paths", "image_path",
        "image_hash", "image_hashes", "thumb_url", "full_url",
        "deepseek_api_key", "api_key", "X-PixCull-API-Key",
        "share_token", "event_token", "token", "client_id",
        "edited_by", "display_name", "user_id",
        # Sentry's own user dict (we don't want to ship IPs)
        "user", "remote_addr", "ip_address",
    }
    def _scrub_dict(d: dict) -> None:
        for k in list(d.keys()):
            if k.lower() in SCRUB_KEYS:
                d[k] = "<scrubbed>"
            elif isinstance(d[k], dict):
                _scrub_dict(d[k])
            elif isinstance(d[k], list):
                for x in d[k]:
                    if isinstance(x, dict):
                        _scrub_dict(x)
    _scrub_dict(event)

    # 2. Drop the entire request body — we never want to ship POST
    # payloads (could carry annotations / photographer notes).
    req = event.get("request") if isinstance(event.get("request"), dict) else None
    if req:
        req.pop("data", None)
        req.pop("cookies", None)
        # Headers — keep only User-Agent for crash debugging
        headers = req.get("headers")
        if isinstance(headers, dict):
            req["headers"] = {"User-Agent": headers.get("User-Agent", "")}

    # 3. Stack frames — keep the trace but drop the locals
    # (locals would carry filenames + ImageData / face embeddings).
    exc = event.get("exception")
    if isinstance(exc, dict):
        values = exc.get("values")
        if isinstance(values, list):
            for v in values:
                if isinstance(v, dict):
                    st = v.get("stacktrace")
                    if isinstance(st, dict):
                        frames = st.get("frames")
                        if isinstance(frames, list):
                            for fr in frames:
                                if isinstance(fr, dict):
                                    fr.pop("vars", None)

    return event


def init(*, dsn: str | None = None, release: str | None = None) -> bool:
    """Initialise Sentry IFF the user opted in.

    Returns True when telemetry is now live; False when:
      * PIXCULL_TELEMETRY is unset / off
      * sentry_sdk isn't installed (also fine — graceful degrade)
      * the DSN is empty (the user explicitly nulled it out)
      * init() was already called once (idempotent)

    No-op safe to call on every server boot.
    """
    global _INITIALIZED, _TIER
    if _INITIALIZED:
        return _TIER != "off"
    _INITIALIZED = True
    tier = _get_tier()
    # Don't commit to the tier until ALL preconditions pass —
    # otherwise is_active() can report on a tier that never
    # actually called sentry_sdk.init().
    if tier == "off":
        _TIER = "off"
        return False
    try:
        import sentry_sdk  # type: ignore
    except ImportError:
        _TIER = "off"
        return False
    # DSN resolution: explicit arg > env > default constant
    effective_dsn = (
        dsn
        or os.environ.get("PIXCULL_SENTRY_DSN", "").strip()
        or DEFAULT_DSN
    )
    if not effective_dsn:
        _TIER = "off"
        return False
    _TIER = tier   # commit only after all gates passed
    sample_rate = 0.01 if tier == "share" else 0.0
    sentry_sdk.init(
        dsn=effective_dsn,
        release=release,
        environment=os.environ.get("PIXCULL_ENV", "production"),
        before_send=_scrub_event,
        traces_sample_rate=sample_rate,
        send_default_pii=False,        # belt + braces
        max_breadcrumbs=0 if tier == "minimal" else 30,
        attach_stacktrace=True,
    )
    return True


def get_tier() -> str:
    """Returns whichever tier init() actually configured.
    Useful for the /admin page banner ('Telemetry: share' etc.)."""
    return _TIER


def is_active() -> bool:
    return _INITIALIZED and _TIER != "off"
