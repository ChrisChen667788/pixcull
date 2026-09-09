"""v3.60 — a missing pyiqa must not take the run down with it.

`pip install pixcull` brings pytest, ruff, yapf and pre-commit into a
photographer's environment — ten packages and 15.1 MB, measured in a
clean venv against the published wheel. They arrive through `pyiqa`,
which lists its own development tooling in `requires_dist`. pyiqa 0.1.16
is the current release and still does.

That is upstream's to fix and PixCull's to live with: pyiqa supplies the
`laion_aes` and `clipiqa` metrics behind the aesthetic axis, one of the
six, and dropping it to save 15 MB would silently remove a scoring axis
from everyone who upgrades. The cost is written down instead.

Investigating it turned up the part that *was* PixCull's. `import pyiqa`
is already lazy — deferred into `_metrics()` — but nothing caught it
failing, so an environment without pyiqa did not lose one axis, it lost
the run: `ImportError: No module named pyiqa` at the first photograph,
with nothing to say which of two dozen dependencies was missing.

A plain install cannot reach that. `--no-deps`, a constrained mirror and
a conda base where the resolver gave up all can.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


class _Blocked:
    """Refuse one module, the way the import system actually asks."""

    def __init__(self, name: str) -> None:
        self.name = name

    def find_spec(self, name, path=None, target=None):
        if name == self.name or name.startswith(self.name + "."):
            raise ImportError(f"No module named {self.name}")
        return None


@pytest.fixture
def without_pyiqa(monkeypatch):
    from pixcull.scoring import aesthetic
    aesthetic._metrics.cache_clear()
    monkeypatch.setattr(sys, "meta_path", [_Blocked("pyiqa")] + sys.meta_path)
    monkeypatch.delitem(sys.modules, "pyiqa", raising=False)
    yield
    aesthetic._metrics.cache_clear()


def test_the_run_survives_and_says_which_axis_it_lost(without_pyiqa, caplog):
    from pixcull.scoring.aesthetic import AestheticScorer

    img = Image.new("RGB", (256, 256), (120, 120, 120))
    result = AestheticScorer().analyze(img)

    assert "aesthetic_unavailable" in result.flags, (
        "the axis went missing without saying so")
    assert not result.metrics, "no score should be invented"
    assert any("pyiqa" in r.getMessage() for r in caplog.records), (
        "nothing in the log names the dependency that is missing")


def test_the_blocker_would_have_caught_the_old_behaviour(without_pyiqa):
    """The fixture has to actually block the import, or the test above
    passes because pyiqa was there all along. An earlier draft used the
    long-removed `find_module` hook and did exactly that."""
    with pytest.raises(ImportError):
        import pyiqa  # noqa: F401


def test_the_import_is_still_lazy():
    """If pyiqa moves to module scope, the degradation above cannot
    happen — the failure returns to import time and takes the process."""
    src = (ROOT / "pixcull" / "scoring" / "aesthetic.py").read_text("utf-8")
    head = src[:src.index("def _metrics")]
    assert "import pyiqa" not in head, (
        "pyiqa is imported at module scope; a missing install will crash "
        "before anything can degrade")


def test_the_cost_of_pyiqa_is_written_down_where_it_is_declared():
    """15 MB of somebody else's dev tooling in a photographer's
    environment is a decision, and decisions that are not written down
    get re-litigated by whoever notices next."""
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    at = toml.index('"pyiqa')
    window = toml[max(0, at - 1200):at]
    assert "pytest" in window and "ruff" in window, (
        "pyproject does not record that pyiqa drags dev tooling into "
        "every install")
