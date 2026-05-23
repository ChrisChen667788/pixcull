"""Tests for pixcull.i18n — locale loader + key lookup."""

from __future__ import annotations

from pixcull.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    all_keys,
    load_locale,
    t,
)


def test_zh_loads_and_has_baseline_keys():
    """zh_CN is the source of truth; every baseline key must exist."""
    d = load_locale("zh_CN")
    # spot-check the chrome strings that drive the workspace bar
    assert d["workspace.crumb.results"]
    assert d["library.title"]
    assert d["buckets.title"]
    assert d["lightbox.toolbar.keep"]
    assert d["shortcuts.title"]
    # >= 30 baseline strings (charter set ~80 baseline)
    assert len(d) >= 30


def test_en_loads_and_matches_zh_keyset():
    """EN must have EXACTLY the same keys as zh_CN — no drift.

    A missing key in EN would silently fall back to the key
    name in the UI; an extra key in EN is dead weight. Either
    is a translator bug that should fail CI loudly.
    """
    zh = set(all_keys("zh_CN"))
    en = set(all_keys("en_US"))
    missing_in_en = zh - en
    extra_in_en = en - zh
    assert not missing_in_en, f"EN missing keys: {sorted(missing_in_en)}"
    assert not extra_in_en, f"EN has extra keys: {sorted(extra_in_en)}"


def test_ja_loads_and_matches_zh_keyset():
    """JA must have EXACTLY the same keys as zh_CN (same drift rule)."""
    zh = set(all_keys("zh_CN"))
    ja = set(all_keys("ja_JP"))
    missing_in_ja = zh - ja
    extra_in_ja = ja - zh
    assert not missing_in_ja, f"JA missing keys: {sorted(missing_in_ja)}"
    assert not extra_in_ja, f"JA has extra keys: {sorted(extra_in_ja)}"


def test_ja_normalisation():
    # All the BCP47 forms a Japanese browser might send
    assert t("workspace.crumb.results", "ja") == "解析結果"
    assert t("workspace.crumb.results", "ja-JP") == "解析結果"
    assert t("workspace.crumb.results", "ja_JP") == "解析結果"


def test_supported_locales_includes_three():
    # Charter v0.8-P2-1: zh + en + ja must all be supported
    assert "zh_CN" in SUPPORTED_LOCALES
    assert "en_US" in SUPPORTED_LOCALES
    assert "ja_JP" in SUPPORTED_LOCALES


def test_t_returns_translation():
    assert t("workspace.crumb.results", "zh_CN") == "分析结果"
    assert t("workspace.crumb.results", "en_US") == "Analysis results"


def test_t_returns_key_on_miss():
    # Loud-failure: untranslated keys are visible in the UI.
    assert t("nonexistent.key.foo", "zh_CN") == "nonexistent.key.foo"
    assert t("nonexistent.key.foo", "en_US") == "nonexistent.key.foo"


def test_accept_language_normalization():
    # The Accept-Language header forms we expect from real
    # browsers; all of these should normalize to one of the
    # two supported locales.
    assert t("workspace.crumb.results", "zh-CN") == "分析结果"
    assert t("workspace.crumb.results", "zh") == "分析结果"
    assert t("workspace.crumb.results", "zh_TW") == "分析结果"  # → zh_CN
    assert t("workspace.crumb.results", "zh-Hans-CN") == "分析结果"
    assert t("workspace.crumb.results", "en-US") == "Analysis results"
    assert t("workspace.crumb.results", "en") == "Analysis results"
    assert t("workspace.crumb.results", "en_GB") == "Analysis results"


def test_unknown_lang_falls_back_to_default():
    # Korean / French / etc. not supported; should fall back to zh_CN.
    # (Japanese IS supported as of v0.8-P2-1 — see test_ja_normalisation.)
    assert t("workspace.crumb.results", "ko-KR") == "分析结果"
    assert t("workspace.crumb.results", "fr") == "分析结果"
    assert t("workspace.crumb.results", "") == "分析结果"
    assert t("workspace.crumb.results", None) == "分析结果"  # type: ignore[arg-type]


def test_default_locale_constant():
    assert DEFAULT_LOCALE == "zh_CN"
    assert "zh_CN" in SUPPORTED_LOCALES
    assert "en_US" in SUPPORTED_LOCALES


def test_lru_cache_returns_stable_dict():
    """Adjacent calls hit the cache, so they return the same object."""
    a = load_locale("zh_CN")
    b = load_locale("zh-CN")  # normalises to zh_CN
    c = load_locale("zh_CN")
    assert a is c  # cached
    # The normaliser routes "zh-CN" to "zh_CN" so this is also cached
    # under the same key.
    assert b is c


def test_lang_name_strings_are_human_readable():
    # The switcher UI displays these — must be the localised
    # display name of the language ITSELF, not the key.
    assert "中文" in t("lang.name", "zh_CN")
    assert "English" in t("lang.name", "en_US")
