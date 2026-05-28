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
