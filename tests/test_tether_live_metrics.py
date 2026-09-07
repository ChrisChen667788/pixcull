"""v3.30 — five of the seventeen gaps, carried into the live path.

v3.24 ruled on all 63 columns the finished path has and the live path
does not, and named 17 as gaps.  The shape of that list was the finding:
almost every one is exposure or the face — the two things a tethered
photographer is actually watching for, and the two the live path was
silent about.

The reason turned out to be smaller than the gap.  `_analyze_one_file`
returned a hand-written seven-key dict written in P2.2, and every metric
added to the pipeline since has been discarded on that one line.  The
numbers were computed and thrown away.
"""
import csv
import inspect
import tempfile
from pathlib import Path

from pixcull import tether, tether_drift as TD


def test_the_carried_set_is_five_not_seventeen():
    """The disposition file says a table is not glanceable during a
    shoot, and it is right. This version takes what changes the next
    frame, not what closes the list."""
    assert len(tether._LIVE_METRICS) == 5
    assert TD.report()["by_disposition"]["gap"] == 12


def test_it_carries_what_changes_the_next_frame():
    for m in ("highlight_clip_pct", "horizon_tilt_deg", "face_max_blink"):
        assert m in tether._LIVE_METRICS


def test_the_live_schema_and_the_writer_still_agree():
    """v3.24's gate. Widening one and not the other is how the two
    statements of this schema drifted in the first place."""
    src = inspect.getsource(tether.TetherSession._append_row)
    start = src.index("cols = [")
    block = src[start:src.index("]", start)]
    written = {x.strip().strip('"') for x in
               block[len("cols = ["):].replace("\n", "").split(",")
               if x.strip()}
    assert written == set(TD.TETHER_COLUMNS)


def test_a_metric_the_analyser_did_not_produce_is_absent_not_invented():
    """`horizon_tilt_deg` and `face_max_blink` are conditional upstream —
    a frame with no horizon and no face has neither. Writing 0 for them
    would say "level" and "eyes open" about a photograph nobody measured.
    """
    code = _code_only(tether.TetherSession._analyze_one_file)
    assert "if key in row:" in code
    assert ".get(key, 0)" not in code


def _code_only(fn) -> str:
    """Source with docstrings and comments removed.

    The fourth time in these two blocks that a guard was satisfied by the
    explanation instead of the code. The comment below the fix says why
    `**row` is wrong, at length, and a substring search was happy to find
    the sentence.
    """
    import ast
    tree = ast.parse(inspect.getsource(fn).lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            node.value.value = ""
    return ast.unparse(tree)


def test_it_copies_named_keys_rather_than_splatting_the_row():
    """`**row` would put seventy columns behind a glance."""
    code = _code_only(tether.TetherSession._analyze_one_file)
    assert "**row" not in code
    assert "for key in _LIVE_METRICS:" in code


def test_a_row_carrying_the_metrics_reaches_the_csv():
    """End-to-end through the writer, with a synthetic analyser result —
    the poll loop and the detectors are not what is under test here."""
    with tempfile.TemporaryDirectory() as d:
        s = tether.TetherSession(Path(d), session_id="t")
        s._append_row({
            "filename": "a.jpg", "path": "a.jpg", "scene": "portrait",
            "decision": "keep", "score_final": 0.8, "flags": [],
            "reason": "", "highlight_clip_pct": 2.5,
            "shadow_clip_pct": 0.1, "horizon_tilt_deg": 3.2,
            "face_count": 2.0, "face_max_blink": 0.9,
        })
        rows = list(csv.DictReader(
            (s._output_dir() / "scores.csv").open(encoding="utf-8")))
        assert rows[0]["face_max_blink"] == "0.9"
        assert rows[0]["highlight_clip_pct"] == "2.5"
        assert rows[0]["horizon_tilt_deg"] == "3.2"
