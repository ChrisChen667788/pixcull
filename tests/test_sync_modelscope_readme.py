"""Tests for scripts/sync_modelscope_readme.py.

We can't actually test the upload (would need real ModelScope creds
+ a test repo).  We CAN test the pure-function path rewrite — the
piece most likely to silently break a sync.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load():
    p = Path(__file__).resolve().parent.parent / "scripts" / "sync_modelscope_readme.py"
    spec = importlib.util.spec_from_file_location("sync_modelscope_readme", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE = "https://raw.githubusercontent.com/ChrisChen667788/pixcull/main"


# ---------------------------------------------------------------------------
# Path rewrite — Markdown image syntax
# ---------------------------------------------------------------------------


def test_rewrites_markdown_image_with_relative_docs_path():
    rw = _load()
    md = "![alt](docs/screenshots/01.png)"
    out = rw._rewrite_relative_paths(md, BASE)
    assert out == f"![alt]({BASE}/docs/screenshots/01.png)"


def test_rewrites_with_brand_subpath():
    rw = _load()
    md = "![hero](docs/brand/mark.svg)"
    out = rw._rewrite_relative_paths(md, BASE)
    assert out == f"![hero]({BASE}/docs/brand/mark.svg)"


def test_handles_empty_alt_text():
    rw = _load()
    md = "![](docs/screenshots/x.png)"
    out = rw._rewrite_relative_paths(md, BASE)
    assert out == f"![]({BASE}/docs/screenshots/x.png)"


def test_handles_mixed_content():
    """Real README has prose + many images; all images rewritten,
    prose untouched."""
    rw = _load()
    md = """# Title

Some prose here.

![A](docs/screenshots/01.png)
Some words.
![B](docs/screenshots/02.png)

