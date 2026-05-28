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


# v0.10-P1-5 additions ---------------------------------------------------


def test_ko_loads_and_matches_zh_keyset():
    """KO must have EXACTLY the same keys as zh_CN (drift rule)."""
    zh = set(all_keys("zh_CN"))
    ko = set(all_keys("ko_KR"))
    missing = zh - ko
    extra   = ko - zh
    assert not missing, f"KO missing keys: {sorted(missing)}"
    assert not extra,   f"KO has extra keys: {sorted(extra)}"


def test_es_loads_and_matches_zh_keyset():
    zh = set(all_keys("zh_CN"))
    es = set(all_keys("es_ES"))
    missing = zh - es
    extra   = es - zh
    assert not missing, f"ES missing keys: {sorted(missing)}"
    assert not extra,   f"ES has extra keys: {sorted(extra)}"


def test_ko_normalisation():
    """Korean Accept-Language fragments all route to ko_KR."""
    assert t("workspace.crumb.results", "ko") == "분석 결과"
    assert t("workspace.crumb.results", "ko-KR") == "분석 결과"
    assert t("workspace.crumb.results", "ko_KR") == "분석 결과"


def test_es_normalisation_covers_latam():
    """es-MX / es-AR / es-CL all collapse onto es_ES (one neutral
    locale serves the whole Spanish-speaking market)."""
    expected = "Resultados del análisis"
    assert t("workspace.crumb.results", "es")    == expected
    assert t("workspace.crumb.results", "es-ES") == expected
    assert t("workspace.crumb.results", "es-MX") == expected
    assert t("workspace.crumb.results", "es-AR") == expected
    assert t("workspace.crumb.results", "es-CL") == expected


def test_supported_locales_includes_five():
    # v0.10-P1-5: zh + en + ja + ko + es must all be supported
    for lang in ("zh_CN", "en_US", "ja_JP", "ko_KR", "es_ES"):
        assert lang in SUPPORTED_LOCALES


def test_ko_es_lang_name_strings_are_native():
    """The switcher displays the language name in its OWN script."""
    assert "한국어" in t("lang.name", "ko_KR")
    assert "Español" in t("lang.name", "es_ES")


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
    # Polish / Hindi / etc. not supported; should fall back to zh_CN.
    # (Japanese added v0.8-P2-1, Korean + Spanish added v0.10-P1-5,
    # German + French + Italian added v0.11-P2-2; see the dedicated
    # normalisation tests above.)
    assert t("workspace.crumb.results", "pl") == "分析结果"
    assert t("workspace.crumb.results", "hi") == "分析结果"
    assert t("workspace.crumb.results", "") == "分析结果"
    assert t("workspace.crumb.results", None) == "分析结果"  # type: ignore[arg-type]


def test_de_fr_it_supported():
    """v0.11-P2-2 — DACH + French + Italian map to their own files."""
    assert t("workspace.crumb.results", "de") == "Analyseergebnisse"
    assert t("workspace.crumb.results", "de-AT") == "Analyseergebnisse"
    assert t("workspace.crumb.results", "fr") == "Résultats d'analyse"
    assert t("workspace.crumb.results", "fr-CA") == "Résultats d'analyse"
    assert t("workspace.crumb.results", "it") == "Risultati dell'analisi"


def test_pt_nl_tr_ru_ar_supported():
    """v0.12-P2-2 — Portuguese / Dutch / Turkish / Russian / Arabic."""
    assert t("workspace.crumb.results", "pt") == "Resultados da análise"
    assert t("workspace.crumb.results", "pt-PT") == "Resultados da análise"
    assert t("workspace.crumb.results", "nl") == "Analyseresultaten"
    assert t("workspace.crumb.results", "nl-BE") == "Analyseresultaten"
    assert t("workspace.crumb.results", "tr") == "Analiz sonuçları"
    assert t("workspace.crumb.results", "ru") == "Результаты анализа"
    assert t("workspace.crumb.results", "ar") == "نتائج التحليل"
    assert t("workspace.crumb.results", "ar-EG") == "نتائج التحليل"


def test_default_locale_constant():
    assert DEFAULT_LOCALE == "zh_CN"
    assert "zh_CN" in SUPPORTED_LOCALES
    assert "en_US" in SUPPORTED_LOCALES
    assert "de_DE" in SUPPORTED_LOCALES
    assert "fr_FR" in SUPPORTED_LOCALES
    assert "it_IT" in SUPPORTED_LOCALES
    # v0.12-P2-2 — second batch of European + global locales
    assert "pt_BR" in SUPPORTED_LOCALES
    assert "nl_NL" in SUPPORTED_LOCALES
    assert "tr_TR" in SUPPORTED_LOCALES
    assert "ru_RU" in SUPPORTED_LOCALES
    assert "ar_SA" in SUPPORTED_LOCALES
    # 13 locales total after v0.12-P2-2
    assert len(SUPPORTED_LOCALES) == 13


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
