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
    # v2.50 added a cloud-upload consent gate in front of every request.
    # It has its own suite (tests/test_cloud_consent.py, including the
    # structural check that it cannot be bypassed); these tests are about
    # the transport, so they opt out rather than each grant consent into
    # a fixture home.
    kw.setdefault("require_consent", False)
    return m3.MiniMaxM3Judge(FAKE_KEY, **kw)


# ---------------------------------------------------------------------------
# 1. The constants that were stale
# ---------------------------------------------------------------------------

def test_endpoint_and_model_are_the_m3_ones():
    """These were wrong for months and failed silently. Pin them.

    v2.52.2 made the host regional, so BASE_URL is now the DEFAULT region
    rather than the only one — see the region tests at the bottom. What
    stays pinned is the model string and the exclusion of the retired
    pre-M3 host.
    """
    assert m3.BASE_URL in m3.REGIONS.values()
    assert m3.MODEL == "minimax-m3"
    assert "minimax.chat" not in " ".join(m3.REGIONS.values()), (
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
    v = m3.MiniMaxM3Judge(FAKE_KEY, enforce_budget=True,
                          require_consent=False).score(photo)
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


# ---------------------------------------------------------------------------
# 12. Regions — v2.52.2
# ---------------------------------------------------------------------------
#
# MiniMax runs two independent regions with separate accounts. A China key
# gets `401 invalid api key (2049)` from the international host, which
# reads as "your key is wrong" and sends you off to reissue a key that was
# fine all along. I hardcoded the international host from the English docs
# while this repo's own brand scripts had been calling the China one for
# months; the evidence was in the tree and I did not look.

def test_both_regions_are_known():
    assert set(m3.REGIONS) == {"cn", "global"}
    assert m3.REGIONS["cn"] == "https://api.minimaxi.com/v1"
    assert m3.REGIONS["global"] == "https://api.minimax.io/v1"


def test_the_default_region_matches_this_project_s_users(monkeypatch):
    monkeypatch.setattr(m3, "load_capabilities", lambda: {})
    monkeypatch.delenv("MINIMAX_REGION", raising=False)
    assert m3.resolve_base_url() == m3.REGIONS["cn"]


def test_a_successful_probe_pins_the_endpoint(monkeypatch):
    monkeypatch.setattr(m3, "load_capabilities",
                        lambda: {"text": "ok",
                                 "base_url": m3.REGIONS["global"]})
    assert m3.resolve_base_url() == m3.REGIONS["global"]


def test_a_FAILED_probe_does_not_pin_the_endpoint(monkeypatch):
    """The bug in my first version of this.

    It trusted any recorded base_url. So a doctor run that got 401 from
    the wrong region pinned the judge to that wrong region permanently —
    the probe's entire job is to find the endpoint that works, and
    remembering one that did not is worse than remembering nothing.
    """
    monkeypatch.setattr(m3, "load_capabilities",
                        lambda: {"text": "APIStatusError: 401 invalid api key",
                                 "base_url": m3.REGIONS["global"]})
    monkeypatch.delenv("MINIMAX_REGION", raising=False)
    assert m3.resolve_base_url() == m3.REGIONS["cn"]


def test_env_can_override_before_anything_is_probed(monkeypatch):
    monkeypatch.setattr(m3, "load_capabilities", lambda: {})
    monkeypatch.setenv("MINIMAX_REGION", "global")
    assert m3.resolve_base_url() == m3.REGIONS["global"]
    monkeypatch.setenv("MINIMAX_REGION", "nonsense")
    assert m3.resolve_base_url() == m3.REGIONS["cn"]


def test_the_doctor_sweeps_regions_rather_than_asking():
    """"Which MiniMax region is your account in?" asks the owner to know
    something their console never told them, and the wrong answer looks
    identical to a bad key."""
    import inspect
    src = inspect.getsource(m3.probe_capabilities)
    assert "probe_key(" in src, (
        "the doctor no longer sweeps regions — it would be asking the "
        "owner which region their account is in")


def test_a_billing_failure_is_reported_over_an_auth_failure():
    """402 and 401 need completely different fixes.

    402 means the key is GOOD and the account is empty — top it up. 401
    means the key does not belong here. Reporting whichever region was
    tried last would send the owner to reissue a working key.
    """
    # v2.52.4 — the ordering now lives in probe_key, which has its own
    # tests below. What this asserts is that probe_capabilities defers to
    # it rather than re-deciding.
    import inspect
    assert "probe_key(" in inspect.getsource(m3.probe_capabilities)
    src = inspect.getsource(m3.probe_key)
    # The final decision block: billing is checked before falling through
    # to badkey. (An earlier "badkey" return exists for a missing SDK, so
    # a plain index() comparison would compare against the wrong one.)
    tail = src[src.index("joined = "):]
    assert tail.index("1008") < tail.index('return "badkey"')


# ---------------------------------------------------------------------------
# 13. Telling the two failures apart — v2.52.3
# ---------------------------------------------------------------------------

def test_a_402_says_the_key_is_fine():
    """402 and 401 need opposite fixes and look alike in a traceback.

    402 = the key authenticated and the account is empty → top up.
    401 = the key does not belong to this region → the doctor's sweep.
    Reporting them interchangeably sent a real debugging session hunting
    for a bad key that was fine all along.
    """
    hint = m3.explain_api_error(Exception(
        "Error code: 402 - {'error': {'type': 'insufficient_balance_error', "
        "'message': 'insufficient balance (1008)'}}"))
    assert "GOOD" in hint and "Top up" in hint
    assert "invalid" not in hint.lower()


def test_a_401_points_at_the_region_not_the_key():
    hint = m3.explain_api_error(Exception(
        "Error code: 401 - {'error': {'message': 'invalid api key (2049)'}}"))
    assert "REGION" in hint
    assert "doctor" in hint


def test_an_unrelated_error_gets_no_invented_advice():
    assert m3.explain_api_error(Exception("ConnectionResetError")) == ""


def test_the_legacy_route_trap_is_written_down():
    """`/v1/text/chatcompletion_v2` answers HTTP 200 with the real failure
    in base_resp.status_code. We do not use it, so this records the hazard
    for whoever adds the next route rather than guarding a live path."""
    assert 1008 in m3.MINIMAX_STATUS
    src = Path(m3.__file__).read_text("utf-8")
    assert "base_resp" in src


# ---------------------------------------------------------------------------
# 14. One region sweep — v2.52.4
# ---------------------------------------------------------------------------
#
# I wrote this loop by hand FOUR times in one session and got it wrong the
# same way in three of them: deciding from the LAST region's error. CN
# answers 402 (key good, out of credit); global answers 401 (wrong
# region). Whichever is tried last wins, so a working key gets reported as
# invalid and the owner is sent to reissue it. That happened twice.
#
# The property being lost — the billing signal must win no matter which
# region produced it — belongs to the whole sweep, not to one iteration.
# Duplicating the loop duplicates the chance to lose it, so these tests
# pin the behaviour AND the fact that there is only one implementation.

class _FakeCompletions:
    def __init__(self, by_url, url):
        self.by_url, self.url = by_url, url

    def create(self, **kw):
        outcome = self.by_url.get(self.url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _region_stub(monkeypatch, by_url):
    def _OpenAI(*, api_key=None, base_url=None, **kw):
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=_FakeCompletions(by_url, base_url)))
    mod = types.ModuleType("openai")
    mod.OpenAI = _OpenAI
    monkeypatch.setitem(sys.modules, "openai", mod)


