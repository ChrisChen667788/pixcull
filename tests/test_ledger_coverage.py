"""v2.82 — the remaining three passes, and a guard against a fourth.

v2.71 built the ledger and wired one pass into it. `meta_judge`,
`caption_gen` and `reel_caption` kept falling back silently, which means
each of them could fail for every single image in a run and produce
output indistinguishable from a healthy one: a template caption instead
of a polished caption, a verdict carrying only an error, a `None` that
sends the caller back to the template. No exception, no log line, no
count.

The interesting test here is the last one. Wiring three passes is
bookkeeping; making the fourth impossible to forget is the version.
"""
import ast
import re

import pytest
from pathlib import Path

from pixcull.fallback_ledger import FallbackLedger

ROOT = Path(__file__).resolve().parents[1] / "pixcull"

# Every pass that calls out to a model or a paid endpoint and has a
# fallback. Adding one to the product and not to this list is caught by
# test_no_unledgered_fallback_pass below.
LEDGERED = {
    "m3_advice": ROOT / "report" / "serve_app.py",
    "m3_verdict": ROOT / "scoring" / "m3.py",
    "meta_judge": ROOT / "scoring" / "meta_judge.py",
    "caption_gen": ROOT / "scoring" / "caption_gen.py",
    "reel_caption": ROOT / "scoring" / "reel_caption.py",
}


