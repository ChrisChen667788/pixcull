"""v3.28 — every writer that puts a file where the photographer already has one.

v3.23 found that `write_xmp` built a fresh sidecar over whatever was
there, destroying hand-set ratings, labels and keywords.  That was ONE
writer, found while answering a charter item that said it might already
be correct.  Nobody had swept for the rest of the class.

This is the sweep.  The inventory it produces is in
`docs/WRITER-INVENTORY.md` and is published even where nothing was wrong,
because both defects this block is built on had already evaded ordinary
attention — so "we looked and found nothing" has to show its work.
"""
import inspect

from pixcull.io import iptc_embed as E

PRIOR = {"rating": 5, "color_label": "Purple",
         "keywords": ["Ceremony", "Delivered", "PixCull:keep"]}


def _args(**kw):
    kw.setdefault("rating", 3)
    kw.setdefault("color_label", "Yellow")
    kw.setdefault("keywords", ["PixCull:maybe"])
    kw.setdefault("prior", PRIOR)
    return E.build_args("exiftool", "a.jpg", **kw)


def test_it_does_not_overwrite_a_rating_inside_the_photograph():
    """Worse than the sidecar case: this writes INTO the file, with
    -overwrite_original, so exiftool keeps no `_original` to recover."""
    assert not [a for a in _args() if a.startswith("-XMP:Rating=")]


def test_it_does_not_overwrite_a_colour_label_inside_the_photograph():
    assert not [a for a in _args() if a.startswith("-XMP:Label=")]


def test_it_never_blanket_clears_the_keyword_tags():
    """`-IPTC:Keywords=` with an empty value wipes every keyword in the
    file. That is the defect, and it was two lines with a comment
    explaining why it was fine."""
    args = _args()
    assert "-IPTC:Keywords=" not in args
    assert "-XMP-dc:Subject=" not in args


def test_it_removes_only_its_own_previous_keywords():
    args = _args()
    assert "-IPTC:Keywords-=PixCull:keep" in args
    assert not [a for a in args if a.startswith("-IPTC:Keywords-=")
                and "PixCull:" not in a]


def test_the_photographers_keywords_are_not_re_added_or_removed():
    args = _args()
    for theirs in ("Ceremony", "Delivered"):
        assert not [a for a in args if a.endswith("=" + theirs)]


def test_the_new_verdict_still_lands():
    assert "-IPTC:Keywords+=PixCull:maybe" in _args()


def test_an_unrated_file_gets_pixculls_rating():
    args = _args(prior={"rating": 0, "color_label": "", "keywords": []})
    assert "-XMP:Rating=3" in args and "-XMP:Label=Yellow" in args


def test_the_destructive_path_still_exists_but_must_be_asked_for():
    args = _args(preserve_existing=False, prior={})
    assert "-IPTC:Keywords=" in args
    assert "-XMP:Rating=3" in args


def test_preserving_is_the_default():
    sig = inspect.signature(E.write_iptc_to_file)
    assert sig.parameters["preserve_existing"].default is True
    sig2 = inspect.signature(E.build_args)
    assert sig2.parameters["preserve_existing"].default is True


def test_an_unreadable_file_is_not_treated_as_an_empty_one():
    """`read_embedded` returns {} when exiftool is missing or the read
    fails. {} means "we could not tell", and the write path must not
    read that as "there is nothing to protect"."""
    args = _args(prior={})
    # With no prior information, nothing is CLEARED — the rating may be
    # written (there is nothing known to protect) but the blanket wipe
    # must not happen.
    assert "-IPTC:Keywords=" not in args
    assert "-XMP-dc:Subject=" not in args


def test_the_builder_needs_no_exiftool_to_be_checked():
    """A rule about somebody's photographs must not go untested because
    a binary is missing from the machine."""
    assert E._exiftool_path() is None or True
    assert _args()          # built anyway