def test_the_billing_signal_wins_from_either_region(monkeypatch):
    """The exact bug, in the exact order that produced it."""
    _region_stub(monkeypatch, {
        m3.REGIONS["cn"]: Exception("Error code: 402 insufficient balance (1008)"),
        m3.REGIONS["global"]: Exception("Error code: 401 invalid api key (2049)"),
    })
    state, detail = m3.probe_key(FAKE_KEY)
    assert state == "nobalance", (
        f"a key that is merely out of credit was reported as {state!r} — "
        f"this sends the owner to reissue a key that works")
    assert "GOOD" in detail


def test_order_does_not_change_the_diagnosis(monkeypatch):
    """Same two answers, regions swapped. Must land on the same verdict."""
    _region_stub(monkeypatch, {
        m3.REGIONS["cn"]: Exception("Error code: 401 invalid api key (2049)"),
        m3.REGIONS["global"]: Exception("Error code: 402 insufficient balance (1008)"),
    })
    assert m3.probe_key(FAKE_KEY)[0] == "nobalance"


def test_a_genuinely_bad_key_is_still_called_bad(monkeypatch):
    _region_stub(monkeypatch, {
        m3.REGIONS["cn"]: Exception("401 invalid api key (2049)"),
        m3.REGIONS["global"]: Exception("401 invalid api key (2049)"),
    })
    state, detail = m3.probe_key(FAKE_KEY)
    assert state == "badkey"
    assert "REGION" in detail


def test_a_working_region_is_returned(monkeypatch):
    _region_stub(monkeypatch, {
        m3.REGIONS["cn"]: Exception("401 invalid api key (2049)"),
        m3.REGIONS["global"]: _Resp("pong"),
    })
    state, detail = m3.probe_key(FAKE_KEY)
    assert state == "ok" and detail == m3.REGIONS["global"]


def test_no_key_is_not_a_bad_key():
    assert m3.probe_key("")[0] == "missing"


def test_there_is_exactly_one_region_sweep_in_the_codebase():
    """The structural guard. Four copies is how three of them went wrong."""
    import ast
    import re
    root = Path(__file__).resolve().parent.parent
    sweeps = []

    def _iterates_regions(node) -> bool:
        it = getattr(node, "iter", None)
        return (isinstance(it, ast.Call)
                and isinstance(it.func, ast.Attribute)
                and it.func.attr in ("items", "values")
                and isinstance(it.func.value, ast.Name)
                and it.func.value.id == "REGIONS")

    for f in (root / "pixcull").rglob("*.py"):
        if any(seg in f.parts for seg in (".venv", "dist", "build")):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        # ast.For only — a dict/set comprehension over REGIONS is a lookup
        # table, not an auth sweep, and banning those would push the code
        # toward worse shapes for no safety.
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and _iterates_regions(node):
                sweeps.append(f"{f.relative_to(root)}:{node.lineno}")
    for f in (root / "scripts").rglob("*.sh"):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"REGIONS\.(?:items|values)\(\)", text):
            sweeps.append(f"{f.relative_to(root)}:{text[:m.start()].count(chr(10)) + 1}")
    assert len(sweeps) == 1, (
        f"the region sweep is duplicated across {len(sweeps)} places: "
        f"{sweeps}. Every copy is another chance to decide from the wrong "
        f"region's error — call probe_key() instead.")


def test_probe_capabilities_uses_the_shared_sweep():
    import inspect
    src = inspect.getsource(m3.probe_capabilities)
    assert "probe_key(" in src
