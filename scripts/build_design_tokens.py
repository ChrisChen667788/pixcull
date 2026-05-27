#!/usr/bin/env python3
"""v0.10-P2-A — design-system token compiler.

Reads ``design-system/tokens.json`` (the single source of truth a
designer can edit via Tokens Studio in Figma) and emits three
platform-specific targets:

  1. ``design-system/tokens.css`` — CSS custom properties under
     ``:root``.  Consumed by results.html via
     ``<link rel="stylesheet" href="/static/design-tokens.css">``
     (Phase A.1 adds the route; for now serve_demo inlines the
     same content).
  2. ``design-system/iOS/BrandTokens.swift`` — Swift constants
     under ``enum BrandTokens``.  Consumed by the iOS Companion
     in addition to BrandKit.swift's higher-level primitives.
  3. ``design-system/tokens.python.json`` — flattened key-value
     map for Python consumers (executive_pdf.py + cli_audit.py
     reach in for the brand gradient + serif stack).

Idempotent — running the script twice with the same input
produces byte-identical outputs.  Designed for CI to run as
``python scripts/build_design_tokens.py --check`` (no writes,
just verify the committed files match the JSON).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


HEADER = (
    "/*\n"
    " * AUTO-GENERATED — DO NOT EDIT BY HAND.\n"
    " *\n"
    " * Source of truth: design-system/tokens.json\n"
    " * Regenerate via:  python scripts/build_design_tokens.py\n"
    " *\n"
    " * Phase A of docs/DESIGN-SYSTEM-ROADMAP.md.  Edits to the JSON\n"
    " * propagate to web (this CSS file), iOS (BrandTokens.swift), and\n"
    " * Python (tokens.python.json) simultaneously on the next build.\n"
    " */\n"
)


def _flatten(node: Any, prefix: str = "", out: dict | None = None) -> dict:
    """Walk the nested Tokens Studio schema and return a flat
    map of ``dot.separated.path → resolved_value_str``.

    Resolves ``{color.semantic.success}``-style references by
    looking the target up in the source tree (one level of
    indirection only — the canonical Tokens Studio depth).
    """
    if out is None:
        out = {}

    def _resolve_refs(val: str, root: dict) -> str:
        # {a.b.c} → root["a"]["b"]["c"]["value"]
        if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
            parts = val[1:-1].split(".")
            cursor: Any = root
            for p in parts:
                if not isinstance(cursor, dict) or p not in cursor:
                    return val   # unresolved — surface as-is
                cursor = cursor[p]
            if isinstance(cursor, dict) and "value" in cursor:
                return cursor["value"]
        return val

    # Phase: walk
    def _walk(n, path, root):
        if not isinstance(n, dict):
            return
        # Leaf when it has a 'value' + 'type' field per Tokens Studio
        if "value" in n and "type" in n:
            out[path] = _resolve_refs(n["value"], root)
            return
        for k, v in n.items():
            if k.startswith("$") or k.startswith("_"):
                continue
            if k == "$comment":
                continue
            new_path = f"{path}.{k}" if path else k
            _walk(v, new_path, root)

    _walk(node, prefix, node)
    return out


def render_css(tokens: dict) -> str:
    """Emit CSS custom-property block."""
    lines = [HEADER, ":root {"]
    # Pre-sort so output is deterministic
    for key in sorted(tokens.keys()):
        val = tokens[key]
        css_var = "--" + key.replace(".", "-").lower()
        lines.append(f"  {css_var}: {val};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_swift(tokens: dict) -> str:
    """Emit Swift constants under ``enum BrandTokens``."""
    swift_header = (
        "// AUTO-GENERATED — DO NOT EDIT BY HAND.\n"
        "//\n"
        "// Source of truth: design-system/tokens.json\n"
        "// Regenerate via:  python scripts/build_design_tokens.py\n"
        "//\n"
        "// Companion to BrandKit.swift — that file has the high-level\n"
        "// SwiftUI primitives (RadialProgress, AISparkline); this one\n"
        "// has the raw token values straight from the design-system\n"
        "// JSON, useful when a SwiftUI view needs e.g. exactly --color-\n"
        "// surface-bg-card without going through a primitive.\n"
        "\n"
        "import SwiftUI\n"
        "\n"
        "public enum BrandTokens {\n"
    )
    lines = [swift_header]
    # Group by namespace for readability
    namespaces: dict[str, list[tuple[str, str]]] = {}
    for key in sorted(tokens.keys()):
        ns = key.split(".")[0]
        namespaces.setdefault(ns, []).append((key, tokens[key]))

    def _swift_safe_id(s: str) -> str:
        out = s.replace(".", "_").replace("-", "_")
        # Prepend underscore for ids starting with a digit (`1` → `_1`)
        if out and out[0].isdigit():
            out = "_" + out
        return out

    for ns, pairs in namespaces.items():
        lines.append(f"  // MARK: {ns}")
        for key, val in pairs:
            ident = _swift_safe_id(key)
            if isinstance(val, str) and val.startswith("#"):
                # Color value — keep as a String the caller can pass
                # to Color(hex:)/UIColor(hex:) (BrandKit defines a
                # convenience init).
                lines.append(
                    f"  public static let {ident}: String = \"{val}\""
                )
            elif isinstance(val, str) and val.endswith("px"):
                # Numeric spacing/font-size — emit as Double
                num = val.removesuffix("px")
                try:
                    f = float(num)
                    lines.append(
                        f"  public static let {ident}: Double = {f}"
                    )
                except ValueError:
                    lines.append(
                        f"  public static let {ident}: String = \"{val}\""
                    )
            else:
                # Everything else (rgba / gradient / cubic-bezier) → String
                escaped = val.replace('"', '\\"') if isinstance(val, str) else str(val)
                lines.append(
                    f"  public static let {ident}: String = \"{escaped}\""
                )
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_python_json(tokens: dict) -> str:
    """Emit a flat key→value map for Python consumers."""
    return json.dumps(tokens, indent=2, sort_keys=True,
                       ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Compile design-system/tokens.json to web + iOS + Python.")
    p.add_argument(
        "--source", type=Path,
        default=Path("design-system/tokens.json"),
        help="JSON source file (Tokens Studio schema)")
    p.add_argument(
        "--out-css", type=Path,
        default=Path("design-system/tokens.css"))
    p.add_argument(
        "--out-swift", type=Path,
        default=Path("design-system/iOS/BrandTokens.swift"))
    p.add_argument(
        "--out-python", type=Path,
        default=Path("design-system/tokens.python.json"))
    p.add_argument(
        "--check", action="store_true",
        help="CI mode — emit nothing, just verify that the on-disk "
             "outputs match what regeneration would produce.  Exits 0 "
             "when files are in sync, 2 when drift detected.")
    args = p.parse_args(argv)

    try:
        raw = json.loads(args.source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[tokens] source not found: {args.source}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[tokens] bad JSON in {args.source}: {exc}", file=sys.stderr)
        return 1

    tokens = _flatten(raw)
    css      = render_css(tokens)
    swift    = render_swift(tokens)
    py_json  = render_python_json(tokens)

    if args.check:
        drift = []
        for path, expected in (
            (args.out_css, css),
            (args.out_swift, swift),
            (args.out_python, py_json),
        ):
            if not path.exists():
                drift.append(f"missing: {path}")
                continue
            actual = path.read_text(encoding="utf-8")
            if actual != expected:
                drift.append(f"drift: {path}")
        if drift:
            print("[tokens] CI drift detected:", file=sys.stderr)
            for d in drift:
                print(f"  - {d}", file=sys.stderr)
            print(
                "[tokens] Run 'python scripts/build_design_tokens.py'"
                " to regenerate, then commit.",
                file=sys.stderr,
            )
            return 2
        print(f"[tokens] OK — {len(tokens)} tokens, all targets in sync",
              file=sys.stderr)
        return 0

    args.out_css.parent.mkdir(parents=True, exist_ok=True)
    args.out_swift.parent.mkdir(parents=True, exist_ok=True)
    args.out_python.parent.mkdir(parents=True, exist_ok=True)
    args.out_css.write_text(css, encoding="utf-8")
    args.out_swift.write_text(swift, encoding="utf-8")
    args.out_python.write_text(py_json, encoding="utf-8")
    print(
        f"[tokens] wrote {args.out_css}, {args.out_swift}, {args.out_python}"
        f" ({len(tokens)} tokens)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
