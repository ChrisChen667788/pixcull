"""v3.98 — does a taste profile learned on some shoots predict another?

v2.83 could not answer it: every correction came from one shoot. The
owner's blind labels now cover five (scripts/measure_generalisation.py,
2026-10-28, 728 photographs). Learned on four and tested on the fifth, the
profile lowers evaluate()'s keep-F1 by 0.027 on average and by 0.178 within
portrait. In the product's own decision the learned threshold shift is
negative on every split, because it compares the photographer's keep rate
with a fixed 65% rather than with what the machine already keeps: keep-F1
rises 0.743 to 0.777 while cull recall halves, 7.7% to 3.6%. The profile
active on the owner's machine (shift -0.08) takes cull recall on all 728
from 12.4% to 1.7%.

Two things made that measurable, and these tests hold them: a photograph's
identity is `filename@datetime`, because the shutter counter wraps and six
names in a 2023 shoot recur in a 2024 one as different frames; and cull
recall is reported beside keep-F1, because keep-F1 alone rewards keeping
more.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pixcull.scoring.personal_learn import (
    AXES, Example, evaluate, examples_from_blind_sheet,
)

ROOT = Path(__file__).resolve().parents[1]
STARS = ",".join(f"rubric_{a}_stars" for a in AXES)


def _scores(path, rows):
    """rows: (filename, datetime, star, score_final)"""
    path.write_text(
        f"filename,datetime,scene,score_final,flags,{STARS}\n"
        + "".join(f"{f},{dt},portrait,{sf},,{s},{s},{s},{s},{s},{s}\n"
                  for f, dt, s, sf in rows), encoding="utf-8")
    return path


def _sheet(path, verdicts, source="human"):
    doc = {"selection": "blind", "verdicts": verdicts}
    if source:
        doc["source"] = source
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ------------------------------------------------------------ the loader


def test_a_blind_sheet_joins_to_the_run_that_scored_it(tmp_path):
    sc = _scores(tmp_path / "s.csv", [("A.JPG", "2023-10-03 09:28:24", 4, 0.8),
                                      ("B.JPG", "2023-10-03 09:28:30", 2, 0.3)])
    sh = _sheet(tmp_path / "v.json", {"A.JPG": "keep", "B.JPG": "cull",
                                      "C.JPG": "keep",        # not in this run
                                      })
    exs = examples_from_blind_sheet(sh, sc, shoot="Zhangye")
    assert [(e.key, e.decision, e.run_id) for e in exs] == [
        ("A.JPG@2023-10-03 09:28:24", "keep", "Zhangye"),
        ("B.JPG@2023-10-03 09:28:30", "cull", "Zhangye")]
    assert exs[0].axes["composition"] == 4.0


def test_a_sheet_that_does_not_say_human_contributes_nothing(tmp_path):
    sc = _scores(tmp_path / "s.csv", [("A.JPG", "2023-10-03 09:28:24", 4, 0.8)])
    assert examples_from_blind_sheet(_sheet(tmp_path / "v.json", {"A.JPG": "keep"},
                                            source=None), sc) == []
    assert examples_from_blind_sheet(_sheet(tmp_path / "w.json", {"A.JPG": "keep"},
                                            source="auto"), sc) == []


def test_scores_that_name_a_file_twice_are_refused(tmp_path):
    sc = _scores(tmp_path / "s.csv", [("A.JPG", "2023-10-03 09:28:24", 4, 0.8),
                                      ("A.JPG", "2024-10-04 16:20:27", 2, 0.3)])
    with pytest.raises(ValueError, match="more than once"):
        examples_from_blind_sheet(_sheet(tmp_path / "v.json", {"A.JPG": "keep"}), sc)


# ------------------------------------------------------------ evaluate()


def _ex(shoot, n, seed, keep_above=3.0):
    import random
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        ax = {a: rnd.uniform(1, 5) for a in AXES}
        out.append(Example(axes=ax, run_id=shoot, key=f"{shoot}{i}",
                           decision="keep" if ax["composition"] > keep_above else "cull"))
    return out


def test_a_cross_shoot_evaluation_names_the_shoot_each_fold_held_out():
    ev = evaluate(_ex("a", 40, 1) + _ex("b", 30, 2) + _ex("c", 20, 3))
    assert ev["grouped"] is True
    assert sorted(zip(ev["fold_groups"], ev["fold_n"])) == [("a", 40), ("b", 30), ("c", 20)]
    assert len(ev["fold_deltas"]) == 3


def test_stride_folds_name_no_shoot():
    assert evaluate([Example(axes=e.axes, decision=e.decision)
                     for e in _ex("a", 60, 4)])["fold_groups"] is None


def test_cull_recall_is_reported_beside_keep_f1():
    ev = evaluate(_ex("a", 40, 1) + _ex("b", 40, 2))
    for k in ("generic_cull_recall", "personal_cull_recall"):
        assert 0.0 <= ev[k] <= 1.0


def test_no_cull_to_find_is_no_cull_recall():
    keeps = [Example(axes={a: 4.0 for a in AXES}, decision="keep", run_id=r)
             for r in ("a", "b") for _ in range(10)]
    ev = evaluate(keeps)
    assert ev["generic_cull_recall"] is None and ev["personal_cull_recall"] is None


# ------------------------------------------------------------ the CLI


def test_the_cli_says_when_the_profile_scores_higher_by_keeping_more(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import pixcull.cli as cli
    import pixcull.scoring.personal_learn as pl
    monkeypatch.setattr(cli, "_PROFILE_PATH", tmp_path / "personal_profile.json")
    monkeypatch.setattr(pl, "gather_examples_from_runs",
                        lambda root, excluded=None: _ex("a", 30, 1) + _ex("b", 30, 2))
    monkeypatch.setattr(pl, "evaluate", lambda exs: {
        "n": 60, "folds": 2, "grouped": True, "n_runs": 2, "refused": None,
        "generic_f1": 0.743, "personal_f1": 0.777, "delta": 0.034,
        "fold_deltas": [0.02, 0.05], "fold_groups": ["a", "b"], "fold_n": [30, 30],
        "generic_cull_recall": 0.077, "personal_cull_recall": 0.036})
    r = CliRunner().invoke(cli.app, ["personalize", "learn", "--runs-root", str(tmp_path)],
                           env={"COLUMNS": "200"})
    assert r.exit_code == 0, r.output
    assert "held-out cull recall" in r.output and "8% → 4%" in r.output
    assert "scores higher by keeping more" in r.output


def test_no_improvement_is_not_called_higher(tmp_path, monkeypatch):
    """Review of v3.98: at Δ +0.000 the warning said "scores higher"."""
    from typer.testing import CliRunner

    import pixcull.cli as cli
    import pixcull.scoring.personal_learn as pl
    monkeypatch.setattr(cli, "_PROFILE_PATH", tmp_path / "personal_profile.json")
    monkeypatch.setattr(pl, "gather_examples_from_runs",
                        lambda root, excluded=None: _ex("a", 30, 1) + _ex("b", 30, 2))
    monkeypatch.setattr(pl, "evaluate", lambda exs: {
        "n": 60, "folds": 2, "grouped": True, "n_runs": 2, "refused": None,
        "generic_f1": 0.743, "personal_f1": 0.743, "delta": 0.0,
        "fold_deltas": [0.0, 0.0], "fold_groups": ["a", "b"], "fold_n": [30, 30],
        "generic_cull_recall": 0.10, "personal_cull_recall": 0.09})
    r = CliRunner().invoke(cli.app, ["personalize", "learn", "--runs-root", str(tmp_path)],
                           env={"COLUMNS": "200"})
    assert r.exit_code == 0, r.output
    assert "scores higher by keeping more" not in r.output


# ------------------------------------------------------------ the script


def _script():
    path = ROOT / "scripts" / "measure_generalisation.py"
    spec = importlib.util.spec_from_file_location("measure_generalisation", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_one_photograph_is_a_filename_at_a_time(tmp_path):
    """The same frame labelled twice is one photograph; the same name a
    year later is another."""
    a = _scores(tmp_path / "a.csv", [("A.JPG", "2023-10-03 09:28:24", 4, 0.8),
                                     ("B.JPG", "2023-10-03 09:28:30", 3, 0.6),
                                     ("C.JPG", "2023-10-03 09:28:40", 2, 0.4)])
    b = _scores(tmp_path / "b.csv", [("A.JPG", "2023-10-03 09:28:24", 4, 0.8),   # same frame
                                     ("B.JPG", "2023-10-03 09:28:30", 3, 0.6),   # same frame
                                     ("C.JPG", "2024-10-04 16:20:27", 2, 0.4)])  # counter wrapped
    s1 = _sheet(tmp_path / "1.json", {"A.JPG": "keep", "B.JPG": "keep", "C.JPG": "cull"})
    s2 = _sheet(tmp_path / "2.json", {"A.JPG": "keep", "B.JPG": "cull", "C.JPG": "keep"})
    exs, dup, rows = _script().assemble([("s", "portrait", s1, a), ("s", "portrait", s2, b)])
    assert dup == {"labelled_twice": 2, "agreed": 1, "dropped": 1}
    assert sorted(e.key for e in exs) == ["A.JPG@2023-10-03 09:28:24",
                                          "C.JPG@2023-10-03 09:28:40",
                                          "C.JPG@2024-10-04 16:20:27"]
    assert set(rows) >= {e.key for e in exs}


def test_a_photograph_in_two_shoots_is_judged_from_the_shoot_it_was_kept_in(tmp_path):
    """Review of v3.98: the kept example came from the first spec and its
    score row from the last."""
    a = _scores(tmp_path / "a.csv", [("SAME.JPG", "2023-10-03 09:28:24", 4, 0.8)])
    b = _scores(tmp_path / "b.csv", [("SAME.JPG", "2023-10-03 09:28:24", 4, 0.2)])
    s1 = _sheet(tmp_path / "1.json", {"SAME.JPG": "keep"})
    s2 = _sheet(tmp_path / "2.json", {"SAME.JPG": "keep"})
    exs, _dup, rows = _script().assemble([("shoot_a", "portrait", s1, a),
                                          ("shoot_b", "portrait", s2, b)])
    assert [e.run_id for e in exs] == ["shoot_a"]
    assert rows[exs[0].key]["score_final"] == "0.8"


def _shoot_files(tmp_path, name, n, keep_share, seed):
    import random
    rnd = random.Random(seed)
    rows, verdicts = [], {}
    for i in range(n):
        star = rnd.uniform(1, 5)
        fn = f"{name}{i:03d}.JPG"
        rows.append((fn, f"2024-10-0{seed} 10:{i // 60:02d}:{i % 60:02d}", round(star, 2),
                     round(star / 5, 3)))
        verdicts[fn] = "keep" if rnd.random() < keep_share else "cull"
    return (_sheet(tmp_path / f"{name}.json", verdicts),
            _scores(tmp_path / f"{name}.csv", rows))


def test_the_script_measures_across_and_within_shoots(tmp_path, capsys):
    specs = []
    for name, share, seed in (("a", 0.9, 1), ("b", 0.8, 2), ("c", 0.6, 3)):
        sh, sc = _shoot_files(tmp_path, name, 40, share, seed)
        specs += ["--shoot", name, "portrait", str(sh), str(sc)]
    assert _script().main(specs + ["--redraws", "3"]) == 0
    out = capsys.readouterr().out
    assert "120 photographs in 3 shoots" in out
    assert "mean over 3 held-out shoots" in out
    for name in "abc":
        assert f"held out {name}" in out
    assert "within the shoot (memorisation)" in out
    assert "the product's decision, leave one shoot out" in out
    assert "fixed 65% shift (before v3.99.1)" in out and "learned shift (vs machine)" in out
    # Review of v3.99.1: "kept" alone hid the culls left at maybe.
    assert "left at maybe" in out


def test_the_script_scores_a_saved_profile(tmp_path, capsys):
    from pixcull.scoring.personalized import PersonalProfile, save_profile
    sh, sc = _shoot_files(tmp_path, "a", 40, 0.8, 1)
    prof = tmp_path / "personal_profile.json"
    save_profile(PersonalProfile(user_id="t", n_annotations=70, keep_rate=0.97, cull_rate=0.03,
                                 keep_threshold_shift=-0.08, axis_keep_means={},
                                 axis_cull_means={}, most_cared_axis=None,
                                 label_provenance="blind"), prof)
    assert _script().main(["--shoot", "a", "portrait", str(sh), str(sc),
                           "--redraws", "2", "--profile", str(prof)]) == 0
    out = capsys.readouterr().out
    assert "no unseen shoot to predict" in out, "one shoot is not a cross-shoot test"
    assert "shift -0.080 from 70 corrections" in out
    without = next(l for l in out.splitlines() if "without it" in l)
    with_ = next(l for l in out.splitlines() if l.strip().startswith("with it"))
    # The shift lowers the keep bar, so the verdicts must actually move.
    assert without.split("verdicts")[1] != with_.split("verdicts")[1], (without, with_)


# ------------------------------------------------- v3.99: one per kind of shoot


def test_the_script_compares_one_profile_with_one_per_kind(tmp_path, capsys):
    """Portrait shot twice can be tested on a shoot it did not learn from;
    landscape shot once cannot, and is named rather than averaged in."""
    specs = []
    for name, genre, share, seed in (("a", "portrait", 0.9, 1), ("b", "portrait", 0.7, 2),
                                     ("c", "landscape", 0.6, 3)):
        sh, sc = _shoot_files(tmp_path, name, 40, share, seed)
        specs += ["--shoot", name, genre, str(sh), str(sc)]
    assert _script().main(specs + ["--redraws", "3"]) == 0
    out = capsys.readouterr().out
    assert "by genre: portrait 80, landscape 40" in out
    assert "held-out shoots ×2" in out and "(weighted by frames: Δ" in out
    assert "shot once, nothing to compare: landscape" in out
    assert "stride, shoots ignored (memorisation)" in out
    # The fixture's scene label is portrait on every frame: keyed by it,
    # there is one vertical and nothing to compare.
    assert "by scene label: portrait 120" in out
    assert "80 frames," in out          # the confusion covers portrait only
    for arm in ("no profile", "pooled", "per genre"):
        assert f"    {arm:<11} agrees" in out
    assert "fixed 65%   per genre" in out and "vs machine  per scene label" in out
    assert "verdicts unlike pooled:" in out


def test_the_confusion_is_built_like_evaluate_by_vertical(tmp_path):
    """Same arms, same held-out shoots as evaluate_by_vertical: its keep-F1
    and cull recall per held-out shoot, and the script's agreement line."""
    from pixcull.scoring.personal_learn import (
        _cull_recall, _keep_f1, decide, evaluate_by_vertical, learn_profile,
    )
    exs = (_ex("a", 40, 1) + _ex("b", 40, 2) + _ex("c", 40, 3))
    for e in exs:
        e.vertical = "landscape" if e.run_id == "c" else "portrait"
    ev = evaluate_by_vertical(exs)
    deltas, pooled_cr, per_cr, agree = [], [], [], []
    for held in ("a", "b"):
        test = [e for e in exs if e.run_id == held]
        pooled = learn_profile([e for e in exs if e.run_id != held])
        per = learn_profile([e for e in exs if e.vertical == "portrait" and e.run_id != held])
        by = {k: (lambda a, p=p: decide(a, profile=p)) for k, p in (("pooled", pooled), ("per", per))}
        deltas.append(round(_keep_f1(test, by["per"]) - _keep_f1(test, by["pooled"]), 3))
        pooled_cr.append(_cull_recall(test, by["pooled"]))
        per_cr.append(_cull_recall(test, by["per"]))
        agree += [by["per"](e.axes) == e.decision for e in test]
    assert ev["fold_deltas"] == deltas
    assert ev["pooled_cull_recall"] == round(sum(pooled_cr) / 2, 3)
    assert ev["per_vertical_cull_recall"] == round(sum(per_cr) / 2, 3)
    lines = _script().vertical_confusion(exs)
    assert "80 frames" in lines[0]
    assert f"    per genre   agrees {sum(agree) / len(agree):.1%}" in "\n".join(lines)


