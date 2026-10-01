"""v3.90 — a run that has died must not be reported as still running.

Issue #3. Offline, 23 photographs, every one failing with the same
``ConnectTimeout``. The reasons went to stderr and were kept nowhere; the
pipeline returned normally with nothing analysed; the server recorded that
as ``done / 完成``; and the results page, finding no ``scores.csv``,
answered ``425 results not ready — pipeline may still be running. Refresh
in a few seconds.`` about a pipeline that had finished two minutes earlier.

Three layers, each held here: the reasons are collected, a run that
produced nothing is an error with its reason, and 425 is answered only
while the analysis is actually running.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from pixcull.pipeline import parallel as P
from pixcull.pipeline import run_failures as RF

ROOT = Path(__file__).resolve().parent.parent
SERVE_APP = ROOT / "pixcull" / "report" / "serve_app.py"
PARALLEL = ROOT / "pixcull" / "pipeline" / "parallel.py"


# -- layer 1: the reasons are collected -------------------------------------

def _timeout(_path):
    raise ConnectionError("[WinError 10060] connect timed out")


@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setenv("PIXCULL_DETECTOR_CACHE", "0")


def test_the_pool_side_wrapper_reports_why_a_frame_failed(
        monkeypatch, no_cache, tmp_path):
    from pixcull.pipeline import worker
    monkeypatch.setattr(worker, "analyze_one", _timeout)
    r = P._analyze_path(str(tmp_path / "a.jpg"))
    assert r[P._FAILED] is True
    assert r["error"].startswith("ConnectionError: ")
    assert "10060" in r["error"]


def test_the_serial_side_wrapper_reports_it_the_same_way(no_cache, tmp_path):
    r = P._analyze_one_safe(str(tmp_path / "a.jpg"), _timeout)
    assert r[P._FAILED] is True and r["error"].startswith("ConnectionError: ")


def test_failures_reach_the_caller_and_never_the_rows(
        monkeypatch, no_cache, tmp_path):
    from pixcull.pipeline import worker
    monkeypatch.setattr(worker, "analyze_one", _timeout)
    failures: list[dict] = []
    rows = P.parallel_analyze([tmp_path / "a.jpg", tmp_path / "b.jpg"],
                              failures=failures)
    assert rows == [], "a failure marker must never be returned as a row"
    assert [Path(f["path"]).name for f in failures] == ["a.jpg", "b.jpg"]


def test_a_frame_that_works_is_still_a_row(monkeypatch, no_cache, tmp_path):
    """The other side: collecting failures must not eat a success."""
    from pixcull.pipeline import worker
    monkeypatch.setattr(worker, "analyze_one",
                        lambda p: {"filename": Path(p).name})
    failures: list[dict] = []
    rows = P.parallel_analyze([tmp_path / "a.jpg"], failures=failures)
    assert rows == [{"filename": "a.jpg"}] and failures == []


def test_omitting_the_list_changes_nothing_else(monkeypatch, no_cache,
                                                tmp_path):
    """``scripts/scan_multi.py`` calls without ``failures``."""
    from pixcull.pipeline import worker
    monkeypatch.setattr(worker, "analyze_one", _timeout)
    assert P.parallel_analyze([tmp_path / "a.jpg"]) == []


def test_both_paths_route_through_the_same_function():
    """The pool cannot be driven from a test without real workers, so its
    half is held structurally: both loops call ``_route`` and both wrappers
    return ``_failure(...)`` from their handler."""
    tree = ast.parse(PARALLEL.read_text("utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def calls(fn, name):
        return [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name) and c.func.id == name]

    assert len(calls(fns["parallel_analyze"], "_route")) == 2, (
        "the serial loop and the pool loop must each route their result")
    for wrapper in ("_analyze_path", "_analyze_one_safe"):
        handlers = [h for h in ast.walk(fns[wrapper])
                    if isinstance(h, ast.ExceptHandler)]
        assert handlers, wrapper
        for h in handlers:
            rets = [r for r in ast.walk(h) if isinstance(r, ast.Return)]
            assert rets and all(
                isinstance(r.value, ast.Call)
                and getattr(r.value.func, "id", None) == "_failure"
                for r in rets), f"{wrapper} swallows a failure without a reason"


# -- the summary -------------------------------------------------------------

def test_failures_are_grouped_by_kind_not_by_message():
    """A message usually carries the file's own path; grouping on it would
    report 23 causes for one."""
    failures = [{"path": f"/shoot/DSCF{i}.JPG",
                 "error": f"ConnectTimeout: timed out reading DSCF{i}.JPG"}
                for i in range(23)]
    failures.append({"path": "/shoot/bad.JPG",
                     "error": "UnidentifiedImageError: cannot identify"})
    s = RF.summarize_failures(failures, total=24, analyzed=0)
    assert s["failed"] == 24 and s["analyzed"] == 0
    assert s["errors"][0]["count"] == 23
    assert s["errors"][0]["error"].startswith("ConnectTimeout: ")
    assert s["errors"][0]["example"] == "DSCF0.JPG"
    assert s["errors"][1]["count"] == 1


def test_no_failures_is_no_summary():
    assert RF.summarize_failures([], total=5, analyzed=5) is None


def test_a_later_success_removes_the_earlier_failure(tmp_path):
    """Both sides of the write: a second run into the same directory that
    succeeds must not leave the first run's failure standing."""
    s = RF.summarize_failures([{"path": "a.jpg", "error": "OSError: x"}],
                              total=1, analyzed=0)
    RF.write_failure_summary(tmp_path, s)
    assert RF.read_failure_summary(tmp_path)["failed"] == 1
    RF.write_failure_summary(tmp_path, None)
    assert not (tmp_path / RF.FILENAME).exists()
    assert RF.read_failure_summary(tmp_path) is None
    RF.write_failure_summary(tmp_path, None)      # idempotent


