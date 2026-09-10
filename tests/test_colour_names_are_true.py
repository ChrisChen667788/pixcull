"""v3.66 — the design system and the product disagreed, and both called it indigo.

`docs/OPEN-ITEMS.md` ask 5 asked the owner to pick between three brand
ramps. Measuring it first turned the question into a different one.

**There was no three-way choice.** `results.html`'s own tokens.css already
calls `#d5b584` `--accent` and names it champagne gold.
`scripts/brand/pixcull-brand.json`'s lighter ramp is keyed
`wordmarkStart/Mid/End` — a different ROLE (a wordmark on a dark banner),
not a competing opinion. Only `design-system/tokens.json` held values
nothing renders, under the names `indigo` / `violet` / `pink` inherited
from the purple palette they replaced.

**And the ratchet that was supposed to fall when this was reconciled
could never have fallen.** `_load_design_tokens()` in
`scripts/lint_design_tokens.py` was defined, documented at length, and
never called — verified by AST, not grep. So the gate had never once read
the design system it exists to enforce. Three documents stated the
consequence as fact anyway: ask 5, the `_why` in `.lint_baseline.json`,
and a test docstring in this suite. All three said reconciling the
palettes would lower the number on its own.

What these tests hold:
  1. no colour token is named for a hue family its value is not in;
  2. the gate actually consults the design system;
  3. every template that ships to a user is scanned.
"""
import ast
import colorsys
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "design-system" / "tokens.json"
LINTER = ROOT / "scripts" / "lint_design_tokens.py"

#: Hue windows in degrees for the colour words a token name might carry.
#: Only words that make a falsifiable claim about hue are listed — `accent`,
#: `brand`, `surface` and `muted` say nothing about hue and are not checked.
HUE_WORDS = {
    "red":     [(345, 360), (0, 15)],
    "orange":  [(15, 45)],
    "amber":   [(30, 55)],
    "gold":    [(35, 60)],
    "champagne": [(30, 60)],
    "bronze":  [(20, 45)],
    "yellow":  [(50, 70)],
    "green":   [(80, 165)],
    "teal":    [(160, 200)],
    "cyan":    [(175, 200)],
    "blue":    [(200, 260)],
    "indigo":  [(240, 280)],
    "violet":  [(265, 295)],
    "purple":  [(270, 300)],
    "magenta": [(290, 330)],
    "pink":    [(300, 350)],
}

#: Below this saturation a colour has no meaningful hue, so a hue word
#: cannot be checked against it — but naming a grey after a hue is its own
#: kind of lie, so it fails with a different message.
MIN_SAT = 0.10

_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")


def _hue_sat(value: str):
    m = _HEX.match(value.strip())
    if not m:
        return None
    r, g, b = (int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s


def _colour_tokens():
    """(dotted path, value) for every leaf whose type is a colour."""
    doc = json.loads(TOKENS.read_text(encoding="utf-8"))
    out = []

    def walk(node, path=""):
        if not isinstance(node, dict):
            return
        if node.get("type") == "color" and isinstance(node.get("value"), str):
            out.append((path, node["value"]))
            return
        for k, v in node.items():
            if k.startswith("$"):
                continue
            walk(v, f"{path}.{k}" if path else k)

    walk(doc)
    return out


def test_no_colour_token_is_named_for_a_hue_it_is_not():
    """`color.brand.indigo = #c4b9a9` was a warm grey called indigo. It
    survived a whole design-system phase because nothing compares a name
    to its own value."""
    wrong = []
    for path, value in _colour_tokens():
        hs = _hue_sat(value)
        if hs is None:
            continue
        hue, sat = hs
        for word, windows in HUE_WORDS.items():
            if word not in path.lower().split("."):
                continue
            if sat < MIN_SAT:
                wrong.append(
                    f"{path} = {value} is effectively grey (sat "
                    f"{sat*100:.0f}%) but is named {word!r}")
                continue
            if not any(lo <= hue <= hi for lo, hi in windows):
                wrong.append(
                    f"{path} = {value} has hue {hue:.0f}° but is named "
                    f"{word!r}, which is {windows}")
    assert not wrong, "colour tokens named for a hue they are not:\n  " + \
        "\n  ".join(wrong)


def test_the_shipped_stylesheets_do_not_name_a_warm_colour_indigo():
    """The same lie lived in the product, not only the design system:
    `video_review.html` and `timeline.html` both defined `--indigo`,
    `--indigo2` and `--pink` holding `#d5b584`, `#eaca98` and `#93743f`.
    Renaming them changed no pixel — which is the point. Nothing about
    the product was wrong except what it called itself."""
    bad = []
    for path in sorted((ROOT / "pixcull").rglob("*.html")) + \
            sorted((ROOT / "pixcull").rglob("*.css")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
                r"(--(?:indigo|violet|pink|purple|magenta)\d*)\s*:\s*(#[0-9a-fA-F]{6})",
                text):
            hs = _hue_sat(m.group(2))
            if hs is None:
                continue
            hue, sat = hs
            word = re.sub(r"^--|\d+$", "", m.group(1))
            windows = HUE_WORDS.get(word, [])
            if sat >= MIN_SAT and not any(lo <= hue <= hi for lo, hi in windows):
                bad.append(f"{path.relative_to(ROOT)}: {m.group(1)} = "
                           f"{m.group(2)} (hue {hue:.0f}°)")
    assert not bad, ("CSS variables named for a hue they do not hold:\n  "
                     + "\n  ".join(bad))


def test_the_ratchet_actually_reads_the_design_system():
    """`_load_design_tokens` was dead code for two design-system phases.
    A gate that does not consult the thing it enforces is not enforcing
    it, and every document that quoted its behaviour was wrong."""
    tree = ast.parse(LINTER.read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    dead = sorted(n for n in defined - called if not n.startswith("__"))
    assert not dead, (
        f"{LINTER.name} defines but never calls {dead}. That is how this "
        "gate spent two phases not reading design-system/tokens.json while "
        "three documents described what it did with it.")


def test_every_template_a_user_opens_is_scanned():
    """The ratchet's target list was one file. `video_review.html` and
    `timeline.html` are written into a user's run directory and opened in
    their browser, and carried 32 uncounted inline hexes between them."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ldt", LINTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    targets = {str(p) for p in mod.DEFAULT_TARGETS}

    shipped = set()
    for p in (ROOT / "pixcull" / "report" / "templates").glob("*.html"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if "<style" in text.lower():
            shipped.add(str(p.relative_to(ROOT)))
    missing = sorted(shipped - targets)
    assert not missing, (
        "these templates carry a <style> block and ship to users, but the "
        f"design-token ratchet does not scan them: {missing}")


def test_the_baseline_keeps_the_reason_somebody_wrote():
    """Both write paths used to replace the file with a single key, so the
    first improvement in the number would have deleted the note explaining
    what the number was."""
    doc = json.loads(
        (ROOT / "design-system" / ".lint_baseline.json").read_text("utf-8"))
    assert isinstance(doc.get("max_violations"), int)
    assert doc.get("_why", "").strip(), (
        ".lint_baseline.json has no _why — a bare number nobody can audit")

    src = LINTER.read_text(encoding="utf-8")
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    assert body.count("BASELINE_PATH.write_text") <= 1, (
        "more than one place writes the baseline file; they drift, and the "
        "one that forgets to preserve _why deletes it")
