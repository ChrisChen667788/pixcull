"""Tests for v0.13.1 per-ref CLIP distance breakdown."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pixcull.style.clip_clone import compute_per_ref_distances


@pytest.fixture
def fake_cache(tmp_path, monkeypatch):
    """Patch _load_cache to return a deterministic embeddings cache."""
    import numpy as np
    # 4 photos, 8-dim unit vectors
    vecs = np.array([
        [1.0, 0, 0, 0, 0, 0, 0, 0],     # target
        [0.95, 0.31, 0, 0, 0, 0, 0, 0],  # ref close (cosine = 0.95)
        [0.5, 0.5, 0.5, 0.5, 0, 0, 0, 0],  # ref medium
        [0, 1.0, 0, 0, 0, 0, 0, 0],     # ref far (cosine = 0)
    ], dtype=np.float32)
    # Re-normalise rows just in case
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = vecs / np.where(norms > 0, norms, 1)
    cache = {
        "filenames": ["target.jpg", "ref_close.jpg", "ref_med.jpg",
                      "ref_far.jpg"],
        "vectors":   vecs,
        "model":     "test",
    }
    import pixcull.style.clip_clone as mod
    monkeypatch.setattr(mod, "_load_cache", lambda p: cache)
    return tmp_path / "embeddings.npz"


def test_per_ref_distance_sorts_closest_first(fake_cache):
    out = compute_per_ref_distances(
        "target.jpg",
        ["ref_close.jpg", "ref_med.jpg", "ref_far.jpg"],
        fake_cache,
    )
    assert len(out) == 3
    # Sorted closest first
    distances = [r["distance"] for r in out]
    assert distances == sorted(distances)
    # ref_close should be top
    assert out[0]["filename"] == "ref_close.jpg"
    assert out[0]["rank"] == 1
    # ref_far should be last
    assert out[-1]["filename"] == "ref_far.jpg"
    assert out[-1]["rank"] == 3


def test_per_ref_distance_excludes_self(fake_cache):
    """Target photo shouldn't appear as its own ref even if user listed it."""
    out = compute_per_ref_distances(
        "target.jpg",
        ["target.jpg", "ref_close.jpg"],
        fake_cache,
    )
    assert len(out) == 1
    assert out[0]["filename"] == "ref_close.jpg"


def test_per_ref_distance_skips_missing_refs(fake_cache):
    """Refs not in the embeddings cache are silently dropped."""
    out = compute_per_ref_distances(
        "target.jpg",
        ["ref_close.jpg", "no_such.jpg", "ref_med.jpg"],
        fake_cache,
    )
    assert len(out) == 2


def test_per_ref_distance_target_missing_returns_empty(fake_cache):
    out = compute_per_ref_distances(
        "absent.jpg",
        ["ref_close.jpg"],
        fake_cache,
    )
    assert out == []


def test_per_ref_distance_distance_range(fake_cache):
    """All distances clamp to [0, 1] — the same scale V2 uses."""
    out = compute_per_ref_distances(
        "target.jpg",
        ["ref_close.jpg", "ref_med.jpg", "ref_far.jpg"],
        fake_cache,
    )
    for r in out:
        assert 0.0 <= r["distance"] <= 1.0


def test_per_ref_distance_empty_ref_list_returns_empty(fake_cache):
    assert compute_per_ref_distances("target.jpg", [], fake_cache) == []


def test_per_ref_distance_no_cache_returns_empty(tmp_path, monkeypatch):
    """numpy missing / cache file missing → empty list, no exception."""
    import pixcull.style.clip_clone as mod
    monkeypatch.setattr(mod, "_load_cache", lambda p: None)
    out = compute_per_ref_distances("x.jpg", ["y.jpg"], tmp_path / "x.npz")
    assert out == []


def test_per_ref_distance_rank_is_1_indexed(fake_cache):
    out = compute_per_ref_distances(
        "target.jpg",
        ["ref_close.jpg", "ref_med.jpg"],
        fake_cache,
    )
    assert out[0]["rank"] == 1
    assert out[1]["rank"] == 2
