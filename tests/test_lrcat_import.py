"""v3.10 — seed a cold start from the photographer's own catalogue, without
letting an imported flag pretend to be a correction.

`is_active()` needs 50+ TRUSTED corrections, so a new user gets the
generic model for a long time.  Most professionals have years of judged
work sitting in a `.lrcat`.

The danger is not reading it.  It is that a Lightroom flag and a PixCull
correction look identical and are not the same act: a flag can mean "the
best frame", "the one the client bought", "the one I retouched", or "what
I flagged before lunch".  Nothing about the label says which.
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from pixcull.io import lrcat
from pixcull.scoring.personalized import PersonalProfile


def _catalog(rows, *, schema=True) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "Photos.lrcat"
    con = sqlite3.connect(p)
    if schema:
        con.execute("CREATE TABLE AgLibraryFile "
                    "(id_local INTEGER PRIMARY KEY, baseName TEXT, "
                    "extension TEXT)")
        con.execute("CREATE TABLE Adobe_images "
                    "(id_local INTEGER PRIMARY KEY, rating REAL, "
                    "pick REAL, rootFile INTEGER)")
        for i, (base, ext, pick, rating) in enumerate(rows, 1):
            con.execute("INSERT INTO AgLibraryFile VALUES (?,?,?)",
                        (i, base, ext))
            con.execute("INSERT INTO Adobe_images VALUES (?,?,?,?)",
                        (i, rating, pick, i))
    else:
        con.execute("CREATE TABLE something_else (x INTEGER)")
    con.commit()
    con.close()
    return p


def test_imported_labels_cannot_switch_personalisation_on():
    """The whole design. A cold start is worth having; it is not worth
    the guard that exists because 608 rows of the rule stack's own output
    once looked like ground truth."""
    assert lrcat.PROVENANCE not in PersonalProfile.TRUSTED
    kw = dict(user_id="local", n_annotations=5000, keep_rate=0.5,
              cull_rate=0.5, keep_threshold_shift=0.0,
              axis_keep_means={}, axis_cull_means={},
              most_cared_axis="technical")
    assert PersonalProfile(label_provenance=lrcat.PROVENANCE,
                           **kw).is_active() is False
    # The same profile with a trusted provenance does activate, so the
    # assertion above is about the provenance and not about the shape.
    assert PersonalProfile(label_provenance="blind", **kw).is_active() is True


def test_an_unflagged_middling_frame_is_not_a_judgement():
    """Importing it as `maybe` would manufacture an opinion out of an
    absence — the one failure this import has to avoid."""
    assert lrcat.decision_for(0.0, 3.0) is None
    assert lrcat.decision_for(0.0, 0.0) is None


def test_a_reject_flag_outranks_a_high_rating():
    """A five-star frame the photographer later rejected is a reject."""
    assert lrcat.decision_for(-1.0, 5.0) == "cull"


def test_flag_and_high_rating_both_read_as_keep():
    assert lrcat.decision_for(1.0, 0.0) == "keep"
    assert lrcat.decision_for(0.0, 5.0) == "keep"


def test_reading_a_catalogue_returns_only_judged_frames():
    p = _catalog([("DSC_0001", "NEF", 1.0, 0.0),      # flagged
                  ("DSC_0002", "NEF", -1.0, 0.0),     # rejected
                  ("DSC_0003", "NEF", 0.0, 3.0),      # untouched
                  ("DSC_0004", "NEF", 0.0, 5.0)])     # five stars
    got = {l.filename: l.decision for l in lrcat.read_labels(p)}
    assert got == {"DSC_0001.NEF": "keep", "DSC_0002.NEF": "cull",
                   "DSC_0004.NEF": "keep"}


def test_every_imported_label_carries_the_catalogue_provenance():
    p = _catalog([("A", "CR3", 1.0, 0.0)])
    assert all(l.provenance == lrcat.PROVENANCE for l in lrcat.read_labels(p))


def test_a_catalogue_of_another_shape_is_refused_not_reported_as_empty():
    """Guessing column names and returning [] reads to the user as 'you
    have no picks', which is a different and much worse answer than 'this
    catalogue is not the shape I know'."""
    p = _catalog([], schema=False)
    with pytest.raises(lrcat.UnsupportedCatalog) as exc:
        lrcat.read_labels(p)
    assert "Adobe_images" in str(exc.value)


def test_a_missing_column_is_named_in_the_refusal():
    d = Path(tempfile.mkdtemp())
    p = d / "P.lrcat"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE AgLibraryFile (id_local INTEGER, baseName TEXT)")
    con.execute("CREATE TABLE Adobe_images (id_local INTEGER, rating REAL)")
    con.commit()
    con.close()
    with pytest.raises(lrcat.UnsupportedCatalog) as exc:
        lrcat.read_labels(p)
    assert "extension" in str(exc.value) or "pick" in str(exc.value)


