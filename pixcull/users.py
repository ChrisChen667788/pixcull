"""V28 — multi-user profiles + shared team sample banks.

ROADMAP P1.4. Pre-V28 PixCull was strictly single-user: one
``~/Library/Application Support/PixCull/`` directory shared by anyone
who logged into the Mac. For a studio with 3 photographers on the
same machine, they all see each other's sample banks and policy
overrides — there's no way to keep "Alice's wedding bank" separate
from "Bob's bird bank".

V28 adds:

1. **User profiles** under ``<data_root>/users/<user_id>/``
   Each user has their own verticals/, runs/, settings/, etc.
   The legacy global layout (``<data_root>/verticals/...``) still
   exists; on first V28 run a "default" user transparently
   inherits it via symlinks (no data move) so existing single-user
   installs keep working.

2. **Active user selection** via ``PIXCULL_USER`` env var. Defaults
   to "default" → the legacy single-user installation.

3. **Team mode** — a per-vertical redirect file
   ``<user_root>/verticals/<key>/_team_redirect.json`` points the
   bank at a shared ``<data_root>/teams/<team_id>/verticals/<key>/``
   path. Multiple users can subscribe to the same team bank by
   placing the same redirect file. Edits made by any subscriber
   are immediately visible to the others (it's a shared dir, not
   a copy).

What's NOT in V28
=================
* No authentication: this is local-first multi-tenant. Users are
  identified by ``PIXCULL_USER`` env var, no password. Appropriate
  for a trusted studio where everyone logs into different macOS
  user accounts already. Real auth is V28.1+ when we cross the
  LAN boundary.
* No conflict resolution on team banks: if two photographers
  simultaneously upload the same sample, the content-hashed
  filename means they overwrite the same file. Race is benign
  (same content → same hash → same path).
* UI: V28 ships the data layer + API endpoints + CLI. The browser
  /verticals page doesn't have a user dropdown yet — that's V28.1.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path


# Whitelist of legal user IDs. Keeps file paths sane (Unicode names work
# but symbol noise like '/' or '..' would break the directory layout).
# Mirrors GitHub username rules: alphanumeric + dash + underscore, 1-39
# chars, can't start with dash. Sufficient for studio scale.
import re as _re
_USER_ID_RE = _re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,38}$")


def _app_data_root() -> Path:
    """Top-level PixCull app data dir. Platform-conventional location.

    macOS: ``~/Library/Application Support/PixCull``
    Linux/Win: ``~/.pixcull``

    This is the GLOBAL root — user profiles live below it. The legacy
    pre-V28 storage (``<root>/verticals/...``) coexists with the new
    ``<root>/users/<id>/verticals/...`` layout; ``default`` symlinks
    bridge the two.
    """
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        p = Path.home() / ".pixcull"
    p.mkdir(parents=True, exist_ok=True)
    return p


# V28.2 — per-request user override. The HTTP handler can set this
# (via a cookie or header read at the top of do_GET / do_POST) so
# different requests can target different users WITHOUT changing
# the env var + restarting. Falls through to the env-var default
# when nothing is set on the current thread.
#
# threading.local because the HTTPServer uses ThreadingHTTPServer
# in V21+ (one thread per request), so attribute access naturally
# isolates per-request state.
_REQUEST_USER = threading.local()


def set_request_user(user_id: str | None) -> None:
    """V28.2 — set the per-request user override.

    Call at the start of each HTTP request from a cookie / header.
    Pass None to clear (revert to env-var default). Invalid IDs are
    silently dropped — same behavior as ``get_active_user`` for env
    var.
    """
    if user_id is None:
        if hasattr(_REQUEST_USER, "uid"):
            del _REQUEST_USER.uid
        return
    if not _USER_ID_RE.match(user_id):
        return
    _REQUEST_USER.uid = user_id


def get_active_user() -> str:
    """Return the active user id.

    Lookup priority:
      1. V28.2 per-request override (``set_request_user``)
      2. ``PIXCULL_USER`` env var (V28 baseline)
      3. ``"default"`` (the legacy single-user install)

    Invalid IDs at any layer silently fall through to ``default``
    rather than crashing — keeps the data-access path safe even
    when a bogus value sneaks in via env var or cookie.
    """
    req_uid = getattr(_REQUEST_USER, "uid", None)
    if req_uid and _USER_ID_RE.match(req_uid):
        return req_uid
    uid = os.environ.get("PIXCULL_USER") or "default"
    if not _USER_ID_RE.match(uid):
        print(f"[users] invalid PIXCULL_USER={uid!r} — using 'default'",
              file=sys.stderr)
        return "default"
    return uid


def user_root(user_id: str | None = None) -> Path:
    """Resolve a user's profile directory. Creates lazily.

    On first call for ``default``, also runs the V28 migration
    that creates symlinks from ``users/default/verticals`` →
    ``../../verticals`` so the legacy single-user data is
    transparently picked up.
    """
    uid = user_id or get_active_user()
    if not _USER_ID_RE.match(uid):
        raise ValueError(f"invalid user_id: {uid!r}")
    root = _app_data_root()
    udir = root / "users" / uid
    udir.mkdir(parents=True, exist_ok=True)
    if uid == "default":
        _ensure_default_user_migration(root, udir)
    return udir


def _ensure_default_user_migration(root: Path, default_udir: Path) -> None:
    """V28 first-run: the 'default' user inherits the legacy global
    sample-bank dir via a symlink, so single-user installs upgrading
    to V28 don't need to move any data.

    Idempotent — only creates the symlink if the legacy verticals/
    exists AND the user-scoped verticals/ doesn't yet.
    """
    legacy = root / "verticals"
    new_verticals = default_udir / "verticals"
    if new_verticals.exists() or new_verticals.is_symlink():
        return  # already migrated
    if not legacy.exists():
        # No legacy data — just create a fresh empty user dir
        new_verticals.mkdir(parents=True, exist_ok=True)
        return
    # Symlink: <root>/users/default/verticals → ../../verticals
    # (relative path keeps it portable if the user moves the root)
    try:
        rel = Path("..") / ".." / legacy.name
        os.symlink(rel, new_verticals, target_is_directory=True)
    except OSError as exc:
        print(f"[users] migration symlink failed ({exc}); falling back "
              f"to fresh user dir — legacy bank still accessible at "
              f"{legacy}", file=sys.stderr)
        new_verticals.mkdir(parents=True, exist_ok=True)


def list_users() -> list[dict]:
    """Enumerate user profiles found under ``<root>/users/``.

    Each entry has:
        ``user_id``        the directory name
        ``created_at``     mtime of the user's dir
        ``vertical_count`` number of verticals with any sample
        ``is_active``      bool — matches get_active_user()
    """
    root = _app_data_root()
    users_dir = root / "users"
    out: list[dict] = []
    if not users_dir.exists():
        return out
    active = get_active_user()
    for entry in sorted(users_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not _USER_ID_RE.match(entry.name):
            continue
        verticals_dir = entry / "verticals"
        vc = 0
        if verticals_dir.exists():
            try:
                for v in verticals_dir.iterdir():
                    if not v.is_dir():
                        continue
                    good = (v / "good").exists() and any(
                        f for f in (v / "good").iterdir() if f.is_file()
                    )
                    bad = (v / "bad").exists() and any(
                        f for f in (v / "bad").iterdir() if f.is_file()
                    )
                    if good or bad:
                        vc += 1
            except OSError:
                pass
        out.append({
            "user_id":        entry.name,
            "created_at":     entry.stat().st_mtime,
            "vertical_count": vc,
            "is_active":      entry.name == active,
        })
    return out


def create_user(user_id: str) -> dict:
    """Create a new user profile. Idempotent — returns the existing
    profile if it's already there.

    Raises ValueError on illegal user_id.
    """
    if not _USER_ID_RE.match(user_id):
        raise ValueError(
            f"invalid user_id {user_id!r} — must match "
            f"alphanumeric + dash + underscore, 1-39 chars, "
            f"non-dash start"
        )
    root = _app_data_root()
    udir = root / "users" / user_id
    already_existed = udir.exists()
    udir.mkdir(parents=True, exist_ok=True)
    (udir / "verticals").mkdir(parents=True, exist_ok=True)
    return {
        "user_id":          user_id,
        "created":          not already_existed,
        "data_root":        str(udir),
    }


# ---------------------------------------------------------------------------
# Team-mode redirects
# ---------------------------------------------------------------------------

def team_root(team_id: str) -> Path:
    """Resolve a team's shared sample-bank root. Creates lazily.

    Mirrors ``user_root`` but under ``<root>/teams/<team_id>/`` so
    multiple users can subscribe to the same bank without touching
    each other's personal data.
    """
    if not _USER_ID_RE.match(team_id):
        raise ValueError(f"invalid team_id: {team_id!r}")
    root = _app_data_root()
    tdir = root / "teams" / team_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "verticals").mkdir(parents=True, exist_ok=True)
    return tdir


def vertical_root_for_user(user_id: str, vertical_key: str) -> Path:
    """V28 — resolve the on-disk path for a (user, vertical) pair,
    honoring any team-redirect file.

    Lookup:
      1. ``<user>/verticals/<key>/_team_redirect.json`` exists →
         return the team path from it.
      2. Otherwise → ``<user>/verticals/<key>/``.

    The redirect file has shape:
        {"team_id": "wedding-team-1"}
    """
    udir = user_root(user_id)
    own_path = udir / "verticals" / vertical_key
    redirect = own_path / "_team_redirect.json"
    if redirect.exists():
        try:
            data = json.loads(redirect.read_text("utf-8"))
            tid = data.get("team_id")
            if tid and _USER_ID_RE.match(str(tid)):
                tdir = team_root(str(tid))
                team_vertical = tdir / "verticals" / vertical_key
                (team_vertical / "good").mkdir(parents=True, exist_ok=True)
                (team_vertical / "bad").mkdir(parents=True, exist_ok=True)
                return team_vertical
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            # Corrupt redirect — fall through to personal bank rather
            # than crash. Surface a warning so the user can fix it.
            print(f"[users] bad team redirect at {redirect}",
                  file=sys.stderr)
    (own_path / "good").mkdir(parents=True, exist_ok=True)
    (own_path / "bad").mkdir(parents=True, exist_ok=True)
    return own_path


def subscribe_to_team_vertical(user_id: str, vertical_key: str,
                                  team_id: str) -> dict:
    """Write a team redirect for one (user, vertical). After this
    call, ``vertical_root_for_user(user_id, vertical_key)`` returns
    the team path instead of the user's personal one.

    Idempotent — overwrites an existing redirect. Pass team_id=""
    (empty) to remove the redirect and restore personal bank.
    """
    udir = user_root(user_id)
    own_path = udir / "verticals" / vertical_key
    own_path.mkdir(parents=True, exist_ok=True)
    redirect_path = own_path / "_team_redirect.json"
    if not team_id:
        if redirect_path.exists():
            redirect_path.unlink()
        return {"user_id": user_id, "vertical": vertical_key,
                "team_id": None, "action": "unsubscribed"}
    if not _USER_ID_RE.match(team_id):
        raise ValueError(f"invalid team_id: {team_id!r}")
    # Create the team's vertical dir so the redirect target exists
    tdir = team_root(team_id)
    (tdir / "verticals" / vertical_key / "good").mkdir(
        parents=True, exist_ok=True)
    (tdir / "verticals" / vertical_key / "bad").mkdir(
        parents=True, exist_ok=True)
    redirect_path.write_text(
        json.dumps({
            "schema":         "pixcull.team_redirect.v1",
            "team_id":        team_id,
            "subscribed_at":  time.time(),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"user_id": user_id, "vertical": vertical_key,
            "team_id": team_id, "action": "subscribed"}


__all__ = [
    "_app_data_root",
    "get_active_user",
    "set_request_user",      # V28.2 — per-request override
    "user_root",
    "list_users",
    "create_user",
    "team_root",
    "vertical_root_for_user",
    "subscribe_to_team_vertical",
]
