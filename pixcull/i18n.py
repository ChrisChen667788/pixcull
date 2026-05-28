"""v0.8-P0-1 — server-side i18n.

Loads a locale (key → translated string map) from pixcull/locale/
JSON files. Used by:

  * server-rendered pages (/, /admin, /tether, /history, /share)
    that emit HTML at request time and want the lang to follow
    the client's `pixcull_lang` cookie
  * the /api/v1/locale endpoint that the JS shim in results.html
    fetches when the user toggles language

V1 design (kept on purpose simple):
  * No fallback chain across multiple zh / en variants — we
    ship exactly two locales (zh_CN, en_US) and any other
    Accept-Language falls back to zh_CN.
  * No pluralization rules. The JSON keys are full strings;
    where a string would need plural form we use a different
    key per branch (``buckets.empty`` vs ``buckets.one`` vs
    ``buckets.many``) instead of importing ICU MessageFormat.
  * Missing keys return the key itself (loud failure mode) —
    makes it obvious during dev that a string wasn't migrated.

V2 (deferred to v0.8-P1-4) can layer on ja_JP + KO/ES + a real
fallback chain (`ja_JP → en_US → key`) once we have more locales.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_LOCALE_DIR = Path(__file__).resolve().parent / "locale"

# Supported locales. The ORDER is the fallback chain when the
# client's preferred lang isn't explicitly in the list — we use
# zh_CN as the default because the original product UI is zh.
# v0.8-P2-1 — added ja_JP.
# v0.10-P1-5 — added ko_KR (Korean photographer community on
# 小红书 / Naver) + es_ES (Latam + Spain wedding photographers).
SUPPORTED_LOCALES: tuple[str, ...] = (
    "zh_CN", "en_US", "ja_JP", "ko_KR", "es_ES",
    # v0.11-P2-2 — DACH + French + Italian (European wedding photo markets).
    "de_DE", "fr_FR", "it_IT",
)
DEFAULT_LOCALE: str = "zh_CN"


def load_locale(lang: str) -> dict[str, str]:
    """Return the {key: translation} dict for ``lang``.

    Normalises the input first (zh-CN → zh_CN etc.), then routes
    to the LRU-cached loader so different input spellings of the
    same locale share the same cached dict.

    Unknown locales fall back to DEFAULT_LOCALE.  Missing files
    return an empty dict (and ``t()`` then returns the key
    verbatim — loud-failure dev mode).
    """
    return _load_locale_normalized(_normalize_lang(lang))


@lru_cache(maxsize=8)
def _load_locale_normalized(norm: str) -> dict[str, str]:
    """LRU-cached locale loader keyed by the *normalised* name.

    Lives inside the module because the @lru_cache key is the
    raw arg — so we must guarantee callers always pass the
    canonical "zh_CN" / "en_US" form here.  Public API
    ``load_locale`` does that normalisation up front.
    """
    p = _LOCALE_DIR / f"{norm}.json"
    if not p.exists():
        if norm != DEFAULT_LOCALE:
            return _load_locale_normalized(DEFAULT_LOCALE)
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Only str → str entries. Anything else (a list, a nested
    # object) is invalid for v1.
    return {str(k): str(v) for k, v in data.items()
            if isinstance(v, str)}


def _normalize_lang(lang: str | None) -> str:
    """Normalise an Accept-Language fragment into one of SUPPORTED_LOCALES.

    Accepts:
      "zh", "zh-CN", "zh_CN", "zh-Hans-CN"     → "zh_CN"
      "en", "en-US", "en_US", "en-GB"          → "en_US"
      "ja", "ja-JP", "ja_JP"                   → "ja_JP"
      "ko", "ko-KR", "ko_KR"                   → "ko_KR"
      "es", "es-ES", "es-MX", "es-AR"          → "es_ES"
      anything else                            → DEFAULT_LOCALE
    """
    if not lang:
        return DEFAULT_LOCALE
    s = str(lang).lower().replace("_", "-").split(",")[0].strip()
    if s.startswith("zh"):
        return "zh_CN"
    if s.startswith("en"):
        return "en_US"
    if s.startswith("ja"):
        return "ja_JP"
    # v0.10-P1-5 — collapse any es-* variant onto es_ES.  Latam
    # Spanish is regionally distinct but the translation strings
    # are deliberately neutral (no vosotros / vos splits) so one
    # locale serves the whole Spanish-speaking market.
    if s.startswith("ko"):
        return "ko_KR"
    if s.startswith("es"):
        return "es_ES"
    # v0.11-P2-2 — DACH (de-DE, de-AT, de-CH all collapse to de_DE),
    # French (fr-FR, fr-CA, fr-BE all → fr_FR — locale strings stay
    # generic European French; quebec-specific switches are not worth
    # a separate file), and Italian (it-IT, it-CH).
    if s.startswith("de"):
        return "de_DE"
    if s.startswith("fr"):
        return "fr_FR"
    if s.startswith("it"):
        return "it_IT"
    return DEFAULT_LOCALE


def t(key: str, lang: str = DEFAULT_LOCALE) -> str:
    """Translate ``key`` under ``lang``. Missing keys return the key.

    The "key returned on miss" pattern is deliberate: during
    development, untranslated UI text becomes immediately visible
    (``library.group.scene`` shows up in the panel instead of
    "场景") so the migration is self-policing.
    """
    table = load_locale(lang)
    return table.get(key, key)


def all_keys(lang: str = DEFAULT_LOCALE) -> list[str]:
    """Sorted list of all keys defined for ``lang``.

    Used by the locale-comparison test and the EN/JA translation
    drift detector in v0.8-P1-4.
    """
    return sorted(load_locale(lang).keys())


__all__ = [
    "SUPPORTED_LOCALES",
    "DEFAULT_LOCALE",
    "load_locale",
    "t",
    "all_keys",
]
