"""P-AI-1 — tests for the personalized keep/maybe-threshold derivation."""
from __future__ import annotations

from pathlib import Path

import pytest

from pixcull.scoring.personalized import (
    BASELINE_KEEP_RATE,
    MAX_THRESHOLD_SHIFT,
    MIN_ANNS_FOR_PERSONALIZATION,
    PersonalProfile,
    apply_threshold_shift,
    load_profile,
    profile_from_preferences,
    save_profile,
)


def test_below_min_annotations_no_shift():
    """User with < MIN_ANNS_FOR_PERSONALIZATION → not active, no shift."""
    prefs = {
        "total_human_annotations": 10,
        "scene_decision_counts": {"landscape": {"keep": 8, "maybe": 1, "cull": 1}},
        "avg_rubric_when": {"keep": {"technical": 4.5}, "cull": {"technical": 2.0}},
    }
    p = profile_from_preferences(prefs)
    assert not p.is_active()
    # apply_threshold_shift returns input unchanged
    base_keep, base_maybe = 0.60, 0.40
    out_keep, out_maybe = apply_threshold_shift(base_keep, base_maybe, p)
    assert out_keep == base_keep
    assert out_maybe == base_maybe


def test_permissive_user_lowers_threshold():
    """A user who keeps more than the machine keeps of the same photographs
    gets a NEGATIVE shift (lower threshold)."""
    prefs = {
        "total_human_annotations": 100,
        # 90 keep, 5 maybe, 5 cull = keep_rate 0.9
        "scene_decision_counts": {"landscape": {"keep": 90, "maybe": 5, "cull": 5}},
        "avg_rubric_when": {"keep": {"technical": 4.0}, "cull": {"technical": 2.0}},
        # v2.57 — volume alone no longer activates a profile. These tests
        # are about the SHIFT, so they declare a provenance that can carry
        # one; the gate itself is covered separately below.
        "label_provenance": "blind",
        # v3.99.1 — and what the machine kept of the same photographs.
        "machine_keep_rate": 0.70,
    }
    p = profile_from_preferences(prefs)
    assert p.is_active()
    assert p.keep_threshold_shift == pytest.approx(-0.08)    # -(0.9-0.7)*0.5, capped
    assert p.shift_basis == "machine" and p.machine_keep_rate == 0.7
    keep, maybe = apply_threshold_shift(0.60, 0.40, p)
    assert keep < 0.60   # lowered for permissive user
    assert maybe < 0.40


def test_strict_user_raises_threshold():
    """A user who keeps less than the machine gets a POSITIVE shift."""
    prefs = {
        "total_human_annotations": 100,
        "scene_decision_counts": {"landscape": {"keep": 20, "maybe": 20, "cull": 60}},
        "avg_rubric_when": {"keep": {"technical": 4.8}, "cull": {"technical": 2.0}},
        "label_provenance": "blind",
        "machine_keep_rate": 0.30,
    }
    p = profile_from_preferences(prefs)
    assert p.keep_threshold_shift == pytest.approx(0.05)     # -(0.2-0.3)*0.5
    keep, _ = apply_threshold_shift(0.60, 0.40, p)
    assert keep > 0.60


def test_the_shift_is_measured_against_the_machine_not_65():
    """v3.99.1. The owner keeps 76% and is stricter than the machine, which
    keeps more of the same frames: the fixed 65% called that permissive and
    lowered the bar; measured against the machine it raises it."""
    prefs = {"total_human_annotations": 100,
             "scene_decision_counts": {"x": {"keep": 76, "maybe": 0, "cull": 24}},
             "label_provenance": "blind", "machine_keep_rate": 0.84}
    p = profile_from_preferences(prefs)
    assert p.keep_rate > BASELINE_KEEP_RATE
    assert p.keep_threshold_shift == pytest.approx(0.04)     # stricter, not looser


def test_without_the_machines_verdicts_there_is_no_shift():
    """Nothing to compare with is no shift, not a fixed 65% standing in."""
    prefs = {"total_human_annotations": 100,
             "scene_decision_counts": {"x": {"keep": 95, "maybe": 0, "cull": 5}},
             "label_provenance": "blind"}
    p = profile_from_preferences(prefs)
    assert p.keep_threshold_shift == 0.0
    assert p.shift_basis == "none" and p.machine_keep_rate is None


