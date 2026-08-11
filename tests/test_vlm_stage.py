"""v2.48-P2 — the VLM scoring stage, which nothing covered before.

``run_pipeline``'s VLM stage had no test at all: the only two tests that
touch ``run_pipeline`` never enable a VLM.  That is the "advertised but
unreachable" shape this repo keeps rediscovering, and it is why the loop
could sit for months pointed at a dead endpoint.

The stage was extracted to :func:`run_vlm_stage` in v2.48-P2 so it has
somewhere to be tested at all.

What is actually risky here is not the API call — it is the bookkeeping
around concurrency.  Workers now finish **out of order**, so every
verdict has to find its way back to its own row.  Getting that wrong
does not raise: pandas happily writes 5 stars onto the neighbouring
photo, the CSV stays well-formed, and the mistake is invisible until a
photographer wonders why a blurred frame is rated highly.
"""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

from pixcull.pipeline.orchestrator import _vlm_workers, run_vlm_stage
from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.vlm_judge import VlmAxisScore, VlmVerdict


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeJudge:
    """Returns a verdict whose stars encode the photo's index.

    That is the whole trick: if verdict N lands on row N for every N, the
    concurrent bookkeeping is right.  Any cross-wiring shows up as a
    mismatch rather than as a plausible-looking number.
    """

    def __init__(self, model_name="minimax:minimax-m3", *, delay=None,
                 fail=(), error_all=False, record_rows=None):
        self.model_name = model_name
        self.delay = delay
        self.fail = set(fail)
        self.error_all = error_all
        self.calls: list[Path] = []
        self.rows_seen: list[dict] = [] if record_rows is None else record_rows
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = threading.Lock()

    def score(self, image_path, scene="", style_section="", row=None):
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            self.calls.append(Path(image_path))
            if row is not None:
                self.rows_seen.append(row)
        try:
            if self.delay is not None:
                time.sleep(self.delay(Path(image_path).stem))
            idx = int(Path(image_path).stem.split("_")[-1])
            if Path(image_path).name in self.fail:
                raise RuntimeError("worker exploded")
            v = VlmVerdict(
                filename=Path(image_path).name,
                axes={a.name: VlmAxisScore(stars=None) for a in RUBRIC_AXES},
                model_name=self.model_name,
            )
            if self.error_all:
                v.error = "APIStatusError: 401 invalid key"
                return v
            # Encode the index in every axis so a mix-up cannot hide.
            for a in RUBRIC_AXES:
                v.axes[a.name] = VlmAxisScore(stars=float(idx % 5 + 1))
            v.overall_label = f"row{idx}"
            v.overall_rationale = f"verdict for {idx}"
            v.elapsed_s = 0.01
            return v
        finally:
            with self._lock:
                self._in_flight -= 1


class LocalJudge(FakeJudge):
    """A backend that predates the `row` kwarg (e.g. the MLX one)."""

    def __init__(self, **kw):
        super().__init__(model_name="mlx-community/Qwen3-VL-4B", **kw)

    def score(self, image_path, scene="", style_section=""):   # no `row`
        return super().score(image_path, scene=scene,
                             style_section=style_section)


