"""V1.2 rescorer runtime-integration tests.

The V1.1 rescorer existed as a *trainer* (`scripts/train_rescorer.py`) and a
review-time overlay (`scripts/serve_review.py`), but the shipped pipeline
itself ignored it. V1.2 wires it into `pixcull.rules.decide` via a three-mode
knob (`config.rescorer.mode`):

* ``off`` — rescorer not loaded; decisions are bit-identical to V1.1.
* ``shadow`` — rescorer loaded + scored, prediction attached to output,
  decisions unchanged. Safe to leave on.
* ``adjudicate`` — rescorer can flip rule-MAYBE rows to KEEP (or CULL) when
  confident. Rule-keeps / rule-culls are never overridden.

These tests exercise ``decide()`` directly (unit) and the library module
``pixcull.scoring.rescorer`` (integration against the real joblib artifact).
They do NOT exercise the full `run_pipeline()` — that needs cv2/rawpy/
mediapipe/torchvision and is covered by `test_v1_1_scripts.py` + eventual
fixture-replay tests.

Bit-identical regression guard: the V1.1 decision behavior is locked in
`test_decision.py`. Here we additionally verify that when mode=off OR
rescorer_prob_keep=None, decide() returns the SAME decision a V1.1 caller
would get — i.e. the V1.2 knob is pure addition, not replacement.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
MODEL_PATH = REPO_ROOT / "models" / "rescorer_v1.joblib"


# Importing pixcull.scoring.decision pulls in pixcull.scoring.__init__ which
# imports AestheticScorer → torchvision. In CI envs without torchvision we
# want the unit tests to still collect — so we guard imports at call time.
def _import_core():
    """Import decide + Decision + PixCullConfig without activating torchvision.

    The scoring package's __init__.py re-exports AestheticScorer, which pulls
    torchvision. We bypass that by loading the modules with importlib.
    """
    import importlib.util

    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    cfg_mod = _load("pixcull.config", REPO_ROOT / "pixcull" / "config.py")
    dec_mod = _load(
        "pixcull.scoring.decision",
        REPO_ROOT / "pixcull" / "scoring" / "decision.py",
    )
    return cfg_mod.PixCullConfig, dec_mod.decide, dec_mod.Decision


def _import_rescorer():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pixcull.scoring.rescorer",
        REPO_ROOT / "pixcull" / "scoring" / "rescorer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pixcull.scoring.rescorer"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def core():
    Cfg, decide, Decision = _import_core()
    return Cfg.load(), decide, Decision


# ---------------------------------------------------------------------------
# Config: RescorerConfig defaults
# ---------------------------------------------------------------------------


def test_rescorer_config_defaults_are_safe(core):
    """Fresh config.load() must default to mode=off. No surprises on clone."""
    config, _, _ = core
    assert config.rescorer.mode == "off", \
        "default mode must be 'off' — enabling rescorer requires explicit opt-in"
    assert config.rescorer.maybe_to_cull_threshold == 0.0, \
        "demote (maybe→cull) must be disabled by default (threshold=0)"
    assert config.rescorer.keep_threshold >= 0.5, \
        "keep_threshold must require above-50% confidence to promote"


# ---------------------------------------------------------------------------
# Mode = off: bit-identical to V1.1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prob", [0.01, 0.5, 0.95, None])
def test_mode_off_ignores_rescorer(core, prob):
    """Whatever P(keep) the rescorer emits, mode=off treats it as absent.

    This is the regression guard: V1.2 code in production but rescorer mode
    still off must produce byte-identical decisions to a V1.1 deployment.
    """
    config, decide, Decision = core
    config.rescorer.mode = "off"
    # Maybe-zone score on landscape: classic V1.1 MAYBE.
    dec, _ = decide(0.55, [], config, "standard",
                    scene="landscape", rescorer_prob_keep=prob)
    assert dec is Decision.MAYBE, \
        f"mode=off + prob={prob} should stay MAYBE (rule's verdict)"


# ---------------------------------------------------------------------------
# Mode = shadow: still no override, but rescorer is "seen" by the pipeline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prob", [0.01, 0.5, 0.95])
def test_mode_shadow_does_not_alter_decisions(core, prob):
    """Shadow mode is *observation only*. Decisions must match mode=off."""
    config, decide, Decision = core
    config.rescorer.mode = "shadow"
    dec, _ = decide(0.55, [], config, "standard",
                    scene="landscape", rescorer_prob_keep=prob)
    assert dec is Decision.MAYBE, \
        f"shadow mode must not alter decisions (got {dec} at prob={prob})"


# ---------------------------------------------------------------------------
# Mode = adjudicate: the rescorer can flip rule=MAYBE, never rule=KEEP/CULL
# ---------------------------------------------------------------------------


def test_adjudicate_promotes_confident_maybe_to_keep(core):
    """When rule says MAYBE and P(keep) clears keep_threshold → KEEP."""
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    config.rescorer.keep_threshold = 0.75
    dec, reasons = decide(0.55, [], config, "standard",
                          scene="landscape", rescorer_prob_keep=0.92)
    assert dec is Decision.KEEP
    assert any("rescorer_promoted" in r for r in reasons), \
        "promotion reason must be in the audit trail"


def test_adjudicate_respects_keep_threshold(core):
    """P(keep) just below keep_threshold must stay MAYBE."""
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    config.rescorer.keep_threshold = 0.75
    dec, _ = decide(0.55, [], config, "standard",
                    scene="landscape", rescorer_prob_keep=0.74)
    assert dec is Decision.MAYBE


def test_adjudicate_never_overrides_rule_keep(core):
    """Even if rescorer is extremely pessimistic, rule-KEEP stands in V1.2.

    Rationale: the rule stack's KEEP bucket is the high-confidence bucket.
    Demoting a confident rule-keep based on rescorer output is a different
    risk profile (and a different eval). Left for V1.3+ behind its own
    threshold knob.
    """
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    dec, reasons = decide(0.90, [], config, "standard",
                          scene="landscape", rescorer_prob_keep=0.05)
    assert dec is Decision.KEEP
    assert all("rescorer_" not in r for r in reasons), \
        "no rescorer note should appear on a rule-KEEP passthrough"


def test_adjudicate_never_overrides_rule_cull(core):
    """Symmetric guard: rescorer cannot resurrect a rule-CULL."""
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    dec, reasons = decide(0.20, [], config, "standard",
                          scene="landscape", rescorer_prob_keep=0.95)
    assert dec is Decision.CULL
    assert all("rescorer_" not in r for r in reasons)


def test_adjudicate_hard_cull_flag_beats_rescorer(core):
    """Hard-cull flags (closed_eyes, motion_blur_on_face, ...) remain
    non-negotiable. The rescorer can't overturn them."""
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    dec, _ = decide(0.80, ["closed_eyes"], config, "standard",
                    scene="portrait", rescorer_prob_keep=0.99)
    assert dec is Decision.CULL


