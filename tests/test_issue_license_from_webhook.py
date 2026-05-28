"""Tests for scripts/issue_license_from_webhook.py — v0.12-P0-4."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import io
import json
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    p = REPO_ROOT / "scripts" / "issue_license_from_webhook.py"
    # Have to also pre-register scripts/issue_license so the module
    # can import it
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location(
        "issue_license_from_webhook", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["issue_license_from_webhook"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# stripe signature verification
# ---------------------------------------------------------------------------


def _stripe_sig(body: bytes, secret: str, ts: int) -> str:
    payload = f"{ts}.".encode() + body
    h = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={h}"


def test_stripe_signature_happy():
    w = _load()
    body = b'{"type":"checkout.session.completed"}'
    secret = "whsec_test"
    sig = _stripe_sig(body, secret, int(time.time()))
    assert w._verify_stripe(body, sig, secret)


def test_stripe_signature_replay_rejected():
    w = _load()
    body = b'{"type":"foo"}'
    secret = "whsec_test"
    # 1 hour ago
    sig = _stripe_sig(body, secret, int(time.time()) - 3600)
    assert not w._verify_stripe(body, sig, secret)


def test_stripe_signature_tampered():
    w = _load()
    body = b'{"type":"foo"}'
    secret = "whsec_test"
    sig = _stripe_sig(body, secret, int(time.time()))
    # Flip a body byte
    tampered = b'{"type":"bar"}'
    assert not w._verify_stripe(tampered, sig, secret)


def test_stripe_signature_wrong_secret():
    w = _load()
    body = b'{"type":"foo"}'
    sig = _stripe_sig(body, "real-secret", int(time.time()))
    assert not w._verify_stripe(body, sig, "wrong-secret")


def test_stripe_signature_missing_v1():
    w = _load()
    assert not w._verify_stripe(b"body", "t=123,v0=abc", "secret")


def test_stripe_signature_empty_inputs():
    w = _load()
    assert not w._verify_stripe(b"body", "", "secret")
    assert not w._verify_stripe(b"body", "t=1,v1=h", "")


# ---------------------------------------------------------------------------
# event parsing
# ---------------------------------------------------------------------------


def test_extract_stripe_checkout_completed():
    w = _load()
    body = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {
            "customer_email": "user@example.com",
            "line_items": {"data": [{
                "price": {"lookup_key": "pixcull_studio_monthly"},
            }]},
        }},
    }).encode()
    ev = w._extract_stripe_event(body)
    assert ev == {"email": "user@example.com",
                  "plan_id": "pixcull_studio_monthly"}


def test_extract_stripe_invoice_succeeded():
    w = _load()
    body = json.dumps({
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "customer_email": "renew@example.com",
            "lines": {"data": [{
                "price": {"lookup_key": "pixcull_team5_yearly"},
            }]},
        }},
    }).encode()
    ev = w._extract_stripe_event(body)
    assert ev["plan_id"] == "pixcull_team5_yearly"


def test_extract_stripe_unrelated_event_returns_none():
    w = _load()
    body = json.dumps({"type": "customer.created"}).encode()
    assert w._extract_stripe_event(body) is None


def test_extract_stripe_missing_email_returns_none():
    w = _load()
    body = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {"line_items": {"data": []}}},
    }).encode()
    assert w._extract_stripe_event(body) is None


def test_extract_stripe_bad_json_returns_none():
    w = _load()
    assert w._extract_stripe_event(b"not json") is None


def test_extract_wechat_happy():
    w = _load()
    body = json.dumps({
        "event_type": "TRANSACTION.SUCCESS",
        "resource": {"cleartext": {
            "attach": json.dumps({
                "email": "wx@example.com",
                "plan_id": "pixcull_lifetime",
            }),
        }},
    }).encode()
    ev = w._extract_wechat_event(body)
    assert ev["email"] == "wx@example.com"
    assert ev["plan_id"] == "pixcull_lifetime"


def test_extract_wechat_unrelated_returns_none():
    w = _load()
    body = json.dumps({"event_type": "REFUND"}).encode()
    assert w._extract_wechat_event(body) is None


# ---------------------------------------------------------------------------
# Plan map
# ---------------------------------------------------------------------------


def test_plan_map_covers_lifetime():
    w = _load()
    tier, days = w.PLAN_MAP["pixcull_lifetime"]
    assert tier == "lifetime"
    assert days is None


def test_plan_map_monthly_yearly():
    w = _load()
    assert w.PLAN_MAP["pixcull_studio_monthly"] == ("studio", 30)
    assert w.PLAN_MAP["pixcull_studio_yearly"] == ("studio", 365)


# ---------------------------------------------------------------------------
# end-to-end main()
# ---------------------------------------------------------------------------


def test_main_happy_stripe(monkeypatch, tmp_path, capsys):
    w = _load()
    body = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {
            "customer_email": "ok@x.com",
            "line_items": {"data": [{
                "price": {"lookup_key": "pixcull_studio_monthly"},
            }]},
        }},
    }).encode()
    secret = "whsec_e2e"
    sig = _stripe_sig(body, secret, int(time.time()))
    out = tmp_path / "lic.json"
    monkeypatch.setattr(sys, "stdin",
                        type("S", (), {"buffer": io.BytesIO(body)})())
    monkeypatch.setenv("PIXCULL_STRIPE_WEBHOOK_SECRET", secret)
    rc = w.main([
        "--provider", "stripe",
        "--signature", sig,
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert "token" in data
    # And the token verifies via the core decoder
    from pixcull.license import decode_license
    lic = decode_license(data["token"])
    assert lic.tier == "studio"
    assert lic.email == "ok@x.com"


def test_main_bad_signature_exits_2(monkeypatch):
    w = _load()
    body = b'{"type":"checkout.session.completed"}'
    monkeypatch.setattr(sys, "stdin",
                        type("S", (), {"buffer": io.BytesIO(body)})())
    monkeypatch.setenv("PIXCULL_STRIPE_WEBHOOK_SECRET", "whsec_x")
    rc = w.main([
        "--provider", "stripe",
        "--signature", "t=999,v1=abc",
    ])
    assert rc == 2


def test_main_unrelated_event_exits_3(monkeypatch):
    w = _load()
    body = json.dumps({"type": "customer.subscription.created"}).encode()
    secret = "whsec_test"
    sig = _stripe_sig(body, secret, int(time.time()))
    monkeypatch.setattr(sys, "stdin",
                        type("S", (), {"buffer": io.BytesIO(body)})())
    monkeypatch.setenv("PIXCULL_STRIPE_WEBHOOK_SECRET", secret)
    rc = w.main([
        "--provider", "stripe", "--signature", sig,
    ])
    assert rc == 3


def test_main_unknown_plan_exits_4(monkeypatch):
    w = _load()
    body = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {
            "customer_email": "u@x.com",
            "line_items": {"data": [{
                "price": {"lookup_key": "unknown_plan"},
            }]},
        }},
    }).encode()
    secret = "whsec_test"
    sig = _stripe_sig(body, secret, int(time.time()))
    monkeypatch.setattr(sys, "stdin",
                        type("S", (), {"buffer": io.BytesIO(body)})())
    monkeypatch.setenv("PIXCULL_STRIPE_WEBHOOK_SECRET", secret)
    rc = w.main([
        "--provider", "stripe", "--signature", sig,
    ])
    assert rc == 4
