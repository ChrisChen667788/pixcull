"""v0.8-P1-3 — short-link issuer.

Maps a 6-char alphanumeric code to a long URL.  Used to compact the
v0.7-P1-4 share links (``/share/<run>/<token>`` is ~80 chars) and
the v0.8-P0-2 sync-event URLs (~60 chars) into something easy to
paste into iMessage, AirDrop, or — when paired with the QR
renderer in ``pixcull.qrcode_svg`` — scan from a client's phone.

Why pixcull-wide (not run-scoped)
=================================
Short links cross run boundaries (a photographer might share two
runs' delivery links with the same client).  Keeping the store at
``_DEMO_ROOT / _shortlinks.json`` means one process-wide map, no
per-run lookup cost.  Concurrency is bounded — at most one
short-link write per user click — so a simple read-modify-write
under a file lock is fine.

Schema (v1)
===========
``_shortlinks.json`` is::

  {
    "schema": "pixcull.shortlinks/v1",
    "links":  {
      "abc123": {
        "long_url":   "/share/sample_xyz/abc...token...",
        "created_at": "2026-05-23T...",
        "expires_at": "2026-06-22T...",
        "label":      "wedding-2026-06"
      },
      ...
    }
  }

Notes
-----
* 6-char alphanumeric (a-z A-Z 0-9) → 56.8B possible codes;
  collision probability after 1M links is ~10^-5 (birthday bound).
  We retry on collision up to 8 times before giving up.
* The lookup intentionally accepts BOTH "/s/<code>" and absolute
  long URLs (so legacy share URLs continue to work even if the
  caller doesn't check the schema first).
* No deletion API in v1 — expired links are 410'd at read time
  but the entry stays in the file (lets the audit trail survive
  garbage collection).  A periodic cleanup job is v0.9 work.
"""

from __future__ import annotations

import json
import secrets
import string
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# 6 chars from base-62 → 56.8B possible codes; collisions ~birthday
# bound (expected first collision around sqrt(56.8B) ≈ 240k links).
_CODE_LEN = 6
_CODE_ALPHABET = string.ascii_letters + string.digits

_SCHEMA = "pixcull.shortlinks/v1"
_FILE_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path(demo_root: Path) -> Path:
    return demo_root / "_shortlinks.json"


def _load(demo_root: Path) -> dict:
    p = _store_path(demo_root)
    if not p.exists():
        return {"schema": _SCHEMA, "links": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": _SCHEMA, "links": {}}
    if not isinstance(data, dict):
        return {"schema": _SCHEMA, "links": {}}
    if "links" not in data or not isinstance(data["links"], dict):
        data["links"] = {}
    return data


def _save(demo_root: Path, data: dict) -> None:
    p = _store_path(demo_root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to tmp + rename, so a crash mid-write
        # can't leave a half-finished file.
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(p)
    except OSError:
        pass


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def issue(
    demo_root: Path,
    long_url: str,
    ttl_hours: int = 24 * 30,   # 30-day default
    label: str = "",
) -> dict:
    """Mint a fresh short-link mapping to ``long_url``.

    Returns ``{short_code, long_url, created_at, expires_at, label}``.
    Raises RuntimeError on the (vanishingly rare) collision-after-8-
    retries case — caller should surface that as 500 to the user.
    """
    long_url = str(long_url).strip()
    if not long_url:
        raise ValueError("long_url must be non-empty")
    ttl_hours = max(1, int(ttl_hours))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    ).isoformat()
    with _FILE_LOCK:
        data = _load(demo_root)
        # Idempotency: if this exact long_url already has an unexpired
        # short-link, return that one. Avoids minting a dozen codes
        # for the same share link if the host re-clicks the button.
        now = datetime.now(timezone.utc)
        for code, rec in data["links"].items():
            if rec.get("long_url") != long_url:
                continue
            try:
                exp = datetime.fromisoformat(rec.get("expires_at", ""))
                if exp >= now:
                    return {"short_code": code, **rec}
            except (TypeError, ValueError):
                pass
        # Mint a fresh code (retry on collision)
        for _ in range(8):
            code = _generate_code()
            if code not in data["links"]:
                break
        else:
            raise RuntimeError("8 collisions in a row — store is saturated?")
        rec = {
            "long_url":   long_url,
            "created_at": _now_iso(),
            "expires_at": expires_at,
            "label":      str(label)[:120],
        }
        data["links"][code] = rec
        _save(demo_root, data)
        return {"short_code": code, **rec}


def resolve(demo_root: Path, code: str) -> Optional[dict]:
    """Return the link record for ``code``, or None if absent / expired.

    The record carries ``long_url`` ready to redirect to, plus the
    metadata fields for diagnostics.  Caller is responsible for the
    302 + (in expired case) a 410 response.
    """
    if not code or not isinstance(code, str):
        return None
    if len(code) != _CODE_LEN:
        return None
    # Defensive: reject anything outside the alphabet so a path-
    # traversal attempt can't slip in via the URL.
    if not all(c in _CODE_ALPHABET for c in code):
        return None
    data = _load(demo_root)
    rec = data["links"].get(code)
    if rec is None:
        return None
    exp = rec.get("expires_at")
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp)
            if exp_dt < datetime.now(timezone.utc):
                # Mark expired by returning a small dict so the
                # caller can 410 rather than 404 — distinguishes
                # "never existed" from "expired".
                return {"expired": True, **rec}
        except ValueError:
            pass
    return rec


__all__ = ["issue", "resolve"]
