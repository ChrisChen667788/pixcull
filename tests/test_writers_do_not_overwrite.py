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
    """It REPLACES the keyword tag rather than clearing it and appending.

    v3.41's effect test in CI found that `-IPTC:Keywords=` followed by
    `-IPTC:Keywords+=ours` in one invocation does not net to "only ours"
    — the photographer's keyword survived a write that had explicitly
    been asked to replace everything. Assigning the first value is
    exiftool's own idiom and leaves no window where two assignments have
    to compose.
    """
    args = _args(preserve_existing=False, prior={})
    assert "-IPTC:Keywords=PixCull:maybe" in args
    assert "-IPTC:Keywords=" not in args, (
        "a bare clear is back; it does not compose with the += that "
        "follows it")
    assert "-XMP:Rating=3" in args


def test_a_replacing_write_with_nothing_to_write_clears():
    args = _args(preserve_existing=False, prior={}, keywords=["", "  "])
    assert "-IPTC:Keywords=" in args
    assert "-XMP-dc:Subject=" in args


def test_the_preserving_path_never_clears():
    """The safety-critical half, restated after the change: it removes
    our own values by name and issues no assignment at all."""
    args = _args()
    assert not [a for a in args if a.startswith("-IPTC:Keywords=")]
    assert not [a for a in args if a.startswith("-XMP-dc:Subject=")]


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


# ---------------------------------------------------------------------
# v3.41 — the effect test, not the construction test
#
# Everything above asserts the command line. That proves the arguments
# are right and proves nothing about what exiftool does with them, and
# three of its behaviours were taken on trust when v3.28 was written:
#
#   1. `-IPTC:Keywords-=<value>` removes ONLY that value, not the tag.
#   2. omitting `-XMP:Rating=` leaves an existing rating untouched.
#   3. `-IPTC:Keywords+=` creates the tag on a file that has none.
#
# If 1 or 2 is wrong, the fix still destroys the photographer's metadata
# inside their original files, with -overwrite_original so there is no
# backup. That is the worst failure class in this repository and it was
# resting on recall.
#
# CI installs exiftool so these cannot silently skip. Locally they skip
# with a reason, because a skip that says nothing is how "we tested it"
# becomes untrue.
# ---------------------------------------------------------------------

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

needs_exiftool = pytest.mark.skipif(
    shutil.which("exiftool") is None,
    reason="exiftool not installed — this asserts what the tool DOES, not "
           "what we ask it to do; CI installs it so this cannot pass by "
           "skipping",
)


def _jpeg_with(tmp: Path, *, rating=None, label=None, keywords=()) -> Path:
    """A real JPEG carrying real metadata, written by exiftool itself."""
    from PIL import Image
    p = tmp / "DSC_0001.jpg"
    Image.new("RGB", (48, 32), "white").save(p, "JPEG")
    args = ["exiftool", "-q", "-overwrite_original"]
    if rating is not None:
        args.append(f"-XMP:Rating={rating}")
    if label:
        args.append(f"-XMP:Label={label}")
    for k in keywords:
        args += [f"-IPTC:Keywords+={k}", f"-XMP-dc:Subject+={k}"]
    args.append(str(p))
    subprocess.run(args, check=True, capture_output=True)
    return p


def _read(p: Path) -> dict:
    return E.read_embedded(p)


@needs_exiftool
def test_a_hand_set_rating_inside_the_photograph_survives():
    """Behaviour 2. If exiftool clears a tag you do not name, this fails
    and v3.28's fix is not a fix."""
    with tempfile.TemporaryDirectory() as d:
        p = _jpeg_with(Path(d), rating=5, label="Purple",
                       keywords=("Ceremony", "Delivered"))
        assert E.write_iptc_to_file(
            p, rating=3, color_label="Yellow", keywords=["PixCull:maybe"])
        got = _read(p)
        assert got["rating"] == 5
        assert got["color_label"] == "Purple"


@needs_exiftool
def test_their_keywords_survive_and_ours_is_added():
    """Behaviour 1, the additive half."""
    with tempfile.TemporaryDirectory() as d:
        p = _jpeg_with(Path(d), rating=5, keywords=("Ceremony", "Delivered"))
        E.write_iptc_to_file(p, rating=3, keywords=["PixCull:maybe"])
        kw = _read(p)["keywords"]
        assert "Ceremony" in kw and "Delivered" in kw
        assert "PixCull:maybe" in kw


@needs_exiftool
def test_a_second_run_replaces_our_keyword_rather_than_stacking():
    """Behaviour 1, the removal half — `-Keywords-=` must take out one
    value and leave the rest. If it clears the tag, the photographer's
    keywords go with it."""
    with tempfile.TemporaryDirectory() as d:
        p = _jpeg_with(Path(d), keywords=("Ceremony",))
        E.write_iptc_to_file(p, keywords=["PixCull:keep"])
        E.write_iptc_to_file(p, keywords=["PixCull:cull"])
        kw = _read(p)["keywords"]
        assert "PixCull:cull" in kw
        assert "PixCull:keep" not in kw
        assert "Ceremony" in kw, "their keyword was taken out with ours"


@needs_exiftool
def test_an_untouched_file_gets_our_rating_and_keyword():
    """Behaviour 3: the tag is created when the file has none."""
    with tempfile.TemporaryDirectory() as d:
        p = _jpeg_with(Path(d))
        E.write_iptc_to_file(p, rating=5, color_label="Green",
                             keywords=["PixCull:keep"])
        got = _read(p)
        assert got["rating"] == 5 and got["color_label"] == "Green"
        assert "PixCull:keep" in got["keywords"]


@needs_exiftool
def test_the_destructive_path_is_still_destructive_when_asked():
    """The escape hatch has to actually work, or a caller who needs
    PixCull's rating to win has no way to get it."""
    with tempfile.TemporaryDirectory() as d:
        p = _jpeg_with(Path(d), rating=5, keywords=("Ceremony",))
        E.write_iptc_to_file(p, rating=1, color_label="Red",
                             keywords=["PixCull:cull"],
                             preserve_existing=False)
        got = _read(p)
        assert got["rating"] == 1
        assert "Ceremony" not in got["keywords"]


def test_ci_installs_exiftool_so_the_effect_tests_cannot_skip_forever():
    """A skip is only honest while somewhere runs it for real.

    v2.45 added the ffmpeg step for exactly this reason and wrote down
    why: without it four journey tests reported green having tested
    nothing. Removing the exiftool step would put the five above into
    permanent skip, and the suite would go on passing while the writer
    that edits people's originals went unverified.
    """
    ci = (Path(__file__).resolve().parent.parent
          / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "libimage-exiftool-perl" in ci
    # And in the job that runs the hermetic suite, not a lane that only
    # fires on a schedule.
    # v3.42 inserted a browser job above this one, so anchor the window
    # at the hermetic job rather than at the top of the file.
    head = ci[ci.index("  pytest:"):ci.index("Run hermetic tests")]
    assert "libimage-exiftool-perl" in head
