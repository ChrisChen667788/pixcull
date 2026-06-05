"""v2.2-P1-2 — tests for the optional-model manager.

The whole fetch path is exercised over ``file://`` URLs (urllib supports
them) with real sha256s, so there is no network dependency.
"""
import hashlib
import json
from pathlib import Path

import pytest

from pixcull.models_manager import (
    ChecksumError,
    ModelSpec,
    NotPublishedError,
    Sidecar,
    get_spec,
    is_installed,
    list_models,
    models_dir,
    pull,
    resolve_path,
    sha256_file,
)


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _fixture_registry(src: Path, sha: str, *, name="fixture",
                      filename="fixture.bin", sidecars=()):
    return {name: ModelSpec(
        name=name, filename=filename, description="test fixture",
        used_by="tests", url=src.resolve().as_uri(), sha256=sha,
        size=len(src.read_bytes()), sidecars=sidecars,
    )}


# --- paths / registry ------------------------------------------------- #
def test_models_dir_is_created(tmp_path):
    d = models_dir(tmp_path)
    assert d == tmp_path / "models" and d.is_dir()


def test_real_registry_has_audio_tagger(tmp_path):
    spec = get_spec("audio-tagger")
    assert spec.filename == "audio_tagger.onnx"
    # cache path matches what scoring/audio_tagger.py already searches.
    assert resolve_path("audio-tagger", base=tmp_path).name == "audio_tagger.onnx"


def test_get_spec_unknown_raises():
    with pytest.raises(KeyError):
        get_spec("does-not-exist")


def test_pull_unpublished_raises():
    # real audio-tagger is catalogued but has no URL yet → no fs touch
    with pytest.raises(NotPublishedError):
        pull("audio-tagger")


# --- fetch happy path ------------------------------------------------- #
def test_pull_end_to_end(tmp_path):
    src = tmp_path / "src.bin"
    sha = _write(src, b"hello-pixcull-model" * 1000)
    reg = _fixture_registry(src, sha)
    cache = tmp_path / "home"

    assert not is_installed("fixture", registry=reg, base=cache)
    path = pull("fixture", registry=reg, base=cache)

    assert path == cache / "models" / "fixture.bin"
    assert path.read_bytes() == src.read_bytes()
    assert sha256_file(path) == sha
    assert is_installed("fixture", registry=reg, base=cache)


def test_pull_idempotent_no_redownload(tmp_path):
    src = tmp_path / "src.bin"
    sha = _write(src, b"abc" * 500)
    reg = _fixture_registry(src, sha)
    cache = tmp_path / "home"

    p1 = pull("fixture", registry=reg, base=cache)
    mtime = p1.stat().st_mtime_ns
    p2 = pull("fixture", registry=reg, base=cache)  # no force
    assert p2 == p1 and p2.stat().st_mtime_ns == mtime  # untouched


def test_pull_checksum_mismatch_leaves_nothing(tmp_path):
    src = tmp_path / "src.bin"
    _write(src, b"data" * 100)
    reg = _fixture_registry(src, "0" * 64)  # wrong digest
    cache = tmp_path / "home"

    with pytest.raises(ChecksumError):
        pull("fixture", registry=reg, base=cache)
    # no partial/bad file left installed; no leftover .part temp files
    assert not (cache / "models" / "fixture.bin").exists()
    assert not is_installed("fixture", registry=reg, base=cache)
    assert list((cache / "models").glob("*.part")) == []


def test_is_installed_detects_tamper(tmp_path):
    src = tmp_path / "src.bin"
    sha = _write(src, b"orig" * 100)
    reg = _fixture_registry(src, sha)
    cache = tmp_path / "home"

    pull("fixture", registry=reg, base=cache)
    assert is_installed("fixture", registry=reg, base=cache)
    (cache / "models" / "fixture.bin").write_bytes(b"tampered")
    assert not is_installed("fixture", registry=reg, base=cache)


def test_force_redownloads(tmp_path):
    src = tmp_path / "src.bin"
    sha = _write(src, b"orig" * 100)
    reg = _fixture_registry(src, sha)
    cache = tmp_path / "home"

    p = pull("fixture", registry=reg, base=cache)
    p.write_bytes(b"corrupt")
    pull("fixture", registry=reg, base=cache, force=True)
    assert is_installed("fixture", registry=reg, base=cache)
    assert p.read_bytes() == src.read_bytes()


def test_pull_fetches_sidecar(tmp_path):
    model = tmp_path / "m.onnx"
    msha = _write(model, b"M" * 200)
    labels = tmp_path / "labels.json"
    lsha = _write(labels, json.dumps(["laughter", "applause"]).encode())
    reg = {"m": ModelSpec(
        name="m", filename="m.onnx", description="d", used_by="t",
        url=model.resolve().as_uri(), sha256=msha, size=200,
        sidecars=(Sidecar("m.onnx.labels.json",
                          labels.resolve().as_uri(), lsha),),
    )}
    cache = tmp_path / "home"

    pull("m", registry=reg, base=cache)
    side = cache / "models" / "m.onnx.labels.json"
    assert side.exists() and json.loads(side.read_text()) == ["laughter", "applause"]


# --- listing ---------------------------------------------------------- #
def test_list_models_fresh_cache(tmp_path):
    rows = list_models(base=tmp_path)
    by_name = {r.spec.name: r for r in rows}
    assert "audio-tagger" in by_name
    assert by_name["audio-tagger"].installed is False


# --- CLI smoke -------------------------------------------------------- #
def test_cli_models_list_exit0():
    from typer.testing import CliRunner
    from pixcull.cli import app
    res = CliRunner().invoke(app, ["models", "list"])
    assert res.exit_code == 0


def test_cli_models_path_unknown_exit2():
    from typer.testing import CliRunner
    from pixcull.cli import app
    res = CliRunner().invoke(app, ["models", "path", "no-such-model"])
    assert res.exit_code == 2


def test_cli_models_path_uninstalled_exit1(tmp_path, monkeypatch):
    import pixcull.models_manager as mm
    monkeypatch.setattr(mm, "PIXCULL_HOME", tmp_path)  # empty cache
    from typer.testing import CliRunner
    from pixcull.cli import app
    res = CliRunner().invoke(app, ["models", "path", "audio-tagger"])
    assert res.exit_code == 1
    assert "audio_tagger.onnx" in res.stdout
