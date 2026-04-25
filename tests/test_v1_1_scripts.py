"""Smoke tests for the V1.1 script suite.

The four V1.1 scripts (`train_rescorer`, `compare_rescorers`,
`pick_next_to_label`, `check_v1_2_trigger`) are standalone entry-points
with no importable library layer. We smoke-test them via subprocess so:

  1. The tests match how the user actually runs them.
  2. Import-time side-effects (sys.path hacks in two of the scripts) are
     exercised exactly as in production.
  3. These tests collect and run even when the full detector stack
     (cv2, rawpy, mediapipe) is unavailable — they only need Python +
     pandas + sklearn, which are already in the V1.1 dep closure.

What we're NOT testing here: the actual CV numbers. Those belong in
`eval_findings.md` so they can drift with the dataset; pinning them in
a test would make future labelling passes break CI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TRAINING_CSV = REPO_ROOT / "training.csv"
SCORES_CSV = REPO_ROOT / "tests/fixtures/_eval_output/scores.csv"
GT_CSV = REPO_ROOT / "tests/fixtures/ground_truth.csv"


def _run(script: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Invoke a V1.1 script with args, capturing stdout/stderr."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# train_rescorer.py
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TRAINING_CSV.exists(),
                    reason="training.csv absent — run export_training_set.py first")
def test_train_rescorer_gbm_smoke(tmp_path):
    """Default GBM head runs, emits expected report sections, saves joblib."""
    out = tmp_path / "rescorer.joblib"
    r = _run("train_rescorer.py", str(TRAINING_CSV), str(out),
             "--model", "gbm", "--cv", "5", "--seed", "42")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "V1.1 RESCORER" in r.stdout
    assert "Accuracy:" in r.stdout
    assert "keep recall:" in r.stdout
    assert "maybe recall:" in r.stdout
    assert "Per-scene accuracy" in r.stdout
    assert "Rule baseline" in r.stdout  # we have a fixture scores.csv
    assert out.exists()
    assert out.stat().st_size > 10_000, "joblib artifact suspiciously small"


@pytest.mark.skipif(not TRAINING_CSV.exists(), reason="training.csv absent")
def test_train_rescorer_skip_save_with_dash(tmp_path):
    """out_path='-' means CV-only, no joblib write — useful for exploration."""
    r = _run("train_rescorer.py", str(TRAINING_CSV), "-",
             "--model", "gbm", "--cv", "5", "--seed", "42")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    # Should still run CV
    assert "Accuracy:" in r.stdout
    # Should NOT claim it saved a file
    assert "Saved model" not in r.stdout


@pytest.mark.skipif(not TRAINING_CSV.exists(), reason="training.csv absent")
def test_train_rescorer_lr_still_works(tmp_path):
    """LR head is retained for interpretability audits (even if GBM is default)."""
    out = tmp_path / "rescorer_lr.joblib"
    r = _run("train_rescorer.py", str(TRAINING_CSV), str(out), "--model", "lr")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "model=lr" in r.stdout


def test_train_rescorer_missing_input_exits_cleanly(tmp_path):
    """Missing training.csv → error exit with a readable message, not a traceback."""
    out = tmp_path / "x.joblib"
    nope = tmp_path / "does_not_exist.csv"
    r = _run("train_rescorer.py", str(nope), str(out))
    assert r.returncode != 0
    combined = (r.stdout + r.stderr).lower()
    assert "not found" in combined or "no such" in combined


# ---------------------------------------------------------------------------
# compare_rescorers.py
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TRAINING_CSV.exists(), reason="training.csv absent")
def test_compare_rescorers_sweep():
    """LR/GBM/RF rows + landscape-only block + verdict banner all present."""
    r = _run("compare_rescorers.py")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    for head in ("lr", "gbm", "rf"):
        assert head in r.stdout, f"missing {head} row"
    assert "Landscape-only subset" in r.stdout
    # Verdict banner: either "data ceiling" or "best = <model>"
    assert ("signal ceiling is DATA" in r.stdout
            or "best =" in r.stdout), "missing verdict banner"


# ---------------------------------------------------------------------------
# pick_next_to_label.py
# ---------------------------------------------------------------------------

def test_pick_next_to_label_report_and_csv(tmp_path):
    """Stratified sampling prints shortfall table + optional --out-csv writes."""
    out_csv = tmp_path / "next_to_label.csv"
    r = _run("pick_next_to_label.py",
             str(SCORES_CSV), str(GT_CSV),
             "--n", "40", "--out-csv", str(out_csv))
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "Total shortfall across cells:" in r.stdout
    # All seven scenes (the canonical V1.1 vocabulary) appear in the table.
    for scene in ("portrait", "landscape", "stilllife", "event",
                  "street", "architecture", "wildlife"):
        assert scene in r.stdout, f"scene {scene!r} missing from report"
    # Output CSV has the expected columns.
    assert out_csv.exists()
    header = out_csv.read_text().splitlines()[0]
    for col in ("filename", "scene", "suggested_band",
                "score_final", "manual_label", "notes"):
        assert col in header, f"missing column {col!r} in out-csv header"


def test_pick_next_to_label_without_out_csv():
    """No --out-csv flag: still emits the report, exit 0."""
    r = _run("pick_next_to_label.py", str(SCORES_CSV), str(GT_CSV), "--n", "5")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "Total shortfall" in r.stdout


def test_pick_next_to_label_missing_inputs_fail_cleanly(tmp_path):
    """Nonexistent paths → clean error exit, no traceback spew."""
    nope = tmp_path / "nope.csv"
    r = _run("pick_next_to_label.py", str(nope), str(GT_CSV))
    assert r.returncode != 0
    assert "not found" in (r.stdout + r.stderr).lower()


# ---------------------------------------------------------------------------
# check_v1_2_trigger.py
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TRAINING_CSV.exists(), reason="training.csv absent")
def test_check_v1_2_trigger_red_on_small_fixture():
    """All three gates fail on the 128-row fixture → exit 1 with STATUS: NOT READY."""
    r = _run("check_v1_2_trigger.py", str(TRAINING_CSV))
    assert r.returncode == 1, "expected non-zero exit on red gates"
    assert "V1.2 RESCORER RUNTIME-INTEGRATION TRIGGER CHECK" in r.stdout
    # All three named gates appear in the checklist
    assert "(1) training rows" in r.stdout
    assert "(2) landscape-only CV AUC" in r.stdout
    assert "(3)" in r.stdout  # Δ acc vs rule line (unicode Δ optional)
    assert "STATUS: NOT READY" in r.stdout
    # The "how to make it green" hints kick in for each failing gate
    assert "needs" in r.stdout and "more labelled rows" in r.stdout


# ---------------------------------------------------------------------------
# V1.1 data housekeeping regression test
# ---------------------------------------------------------------------------

def test_ground_truth_uses_english_scene_vocabulary():
    """V1.1 normalised 街拍 → street and bird → wildlife.

    Regression guard: if someone re-imports a raw labelling session and
    accidentally introduces Chinese scene labels again, pick_next_to_label
    will silently undercount those cells. This test fails loudly.
    """
    import pandas as pd
    gt = pd.read_csv(GT_CSV, comment="#")
    scenes = set(gt["scene"].unique())
    allowed = {
        "portrait", "landscape", "stilllife", "event",
        "street", "architecture", "wildlife",
    }
    non_ascii = [s for s in scenes if not s.isascii()]
    assert not non_ascii, f"non-ASCII scene labels leaked back in: {non_ascii}"
    leaked = scenes - allowed
    assert not leaked, f"scene labels outside V1.1 vocabulary: {leaked}"
