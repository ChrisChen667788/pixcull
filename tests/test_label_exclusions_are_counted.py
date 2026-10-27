"""v3.96 — what the taste profile leaves out has to be countable.

v3.9 and v3.29 taught `personal_learn` to leave two kinds of correction out
of one photographer's taste: burst siblings rejected in the compare modal,
and corrections synced from another photographer. Both rules dropped the
record and said nothing, so the v3.29 charter's own measurement —
`evaluate()` with and without those rows — could not be run, and nobody
could say how many there had ever been.

Measured once the rows could be counted (scripts/measure_label_provenance.py,
2026-10-28): neither kind occurs in any label set on the owner's machine,
and the published 0.801 vs 0.799 reproduces exactly from the 608-row sheet.
That sheet is 408 rows endorsed with the verdict on screen, where
personalisation scores below generic however the folds are drawn, and 200
rows with real disagreements, where it scores above.
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from pixcull.scoring.personal_learn import (
    AXES, Example, evaluate, excluded_reason, gather_examples_from_runs,
    load_corrections,
)

ROOT = Path(__file__).resolve().parents[1]
STARS = ",".join(f"rubric_{a}_stars" for a in AXES)


def _run(tmp: Path, records, stars="4,4,4,4,4,4"):
    out = tmp / "shoot" / "output"
    out.mkdir(parents=True)
    names = dict.fromkeys(r["filename"] for r in records)
    (out / "scores.csv").write_text(
        f"filename,scene,{STARS}\n" + "".join(f"{n},wedding,{stars}\n" for n in names),
        encoding="utf-8")
    (out / "annotations.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return tmp


RECORDS = [
    {"filename": "mine.jpg", "overall_label": "keep", "source": "human"},
    {"filename": "lost.jpg", "overall_label": "cull", "source": "compare_rejected"},
    {"filename": "theirs.jpg", "overall_label": "cull", "source": "human",
     "synced": True},
]


def test_the_rule_names_both_kinds_and_nothing_else():
    assert excluded_reason({"source": "compare_rejected"}) == "compare_rejected"
    assert excluded_reason({"source": "human", "synced": True}) == "synced"
    for rec in ({"source": "human"}, {"source": "compare_winner"},
                {"source": "lr_round_trip"}, {}):
        assert excluded_reason(rec) is None, rec


def test_what_is_left_out_is_counted_and_adds_up(tmp_path):
    root = _run(tmp_path, RECORDS)
    left_out: Counter = Counter()
    without = gather_examples_from_runs(root, excluded=left_out)
    with_ = gather_examples_from_runs(root, include_excluded=True)
    assert [e.decision for e in without] == ["keep"]
    assert left_out == {"compare_rejected": 1, "synced": 1}
    assert len(with_) == len(without) + sum(left_out.values())


def test_the_default_is_unchanged(tmp_path):
    """Counting must not change what is learned: no counter, same result."""
    root = _run(tmp_path, RECORDS)
    assert gather_examples_from_runs(root) == gather_examples_from_runs(
        root, excluded=Counter())


def test_a_later_local_label_is_not_counted_as_left_out(tmp_path):
    root = _run(tmp_path, [
        {"filename": "a.jpg", "overall_label": "cull", "source": "human",
         "synced": True},
        {"filename": "a.jpg", "overall_label": "keep", "source": "human"},
    ])
    left_out: Counter = Counter()
    assert len(gather_examples_from_runs(root, excluded=left_out)) == 1
    assert not left_out


def test_an_unlabelled_excluded_record_that_ends_a_label_is_counted(tmp_path):
    """Review of v3.96: it removes the earlier label, so the frame is left
    out, and the "with" half keeps it. Uncounted, `with = without + left
    out` failed by one."""
    root = _run(tmp_path, [
        {"filename": "a.jpg", "overall_label": "keep", "source": "human"},
        {"filename": "a.jpg", "source": "human", "synced": True},
        {"filename": "b.jpg", "source": "compare_rejected"},
    ])
    left_out: Counter = Counter()
    without = gather_examples_from_runs(root, excluded=left_out)
    with_ = gather_examples_from_runs(root, include_excluded=True)
    assert (len(without), len(with_)) == (0, 1)
    assert left_out == {"synced": 1}, "b.jpg had no label to lose"


def test_a_frame_with_no_score_is_not_counted(tmp_path):
    """It would not have become an example either way, so counting it
    would break `with = without + left out`."""
    root = _run(tmp_path, RECORDS)
    scores = root / "shoot" / "output" / "scores.csv"
    scores.write_text(scores.read_text(encoding="utf-8").replace(
        "theirs.jpg,", "elsewhere.jpg,"), encoding="utf-8")
    left_out: Counter = Counter()
    gather_examples_from_runs(root, excluded=left_out)
    assert left_out == {"compare_rejected": 1}


# ------------------------------------------------------ corrections file


def _corrections(tmp_path, records):
    p = tmp_path / "corrections.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return p


def _rec(fn, label, **kw):
    return {"filename": fn, "overall_label": label, "run_id": "shoot-a",
            "vertical": "landscape", "axes": {a: 3 for a in AXES}, **kw}


def test_a_corrections_file_loads_with_its_shoot_and_kind(tmp_path):
    p = _corrections(tmp_path, [_rec("a.jpg", "keep"), _rec("b.jpg", "cull")])
    exs = load_corrections(p)
    assert sorted(e.decision for e in exs) == ["cull", "keep"]
    assert {(e.run_id, e.vertical) for e in exs} == {("shoot-a", "landscape")}
    assert all(e.axes["composition"] == 3.0 for e in exs)


def test_a_corrections_file_applies_the_same_rule(tmp_path):
    p = _corrections(tmp_path, [_rec("a.jpg", "keep"),
                                _rec("b.jpg", "cull", synced=True)])
    left_out: Counter = Counter()
    assert len(load_corrections(p, excluded=left_out)) == 1
    assert left_out == {"synced": 1}
    assert len(load_corrections(p, include_excluded=True)) == 2


def test_a_corrections_file_with_a_byte_order_mark_loads(tmp_path):
    p = _corrections(tmp_path, [_rec("a.jpg", "keep")])
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    assert len(load_corrections(p)) == 1


def test_a_labelled_record_without_axes_is_refused(tmp_path):
    """A broken join. Dropping it would shrink the sample silently."""
    bad = _rec("b.jpg", "cull")
    del bad["axes"]
    p = _corrections(tmp_path, [_rec("a.jpg", "keep"), bad])
    with pytest.raises(ValueError, match=":2:"):
        load_corrections(p)


# ------------------------------------------------------ the spread


def _examples(n, seed):
    import random
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        ax = {a: rnd.uniform(1, 5) for a in AXES}
        out.append(Example(axes=ax, decision="keep" if ax["composition"] > 3 else "cull"))
    return out


def test_a_delta_comes_with_its_folds():
    ev = evaluate(_examples(80, 7))
    fd = ev["fold_deltas"]
    assert len(fd) == ev["folds"] == 4
    assert abs(sum(fd) / len(fd) - ev["delta"]) <= 0.002   # rounding only
    assert min(fd) <= ev["delta"] <= max(fd)


def test_a_refused_evaluation_has_no_folds():
    assert "fold_deltas" not in evaluate(_examples(3, 1))


def test_the_cli_says_what_it_left_out_and_how_much_the_folds_move(
        tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import pixcull.cli as cli
    monkeypatch.setattr(cli, "_PROFILE_PATH", tmp_path / "personal_profile.json")
    records = ([{"filename": f"k{i}.jpg", "overall_label": "keep", "source": "human"}
                for i in range(12)]
               + [{"filename": f"c{i}.jpg", "overall_label": "cull", "source": "human"}
                  for i in range(12)]
               + [{"filename": "s.jpg", "overall_label": "cull", "source": "human",
                   "synced": True}])
    root = _run(tmp_path / "runs", records)
    r = CliRunner().invoke(cli.app, ["personalize", "learn", "--runs-root", str(root)],
                           env={"COLUMNS": "200"})
    assert r.exit_code == 0, r.output
    assert "not learned from" in r.output
    assert "synced from another photographer: 1" in r.output
    assert "Δ per held-out fold" in r.output


# ------------------------------------------------------ the script


def _script():
    path = ROOT / "scripts" / "measure_label_provenance.py"
    spec = importlib.util.spec_from_file_location("measure_label_provenance", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_script_measures_with_and_without(tmp_path, capsys):
    recs = ([_rec(f"k{i}.jpg", "keep") for i in range(10)]
            + [_rec(f"c{i}.jpg", "cull") for i in range(10)]
            + [_rec("s.jpg", "cull", synced=True)])
    assert _script().main(["--corrections", str(_corrections(tmp_path, recs)),
                           "--reorder", "0"]) == 0
    out = capsys.readouterr().out
    assert "leaves out 1 synced" in out
    assert "with the excluded rows       n=21" in out
    assert "without them (as learned)    n=20" in out


def test_the_script_splits_a_sheet_into_its_subsets(tmp_path, capsys):
    (tmp_path / "scores.csv").write_text(
        f"filename,{STARS}\n" + "".join(f"f{i}.jpg,{i % 5},3,3,3,3,3\n"
                                        for i in range(24)), encoding="utf-8")
    (tmp_path / "labels.csv").write_text(
        "filename,manual_label\n" + "".join(
            f"f{i}.jpg,{'keep' if i % 5 > 2 else 'cull'}\n" for i in range(24))
        + "missing.jpg,keep\n", encoding="utf-8")
    (tmp_path / "half.csv").write_text(
        "filename\n" + "".join(f"f{i}.jpg\n" for i in range(12)), encoding="utf-8")
    assert _script().main(["--labels", str(tmp_path / "labels.csv"),
                           "--scores", str(tmp_path / "scores.csv"),
                           "--subset", f"half={tmp_path / 'half.csv'}",
                           "--reorder", "0"]) == 0
    out = capsys.readouterr().out
    assert "1 row(s) not joined" in out
    assert "labels.csv                   n=24" in out
    assert "  half                       n=12" in out


def test_a_stride_figure_comes_with_how_much_reordering_moves_it():
    """Stride folds are drawn by position, so one file order is one draw.
    The owner's 158 blind corrections gave +0.041 as the file lies and
    anywhere from -0.279 to +0.065 across 200 reorderings."""
    mod = _script()
    exs = _examples(60, 3)
    ds = mod.reordered(exs, 12)
    assert len(ds) == 12
    assert ds == mod.reordered(exs, 12), "seeded, so a rerun gives the same spread"
    assert len(set(ds)) > 1, "different orders draw different folds"
    line = mod._row("x", exs, reorder=5)
    assert "reordered ×5" in line


def test_whole_shoot_folds_are_not_reordered():
    """They do not depend on order; a spread there would be noise."""
    exs = ([Example(axes=e.axes, decision=e.decision, run_id="a") for e in _examples(30, 1)]
           + [Example(axes=e.axes, decision=e.decision, run_id="b") for e in _examples(30, 2)])
    assert "reordered" not in _script()._row("x", exs, reorder=5)
