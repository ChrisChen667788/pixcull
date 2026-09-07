"""v3.21 — the run's health, where the photographer can find it.

`fallback_ledger` has recorded, per pass, how many frames were
candidates, how many were attempted, what was withheld and why, and the
server has put all of it in /api/run/<id>.  `results.html` never read a
byte of it.  So a run that quietly fell back to template advice on 40% of
frames looked, in the report, exactly like one that did not, and the only
route to the truth was /admin — which a photographer has no reason to
open on a good day and no idea to open on a bad one.
"""
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parent.parent / "pixcull" / "report"
       / "templates" / "src" / "modules" / "35-session-health.js")


def _summarise(fallbacks, faults=None):
    """Run the module's own summarise() under node."""
    if not SRC.exists():
        pytest.skip("module missing")
    harness = f"""
    global.window = {{}}; global.document = {{
        readyState: "complete", addEventListener: function () {{}},
        querySelector: function () {{ return null; }},
        getElementById: function () {{ return null; }},
        createElement: function () {{ return {{ style: {{}},
            classList: {{ add: function () {{}} }},
            addEventListener: function () {{}} }}; }},
        body: {{ appendChild: function () {{}} }} }};
    global.fetch = function () {{ return {{ then: function () {{
        return {{ then: function () {{ return {{ catch: function () {{}} }};
        }} }}; }} }}; }};
    {SRC.read_text(encoding="utf-8")}
    const out = window.PixCullSessionHealth.summarise(
        {json.dumps(fallbacks)}, {json.dumps(faults or [])});
    console.log(JSON.stringify(out));
    """
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(harness)
        p = fh.name
    got = subprocess.run(["node", p], capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout.strip())


def _pass(**kw):
    base = {"candidates": 0, "attempted": 0, "succeeded": 0, "fell_back": 0,
            "fallback_rate": 0.0, "by_reason": {}, "withheld": 0,
            "withheld_reasons": {}, "structural": False}
    base.update(kw)
    return base


def test_a_clean_run_renders_nothing():
    """Health telemetry in the main view reads as self-flagellation and
    gets ignored within a week. Nothing to say means no chip."""
    assert _summarise({"passes": {"m3_advice": _pass(attempted=9,
                                                     succeeded=9)}}) is None


def test_no_ledger_at_all_renders_nothing():
    assert _summarise(None) is None
    assert _summarise({}) is None


def test_a_fallback_is_reported_with_its_reason():
    got = _summarise({"passes": {"m3_advice": _pass(
        attempted=10, succeeded=6, fell_back=4, fallback_rate=0.4,
        by_reason={"budget_exhausted": 4})}})
    assert got["level"] == "degraded"
    assert got["lines"][0]["rate"] == 40
    assert "budget_exhausted×4" in got["lines"][0]["why"]


def test_withheld_is_counted_separately_from_fell_back():
    """They are opposite findings. "Tried and used the fallback" and
    "never tried" have to stay distinguishable or the ledger's whole
    point is lost."""
    got = _summarise({"passes": {"m3_advice": _pass(
        withheld=7, withheld_reasons={"cloud_disabled": 7})}})
    assert got["lines"][0]["withheld"] == 7
    assert got["lines"][0]["fell_back"] == 0
    assert "cloud_disabled×7" in got["lines"][0]["heldWhy"]


def test_a_pass_that_did_nothing_wrong_is_not_listed():
    got = _summarise({"passes": {
        "ok_pass": _pass(attempted=5, succeeded=5),
        "bad_pass": _pass(attempted=5, succeeded=1, fell_back=4,
                          fallback_rate=0.8, by_reason={"x": 4})}})
    assert [l["pass"] for l in got["lines"]] == ["bad_pass"]


def test_a_structural_fault_outranks_a_rate():
    """"This pass had work to do and did none of it" is not a percentage,
    it is a thing that is broken."""
    got = _summarise({"passes": {"m3_advice": _pass(
        attempted=10, succeeded=9, fell_back=1, fallback_rate=0.1,
        by_reason={"x": 1})}},
        faults=["m3_advice: 0/1 ok, 100% fell back"])
    assert got["level"] == "fault"
    assert got["faults"]


def test_a_fault_alone_still_reports():
    got = _summarise({"passes": {}}, faults=["m3_advice: had 40, did 0"])
    assert got is not None and got["level"] == "fault"


# -- reachability -----------------------------------------------------

def test_the_module_is_spliced_into_the_page():
    js = (Path(__file__).resolve().parent.parent / "pixcull" / "report"
          / "templates" / "src" / "results.js").read_text(encoding="utf-8")
    assert "@@MODULE:35-session-health.js@@" in js
    built = (Path(__file__).resolve().parent.parent / "pixcull" / "report"
             / "templates" / "results.html").read_text(encoding="utf-8")
    assert "PixCullSessionHealth" in built


def test_it_reads_the_keys_the_server_actually_sends():
    src = SRC.read_text(encoding="utf-8")
    assert "view.fallbacks" in src and "view.fallback_faults" in src


# -- the reachability this module shipped without --------------------
#
# The first version of these three did not exist, and the module fetched
# `/api/run/<id>` — a route the server does not have — read the run id off
# `window.run_id` when the page injects it as a scope const, and hit a
# `_serve_status` that 404s for any run the process had not scanned.
# Three independent breaks, all invisible: the module swallows fetch
# errors by design, so the chip simply never appeared and every test
# passed.

def _code_only(js: str) -> str:
    """JS with `//` comments removed.

    The third time in this block that a guard was satisfied by the
    explanation instead of the code: this module discusses `window.run_id`
    at length precisely because it must not read it, and a plain substring
    search was happy to find the sentence.
    """
    return "\n".join(line.split("//", 1)[0] for line in js.splitlines())


def test_the_url_it_fetches_is_a_route_the_server_registers():
    import re
    import inspect
    from pixcull.report import serve_app

    src = SRC.read_text(encoding="utf-8")
    m = re.search(r'fetch\("(/[a-z_/]+)"', _code_only(src))
    assert m, "the module fetches no literal path"
    route = m.group(1)
    registered = inspect.getsource(serve_app)
    assert f'("{route}"' in registered, (
        f"the module fetches {route!r}, which the server does not route")


def test_it_reads_the_run_id_the_way_the_page_provides_it():
    """Every other module references `run_id` bare, because the page
    injects it as a const in this script's scope. `window.run_id` is
    undefined there, and undefined means the module returns early."""
    code = _code_only(SRC.read_text(encoding="utf-8"))
    assert "window.run_id" not in code, (
        "reads the run id off window; the page injects it as a scope const")
    assert "typeof run_id ===" in code


def test_the_status_endpoint_survives_a_server_restart():
    """It only looked in the in-process registry, so a report opened for
    a run this process had not scanned — the normal case after a restart,
    and the case the chip needs — returned 404."""
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app.PixCullHandler._serve_status) \
        if hasattr(serve_app, "PixCullHandler") else ""
    if not src:
        whole = inspect.getsource(serve_app)
        i = whole.index("def _serve_status(self")
        src = whole[i:i + 600]
    assert "_reload_run_from_disk(run_id)" in src
