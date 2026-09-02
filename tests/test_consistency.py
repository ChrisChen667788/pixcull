"""v3.6 — measured agreement, and the several ways it could be a lie.

The grid shows `⌬ K 85%`. That number is the meta-judge reporting its own
confidence, and nothing has ever checked whether it predicts anything.

Replacing it with a measurement is only worth doing if the measurement is
real, and there are four distinct ways it would not have been:

  * N draws reading one cached answer (v3.2 and the sample index here)
  * a single draw agreeing with itself and being reported as 1.0
  * an API error counted as the model changing its mind
  * agreement read as accuracy
"""
import pytest

from pixcull.scoring import consistency as C


def test_one_draw_is_not_perfect_agreement():
    """The failure mode this whole line of work exists to remove: a
    number that looks like a measurement and is an artefact."""
    assert C.agreement_of(["keep"]) is None
    assert C.agreement_of([]) is None
    assert C.agreement_of([None, "", "  "]) is None


def test_two_draws_are_enough_to_measure():
    a = C.agreement_of(["keep", "maybe"])
    assert a is not None and a.n == 2 and a.agreement == 0.5
    assert a.unanimous is False


def test_unanimous_is_reported_separately_from_the_rate():
    a = C.agreement_of(["cull", "cull", "cull"])
    assert a.agreement == 1.0 and a.unanimous is True


def test_modal_label_wins_and_the_rate_is_its_share():
    a = C.agreement_of(["keep", "keep", "maybe"])
    assert a.modal_label == "keep"
    assert a.agreement == pytest.approx(2 / 3)


def test_the_measured_number_is_named_so_it_cannot_be_mistaken():
    """`confidence` already means the self-reported one. Two floats in
    one row both called confidence is a bug waiting for a consumer."""
    d = C.agreement_of(["keep", "keep"]).as_dict()
    assert "measured_agreement" in d
    assert "confidence" not in d


# -- the gate ---------------------------------------------------------

def test_a_confident_uncontradicted_frame_is_not_resampled():
    """N draws on every frame of a 2,000-frame wedding is the owner's
    money spent answering a question about maybe 200 of them."""
    assert C.should_sample({"meta_confidence": 0.95}) is False


def test_low_confidence_or_a_contradiction_opens_the_gate():
    assert C.should_sample({"meta_confidence": 0.4}) is True
    assert C.should_sample({"meta_confidence": 0.95,
                            "meta_inconsistencies": "焦点与主体冲突"}) is True
    assert C.should_sample({"meta_confidence": 0.95,
                            "meta_inconsistencies": ["a"]}) is True


def test_a_frame_the_meta_pass_never_saw_is_not_sampled():
    """Sampling everything unjudged is how a gate becomes a full pass."""
    assert C.should_sample({}) is False
    assert C.should_sample({"meta_inconsistencies": ""}) is False


def test_sampling_is_off_unless_a_draw_count_is_set(monkeypatch):
    monkeypatch.delenv(C.ENV_FLAG, raising=False)
    assert C.draws_requested() == 0
    monkeypatch.setenv(C.ENV_FLAG, "3")
    assert C.draws_requested() == 3


def test_one_requested_draw_is_treated_as_off():
    """N=1 costs a call per frame and measures nothing."""
    import os
    os.environ[C.ENV_FLAG] = "1"
    try:
        assert C.draws_requested() == 0
    finally:
        os.environ.pop(C.ENV_FLAG, None)


# -- the draws themselves ---------------------------------------------

class _Judge:
    """Records how it was called and returns scripted (label, error) pairs.

    Label and error are independent on purpose. A draw that errors can
    still carry a label — a truncated reply whose first field parsed, a
    budget refusal on a verdict object that was already partly filled —
    and if error is not checked, that half-answer is counted as a vote.
    Tying the two together in the fixture would make the error check look
    tested when nothing tests it.
    """
    def __init__(self, script):
        self.script = [x if isinstance(x, tuple) else (x, None)
                       for x in script]
        self.calls = []

    def score(self, path, *, scene=None, vertical=None, row=None,
              temperature=0.0, sample=0):
        self.calls.append({"temperature": temperature, "sample": sample})
        lab, err = self.script[len(self.calls) - 1]

        class V:
            overall_label = lab
            error = err
        return V()


def test_each_draw_carries_its_own_sample_index():
    """Without this the second and third draws read the first one back
    out of the cache and the measurement is a tautology."""
    j = _Judge(["keep", "maybe", "keep"])
    C.sample(j, "x.jpg", n=3)
    assert [c["sample"] for c in j.calls] == [1, 2, 3]


def test_draws_are_not_taken_at_temperature_zero():
    j = _Judge(["keep", "keep"])
    C.sample(j, "x.jpg", n=2)
    assert all(c["temperature"] > 0 for c in j.calls)


def test_an_errored_draw_is_dropped_even_when_it_carries_a_label():
    """An API timeout is not the model changing its mind.

    The errored draw here says "cull" — a truncated reply whose label
    field happened to parse. Counted, it turns a unanimous pair into a
    two-thirds split and invents a disagreement.
    """
    j = _Judge(["keep", ("cull", "truncated"), "keep"])
    a = C.sample(j, "x.jpg", n=3)
    assert a.n == 2 and a.unanimous is True and a.modal_label == "keep"


def test_all_draws_failing_yields_no_measurement_rather_than_a_number():
    j = _Judge([("keep", "boom"), ("keep", "boom")])
    assert C.sample(j, "x.jpg", n=2) is None
