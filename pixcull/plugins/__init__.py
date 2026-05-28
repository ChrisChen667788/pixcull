"""v0.13.13 — Plugin SDK foundation.

PixCull plugins extend the core in three ways:

  1. **Custom rubric axes** — register a 7th / 8th / ... rubric axis
     that the scoring pipeline calls in addition to the canonical 6.
  2. **Custom cull-reason taxonomy** — replace / extend the built-in
     ``out_of_focus / closed_eye / ...`` list with vertical-specific
     reasons (event-photog vs wildlife-photog).
  3. **Hook-style observers** — receive callbacks on
     ``after_pipeline_complete``, ``after_decision_change``,
     ``after_export``, etc.

A plugin is **any Python module that exposes a
``register(api)`` function** and lives in:

  * ``~/.pixcull/plugins/`` (user-local, takes priority)
  * ``pixcull/plugins/builtin/`` (shipped with the app)
  * Any importable package declaring an entry point under
    ``pixcull.plugins`` (PyPI-distributable plugins)

The plugin runtime is intentionally minimal:  no sandbox (you
already chose to install this code), no DB, no fancy lifecycle —
just a manifest + a registry.

API surface
===========

  ``register(api: PluginAPI) -> None``
      Called once at PixCull boot.  The plugin uses
      ``api.register_rubric_axis()`` / ``api.register_cull_reason()``
      / ``api.on(event, callback)`` to declare its contributions.

  ``PluginManifest``
      Optional `MANIFEST` module-level dict listing name, version,
      author, scope.  Used by ``pixcull plugins list``.

Example plugin (``~/.pixcull/plugins/my_wildlife_plugin.py``)
============================================================

    MANIFEST = {
        "name":    "Wildlife axis pack",
        "version": "1.0.0",
        "author":  "Me",
        "scope":   ["rubric_axis", "cull_reason"],
    }

    def register(api):
        api.register_rubric_axis(
            id="behavior",
            label_en="Animal behavior",
            label_zh="动物动作",
            description="Capturing dynamic action vs static rest",
        )
        api.register_cull_reason(
            id="wing_clipped",
            label_zh="翅膀被切",
            applies_to=["wildlife", "birds"],
        )
        api.on("after_decision_change", lambda evt: print(
            f"  · {evt['filename']} → {evt['new_decision']}"))

CLI
===

    pixcull plugins list                  # show installed plugins
    pixcull plugins enable <name>         # mark a plugin as active
    pixcull plugins disable <name>        # mark as inactive (kept on disk)
    pixcull plugins reload                # re-scan + re-register

Plugins are disabled by default — installing one to disk does
nothing until you ``enable`` it.  Removes the ambient-authority
risk.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1

# Plugins must define a ``register(api)`` callable.
_REGISTRATION_HOOK = "register"

# Optional module-level dict for "pixcull plugins list".
_MANIFEST_VAR = "MANIFEST"


@dataclass
class CustomRubricAxis:
    """A user-defined rubric axis."""
    id: str
    label_en: str
    label_zh: str = ""
    description: str = ""
    weight: float = 1.0     # relative weight in score_final blend
    source_plugin: str = ""


@dataclass
class CustomCullReason:
    """A user-defined cull-reason token."""
    id: str
    label_zh: str
    label_en: str = ""
    applies_to: list[str] = field(default_factory=list)   # vertical filter
    source_plugin: str = ""


# Event names that the runtime fires.  Plugins register via api.on().
EVENTS = (
    "after_pipeline_complete",   # one run finished analysing
    "after_decision_change",     # user updated a decision
    "after_export",              # export to XMP / ZIP / share link
    "after_run_resumed",         # /history → open old run
    "before_pipeline_start",     # about to begin
)


@dataclass
class PluginInfo:
    """Surfaceable plugin metadata for the CLI + UI."""
    name: str
    version: str = "0.0.0"
    author: str = ""
    scope: list[str] = field(default_factory=list)
    enabled: bool = False
    source_path: str = ""
    n_axes: int = 0
    n_cull_reasons: int = 0
    n_event_handlers: int = 0


# ---------------------------------------------------------------------------
# Registry (singleton, in-process)
# ---------------------------------------------------------------------------


class PluginAPI:
    """Public interface plugins use to register their contributions."""

    def __init__(self, plugin_name: str):
        self._plugin_name = plugin_name
        self.axes: list[CustomRubricAxis] = []
        self.cull_reasons: list[CustomCullReason] = []
        self.event_handlers: dict[str, list[Callable]] = {}

    def register_rubric_axis(self, *, id: str, label_en: str,
                              label_zh: str = "",
                              description: str = "",
                              weight: float = 1.0) -> None:
        """Add a new axis to the rubric scoring stack."""
        if not id or not label_en:
            raise ValueError("axis needs id + label_en")
        self.axes.append(CustomRubricAxis(
            id=id, label_en=label_en, label_zh=label_zh,
            description=description, weight=float(weight),
            source_plugin=self._plugin_name,
        ))

    def register_cull_reason(self, *, id: str, label_zh: str,
                              label_en: str = "",
                              applies_to: list[str] | None = None) -> None:
        """Add a vertical-specific cull reason."""
        if not id or not label_zh:
            raise ValueError("cull reason needs id + label_zh")
        self.cull_reasons.append(CustomCullReason(
            id=id, label_zh=label_zh, label_en=label_en,
            applies_to=list(applies_to or []),
            source_plugin=self._plugin_name,
        ))

    def on(self, event: str, callback: Callable[[dict], Any]) -> None:
        """Register an event-handler callback."""
        if event not in EVENTS:
            raise ValueError(
                f"unknown event {event!r}; valid: {EVENTS}")
        self.event_handlers.setdefault(event, []).append(callback)


class _Registry:
    """Process-singleton plugin registry."""

    def __init__(self):
        self._plugins: dict[str, dict] = {}
        # Loaded modules go here so subsequent reload() doesn't
        # double-call register().
        self._loaded_modules: dict[str, Any] = {}

    def register(self, name: str, manifest: dict, api: PluginAPI,
                 source_path: str, enabled: bool) -> None:
        self._plugins[name] = {
            "name":      name,
            "manifest":  manifest,
            "api":       api,
            "source":    source_path,
            "enabled":   enabled,
        }

    def info(self) -> list[PluginInfo]:
        out: list[PluginInfo] = []
        for name, p in self._plugins.items():
            m = p["manifest"] or {}
            api: PluginAPI = p["api"]
            out.append(PluginInfo(
                name=name,
                version=str(m.get("version", "0.0.0")),
                author=str(m.get("author", "")),
                scope=list(m.get("scope", [])),
                enabled=p["enabled"],
                source_path=p["source"],
                n_axes=len(api.axes),
                n_cull_reasons=len(api.cull_reasons),
                n_event_handlers=sum(len(v) for v in
                                      api.event_handlers.values()),
            ))
        return out

    def axes(self) -> list[CustomRubricAxis]:
        return [a for p in self._plugins.values() if p["enabled"]
                for a in p["api"].axes]

    def cull_reasons(self) -> list[CustomCullReason]:
        return [r for p in self._plugins.values() if p["enabled"]
                for r in p["api"].cull_reasons]

    def fire_event(self, event: str, payload: dict) -> None:
        """Invoke every registered handler for `event`.

        Handlers are best-effort:  a raising handler doesn't crash
        the runtime, just gets logged + skipped.
        """
        for p in self._plugins.values():
            if not p["enabled"]:
                continue
            for cb in p["api"].event_handlers.get(event, []):
                try:
                    cb(payload)
                except Exception as exc:
                    # Don't let one plugin break the whole pipeline.
                    print(f"[plugin] {p['name']} {event} handler "
                          f"raised {type(exc).__name__}: {exc}",
                          file=sys.stderr)

    def enable(self, name: str) -> bool:
        if name in self._plugins:
            self._plugins[name]["enabled"] = True
            _save_enabled_set(self.list_enabled())
            return True
        return False

    def disable(self, name: str) -> bool:
        if name in self._plugins:
            self._plugins[name]["enabled"] = False
            _save_enabled_set(self.list_enabled())
            return True
        return False

    def list_enabled(self) -> list[str]:
        return [n for n, p in self._plugins.items() if p["enabled"]]

    def clear(self) -> None:
        """Test helper — drop everything."""
        self._plugins.clear()
        self._loaded_modules.clear()


_registry = _Registry()


def get_registry() -> _Registry:
    return _registry


# ---------------------------------------------------------------------------
# Disk layout helpers
# ---------------------------------------------------------------------------


def _user_plugins_dir() -> Path:
    if os.name == "posix" and Path.home().joinpath(
            "Library", "Application Support").exists():
        base = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        base = Path.home() / ".pixcull"
    base.mkdir(parents=True, exist_ok=True)
    return base / "plugins"


def _enabled_path() -> Path:
    return _user_plugins_dir().parent / "plugins_enabled.json"


def _load_enabled_set() -> set[str]:
    p = _enabled_path()
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x) for x in data}
    except (OSError, json.JSONDecodeError):
        pass
    return set()


def _save_enabled_set(names: list[str]) -> None:
    p = _enabled_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(sorted(set(names)), indent=2),
            encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Discovery + load
# ---------------------------------------------------------------------------


def discover_plugin_paths() -> list[Path]:
    """Return every plugin file found in known locations."""
    out: list[Path] = []
    user_dir = _user_plugins_dir()
    if user_dir.exists():
        out.extend(user_dir.glob("*.py"))
    # Builtin directory (shipped with the app)
    builtin_dir = Path(__file__).resolve().parent / "builtin"
    if builtin_dir.exists():
        out.extend(builtin_dir.glob("*.py"))
    return sorted(out)


def _load_plugin_module(path: Path):
    """Import a single plugin file.  Returns the loaded module or
    None on failure (with a stderr message)."""
    name = f"pixcull_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        print(f"[plugin] failed to load {path.name}: "
              f"{type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None


def load_all() -> int:
    """Discover + load every plugin.  Returns the count loaded.

    A plugin loaded successfully when:
      * The file imports without error.
      * It defines a top-level ``register(api)`` callable.

    Whether the plugin is *enabled* is determined by the persisted
    enabled-set (``plugins_enabled.json``).  Default is OFF for any
    plugin not previously enabled.
    """
    _registry.clear()
    enabled = _load_enabled_set()
    n = 0
    for path in discover_plugin_paths():
        mod = _load_plugin_module(path)
        if mod is None:
            continue
        register_fn = getattr(mod, _REGISTRATION_HOOK, None)
        if not callable(register_fn):
            continue
        plugin_name = getattr(mod, "__name__", path.stem)
        # Strip our import-name prefix for display
        if plugin_name.startswith("pixcull_plugin_"):
            plugin_name = plugin_name[len("pixcull_plugin_"):]
        manifest = getattr(mod, _MANIFEST_VAR, {}) or {}
        api = PluginAPI(plugin_name)
        try:
            register_fn(api)
        except Exception as exc:
            print(f"[plugin] {plugin_name}.register raised "
                  f"{type(exc).__name__}: {exc}",
                  file=sys.stderr)
            continue
        _registry.register(
            name=plugin_name,
            manifest=manifest,
            api=api,
            source_path=str(path),
            enabled=plugin_name in enabled,
        )
        n += 1
    return n


def fire_event(event: str, payload: dict | None = None) -> None:
    """Shortcut for ``get_registry().fire_event``."""
    _registry.fire_event(event, payload or {})


# Lazy auto-load on first import (best-effort).  Tests + scripts can
# call ``load_all()`` to re-scan.
def _maybe_auto_load() -> None:
    if os.environ.get("PIXCULL_PLUGINS_AUTOLOAD", "1") != "0":
        try:
            load_all()
        except Exception:
            pass


_maybe_auto_load()
