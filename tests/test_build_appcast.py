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
    """The shipped docs/sparkle/releases.example.json must always render."""
    import json as _j
    bc = _load_module()
    example = (Path(__file__).resolve().parent.parent
               / "docs" / "sparkle" / "releases.example.json")
    doc = _j.loads(example.read_text(encoding="utf-8"))
    xml = bc.render_appcast(doc)
    root = ET.fromstring(xml)
    # 2 entries in the example
    assert len(root.findall(".//item")) == 2


# ---------------------------------------------------------------------------
# v0.8-P1-2 — multi-platform schema (macOS DMG + Windows MSI + Linux AppImage
# all coexist in one item, each with its own sparkle:os enclosure).
# ---------------------------------------------------------------------------


def test_legacy_schema_emits_sparkle_os_macos():
    """A pre-v0.8 release with only a top-level url/sig still works
    — but the emitted enclosure now carries `sparkle:os="macos"` so
    Windows/Linux clients ignore it instead of mis-routing."""
    bc = _load_module()
    doc = {
        "releases": [
            {
                "version": "0.7.0",
                "pub_date": "2026-06-15",
                "url": "https://x.com/PC.dmg",
                "size_bytes": 12345,
                "ed_signature": "SIG_MAC",
            }
        ]
    }
    xml = bc.render_appcast(doc)
    root = ET.fromstring(xml)
    encs = root.findall(".//enclosure")
    assert len(encs) == 1
    assert encs[0].get("sparkle:os",
                       encs[0].get(
                           "{http://www.andymatuschak.org/xml-namespaces/sparkle}os"
                       )) == "macos"
    assert encs[0].get("url") == "https://x.com/PC.dmg"


def test_multi_platform_schema_emits_three_enclosures():
    """An 0.8+ release with a platforms[] array emits one enclosure
    per platform, each tagged sparkle:os."""
    bc = _load_module()
    doc = {
        "releases": [
            {
                "version": "0.8.0",
                "pub_date": "2026-09-01",
                "release_notes": "<p>multi-platform release</p>",
                "platforms": [
                    {
                        "os": "macos",
                        "url": "https://x.com/PC-0.8.dmg",
                        "size_bytes": 11111,
                        "ed_signature": "SIG_MAC",
                    },
                    {
                        "os": "windows",
                        "url": "https://x.com/PC-0.8.msi",
                        "size_bytes": 22222,
                        "ed_signature": "SIG_WIN",
                        "installer_arguments": "/passive",
                    },
                    {
                        "os": "linux",
                        "url": "https://x.com/PC-0.8.AppImage",
                        "size_bytes": 33333,
                        "ed_signature": "SIG_LIN",
                    },
                ],
            }
        ]
    }
    xml = bc.render_appcast(doc)
    root = ET.fromstring(xml)
    item = root.find(".//item")
    encs = item.findall("enclosure")
    assert len(encs) == 3
    sp_ns = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
    by_os = {e.get(f"{sp_ns}os"): e for e in encs}
    assert set(by_os) == {"macos", "windows", "linux"}
    assert by_os["macos"].get("url") == "https://x.com/PC-0.8.dmg"
    assert by_os["windows"].get("url") == "https://x.com/PC-0.8.msi"
    assert by_os["linux"].get("url") == "https://x.com/PC-0.8.AppImage"
    # Per-platform sigs
    assert by_os["macos"].get(f"{sp_ns}edSignature") == "SIG_MAC"
    assert by_os["windows"].get(f"{sp_ns}edSignature") == "SIG_WIN"
    assert by_os["linux"].get(f"{sp_ns}edSignature") == "SIG_LIN"
    # Windows-only installer arguments propagate
    assert by_os["windows"].get(f"{sp_ns}installerArguments") == "/passive"
    # macOS + Linux entries don't carry the windows-only attr
    assert by_os["macos"].get(f"{sp_ns}installerArguments") is None
    assert by_os["linux"].get(f"{sp_ns}installerArguments") is None


def test_multi_platform_missing_url_raises():
    """A platform entry without `url` must blow up loudly — never
    ship an enclosure with no download target."""
    bc = _load_module()
    import pytest
    with pytest.raises(SystemExit):
        bc.render_appcast({
            "releases": [{
                "version": "0.8.0",
                "pub_date": "2026-09-01",
                "platforms": [
                    {"os": "windows", "size_bytes": 1},  # url missing
                ],
            }]
        })


def test_per_platform_sizes_propagate():
    """Each platform's size_bytes ends up in the matching enclosure's
    length attribute — not collapsed across variants."""
    bc = _load_module()
    doc = {
        "releases": [{
            "version": "0.8.0",
            "pub_date": "2026-09-01",
            "platforms": [
                {"os": "macos",   "url": "u1", "size_bytes": 100},
                {"os": "windows", "url": "u2", "size_bytes": 200},
            ],
        }]
    }
    xml = bc.render_appcast(doc)
    root = ET.fromstring(xml)
    encs = root.findall(".//enclosure")
    sp_ns = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
    by_os = {e.get(f"{sp_ns}os"): e for e in encs}
    assert by_os["macos"].get("length") == "100"
    assert by_os["windows"].get("length") == "200"
