"""v2.48 — MiniMax M3 adapter.

**Not one test here may touch the network.**  CI has no MiniMax key and
``conftest.py`` has no global network block, so every test stubs
``openai.OpenAI`` before a judge is constructed.  ``test_no_live_client``
at the bottom is the guard that this discipline held.

The bugs these tests exist to catch, in order of how expensive they were
to reason about:

1. **Stale constants.**  The endpoint and model were wrong for months and
   nobody noticed, because ``score()`` turns every failure into
   ``verdict.error`` — a run of 3000 nulls reads as a successful run.
   They must also be wrong *together*: the M3 endpoint rejects the old
   model name and vice versa.
2. **Refusing to guess.**  ``score_video`` must raise when the wire shape
   has never been probed, rather than sending a guess whose 4xx becomes
   one more null verdict.
3. **Retrying what cannot recover.**  A 401 retried five times with
   exponential backoff wastes ~30 s per photo and still fails.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from pixcull.scoring import m3


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

# A syntactically plausible key built at runtime, never a literal —
# secret scanners (and tests/test_repo_hygiene.py) must have nothing to
# match on.
FAKE_KEY = "sk-" + "0" * 32


class _Usage:
    prompt_tokens = 1500
    completion_tokens = 120


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = _Usage()


GOOD_JSON = json.dumps({
    "axes": {
        "technical":   {"stars": 4, "rationale": "对焦准"},
        "subject":     {"stars": 5, "rationale": "主体明确"},
        "composition": {"stars": 3, "rationale": "构图偏中"},
        "light":       {"stars": 4, "rationale": "侧光"},
        "moment":      {"stars": 5, "rationale": "抓到了"},
        "aesthetic":   {"stars": 4, "rationale": "耐看"},
    },
    "overall_label": "keep",
    "overall_rationale": "值得留",
}, ensure_ascii=False)


class FakeCompletions:
    """Records every call; replays a scripted sequence of results."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0) if self.script else _Resp(GOOD_JSON)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script=(), **kw):
        self.init_kwargs = kw
        self.chat = types.SimpleNamespace(completions=FakeCompletions(script))


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a fake ``openai`` module and hand back a factory.

    Patching the module rather than the judge means the test also covers
    the lazy ``from openai import OpenAI`` inside ``__init__`` — the real
    injection point.
    """
    created: list[FakeClient] = []
    script: list = []

    def _OpenAI(**kw):
        c = FakeClient(script, **kw)
        created.append(c)
        return c

    class _Err(Exception):
        pass

    class APIStatusError(_Err):
        def __init__(self, status_code=400, message="boom"):
            super().__init__(message)
            self.status_code = status_code

    mod = types.ModuleType("openai")
    mod.OpenAI = _OpenAI
    mod.RateLimitError = type("RateLimitError", (_Err,), {})
    mod.APITimeoutError = type("APITimeoutError", (_Err,), {})
    mod.APIConnectionError = type("APIConnectionError", (_Err,), {})
    mod.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "openai", mod)
    # No real sleeping in retry tests.
    monkeypatch.setattr(m3.MiniMaxM3Judge, "_sleep_for_retry",
                        lambda self, attempt: 0.0)
    return types.SimpleNamespace(created=created, script=script, mod=mod)


@pytest.fixture
def photo(tmp_path):
    from PIL import Image
    p = tmp_path / "shot.jpg"
    Image.new("RGB", (640, 480), (120, 90, 70)).save(p, "JPEG")
    return p


def _judge(**kw):
    kw.setdefault("enforce_budget", False)
    return m3.MiniMaxM3Judge(FAKE_KEY, **kw)


# ---------------------------------------------------------------------------
# 1. The constants that were stale
# ---------------------------------------------------------------------------

def test_endpoint_and_model_are_the_m3_ones():
    """These were wrong for months and failed silently. Pin them."""
    assert m3.BASE_URL == "https://api.minimax.io/v1"
    assert m3.MODEL == "minimax-m3"
    assert "minimax.chat" not in m3.BASE_URL, (
        "api.minimax.chat is the pre-M3 endpoint; it rejects minimax-m3")


def test_no_stale_minimax_constants_left_in_the_tree():
    """The endpoint and model must change *together*.

    A half-applied fix is worse than none: the new endpoint rejects the
    old model and the old endpoint rejects the new one, and either way
    score() reports it as verdict.error on every row.

    Scoped to real string *constants* via AST rather than a text grep.
    A grep flags the docstrings that explain what the old values were and
    why they had to move — prose that is the opposite of the defect, and
    that a naive lint would pressure a future reader into deleting.
    """
    import ast

    stale = ("api.minimax.chat", "MiniMax-VL-01", "abab6.5-vision")
    root = Path(__file__).resolve().parent.parent

    def _docstring_nodes(tree):
        """Every string node that is a docstring, by identity."""
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    out.add(id(body[0].value))
        return out

    offenders = []
    for py in sorted(root.rglob("*.py")):
        if any(seg in py.parts for seg in (".venv", "dist", "build", ".git")):
            continue
        if py.name == Path(__file__).name:
            continue        # this file names them on purpose
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docs):
                for token in stale:
                    if token in node.value:
                        offenders.append(
                            f"{py.relative_to(root)}:{node.lineno}: {token}")
    assert not offenders, (
        "stale MiniMax constants are still live code: " + ", ".join(offenders))


def test_make_minimax_judge_returns_the_m3_judge(fake_openai):
    from pixcull.scoring.vlm_judge import make_minimax_judge
    j = make_minimax_judge(FAKE_KEY)
    assert isinstance(j, m3.MiniMaxM3Judge)
    assert j.model_name == "minimax:minimax-m3"
    assert fake_openai.created[-1].init_kwargs["base_url"] == m3.BASE_URL


def test_pricing_table_knows_m3():
    """Without this entry M3 billed at DeepSeek-Pro's rate — the cap
    arithmetic was meaningless for the model that makes the most calls."""
    from pixcull.llm_budget import _MODEL_PRICING, _UNKNOWN_MODEL_PRICE, estimate_cost
    assert "minimax-m3" in _MODEL_PRICING
    assert _MODEL_PRICING["minimax-m3"] != _UNKNOWN_MODEL_PRICE
    # A 3000-photo wedding: ~1.5k in + 150 out per photo.
    cost = estimate_cost("minimax-m3", 1500 * 3000, 150 * 3000)
    assert 5.0 < cost < 25.0, f"per-wedding estimate looks wrong: ¥{cost:.2f}"


# ---------------------------------------------------------------------------
# 2. Evidence fusion — the load-bearing idea
# ---------------------------------------------------------------------------

def test_evidence_block_carries_measurements():
    block = m3.build_evidence_block({
        "laplacian_subject": 412.7,
        "highlight_clip_pct": 2.31,
        "face_count": 3,
        "eyes_closed_count": 1,
    })
    assert "413" in block or "412" in block
    assert "2.31%" in block
    assert "闭眼" in block


def test_evidence_block_is_empty_without_measurements():
    """An empty heading would cost tokens on every photo and say nothing."""
    assert m3.build_evidence_block(None) == ""
    assert m3.build_evidence_block({}) == ""
    assert m3.build_evidence_block({"laplacian_subject": None}) == ""


def test_evidence_block_survives_junk_values():
    """DataFrame round-trips turn None into NaN and ints into strings."""
    block = m3.build_evidence_block({
        "laplacian_subject": "not-a-number",
        "face_count": float("nan"),
        "highlight_clip_pct": 1.0,
    })
    assert "1.00%" in block


def test_evidence_reaches_the_prompt(fake_openai, photo):
    j = _judge()
    j.score(photo, row={"laplacian_subject": 999.0})
    sent = fake_openai.created[-1].chat.completions.calls[-1]
    text = sent["messages"][0]["content"][0]["text"]
    assert "999" in text and "客观测量" in text


# ---------------------------------------------------------------------------
# 3. Scoring
# ---------------------------------------------------------------------------

def test_score_parses_axes(fake_openai, photo):
    v = _judge().score(photo)
    assert v.error is None
    assert v.overall_label == "keep"
    assert v.axes["moment"].stars == 5.0
    assert v.axes["composition"].rationale == "构图偏中"


def test_score_sends_an_image_data_uri(fake_openai, photo):
    _judge().score(photo)
    parts = fake_openai.created[-1].chat.completions.calls[-1]["messages"][0]["content"]
    img = [p for p in parts if p["type"] == "image_url"]
    assert len(img) == 1
    assert img[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_score_reports_errors_rather_than_raising(fake_openai, photo):
    fake_openai.script.append(RuntimeError("network went away"))
    v = _judge().score(photo)
    assert v.error and "network went away" in v.error
    assert all(a.stars is None for a in v.axes.values())


def test_malformed_json_is_flagged(fake_openai, photo):
    fake_openai.script.append(_Resp("I think it's a nice photo, honestly."))
    v = _judge().score(photo)
    assert v.error == "JSON parse failed"


# ---------------------------------------------------------------------------
# 4. Retry policy
# ---------------------------------------------------------------------------

def test_rate_limit_is_retried(fake_openai, photo):
    err = fake_openai.mod.RateLimitError("429")
    fake_openai.script.extend([err, err, _Resp(GOOD_JSON)])
    v = _judge().score(photo)
    assert v.error is None
    assert len(fake_openai.created[-1].chat.completions.calls) == 3


def test_client_errors_are_not_retried(fake_openai, photo):
    """A 401 retried 5x costs ~30 s of backoff and still fails."""
    fake_openai.script.extend(
        [fake_openai.mod.APIStatusError(401, "bad key")] * 5)
    v = _judge().score(photo)
    assert v.error is not None and "bad key" in v.error, (
        f"the auth failure must reach the caller intact, got {v.error!r}")
    assert len(fake_openai.created[-1].chat.completions.calls) == 1, (
        "a 4xx must not be retried — it will never succeed")


def test_server_errors_are_retried(fake_openai, photo):
    fake_openai.script.extend([
        fake_openai.mod.APIStatusError(503, "unavailable"),
        _Resp(GOOD_JSON),
    ])
    v = _judge().score(photo)
    assert v.error is None
    assert len(fake_openai.created[-1].chat.completions.calls) == 2


def test_retry_gives_up_and_reports(fake_openai, photo):
    err = fake_openai.mod.APITimeoutError("slow")
    fake_openai.script.extend([err] * 9)
    v = _judge(max_retries=3).score(photo)
    assert v.error is not None
    assert len(fake_openai.created[-1].chat.completions.calls) == 3


# ---------------------------------------------------------------------------
# 5. Cache — resumability
# ---------------------------------------------------------------------------

def test_cache_hit_makes_no_second_call(fake_openai, photo, tmp_path):
    cache = m3.VerdictCache(tmp_path / "c.jsonl")
    j = _judge(cache=cache)
    v1 = j.score(photo)
    n_after_first = len(fake_openai.created[-1].chat.completions.calls)
    v2 = j.score(photo)
    assert v2.error is None
    assert v2.axes["moment"].stars == v1.axes["moment"].stars
    assert len(fake_openai.created[-1].chat.completions.calls) == n_after_first, (
        "a cached photo must not be re-billed")


def test_cache_persists_across_instances(fake_openai, photo, tmp_path):
    p = tmp_path / "c.jsonl"
    _judge(cache=m3.VerdictCache(p)).score(photo)
    assert len(m3.VerdictCache(p)) == 1


def test_cache_survives_a_torn_final_line(tmp_path):
    """A run killed mid-write must not poison every later run."""
    p = tmp_path / "c.jsonl"
    p.write_text(
        json.dumps({"key": "a", "verdict": {"overall_label": "keep"}}) + "\n"
        + '{"key": "b", "verdict": {"over',            # killed here
        encoding="utf-8")
    c = m3.VerdictCache(p)
    assert len(c) == 1 and c.get("a") is not None


def test_prompt_version_invalidates_the_cache(fake_openai, photo, tmp_path,
                                              monkeypatch):
    cache = m3.VerdictCache(tmp_path / "c.jsonl")
    _judge(cache=cache).score(photo)
    monkeypatch.setattr(m3, "PROMPT_VERSION", "v9.9.9-changed")
    _judge(cache=cache).score(photo)
    assert len(cache) == 2, (
        "a prompt change must not silently serve verdicts written under "
        "the old prompt")


def test_cache_key_is_content_not_filename(photo, tmp_path):
    """Photographers rename and re-export constantly."""
    import shutil
    other = tmp_path / "renamed.jpg"
    shutil.copy(photo, other)
    assert m3._content_hash(photo, "x") == m3._content_hash(other, "x")


# ---------------------------------------------------------------------------
# 6. Limits
# ---------------------------------------------------------------------------

def test_oversize_video_is_refused_with_a_useful_message(tmp_path):
    big = tmp_path / "clip.mp4"
    big.write_bytes(b"\0" * (m3.MAX_VIDEO_BYTES + 1))
    with pytest.raises(ValueError) as ei:
        m3.MiniMaxM3Judge._video_data_uri(big)
    assert "transcode" in str(ei.value), (
        "the message must say what to DO — 4K ProRes always trips this")


def test_video_fps_is_clamped_to_the_vendor_range(fake_openai, tmp_path,
                                                  monkeypatch):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\0" * 1024)
    monkeypatch.setattr(m3, "load_capabilities",
                        lambda: {"video_part_shape": "video_url_object"})
    _judge().score_video(clip, "describe", fps=99.0)
    part = fake_openai.created[-1].chat.completions.calls[-1]["messages"][0]["content"][1]
    assert part["video_url"]["fps"] == m3.VIDEO_FPS_MAX


# ---------------------------------------------------------------------------
# 7. Refusing to guess
# ---------------------------------------------------------------------------

def test_score_video_refuses_when_the_shape_was_never_probed(
        fake_openai, tmp_path, monkeypatch):
    """The vendor docs do not publish the video content-part schema.

    Sending a guess is the worst option: a wrong shape returns a generic
    4xx that the caller stores as one more null verdict, which is exactly
    the failure mode this whole version exists to eliminate.
    """
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\0" * 512)
    monkeypatch.setattr(m3, "load_capabilities", lambda: {})
    with pytest.raises(RuntimeError) as ei:
        _judge().score_video(clip, "describe")
    assert "doctor" in str(ei.value), "the error must name the fix"


def test_probe_covers_every_declared_shape():
    """A shape added to the table but not probed would never be reachable."""
    import inspect
    src = inspect.getsource(m3.probe_capabilities)
    assert "VIDEO_PART_SHAPES.items()" in src
    assert len(m3.VIDEO_PART_SHAPES) >= 2
    for name, build in m3.VIDEO_PART_SHAPES.items():
        part = build("data:video/mp4;base64,AA==", 1.0)
        assert part["type"] == "video_url", name


# ---------------------------------------------------------------------------
# 8. Rate limiter
# ---------------------------------------------------------------------------

def test_rate_limiter_allows_a_burst_then_blocks(monkeypatch):
    """Pacing to the average would waste the budget after an idle phase —
    the pipeline alternates local-detector phases with API phases."""
    now = [1000.0]
    slept: list[float] = []
    monkeypatch.setattr(m3.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(m3.time, "sleep",
                        lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    lim = m3.RateLimiter(rpm=3)
    for _ in range(3):
        assert lim.acquire() == 0.0
    assert lim.acquire() > 0.0 and slept


def test_rate_limiter_window_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(m3.time, "monotonic", lambda: now[0])
    lim = m3.RateLimiter(rpm=2)
    lim.acquire()
    lim.acquire()
    now[0] += 61.0
    assert lim.acquire() == 0.0


def test_rpm_matches_the_published_limit():
    assert m3.RPM_LIMIT == 200


# ---------------------------------------------------------------------------
# 9. Budget
# ---------------------------------------------------------------------------

def test_budget_exhaustion_stops_the_call(fake_openai, photo, monkeypatch):
    monkeypatch.setattr("pixcull.llm_budget.check_budget", lambda est=0.0: False)
    v = m3.MiniMaxM3Judge(FAKE_KEY, enforce_budget=True).score(photo)
    assert v.error and "budget" in v.error.lower()
    assert not fake_openai.created[-1].chat.completions.calls, (
        "an over-budget photo must not be sent")


def test_usage_is_recorded(fake_openai, photo, monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr("pixcull.llm_budget.record_call",
                        lambda m, p, c: seen.append((m, p, c)) or {})
    _judge().score(photo)
    assert seen == [("minimax-m3", 1500, 120)]


# ---------------------------------------------------------------------------
# 10. Key handling
# ---------------------------------------------------------------------------

def test_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", FAKE_KEY)
    assert m3.api_key_from_env() == FAKE_KEY


def test_missing_key_is_a_clear_error(fake_openai):
    with pytest.raises(ValueError) as ei:
        m3.MiniMaxM3Judge("")
    assert "MINIMAX_API_KEY" in str(ei.value)


def test_no_key_material_anywhere_in_the_module():
    """The adapter must read keys, never carry one."""
    src = Path(m3.__file__).read_text(encoding="utf-8")
    for marker in ("sk-cp-", "eyJhbGciOi"):
        assert marker not in src


# ---------------------------------------------------------------------------
# 11. The guard on this whole file
# ---------------------------------------------------------------------------

def test_openai_is_imported_lazily_so_every_call_site_is_stubbable():
    """The property that makes the whole no-network discipline work.

    Every construction of an OpenAI client must resolve ``openai`` at
    call time, so ``monkeypatch.setitem(sys.modules, "openai", fake)``
    intercepts it.  A module-level ``from openai import OpenAI`` would
    bind the real symbol at import time — the fake fixture would appear
    to work while the code under test held the real class, and the first
    CI run without a key would fail as a confusing auth error minutes
    into the suite rather than here.
    """
    import ast

    tree = ast.parse(Path(m3.__file__).read_text(encoding="utf-8"))
    for node in tree.body:          # module scope only
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, "module", None) or ""
            names = [a.name for a in node.names]
            assert "openai" not in name and "openai" not in names, (
                "openai must not be imported at module scope — it would "
                "bind the real client before any fixture can stub it")


def test_importing_the_module_makes_no_client(monkeypatch):
    """Importing pixcull.scoring.m3 must not touch the network stack."""
    import importlib

    boom = types.ModuleType("openai")

    def _explode(**kw):
        raise AssertionError("import-time client construction")

    boom.OpenAI = _explode
    monkeypatch.setitem(sys.modules, "openai", boom)
    importlib.reload(m3)            # must not raise
    assert m3.MODEL == "minimax-m3"
