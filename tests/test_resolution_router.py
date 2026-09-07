"""v3.17 — route resolution, and be wrong in the safe direction only.

`VLM_RESIZE_LONG_EDGE = 1024` goes to every frame.  The charter said
`resize_long_edge` was already a per-call argument on both judges; it is
a CONSTRUCTOR argument, so the per-call path had to be built before any
routing could exist.

Downgrading the wrong frame is not a saving, it is a worse verdict — and
the axes that live in pixels are exactly the ones a naive router strips
first: whether the eyes are sharp inside a face that is 3% of the frame.
So every rule here is asymmetric on purpose, and the tests are mostly
about what the router REFUSES to downgrade.
"""
import pytest

from pixcull.scoring import resolution_router as RR


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv(RR.ENV_FLAG, "1")


def test_a_frame_with_a_face_keeps_its_pixels():
    """Eye sharpness is the most decision-relevant thing in portrait,
    wedding and event work, and it is measured in pixels."""
    r = RR.route({"face_count": 1, "laplacian_subject": 5000})
    assert r.long_edge == RR.DEFAULT and not r.downgraded
    assert "face" in r.reason


def test_a_frame_near_the_sharpness_boundary_keeps_its_pixels():
    """Those are the frames whose answer is not already known — the ones
    the judge exists for."""
    mid = (RR.SOFT_BELOW + RR.SHARP_ABOVE) / 2
    assert RR.route({"laplacian_subject": mid}).long_edge == RR.DEFAULT


def test_an_unmeasurable_frame_keeps_its_pixels():
    """Unknown is not 'easy'. A frame the detectors could not measure is
    the last one to strip."""
    for row in ({}, {"laplacian_subject": None},
                {"laplacian_subject": "n/a"},
                {"laplacian_subject": float("nan")}):
        assert RR.route(row).long_edge == RR.DEFAULT


def test_a_bad_face_count_does_not_become_zero_faces():
    """A NaN or a string in that column must not read as 'nobody here'."""
    assert RR.route({"face_count": float("nan"),
                     "laplacian_subject": 5000}).long_edge == RR.DEFAULT


def test_only_unambiguous_faceless_frames_go_down():
    assert RR.route({"laplacian_subject": RR.SHARP_ABOVE + 1}).downgraded
    assert RR.route({"laplacian_subject": RR.SOFT_BELOW - 1}).downgraded


def test_the_boundaries_are_exclusive_so_a_frame_on_them_keeps_pixels():
    assert not RR.route({"laplacian_subject": RR.SHARP_ABOVE}).downgraded
    assert not RR.route({"laplacian_subject": RR.SOFT_BELOW}).downgraded


def test_the_undecided_band_is_wide():
    """A narrow band routes most frames down and saves the most, which is
    the temptation this module is shaped against."""
    assert RR.SHARP_ABOVE / RR.SOFT_BELOW >= 10


def test_the_subject_reading_is_preferred_over_the_global_one():
    """A sharp background behind a soft subject is the classic miss."""
    r = RR.route({"laplacian_subject": 300, "laplacian_global": 5000})
    assert not r.downgraded


def test_every_route_explains_itself():
    """A router whose decisions cannot be explained cannot be reviewed
    when a per-axis number moves."""
    for row in ({"face_count": 2}, {"laplacian_subject": 1},
                {"laplacian_subject": 300}, {}):
        assert RR.route(row).reason.strip()


def test_the_router_is_off_by_default(monkeypatch):
    monkeypatch.delenv(RR.ENV_FLAG, raising=False)
    assert RR.enabled() is False
    assert RR.route({"laplacian_subject": 5000}).long_edge == RR.DEFAULT


def test_the_size_set_is_closed():
    """A cache keyed on the chosen edge needs a bounded number of slots
    per frame, not one per arbitrary integer."""
    seen = {RR.route(r).long_edge for r in
            ({}, {"face_count": 1}, {"laplacian_subject": 1},
             {"laplacian_subject": 5000}, {"laplacian_subject": 300})}
    assert seen <= set(RR.SIZES)


# -- the per-call path that had to be built first ---------------------

def test_the_judge_accepts_a_per_frame_resolution():
    import inspect

    from pixcull.scoring.m3 import MiniMaxM3Judge
    assert "resize_long_edge" in inspect.signature(MiniMaxM3Judge.score).parameters
    src = inspect.getsource(MiniMaxM3Judge._image_data_uri)
    assert "long_edge or self.resize_long_edge" in src


def test_the_resolution_is_part_of_the_cache_key():
    """Third time in this block: an arm that changes what the model SEES
    and not the key reads back the other arm's answer."""
    from pixcull.scoring.m3 import cache_extra
    base = dict(model="m", scene="s", vertical="v", evidence_arm="technical",
                evidence_len=1, prompt_override=None)
    assert cache_extra(**base) != cache_extra(**base, long_edge=RR.LOW)
    assert cache_extra(**base) == cache_extra(**base, long_edge=None)
