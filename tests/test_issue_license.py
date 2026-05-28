"""Tests for scripts/issue_license.py (v0.11-P0-4).

Mints tokens via the CLI, verifies them with the in-repo decoder,
checks tier behaviour for team-* and studio.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    p = REPO_ROOT / "scripts" / "issue_license.py"
    spec = importlib.util.spec_from_file_location("issue_license", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["issue_license"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# token minting + verification round-trip
# ---------------------------------------------------------------------------


def test_studio_30day_round_trip():
    il = _load()
    from pixcull.license import decode_license
    token = il._issue(email="a@b.com", tier="studio",
                      days=30, lifetime=False, seats=None)
    lic = decode_license(token)
    assert lic is not None
    assert lic.tier == "studio"
    assert lic.email == "a@b.com"
    assert lic.is_pro
    assert lic.is_studio
    assert lic.is_unlimited
    # 30 days expiry → ~30 days remaining
    assert 28 <= lic.days_remaining <= 30


def test_team5_default_seats():
    il = _load()
    from pixcull.license import decode_license
    token = il._issue(email="t@b.com", tier="team-5",
                      days=None, lifetime=False, seats=None)
    lic = decode_license(token)
    assert lic.tier == "team-5"
    assert lic.team_seats == 5
    assert lic.is_studio   # team-* unlocks LAN multi-user
    assert lic.is_pro


def test_team20_seats_override():
    il = _load()
    from pixcull.license import decode_license
    token = il._issue(email="t@b.com", tier="team-20",
                      days=None, lifetime=False, seats=17)
    lic = decode_license(token)
    assert lic.team_seats == 17  # explicit override wins
    assert lic.tier == "team-20"


def test_lifetime_no_expiry():
    il = _load()
    from pixcull.license import decode_license
    token = il._issue(email="l@b.com", tier="lifetime",
                      days=None, lifetime=True, seats=None)
    lic = decode_license(token)
    assert lic.expires_at is None
    assert not lic.is_expired
    assert lic.days_remaining is None


def test_free_tier_team_seats_zero():
    il = _load()
    from pixcull.license import decode_license
    token = il._issue(email="free@b.com", tier="free",
                      days=None, lifetime=False, seats=None)
    lic = decode_license(token)
    assert lic.tier == "free"
    assert lic.team_seats == 0
    assert not lic.is_pro
    assert not lic.is_studio


def test_unknown_tier_raises():
    il = _load()
    with pytest.raises(ValueError):
        il._issue(email="x", tier="enterprise-megacorp",
                  days=None, lifetime=False, seats=None)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def test_main_writes_out_file(tmp_path):
    il = _load()
    out = tmp_path / "lic.json"
    rc = il.main([
        "--email", "x@y.com",
        "--tier", "studio",
        "--days", "7",
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "token" in data
    # And the token verifies
    from pixcull.license import decode_license
    lic = decode_license(data["token"])
    assert lic.tier == "studio"


def test_main_decode_round_trip(capsys):
    il = _load()
    token = il._issue(email="d@b.com", tier="team-5",
                      days=14, lifetime=False, seats=None)
    rc = il._decode_and_print(token)
    captured = capsys.readouterr()
    assert rc == 0
    decoded = json.loads(captured.out)
    assert decoded["tier"] == "team-5"
    assert decoded["email"] == "d@b.com"


def test_main_decode_bad_token():
    il = _load()
    rc = il._decode_and_print("garbage.signature")
    assert rc == 4


def test_main_unknown_tier_exits_2():
    """argparse choices catches it first and raises SystemExit(2)."""
    il = _load()
    with pytest.raises(SystemExit) as exc:
        il.main(["--tier", "bogus", "--email", "x"])
    assert exc.value.code == 2


def test_main_install_refuses_overwrite(tmp_path, monkeypatch):
    il = _load()
    # Sandbox the install path
    fake_lic = tmp_path / "license.json"
    fake_lic.write_text('{"token":"x"}', encoding="utf-8")
    import pixcull.license
    monkeypatch.setattr(pixcull.license, "license_path",
                        lambda: fake_lic)
    monkeypatch.setattr(il, "license_path", lambda: fake_lic)
    rc = il.main([
        "--email", "x@y.com", "--tier", "studio",
        "--days", "7", "--install",
    ])
    assert rc == 3   # refused without --force
    # Original content unchanged
    assert fake_lic.read_text() == '{"token":"x"}'


def test_main_install_force_overwrites(tmp_path, monkeypatch):
    il = _load()
    fake_lic = tmp_path / "license.json"
    fake_lic.write_text('{"token":"x"}', encoding="utf-8")
    import pixcull.license
    monkeypatch.setattr(pixcull.license, "license_path",
                        lambda: fake_lic)
    monkeypatch.setattr(il, "license_path", lambda: fake_lic)
    rc = il.main([
        "--email", "x@y.com", "--tier", "studio", "--days", "7",
        "--install", "--force",
    ])
    assert rc == 0
    data = json.loads(fake_lic.read_text(encoding="utf-8"))
    assert "token" in data
    assert data["token"] != "x"   # overwritten


# ---------------------------------------------------------------------------
# Tampered-token rejection
# ---------------------------------------------------------------------------


def test_tampered_signature_rejected():
    """Edit one byte of the body → HMAC fails → decode returns None."""
    il = _load()
    from pixcull.license import decode_license
    token = il._issue(email="real@b.com", tier="studio",
                      days=30, lifetime=False, seats=None)
    body, sig = token.rsplit(".", 1)
    # Flip the last char of the body
    flipped = body[:-1] + ("A" if body[-1] != "A" else "B")
    bad_token = f"{flipped}.{sig}"
    assert decode_license(bad_token) is None
