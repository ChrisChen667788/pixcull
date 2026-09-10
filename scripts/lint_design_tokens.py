#!/usr/bin/env python3
"""v0.10-P2-A — CI lint enforcing design-token discipline.

Scans `pixcull/report/templates/results.html` for inline color
literals that should be using a `var(--color-*)` reference from
`design-system/tokens.json` instead.

This is the "no new visual debt" gate.  The existing 15k LOC of
results.html accumulated ~200 hex colors before Phase A landed —
we don't try to migrate all of them at once (that's Phase A.1).
We DO refuse to let new ones land: this script tracks a baseline
of currently-legal violations and fails CI when it grows.

v3.66 — `_load_design_tokens()` was defined here and NEVER CALLED.
Its docstring described a short-circuit for hexes that match a
canonical token; the scan never consulted it, so this gate has
never once read the design system it exists to enforce.  Three
documents repeated the consequence as fact — `docs/OPEN-ITEMS.md`
ask 5, the `_why` field in `.lint_baseline.json`, and a test
docstring — all saying that reconciling the palettes would make
the number fall on its own.  It could not have.  The number was
"count of inline hex" and nothing else.

It is wired in now, and the count is split rather than
short-circuited, because those are two different debts:

  undesigned — a hex that is in NO design token.  Real debt: a
               colour nobody decided on.  This is what the
               baseline ratchets.
  unmigrated — a hex that IS a design token, written as a
               literal instead of `var(--…)`.  Mechanical, and
               it must not vanish from the report just because
               the token file learned the value — that would let
               a palette edit erase 55 violations without one
               line of CSS improving.

Rules
=====
A violation is:
  * A `#RRGGBB` or `#RGB` literal
  * Inside a CSS rule block (between `<style>` and `</style>` of
    a *.html file, or anywhere in a *.css file)

and it is `unmigrated` when its value is a design token,
`undesigned` otherwise.

Sanctioned exceptions (NOT counted as violations):
  * Inside an SVG `<symbol>` block — those are illustration
    pixel art, not theme colors
  * Inside a `/* … */` CSS comment — explanatory
  * `#000` and `#fff` — universal opacity-base / contrast-text
    primitives that don't need a token

Baseline
========
On first run, this script writes the current count to
`design-system/.lint_baseline.json`.  Subsequent runs allow at
most that count; a single new violation makes it fail.  This
encourages incremental migration: every PR removes one inline
hex, the baseline shrinks, eventually reaches zero.

Usage
=====
    # CI mode — fails on any growth over baseline
    python scripts/lint_design_tokens.py

    # Migration helper — print a list of violations grouped by file
    python scripts/lint_design_tokens.py --list

    # Reset baseline (use after a deliberate inline-hex addition,
    # e.g. illustration palette inside a new SVG symbol)
    python scripts/lint_design_tokens.py --update-baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3,8})\b")

SANCTIONED_HEX = {
    "#000", "#fff", "#000000", "#ffffff",
    "#FFF", "#FFFFFF",   # case variants
}

DEFAULT_TARGETS = (
    Path("pixcull/report/templates/results.html"),
    # v3.66 — these two ship to users and were scanned by nothing.
    # 32 further violations lived behind that, including the three
    # CSS variables literally named --indigo / --indigo2 / --pink
    # holding the warm gold.
    Path("pixcull/report/templates/video_review.html"),
    Path("pixcull/report/templates/timeline.html"),
)

BASELINE_PATH = Path("design-system/.lint_baseline.json")


def _load_design_tokens() -> set[str]:
    """Pull every color hex string out of tokens.json so we can
    short-circuit violations whose value happens to match a
    canonical token (those should be using the var(--) form,
    but they're not a *new* color — they're a forgotten
    migration).
    """
    p = Path("design-system/tokens.json")
    if not p.exists():
        return set()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    found: set[str] = set()

    def _walk(n):
        if isinstance(n, dict):
            if "value" in n and isinstance(n["value"], str):
                for m in HEX_RE.finditer(n["value"]):
                    found.add(m.group(0).lower())
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for v in n:
                _walk(v)
    _walk(doc)
    return found


#: A paint literal outside a stylesheet still paints. Matching these by
#: text is deliberate: several live inside JavaScript that assembles SVG
#: as a string, where there is no DOM to inspect and no CSS to parse.
_INLINE_STYLE = re.compile(r"""style\s*=\s*(["'])(.*?)\1""", re.I | re.S)
_PAINT_ATTR = re.compile(
    r"""\b(?:fill|stroke|stop-color|flood-color|lighting-color|color|"""
    r"""bgcolor)\s*=\s*(["'])\s*(\#[0-9a-fA-F]{3,8})\s*\1""", re.I)
#: `--token: #hex` — the definition of a custom property. This is the one
#: place a literal is mandatory: a token cannot be a var() reference to
#: itself. Counting these as "unmigrated" is what v3.71 came from.
_DEFINITION = re.compile(r"--[A-Za-z0-9_-]+\s*:\s*(\#[0-9a-fA-F]{3,8})")


def _sanctioned() -> set[str]:
    return {h.lower() for h in SANCTIONED_HEX}


def _scan(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, hex_value, kind) for every paint literal.

    ``kind`` is one of:

    ``rule``        a declaration inside a stylesheet — migratable
    ``definition``  ``--token: #hex`` — a custom property being defined,
                    which cannot become a var() reference to itself
    ``inline``      a ``style="…"`` attribute in the body
    ``paint``       an SVG/HTML paint attribute, including ones built
                    inside JavaScript strings

    v3.71 — this used to look only inside ``<style>``, so it saw one of
    the three places a single-file HTML app paints. The consequence was
    not a shortfall but an inversion: of the three literals it found in
    ``video_review.html`` all three were ``:root`` definitions, the only
    kind that cannot be migrated, while all seven real usages sat in
    JavaScript building SVG and were invisible to it.

    Skips lines inside SVG <symbol> blocks (illustration pixels)
    and inside comments.  Defensive against multi-line comments
    and `<symbol>` blocks: a stateful single-pass parse.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []

    is_html = path.suffix.lower() in (".html", ".htm")
    lines = text.splitlines()

    violations: list[tuple[int, str, str]] = []
    in_style = not is_html        # plain .css → always in-style
    in_block_comment = False
    in_symbol_block = 0           # nest depth (defensive)

    style_open  = re.compile(r"<style\b", re.IGNORECASE)
    style_close = re.compile(r"</style>", re.IGNORECASE)
    sym_open    = re.compile(r"<symbol\b", re.IGNORECASE)
    sym_close   = re.compile(r"</symbol>", re.IGNORECASE)

    for i, line in enumerate(lines, start=1):
        # Split the line into its stylesheet part and its body part.
        #
        # v3.71 — this used to flip a flag on `<style` and off on
        # `</style>`, so a block that opened and closed on one line
        # turned itself off before its content was read and the CSS in
        # it was never scanned at all. Harmless while every literal
        # outside a stylesheet was ignored anyway; the moment the body
        # became a place worth looking, a one-line block started being
        # read as body and its declarations matched nothing.
        css_part, body_part = (line, "") if in_style else ("", line)
        if is_html and (style_open.search(line) or style_close.search(line)):
            css_part, body_part, pos = "", "", 0
            while pos < len(line):
                if in_style:
                    m = style_close.search(line, pos)
                    end = m.start() if m else len(line)
                    css_part += line[pos:end]
                    if not m:
                        break
                    in_style, pos = False, m.end()
                else:
                    m = style_open.search(line, pos)
                    end = m.start() if m else len(line)
                    body_part += line[pos:end]
                    if not m:
                        break
                    # skip to the end of the opening tag
                    gt = line.find(">", m.end())
                    in_style, pos = True, (gt + 1 if gt != -1 else m.end())
        # Symbol blocks (HTML body)
        if sym_open.search(line):
            in_symbol_block += 1
        if sym_close.search(line):
            in_symbol_block = max(0, in_symbol_block - 1)
        if in_symbol_block:
            continue
        if body_part:
            # A stylesheet is not the only thing that paints, so look at
            # the two surfaces that also do.
            for m in _INLINE_STYLE.finditer(body_part):
                for h in HEX_RE.finditer(m.group(2)):
                    if h.group(0).lower() not in _sanctioned():
                        violations.append((i, h.group(0), "inline"))
            for m in _PAINT_ATTR.finditer(body_part):
                if m.group(2).lower() not in _sanctioned():
                    violations.append((i, m.group(2), "paint"))
        if not css_part:
            continue
        # Multi-line CSS comments
        l = css_part
        if in_block_comment:
            end = l.find("*/")
            if end == -1:
                continue
            l = l[end + 2:]
            in_block_comment = False
        # Strip line comments + inline /* */
        l = re.sub(r"/\*.*?\*/", "", l)
        if "/*" in l:
            l = l.split("/*")[0]
            in_block_comment = True
        defined = {d.lower() for d in _DEFINITION.findall(l)}
        for m in HEX_RE.finditer(l):
            hexval = m.group(0)
            if hexval.lower() in _sanctioned():
                continue
            kind = "definition" if hexval.lower() in defined else "rule"
            violations.append((i, hexval, kind))
    return violations


def undesigned(violations, tokens) -> list:
    """Hexes that are in no design token at all — the ratcheted number."""
    return [(ln, h, k) for ln, h, k in violations if h.lower() not in tokens]


def unmigrated(violations, tokens) -> list:
    """A token's value written as a literal where a var() would do.

    v3.71 — `definition` is excluded. `--accent: #d5b584` is the token
    being defined, and a token cannot be a var() reference to itself, so
    counting it as work-to-do described something nobody could ever act
    on. In `video_review.html` that was the entire number: three counted,
    all three definitions, and the seven real usages in JavaScript-built
    SVG unseen.

    At module level rather than nested in main() so a test can check the
    number the tool reports. The first cut left it inside main(), and the
    mutation that put definitions back into the count changed nothing any
    test could see — the label was covered and the use of the label was
    not.
    """
    return [(ln, h, k) for ln, h, k in violations
            if h.lower() in tokens and k != "definition"]


def _write_baseline(total: int) -> None:
    """Rewrite the count and keep everything else in the file.

    v3.66 — both write sites used to replace the whole document with
    ``{"max_violations": n}``, which silently deleted the ``_why`` field
    somebody had written to explain the number. The first improvement
    would have erased the explanation of what the number was for.
    """
    doc = {}
    if BASELINE_PATH.exists():
        try:
            existing = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                doc = existing
        except json.JSONDecodeError:
            doc = {}
    doc["max_violations"] = total
    BASELINE_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Lint design-token discipline (no inline hex)."
    )
    p.add_argument("--list", action="store_true",
                   help="Print every violation grouped by file")
    p.add_argument("--update-baseline", action="store_true",
                   help="Overwrite .lint_baseline.json with the "
                        "current violation count (use after a "
                        "deliberate addition).")
    p.add_argument("--targets", nargs="*", type=Path,
                   default=list(DEFAULT_TARGETS))
    args = p.parse_args(argv)

    tokens = _load_design_tokens()

    all_violations: dict[Path, list[tuple[int, str, str]]] = {}
    for t in args.targets:
        vs = _scan(t)
        if vs:
            all_violations[t] = vs

    def _undesigned(vs):
        return undesigned(vs, tokens)

    def _unmigrated(vs):
        return unmigrated(vs, tokens)

    total = sum(len(_undesigned(vs)) for vs in all_violations.values())
    n_unmigrated = sum(len(_unmigrated(vs)) for vs in all_violations.values())

    if args.list:
        for path, vs in all_violations.items():
            und = _undesigned(vs)
            print(f"\n--- {path} · {len(und)} undesigned, "
                  f"{len(_unmigrated(vs))} unmigrated ---")
            for ln, h, k in und[:30]:
                print(f"  line {ln:>5}  {h}  [{k}]")
            if len(und) > 30:
                print(f"  … +{len(und) - 30} more")
        print(f"\nTOTAL undesigned: {total}   unmigrated: {n_unmigrated}")
        return 0

    if args.update_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write_baseline(total)
        print(f"[design-lint] baseline updated → {total}", file=sys.stderr)
        return 0

    # CI gate: read baseline + compare
    baseline = 0
    if BASELINE_PATH.exists():
        try:
            baseline = int(json.loads(
                BASELINE_PATH.read_text(encoding="utf-8")
            ).get("max_violations", 0))
        except (json.JSONDecodeError, ValueError):
            baseline = 0

    if not tokens:
        # A gate that cannot read the design system is not a gate that
        # agrees with it. This is the shape the whole v3.66 finding took.
        print("[design-lint] FAIL — design-system/tokens.json produced no "
              "colour values; every hex would count as undesigned",
              file=sys.stderr)
        return 2

    if total > baseline:
        new_n = total - baseline
        print(
            f"[design-lint] FAIL — {new_n} new inline-hex violation(s) "
            f"introduced (total {total} > baseline {baseline})",
            file=sys.stderr,
        )
        print(
            "[design-lint] Use a var(--color-*) reference from "
            "design-system/tokens.json instead, or run "
            "'python scripts/lint_design_tokens.py --list' to see "
            "all violations.",
            file=sys.stderr,
        )
        return 2

    if total < baseline:
        # v3.46 — but not when we scanned nothing. `_scan` returns [] for
        # a path that does not exist, so a renamed target reads as "zero
        # violations, huge progress" and rewrites the baseline to 0 —
        # after which every real run is red for a reason that has nothing
        # to do with the code. Seen within minutes of first wiring this
        # up: a mutation test pointed the scanner at a moved filename and
        # the baseline went to 0 on disk.
        if not all_violations and total == 0:
            print("[design-lint] refusing to lower the baseline — no "
                  "target file was readable, which is a configuration "
                  "error, not migration progress", file=sys.stderr)
            return 2
        # Migration progress! Lower the baseline so we don't regress.
        _write_baseline(total)
        print(
            f"[design-lint] OK — {baseline - total} undesigned colour(s) "
            f"resolved; baseline lowered to {total} "
            f"({n_unmigrated} unmigrated)",
            file=sys.stderr,
        )
        return 0

    print(
        f"[design-lint] OK — {total} undesigned (at baseline), "
        f"{n_unmigrated} unmigrated",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
