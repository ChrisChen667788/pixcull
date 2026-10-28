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


def load_page_catalogue(name: str, lang: str) -> dict[str, str]:
    """Return the source-to-translation map for one page and locale.

    Only translations that exist are returned. Chinese, and any locale
    without a catalogue, gets an empty map and therefore the original
    page.

    The mtime is part of the cache key so a translator editing a JSON
    file sees the change on the next request, without restarting the
    server.
    """
    norm = _normalize_lang(lang)
    if norm == DEFAULT_LOCALE:
        return {}
    path = _CATALOGUE_DIR / norm / f"{page_name(name)}.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return _load_catalogue_cached(str(path), stamp)


@lru_cache(maxsize=64)
def _load_catalogue_cached(path_str: str, _stamp: int) -> dict[str, str]:
    path = Path(path_str)
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


# Pipeline progress lines are built in pixcull/pipeline/orchestrator.py and
# reach the browser through /status/<run>, so they are not part of any page
# template. Translate the ones a photographer sees while a scan runs.
_PROGRESS_EN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^找到 (\d+) 张图,开始分析…$"),
     r"Found \1 photos, starting analysis..."),
    (re.compile(r"^已收到 (\d+) 张图,正在排队…$"),
     r"Received \1 photos, queued..."),
    (re.compile(r"^已索引 (\d+) 张图,准备分析[（(]原图不复制[）)]…$"),
     r"Indexed \1 photos, ready to analyse (originals are not copied)..."),
    (re.compile(r"^跨照片人脸聚类…$"), "Clustering faces across photos..."),
    (re.compile(r"^按 GPS 地点聚类…$"), "Clustering by GPS location..."),
    (re.compile(r"^聚类与连拍检测…$"), "Clustering and burst detection..."),
    (re.compile(r"^评分与决策…$"), "Scoring and deciding..."),
    (re.compile(r"^连拍峰值排名…$"), "Ranking burst peaks..."),
    (re.compile(r"^rubric 多维评分…$"), "Rubric scoring..."),
    (re.compile(r"^VLM \((\w+)\) 评分中…$"), r"VLM (\1) scoring..."),
    (re.compile(r"^Meta judge \((\w+)\) 并发综合中…$"),
     r"Meta judge (\1) combining..."),
    (re.compile(r"^完成$"), "Done"),
    (re.compile(r"^分析失败: (.*)$"), r"Analysis failed: \1"),
    (re.compile(r"^没有训练数据 — (.*)$"), r"No training data: \1"),
    (re.compile(r"^过滤后无训练数据,(.*)$"), r"No training data after filtering, \1"),
    (re.compile(r"^训练完成 (.*)$"), r"Training finished \1"),
    (re.compile(r"^训练失败: (.*)$"), r"Training failed: \1"),
)


# Folder and upload errors are raised by the server and printed straight
# into the page by its JavaScript, so they bypass the template catalogue.
_RUNTIME_EN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^不是文件夹: (.*)$"), r"Not a folder: \1"),
    (re.compile(r"^路径不存在: (.*)$"), r"Path does not exist: \1"),
    (re.compile(r"^没有权限读取: (.*)$"), r"No permission to read: \1"),
    (re.compile(r"^路径解析失败: (.*)$"), r"Could not resolve the path: \1"),
    (re.compile(r"^参数错误: (.*)$"), r"Bad parameter: \1"),
    (re.compile(r"^上传里没有可用图片。(.*)$"), r"No usable images in the upload. \1"),
    (re.compile(r"^缺少 token 字段$"), "Missing token field"),
    (re.compile(r"^需要 folder 字段:?(.*)$"), r"folder is required:\1"),
    (re.compile(r"^已有训练任务在跑,等完成再来$"),
     "A training job is already running; wait for it to finish"),
    (re.compile(r"^license token 验证失败 — (.*)$"),
     r"License token check failed: \1"),

    (re.compile(r"^上传失败: (.*)$"), r"Upload failed: \1"),
)


def translate_message(message: str, lang: str) -> str:
    """English for a server-generated runtime line, or the line unchanged.

    Provisional: the pipeline and the upload handlers still send prose,
    so this is the only place that can translate it. The replacement is
    for the server to send a message code plus parameters and for the
    client to render it; this function then goes away.

    Covers both pipeline progress (``orchestrator.py``) and the folder
    and upload errors the pages print into the DOM.
    """
    if _normalize_lang(lang) != "en_US" or not message:
        return message
    found = re.match(
        r"^在 (.*?) 下没找到可分析的图片"
        r"(?:[（(]支持 (.*?)[）)])?$", message)
    if found:
        formats = found.group(2) or "jpg/png/cr3/cr2/nef/arw/dng/tif"
        return (f"No analysable images under {found.group(1)}. "
                f"Supported: {formats}")
    for pattern, replacement in _PROGRESS_EN + _RUNTIME_EN:
        if pattern.match(message):
            return pattern.sub(replacement, message, count=1)
    return message


def translate_progress_message(message: str, lang: str) -> str:
    """Kept for callers that only deal with pipeline progress."""
    return translate_message(message, lang)


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
