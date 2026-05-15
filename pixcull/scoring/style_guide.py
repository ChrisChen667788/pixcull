"""P2.3 — per-team style-guide enforcement.

ROADMAP P2 long-shot. V28 unlocked multi-user + shared team sample
banks. But studios with strong brand identity have more than just
"reference samples" — they have explicit rules: "the brand red is
#C8102E; cull anything where the dominant color drifts more than
20%", "all delivered shots must be 3:2 or 16:9", "no portrait shots
where the model's eyes aren't dead-center horizontal", etc.

P2.3 adds a YAML-driven rule layer that runs AFTER the standard
rule stack + rescorer + meta-judge. A photo that's a clear "keep"
on quality grounds can get knocked to "maybe" or "cull" by a
style-guide violation, with the failing rule surfaced in the
per-image advice so the photographer knows why.

Storage layout
==============
Per-team style guides live at
``<team_root>/style_guide.yaml`` (alongside the shared verticals/
dir from V28). Users who subscribed a vertical to that team
automatically inherit the team's style guide.

Per-user override at ``<user_root>/style_guide.yaml`` takes
precedence — same path-fallback as V28 vertical_root_for_user.

Schema
======
    schema: pixcull.style_guide.v1
    name: "Studio42 Wedding Brand"
    rules:
      - id: aspect_ratio
        require_aspect: ["3:2", "16:9"]      # tolerance ±2%
        on_violation: cull                    # or maybe / advisory
        why: "deliverables must be 3:2 or 16:9"

      - id: dominant_color
        target_hex: "#C8102E"                  # brand red
        tolerance: 0.20                         # cosine distance
        scope: keep_only                        # only check keepers
        on_violation: maybe
        why: "dominant color drifts from Studio42 red"

      - id: face_center
        scope: portrait_keepers
        max_horizontal_offset: 0.15            # 15% from frame center
        on_violation: advisory
        why: "face off-center by > 15%"

Rule engine
===========
``apply_style_guide(row, rules)`` runs every applicable rule and
returns a list of violations + the suggested decision change.
Integration point is post-decision in the orchestrator (V32 hook),
but P2.3 also adds an OPTIONAL admin endpoint to re-apply a guide
to an already-scored run without re-analyzing.

We keep the rule set DELIBERATELY SMALL — three rule types in V1:
  * aspect_ratio (cheap, deterministic)
  * dominant_color  (PIL color histogram, ~30 ms / photo)
  * face_center    (needs face_bboxes from face detector)

Brand color palettes / framing conventions / etc. are user-defined
via the YAML; we don't ship preset palettes.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any


# Maximum aspect-ratio fraction tolerance (treat 3.00:2.00 vs
# 3.05:2.00 as matching). Studios sometimes deliver "3:2" that
# rounds to 1.498 or 1.502 — we forgive that.
_ASPECT_TOLERANCE = 0.02

# Default decision changes per ``on_violation`` keyword. Used when
# the rule doesn't specify, but the YAML schema lets each rule
# override.
_VIOLATION_TO_DECISION_FLOOR: dict[str, str] = {
    "advisory": None,    # surface only, decision unchanged
    "maybe":    "maybe",
    "cull":     "cull",
}


# ---------------------------------------------------------------------------
# YAML load
# ---------------------------------------------------------------------------

def _style_guide_path_for_user(user_id: str) -> Path | None:
    """Resolve the on-disk style_guide.yaml for the active user.

    Lookup order matches V28's vertical_root_for_user pattern: per-
    user override first, then ANY team the user is subscribed to
    (first match wins — most studios use a single team), else None.
    """
    from pixcull.users import user_root, _app_data_root

    udir = user_root(user_id)
    own = udir / "style_guide.yaml"
    if own.exists():
        return own

    # Walk the user's vertical redirects to find the team(s) they're
    # subscribed to. First team with a style_guide.yaml wins.
    verticals_dir = udir / "verticals"
    if not verticals_dir.exists():
        return None
    teams_seen: set[str] = set()
    for v in verticals_dir.iterdir():
        if not v.is_dir():
            continue
        redirect = v / "_team_redirect.json"
        if not redirect.exists():
            continue
        try:
            import json as _json
            data = _json.loads(redirect.read_text("utf-8"))
            tid = str(data.get("team_id") or "").strip()
            if not tid or tid in teams_seen:
                continue
            teams_seen.add(tid)
            cand = _app_data_root() / "teams" / tid / "style_guide.yaml"
            if cand.exists():
                return cand
        except (OSError, KeyError, ValueError):
            continue
    return None


def load_style_guide(user_id: str | None = None) -> dict:
    """Load the active style-guide YAML for ``user_id`` (defaults
    to the active user). Returns an empty dict when no guide is
    configured — callers should treat empty as "no rules apply."
    """
    from pixcull.users import get_active_user
    uid = user_id or get_active_user()
    p = _style_guide_path_for_user(uid)
    if p is None:
        return {}
    try:
        import yaml
        return yaml.safe_load(p.read_text("utf-8")) or {}
    except ImportError:
        print("[style_guide] PyYAML missing — style guide ignored",
              file=sys.stderr)
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"[style_guide] failed to parse {p}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Rule evaluators
# ---------------------------------------------------------------------------

def _parse_aspect(spec: str) -> float | None:
    """Convert ``"3:2"`` → 1.5; bad strings → None."""
    try:
        a, b = spec.split(":")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return None


def _check_aspect_ratio(row: dict, rule: dict) -> str | None:
    """Return a violation message when the row's aspect ratio
    doesn't match any of the rule's ``require_aspect`` values."""
    target_specs = rule.get("require_aspect") or []
    if not target_specs:
        return None
    # Row doesn't carry width/height directly; pull from path stat
    # is too expensive. Instead, the rule fires only when row carries
    # ``img_width`` / ``img_height`` (analyze_one doesn't emit those
    # today; V32 candidate). For now, skip when missing.
    w = row.get("img_width")
    h = row.get("img_height")
    if not w or not h:
        return None
    try:
        actual = float(w) / float(h)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    for spec in target_specs:
        target = _parse_aspect(str(spec))
        if target is None:
            continue
        # Compare both orientations
        for t in (target, 1.0 / target):
            if abs(actual - t) / t <= _ASPECT_TOLERANCE:
                return None
    return (f"aspect {actual:.3f} not in "
            f"{', '.join(str(s) for s in target_specs)}")


def _check_dominant_color(row: dict, rule: dict,
                              image_path: Path | None) -> str | None:
    """Compare the row's dominant color to ``rule.target_hex``.
    Cosine distance > ``rule.tolerance`` triggers a violation.

    ``image_path`` is read lazily; the caller passes the resolved
    path so we don't have to rebuild it here.
    """
    target_hex = (rule.get("target_hex") or "").lstrip("#")
    if len(target_hex) != 6 or image_path is None or not image_path.exists():
        return None
    try:
        target_rgb = (int(target_hex[0:2], 16) / 255.0,
                        int(target_hex[2:4], 16) / 255.0,
                        int(target_hex[4:6], 16) / 255.0)
    except ValueError:
        return None
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            # Downsize for speed — 64 px square gives a stable mean
            # color for ~5 ms vs ~500 ms on a 50 MP shot.
            im.thumbnail((64, 64), Image.LANCZOS)
            import numpy as np
            arr = np.asarray(im, dtype=np.float32) / 255.0
            mean = arr.reshape(-1, 3).mean(axis=0)
    except Exception:  # noqa: BLE001
        return None
    # Cosine distance between mean RGB and target.
    import numpy as np
    a = np.array(mean, dtype=np.float32)
    b = np.array(target_rgb, dtype=np.float32)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return None
    cos = float((a @ b) / (na * nb))
    dist = 1.0 - cos
    tol = float(rule.get("tolerance") or 0.20)
    if dist > tol:
        actual_hex = "#{:02X}{:02X}{:02X}".format(
            int(mean[0] * 255), int(mean[1] * 255), int(mean[2] * 255),
        )
        return (f"dominant color {actual_hex} vs target #{target_hex.upper()} "
                f"(distance {dist:.2f} > {tol:.2f})")
    return None


def _check_face_center(row: dict, rule: dict) -> str | None:
    """Check that the largest face is within ``max_horizontal_offset``
    of frame center (0.15 = 15% of frame width). Skipped when no
    face bboxes are present on the row.
    """
    bboxes = row.get("face_bboxes") or []
    if not bboxes:
        return None
    w = row.get("img_width")
    if not w:
        return None
    # Pick the largest face by area
    largest = max(
        bboxes,
        key=lambda bb: (bb[2] - bb[0]) * (bb[3] - bb[1]),
        default=None,
    )
    if largest is None:
        return None
    cx_face = (largest[0] + largest[2]) / 2.0
    cx_frame = float(w) / 2.0
    offset_frac = abs(cx_face - cx_frame) / float(w)
    max_off = float(rule.get("max_horizontal_offset") or 0.15)
    if offset_frac > max_off:
        return (f"face off-center by {offset_frac:.0%} "
                f"(rule allows ≤{max_off:.0%})")
    return None


# ---------------------------------------------------------------------------
# Top-level: apply guide to one row, optionally adjust decision
# ---------------------------------------------------------------------------

def apply_style_guide(
    row: dict,
    guide: dict,
    *,
    image_path: Path | None = None,
) -> dict:
    """Run every applicable rule from ``guide`` against ``row``.

    Returns a dict ``{violations: [...], new_decision: str | None,
    rules_evaluated: int}``. ``new_decision`` is the suggested
    floor based on the most-severe violation; None means no
    change.
    """
    rules = guide.get("rules") or []
    if not rules:
        return {"violations": [], "new_decision": None,
                "rules_evaluated": 0}

    violations: list[dict] = []
    rules_evaluated = 0
    decision_floor: str | None = None
    decision_severity = {"advisory": 0, "maybe": 1, "cull": 2}

    for rule in rules:
        rid = str(rule.get("id") or "")
        # Scope check — some rules only target keep / portrait / etc.
        scope = rule.get("scope") or ""
        if scope == "keep_only" and row.get("decision") != "keep":
            continue
        if scope == "portrait_keepers" and (
            row.get("decision") != "keep"
            or row.get("scene") != "portrait"
        ):
            continue
        rules_evaluated += 1

        msg: str | None = None
        if "require_aspect" in rule:
            msg = _check_aspect_ratio(row, rule)
        elif "target_hex" in rule:
            msg = _check_dominant_color(row, rule, image_path)
        elif "max_horizontal_offset" in rule:
            msg = _check_face_center(row, rule)
        else:
            # Unknown rule type — skip silently. Forwards-compatible
            # with future rule kinds.
            continue

        if msg is None:
            continue
        on_violation = str(rule.get("on_violation") or "advisory")
        violations.append({
            "rule_id":  rid,
            "why":      rule.get("why") or msg,
            "detail":   msg,
            "level":    on_violation,
        })
        if on_violation in ("maybe", "cull"):
            cur_sev = decision_severity.get(decision_floor or "advisory", 0)
            new_sev = decision_severity.get(on_violation, 0)
            if new_sev > cur_sev:
                decision_floor = on_violation

    return {
        "violations":      violations,
        "new_decision":    decision_floor,
        "rules_evaluated": rules_evaluated,
    }


__all__ = [
    "load_style_guide",
    "apply_style_guide",
]
