"""v2.87 — a proof sheet the client opens, with no account anywhere.

The largest product gap the 2026 Q3 competitive refresh found: between
the photographer's cull and the client's own selection there is a step
PixCull did not address, and every Chinese studio product does.

This is the smallest thing that closes it and deliberately not a
delivery platform. The tests below are mostly about what must NOT
happen: the original leaking out, a photograph vanishing quietly, a
filename escaping the output folder.
"""
from pathlib import Path

import pytest

from pixcull.export.proof_sheet import (
    PROOF_WIDTH, build_items, render_gallery, safe_slug, write_proof_sheet,
)


@pytest.fixture()
def src_photo(tmp_path):
    from PIL import Image
    p = tmp_path / "src.jpg"
    Image.new("RGB", (2400, 1600), (90, 120, 160)).save(p, "JPEG", quality=90)
    return p


def _rows(*names, decision="keep"):
    return [{"filename": n, "decision": decision, "orig_filename": n}
            for n in names]


# ------------------------------------------------------------ the names


@pytest.mark.parametrize("bad", [
    "../../etc/passwd", "one/a.jpg", "/abs/path.jpg", "..", "",
    "a\x00b.jpg", "C:/win.jpg",
])
def test_no_name_can_escape_the_output_folder(bad):
    """v2.76 made photo names relative paths, so they legitimately
    contain '/'. Writing one straight into the folder would create
    directories, or climb out of it."""
    s = safe_slug(bad)
    assert "/" not in s and "\\" not in s and "\x00" not in s
    assert s not in ("", ".", "..")
    assert not s.startswith(".")


def test_a_photo_does_not_arrive_named_twice():
    """The derivative is always a JPEG and the caller appends '.jpg'."""
    assert safe_slug("IMG_0042.jpg") == "IMG_0042"
    assert safe_slug("shot.CR3") == "shot"


def test_two_names_that_slug_alike_still_get_two_files():
    """Names that differ only in characters the slug replaces.
    "one/a.jpg" and "two/a.jpg" do NOT collide — they become one_a and
    two_a — so testing with those exercises nothing. These do."""
    assert safe_slug("a b.jpg") == safe_slug("a+b.jpg") == "a_b"
    items = build_items(_rows("a b.jpg", "a+b.jpg", "a%b.jpg"))
    rels = [i.rel for i in items]
    assert len(set(rels)) == 3, f"three photographs write to {rels}"


def test_the_watermark_scales_with_the_image(tmp_path):
    """PIL's default is ~11px. Tiled across a 1024px proof that is a
    mark a client can see and not read."""
    from PIL import Image, ImageDraw
    from pixcull.export.proof_sheet import _stamp
    im = Image.new("RGB", (1024, 683), (90, 120, 160))
    _stamp(im, ImageDraw, "ZHANG WEDDING PROOF")
    px = im.convert("RGB").load()
    rows_touched = sum(
        1 for y in range(0, 683, 2)
        if any(abs(px[x, y][0] - 90) > 25 for x in range(0, 1024, 4)))
    assert rows_touched > 40, (
        f"the mark occupies {rows_touched} sampled rows; an 11px font "
        "across a 1024px image touches almost none")


def test_the_client_sees_the_name_the_photographer_knows():
    """The disambiguated name is an internal key. A client reading
    'one_a' where the photographer said 'a.jpg' cannot reconcile the two."""
    rows = [{"filename": "one/a.jpg", "orig_filename": "a.jpg",
             "decision": "keep"}]
    assert build_items(rows)[0].label == "a.jpg"


# ---------------------------------------------------------- the pictures


def test_the_original_never_reaches_the_client(tmp_path, src_photo):
    out = tmp_path / "proof"
    res = write_proof_sheet(_rows("a.jpg"), out,
                            resolve=lambda _f: src_photo, title="PROOF")
    assert res["written"] == 1
    made = list((out / "photos").glob("*.jpg"))
    assert made
    assert made[0].read_bytes() != src_photo.read_bytes()
    from PIL import Image
    assert Image.open(made[0]).width == PROOF_WIDTH, \
        "a full-resolution frame went out as a proof"


def test_the_derivative_carries_a_watermark(tmp_path, src_photo):
    """A flat source, so any pixel that differs from the fill is the mark.
    The first version used PIL's 11px default font on a 1024px image and
    produced something visible and unreadable, which is texture."""
    from PIL import Image
    out = tmp_path / "proof"
    write_proof_sheet(_rows("a.jpg"), out, resolve=lambda _f: src_photo,
                      title="ZHANG WEDDING")
    im = Image.open(next((out / "photos").glob("*.jpg"))).convert("RGB")
    px = im.load()
    marked = sum(1 for y in range(0, im.height, 3) for x in range(0, im.width, 3)
                 if abs(px[x, y][0] - 90) > 25)
    total = len(range(0, im.height, 3)) * len(range(0, im.width, 3))
    assert marked > total * 0.01, \
        f"only {marked}/{total} sampled pixels differ from the fill"


def test_a_missing_original_is_reported_not_skipped(tmp_path, src_photo):
    """A proof sheet quietly missing four photographs is the worst
    possible way for this to fail — the client chooses from what they
    were sent and nobody knows what they were not."""
    out = tmp_path / "proof"
    res = write_proof_sheet(
        _rows("here.jpg", "gone.jpg"), out,
        resolve=lambda f: src_photo if f == "here.jpg" else None)
    assert res["written"] == 1
    assert res["missing"] == ["gone.jpg"]


def test_a_frame_that_could_not_be_written_is_not_in_the_gallery(tmp_path, src_photo):
    out = tmp_path / "proof"
    write_proof_sheet(_rows("here.jpg", "gone.jpg"), out,
                      resolve=lambda f: src_photo if f == "here.jpg" else None)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "here.jpg" in html
    assert "gone.jpg" not in html, \
        "the gallery offers a photograph whose file was never written"


# ----------------------------------------------------------- the gallery


def test_the_gallery_needs_nothing_from_the_network():
    """The client may open this from a USB stick on a train."""
    html = render_gallery(build_items(_rows("a.jpg", "b.jpg")), title="T")
    assert "http://" not in html and "https://" not in html


def test_only_the_keepers_go_by_default():
    rows = _rows("k.jpg") + _rows("c.jpg", decision="cull")
    assert [i.filename for i in build_items(rows)] == ["k.jpg"]


def test_a_title_cannot_inject_markup():
    html = render_gallery(build_items(_rows("a.jpg")),
                          title='</title><script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in html


def test_a_webhook_is_optional_and_absent_when_unset():
    html = render_gallery(build_items(_rows("a.jpg")), title="T")
    assert 'WEBHOOK = ""' in html