def test_a_corrupt_summary_reads_as_none(tmp_path):
    (tmp_path / RF.FILENAME).write_text("{not json", "utf-8")
    assert RF.read_failure_summary(tmp_path) is None


def test_the_message_names_the_cause():
    s = RF.summarize_failures(
        [{"path": "a.jpg", "error": "ConnectTimeout: [WinError 10060]"}] * 3,
        total=3, analyzed=0)
    msg = RF.no_results_message(s)
    assert "ConnectTimeout" in msg and "3" in msg
    assert RF.no_results_message(None) == "没有可分析的图片"


# -- layer 2: the pipeline writes it, the server records an error -----------

def _two_fake_photos(folder: Path) -> None:
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("a.jpg", "b.jpg"):
        Image.new("RGB", (32, 32), (120, 120, 120)).save(folder / name)


def test_a_run_where_every_frame_fails_says_so(monkeypatch, no_cache,
                                               tmp_path):
    from pixcull.pipeline import orchestrator, worker
    monkeypatch.setattr(worker, "analyze_one", _timeout)
    src, out = tmp_path / "in", tmp_path / "out"
    _two_fake_photos(src)
    messages: list[str] = []
    orchestrator.run_pipeline(
        src, out, progress_cb=lambda d, t, m: messages.append(m))
    assert not (out / "scores.csv").exists()
    summary = json.loads((out / RF.FILENAME).read_text("utf-8"))
    assert summary["failed"] == 2 and summary["analyzed"] == 0
    assert summary["errors"][0]["error"].startswith("ConnectionError: ")
    assert "ConnectionError" in messages[-1], messages[-1]


@pytest.fixture
def SA():
    from pixcull.report import serve_app
    return serve_app


def _register(SA, tmp_path, run_id="deadrun01"):
    out = tmp_path / run_id / "output"
    out.mkdir(parents=True)
    SA._set_run(run_id, state="queued", input_dir=str(tmp_path / "in"),
                output_dir=str(out))
    return run_id, out