def _code_only(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    docs = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    body = "\n".join("" if l.lstrip().startswith("#") else l.split("#", 1)[0]
                     for l in text.splitlines())
    for d in docs:
        body = body.replace(d, "")
    return body


def test_each_pass_records_all_four_events():
    """candidates / attempt / ok / fell_back. A pass that records only
    failures cannot produce a rate; one that records only successes
    cannot produce a fallback."""
    for name, path in LEDGERED.items():
        code = _code_only(path)
        assert f'LEDGER.candidates("{name}"' in code, f"{name}: no candidates"
        assert f'LEDGER.attempt("{name}"' in code, f"{name}: no attempt"
        assert f'LEDGER.ok("{name}"' in code, f"{name}: no ok"
        assert f'LEDGER.fell_back("{name}"' in code, f"{name}: no fell_back"


def test_no_unledgered_fallback_pass():
    """The guard that outlives this version.

    Any function that swallows an exception and returns a usable value
    instead — the shape of a silent fallback — must sit in a module that
    talks to the ledger. Wiring three passes is bookkeeping; making the
    fourth impossible to add unnoticed is the point.
    """
    # Explicitly exempt, with the reason. An exemption list is not a
    # weakening: an unexplained silence is what this test exists to stop,
    # and an entry here is a sentence someone had to write.
    EXEMPT = {
        "phrase_generator.py": "offline phrase bank; its fallback is a "
                               "different phrase, not a missing answer",
        "scoring/vlm_judge.py": "loader and parser for the judges that ARE "
                                "ledgered; wiring it would double-count",
        "scoring/reel.py": "assembles a reel from captions already counted "
                           "by reel_caption",
        "cli.py": "argument handling; its one swallowed exception is a "
                  "missing optional import, reported to the user directly",
    }
    suspects = []
    for path in ROOT.rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        if "dist/" in str(path) or "/.venv/" in str(path) or rel in EXEMPT:
            continue
        code = _code_only(path)
        if "api_key" not in code and "client.chat" not in code:
            continue                      # not a paid/model call site
        if "LEDGER." in code:
            continue                      # wired
        # The shape that matters: an except that hands back a usable
        # value instead of raising. A module that merely names an API key
        # is not a silent fallback.
        if not re.search(r"except [^\n]*:\s*\n(?:\s*#[^\n]*\n)*\s*"
                         r"return (?:\{|\"|'|None|[a-z_]+ or )", code):
            continue
        suspects.append(rel)
    assert not suspects, (
        "these modules call a model or a paid endpoint, swallow the "
        "failure into a usable return value, and never touch the ledger, "
        f"so it is invisible: {suspects}")


def test_a_bucket_keeps_its_first_example():
    led = FallbackLedger()
    led.fell_back("p", "request_failed", "ConnectionRefused: nothing listening")
    led.fell_back("p", "request_failed", "a later, less interesting one")
    ex = led.to_json()["passes"]["p"]["examples"]
    assert ex["request_failed"].startswith("ConnectionRefused")


def test_an_unknown_reason_lands_in_other_and_keeps_itself_as_the_example():
    led = FallbackLedger()
    led.fell_back("p", "the disk melted")
    p = led.to_json()["passes"]["p"]
    assert p["by_reason"] == {"other": 1}
    assert p["examples"]["other"] == "the disk melted"


def test_a_pass_that_had_work_and_did_none_is_structural():
    """The condition that is never normal."""
    led = FallbackLedger()
    led.candidates("caption_gen", 40)
    assert led.to_json()["passes"]["caption_gen"]["structural"] is True
    led.attempt("caption_gen", 1)
    assert led.to_json()["passes"]["caption_gen"]["structural"] is False


def test_reel_caption_records_the_missing_model_as_a_fallback():
    """`_try_llm()` returning None sends the caller silently back to the
    template. A run where the local model never loaded once must not be
    reportable as a run that produced captions."""
    code = _code_only(ROOT / "scoring" / "reel_caption.py")
    m = re.search(r"llm = _try_llm\(\)\s*\n\s*if llm is None:\s*\n(\s*)(.+)", code)
    assert m, "could not find the missing-model branch"
    assert "LEDGER.fell_back" in m.group(2), \
        "a missing local model returns None without recording anything"


# Each pass's exits, by the reason each one must record. "The file
# mentions fell_back somewhere" is not enough: a pass with five exits
# and one ledger call passes that check while four of its five silent
# failures stay silent, which is the exact defect this version fixes.
REQUIRED_REASONS = {
    "caption_gen": {
        "no_api_key": "no key configured — returns the unpolished caption",
        "budget_exhausted": "today's spend cap reached",
        "parse_failed": "the model returned an empty completion",
        "request_failed": "the call raised",
    },
    "m3_verdict": {
        "parse_failed": "the reply could not be read as JSON",
        "truncated": "parsed cleanly and still carried no rationale — "
                     "5.1% of the cached corpus, previously indistinguishable "
                     "from a verdict the model declined to give",
    },
    "reel_caption": {
        "request_failed": "the local model never loaded, or the call raised",
        "parse_failed": "the model returned an empty string",
    },
    "meta_judge": {
        "request_failed": "the endpoint was unreachable",
        "parse_failed": "the reply could not be read as JSON",
    },
}


@pytest.mark.parametrize("pass_name", sorted(REQUIRED_REASONS))
def test_every_exit_of_a_pass_records_its_own_reason(pass_name):
    code = _code_only(LEDGERED[pass_name])
    for reason, why in REQUIRED_REASONS[pass_name].items():
        assert f'LEDGER.fell_back("{pass_name}", "{reason}"' in code, (
            f"{pass_name} can fail with {reason} ({why}) and records nothing")


# ------------------------------------------------ v2.93: the false alarm


def test_a_pass_the_operator_disabled_is_not_a_structural_failure():
    """Every `--vlm-mode off` run printed the ledger's loudest warning:
    "FALLBACK FAULT — 4,396 candidate rows, 0 attempted — the pass had
    work and did none". The run asked to stay local and the pass obeyed.
    A warning that fires on the most ordinary configuration is one people
    learn to scroll past, which costs the ledger everything it is for."""
    led = FallbackLedger()
    led.candidates("m3_advice", 4396)
    led.withheld("m3_advice", 4396, "cloud_disabled")
    assert led.structural_failures() == []
    assert led.to_json()["passes"]["m3_advice"]["structural"] is False


def test_a_genuinely_silent_pass_still_shouts():
    """The v2.68.6 shape: work it meant to do, and did none."""
    led = FallbackLedger()
    led.candidates("m3_advice", 200)
    assert led.structural_failures()
    assert led.to_json()["passes"]["m3_advice"]["structural"] is True


def test_excluding_some_does_not_excuse_skipping_the_rest():
    """The mutation that would make this guard useless: withhold a few
    and let the remainder vanish."""
    led = FallbackLedger()
    led.candidates("p", 200)
    led.withheld("p", 150, "decision=cull")
    assert led.structural_failures(), \
        "50 rows were the pass's business and it did none of them"


def test_the_cloud_disabled_exit_records_its_reason():
    code = _code_only(ROOT / "report" / "serve_app.py")
    i = code.find("def _m3_advice_pass")
    body = code[i:i + 4000]
    j = body.find("cloud_allowed()")
    assert j > 0
    assert "cloud_disabled" in body[j:j + 900], (
        "the cloud-disabled exit leaves candidates recorded with nothing "
        "attempted, which reads as a structural failure")