def test_a_fold_of_a_few_frames_counts_as_a_few_frames():
    """Keyed by scene label, a fold can be one photograph, and the plain
    mean weighs it like a whole shoot."""
    ev = {"refused": None, "grouped": True, "folds": 2, "pooled_f1": 0.5,
          "per_vertical_f1": 0.4, "delta": -0.1, "pooled_cull_recall": None,
          "fold_deltas": [-1.0, 0.1], "fold_n": [1, 99],
          "fold_groups": [("portrait", "a"), ("portrait", "b")], "verticals_unmeasured": []}
    assert "(weighted by frames: Δ +0.089)" in _script()._vertical_lines(ev)[0]


# ------------------------- v3.99: the whole profile, as run_pipeline applies it


def _dims_row(fn, scene, dims, cfg, flags=""):
    """A scores row whose score_final is what the fusion gives its dims."""
    row = {"filename": fn, "scene": scene, "flags": flags,
           **{f"score_{k}": str(v) for k, v in dims.items()}}
    row["score_final"] = str(_script()._refuse(row, None, cfg))
    return row


def test_axis_weights_are_applied_only_where_score_final_comes_back():
    """A run whose score_final cannot be recomputed from its per-dimension
    scores says so, rather than reporting a tilt it did not measure."""
    from pixcull.config import PixCullConfig
    cfg = PixCullConfig.load()
    mod = _script()
    ok = {"a": _dims_row("a.JPG", "portrait",
                         {"sharpness": 0.9, "composition": 0.3, "exposure": 0.7,
                          "aesthetic": 0.4, "moment": 0.8}, cfg)}
    assert mod.refuses(ok, cfg) is True
    off = {"a": {**ok["a"], "score_final": str(float(ok["a"]["score_final"]) + 0.05)}}
    assert mod.refuses(off, cfg) is False
    assert mod.refuses({"a": {"filename": "a.JPG", "score_final": "0.7"}}, cfg) is False


