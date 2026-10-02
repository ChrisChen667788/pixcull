"""v3.92 — the PyPI page said `pixcull video` detects audio events. It never has.

`run_audio_analysis` was written on 2026-05-29 (v2.0-P1-3) and nothing in
the package has ever called it. `audio_events.json` has two readers — the
reel caption and the review page — and no writer. The learned tagger of
v2.1 and v2.2 is reachable only from its own evaluation script. And
`README-PYPI.md`, which is the PyPI landing page, listed "audio events
(laughter / applause / music)" among the things you get.

Found while fixing an unrelated test in v3.88, and due to be wired in
v3.93. This release goes to PyPI before that, so the sentence came out
rather than be published again. The rule it leaves behind: the claim and
the call arrive together, in either order, or neither is there.

v3.93 — the call arrived, and with a condition the old sentence did not
have. Events come from an optional model; without it the product records
that it did not listen (``tests/test_video_listens_to_the_clip.py`` says
why the DSP detectors are not a substitute). So the claim is true for
someone who has pulled the model and false for someone who has not, and
a public page that names the feature has to name the model beside it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pixcull"
#: What a stranger reads before installing.
PUBLIC = ("README-PYPI.md", "README.md", "modelscope/README.md")
#: Naming the feature as something the product does. Deliberately narrow:
#: release notes that say the feature was *missing* talk about "the audio
#: pass", not "audio events".
CLAIM = re.compile(r"audio events?\s*\(|音频事件", re.I)
#: The kinds, however the sentence is built — v3.93's wording does not
#: say "audio events" at all.
KINDS = re.compile(r"\blaughter\b|\bapplause\b|笑声|掌声", re.I)
#: What a reader has to be told they need.
MODEL = "audio-tagger"


def _callers_of(name: str) -> list[str]:
    """Files in the package that call ``name`` — parsed, so a mention in a
    docstring or a comment is not a call, and the definition is not one."""
    out = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                called = fn.attr if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else None)
                if called == name:
                    out.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return out


def test_audio_events_are_claimed_only_if_something_produces_them():
    claims = [f"{rel}:{i}" for rel in PUBLIC
              for i, line in enumerate(
                  (ROOT / rel).read_text("utf-8").splitlines(), 1)
              if CLAIM.search(line)]
    callers = _callers_of("run_audio_analysis")
    assert not claims or callers, (
        "these lines tell a reader that PixCull detects audio events, and "
        "nothing in the package calls run_audio_analysis, so no run has "
        f"ever produced audio_events.json: {claims}. Wire the pass into "
        "`pixcull video`, or take the claim out.")


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """``(first line number, text)`` for each blank-line-separated block."""
    out, start, buf = [], 1, []
    for i, line in enumerate(text.splitlines() + [""], 1):
        if line.strip():
            if not buf:
                start = i
            buf.append(line)
        elif buf:
            out.append((start, "\n".join(buf)))
            buf = []
    return out


def test_wherever_the_kinds_are_named_the_model_is_named_too():
    """A default install has no audio model and detects nothing. A page
    that lists laughter and applause without saying what they need is
    describing somebody else's install."""
    bare = [f"{rel}:{line}" for rel in PUBLIC
            for line, para in _paragraphs((ROOT / rel).read_text("utf-8"))
            if KINDS.search(para) and MODEL not in para]
    assert not bare, (
        f"these paragraphs name audio event kinds without naming the "
        f"optional model that produces them (`pixcull models pull "
        f"{MODEL}`): {bare}")


def test_the_paragraph_scan_sees_a_bare_claim_and_a_qualified_one():
    text = ("Video — marks laughter and applause.\n\n"
            "Video — with `pixcull models pull audio-tagger` it marks\n"
            "laughter and applause.\n\n"
            "视频 —— 标出笑声和掌声。\n")
    hits = [line for line, para in _paragraphs(text)
            if KINDS.search(para) and MODEL not in para]
    assert hits == [1, 6]


def test_the_scan_tells_a_call_from_a_mention(tmp_path, monkeypatch):
    pkg = tmp_path / "pixcull"
    pkg.mkdir()
    (pkg / "a.py").write_text(
        '"""run_audio_analysis(x) in a docstring."""\n'
        "# run_audio_analysis(x) in a comment\n"
        "def run_audio_analysis(x): return x\n", "utf-8")
    monkeypatch.setattr("tests.test_audio_claim_matches_wiring.PACKAGE", pkg)
    monkeypatch.setattr("tests.test_audio_claim_matches_wiring.ROOT", tmp_path)
    assert _callers_of("run_audio_analysis") == []
    (pkg / "b.py").write_text(
        "from a import run_audio_analysis\nrun_audio_analysis(1)\n", "utf-8")
    assert _callers_of("run_audio_analysis") == ["pixcull/b.py:2"]


def test_the_claim_pattern_matches_the_sentence_that_was_published():
    assert CLAIM.search("temporal scoring, audio events (laughter / "
                        "applause / music), reel-candidate detection")
    assert not CLAIM.search("`pixcull video` has never run the audio pass")
