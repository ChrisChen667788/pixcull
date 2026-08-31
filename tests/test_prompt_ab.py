"""v2.91 — the guards a prompt A/B needs before it is worth running.

Not the run. The run needs an API budget the owner controls, and
spending it unbidden is not an agent's decision. What is buildable now
is everything that stops the run producing a confident wrong answer.
"""
import pytest

from pixcull.scoring.prompt_ab import Arm, arm_differences, cache_key, plan


def _arm(name, prompt, **kw):
    base = dict(model="m", temperature=0.3, max_tokens=3000)
    base.update(kw)
    return Arm(name=name, prompt=prompt, **base)


def _cost(_model, pt, ct):
    return (pt + ct) / 1_000_000.0


FRAMES = [f"f{i}.jpg" for i in range(150)]


def test_arms_that_differ_in_the_model_are_refused():
    """"We changed the prompt and the model and it got better" is not a
    finding about a prompt."""
    p = plan([_arm("a", "P1"), _arm("b", "P2", model="other")],
             FRAMES, ceiling_units=1e9, estimate_cost=_cost)
    assert p.refused and "more than the prompt" in p.refused
    assert any("model" in d for d in p.differences)


@pytest.mark.parametrize("field,value", [
    ("temperature", 0.9), ("max_tokens", 500),
])
def test_any_other_difference_is_refused(field, value):
    p = plan([_arm("a", "P1"), _arm("b", "P2", **{field: value})],
             FRAMES, ceiling_units=1e9, estimate_cost=_cost)
    assert p.refused
    assert any(field in d for d in p.differences)


def test_identical_prompts_are_refused():
    p = plan([_arm("a", "SAME"), _arm("b", "SAME")],
             FRAMES, ceiling_units=1e9, estimate_cost=_cost)
    assert p.refused and "same prompt" in p.refused


def test_one_arm_is_not_an_ab():
    p = plan([_arm("a", "P")], FRAMES, ceiling_units=1e9, estimate_cost=_cost)
    assert p.refused and "two arms" in p.refused


def test_too_few_frames_is_refused():
    p = plan([_arm("a", "P1"), _arm("b", "P2")], FRAMES[:20],
             ceiling_units=1e9, estimate_cost=_cost)
    assert p.refused and "below the floor" in p.refused


def test_the_ceiling_is_checked_before_the_first_call():
    """Bounded, not tracked. A run that stops halfway leaves one arm
    half-measured, which is worse than not starting."""
    p = plan([_arm("a", "P1"), _arm("b", "P2")], FRAMES,
             ceiling_units=1e-9, estimate_cost=_cost)
    assert p.refused and "ceiling" in p.refused
    assert p.est_calls == 300, "the estimate is still reported when refusing"


def test_a_clean_plan_carries_no_refusal():
    p = plan([_arm("a", "P1"), _arm("b", "P2")], FRAMES,
             ceiling_units=1e9, estimate_cost=_cost)
    assert p.refused is None
    assert p.est_calls == 300


# ------------------------------------------------------------ cache keys


def test_two_arms_cannot_share_a_cached_answer():
    """The mirror of v2.66's bug, and worse: arm B reading arm A's
    cached answers reports them as its own and the A/B ties perfectly."""
    a, b = _arm("a", "P1"), _arm("b", "P2")
    assert cache_key(a, "f.jpg", prompt_version="v1") != \
        cache_key(b, "f.jpg", prompt_version="v1")


def test_editing_a_prompt_changes_its_key():
    """Two runs a week apart, same arm name, edited prompt. Without the
    prompt text in the key the second run reads the first one's answers."""
    a1 = _arm("a", "P1")
    a2 = _arm("a", "P1 with one more sentence")
    assert cache_key(a1, "f.jpg", prompt_version="v1") != \
        cache_key(a2, "f.jpg", prompt_version="v1")


def test_the_same_arm_and_frame_is_stable():
    a = _arm("a", "P1")
    assert cache_key(a, "f.jpg", prompt_version="v1") == \
        cache_key(a, "f.jpg", prompt_version="v1")


def test_different_frames_do_not_collide():
    a = _arm("a", "P1")
    keys = {cache_key(a, f, prompt_version="v1") for f in FRAMES}
    assert len(keys) == len(FRAMES)


def test_the_prompt_version_still_participates():
    a = _arm("a", "P1")
    assert cache_key(a, "f.jpg", prompt_version="v1") != \
        cache_key(a, "f.jpg", prompt_version="v2")


def test_the_key_is_safe_without_plan_having_run():
    """`cache_key` is callable on its own, so its safety cannot rest on
    `plan()` having refused the bad cases first. Two arms that differ
    only in name — which plan() would reject, but a caller reaching for
    the key directly never sees — must still not share a cached answer.
    """
    a = _arm("baseline", "IDENTICAL PROMPT")
    b = _arm("candidate", "IDENTICAL PROMPT")
    assert cache_key(a, "f.jpg", prompt_version="v1") != \
        cache_key(b, "f.jpg", prompt_version="v1"), (
        "the arm name is not in the key, so a caller who skips plan() "
        "gets arm A's cached answers reported as arm B's")


def test_arm_differences_reports_every_field_that_moved():
    a = _arm("a", "P1")
    b = _arm("b", "P2", model="other", temperature=0.9, max_tokens=10)
    diffs = arm_differences(a, b)
    assert len(diffs) == 3
    assert any("model" in d for d in diffs)
    assert any("temperature" in d for d in diffs)
    assert any("max_tokens" in d for d in diffs)
