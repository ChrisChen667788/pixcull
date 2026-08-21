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
import time
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


# Known-good .gitattributes: standard binary formats + images via LFS,
# but README / *.md / *.svg as TEXT.  Critically does NOT LFS-track
# README.md or .gitattributes itself.
_GITATTRIBUTES_TEXT = "\n".join([
    *(f"*.{ext} filter=lfs diff=lfs merge=lfs -text" for ext in (
        "7z arrow bin bz2 gz h5 joblib onnx parquet pb pt pth rar tar "
        "tflite tgz xz zip safetensors ckpt npy npz pkl pickle model "
        "msgpack".split())),
    "# pixcull: render docs as text; host images via LFS",
    "*.md text", "README.md text", "*.svg text",
    "*.png filter=lfs diff=lfs merge=lfs -text",
    "*.gif filter=lfs diff=lfs merge=lfs -text",
    "*.jpg filter=lfs diff=lfs merge=lfs -text",
    "*.jpeg filter=lfs diff=lfs merge=lfs -text",
    "*.webp filter=lfs diff=lfs merge=lfs -text",
]) + "\n"


def _shallow_clone(repo_id: str, branch: str, dest: Path) -> bool:
    """Depth-1, LFS-skipping clone via the cached git token.

    The SDK ``Repository`` does a FULL clone of the whole LFS history,
    which RPC-drops (``fetch-pack: early EOF``) on a large model repo or a
    flaky link.  We only rewrite two text files, so the branch tip is
    enough — depth-1 + ``GIT_LFS_SKIP_SMUDGE`` transfers a tiny pack and
    survives.  Returns ``False`` (caller falls back to the SDK clone) when
    the token is missing or the clone fails.  The tokenised URL is never
    printed.
    """
    import json as _json
    import os as _os
    import subprocess as _sp
    try:
        raw = (Path.home() / ".modelscope" / "credentials"
               / "git_token").read_text().strip()
    except OSError:
        return False
    try:
        parsed = _json.loads(raw)
        tok = parsed.get("git_token") or parsed.get("token") or ""
    except Exception:  # noqa: BLE001
        tok = raw
    tok = str(tok).strip().strip('"')
    if not tok:
        return False
    _SECRETS.add(tok)
    url = f"https://oauth2:{tok}@www.modelscope.cn/{repo_id}.git"
    env = {**_os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    r = _sp.run(["git", "clone", "--depth", "1", "--branch", branch,
                 "--single-branch", url, str(dest)],
                capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print("[modelscope-sync] shallow clone failed → falling back to SDK clone",
              file=sys.stderr)
        return False
    return True


def _asset_is_current(repo_id: str, branch: str, rel: str,
                      local: Path) -> bool:
    """Is the server already serving what we hold locally?

    Size-equality rather than a digest: ModelScope serves assets through
    a CDN redirect and exposes no hash we could compare without pulling
    the whole file.  Length separates the two cases that matter — absent
    (404, or a zero-length body) and stale (a different render of the
    same screenshot).  A same-size different-image collision is not a
    failure mode this sync can produce: the local file is the only place
    these ever come from.
    """
    import urllib.error
    import urllib.request
    url = (f"https://www.modelscope.cn/models/{repo_id}/resolve/"
           f"{branch}/{rel}")
    try:
        want = local.stat().st_size
    except OSError:
        return False
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            got = resp.headers.get("Content-Length")
            if got is not None:
                return int(got) == want
            return len(resp.read()) == want
    except (urllib.error.URLError, ValueError, OSError):
        return False


#: Every credential this script has constructed, so that _redact() does
#: not depend on each call site remembering to pass it along.
_SECRETS: set[str] = set()


def _redact(text: str, *secrets: str) -> str:
    """Strip credentials out of anything this script prints.

    v2.67.1 — a failed push printed git's own error, and git names the
    remote in it.  The remote is ``https://oauth2:<token>@…`` because
    that is how the shallow clone authenticates, so the token went to
    the terminal, the CI log and the scrollback of whoever ran `make
    modelscope-sync`.  The token is not the interesting part of any
    error message; nothing is lost by removing it, and it is not enough
    to redact the one message we know about — every subprocess stream
    this script surfaces goes through here.
    """
    out = str(text)
    for sec in (*secrets, *_SECRETS):
        if sec and len(sec) >= 4:
            out = out.replace(sec, "***")
    # Belt and braces: any userinfo in a URL, whether or not we were
    # handed the secret that built it.
    return re.sub(r"(https?://)[^/\s@]+@", r"\1***@", out)


def _git_push_readme(repo_id: str, branch: str, readme_text: str) -> bool:
    """Commit README.md + a correct .gitattributes via **git** (not
    HubApi.upload_file).

    Why git: ModelScope's ``upload_file`` auto-adds ``<path> filter=lfs``
    for every file, so README.md becomes an LFS object the model-card
    viewer renders as a raw ``version https://git-lfs.github.com/…``
    pointer.  A git commit honours our .gitattributes (README → text),
    so the card renders.  The SDK ``Repository`` clones with the cached
    session auth — no separate git token needed.  We touch only the two
    text files, so the push needs no git-lfs (images stay as they were
    uploaded via HubApi)."""
    import subprocess
    import tempfile
    try:
        from modelscope.hub.repository import Repository
    except Exception as exc:  # noqa: BLE001
        print(f"[modelscope-sync] Repository unavailable: {_redact(exc)}",
              file=sys.stderr)
        return False
    tmp = Path(tempfile.mkdtemp(prefix="ms_sync_")) / "repo"
    # Prefer a shallow token clone (survives the RPC drop a full SDK clone
    # hits on this large LFS repo); fall back to the SDK Repository clone.
    if not _shallow_clone(repo_id, branch, tmp):
        try:
            Repository(model_dir=str(tmp), clone_from=repo_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[modelscope-sync] git clone failed: {_redact(exc)}",
                  file=sys.stderr)
            return False
    cfg = [("filter.lfs.required", "false"), ("filter.lfs.smudge", "cat"),
           ("filter.lfs.clean", "cat"), ("user.email", "noreply@anthropic.com"),
           ("user.name", "pixcull-sync"),
           # v2.67.1 — ModelScope's remote advertises LFS locking, and
           # git-lfs aborts the push rather than guess.  We touch only
           # two text files and hold no locks, so verification has
           # nothing to verify.
           ("lfs.locksverify", "false")]
    for k, v in cfg:
        subprocess.run(["git", "-C", str(tmp), "config", k, v], check=False)
    (tmp / "README.md").write_text(readme_text, encoding="utf-8")
    (tmp / ".gitattributes").write_text(_GITATTRIBUTES_TEXT, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp), "add", ".gitattributes",
                    "README.md"], check=True)
    c = subprocess.run(["git", "-C", str(tmp), "commit", "-m",
                        "sync: README + .gitattributes as text (de-LFS card)"],
                       capture_output=True, text=True)
    if c.returncode != 0:
        # v2.67.1 — ask git the question instead of reading its prose.
        # "the card is already current" is a normal, successful outcome
        # and was being reported as a failed sync; matching the English
        # sentence "nothing to commit" also fails under any other
        # locale, and it did: this branch printed `commit failed:` with
        # an empty string after it, which is a diagnostic that diagnoses
        # nothing.
        clean = subprocess.run(["git", "-C", str(tmp), "diff", "--cached",
                                "--quiet"])
        if clean.returncode == 0:
            print("[modelscope-sync] README already current", file=sys.stderr)
            return True
        detail = _redact((c.stdout + c.stderr).strip()) or f"rc={c.returncode}"
        print(f"[modelscope-sync] commit failed: {detail[:300]}",
              file=sys.stderr)
        return False
    pr = subprocess.run(["git", "-C", str(tmp), "push", "origin",
                         f"HEAD:{branch}"], capture_output=True, text=True)
    if pr.returncode != 0:
        print(f"[modelscope-sync] git push failed: {_redact(pr.stderr)[:200]}",
              file=sys.stderr)
        return False
    print("[modelscope-sync] ✓ README pushed as text via git (renders)",
          file=sys.stderr)
    return True


