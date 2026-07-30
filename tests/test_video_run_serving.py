"""v2.35.2 — a video run culled by the CLI must be serveable.

Found while shooting the gallery: `pixcull video` produces a run with
**no manifest.json and no input/ dir** (its frames live in
``video_frames/<clip>_<hash>/``), and ``_reload_run_from_disk`` required
one of those two to exist.  So after a server restart the run failed to
reload entirely — ``/api/v1/runs`` reported it missing, every
``/thumb/<run>/<frame>`` 404'd, and ``/timeline/<run>`` rendered as 50
broken images.

Two fixes, both tested here:

* recognise a run by ``scores.csv`` (the real marker), in either the
  nested ``<run>/output/`` layout or directly in ``<run>/`` — which is
  what ``pixcull video --output <dir>`` produces;
* resolve frames through scores.csv's own ``path`` column, mtime-cached
  because the resolver runs once PER THUMBNAIL.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HEADER = "path,filename,decision,score_final\n"


@pytest.fixture(scope="module")
def mod():
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_app_videorun_test", repo / "pixcull" / "report" / "serve_app.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["serve_app_videorun_test"] = m
    spec.loader.exec_module(m)
    return m


def _frames(root: Path, n=3, sub="video_frames/clip_abc123"):
    d = root / sub
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(1, n + 1):
        p = d / f"frame_{i:06d}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xd9")
        out.append(p)
    return out


def _scores(out_dir: Path, frames):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{p},{p.name},keep,0.7\n" for p in frames)
    (out_dir / "scores.csv").write_text(_HEADER + rows, encoding="utf-8")


def test_video_run_nested_layout_reloads(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    run = tmp_path / "vidrun"
    out = run / "output"
    frames = _frames(run, 3)
    _scores(out, frames)

    info = mod._reload_run_from_disk("vidrun")
    assert info is not None, "a video run must be reloadable"
    assert info["mode"] == "csv"
    assert Path(info["output_dir"]) == out


def test_video_run_flat_layout_reloads(mod, tmp_path, monkeypatch):
    """`pixcull video --output <dir>` writes scores.csv straight into
    <dir> — there is no nested output/."""
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    run = tmp_path / "flatrun"
    frames = _frames(run, 2)
    _scores(run, frames)

    info = mod._reload_run_from_disk("flatrun")
    assert info is not None, "flat --output layout must be reloadable"
    assert Path(info["output_dir"]) == run


def test_frames_resolve_through_the_scores_path_column(mod, tmp_path,
                                                       monkeypatch):
    """The concrete failure: /thumb 404 for every frame."""
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    run = tmp_path / "vidrun2"
    out = run / "output"
    frames = _frames(run, 3)
    _scores(out, frames)

    info = mod._reload_run_from_disk("vidrun2")
    for p in frames:
        got = mod._resolve_image_source(info, p.name)
        assert got is not None, f"{p.name} did not resolve — /thumb would 404"
        assert Path(got) == p


def test_a_frame_that_moved_resolves_to_none(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    run = tmp_path / "vidrun3"
    out = run / "output"
    frames = _frames(run, 2)
    _scores(out, frames)
    info = mod._reload_run_from_disk("vidrun3")
    frames[0].unlink()
    mod._SCORES_PATH_CACHE = type(mod._SCORES_PATH_CACHE)(maxsize=8)
    assert mod._resolve_image_source(info, frames[0].name) is None
    assert mod._resolve_image_source(info, frames[1].name) is not None


def test_scores_path_map_is_cached_not_reparsed_per_thumbnail(mod, tmp_path):
    """Called once per image: an inline parse would be N parses to draw
    one timeline."""
    run = tmp_path / "cachedrun"
    frames = _frames(run, 3)
    _scores(run, frames)

    first = mod._scores_path_map(run)
    second = mod._scores_path_map(run)
    assert first is second, "scores.csv path map is being rebuilt every call"
    assert len(first) == 3


def test_rewriting_scores_csv_busts_the_path_map(mod, tmp_path):
    import os
    run = tmp_path / "rerun"
    frames = _frames(run, 2)
    _scores(run, frames)
    assert len(mod._scores_path_map(run)) == 2

    more = _frames(run, 4)
    _scores(run, more)
    csv_path = run / "scores.csv"
    st = csv_path.stat()
    os.utime(csv_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    assert len(mod._scores_path_map(run)) == 4, "stale path map served"


# ── the two pre-existing modes must be untouched ────────────────────────

def test_scan_mode_still_wins_when_a_manifest_exists(mod, tmp_path,
                                                     monkeypatch):
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    run = tmp_path / "scanrun"
    out = run / "output"
    out.mkdir(parents=True)
    src = tmp_path / "originals"
    src.mkdir()
    real = src / "a.jpg"
    real.write_bytes(b"\xff\xd8\xff\xd9")
    (out / "manifest.json").write_text(json.dumps({"a.jpg": str(real)}))
    _scores(out, [real])

    info = mod._reload_run_from_disk("scanrun")
    assert info["mode"] == "scan"
    assert Path(mod._resolve_image_source(info, "a.jpg")) == real


def test_upload_mode_still_wins_when_input_dir_exists(mod, tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    run = tmp_path / "uprun"
    out = run / "output"
    inp = run / "input"
    out.mkdir(parents=True)
    inp.mkdir()
    f = inp / "b.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")
    _scores(out, [f])

    info = mod._reload_run_from_disk("uprun")
    assert info["mode"] == "upload"
    assert Path(mod._resolve_image_source(info, "b.jpg")) == f


def test_a_directory_with_no_scores_csv_is_still_not_a_run(mod, tmp_path,
                                                           monkeypatch):
    """Recognition must not become so loose that any folder is a run."""
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    (tmp_path / "notarun" / "output").mkdir(parents=True)
    assert mod._reload_run_from_disk("notarun") is None
