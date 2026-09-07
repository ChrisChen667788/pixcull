"""v3.23 — PixCull was silently destroying the photographer's own ratings.

The charter asked whether a rating or colour label already in a sidecar
survives a PixCull write, noted that nothing in the repo asserted it, and
said it might already be correct.

It was not.  `write_xmp` built a fresh sidecar and wrote it over whatever
was there, so a photographer who had already starred, colour-labelled and
keyworded a shoot in Lightroom lost all of it the first time they pointed
PixCull at the folder.  No error, no warning, no test.

The fix follows Capture One's Assisted Review, which is the design this
charter item came from: its tags are ADDITIVE, sitting alongside the
photographer's own stars rather than replacing them.  PixCull's verdict
already travels in the keywords, so the stars and the label stay theirs.
"""
import tempfile
from pathlib import Path

from pixcull.io.xmp import (
    PIXCULL_KEYWORD_PREFIX, read_xmp, read_xmp_keywords, write_xmp,
)

EXISTING = '''<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<xmp:Rating>5</xmp:Rating><xmp:Label>Purple</xmp:Label>
<dc:subject><rdf:Bag><rdf:li>Ceremony</rdf:li><rdf:li>Delivered</rdf:li>
</rdf:Bag></dc:subject>
</rdf:Description></rdf:RDF></x:xmpmeta>'''


def _shoot(existing: str | None = EXISTING):
    d = Path(tempfile.mkdtemp())
    img = d / "DSC_0001.NEF"
    img.write_bytes(b"\xff\xd8\xff")
    if existing is not None:
        img.with_suffix(".xmp").write_text(existing, encoding="utf-8")
    return img


def test_a_hand_set_star_rating_survives():
    """The defect. A rating the photographer set is a judgement;
    PixCull's is a proposal."""
    img = _shoot()
    write_xmp(img, 3, "Yellow", keywords=["PixCull:maybe"])
    assert read_xmp(img)["rating"] == 5


def test_a_hand_set_colour_label_survives():
    img = _shoot()
    write_xmp(img, 3, "Yellow", keywords=["PixCull:maybe"])
    assert read_xmp(img)["color_label"] == "Purple"


def test_the_photographers_keywords_survive():
    img = _shoot()
    write_xmp(img, 3, "Yellow", keywords=["PixCull:maybe"])
    kw = read_xmp_keywords(img)
    assert "Ceremony" in kw and "Delivered" in kw


def test_pixculls_verdict_still_lands_in_the_keywords():
    """Preserving their stars must not mean losing the verdict — the
    keyword is where it lives, which is Capture One's whole design."""
    img = _shoot()
    write_xmp(img, 3, "Yellow", keywords=["PixCull:maybe"])
    assert "PixCull:maybe" in read_xmp_keywords(img)


def test_a_second_run_replaces_pixculls_own_keywords_rather_than_stacking():
    """`PixCull:keep` beside `PixCull:cull` would leave the reader to
    arbitrate between two verdicts from the same tool."""
    img = _shoot()
    write_xmp(img, 5, "Green", keywords=["PixCull:keep"])
    write_xmp(img, 1, "Red", keywords=["PixCull:cull"])
    kw = read_xmp_keywords(img)
    assert "PixCull:cull" in kw
    assert "PixCull:keep" not in kw
    assert len([k for k in kw if k.startswith(PIXCULL_KEYWORD_PREFIX)]) == 1


def test_an_unrated_frame_gets_pixculls_rating():
    """Additive, not passive. With nothing to preserve the verdict is
    what the catalogue should sort by."""
    img = _shoot('<x:xmpmeta><rdf:RDF><rdf:Description>'
                 '</rdf:Description></rdf:RDF></x:xmpmeta>')
    write_xmp(img, 3, "Yellow", keywords=["PixCull:maybe"])
    got = read_xmp(img)
    assert got["rating"] == 3 and got["color_label"] == "Yellow"


def test_a_fresh_folder_is_unaffected():
    img = _shoot(existing=None)
    write_xmp(img, 5, "Green", keywords=["PixCull:keep"])
    got = read_xmp(img)
    assert got["rating"] == 5 and got["color_label"] == "Green"


def test_a_zero_rating_is_not_treated_as_a_judgement():
    """Lightroom writes 0 for "unrated". Preserving it would mean
    PixCull could never rate anything the photographer had merely
    opened."""
    img = _shoot('<x:xmpmeta xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
                 '<xmp:Rating>0</xmp:Rating></x:xmpmeta>')
    write_xmp(img, 5, "Green", keywords=["PixCull:keep"])
    assert read_xmp(img)["rating"] == 5


def test_the_old_destructive_behaviour_is_still_reachable_explicitly():
    """A caller that genuinely wants PixCull's rating to win can say so —
    but has to say so."""
    img = _shoot()
    write_xmp(img, 1, "Red", keywords=["PixCull:cull"],
              preserve_existing=False)
    got = read_xmp(img)
    assert got["rating"] == 1 and got["color_label"] == "Red"
    assert "Ceremony" not in read_xmp_keywords(img)


def test_preserving_is_the_default():
    import inspect
    sig = inspect.signature(write_xmp)
    assert sig.parameters["preserve_existing"].default is True
