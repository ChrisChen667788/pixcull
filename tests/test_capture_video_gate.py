"""v3.87 — the screenshot gate that stands in for a face detector.

`make_demo_clip.py` cannot certify the demo footage: on one frame of the
v3.77 clip its detector returned two boxes, both on the subject's coat,
none on her face, and the containment check passed at 100% while the
face was legible and unfrosted. Both models on this machine miss that
face entirely. So the thing that decides what may be published is a
person's eyes plus `docs/demo-clip-frames.tsv`, and these tests are what
stop that from quietly becoming decorative.
"""

from __future__ import annotations

import ast
import importlib.util
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "brand" / "capture_video_shots.py"
LEDGER = REPO / "docs" / "demo-clip-frames.tsv"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("capture_video_shots",
                                                  SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(SCRIPT.read_text("utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from {SCRIPT.name}")


def _calls(fn: ast.FunctionDef) -> set[str]:
    return {n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


@pytest.mark.parametrize("shot", ["shot_18", "shot_19"])
def test_every_video_shot_passes_through_the_gate(shot):
    """Parsed, not grepped — a mention in a docstring is not a call."""
    assert "gate_visible_frames" in _calls(_fn(shot)), (
        f"{shot} writes a screenshot of the demo footage without asking "
        f"whether the frames in it have been looked at")


@pytest.mark.parametrize("shot", ["shot_18", "shot_19"])
def test_the_gate_runs_before_the_screenshot(shot):
    """Order matters: gating after the write leaves the file on disk."""
    fn = _fn(shot)
    gate = shot_at = None
    for stmt in ast.walk(fn):
        if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) \
                and stmt.func.id == "gate_visible_frames":
            gate = stmt.lineno
        if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) \
                and stmt.func.id == "save_shot":
            shot_at = stmt.lineno
    assert gate is not None and shot_at is not None
    assert gate < shot_at, (
        f"{shot} takes the screenshot before checking the frames in it")


def test_no_shot_writes_a_file_around_save_shot():
    """Every write goes through save_shot, which applies the width cap.

    The first cut of this script called `page.screenshot` directly and
    committed three 2880 px files; `tests/test_image_weight.py` caught
    it. This is the same rule stated where it is easy to break.
    """
    tree = ast.parse(SCRIPT.read_text("utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef)
                and node.name.startswith("shot_")):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) \
                    and isinstance(call.func, ast.Attribute) \
                    and call.func.attr == "screenshot":
                raise AssertionError(
                    f"{node.name} calls page.screenshot directly; use "
                    f"save_shot so the width cap applies")


def test_ledger_is_parseable_and_not_empty(mod, monkeypatch):
    rows = mod._screened()
    assert rows, f"{LEDGER.name} lists no screened frames"
    for sha in rows:
        assert len(sha) == 16 and all(c in "0123456789abcdef" for c in sha), \
            f"not a sha256 prefix: {sha!r}"


def test_an_unlisted_frame_is_not_silently_allowed(mod, tmp_path,
                                                   monkeypatch):
    """The failure mode that matters: the ledger is missing or unreadable.

    An empty ledger must refuse everything, not allow everything — the
    same shape as "the detector found nothing, so nothing escaped".
    """
    monkeypatch.setattr(mod, "SCREENED", tmp_path / "nope.tsv")
    assert mod._screened() == {}

    run = tmp_path / "run" / "video_frames" / "clip"
    run.mkdir(parents=True)
    (run / "frame_000001.jpg").write_bytes(b"not really a jpeg")
    sha = mod._frame_sha(tmp_path / "run", "frame_000001")
    assert sha and sha not in mod._screened()


def test_missing_frame_file_is_a_refusal_not_a_pass(mod, tmp_path):
    assert mod._frame_sha(tmp_path, "frame_999999") is None


def test_the_grade_check_measures_pixels_not_means():
    """v3.87 — the first version compared the two frames' mean channel
    values, which a colour-shuffling grade passes as "no change" and a
    snow-filled frame damps toward zero for every grade. The check reads
    per-pixel difference now; this fails if it drifts back."""
    src = SCRIPT.read_text("utf-8")
    assert "_DIFF_JS" in src and "_MEAN_RGB_JS" not in src
    fn = _fn("shot_19")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "_DIFF_JS" in names, "shot_19 no longer runs the pixel diff"


# v3.103 — the transcript shot was the other way into the same footage.
# README told readers to rebuild the clip and re-take 24 with
# capture_transcript_edit.py, which wrote whatever was on screen; its
# caption said "the faces are frosted", which is what v3.87 disproved.

TX_SCRIPT = REPO / "scripts" / "brand" / "capture_transcript_edit.py"


def _tx_main() -> ast.FunctionDef:
    for node in ast.parse(TX_SCRIPT.read_text("utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError(f"main() is gone from {TX_SCRIPT.name}")


def test_the_transcript_shot_is_gated_before_it_is_written():
    fn = _tx_main()
    lines = {}
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            # ast.walk is breadth-first, not line order: keep the earliest.
            lines[call.func.id] = min(call.lineno,
                                      lines.get(call.func.id, call.lineno))
    assert "gate_visible_frames" in lines, (
        "capture_transcript_edit.py writes 24 without asking whether the "
        "frames on screen have been screened")
    assert "save_shot" in lines and lines["gate_visible_frames"] < lines["save_shot"], (
        "the transcript shot is written before its frames are checked")


def test_the_transcript_shot_writes_only_through_save_shot():
    for call in ast.walk(_tx_main()):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                and call.func.attr == "screenshot":
            raise AssertionError("capture_transcript_edit.py calls "
                                 "page.screenshot directly; use save_shot")


def test_the_readme_does_not_vouch_for_the_frosting():
    """What v3.87 established: the frosting misses faces, and what clears
    a frame is a person and the ledger. The caption says that now."""
    text = (REPO / "README.md").read_text("utf-8")
    assert "faces are frosted" not in text.lower()
    caption = text[text.index("24-transcript-edit.png"):][:2500]
    assert "demo-clip-frames.tsv" in caption, (
        "the caption under 24 no longer names what clears a frame")


def test_the_gate_itself_refuses_and_passes(mod, tmp_path, monkeypatch):
    """End to end through gate_visible_frames, not its helpers: both
    capture scripts now depend on this one function."""
    import hashlib
    clip = tmp_path / "run" / "video_frames" / "clip"
    clip.mkdir(parents=True)
    (clip / "frame_000001.jpg").write_bytes(b"screened")
    (clip / "frame_000002.jpg").write_bytes(b"not screened")
    ok = hashlib.sha256(b"screened").hexdigest()[:16]
    monkeypatch.setattr(mod, "_screened", lambda: {ok: "looked at"})

    class Page:
        def __init__(self, ids):
            self.ids = ids

        def evaluate(self, _js):
            return self.ids

    run = tmp_path / "run"
    assert mod.gate_visible_frames(Page(["frame_000001"]), run, "s") == ["frame_000001"]
    with pytest.raises(AssertionError, match="frame_000002"):
        mod.gate_visible_frames(Page(["frame_000001", "frame_000002"]), run, "s")
    with pytest.raises(AssertionError, match="could not tell"):
        mod.gate_visible_frames(Page([]), run, "s")
    with pytest.raises(AssertionError, match="no file"):
        mod.gate_visible_frames(Page(["frame_000009"]), run, "s")
