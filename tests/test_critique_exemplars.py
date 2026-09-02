"""v3.4 — worked critiques in the prompt, with provenance enforced.

The prompt grounds itself in the photography canon as abstract principle
text and has never shown the model a finished critique. That is the half
of AtelierJudge's design that transfers.

The risk being guarded here is not that the mechanism fails. It is that a
critique written by someone who is not a working photographer gets
injected as an example of photographic expertise — teaching a model to
imitate a non-expert, invisibly, inside a prompt nobody reads. That is
the same act as fabricating a label, one layer up.
"""
import json

from pixcull.scoring import critique_exemplars as ce


def test_an_exemplar_with_undeclared_provenance_never_reaches_a_prompt():
    got = ce._clean([
        {"reading": "有出处的一条,观察带到后果。", "provenance": "cache-selected"},
        {"reading": "没有出处的一条。"},
        {"reading": "出处是编的。", "provenance": "expert"},
        {"reading": "出处是空的。", "provenance": ""},
    ])
    assert [g["reading"] for g in got] == ["有出处的一条,观察带到后果。"]


def test_every_shipped_exemplar_declares_a_known_provenance():
    payload = json.loads(ce.DATA.read_text(encoding="utf-8"))
    banks = payload["exemplars"]
    assert banks, "the shipped bank is empty"
    for key, items in banks.items():
        for it in items:
            assert it.get("provenance") in ce.KNOWN_PROVENANCE, (
                f"{key} carries an exemplar with provenance "
                f"{it.get('provenance')!r}"
            )


def test_nothing_shipped_claims_to_come_from_a_photographer():
    """`photographer` is the only provenance that makes the bank an
    upgrade rather than a stabiliser. Claiming it without a photographer
    having written the text is the failure this whole module guards."""
    payload = json.loads(ce.DATA.read_text(encoding="utf-8"))
    for items in payload["exemplars"].values():
        for it in items:
            assert it["provenance"] != "photographer", (
                "an exemplar claims photographer provenance; a working "
                "photographer has not written or approved one yet"
            )


def test_prompt_section_names_the_provenance_of_each_exemplar():
    sec = ce.prompt_section(None)
    assert "cache-selected" in sec


def test_prompt_section_asks_for_the_form_not_the_content():
    """Exemplars are a strong stylistic attractor. Without this the model
    reuses their openings on photographs where that is the wrong move."""
    sec = ce.prompt_section(None)
    assert "只示范形式" in sec
    assert "不要模仿它们的内容" in sec


def test_unknown_vertical_falls_back_to_the_default_bank():
    assert ce.for_vertical("no-such-vertical") == ce.for_vertical(None)


def test_prompt_section_is_a_string_never_none():
    assert ce.prompt_section(None) != ""
    assert isinstance(ce.prompt_section("anything"), str)


def test_bank_is_capped_so_it_cannot_crowd_out_the_evidence():
    assert ce.MAX_IN_PROMPT <= 3
    assert len(ce.for_vertical(None)) <= ce.MAX_IN_PROMPT


# -- reachability and the off-switch ----------------------------------

def test_the_advice_prompt_actually_carries_the_section():
    import importlib
    import os
    os.environ.pop("PIXCULL_CRITIQUE_EXEMPLARS", None)
    from pixcull.scoring import m3_advice
    importlib.reload(m3_advice)
    on = m3_advice.build_prompt({}, {}, "cull")
    assert "写法示范" in on
    assert "None" not in on and "{exemplars}" not in on


def test_the_off_switch_removes_it(monkeypatch):
    import importlib
    monkeypatch.setenv("PIXCULL_CRITIQUE_EXEMPLARS", "0")
    from pixcull.scoring import m3_advice
    importlib.reload(m3_advice)
    off = m3_advice.build_prompt({}, {}, "cull")
    assert "写法示范" not in off
    monkeypatch.delenv("PIXCULL_CRITIQUE_EXEMPLARS")
    importlib.reload(m3_advice)


def test_the_advice_pass_passes_the_vertical_through():
    import inspect
    src = inspect.getsource(
        __import__("pixcull.report.serve_app", fromlist=["x"]))
    assert 'vertical=str((rec or row).get("vertical")' in src


def test_the_cache_now_records_which_shoot_type_a_call_was_for():
    """Without this the bank can never become per-vertical: scene and
    vertical lived only in the cache key, which is a hash."""
    import inspect
    from pixcull.scoring import m3
    src = inspect.getsource(m3.MiniMaxM3Judge.score)
    assert '"scene": scene or ""' in src
    assert '"vertical": vertical or ""' in src