def test_a_profile_from_before_says_what_its_shift_was_measured_against(tmp_path):
    """Owner's call (2026-10-29): the active profile is not reset. It loads
    as it was written, applies as it did, and says how to re-fit it."""
    import json
    from pixcull.scoring.personalized import legacy_shift_note
    path = tmp_path / "personal_profile.json"
    path.write_text(json.dumps({
        "schema": "pixcull.personal_profile.v1", "user_id": "local",
        "n_annotations": 70, "keep_rate": 0.97, "cull_rate": 0.03,
        "keep_threshold_shift": -0.08, "label_provenance": "blind"}), encoding="utf-8")
    old = load_profile(path)
    assert old.keep_threshold_shift == -0.08 and old.is_active()
    assert old.shift_basis == "" and old.machine_keep_rate is None
    assert "fixed 65%" in legacy_shift_note(old) and "calibrate" in legacy_shift_note(old)
    new = profile_from_preferences({"total_human_annotations": 100,
                                    "scene_decision_counts": {"x": {"keep": 95, "cull": 5}},
                                    "machine_keep_rate": 0.9})
    assert legacy_shift_note(new) == ""


def test_shift_capped_by_max():
    """Even extreme keep-rates can't move the threshold more than MAX_THRESHOLD_SHIFT."""
    extreme_prefs = {
        "total_human_annotations": 100,
        "scene_decision_counts": {"x": {"keep": 100, "maybe": 0, "cull": 0}},
        "avg_rubric_when": {"keep": {}, "cull": {}},
    }
    p = profile_from_preferences(extreme_prefs)
    assert abs(p.keep_threshold_shift) <= MAX_THRESHOLD_SHIFT + 1e-9


def test_most_cared_axis_from_keep_vs_cull_gap():
    """most_cared_axis is the axis with the largest keep-mean − cull-mean gap."""
    prefs = {
        "total_human_annotations": 100,
        "scene_decision_counts": {"x": {"keep": 50, "maybe": 30, "cull": 20}},
        "avg_rubric_when": {
            "keep": {"technical": 4.5, "subject": 4.7, "composition": 4.9, "light": 4.5, "moment": 4.0, "aesthetic": 4.0},
            "cull": {"technical": 3.5, "subject": 4.6, "composition": 1.0, "light": 4.0, "moment": 4.0, "aesthetic": 4.0},
        },
    }
    p = profile_from_preferences(prefs)
    # composition gap is 3.9 — bigger than every other
    assert p.most_cared_axis == "composition"


def test_save_and_load_round_trip(tmp_path: Path):
    p = PersonalProfile(
        user_id="testuser",
        n_annotations=120,
        keep_rate=0.55,
        cull_rate=0.20,
        keep_threshold_shift=0.05,
        axis_keep_means={"technical": 4.3, "subject": 4.5},
        axis_cull_means={"technical": 2.0, "subject": 3.0},
        most_cared_axis="technical",
        label_provenance="blind",
        machine_keep_rate=0.65,
        shift_basis="machine",
    )
    path = tmp_path / "profile.json"
    save_profile(p, path)
    loaded = load_profile(path)
    assert loaded is not None
    assert loaded.user_id == "testuser"
    assert loaded.n_annotations == 120
    assert loaded.keep_threshold_shift == 0.05
    assert loaded.axis_keep_means == {"technical": 4.3, "subject": 4.5}
    assert loaded.most_cared_axis == "technical"
    assert loaded.is_active()  # 120 >= MIN_ANNS_FOR_PERSONALIZATION
    assert (loaded.machine_keep_rate, loaded.shift_basis) == (0.65, "machine")


def test_load_profile_missing_returns_none(tmp_path: Path):
    assert load_profile(tmp_path / "ghost.json") is None


def test_load_profile_bad_schema(tmp_path: Path):
    """Wrong schema field returns None instead of crashing."""
    p = tmp_path / "bad.json"
    p.write_text('{"schema": "wrong", "user_id": "x"}', encoding="utf-8")
    assert load_profile(p) is None


