"""v2.14-P0-2 — make_label_sheet.py: scores.csv → fill-in labeling CSV."""

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_label_sheet.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("make_label_sheet", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["make_label_sheet"] = m
    spec.loader.exec_module(m)
    return m


def _write_scores(tmp_path, rows):
    p = tmp_path / "scores.csv"
    cols = ["filename", "scene", "decision", "score_final",
            "rubric_technical_stars", "rubric_moment_stars"]
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return p


def test_uncertain_first_order_and_columns(tmp_path, mod):
    p = _write_scores(tmp_path, [
        {"filename": "a.jpg", "scene": "landscape", "decision": "keep",
         "score_final": "0.92", "rubric_technical_stars": "4.8", "rubric_moment_stars": "3.0"},
        {"filename": "b.jpg", "scene": "portrait", "decision": "maybe",
         "score_final": "0.52", "rubric_technical_stars": "3.1", "rubric_moment_stars": "2.0"},
        {"filename": "c.jpg", "scene": "wildlife", "decision": "cull",
         "score_final": "0.20", "rubric_technical_stars": "1.5", "rubric_moment_stars": "1.0"},
    ])
    rows = mod.build_rows(p, "uncertain")
    # closest-to-0.5 first: b (0.52) → c (0.20, d=0.30) → a (0.92, d=0.42)
    assert [r["filename"] for r in rows] == ["b.jpg", "c.jpg", "a.jpg"]
    r0 = rows[0]
    assert r0["manual_label"] == ""          # empty for the user to fill
    assert r0["model_decision"] == "maybe"
    assert r0["technical★"] == 3.1
    assert "notes" in r0


def test_missing_score_sorts_last(tmp_path, mod):
    p = _write_scores(tmp_path, [
        {"filename": "has.jpg", "scene": "x", "decision": "maybe",
         "score_final": "0.5", "rubric_technical_stars": "3", "rubric_moment_stars": "3"},
        {"filename": "none.jpg", "scene": "x", "decision": "",
         "score_final": "", "rubric_technical_stars": "", "rubric_moment_stars": ""},
    ])
    rows = mod.build_rows(p, "uncertain")
    assert rows[0]["filename"] == "has.jpg"
    assert rows[-1]["filename"] == "none.jpg"   # no score → last
    assert rows[-1]["score_final"] == ""        # blank, not a crash


def test_end_to_end_writes_fillable_csv(tmp_path, mod):
    p = _write_scores(tmp_path, [
        {"filename": "a.jpg", "scene": "landscape", "decision": "keep",
         "score_final": "0.8", "rubric_technical_stars": "4", "rubric_moment_stars": "3"},
    ])
    out = tmp_path / "sheet.csv"
    mod.main([str(p), "-o", str(out)])
    with open(out, encoding="utf-8-sig") as fh:
        got = list(csv.DictReader(fh))
    assert got[0]["filename"] == "a.jpg"
    assert got[0]["manual_label"] == ""
    assert "moment★" in got[0]
