"""v2.71 — a silent fallback has to be counted.

`_m3_advice_pass` returned 0 on every run for seventeen versions and
nothing noticed. The reason it could hide is a property of the design
rather than an oversight: **falling back is the correct behaviour**, so
a pass that works and a pass that has never executed produce identical
output — template advice, no error, no line anywhere.

The distinction that matters is not "did it fail". Failures are expected
and handled. It is:

* **fell back** — tried, and the fallback took over. A rate. 9% is life,
  100% is a bug wearing life's clothes.
* **had work and did none** — the v2.68.6 signature exactly, and the one
  state that is never normal.

Wired up, the ledger caught a second, live bug within minutes: the
verdict cache did not store `raw_text`, which is the entire payload
`m3_advice` parses. So advice worked exactly ONCE per photograph and
reverted to templates on every later run — 195 of 197 rows reported
`parse_failed`, and every version before this one reported nothing.
"""

from __future__ import annotations

import pytest

from pixcull.fallback_ledger import REASONS, FallbackLedger


def test_work_available_and_none_attempted_is_named():
    """The v2.68.6 signature. Nothing else in the ledger is an alarm."""
    L = FallbackLedger()
    L.candidates("advice", 200)
    faults = L.structural_failures()
    assert faults, "a pass with 200 candidates and 0 attempts went unreported"
    assert "200 candidate rows, 0 attempted" in faults[0]


def test_an_ordinary_fallback_rate_is_not_a_fault():
    """9% is life. A ledger that cries at every fallback gets muted, and
    then it is worth exactly as much as no ledger."""
    L = FallbackLedger()
    L.candidates("advice", 100)
    for _ in range(100):
        L.attempt("advice")
    for _ in range(91):
        L.ok("advice")
    for _ in range(9):
        L.fell_back("advice", "truncated")
    assert L.structural_failures() == []
    st = L.snapshot()["advice"]
    assert st.fallback_rate == pytest.approx(0.09)
    assert "9% fell back" in st.summary()


def test_total_fallback_is_a_fault():
    L = FallbackLedger()
    L.candidates("advice", 50)
    for _ in range(50):
        L.attempt("advice")
        L.fell_back("advice", "parse_failed")
    assert L.structural_failures(), (
        "every attempt fell back and the run reported success")


def test_an_unknown_reason_is_bucketed_but_not_lost():
    """Bucketing that discards the outlier reintroduces the problem this
    module exists to solve, one level up."""
    L = FallbackLedger()
    L.attempt("x")
    L.fell_back("x", "something nobody anticipated")
    st = L.snapshot()["x"]
    assert st.by_reason == {"other": 1}
    assert "something nobody anticipated" in st.examples.get("other", "")


def test_the_ledger_never_raises():
    """A ledger that can break a run would be a worse bug than the one it
    exists to catch."""
    L = FallbackLedger()
    L.candidates("x", -5)
    L.fell_back("x", None)          # type: ignore[arg-type]
    L.attempt("x", 0)
    assert isinstance(L.to_json(), dict)


def test_the_advice_pass_books_its_candidates_before_filtering():
    """Counting only what survived the filter cannot detect a filter that
    drops everything — which is precisely what happened."""
    import inspect

    from pixcull.report import serve_app

    src = inspect.getsource(serve_app._m3_advice_pass)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    at_cand = code.index('LEDGER.candidates("m3_advice"')
    at_filter = code.index("_row_image_path(r)]")
    assert at_cand < at_filter, (
        "candidates are counted after the eligibility filter, so a filter "
        "that matches nothing still reports zero candidates")


def test_enrich_advice_can_report_why_it_fell_back():
    import inspect

    from pixcull.scoring import m3_advice

    sig = inspect.signature(m3_advice.enrich_advice)
    assert "on_fallback" in sig.parameters, (
        "every `return fallback` is invisible to the caller again")
    seen = []
    out = m3_advice.enrich_advice(
        {}, {}, "keep", {"advice_source": "template"}, judge=None,
        image_path=None, on_fallback=seen.append)
    assert out == {"advice_source": "template"}
    assert seen == ["no_image"]


def test_a_broken_reporter_cannot_break_the_caller():
    from pixcull.scoring import m3_advice

    def _explode(_reason):
        raise RuntimeError("telemetry is down")

    out = m3_advice.enrich_advice(
        {}, {}, "keep", {"advice_source": "template"}, judge=None,
        image_path=None, on_fallback=_explode)
    assert out == {"advice_source": "template"}


# ---------------------------------------------------------------------------
# The bug the ledger found on its first run
# ---------------------------------------------------------------------------

def test_the_verdict_cache_round_trips_raw_text():
    """`m3_advice` parses its whole output out of `raw_text`.

    The cache stored every other field and dropped that one, so a cache
    hit handed the advice path an empty string: the feature worked
    exactly once per photograph and silently reverted to templates
    forever after. A cache that drops a field the caller reads changes
    behaviour on the SECOND call and not the first, which is the hardest
    kind of bug to see from outside.
    """
    from pixcull.scoring.m3 import _verdict_from_dict
    from pixcull.scoring.vlm_judge import VlmVerdict

    v = VlmVerdict(filename="a.jpg", axes={})
    v.raw_text = '{"reading": "企鹅侧头看向画面外"}'
    d = v.to_dict()
    assert "raw_text" in d, "the cache drops the model's own words"
    back = _verdict_from_dict(d, "a.jpg", "m3")
    assert back.raw_text == v.raw_text


def test_a_pre_v271_cache_entry_is_a_miss_for_a_caller_that_needs_raw_text():
    """Entries written before this version carry no raw_text. Serving
    one to the advice path would read as 'the model said nothing'."""
    import inspect

    from pixcull.scoring.m3 import MiniMaxM3Judge

    src = inspect.getsource(MiniMaxM3Judge.score)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert 'prompt_override and not (hit.get("raw_text")' in code, (
        "a cache entry with no raw_text is still served to callers that "
        "parse it, so old entries stay permanently broken")
