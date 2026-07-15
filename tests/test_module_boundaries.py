"""v2.16-P1 — module boundaries for the results.js split.

The frontend stays a single-file artifact at runtime, but its source is now
results.js + src/modules/*.js spliced by build_results_html at @@MODULE:
markers. These lints machine-enforce the boundary so the next
"one broken invariant → nine simultaneous bugs" (v2.13) can't creep back in
through the module seams:

  1. marker discipline — every module has exactly one marker, no orphans,
     no unresolved markers (mirrors the build's own failure modes);
  2. each module is ONE self-contained IIFE statement (no top-level
     declarations leaking into the main closure);
  3. cross-module isolation — a module may not reference another module's
     internal top-level names; modules talk via window.PixCull* only.
"""

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "pixcull" / "report" / "templates" / "src"
_MOD = _SRC / "modules"


def _modules():
    return sorted(_MOD.glob("*.js"))


def test_marker_discipline():
    js = (_SRC / "results.js").read_text(encoding="utf-8")
    markers = re.findall(r"@@MODULE:([^@\n]+)@@", js)
    files = [m.name for m in _modules()]
    assert files, "module dir empty — the split disappeared?"
    assert sorted(markers) == sorted(files), (
        f"marker/file mismatch: markers={sorted(markers)} files={sorted(files)}")
    for name in files:
        assert markers.count(name) == 1, f"{name}: marker not unique"


def test_each_module_is_one_iife():
    for mod in _modules():
        text = mod.read_text(encoding="utf-8")
        # first code line (skip comments / blanks)
        first = next((l for l in text.splitlines()
                      if l.strip() and not l.strip().startswith(("//", "/*", "*"))), "")
        assert re.match(r"\s*(?:window\.[A-Za-z_$][\w$]*\s*=\s*)?\(function", first), (
            f"{mod.name}: does not open as an IIFE: {first[:60]!r}")
        last = next((l for l in reversed(text.splitlines()) if l.strip()), "")
        assert last.strip().rstrip(";").endswith("})()") or last.strip() == "})();", (
            f"{mod.name}: does not close as an IIFE: {last[:60]!r}")


# A module's noteworthy internals: declarations at the IIFE's top level
# (4-space indent). The self-exemption below must look at ANY indent —
# a module legitimately declares its own `gridEl` / `dismissed` deep
# inside a nested function, and that must not read as a cross-reference.
_DECL_TOP = re.compile(
    r"^\s{4}(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    r"|^\s{4}(?:const|let|var)\s+([A-Za-z_$][\w$]*)", re.M)
_DECL_ANY = re.compile(
    r"^\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    r"|^\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"|\bcatch\s*\(\s*([A-Za-z_$][\w$]*)"
    r"|\(([A-Za-z_$][\w$]*)\s*(?:,|\)\s*(?:=>|\{))", re.M)


def _names(rx, text: str) -> set:
    out = set()
    for m in rx.finditer(text):
        out.update(g for g in m.groups() if g)
    return out


def _strip_comments(text: str) -> str:
    """Reference-scan on CODE only — a prose word in a comment ("wait until
    onboarding done") must not read as a cross-module reference. Heuristic:
    /* … */ blocks, full-line //, and ` // trailing` (space-guarded so URL
    "https://" strings survive)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    text = re.sub(r"\s//\s.*$", "", text, flags=re.M)
    return text


def test_cross_module_isolation():
    mods = {m.name: m.read_text(encoding="utf-8") for m in _modules()}
    top = {name: _names(_DECL_TOP, text) for name, text in mods.items()}
    own = {name: _names(_DECL_ANY, text) for name, text in mods.items()}
    violations = []
    code = {name: _strip_comments(text) for name, text in mods.items()}
    for a, a_decls in top.items():
        for b in mods:
            if a == b:
                continue
            for name in a_decls:
                if name in own[b]:
                    continue          # b declares/binds its own `name` — fine
                if len(name) < 4:
                    continue          # skip tiny common identifiers
                if re.search(rf"\b{re.escape(name)}\b", code[b]):
                    violations.append(f"{b} references {a}'s internal {name!r}")
    assert not violations, (
        "modules must communicate via window.PixCull* only:\n  "
        + "\n  ".join(violations))