End."""
    out = rw._rewrite_relative_paths(md, BASE)
    assert out.count(BASE) == 2
    assert "Some prose here." in out
    assert "End." in out


def test_does_not_rewrite_absolute_urls():
    """The hero SVGs in the modelscope README use absolute URLs;
    those must stay as-is."""
    rw = _load()
    md = f"![hero]({BASE}/docs/brand/lockup.svg)"
    out = rw._rewrite_relative_paths(md, BASE)
    # Stays untouched — no double-rewrite
    assert out == md
    # And no double-prefix
    assert out.count(BASE) == 1


def test_does_not_rewrite_unrelated_relative_links():
    """Relative paths that don't start with 'docs/' are out of scope
    (e.g. links to other files / anchors)."""
    rw = _load()
    md = "![local](./assets/img.png)"
    out = rw._rewrite_relative_paths(md, BASE)
    assert out == md   # untouched


# ---------------------------------------------------------------------------
# Path rewrite — HTML <img> tags
# ---------------------------------------------------------------------------


def test_rewrites_html_img_tag():
    rw = _load()
    html = '<img src="docs/brand/mark.svg" alt="logo" />'
    out = rw._rewrite_relative_paths(html, BASE)
    assert out == f'<img src="{BASE}/docs/brand/mark.svg" alt="logo" />'


def test_rewrites_html_img_with_multiple_attrs():
    rw = _load()
    html = '<img width="60%" src="docs/screenshots/01.png" alt="grid" />'
    out = rw._rewrite_relative_paths(html, BASE)
    assert f'src="{BASE}/docs/screenshots/01.png"' in out
    # other attrs preserved
    assert 'width="60%"' in out
    assert 'alt="grid"' in out


def test_does_not_rewrite_absolute_html_src():
    rw = _load()
    html = f'<img src="{BASE}/docs/brand/lockup.svg" />'
    out = rw._rewrite_relative_paths(html, BASE)
    assert out == html


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def test_token_explicit_arg_wins(monkeypatch):
    rw = _load()
    monkeypatch.setenv("MODELSCOPE_API_TOKEN", "from-env-XYZ")
    assert rw._resolve_token("explicit-ABC") == "explicit-ABC"


def test_token_env_used_when_no_arg(monkeypatch):
    rw = _load()
    monkeypatch.setenv("MODELSCOPE_API_TOKEN", "from-env-ABC")
    assert rw._resolve_token(None) == "from-env-ABC"


def test_token_strips_whitespace_in_env(monkeypatch):
    rw = _load()
    monkeypatch.setenv("MODELSCOPE_API_TOKEN", "  padded  ")
    assert rw._resolve_token(None) == "padded"


def test_token_returns_empty_string_when_saved_creds_exist(monkeypatch, tmp_path):
    """When ~/.modelscope/credentials exists but no env, return ""
    (signal: SDK will read saved creds on next HubApi() call)."""
    rw = _load()
    monkeypatch.delenv("MODELSCOPE_API_TOKEN", raising=False)
    # Sandbox HOME so we don't read the real creds
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".modelscope").mkdir()
    (tmp_path / ".modelscope" / "credentials").write_text("fake")
    assert rw._resolve_token(None) == ""


def test_token_returns_none_when_nothing_anywhere(monkeypatch, tmp_path):
    rw = _load()
    monkeypatch.delenv("MODELSCOPE_API_TOKEN", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    # tmp_path has no .modelscope dir → no creds
    assert rw._resolve_token(None) is None


# ---------------------------------------------------------------------------
# Sanity — the actual modelscope/README.md file rewrites cleanly
# ---------------------------------------------------------------------------


def test_real_modelscope_readme_rewrites():
    """End-to-end: read the real source file, rewrite it, check
    the count matches expectations."""
    rw = _load()
    src_path = Path(__file__).resolve().parent.parent / "modelscope" / "README.md"
    if not src_path.exists():
        pytest.skip("modelscope/README.md not in this checkout")
    src = src_path.read_text(encoding="utf-8")
    out = rw._rewrite_relative_paths(src, BASE)
    # At least one rewrite happened (the README references several
    # docs/screenshots/* paths)
    n_added = out.count(BASE) - src.count(BASE)
    assert n_added > 0, "no relative paths rewritten — schema drift?"
    # Output is strictly longer (added URL prefix to N paths)
    assert len(out) > len(src)


# ---------------------------------------------------------------------------
# v2.67.1 — the release tooling's own failures
# ---------------------------------------------------------------------------


def test_the_token_never_reaches_the_terminal():
    """A failed push printed git's error, and git names the remote in it.

    The remote is `https://oauth2:<token>@…` — that is how the shallow
    clone authenticates — so a routine push failure put a live
    ModelScope credential into the terminal, the CI log, and the
    scrollback of whoever ran `make modelscope-sync`.  Found the only
    way these things are found: it happened.
    """
    m = _load()
    tok = "vz-" + "K" * 17
    m._SECRETS.add(tok)
    try:
        msg = (f'Locking support detected on remote "origin". Consider '
               f'enabling it with:\n  $ git config '
               f'lfs.https://oauth2:{tok}@www.modelscope.cn/haozi667788/'
               f'pixcull.git/info/lfs.locksverify true')
        out = m._redact(msg)
        assert tok not in out, "the token survived redaction"
        assert "locksverify" in out, (
            "redaction ate the message; the error still has to be readable")

        # Not only the secrets we happen to know about.  Built at
        # runtime, per this repo's rule for anything key-shaped: a
        # literal here reads as an address to the hygiene lint, and to
        # any secret scanner pointed at the tree.
        other = "hunter" + "2"
        assert other not in m._redact(
            f"fatal: https://oauth2:{other}@www.modelscope.cn/x.git")
    finally:
        m._SECRETS.discard(tok)


def test_the_push_does_not_stall_on_lfs_lock_verification():
    """ModelScope's remote advertises LFS locking; git-lfs then aborts
    the push rather than guess, and the README never lands."""
    import inspect

    m = _load()
    src = inspect.getsource(m._git_push_readme)
    assert '"lfs.locksverify", "false"' in src, (
        "nothing tells git-lfs whether to verify locks, so the push that "
        "carries the model card aborts")


def test_an_upload_rejection_is_not_a_missing_asset(monkeypatch, tmp_path):
    """30 assets present and current, reported as "hosted 0/30", exit 1.

    Re-uploading a blob the server already holds can 400 on the LFS
    batch endpoint.  The old code read that as a failed sync.  A red
    sync that is actually fine is worse than no check at all, because it
    is indistinguishable from the real thing it was built to catch —
    which is a README referencing images nobody hosted.
    """
    m = _load()
    readme = "![a](docs/screenshots/24-review-sheet.png)\n"

    class _Api:
        def upload_file(self, **kw):
            raise RuntimeError("400 Client Error: Bad Request … lfs/objects/batch")

    monkeypatch.setattr(m, "_is_transient", lambda exc: False)

    # Present on the server → counted, and the sync is not failed.
    monkeypatch.setattr(m, "_asset_is_current", lambda *a, **k: True)
    n, expected, failed = m._upload_referenced_assets(
        _Api(), "haozi667788/pixcull", "master", readme, attempts=1)
    assert (n, expected, failed) == (1, 1, []), (
        "an asset that is demonstrably on the server was reported missing")

    # Absent from the server → still a failure.  The strictness this
    # function was written for has to survive the fix.
    monkeypatch.setattr(m, "_asset_is_current", lambda *a, **k: False)
    n, expected, failed = m._upload_referenced_assets(
        _Api(), "haozi667788/pixcull", "master", readme, attempts=1)
    assert n == 0 and failed == ["docs/screenshots/24-review-sheet.png"], (
        "a genuinely unhosted asset now passes — the fix removed the check "
        "instead of correcting it")


def test_an_already_current_card_is_not_a_failed_sync():
    """`commit failed:` followed by an empty string.

    git says "nothing to commit" in English, on stdout, and only when it
    feels like it; the branch that matched that sentence missed, so a
    sync whose only remaining work was already done exited 1 with a
    diagnostic that diagnosed nothing.  Ask git the question — is
    anything staged — rather than reading its prose, and never print an
    empty reason.
    """
    import inspect

    m = _load()
    src = inspect.getsource(m._git_push_readme)
    assert '"diff", "--cached",' in src and '"--quiet"' in src, (
        "the clean-tree case is still decided by string-matching git's "
        "English output")
    assert 'or f"rc={c.returncode}"' in src, (
        "the failure branch can still print an empty reason")
