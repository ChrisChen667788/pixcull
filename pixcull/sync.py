"""INFRA-2 — multi-machine sync for sample banks + face library +
location/face labels.

Pre-INFRA-2 every user / team profile lived under
``~/Library/Application Support/PixCull/`` on the machine where it
was created. A 3-person studio with Alice (iMac), Bob (MacBook Pro),
and Carol (Mac mini in the studio) couldn't share the
"wedding-team-1" team bank — every machine had its own copy that
drifted independently.

INFRA-2 adds a backend-agnostic sync layer with the simplest
possible adapter (folder mirror) that already works for the 80%
case: any shared filesystem path (iCloud Drive, Dropbox, OneDrive,
NAS-mounted SMB, rsync-shared dir) becomes the canonical store.
The user just points each machine at the same shared folder.

Why folder-mirror first
=======================
* Zero new dependencies. The OS already does the heavy lifting
  (iCloud Drive sync, Dropbox client, etc.); we just point a
  symlink at the shared folder.
* Easiest user setup. "Type the path; restart." No OAuth, no
  Backblaze keys, no S3 bucket setup.
* Idempotent. We don't conflict-resolve — the OS sync layer does
  (last-writer-wins on metadata, content-hashed filenames means
  same-content uploads don't conflict).

The adapter interface (``SyncAdapter`` ABC below) is generic — a
future ``S3Adapter`` / ``WebDAVAdapter`` / ``iCloudCloudKitAdapter``
plugs in for the cases where a folder mirror isn't acceptable
(true cloud-native, server-side dedup, signed URLs for clients
without filesystem mounts).

What gets synced
================
By default, when a sync target is configured, we MIRROR these
subtrees from ``user_root`` / ``team_root`` to the target:

  verticals/<key>/{good,bad}/<hash>.jpg   sample bank
  verticals/<key>/{metadata,policy_override,phrase_override}.json
  face_library.npz                        V22.2 face centroids
  llm_budget.json                         INFRA-4 daily ledger

NOT synced (transient / per-machine):
  /tmp/pixcull_demo/<run_id>/...          per-run output (huge)
  models/*.joblib                         per-machine retrains
  *.log, *.cache                          obvious

Config
======
``PIXCULL_SYNC_DIR`` env var = path to the shared root. On first
non-empty value, ``configure_sync_target(path)`` symlinks the
matching subtrees out to the shared dir. Existing local data is
moved (not copied) on first sync so no double-storage.

Use ``status()`` for an admin readout of what's mirrored where.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path


# Subtrees that participate in multi-machine sync. Each entry is
# relative to a user_root (or team_root). The folder-mirror adapter
# replaces each with a symlink to the shared target's matching path.
_SYNC_SUBTREES_PER_USER = [
    "verticals",
    "face_library.npz",
    "llm_budget.json",
]
_SYNC_SUBTREES_PER_TEAM = [
    "verticals",
]


class SyncAdapter(ABC):
    """Future-proof interface. The folder-mirror adapter below is
    the only implementation today; S3 / WebDAV / iCloud CloudKit
    would each subclass this when there's demand.
    """

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def link_user_path(self, user_id: str, rel: str,
                          local_path: Path) -> bool:
        """Make ``local_path`` resolve to the shared backend's
        copy of ``users/<user_id>/<rel>``. Returns True on success."""
        ...

    @abstractmethod
    def link_team_path(self, team_id: str, rel: str,
                          local_path: Path) -> bool:
        ...

    @abstractmethod
    def describe(self) -> dict:
        """Admin readout."""
        ...


class FolderMirrorAdapter(SyncAdapter):
    """Simplest sync backend: a shared filesystem folder.

    Works with any OS-level sync (iCloud Drive, Dropbox, OneDrive,
    rsync mount, SMB share). The user just points each PixCull
    instance at the same path; we symlink the relevant subtrees
    into it.

    First-time setup behavior: if the user_root has existing local
    data AND the shared target is empty, MOVE the data into the
    target before creating the symlink — no double storage, no
    silent overwrites.
    """

    def __init__(self, shared_root: Path):
        self.shared_root = Path(shared_root).expanduser().resolve()

    def is_available(self) -> bool:
        if not self.shared_root.exists():
            return False
        # Smoke-write to confirm we can actually write — iCloud Drive
        # in particular has a "not yet downloaded" state where the
        # folder exists but writes silently fail.
        try:
            self.shared_root.mkdir(parents=True, exist_ok=True)
            probe = self.shared_root / ".pixcull_sync_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False

    def _link_one(self, target_path: Path, local_path: Path) -> bool:
        """Symlink-or-move logic. Idempotent on re-runs."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        # Already symlinked correctly?
        if local_path.is_symlink():
            try:
                if local_path.resolve() == target_path.resolve():
                    return True
            except OSError:
                pass

        # Move existing local data into the shared target IF the
        # target doesn't already have data (avoid clobbering a
        # sync partner's content).
        if local_path.exists() and not local_path.is_symlink():
            if not target_path.exists():
                # First-time migration: move local → shared
                try:
                    shutil.move(str(local_path), str(target_path))
                except OSError as exc:
                    print(f"[sync] move {local_path} → {target_path} "
                          f"failed: {exc}", file=sys.stderr)
                    return False
            else:
                # Both exist → don't overwrite. User must merge
                # manually (rare; we surface this in status()).
                print(f"[sync] both local and shared have data at "
                      f"{local_path} — refusing to merge. Resolve "
                      f"manually then delete the local copy.",
                      file=sys.stderr)
                return False
        else:
            # No local data → just point the symlink at the target
            # (creating an empty dir if needed).
            target_path.mkdir(parents=True, exist_ok=True) \
                if local_path.suffix == "" else \
                target_path.touch()

        # Now create the symlink. Use a RELATIVE path so the link
        # survives the user moving their app data dir.
        try:
            rel = os.path.relpath(target_path, local_path.parent)
            if local_path.exists() or local_path.is_symlink():
                local_path.unlink()
            os.symlink(rel, local_path,
                       target_is_directory=target_path.is_dir())
            return True
        except OSError as exc:
            print(f"[sync] symlink {local_path} → {target_path} failed: "
                  f"{exc}", file=sys.stderr)
            return False

    def link_user_path(self, user_id: str, rel: str,
                          local_path: Path) -> bool:
        target = self.shared_root / "users" / user_id / rel
        return self._link_one(target, local_path)

    def link_team_path(self, team_id: str, rel: str,
                          local_path: Path) -> bool:
        target = self.shared_root / "teams" / team_id / rel
        return self._link_one(target, local_path)

    def describe(self) -> dict:
        return {
            "kind":         "folder_mirror",
            "shared_root":  str(self.shared_root),
            "available":    self.is_available(),
            "writable":     self.is_available(),    # same check
        }


