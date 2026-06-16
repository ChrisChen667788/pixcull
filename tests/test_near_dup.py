"""v2.6-P1 — tests for CLIP near-duplicate grouping."""
from __future__ import annotations

import numpy as np

from pixcull.scoring.near_dup import (
    group_cross_shoot,
    group_near_dups,
    pick_cross_shoot_heroes,
    pick_heroes,
)


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_groups_connected_components():
    # a≈b≈c (one chain), d alone, e≈f — expect [abc], [ef]
    base = _unit([1, 0, 0, 0])
    near = _unit([0.99, 0.14, 0, 0])          # cos≈0.990 with base
    near2 = _unit([0.98, 0.0, 0.19, 0])       # cos≈0.98 with base
    far = _unit([0, 1, 0, 0])
    e = _unit([0, 0, 1, 0]); f = _unit([0.1, 0, 0.99, 0])
    fns = ["a", "b", "c", "d", "e", "f"]
    vecs = np.stack([base, near, near2, far, e, f])
    groups = group_near_dups(fns, vecs, threshold=0.95)
    assert sorted(map(sorted, groups)) == [["a", "b", "c"], ["e", "f"]]


def test_threshold_controls_linking():
    a = _unit([1, 0]); b = _unit([0.92, 0.39])    # cos ≈ 0.92
    fns = ["a", "b"]; vecs = np.stack([a, b])
    assert group_near_dups(fns, vecs, threshold=0.95) == []
    assert group_near_dups(fns, vecs, threshold=0.90) == [["a", "b"]]


def test_blocked_matches_unblocked():
    rng = np.random.default_rng(7)
    vecs = rng.normal(size=(50, 16)).astype(np.float32)
    vecs[10] = vecs[3] + 0.01           # plant a near-dup pair
    vecs[41] = vecs[20] * 1.5           # scale-invariant (normalised)
    fns = [f"p{i}" for i in range(50)]
    g_small = group_near_dups(fns, vecs, threshold=0.995, block=7)
    g_full = group_near_dups(fns, vecs, threshold=0.995, block=4096)
    assert sorted(map(sorted, g_small)) == sorted(map(sorted, g_full))
    flat = {fn for g in g_full for fn in g}
    assert {"p3", "p10", "p20", "p41"} <= flat


def test_empty_and_mismatch():
    assert group_near_dups([], np.zeros((0, 4))) == []
    assert group_near_dups(["a"], np.zeros((2, 4))) == []


def test_pick_heroes_by_score():
    groups = [["a", "b", "c"], ["e", "f"]]
    scores = {"a": 0.5, "b": 0.9, "c": 0.7, "f": 0.3}
    out = pick_heroes(groups, scores)
    assert out[0] == {"hero": "b", "members": ["a", "b", "c"]}
    assert out[1]["hero"] == "f"            # e has no score → f wins
    assert pick_heroes([["x", "y"]])[0]["hero"] == "x"   # no scores → first


# ── v2.7 cross-shoot dedup ──────────────────────────────────────────────

def test_cross_shoot_finds_recurring_frame():
    """The same frame delivered across two shoots links into one group."""
    base = _unit([1, 0, 0, 0])
    near = _unit([0.97, 0.24, 0, 0])          # cos≈0.97 with base (cross-shoot dup)
    shoots = [
        ("wedding", ["a.jpg", "b.jpg"], np.stack([base, _unit([0, 1, 0, 0])])),
        ("teaser",  ["x.jpg", "y.jpg"], np.stack([near, _unit([0, 0, 1, 0])])),
    ]
    groups = group_cross_shoot(shoots, threshold=0.92)
    assert len(groups) == 1
    assert sorted(groups[0]) == [("teaser", "x.jpg"), ("wedding", "a.jpg")]