def test_adjudicate_prob_none_falls_back_to_rule(core):
    """rescorer_prob_keep=None = 'rescorer had no opinion here'. Exit gracefully.

    This path is what happens when the rescorer failed to score a row (bad
    feature values, model load failed silently, etc.). Must NOT crash; must
    NOT promote or demote.
    """
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    dec, _ = decide(0.55, [], config, "standard",
                    scene="landscape", rescorer_prob_keep=None)
    assert dec is Decision.MAYBE


def test_adjudicate_demote_disabled_by_default(core):
    """maybe→cull demote is OFF by default (threshold=0). Must not trigger.

    Rationale: wrongly culling a maybe photo is much worse than wrongly
    keeping one — the user can still re-review keeps, but a culled photo
    may be gone. V1.2 ships promote-only; demote is opt-in per-user.
    """
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    config.rescorer.maybe_to_cull_threshold = 0.0
    dec, _ = decide(0.55, [], config, "standard",
                    scene="landscape", rescorer_prob_keep=0.02)
    assert dec is Decision.MAYBE


def test_adjudicate_demote_fires_when_enabled(core):
    """If the user opts in, low P(keep) demotes maybe → cull."""
    config, decide, Decision = core
    config.rescorer.mode = "adjudicate"
    config.rescorer.maybe_to_cull_threshold = 0.15
    dec, reasons = decide(0.55, [], config, "standard",
                          scene="landscape", rescorer_prob_keep=0.05)
    assert dec is Decision.CULL
    assert any("rescorer_demoted" in r for r in reasons)


