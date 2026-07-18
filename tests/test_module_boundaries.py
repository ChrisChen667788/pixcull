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


# ── v2.22-P2 — the CSS side of the split (@@CSS: markers) ─────────────
def _css_modules():
    return sorted(_MOD.glob("*.css"))


def test_css_marker_discipline():
    """Same contract as the JS markers: modules/*.css ↔ @@CSS: markers
    resolve 1:1, each marker unique.  Build fails on violation too —
    this test catches it without running the build."""
    css = (_SRC / "results.css").read_text(encoding="utf-8")
    markers = re.findall(r"@@CSS:([^@\n]+)@@", css)
    files = [m.name for m in _css_modules()]
    assert files, "css module dir empty — the v2.22 split disappeared?"
    assert sorted(markers) == sorted(files), (
        f"css marker/file mismatch: markers={sorted(markers)} files={sorted(files)}")
    for name in files:
        assert markers.count(name) == 1, f"{name}: css marker not unique"


def test_css_modules_are_balanced_blocks():
    """Each extracted CSS module must be a self-contained region:
    balanced braces (an unbalanced cut would corrupt every rule after
    the splice point in the assembled artifact)."""
    for mod in _css_modules():
        text = mod.read_text(encoding="utf-8")
        assert text.strip(), f"{mod.name}: empty module"
        opens, closes = text.count("{"), text.count("}")
        assert opens == closes, (
            f"{mod.name}: unbalanced braces ({opens} open / {closes} close)")


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


_PARAM_LISTS = re.compile(
    r"function\s*[A-Za-z_$\w]*\s*\(([^)]*)\)"     # function decls/exprs
    r"|\(([^()]*)\)\s*=>"                         # (a, b) => arrows
    r"|\b([A-Za-z_$][\w$]*)\s*=>"                 # bare-param arrows: card =>
    r"|\bfor\s*\(\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)",  # for (const x of…
    re.M)


def _names(rx, text: str) -> set:
    out = set()
    for m in rx.finditer(text):
        out.update(g for g in m.groups() if g)
    # every parameter name counts as a self-binding (the earlier single-param
    # capture missed `text` in `_insertAt(ta, text)` — a real false positive)
    for m in _PARAM_LISTS.finditer(text):
        for params in m.groups():
            if not params:
                continue
            for p in params.split(","):
                p = p.strip().lstrip(".").split("=")[0].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
                    out.add(p)
    return out


def _strip_comments(text: str) -> str:
    """Reference-scan on CODE only. Strips comments AND (single-line) string
    literals — a CSS class name `"dragging"` or prose in a comment must not
    read as a cross-module reference. Heuristics, calibrated on the real
    false-positive families hit during the split:
      comments: /* … */ blocks, full-line //, space-guarded trailing //;
      strings: '…' / "…" without embedded newlines (template literals stay —
      their ${expr} interpolations ARE code we want scanned)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    text = re.sub(r"\s//\s.*$", "", text, flags=re.M)
    text = re.sub(r"'[^'\n]*'", "''", text)
    text = re.sub(r'"[^"\n]*"', '""', text)
    # template literals: DROP the literal text (prose like "标 keep / cull"
    # is not code) but KEEP the ${…} interpolations — those ARE code.
    text = re.sub(
        r"`[^`]*`",
        lambda m: " ; ".join(re.findall(r"\$\{([^}]*)\}", m.group(0))),
        text, flags=re.S)
    return text


def test_cross_module_isolation():
    mods = {m.name: m.read_text(encoding="utf-8") for m in _modules()}
    top = {name: _names(_DECL_TOP, text) for name, text in mods.items()}
    own = {name: _names(_DECL_ANY, text) for name, text in mods.items()}
    # Names the MAIN closure also declares (2-space indent in results.js —
    # e.g. `const grid`) are shared vocabulary every module may use; a module
    # shadowing one must not claim ownership of everyone else's usage.
    main_js = (_SRC / "results.js").read_text(encoding="utf-8")
    shared = _names(re.compile(
        r"^\s{2}(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
        r"|^\s{2}(?:const|let|var)\s+([A-Za-z_$][\w$]*)", re.M), main_js)
    # the PAYLOAD destructuring (`const { run_id, rows, summary } = PAYLOAD`)
    # is THE core shared vocabulary — plain decl regexes miss brace patterns.
    for m in re.finditer(r"^\s{2}(?:const|let)\s*\{([^}]*)\}", main_js, re.M):
        for nm in m.group(1).split(","):
            nm = nm.strip().split(":")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", nm):
                shared.add(nm)
    violations = []
    code = {name: _strip_comments(text) for name, text in mods.items()}
    for a, a_decls in top.items():
        for b in mods:
            if a == b:
                continue
            for name in a_decls:
                if name in own[b]:
                    continue          # b declares/binds its own `name` — fine
                if name in shared:
                    continue          # main-closure vocabulary (e.g. grid)
                if len(name) < 4:
                    continue          # skip tiny common identifiers
                # bare-identifier match only: `.name` (property access),
                # `obj.name(` (method call) and `name:` (object-literal key,
                # e.g. fetch's `body:`) are NOT references to A's const.
                if re.search(rf"(?<![.\w$]){re.escape(name)}\b(?!\s*:)", code[b]):
                    violations.append(f"{b} references {a}'s internal {name!r}")
    assert not violations, (
        "modules must communicate via window.PixCull* only:\n  "
        + "\n  ".join(violations))
