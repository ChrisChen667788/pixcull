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


# ── v2.39 — append-only vector store ──────────────────────────────────
#
# Appending used to np.vstack the whole library and rewrite vectors.npy.
# Measured with one 2,000-photo shoot going in:
#   library  50k → 0.37s      150k → 1.08s      300k → 3.30s
# i.e. linear in everything already indexed, on every cull (auto-index
# has been on since v2.34). The raw store appends in O(new bytes):
#   library  50k → 0.16s      150k → 0.38s      300k → 0.70s
# What is left is load_manifest parsing the dedup set (0.556s of that
# 0.70s), not the vector write (0.005s).

def _v39(n, dim=8, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, dim)).astype(np.float32)


def _e39(n, prefix="p"):
    return [(f"{prefix}{i}.jpg", f"/src/{prefix}{i}.jpg", 1.0)
            for i in range(n)]


def test_append_uses_the_raw_store(tmp_path):
    LX.append_run("r1", _e39(3), _v39(3), library_dir=tmp_path)
    assert (tmp_path / "vectors.f32").is_file()
    meta = LX.read_meta(tmp_path)
    assert meta["n_rows"] == 3 and meta["dim"] == 8
    assert meta["store"] == "vectors.f32"


def test_second_append_does_not_rewrite_existing_bytes(tmp_path):
    """The whole point: old bytes stay put, new ones are appended."""
    LX.append_run("r1", _e39(4), _v39(4, seed=1), library_dir=tmp_path)
    raw = tmp_path / "vectors.f32"
    first = raw.read_bytes()
    LX.append_run("r2", _e39(3, "q"), _v39(3, seed=2),
                  library_dir=tmp_path)
    after = raw.read_bytes()
    assert after[:len(first)] == first, "existing rows were rewritten"
    assert len(after) == len(first) + 3 * 8 * 4


def test_rows_survive_the_append_intact(tmp_path):
    a, b = _v39(3, seed=3), _v39(2, seed=4)
    LX.append_run("r1", _e39(3), a, library_dir=tmp_path)
    LX.append_run("r2", _e39(2, "q"), b, library_dir=tmp_path)
    got = np.asarray(LX.load_vectors(tmp_path))
    assert got.shape == (5, 8)

    def unit(v):
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    assert np.allclose(got[:3], unit(a), atol=1e-6)
    assert np.allclose(got[3:], unit(b), atol=1e-6)


def test_torn_append_is_invisible_until_meta_commits(tmp_path):
    """Crash safety: vectors are appended and fsynced BEFORE meta.json is
    swapped in, so a half-written tail must not be readable."""
    LX.append_run("r1", _e39(4), _v39(4), library_dir=tmp_path)
    raw = tmp_path / "vectors.f32"
    # simulate a crash mid-append: extra bytes, meta untouched
    with raw.open("ab") as fh:
        fh.write(b"\x01" * (8 * 4 * 2 + 5))     # 2 rows + a partial one

    got = LX.load_vectors(tmp_path)
    assert got.shape == (4, 8), "reader exposed an uncommitted tail"
    hits = LX.search(_v39(1)[0], k=10, library_dir=tmp_path,
                     check_liveness=False)
    assert len(hits) == 4


def test_meta_claiming_more_rows_than_exist_is_clamped(tmp_path):
    """Never read past the end of the file, whatever meta says."""
    LX.append_run("r1", _e39(3), _v39(3), library_dir=tmp_path)
    meta = LX.read_meta(tmp_path)
    meta["n_rows"] = 99
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert LX.load_vectors(tmp_path).shape == (3, 8)


def test_legacy_npy_library_is_migrated_on_next_append(tmp_path):
    """An index built before v2.39 must keep working — and converge onto
    the new store rather than staying slow forever."""
    old = np.ascontiguousarray(
        _v39(3, seed=7) / np.linalg.norm(_v39(3, seed=7), axis=1,
                                           keepdims=True))
    with (tmp_path / "vectors.npy").open("wb") as fh:
        np.save(fh, old)
    (tmp_path / "manifest.jsonl").write_text("".join(
        json.dumps({"run_id": "old", "filename": f"o{i}.jpg",
                     "abs_path": f"/o/o{i}.jpg", "mtime": 1.0, "row": i})
        + "\n" for i in range(3)), encoding="utf-8")
    (tmp_path / "meta.json").write_text(
        json.dumps({"n_rows": 3, "dim": 8}), encoding="utf-8")

    LX.append_run("new", _e39(2, "n"), _v39(2, seed=8),
                  library_dir=tmp_path)

    assert (tmp_path / "vectors.f32").is_file()
    got = np.asarray(LX.load_vectors(tmp_path))
    assert got.shape == (5, 8), "migration lost or duplicated rows"
    assert np.allclose(got[:3], old, atol=1e-6), "legacy rows corrupted"
    assert LX.read_meta(tmp_path)["n_rows"] == 5


def test_legacy_only_library_still_reads_without_migrating(tmp_path):
    old = _v39(2, seed=9)
    with (tmp_path / "vectors.npy").open("wb") as fh:
        np.save(fh, old)
    got = LX.load_vectors(tmp_path)
    assert got is not None and got.shape == (2, 8)
    assert not (tmp_path / "vectors.f32").exists()


