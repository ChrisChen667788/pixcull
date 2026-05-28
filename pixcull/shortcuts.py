"""v0.12-P0-1 — User-customisable keyboard shortcuts.

Server-side registry + persistence.  The actual key-event listener
lives in the browser; this module owns:

  * The canonical action catalogue (every action that *can* be bound)
  * Default bindings (matching v0.11 hard-coded chord set)
  * Persistence to ``~/.pixcull/shortcuts.json``
  * Import / export of bindings as portable JSON (Raycast-style)
  * Conflict detection (per-surface scope)

Why this lives in Python (not just localStorage)
================================================
Two reasons:

1. **Multi-device sync prep.** Once a photographer customises their
   bindings on a Mac Studio, the same JSON should follow to their
   MacBook Pro.  Server-side persistence is the foundation for the
   v0.12 cloud sync (or LAN sync via existing event channel).
2. **Conflict checking authority.** Browser-side detection is great
   for ad-hoc edits; server-side check is what guarantees imports
   from a JSON file haven't introduced same-scope duplicates.

Surface scopes
==============
Same key chord can mean different things in different surfaces:
  * ``grid``      — main results grid
  * ``lightbox``  — image viewer modal
  * ``compare``   — A/B compare modal
  * ``inspector`` — Inspector panel (read-only chips clickable)
  * ``global``    — applies anywhere not specifically scoped

A binding's ``scope`` field places it in one of these.  Conflict =
two bindings with the same scope + same chord.  Cross-scope chord
reuse is allowed (and common — ``j`` / ``k`` for next/prev works in
every surface).

Persistence schema (``~/.pixcull/shortcuts.json``)
==================================================

    {
      "version": 1,
      "bindings": [
        {
          "action_id": "lightbox.next",
          "scope": "lightbox",
          "chord": "ArrowRight"
        },
        {
          "action_id": "lightbox.next",
          "scope": "lightbox",
          "chord": "k"
        },
        ...
      ]
    }

Multiple bindings per action are allowed (slot 1 + slot 2 +
slot 3); user can clear slots they don't want.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Action:
    """A bindable action."""
    id: str                     # e.g. "lightbox.next"
    scope: str                  # grid / lightbox / compare / inspector / global
    label: str                  # human-readable, EN
    label_zh: str = ""          # optional ZH label for UI
    default_chords: tuple[str, ...] = ()


@dataclass
class Binding:
    """A single (action × scope × chord) triple."""
    action_id: str
    scope: str
    chord: str


# Canonical action catalogue.  Keep in sync with the in-app keymap.
# When adding a new bindable action: append here + add the default,
# then wire the listener client-side.
ACTIONS: tuple[Action, ...] = (
    # ---- grid ----
    Action("grid.focus_next", "grid", "Focus next photo", "下一张",
           ("ArrowRight", "j")),
    Action("grid.focus_prev", "grid", "Focus prev photo", "上一张",
           ("ArrowLeft", "k")),
    Action("grid.open_lightbox", "grid", "Open lightbox", "打开 lightbox",
           ("Enter", " ")),
    Action("grid.decide_keep", "grid", "Mark Keep", "标 keep",
           ("1",)),
    Action("grid.decide_maybe", "grid", "Mark Maybe", "标 maybe",
           ("2",)),
    Action("grid.decide_cull", "grid", "Mark Cull", "标 cull",
           ("3",)),
    Action("grid.select_all", "grid", "Select all visible", "全选当前可见",
           ("Mod+a",)),
    Action("grid.clear_selection", "grid", "Clear selection", "取消选择",
           ("Escape",)),
    Action("grid.open_palette", "grid", "Open Cmd+K palette", "打开命令面板",
           ("Mod+k",)),
    # ---- lightbox ----
    Action("lightbox.next", "lightbox", "Next photo", "下一张",
           ("ArrowRight", "j")),
    Action("lightbox.prev", "lightbox", "Prev photo", "上一张",
           ("ArrowLeft", "k")),
    Action("lightbox.close", "lightbox", "Close lightbox", "关闭",
           ("Escape",)),
    Action("lightbox.zoom_toggle", "lightbox", "Toggle 1:1 zoom", "切换 1:1",
           ("z",)),
    Action("lightbox.decide_keep", "lightbox", "Keep", "keep",
           ("1",)),
    Action("lightbox.decide_maybe", "lightbox", "Maybe", "maybe",
           ("2",)),
    Action("lightbox.decide_cull", "lightbox", "Cull", "cull",
           ("3",)),
    Action("lightbox.rotate_cw", "lightbox", "Rotate clockwise", "顺时针旋转",
           ("]",)),
    Action("lightbox.rotate_ccw", "lightbox", "Rotate counter-clockwise",
           "逆时针旋转", ("[",)),
    # ---- compare ----
    Action("compare.next_burst", "compare", "Next burst",
           "下一个连拍组", ("ArrowRight", "j")),
    Action("compare.prev_burst", "compare", "Prev burst",
           "上一个连拍组", ("ArrowLeft", "k")),
    Action("compare.close", "compare", "Close compare", "关闭比较",
           ("Escape",)),
    # ---- inspector ----
    Action("inspector.cycle_lambda", "inspector", "Cycle style λ",
           "切换 λ 权重", ("l",)),
    Action("inspector.expand_explain", "inspector",
           "Expand AI explain", "展开 AI 解释", ("?",)),
    # ---- global ----
    Action("global.show_shortcuts", "global", "Show shortcut help",
           "显示快捷键帮助", ("?",)),
)

# Index for fast lookup
_ACTIONS_BY_ID: dict[str, Action] = {a.id: a for a in ACTIONS}


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def shortcuts_path() -> Path:
    """Location of the per-user shortcuts JSON."""
    if os.name == "posix":
        base = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        base = Path.home() / ".pixcull"
    base.mkdir(parents=True, exist_ok=True)
    return base / "shortcuts.json"


def default_bindings() -> list[Binding]:
    """Build the default binding set from ACTIONS.default_chords."""
    out: list[Binding] = []
    for a in ACTIONS:
        for c in a.default_chords:
            out.append(Binding(action_id=a.id, scope=a.scope, chord=c))
    return out


def load_bindings() -> list[Binding]:
    """Read user's saved bindings; fall back to defaults."""
    p = shortcuts_path()
    if not p.exists():
        return default_bindings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_bindings()
    if not isinstance(data, dict):
        return default_bindings()
    if data.get("version") != SCHEMA_VERSION:
        # Unknown version → start fresh.  Future migrations branch here.
        return default_bindings()
    out: list[Binding] = []
    for b in data.get("bindings", []):
        if not isinstance(b, dict):
            continue
        aid = b.get("action_id")
        sc = b.get("scope")
        ch = b.get("chord")
        if (isinstance(aid, str) and aid in _ACTIONS_BY_ID
                and isinstance(sc, str) and isinstance(ch, str)):
            out.append(Binding(action_id=aid, scope=sc, chord=ch))
    if not out:
        # Empty / all-invalid file → defaults so the user is never stuck
        return default_bindings()
    return out