def test_cross_shoot_ignores_within_shoot_dup():
    """A near-dup pair WITHIN one shoot must not surface (min_shoots=2)."""
    a = _unit([1, 0, 0, 0]); a2 = _unit([0.98, 0.16, 0, 0])     # within-shoot dup
    shoots = [
        ("s1", ["a.jpg", "a2.jpg"], np.stack([a, a2])),
        ("s2", ["z.jpg"], np.stack([_unit([0, 0, 1, 0])])),
    ]
    assert group_cross_shoot(shoots, threshold=0.92) == []


def test_cross_shoot_threshold_and_malformed():
    base = _unit([1, 0, 0, 0]); near = _unit([0.96, 0.28, 0, 0])   # cos≈0.96
    shoots = [("a", ["p.jpg"], np.stack([base])),
              ("b", ["q.jpg"], np.stack([near]))]
    assert len(group_cross_shoot(shoots, threshold=0.92)) == 1
    assert group_cross_shoot(shoots, threshold=0.999) == []        # too strict
    # malformed shoot (filename/vector count mismatch) is skipped gracefully
    bad = [("a", ["p.jpg", "extra.jpg"], np.stack([base])),
           ("b", ["q.jpg"], np.stack([near]))]
    assert group_cross_shoot(bad, threshold=0.92) == []            # 'a' dropped → no cross


def test_pick_cross_shoot_heroes_by_score():
    g = [("wedding", "a.jpg"), ("teaser", "x.jpg")]
    scores = {("wedding", "a.jpg"): 0.6, ("teaser", "x.jpg"): 0.9}
    out = pick_cross_shoot_heroes([g], scores)
    assert out[0]["hero"] == ("teaser", "x.jpg")
    assert out[0]["duplicates"] == [("wedding", "a.jpg")]
    assert set(out[0]["members"]) == set(g)


def test_dedup_across_cli_reports_cross_shoot(tmp_path):
    """End-to-end CLI: two synthetic runs sharing a frame → 1 group + JSON."""
    import json
    from typer.testing import CliRunner
    from pixcull.cli import app
    e = np.eye(8, dtype=np.float32); near = e[0] + 0.25 * e[1]   # cross-shoot dup
    specs = [("A", [e[0], e[1]], ["a.jpg", "b.jpg"], "a.jpg,0.9\nb.jpg,0.5\n"),
             ("B", [near, e[2]], ["x.jpg", "c.jpg"], "x.jpg,0.8\nc.jpg,0.4\n")]
    dirs = []
    for name, vecs, fns, sc in specs:
        d = tmp_path / name / "output"; d.mkdir(parents=True)
        with open(d / "embeddings.npz", "wb") as fh:
            np.savez(fh, filenames=np.array(fns),
                     vectors=np.stack(vecs).astype(np.float32),
                     model=np.array("clip"))
        (d / "scores.csv").write_text("filename,score_final\n" + sc, encoding="utf-8")
        dirs.append(str(d))
    rep = tmp_path / "report.json"
    res = CliRunner().invoke(app, ["dedup-across", *dirs, "-o", str(rep)])
    assert res.exit_code == 0, res.stdout
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["schema"] == "pixcull.dedup_across.v1"
    assert len(data["groups"]) == 1
    g = data["groups"][0]
    assert g["hero"] == ["A", "a.jpg"]            # 0.9 > B/x.jpg 0.8
    assert ["B", "x.jpg"] in g["duplicates"]


def test_dedup_across_cli_needs_two_runs(tmp_path):
    """A single run → friendly error + non-zero exit (not a crash)."""
    from typer.testing import CliRunner
    from pixcull.cli import app
    d = tmp_path / "solo" / "output"; d.mkdir(parents=True)
    with open(d / "embeddings.npz", "wb") as fh:
        np.savez(fh, filenames=np.array(["a.jpg"]),
                 vectors=np.eye(4, dtype=np.float32)[:1], model=np.array("clip"))
    res = CliRunner().invoke(app, ["dedup-across", str(d)])
    assert res.exit_code == 1
