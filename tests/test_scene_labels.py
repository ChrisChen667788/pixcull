"""v2.74 — name a stretch of a shoot, without inventing the event.

Narrative Select's Scenes view is the one competitor capability this
product lacked outright, and reviewers single it out: you cull in story
order — ceremony, cocktail hour, reception — rather than image by image.

PixCull already segmented on capture-time gaps and already rendered a
strip of chips. The chips said `场景 1` … `场景 28`. An index is not a
name; it tells the reader nothing they could not get by counting.

Everything here is about what may honestly go on that chip. Two things
are known — when the stretch was shot, and how its frames were
classified — and the event is not one of them. A label that guessed
"仪式" would be the most useful-looking and least checkable thing this
product could print.
"""

from __future__ import annotations

import pytest

from pixcull.scoring.scene_labels import (
    DOMINANT_SHARE, MIN_STRETCH, hour_band, label_stretch,
)


def test_a_plurality_is_not_a_description():
    """The stretch that forced this rule: 10 `fashion` frames of 29.

    Naming it 时尚 describes a third of the photographs and misleads
    about the other nineteen. Below the threshold the chip says the time
    and stops.
    """
    scenes = ["fashion"] * 10 + ["a"] * 7 + ["b"] * 6 + ["c"] * 6
    lab = label_stretch(scenes, hour=16, n=29)
    assert lab.dominant_share == pytest.approx(10 / 29, abs=0.01)
    assert lab.dominant_scene == "", (
        f"named on a {10/29:.0%} plurality")
    assert lab.hour_band == "下午"
    assert lab.key == ""


def test_a_real_majority_is_named():
    lab = label_stretch(["landscape"] * 8 + ["street"] * 3, hour=6, n=11)
    assert lab.dominant_scene == "landscape"
    assert lab.key == "scene.landscape"
    assert lab.hour_band == "清晨"


def test_unknown_frames_count_against_the_share():
    """A stretch that is half unclassified must not be named on the
    strength of the other half.

    `unknown` is the classifier declining to answer (v2.69 gave it its
    own treatment in the filter panel for the same reason). Excluding
    those frames from the DENOMINATOR would let 5 portraits out of 11
    frames read as a portrait session.
    """
    lab = label_stretch(["portrait"] * 5 + ["unknown"] * 6, hour=10, n=11)
    assert lab.dominant_share < DOMINANT_SHARE
    assert lab.dominant_scene == ""


def test_a_stray_frame_is_not_announced_as_a_chapter():
    """Eleven of 28 stretches on a real run were one or two frames.

    They keep their place and their frames stay reachable — dropping
    them would hide photographs — but a chapter of the shoot is not one
    frame between two sessions.
    """
    for n in range(1, MIN_STRETCH):
        assert label_stretch(["architecture"] * n, hour=15, n=n).is_stray
    assert not label_stretch(["architecture"] * MIN_STRETCH, hour=15,
                             n=MIN_STRETCH).is_stray


@pytest.mark.parametrize("hour,want", [
    (0, "夜晚"), (5, "清晨"), (7, "清晨"), (8, "上午"), (12, "中午"),
    (15, "下午"), (18, "傍晚"), (23, "夜晚"),
])
def test_hour_bands_cover_the_clock(hour, want):
    assert hour_band(hour) == want


def test_a_missing_timestamp_produces_no_time_claim():
    """A run without EXIF must not be told it was shot at midnight."""
    assert hour_band(None) == ""
    lab = label_stretch(["landscape"] * 5, hour=None, n=5)
    assert lab.hour_band == ""
    assert lab.dominant_scene == "landscape"


def test_the_chip_never_invents_an_event():
    """Structural: the label is built from an hour band and a scene key,
    and there is nowhere for an event name to come from."""
    import inspect
    import re

    from pixcull.scoring import scene_labels

    # Code only. This module EXPLAINS that it must not invent an event,
    # using the words it must not print — and a lint that reads prose
    # flags the explanation of its own rule. Third time this session:
    # v2.68.1's grid lint counted `querySelectorAll` inside the comment
    # saying it had been removed, and v2.68.4's NaN lint matched its own
    # docstring.
    src = inspect.getsource(scene_labels)
    src = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src)
    src = "\n".join(ln for ln in src.splitlines()
                    if not ln.lstrip().startswith("#"))
    for word in ("ceremony", "reception", "仪式", "婚礼", "晚宴", "开场"):
        assert word not in src, (
            f"the labeller carries an event vocabulary ({word!r}) — "
            f"timestamps and a scene classifier cannot know that")


def test_the_scene_name_goes_through_the_dictionary():
    """`scene.landscape` is a key, not a label. v2.69 shipped the
    translations; a chip that printed the key would undo it."""
    js_path = (__import__("pathlib").Path(__file__).resolve().parents[1]
               / "pixcull/report/templates/src/results.js")
    js = js_path.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith("//"))
    assert "_t(s.scene_key" in code, (
        "the chip renders the raw i18n key instead of the translation")
    assert "s.hour_band" in code
    assert "scene-chip-stray" in code
