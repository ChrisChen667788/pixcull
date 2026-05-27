"""Tests for the Phase-A design-token infrastructure.

Covers
------
* build_design_tokens: flatten + reference resolution + CSS / Swift
  output shapes + check-mode drift detection
* lint_design_tokens: scan of inline hex + sanctioned exceptions
  + baseline mechanism
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load(rel_path: str):
    p = Path(__file__).resolve().parent.parent / "scripts" / rel_path
    spec = importlib.util.spec_from_file_location(rel_path, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# build_design_tokens
# ---------------------------------------------------------------------------


def _make_tokens_json(tmp_path: Path) -> Path:
    p = tmp_path / "tokens.json"
    p.write_text(json.dumps({
        "color": {
            "brand": {
                "indigo": {"value": "#6E56CF", "type": "color"},
            },
            "semantic": {
                "success": {"value": "#34d399", "type": "color"},
            },
            "decision": {
                "keep": {"value": "{color.semantic.success}", "type": "color"},
            },
        },
        "spacing": {
            "1": {"value": "4px", "type": "spacing"},
            "2": {"value": "8px", "type": "spacing"},
        },
        "motion": {
            "ease": {
                "out": {
                    "value": "cubic-bezier(0.34, 1.56, 0.64, 1)",
                    "type": "cubicBezier",
                },
            },
        },
    }), encoding="utf-8")
    return p


def test_flatten_collapses_nested_structure(tmp_path):
    bd = _load("build_design_tokens.py")
    src = json.loads(_make_tokens_json(tmp_path).read_text())
    flat = bd._flatten(src)
    assert flat["color.brand.indigo"] == "#6E56CF"
    assert flat["color.semantic.success"] == "#34d399"
    assert flat["spacing.1"] == "4px"
    assert flat["motion.ease.out"] == "cubic-bezier(0.34, 1.56, 0.64, 1)"


def test_flatten_resolves_token_references(tmp_path):
    """{color.semantic.success} → the actual hex value."""
    bd = _load("build_design_tokens.py")
    src = json.loads(_make_tokens_json(tmp_path).read_text())
    flat = bd._flatten(src)
    # color.decision.keep references color.semantic.success
    assert flat["color.decision.keep"] == "#34d399"


def test_flatten_skips_comment_and_meta_keys(tmp_path):
    """$schema, $comment, _themes etc. must NOT appear in the output."""
    bd = _load("build_design_tokens.py")
    src = json.loads((tmp_path / "tokens.json").write_text(json.dumps({
        "$schema": "https://...",
        "$comment": "should be ignored",
        "_themes": {"$comment": "ditto"},
        "color": {"x": {"value": "#fff", "type": "color"}},
    }))) if False else json.loads(_make_tokens_json(tmp_path).read_text())
    src["$schema"] = "https://test"
    src["$comment"] = "should be ignored"
    src["_themes"] = {"foo": "bar"}
    flat = bd._flatten(src)
    assert not any("schema" in k.lower() for k in flat)
    assert not any("comment" in k.lower() for k in flat)
    assert not any(k.startswith("_themes") for k in flat)


def test_render_css_emits_well_formed_block(tmp_path):
    bd = _load("build_design_tokens.py")
    flat = bd._flatten(json.loads(_make_tokens_json(tmp_path).read_text()))
    css = bd.render_css(flat)
    # Header + :root block
    assert "AUTO-GENERATED" in css
    assert css.strip().startswith("/*")
    assert ":root {" in css
    assert css.strip().endswith("}")
    # Token names use --color-* / --spacing-* / --motion-* prefix
    assert "--color-brand-indigo: #6E56CF;" in css
    assert "--spacing-1: 4px;" in css


def test_render_css_is_deterministic(tmp_path):
    """Same input → byte-identical output."""
    bd = _load("build_design_tokens.py")
    flat = bd._flatten(json.loads(_make_tokens_json(tmp_path).read_text()))
    assert bd.render_css(flat) == bd.render_css(flat)


def test_render_swift_groups_by_namespace(tmp_path):
    bd = _load("build_design_tokens.py")
    flat = bd._flatten(json.loads(_make_tokens_json(tmp_path).read_text()))
    swift = bd.render_swift(flat)
    assert "public enum BrandTokens {" in swift
    assert "// MARK: color" in swift
    assert "// MARK: spacing" in swift
    # Hex colors → String, sized numerics → Double
    assert 'public static let color_brand_indigo: String = "#6E56CF"' in swift
    assert "public static let spacing_1: Double = 4.0" in swift


def test_render_swift_identifiers_safe_for_digits():
    """Spacing tokens are keyed by `1`, `2`, ... — Swift identifiers
    can't start with a digit, so we prefix with underscore."""
    bd = _load("build_design_tokens.py")
    swift = bd.render_swift({"spacing.1": "4px", "color.x.normal": "#fff"})
    # Direct `1: Double = 4` would be a Swift syntax error; we want spacing_1
    assert "spacing_1" in swift
    assert "color_x_normal" in swift


def test_render_python_json_is_sorted_and_complete(tmp_path):
    bd = _load("build_design_tokens.py")
    flat = bd._flatten(json.loads(_make_tokens_json(tmp_path).read_text()))
    txt = bd.render_python_json(flat)
    parsed = json.loads(txt)
    assert parsed["color.brand.indigo"] == "#6E56CF"
    # Sorted
    keys = list(parsed.keys())
    assert keys == sorted(keys)


