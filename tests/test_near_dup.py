"""v2.6-P1 — tests for CLIP near-duplicate grouping."""
from __future__ import annotations

import numpy as np

from pixcull.scoring.near_dup import group_near_dups, pick_heroes


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
