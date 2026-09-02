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


def test_the_catalogue_is_opened_read_only():
    """It is the photographer's working database and often the only copy."""
    import inspect
    src = inspect.getsource(lrcat.read_labels)
    assert "mode=ro" in src and "uri=True" in src


def test_a_missing_catalogue_raises_rather_than_returning_nothing():
    with pytest.raises(FileNotFoundError):
        lrcat.read_labels(Path(tempfile.mkdtemp()) / "nope.lrcat")
