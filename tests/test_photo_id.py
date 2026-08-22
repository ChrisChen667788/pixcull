"""v2.76 — a photograph must have exactly one name, and that name must
address exactly that photograph.

The defect these guard: 5,069 files scanned, 4,295 distinct basenames,
and every URL, index and manifest keyed on the basename. 774 originals
were addressable only by a name that resolved to somebody else's pixels.
Nothing errored — the grid simply showed one photo twice and never showed
the other, which is why it survived seventeen versions.
"""
import ast
import json
from pathlib import Path

import pytest

from pixcull.photo_id import apply_unique_names, migrate_legacy_annotations

SRC = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "serve_app.py"


def _rows(*pairs):
    return [{"filename": n, "path": p} for n, p in pairs]


def _code_only(path: Path) -> str:
    """Source with comments and docstrings removed.

    Lints in this repo have three times matched their own prose and
    reported a clean bill of health for code that was still broken.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        out.append(stripped)
    body = "\n".join(out)
    for d in docs:
        body = body.replace(d, "")
    return body


# ---------------------------------------------------------------- naming


def test_every_name_is_unique_after_disambiguation():
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"),
                 ("a.jpg", "/L/three/a.jpg"), ("b.jpg", "/L/b.jpg"))
    apply_unique_names(rows)
    names = [r["filename"] for r in rows]
    assert len(set(names)) == len(names), names


def test_disambiguation_is_symmetric():
    """Neither colliding file keeps the bare name.

    Letting one keep it makes the rename look like a property of the
    other file, and makes 'a.jpg' mean different things in different
    runs depending on scan order.
    """
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"))
    apply_unique_names(rows)
    assert "a.jpg" not in [r["filename"] for r in rows]


def test_a_run_without_collisions_is_untouched():
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("b.jpg", "/L/two/b.jpg"))
    before = [dict(r) for r in rows]
    assert apply_unique_names(rows) == 0
    assert rows == before


def test_naming_does_not_depend_on_scan_order():
    """Re-scanning a library must not re-key it.

    A counter-based scheme ('a.jpg', 'a_2.jpg') names files by the order
    they happened to be walked, so the next scan silently reassigns the
    names every annotation is filed under.
    """
    pairs = [("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"),
             ("a.jpg", "/L/three/a.jpg")]
    fwd = _rows(*pairs)
    rev = _rows(*reversed(pairs))
    apply_unique_names(fwd)
    apply_unique_names(rev)
    assert {r["path"]: r["filename"] for r in fwd} == \
           {r["path"]: r["filename"] for r in rev}


def test_original_name_is_preserved():
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"))
    apply_unique_names(rows)
    assert all(r["orig_filename"] == "a.jpg" for r in rows)


def test_same_file_listed_twice_is_not_a_collision():
    """One path, two rows is a duplicate row, not two photographs."""
    rows = _rows(("a.jpg", "/L/a.jpg"), ("a.jpg", "/L/a.jpg"))
    assert apply_unique_names(rows) == 0


# ------------------------------------------------------------ resolution


def test_resolver_is_not_handed_a_stripped_name():
    """``_resolve_image_source(run, Path(fn).name)`` undoes the rename.

    The URL carries 'one/a.jpg'; taking .name throws the 'one/' away and
    lands back on the colliding key, so the disambiguation would change
    the label under the photo and nothing else.
    """
    assert "Path(fn).name)" not in _code_only(SRC)


def test_scores_path_map_indexes_every_row(tmp_path):
    """The authoritative resolver must not lose a file per collision.

    Deliberately behavioural, not a source lint: the first version of
    this asserted "apply_unique_names" appeared in the function body,
    which the import line satisfies on its own — deleting the actual
    call left the test green.
    """
    from pixcull.report.serve_app import _scores_path_map

    out = tmp_path / "output"
    out.mkdir()
    made = []
    for d in ("one", "two", "three"):
        sub = tmp_path / d
        sub.mkdir()
        f = sub / "a.jpg"
        f.write_bytes(b"\xff\xd8" + d.encode())
        made.append(f)
    lone = tmp_path / "b.jpg"
    lone.write_bytes(b"\xff\xd8b")
    made.append(lone)

    with (out / "scores.csv").open("w", encoding="utf-8", newline="") as fh:
        fh.write("filename,path\n")
        for f in made:
            fh.write(f"{f.name},{f}\n")

    idx = _scores_path_map(out)
    assert len(idx) == len(made), \
        f"{len(made)} files indexed to {len(idx)} keys — the missing ones " \
        f"are addressable only by a name that returns another file"
    assert sorted(str(v) for v in idx.values()) == sorted(str(f) for f in made)


@pytest.mark.parametrize("bad", [
    "../etc/passwd", "a/../../etc/passwd", "/etc/passwd",
    "..", "a/..", "C:/Windows/win.ini", "a\\..\\..\\b", "", "a\x00b",
])
def test_traversal_guard_rejects(bad):
    from pixcull.report.serve_app import _safe_photo_name
    assert _safe_photo_name(bad) is False


@pytest.mark.parametrize("ok", [
    "a.jpg", "one/a.jpg", "shoot 2024/raw/a.jpg", "a..b.jpg", "..a.jpg",
])
def test_traversal_guard_allows_real_names(ok):
    from pixcull.report.serve_app import _safe_photo_name
    assert _safe_photo_name(ok) is True


def test_guard_is_actually_called_on_url_facing_routes():
    code = _code_only(SRC)
    for fn in ("_serve_image", "_serve_face_crop"):
        i = code.find(f"def {fn}")
        assert i > 0, fn
        seg = code[i:i + 6000]
        j = seg.find("_resolve_image_source")
        assert j > 0, fn
        assert "_safe_photo_name" in seg[:j], \
            f"{fn} resolves a URL-supplied name with no traversal guard"


# ------------------------------------------------------------ migration


def test_legacy_annotation_follows_the_photo_that_was_shown():
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"))
    apply_unique_names(rows)
    idx = {"a.jpg": {"label": "keep"}}
    out, migrated, dropped = migrate_legacy_annotations(
        idx, rows, {"a.jpg": "/L/two/a.jpg"})
    assert (migrated, dropped) == (1, 0)
    assert out["two/a.jpg"]["label"] == "keep"
    assert "one/a.jpg" not in out
    assert "a.jpg" not in out


def test_unattributable_annotation_is_counted_not_spread():
    """With no manifest the annotation genuinely does not say which file.

    Copying it onto both attaches a human's keep verdict to a photograph
    they never looked at.
    """
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"))
    apply_unique_names(rows)
    out, migrated, dropped = migrate_legacy_annotations(
        {"a.jpg": {"label": "keep"}}, rows, None)
    assert (migrated, dropped) == (0, 1)
    assert [k for k in out if k.endswith("a.jpg")] == ["a.jpg"]


def test_migration_leaves_uncollided_annotations_alone():
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"),
                 ("b.jpg", "/L/b.jpg"))
    apply_unique_names(rows)
    out, _m, _d = migrate_legacy_annotations(
        {"b.jpg": {"label": "cull"}}, rows, {"a.jpg": "/L/one/a.jpg"})
    assert out["b.jpg"]["label"] == "cull"


def test_migration_is_a_noop_without_renames():
    rows = _rows(("a.jpg", "/L/a.jpg"))
    apply_unique_names(rows)
    idx = {"a.jpg": {"label": "keep"}}
    out, m, d = migrate_legacy_annotations(idx, rows, {"a.jpg": "/L/a.jpg"})
    assert (out, m, d) == (idx, 0, 0)


# -------------------------------------------------------------- the run


def test_no_photograph_is_unreachable_after_disambiguation(tmp_path):
    """The acceptance check, on the shape that produced the defect."""
    from pixcull.scoring.identity_audit import audit_rows
    rows = _rows(*[(f"IMG_{i%40:03d}.jpg", f"/L/d{i//40}/IMG_{i%40:03d}.jpg")
                   for i in range(200)])
    assert audit_rows(rows).n_unreachable > 0
    apply_unique_names(rows)
    assert audit_rows(rows).n_unreachable == 0


def test_uncollided_files_keep_their_bare_name_in_a_mixed_run():
    """Only the ambiguous names change.

    Renaming every file in a library that merely contains some
    duplicates re-keys the whole run: every annotation, every sidecar
    and every saved selection is filed under a name that no longer
    exists. The blast radius has to stay the size of the defect.
    """
    rows = _rows(("a.jpg", "/L/one/a.jpg"), ("a.jpg", "/L/two/a.jpg"),
                 ("b.jpg", "/L/one/b.jpg"), ("c.jpg", "/L/two/c.jpg"))
    apply_unique_names(rows)
    kept = {r["path"]: r["filename"] for r in rows}
    assert kept["/L/one/b.jpg"] == "b.jpg"
    assert kept["/L/two/c.jpg"] == "c.jpg"


def test_names_stay_unique_when_the_path_is_missing():
    """A row with no recorded path cannot be told apart by its path.

    It still must not end up sharing a name with another row, or the
    URL for one of them serves the other — the whole defect, reproduced
    on the rows least likely to be noticed.
    """
    rows = _rows(("a.jpg", ""), ("a.jpg", ""), ("a.jpg", "/L/one/a.jpg"))
    apply_unique_names(rows)
    names = [r["filename"] for r in rows]
    assert len(set(names)) == 3, names


def test_resolution_survives_a_lossy_manifest(tmp_path):
    """manifest.json holds one entry per basename — it cannot describe
    a run with duplicate names, and 453 of 5,069 files were missing from
    the one that exposed this. The CSV's ``path`` column can, so it has
    to be consulted first rather than as a fallback.

    ``source_dir`` is deliberately absent: with it, the rglob fallback
    masks the precedence and the test passes either way.
    """
    from pixcull.report.serve_app import _resolve_image_source

    out = tmp_path / "output"
    out.mkdir()
    files = {}
    for d in ("one", "two", "three"):
        sub = tmp_path / d
        sub.mkdir()
        f = sub / "a.jpg"
        f.write_bytes(b"\xff\xd8" + d.encode())
        files[f"{d}/a.jpg"] = f

    with (out / "scores.csv").open("w", encoding="utf-8", newline="") as fh:
        fh.write("filename,path\n")
        for f in files.values():
            fh.write(f"a.jpg,{f}\n")
    # what the old writer produced: last one wins, the other two vanish
    (out / "manifest.json").write_text(
        json.dumps({"a.jpg": str(files["three/a.jpg"])}), encoding="utf-8")

    run = {"mode": "scan", "output_dir": str(out)}
    for name, expected in files.items():
        got = _resolve_image_source(run, name)
        assert got is not None, f"{name} resolves to nothing"
        assert Path(got).read_bytes() == expected.read_bytes(), \
            f"{name} served another photograph's pixels"
