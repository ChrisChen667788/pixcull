"""v2.5-P0-1 — pure serialization + coercion helpers for the web demo.

First slice of splitting the ``scripts/serve_demo.py`` monolith: these
seven functions are *pure* (no module state, no ``self``, no I/O), so
they lift out cleanly into an importable, independently-unit-tested home
while ``serve_demo.py`` imports them back unchanged.  Behaviour is
byte-identical — they were copied verbatim from serve_demo.py.

Grouped here: NaN-safe JSON (``_scrub_nan`` / ``_safe_dumps``), HTML
escaping (``_html_escape``), and the pandas-CSV coercion helpers
(``_f`` / ``_clean_csv_string`` / ``_opt_int`` / ``_parse_int_list``)
that turn round-tripped CSV cells back into clean Python values.
"""

from __future__ import annotations

import json


def _scrub_nan(o):
    """Recursively replace float NaN/inf with None; everything else unchanged."""
    import math
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        return o
    if isinstance(o, dict):
        return {k: _scrub_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_scrub_nan(v) for v in o]
    return o


def _safe_dumps(obj, **kwargs) -> str:
    """``json.dumps`` that never emits invalid NaN/Infinity tokens."""
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(_scrub_nan(obj), **kwargs)


def _html_escape(s) -> str:
    """Minimal HTML escape for filename / alt-text interpolation. Returns
    ``""`` on None so f-strings stay safe. We don't import the ``html``
    module here because we want explicit control over which characters
    matter for the very narrow cases we hit (alt attribute, data-*).
    """
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _f(v: object) -> float | None:
    """Coerce to float or None for NaN/empty."""
    try:
        x = float(v)  # type: ignore[arg-type]
        if x != x:
            return None
        return round(x, 3)
    except (TypeError, ValueError):
        return None


def _clean_csv_string(v: object) -> str:
    """V20 — return empty string for CSV cells that round-tripped through
    pandas as NaN.

    pandas reads an empty CSV cell as ``float('nan')``, and ``str(NaN)``
    returns the literal string ``"nan"``. Naive ``str(r.get(col, "") or "")``
    therefore emits ``"nan"`` for missing values, which the JS template
    happily renders as a real-looking "nan" line.

    Treats the following as empty:
      * ``None``
      * ``float('nan')`` (and any value whose ``str`` is exactly ``"nan"``)
      * empty string / whitespace
    """
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    return s


def _opt_int(v: object) -> int | None:
    """V23 — coerce a CSV cell to int-or-None, NaN-safe.

    pandas reads missing CSV cells as ``float('nan')``. Naive
    ``int(NaN)`` raises ValueError; naive ``int(v) if v is not None``
    converts NaN to a junk integer on some platforms (NaN → 0 or
    -9223372036854775808 depending on libc). This helper rejects
    NaN explicitly.
    """
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _parse_int_list(v: object) -> list[int]:
    """V22.0 — parse a CSV cell that round-tripped a Python list of ints
    back into a list.

    pandas writes ``[0, 1, -1]`` as the string ``"[0, 1, -1]"`` and reads
    it back as that same string. We use ``ast.literal_eval`` for safe
    parsing (only accepts literal Python expressions — no code
    execution) and fall through to empty list for any malformed input.
    """
    if v is None:
        return []
    if isinstance(v, list):
        # Already-parsed (e.g. when called inline before CSV write)
        return [int(x) for x in v if x is not None]
    if isinstance(v, float) and v != v:
        return []
    s = str(v).strip()
    if not s or s.lower() == "nan" or s in ("[]", "()"):
        return []
    try:
        import ast
        parsed = ast.literal_eval(s)
        if isinstance(parsed, (list, tuple)):
            return [int(x) for x in parsed]
    except (ValueError, SyntaxError, TypeError):
        pass
    return []
