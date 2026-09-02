"""v3.10 — read picks and ratings out of a Lightroom Classic catalogue.

`personalized.is_active()` needs 50+ corrections with TRUSTED provenance
before it will move a threshold, so a photographer who installs PixCull
gets the generic model for a long time. Imagen and Aftershoot both solve
this by seeding from work the photographer has already done. Most
professionals have years of it sitting in a `.lrcat`.

WHAT AN IMPORTED PICK IS NOT

It is not a PixCull correction. A flag in Lightroom can mean "this is the
best frame", and it can equally mean "this is the one the client bought",
"this is the one I retouched", or "this is what I flagged before lunch on
a job I no longer remember". The acts are different and the labels look
identical.

So imported labels carry their own provenance — ``lr_catalog`` — which is
deliberately NOT in `PersonalProfile.TRUSTED`. They can seed, describe
and be inspected. They cannot switch personalisation on by themselves.
That is the whole design: a cold start is worth having, and it is not
worth having at the price of the guard that exists because 608 rows of
the rule stack's own output once looked like ground truth.

WHAT THIS DOES ABOUT A SCHEMA IT CANNOT VERIFY

A `.lrcat` is a SQLite database, not the opaque binary the old deferral
note called it. But its schema is Adobe's, it changes between versions,
and there is no catalogue on this machine to test against. So the reader
introspects first and REFUSES with the names it was looking for when the
shape is not there, rather than guessing column names and returning an
empty result that reads like "you have no picks".
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

#: Provenance stamped on every label read from a catalogue. Deliberately
#: absent from `PersonalProfile.TRUSTED`.
PROVENANCE = "lr_catalog"

#: What Lightroom Classic stores. `pick` is 1.0 flagged, -1.0 rejected,
#: 0.0 unflagged; `rating` is 0-5 stars.
_IMAGES = "Adobe_images"
_FILES = "AgLibraryFile"
_NEEDED = {
    _IMAGES: ("id_local", "rating", "pick", "rootFile"),
    _FILES: ("id_local", "baseName", "extension"),
}


class UnsupportedCatalog(RuntimeError):
    """The catalogue is readable but is not shaped the way we expect."""


@dataclass(frozen=True)
class CatalogLabel:
    filename: str
    decision: str        # keep | cull  (never maybe — see below)
    pick: float
    rating: float

    @property
    def provenance(self) -> str:
        return PROVENANCE


def _check_schema(con: sqlite3.Connection) -> None:
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing_tables = [t for t in _NEEDED if t not in have]
    if missing_tables:
        raise UnsupportedCatalog(
            f"catalogue has no {', '.join(missing_tables)} table — this "
            f"reader expects a Lightroom Classic catalogue; tables found: "
            f"{sorted(have)[:12]}")
    for table, cols in _NEEDED.items():
        got = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        missing = [c for c in cols if c not in got]
        if missing:
            raise UnsupportedCatalog(
                f"{table} is missing {missing}; Adobe's schema differs "
                f"between versions and guessing would return an empty "
                f"result that reads like 'you have no picks'")


def decision_for(pick: float, rating: float, *,
                 keep_min_stars: float = 4.0) -> str | None:
    """Map a Lightroom flag/rating to keep or cull, or None for neither.

    Returns None generously. An unflagged 3-star frame is not a judgement
    — it is a frame the photographer never got round to, and importing it
    as `maybe` would manufacture an opinion out of an absence, which is
    the single failure mode this whole import has to avoid.
    """
    if pick is not None and float(pick) <= -1.0:
        return "cull"
    if pick is not None and float(pick) >= 1.0:
        return "keep"
    if rating is not None and float(rating) >= keep_min_stars:
        return "keep"
    return None


def read_labels(catalog: Path | str, *,
                keep_min_stars: float = 4.0) -> list[CatalogLabel]:
    """Every frame in the catalogue the photographer actually judged.

    Opened read-only. A catalogue is the photographer's working
    database — often the only copy — and this must not be able to write
    to it even by accident.
    """
    path = Path(catalog)
    if not path.exists():
        raise FileNotFoundError(str(path))
    uri = f"file:{path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        _check_schema(con)
        rows = con.execute(
            f"SELECT f.baseName, f.extension, i.pick, i.rating "
            f"FROM {_IMAGES} i JOIN {_FILES} f ON f.id_local = i.rootFile"
        ).fetchall()
    finally:
        con.close()

    out: list[CatalogLabel] = []
    for base, ext, pick, rating in rows:
        d = decision_for(pick or 0.0, rating or 0.0,
                         keep_min_stars=keep_min_stars)
        if d is None:
            continue
        name = f"{base}.{ext}" if ext else str(base)
        out.append(CatalogLabel(filename=name, decision=d,
                                pick=float(pick or 0.0),
                                rating=float(rating or 0.0)))
    return out
