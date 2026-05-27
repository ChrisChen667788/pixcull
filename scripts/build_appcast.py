#!/usr/bin/env python3
"""v0.7-P2-3 — generate a Sparkle appcast.xml from a releases JSON.

Sparkle is the canonical macOS auto-updater (used by Bear, Things,
Reeder, 1Password, … virtually every native Mac product). It polls
a URL serving an "appcast" XML — RSS-like feed of releases — and
prompts the user to update when a newer version is available.

This script reads ``releases.json`` (the source of truth for what's
shipped) and emits ``appcast.xml`` ready to host at
``https://pixcull.app/appcast.xml`` (or wherever the binary's
``SUFeedURL`` Info.plist key points).

Pipeline
--------
1. Cut a release: build the .app, package as .dmg, sign + notarize
   with Apple Developer ID (see docs/macos-signing.md).
2. Run ``sparkle-bin/sign_update <dmg>`` with the EdDSA private key
   to get an ``EdDSA`` signature.
3. Update ``releases.json`` with the new entry + signature.
4. Run this script → ``appcast.xml`` → upload to CDN.

Schema for releases.json
------------------------
``{
  "schema": "pixcull.releases/v1",
  "feed": {
    "title":       "PixCull",
    "link":        "https://pixcull.app/",
    "description": "Local-first AI photo culling for pros."
  },
  "releases": [
    {
      "version":         "0.7.0",        # Sparkle's CFBundleVersion
      "short_version":   "0.7",          # CFBundleShortVersionString
      "min_system":      "12.0",         # minimumSystemVersion
      "pub_date":        "2026-06-15",   # ISO date — converted to RFC 822
      "url":             "https://pixcull.app/downloads/PixCull-0.7.0.dmg",
      "size_bytes":      48319201,
      "ed_signature":    "MEUCIQD…",     # from sparkle-bin/sign_update
      "release_notes":   "<h2>What's new in 0.7</h2><ul>…</ul>",
      "critical":        false           # if true, Sparkle skip-tracks
    },
    ...
  ]
}``

Output is plain XML — Sparkle's parser is forgiving but we follow
the canonical structure documented at
https://sparkle-project.org/documentation/publishing/.

Usage
-----
    python scripts/build_appcast.py releases.json --out appcast.xml
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from html import escape as _esc
from pathlib import Path


def _rfc822_date(iso_date: str) -> str:
    """Sparkle expects RFC 822 timestamps (RFC 5322 in modern parlance).

    iso_date may be just "YYYY-MM-DD" (we default time to noon UTC,
    which is what Sparkle's own docs show as the conventional form)
    or a full ISO 8601 datetime.
    """
    try:
        if len(iso_date) == 10:  # YYYY-MM-DD
            dt = datetime.strptime(iso_date, "%Y-%m-%d").replace(
                hour=12, tzinfo=timezone.utc
            )
        else:
            dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SystemExit(f"bad pub_date {iso_date!r}: {exc}") from exc
    # Mon, 15 Jun 2026 12:00:00 +0000
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def render_appcast(releases_doc: dict) -> str:
    """Render the appcast XML from a parsed releases.json dict.

    Returns the XML as a string ready for write_text().
    """
    if not isinstance(releases_doc, dict):
        raise SystemExit("releases.json: top-level must be an object")
    feed = releases_doc.get("feed") or {}
    releases = releases_doc.get("releases") or []
    if not isinstance(releases, list) or not releases:
        raise SystemExit("releases.json: missing or empty 'releases' list")

    title = feed.get("title") or "PixCull"
    link = feed.get("link") or "https://pixcull.app/"
    desc = feed.get("description") or "Local-first AI photo culling for pros."

    # Items are emitted newest-first — Sparkle picks the first item
    # whose version > installed and whose minimumSystemVersion is
    # satisfied. We sort by pub_date descending defensively.
    sorted_rel = sorted(
        releases,
        key=lambda r: r.get("pub_date", "1970-01-01"),
        reverse=True,
    )

    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="utf-8"?>')
    parts.append(
        '<rss version="2.0" '
        'xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
    )
    parts.append("  <channel>")
    parts.append(f"    <title>{_esc(title)}</title>")
    parts.append(f"    <link>{_esc(link)}</link>")
    parts.append(f"    <description>{_esc(desc)}</description>")
    parts.append("    <language>en</language>")
    for r in sorted_rel:
        version = str(r.get("version") or "")
        short = str(r.get("short_version") or version)
        notes = str(r.get("release_notes") or "")
        pub = _rfc822_date(str(r.get("pub_date") or "1970-01-01"))
        min_sys = str(r.get("min_system") or "")
        critical = bool(r.get("critical"))

        # v0.8-P1-2 — backward-compat with the v0.7-P2-3 single-
        # platform schema: when a release has only a top-level url /
        # size_bytes / ed_signature, we emit one enclosure as before
        # (and tag it macos so Sparkle on Windows / Linux ignores it
        # rather than mis-routing).  When `platforms: [...]` is
        # present, we emit one enclosure per platform with the
        # appropriate sparkle:os attribute — Sparkle on each OS
        # picks the enclosure tagged for its platform.
        platforms = r.get("platforms")
        if not isinstance(platforms, list) or not platforms:
            platforms = [{
                "os":           "macos",
                "url":          r.get("url"),
                "size_bytes":   r.get("size_bytes"),
                "ed_signature": r.get("ed_signature"),
                "min_system":   min_sys,
            }]

        if not version:
            raise SystemExit(
                f"release entry missing required 'version': {r!r}"
            )
        # Each platform variant must at least have a url.
        for plat in platforms:
            if not plat.get("url"):
                raise SystemExit(
                    f"platform entry in v{version} missing 'url': {plat!r}"
                )

        parts.append("    <item>")
        parts.append(f"      <title>Version {_esc(short)}</title>")
        parts.append(
            f"      <description><![CDATA[{notes}]]></description>"
        )
        parts.append(f"      <pubDate>{pub}</pubDate>")
        parts.append(
            f'      <sparkle:version>{_esc(version)}</sparkle:version>'
        )
        parts.append(
            f'      <sparkle:shortVersionString>{_esc(short)}'
            "</sparkle:shortVersionString>"
        )
        if min_sys:
            parts.append(
                f'      <sparkle:minimumSystemVersion>{_esc(min_sys)}'
                "</sparkle:minimumSystemVersion>"
            )
        if critical:
            # When a release is marked critical, Sparkle's
            # "Skip this version" / "Remind me later" UI is
            # disabled — used sparingly (data-loss fixes only).
            parts.append('      <sparkle:criticalUpdate />')

        for plat in platforms:
            os_name = str(plat.get("os") or "macos").lower()
            p_url   = str(plat.get("url") or "")
            p_size  = int(plat.get("size_bytes") or 0)
            p_sig   = str(plat.get("ed_signature") or "")
            # Enclosure carries the actual binary URL + signature.
            # ``sparkle:edSignature`` is the modern EdDSA variant;
            # the legacy ``sparkle:dsaSignature`` is deprecated
            # since Sparkle 2.0.
            enclosure_attrs = [
                f'url="{_esc(p_url)}"',
                f'sparkle:os="{_esc(os_name)}"',
                'type="application/octet-stream"',
            ]
            if p_size > 0:
                enclosure_attrs.append(f'length="{p_size}"')
            if p_sig:
                enclosure_attrs.append(
                    f'sparkle:edSignature="{_esc(p_sig)}"'
                )
            # Optional installer args — Windows MSI takes /passive
            # so the user doesn't get a "click Next 5 times" UAC
            # popup on update.  Linux + macOS ignore this.
            inst_args = plat.get("installer_arguments")
            if inst_args:
                enclosure_attrs.append(
                    f'sparkle:installerArguments="{_esc(str(inst_args))}"'
                )
            parts.append(
                "      <enclosure " + " ".join(enclosure_attrs) + " />"
            )
        parts.append("    </item>")
    parts.append("  </channel>")
    parts.append("</rss>")
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate a Sparkle appcast.xml from releases.json"
    )
    p.add_argument(
        "releases",
        type=Path,
        help="path to releases.json",
    )
    p.add_argument(
        "-o", "--out",
        type=Path,
        default=Path("appcast.xml"),
        help="output path (default: appcast.xml)",
    )
    args = p.parse_args(argv)
    try:
        doc = json.loads(args.releases.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[appcast] not found: {args.releases}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[appcast] bad JSON in {args.releases}: {exc}",
              file=sys.stderr)
        return 1
    xml = render_appcast(doc)
    args.out.write_text(xml, encoding="utf-8")
    n_releases = len(doc.get("releases") or [])
    print(f"[appcast] wrote {args.out} · {n_releases} release(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