def save_bindings(bindings: Iterable[Binding]) -> None:
    """Persist bindings to disk.  Atomic write via temp-file rename."""
    p = shortcuts_path()
    body = json.dumps({
        "version": SCHEMA_VERSION,
        "bindings": [asdict(b) for b in bindings],
    }, indent=2, ensure_ascii=False)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Conflict:
    """Two bindings claim the same chord in the same scope."""
    scope: str
    chord: str
    action_ids: tuple[str, ...]


def find_conflicts(bindings: Iterable[Binding]) -> list[Conflict]:
    """Return every (scope, chord) that's bound by ≥ 2 actions."""
    seen: dict[tuple[str, str], list[str]] = {}
    for b in bindings:
        key = (b.scope, b.chord)
        seen.setdefault(key, []).append(b.action_id)
    out: list[Conflict] = []
    for (scope, chord), aids in seen.items():
        # De-dup repeats of the same action (which is fine — same
        # action, multiple slots = "two ways to invoke it")
        unique = sorted(set(aids))
        if len(unique) > 1:
            out.append(Conflict(scope=scope, chord=chord,
                                action_ids=tuple(unique)))
    return out


# ---------------------------------------------------------------------------
# Catalog metadata for the UI
# ---------------------------------------------------------------------------


def actions_for_scope(scope: str) -> list[Action]:
    return [a for a in ACTIONS if a.scope == scope]


def action(action_id: str) -> Action | None:
    return _ACTIONS_BY_ID.get(action_id)


def reset_to_defaults() -> list[Binding]:
    """Atomic 'reset' — write defaults to disk and return them."""
    bindings = default_bindings()
    save_bindings(bindings)
    return bindings
