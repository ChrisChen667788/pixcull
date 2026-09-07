"""v3.18 — the judge finally sees two frames of the burst at once.

The local Qwen3-VL path called the model with `num_images=1`, under a
comment saying "we pass the image path as a list since some templates
support multi-image".  The capability was considered and not built, so
the model that could say "this one, because the eyes are open here and
not there" was never shown both frames.  Burst demotion ran afterwards,
on scores produced independently.
"""
import inspect

from pixcull.scoring import burst_multi as BM

MEMBERS = [
    {"filename": "peak.jpg", "is_burst_peak": True, "score_final": 0.70},
    {"filename": "high.jpg", "score_final": 0.90},
    {"filename": "mid.jpg", "score_final": 0.60},
    {"filename": "low.jpg", "score_final": 0.40},
    {"filename": "self.jpg", "score_final": 0.50},
]


def test_the_frame_being_judged_is_never_its_own_peer():
    assert "self.jpg" not in BM.burst_peers("self.jpg", MEMBERS)


def test_the_peak_comes_first_even_when_it_scores_lower():
    """A photographer reviewing a loser wants it against the frame the
    tool CHOSE, not against another loser."""
    assert BM.burst_peers("self.jpg", MEMBERS)[0] == "peak.jpg"


def test_the_rest_follow_by_score():
    assert BM.burst_peers("self.jpg", MEMBERS) == [
        "peak.jpg", "high.jpg", "mid.jpg"]


def test_a_forty_frame_burst_does_not_become_a_slideshow():
    """Beyond a few images the context is mostly pixels and the schema
    gets harder to hold — a model problem that is really a prompt one."""
    many = [{"filename": f"{i:03d}.jpg", "score_final": i / 100}
            for i in range(40)]
    assert len(BM.burst_peers("000.jpg", many)) == BM.MAX_PEERS
    assert BM.MAX_PEERS <= 3


def test_a_lone_frame_has_no_peers():
    assert BM.burst_peers("a.jpg", [{"filename": "a.jpg"}]) == []


def test_unscored_siblings_sort_last_rather_than_crashing():
    got = BM.burst_peers("x.jpg", [{"filename": "a.jpg"},
                                   {"filename": "b.jpg", "score_final": 0.9}])
    assert got == ["b.jpg", "a.jpg"]


# -- the note ---------------------------------------------------------

def test_the_note_names_which_frame_is_being_judged():
    """Four photographs and no reason to treat one differently gets a
    verdict about the burst instead of a verdict about the frame."""
    note = BM.peer_prompt_note(3)
    assert "第一张才是要评的那张" in note


def test_the_note_forbids_borrowing_the_siblings_merits():
    note = BM.peer_prompt_note(2)
    assert "不要给其他帧打分" in note
    assert "不要把它们的优点算到这一张头上" in note


def test_no_peers_means_no_note():
    assert BM.peer_prompt_note(0) == ""
    assert BM.peer_prompt_note(-1) == ""


def test_it_is_off_until_measured(monkeypatch):
    monkeypatch.delenv(BM.ENV_FLAG, raising=False)
    assert BM.enabled() is False
    monkeypatch.setenv(BM.ENV_FLAG, "1")
    assert BM.enabled() is True


# -- the call ---------------------------------------------------------

def test_the_local_judge_declares_the_real_image_count():
    """`num_images=1` with peers attached is a prompt that says one image
    and a payload that carries four."""
    from pixcull.scoring import vlm_judge
    src = inspect.getsource(vlm_judge)
    assert "num_images=1 + len(peers)" in src
    assert "num_images=1," not in src


def test_peers_are_sent_after_the_frame_under_judgement():
    from pixcull.scoring import vlm_judge
    src = inspect.getsource(vlm_judge)
    assert "image=[str(small_path)] + peer_paths" in src


def test_an_unpreparable_peer_does_not_fail_the_judgement():
    """A peer is context, not a precondition."""
    from pixcull.scoring import vlm_judge
    src = inspect.getsource(vlm_judge)
    block = src[src.index("peer_paths = []"):]
    assert "except Exception" in block.split("output = generate")[0]
