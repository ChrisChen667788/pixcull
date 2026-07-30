"""v2.33 — the _build_results cache must be fast AND never stale.

A results cache is the kind of optimisation that trades a visible
slowness for an invisible wrongness, so the tests here are mostly about
invalidation, not speed:

* a warm second call must NOT rebuild (that's the whole point);
* saving an annotation must bust it — otherwise the photographer's own
  keep/cull judgment silently fails to appear, which is far worse than
  a slow page;
* re-scoring (rewriting scores.csv) must bust it;
* the same run_id under a different demo root must not collide.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_HEADER = (
    "path,filename,datetime,scene,scene_probs,gps_lat,gps_lon,flags,"
    "elapsed_s,subject_fraction,laplacian_global,laplacian_subject,mean_luma,"
    "highlight_clip_pct,shadow_clip_pct,scene_confidence,laion_aes,clipiqa,"
    "face_count,horizon_tilt_deg,rule_of_thirds_offset,composition_score,"
    "canon_zone_distribution_kl,canon_zone_clip_pct,canon_midgray_offset,"
    "canon_symmetry,canon_diagonal_energy,canon_balance,"
    "canon_thirds_concentration,canon_lead_room,canon_figure_ground,"
    "canon_mono_channel_delta,canon_long_exposure_score,face_clusters,"
    "gps_cluster_id,cluster_id,decision,reason,score_final,score_sharpness,"
    "score_composition,score_exposure,score_aesthetic,score_moment,peak_rank,"
    "is_burst_peak,burst_peak_reason,rubric_technical_stars,"
    "rubric_technical_pass,rubric_subject_stars,rubric_subject_pass,"
    "rubric_composition_stars,rubric_composition_pass,rubric_light_stars,"
    "rubric_light_pass,rubric_moment_stars,rubric_moment_pass,"
    "rubric_aesthetic_stars,rubric_aesthetic_pass,model_technical_stars,"
    "model_subject_stars,model_composition_stars,model_light_stars,"
    "model_moment_stars,model_aesthetic_stars\n"
)


def _row(fn, decision="keep"):
    return (f"/x/{fn},{fn},,landscape,\"{{'landscape':0.9}}\",,,,,0.5,800,800,"
            f"128,5,5,0.9,4.2,0.4,0,,,0.6,,,,,,,,,,,,[],,0,{decision},demo,"
            f"0.7,1.0,0.6,0.5,0.5,0.5,0,False,,4,,4,,4,,4,,4,,4,,,,,,,\n")


@pytest.fixture(scope="module")
def mod():
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_app_results_cache_test",
        repo / "pixcull" / "report" / "serve_app.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["serve_app_results_cache_test"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def counting_build(mod, monkeypatch):
    """Wrap the uncached builder so tests can count real rebuilds."""
    calls = []
    original = mod._build_results_uncached

    def counted(run_id):
        calls.append(run_id)
        return original(run_id)

    monkeypatch.setattr(mod, "_build_results_uncached", counted)
    # a shared dict across tests would leak hits; start clean
    monkeypatch.setattr(mod, "_RESULTS_CACHE", {})
    return calls


def _make_run(mod, monkeypatch, root, rid="cacherun", n=3, annotations=None):
    out = root / rid / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.csv").write_text(
        _HEADER + "".join(_row(f"p{i}.jpg") for i in range(n)),
        encoding="utf-8")
    (out / "manifest.json").write_text("{}")
    if annotations is not None:
        (out / "annotations.jsonl").write_text(
            "".join(json.dumps(a) + "\n" for a in annotations),
            encoding="utf-8")
    monkeypatch.setattr(mod, "_DEMO_ROOT", root)
    assert mod._reload_run_from_disk(rid) is not None
    return rid


def test_warm_call_is_served_from_cache(mod, monkeypatch, tmp_path,
                                       counting_build):
    rid = _make_run(mod, monkeypatch, tmp_path)

    first = mod._build_results(rid)
    second = mod._build_results(rid)

    assert first is not None
    assert len(counting_build) == 1, "second call rebuilt instead of hitting cache"
    # same objects handed back — the documented read-only contract
    assert second[0] is first[0]
    assert second[1] is first[1]


def test_saving_an_annotation_busts_the_cache(mod, monkeypatch, tmp_path,
                                              counting_build):
    """The failure this guards against: a photographer marks a photo and
    the server keeps serving the pre-annotation snapshot."""
    rid = _make_run(mod, monkeypatch, tmp_path)
    ann_path = tmp_path / rid / "output" / "annotations.jsonl"

    rows, summary = mod._build_results(rid)
    assert summary["n_human_decided"] == 0

    ann_path.write_text(
        json.dumps({"filename": "p1.jpg", "overall_label": "cull"}) + "\n",
        encoding="utf-8")

    rows2, summary2 = mod._build_results(rid)
    assert len(counting_build) == 2, "annotation write did not bust the cache"
    assert summary2["n_human_decided"] == 1
    assert {r["filename"]: r["human_decided"]
            for r in rows2}["p1.jpg"] is True


def test_appending_a_second_annotation_busts_again(mod, monkeypatch, tmp_path,
                                                   counting_build):
    rid = _make_run(
        mod, monkeypatch, tmp_path,
        annotations=[{"filename": "p0.jpg", "overall_label": "keep"}])
    ann_path = tmp_path / rid / "output" / "annotations.jsonl"

    assert mod._build_results(rid)[1]["n_human_decided"] == 1

    # mtime granularity: ensure the append is observably newer
    with ann_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"filename": "p1.jpg",
                             "overall_label": "cull"}) + "\n")
    _bump_mtime(ann_path)

    assert mod._build_results(rid)[1]["n_human_decided"] == 2
    assert len(counting_build) == 2


def test_rescore_rewriting_scores_csv_busts_the_cache(mod, monkeypatch,
                                                      tmp_path,
                                                      counting_build):
    rid = _make_run(mod, monkeypatch, tmp_path, n=3)
    scores = tmp_path / rid / "output" / "scores.csv"

    assert mod._build_results(rid)[1]["n_total"] == 3

    scores.write_text(_HEADER + "".join(_row(f"p{i}.jpg") for i in range(5)),
                      encoding="utf-8")
    _bump_mtime(scores)

    assert mod._build_results(rid)[1]["n_total"] == 5
    assert len(counting_build) == 2


def test_same_run_id_under_a_different_root_does_not_collide(
        mod, monkeypatch, tmp_path, counting_build):
    """run_id is unique only within a demo root; the key carries the
    output_dir so two roots can't serve each other's rows."""
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _make_run(mod, monkeypatch, root_a, rid="samename", n=2)
    rows_a, sum_a = mod._build_results("samename")
    assert sum_a["n_total"] == 2

    _make_run(mod, monkeypatch, root_b, rid="samename", n=7)
    rows_b, sum_b = mod._build_results("samename")

    assert sum_b["n_total"] == 7, "cache served the other root's run"
    assert len(counting_build) == 2


def test_cache_is_bounded(mod, monkeypatch, tmp_path, counting_build):
    for i in range(mod._RESULTS_CACHE_MAX + 3):
        _make_run(mod, monkeypatch, tmp_path, rid=f"run{i}", n=1)
        mod._build_results(f"run{i}")
    assert len(mod._RESULTS_CACHE) <= mod._RESULTS_CACHE_MAX


def test_missing_scores_csv_returns_none_and_caches_nothing(
        mod, monkeypatch, tmp_path, counting_build):
    rid = _make_run(mod, monkeypatch, tmp_path)
    (tmp_path / rid / "output" / "scores.csv").unlink()

    assert mod._build_results(rid) is None
    assert mod._RESULTS_CACHE == {}, "a None result must not be cached"


def _bump_mtime(path: Path) -> None:
    """Force an observably newer mtime.

    Same-second rewrites can land on an identical st_mtime_ns on some
    filesystems, which would make this test pass or fail by timing rather
    than by logic.  Nudge it forward explicitly instead of sleeping.
    """
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert path.stat().st_mtime_ns != st.st_mtime_ns


def test_rescore_does_not_pin_old_generations(mod, monkeypatch, tmp_path,
                                              counting_build):
    """A re-scored run must not keep N copies of its own rows alive."""
    rid = _make_run(mod, monkeypatch, tmp_path, n=2)
    scores = tmp_path / rid / "output" / "scores.csv"
    for n in (3, 4, 5):
        scores.write_text(
            _HEADER + "".join(_row(f"p{i}.jpg") for i in range(n)),
            encoding="utf-8")
        _bump_mtime(scores)
        mod._build_results(rid)
    keys = [k for k in mod._RESULTS_CACHE if k[0] == rid]
    assert len(keys) == 1, f"superseded generations still cached: {keys}"
    assert mod._build_results(rid)[1]["n_total"] == 5
