"""Tests for v0.13.13 plugin SDK foundation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.plugins import (
    EVENTS,
    PluginAPI,
    fire_event,
    get_registry,
    load_all,
)


# ---------------------------------------------------------------------------
# PluginAPI surface
# ---------------------------------------------------------------------------


def test_register_axis_basic():
    api = PluginAPI("test_plugin")
    api.register_rubric_axis(
        id="behavior", label_en="Behavior", label_zh="动作")
    assert len(api.axes) == 1
    assert api.axes[0].id == "behavior"
    assert api.axes[0].source_plugin == "test_plugin"


def test_register_axis_rejects_missing_id():
    api = PluginAPI("test")
    with pytest.raises(ValueError):
        api.register_rubric_axis(id="", label_en="x")
    with pytest.raises(ValueError):
        api.register_rubric_axis(id="x", label_en="")


def test_register_cull_reason_basic():
    api = PluginAPI("test")
    api.register_cull_reason(
        id="wing_clipped", label_zh="翅膀被切",
        applies_to=["wildlife"])
    assert len(api.cull_reasons) == 1
    assert api.cull_reasons[0].id == "wing_clipped"
    assert api.cull_reasons[0].applies_to == ["wildlife"]


def test_register_cull_reason_rejects_empty():
    api = PluginAPI("test")
    with pytest.raises(ValueError):
        api.register_cull_reason(id="", label_zh="x")
    with pytest.raises(ValueError):
        api.register_cull_reason(id="x", label_zh="")


def test_register_event_handler():
    api = PluginAPI("test")
    api.on("after_decision_change", lambda evt: None)
    assert "after_decision_change" in api.event_handlers
    assert len(api.event_handlers["after_decision_change"]) == 1


def test_register_unknown_event_rejected():
    api = PluginAPI("test")
    with pytest.raises(ValueError):
        api.on("not_a_real_event", lambda evt: None)


def test_events_canonical_list():
    """The runtime advertises a fixed set of events for plugins to
    bind against."""
    assert isinstance(EVENTS, tuple)
    assert "after_decision_change" in EVENTS
    assert "after_pipeline_complete" in EVENTS


# ---------------------------------------------------------------------------
# Registry + discovery (via tmp_path-isolated HOME)
# ---------------------------------------------------------------------------


def _write_plugin(plugins_dir: Path, name: str, body: str) -> None:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / f"{name}.py").write_text(body, encoding="utf-8")


def test_load_all_picks_up_user_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "test_plug", """
MANIFEST = {"name": "Test plugin", "version": "1.0.0"}
def register(api):
    api.register_rubric_axis(id="custom", label_en="Custom",
                              label_zh="自定义")
""")
    n = load_all()
    # The builtin example_wildlife is also picked up
    info = get_registry().info()
    names = {p.name for p in info}
    assert "test_plug" in names
    # The test plugin shouldn't be enabled by default
    test_plug = next(p for p in info if p.name == "test_plug")
    assert not test_plug.enabled
    assert test_plug.n_axes == 1


def test_disabled_plugin_axes_not_in_registry_view(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "off_plug", """
def register(api):
    api.register_rubric_axis(id="off_axis", label_en="Off",
                              label_zh="关闭")
""")
    load_all()
    reg = get_registry()
    # off_plug isn't enabled — its axis shouldn't appear
    assert all(a.id != "off_axis" for a in reg.axes())


def test_enable_makes_axis_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "enabled_plug", """
def register(api):
    api.register_rubric_axis(id="on_axis", label_en="On",
                              label_zh="开启")
""")
    load_all()
    reg = get_registry()
    assert reg.enable("enabled_plug")
    assert any(a.id == "on_axis" for a in reg.axes())
    # Persistence check — reload should preserve enabled state
    load_all()
    reg2 = get_registry()
    info = {p.name: p.enabled for p in reg2.info()}
    assert info.get("enabled_plug") is True


def test_disable_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "toggle_plug", """
def register(api):
    api.register_rubric_axis(id="x", label_en="X", label_zh="X")
""")
    load_all()
    reg = get_registry()
    reg.enable("toggle_plug")
    reg.disable("toggle_plug")
    load_all()
    info = {p.name: p.enabled for p in get_registry().info()}
    assert info.get("toggle_plug") is False


def test_broken_plugin_doesnt_kill_runtime(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "broken", "this is not python")
    _write_plugin(plugins_dir, "good", """
def register(api):
    api.register_rubric_axis(id="g", label_en="G", label_zh="G")
""")
    n = load_all()
    # Good plugin still loaded; broken is silently dropped with stderr log
    info = {p.name: p for p in get_registry().info()}
    assert "good" in info
    assert "broken" not in info


def test_plugin_no_register_fn_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "no_register", """
MANIFEST = {"name": "Forgot to register"}
""")
    load_all()
    info = {p.name for p in get_registry().info()}
    assert "no_register" not in info


# ---------------------------------------------------------------------------
# Event firing
# ---------------------------------------------------------------------------


def test_event_fires_to_enabled_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "evt_plug", """
events_seen = []
def register(api):
    api.on("after_decision_change",
           lambda evt: events_seen.append(evt))
""")
    load_all()
    reg = get_registry()
    reg.enable("evt_plug")
    fire_event("after_decision_change",
               {"filename": "a.jpg", "new_decision": "keep"})
    import sys
    mod = sys.modules.get("pixcull_plugin_evt_plug")
    assert mod is not None
    assert len(mod.events_seen) == 1
    assert mod.events_seen[0]["filename"] == "a.jpg"


def test_event_raising_handler_doesnt_crash_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plugins_dir = tmp_path / ".pixcull" / "plugins"
    _write_plugin(plugins_dir, "boom_plug", """
def register(api):
    def explode(evt):
        raise RuntimeError("oops")
    api.on("after_decision_change", explode)
""")
    _write_plugin(plugins_dir, "calm_plug", """
seen = []
def register(api):
    api.on("after_decision_change", lambda evt: seen.append(evt))
""")
    load_all()
    reg = get_registry()
    reg.enable("boom_plug")
    reg.enable("calm_plug")
    # Should NOT raise; calm_plug still gets the event
    fire_event("after_decision_change", {"filename": "a.jpg"})
    import sys
    calm = sys.modules.get("pixcull_plugin_calm_plug")
    assert calm is not None
    assert len(calm.seen) == 1


# ---------------------------------------------------------------------------
# Builtin example_wildlife sanity
# ---------------------------------------------------------------------------


def test_builtin_example_wildlife_loads(tmp_path, monkeypatch):
    """The shipped example_wildlife plugin loads without errors."""
    # Use a tmp HOME so user_plugins_dir is empty
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    load_all()
    info = {p.name: p for p in get_registry().info()}
    assert "example_wildlife" in info
    assert info["example_wildlife"].n_axes == 1
    assert info["example_wildlife"].n_cull_reasons == 2
    assert not info["example_wildlife"].enabled   # opt-in by default