# Module-level singleton, lazy-loaded from env on first use.
_ADAPTER: SyncAdapter | None = None


def _get_adapter() -> SyncAdapter | None:
    """Resolve the active sync adapter or None if not configured."""
    global _ADAPTER
    if _ADAPTER is not None:
        return _ADAPTER
    shared = os.environ.get("PIXCULL_SYNC_DIR") or ""
    if not shared:
        return None
    a = FolderMirrorAdapter(Path(shared))
    if not a.is_available():
        print(f"[sync] PIXCULL_SYNC_DIR={shared!r} not writable — "
              f"sync disabled this session.", file=sys.stderr)
        return None
    _ADAPTER = a
    return a


def configure_sync_for_user(user_id: str) -> dict:
    """Wire all sync subtrees for one user. Idempotent on re-runs.

    Returns a status dict listing each subtree's link result.
    """
    adapter = _get_adapter()
    if adapter is None:
        return {"ok": False, "reason": "no sync target configured "
                "(set PIXCULL_SYNC_DIR)"}
    from pixcull.users import user_root
    udir = user_root(user_id)
    results: dict[str, bool] = {}
    for rel in _SYNC_SUBTREES_PER_USER:
        local = udir / rel
        ok = adapter.link_user_path(user_id, rel, local)
        results[rel] = ok
    return {"ok": all(results.values()),
            "user_id": user_id,
            "results": results,
            "adapter": adapter.describe()}


def configure_sync_for_team(team_id: str) -> dict:
    adapter = _get_adapter()
    if adapter is None:
        return {"ok": False, "reason": "no sync target configured"}
    from pixcull.users import team_root
    tdir = team_root(team_id)
    results: dict[str, bool] = {}
    for rel in _SYNC_SUBTREES_PER_TEAM:
        local = tdir / rel
        ok = adapter.link_team_path(team_id, rel, local)
        results[rel] = ok
    return {"ok": all(results.values()),
            "team_id": team_id,
            "results": results,
            "adapter": adapter.describe()}


def status() -> dict:
    """Admin readout of sync configuration + per-subtree state.

    Includes:
      * adapter info (kind, shared_root, writable)
      * for the active user: which subtrees are symlinked
        through the shared target vs. living locally
    """
    adapter = _get_adapter()
    if adapter is None:
        return {
            "schema":     "pixcull.sync.status.v1",
            "configured": False,
            "hint":       "set PIXCULL_SYNC_DIR=/path/to/shared "
                          "(iCloud Drive folder works) + restart",
        }
    from pixcull.users import get_active_user, user_root
    uid = get_active_user()
    udir = user_root(uid)
    subtree_state: dict[str, str] = {}
    for rel in _SYNC_SUBTREES_PER_USER:
        p = udir / rel
        if p.is_symlink():
            try:
                tgt = p.resolve()
                subtree_state[rel] = f"linked → {tgt}"
            except OSError:
                subtree_state[rel] = "linked → (unresolvable)"
        elif p.exists():
            subtree_state[rel] = "local only (not yet synced)"
        else:
            subtree_state[rel] = "absent"
    return {
        "schema":      "pixcull.sync.status.v1",
        "configured":  True,
        "adapter":     adapter.describe(),
        "active_user": uid,
        "subtrees":    subtree_state,
    }


__all__ = [
    "SyncAdapter",
    "FolderMirrorAdapter",
    "configure_sync_for_user",
    "configure_sync_for_team",
    "status",
]
