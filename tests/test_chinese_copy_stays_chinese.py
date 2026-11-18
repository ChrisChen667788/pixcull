"""v3.102 — the Chinese workspace copy stays Chinese, and says one thing.

Reviewing PR #7 (the English pages) found `workspace.tuned_badge` in
`zh_CN.json` reading `再标 {n} photos`, where it had said `张`, and the
fallback in `12-tuned-badge.js` carrying the same mixed text. Translating a
catalogue in place is how an English word lands in the Chinese one, and
nothing compared them.

Two checks. Chinese copy may use the product's own English terms (keep,
rubric, lightbox…) but no other English word that its English counterpart
also uses. And a JavaScript fallback — what the page shows before or
without the string table — must be the same text as `zh_CN.json`, since it
is the same string kept twice; the compare view's fallback still said the
other photo is culled, from before comparison took more than two.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALE = ROOT / "pixcull" / "locale"
SRC = ROOT / "pixcull" / "report" / "templates" / "src"

#: English the Chinese UI uses on purpose: decisions, file and feature
#: names a photographer meets in other tools. A new word belongs here only
#: if it is a term, not a translation someone forgot to make.
PRODUCT_TERMS = {
    "keep", "maybe", "cull", "grid", "lightbox", "tether", "session",
    "sidecar", "scores", "score", "standalone", "rubric", "rescorer",
    "stddev", "active", "learning",
}


def _catalogue(name: str) -> dict:
    return json.loads((LOCALE / name).read_text(encoding="utf-8"))


def _stray_english(zh_value: str, en_value: str) -> list[str]:
    bare = re.sub(r"\{[^}]*\}", "", zh_value)          # placeholders are code
    words = re.findall(r"\b[a-z]{4,}\b", bare)
    return [w for w in words
            if w in en_value.lower() and w not in PRODUCT_TERMS]


def test_chinese_strings_carry_no_untranslated_english():
    zh, en = _catalogue("zh_CN.json"), _catalogue("en_US.json")
    stray = {k: _stray_english(v, en.get(k, ""))
             for k, v in zh.items()
             if isinstance(v, str) and re.search(r"[一-鿿]", v)}
    stray = {k: w for k, w in stray.items() if w}
    assert not stray, f"English left in zh_CN.json: {stray}"


def test_the_stray_check_sees_the_case_that_shipped():
    assert _stray_english("再标 {n} photos,新批次就会自动校准",
                          "{n} more photos and the next batch") == ["photos"]
    assert _stray_english("再标 {n} 张", "{n} more photos") == []


_LITERAL = r"""(["'`])((?:(?!\1)[^\\]|\\.)*)\1"""
_CALL = re.compile(r"""\b_tf?\(\s*["']([\w.]+)["']\s*,\s*""")


def _fallback_at(src: str, pos: int) -> str | None:
    """The fallback string starting at ``pos``: one literal, or several
    joined with ``+``. None when it is built from anything else."""
    parts = []
    while True:
        m = re.compile(_LITERAL, re.S).match(src, pos)
        if not m:
            return None
        parts.append(m.group(2))
        pos = m.end()
        nxt = re.compile(r"\s*\+\s*").match(src, pos)
        if not nxt or not re.compile(_LITERAL).match(src, nxt.end()):
            break
        pos = nxt.end()
    text = "".join(parts)
    return (text.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'"))


def _fallbacks() -> list[tuple[str, str, str]]:
    found = []
    for path in [SRC / "results.js", *sorted((SRC / "modules").glob("*.js"))]:
        src = path.read_text(encoding="utf-8")
        for call in _CALL.finditer(src):
            text = _fallback_at(src, call.end())
            if text is not None:
                found.append((path.name, call.group(1), text))
    return found


def test_a_fallback_says_what_zh_cn_says():
    zh = _catalogue("zh_CN.json")
    pairs = [(f, k, t) for f, k, t in _fallbacks() if k in zh]
    assert len(pairs) >= 50, f"only {len(pairs)} fallbacks found; the scan broke"
    differ = [(f, k) for f, k, t in pairs if t != zh[k]]
    assert not differ, f"fallback and zh_CN.json disagree: {differ}"


def test_concatenated_fallbacks_are_read_whole():
    src = '_t("health.note", "前半句。"\n           + "后半句。")'
    call = _CALL.search(src)
    assert _fallback_at(src, call.end()) == "前半句。后半句。"
