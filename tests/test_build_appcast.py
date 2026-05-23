"""Tests for scripts/build_appcast.py — Sparkle appcast generator.

We don't need a real Sparkle client to test the output — just that
the XML is well-formed, all required Sparkle fields are present,
and items are ordered newest-first.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET


def _load_module():
    """Importlib trick because scripts/ has a hyphenless-but-non-package
    layout — same pattern used elsewhere in tests/."""
    p = Path(__file__).resolve().parent.parent / "scripts" / "build_appcast.py"
    spec = importlib.util.spec_from_file_location("build_appcast", p)
    assert spec and spec.loader, p
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_basic_two_releases():
    bc = _load_module()
    doc = {
        "feed": {
            "title": "PixCull",
            "link": "https://pixcull.app/",
            "description": "AI photo culling",
        },
        "releases": [
            {
                "version": "0.6.0",
                "short_version": "0.6",
                "pub_date": "2026-05-01",
                "url": "https://x.com/PC-0.6.dmg",
                "size_bytes": 1234567,
                "ed_signature": "SIG_06",
                "release_notes": "<p>old</p>",
            },
            {
                "version": "0.7.0",
                "short_version": "0.7",
                "pub_date": "2026-06-15",
                "url": "https://x.com/PC-0.7.dmg",
                "size_bytes": 7654321,
                "ed_signature": "SIG_07",
                "release_notes": "<p>new</p>",
                "min_system": "12.0",
            },
        ],
    }
    xml = bc.render_appcast(doc)

    # Well-formed XML
    root = ET.fromstring(xml)
    ns = {"s": "http://www.andymatuschak.org/xml-namespaces/sparkle"}
    items = root.findall(".//item")
    assert len(items) == 2

    # Newest first by pub_date
    versions = [it.find("s:version", ns).text for it in items]
    assert versions == ["0.7.0", "0.6.0"]

    # Enclosure has the right url + signature + size
    top = items[0]
    enc = top.find("enclosure")
    assert enc.get("url") == "https://x.com/PC-0.7.dmg"
    assert enc.get("length") == "7654321"
    # EdDSA signature attribute lives in the sparkle namespace
    assert (
        enc.get("{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature")
        == "SIG_07"
    )

    # min_system is propagated only when present
    assert top.find("s:minimumSystemVersion", ns).text == "12.0"
    assert items[1].find("s:minimumSystemVersion", ns) is None


def test_critical_update_flag_emitted():
    bc = _load_module()
    doc = {
        "releases": [
            {
                "version": "0.7.1",
                "pub_date": "2026-06-20",
                "url": "https://x.com/PC-0.7.1.dmg",
                "ed_signature": "SIG",
                "critical": True,
            }
        ]
    }
    xml = bc.render_appcast(doc)
    assert "<sparkle:criticalUpdate />" in xml


def test_pub_date_iso_short_form_accepted():
    bc = _load_module()
    doc = {
        "releases": [
            {
                "version": "0.7.0",
                "pub_date": "2026-06-15",
                "url": "https://x.com/PC.dmg",
            }
        ]
    }
    xml = bc.render_appcast(doc)
    # RFC 822 date contains weekday + month-name + GMT offset
    assert ", 15 Jun 2026 12:00:00 +0000" in xml


def test_missing_version_or_url_raises():
    bc = _load_module()
    import pytest
    with pytest.raises(SystemExit):
        bc.render_appcast({"releases": [{"version": "0.7.0"}]})
    with pytest.raises(SystemExit):
        bc.render_appcast({"releases": [{"url": "https://x.com/PC.dmg"}]})


def test_release_notes_in_cdata():
    bc = _load_module()
    doc = {
        "releases": [
            {
                "version": "0.7.0",
                "pub_date": "2026-06-15",
                "url": "https://x.com/PC.dmg",
                "release_notes": "<h2>Fixes</h2><p>Bug & feature</p>",
            }
        ]
    }
    xml = bc.render_appcast(doc)
    # The CDATA section keeps the HTML un-escaped so Sparkle's
    # in-app updater renders it as rich text.
    assert "<![CDATA[<h2>Fixes</h2><p>Bug & feature</p>]]>" in xml


def test_example_releases_json_renders():
    """The shipped dist/releases.example.json must always render."""
    import json as _j
    bc = _load_module()
    example = (Path(__file__).resolve().parent.parent
               / "dist" / "releases.example.json")
    doc = _j.loads(example.read_text(encoding="utf-8"))
    xml = bc.render_appcast(doc)
    root = ET.fromstring(xml)
    # 2 entries in the example
    assert len(root.findall(".//item")) == 2
