"""INFRA-2 — release gate for scripts/cli_audit.py.

This test acts as the regression boundary for the audit report
surface.  Anyone breaking the markdown shape (changing a header,
dropping a section, removing a flag) fails CI here before the
break ships.

We exercise the CLI as a subprocess so we test the actual
user-facing surface (argparse + stdout) rather than the internal
helpers (which already have unit tests in
test_face_audit / test_wedding_moments / etc.).
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "cli_audit.py"


@pytest.fixture
def synthetic_scores_csv(tmp_path: Path) -> Path:
    """Build a tiny synthetic scores.csv that exercises every audit
    section: scene distribution, polluted face cluster, wedding
    moment coverage."""
    out = tmp_path / "out" / "scores.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "filename", "scene", "wedding_moment",
            "face_cluster_id", "face_embeddings",
        ])
        # Wedding moments — mix of mandatory + non-mandatory
        w.writerow(["IMG_001.jpg", "wedding", "preparation_bride",
                    1, json.dumps([[1.0, 0.0, 0.0]])])
        w.writerow(["IMG_002.jpg", "wedding", "preparation_bride",
                    1, json.dumps([[0.98, 0.02, 0.0]])])
        w.writerow(["IMG_003.jpg", "wedding", "first_kiss",
                    2, json.dumps([[0.0, 1.0, 0.0]])])
        w.writerow(["IMG_004.jpg", "wedding", "processional",
                    2, json.dumps([[0.0, 0.95, 0.05]])])
        # Cluster 3 = polluted (alice + alice + intruder)
        w.writerow(["IMG_005.jpg", "wedding", "first_kiss",
                    3, json.dumps([[-1.0, 0.0, 0.0]])])
        w.writerow(["IMG_006.jpg", "wedding", "unknown",
                    3, json.dumps([[1.0, 0.0, 0.0]])])
        w.writerow(["IMG_007.jpg", "wedding", "unknown",
                    3, json.dumps([[-0.95, 0.05, 0.0]])])
        # Non-wedding rows for the scene-distribution table
        w.writerow(["IMG_008.jpg", "landscape", "", "", ""])
        w.writerow(["IMG_009.jpg", "unknown",   "", "", ""])
    return out


def _run_cli(scores_csv: Path, *extra_args: str) -> str:
    """Invoke scripts/cli_audit.py with PYTHONPATH=REPO_ROOT so the
    pixcull package imports cleanly."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + ":" + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(CLI), "--scores-csv", str(scores_csv),
         *extra_args],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, (
        f"cli_audit exit={proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    return proc.stdout


def test_cli_emits_markdown_header(synthetic_scores_csv):
    out = _run_cli(synthetic_scores_csv)
    assert out.startswith("# PixCull audit")


def test_cli_emits_scene_section(synthetic_scores_csv):
    out = _run_cli(synthetic_scores_csv)
    assert "## 📷 scene classifier audit" in out
    assert "abstain (scene=unknown)" in out
    assert "| scene | 数量 | 占比 |" in out
    # The fixture has 7 wedding rows / 9 total = 77% — should trip
    # the > 40% over-firing warning
    assert "占比" in out and ("超过 40%" in out or "scene over" in out.lower())


def test_cli_emits_face_audit_section(synthetic_scores_csv):
    out = _run_cli(synthetic_scores_csv)
    assert "## 👤 face library audit" in out
    assert "簇精度" in out
    # cluster 3 has an intruder → should be flagged as polluted
    assert "污染" in out
    # Without --user-root, library + continuity sections are skipped
    assert "skipping library fragmentation" in out


def test_cli_emits_wedding_section_when_wedding_rows_present(
    synthetic_scores_csv,
):
    out = _run_cli(synthetic_scores_csv)
    assert "## 💒 wedding moment coverage" in out
    assert "mandatory moment" in out
    # Default preset is western — first_dance / cake_cutting are
    # missing from the fixture so they should be flagged.
    assert "first_dance" in out
    assert "cake_cutting" in out


def test_cli_chinese_preset_swaps_mandatory_list(synthetic_scores_csv):
    """P-PRO-4.3 — --mandatory-preset chinese should label the report
    "中式" and flag Chinese mandatory misses instead of western."""
    out = _run_cli(synthetic_scores_csv, "--mandatory-preset", "chinese")
    assert "(中式)" in out
    # Chinese mandatory includes tea_ceremony / kneeling_bow — fixture
    # has neither, so they should appear as missing
    assert "tea_ceremony" in out
    assert "kneeling_bow" in out
    # And first_dance / cake_cutting should NOT be flagged as missing
    # under the Chinese preset (they're not on its list)
    missing_block = out.split("⚠ **未覆盖的 mandatory moment:**")[1] \
                    if "⚠ **未覆盖" in out else ""
    if missing_block:
        # Stop at the next section header
        missing_block = missing_block.split("##")[0]
        assert "first_dance" not in missing_block
        assert "cake_cutting" not in missing_block


def test_cli_writes_to_file_when_out_specified(synthetic_scores_csv,
                                                tmp_path):
    target = tmp_path / "report.md"
    out = _run_cli(synthetic_scores_csv, "--out", str(target))
    # When --out is set, stdout should be empty (only stderr "wrote ..."
    # message goes there). The file should exist + be non-trivial.
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "# PixCull audit" in content
    assert len(content) > 200


def test_cli_handles_no_wedding_rows_gracefully(tmp_path):
    """A non-wedding run shouldn't emit a wedding section at all."""
    out = tmp_path / "out" / "scores.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "scene", "face_cluster_id"])
        w.writerow(["IMG_001.jpg", "landscape", ""])
        w.writerow(["IMG_002.jpg", "landscape", ""])
    report = _run_cli(out)
    assert "# PixCull audit" in report
    assert "## 📷 scene classifier audit" in report
    # No wedding rows → no wedding section
    assert "## 💒 wedding moment coverage" not in report


def test_cli_handles_missing_scores_csv(tmp_path):
    """Pointing at a nonexistent CSV should still produce a sensible
    skeleton (each section degrades gracefully)."""
    ghost = tmp_path / "ghost.csv"
    out = _run_cli(ghost)
    # Header still emitted; each section reports the missing file
    assert "# PixCull audit" in out
    assert "no scores.csv" in out or "scores.csv" in out


def test_cli_help_lists_mandatory_preset(synthetic_scores_csv):
    """`--help` should document the mandatory-preset flag added in
    P-PRO-4.3 so users discover it."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + ":" + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0
    assert "--mandatory-preset" in proc.stdout
    assert "chinese" in proc.stdout
    assert "western" in proc.stdout


# -----------------------------------------------------------------
# P-PRO-6 — ICC color-space audit smoke
# -----------------------------------------------------------------

def test_cli_emits_icc_section_when_images_reachable(tmp_path):
    """Build a 2-image mini-album (1× untagged JPG + 1× sRGB-tagged
    JPG via PIL), point cli_audit at it, assert the ICC section
    renders + lists the count by canonical name."""
    from PIL import Image

    img_root = tmp_path / "input"
    img_root.mkdir(parents=True)
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True)
    # Two real JPGs.  Without an ICC blob, PIL writes them as
    # untagged → audit reports "unknown".
    Image.new("RGB", (32, 32), (128, 0, 0)).save(img_root / "a.jpg", "JPEG")
    Image.new("RGB", (32, 32), (0, 0, 128)).save(img_root / "b.jpg", "JPEG")

    scores_csv = out_dir / "scores.csv"
    with scores_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "scene", "path"])
        w.writerow(["a.jpg", "landscape", str(img_root / "a.jpg")])
        w.writerow(["b.jpg", "landscape", str(img_root / "b.jpg")])

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + ":" + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(CLI),
         "--scores-csv", str(scores_csv),
         "--image-root", str(img_root)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "## 🎨 color-space audit" in out
    assert "总 audit 文件数" in out
    assert "主色彩空间" in out


def test_cli_icc_section_handles_no_images_gracefully(synthetic_scores_csv):
    """When scores.csv references files that don't exist on disk
    (synthetic test data), the section should report "no readable
    image files" instead of crashing."""
    out = _run_cli(synthetic_scores_csv)
    assert "## 🎨 color-space audit" in out
    assert "no readable image files" in out


def test_cli_help_lists_image_root(synthetic_scores_csv):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + ":" + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert "--image-root" in proc.stdout
