"""v3.43 — two of the style guide's three rule types had never fired.

P2.3 shipped a YAML rule layer for studios with an explicit house
standard: "all delivered shots must be 3:2 or 16:9", "no portraits where
the model is off-centre". Three rule types. `dominant_color` worked.

The other two read `img_width` / `img_height`, and nothing in the
pipeline has ever written them — grep the package and the only hits were
the two readers. A rule whose field is missing returns None, and None
means "no violation", so a studio's aspect rule came back satisfied on
every frame including the ones that broke it. The comment on the line
said "analyze_one doesn't emit those today; V32 candidate", which reads
as "skips on some rows" and meant "has never fired once".

`face_center` needed a second fix. It was written to read `face_bboxes`
off the row, and the clustering pass drops that key from every row
before the DataFrame is built, so it had nothing to read even once the
width existed. The worker now derives the offset where the boxes and the
width are both in hand.
"""
import pytest

from pixcull.scoring.style_guide import apply_style_guide

ASPECT_RULE = {
    "id": "aspect_ratio",
    "require_aspect": ["3:2", "16:9"],
    "on_violation": "cull",
    "why": "deliverables must be 3:2 or 16:9",
}
FACE_RULE = {
    "id": "face_center",
    "max_horizontal_offset": 0.15,
    "on_violation": "advisory",
    "why": "face off-center by > 15%",
}


def _guide(*rules):
    return {"schema": "pixcull.style_guide.v1", "name": "t", "rules": list(rules)}


def test_the_aspect_rule_fires_on_a_frame_that_breaks_it():
    """4:3 against a 3:2-or-16:9 house standard."""
    row = {"filename": "a.jpg", "decision": "keep",
           "img_width": 2048, "img_height": 1536}
    res = apply_style_guide(row, _guide(ASPECT_RULE))
    assert res["violations"], "a 4:3 frame passed a 3:2/16:9 rule"
    assert "aspect" in res["violations"][0]["detail"]


def test_the_aspect_rule_stays_quiet_on_a_frame_that_meets_it():
    """The thumbnail step makes 6000x4000 into 2048x1365 — 1.5004, not
    1.5 — so the rule has to keep its own tolerance."""
    for w, h in ((2048, 1365), (2048, 1152), (1365, 2048)):
        row = {"filename": "a.jpg", "decision": "keep",
               "img_width": w, "img_height": h}
        assert not apply_style_guide(row, _guide(ASPECT_RULE))["violations"], \
            f"{w}x{h} was reported as violating 3:2/16:9"


def test_the_aspect_rule_reads_the_strings_a_csv_row_carries():
    """The admin endpoint rebuilds rows from scores.csv, where every
    value is text. A rule that only works on ints works on nothing."""
    row = {"filename": "a.jpg", "decision": "keep",
           "img_width": "2048", "img_height": "1536"}
    assert apply_style_guide(row, _guide(ASPECT_RULE))["violations"]


def test_the_face_rule_fires_on_the_derived_offset():
    row = {"filename": "a.jpg", "decision": "keep",
           "img_width": 2048, "img_height": 1365,
           "face_max_center_offset": 0.30}
    res = apply_style_guide(row, _guide(FACE_RULE))
    assert res["violations"]
    assert "30%" in res["violations"][0]["detail"]


def test_the_face_rule_stays_quiet_inside_the_allowance():
    row = {"filename": "a.jpg", "decision": "keep",
           "img_width": 2048, "img_height": 1365,
           "face_max_center_offset": 0.10}
    assert not apply_style_guide(row, _guide(FACE_RULE))["violations"]


def test_a_row_with_no_face_is_not_a_violation():
    """Absence of a face is not an off-centre face. This is the
    distinction the whole version is about: a missing field must not be
    read as either a pass or a fail."""
    row = {"filename": "a.jpg", "decision": "keep",
           "img_width": 2048, "img_height": 1365}
    assert not apply_style_guide(row, _guide(FACE_RULE))["violations"]


def test_the_bbox_path_still_works_for_a_caller_holding_live_boxes():
    row = {"filename": "a.jpg", "decision": "keep", "img_width": 1000,
           "img_height": 667, "face_bboxes": [[800, 100, 900, 200]]}
    res = apply_style_guide(row, _guide(FACE_RULE))
    assert res["violations"], "bbox at x=850 of a 1000px frame is 35% off"


def test_the_pipeline_actually_emits_the_fields():
    """The half that made this a bug rather than a rule nobody wrote.

    Asserted against the worker's source rather than a run, because a
    run needs models; `tests/test_tether_drift.py` checks the same names
    against a real finished run's header.
    """
    import inspect

    from pixcull.pipeline import worker
    src = inspect.getsource(worker.analyze_one)
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    for name in ("img_width", "img_height", "face_max_center_offset"):
        assert f'metrics["{name}"]' in body or f'"{name}"' in body, name


def test_the_columns_are_in_the_finished_schema():
    from pixcull import tether_drift as TD
    cols = TD.finished_columns()
    for name in ("img_width", "img_height"):
        assert name in cols, f"{name} is not in the finished-run snapshot"
