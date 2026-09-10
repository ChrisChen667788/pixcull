"""v3.73 (Phase A.1) — the design system has to say what actually ships.

`design-system/tokens.json` is the source of truth for the brand, and it
was wrong about fifteen of its sixteen role tokens. It held the warm
palette — `#161310` for the page background, `#f3ede1` for foreground —
that v2.21 replaced with an achromatic set so the surround could not tint
colour judgment. The product changed; the design system was not told; and
nothing compared them, so the file kept describing a version of PixCull
that had not shipped in a long time.

Phase A.1 was supposed to add the light theme to that file. It would have
added a second theme to a document that was wrong about the first.

Reading the CSS could not have caught it. The palette is computed with
relative colour —

    --accent-hi: oklch(from var(--accent) calc(l + 0.064) c h);

— so the source holds arithmetic and the second theme runs the same
arithmetic from a different base. The only honest comparison is against
what a browser paints, which is what this does.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "design-system" / "tokens.json"


def _measure():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mtt", ROOT / "scripts" / "measure_theme_tokens.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.measure(sorted(set(mod.ROLE.values())))


def _flat(doc):
    out = {}

    def walk(n, p=""):
        if isinstance(n, dict):
            if "value" in n and isinstance(n["value"], str):
                out[p] = n["value"]
            else:
                for k, v in n.items():
                    walk(v, f"{p}.{k}" if p else k)
    walk(doc)
    return out


def test_every_declared_dark_value_is_what_the_browser_paints():
    """The defect, stated as a check. Fifteen of sixteen failed this."""
    mod, meas = _measure()
    flat = _flat(json.loads(TOKENS.read_text(encoding="utf-8")))

    assert len(meas["dark"]) >= 20, (
        f"only {len(meas['dark'])} properties measured — the page did not "
        "render, and an empty comparison agrees with anything")

    wrong = []
    for path, prop in mod.ROLE.items():
        got = meas["dark"].get(prop)
        assert got and got["srgb"], f"{prop} did not resolve in the render"
        declared = flat.get(path)
        assert declared, f"{path} is not in tokens.json"
        if declared.lower() != got["srgb"].lower():
            wrong.append(f"{path}: declared {declared}, renders {got['srgb']}")
    assert not wrong, (
        "the design system disagrees with the product it describes: "
        + "; ".join(wrong))


def test_the_light_theme_is_what_the_browser_paints_too():
    """Phase A.1 itself. Values measured, never derived — arithmetic on
    the source produces numbers that look right and are not what ships."""
    mod, meas = _measure()
    doc = json.loads(TOKENS.read_text(encoding="utf-8"))
    light = (doc.get("_themes") or {}).get("light") or {}

    assert light, "design-system/tokens.json models no light theme"
    missing = sorted(set(mod.ROLE) - set(light))
    assert not missing, f"light theme is missing {len(missing)}: {missing}"

    wrong = []
    for path, prop in mod.ROLE.items():
        got = meas["light"].get(prop)
        assert got and got["srgb"], f"{prop} did not resolve in light"
        if light[path].lower() != got["srgb"].lower():
            wrong.append(f"{path}: declared {light[path]}, renders {got['srgb']}")
    assert not wrong, "the light theme disagrees with the render: " + "; ".join(wrong)


def test_the_two_themes_are_actually_different():
    """A light theme copied from the dark one would satisfy both checks
    above if the measurement silently returned one theme twice."""
    mod, meas = _measure()
    same = [p for p in mod.ROLE.values()
            if meas["dark"][p]["srgb"] == meas["light"][p]["srgb"]]
    # The colour-blind decision markers are deliberately theme-invariant.
    unexpected = [p for p in same if not p.endswith("-cb")]
    assert len(unexpected) <= 2, (
        f"{len(unexpected)} role properties render identically in both "
        f"themes: {unexpected}. Either the theme did not apply or the "
        "measurement read the same page twice.")