# A ModelScope commit takes a repo-wide lock, so two syncs running at
# once (e.g. a manual `make modelscope-sync` while the push-triggered CI
# workflow is doing the same thing) make each other fail with
# HTTP 429 "commit lock busy".  That is transient by definition — wait
# and it succeeds — so it is worth retrying rather than reporting.
_TRANSIENT_MARKERS = ("commit lock busy", "429", "too many requests",
                      "500", "502", "503", "504", "timeout", "timed out")


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _upload_referenced_assets(api, repo_id: str, branch: str,
                              readme_text: str,
                              *, attempts: int = 4) -> tuple[int, int, list]:
    """Upload every ``docs/...(png|gif|svg|jpg|jpeg|webp)`` the README
    references so the relative paths resolve on ModelScope itself.

    Returns ``(uploaded, expected, failed_paths)``.  The caller must treat
    a short count as a FAILURE: this used to return only a count that
    nobody compared against ``expected``, so a run that hosted 20 of 28
    assets still printed "✓ synced" and exited 0 — the README then
    referenced eight images that were not on the server.
    """
    paths = sorted(set(re.findall(
        r"docs/[A-Za-z0-9/_.-]+\.(?:png|gif|svg|jpe?g|webp)", readme_text)))
    expected, n, failed = 0, 0, []
    for rel in paths:
        local = REPO_ROOT / rel
        if not local.exists():
            # Not counted against the total: a missing local file is a
            # README bug, reported separately from an upload failure.
            print(f"[modelscope-sync]   skip (missing): {rel}", file=sys.stderr)
            continue
        expected += 1
        for attempt in range(1, attempts + 1):
            try:
                api.upload_file(
                    path_or_fileobj=str(local), path_in_repo=rel,
                    repo_id=repo_id, repo_type="model", revision=branch,
                    commit_message=f"host {rel}", disable_tqdm=True)
                n += 1
                break
            except Exception as exc:  # noqa: BLE001
                if attempt < attempts and _is_transient(exc):
                    delay = 2 ** attempt          # 2s, 4s, 8s
                    print(f"[modelscope-sync]   {rel}: {type(exc).__name__} "
                          f"(transient) — retry {attempt}/{attempts - 1} "
                          f"in {delay}s", file=sys.stderr)
                    time.sleep(delay)
                    continue
                # v2.67.1 — an upload that errors is not the same as an
                # asset that is missing.  Re-uploading a blob the server
                # already holds can 400 on the LFS batch endpoint, and
                # the old code counted that as a failed sync: 30 assets
                # all present and current, reported as "hosted 0/30",
                # exit 1.  A red sync that is actually fine is worse
                # than no check — it teaches you to ignore red syncs.
                #
                # The invariant was never "upload returned 200"; it is
                # "the README's images can be fetched from the server".
                # Check that instead.  It is also strictly stronger: a
                # 200 from upload never proved retrievability either.
                if _asset_is_current(repo_id, branch, rel, local):
                    print(f"[modelscope-sync]   {rel}: upload rejected but "
                          f"the remote copy is current — counted",
                          file=sys.stderr)
                    n += 1
                    break
                print(f"[modelscope-sync]   asset upload failed {rel}: {_redact(exc)}",
                      file=sys.stderr)
                failed.append(rel)
                break
    mark = "✓" if n == expected else "✗"
    print(f"[modelscope-sync] {mark} hosted {n}/{expected} referenced assets",
          file=sys.stderr)
    return n, expected, failed


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
        help="(legacy alias; default is already self-contained)"
    )
    p.add_argument(
        "--github-links", action="store_true",
        help="Rewrite docs/* image paths to raw.githubusercontent.com "
             "instead of hosting them on ModelScope.  Default (off) is "
             "SELF-CONTAINED: keep relative paths + upload the referenced "
             "assets to ModelScope + fix .gitattributes so README renders "
             "as text (not an LFS pointer)."
    )
    args = p.parse_args(argv)

    # Step 1 — read the source README.
    if not args.readme_source.exists():
        print(f"[modelscope-sync] not found: {args.readme_source}",
              file=sys.stderr)
        return 2
    original = args.readme_source.read_text(encoding="utf-8")

    # Step 2 — image paths.  Default is SELF-CONTAINED: keep relative
    # `docs/...` paths and host the assets on ModelScope (Step 6).  Only
    # rewrite to GitHub raw URLs when --github-links is explicitly asked.
    if args.github_links:
        rewritten = _rewrite_relative_paths(original, GH_RAW_BASE)
        n_rewrites = rewritten.count(GH_RAW_BASE) - original.count(GH_RAW_BASE)
        print(f"[modelscope-sync] {n_rewrites} paths → raw.githubusercontent",
              file=sys.stderr)
    else:
        rewritten = original
        print("[modelscope-sync] self-contained mode: relative paths kept, "
              "assets hosted on ModelScope", file=sys.stderr)

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
            # v2.30 — the modelscope SDK renamed the login kwarg: newer
            # releases (the version CI's bare `pip install modelscope`
            # resolves) take the token positionally and raise TypeError
            # on `access_token=`; older ones (the local venv) require the
            # keyword. Try new-style first, fall back to legacy.
            try:
                api.login(token)
            except TypeError:
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
    if args.github_links:
        # Legacy path — single README with raw.githubusercontent image
        # links, pushed via upload_file (renders as an LFS pointer on
        # ModelScope; kept only for explicit opt-in).
        try:
            commit = api.upload_file(
                path_or_fileobj=rewritten.encode("utf-8"),
                path_in_repo="README.md", repo_id=args.repo_id,
                repo_type="model", commit_message=args.commit_message,
                revision=args.branch, disable_tqdm=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[modelscope-sync] upload failed: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(f"[modelscope-sync] ✓ uploaded README (github-links mode) to "
              f"{args.repo_id}#{args.branch}", file=sys.stderr)
        if hasattr(commit, "commit_url") and commit.commit_url:
            print(f"[modelscope-sync] view at: {commit.commit_url}",
                  file=sys.stderr)
        return 0

    # Self-contained (default):
    #   1. host the referenced docs/** assets via HubApi (images → LFS,
    #      which upload_file handles correctly), then
    #   2. push README.md + a correct .gitattributes via GIT so the
    #      model card renders as text (upload_file would re-LFS it).
    n_up, n_exp, failed = _upload_referenced_assets(
        api, args.repo_id, args.branch, rewritten)
    if not _git_push_readme(args.repo_id, args.branch, rewritten):
        print("[modelscope-sync] ✗ README git push failed — card may show "
              "an LFS pointer; check git/Repository auth", file=sys.stderr)
        return 1
    if failed:
        # Exit non-zero: the README is live but points at images that
        # are not.  Printing "✓ synced" here (as this did until v2.37)
        # made a half-published model card look finished.
        print(f"[modelscope-sync] ✗ {len(failed)} asset(s) still missing "
              f"after retries — the model card references images that are "
              f"NOT hosted:", file=sys.stderr)
        for rel in failed:
            print(f"[modelscope-sync]     {rel}", file=sys.stderr)
        print("[modelscope-sync]   re-run once nothing else is syncing "
              "(a push also triggers the CI sync workflow, and the two "
              "fight over the same commit lock).", file=sys.stderr)
        return 1
    print(f"[modelscope-sync] ✓ synced {args.repo_id}#{args.branch} "
          f"({n_up}/{n_exp} assets hosted; README renders as text)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
