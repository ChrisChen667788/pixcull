"""v2.19 — pyproject version and pixcull.__version__ stay in lockstep."""
import re
from pathlib import Path

def test_version_single_source():
    repo = Path(__file__).resolve().parent.parent
    py = (repo / "pyproject.toml").read_text()
    m = re.search(r'^version = "([^"]+)"', py, re.M)
    assert m, "pyproject version missing"
    init = (repo / "pixcull" / "__init__.py").read_text()
    f = re.search(r'__version__ = "([^"]+)"', init)
    assert f, "fallback literal missing"
    assert f.group(1) == m.group(1), (
        f"bump both: pyproject={m.group(1)} vs __init__ fallback={f.group(1)}")
