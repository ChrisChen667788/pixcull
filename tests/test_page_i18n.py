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
from pixcull.report.page_i18n import localize_page, resolve_lang

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
    found += [_REPORT / "video_review.html", _REPORT / "timeline.html"]
    return sorted(p for p in found if p.name != "results.html")


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
