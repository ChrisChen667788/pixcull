"""v2.79 — the complaint "too shallow" turned into numbers.

Four signals, reported separately and never combined into one score. A
composite would let a prompt change claim victory by moving the cheapest
component, and "is this critique good" is a photographer's judgement, not
a regex's.

Baseline over 4,318 cached VLM verdicts (docs/ADVICE-DEPTH-BASELINE.md):
  empty 9.0%   median 69 chars   sees_the_picture 63%   argues 65%
  BOTH 45.7%   hedged 3.1%
"""
import pytest

from pixcull.scoring.advice_depth import Depth, measure, summarise

DEEP = ("构图 5★ 拉满,S 形潮沟引导线与藏露比例堪称海岸风光范本;"
        "光线 4★ 强反射塑造肌理但缺暖调情绪;整体为可入作品集的抽象海岸纪实。")
THIN = "这张照片展现了较为不错的画面,整体来说构图或用光有一定的可取之处。"
METRIC_ONLY = "Zone V 偏差 0.4%,拉普拉斯方差 312,高光剪切 0.2%,综合判定保留。"


def test_it_separates_a_real_critique_from_a_template_one():
    """If this ever stops holding, the metric has stopped measuring."""
    d, t = measure(DEEP), measure(THIN)
    assert d.sees_the_picture and not t.sees_the_picture
    assert d.argues and not t.argues
    assert t.hedges > d.hedges


def test_reciting_the_numbers_does_not_count_as_seeing_the_picture():
    """The template path can produce fluent, specific-sounding text made
    entirely of measurements. That is the exact failure being measured."""
    m = measure(METRIC_ONLY)
    assert not m.sees_the_picture, \
        "a critique made only of readings must not score as having looked"


def test_the_two_signals_are_independent():
    """Each must be reachable without the other, or the pair is one
    signal wearing two names and the 45.7% figure means nothing."""
    sees_only = measure("画面里新娘的手放在栏杆上,发丝清晰。")
    argues_only = measure("测光偏差虽小,但动态范围压缩导致判定下调。")
    assert sees_only.sees_the_picture and not sees_only.argues
    assert argues_only.argues and not argues_only.sees_the_picture


def test_empty_is_a_zero_not_an_error():
    for empty in (None, "", "   "):
        m = measure(empty)
        assert m == Depth(0, False, 0, False, 0, 0, ())


def test_empty_critiques_count_in_the_denominator():
    """9% of the cached corpus is empty. Reporting rates over only the
    non-empty texts would hide a pass that stopped producing output —
    the failure most worth catching, and the one that looks best."""
    s = summarise([DEEP, None, None, None], field="reading")
    assert s["n"] == 4 and s["empty"] == 3
    assert s["sees_the_picture_rate"] == pytest.approx(0.25)


def test_the_hedge_the_prompt_already_forbids_is_detected():
    """The advice prompt forbids offering two possibilities instead of
    looking — "expression or movement". It shipped anyway, so the
    instruction alone was not enough and something has to check."""
    m = measure("捕捉到动物的神情或动作,值得保留。")
    assert m.hedges > 0
    assert "两可并列" in m.hedge_kinds


def test_a_longer_text_is_not_automatically_deeper():
    """Length is reported, never scored. Padding must not buy depth."""
    padded = THIN + THIN + THIN
    assert measure(padded).length > measure(DEEP).length
    assert not measure(padded).sees_the_picture


def test_summarise_reports_both_rather_than_either():
    """A corpus where half the texts see the picture and the other half
    argue is not a corpus of critiques — it is two piles of halves."""
    s = summarise(["新娘的手搭在栏杆上。", "因为动态范围压缩,判定下调。"], field="reading")
    assert s["sees_the_picture_rate"] == pytest.approx(0.5)
    assert s["argues_rate"] == pytest.approx(0.5)
    assert s["both_rate"] == pytest.approx(0.0)


# --------------------------------------------------------------------
# v3.1 — a corpus figure has to say which field it measured.
#
# v2.81 published a depth baseline that averaged two different call
# types together: verdict calls carry a one-line `overall_rationale` by
# design, advice calls carry the multi-sentence `reading`. The averaged
# figure was wrong in a way nobody could see from the number, because
# the number did not say what it was over. These pin the guard.
# --------------------------------------------------------------------

def test_summarise_refuses_to_produce_an_unlabelled_figure():
    import pytest
    with pytest.raises(TypeError):
        summarise(["新娘的手搭在栏杆上,所以视线被带向左侧。"])  # type: ignore[call-arg]


def test_summarise_refuses_a_blank_field_name():
    import pytest
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            summarise(["新娘的手搭在栏杆上。"], field=bad)


def test_summarise_carries_the_field_into_the_result():
    s = summarise(["新娘的手搭在栏杆上,所以视线被带向左侧。"],
                  field="advice.reading")
    assert s["field"] == "advice.reading"


def test_baseline_doc_names_the_field_of_every_figure_it_reports():
    """The published baseline must not contain a table nobody can attribute.

    Not a style check: the v2.81 defect was exactly a table of rates with
    no field named above it.
    """
    from pathlib import Path
    doc = Path(__file__).resolve().parent.parent / "docs" / "ADVICE-DEPTH-BASELINE.md"
    text = doc.read_text(encoding="utf-8")
    # Every "median length" row belongs to a section that names its field.
    sections = text.split("\n### ")[1:]
    assert sections, "baseline doc has no per-field sections"
    for sec in sections:
        if "median length" not in sec:
            continue
        head = sec.split("\n", 1)[0]
        assert ("rationale" in head or "reading" in head
                or "alternative" in head), (
            f"section {head!r} reports a median with no field named in its heading"
        )
