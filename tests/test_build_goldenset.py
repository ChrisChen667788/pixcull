"""Tests for scripts/build_goldenset.py.

We test the pure merging + label normalisation paths.  The actual disk
scan is exercised end-to-end via a tmpdir fixture.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


def _load():
    p = Path(__file__).resolve().parent.parent / "scripts" / "build_goldenset.py"
    spec = importlib.util.spec_from_file_location("build_goldenset", p)
    mod = importlib.util.module_from_spec(spec)
    # @dataclass needs the module registered before exec to resolve __module__
    sys.modules["build_goldenset"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# label normalisation
# ---------------------------------------------------------------------------


def test_normalise_canonical():
    g = _load()
    assert g._normalise_label("keep") == "keep"
    assert g._normalise_label("MAYBE") == "maybe"
    assert g._normalise_label("  cull  ") == "cull"


def test_normalise_aliases_yes_no():
    g = _load()
    assert g._normalise_label("yes") == "keep"
    assert g._normalise_label("y") == "keep"
    assert g._normalise_label("no") == "cull"
    assert g._normalise_label("0") == "cull"


def test_normalise_garbage():
    g = _load()
    assert g._normalise_label("") == ""
    assert g._normalise_label(None) == ""
    assert g._normalise_label("definitely") == ""


# ---------------------------------------------------------------------------
# scene / vertical fill
# ---------------------------------------------------------------------------


def test_pick_vertical_fills_blanks_both_ways():
    g = _load()
    assert g._pick_vertical("wedding", "") == ("wedding", "wedding")
    assert g._pick_vertical("", "portrait") == ("portrait", "portrait")
    # Both set — leave alone
    assert g._pick_vertical("event", "wedding") == ("event", "wedding")


# ---------------------------------------------------------------------------
# merge — priority + within-source dedup
# ---------------------------------------------------------------------------


def test_merge_higher_priority_wins():
    g = _load()
    hi = [g.Row(filename="a.jpg", manual_label="keep",
                source="gt:x", updated_at_ms=100)]
    lo = [g.Row(filename="a.jpg", manual_label="cull",
                source="ann:y", updated_at_ms=999)]
    out = g._merge_rows(hi, lo)
    assert len(out) == 1
    assert out[0].manual_label == "keep"  # higher-priority gt wins


def test_merge_within_source_latest_wins():
    g = _load()
    rows = [
        g.Row(filename="a.jpg", manual_label="keep",
              source="ann:1", updated_at_ms=100),
        g.Row(filename="a.jpg", manual_label="cull",
              source="ann:1", updated_at_ms=200),
    ]
    out = g._merge_rows(rows)
    assert len(out) == 1
    assert out[0].manual_label == "cull"  # latest within source


def test_merge_different_filenames_kept():
    g = _load()
    out = g._merge_rows([
        g.Row(filename="a.jpg", manual_label="keep"),
        g.Row(filename="b.jpg", manual_label="cull"),
    ])
    assert {r.filename for r in out} == {"a.jpg", "b.jpg"}


# ---------------------------------------------------------------------------
# end-to-end on a tmp directory
# ---------------------------------------------------------------------------


def test_scan_ground_truth_csv(tmp_path):
    g = _load()
    set_dir = tmp_path / "wedding"
    set_dir.mkdir()
    gt_path = set_dir / "ground_truth.csv"
    gt_path.write_text(
        "filename,manual_label,scene\n"
        "img1.jpg,keep,wedding\n"
        "img2.jpg,cull,wedding\n",
        encoding="utf-8",
    )
    rows = list(g._scan_ground_truth_csvs(tmp_path))
    assert len(rows) == 2
    assert {r.manual_label for r in rows} == {"keep", "cull"}
    assert all(r.vertical == "wedding" for r in rows)  # filled from scene


def test_scan_annotations_jsonl(tmp_path):
    g = _load()
    # Mimic the per-user run dir layout
    run = tmp_path / "abcdef0123"
    run.mkdir()
    ann = run / "annotations.jsonl"
    ann.write_text(
        json.dumps({"filename": "p1.jpg", "decision": "keep",
                    "timestamp": 1.0, "scene": "portrait"})
        + "\n"
        + json.dumps({"filename": "p1.jpg", "decision": "cull",
                      "timestamp": 2.0})  # later → wins
        + "\n",
        encoding="utf-8",
    )
    rows = list(g._scan_annotations(tmp_path))
    assert len(rows) == 1
    assert rows[0].manual_label == "cull"
    assert rows[0].updated_at_ms == 2000


def test_scan_in_app_corrections(tmp_path):
    g = _load()
    run = tmp_path / "0123456789"
    run.mkdir()
    df = pd.DataFrame([
        {"filename": "x.jpg", "rubric_human_labeled": True,
         "decision": "keep", "scene": "event"},
        {"filename": "y.jpg", "rubric_human_labeled": False,
         "decision": "cull"},  # ignored
    ])
    df.to_csv(run / "scores.csv", index=False)
    rows = list(g._scan_in_app_corrections(tmp_path))
    assert len(rows) == 1
    assert rows[0].filename == "x.jpg"
    assert rows[0].vertical == "event"


def test_e2e_main_writes_csv(tmp_path, capsys):
    g = _load()
    we_root = tmp_path / "wedding_eval"
    we_root.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (we_root / "ground_truth.csv").write_text(
        "filename,manual_label,vertical\nimg1.jpg,keep,wedding\n",
        encoding="utf-8",
    )
    out = tmp_path / "goldenset.csv"
    rc = g.main([
        "--wedding-eval", str(we_root),
        "--runs-root", str(runs_root),
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    df = pd.read_csv(out)
    assert len(df) == 1
    assert df.iloc[0]["manual_label"] == "keep"


def test_e2e_main_no_sources_returns_2(tmp_path, capsys):
    g = _load()
    rc = g.main([
        "--wedding-eval", str(tmp_path / "absent"),
        "--runs-root",    str(tmp_path / "absent2"),
        "--out",          str(tmp_path / "x.csv"),
    ])
    assert rc == 2
