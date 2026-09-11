"""v3.76 — the popover for undecided frames never appeared on an undecided frame.

`_isUncertain` asked whether `score_final` was between 0.45 and 0.55.
Under the standard preset the pipeline culls below 0.575 and keeps above
0.65, so that band lies **entirely inside the cull zone**: every frame it
called uncertain had been decided, confidently, and every frame that was
genuinely undecided got no popover at all.

Measured on the shipped sample run at the time: the band matched 0 of 32
frames while exactly one frame carried `decision=maybe`. The feature was
invisible on the data every visitor sees.

No band can be right. `cull_max_score` and `keep_min_score` move with the
strictness preset and again with the per-genre vertical, so a number
written into the page is wrong for most runs by construction. The fix is
to stop deriving the answer and read it: `decision` is what the pipeline
concluded after all of that.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "pixcull" / "report" / "templates" / "src" / "modules" / "14-confidence-modal.js"
PAGE = ROOT / "pixcull" / "report" / "templates" / "results.html"
GUIDE = ROOT / "docs" / "USER-GUIDE.md"
TEMPLATES = ROOT / "pixcull" / "scoring" / "templates" / "scene_templates.yaml"


def _code(path: Path) -> str:
    """Source with comments stripped — the explanation above the fix
    names the old band, and a raw search finds it there."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(l.split("//", 1)[0] for l in text.splitlines())


def test_the_popover_asks_the_decision_not_a_score_band():
    body = _code(MODULE)
    m = re.search(r"function _isUncertain\(row\)\s*\{(.*?)\n    \}", body, re.S)
    assert m, "_isUncertain is gone or reshaped; this gate cannot see it"
    fn = m.group(1)
    assert "decision" in fn, (
        "_isUncertain no longer reads `decision`. A score band cannot "
        "track the strictness preset or the per-genre vertical, so any "
        "literal here is wrong for most runs.")
    numbers = re.findall(r"0\.\d+", fn)
    assert not numbers, (
        f"_isUncertain compares against hard-coded scores {numbers}; the "
        "thresholds it would have to match are per-preset and per-vertical")


def test_the_band_it_used_lay_entirely_inside_the_cull_zone():
    """The defect restated as arithmetic, so it cannot be re-introduced
    on the belief that 0.45-0.55 was roughly right."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(TEMPLATES.read_text(encoding="utf-8"))

    def _find(node):
        if isinstance(node, dict):
            if "cull_max_score" in node and "keep_min_score" in node:
                return node
            for v in node.values():
                got = _find(v)
                if got:
                    return got
        elif isinstance(node, list):
            for v in node:
                got = _find(v)
                if got:
                    return got
        return None

    std = _find(doc)
    assert std, "no preset with both thresholds found in scene_templates.yaml"
    cull_max = float(std["cull_max_score"]) / 10.0
    keep_min = float(std["keep_min_score"]) / 10.0
    assert 0.55 < cull_max, (
        f"the old band's top (0.55) is no longer below cull_max ({cull_max}); "
        "re-read the defect before changing this test")
    assert cull_max < keep_min, "cull_max is not below keep_min"


def test_the_user_guide_describes_the_same_rule_as_the_code():
    """It documented the band, so a reader learned to watch the wrong
    frames."""
    text = GUIDE.read_text(encoding="utf-8")
    hits = [l.strip() for l in text.splitlines()
            if "popover" in l and re.search(r"0\.\d+\s*[~-]\s*0\.\d+", l)]
    assert not hits, (
        f"the guide still describes the popover by a score band: {hits}")


def test_the_built_page_carries_the_fix():
    """The module is source; results.html is what ships."""
    body = _code(PAGE)
    m = re.search(r"function _isUncertain\(row\)\s*\{(.*?)\n    \}", body, re.S)
    assert m, "_isUncertain is not in the built page"
    assert "decision" in m.group(1), (
        "results.html was not rebuilt after the module changed — run "
        "scripts/build_results_html.py")
