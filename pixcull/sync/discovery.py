"""v0.10-P0-2 — mDNS auto-discovery for LAN sync events.

The v0.8-P0-2 LAN sync requires the host to share a URL ("scan this
QR" or "paste this link") with collaborators.  That's fine for a
remote second-shooter but feels archaic on the same LAN where any
modern app (AirDrop, Sonos, Time Machine) just *finds* peers via
Bonjour / mDNS.

This module adds a zeroconf service announcement so PixCull
instances on the same LAN can discover each other's active sync
events without any URL exchange:

  * Host calls advertise_event(event_session, port) when a session
    is issued.  We broadcast _pixcull-sync._tcp.local. with the
    event_id + label as TXT records.
  * Collaborator calls discover_events(timeout=2.0) when the
    results page opens.  Returns a list of {event_id, label,
    host_url, run_id} so the UI can show a toast "在 LAN 内发现 N
    个协作会话".
  * unadvertise_event() cleans up when the event is revoked.

Optional zeroconf import
========================
zeroconf is a sync/multicast UDP lib that pip-installs ~6 MB of
dependencies (ifaddr etc.).  We make it an optional install
(``pip install -e ".[sync]"``) so users who only do solo runs
don't pay the import cost.  When zeroconf isn't available, this
module's public functions return cleanly (no advertise / empty
discover list) and the caller-side UI shows the legacy "paste
URL" flow.
"""

from __future__ import annotations

import socket
from typing import Any

# Optional import.  We re-export the availability flag so callers
# can decide whether to render the "LAN discovered N sessions"
# toast at all.
try:
    from zeroconf import (
        IPVersion,
        ServiceBrowser,
        ServiceInfo,
        ServiceListener,
        Zeroconf,
    )
    ZEROCONF_AVAILABLE = True
except ImportError:
    Zeroconf = None  # type: ignore
    ServiceBrowser = None  # type: ignore
    ServiceInfo = None  # type: ignore
    ServiceListener = object  # type: ignore
    IPVersion = None  # type: ignore
    ZEROCONF_AVAILABLE = False


SERVICE_TYPE = "_pixcull-sync._tcp.local."