def test_the_catalogue_is_never_opened_for_writing(tmp_path):
    """It is the photographer's working database and often the only copy.

    v3.79 — this used to assert `"mode=ro" in src`, which is a mechanism,
    not the property. And the mechanism was wrong: a read-only SQLite
    connection cannot open a WAL database, which is what every real
    Lightroom catalogue is, so the reader worked on every fixture here
    and on no genuine catalogue at all.

    Asserting the mechanism made the test pass while the thing it stood
    for was broken, and then blocked the fix. The property is that the
    photographer's file does not change and is not connected to; that is
    what the three tests at the end of this file check, and this one now
    checks the source cannot quietly go back.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(lrcat.read_labels)))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "connect"):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            assert "path" not in names, (
                "read_labels connects to the photographer's own file")


def test_a_missing_catalogue_raises_rather_than_returning_nothing():
    with pytest.raises(FileNotFoundError):
        lrcat.read_labels(Path(tempfile.mkdtemp()) / "nope.lrcat")


# ── v3.79 — a real catalogue is in WAL mode, and read-only could not open it ──

def _wal_catalogue(tmp_path: Path) -> Path:
    """A fixture in the journal mode every real catalogue uses.

    Every other fixture in this file is created in SQLite's default
    rollback mode, so the suite was self-consistent and silent about the
    one property that made the reader fail on the genuine article.
    """
    p = tmp_path / "wal.lrcat"
    con = sqlite3.connect(str(p))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE Adobe_images "
                "(id_local INTEGER, rating REAL, pick REAL, rootFile INTEGER)")
    con.execute("CREATE TABLE AgLibraryFile "
                "(id_local INTEGER, baseName TEXT, extension TEXT)")
    con.execute("INSERT INTO AgLibraryFile VALUES (1, 'IMG_1', 'JPG')")
    con.execute("INSERT INTO Adobe_images VALUES (1, 5.0, 0.0, 1)")
    con.commit()
    con.close()
    # Lightroom closes cleanly and leaves no `-wal`/`-shm` beside the
    # catalogue, and that is the state the reader failed on: with the
    # sidecars still present a read-only connection opens fine, so a
    # fixture that leaves them behind tests the easy case and stays
    # silent about the real one. Which is how the original fault
    # survived — every fixture here was in rollback mode, and this one
    # would have been in WAL-with-sidecars.
    for side in ("-wal", "-shm"):
        p.with_name(p.name + side).unlink(missing_ok=True)
    return p


def test_a_wal_catalogue_can_be_read_while_lightroom_holds_it(tmp_path):
    """The defect `docs/OPEN-ITEMS.md` ask 4 existed to find.

    Lightroom Classic keeps its catalogue in WAL. A read-only SQLite
    connection cannot create the `-shm` file WAL needs, so an open of a
    real catalogue failed with "unable to open database file" while every
    fixture here passed.

    The holder connection is the point. A catalogue closed cleanly is
    fully checkpointed and a read-only open of it succeeds — so a fixture
    that just builds one and closes it tests the easy case and stays
    silent about the real one. With the application still attached there
    is a populated `-wal`, which is the state a photographer's catalogue
    is in whenever Lightroom is running, and the state this failed on.
    """
    cat = _wal_catalogue(tmp_path)
    holder = sqlite3.connect(str(cat))
    holder.execute("INSERT INTO AgLibraryFile VALUES (2, 'IMG_2', 'JPG')")
    holder.execute("INSERT INTO Adobe_images VALUES (2, 5.0, 0.0, 2)")
    holder.commit()                     # in the -wal, not yet checkpointed
    try:
        assert cat.with_name(cat.name + "-wal").exists(), (
            "no -wal beside the catalogue, so this tests the easy case")
        labels = lrcat.read_labels(cat)
        assert sorted(l.filename for l in labels) == ["IMG_1.JPG", "IMG_2.JPG"], (
            "the reader missed a frame that lives in the -wal — reading the "
            "main file alone gives a stale catalogue")
        assert all(l.decision == "keep" for l in labels)
    finally:
        holder.close()


def test_reading_does_not_modify_the_catalogue(tmp_path):
    """Why it was opened read-only in the first place, kept as a property
    rather than as a connection flag: a catalogue is often the
    photographer's only copy."""
    import hashlib
    cat = _wal_catalogue(tmp_path)
    snap = lambda: (cat.stat().st_size,
                    hashlib.sha256(cat.read_bytes()).hexdigest())
    before = snap()
    lrcat.read_labels(cat)
    assert snap() == before, "reading the catalogue changed it"


def test_reading_leaves_no_sidecars_beside_the_original(tmp_path):
    """Opening a WAL database read-write creates `-shm` and `-wal` beside
    it. Next to the photographer's catalogue that is litter in a folder
    Lightroom watches, so the work happens on a copy."""
    cat = _wal_catalogue(tmp_path)     # already leaves none
    lrcat.read_labels(cat)
    strays = sorted(p.name for p in tmp_path.iterdir()
                    if p.name.endswith(("-wal", "-shm")))
    assert not strays, f"left {strays} beside the catalogue"


def test_the_reader_never_connects_to_the_original(tmp_path):
    """Stated against the source as well, because the property is what
    matters: a later change could satisfy the tests above while opening
    the original read-write and merely not writing to it."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(lrcat.read_labels)))
    connects = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "connect"]
    assert connects, "read_labels no longer opens a database at all"
    for call in connects:
        names = {n.id for n in ast.walk(call) if isinstance(n, ast.Name)}
        assert "path" not in names, (
            "read_labels connects to `path`, the photographer's own file. "
            "Copy first and connect to the copy.")
