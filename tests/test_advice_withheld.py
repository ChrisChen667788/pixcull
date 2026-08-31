"""v2.81 — the deep critique was withheld from every discarded frame.

`_m3_advice_pass` filtered on `decision in ("keep", "maybe")`. For a
culling tool that is backwards: "why are you throwing this one away" is
the question the product exists to answer, and it was answered by the
one-line verdict rationale — which names something in the frame AND
connects it to a consequence 47.7% of the time — while the deep critique,
which does both 96.1% of the time and never comes back empty, went to the
keepers.

Including culls roughly doubles the calls, which is the owner's money, so
the default is unchanged. What changed is that the policy is now a number
instead of an implicit rule. An implicit rule nobody can see is
indistinguishable from a bug; that is the lesson of v2.68.6, v2.75 and
v2.76 in this repository.
"""
import ast
import dataclasses
from pathlib import Path

from pixcull.fallback_ledger import FallbackLedger, PassStat

SRC = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "serve_app.py"


def _code_only(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    docs = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    lines = ["" if l.lstrip().startswith("#") else l.split("#", 1)[0]
             for l in text.splitlines()]
    body = "\n".join(lines)
    for d in docs:
        body = body.replace(d, "")
    return body


# ------------------------------------------------------------- the ledger


def test_withheld_is_recorded_with_its_reason():
    led = FallbackLedger()
    led.candidates("m3_advice", 104)
    led.withheld("m3_advice", 95, "decision=cull")
    p = led.to_json()["passes"]["m3_advice"]
    assert p["withheld"] == 95
    assert p["withheld_reasons"] == {"decision=cull": 95}


def test_withheld_is_not_a_fallback():
    """Three different things, and conflating them is how a policy hides.
    `fell_back` = tried and could not. The candidates/attempted gap =
    should have tried and did not. `withheld` = declined by design."""
    led = FallbackLedger()
    led.candidates("m3_advice", 10)
    led.withheld("m3_advice", 90, "decision=cull")
    led.attempt("m3_advice", 10)
    led.ok("m3_advice", 10)
    p = led.to_json()["passes"]["m3_advice"]
    assert p["fell_back"] == 0
    assert p["fallback_rate"] == 0.0
    assert p["structural"] is False
    assert p["withheld"] == 90


def test_every_passstat_field_survives_a_snapshot():
    """snapshot() copied fields by hand, so `withheld` was recorded
    correctly and read back as 0. Any field added after this test must
    survive, or the number it carries silently becomes its default."""
    led = FallbackLedger()
    led.candidates("p", 3)
    led.attempt("p", 3)
    led.ok("p", 1)
    led.fell_back("p", "parse")
    led.withheld("p", 7, "decision=cull")
    snap = led.snapshot()["p"]
    live = led._passes["p"]
    for f in dataclasses.fields(PassStat):
        assert getattr(snap, f.name) == getattr(live, f.name), \
            f"snapshot() dropped PassStat.{f.name}"


def test_a_snapshot_is_detached():
    led = FallbackLedger()
    led.withheld("p", 1, "r")
    snap = led.snapshot()["p"]
    snap.withheld_reasons["r"] = 999
    assert led.to_json()["passes"]["p"]["withheld_reasons"]["r"] == 1


# --------------------------------------------------------------- the pass


def test_the_advice_pass_records_what_it_denies():
    code = _code_only(SRC)
    i = code.find("def _m3_advice_pass")
    assert i > 0
    body = code[i:i + 4000]
    assert "withheld" in body, (
        "the pass excludes culled frames and records nothing; the policy "
        "is invisible and therefore indistinguishable from a defect")


def test_culled_frames_are_reachable_by_configuration():
    code = _code_only(SRC)
    i = code.find("def _m3_advice_pass")
    body = code[i:i + 4000]
    assert "PIXCULL_ADVISE_CULL" in body
    assert '"cull"' in body, "no configuration admits culled frames at all"
