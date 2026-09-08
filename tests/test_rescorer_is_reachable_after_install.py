"""v3.44 — the learned head has to be findable from outside a checkout.

`RescorerConfig.model_path` defaults to `models/rescorer_v1.joblib`,
which is relative to the working directory. In a git checkout that
resolves; after `pip install pixcull` it never did, and the artifacts
were not in the wheel either, so every PyPI user has been scored
rule-only while the README listed the learned head as something you get.
v3.38's reachability column found it.

The artifacts now live in `pixcull/models/`. The working-directory path
still wins when it exists, because that is where `scripts/train_*.py`
write and a photographer's own retrained head must beat the one we
shipped.
"""
from pathlib import Path

import pytest

from pixcull import model_assets
from pixcull.scoring.axis_rescorer import load_axis_rescorers
from pixcull.scoring.rescorer import load_rescorer
from pixcull.scoring.rubric import RUBRIC_AXES

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = "models/rescorer_v1.joblib"


def test_the_artifacts_are_inside_the_package():
    """Not next to it. `models/` at the repo root is where training
    writes; it is not in the wheel and must not be what the default
    depends on."""
    assert (model_assets.PACKAGED_MODELS / "rescorer_v1.joblib").is_file()
    for axis in RUBRIC_AXES:
        p = model_assets.PACKAGED_MODELS / f"rescorer_axis_{axis.name}.joblib"
        assert p.is_file(), f"no packaged model for axis {axis.name}"


def test_the_default_path_resolves_from_a_directory_with_no_models(tmp_path,
                                                                   monkeypatch):
    """The actual failure, reproduced: cwd is not a checkout."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "models").exists()
    resolved = model_assets.resolve(DEFAULT)
    assert resolved.is_file(), f"{DEFAULT} still resolves to nothing"
    assert model_assets.PACKAGED_MODELS in resolved.parents


def test_it_actually_loads_from_there(tmp_path, monkeypatch):
    """Resolving to a path proves nothing; joblib has to open it."""
    monkeypatch.chdir(tmp_path)
    art = load_rescorer(DEFAULT)
    if art is None:
        pytest.skip("joblib/sklearn unavailable or version-drifted in this env")
    assert art.model_name
    axes = load_axis_rescorers("models")
    assert sorted(axes) == sorted(a.name for a in RUBRIC_AXES)


def test_a_local_models_dir_still_wins(tmp_path, monkeypatch):
    """A head the photographer trained beats the one we shipped. If this
    inverts, `pixcull train` becomes a no-op and says nothing."""
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "models"
    local.mkdir()
    (local / "rescorer_v1.joblib").write_bytes(b"not really a model")
    assert model_assets.resolve(DEFAULT) == Path(DEFAULT)
    assert model_assets.resolve_dir("models") == Path("models")


def test_an_absolute_path_is_never_second_guessed(tmp_path):
    """--rescorer-path names one file. Silently substituting ours for a
    typo'd path would be worse than the error."""
    missing = tmp_path / "nope.joblib"
    assert model_assets.resolve(missing) == missing
    assert load_rescorer(missing) is None


def test_the_error_still_names_what_the_user_asked_for(tmp_path, monkeypatch,
                                                       capsys):
    monkeypatch.chdir(tmp_path)
    assert load_rescorer("models/not_a_model_we_ship.joblib") is None
    err = capsys.readouterr().err
    assert "not_a_model_we_ship.joblib" in err
    assert "rule-only" in err