# ---------------------------------------------------------------------------
# Library module: load_rescorer + score_row against the real joblib
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not MODEL_PATH.exists(),
                    reason="rescorer_v1.joblib absent — run scripts/train_rescorer.py first")
def test_load_rescorer_returns_artifact_with_expected_shape():
    mod = _import_rescorer()
    art = mod.load_rescorer(str(MODEL_PATH))
    assert art is not None, "joblib should load cleanly in current env"
    assert art.model_name in ("lr", "gbm", "rf")
    assert art.train_rows >= 30, "training set too small for a sane V1.1 artifact"
    assert len(art.feature_cols) >= 10, "feature list suspiciously short"
    # The scene column goes through OneHotEncoder, so it IS a feature col.
    assert "scene" in art.feature_cols
    # __missing indicators must be discoverable by suffix (see the class doc).
    assert set(art.missing_indicator_bases) >= {"face_min_ear"}, \
        "face_min_ear__missing was one of the more informative features; " \
        "its absence from the artifact suggests the trainer drifted"


def test_load_rescorer_missing_path_returns_none():
    mod = _import_rescorer()
    assert mod.load_rescorer("/tmp/nope.joblib") is None


def test_load_rescorer_none_path_returns_none():
    """Sentinel: orchestrator passes None when mode=off.  Must not raise."""
    mod = _import_rescorer()
    assert mod.load_rescorer(None) is None


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="rescorer_v1.joblib absent")
def test_score_row_returns_pred_and_prob():
    mod = _import_rescorer()
    art = mod.load_rescorer(str(MODEL_PATH))
    row = {
        "filename": "t.JPG", "scene": "landscape",
        "laplacian_global": 420.0, "laplacian_subject": 380.0,
        "mean_luma": 0.45, "highlight_clip_pct": 0.01, "shadow_clip_pct": 0.02,
        "laion_aes": 5.2, "clipiqa": 0.58, "scene_confidence": 0.91,
        "face_count": 0, "face_max_blink": math.nan, "face_min_ear": math.nan,
        "horizon_tilt_deg": 1.2, "rule_of_thirds_offset": 0.08,
        "composition_score": 0.82, "subject_fraction": 0.04,
        "score_sharpness": 0.88, "score_composition": 0.82,
        "score_exposure": 0.95, "score_aesthetic": 0.52, "score_final": 0.76,
    }
    out = mod.score_row(art, row)
    assert out is not None
    assert out["pred"] in ("keep", "maybe")
    assert 0.0 <= out["prob_keep"] <= 1.0
    # Consistency: pred should match the prob_keep threshold at 0.5
    assert (out["pred"] == "keep") == (out["prob_keep"] > 0.5)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="rescorer_v1.joblib absent")
def test_score_row_handles_sparse_input():
    """Rows with most features missing must still produce an answer — the
    pipeline's imputer handles NaN. No crash, no None."""
    mod = _import_rescorer()
    art = mod.load_rescorer(str(MODEL_PATH))
    out = mod.score_row(art, {"filename": "x.JPG", "scene": "portrait"})
    assert out is not None
    assert out["pred"] in ("keep", "maybe")


# ---------------------------------------------------------------------------
# CLI surface: --rescorer-mode / --rescorer-path are wired up
# ---------------------------------------------------------------------------


def test_cli_help_advertises_rescorer_flags():
    """`pixcull run --help` must document the V1.2 flags so users discover them."""
    # typer/rich decorates CLI help; we pipe through a dumb COLUMNS so output
    # isn't wrapped across lines in a way that hides keywords.
    r = subprocess.run(
        [sys.executable, "-m", "pixcull", "run", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={"COLUMNS": "200", "PATH": __import__("os").environ["PATH"],
             "PYTHONPATH": str(REPO_ROOT),
             "HOME": __import__("os").environ.get("HOME", "/tmp")},
        timeout=30,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"help failed: {out}"
    assert "--rescorer-mode" in out, \
        "--rescorer-mode flag must appear in `run --help`"
    assert "--rescorer-path" in out, \
        "--rescorer-path flag must appear in `run --help`"
