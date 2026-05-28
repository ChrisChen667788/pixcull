#!/usr/bin/env python3
"""v0.11-P0-4 — Issue signed PixCull licenses from the CLI.

Why this exists
===============
The license verifier already lives in ``pixcull/license/__init__.py``
(V12.0+ — token = base64(payload) + HMAC-SHA256 of the body).  What
was missing: a way to mint new tokens from a CLI rather than the
billing repo's web app.  This script fills that gap, and prepares
the v0.11 charter's commercial first step:

  free  → no token needed; default tier
  studio → multi-user LAN + team taste; v0.10 P1-1 unlock
  team-5 → studio + 5 paid seats
  team-20 → studio + 20 paid seats
  pro    → legacy single-seat alias kept for v0.10 compat
  lifetime → like pro but never expires

The HMAC verify key is a build-time constant in the verifier — the
script must use the SAME key.  Override via:
    PIXCULL_LICENSE_KEY=<hex bytes>   # for production minting
The default key is the development-mode value embedded in the
verifier.  Real release builds must rotate it (see deployment
note below) — never ship the dev key in the production binary.

Usage
=====

    # 30-day studio trial
    python scripts/issue_license.py \\
        --email alice@example.com \\
        --tier studio \\
        --days 30 \\
        --out /tmp/alice.json

    # Lifetime (no expiry) team-5
    python scripts/issue_license.py \\
        --email bob@example.com \\
        --tier team-5 \\
        --lifetime \\
        --out /tmp/bob.json

    # Inspect a token (verify + decode + pretty-print)
    python scripts/issue_license.py --decode "<token>"

Output
======
A JSON file with ``{"token": "<base64.<sig>"}`` ready to drop into
``~/Library/Application Support/PixCull/license.json`` (macOS) or
``~/.pixcull/license.json`` (Linux/Windows).

Exit codes
==========
* 0 — issued / decoded successfully
* 2 — invalid tier
* 3 — could not write output (permissions / missing dir)
* 4 — decode mode + token failed verification
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pixcull.license import (  # noqa: E402  — sys.path mutated above
    encode_license,
    decode_license,
    license_path,
)


# Canonical tier metadata.  monthly_quota: -1 means unlimited; the
# verifier (License.is_unlimited) covers this for any "pro" family
# tier anyway.  We keep the explicit number so we can render tier
# differences in the upgrade page later.
TIERS = {
    "free":     {"monthly_quota": 100,  "team_seats": 0},
    "pro":      {"monthly_quota": -1,   "team_seats": 0},
    "studio":   {"monthly_quota": -1,   "team_seats": 1},
    "team-5":   {"monthly_quota": -1,   "team_seats": 5},
    "team-20":  {"monthly_quota": -1,   "team_seats": 20},
    "lifetime": {"monthly_quota": -1,   "team_seats": 0},
}


def _issue(email: str, tier: str, days: int | None,
           lifetime: bool, seats: int | None) -> str:
    """Mint a signed token.  Mirrors the verifier's payload schema."""
    if tier not in TIERS:
        raise ValueError(
            f"unknown tier {tier!r}; valid: {sorted(TIERS)}"
        )
    meta = TIERS[tier]
    now = int(time.time())
    payload = {
        "email": email,
        "tier": tier,
        "monthly_quota": meta["monthly_quota"],
        "team_seats": seats if seats is not None else meta["team_seats"],
        "issued_at": now,
    }
    if not lifetime:
        days_val = days if days is not None else 30
        payload["expires_at"] = now + int(days_val) * 86400
    token = encode_license(payload)
    return token


def _decode_and_print(token: str) -> int:
    lic = decode_license(token)
    if lic is None:
        print("[license] decode FAILED — bad signature or malformed",
              file=sys.stderr)
        return 4
    print(json.dumps({
        "email": lic.email,
        "tier": lic.tier,
        "monthly_quota": lic.monthly_quota,
        "expires_at": lic.expires_at,
        "days_remaining": lic.days_remaining,
        "is_pro": lic.is_pro,
        "is_unlimited": lic.is_unlimited,
        "is_expired": lic.is_expired,
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Issue (and verify) PixCull licenses."
    )
    p.add_argument(
        "--decode", metavar="TOKEN",
        help="Decode an existing token instead of minting a new one"
    )
    p.add_argument("--email", default="user@example.com",
                   help="Licensee email (identifier)")
    p.add_argument("--tier", default="studio",
                   choices=sorted(TIERS),
                   help="Tier (default: studio)")
    p.add_argument("--days", type=int, default=None,
                   help="Expiry in days (default 30; ignored if "
                        "--lifetime is set)")
    p.add_argument("--lifetime", action="store_true",
                   help="Never expires (no expires_at)")
    p.add_argument("--seats", type=int, default=None,
                   help="Override team seat count for team-* tiers")
    p.add_argument("--out", type=Path, default=None,
                   help="Write license JSON here (default: print to stdout)")
    p.add_argument("--install", action="store_true",
                   help="Also drop into the local license_path() — "
                        "useful for development / testing.  Refuses to "
                        "overwrite an existing non-dev license unless "
                        "--force is also passed.")
    p.add_argument("--force", action="store_true",
                   help="With --install, overwrite even if a license is "
                        "already installed")
    args = p.parse_args(argv)

    if args.decode:
        return _decode_and_print(args.decode)

    try:
        token = _issue(
            email=args.email,
            tier=args.tier,
            days=args.days,
            lifetime=args.lifetime,
            seats=args.seats,
        )
    except ValueError as exc:
        print(f"[license] {exc}", file=sys.stderr)
        return 2

    file_body = {"token": token}
    blob = json.dumps(file_body, ensure_ascii=False, indent=2)

    if args.out is None and not args.install:
        # No destination flag → print to stdout for piping
        print(blob)
    if args.out is not None:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(blob, encoding="utf-8")
            os.chmod(args.out, 0o600)
        except OSError as exc:
            print(f"[license] could not write {args.out}: {exc}",
                  file=sys.stderr)
            return 3
        print(f"[license] wrote {args.out}", file=sys.stderr)

    if args.install:
        p_install = license_path()
        if p_install.exists() and not args.force:
            print(f"[license] {p_install} already exists; "
                  f"pass --force to overwrite", file=sys.stderr)
            return 3
        p_install.write_text(blob, encoding="utf-8")
        os.chmod(p_install, 0o600)
        print(f"[license] installed at {p_install}", file=sys.stderr)

    # Echo a one-line summary to stderr
    lic = decode_license(token)
    print(
        f"[license] ✓ minted {lic.tier} for {lic.email} "
        f"({'lifetime' if lic.expires_at is None else f'expires in {lic.days_remaining} days'})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
