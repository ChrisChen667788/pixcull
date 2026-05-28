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

# V12.1 — cloud verification server. Defaults to the public
# pixcull.dev endpoint; overridable via PIXCULL_LICENSE_API env
# var (e.g. for self-hosted enterprise installs).
import os as _os
_CLOUD_LICENSE_API = _os.environ.get(
    "PIXCULL_LICENSE_API",
    "https://api.pixcull.dev/v1/license",
)
_CLOUD_REFRESH_INTERVAL_S = 24 * 3600   # check once per day max


@dataclass
class License:
    """Parsed + verified license."""
    email: str = ""
    tier: str = "free"
    expires_at: int | None = None        # unix seconds
    monthly_quota: int = 100             # -1 = unlimited
    issued_at: int = 0
    # v0.11-P0-4 — paid-seat count for team-* tiers.  0 for solo tiers
    # (free / pro / studio / lifetime); studio is the LAN multi-user
    # tier but caps at "household" use, team-5 / team-20 are paid
    # multi-seat plans.
    team_seats: int = 0
    raw_token: str = ""

    @property
    def is_pro(self) -> bool:
        # v0.11-P0-4: team-* tiers count as pro too (multi-seat plans
        # are paid).  We keep the legacy single-seat tiers in front so
        # downstream feature checks (cloud sync, auto-retrain) remain
        # exactly the same.
        return (
            self.tier in ("pro", "studio", "lifetime")
            or self.tier.startswith("team-")
        )

    @property
    def is_studio(self) -> bool:
        """Studio + team-* tiers unlock LAN multi-user collaboration."""
        return self.tier == "studio" or self.tier.startswith("team-")

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
        team_seats=int(payload.get("team_seats", 0)),
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
    Returns the new monthly count.

    V15.1: when the dev-mode kill switch is on, return the existing
    count without writing. Keeps real-world test runs from inflating
    quota.json — when we flip the gate back on for a release build,
    the file reflects only what was actually paid for.
    """
    if _quota_disabled():
        return usage_this_month()
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


# V15.1 — temporary kill switch for the commercial gate. We're still
# in heavy real-world testing (large RAW batches off SD cards) where
# the 100/月 free cap is in the way. Keeping all the license / quota
# code intact so we can re-enable later without bisecting; this flag
# is the single point of bypass.
#
# Set ``PIXCULL_DISABLE_QUOTA=0`` to re-arm the gate. Default is on.
import os as _os
_QUOTA_DISABLED_DEFAULT = "1"
def _quota_disabled() -> bool:
    return _os.environ.get("PIXCULL_DISABLE_QUOTA",
                            _QUOTA_DISABLED_DEFAULT) not in ("0", "false", "")


def check_quota(n_planned: int) -> tuple[bool, str]:
    """Decide whether a planned analysis of `n_planned` images is allowed.

    Returns (allowed, message). Message is a human-readable status line
    suitable for showing in the upload-page status bar.

    V15.1: respects ``_quota_disabled()`` — when on (the current default
    while we iterate on the product), every batch passes through with
    a "dev mode" banner so frequent real-world tests aren't blocked
    by the 100/月 free cap. License code path unchanged otherwise.
    """
    if _quota_disabled():
        return True, "开发模式 · 配额闸门已关闭"
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
    """One-line status for the upload page footer.

    V15.1: dev-mode banner takes priority over license tier so the
    footer doesn't keep showing "FREE 0/100" while the gate is off.
    """
    if _quota_disabled():
        return "DEV · 不限量(配额闸门关闭)"
    lic = load_license()
    if lic.is_unlimited:
        days = lic.days_remaining
        days_str = f" · 还有 {days} 天" if days is not None else ""
        return f"PixCull {lic.tier.upper()}{days_str}"
    used = usage_this_month()
    return f"PixCull Free · 本月已分析 {used}/{lic.monthly_quota} 张"


# ---------------------------------------------------------------------------
# V12.1 — cloud refresh + revocation check
#
# Why this exists
# ---------------
# Offline HMAC verification (decode_license) catches naive token
# forgery, but it can't stop a stolen / refunded / abused token —
# the bytes still verify. The cloud server keeps a revocation list
# AND can roll the token's expires_at forward as the user keeps
# paying their subscription.
#
# Behavior
# --------
# load_license() now calls maybe_cloud_refresh() in the background
# (non-blocking, fire-and-forget). The refresh:
#   1. Reads the cached license token + last-checked timestamp.
#   2. If we already checked within _CLOUD_REFRESH_INTERVAL_S, skip.
#   3. Else POST {token: ...} to <_CLOUD_LICENSE_API>/refresh
#      and either:
#      - get back a new {token: ...}  → install (new expires_at)
#      - get back {revoked: true, reason: "..."} → wipe the file
#      - on network failure, keep the cached token (graceful degrade)
#
# Privacy: only the token + a daily refresh ping leaves the box.
# No image data, no annotation data is touched by license refresh.
# ---------------------------------------------------------------------------

def _last_refresh_path() -> Path:
    return license_path().parent / "license_refresh.json"


def _last_refresh_ts() -> float:
    p = _last_refresh_path()
    if not p.exists():
        return 0.0
    try:
        return float(json.loads(p.read_text("utf-8")).get("last_check", 0))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def _set_last_refresh_ts() -> None:
    _last_refresh_path().write_text(
        json.dumps({"last_check": _now()}), encoding="utf-8",
    )


def maybe_cloud_refresh(force: bool = False) -> dict:
    """V12.1: try to refresh the cached license against the cloud.

    Returns a status dict suitable for surfacing in the admin UI:
      {
        "skipped": True/False,    # debounced or no token to refresh
        "ok": True/False,
        "action": "no_change" | "renewed" | "revoked" | "network_error",
        "message": "<human readable>"
      }

    Safe to call from a thread; uses urllib stdlib (no extra deps).
    """
    import urllib.request
    import urllib.error

    p = license_path()
    if not p.exists():
        return {"skipped": True, "ok": True,
                "action": "no_change", "message": "尚未安装 license"}
    try:
        token = json.loads(p.read_text("utf-8")).get("token", "")
    except (OSError, json.JSONDecodeError):
        return {"skipped": True, "ok": False,
                "action": "no_change", "message": "license 文件损坏"}

    if not token:
        return {"skipped": True, "ok": True,
                "action": "no_change", "message": "license 为空"}

    if not force and (_now() - _last_refresh_ts()) < _CLOUD_REFRESH_INTERVAL_S:
        return {"skipped": True, "ok": True,
                "action": "no_change",
                "message": "24 小时内已检查过,跳过"}

    try:
        req = urllib.request.Request(
            f"{_CLOUD_LICENSE_API}/refresh",
            data=json.dumps({"token": token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        # Network failure — keep the cached token
        return {"skipped": False, "ok": False,
                "action": "network_error",
                "message": f"无法联网校验({type(exc).__name__});"
                           f"使用本地缓存的 license 继续工作"}

    _set_last_refresh_ts()

    if data.get("revoked"):
        try:
            p.unlink()
        except OSError:
            pass
        return {"skipped": False, "ok": True,
                "action": "revoked",
                "message": f"license 已被撤销: {data.get('reason', '未注明原因')}"}

    new_token = data.get("token")
    if new_token and new_token != token:
        # Server rotated the token (e.g. extended expiry after renewal)
        new_lic = install_license(new_token)
        if new_lic is not None:
            return {"skipped": False, "ok": True,
                    "action": "renewed",
                    "message": f"license 已续期至 {new_lic.expires_at}"}

    return {"skipped": False, "ok": True,
            "action": "no_change",
            "message": "license 仍然有效"}


# ---------------------------------------------------------------------------
# V12.1 — annotation sync (upload to cloud, download on new install)
#
# Photographers using PixCull on a Mac Studio + a MacBook Pro need
# their annotations to follow them. The implementation is a thin
# wrapper around the cloud endpoint:
#
#   POST <api>/sync/upload    {token, annotations: [...]}
#   GET  <api>/sync/download  {token}  →  {annotations: [...]}
#
# Cloud sync is Pro+ only — gated client-side by lic.is_pro.
# The protocol is opaque to PixCull: we just post the JSONL lines.
# ---------------------------------------------------------------------------

def cloud_sync_upload(annotation_records: list[dict]) -> dict:
    """Push the user's annotations to the cloud. Pro+ only."""
    import urllib.request
    import urllib.error

    lic = load_license()
    if not lic.is_pro:
        return {"ok": False, "message": "云同步是 Pro 功能"}
    p = license_path()
    if not p.exists():
        return {"ok": False, "message": "无 license token"}
    try:
        token = json.loads(p.read_text("utf-8")).get("token", "")
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "message": "license 文件损坏"}

    body = json.dumps({
        "token": token,
        "annotations": annotation_records,
    }, ensure_ascii=False).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{_CLOUD_LICENSE_API}/../sync/upload",  # neighbor of /license
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "message": data.get("message", "已上传")}
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False,
                "message": f"上传失败: {type(exc).__name__}: {exc}"}


def cloud_sync_download() -> dict:
    """Pull annotations from the cloud. Returns {ok, annotations, message}."""
    import urllib.request
    import urllib.error

    lic = load_license()
    if not lic.is_pro:
        return {"ok": False, "annotations": [], "message": "云同步是 Pro 功能"}
    p = license_path()
    if not p.exists():
        return {"ok": False, "annotations": [], "message": "无 license token"}
    try:
        token = json.loads(p.read_text("utf-8")).get("token", "")
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "annotations": [], "message": "license 文件损坏"}

    try:
        # Send token via Authorization header rather than URL param
        # so it doesn't end up in cloud-server access logs.
        req = urllib.request.Request(
            f"{_CLOUD_LICENSE_API}/../sync/download",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"ok": True,
                "annotations": data.get("annotations", []),
                "message": f"已下载 {len(data.get('annotations', []))} 条"}
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "annotations": [],
                "message": f"下载失败: {type(exc).__name__}: {exc}"}