def _local_ipv4() -> str:
    """Best-effort guess of the LAN IPv4 the host should advertise.

    We connect a UDP socket to a public IP (no packet actually sent)
    to discover which interface the OS would use; the local end of
    that socket is the LAN address.  Falls back to 127.0.0.1 if
    something blocks (no network, container without bridge, ...).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# Shared singleton per process.  zeroconf opens UDP sockets, so we
# don't spin up multiple instances if advertise + discover are both
# called from the same serve_demo.
_zc_singleton = None


def _zc() -> Any:
    """Lazy-init the shared Zeroconf instance.  Raises if the
    dependency isn't installed — callers should gate on
    ZEROCONF_AVAILABLE first."""
    global _zc_singleton
    if not ZEROCONF_AVAILABLE:
        raise RuntimeError(
            "zeroconf not installed — pip install -e '.[sync]'"
        )
    if _zc_singleton is None:
        _zc_singleton = Zeroconf(ip_version=IPVersion.V4Only)
    return _zc_singleton


def close_zc() -> None:
    """Tear down the singleton.  Called by serve_demo on shutdown."""
    global _zc_singleton
    if _zc_singleton is not None:
        try:
            _zc_singleton.close()
        except Exception:
            pass
        _zc_singleton = None


def _service_name(event_id: str, host: str | None = None) -> str:
    """Per-event service name — unique within the LAN.

    Format: "PixCull-<event_id>-<hostname>._pixcull-sync._tcp.local."
    We include the hostname so two different machines hosting events
    with the same event_id (impossible by design but defensive) can
    still both register.
    """
    h = host or socket.gethostname().split(".")[0]
    safe_eid = event_id.replace(".", "_").replace(" ", "_")
    safe_h = h.replace(".", "_").replace(" ", "_")
    return f"PixCull-{safe_eid}-{safe_h}.{SERVICE_TYPE}"


def advertise_event(
    *,
    event_id: str,
    label: str,
    run_id: str,
    port: int,
    token: str,
) -> dict | None:
    """Broadcast a sync event on the LAN.

    Returns a "handle" dict the caller stashes; pass it back to
    :func:`unadvertise_event` on event revoke.  Returns None when
    zeroconf isn't available — callers should treat that as
    "advertisement skipped, sharing still works via URL".

    The TXT record carries enough metadata that collaborators don't
    need to refetch from the host before deciding whether to join:
      event_id   — for stable comparison / dedup
      label      — display string ("婚礼-2026-06-15")
      run_id     — confirms which run this event scopes
      token_prefix — first 6 chars of the token, so the UI can
                     dedup with a pasted URL that has the full token
      version    — protocol version for future compatibility
    """
    if not ZEROCONF_AVAILABLE:
        return None
    ip = _local_ipv4()
    name = _service_name(event_id)
    # TXT-record values must be bytes when shipping to zeroconf.
    props: dict[bytes, bytes] = {
        b"event_id":     event_id.encode("utf-8"),
        b"label":        (label or "")[:80].encode("utf-8"),
        b"run_id":       run_id.encode("utf-8"),
        b"token_prefix": (token[:6] or "").encode("utf-8"),
        b"version":      b"1",
    }
    info = ServiceInfo(
        type_=SERVICE_TYPE,
        name=name,
        addresses=[socket.inet_aton(ip)],
        port=int(port),
        properties=props,
        server=f"{socket.gethostname()}.local.",
    )
    try:
        _zc().register_service(info)
    except Exception:
        # zeroconf raises NonUniqueNameException etc. for legitimate
        # reasons (two events with the same id on the same host).
        # Return None so the caller knows advertisement didn't take.
        return None
    return {
        "service_name": name,
        "event_id":     event_id,
        "ip":           ip,
        "port":         port,
        "info":         info,
    }


def unadvertise_event(handle: dict | None) -> bool:
    """Stop advertising an event.  Idempotent."""
    if not handle or not ZEROCONF_AVAILABLE:
        return False
    info = handle.get("info")
    if info is None:
        return False
    try:
        _zc().unregister_service(info)
        return True
    except Exception:
        return False


def discover_events(
    *,
    timeout: float = 2.0,
    exclude_self_event_ids: set[str] | None = None,
) -> list[dict]:
    """Scan the LAN for active PixCull sync events.

    ``timeout`` seconds to listen; 2s is a good default — long
    enough that slow LANs respond, short enough that the UI doesn't
    feel laggy on first results-page open.

    Returns a list of dicts:
      [{
        event_id, label, run_id, token_prefix,
        host_url,      # http://<ip>:<port> — what the JS side fetches
        service_name,
      }, ...]

    Returns [] when zeroconf isn't available.  The caller-side UI
    in that case skips the auto-discovered toast — pasting URLs
    still works.
    """
    if not ZEROCONF_AVAILABLE:
        return []
    exclude = exclude_self_event_ids or set()
    found: dict[str, dict] = {}   # event_id → record

    class _Listener(ServiceListener):
        def __init__(self):
            super().__init__()
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=int(timeout * 1000))
            if info is None:
                return
            props = info.properties or {}
            def _s(k: str) -> str:
                v = props.get(k.encode("utf-8"))
                if v is None:
                    return ""
                if isinstance(v, bytes):
                    try:
                        return v.decode("utf-8")
                    except UnicodeDecodeError:
                        return ""
                return str(v)
            eid = _s("event_id")
            if not eid or eid in exclude:
                return
            ip = ""
            if info.addresses:
                try:
                    ip = socket.inet_ntoa(info.addresses[0])
                except OSError:
                    ip = ""
            found[eid] = {
                "event_id":     eid,
                "label":        _s("label"),
                "run_id":       _s("run_id"),
                "token_prefix": _s("token_prefix"),
                "host_url":     f"http://{ip}:{info.port}" if ip else "",
                "service_name": name,
            }
        def remove_service(self, zc, type_, name):
            # We don't bother tracking removal during the brief
            # discovery window — the next call will skip them.
            pass
        def update_service(self, zc, type_, name):
            self.add_service(zc, type_, name)

    listener = _Listener()
    browser = ServiceBrowser(_zc(), SERVICE_TYPE, listener)
    import time as _t
    _t.sleep(timeout)
    try:
        browser.cancel()
    except Exception:
        pass
    return list(found.values())
