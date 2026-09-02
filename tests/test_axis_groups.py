"""v3.5 — grouped axis prompts, and the merge that refuses to guess.

The six-axis prompt asks one reply for everything, so the model splits
attention six ways and anchors each score to the prose it just wrote for
the previous axis. Grouping is the prompt-only derivation of the NTIRE
2026 second-place architecture, which used per-dimension specialist
models.

The dangerous half is not the prompt. It is the merge: three calls where
one used to be means two of them can succeed and one fail, and a merge
that filled the gap — or computed a verdict from what it happened to
get — would produce a confident judgement resting on two thirds of the
evidence with nothing anywhere saying so.
"""
import pytest

from pixcull.scoring import axis_groups as ag

OK = {"stars": 4, "rationale": "睫毛清晰可数,焦平面落在眼睛上。"}


def test_the_groups_partition_the_rubric():
    """A dropped axis scores every photograph on five and looks fine."""
    assert ag.covers_every_axis()


def test_no_axis_appears_in_two_groups():
    flat = [a for g in ag.AXIS_GROUPS for a in g]
    assert len(flat) == len(set(flat))


def test_a_group_prompt_asks_only_for_its_own_axes():
    p = ag.build_group_prompt(("technical", "light"))
    assert '"technical"' in p and '"light"' in p
    for other in ("composition", "aesthetic", "moment"):
        assert f'"{other}": {{"stars"' not in p


def test_a_group_prompt_forbids_an_overall_verdict():
    """Each call sees a third of the evidence. A per-call overall label
    would be three verdicts where the product needs one."""
    p = ag.build_group_prompt(("subject", "moment"))
    assert "不要给总判" in p
    assert '"overall_label"' not in p


def test_group_prompts_keep_the_canon_and_vertical_blocks():
    """The arms must differ only in which axes are asked for. If the
    grouped arm also lost the canon, the A/B would measure two changes."""
    from pixcull.scoring.vlm_judge import build_prompt
    full = build_prompt("wedding", vertical="wedding")
    grouped = ag.build_group_prompt(("technical", "light"), scene="wedding",
                                    vertical="wedding")
    head = full.split("\n★ 含义:", 1)[0]
    assert grouped.startswith(head)


def test_unknown_axis_is_refused_rather_than_silently_dropped():
    with pytest.raises(ValueError):
        ag.build_group_prompt(("technical", "nosuchaxis"))


# -- the merge --------------------------------------------------------

def test_merge_reports_complete_only_when_every_axis_arrived():
    partials = [(g, {"axes": {a: OK for a in g}}) for g in ag.AXIS_GROUPS]
    out = ag.merge(partials)
    assert out["complete"] is True
    assert out["failed_groups"] == []
    assert set(out["axes"]) == set(ag._ALL_AXES)


def test_a_failed_group_is_named_and_its_axes_stay_absent():
    partials = [(ag.AXIS_GROUPS[0], {"axes": {a: OK for a in ag.AXIS_GROUPS[0]}}),
                (ag.AXIS_GROUPS[1], None),
                (ag.AXIS_GROUPS[2], {"axes": {a: OK for a in ag.AXIS_GROUPS[2]}})]
    out = ag.merge(partials)
    assert out["complete"] is False
    assert out["failed_groups"] == [ag.group_name(ag.AXIS_GROUPS[1])]
    for a in ag.AXIS_GROUPS[1]:
        assert a not in out["axes"], "a failed group must not be filled in"


def test_a_half_answered_group_counts_as_failed():
    """One of two axes is a partial answer. Counting it as a success is
    how five-axis scoring would start looking like six-axis scoring."""
    g = ag.AXIS_GROUPS[0]
    out = ag.merge([(g, {"axes": {g[0]: OK}})])
    assert ag.group_name(g) in out["failed_groups"]
    assert g[0] in out["axes"] and g[1] not in out["axes"]


def test_merge_never_produces_an_overall_label():
    partials = [(g, {"axes": {a: OK for a in g}}) for g in ag.AXIS_GROUPS]
    assert "overall_label" not in ag.merge(partials)


def test_merge_survives_garbage_without_claiming_completeness():
    for junk in (None, "", [], {"axes": "not a dict"}, {"nope": 1}):
        out = ag.merge([(ag.AXIS_GROUPS[0], junk)])
        assert out["complete"] is False
        assert out["failed_groups"]


# -- it is an arm, not the path ---------------------------------------

def test_grouped_scoring_is_off_unless_explicitly_switched_on(monkeypatch):
    """Three calls per frame where there was one. That is the owner's
    money, and it buys a benefit nobody has measured yet."""
    monkeypatch.delenv(ag.ENV_FLAG, raising=False)
    assert ag.enabled() is False
    monkeypatch.setenv(ag.ENV_FLAG, "1")
    assert ag.enabled() is True
    monkeypatch.setenv(ag.ENV_FLAG, "yes")
    assert ag.enabled() is False, "only an explicit 1 turns on 3x spend"