def test_returning_with_no_results_is_recorded_as_an_error(
        monkeypatch, SA, tmp_path):
    """run_pipeline returns normally when nothing could be analysed. The
    thread used to call that ``done``."""
    from pixcull.pipeline import orchestrator
    run_id, out = _register(SA, tmp_path)

    def _dies_quietly(_src, output, **_kw):
        RF.write_failure_summary(output, RF.summarize_failures(
            [{"path": "a.jpg", "error": "ConnectTimeout: [WinError 10060]"}],
            total=1, analyzed=0))
        return output

    monkeypatch.setattr(orchestrator, "run_pipeline", _dies_quietly)
    try:
        SA._analyze_in_background(run_id, "rule", None)
        run = SA._get_run(run_id)
        assert run["state"] == "error"
        assert "ConnectTimeout" in run["message"]
        assert SA._no_results_status(run_id)[0] == 500
        assert "ConnectTimeout" in SA._no_results_status(run_id)[1]
    finally:
        SA._RUNS.pop(run_id, None)


def test_a_run_that_wrote_results_is_still_done(monkeypatch, SA, tmp_path):
    """The other side of the same check."""
    from pixcull.pipeline import orchestrator
    run_id, out = _register(SA, tmp_path, "liverun01")

    def _works(_src, output, **_kw):
        (Path(output) / "scores.csv").write_text("filename\na.jpg\n", "utf-8")
        return output

    monkeypatch.setattr(orchestrator, "run_pipeline", _works)
    try:
        SA._analyze_in_background(run_id, "rule", None)
        assert SA._get_run(run_id)["state"] == "done"
    finally:
        SA._RUNS.pop(run_id, None)


# -- layer 3: 425 only while it is running -----------------------------------

@pytest.mark.parametrize("state", ["queued", "running"])
def test_a_run_in_progress_is_too_early(SA, tmp_path, state):
    run_id, _ = _register(SA, tmp_path, "busy01")
    SA._set_run(run_id, state=state)
    try:
        code, msg = SA._no_results_status(run_id)
        assert code == 425 and "still running" in msg
    finally:
        SA._RUNS.pop(run_id, None)


@pytest.mark.parametrize("state,message", [
    ("error", "分析失败: RuntimeError: boom"),
    ("done", "完成"),
])
def test_a_finished_run_with_nothing_is_not_too_early(SA, tmp_path, state,
                                                     message):
    run_id, _ = _register(SA, tmp_path, "over01")
    SA._set_run(run_id, state=state, message=message)
    try:
        code, msg = SA._no_results_status(run_id)
        assert code == 500
        assert "still running" not in msg and "Refresh" not in msg
        if state == "error":
            assert "boom" in msg
    finally:
        SA._RUNS.pop(run_id, None)


def test_a_run_left_by_a_restart_is_not_too_early(monkeypatch, SA, tmp_path):
    """Not in this process's registry: nothing here is running it."""
    monkeypatch.setattr(SA, "_reload_run_from_disk",
                        lambda rid: {"output_dir": str(tmp_path)})
    code, msg = SA._no_results_status("ghost01")
    assert code == 500 and "not running" in msg


def test_no_route_answers_too_early_on_its_own():
    """Ten routes each sent 425 whenever results were missing. One function
    decides now; a route that brings back its own literal is the defect
    returning for that route alone."""
    tree = ast.parse(SERVE_APP.read_text("utf-8"))
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name == "_no_results_status":
            continue
        for c in ast.walk(fn):
            if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr in ("send_error", "_reject_upload")):
                continue
            consts = [a.value for a in c.args if isinstance(a, ast.Constant)]
            if 425 in consts and any(
                    isinstance(v, str) and "results not ready" in v
                    for v in consts):
                offenders.append(f"{fn.name}:{c.lineno}")
    assert not offenders, (
        "use self.send_error(*_no_results_status(run_id)) — a bare 425 "
        f"tells a dead run to wait: {offenders}")
