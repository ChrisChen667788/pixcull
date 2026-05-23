"""Tests for pixcull.style.clip_clone — style clone V2 (CLIP centroid).

These tests synthesise a tiny "embeddings cache" with numpy and
exercise the public API without touching the actual CLIP model
(no GPU, no slow import).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# numpy is a soft dependency of the style-V2 module — skip the
# whole test file if not present (style-V1 / cli_audit tests don't
# need it).
np = pytest.importorskip("numpy")

from pixcull.style.clip_clone import (   # noqa: E402  — needs np import above
    DEFAULT_LAMBDA,
    blend,
    compute_visual_distances,
    learn_visual_profile,
)


def _mk_cache(tmp_path: Path, fns: list[str], vectors) -> Path:
    """Build a minimal embeddings.npz matching the schema
    ``pixcull.scoring.semantic_search.load_embeddings_cache`` reads."""
    path = tmp_path / "embeddings.npz"
    np.savez(
        path,
        filenames=np.array(fns),
        vectors=np.asarray(vectors, dtype=np.float32),
        model="test/clip-v1",
    )
    return path


def _normalise(v):
    """Unit-norm a vector."""
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def test_learn_visual_profile_returns_normalised_centroid(tmp_path):
    # Two references pointing roughly the same direction
    v_a = _normalise([1.0, 0.0, 0.0])
    v_b = _normalise([1.0, 0.1, 0.0])
    v_c = _normalise([0.0, 1.0, 0.0])  # ortho — NOT a ref
    cache = _mk_cache(tmp_path, ["a.jpg", "b.jpg", "c.jpg"],
                       [v_a, v_b, v_c])

    profile = learn_visual_profile(["a.jpg", "b.jpg"], cache)
    assert profile is not None
    assert profile["n_refs"] == 2
    assert profile["dim"] == 3
    assert profile["schema"] == "pixcull.style_profile_v2/v1"

    centroid = np.asarray(profile["centroid"])
    # Should be L2-normalised
    assert abs(float(np.linalg.norm(centroid)) - 1.0) < 1e-5
    # And should point mostly along axis-0 (the refs were both ~[1,0,0])
    assert centroid[0] > 0.99


def test_learn_returns_none_when_no_refs_in_cache(tmp_path):
    cache = _mk_cache(tmp_path, ["a.jpg"], [_normalise([1, 0])])
    # User picked filenames that aren't in this run's cache
    profile = learn_visual_profile(["other.jpg", "missing.jpg"], cache)
    assert profile is None


def test_learn_returns_none_when_cache_missing(tmp_path):
    profile = learn_visual_profile(
        ["a.jpg"], tmp_path / "no-such-file.npz"
    )
    assert profile is None


def test_distances_against_centroid_are_in_zero_one(tmp_path):
    v_a = _normalise([1.0, 0.0, 0.0])
    v_b = _normalise([0.0, 1.0, 0.0])
    cache = _mk_cache(tmp_path, ["a.jpg", "b.jpg"], [v_a, v_b])
    profile = learn_visual_profile(["a.jpg"], cache)
    distances = compute_visual_distances(profile, cache)
    assert set(distances) == {"a.jpg", "b.jpg"}
    # a.jpg is the reference → distance ~ 0
    assert distances["a.jpg"] < 0.01
    # b.jpg is orthogonal → distance == 1 - cos(90°) == 1
    assert 0.95 <= distances["b.jpg"] <= 1.0


def test_distances_empty_when_no_profile(tmp_path):
    cache = _mk_cache(tmp_path, ["a.jpg"], [_normalise([1, 0])])
    assert compute_visual_distances(None, cache) == {}
    assert compute_visual_distances({}, cache) == {}


def test_distances_empty_when_cache_dim_mismatch(tmp_path):
    """Stale profile from a different model shouldn't crash."""
    cache = _mk_cache(tmp_path, ["a.jpg"], [_normalise([1, 0, 0, 0])])
    profile = {"schema": "pixcull.style_profile_v2/v1",
               "centroid": [1.0, 0.0]}  # 2D, cache is 4D
    assert compute_visual_distances(profile, cache) == {}


def test_blend_basic():
    # λ=0.3 default: 0.3*0.4 + 0.7*0.2 = 0.12 + 0.14 = 0.26
    assert blend(0.4, 0.2) == 0.26


def test_blend_handles_none_inputs():
    assert blend(None, None) is None
    assert blend(0.5, None) == 0.5
    assert blend(None, 0.5) == 0.5


def test_blend_clamps_lambda():
    # λ clamped to [0, 1]
    assert blend(0.4, 0.2, lam=-0.5) == 0.2   # λ → 0 → pure V2
    assert blend(0.4, 0.2, lam=2.0) == 0.4    # λ → 1 → pure V1


def test_default_lambda_constant():
    # Charter committed to default 0.3 / 0.7 (V1 weight / V2 weight)
    assert DEFAULT_LAMBDA == 0.3
