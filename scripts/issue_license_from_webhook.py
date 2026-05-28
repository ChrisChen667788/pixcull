#!/usr/bin/env python3
"""v0.12-P0-4 — Mint a PixCull license from a Stripe / 微信支付 webhook.

Why this is split out
=====================
``scripts/issue_license.py`` is the human-driven mint tool.  This
script is the *automated* equivalent: a webhook receiver (sitting
behind a public endpoint — the ``pixcull.dev/api/billing/webhook``
or self-hosted equivalent) calls into ``main()`` with the raw event
payload and a destination email/recipient, and the script

  1. Verifies the webhook signature (Stripe ``Stripe-Signature``
     header, or 微信支付 ``Wechatpay-Signature`` header)
  2. Maps the product/plan code to a PixCull tier
  3. Calls into ``scripts/issue_license.py`` to mint the JSON
  4. Drops the JSON into a file (or stdout) ready to be email-shipped

We deliberately don't email here — email delivery is a separate
process owned by the billing system.  This script's job is "given
a verified webhook, produce the license JSON".

Supported plans
===============

Stripe plan IDs → tier:
  pixcull_studio_monthly      → studio   (30 days)
  pixcull_studio_yearly       → studio   (365 days)
  pixcull_team5_monthly       → team-5   (30 days)
  pixcull_team5_yearly        → team-5   (365 days)
  pixcull_team20_monthly      → team-20  (30 days)
  pixcull_team20_yearly       → team-20  (365 days)
  pixcull_lifetime            → lifetime (no expiry)

微信支付 (WeChat Pay) — uses the same plan IDs via the ``attach``
field on the unified order request.

Usage
=====

    # Verify + mint from a Stripe webhook payload on stdin
    PIXCULL_LICENSE_KEY=<hex> \
    PIXCULL_STRIPE_WEBHOOK_SECRET=whsec_xxx \
    python scripts/issue_license_from_webhook.py \
        --provider stripe \
        --signature "$STRIPE_SIGNATURE_HEADER" \
        --out /tmp/licenses/$(uuidgen).json \
        < webhook_body.json

    # Dry-run — print the would-be license, don't write
    python scripts/issue_license_from_webhook.py \
        --provider stripe --dry-run \
        --signature ... < body.json

Exit codes
==========
* 0 — license written / dry-run successful
* 2 — signature verification failed
* 3 — unrecognised event type (not a payment success)
* 4 — unrecognised plan id
* 5 — output write failed
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.issue_license import _issue, TIERS  # noqa: E402


# Plan ID → (tier, days) mapping.  None days = lifetime.
PLAN_MAP: dict[str, tuple[str, int | None]] = {
    "pixcull_studio_monthly":  ("studio", 30),
    "pixcull_studio_yearly":   ("studio", 365),
    "pixcull_team5_monthly":   ("team-5", 30),
    "pixcull_team5_yearly":    ("team-5", 365),
    "pixcull_team20_monthly":  ("team-20", 30),
    "pixcull_team20_yearly":   ("team-20", 365),
    "pixcull_lifetime":        ("lifetime", None),
}


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def _verify_stripe(body: bytes, sig_header: str, secret: str,
                   tolerance: int = 300) -> bool:
    """Verify a Stripe webhook signature.

    Stripe header format:
        Stripe-Signature: t=<ts>,v1=<hex>,v0=...
    HMAC-SHA256 over ``<ts>.<body>`` with ``secret`` must match v1.

    Returns True only when:
      * Header is well-formed
      * The HMAC matches (constant-time comparison)
      * ``|now - ts| <= tolerance``  (prevents replay)
    """
    if not sig_header or not secret:
        return False
    parts = dict(p.split("=", 1) for p in sig_header.split(",")
                 if "=" in p)
    try:
        ts = int(parts.get("t", ""))
        v1 = parts.get("v1", "")
    except (ValueError, TypeError):
        return False
    if not v1:
        return False
    if abs(int(time.time()) - ts) > tolerance:
        return False
    signed_payload = f"{ts}.".encode() + body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256
                        ).hexdigest()
    return hmac.compare_digest(expected, v1)


def _verify_wechat(body: bytes, sig_header: str,
                   apiv3_key: str) -> bool:
    """Verify a 微信支付 V3 webhook signature.

    Header:
        Wechatpay-Signature: <base64-encoded SHA256-RSA signature>
        Wechatpay-Nonce: <nonce>
        Wechatpay-Timestamp: <ts>

    Caller is expected to pass the JOINED nonce.ts.body fields as the
    second arg (a future v0.12 polish can split this); for now we
    accept the same opaque-string contract Stripe uses and verify
    via HMAC-SHA256 like Stripe.

    Note: the *real* 微信支付 V3 protocol uses RSA, not HMAC.  This
    function is a placeholder for the production wiring — replace
    with ``cryptography.hazmat.primitives.asymmetric.padding.PKCS1v15``
    + RSA public key from 微信支付 platform certificate.
    """
    if not sig_header or not apiv3_key:
        return False
    expected = hmac.new(apiv3_key.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


def _extract_stripe_event(body: bytes) -> dict | None:
    """Pull the relevant fields out of a Stripe ``checkout.session.completed``
    or ``invoice.payment_succeeded`` event.

    Returns ``{email, plan_id}`` or None if this isn't a payment-success
    event.
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    event_type = data.get("type", "")
    if event_type not in (
        "checkout.session.completed",
        "invoice.payment_succeeded",
    ):
        return None
    obj = data.get("data", {}).get("object", {})
    email = (obj.get("customer_email")
             or obj.get("customer_details", {}).get("email")
             or "")
    plan_id = ""
    # For checkout sessions: line_items expanded → first item's price.lookup_key
    if event_type == "checkout.session.completed":
        line_items = obj.get("line_items", {}).get("data", [])
        if line_items:
            plan_id = (line_items[0].get("price", {}).get("lookup_key", "")
                       or line_items[0].get("price", {}).get("id", ""))
    elif event_type == "invoice.payment_succeeded":
        lines = obj.get("lines", {}).get("data", [])
        if lines:
            plan_id = (lines[0].get("price", {}).get("lookup_key", "")
                       or lines[0].get("price", {}).get("id", ""))
    if not email or not plan_id:
        return None
    return {"email": email, "plan_id": plan_id}


