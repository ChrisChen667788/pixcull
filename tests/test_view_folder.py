"""v2.99 — the two things PixCull knows that a flat folder destroys.

The studio path is: export, open on an iPad or a Mac, client sits beside
you and points. `pixcull export` wrote XMP sidecars or a ratings CSV —
useful to Lightroom, useless to a person with a client waiting.

So the photographer copies files by hand, and at that moment loses:

  which MOMENT a photograph belongs to
  which frames are the SAME moment, and which of them is best

The second is the whole conversation. "This one is lovely but her eyes
are closed — is there another?" PixCull knows there are four more from
that half-second and which is sharpest. Flattened, the answer becomes
"let me check back at the computer".
"""
import json
from pathlib import Path

import pytest

from pixcull.export.view_folder import (
    chapter_of, plan_layout, safe_component, write_view_folder,
)


@pytest.fixture()
def photo(tmp_path):
    from PIL import Image
    p = tmp_path / "src.jpg"
    Image.new("RGB", (1200, 800), (110, 130, 150)).save(p, "JPEG")
    return p


def _row(i, *, cluster=None, peak=False, moment="", scene="", dec="keep"):
    return {"filename": f"IMG_{i:04d}.jpg", "orig_filename": f"IMG_{i:04d}.jpg",
            "path": f"/src/IMG_{i:04d}.jpg", "decision": dec,
            "cluster_id": cluster if cluster is not None else "",
            "is_burst_peak": "True" if peak else "False",
            "wedding_moment": moment, "scene": scene,
            "datetime": f"2026-05-01 10:{i:02d}:00"}


# ----------------------------------------------------------- the grouping


def test_a_burst_becomes_a_folder_with_the_best_frame_first():
    rows = [_row(1, cluster="c1", peak=False, moment="toast"),
            _row(2, cluster="c1", peak=True, moment="toast"),
            _row(3, cluster="c1", peak=False, moment="toast")]
    plan = plan_layout(rows)
    entries = plan.chapters["敬酒"]
    assert len(entries) == 3
    rels = [e[0] for e in entries]
    assert all("连拍" in r for r in rels)
    first = sorted(rels)[0]
    assert "最佳" in first
    assert "IMG_0002" in first, "the peak is not the frame that sorts first"


def test_a_single_photograph_does_not_get_a_burst_folder():
    plan = plan_layout([_row(1, moment="toast")])
    rel = plan.chapters["敬酒"][0][0]
    assert "/" not in rel
    assert plan.singles == 1 and plan.bursts == 0


def test_the_moment_wins_over_the_scene():
    """"敬酒" tells a photographer more than "人像" while they are
    standing next to the client."""
    assert chapter_of({"wedding_moment": "toast", "scene": "portrait"}) == "敬酒"
    assert chapter_of({"scene": "portrait"}) == "人像"


def test_a_photograph_with_neither_still_lands_somewhere():
    """An empty chapter puts files in the root and loses the grouping
    for everything else in the folder."""
    assert chapter_of({}) == "其他"
    assert chapter_of({"wedding_moment": "", "scene": ""}) == "其他"


def test_an_unknown_moment_is_kept_rather_than_dropped():
    assert chapter_of({"wedding_moment": "cake-cutting"}) == "cake-cutting"


def test_shooting_order_survives_the_filenames():
    """Finder sorts by name. Without the sequence prefix the client is
    shown the afternoon before the morning.

    The camera numbers here run OPPOSITE to the shooting times — a card
    swap, or a second body. A fixture where the two agree cannot tell a
    datetime sort from a filename sort, and the first version of this
    test had exactly that: reversing the sort key left it green.
    """
    rows = [dict(_row(1, moment="toast"), datetime="2026-05-01 18:00:00"),
            dict(_row(5, moment="toast"), datetime="2026-05-01 12:00:00"),
            dict(_row(9, moment="toast"), datetime="2026-05-01 09:00:00")]
    rels = sorted(e[0] for e in plan_layout(rows).chapters["敬酒"])
    assert "IMG_0009" in rels[0], (
        f"sorted by name, not by when it was taken: {rels}")
    assert "IMG_0005" in rels[1]
    assert "IMG_0001" in rels[2]


# ------------------------------------------------------------- the writing


def test_names_cannot_escape_the_folder():
    for bad in ("../../etc/passwd", "a/b.jpg", "", "...", "con"):
        s = safe_component(bad)
        assert "/" not in s and s not in ("", ".", "..")


def test_a_missing_original_is_reported(tmp_path, photo):
    out = tmp_path / "ipad"
    res = write_view_folder(
        [_row(1, moment="toast"), _row(2, moment="toast")], out,
        resolve=lambda f: photo if f == "IMG_0001.jpg" else None)
    assert res["written"] == 1
    assert res["missing"] == ["IMG_0002.jpg"], \
        "a folder quietly short of frames is discovered in front of the client"


def test_the_originals_are_copied_not_linked(tmp_path, photo):
    """This folder goes onto an iPad, into Files, onto a stick. A symlink
    survives none of those."""
    out = tmp_path / "ipad"
    write_view_folder([_row(1, moment="toast")], out, resolve=lambda _f: photo)
    made = next(out.rglob("*.jpg"))
    assert not made.is_symlink()
    assert made.read_bytes() == photo.read_bytes()


def test_downsizing_is_opt_in(tmp_path, photo):
    from PIL import Image
    out = tmp_path / "ipad"
    write_view_folder([_row(1, moment="toast")], out,
                      resolve=lambda _f: photo, max_width=600)
    assert Image.open(next(out.rglob("*.jpg"))).width == 600


def test_a_portrait_frame_is_not_sent_sideways(tmp_path):
    """Only on the resize path — a plain copy keeps the EXIF flag, and
    every viewer honours it. Resizing without transposing does not."""
    from PIL import Image
    src = tmp_path / "p.jpg"
    ex = Image.Exif(); ex[274] = 6
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(src, "JPEG", exif=ex)
    out = tmp_path / "ipad"
    write_view_folder([_row(1, moment="toast")], out,
                      resolve=lambda _f: src, max_width=600)
    im = Image.open(next(out.rglob("*.jpg")))
    assert im.height > im.width


def test_only_the_keepers_by_default():
    rows = [_row(1, moment="toast"), _row(2, moment="toast", dec="cull")]
    plan = plan_layout(rows)
    assert plan.total == 1


def test_the_index_records_what_was_written(tmp_path, photo):
    out = tmp_path / "ipad"
    write_view_folder([_row(1, cluster="c", peak=True, moment="toast"),
                       _row(2, cluster="c", moment="toast"),
                       _row(3, moment="ceremony")],
                      out, resolve=lambda _f: photo)
    idx = json.loads((out / "_目录.json").read_text(encoding="utf-8"))
    assert idx["bursts"] == 1 and idx["singles"] == 1
    assert idx["chapters"] == {"仪式": 1, "敬酒": 2}
