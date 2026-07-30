"""v2.38 — WCAG contrast, computed from the real tokens.

v2.35 and v2.37 rolled light theme out across a dozen surfaces that had
never rendered light before.  Nobody had checked what that did to
contrast, so this measures it instead of assuming.

What it found: the palette is healthy — every text tier clears AA on
both themes — except ``--muted-soft``, which was 3.01:1 in light and
3.65:1 in dark while being used for 10.5–11px text (timestamps, hints,
placeholders, hotkey labels).  WCAG "large text" starts at 18.66px bold
/ 24px, so that text needed the full 4.5:1 and did not have it.

Solving for a compliant value showed there is no room for a tier
*softer* than ``--muted`` that still passes on the deeper surfaces —
so ``--muted-soft`` became decoration-only (dividers, chevrons, dots,
hover borders, empty-state SVG strokes), and every text use moved to
``--muted``.  These tests pin both halves of that decision.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SERVE_APP = REPO / "pixcull" / "report" / "serve_app.py"
SRC = REPO / "pixcull" / "report" / "templates" / "src"

AA_TEXT = 4.5      # WCAG 2.1 AA, normal-size text
AA_NON_TEXT = 3.0  # AA, UI components and graphical objects


def _rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(h):
    r, g, b = (_lin(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _token_blocks():
    """(dark, light) token dicts from the shared _DESIGN_TOKENS_CSS."""
    css = re.search(r'_DESIGN_TOKENS_CSS\s*=\s*r"""(.*?)"""',
                    SERVE_APP.read_text("utf-8"), re.S).group(1)
    dark_src, _, rest = css.partition('html[data-theme="light"]')
    light_src = rest.partition("}")[0]

    def parse(block):
        return {m.group(1): m.group(2).strip() for m in
                re.finditer(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", block)}

    dark = parse(dark_src)
    return dark, {**dark, **parse(light_src)}


DARK, LIGHT = _token_blocks()

# Surfaces that text actually sits on.
_SURFACES = ("--bg", "--bg-card")
# Text tiers. --muted-soft is deliberately absent: see module docstring.
_TEXT_TIERS = ("--fg", "--fg-2", "--muted", "--accent")


def test_tokens_were_parsed():
    for name, t in (("dark", DARK), ("light", LIGHT)):
        assert t.get("--fg") and t.get("--bg"), f"{name} tokens not parsed"


@pytest.mark.parametrize("theme,tokens", [("dark", DARK), ("light", LIGHT)])
@pytest.mark.parametrize("tier", _TEXT_TIERS)
@pytest.mark.parametrize("surface", _SURFACES)
def test_text_tiers_meet_aa(theme, tokens, tier, surface):
    fg, bg = tokens.get(tier), tokens.get(surface)
    if not fg or not bg:
        pytest.skip(f"{tier}/{surface} not defined in {theme}")
    r = contrast(fg, bg)
    assert r >= AA_TEXT, (
        f"{theme}: {tier} ({fg}) on {surface} ({bg}) is {r:.2f}:1, "
        f"below WCAG AA {AA_TEXT}:1 for normal text")


@pytest.mark.parametrize("theme,tokens", [("dark", DARK), ("light", LIGHT)])
def test_muted_soft_clears_the_non_text_threshold(theme, tokens):
    """It is decoration-only, so 3:1 is the bar — but it must clear it
    with margin, not sit on 3.01 as the light value used to."""
    fg, bg = tokens["--muted-soft"], tokens["--bg"]
    r = contrast(fg, bg)
    assert r >= AA_NON_TEXT + 0.15, (
        f"{theme}: --muted-soft ({fg}) on --bg ({bg}) is {r:.2f}:1 — too "
        f"close to the {AA_NON_TEXT}:1 floor for graphical objects")


@pytest.mark.parametrize("theme,tokens", [("dark", DARK), ("light", LIGHT)])
def test_muted_soft_stays_softer_than_muted(theme, tokens):
    """If it stopped being the fainter tier it would have no reason to
    exist and every decorative mark would jump in weight."""
    soft = contrast(tokens["--muted-soft"], tokens["--bg"])
    muted = contrast(tokens["--muted"], tokens["--bg"])
    assert soft < muted, (
        f"{theme}: --muted-soft ({soft:.2f}) is no longer fainter than "
        f"--muted ({muted:.2f})")


# ── --muted-soft must not creep back into text ────────────────────────

def _style_sources():
    files = list(SRC.glob("*.css")) + list(SRC.glob("modules/*.css"))
    files += list((REPO / "pixcull" / "report" / "templates"
                   / "pages").glob("*.html"))
    files.append(SERVE_APP)
    return files


# Properties that paint TEXT. `border-color`, `background`, `stroke` and
# `fill` are graphical and may keep the soft tier.
_TEXT_PROP = re.compile(r"(?<![-\w])color\s*:\s*var\(--muted-soft")


@pytest.mark.parametrize("path", _style_sources(), ids=lambda p: p.name)
def test_muted_soft_is_not_used_as_a_text_colour(path):
    text = path.read_text("utf-8")
    hits = [i + 1 for i, ln in enumerate(text.splitlines())
            if _TEXT_PROP.search(ln)]
    # The breadcrumb divider is punctuation, not prose: user-select:none,
    # conveys nothing, and is exempt as a purely decorative mark.
    hits = [n for n in hits
            if "crumb-divider" not in "\n".join(
                text.splitlines()[max(0, n - 3):n])]
    # The library-panel chevron and icon button are graphical affordances.
    hits = [n for n in hits
            if not any(k in "\n".join(text.splitlines()[max(0, n - 5):n])
                       for k in ('content: "›"', "lp-icon", "lp-chev"))]
    assert not hits, (
        f"{path.name}: --muted-soft used as a text colour at line(s) "
        f"{hits}. It only clears the 3:1 graphical bar, not the 4.5:1 "
        f"text bar — use --muted for anything readable.")
