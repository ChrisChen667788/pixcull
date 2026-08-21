"""v2.68.5 — the photographer had never seen model-written advice.

`enrich_advice` asked M3 for commentary with `max_tokens=700`. M3 is a
reasoning model: it emits a `<think>` block before the answer, and
`m3.py` already carries the measurement for what that costs — "600 was
sized for a non-reasoning VLM … the reasoning alone runs past 2800
characters, leaving nothing for the answer. Measured, not guessed: at
600 every one of 250 calls came back with no JSON." The scoring path was
raised to 3000 on the strength of it. The advice path, whose prompt is
LONGER, stayed at 700 and nobody re-derived the arithmetic.

Every advice call therefore truncated, `advice_from_m3` returned None,
and `enrich_advice` fell back to the template — silently, because
falling back is the correct behaviour on failure and nothing counted how
often it fired.

Re-measured on the owner's own photographs, same images, same prompt:

    max_tokens=700    template, no reading      3 of 3
    max_tokens=3000   minimax-m3, 201-248 字     2 of 3

So "the AI's commentary is too shallow" was a report about 1,576 lines
of templates. The model had never once been heard from.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from pixcull.scoring import m3, m3_advice

ROOT = Path(__file__).resolve().parents[1]


def test_the_advice_budget_is_not_below_the_measured_floor():
    """The advice prompt is longer than the scoring prompt, so its budget
    can never be the smaller of the two."""
    advice = inspect.signature(
        m3_advice.enrich_advice).parameters["max_tokens"].default
    scoring = inspect.signature(m3.MiniMaxM3Judge.score).parameters[
        "max_tokens"].default
    assert advice >= scoring, (
        f"advice asks for {advice} tokens where scoring — with a SHORTER "
        f"prompt — needs {scoring}. At 700 every advice call truncated and "
        f"fell back to the template, which is what 'the AI's commentary is "
        f"too shallow' actually was.")


def test_the_schema_has_room_for_an_argument():
    """Three detached one-line strengths cannot carry a critique.

    What a senior director is paid for is the connection between an
    observation, the judgement it supports, and what they would have
    done instead. The old schema had no field that could hold it, so no
    prompt wording could have produced it.
    """
    assert "reading" in m3_advice.PROMPT, (
        "nothing in the schema asks the model to connect what it sees to "
        "the call it is explaining")
    assert "alternative" in m3_advice.PROMPT

    fallback = {"verdict": "keep", "verdict_short": "保留", "strengths": [],
                "weaknesses": [], "suggestions": [], "inconsistencies": [],
                "rationale": "", "strengths_detail": [],
                "weaknesses_detail": [], "advice_source": "template"}
    import json
    got = m3_advice.advice_from_m3(
        json.dumps({"reading": "企鹅侧头看向画面外。",
                    "alternative": "再低半个机位。",
                    "strengths": ["围巾的暖色把主体拎出来"]},
                   ensure_ascii=False),
        decision="keep", fallback=fallback)
    assert got and got["reading"] and got["alternative"]
    # And the nine-key contract three consumers read is untouched.
    for k in fallback:
        assert k in got, f"{k} vanished — a consumer will fail silently"


def test_a_citation_is_never_invented():
    """"作品塔 · 图底关系", attached to a sentence about contrast, in a
    photographer's inspector.

    The prompt used to require a `source` on every line. A model asked to
    cite something for a claim with no canon behind it will produce one,
    and a citation nobody can look up costs more than the blank it
    replaces — it is the part of the pane that is meant to be checkable.
    """
    prompt = m3_advice.PROMPT
    # Scoped to the `source` field itself. The first version of this
    # assertion looked for the permission anywhere in the prompt, and
    # `alternative` also says "空字符串" — so restoring "必须填" on the
    # citation left the test green. A lint that can be satisfied by an
    # unrelated line is not checking the thing it names.
    at = prompt.index('"source"')
    field = prompt[at:prompt.index("]", at)]
    assert "留空" in field or "空字符串" in field, (
        f"the source field does not permit a blank citation: {field[:120]}")
    assert "必须" not in field, "the citation is mandatory again"
    # An empty source must survive normalisation rather than being filled.
    rows = m3_advice._details(
        [{"axis": "composition", "phrase": "围巾把主体拎出来", "source": ""}],
        ["围巾把主体拎出来"], 3)
    assert rows[0]["source"] == "", "a blank citation got backfilled"


def test_the_reading_renders_only_when_a_model_wrote_it():
    """A template row has no reading, and the section must not appear —
    an empty '◎ 读这张照片' header would advertise depth that is not
    there."""
    js = (ROOT / "pixcull/report/templates/src/results.js").read_text(
        encoding="utf-8")
    code = "\n".join(re.sub(r"//.*$", "", ln) for ln in js.splitlines())
    assert re.search(r"r\.advice\s*&&\s*r\.advice\.reading", code), (
        "nothing reads the reading")
    assert '_sec("reading"' in code, "the reading has no section"
    # _sec returns "" for an empty body, so an absent reading renders
    # nothing. Pin that, because it is what makes the above safe.
    sec = code[code.index("function _sec("):]
    assert "if (!bodyHtml) return \"\";" in sec[:200], (
        "_sec no longer suppresses empty sections, so template rows will "
        "show an empty reading header")


# ---------------------------------------------------------------------------
# v2.68.6 — the pass that had never run
# ---------------------------------------------------------------------------

def test_the_advice_pass_can_find_the_image():
    """`_m3_advice_pass` filtered on a key the built row does not have.

    The row builder renames scores.csv's `path` column to `src_path`.
    The advice pass filtered `r.get("path")`, which is therefore always
    None, so `todo` was always empty and the pass returned 0 on every
    run since v2.51 — seventeen versions of a feature that had never
    once executed.

    It survived because failing quietly is the CORRECT behaviour here
    (advice is commentary on a decision already made, and a key expiring
    must not cost anyone their cull), so an unreachable pass and a
    working one look identical from outside: template advice, no error.

    Caught by rebuilding a real 200-photo run and noticing the page
    returned in 1.9s when 190 cloud calls should have taken minutes.
    """
    from pixcull.report.serve_app import _row_image_path

    # The shape the row builder actually produces.
    assert _row_image_path({"src_path": "/a/b.jpg"}) == "/a/b.jpg"
    # And the CSV's own name, for API-fed rows.
    assert _row_image_path({"path": "/a/b.jpg"}) == "/a/b.jpg"
    assert _row_image_path({}) == ""
    # NaN must not read as a path.
    assert _row_image_path({"src_path": float("nan")}) == ""

    src = (ROOT / "pixcull/report/serve_app.py").read_text(encoding="utf-8")
    at = src.index("def _m3_advice_pass")
    body = src[at:src.index("\ndef ", at + 10)]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert 'r.get("path")' not in code and 'row.get("path")' not in code, (
        "the advice pass is reading a key the built row does not carry")


def test_the_row_builder_and_the_advice_pass_agree_on_the_key():
    """Whatever the row calls its image, both sides must use the same
    name — the bug was two halves of one file disagreeing."""
    src = (ROOT / "pixcull/report/serve_app.py").read_text(encoding="utf-8")
    assert '"src_path": _s(r.get("path", ""))' in src, (
        "the row builder's output key changed; _row_image_path must "
        "follow it or the advice pass goes quiet again")
