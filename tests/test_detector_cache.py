"""v3.16 — the incremental cache orchestrator.py promised in V0.1.

Its module docstring has said since the first commit that "V0.3 will add
multi-process workers and incremental runs via the cache layer".  The
workers shipped.  The cache did not, so re-running a folder re-executed
CLIP, DINOv2, MediaPipe, the aesthetic head and segmentation on every
frame that had not changed — which on a re-run is all of them.

Two things here are load-bearing and neither is the speed.
"""
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from pixcull.pipeline import detector_cache as DC


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("PIXCULL_DETECTOR_CACHE_DIR", d)
    monkeypatch.delenv(DC.ENV_FLAG, raising=False)
    yield d


def _img(tmp: Path, name="a.jpg", data=b"one") -> Path:
    p = tmp / name
    p.write_bytes(data)
    return p


def test_a_vector_comes_back_as_an_array_not_a_list():
    """The defect that would have shipped invisibly.

    orchestrator.py builds the CLIP embeddings file with
    `if emb is None or not hasattr(emb, "shape"): continue`.  A list has
    no `.shape`, so storing vectors as plain JSON lists would have
    dropped every warm-run photograph out of semantic search and the
    library index — silently, while the run itself looked perfect.
    """
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        key = DC.key_for(p)
        row = {"path": str(p), "filename": p.name,
               "clip_embedding": np.arange(4, dtype=np.float32),
               "embedding": np.arange(3, dtype=np.float32)}
        assert DC.put(key, row)
        back = DC.get(key, p)
        for f in ("clip_embedding", "embedding"):
            assert hasattr(back[f], "shape"), f"{f} lost its .shape"
            assert np.allclose(back[f], row[f])
        assert back["clip_embedding"].dtype == np.float32


def test_the_same_photograph_in_another_folder_is_a_hit():
    """This is the re-run. Photographers rename and re-export constantly,
    so a path key would miss exactly when it matters."""
    with tempfile.TemporaryDirectory() as d:
        a = _img(Path(d), "shoot1.jpg", b"identical bytes")
        b = _img(Path(d), "renamed.jpg", b"identical bytes")
        assert DC.key_for(a) == DC.key_for(b)


def test_a_hit_describes_the_file_that_was_asked_about():
    """Returning the first file's path would send the thumbnailer and the
    exporter at a file that may not exist."""
    with tempfile.TemporaryDirectory() as d:
        a = _img(Path(d), "first.jpg", b"same")
        b = _img(Path(d), "second.jpg", b"same")
        DC.put(DC.key_for(a), {"path": str(a), "filename": a.name})
        got = DC.get(DC.key_for(b), b)
        assert got["filename"] == "second.jpg"
        assert got["path"] == str(b)


def test_an_edited_file_is_a_miss_even_when_mtime_is_restored():
    """A stale row for an edited file is worse than a slow run: a verdict
    about a photograph that no longer exists, with nothing saying so."""
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d), "a.jpg", b"before")
        before = DC.key_for(p)
        st = p.stat()
        p.write_bytes(b"after!")
        os.utime(p, (st.st_atime, st.st_mtime))     # `touch -r`
        assert p.stat().st_mtime == st.st_mtime
        assert DC.key_for(p) != before


def test_a_detector_change_invalidates_every_entry():
    """Without this, editing a threshold in blur.py leaves every cached
    row in place and the change appears to do nothing."""
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        before = DC.key_for(p)
        old = DC.DETECTOR_VERSION
        try:
            DC.DETECTOR_VERSION = "v9.9.9"
            assert DC.key_for(p) != before
        finally:
            DC.DETECTOR_VERSION = old


def test_a_hit_reports_no_wall_clock():
    """Leaving the original timing in makes every performance report of a
    warm run a report of a cold one."""
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        DC.put(DC.key_for(p), {"elapsed_s": 9.9})
        assert DC.get(DC.key_for(p), p)["elapsed_s"] == 0.0


def test_a_torn_entry_is_a_miss_not_a_crash():
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        key = DC.key_for(p)
        dest = DC._entry_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('{"path": "x", "clip_emb', encoding="utf-8")
        assert DC.get(key, p) is None


def test_writes_are_atomic_so_a_killed_run_leaves_no_half_entry():
    import inspect
    src = inspect.getsource(DC.put)
    assert "mkstemp" in src and "os.replace" in src


def test_an_unserialisable_row_does_not_kill_the_run():
    """The frame was analysed. It just will not be cached."""
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        assert DC.put(DC.key_for(p), {"f": object()}) is False


def test_the_wrapper_only_analyses_on_a_miss():
    calls = []

    def _fake(path):
        calls.append(path)
        return {"path": str(path), "filename": Path(path).name}

    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        DC.analyze_one_cached(p, _fake)
        DC.analyze_one_cached(p, _fake)
        assert len(calls) == 1


def test_a_none_result_is_not_cached_as_a_verdict():
    """A frame that failed to load must be retried next run, not
    remembered as 'this photograph has no analysis'."""
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        n = []
        DC.analyze_one_cached(p, lambda q: (n.append(1), None)[1])
        DC.analyze_one_cached(p, lambda q: (n.append(1), None)[1])
        assert len(n) == 2


def test_the_switch_turns_it_off(monkeypatch):
    calls = []
    monkeypatch.setenv(DC.ENV_FLAG, "0")
    with tempfile.TemporaryDirectory() as d:
        p = _img(Path(d))
        for _ in range(2):
            DC.analyze_one_cached(p, lambda q: (calls.append(1),
                                                {"path": str(q)})[1])
        assert len(calls) == 2


def test_both_analysis_paths_go_through_the_cache():
    """This file holds the pool path and the serial fallback, and a
    capability wired into one and not its twin is this repository's
    most-repeated defect."""
    import inspect
    from pixcull.pipeline import parallel
    src = inspect.getsource(parallel)
    assert src.count("analyze_one_cached") >= 2
    assert "return analyze_one(Path(path_str))" not in src
