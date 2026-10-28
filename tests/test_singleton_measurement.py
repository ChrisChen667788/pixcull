"""v3.97 — the singleton analysis, on the vectors that made the clusters.

Recorded 2026-09-13: over four contiguous blind-labelled blocks, a frame
with no near-duplicate was culled more often in three, and not in the
fourth (portrait, mid-shoot). The one explanation left open was that a
scene misclassification had widened the clustering window and diluted
the singleton group. Its first test was withdrawn because it ran on
`embeddings.npz` — the CLIP search vectors — while `cluster_bursts`
groups on DINOv2 vectors, and both files have the same keys.

Rerun on `burst_embeddings.npz` (scripts/measure_singletons.py,
2026-10-28), after checking each block's recorded clusters reproduce from
its vectors: the exception block was classified landscape on 119 of 150
frames. Under one label at landscape thresholds its singletons fall from
70 to 56, under portrait thresholds to 45, and none of those 45 was
culled. The misclassification moved its odds ratio toward 1, not away,
so it does not explain the exception. The entry closes with no rule.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from pixcull.detectors.duplicate import (  # noqa: E402
    WrongVectors, cluster_bursts, load_burst_vectors, recluster,
)

ROOT = Path(__file__).resolve().parent.parent


def _vec(seed, base=None, jitter=0.0):
    rnd = np.random.default_rng(seed)
    v = rnd.normal(size=16) if base is None else base + jitter * rnd.normal(size=16)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _frames():
    """Two bursts and two singletons, one burst straddling a scene change."""
    t0 = pd.Timestamp("2026-09-12 10:00:00")
    a, b = _vec(1), _vec(2)
    rows = [
        ("f01.jpg", 0, "portrait", _vec(10, a, 0.02)),
        ("f02.jpg", 1, "portrait", _vec(11, a, 0.02)),
        ("f03.jpg", 2, "landscape", _vec(12, a, 0.02)),   # same burst, new label
        ("f04.jpg", 30, "portrait", _vec(3)),               # singleton
        ("f05.jpg", 60, "portrait", _vec(13, b, 0.02)),
        ("f06.jpg", 61, "portrait", _vec(14, b, 0.02)),
        ("f07.jpg", 90, "portrait", _vec(4)),               # singleton
    ]
    return pd.DataFrame({"filename": [r[0] for r in rows],
                         "datetime": [t0 + pd.Timedelta(seconds=r[1]) for r in rows],
                         "scene": [r[2] for r in rows],
                         "embedding": [r[3] for r in rows]})


def _run(tmp_path, df=None):
    """A run directory as the pipeline leaves it: scores.csv with the
    recorded cluster_id, and the vectors written by the real writer."""
    from pixcull.pipeline.orchestrator import _write_burst_cache
    df = cluster_bursts(_frames() if df is None else df)
    out = tmp_path / "run" / "output"
    _write_burst_cache(df, out)
    df.drop(columns=["embedding"]).to_csv(out / "scores.csv", index=False)
    return out


# ------------------------------------------------------------ the reader


def test_the_reader_reads_what_the_writer_wrote(tmp_path):
    out = _run(tmp_path)
    vec = load_burst_vectors(out / "burst_embeddings.npz")
    assert sorted(vec) == [f"f0{i}.jpg" for i in range(1, 8)]
    assert all(v.shape == (16,) for v in vec.values())


@pytest.mark.parametrize("stamp", [{"model": "clip-vit-base-patch32", "preproc": "x"},
                                   {"model": "dinov2-base"},      # no emb_col
                                   {}])
def test_the_reader_refuses_anything_else(tmp_path, stamp):
    """The CLIP cache has the same `filenames` and `vectors` keys."""
    p = tmp_path / "embeddings.npz"
    with open(p, "wb") as fh:
        np.savez(fh, filenames=np.array(["a.jpg"]), vectors=np.zeros((1, 512), np.float32),
                 **{k: np.array(v) for k, v in stamp.items()})
    with pytest.raises(WrongVectors):
        load_burst_vectors(p)


def test_a_file_that_names_a_frame_twice_is_refused(tmp_path):
    """Review of v3.97: filenames are basenames, so two folders can each
    hold a DSC_0001.JPG, and a dict keyed by name keeps one vector for
    both rows without a word."""
    p = tmp_path / "burst_embeddings.npz"
    with open(p, "wb") as fh:
        np.savez(fh, filenames=np.array(["DSC_0001.JPG", "DSC_0001.JPG"]),
                 vectors=np.zeros((2, 4), np.float32),
                 model=np.array("dinov2-base"), emb_col=np.array("embedding"))
    with pytest.raises(WrongVectors, match="more than once"):
        load_burst_vectors(p)


def test_scores_that_name_a_frame_twice_are_refused(tmp_path):
    out = _run(tmp_path)
    scores = pd.read_csv(out / "scores.csv")
    scores.loc[1, "filename"] = scores.loc[0, "filename"]
    with pytest.raises(WrongVectors, match="more than once"):
        recluster(scores, load_burst_vectors(out / "burst_embeddings.npz"))


# ----------------------------------------------------- the reproduction


def test_a_run_reproduces_from_its_own_vectors(tmp_path):
    out = _run(tmp_path)
    scores = pd.read_csv(out / "scores.csv")
    again, same = recluster(scores, load_burst_vectors(out / "burst_embeddings.npz"))
    assert same is True
    assert again["cluster_id"].nunique() == scores["cluster_id"].nunique()


def test_vectors_from_somewhere_else_do_not_reproduce(tmp_path):
    """The check the withdrawn test did not have."""
    out = _run(tmp_path)
    scores = pd.read_csv(out / "scores.csv")
    vec = load_burst_vectors(out / "burst_embeddings.npz")
    shuffled = dict(zip(vec, reversed(list(vec.values()))))
    assert recluster(scores, shuffled)[1] is False


def test_a_frame_without_a_vector_is_refused(tmp_path):
    out = _run(tmp_path)
    vec = load_burst_vectors(out / "burst_embeddings.npz")
    vec.pop("f04.jpg")
    with pytest.raises(WrongVectors, match="f04.jpg"):
        recluster(pd.read_csv(out / "scores.csv"), vec)


def test_one_label_removes_the_split_a_label_change_makes(tmp_path):
    out = _run(tmp_path)
    scores = pd.read_csv(out / "scores.csv")
    vec = load_burst_vectors(out / "burst_embeddings.npz")
    as_run, _ = recluster(scores, vec)
    one, _ = recluster(scores, vec, scene="portrait")
    sizes = lambda d: sorted(d.groupby("cluster_id").size().tolist())
    assert sizes(as_run) == [1, 1, 1, 2, 2], "f03's new label splits its burst"
    assert sizes(one) == [1, 1, 2, 3]


# ------------------------------------------------------------ the script


def _script():
    path = ROOT / "scripts" / "measure_singletons.py"
    spec = importlib.util.spec_from_file_location("measure_singletons", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_table_counts_singletons_over_the_whole_block():
    df = pd.DataFrame({"filename": list("abcdef"), "cluster_id": [1, 2, 3, 3, 4, 4]})
    labels = {"a": "cull", "b": "keep", "c": "cull", "d": "keep", "e": "keep"}  # f unlabelled
    t = _script().singleton_table(df, labels)
    assert (t["n"], t["singletons"]) == (5, 2)
    assert t["single_cull"] == 0.5 and t["burst_cull"] == pytest.approx(1 / 3)
    assert t["odds_ratio"] == pytest.approx(2.0)


def test_a_block_with_nothing_to_compare_has_no_odds_ratio():
    """Review of v3.97: every labelled frame a singleton gave `OR nan`."""
    df = pd.DataFrame({"filename": list("abcd"), "cluster_id": [1, 2, 3, 3]})
    mod = _script()
    t = mod.singleton_table(df, {"a": "cull", "b": "keep"})
    assert t["odds_ratio"] is None and t["p"] is None
    assert "OR n/a" in mod._line("x", t)


def test_the_odds_ratio_is_the_plain_one():
    """September's table added 0.5 to every cell; this does not."""
    df = pd.DataFrame({"filename": [f"f{i}" for i in range(149)],
                       "cluster_id": list(range(22)) + [999] * 127})
    labels = {f"f{i}": "cull" if (i < 11 or 22 <= i < 42) else "keep" for i in range(149)}
    t = _script().singleton_table(df, labels)
    assert t["cells"] == (11, 11, 20, 107)          # the landscape block's counts
    assert t["odds_ratio"] == pytest.approx(5.35, abs=0.005)


def _sheet(tmp_path, labels):
    import json
    p = tmp_path / "sheet.json"
    p.write_text(json.dumps({"source": "human", "selection": "blind",
                             "verdicts": labels}), encoding="utf-8")
    return p


def test_the_script_measures_a_block(tmp_path, capsys):
    out = _run(tmp_path)
    sheet = _sheet(tmp_path, {f"f0{i}.jpg": "cull" if i in (4, 7) else "keep"
                              for i in range(1, 8)})
    rc = _script().main(["--block", "b1", str(out.parent), str(sheet), "event"])
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "classified portrait on 6, label changes 2 times" in text
    assert "as run" in text and "one label, portrait thresholds" in text
    assert "one label, event thresholds (its genre)" in text


def test_the_script_refuses_a_block_that_does_not_reproduce(tmp_path, capsys):
    out = _run(tmp_path)
    scores = pd.read_csv(out / "scores.csv")
    scores["cluster_id"] = range(len(scores))          # not what the vectors give
    scores.to_csv(out / "scores.csv", index=False)
    sheet = _sheet(tmp_path, {"f01.jpg": "keep"})
    assert _script().main(["--block", "b1", str(out), str(sheet), "portrait"]) == 1
    assert "not measured" in capsys.readouterr().out