def test_the_whole_profile_tilts_the_fusion():
    """Measured in v3.99: v3.98's product figures applied the threshold shift
    alone; run_pipeline also tilts fuse_score with the axis weights."""
    from pixcull.config import PixCullConfig
    cfg = PixCullConfig.load()
    mod = _script()
    row = _dims_row("a.JPG", "portrait", {"sharpness": 0.95, "composition": 0.2,
                                          "exposure": 0.9, "aesthetic": 0.3,
                                          "moment": 0.95}, cfg)
    tilt = {"technical": 0.5, "moment": 0.5, "subject": 0.0, "composition": 0.0,
            "light": 0.0, "aesthetic": 0.0}
    assert mod._refuse(row, tilt, cfg) > float(row["score_final"])
    # Equal weights are a no-op, as fusion._personalize_weights promises.
    eq = {a: 1 / 6 for a in tilt}
    assert mod._refuse(row, eq, cfg) == pytest.approx(float(row["score_final"]))


def test_the_script_says_when_it_cannot_measure_the_axis_weights(tmp_path, capsys):
    """The fixture's runs record score_final alone."""
    specs = []
    for name, share, seed in (("a", 0.9, 1), ("b", 0.8, 2)):
        sh, sc = _shoot_files(tmp_path, name, 40, share, seed)
        specs += ["--shoot", name, "portrait", str(sh), str(sc)]
    assert _script().main(specs + ["--redraws", "2"]) == 0
    out = capsys.readouterr().out
    assert f"{'learned shift and axis weights':<34} not measured" in out
    assert "the whole profile: not measured" in out


