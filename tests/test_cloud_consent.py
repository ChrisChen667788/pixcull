"""v2.50 — nobody's photos get uploaded without them saying so.

v2.50 ships cloud judging ON. That is only defensible while the first
upload is a thing the photographer chose, and the constraint is real
rather than ceremonial: wedding and commercial contracts routinely forbid
third-party cloud processing of client images, and the person who signed
one cannot find out after the fact.

The design decision under test is *where* the gate lives. Checking it in
the CLI would leave the library, the web app, the launcher and every
future call site each responsible for remembering — which is how
"advertised but unreachable" happens in reverse. It lives in
``_complete()``, the single funnel every upload passes through, so a new
call site cannot forget it.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from pixcull.scoring import m3

FAKE_KEY = "sk-" + "0" * 32


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real ~/.pixcull/cloud_consent.json."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    yield tmp_path


@pytest.fixture
def fake_openai(monkeypatch):
    calls: list[dict] = []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            raise AssertionError("a request was actually sent")

    class _Client:
        def __init__(self, **kw):
            self.chat = types.SimpleNamespace(completions=_Completions())

    mod = types.ModuleType("openai")
    mod.OpenAI = _Client
    for name in ("RateLimitError", "APITimeoutError", "APIConnectionError",
                 "APIStatusError"):
        setattr(mod, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "openai", mod)
    return calls


@pytest.fixture
def photo(tmp_path):
    from PIL import Image
    p = tmp_path / "shot.jpg"
    Image.new("RGB", (64, 48), (10, 20, 30)).save(p, "JPEG")
    return p


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def test_absent_by_default():
    assert not m3.has_consent()


def test_grant_then_revoke_round_trips():
    m3.grant_consent()
    assert m3.has_consent()
    assert m3.revoke_consent()
    assert not m3.has_consent()


def test_revoking_nothing_is_not_an_error():
    assert m3.revoke_consent() is False


def test_the_grant_records_what_was_agreed_to():
    p = m3.grant_consent()
    d = json.loads(p.read_text("utf-8"))
    assert d["granted"] is True
    assert d["endpoint"] == m3.BASE_URL
    assert d["granted_at"].endswith("Z")


def test_an_old_grant_does_not_cover_a_new_kind_of_upload(isolated_home):
    """Versioned on purpose.

    If what we upload ever materially changes — whole video clips as well
    as stills — the old grant does not cover the new thing. Silently
    reusing it is precisely the trick this gate exists to prevent.
    """
    p = m3.consent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"granted": True, "version": 0}), "utf-8")
    assert not m3.has_consent()


def test_a_corrupt_file_denies_rather_than_permits():
    p = m3.consent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    assert not m3.has_consent()


# ---------------------------------------------------------------------------
# Enforcement — the part that must not be bypassable
# ---------------------------------------------------------------------------

def test_no_consent_means_no_bytes_leave(fake_openai, photo):
    judge = m3.MiniMaxM3Judge(FAKE_KEY, enforce_budget=False)
    verdict = judge.score(photo)
    assert verdict.error and "consent" in verdict.error.lower()
    assert not fake_openai, "a request was sent without consent"


def test_the_refusal_names_both_ways_out(fake_openai, photo):
    judge = m3.MiniMaxM3Judge(FAKE_KEY, enforce_budget=False)
    err = judge.score(photo).error or ""
    assert "consent --grant" in err
    assert "--vlm-mode off" in err, (
        "a user who cannot upload must be told the local path exists")


def test_video_is_gated_too(fake_openai, tmp_path, monkeypatch):
    """Every upload path, not just the photo one."""
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\0" * 256)
    monkeypatch.setattr(m3, "load_capabilities",
                        lambda: {"video_part_shape": "video_url_object"})
    judge = m3.MiniMaxM3Judge(FAKE_KEY, enforce_budget=False)
    v = judge.score_video(clip, "describe")
    assert v.error and "consent" in v.error.lower()
    assert not fake_openai


def test_the_gate_sits_in_the_single_transport_funnel():
    """Structural, not behavioural — this is what makes it unforgettable.

    If the check ever moves out to the callers, a call site added later
    can omit it and nothing else here would notice.
    """
    import inspect
    assert "has_consent()" in inspect.getsource(m3.MiniMaxM3Judge._complete)
    for name in ("score", "score_video"):
        src = inspect.getsource(getattr(m3.MiniMaxM3Judge, name))
        assert "self._complete(" in src, (
            f"{name} no longer goes through _complete — it can now upload "
            f"without passing the consent gate")


def test_granted_consent_lets_the_call_through(fake_openai, photo):
    m3.grant_consent()
    judge = m3.MiniMaxM3Judge(FAKE_KEY, enforce_budget=False)
    verdict = judge.score(photo)
    # The fake raises on send; reaching it is the proof.
    assert verdict.error and "consent" not in verdict.error.lower()


def test_the_gate_is_only_disablable_in_process(fake_openai, photo):
    """Tests and the doctor need to bypass it; users must not.

    There is deliberately no env var and no config key — a flag that can
    be set from outside the process is a flag an installer script can set
    on a photographer's behalf.
    """
    judge = m3.MiniMaxM3Judge(FAKE_KEY, enforce_budget=False,
                              require_consent=False)
    judge.score(photo)
    src = Path(m3.__file__).read_text("utf-8")
    gate = src[src.index("def _complete"):src.index("def _charge")]
    assert "environ" not in gate, (
        "the consent gate reads the environment — that is settable by "
        "anything that can write a shell profile")


# ---------------------------------------------------------------------------
# The notice itself
# ---------------------------------------------------------------------------

def test_the_notice_says_the_uncomfortable_parts():
    n = m3.CONSENT_NOTICE
    assert "api.minimax.io" in n
    assert "NOT stripped" in n, "must state that faces and GPS are not removed"
    assert "contract" in n.lower(), (
        "must name the actual reason a professional would decline")
    assert "--vlm-mode off" in n


def test_cli_exposes_consent():
    from typer.testing import CliRunner

    from pixcull.cli import app
    assert "consent" in CliRunner().invoke(app, ["m3", "--help"]).output


def test_run_declines_gracefully_when_it_cannot_ask(monkeypatch, tmp_path):
    """Non-interactive (CI, cron, a script): default to NOT uploading."""
    seen = {}
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env",
                        lambda: FAKE_KEY)
    monkeypatch.setattr("pixcull.pipeline.orchestrator.run_pipeline",
                        lambda *a, **kw: seen.update(kw) or tmp_path)
    from typer.testing import CliRunner

    from pixcull.cli import app
    (tmp_path / "in").mkdir()
    CliRunner().invoke(app, ["run", str(tmp_path / "in")])
    assert seen.get("vlm_mode") == "off", (
        "a headless run must not upload on the strength of a key alone")
