"""v3.0 — the client's choice, kept out of the photographer's judgement.

Two people, two questions. `overall_label` answers "is this frame good
enough to deliver". A client pick answers "do I want this one". They
disagree constantly and that is normal: a slightly soft frame where the
grandmother is laughing gets picked every time.

Most of this file is about the ways those two could contaminate each
other, because each one is silent and each one is expensive:

  the annotation index is LATEST-WINS on the whole record, so one line
  of the client's opinion appended to annotations.jsonl erases the
  photographer's verdict from every reader of it

  the personalisation profile would learn the client's taste as the
  photographer's

  ground truth would stop being an independent judgement of the same
  question, which is the one property v2.88 exists to protect
"""
import json
from pathlib import Path

import pytest

from pixcull import client_picks as cp


# ------------------------------------------------------- the separation


def test_picks_never_touch_the_annotation_file(tmp_path):
    """The hazard that decided the design. `_read_human_by_fn_cached`
    does `out[fn] = rec` — later wins, whole record — so a pick appended
    to annotations.jsonl with an empty overall_label would wipe the
    photographer's own label out of the UI."""
    ann = tmp_path / "annotations.jsonl"
    ann.write_text(json.dumps({
        "filename": "a.jpg", "overall_label": "cull",
        "source": "human", "timestamp": 1.0}) + "\n", encoding="utf-8")
    before = ann.read_bytes()
    cp.record(tmp_path, ["a.jpg"], source="wechat-reply")
    assert ann.read_bytes() == before, \
        "recording a client pick modified annotations.jsonl"
    assert cp.path_for(tmp_path).name != "annotations.jsonl"


def test_the_photographers_verdict_survives_a_client_pick(tmp_path):
    """The end-to-end version of the same thing, through the real reader."""
    from pixcull.report.serve_app import _read_human_by_fn_cached
    ann = tmp_path / "annotations.jsonl"
    ann.write_text(json.dumps({
        "filename": "a.jpg", "overall_label": "cull",
        "source": "human", "timestamp": 1.0}) + "\n", encoding="utf-8")
    cp.record(tmp_path, ["a.jpg"], source="wechat-reply")
    idx = _read_human_by_fn_cached(ann)
    assert idx["a.jpg"]["overall_label"] == "cull"


def test_a_pick_is_not_ground_truth(tmp_path):
    """v2.88 refuses to measure accuracy against anything but an
    independent human judgement of the SAME question. A client answering
    a different question must not qualify."""
    from pixcull.scoring.ground_truth import audit_labels, label_provenance
    cp.record(tmp_path, ["a.jpg", "b.jpg"], source="wechat-reply")
    inv = audit_labels([cp.path_for(tmp_path)])
    assert inv.human == 0, "client picks counted as human ground truth"
    assert inv.usable_for_accuracy is False
    rec = json.loads(cp.path_for(tmp_path).read_text(encoding="utf-8")
                     .splitlines()[0])
    assert "overall_label" not in rec and "decision" not in rec
    assert label_provenance(rec) != "human"


def test_a_pick_is_not_a_correction_for_personalisation(tmp_path):
    """`gather_examples_from_runs` walks annotations.jsonl. The pick file
    is not that file, and its records carry no label for the gatherer to
    read even if it ever did."""
    from pixcull.scoring.personal_learn import gather_examples_from_runs
    run = tmp_path / "run" / "output"
    run.mkdir(parents=True)
    cp.record(run, ["a.jpg", "b.jpg"], source="wechat-reply")
    assert gather_examples_from_runs(tmp_path) == []


# ------------------------------------------------------------- the file


def test_a_run_with_no_picks_is_not_an_error(tmp_path):
    assert cp.load(tmp_path) == {}
    assert cp.picked_filenames(tmp_path) == set()
    assert cp.summary(tmp_path)["n_picked"] == 0


def test_a_client_can_change_their_mind(tmp_path):
    """Append-only, latest wins. An un-pick must actually un-pick, and
    the earlier line stays as history."""
    cp.record(tmp_path, ["a.jpg", "b.jpg"], source="wechat-reply")
    cp.record(tmp_path, ["b.jpg"], source="on-site", picked=False)
    assert cp.picked_filenames(tmp_path) == {"a.jpg"}
    assert cp.summary(tmp_path)["n_seen"] == 2
    lines = cp.path_for(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3, "history was rewritten instead of appended"


def test_where_a_pick_came_from_is_recorded(tmp_path):
    """A pick made on-site with the client pointing and one parsed out of
    a WeChat reply are different evidence."""
    cp.record(tmp_path, ["a.jpg"], source="on-site")
    cp.record(tmp_path, ["b.jpg"], source="wechat-reply")
    assert cp.summary(tmp_path)["sources"] == {"on-site": 1, "wechat-reply": 1}


def test_a_corrupt_line_does_not_lose_the_rest(tmp_path):
    p = cp.path_for(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cp.record(tmp_path, ["a.jpg"], source="on-site")
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    cp.record(tmp_path, ["b.jpg"], source="on-site")
    assert cp.picked_filenames(tmp_path) == {"a.jpg", "b.jpg"}


def test_blank_filenames_are_skipped(tmp_path):
    assert cp.record(tmp_path, ["", "  ", None, "a.jpg"], source="x") == 1


# ------------------------------------------------------ the round trip


def test_the_manifest_carries_the_run_it_came_from(tmp_path):
    """The reply arrives days later with nothing in it but numbers. If
    the export did not write down which run it came from, there is
    nowhere for the picks to go."""
    from PIL import Image
    from pixcull.export.proof_sheet import write_proof_sheet
    src = tmp_path / "s.jpg"
    Image.new("RGB", (900, 600), (100, 120, 140)).save(src, "JPEG")
    out = tmp_path / "proof"
    write_proof_sheet(
        [{"filename": "a.jpg", "decision": "keep", "orig_filename": "a.jpg"}],
        out, resolve=lambda _f: src, title="T",
        run_output=str(tmp_path / "run"))
    man = json.loads((out / "picks_manifest.json").read_text(encoding="utf-8"))
    assert man["run_output"] == str(tmp_path / "run")


def test_an_old_manifest_without_a_run_still_parses(tmp_path):
    """Proof folders exported before v3.0 have no run_output. They must
    still work for reading the numbers back, just without writing."""
    man = {"schema": "pixcull.proof_manifest/v1", "n": 2,
           "by_index": {"1": "a.jpg", "2": "b.jpg"}, "labels": {}}
    assert man.get("run_output", "") == ""
