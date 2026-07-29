"""v2.32-P0 — cross-run library index.

The hard parts of library search aren't the dot product; they're
liveness (drives go offline, runs get deleted), incremental correctness
(re-indexing must be idempotent, a re-scored photo must re-index), and
never corrupting the row-parallel invariant between vectors.npy and
manifest.jsonl. These tests target exactly those.
"""
import json

import numpy as np
import pytest

from pixcull.scoring import library_index as LX


def _vecs(n, d=8, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, d)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _mk_photos(tmp_path, run_id, n):
    """Create n real files so liveness checks have something to see."""
    d = tmp_path / run_id
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(n):
        p = d / f"{run_id}_{i}.jpg"
        p.write_bytes(b"x")
        out.append((p.name, str(p), p.stat().st_mtime))
    return out


def test_empty_library_is_not_an_error(tmp_path):
    lib = tmp_path / "lib"
    assert LX.load_manifest(lib) == []
    assert LX.load_vectors(lib) is None
    assert LX.search(np.zeros(8, np.float32), library_dir=lib) == []
    st = LX.status(lib)
    assert st["n_photos"] == 0 and st["n_runs"] == 0


def test_append_then_search_finds_the_planted_vector(tmp_path):
    lib = tmp_path / "lib"
    entries = _mk_photos(tmp_path, "runA", 5)
    v = _vecs(5)
    LX.append_run("runA", entries, v, library_dir=lib)
    # query == row 3's vector → row 3 must rank first with sim ≈ 1
    hits = LX.search(v[3], k=3, library_dir=lib)
    assert hits[0]["filename"] == entries[3][0]
    assert hits[0]["similarity"] == pytest.approx(1.0, abs=1e-5)
    assert hits[0]["stale"] is False


def test_append_is_idempotent(tmp_path):
    lib = tmp_path / "lib"
    entries = _mk_photos(tmp_path, "runA", 4)
    v = _vecs(4)
    first = LX.append_run("runA", entries, v, library_dir=lib)
    second = LX.append_run("runA", entries, v, library_dir=lib)
    assert first["added"] == 4
    assert second["added"] == 0 and second["skipped"] == 4
    assert LX.status(lib)["n_photos"] == 4


def test_changed_mtime_reindexes_that_photo(tmp_path):
    """A re-scored / edited photo has a new vector — the mtime in the
    identity key is what makes it re-index instead of going stale."""
    lib = tmp_path / "lib"
    entries = _mk_photos(tmp_path, "runA", 2)
    LX.append_run("runA", entries, _vecs(2), library_dir=lib)
    bumped = [(entries[0][0], entries[0][1], entries[0][2] + 100),
              entries[1]]
    res = LX.append_run("runA", bumped, _vecs(2, seed=1), library_dir=lib)
    assert res["added"] == 1 and res["skipped"] == 1


def test_multiple_runs_coexist_and_are_attributed(tmp_path):
    lib = tmp_path / "lib"
    a, b = _mk_photos(tmp_path, "runA", 3), _mk_photos(tmp_path, "runB", 3)
    va, vb = _vecs(3, seed=1), _vecs(3, seed=2)
    LX.append_run("runA", a, va, library_dir=lib)
    LX.append_run("runB", b, vb, library_dir=lib)
    st = LX.status(lib)
    assert st["n_photos"] == 6 and st["n_runs"] == 2
    assert LX.search(vb[0], k=1, library_dir=lib)[0]["run_id"] == "runB"


def test_missing_file_is_reported_stale_not_dropped(tmp_path):
    """The whole point: 'found it, but the file moved' must reach the
    user — silently dropping the hit hides that the photo ever existed."""
    lib = tmp_path / "lib"
    entries = _mk_photos(tmp_path, "runA", 3)
    v = _vecs(3)
    LX.append_run("runA", entries, v, library_dir=lib)
    (tmp_path / "runA" / entries[1][0]).unlink()      # drive offline / deleted
    hits = LX.search(v[1], k=3, library_dir=lib)
    assert hits[0]["filename"] == entries[1][0]
    assert hits[0]["stale"] is True
    assert LX.status(lib)["n_stale"] == 1


