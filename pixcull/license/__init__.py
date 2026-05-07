"""V12.0 license + quota gate — basic Pro subscription enforcement.

Architecture
============
PixCull stays open-source. The "Pro" line is enforced client-side
via a signed license token saved in
~/Library/Application Support/PixCull/license.json. The token has:

  email         user identifier (only for license recovery support)
  tier          "free" | "pro" | "studio" | "lifetime"
  expires_at    UNIX seconds; absent = perpetual
  monthly_quota integer; -1 = unlimited
  signature     HMAC-SHA256 over the rest, with a public-key-style
                offline-verifiable scheme

Free tier
=========
* 100 image analyses per calendar month, no upgrade required.
* All scoring features (V8 style modes / V8.2 genres / V11.1
  differentiated reviews) work — we don't gate quality, we gate
  volume.

Pro tier (¥35/月 or ¥299/年)
=============================
* Unlimited monthly volume.
* Auto-retrain enabled (V11.2 silently uses your annotations).
* Priority support email.
* Cloud sync of annotations across devices (V12.1).

Studio tier (¥299/月)
======================
* All Pro features + LAN multi-user mode.
* Up to 4 collaborators sharing one license.
* Custom genre presets / branded reports.

This module ships the verifier; the issuance side (server that
mints licenses) is intentionally out of scope here — that lives
in a separate billing repo.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


# Public verification key — anyone can verify licenses; only the
# license-issuing server can sign them. Replace this in your
# production fork with the real key embedded in the .app bundle.
_VERIFY_KEY = b"pixcull-v12-public-verify-key-replace-in-prod"


@dataclass
class License:
    """Parsed + verified license."""
    email: str = ""
    tier: str = "free"
    expires_at: int | None = None        # unix seconds
    monthly_quota: int = 100             # -1 = unlimited
    issued_at: int = 0
    raw_token: str = ""

    @property
    def is_pro(self) -> bool:
        return self.tier in ("pro", "studio", "lifetime")

    @property
    def is_unlimited(self) -> bool:
        return self.monthly_quota == -1 or self.is_pro

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at < int(_now())

    @property
    def days_remaining(self) -> int | None:
        if self.expires_at is None:
            return None
        return max(0, (self.expires_at - int(_now())) // 86400)


def _now() -> float:
    return datetime.datetime.now().timestamp()


def _hmac(payload: bytes) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_VERIFY_KEY, payload, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")


def encode_license(payload: dict) -> str:
    """Helper for the issuing server (or for tests).

    Token format: <base64(json payload)>.<base64(hmac)>
    """
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    sig = _hmac(body.encode("ascii"))
    return f"{body}.{sig}"


def decode_license(token: str) -> License | None:
    """Verify HMAC + parse. Returns None on tamper / malformed."""
    if not token or "." not in token:
        return None
    body_b64, sig = token.rsplit(".", 1)
    expected = _hmac(body_b64.encode("ascii"))
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        # Pad b64 if needed
        pad = "=" * (-len(body_b64) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(body_b64 + pad).decode("utf-8")
        )
    except Exception:
        return None
    return License(
        email=str(payload.get("email", "")),
        tier=str(payload.get("tier", "free")),
        expires_at=payload.get("expires_at"),
        monthly_quota=int(payload.get("monthly_quota", 100)),
        issued_at=int(payload.get("issued_at", 0)),
        raw_token=token,
    )


# ---------------------------------------------------------------------------
# Persistent license + monthly quota counter
# ---------------------------------------------------------------------------

def license_path() -> Path:
    if os.name == "posix":
        base = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        base = Path.home() / ".pixcull"
    base.mkdir(parents=True, exist_ok=True)
    return base / "license.json"


def quota_path() -> Path:
    return license_path().parent / "quota.json"


def load_license() -> License:
    p = license_path()
    if p.exists():
        try:
            data = json.loads(p.read_text("utf-8"))
            tok = data.get("token", "")
            lic = decode_license(tok)
            if lic and not lic.is_expired:
                return lic
        except (OSError, json.JSONDecodeError):
            pass
    # Default: free tier with no expiry, 100/mo
    return License(tier="free", monthly_quota=100)


def install_license(token: str) -> License | None:
    """Persist a license token to disk after verification."""
    lic = decode_license(token)
    if lic is None or lic.is_expired:
        return None
    p = license_path()
    p.write_text(
        json.dumps({"token": token}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(p, 0o600)
    return lic


# ---------------------------------------------------------------------------
# Monthly quota tracker
# ---------------------------------------------------------------------------

def _current_month_key() -> str:
    return datetime.datetime.now().strftime("%Y-%m")


def usage_this_month() -> int:
    p = quota_path()
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text("utf-8"))
        return int(data.get(_current_month_key(), 0))
    except (OSError, json.JSONDecodeError):
        return 0


def increment_usage(n: int = 1) -> int:
    """Charge n images against the current month's quota.
    Returns the new monthly count."""
    p = quota_path()
    data: dict = {}
    if p.exists():
        try:
            data = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    key = _current_month_key()
    data[key] = int(data.get(key, 0)) + n
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data[key]


def check_quota(n_planned: int) -> tuple[bool, str]:
    """Decide whether a planned analysis of `n_planned` images is allowed.

    Returns (allowed, message). Message is a human-readable status line
    suitable for showing in the upload-page status bar.
    """
    lic = load_license()
    if lic.is_unlimited:
        return True, f"Pro · 不限量 ({lic.tier})"
    used = usage_this_month()
    remaining = max(0, lic.monthly_quota - used)
    if remaining >= n_planned:
        return True, f"Free · 本月剩 {remaining}/{lic.monthly_quota} 张"
    if remaining > 0:
        return False, (
            f"配额不足:本月剩 {remaining} 张,本次需 {n_planned} 张。"
            f"分批扫描,或升级 Pro 不限量。"
        )
    return False, (
        f"本月免费配额已用完 ({lic.monthly_quota} 张)。"
        f"下个月 1 号自动重置,或升级 Pro 不限量。"
    )


def status_line() -> str:
    """One-line status for the upload page footer."""
    lic = load_license()
    if lic.is_unlimited:
        days = lic.days_remaining
        days_str = f" · 还有 {days} 天" if days is not None else ""
        return f"PixCull {lic.tier.upper()}{days_str}"
    used = usage_this_month()
    return f"PixCull Free · 本月已分析 {used}/{lic.monthly_quota} 张"
