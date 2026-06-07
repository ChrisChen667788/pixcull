"""v2.5-P0-2 — static visual-regression guard (deterministic, no browser).

The pre-v2.3 "AI" palette (pink / indigo / violet / periwinkle / generic
blue) must never reappear in the UI source.  Runs in *every* gate with
zero deps and catches all the forms the v2.3 leak hid in:

  1. any ``#rrggbb`` in the purple/blue/pink family (detected by maths,
     so a *new* shade can't sneak past a fixed list),
  2. the old decimal ``rgba(232,72,153)`` / ``rgba(59,130,246)`` triples,
  3. the JS **hex-arithmetic** colour ramp (``0x6E + (0xEC - 0x6E)*t``).

Intentional exceptions: the colour-blind decision palette
(#0ea5e9 keep / #f59e0b maybe / #d946ef cull — Wong's deuteranopia-safe
set).  Editorial-warm stone/brass/terracotta never fall in the family.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_FILES = [
    ROOT / "pixcull" / "report" / "templates" / "results.html",
    ROOT / "scripts" / "serve_demo.py",
    ROOT / "pixcull" / "scoring" / "attribution.py",
]

# Colour-blind decision palette — intentional, never flagged.
_CB_ALLOW = {"0ea5e9", "f59e0b", "d946ef"}

_HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
_LITERAL = [
    ("pink rgba 23x,72,153",    r"23[26],\s*72,\s*153"),
    ("indigo rgba 110,86,207",  r"110,\s*86,\s*207"),
    ("violet rgba 168,85,247",  r"168,\s*85,\s*247"),
    ("blue rgba 59,130,246",    r"59,\s*130,\s*246"),
    ("hex-arith old ramp",      r"0xEC48|0x6E56|0xA855|0x6E\b\s*\+\s*\(\s*0xEC"),
]


def _is_ai_family(hex6: str) -> bool:
    """True for the indigo/violet/periwinkle/blue/pink family — the colours
    the editorial-warm brand deliberately does NOT use."""
    r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
    bluish = (b >= 190 and b > r + 25 and g < 205)        # blue/indigo/violet/periwinkle
    pinky = (r > 180 and g < 115 and 110 < b < r)         # pink/magenta (not warm red)
    return bluish or pinky


def test_no_legacy_palette_in_ui_source():
    offenders = []
    for f in UI_FILES:
        text = f.read_text("utf-8")
        for m in _HEX.finditer(text):
            h = m.group(1).lower()
            if h in _CB_ALLOW or not _is_ai_family(h):
                continue
            line = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{f.name}:{line}  #{h}  (AI purple/blue/pink family)")
        for label, pat in _LITERAL:
            for m in re.finditer(pat, text, re.IGNORECASE):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{f.name}:{line}  [{label}]  {m.group(0)!r}")
    assert not offenders, (
        "Legacy pre-v2.3 palette reintroduced — use editorial-warm "
        "stone/brass (var(--accent) / #c4b9a9 / #dcb87e / #d8cebf) or the "
        "terracotta danger (#cf6f5b) instead:\n  " + "\n  ".join(offenders))
