"""v2.34 — the CLIP cache is a free by-product of culling.

Scene detection already runs the full CLIP forward on every photo to get
``logits_per_image``; the same pass projects and L2-normalizes the image
tower, so ``out.image_embeds`` is the exact 512-d vector semantic search
used to re-encode the whole shoot for (verified cosine 1.000000 against
``get_image_features``).  The pipeline now persists those vectors as
``output/embeddings.npz``.

Also covered: ``_run_path_map``, which fixes a v2.32 bug where
``pixcull library index`` resolved *nothing* on a plain ``pixcull run``
because it never consulted scores.csv's own ``path`` column.
"""

import csv
import json

import numpy as np
import pandas as pd
import pytest

from pixcull.cli import _run_path_map
from pixcull.pipeline.orchestrator import _write_clip_cache
from pixcull.scoring.semantic_search import load_embeddings_cache


def _df(n=3, dim=512, bad=(), prefix="p"):
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        if i in bad:
            emb = None
        else:
            v = rng.normal(size=dim).astype(np.float32)
            emb = v / np.linalg.norm(v)
        rows.append({"filename": f"{prefix}{i}.jpg", "clip_embedding": emb})
    return pd.DataFrame(rows)


def test_writes_a_cache_semantic_search_can_load(tmp_path):
    n = _write_clip_cache(_df(4), tmp_path)
    assert n == 4

    cache = load_embeddings_cache(tmp_path / "embeddings.npz")
    assert cache is not None, "semantic search cannot read what the run wrote"
    assert cache["vectors"].shape == (4, 512)
    assert cache["vectors"].dtype == np.float32
    assert cache["model"] == "clip-vit-base-patch32"
    assert list(cache["filenames"]) == [f"p{i}.jpg" for i in range(4)]
    # rows must be unit vectors — search does a bare dot product
    norms = np.linalg.norm(cache["vectors"], axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_rows_without_a_vector_are_dropped_not_zero_filled(tmp_path):
    """A zero row would rank as equally-unlike-everything in every future
    query, which is worse than being absent."""
    n = _write_clip_cache(_df(4, bad=(1, 2)), tmp_path)
    assert n == 2
    cache = load_embeddings_cache(tmp_path / "embeddings.npz")
    assert list(cache["filenames"]) == ["p0.jpg", "p3.jpg"]
    assert not (cache["vectors"] == 0).all(axis=1).any()


def test_non_finite_vectors_are_dropped(tmp_path):
    df = _df(3)
    df.at[1, "clip_embedding"] = np.full(512, np.nan, np.float32)
    assert _write_clip_cache(df, tmp_path) == 2
    cache = load_embeddings_cache(tmp_path / "embeddings.npz")
    assert list(cache["filenames"]) == ["p0.jpg", "p2.jpg"]
    assert np.isfinite(cache["vectors"]).all()


def test_ragged_dims_are_refused_rather_than_stacked(tmp_path):
    df = _df(3)
    df.at[1, "clip_embedding"] = np.ones(256, np.float32)
    assert _write_clip_cache(df, tmp_path) == 0
    assert not (tmp_path / "embeddings.npz").exists()


def test_missing_column_is_a_no_op(tmp_path):
    assert _write_clip_cache(pd.DataFrame([{"filename": "a.jpg"}]), tmp_path) == 0
    assert not (tmp_path / "embeddings.npz").exists()


def test_all_rows_missing_writes_nothing(tmp_path):
    assert _write_clip_cache(_df(2, bad=(0, 1)), tmp_path) == 0
    assert not (tmp_path / "embeddings.npz").exists()


def test_no_stray_npz_tmp_left_behind(tmp_path):
    """np.savez appends '.npz' to a target not already ending in it — the
    trap that would leave 'embeddings.npz.tmp.npz' behind and never
    rename."""
    _write_clip_cache(_df(2), tmp_path)
    assert (tmp_path / "embeddings.npz").is_file()
    assert list(tmp_path.glob("*.tmp*")) == []


def test_a_failure_never_breaks_the_run(tmp_path, monkeypatch):
    """The cache is a bonus; a cull that otherwise succeeded must not
    fail because of it."""
    target = tmp_path / "embeddings.npz"
    monkeypatch.setattr("builtins.open",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert _write_clip_cache(_df(2), tmp_path) == 0     # no exception escapes
    assert not target.exists()


# ---------------------------------------------------------------- path map

def _write_scores(out_dir, rows):
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "scores.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "filename"])
        w.writeheader()
        w.writerows(rows)


def test_path_map_resolves_from_scores_csv_path_column(tmp_path):
    """The v2.32 bug: a plain `pixcull run` writes no manifest.json and
    has no sibling input/, so this column is the ONLY source — and it was
    the one source not consulted."""
    src = tmp_path / "shoot"
    src.mkdir()
    for i in range(3):
        (src / f"p{i}.jpg").write_bytes(b"\xff\xd8\xff")
    out = tmp_path / "run" / "output"
    _write_scores(out, [{"path": str(src / f"p{i}.jpg"), "filename": f"p{i}.jpg"}
                        for i in range(3)])

    m = _run_path_map(out)
    assert set(m) == {"p0.jpg", "p1.jpg", "p2.jpg"}
    assert m["p1.jpg"] == src / "p1.jpg"


def test_path_map_omits_photos_that_are_gone(tmp_path):
    src = tmp_path / "shoot"
    src.mkdir()
    (src / "here.jpg").write_bytes(b"\xff\xd8\xff")
    out = tmp_path / "run" / "output"
    _write_scores(out, [
        {"path": str(src / "here.jpg"), "filename": "here.jpg"},
        {"path": str(src / "moved.jpg"), "filename": "moved.jpg"},
    ])
    assert set(_run_path_map(out)) == {"here.jpg"}


def test_scores_csv_wins_over_manifest(tmp_path):
    real = tmp_path / "real"
    other = tmp_path / "other"
    real.mkdir()
    other.mkdir()
    (real / "p.jpg").write_bytes(b"\xff\xd8\xff")
    (other / "p.jpg").write_bytes(b"\xff\xd8\xff")
    out = tmp_path / "run" / "output"
    _write_scores(out, [{"path": str(real / "p.jpg"), "filename": "p.jpg"}])
    (out / "manifest.json").write_text(json.dumps({"p.jpg": str(other / "p.jpg")}))

    assert _run_path_map(out)["p.jpg"] == real / "p.jpg"


def test_manifest_and_input_dir_still_work(tmp_path):
    """The demo server's layout must keep resolving — no scores.csv path
    column there."""
    out = tmp_path / "run" / "output"
    out.mkdir(parents=True)
    inp = tmp_path / "run" / "input"
    inp.mkdir()
    (inp / "fromdir.jpg").write_bytes(b"\xff\xd8\xff")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "frommanifest.jpg").write_bytes(b"\xff\xd8\xff")
    (out / "manifest.json").write_text(
        json.dumps({"frommanifest.jpg": str(elsewhere / "frommanifest.jpg")}))

    m = _run_path_map(out)
    assert m["frommanifest.jpg"] == elsewhere / "frommanifest.jpg"
    assert m["fromdir.jpg"] == inp / "fromdir.jpg"


def test_path_map_on_an_empty_run_is_empty_not_an_error(tmp_path):
    out = tmp_path / "run" / "output"
    out.mkdir(parents=True)
    assert _run_path_map(out) == {}


def test_path_map_survives_a_corrupt_manifest(tmp_path):
    out = tmp_path / "run" / "output"
    out.mkdir(parents=True)
    (out / "manifest.json").write_text("{not json")
    assert _run_path_map(out) == {}


@pytest.mark.parametrize("dim", [512, 768])
def test_dim_is_taken_from_the_data_not_hardcoded(tmp_path, dim):
    _write_clip_cache(_df(2, dim=dim), tmp_path)
    assert load_embeddings_cache(tmp_path / "embeddings.npz")[
        "vectors"].shape == (2, dim)


def test_scene_forward_exposes_the_same_vector_semantic_search_encodes():
    """The load-bearing claim of this whole slice.

    If a transformers upgrade ever changes what ``image_embeds`` means,
    every cache the pipeline writes would silently stop matching the
    query encoder — and semantic search would return plausible nonsense
    rather than fail loudly.  Pin the equivalence.
    """
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    torch = pytest.importorskip("torch")
    from PIL import Image

    try:
        from pixcull.detectors.scene import SceneDetector, _clip
        proc, model, device = _clip()
    except Exception:                                   # noqa: BLE001
        pytest.skip("CLIP unavailable")

    rng = np.random.default_rng(3)
    a = np.zeros((224, 224, 3), np.uint8)
    a[:112] = (190, 70, 50)
    a[112:] = (235, 225, 175)
    a[80:140, 80:140] = rng.integers(0, 255, (60, 60, 3))
    img = Image.fromarray(a)

    got = SceneDetector().analyze(img).extras.get("clip_embedding")
    assert got is not None, "scene detection stopped exposing clip_embedding"
    assert got.shape == (512,) and got.dtype == np.float32
    assert np.isclose(np.linalg.norm(got), 1.0, atol=1e-4), "not L2-normalized"

    with torch.no_grad():
        feats = model.get_image_features(
            **proc(images=img, return_tensors="pt").to(device))
    ref = (feats if isinstance(feats, torch.Tensor)
           else feats.pooler_output).cpu().numpy()[0]
    ref = ref / np.linalg.norm(ref)

    cos = float(got @ ref)
    assert cos > 0.9999, (
        f"scene-forward embedding diverged from get_image_features "
        f"(cos={cos:.6f}) — every cached vector would be in the wrong space")


# ------------------------------------------------------ auto-index (P2)

def _finished_run(tmp_path, rid="autorun", n=3):
    """A run dir shaped like one the pipeline just finished."""
    src = tmp_path / "shoot"
    src.mkdir(exist_ok=True)
    out = tmp_path / rid / "output"
    out.mkdir(parents=True)
    for i in range(n):
        (src / f"a{i}.jpg").write_bytes(b"\xff\xd8\xff")
    _write_scores(out, [{"path": str(src / f"a{i}.jpg"), "filename": f"a{i}.jpg"}
                        for i in range(n)])
    _write_clip_cache(_df(n, prefix="a"), out)
    return out


def test_a_finished_run_lands_in_the_library(tmp_path, monkeypatch):
    from pixcull.pipeline.orchestrator import _auto_index_library
    from pixcull.scoring import library_index as LX

    lib = tmp_path / "lib"
    monkeypatch.setattr(LX, "LIBRARY_DIR", lib)
    monkeypatch.delenv("PIXCULL_NO_AUTO_INDEX", raising=False)

    out = _finished_run(tmp_path, n=3)
    _auto_index_library(out)

    st = LX.status(lib)
    assert st["n_photos"] == 3
    assert st["runs"] == ["autorun"], "run_id must match `library index`'s"


def test_auto_index_is_idempotent(tmp_path, monkeypatch):
    from pixcull.pipeline.orchestrator import _auto_index_library
    from pixcull.scoring import library_index as LX
    lib = tmp_path / "lib"
    monkeypatch.setattr(LX, "LIBRARY_DIR", lib)
    monkeypatch.delenv("PIXCULL_NO_AUTO_INDEX", raising=False)

    out = _finished_run(tmp_path, n=2)
    _auto_index_library(out)
    _auto_index_library(out)
    assert LX.status(lib)["n_photos"] == 2, "re-running duplicated rows"


def test_opt_out_env_var_is_respected(tmp_path, monkeypatch):
    from pixcull.pipeline.orchestrator import _auto_index_library
    from pixcull.scoring import library_index as LX
    lib = tmp_path / "lib"
    monkeypatch.setattr(LX, "LIBRARY_DIR", lib)
    monkeypatch.setenv("PIXCULL_NO_AUTO_INDEX", "1")

    _auto_index_library(_finished_run(tmp_path, n=2))
    assert LX.status(lib)["n_photos"] == 0
    assert not lib.exists(), "opt-out still touched the library dir"


def test_auto_index_without_a_cache_is_a_no_op(tmp_path, monkeypatch):
    from pixcull.pipeline.orchestrator import _auto_index_library
    from pixcull.scoring import library_index as LX
    lib = tmp_path / "lib"
    monkeypatch.setattr(LX, "LIBRARY_DIR", lib)
    monkeypatch.delenv("PIXCULL_NO_AUTO_INDEX", raising=False)

    out = tmp_path / "norun" / "output"
    out.mkdir(parents=True)
    _write_scores(out, [])
    _auto_index_library(out)            # must not raise
    assert LX.status(lib)["n_photos"] == 0


def test_auto_index_failure_never_propagates(tmp_path, monkeypatch):
    from pixcull.pipeline.orchestrator import _auto_index_library
    from pixcull.scoring import library_index as LX
    monkeypatch.setattr(LX, "LIBRARY_DIR", tmp_path / "lib")
    monkeypatch.delenv("PIXCULL_NO_AUTO_INDEX", raising=False)
    monkeypatch.setattr(LX, "append_run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    _auto_index_library(_finished_run(tmp_path, n=2))   # no exception escapes
