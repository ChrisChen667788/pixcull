"""v2.40 — the gate that decides skip-vs-fail must itself be right.

If this logic is wrong in the lenient direction we are back where we
started: real regressions reported as skips on a green gate.
"""

import pytest

from tests import _model_gate as G


def test_uncached_model_skips(monkeypatch):
    monkeypatch.setattr(G, "is_cached", lambda repo: False)
    with pytest.raises(pytest.skip.Exception):
        G.require_model("some/repo", lambda: None, what="Thing")


def test_cached_model_that_loads_returns_its_value(monkeypatch):
    monkeypatch.setattr(G, "is_cached", lambda repo: True)
    assert G.require_model("some/repo", lambda: "loaded", what="Thing") == "loaded"


def test_cached_model_that_fails_is_a_FAILURE_not_a_skip(monkeypatch):
    """The whole point. A model sitting on disk that won't load is a
    defect; swallowing it as a skip is how v2.39's gate lost three
    real-model tests without going red."""
    monkeypatch.setattr(G, "is_cached", lambda repo: True)

    def boom():
        raise RuntimeError("HTTP 429 rate limited")

    with pytest.raises(AssertionError) as ei:
        G.require_model("some/repo", boom, what="Thing")
    assert not isinstance(ei.value, pytest.skip.Exception)
    assert "429" in str(ei.value)


def test_cached_load_runs_offline(monkeypatch):
    """Offline during the load, so Hub rate-limiting can never turn a
    cached model into a failure."""
    monkeypatch.setattr(G, "is_cached", lambda repo: True)
    seen = {}

    def loader():
        import os
        seen["offline"] = os.environ.get("HF_HUB_OFFLINE")
        return 1

    G.require_model("some/repo", loader, what="Thing")
    assert seen["offline"] == "1"


def test_offline_env_is_restored(monkeypatch):
    monkeypatch.setattr(G, "is_cached", lambda repo: True)
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    G.require_model("some/repo", lambda: None, what="Thing")
    import os
    assert os.environ["HF_HUB_OFFLINE"] == "0"


def test_offline_env_is_removed_when_it_was_unset(monkeypatch):
    monkeypatch.setattr(G, "is_cached", lambda repo: True)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    G.require_model("some/repo", lambda: None, what="Thing")
    import os
    assert "HF_HUB_OFFLINE" not in os.environ


def test_is_cached_reads_the_hub_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    assert not G.is_cached("org/model")
    snap = tmp_path / "models--org--model" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    assert not G.is_cached("org/model"), "an empty snapshot isn't cached"
    (snap / "config.json").write_text("{}")
    assert G.is_cached("org/model")


def test_the_real_repos_are_the_ones_production_uses():
    """If production switches models, the gate must follow or it will
    check the cache for something nobody loads."""
    scene = (G.Path(__file__).resolve().parent.parent / "pixcull"
             / "detectors" / "scene.py").read_text("utf-8")
    assert G.CLIP_REPO in scene, (
        f"{G.CLIP_REPO} is no longer what scene.py loads")
