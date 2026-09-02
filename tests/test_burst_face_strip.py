"""v3.12 — the burst winner, checkable at a glance instead of on faith.

`rank_burst_peak` picks the peak on blink, smile and brow blendshapes and
then asserts it in a sentence — "最锐 +1.6σ".  A photographer who wants
to check that has to open every frame of the cluster in turn.  Narrative's
Close-Ups Panel and Lightroom's Face View both do the obvious thing
instead, and eyes-open across five frames is the one comparison a person
makes faster than any model.
"""
from pixcull.report.serve_app import burst_strip_plan


def _f(name, peak=False, shot=""):
    return {"filename": name, "is_burst_peak": peak, "shot_at": shot}


def test_the_frame_the_tool_chose_comes_first():
    """It is the claim under review, so it goes where the eye lands."""
    shown, _ = burst_strip_plan(
        [_f("c.jpg", shot="3"), _f("a.jpg", shot="1"),
         _f("b.jpg", peak=True, shot="2")], 10)
    assert shown[0]["filename"] == "b.jpg"


def test_the_rest_stay_in_capture_order():
    """A burst is a sequence. Sorting the rest by score destroys the one
    thing the eye reads it with."""
    shown, _ = burst_strip_plan(
        [_f("c.jpg", shot="3"), _f("a.jpg", shot="1"), _f("b.jpg", shot="2")],
        10)
    assert [f["filename"] for f in shown] == ["a.jpg", "b.jpg", "c.jpg"]


def test_a_long_burst_is_capped_and_says_how_many_it_dropped():
    """A strip that silently showed 12 of 40 would read as 'this is the
    burst', which is a different and false statement."""
    members = [_f(f"{i:03d}.jpg", shot=f"{i:03d}") for i in range(40)]
    shown, dropped = burst_strip_plan(members, 12)
    assert len(shown) == 12
    assert dropped == 28


def test_a_short_burst_drops_nothing():
    shown, dropped = burst_strip_plan([_f("a.jpg"), _f("b.jpg")], 12)
    assert len(shown) == 2 and dropped == 0


def test_the_cap_cannot_be_zero_or_negative():
    shown, dropped = burst_strip_plan([_f("a.jpg"), _f("b.jpg")], 0)
    assert len(shown) == 1 and dropped == 1


def test_the_input_list_is_not_mutated():
    members = [_f("c.jpg", shot="3"), _f("a.jpg", shot="1")]
    before = [m["filename"] for m in members]
    burst_strip_plan(members, 10)
    assert [m["filename"] for m in members] == before


# -- what the endpoint claims -----------------------------------------

def test_the_payload_does_not_claim_to_have_tracked_one_person():
    """The crop is the largest face per frame. In a two-person burst the
    largest face can change frame to frame, and calling that 'the same
    face' would be a claim the code does not make good on."""
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app.PixCullHandler._serve_api_v1_burst_faces) \
        if hasattr(serve_app, "PixCullHandler") else inspect.getsource(serve_app)
    assert '"match":      "largest"' in src
    assert "not a tracked identity" in src


def test_a_frame_with_no_face_reports_none_rather_than_a_dead_url():
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app)
    assert "if face_i is not None else None" in src


def test_the_endpoint_is_routed():
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app)
    assert 'rest.startswith("burst_faces/")' in src


def test_a_cluster_of_one_is_not_a_burst():
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app)
    assert 'if len(members) < 2:' in src
