"""v3.9 — the compare gesture's answer, kept as a comparison.

The charter said the compare modal had no "prefer this side" gesture.
It does, and it has since v0.7 — the 选最佳 button at results.js:7538.
What it did with the answer was the problem: N pointwise labels, keep for
the winner and cull for every sibling, and nothing recording that a
comparison happened.

That loses the pair, and it actively breaks something. A burst sibling
rejected in compare is not a photograph the photographer disliked; it is
one that lost to a near-identical frame, so its axis stars are nearly the
winner's. Averaged into `personal_learn`'s cull bucket it flattens the
keep-minus-cull gap that `axis_weights` is built from. Every use of the
gesture made the taste profile slightly worse and nothing said so.
"""
import json
import tempfile
from pathlib import Path

from pixcull.scoring import pairwise as P
from pixcull.scoring.personal_learn import gather_examples_from_runs


def test_a_comparison_of_seven_frames_is_six_pairs_not_one():
    """Counting it as one undercounts the signal by the size of the
    burst, which is exactly the data this is collected for."""
    recs = [{"winner": "a.jpg", "losers": [f"b{i}.jpg" for i in range(6)]}]
    assert len(P.pairs(recs)) == 6


def test_pairs_are_deduplicated_across_repeated_comparisons():
    recs = [{"winner": "a.jpg", "losers": ["b.jpg", "c.jpg"]},
            {"winner": "a.jpg", "losers": ["b.jpg"]}]
    assert P.pairs(recs) == [("a.jpg", "b.jpg"), ("a.jpg", "c.jpg")]


def test_a_preference_over_nothing_is_not_stored_as_a_preference():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / P.FILENAME
        path.write_text(json.dumps(
            {"schema": P.SCHEMA, "winner": "a.jpg", "losers": []}) + "\n",
            encoding="utf-8")
        assert P.load(d) == []


def test_a_torn_final_line_does_not_lose_the_preferences_before_it():
    with tempfile.TemporaryDirectory() as d:
        P.record(d, winner="a.jpg", losers=["b.jpg"])
        with open(Path(d) / P.FILENAME, "a", encoding="utf-8") as fh:
            fh.write('{"schema": "pixcull.pair')     # killed mid-write
        assert len(P.load(d)) == 1


def test_records_from_another_schema_are_ignored():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / P.FILENAME
        path.write_text(json.dumps(
            {"schema": "something.else/v1", "winner": "a", "losers": ["b"]})
            + "\n", encoding="utf-8")
        assert P.load(d) == []


def test_round_trip_and_summary():
    with tempfile.TemporaryDirectory() as d:
        P.record(d, winner="a.jpg", losers=["b.jpg", "c.jpg"], cluster="c7")
        P.record(d, winner="d.jpg", losers=["e.jpg"], cluster="c9")
        s = P.summary(d)
        assert s == {"comparisons": 2, "pairs": 3, "frames_preferred": 2}


def test_the_winner_is_never_listed_among_its_own_losers():
    with tempfile.TemporaryDirectory() as d:
        rec = P.record(d, winner="a.jpg", losers=["a.jpg", "b.jpg"])
        assert rec["losers"] == ["b.jpg"]


# -- the label-pollution fix -----------------------------------------

def _run_with(tmp: Path, annotations: list[dict]) -> Path:
    out = tmp / "shoot" / "output"
    out.mkdir(parents=True)
    (out / "scores.csv").write_text(
        "filename,scene,rubric_technical_stars,rubric_subject_stars,"
        "rubric_composition_stars,rubric_light_stars,rubric_moment_stars,"
        "rubric_aesthetic_stars\n"
        + "".join(f"{a['filename']},wedding,4,4,4,4,4,4\n"
                  for a in annotations),
        encoding="utf-8")
    (out / "annotations.jsonl").write_text(
        "".join(json.dumps(a, ensure_ascii=False) + "\n"
                for a in annotations), encoding="utf-8")
    return tmp


def test_a_sibling_rejected_in_compare_stays_out_of_the_taste_profile():
    """It is not a disliked photograph. Its axis stars are the winner's."""
    with tempfile.TemporaryDirectory() as d:
        root = _run_with(Path(d), [
            {"filename": "a.jpg", "overall_label": "keep",
             "source": "compare_winner"},
            {"filename": "b.jpg", "overall_label": "cull",
             "source": "compare_rejected"},
            {"filename": "c.jpg", "overall_label": "cull",
             "source": "human"},
        ])
        got = {e.decision for e in gather_examples_from_runs(root)}
        names = gather_examples_from_runs(root)
        assert len(names) == 2, "the rejected sibling must not be an example"
        assert got == {"keep", "cull"}


def test_a_real_human_cull_is_still_learned_from():
    with tempfile.TemporaryDirectory() as d:
        root = _run_with(Path(d), [
            {"filename": "c.jpg", "overall_label": "cull", "source": "human"},
        ])
        assert len(gather_examples_from_runs(root)) == 1


def test_a_later_compare_rejection_removes_an_earlier_label():
    """Latest line wins in this file. If a frame was labelled by hand and
    then rejected in a compare, the compare is the newer statement and
    the older pointwise label must not survive it."""
    with tempfile.TemporaryDirectory() as d:
        root = _run_with(Path(d), [
            {"filename": "b.jpg", "overall_label": "keep", "source": "human"},
            {"filename": "b.jpg", "overall_label": "cull",
             "source": "compare_rejected"},
        ])
        assert gather_examples_from_runs(root) == []


# -- provenance cannot be invented -----------------------------------

def test_an_unknown_source_falls_back_to_human():
    from pixcull.report.serve_app import _annotation_source
    assert _annotation_source("compare_rejected") == "compare_rejected"
    assert _annotation_source("trust_me") == "human"
    assert _annotation_source(None) == "human"
    assert _annotation_source("") == "human"


# -- reachability -----------------------------------------------------

def test_the_compare_gesture_posts_the_pair_and_marks_the_labels():
    src = (Path(__file__).resolve().parent.parent / "pixcull" / "report"
           / "templates" / "src" / "results.js").read_text(encoding="utf-8")
    assert "await fetch(`/pairwise/${run_id}`" in src
    assert '"compare_winner" : "compare_rejected"' in src


def test_the_endpoint_is_routed():
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app)
    assert 'path.startswith("/pairwise/")' in src
