#!/usr/bin/env python3
"""v2.5-P0-1 (final slice) — build the single-file results.html artifact.

``results.html`` stays a single self-contained file at runtime (the
serve_demo contract: no bundler, no external requests) — but as a
*source* it was a 17k-line monolith where CSS, JS and markup edits all
collided, which is how the v2.3.1 palette leak shipped.  The sources now
live in ``pixcull/report/templates/src/``:

    results.src.html   1.2k-line HTML skeleton with @@INLINE markers
    results.css        the full stylesheet
    results.js         the full application script

and this script splices them back into the committed artifact:

    python scripts/build_results_html.py        # or: make results-html

The reconstruction is pure concatenation (marker line → file content),
so the artifact is byte-identical to what the same sources produced
before the split.  ``tests/test_results_build.py`` is the golden guard:
it rebuilds in CI and asserts the committed artifact matches the
sources, so hand-editing results.html (or editing sources without
rebuilding) fails the gate instead of silently drifting.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "pixcull" / "report" / "templates" / "src"
OUT = ROOT / "pixcull" / "report" / "templates" / "results.html"

_MARKERS = ("results.css", "results.js")


def _assemble_js(src_dir: Path) -> str:
    """v2.16-P1 — results.js is itself assembled from modules.

    Self-contained subsystems (undo stack, selects mode, smart collections,
    bookmark/conflicts, marquee select, WebRTC, onboarding) live as files in
    ``src/modules/`` and are spliced back at their original positions via
    ``@@MODULE:<file>@@`` marker lines, so the built artifact stays
    byte-identical to the pre-split monolith.  Markers must resolve 1:1 —
    a missing module file or an orphaned module file both fail the build.
    """
    js = (src_dir / "results.js").read_text("utf-8")
    mod_dir = src_dir / "modules"
    used: set[str] = set()
    for mod in sorted(mod_dir.glob("*.js")) if mod_dir.exists() else []:
        marker = f"@@MODULE:{mod.name}@@\n"
        if marker not in js:
            raise SystemExit(
                f"[build-results] orphaned module (no marker): {mod.name}")
        js = js.replace(marker, mod.read_text("utf-8"))
        used.add(mod.name)
    if "@@MODULE:" in js:
        import re
        left = re.findall(r"@@MODULE:([^@]+)@@", js)
        raise SystemExit(f"[build-results] unresolved module marker(s): {left}")
    return js


def _assemble_css(src_dir: Path) -> str:
    """v2.22-P2 — results.css is assembled from modules, same contract
    as ``_assemble_js``: contiguous regions (design tokens, lightbox)
    live as files in ``src/modules/*.css`` and are spliced back at
    ``@@CSS:<file>@@`` marker lines.  Markers must resolve 1:1 — a
    missing module file or an orphaned module file both fail the build,
    and the artifact stays byte-identical to the pre-split monolith."""
    css = (src_dir / "results.css").read_text("utf-8")
    mod_dir = src_dir / "modules"
    for mod in sorted(mod_dir.glob("*.css")) if mod_dir.exists() else []:
        marker = f"@@CSS:{mod.name}@@\n"
        if marker not in css:
            raise SystemExit(
                f"[build-results] orphaned css module (no marker): {mod.name}")
        css = css.replace(marker, mod.read_text("utf-8"))
    if "@@CSS:" in css:
        import re
        left = re.findall(r"@@CSS:([^@]+)@@", css)
        raise SystemExit(f"[build-results] unresolved css marker(s): {left}")
    return css


def build(src_dir: Path = SRC_DIR) -> str:
    """Splice src/results.src.html + its @@INLINE parts into one page."""
    shell = (src_dir / "results.src.html").read_text("utf-8")
    parts = {
        "results.css": _assemble_css(src_dir),
        "results.js": _assemble_js(src_dir),
    }
    for name in _MARKERS:
        marker = f"@@INLINE:{name}@@\n"
        if marker not in shell:
            raise SystemExit(f"[build-results] marker missing: {marker!r}")
        shell = shell.replace(marker, parts[name])
    if "@@INLINE:" in shell:
        raise SystemExit("[build-results] unresolved @@INLINE marker left")
    return shell


def main() -> int:
    html = build()
    old = OUT.read_text("utf-8") if OUT.exists() else ""
    if html == old:
        print(f"[build-results] {OUT.name} already current "
              f"({len(html):,} bytes)")
        return 0
    OUT.write_text(html, "utf-8")
    print(f"[build-results] wrote {OUT.relative_to(ROOT)} "
          f"({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
