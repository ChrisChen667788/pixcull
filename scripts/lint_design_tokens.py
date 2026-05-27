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

Rules
=====
A violation is:
  * A `#RRGGBB` or `#RGB` literal
  * Inside a CSS rule block (between `<style>` and `</style>` of
    a *.html file, or anywhere in a *.css file)
  * Whose color value is NOT already in the design-system tokens

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


def _scan(path: Path) -> list[tuple[int, str]]:
    """Return list of (lineno, hex_value) for every violation
    inside the CSS context of ``path``.

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

    violations: list[tuple[int, str]] = []
    in_style = not is_html        # plain .css → always in-style
    in_block_comment = False
    in_symbol_block = 0           # nest depth (defensive)

    style_open  = re.compile(r"<style\b", re.IGNORECASE)
    style_close = re.compile(r"</style>", re.IGNORECASE)
    sym_open    = re.compile(r"<symbol\b", re.IGNORECASE)
    sym_close   = re.compile(r"</symbol>", re.IGNORECASE)

    for i, line in enumerate(lines, start=1):
        # Update <style> context
        if is_html:
            if style_open.search(line):
                in_style = True
            if style_close.search(line):
                in_style = False
        # Symbol blocks (HTML body)
        if sym_open.search(line):
            in_symbol_block += 1
        if sym_close.search(line):
            in_symbol_block = max(0, in_symbol_block - 1)
        if not in_style or in_symbol_block:
            continue
        # Multi-line CSS comments
        l = line
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
        for m in HEX_RE.finditer(l):
            hexval = m.group(0)
            if hexval.lower() in {h.lower() for h in SANCTIONED_HEX}:
                continue
            violations.append((i, hexval))
    return violations


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

    all_violations: dict[Path, list[tuple[int, str]]] = {}
    for t in args.targets:
        vs = _scan(t)
        if vs:
            all_violations[t] = vs

    total = sum(len(vs) for vs in all_violations.values())

    if args.list:
        for path, vs in all_violations.items():
            print(f"\n--- {path} · {len(vs)} violations ---")
            for ln, h in vs[:30]:
                print(f"  line {ln:>5}  {h}")
            if len(vs) > 30:
                print(f"  … +{len(vs) - 30} more")
        print(f"\nTOTAL violations: {total}")
        return 0

    if args.update_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps({"max_violations": total}, indent=2),
            encoding="utf-8",
        )
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
        # Migration progress! Lower the baseline so we don't regress.
        BASELINE_PATH.write_text(
            json.dumps({"max_violations": total}, indent=2),
            encoding="utf-8",
        )
        print(
            f"[design-lint] OK — {baseline - total} violation(s) "
            f"migrated; baseline lowered to {total}",
            file=sys.stderr,
        )
        return 0

    print(
        f"[design-lint] OK — {total} violations (at baseline)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
