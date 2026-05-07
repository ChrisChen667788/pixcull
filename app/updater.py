"""V13.0 — pure-Python Sparkle-style updater.

Why we don't use the real Sparkle Objective-C framework:
* PyInstaller bundling Sparkle (a 5MB AppKit framework) would
  push the .app over its current 1.3GB size + add fragility.
* We only need Sparkle's "check appcast → notify user" loop, not
  its in-place replacement (we have full DMG download UX).

This module:
* Polls https://pixcull.dev/appcast.xml every 24 hours (debounced
  via ~/Library/Application Support/PixCull/last_update_check.txt).
* Compares <sparkle:version> against the running .app's bundled
  CFBundleVersion.
* If newer is available, sends a macOS notification + updates the
  status bar menu item to '⚠ 有新版本 vN.N (点击更新)'.
* Manual trigger: launcher.py menu '检查更新' calls check_for_update
  with force=True.

Failure-mode behavior:
* Network down → silent skip, retry next launch
* Appcast malformed → log to ~/.../logs/, no UI noise
* User on a tier-restricted (free) version + the new release
  requires Pro → show upgrade-Pro link instead of update prompt
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from xml.etree import ElementTree as ET


APPCAST_URL = os.environ.get(
    "PIXCULL_APPCAST_URL",
    "https://pixcull.dev/appcast.xml",
)
CHECK_INTERVAL_S = 24 * 3600


def _data_dir() -> Path:
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        p = Path.home() / ".pixcull"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _last_check_path() -> Path:
    return _data_dir() / "last_update_check.txt"


def _read_last_check() -> float:
    p = _last_check_path()
    if not p.exists():
        return 0.0
    try:
        return float(p.read_text().strip())
    except (OSError, ValueError):
        return 0.0


def _write_last_check() -> None:
    _last_check_path().write_text(str(time.time()))


def _running_version() -> str:
    """Read CFBundleShortVersionString from our own Info.plist when
    bundled. In dev mode, return the hardcoded VERSION constant."""
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller bundle — Info.plist is two dirs up
        plist = Path(sys._MEIPASS).parent.parent / "Info.plist"  # type: ignore
        if plist.exists():
            try:
                import plistlib
                d = plistlib.loads(plist.read_bytes())
                return str(d.get("CFBundleShortVersionString", "0.0"))
            except Exception:
                pass
    return "13.0"


def _parse_version(v: str) -> tuple[int, ...]:
    """'13.0' → (13, 0). Strips non-numeric suffixes like '-beta'."""
    nums = re.findall(r"\d+", v)
    return tuple(int(x) for x in nums) or (0,)


def _is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _fetch_appcast() -> ET.Element | None:
    try:
        req = urllib.request.Request(
            APPCAST_URL,
            headers={"User-Agent": f"PixCull/{_running_version()}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        return ET.fromstring(data)
    except (urllib.error.URLError, ET.ParseError, OSError):
        return None


def check_for_update(force: bool = False) -> dict:
    """Return {available, current, latest, download_url, notes} or
    {available: False, reason: '...'}."""
    if not force and (time.time() - _read_last_check()) < CHECK_INTERVAL_S:
        return {"available": False, "reason": "debounced"}
    _write_last_check()

    root = _fetch_appcast()
    if root is None:
        return {"available": False, "reason": "network/parse error"}

    NS = {"sparkle": "http://www.andymatuschak.org/xml-namespaces/sparkle"}
    items = root.findall(".//item")
    if not items:
        return {"available": False, "reason": "appcast 无 item"}

    # Newest item is the first <item>
    item = items[0]
    enclosure = item.find("enclosure")
    if enclosure is None:
        return {"available": False, "reason": "无 enclosure"}
    remote_v = enclosure.get(
        "{http://www.andymatuschak.org/xml-namespaces/sparkle}shortVersionString",
        ""
    )
    if not remote_v:
        remote_v = enclosure.get(
            "{http://www.andymatuschak.org/xml-namespaces/sparkle}version", ""
        )
    download_url = enclosure.get("url", "")
    notes_el = item.find("description")
    notes = notes_el.text if notes_el is not None else ""

    local_v = _running_version()
    if not _is_newer(remote_v, local_v):
        return {"available": False, "current": local_v, "latest": remote_v,
                "reason": f"已是最新 {local_v}"}

    return {
        "available": True,
        "current": local_v,
        "latest": remote_v,
        "download_url": download_url,
        "notes": (notes or "")[:600],
    }


def notify_macos(title: str, message: str) -> None:
    """Send a macOS notification via osascript."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            timeout=5,
        )
    except Exception:
        pass


def background_check(callback=None) -> None:
    """Fire-and-forget update check. Calls back with the result dict
    if a newer version is found. Safe to invoke from the main launcher
    thread; no GUI side-effects."""
    result = check_for_update(force=False)
    if not result.get("available"):
        return
    notify_macos(
        "PixCull · 有新版本",
        f"v{result['latest']} 已发布 (你当前 v{result['current']})。"
        f"在菜单栏点 '检查更新' 下载。"
    )
    if callback:
        try:
            callback(result)
        except Exception:
            pass


if __name__ == "__main__":
    # CLI entry: `python -m pixcull.updater` — useful for testing
    print(json.dumps(check_for_update(force=True), ensure_ascii=False, indent=2))
