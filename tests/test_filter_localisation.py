"""v2.69 — the filter panel spoke to a Chinese photographer in enum values.

The decision pills read `keep` / `maybe` / `cull`. The scene chips read
`landscape`, `documentary`, `stilllife`. Both in a UI that is otherwise
Chinese, in the one panel used to navigate a 5,000-frame shoot.

Two separate causes, and the first is the interesting one::

    if (stored !== "zh_CN") {
      // The HTML is rendered server-side in zh — fetch + repaint when
      // the resolved locale isn't zh
      _applyLang(stored);
    }

**Chinese never fetched the dictionary.** The assumption held for 190 of
192 strings and failed silently for the rest: `decision.keep = 保留` sat
in zh_CN.json, unread, while the pill it belongs to rendered the English
identifier that someone had typed as its fallback. The primary audience
was the only audience that could not see the translation.

Second cause: `scene.*` and `style.*` had **zero** entries in any of the
13 locales, so there was nothing to render but the identifier.

This file turns the assumption into an invariant. A `data-i18n` fallback
in the template is not a comment; it is what a reader sees when the
dictionary is late, absent, or — as here — deliberately skipped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCALE = ROOT / "pixcull/locale"
SRC_HTML = ROOT / "pixcull/report/templates/src/results.src.html"
SRC_JS = ROOT / "pixcull/report/templates/src/results.js"

_CJK = re.compile(r"[一-鿿]")


def _is_symbolic(text: str) -> bool:
    """Pure punctuation / digits / emoji — nothing to translate."""
    return not re.search(r"[A-Za-z]", text)


def _zh() -> dict:
    return json.loads((LOCALE / "zh_CN.json").read_text(encoding="utf-8"))


def test_every_template_fallback_matches_the_chinese_string():
    """The fallback IS the Chinese UI for anyone whose dictionary is late.

    Three of them were the English enum, which is how `keep` / `maybe` /
    `cull` reached the panel and stayed there.
    """
    zh = _zh()
    html = SRC_HTML.read_text(encoding="utf-8")
    bad = []
    for m in re.finditer(r'data-i18n="([^"]+)"[^>]*>([^<]{1,40})<', html):
        key, fallback = m.group(1), m.group(2).strip()
        want = zh.get(key)
        if not want or not fallback:
            continue
        # Not byte-equality: `← 上传` and `← 上传新一批` are both fine,
        # and demanding they match would make every copy tweak a
        # two-file edit for no reader's benefit. What must hold is that
        # the fallback is CHINESE — `keep`, `maybe`, `cull` and
        # `Library` were not, and that is the whole bug.
        if not _CJK.search(fallback) and not _is_symbolic(fallback):
            bad.append(f"{key}: 模板兜底 {fallback!r} 不是中文 "
                       f"(zh_CN 有 {want!r})")
    assert not bad, (
        "a data-i18n fallback is not Chinese. The fallback is what a "
        "Chinese reader sees before — or, when the fetch is skipped, "
        "instead of — the dictionary:\n" + "\n".join(bad[:8]))


def test_chinese_is_not_special_cased_out_of_the_dictionary():
    js = SRC_JS.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith("//"))
    assert 'if (stored !== "zh_CN")' not in code, (
        "zh_CN skips the locale fetch again, so every string built by JS "
        "through _t() falls back to whatever the caller typed")


def test_scene_and_style_names_are_translated_everywhere():
    """A locale missing these renders the raw identifier."""
    zh = _zh()
    scenes = [k for k in zh if k.startswith("scene.")]
    styles = [k for k in zh if k.startswith("style.")]
    assert len(scenes) >= 12, f"only {len(scenes)} scene names translated"
    assert len(styles) >= 5, f"only {len(styles)} style names translated"
    for k in scenes + styles:
        assert _CJK.search(zh[k]), f"{k} is not Chinese: {zh[k]!r}"

    missing = {}
    for p in sorted(LOCALE.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        gap = [k for k in scenes + styles if k not in d]
        if gap:
            missing[p.name] = gap[:3]
    assert not missing, (
        f"locales without scene/style names — they render the enum: {missing}")


def test_no_chinese_string_is_silently_english():
    """Turning the fetch on for zh exposed six entries that were English.

    They had been invisible: the fast path meant zh_CN.json was never
    read, so an untranslated value there cost nothing until the day it
    started being used, and then it OVERWROTE a correct Chinese
    fallback — `主动学习` became `Active Learning` the moment the fix
    landed.
    """
    zh, en = _zh(), json.loads(
        (LOCALE / "en_US.json").read_text(encoding="utf-8"))
    same = [k for k in zh
            if k in en and zh[k] == en[k]
            and str(zh[k]).strip() and not _CJK.search(str(zh[k]))]
    assert not same, f"zh_CN entries that are still the English text: {same}"


def test_the_chips_read_the_dictionary_rather_than_the_enum():
    js = SRC_JS.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith("//"))
    for prefix in ('_t("scene." + s', '_t("style." + s'):
        assert prefix in code, f"chips are not translated: {prefix}"
    # Inside _applyLang's body, not merely somewhere after it. The first
    # version sliced on the last occurrence of the name and passed while
    # the call was deleted — `buildDynamicFilters` is also *defined*
    # later in the file, and a definition satisfied the search.
    at = code.index("async function _applyLang(")
    body = code[at:code.index("\n  }", at)]
    assert "buildDynamicFilters()" in body, (
        "the chips are built before the dictionary arrives and never "
        "rebuilt, so every scene.* string ships unreachable")


def test_unknown_is_not_presented_as_a_kind_of_photograph():
    """`unknown` is the classifier declining to answer. Sorted among real
    scenes by count, it invites filtering by it as though it described
    the picture."""
    js = SRC_JS.read_text(encoding="utf-8")
    assert "_sceneRank" in js, "scene chips are ordered by count alone"
    assert "pill-unknown" in js, "the unknown chip has no distinct treatment"
    css = (ROOT / "pixcull/report/templates/src/modules/chips.css").read_text(
        encoding="utf-8")
    assert ".pill.pill-unknown" in css, "pill-unknown is emitted but unstyled"


def test_translating_a_label_does_not_delete_its_count():
    """`el.textContent = txt` wipes every child, and the decision pills
    now carry a count element."""
    js = SRC_JS.read_text(encoding="utf-8")
    at = js.index('document.querySelectorAll("[data-i18n]")')
    block = js[at:at + 1200]
    assert "el.children.length" in block, (
        "the i18n repaint still clobbers child elements, so the counts "
        "vanish the moment the dictionary lands")