def test_empty_preferences_defaults_to_baseline():
    """Zero annotations → keep_rate falls back to BASELINE, no shift."""
    p = profile_from_preferences({})
    assert p.n_annotations == 0
    assert not p.is_active()
    assert p.keep_threshold_shift == 0.0   # no shift when no signal


# ── v2.57: enough data was never the bar ──────────────────────────────

def _profile(**kw):
    from pixcull.scoring.personalized import PersonalProfile
    base = dict(user_id="local", n_annotations=608, keep_rate=0.7697,
                cull_rate=0.2039, keep_threshold_shift=-0.0599,
                axis_keep_means={}, axis_cull_means={}, most_cared_axis=None)
    base.update(kw)
    return PersonalProfile(**base)


def test_a_profile_learned_from_the_rule_stack_does_not_move_thresholds():
    """The fifth circular label set, and the first one that shipped.

    The author's own profile was built from 608 "corrections" whose
    labels were byte-identical to the rule stack's decisions. It
    concluded the photographer culls 20.4% and shifted the keep
    threshold -0.060 to match. A blind pass on the same photographer
    says 6.7% — off by 3.1x. The UI called it "tuned to you".

    Volume was the old gate and 608 rows clears it comfortably, which is
    exactly why volume is not the gate any more.
    """
    stale = _profile()                      # no provenance: pre-v2.57
    assert not stale.is_active()
    assert "provenance" in stale.inactive_reason()

    echoed = _profile(label_provenance="corrections")
    assert not echoed.is_active(), (
        "corrections made with the verdict on screen can echo it back")

    blind = _profile(label_provenance="blind")
    assert blind.is_active(), "a blind pass is exactly what we want to trust"


def test_volume_alone_is_not_enough_and_provenance_alone_is_not_either():
    from pixcull.scoring.personalized import MIN_ANNS_FOR_PERSONALIZATION
    thin = _profile(label_provenance="blind",
                    n_annotations=MIN_ANNS_FOR_PERSONALIZATION - 1)
    assert not thin.is_active()
    assert "annotations" in thin.inactive_reason()


def test_provenance_round_trips_through_disk(tmp_path):
    """A field that is dropped on save is a guard that lasts one process."""
    from pixcull.scoring.personalized import load_profile, save_profile
    p = tmp_path / "profile.json"
    save_profile(_profile(label_provenance="blind"), p)
    assert load_profile(p).label_provenance == "blind"
    assert load_profile(p).is_active()

    # And a file written before the field existed loads as untrusted,
    # rather than as trusted-by-omission.
    import json
    d = json.loads(p.read_text())
    del d["label_provenance"]
    p.write_text(json.dumps(d))
    assert load_profile(p).label_provenance == ""
    assert not load_profile(p).is_active()


def test_the_profile_api_says_its_shift_has_no_basis(tmp_path, monkeypatch):
    """v3.99.1. The preferences the server aggregates carry no machine
    verdicts, so the profile it derives has no shift and says why, rather
    than a fixed 65% standing in for the comparison."""
    import importlib.util
    import json as _json
    import sys
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_app_profile_api_test", repo / "pixcull" / "report" / "serve_app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    out = tmp_path / "run1" / "output"
    out.mkdir(parents=True)
    (out / "scores.csv").write_text("filename,scene\n" + "".join(
        f"f{i}.jpg,portrait\n" for i in range(60)), encoding="utf-8")
    (out / "annotations.jsonl").write_text("".join(
        _json.dumps({"filename": f"f{i}.jpg", "overall_label": "keep", "source": "human"}) + "\n"
        for i in range(60)), encoding="utf-8")
    monkeypatch.setattr(mod, "_DEMO_ROOT", tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/api/v1/users/profile"
        with urllib.request.urlopen(url, timeout=30) as r:
            got = _json.loads(r.read().decode("utf-8"))
    finally:
        srv.shutdown()
    assert got["keep_rate"] == 1.0
    assert got["shift_basis"] == "none" and got["machine_keep_rate"] is None
    assert got["keep_threshold_shift"] == 0.0
