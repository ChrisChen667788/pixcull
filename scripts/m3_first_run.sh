#!/usr/bin/env bash
# v2.49 — one command to go from "no key" to "here is the verdict".
#
# The four-step runbook (store key → grant consent → probe endpoint →
# measure) is correct but it is four steps, and getting step 3 wrong
# makes step 4 produce a page of confident-looking zeros. This does them
# in order and stops at the first thing that fails.
#
# `security` does its own hidden prompt, so the key goes from your
# keyboard into the keychain without passing through this script at all —
# no shell variable, no file, and crucially no argv, which `ps` shows to
# every other process on the machine. It is not in HISTFILE either.
#
#   bash scripts/m3_first_run.sh                     # full run
#   bash scripts/m3_first_run.sh --dry-run           # everything but the spend

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/pixcull/.venv/bin/python"
LABELS="$HOME/pixcull_label_run/training_combined.csv"
SCORES="$HOME/pixcull_label_run/m3_eval_input.csv"
DRY=""
[[ "${1:-}" == "--dry-run" ]] && DRY="--dry-run"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[[ -x "$PY" ]] || die "no venv at $PY"
[[ -f "$LABELS" ]] || die "label sheet missing: $LABELS"
[[ -f "$SCORES" ]] || die "eval input missing: $SCORES"

# ── 1. key ────────────────────────────────────────────────────────────
if "$PY" -c 'import sys;from pixcull.scoring.m3 import api_key_from_env;sys.exit(0 if api_key_from_env() else 1)' 2>/dev/null; then
  say "1/4  key — already in the keychain, leaving it alone"
else
  say "1/4  key"
  echo "     'security' will prompt for it below. Paste and press Enter —"
  echo "     it is hidden, and it goes straight into the keychain."
  # -w with NO value makes security prompt (twice, to confirm) and read
  # the secret itself. Passing it as `-w "$key"` would put the key in
  # argv, where `ps` shows it to every process on the machine. -U updates
  # in place if the item already exists.
  security add-generic-password -U -a "$USER" -s MINIMAX_API_KEY -w \
    || die "keychain write failed (or you cancelled)"
  "$PY" -c 'import sys;from pixcull.scoring.m3 import api_key_from_env;sys.exit(0 if api_key_from_env() else 1)' \
    || die "stored, but PixCull still cannot read it back — check that the
item is named MINIMAX_API_KEY under your login keychain"
  echo "     stored, and PixCull can read it"
fi

# ── 2. consent ────────────────────────────────────────────────────────
say "2/4  upload consent"
if "$PY" -c 'import sys;from pixcull.scoring.m3 import has_consent;sys.exit(0 if has_consent() else 1)' 2>/dev/null; then
  echo "     already granted"
else
  "$PY" -m pixcull m3 consent
  echo
  read -rp "     Upload photos to MiniMax for judging? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || die "declined — nothing was sent. Re-run any time."
  "$PY" -m pixcull m3 consent --grant >/dev/null
  echo "     granted (revoke with: $PY -m pixcull m3 consent --revoke)"
fi

# ── 3. probe ──────────────────────────────────────────────────────────
# This step is why the script exists. A stale endpoint or model string
# turns every later call into verdict.error, and 408 nulls look exactly
# like a model with no opinion. Fail here, loudly, on one call.
say "3/4  probing the endpoint (one real call)"
PHOTO="$("$PY" - <<'EOF'
import csv, os
src = os.path.expanduser("~/pixcull_label_run/m3_eval_input.csv")
for r in csv.DictReader(open(src, encoding="utf-8-sig")):
    p = r.get("path") or ""
    if p and os.path.exists(p):
        print(p); break
EOF
)"
[[ -n "$PHOTO" ]] || die "no readable photo in $SCORES — the paths are stale"
"$PY" -m pixcull m3 doctor --image "$PHOTO" \
  || die "the probe failed. Do NOT run the eval — it would bill for calls
that all return errors and report a confident-looking 0.000 for both
sides. Fix what the table above reports first."

# ── 4. measure ────────────────────────────────────────────────────────
say "4/4  measuring M3 against the rule stack"
"$PY" -m pixcull m3 eval --labels "$LABELS" --scores "$SCORES" $DRY

if [[ -z "$DRY" ]]; then
  say "done — report at $REPO/docs/M3-EVAL.md"
  echo "Paste the verdict line back and the roadmap follows it:"
  echo "  BETTER  → sync the numbers into the README and push"
  echo "  WORSE / NO MEANINGFUL DIFFERENCE"
  echo "          → revert the default to off and the 47 claims with it"
fi