def test_prune_drops_stale_rows_and_keeps_rows_parallel(tmp_path):
    lib = tmp_path / "lib"
    entries = _mk_photos(tmp_path, "runA", 4)
    v = _vecs(4)
    LX.append_run("runA", entries, v, library_dir=lib)
    (tmp_path / "runA" / entries[0][0]).unlink()
    (tmp_path / "runA" / entries[2][0]).unlink()
    res = LX.prune(lib)
    assert res["removed"] == 2 and res["remaining"] == 2
    man = LX.load_manifest(lib)
    vecs = LX.load_vectors(lib, mmap=False)
    assert len(man) == vecs.shape[0] == 2
    assert [e["row"] for e in man] == [0, 1]      # rows renumbered
    # the surviving vectors still match their manifest rows
    for e in man:
        assert LX.search(vecs[e["row"]], k=1,
                         library_dir=lib)[0]["filename"] == e["filename"]


def test_prune_one_run_leaves_the_other(tmp_path):
    lib = tmp_path / "lib"
    a, b = _mk_photos(tmp_path, "runA", 2), _mk_photos(tmp_path, "runB", 3)
    LX.append_run("runA", a, _vecs(2, seed=1), library_dir=lib)
    LX.append_run("runB", b, _vecs(3, seed=2), library_dir=lib)
    LX.prune(lib, run_id="runA")
    st = LX.status(lib)
    assert st["n_photos"] == 3 and st["runs"] == ["runB"]


def test_dimension_mismatch_is_refused(tmp_path):
    lib = tmp_path / "lib"
    LX.append_run("runA", _mk_photos(tmp_path, "runA", 2), _vecs(2, d=8),
                  library_dir=lib)
    with pytest.raises(ValueError, match="dimension"):
        LX.append_run("runB", _mk_photos(tmp_path, "runB", 2), _vecs(2, d=16),
                      library_dir=lib)


def test_misaligned_entries_are_refused(tmp_path):
    lib = tmp_path / "lib"
    with pytest.raises(ValueError, match="align"):
        LX.append_run("runA", _mk_photos(tmp_path, "runA", 3), _vecs(2),
                      library_dir=lib)


def test_torn_manifest_line_does_not_break_the_library(tmp_path):
    """An interrupted append can leave a half-written line; the library
    must stay readable rather than becoming a brick."""
    lib = tmp_path / "lib"
    entries = _mk_photos(tmp_path, "runA", 3)
    LX.append_run("runA", entries, _vecs(3), library_dir=lib)
    man_path = lib / "manifest.jsonl"
    with man_path.open("a", encoding="utf-8") as fh:
        fh.write('{"run_id": "runA", "filename": "trunc')   # torn write
    assert len(LX.load_manifest(lib)) == 3
    assert LX.search(_vecs(3)[0], k=2, library_dir=lib)


def test_vectors_are_normalized_on_append(tmp_path):
    """Cosine == dot product only holds for unit vectors; callers may
    hand us unnormalized ones."""
    lib = tmp_path / "lib"
    raw = np.array([[3.0, 4.0] + [0.0] * 6], dtype=np.float32)   # norm 5
    LX.append_run("runA", _mk_photos(tmp_path, "runA", 1), raw, library_dir=lib)
    v = LX.load_vectors(lib, mmap=False)
    assert np.linalg.norm(v[0]) == pytest.approx(1.0, abs=1e-6)


def test_manifest_is_json_lines_with_expected_fields(tmp_path):
    lib = tmp_path / "lib"
    LX.append_run("runA", _mk_photos(tmp_path, "runA", 1), _vecs(1),
                  library_dir=lib)
    line = (lib / "manifest.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert set(rec) >= {"run_id", "filename", "abs_path", "mtime", "row"}
