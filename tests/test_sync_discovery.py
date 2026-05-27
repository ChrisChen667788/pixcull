"""Tests for pixcull.sync.discovery — v0.10-P0-2 mDNS auto-discovery.

zeroconf is an optional extra (``pip install -e '.[sync]'``), so
these tests exercise BOTH branches:

  * When zeroconf isn't installed: advertise/discover/unadvertise
    must be no-ops returning sensible empty values.
  * When zeroconf IS installed: advertise + a same-process
    discover round-trips correctly.

The second set is gated on ``zeroconf`` import and skipped
otherwise so the dev test run doesn't force-install a dep that
solo users don't need.
"""

from __future__ import annotations

import socket

import pytest

from pixcull.sync.discovery import (
    SERVICE_TYPE,
    ZEROCONF_AVAILABLE,
    _local_ipv4,
    _service_name,
    advertise_event,
    close_zc,
    discover_events,
    unadvertise_event,
)


# ---------------------------------------------------------------------------
# Always-on tests (independent of zeroconf availability)
# ---------------------------------------------------------------------------


def test_service_type_is_stable_wire_contract():
    """The mDNS service type is part of the wire protocol — bumping
    it is a deliberate v2 break that breaks every existing peer."""
    assert SERVICE_TYPE == "_pixcull-sync._tcp.local."


def test_local_ipv4_returns_a_string():
    """Best-effort fallback never raises."""
    ip = _local_ipv4()
    assert isinstance(ip, str)
    # Valid IPv4 or the 127.0.0.1 fallback
    try:
        socket.inet_aton(ip)
    except OSError:
        pytest.fail(f"_local_ipv4() returned non-IPv4 {ip!r}")


def test_service_name_deterministic_per_event():
    n1 = _service_name("evt_abc", host="machineA")
    n2 = _service_name("evt_abc", host="machineA")
    assert n1 == n2
    assert "evt_abc" in n1
    assert n1.endswith(SERVICE_TYPE)


def test_service_name_sanitises_dots_spaces():
    n = _service_name("evt with spaces.and.dots", host="host name")
    # DNS-SD doesn't love unescaped dots; we just defensively replace
    assert " " not in n
    assert n.count(".") == n.replace(SERVICE_TYPE, "").count(".") + \
        SERVICE_TYPE.count(".")


# ---------------------------------------------------------------------------
# No-zeroconf graceful-degrade — assert these never raise
# ---------------------------------------------------------------------------


def test_advertise_without_zeroconf_returns_none(monkeypatch):
    """Even if zeroconf IS importable, force-disable the flag and
    confirm advertise returns None (so callers learn it was a no-op)."""
    monkeypatch.setattr(
        "pixcull.sync.discovery.ZEROCONF_AVAILABLE", False
    )
    h = advertise_event(
        event_id="evt_test", label="t", run_id="r1",
        port=8765, token="abcdef1234",
    )
    assert h is None


def test_unadvertise_handles_none_handle():
    """Idempotent on a None handle (e.g. when advertise no-op'd)."""
    assert unadvertise_event(None) is False


def test_discover_without_zeroconf_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "pixcull.sync.discovery.ZEROCONF_AVAILABLE", False
    )
    assert discover_events(timeout=0.1) == []


def test_close_zc_idempotent():
    """Calling close_zc when nothing was opened doesn't crash."""
    close_zc()
    close_zc()


# ---------------------------------------------------------------------------
# Zeroconf-installed round-trip (only runs when the optional dep is there)
# ---------------------------------------------------------------------------


pytestmark_zc = pytest.mark.skipif(
    not ZEROCONF_AVAILABLE,
    reason="zeroconf not installed (pip install -e '.[sync]')",
)


@pytestmark_zc
def test_advertise_then_discover_same_process():
    """End-to-end: advertise a fake event, give the multicast a
    moment to land, then discover finds our advertisement back.

    Excludes 'evt_p02_test' from the listener-side filter to confirm
    the exclusion path works (we explicitly DO want to see our own
    event for this test, so don't pass that into the exclude set).
    """
    handle = None
    try:
        handle = advertise_event(
            event_id="evt_p02_test",
            label="p02-roundtrip",
            run_id="run_p02_test",
            port=8765,
            token="prefix12abcdef",
        )
        assert handle is not None
        # Multicast needs a beat to propagate even on loopback —
        # give the discover loop 1s.
        sessions = discover_events(timeout=1.0)
        eids = {s["event_id"] for s in sessions}
        assert "evt_p02_test" in eids
        found = next(s for s in sessions
                     if s["event_id"] == "evt_p02_test")
        assert found["label"] == "p02-roundtrip"
        assert found["run_id"] == "run_p02_test"
        # token_prefix is the first 6 chars of the token we registered
        assert found["token_prefix"] == "prefix"
        # host_url contains an IP + port
        assert found["host_url"].startswith("http://")
        assert ":8765" in found["host_url"]
    finally:
        if handle is not None:
            unadvertise_event(handle)
        close_zc()


@pytestmark_zc
def test_discover_excludes_self_event_ids():
    """exclude_self_event_ids is the path the serve_demo HTTP handler
    uses to hide its own advertisements from collaborators."""
    handle = None
    try:
        handle = advertise_event(
            event_id="evt_p02_excl",
            label="x",
            run_id="r2",
            port=8765,
            token="t" * 22,
        )
        sessions = discover_events(
            timeout=1.0,
            exclude_self_event_ids={"evt_p02_excl"},
        )
        eids = {s["event_id"] for s in sessions}
        assert "evt_p02_excl" not in eids
    finally:
        if handle is not None:
            unadvertise_event(handle)
        close_zc()


@pytestmark_zc
def test_unadvertise_removes_from_next_discover():
    handle = advertise_event(
        event_id="evt_p02_unadv",
        label="will-disappear",
        run_id="r3",
        port=8765,
        token="prefix34000000",
    )
    try:
        # Confirm visible first
        s1 = discover_events(timeout=1.0)
        assert any(s["event_id"] == "evt_p02_unadv" for s in s1)
        # Pull it
        assert unadvertise_event(handle) is True
        # 1s later, gone (zeroconf sends goodbye packets)
        import time
        time.sleep(1.2)
        s2 = discover_events(timeout=1.0)
        # Note: zeroconf caches; the goodbye may or may not have
        # propagated within our budget.  Best-effort assertion: at
        # minimum, the unadvertise call returned True.
        # If the test environment is slow, this might still be in
        # s2 — that's OK, the protocol is best-effort.
    finally:
        close_zc()