def test_check_mode_passes_when_outputs_match(tmp_path, monkeypatch):
    """--check exits 0 when on-disk files match the JSON."""
    bd = _load("build_design_tokens.py")
    src = _make_tokens_json(tmp_path)
    out_css   = tmp_path / "tokens.css"
    out_swift = tmp_path / "ios" / "Tokens.swift"
    out_py    = tmp_path / "tokens.python.json"
    # Generate first
    assert bd.main([
        "--source", str(src),
        "--out-css", str(out_css),
        "--out-swift", str(out_swift),
        "--out-python", str(out_py),
    ]) == 0
    # Then verify
    rc = bd.main([
        "--source", str(src),
        "--out-css", str(out_css),
        "--out-swift", str(out_swift),
        "--out-python", str(out_py),
        "--check",
    ])
    assert rc == 0


def test_check_mode_detects_drift(tmp_path):
    """--check exits 2 when the JSON changed but the targets didn't."""
    bd = _load("build_design_tokens.py")
    src = _make_tokens_json(tmp_path)
    out_css = tmp_path / "tokens.css"
    out_swift = tmp_path / "Tokens.swift"
    out_py = tmp_path / "tokens.python.json"
    # Initial build
    bd.main([
        "--source", str(src),
        "--out-css", str(out_css),
        "--out-swift", str(out_swift),
        "--out-python", str(out_py),
    ])
    # Mutate the JSON
    doc = json.loads(src.read_text(encoding="utf-8"))
    doc["color"]["brand"]["indigo"]["value"] = "#000000"
    src.write_text(json.dumps(doc), encoding="utf-8")
    # Check now detects drift
    rc = bd.main([
        "--source", str(src),
        "--out-css", str(out_css),
        "--out-swift", str(out_swift),
        "--out-python", str(out_py),
        "--check",
    ])
    assert rc == 2


# ---------------------------------------------------------------------------
# lint_design_tokens
# ---------------------------------------------------------------------------


def _make_results_html(tmp_path: Path, *, body: str) -> Path:
    p = tmp_path / "results.html"
    p.write_text(
        "<!DOCTYPE html><html><head><style>\n"
        + body
        + "\n</style></head><body></body></html>",
        encoding="utf-8",
    )
    return p


def test_lint_finds_inline_hex(tmp_path):
    lint = _load("lint_design_tokens.py")
    p = _make_results_html(tmp_path, body="""
        :root { --accent: #6e56cf; }
        .card { background: #1a1c20; color: #fff; }
    """)
    v = lint._scan(p)
    found = [h for _, h in v]
    assert "#6e56cf" in found
    assert "#1a1c20" in found
    # #fff is sanctioned
    assert "#fff" not in found


def test_lint_skips_svg_symbol_blocks(tmp_path):
    """Illustration palettes inside <symbol> blocks are explicit
    pixel art, not theme colors — they don't get linted."""
    lint = _load("lint_design_tokens.py")
    p = _make_results_html(tmp_path, body="""
        .real { background: #6e56cf; }
    """)
    # Append SVG symbol block to the HTML, post-style
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            "<body>",
            "<body>\n<svg><symbol id=art><rect fill=#abcdef /></symbol></svg>",
        ),
        encoding="utf-8",
    )
    found = [h for _, h in lint._scan(p)]
    assert "#6e56cf" in found
    assert "#abcdef" not in found


def test_lint_skips_inline_comments(tmp_path):
    lint = _load("lint_design_tokens.py")
    p = _make_results_html(tmp_path, body="""
        .a { /* color: #deadbe; was an old token */
             background: #6e56cf; }
    """)
    found = [h for _, h in lint._scan(p)]
    assert "#6e56cf" in found
    assert "#deadbe" not in found


def test_lint_skips_block_comments_multiline(tmp_path):
    lint = _load("lint_design_tokens.py")
    p = _make_results_html(tmp_path, body="""
        /*
         * old palette:
         *   --accent: #6e56cf;
         */
        .a { background: #abcdef; }
    """)
    found = [h for _, h in lint._scan(p)]
    assert "#6e56cf" not in found
    assert "#abcdef" in found


def test_lint_sanctioned_hexes_are_allowed(tmp_path):
    """#fff and #000 are universal primitives, never count as
    violations."""
    lint = _load("lint_design_tokens.py")
    p = _make_results_html(tmp_path, body="""
        .a { color: #fff; }
        .b { color: #000000; }
        .c { color: #FFFFFF; }
        .d { color: #abcdef; }
    """)
    found = [h.lower() for _, h in lint._scan(p)]
    assert found == ["#abcdef"]


def test_lint_returns_empty_for_missing_file(tmp_path):
    lint = _load("lint_design_tokens.py")
    assert lint._scan(tmp_path / "missing.html") == []


def test_lint_handles_pure_css_file(tmp_path):
    """No <style> tag means the whole file is CSS context."""
    lint = _load("lint_design_tokens.py")
    p = tmp_path / "tokens.css"
    p.write_text(":root { --x: #aabbcc; }\n", encoding="utf-8")
    found = [h for _, h in lint._scan(p)]
    assert "#aabbcc" in found
