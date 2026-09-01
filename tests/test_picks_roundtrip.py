"""v2.98 — the client refers to a photograph by something; over WeChat
that something can only be the pixels.

A filename in a caption is gone the moment the album reorders, the
client screenshots a subset, forwards three to their mother, or two of
the sends fail. Position is not an identifier. A number burned into the
frame is, and it survives every one of those.

Measured: at WeChat's typical treatment — long edge to 1080, re-encoded
at q=50, then shown as a ~220 px chat thumbnail — the badge is still
readable.

The other half is the return path. "第3张、第7张,还有 3-4" has to become
filenames, and the mapping must come from the manifest written when
those pictures were exported. Never recomputed: cull one more frame and
every number after it shifts, while the client is still holding the old
ones.
"""
import json
from pathlib import Path

import pytest

from pixcull.export.proof_sheet import parse_picks, write_proof_sheet


@pytest.fixture()
def photo(tmp_path):
    from PIL import Image
    p = tmp_path / "src.jpg"
    Image.new("RGB", (1600, 1067), (140, 150, 160)).save(p, "JPEG", quality=92)
    return p


def _rows(n):
    return [{"filename": f"IMG_{i:03d}.jpg", "decision": "keep",
             "orig_filename": f"IMG_{i:03d}.jpg"} for i in range(n)]


# --------------------------------------------------------- the burned number


def test_the_number_is_in_the_pixels(tmp_path, photo):
    """Not in a caption, not in the filename — in the picture."""
    from PIL import Image
    out = tmp_path / "proof"
    write_proof_sheet(_rows(3), out, resolve=lambda _f: photo, title="T")
    im = Image.open(next((out / "photos").glob("*.jpg"))).convert("RGB")
    px = im.load()
    # The badge is a black plate in the top-left inset.
    dark = sum(1 for y in range(4, 110, 2) for x in range(4, 110, 2)
               if sum(px[x, y]) < 180)
    assert dark > 200, "no dark badge found in the top-left corner"


def test_the_badge_survives_wechat(tmp_path, photo):
    """Resize to 1080 and re-encode at q=50 — the badge must still be
    a solid dark block, not mush."""
    import io
    from PIL import Image
    out = tmp_path / "proof"
    write_proof_sheet(_rows(1), out, resolve=lambda _f: photo, title="T")
    im = Image.open(next((out / "photos").glob("*.jpg")))
    w = 1080
    r = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    r.save(buf, "JPEG", quality=50)
    back = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    px = back.load()
    dark = sum(1 for y in range(4, 90, 2) for x in range(4, 90, 2)
               if sum(px[x, y]) < 200)
    assert dark > 150


def test_numbering_can_be_turned_off(tmp_path, photo):
    from PIL import Image
    out = tmp_path / "proof"
    write_proof_sheet(_rows(1), out, resolve=lambda _f: photo, title="T",
                      number=False)
    im = Image.open(next((out / "photos").glob("*.jpg"))).convert("RGB")
    px = im.load()
    dark = sum(1 for y in range(4, 110, 2) for x in range(4, 110, 2)
               if sum(px[x, y]) < 180)
    assert dark < 50


# ------------------------------------------------------------ the manifest


def test_the_manifest_maps_number_to_filename(tmp_path, photo):
    out = tmp_path / "proof"
    res = write_proof_sheet(_rows(4), out, resolve=lambda _f: photo, title="T")
    man = json.loads((out / "picks_manifest.json").read_text(encoding="utf-8"))
    assert man["n"] == 4
    assert man["by_index"]["1"] == "IMG_000.jpg"
    assert man["by_index"]["4"] == "IMG_003.jpg"
    assert man["digest"] == res["digest"]


def test_the_digest_changes_when_the_exported_set_does(tmp_path, photo):
    """A reply carries the numbers from ONE export. If the set changed,
    the digest is how anyone can tell.

    Same COUNT, different photographs — the case that matters and the
    one a lazy digest passes. Comparing four rows against five is not a
    test: a digest that hashes a constant per item still changes when
    the number of items does, and it is exactly the shift-by-one
    re-export this field exists to catch.
    """
    a = write_proof_sheet(_rows(4), tmp_path / "a",
                          resolve=lambda _f: photo, title="T")
    other = [{"filename": f"OTHER_{i:03d}.jpg", "decision": "keep",
              "orig_filename": f"OTHER_{i:03d}.jpg"} for i in range(4)]
    b = write_proof_sheet(other, tmp_path / "b",
                          resolve=lambda _f: photo, title="T")
    assert a["digest"] != b["digest"]

    reordered = list(reversed(_rows(4)))
    c = write_proof_sheet(reordered, tmp_path / "c",
                          resolve=lambda _f: photo, title="T")
    assert a["digest"] != c["digest"], (
        "the same photographs in a different order carry different "
        "numbers, so they are a different export")


def test_numbering_starts_at_one(tmp_path, photo):
    """Clients count from 1. An off-by-one here hands back the wrong
    photograph for every single number."""
    out = tmp_path / "proof"
    write_proof_sheet(_rows(3), out, resolve=lambda _f: photo, title="T")
    man = json.loads((out / "picks_manifest.json").read_text(encoding="utf-8"))
    assert sorted(int(k) for k in man["by_index"]) == [1, 2, 3]


def test_a_frame_that_failed_to_export_is_not_numbered(tmp_path, photo):
    """The client cannot pick a photograph they were never sent, and a
    gap in the numbering would shift everything after it."""
    out = tmp_path / "proof"
    rows = _rows(3)
    write_proof_sheet(
        rows, out,
        resolve=lambda f: None if f == "IMG_001.jpg" else photo, title="T")
    man = json.loads((out / "picks_manifest.json").read_text(encoding="utf-8"))
    assert "IMG_001.jpg" not in man["by_index"].values()
    assert man["n"] == 2


# --------------------------------------------------------------- the reply


@pytest.mark.parametrize("text,want", [
    ("3,7,12", [3, 7, 12]),
    ("3、7、12", [3, 7, 12]),
    ("第3张 第7张 第12张", [3, 7, 12]),
    ("3 7 12。", [3, 7, 12]),
    ("#3 #7", [3, 7]),
    ("3-5", [3, 4, 5]),
    ("5-3", [3, 4, 5]),
    ("3,3,7", [3, 7]),
])
def test_the_shapes_a_client_actually_types(text, want):
    idx, problems = parse_picks(text, n=12)
    assert idx == want
    assert problems == []


def test_order_is_the_order_they_said_it():
    """Not sorted. "7, then 3" may be a preference order, and silently
    re-sorting throws that away."""
    idx, _ = parse_picks("7,3,9", n=12)
    assert idx == [7, 3, 9]


def test_a_number_out_of_range_is_reported_not_dropped():
    """A silently ignored 17 on a 12-photo set is a photograph the client
    asked for and will not get."""
    idx, problems = parse_picks("3,17,7", n=12)
    assert idx == [3, 7]
    assert any("17" in p for p in problems)


def test_words_are_reported_not_dropped():
    idx, problems = parse_picks("3、七、7", n=12)
    assert idx == [3, 7]
    assert any("七" in p for p in problems)


def test_an_absurd_range_is_refused_whole():
    idx, problems = parse_picks("1-9999", n=12)
    assert idx == []
    assert problems


def test_an_empty_reply_yields_nothing_and_says_nothing_wrong():
    assert parse_picks("", n=12) == ([], [])
    assert parse_picks("   ", n=12) == ([], [])
