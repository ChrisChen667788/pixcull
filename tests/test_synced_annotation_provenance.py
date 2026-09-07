"""v3.29 — every producer of annotations.jsonl, and whether it tells the truth.

v3.9 added `source` and taught `personal_learn` to drop the compare
modal's rejected siblings.  That was one producer.  This is the sweep for
the rest, and it found a second one doing the same damage by a different
route.

The sync path wrote the peer's record verbatim, minus one field.  So a
record arriving from another machine carried arbitrary keys, whatever
`source` it liked, and nothing at all saying it had come from somewhere
else — after which `personal_learn` read it as one of this
photographer's own corrections and fitted a taste profile to two people.
"""
import inspect
import json
import tempfile
from pathlib import Path

from pixcull.report.serve_app import sanitise_synced_annotation as clean
from pixcull.scoring.personal_learn import gather_examples_from_runs

REMOTE = {
    "__run_id": "r1",
    "filename": "a.jpg",
    "overall_label": "keep",
    "axes": {},
    "source": "blind",
    "evil": {"anything": "at all"},
    "timestamp": 1.0,
}


def test_unknown_keys_from_a_peer_are_dropped():
    """A remote record is untrusted input and annotations.jsonl is read
    by six different consumers."""
    got = clean(REMOTE)
    assert "evil" not in got and "__run_id" not in got


def test_a_peer_cannot_choose_its_own_provenance():
    """`blind` is a TRUSTED provenance for the personalisation gate. This
    machine cannot verify another machine's blind-labelling protocol, so
    the claim does not survive the wire."""
    assert clean(REMOTE)["source"] == "human"


def test_a_known_provenance_survives():
    assert clean({**REMOTE, "source": "lr_round_trip"})["source"] == "lr_round_trip"


def test_every_synced_record_is_marked_as_synced():
    assert clean(REMOTE)["synced"] is True


def test_a_peer_cannot_unmark_itself():
    assert clean({**REMOTE, "synced": False})["synced"] is True


def test_the_real_content_still_arrives():
    got = clean(REMOTE)
    assert got["filename"] == "a.jpg" and got["overall_label"] == "keep"


# -- the consequence --------------------------------------------------

def _run(tmp: Path, records):
    out = tmp / "shoot" / "output"
    out.mkdir(parents=True)
    (out / "scores.csv").write_text(
        "filename,scene,rubric_technical_stars,rubric_subject_stars,"
        "rubric_composition_stars,rubric_light_stars,rubric_moment_stars,"
        "rubric_aesthetic_stars\n"
        + "".join(f"{r['filename']},wedding,4,4,4,4,4,4\n" for r in records),
        encoding="utf-8")
    (out / "annotations.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8")
    return tmp


def test_a_second_shooters_correction_is_not_learned_as_your_taste():
    """It is a real human correction. It is not THIS photographer's, and
    personal_learn exists to learn one person's taste."""
    with tempfile.TemporaryDirectory() as d:
        root = _run(Path(d), [
            {"filename": "mine.jpg", "overall_label": "keep",
             "source": "human"},
            {"filename": "theirs.jpg", "overall_label": "cull",
             "source": "human", "synced": True},
        ])
        got = gather_examples_from_runs(root)
        assert len(got) == 1
        assert got[0].decision == "keep"


def test_a_later_synced_record_removes_an_earlier_local_label():
    """Latest-wins on this file. A synced record arriving after a local
    one must not leave the local label standing as if nothing happened —
    the frame's newest statement came from elsewhere."""
    with tempfile.TemporaryDirectory() as d:
        root = _run(Path(d), [
            {"filename": "a.jpg", "overall_label": "keep", "source": "human"},
            {"filename": "a.jpg", "overall_label": "cull",
             "source": "human", "synced": True},
        ])
        assert gather_examples_from_runs(root) == []


def test_the_sync_handler_actually_sanitises():
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app)
    assert "sanitise_synced_annotation(rec)" in src
    # And the old verbatim write is gone.
    assert 'k != "__run_id"' not in src
