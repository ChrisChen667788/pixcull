"""v2.72 — `--vlm-mode off` is a promise; test it like one.

The README offers photographers whose contracts forbid third-party cloud
processing a fully local path. Everything measured since v2.48 measured
the cloud path, and the offline one had no end-to-end gate at all.

It was broken. `_m3_advice_pass` gated on "is there an API key" and "is
there consent" — never on "did this run ask to stay local". A
photographer with a key configured in an earlier session, running
`--vlm-mode off`, had every keep/maybe frame uploaded to MiniMax.
Measured on a six-frame run: 6 of 6 uploaded, while the startup banner
that warns about uploads stayed silent, because THAT is tied to
vlm_mode. The user was told the opposite of what happened.

Two things are tested here and they are different promises:

* **Nothing leaves the machine.** Asserted by making the socket layer
  itself unusable, not by reading a flag. A flag says what the code
  intended; a raised connection says what it did.
* **The local stack still culls.** An offline path that is silent AND
  useless keeps the privacy promise by doing nothing. The floor comes
  from v2.68's cross-validated numbers on 494 blind frames, committed
  as an anonymous fixture — scores, flags, scene and verdict, no
  filenames and no images.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring.decision import decide

FIXTURE = Path(__file__).parent / "fixtures" / "blind_rule_stack.jsonl"


@pytest.fixture(scope="module")
def blind():
    rows = [json.loads(ln) for ln in
            FIXTURE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) > 400, f"fixture shrank to {len(rows)} rows"
    return rows


@pytest.fixture(scope="module")
def cfg():
    return PixCullConfig.load()


# ---------------------------------------------------------------------------
# Promise 1 — nothing leaves the machine
# ---------------------------------------------------------------------------

def test_the_advice_pass_asks_whether_this_run_may_use_the_cloud(monkeypatch):
    """It asked whether a key existed. That is not the same question."""
    from pixcull.report import serve_app

    serve_app.set_cloud_mode("off")
    assert serve_app.cloud_allowed() is False
    for mode in ("minimax", "MiniMax", "deepseek"):
        serve_app.set_cloud_mode(mode)
        assert serve_app.cloud_allowed() is True, mode
    for mode in ("off", "", "none", "local", None):
        serve_app.set_cloud_mode(mode)
        assert serve_app.cloud_allowed() is False, mode
    serve_app.set_cloud_mode("off")

    # And the gate is consulted BEFORE the key is, or a keyed machine
    # still decides the question.
    import inspect
    src = inspect.getsource(serve_app._m3_advice_pass)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert code.index("cloud_allowed()") < code.index("api_key_from_env"), (
        "the key is checked before the mode, so a machine with a key "
        "uploads regardless of what the run asked for")


def test_the_rule_stack_decides_without_a_network(monkeypatch, blind, cfg):
    """Asserted against the socket layer, not against a flag.

    A flag records what the code meant to do. A raised connection records
    what it did.
    """
    def _forbidden(*_a, **_k):
        raise AssertionError(
            "the offline path opened a socket — this is the promise the "
            "README makes to photographers under NDA")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    seen = set()
    for r in blind[:200]:
        d, _ = decide(r["score_final"], list(r["flags"]), cfg, "standard",
                      scene=r["scene"] or None, vlm_authority="off")
        seen.add(d.value)
    assert seen, "no decisions were produced at all"


# ---------------------------------------------------------------------------
# Promise 2 — the local stack still does the job
# ---------------------------------------------------------------------------

def _outcomes(rows, cfg):
    destroyed = found = 0.0
    dist = {"keep": 0, "maybe": 0, "cull": 0}
    for r in rows:
        d, _ = decide(r["score_final"], list(r["flags"]), cfg, "standard",
                      scene=r["scene"] or None, vlm_authority="off")
        dist[d.value] = dist.get(d.value, 0) + 1
        if d.value != "cull":
            continue
        if r["truth"] == "keep":
            destroyed += r["weight"]
        elif r["truth"] == "cull":
            found += r["weight"]
    return destroyed, found, dist


def test_the_offline_path_does_not_destroy_the_shoot(blind, cfg):
    """v2.68's floor, pinned.

    Before that version the rule stack destroyed 274 weighted keepers on
    these frames. A regression that quietly re-arms `flag ⇒ cull` would
    look like nothing from outside; it would look like this number.
    """
    destroyed, _found, _dist = _outcomes(blind, cfg)
    assert destroyed <= 8, (
        f"the offline path destroys {destroyed:.0f} weighted keepers; "
        f"v2.68 brought this from 274 to 4 and 8 is the ceiling that "
        f"change bought")


def test_the_offline_path_still_culls_something(blind, cfg):
    """Silent and useless keeps the privacy promise by doing nothing.

    `flags_policy: ignore` scored well on macro-F1 for exactly this
    reason — it culled 1 frame in 494 and found none of the 43 real
    culls — and v2.68 refused it by name.
    """
    _destroyed, found, dist = _outcomes(blind, cfg)
    assert found >= 3, (
        f"the offline path finds {found:.0f} weighted culls — an offline "
        f"mode that culls nothing is not a privacy feature, it is an "
        f"off switch")
    assert dist["maybe"] > 0, (
        "no frame is sent for a second look, so the flags are doing "
        "nothing at all")


def test_the_fixture_carries_no_identifying_information():
    """It is derived from a real photographer's shoot. What it may
    contain is numbers, flag names, scene names and a verdict."""
    allowed = {"score_final", "flags", "scene", "truth", "weight"}
    for ln in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        extra = set(row) - allowed
        assert not extra, f"fixture carries {extra}"
        assert isinstance(row["scene"], str) and "/" not in row["scene"]
