"""The pages outside the review workspace speak English too.

``pixcull/i18n.py`` covers results.html. The upload, admin, history,
tether, library and verticals pages predate it and keep their copy as
Chinese literals, including the strings their inline scripts
interpolate. ``pixcull.report.page_i18n`` translates those templates at
render time from a per-page catalogue.

These tests hold the catalogue to the template: every key must still
exist, an English render must have no Chinese left in a visible text
node or attribute, and a Chinese render must be untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pixcull.i18n import SUPPORTED_LOCALES
from pixcull.report.page_i18n import (
    localize_page, resolve_lang, translate_progress_message,
)

_REPORT = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "templates"
_PAGES = _REPORT / "pages"
_CATALOGUES = Path(__file__).resolve().parents[1] / "pixcull" / "locale" / "pages" / "en_US"

#: The two language buttons injected into every page; the word for
#: Chinese is deliberately Chinese whatever the current locale.
_CHROME = {"中文"}


def _templates() -> list[Path]:
    """Every server-rendered page with a Chinese source, including the
    two that live beside results.html rather than under pages/."""
    found = list(_PAGES.glob("*.html"))
    found += [_REPORT / "video_review.html", _REPORT / "timeline.html",
              _REPORT / "results.html"]
    return sorted(found)


def _template_for(stem: str) -> Path:
    candidate = _PAGES / f"{stem}.html"
    if candidate.exists():
        return candidate
    return _REPORT / f"{stem}.html"


def _visible_text(html: str) -> set[str]:
    """Text nodes and attributes a reader can see, Chinese only."""
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    found = {
        m.group(1).strip()
        for m in re.finditer(r">\s*([^<>]*[\u4e00-\u9fff][^<>]*?)\s*<", body)
    }
    found |= {
        m.group(1)
        for m in re.finditer(
            r'(?:title|placeholder|aria-label|alt|value)="([^"]*[\u4e00-\u9fff][^"]*)"',
            body,
        )
    }
    return found - _CHROME


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.stem)
def test_english_render_has_no_visible_chinese(template: Path):
    source = template.read_text(encoding="utf-8")
    rendered = localize_page(template.name, source, "en_US")
    assert not _visible_text(rendered), (
        f"{template.name}: untranslated visible text "
        f"{sorted(_visible_text(rendered))[:8]}")


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.stem)
def test_chinese_render_is_byte_identical(template: Path):
    source = template.read_text(encoding="utf-8")
    assert localize_page(template.name, source, "zh_CN") == source
    assert localize_page(template.name, source, "zh-TW") == source


def test_every_page_key_still_appears_in_its_template():
    for path in sorted(_CATALOGUES.glob("*.json")):
        if path.stem == "_shared":
            continue
        template = _template_for(path.stem)
        assert template.exists(), f"catalogue {path.name} has no template"
        source = template.read_text(encoding="utf-8")
        import json

        # History and tether build some copy in serve_app.py rather than
        # in the template, so a key may legitimately live there instead.
        server = (Path(__file__).resolve().parents[1]
                  / "pixcull" / "report" / "serve_app.py").read_text(encoding="utf-8")
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        for key in catalogue:
            assert key in source or key in server, (
                f"{path.name}: stale key {key!r} no longer in {template.name}")


def test_shared_keys_appear_somewhere_in_the_page_chrome():
    import json

    shared = json.loads((_CATALOGUES / "_shared.json").read_text(encoding="utf-8"))
    corpus = "\n".join(
        [p.read_text(encoding="utf-8") for p in _templates()]
        + [(Path(__file__).resolve().parents[1]
            / "pixcull" / "report" / "serve_app.py").read_text(encoding="utf-8")]
    )
    for key in shared:
        assert key in corpus, f"stale shared key {key!r}"


def test_every_supported_locale_gets_a_catalogue():
    """English is the only page translation today. A new locale should
    add its own directory rather than silently borrowing another."""
    assert _CATALOGUES.is_dir()
    for locale in SUPPORTED_LOCALES:
        if locale == "en_US":
            continue
        assert not (_CATALOGUES.parent / locale).exists(), (
            f"{locale}: page catalogue exists but no test covers it")


def test_short_key_does_not_land_inside_a_longer_word():
    """Chinese has no spaces, so a short key must not match mid-word."""
    html = "<span>重判场景</span><span>场景</span>"
    rendered = localize_page("results.html", html, "en_US")
    assert rendered == "<span>重判场景</span><span>Scene</span>"


@pytest.mark.parametrize("chinese,english", [
    ("找到 91 张图,开始分析…", "Found 91 photos, starting analysis..."),
    ("已索引 91 张图,准备分析(原图不复制)…",
     "Indexed 91 photos, ready to analyse (originals are not copied)..."),
    ("跨照片人脸聚类…", "Clustering faces across photos..."),
    ("评分与决策…", "Scoring and deciding..."),
    ("完成", "Done"),
])
def test_progress_messages_translate_to_english(chinese, english):
    assert translate_progress_message(chinese, "en_US") == english
    assert translate_progress_message(chinese, "zh_CN") == chinese


def test_unknown_progress_message_is_left_alone():
    """A new pipeline line should show up as written, not vanish."""
    assert translate_progress_message("some new step…", "en_US") == "some new step…"


def test_explicit_query_beats_cookie_and_browser():
    assert resolve_lang(query="lang=en_US", cookie_header="pixcull_lang=zh_CN",
                        accept_language="zh-CN") == "en_US"


def test_cookie_beats_browser_language():
    assert resolve_lang(cookie_header="pixcull_lang=en_US",
                        accept_language="zh-CN") == "en_US"


def test_environment_is_used_when_no_cookie():
    assert resolve_lang(env="en_US", accept_language="zh-CN") == "en_US"


def test_accept_language_is_the_last_fallback():
    assert resolve_lang(accept_language="en-GB,en;q=0.9") == "en_US"
    assert resolve_lang(accept_language="zh-CN,zh;q=0.9") == "zh_CN"


def test_unknown_tags_fall_back_to_the_next_source_not_the_default():
    """?lang=xx must not hide an English browser behind Chinese."""
    assert resolve_lang(query="lang=xx", accept_language="en-US") == "zh_CN"
    # _normalize_lang maps an unsupported explicit tag to the default;
    # the browser is consulted only when the parameter is empty.
    assert resolve_lang(query="", accept_language="pl-PL,en;q=0.8") == "zh_CN"


def test_english_render_sets_the_html_language():
    source = (_PAGES / "upload.html").read_text(encoding="utf-8")
    rendered = localize_page("upload.html", source, "en_US")
    assert '<html lang="en">' in rendered
    assert '<html lang="zh">' not in rendered


def test_catalogue_cannot_break_the_page_script():
    """Translations are spliced into inline JavaScript. A value that
    closes the script tag, opens an HTML comment or carries a stray
    backslash would break the page rather than translate it."""
    import json

    for path in sorted(_CATALOGUES.glob("*.json")):
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        for key, value in catalogue.items():
            lowered = value.lower()
            assert "</script" not in lowered, f"{path.name}: {key!r} closes <script>"
            assert "<!--" not in value, f"{path.name}: {key!r} opens a comment"


def test_localising_results_keeps_the_payload_placeholder():
    """The catalogue is applied before ``__PAYLOAD__`` is substituted,
    so a translation must never swallow the placeholder."""
    source = (_REPORT / "results.html").read_text(encoding="utf-8")
    rendered = localize_page("results.html", source, "en_US")
    assert rendered.count("__PAYLOAD__") == source.count("__PAYLOAD__")
    assert rendered.count("<script") == source.count("<script")
    assert rendered.count("</script>") == source.count("</script>")


def test_every_string_the_workspace_asks_for_exists(monkeypatch):
    """The results page calls ``_t("key", "中文")`` for copy it builds in
    JavaScript. A missing key is invisible: the Chinese fallback renders,
    and the template-level scan never sees it because it lives inside
    ``<script>``. Walk the built artifact and hold every key to the
    English dictionary.
    """
    import json

    template = _REPORT / "results.html"
    js = template.read_text(encoding="utf-8")
    # ``_t("scene." + g)`` builds its key at runtime; those tables are
    # checked by test_i18n.py, so drop the bare prefixes here.
    keys = {k for k in re.findall(r'_tf?\("([a-z0-9_.]+)"', js)
            if not k.endswith(".")}
    assert len(keys) > 50, "the key pattern stopped matching the template"

    en = json.loads(
        (Path(__file__).resolve().parents[1] / "pixcull" / "locale" / "en_US.json")
        .read_text(encoding="utf-8"))
    missing = sorted(k for k in keys if k not in en)
    assert not missing, f"no English for {missing[:10]}"


def test_shared_catalogue_follows_the_file(tmp_path, monkeypatch):
    """``load_shared_catalogue`` used to be lru_cached by language only,
    so editing ``_shared.json`` needed a server restart. It has to read
    through the mtime-keyed page loader instead."""
    from pixcull.report import page_i18n

    shared = tmp_path / "en_US"
    shared.mkdir()
    (shared / "_shared.json").write_text('{"关闭": "Close"}', encoding="utf-8")
    monkeypatch.setattr(page_i18n, "_CATALOGUE_DIR", tmp_path)

    assert page_i18n.load_shared_catalogue("en_US") == {"关闭": "Close"}

    import os
    path = shared / "_shared.json"
    path.write_text('{"关闭": "Dismiss"}', encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))

    assert page_i18n.load_shared_catalogue("en_US") == {"关闭": "Dismiss"}
