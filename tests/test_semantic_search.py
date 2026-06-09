"""P-AI-2 — tests for the CLIP semantic-search math + cache I/O.

We don't load the actual CLIP model (it's 200 MB + slow); the test
asserts the ranking math + cache round-trip work correctly given
hand-built embedding arrays.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pixcull.scoring.semantic_search import (
    _norm,
    load_embeddings_cache,
    search,
)


def test_norm_unit_vectors():
    """_norm produces L2-unit vectors regardless of input scale."""
    v = np.array([[3.0, 4.0]], dtype=np.float32)
    n = _norm(v)
    assert np.allclose(np.linalg.norm(n, axis=-1), [1.0])
    # zero-vector is preserved (avoid div-by-zero)
    z = _norm(np.zeros((1, 4), dtype=np.float32))
    assert z.shape == (1, 4)


def test_search_returns_topk_by_cosine(tmp_path: Path, monkeypatch):
    """Search picks the top-k entries by dot-product against the query."""
    # 3 image embeddings + 1 query, all 2-D for easy hand-checking
    # img0 points (1, 0)   → very similar to query (0.9, 0.4)
    # img1 points (0, 1)   → less similar
    # img2 points (-1, 0)  → opposite
    cache = {
        "filenames": np.array(["img0.jpg", "img1.jpg", "img2.jpg"]),
        "vectors":   _norm(np.array([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)),
        "model":     "test",
    }
    # We can't call the real encode_query (needs CLIP); patch it — via the
    # monkeypatch fixture so it's restored (else it leaks into later tests
    # that DO use the real encoder, e.g. the CLIP integration test below).
    import pixcull.scoring.semantic_search as ss
    monkeypatch.setattr(
        ss, "encode_query",
        lambda q: _norm(np.array([0.9, 0.4], np.float32)[None])[0])

    ranked = search("query string", cache=cache, k=3)
    assert [r[0] for r in ranked] == ["img0.jpg", "img1.jpg", "img2.jpg"]
    # Highest similarity should be img0, very close to 1
    assert ranked[0][1] > 0.9
    # img2 is opposite the query, similarity should be < 0
    assert ranked[2][1] < 0


def test_search_handles_empty_cache():
    """No embeddings → empty result, no exception."""
    cache = {
        "filenames": np.array([]),
        "vectors":   np.zeros((0, 4), np.float32),
        "model":     "test",
    }
    assert search("anything", cache=cache, k=5) == []


def test_load_embeddings_cache_missing(tmp_path: Path):
    """load_embeddings_cache returns None for nonexistent file."""
    assert load_embeddings_cache(tmp_path / "does_not_exist.npz") is None


def test_load_embeddings_cache_round_trip(tmp_path: Path):
    """Save + load round-trip preserves filenames + vectors + model."""
    vecs = _norm(np.random.randn(5, 8).astype(np.float32))
    fns = np.array([f"img_{i}.jpg" for i in range(5)])
    np.savez(tmp_path / "embeddings.npz",
              filenames=fns, vectors=vecs, model=np.array("test-model"))
    loaded = load_embeddings_cache(tmp_path / "embeddings.npz")
    assert loaded is not None
    assert list(loaded["filenames"]) == list(fns)
    assert np.allclose(loaded["vectors"], vecs)
    assert loaded["model"] == "test-model"


def test_search_k_clamped_to_cache_size(monkeypatch):
    """Asking for k larger than cache size returns just cache_size items."""
    cache = {
        "filenames": np.array(["a.jpg", "b.jpg"]),
        "vectors":   _norm(np.array([[1, 0], [0, 1]], dtype=np.float32)),
        "model":     "test",
    }
    import pixcull.scoring.semantic_search as ss
    monkeypatch.setattr(
        ss, "encode_query",
        lambda q: _norm(np.array([1.0, 0.0], np.float32)[None])[0])
    ranked = search("query", cache=cache, k=10)
    assert len(ranked) == 2


# --------------------------------------------------------------------------
# v2.4-P1-2 — integration test over the REAL CLIP model.
#
# The unit tests above deliberately skip the model, so they could not see
# two breakages that only the live path hits: (1) transformers ≥ 5 returns
# a BaseModelOutputWithPooling from get_image_features/get_text_features
# (not a tensor), and (2) np.savez appends ".npz" to the ".npz.tmp" temp
# file, breaking the atomic rename.  This exercises encode → build → save →
# reload → rank, and skips cleanly where CLIP can't load (no torch / no
# model cache in CI).
# --------------------------------------------------------------------------

def test_feature_tensor_shim_handles_both_return_shapes():
    """Hermetic guard for the transformers-5 compat shim — runs in CI with
    NO model download, so dependency drift in the CLIP return type is
    caught even though the real-model test below skips on the runner.

    transformers < 5 returned the projected tensor directly; >= 5 wraps it
    in a BaseModelOutputWithPooling whose ``pooler_output`` is that tensor.
    """
    torch = pytest.importorskip("torch")
    from pixcull.scoring.semantic_search import _feature_tensor
    t = torch.zeros(2, 512)
    assert _feature_tensor(t) is t                       # tensor → identity

    class _Out:                                          # mimics transformers ≥5
        pooler_output = torch.ones(2, 512)
    got = _feature_tensor(_Out())
    assert torch.is_tensor(got) and tuple(got.shape) == (2, 512)
    assert float(got.sum()) == 2 * 512                   # it's the pooler_output

    class _Bad:                                          # neither tensor nor known attr
        pass
    with pytest.raises(TypeError):
        _feature_tensor(_Bad())


def _require_clip():
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("PIL")
    try:
        from pixcull.detectors.scene import _clip
        _clip()
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"CLIP model unavailable: {e}")


def test_build_search_real_clip_end_to_end(tmp_path: Path):
    _require_clip()
    from PIL import Image
    from pixcull.scoring import semantic_search as ss

    colors = {"red": (220, 30, 30), "green": (30, 180, 40), "blue": (30, 60, 210)}
    paths = []
    for name, rgb in colors.items():
        p = tmp_path / f"{name}.png"
        Image.new("RGB", (224, 224), rgb).save(p)
        paths.append(p)

    cache_path = tmp_path / "embeddings.npz"
    cache = ss.build_embeddings_cache(paths, cache_path)
    assert cache["vectors"].shape == (3, 512)               # projected dim
    assert cache_path.is_file()                             # savez+rename OK
    # round-trips from disk
    assert ss.load_embeddings_cache(cache_path)["vectors"].shape == (3, 512)

    # text→image relevance: each colour query ranks its own swatch first.
    for q, want in [("a red photo", "red.png"),
                    ("a blue photo", "blue.png"),
                    ("a green photo", "green.png")]:
        ranked = ss.search(q, cache=cache, k=3)
        assert ranked[0][0] == want, f"{q!r} ranked {ranked}"
