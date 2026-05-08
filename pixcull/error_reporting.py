r"""V14.7 — opt-in error reporting framework (defaults OFF).

Why this is just a skeleton
---------------------------
There is no shared backend Sentry/PostHog endpoint for this app yet.
The user (or future maintainer) wires their own endpoint into
``error_reports_endpoint`` in config.json. Until then:

* The toggle is OFF by default. Nothing is collected, nothing is sent.
* When ON but no endpoint configured, ``submit_report`` returns a
  ``would_send`` payload — useful for debugging the redaction pipeline
  before pointing at a real server.
* When ON with a configured endpoint, we POST a redacted payload to
  it. The function still returns the payload so the UI can show the
  user exactly what was sent.

What gets collected (and what doesn't)
--------------------------------------
Always included:
    * App version, OS name / version
    * Recent stderr log tail (default last 200 lines), redacted

Redactions applied to every string that ships:
    * ``/Users/<name>``           → ``/Users/<redacted>``
    * ``/home/<name>``            → ``/home/<redacted>``
    * ``C:\Users\<name>``         → ``C:\Users\<redacted>``
    * ``sk-[0-9a-zA-Z]{20,}``     → ``sk-***`` (DeepSeek / OpenAI keys)
    * ``Bearer [a-zA-Z0-9._-]+``  → ``Bearer ***``
    * email-like patterns         → ``<email>``

Never included:
    * Image filenames, full paths, image bytes
    * License tokens
    * The user's annotation text
    * Any /annotation or /export request payloads

The user MUST opt in via the admin page. The toggle writes
``error_reports_enabled: true`` to config.json. They can also paste
an endpoint URL — if blank, the module runs in dry-run mode.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


# -----------------------------------------------------------------------------
# Config + state
# -----------------------------------------------------------------------------

DEFAULT_LOG_TAIL = 200          # lines from the most recent stderr log
SUBMIT_TIMEOUT_S = 8            # don't hang the menu app if the endpoint is dead


def is_enabled(cfg: dict) -> bool:
    """Single source of truth for whether reports may be sent."""
    return bool(cfg.get("error_reports_enabled"))


def endpoint(cfg: dict) -> str:
    """Where to POST the redacted payload. Empty string = dry run."""
    return str(cfg.get("error_reports_endpoint", "") or "").strip()


# -----------------------------------------------------------------------------
# Redaction
# -----------------------------------------------------------------------------

# Keep the patterns conservative — we'd rather miss a redaction class than
# accidentally blank out a useful traceback line. False positives here
# directly hurt the value of the report.
_REDACT_PATTERNS = [
    # Mac & Linux home dirs.  /Users/foo/...  →  /Users/<redacted>/...
    (re.compile(r"(/Users/)[^/\s'\"]+"),  r"\1<redacted>"),
    (re.compile(r"(/home/)[^/\s'\"]+"),   r"\1<redacted>"),
    # Windows.  C:\Users\foo\...  →  C:\Users\<redacted>\...
    (re.compile(r"([A-Za-z]:\\Users\\)[^\\\s'\"]+"),
                                          r"\1<redacted>"),
    # API keys: DeepSeek / OpenAI / Anthropic style sk-... tokens.
    (re.compile(r"sk-[0-9a-zA-Z_-]{20,}"), "sk-***"),
    # Bearer tokens.
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer ***"),
    # Hugging Face hf_... tokens.
    (re.compile(r"hf_[0-9a-zA-Z]{20,}"),  "hf_***"),
    # AWS-style access keys.
    (re.compile(r"AKIA[0-9A-Z]{16}"),     "AKIA***"),
    # Email addresses.
    (re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
                                          "<email>"),
]


def redact(text: str) -> str:
    """Run all redaction patterns over ``text`` and return the cleaned string.

    Idempotent — re-running on already-redacted text leaves it alone.
    Whitespace is preserved exactly.
    """
    if not text:
        return text
    for pat, repl in _REDACT_PATTERNS:
        text = pat.sub(repl, text)
    return text


# -----------------------------------------------------------------------------
# Log gathering
# -----------------------------------------------------------------------------

def find_recent_log(log_dir: Path) -> Path | None:
    """Return the most recently modified pixcull_YYYY-MM-DD.log, or None."""
    if not log_dir.exists():
        return None
    candidates = sorted(
        log_dir.glob("pixcull_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def gather_recent_log(log_dir: Path,
                      max_lines: int = DEFAULT_LOG_TAIL) -> str:
    """Read the tail of the most recent stderr log, redacted.

    Returns an empty string if there's no log file. Caps the number of
    lines so we don't ship a 50 MB log to a remote endpoint.
    """
    fp = find_recent_log(log_dir)
    if fp is None:
        return ""
    try:
        # Cheap tail: read the whole file (logs are line-buffered and
        # typically <1 MB after a session) then slice. If logs grow big,
        # swap this for a seek-from-end implementation.
        text = fp.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()[-max_lines:]
        return redact("\n".join(lines))
    except OSError:
        return ""


# -----------------------------------------------------------------------------
# Payload + submit
# -----------------------------------------------------------------------------

def build_payload(app_version: str,
                  log_dir: Path,
                  *,
                  reason: str = "manual",
                  extra: dict | None = None,
                  log_tail_lines: int = DEFAULT_LOG_TAIL) -> dict:
    """Assemble the JSON we'd ship to a remote endpoint.

    ``reason`` distinguishes manual ("user clicked submit") from
    auto-on-crash ("worker raised") so a server-side dashboard can
    bucket them differently.
    """
    return {
        "schema":      "pixcull.error_report.v1",
        "app_version": app_version,
        "reason":      reason,
        "ts":          time.time(),
        "platform": {
            "system":       platform.system(),
            "release":      platform.release(),
            "machine":      platform.machine(),
            "python":       platform.python_version(),
        },
        "log_tail":    gather_recent_log(log_dir, max_lines=log_tail_lines),
        "extra":       extra or {},
    }


def submit_report(cfg: dict,
                  app_version: str,
                  log_dir: Path,
                  *,
                  reason: str = "manual",
                  extra: dict | None = None) -> dict:
    """POST a redacted payload to the configured endpoint.

    Returns a dict describing what happened:
        {sent: bool, status: int|None, payload: dict, message: str}

    Cases:
        * disabled        → ``sent=False, message="opt-in disabled"``
        * no endpoint     → ``sent=False, message="dry run"`` plus the
                            payload so the user can preview what would ship
        * HTTP failure    → ``sent=False, status=<code>, message=<reason>``
        * success         → ``sent=True, status=2xx``
    """
    if not is_enabled(cfg):
        return {
            "sent":    False,
            "status":  None,
            "payload": None,
            "message": "未开启错误上报",
        }

    payload = build_payload(app_version, log_dir,
                              reason=reason, extra=extra)

    ep = endpoint(cfg)
    if not ep:
        return {
            "sent":    False,
            "status":  None,
            "payload": payload,
            "message": "已开启,但未配置 endpoint(dry run — 查看上方 payload 即可)",
        }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ep,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent":   f"PixCull/{app_version} error-reporter",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=SUBMIT_TIMEOUT_S) as resp:
            return {
                "sent":    True,
                "status":  resp.status,
                "payload": payload,
                "message": "已发送",
            }
    except urllib.error.HTTPError as exc:
        return {
            "sent":    False,
            "status":  exc.code,
            "payload": payload,
            "message": f"HTTP {exc.code} {exc.reason}",
        }
    except (urllib.error.URLError, OSError) as exc:
        return {
            "sent":    False,
            "status":  None,
            "payload": payload,
            "message": f"网络错误: {type(exc).__name__}: {exc}",
        }


__all__ = [
    "is_enabled",
    "endpoint",
    "redact",
    "find_recent_log",
    "gather_recent_log",
    "build_payload",
    "submit_report",
]