def test_prune_rewrites_the_raw_store_and_drops_the_legacy_one(tmp_path):
    """A leftover vectors.npy would resurrect exactly the rows the user
    asked to remove if anything ever read it again."""
    real = tmp_path / "kept.jpg"
    real.write_bytes(b"x")
    entries = [("kept.jpg", str(real), 1.0),
               ("gone.jpg", str(tmp_path / "missing.jpg"), 1.0)]
    LX.append_run("r1", entries, _v39(2), library_dir=tmp_path)
    (tmp_path / "vectors.npy").write_bytes(b"stale legacy")

    res = LX.prune(tmp_path)
    assert res == {"removed": 1, "remaining": 1}
    assert not (tmp_path / "vectors.npy").exists()
    assert LX.load_vectors(tmp_path).shape == (1, 8)
    assert LX.read_meta(tmp_path)["n_rows"] == 1


def test_status_counts_the_raw_store_on_disk(tmp_path):
    LX.append_run("r1", _e39(5), _v39(5), library_dir=tmp_path)
    st = LX.status(tmp_path)
    assert st["n_photos"] == 5
    assert st["disk_bytes"] >= 5 * 8 * 4


# ── v2.40 — dedup only parses the run being appended ───────────────────
#
# After v2.39 made the vector write O(new), load_manifest was the last
# linear cost. Profiled on a 300,000-row manifest (41 MB): json.loads was
# 0.525s of 0.720s. The dedup key starts with run_id, so rows from other
# runs can never match an incoming entry — a substring pre-filter (0.013s
# for all 300k lines) keeps them out of the parser.
#   append 2,000 into a 300k library: 0.697s → 0.061s, and flat in
#   library size rather than linear.

def _seed(lib, rid, n, start=0, mtime=1.0):
    LX.append_run(rid,
                  [(f"{rid}-{i}.jpg", f"/p/{rid}-{i}.jpg", mtime)
                   for i in range(start, start + n)],
                  _v39(n, seed=abs(hash(rid)) % 999), library_dir=lib)


def test_seen_keys_matches_a_full_manifest_scan(tmp_path):
    """The fast path must agree with the naive one, run by run."""
    for rid, n in (("alpha", 6), ("beta", 4), ("gamma", 3)):
        _seed(tmp_path, rid, n)
    full = {LX.entry_key(e["run_id"], e["filename"], e.get("mtime", 0))
            for e in LX.load_manifest(tmp_path)}
    for rid in ("alpha", "beta", "gamma"):
        want = {k for k in full if k.split("\x1f")[0] == rid}
        assert LX._seen_keys_for_run(tmp_path, rid) == want, rid


def test_other_runs_are_not_parsed_into_the_key_set(tmp_path):
    _seed(tmp_path, "mine", 3)
    _seed(tmp_path, "theirs", 5)
    keys = LX._seen_keys_for_run(tmp_path, "mine")
    assert len(keys) == 3
    assert all(k.startswith("mine\x1f") for k in keys)


@pytest.mark.parametrize("rid", ["婚礼·二号", 'quo"te', "back\\slash",
                                 "with space"])
def test_needle_escaping_matches_how_the_manifest_was_written(tmp_path, rid):
    """The pre-filter is a raw substring test, so its escaping has to be
    byte-identical to what json.dumps wrote — non-ASCII, quotes and
    backslashes all included."""
    _seed(tmp_path, rid, 3)
    assert len(LX._seen_keys_for_run(tmp_path, rid)) == 3


def test_a_filename_containing_the_needle_is_not_a_false_match(tmp_path):
    """The pre-filter is a SUPERSET test on purpose; run_id is re-checked
    after parsing, so a filename that happens to contain the needle text
    costs one wasted parse and nothing else."""
    _seed(tmp_path, "victim", 2)
    LX.append_run("attacker",
                  [('x"run_id": "victim"y.jpg', "/p/evil.jpg", 9.0)],
                  _v39(1), library_dir=tmp_path)
    keys = LX._seen_keys_for_run(tmp_path, "victim")
    assert len(keys) == 2
    assert all("evil" not in k and 'x"run_id"' not in k for k in keys)


def test_reindexing_is_still_idempotent(tmp_path):
    entries = [(f"r{i}.jpg", f"/p/r{i}.jpg", 5.0) for i in range(6)]
    LX.append_run("r", entries, _v39(6), library_dir=tmp_path)
    again = LX.append_run("r", entries, _v39(6), library_dir=tmp_path)
    assert again["added"] == 0 and again["skipped"] == 6
    assert again["total"] == 6, "total must come from meta, not a re-parse"


def test_partial_overlap_adds_only_the_new_rows(tmp_path):
    old = [(f"o{i}.jpg", f"/p/o{i}.jpg", 5.0) for i in range(4)]
    LX.append_run("r", old, _v39(4), library_dir=tmp_path)
    mixed = old[:2] + [(f"n{i}.jpg", f"/p/n{i}.jpg", 7.0) for i in range(3)]
    res = LX.append_run("r", mixed, _v39(5), library_dir=tmp_path)
    assert (res["added"], res["skipped"]) == (3, 2)
    assert LX.status(tmp_path)["n_photos"] == 7


def test_changed_mtime_reindexes_that_photo(tmp_path):
    """mtime is in the key so an edited photo gets a fresh vector."""
    LX.append_run("r", [("a.jpg", "/p/a.jpg", 1.0)], _v39(1),
                  library_dir=tmp_path)
    res = LX.append_run("r", [("a.jpg", "/p/a.jpg", 2.0)], _v39(1),
                        library_dir=tmp_path)
    assert res["added"] == 1, "a re-scored photo must not be deduped away"


def test_torn_manifest_line_does_not_break_dedup(tmp_path):
    _seed(tmp_path, "r", 3)
    with (tmp_path / "manifest.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"run_id": "r", "filename": "torn.jpg"')   # no newline/close
    assert len(LX._seen_keys_for_run(tmp_path, "r")) == 3


def test_no_manifest_yet_is_an_empty_set(tmp_path):
    assert LX._seen_keys_for_run(tmp_path, "anything") == set()
