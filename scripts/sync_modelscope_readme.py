#!/usr/bin/env python3
"""Sync modelscope/README.md → ModelScope model repo via official SDK.

Why we needed to find this: ModelScope's web UI is the official path
for README updates, but they DO ship a Python SDK with
``HubApi.upload_file`` / ``upload_folder`` / ``create_commit`` — the
same shape as huggingface_hub.  Their model repos are git-LFS-backed,
so a token-authed SDK call gives us full programmatic updates.

Discovery trail (for the next maintainer)
=========================================
* SDK: ``pip install modelscope`` — full-fat install (~200 MB,
  pulls torch etc.); ``modelscope[fundamental]`` is a lighter
  alternative if you only need Hub
* API: ``from modelscope.hub.api import HubApi``
* Auth: ``HubApi.login(access_token=...)`` OR env
  ``MODELSCOPE_API_TOKEN``; persists to ``~/.modelscope/credentials``
  for 30 days
* Repo type: ``"model"`` (since we registered PixCull as a Model,
  not a Dataset or Studio)
* Token source: https://modelscope.cn/my/myaccesstoken — generate
  one with "SDK 访问令牌" type

What this script does
=====================
1. Loads ``modelscope/README.md`` from this repo
2. Rewrites relative ``docs/screenshots/*.png`` references to
   absolute ``https://raw.githubusercontent.com/.../main/...``
   URLs, so screenshots load from GitHub's CDN without us needing
   to mirror binaries to ModelScope.  (Hero SVGs in the README
   are already absolute URLs.)
3. Logs into HubApi with the token (env or arg)
4. Uploads the rewritten README to the configured repo

Idempotent — re-running with the same content is a no-op commit on
ModelScope's end (their server detects identical SHA).  Safe to
wire into CI / release flow.

Usage
=====

    # Token from env (preferred — no shell history leak)
    export MODELSCOPE_API_TOKEN=ms-xxxxxxxxxxxx
    python scripts/sync_modelscope_readme.py

    # Dry-run — show what would be uploaded, don't push
    python scripts/sync_modelscope_readme.py --dry-run

    # Different repo / commit message
    python scripts/sync_modelscope_readme.py \\
        --repo-id haozi667788/pixcull \\
        --commit-message "v0.10 — 13 fresh screenshots + design uplift"

Security
========
* Token NEVER printed.  Script aborts cleanly if env + arg both
  missing.
* Read-only access to local files; doesn't modify the source
  ``modelscope/README.md``.

Exit codes
==========
* 0 — sync succeeded
* 1 — auth failure / network error
* 2 — local file missing
* 3 — SDK missing
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


REPO_ROOT      = Path(__file__).resolve().parent.parent
README_SOURCE  = REPO_ROOT / "modelscope" / "README.md"

# GitHub raw-content base for the active branch.  All relative
# docs/* paths in the README get rewritten to this base.
GH_RAW_BASE = (
    "https://raw.githubusercontent.com/ChrisChen667788/pixcull/main"
)

# Default repo + commit metadata.  Overridable via CLI args.
DEFAULT_REPO_ID  = "haozi667788/pixcull"
DEFAULT_MESSAGE  = "chore(docs): sync README from upstream GitHub"


def _rewrite_relative_paths(text: str, base_url: str) -> str:
    """Turn every relative ``docs/...`` path inside Markdown image
    refs or HTML <img src=> into an absolute raw.githubusercontent
    URL.

    Handles:
      ``![alt](docs/screenshots/01.png)``
      ``<img src="docs/brand/mark.svg" ...>``

    Leaves absolute URLs untouched (lines that already begin with
    ``https://``).
    """
    # ![alt](relative/path)  →  ![alt](base/relative/path)
    text = re.sub(
        r"(!\[[^\]]*\]\()(docs/[^)]+)\)",
        lambda m: f"{m.group(1)}{base_url}/{m.group(2)})",
        text,
    )
    # <img src="relative/path"> → <img src="base/relative/path">
    text = re.sub(
        r'(<img[^>]*\bsrc=")(docs/[^"]+)"',
        lambda m: f"{m.group(1)}{base_url}/{m.group(2)}\"",
        text,
    )
    return text


def _resolve_token(arg_token: str | None) -> str | None:
    """Token precedence: CLI arg > env > saved credentials.

    Returns None when none of the above produce a non-empty token —
    caller decides whether to abort or fall through to anonymous.
    """
    if arg_token:
        return arg_token.strip()
    env = os.environ.get("MODELSCOPE_API_TOKEN", "").strip()
    if env:
        return env
    # Saved cred from a prior login (30-day TTL)
    cred = Path.home() / ".modelscope" / "credentials"
    if cred.exists():
        # Don't try to parse — the SDK does that internally on
        # next HubApi() construction.  Just signal "use saved".
        return ""
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Sync modelscope/README.md → ModelScope repo."
    )
    p.add_argument(
        "--repo-id", default=DEFAULT_REPO_ID,
        help=f"ModelScope repo id (default: {DEFAULT_REPO_ID})"
    )
    p.add_argument(
        "--commit-message", default=DEFAULT_MESSAGE,
        help="Commit message on ModelScope"
    )
    p.add_argument(
        "--readme-source", type=Path, default=README_SOURCE,
        help="Local README source path"
    )
    p.add_argument(
        "--token", default=None,
        help="ModelScope SDK token (overrides MODELSCOPE_API_TOKEN). "
             "DO NOT pass on the command line — use env var instead."
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print the rewritten README + intended commit, "
             "don't actually upload"
    )
    p.add_argument(
        "--branch", default="master",
        help="Target branch on the ModelScope repo (default: master)"
    )
    p.add_argument(
        "--no-rewrite", action="store_true",
        help="Skip the docs/* → raw.githubusercontent.com URL rewrite "
             "(use when you've already done the rewrite manually)"
    )
    args = p.parse_args(argv)

    # Step 1 — read the source README.
    if not args.readme_source.exists():
        print(f"[modelscope-sync] not found: {args.readme_source}",
              file=sys.stderr)
        return 2
    original = args.readme_source.read_text(encoding="utf-8")

    # Step 2 — rewrite relative image paths to absolute GitHub raw URLs.
    if args.no_rewrite:
        rewritten = original
    else:
        rewritten = _rewrite_relative_paths(original, GH_RAW_BASE)
    n_rewrites = rewritten.count(GH_RAW_BASE) - original.count(GH_RAW_BASE)
    print(f"[modelscope-sync] {n_rewrites} relative image paths rewritten",
          file=sys.stderr)

    # Step 3 — dry-run path: write the rewritten README to /tmp + bail.
    if args.dry_run:
        preview = Path("/tmp/modelscope_readme_preview.md")
        preview.write_text(rewritten, encoding="utf-8")
        print(f"[modelscope-sync] DRY RUN — would upload {len(rewritten):,} "
              f"chars to {args.repo_id}#{args.branch}",
              file=sys.stderr)
        print(f"[modelscope-sync] preview at {preview}", file=sys.stderr)
        # Sanity sample
        for line in rewritten.splitlines()[:5]:
            print(f"  | {line}", file=sys.stderr)
        return 0

    # Step 4 — import SDK lazily so --dry-run works without it.
    try:
        from modelscope.hub.api import HubApi
    except ImportError as exc:
        print(f"[modelscope-sync] modelscope SDK not installed: {exc}",
              file=sys.stderr)
        print("[modelscope-sync] fix: pip install modelscope",
              file=sys.stderr)
        return 3

    # Step 5 — auth.
    token = _resolve_token(args.token)
    if token is None:
        print("[modelscope-sync] no token (set MODELSCOPE_API_TOKEN env "
              "var or run `modelscope login` once to cache credentials)",
              file=sys.stderr)
        return 1
    api = HubApi()
    try:
        if token:        # non-empty → explicit login
            api.login(access_token=token)
        # Empty string means "use saved credentials" — HubApi reads
        # ~/.modelscope automatically on first request.
    except Exception as exc:  # noqa: BLE001 — SDK raises broad exc types
        print(f"[modelscope-sync] login failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    # Step 6 — upload the README.
    # `upload_file` accepts bytes via `path_or_fileobj` (avoids the
    # local-file roundtrip; we want to upload the REWRITTEN content,
    # not the source).
    try:
        commit = api.upload_file(
            path_or_fileobj=rewritten.encode("utf-8"),
            path_in_repo="README.md",
            repo_id=args.repo_id,
            repo_type="model",
            commit_message=args.commit_message,
            revision=args.branch,
            disable_tqdm=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[modelscope-sync] upload failed: "
              f"{type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    # `commit` is a CommitInfo with .commit_url / .commit_message
    print(f"[modelscope-sync] ✓ uploaded to {args.repo_id}#{args.branch}",
          file=sys.stderr)
    if hasattr(commit, "commit_url") and commit.commit_url:
        print(f"[modelscope-sync] view at: {commit.commit_url}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