def _extract_wechat_event(body: bytes) -> dict | None:
    """Pull email + plan from 微信支付 V3 notification.

    Schema (simplified):
        {event_type: "TRANSACTION.SUCCESS", resource: {ciphertext: ...},
         summary: ...}

    The ciphertext field is AES-GCM encrypted with the apiv3 key;
    decryption is left to the production wiring.  For this stub we
    expect the caller to pre-decrypt and pass the cleartext in
    ``resource.cleartext``.
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if data.get("event_type") != "TRANSACTION.SUCCESS":
        return None
    cleartext = data.get("resource", {}).get("cleartext", {})
    if not isinstance(cleartext, dict):
        return None
    # ``attach`` is the user-supplied passthrough field — we put the
    # plan_id + email there during unified-order creation.
    attach = cleartext.get("attach", "")
    try:
        attach_obj = json.loads(attach) if attach else {}
    except (json.JSONDecodeError, ValueError):
        return None
    email = attach_obj.get("email", "")
    plan_id = attach_obj.get("plan_id", "")
    if not email or not plan_id:
        return None
    return {"email": email, "plan_id": plan_id}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Mint a PixCull license from a verified webhook."
    )
    p.add_argument("--provider", choices=["stripe", "wechat"],
                   required=True, help="Webhook provider")
    p.add_argument("--signature", required=True,
                   help="Provider signature header value")
    p.add_argument("--out", type=Path, default=None,
                   help="Write license JSON here (default: stdout)")
    p.add_argument("--dry-run", action="store_true",
                   help="Verify + mint, but print, don't write")
    args = p.parse_args(argv)

    body = sys.stdin.buffer.read()
    if not body:
        print("[webhook] empty body on stdin", file=sys.stderr)
        return 2

    # Signature verification
    if args.provider == "stripe":
        secret = os.environ.get("PIXCULL_STRIPE_WEBHOOK_SECRET", "")
        if not _verify_stripe(body, args.signature, secret):
            print("[webhook] Stripe signature failed verification",
                  file=sys.stderr)
            return 2
        event = _extract_stripe_event(body)
    else:  # wechat
        secret = os.environ.get("PIXCULL_WECHAT_APIV3_KEY", "")
        if not _verify_wechat(body, args.signature, secret):
            print("[webhook] WeChat signature failed verification",
                  file=sys.stderr)
            return 2
        event = _extract_wechat_event(body)

    if event is None:
        print("[webhook] not a payment-success event — ignoring",
              file=sys.stderr)
        return 3

    email = event["email"]
    plan_id = event["plan_id"]
    if plan_id not in PLAN_MAP:
        print(f"[webhook] unrecognised plan {plan_id!r}", file=sys.stderr)
        return 4

    tier, days = PLAN_MAP[plan_id]
    token = _issue(
        email=email, tier=tier,
        days=days, lifetime=days is None,
        seats=None,
    )
    file_body = json.dumps({"token": token}, ensure_ascii=False, indent=2)

    if args.dry_run:
        print(file_body)
        print(f"[webhook] DRY RUN — would issue {tier} for {email}",
              file=sys.stderr)
        return 0
    if args.out is None:
        print(file_body)
    else:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(file_body, encoding="utf-8")
            os.chmod(args.out, 0o600)
        except OSError as exc:
            print(f"[webhook] could not write {args.out}: {exc}",
                  file=sys.stderr)
            return 5
        print(f"[webhook] ✓ wrote {args.out}", file=sys.stderr)
    print(f"[webhook] ✓ issued {tier} for {email} via {args.provider}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
