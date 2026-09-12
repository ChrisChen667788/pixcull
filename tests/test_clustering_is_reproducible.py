"""v3.84 — the same folder came back with different verdicts.

Two consecutive runs of one 150-frame folder, no code change between
them: `Keep=97 Maybe=53` and `Keep=95 Maybe=55`.

**Why.** EXIF time is second-resolution and a burst is several frames a
second, so tied timestamps are the normal case. `cluster_bursts` sorted
on time alone with a stable sort, so ties kept the order the rows
arrived in — and they arrive from a parallel scoring pass, in completion
order. Only adjacent rows are compared and the chain is transitive, so
whichever row lands at a tie boundary decides whether two groups merge.

Measured on four real frames at 16:25:12 / :12 / :13 / :13, every
adjacent pair above threshold:

    3912,3913,3914,3915  boundary 3913×3914 = 0.9480  -> 1 cluster
    3912,3913,3915,3914  boundary 3913×3915 = 0.9268  -> 2 clusters
    3913,3912,3914,3915  boundary 3912×3914 = 0.9584  -> 1 cluster
    3913,3912,3915,3914  boundary 3912×3915 = 0.9392  -> 2 clusters

Half the orderings merge and half split. Which one you got depended on
which worker finished first.

Since v3.83 `cluster_id` decides `keep` versus `maybe`, so this reached
the verdict. It is also why the cluster boundary that moved between runs
in v3.83 could not be reproduced: nothing recorded the order, and
nothing recorded the vectors either — `embeddings.npz` holds the 512-d
CLIP vectors for semantic search, while clustering groups on the 768-d
DINOv2 vector, which was discarded with the dataframe. An analysis that
reached for the file on disk got the wrong model at the wrong
dimensionality, and cosine similarity does not complain: it returns
plausible numbers. I did that, got 44 singletons where the run had 74,
and nearly reported the conclusion.

The fix is two parts: tie-break on the filename, which is the camera's
own shutter counter and the only real order on the dataframe; and write
the vectors that decided the clusters, so the grouping can be checked
rather than trusted.
"""
import ast
import itertools
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from pixcull.detectors.duplicate import cluster_bursts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ORCH = ROOT / "pixcull" / "pipeline" / "orchestrator.py"
DUP = ROOT / "pixcull" / "detectors" / "duplicate.py"


def _tied_frames():
    """Four frames, two tied timestamps, adjacent similarity above the
    threshold and the diagonal below it — the shape that made the
    boundary a coin flip."""
    base = pd.Timestamp("2024-10-04 16:25:12")
    def vec(theta):
        v = np.zeros(8, dtype=float)
        v[0], v[1] = np.cos(theta), np.sin(theta)
        return v
    # Spaced so neighbours clear 0.94 and frames two apart do not.
    angles = [0.0, 0.18, 0.36, 0.54]
    return [
        {"filename": f"IMG_{i}.JPG",
         "datetime": base + pd.Timedelta(seconds=0 if i < 2 else 1),
         "scene": "landscape",
         "embedding": vec(a)}
        for i, a in enumerate(angles)
    ]


def _grouping(rows) -> set:
    d = cluster_bursts(pd.DataFrame(rows))
    sizes = d["cluster_id"].value_counts()
    names = list(d["filename"])
    cid = dict(zip(d["filename"], d["cluster_id"]))
    return {tuple(sorted((a, b)))
            for a, b in itertools.combinations(names, 2)
            if cid[a] == cid[b] and int(sizes.get(cid[a], 0)) > 1}


def test_the_fixture_actually_has_a_tie_boundary():
    """If the fixture stops having tied timestamps, the test below passes
    for the wrong reason — it would be asserting determinism on data
    where order never mattered."""
    rows = _tied_frames()
    stamps = [r["datetime"] for r in rows]
    assert len(set(stamps)) < len(stamps), "no tied timestamps in the fixture"
    embs = [r["embedding"] for r in rows]
    adjacent = [float(np.dot(embs[i], embs[i + 1])) for i in range(3)]
    diagonal = [float(np.dot(embs[i], embs[i + 2])) for i in range(2)]
    assert all(x >= 0.94 for x in adjacent), (
        f"neighbours must clear the threshold: {adjacent}")
    assert any(x < 0.94 for x in diagonal), (
        f"a non-neighbour must fall below it, or order cannot matter: "
        f"{diagonal}")


def test_the_clustering_does_not_depend_on_input_order():
    """The property the fix exists for. Every permutation of the input
    has to produce the same grouping."""
    rows = _tied_frames()
    want = _grouping(rows)
    for perm in itertools.permutations(rows):
        got = _grouping(list(perm))
        assert got == want, (
            "input order changed the clusters: "
            f"{[r['filename'] for r in perm]} gave {sorted(got)}, "
            f"baseline gave {sorted(want)}")


def test_the_tie_break_is_the_filename():
    """Stated as code, not as a comment: the sort has to name a second
    key, and it has to be the one that means something."""
    src = DUP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "sort_values":
            seg = ast.get_source_segment(src, node) or ""
            if "sort_cols" in seg or "filename" in seg:
                found = True
    assert found, (
        "cluster_bursts no longer sorts by anything but time; ties are "
        "decided by worker completion order again")
    assert "sort_cols.append(\"filename\")" in src, (
        "the filename tie-break is gone")


def test_a_frame_with_no_timestamp_still_lands_somewhere():
    """Video stills and scans reach this with no EXIF time. They must not
    take the run down, and they must not silently join a burst."""
    rows = _tied_frames()
    rows.append({"filename": "IMG_NOTIME.JPG", "datetime": pd.NaT,
                 "scene": "landscape", "embedding": np.zeros(8)})
    d = cluster_bursts(pd.DataFrame(rows))
    assert len(d) == len(rows)
    assert "cluster_id" in d.columns


# ── the evidence has to be on disk ───────────────────────────────────

def test_the_run_writes_the_vectors_that_decided_the_clusters():
    src = ORCH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)}
    assert "_write_burst_cache" in names, (
        "nothing persists the burst vectors; cluster_id cannot be checked")
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_write_burst_cache" in called, (
        "_write_burst_cache is defined and never called")


def test_the_burst_cache_is_not_the_clip_cache():
    """They are different models at different dimensionalities, and
    swapping them produces wrong answers without an error."""
    src = ORCH.read_text(encoding="utf-8")
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    i = body.index("def _write_burst_cache")
    j = body.index("def ", i + 10)
    burst = body[i:j]
    assert '"embedding"' in burst, (
        "the burst cache does not read the column cluster_bursts groups on")
    assert "clip_embedding" not in burst, (
        "the burst cache is writing the CLIP vectors — the wrong model")
