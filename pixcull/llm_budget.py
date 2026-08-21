"""INFRA-4 — cost-aware LLM call routing.

Pre-V32 PixCull would happily call DeepSeek V4-Flash / V4-Pro for
every photo's meta-judge + every vertical's phrase generation without
any budget visibility. These calls are billed per photo, which is fine
for a 100-photo session and hostile for a 5000-photo wedding — let
alone a studio running unattended overnight retrains.

INFRA-4 adds:

1. **Per-call cost estimation.** Wrappers compute the approximate
   yuan / dollar cost from input + output token counts using the
   model's published per-1k-token prices, persisted in
   ``_MODEL_PRICING``.

2. **Daily spend caps.** ``PIXCULL_LLM_BUDGET_YUAN`` env var (default
   10.0) sets a soft daily ceiling. The first call that would cross
   it returns a "budget exceeded" sentinel — callers can choose to
   skip the LLM step (rule-only fallback) or queue for tomorrow.

3. **Persistent ledger.** ``<user_root>/llm_budget.json`` holds the
   running total per UTC date. Survives server restarts so the cap
   isn't a per-process reset.

4. **Discoverable surface.** ``GET /api/v1/llm_budget`` returns
   ``{today_yuan, cap_yuan, calls_today, models}`` for an admin
   dashboard / API consumer.

Local-model fallback (V32.1+) is a future hook. For V32 we just
short-circuit cleanly when the cap is hit; callers decide.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any


# Per-1k-token prices in yuan. Sourced from DeepSeek's public pricing
# page (https://api-docs.deepseek.com/quick_start/pricing). Update
# when DeepSeek changes their numbers.
#
# Format: model → (input_per_1k, output_per_1k) in CNY.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash":   (0.0010, 0.0040),
    "deepseek-v4-pro":     (0.0040, 0.0160),
    "deepseek-chat":       (0.0010, 0.0040),   # alias for v4-flash
    "deepseek-reasoner":   (0.0040, 0.0160),   # alias for v4-pro
    # v2.48 — MiniMax M3, the primary vision judge. Taken from the
    # vendor's published per-token rates for the standard tier, which
    # covers requests under 512K context (the rates double above it,
    # which PixCull never approaches — one photo is ~1.5k tokens), and
    # converted to CNY.
    #
    # This entry matters more than it looks: without it M3 fell through
    # to _UNKNOWN_MODEL_PRICE, which is DeepSeek-Pro's CNY rate and is
    # ~1.8x too high on input and ~1.8x too high on output. The daily
    # cap arithmetic was therefore meaningless for the one model that
    # now does the most calls.
    "minimax-m3":          (0.00218, 0.00870),
}

# Hard floor used when a model is called that isn't in the table.
# Conservative — assume the priciest current model. Better to
# over-account than to silently overspend.
_UNKNOWN_MODEL_PRICE = (0.0040, 0.0160)

_DEFAULT_DAILY_CAP_YUAN = 10.0

# Ledger schema:
#   {
#     "schema":     "pixcull.llm_budget.v1",
#     "by_date":    {"2026-05-15": {"yuan": 1.23, "calls": 17, "by_model": {...}}},
#     "updated_at": <unix_ts>,
#   }
_LEDGER_FILE = "llm_budget.json"

_LOCK = threading.Lock()


def _today_iso() -> str:
    """UTC date — using local time would double-count near midnight
    or undercount when the user's machine TZ != server's expectations."""
    return time.strftime("%Y-%m-%d", time.gmtime())


def _ledger_path() -> Path:
    # Lazy import — avoid circular when pixcull.__init__ imports us
    from pixcull.users import user_root, get_active_user
    return user_root(get_active_user()) / _LEDGER_FILE


def _load_ledger() -> dict:
    p = _ledger_path()
    if not p.exists():
        return {"schema": "pixcull.llm_budget.v1", "by_date": {}}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "pixcull.llm_budget.v1", "by_date": {}}


def _save_ledger(ledger: dict) -> None:
    ledger["updated_at"] = time.time()
    p = _ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(ledger, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    except OSError as exc:
        print(f"[llm_budget] save failed: {exc}", file=sys.stderr)


def cap_yuan() -> float:
    """Today's effective daily cap in CNY. Sourced from env;
    default ``_DEFAULT_DAILY_CAP_YUAN``."""
    raw = os.environ.get("PIXCULL_LLM_BUDGET_YUAN") or ""
    if not raw:
        return _DEFAULT_DAILY_CAP_YUAN
    try:
        v = float(raw)
        return max(0.0, v)
    except ValueError:
        return _DEFAULT_DAILY_CAP_YUAN


def estimate_cost(model: str, prompt_tokens: int,
                       completion_tokens: int) -> float:
    """Estimated CNY cost for a single LLM call. Returns 0.0 for
    zero-token edge cases.
    """
    inp_per_1k, out_per_1k = _MODEL_PRICING.get(
        model, _UNKNOWN_MODEL_PRICE,
    )
    return (prompt_tokens * inp_per_1k / 1000.0
            + completion_tokens * out_per_1k / 1000.0)


def check_budget(estimated_cost_yuan: float = 0.0) -> bool:
    """Return True if a call of approximately ``estimated_cost_yuan``
    can proceed without crossing today's cap.

    Pass 0.0 (default) to check "are we currently OVER cap?" without
    pre-counting the new call. Useful for callers that want to peek
    state before paying.
    """
    cap = cap_yuan()
    if cap <= 0.0:                # admin set the env var to 0 = blocked
        return False
    with _LOCK:
        ledger = _load_ledger()
        today = ledger["by_date"].get(_today_iso()) or {}
        spent = float(today.get("yuan") or 0.0)
    return (spent + estimated_cost_yuan) <= cap


def record_call(model: str, prompt_tokens: int,
                   completion_tokens: int) -> dict:
    """Charge an LLM call against the daily ledger AFTER it completes.

    Returns the post-call status:
      ``{cost_yuan, total_today, cap_yuan, over_cap, calls_today}``

    Recording always happens (we want the ledger to reflect true
    spend), but ``over_cap=True`` lets callers decide whether to
    suppress further calls in the same session.
    """
    cost = estimate_cost(model, prompt_tokens, completion_tokens)
    with _LOCK:
        ledger = _load_ledger()
        date = _today_iso()
        bucket = ledger["by_date"].setdefault(date, {
            "yuan": 0.0,
            "calls": 0,
            "by_model": {},
        })
        bucket["yuan"] = float(bucket.get("yuan") or 0.0) + cost
        bucket["calls"] = int(bucket.get("calls") or 0) + 1
        by_model = bucket.setdefault("by_model", {})
        by_model[model] = float(by_model.get(model) or 0.0) + cost
        _save_ledger(ledger)
        cap = cap_yuan()
        return {
            "cost_yuan":   cost,
            "total_today": float(bucket["yuan"]),
            "cap_yuan":    cap,
            "over_cap":    bucket["yuan"] > cap,
            "calls_today": int(bucket["calls"]),
        }


def snapshot() -> dict:
    """Get today's spend + cap without recording a call. For the
    admin endpoint."""
    with _LOCK:
        ledger = _load_ledger()
        today = ledger["by_date"].get(_today_iso()) or {}
    cap = cap_yuan()
    spent = float(today.get("yuan") or 0.0)
    return {
        "schema":      "pixcull.llm_budget.snapshot.v1",
        "date_utc":    _today_iso(),
        "today_yuan":  spent,
        "cap_yuan":    cap,
        "remaining_yuan": max(0.0, cap - spent),
        "over_cap":    spent > cap,
        "calls_today": int(today.get("calls") or 0),
        "by_model":    today.get("by_model") or {},
        "all_dates":   sorted(ledger.get("by_date", {}).keys())[-30:],
    }


__all__ = [
    "cap_yuan",
    "estimate_cost",
    "check_budget",
    "record_call",
    "snapshot",
]