def test_the_script_measures_the_whole_profile_where_it_can(tmp_path, capsys):
    import csv
    import random

    from pixcull.config import PixCullConfig
    cfg = PixCullConfig.load()
    specs = []
    for name, share, seed in (("a", 0.9, 1), ("b", 0.7, 2)):
        rnd = random.Random(seed)
        rows, verdicts = [], {}
        for i in range(40):
            fn = f"{name}{i:03d}.JPG"
            dims = {k: round(rnd.uniform(0.3, 1.0), 3) for k in
                    ("sharpness", "composition", "exposure", "aesthetic", "moment")}
            star = round(1 + 4 * sum(dims.values()) / 5, 2)
            row = _dims_row(fn, "portrait", dims, cfg)
            row.update({"datetime": f"2024-10-0{seed} 10:00:{i:02d}",
                        **{f"rubric_{a}_stars": star for a in AXES}})
            rows.append(row)
            verdicts[fn] = "keep" if rnd.random() < share else "cull"
        sc = tmp_path / f"{name}.csv"
        with open(sc, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        specs += ["--shoot", name, "portrait", str(_sheet(tmp_path / f"{name}.json", verdicts)), str(sc)]
    assert _script().main(specs + ["--redraws", "2"]) == 0
    out = capsys.readouterr().out
    assert f"{'learned shift and axis weights':<34} keep-F1" in out
    assert "the whole profile, shift and axis weights, as run_pipeline applies it:" in out


def test_every_whole_profile_path_decides_on_the_refused_score(tmp_path, capsys, monkeypatch):
    """Pin the re-fused score to 0 and every path that applies axis weights
    must cull everything; a path that quietly used score_final would not."""
    from pixcull.config import PixCullConfig
    from pixcull.scoring.personalized import PersonalProfile, save_profile
    mod = _script()
    cfg = PixCullConfig.load()
    row = {"filename": "a.JPG", "scene": "portrait", "flags": "", "score_final": "0.99"}
    tilt = {"technical": 0.5, "moment": 0.5}
    assert mod._product_verdict(row, 0.0, cfg) == "keep"
    monkeypatch.setattr(mod, "_refuse", lambda r, a, c: 0.0)
    monkeypatch.setattr(mod, "refuses", lambda rows, c: True)
    assert mod._product_verdict(row, 0.0, cfg, tilt) == "cull"

    specs = []
    for name, share, seed in (("a", 0.9, 1), ("b", 0.7, 2)):
        sh, sc = _shoot_files(tmp_path, name, 40, share, seed)
        specs += ["--shoot", name, "portrait", str(sh), str(sc)]
    prof = tmp_path / "p.json"
    save_profile(PersonalProfile(user_id="t", n_annotations=70, keep_rate=0.8, cull_rate=0.2,
                                 keep_threshold_shift=-0.08,
                                 axis_keep_means={"technical": 4.5, "moment": 4.5, "subject": 3,
                                                  "composition": 3, "light": 3, "aesthetic": 3},
                                 axis_cull_means={a: 2.0 for a in AXES}, most_cared_axis="moment",
                                 label_provenance="blind"), prof)
    assert mod.main(specs + ["--redraws", "2", "--profile", str(prof)]) == 0
    out = capsys.readouterr().out
    assert f"{'learned shift and axis weights':<34} keep-F1 0.000  cull recall 100.0%" in out
    assert f"{'fixed 65% shift and axis weights':<34} keep-F1 0.000  cull recall 100.0%" in out
    whole = out.split("as run_pipeline applies it:")[1]
    assert "fixed 65%   pooled           keep-F1 0.000  cull recall 100.0%" in whole
    with_ = next(l for l in out.splitlines() if l.strip().startswith("with it"))
    assert "'cull': 80" in with_, with_


@pytest.mark.parametrize("flags", ["", "closed_eyes", "smile,eye_contact", "closed_eyes,open_eyes"])
@pytest.mark.parametrize("tilt", [None, {"technical": 0.5, "moment": 0.3, "aesthetic": 0.2,
                                         "subject": 0.0, "composition": 0.0, "light": 0.0}])
def test_the_refused_score_is_the_products_fusion(flags, tilt):
    """Checked against fusion.fuse_score itself, penalties and bonuses
    included, so the script cannot drift from what a run computes."""
    from pixcull.config import PixCullConfig
    from pixcull.scoring.fusion import fuse_score
    cfg = PixCullConfig.load()
    raw = {"laplacian_subject": 180, "laplacian_global": 90, "highlight_clip_pct": 0.5,
           "shadow_clip_pct": 1.0, "mean_luma": 120, "laion_aes": 5.6, "clipiqa": 0.55,
           "composition_score": 0.42, "moment_score": 0.77}
    fl = [f for f in flags.split(",") if f]
    dims = fuse_score(raw, fl, "portrait", cfg)
    row = {"filename": "a.JPG", "scene": "portrait", "flags": "|".join(fl),
           "score_final": str(dims["final"]),
           **{f"score_{k}": str(dims[k]) for k in
              ("sharpness", "composition", "exposure", "aesthetic", "moment")}}
    from pixcull.scoring.vlm_eval import _flags_of
    assert _flags_of(row) == fl, "the fixture's flags must parse as the run's do"
    want = fuse_score(raw, fl, "portrait", cfg, axis_pref=tilt)["final"]
    assert _script()._refuse(row, tilt, cfg) == pytest.approx(want)


# ------------------- v3.99.1: the shift is measured against the machine


def test_the_old_formula_is_kept_only_to_report_it(tmp_path):
    """The script's fixed-65% arm is exactly what profile_from_preferences
    computed until v3.99.1: -(keep rate - 0.65) * 0.5, capped, to 4 places."""
    mod = _script()
    exs = [Example(axes={}, decision="keep")] * 76 + [Example(axes={}, decision="cull")] * 24
    assert mod._fixed_shift(exs) == round(-(0.76 - 0.65) * 0.5, 4)
    assert mod._fixed_shift([Example(axes={}, decision="keep")] * 10) == -0.08


def test_the_learned_shift_is_the_one_measured_against_the_machine(tmp_path):
    """learn_profile on blind-sheet examples gives the shift the script
    reports as measured against the machine's keep rate."""
    from pixcull.config import PixCullConfig
    from pixcull.scoring.personal_learn import learn_profile
    mod = _script()
    cfg = PixCullConfig.load()
    specs = []
    for name, share, seed in (("a", 0.9, 1), ("b", 0.6, 2)):
        sh, sc = _shoot_files(tmp_path, name, 40, share, seed)
        specs.append((name, "portrait", sh, sc))
    exs, _dup, rows = mod.assemble(specs)
    assert all(e.machine for e in exs), "every example carries the machine's verdict"
    prof = learn_profile(exs)
    assert prof.shift_basis == "machine"
    assert prof.keep_threshold_shift == pytest.approx(mod._relative_shift(exs, rows, cfg), abs=1e-4)
