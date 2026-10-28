"""Render-time translations for the server-rendered pages.

The review workspace (``results.html``) has carried ``data-i18n`` keys
since v0.8. The pages around it — upload, admin, history, tether,
library, verticals — predate that shim and still carry their copy as
Chinese literals in HTML and inline JavaScript.

Marking every one of those nodes with a ``data-i18n`` attribute would
be a mechanical rewrite of eleven templates, and the inline scripts
would still interpolate Chinese strings at runtime. Instead each page
ships a catalogue keyed by the Chinese source text. The catalogue is
applied to the template before it reaches the browser, longest key
first, so both static markup and script literals are translated.

The Chinese source is still the source of truth: a page with no
catalogue, or a request in Chinese, is returned byte-for-byte. A
catalogue entry that no longer appears in its template fails
``tests/test_page_i18n.py``, which is what keeps the two in step.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from pixcull.i18n import DEFAULT_LOCALE, _normalize_lang

_CATALOGUE_DIR = Path(__file__).resolve().parent.parent / "locale" / "pages"


def page_name(template: str) -> str:
    """``pages/upload.html`` -> ``upload``; ``upload.html`` -> ``upload``."""
    return Path(template).stem


@lru_cache(maxsize=64)
def load_page_catalogue(name: str, lang: str) -> dict[str, str]:
    """Return the source-to-translation map for one page and locale.

    Only translations that exist are returned. Chinese, and any locale
    without a catalogue, gets an empty map and therefore the original
    page.
    """
    norm = _normalize_lang(lang)
    if norm == DEFAULT_LOCALE:
        return {}
    path = _CATALOGUE_DIR / norm / f"{page_name(name)}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()
            if isinstance(k, str) and isinstance(v, str) and k}


@lru_cache(maxsize=16)
def load_shared_catalogue(lang: str) -> dict[str, str]:
    """Strings every page uses: Close, Retry, Working, and the like."""
    return load_page_catalogue("_shared", lang)


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _replace_source(html: str, source: str, target: str) -> str:
    """Replace one catalogue key, keeping short keys out of longer words.

    Chinese has no spaces, so a short key like ``场景`` happily matches
    inside ``重判场景`` and turns the button into ``重判Scene``. Keys of
    four characters or fewer therefore only match where neither
    neighbour is a CJK character; longer keys are specific enough to
    replace anywhere.
    """
    if len(source) > 4 or not _CJK.search(source):
        return html.replace(source, target)
    pattern = re.compile(
        r"(?<![\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])"
        + re.escape(source)
        + r"(?![\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])"
    )
    return pattern.sub(lambda _m: target, html)


def localize_page(name: str, html: str, lang: str) -> str:
    """Translate a page template into ``lang``.

    Keys are applied longest-first: a catalogue may hold both a whole
    sentence and a phrase inside it, and the sentence must win.
    """
    catalogue = {**load_shared_catalogue(lang),
                 **load_page_catalogue(name, lang)}
    if not catalogue:
        return html
    for source in sorted(catalogue, key=len, reverse=True):
        html = _replace_source(html, source, catalogue[source])
    if _normalize_lang(lang) == "en_US":
        html = html.replace('<html lang="zh">', '<html lang="en">', 1)
        html = html.replace("<html lang='zh'>", "<html lang='en'>", 1)
        html = html.replace('<html lang="zh-CN">', '<html lang="en">', 1)
    return html


def resolve_lang(
    *,
    query: str = "",
    cookie_header: str = "",
    accept_language: str = "",
    env: str = "",
) -> str:
    """Pick the page language for a request.

    Order: explicit ``?lang=``, the ``pixcull_lang`` cookie, the
    ``PIXCULL_LANG`` environment variable, then ``Accept-Language``.
    """
    if query:
        value = (parse_qs(query).get("lang") or [""])[0].strip()
        if value:
            return _normalize_lang(value)
    if cookie_header:
        try:
            jar = SimpleCookie()
            jar.load(cookie_header)
            value = jar["pixcull_lang"].value if "pixcull_lang" in jar else ""
        except Exception:
            value = ""
        if value:
            return _normalize_lang(value)
    if env:
        return _normalize_lang(env)
    if accept_language:
        return _normalize_lang(accept_language)
    return DEFAULT_LOCALE
