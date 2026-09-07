"""v3.24 — every column the live path lacks has been ruled on, once.

`tether.py` dates from P2.2.  Everything the last forty versions added to
the finished pipeline went into the finished path and stopped there: the
live path writes ten columns, the finished path writes seventy-three.

It is NOT obvious the live path should carry all of them — a four-sentence
critique between shutter releases would be worse, not better.  What is
obvious is that nobody decided.  So the deliverable is the decision, and
this gate is what keeps it a decision instead of an accumulation.
"""
import csv
import inspect
from pathlib import Path

from pixcull import tether, tether_drift as TD


def test_nothing_in_the_finished_path_is_undecided():
    """The gate. A column added to the pipeline without a disposition
    widens the gap silently; here it fails a test instead, at the moment
    somebody still knows why they added it."""
    assert TD.undecided() == [], (
        "these finished-run columns have no disposition in "
        "tether_drift.DISPOSITIONS: " + ", ".join(TD.undecided())
    )


def test_the_declared_live_schema_matches_what_tether_actually_writes():
    """Two statements of one schema is the drift this file exists to
    catch, so they are checked against each other."""
    src = inspect.getsource(tether.TetherSession._append_row)
    start = src.index("cols = [")
    block = src[start:src.index("]", start)]
    written = tuple(x.strip().strip('"') for x in
                    block[len("cols = ["):].replace("\n", "").split(",")
                    if x.strip())
    assert set(written) == set(TD.TETHER_COLUMNS)


def test_the_snapshot_is_a_real_run_not_a_wish_list():
    cols = TD.finished_columns()
    assert len(cols) > 50
    for essential in ("filename", "decision", "score_final", "scene"):
        assert essential in cols


def test_every_disposition_is_one_of_the_three_kinds():
    kinds = {"deliberate", "impossible", "gap"}
    for col, (kind, why) in TD.DISPOSITIONS.items():
        assert kind in kinds, f"{col}: {kind}"
        assert why.strip(), f"{col}: no reason given"
    for prefix, kind, why in TD.FAMILY_DISPOSITIONS:
        assert kind in kinds and why.strip()


def test_the_gaps_are_named_rather_than_counted():
    """"11 things are missing" is a number. "eyes-open is the live
    question and it is absent" is work."""
    gaps = TD.gaps()
    assert gaps
    assert all(why.strip() for _, why in gaps)


def test_the_eyes_open_signals_are_recorded_as_gaps_not_as_deliberate():
    """A tethered portrait session is watching for blinks. Calling that
    a deliberate omission would be the file lying to the next reader."""
    for col in ("face_count", "face_max_blink", "face_region_lap_var"):
        assert TD.disposition_for(col)[0] == "gap"


def test_whole_shoot_passes_are_impossible_not_gaps():
    """Ranking a burst that is still arriving is not work anyone can do."""
    for col in ("cluster_id", "peak_rank", "gps_cluster_id"):
        assert TD.disposition_for(col)[0] == "impossible"


def test_a_family_prefix_covers_its_members():
    assert TD.disposition_for("rubric_technical_stars")[0] == "deliberate"
    assert TD.disposition_for("vlm_overall_label")[0] == "impossible"


def test_an_unknown_column_has_no_disposition():
    """Otherwise the gate would pass by matching everything."""
    assert TD.disposition_for("a_column_nobody_added") is None


def test_the_report_adds_up():
    r = TD.report()
    live = set(TD.TETHER_COLUMNS)
    missing = [c for c in TD.finished_columns() if c not in live]
    assert sum(r["by_disposition"].values()) == len(missing)