def make_df(n=12, cull_every=None):
    rows = []
    for i in range(n):
        rows.append({
            "path": f"/nowhere/img_{i}.jpg",
            "filename": f"img_{i}.jpg",
            "scene": "portrait",
            "decision": ("cull" if cull_every and i % cull_every == 0
                         else "keep"),
            "laplacian_subject": 100.0 + i,
            "highlight_clip_pct": 0.5,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Worker count
# ---------------------------------------------------------------------------

def test_local_backend_stays_serial():
    """Threads against a saturated GPU make it slower, not faster."""
    assert _vlm_workers(LocalJudge()) == 1


def test_cloud_backends_run_concurrently():
    for name in ("minimax:minimax-m3", "deepseek:deepseek-vl",
                 "openai:gpt-4o-mini", "custom:whatever"):
        assert _vlm_workers(FakeJudge(name)) > 1, name


def test_worker_count_is_overridable(monkeypatch):
    monkeypatch.setenv("PIXCULL_VLM_WORKERS", "3")
    assert _vlm_workers(LocalJudge()) == 3


def test_garbage_override_falls_back(monkeypatch):
    monkeypatch.setenv("PIXCULL_VLM_WORKERS", "lots")
    assert _vlm_workers(FakeJudge()) == 8


def test_zero_or_negative_override_is_clamped(monkeypatch):
    """max_workers=0 raises inside ThreadPoolExecutor."""
    monkeypatch.setenv("PIXCULL_VLM_WORKERS", "0")
    assert _vlm_workers(FakeJudge()) >= 1
    monkeypatch.setenv("PIXCULL_VLM_WORKERS", "-4")
    assert _vlm_workers(FakeJudge()) >= 1


# ---------------------------------------------------------------------------
# The bookkeeping — the part concurrency actually endangers
# ---------------------------------------------------------------------------

def test_every_verdict_lands_on_its_own_row(tmp_path):
    df = make_df(12)
    run_vlm_stage(df, FakeJudge(), tmp_path)
    for i in range(12):
        assert df.at[i, "vlm_overall_label"] == f"row{i}", (
            f"row {i} got {df.at[i, 'vlm_overall_label']!r} — verdicts are "
            f"cross-wired under concurrency")
        assert df.at[i, "vlm_technical_stars"] == float(i % 5 + 1)


def test_out_of_order_completion_still_maps_correctly(tmp_path):
    """The failure mode this test exists for.

    Workers finish in whatever order the network returns them.  Reversing
    the completion order relative to submission is the cheapest way to
    provoke an index/enumeration mix-up, and it is exactly what a slow
    first photo produces in the field.
    """
    rng = random.Random(7)
    df = make_df(10)
    judge = FakeJudge(delay=lambda stem: rng.uniform(0.0, 0.05))
    run_vlm_stage(df, judge, tmp_path)
    assert judge.max_in_flight > 1, "did not actually run concurrently"
    for i in range(10):
        assert df.at[i, "vlm_overall_label"] == f"row{i}"


def test_culled_rows_are_skipped_and_left_untouched(tmp_path):
    df = make_df(12, cull_every=3)
    judge = FakeJudge()
    run_vlm_stage(df, judge, tmp_path)
    scored = {p.name for p in judge.calls}
    for i in range(12):
        if i % 3 == 0:
            assert f"img_{i}.jpg" not in scored
            assert pd.isna(df.at[i, "vlm_elapsed_s"])
        else:
            assert f"img_{i}.jpg" in scored
            assert df.at[i, "vlm_overall_label"] == f"row{i}"


def test_progress_is_monotonic_under_concurrency(tmp_path):
    """_set_run's lock protects the dict, not the ordering of the tuple."""
    seen: list[int] = []
    lock = threading.Lock()

    def cb(done, total, msg):
        with lock:
            seen.append(done)

    df = make_df(10)
    rng = random.Random(3)
    run_vlm_stage(df, FakeJudge(delay=lambda s: rng.uniform(0, 0.03)),
                  tmp_path, progress_cb=cb)
    assert seen == sorted(seen), f"progress went backwards: {seen}"
    assert seen[-1] == 10


def test_verdicts_jsonl_has_one_line_per_scored_photo(tmp_path):
    df = make_df(9, cull_every=3)
    run_vlm_stage(df, FakeJudge(), tmp_path)
    lines = [json.loads(x) for x in
             (tmp_path / "vlm_verdicts.jsonl").read_text("utf-8").splitlines()
             if x.strip()]
    assert len(lines) == 6
    assert {x["filename"] for x in lines} == {
        f"img_{i}.jpg" for i in range(9) if i % 3}


def test_jsonl_is_not_interleaved_garbage(tmp_path):
    """Concurrent writers to one file handle would produce torn lines."""
    df = make_df(24)
    run_vlm_stage(df, FakeJudge(delay=lambda s: 0.001), tmp_path)
    for line in (tmp_path / "vlm_verdicts.jsonl").read_text("utf-8").splitlines():
        if line.strip():
            json.loads(line)     # raises if a write was torn


# ---------------------------------------------------------------------------
# Evidence plumbing
# ---------------------------------------------------------------------------

def test_local_measurements_are_handed_to_the_judge(tmp_path):
    df = make_df(4)
    judge = FakeJudge()
    run_vlm_stage(df, judge, tmp_path)
    assert len(judge.rows_seen) == 4
    assert all("laplacian_subject" in r for r in judge.rows_seen), (
        "the judge is not receiving the detector readings it is supposed "
        "to reason over — evidence fusion is silently off")


def test_backends_without_the_row_kwarg_still_work(tmp_path):
    """The MLX judge predates evidence fusion; it must not crash."""
    df = make_df(4)
    judge = LocalJudge()
    run_vlm_stage(df, judge, tmp_path)
    assert len(judge.calls) == 4
    assert df.at[2, "vlm_overall_label"] == "row2"


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

def test_one_exploding_worker_does_not_lose_the_others(tmp_path):
    df = make_df(8)
    run_vlm_stage(df, FakeJudge(fail={"img_3.jpg"}), tmp_path)
    assert pd.isna(df.at[3, "vlm_elapsed_s"])
    for i in (0, 1, 2, 4, 5, 6, 7):
        assert df.at[i, "vlm_overall_label"] == f"row{i}"


def test_a_total_wipeout_is_called_out_loudly(tmp_path, capsys):
    """3000 nulls must not read as 3000 quiet judgements.

    This is the exact failure that let a stale endpoint survive for
    months: every call errors, every column stays empty, and the run
    reports success.
    """
    df = make_df(5)
    run_vlm_stage(df, FakeJudge(error_all=True), tmp_path)
    out = capsys.readouterr().out
    assert "every call failed" in out
    assert "doctor" in out, "the message must name the fix"


def test_a_partial_failure_is_not_reported_as_a_wipeout(tmp_path, capsys):
    df = make_df(5)
    run_vlm_stage(df, FakeJudge(fail={"img_1.jpg"}), tmp_path)
    assert "every call failed" not in capsys.readouterr().out


def test_no_rows_to_score_is_not_a_wipeout(tmp_path, capsys):
    """An all-cull batch has zero calls; 0 == 0 must not trip the alarm."""
    df = make_df(6, cull_every=1)
    run_vlm_stage(df, FakeJudge(), tmp_path)
    assert "every call failed" not in capsys.readouterr().out
