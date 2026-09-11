"""v3.77 — the demo clip is real footage now, so it has to be safe by rule.

`24-transcript-edit.png` was an ffmpeg test pattern with synthesised
speech, because the panel it shows exists to put spoken words on screen
and real speech is a voiceprint. It read as a rendering fault on the
front page of the README, which is its own kind of untruth about the
product.

It is real footage with its own audio now, and the faces in it are
frosted. That turns a documentation problem into a publishing one, so
the properties that make it safe are asserted here rather than
remembered.

What went wrong while building it, both worth keeping:

**Screening at 640 px found a 29-second "face-free" run that had
bystanders with legible faces in it.** At 3840x2160 they are plain. The
repository already knew — "`face_count == 0` is not evidence of no face;
screen by eye at >=1400 px" — and the shortcut reproduced it anyway.

**Re-running the face detector on the frosted output is not a test.** It
reported a face on 569 of 620 frosted frames, correctly in its own
terms: a smooth oval in skin tones is what it looks for, so it fires on
the treatment. It cannot tell a face from a blurred face. The check that
means something is geometric — every box found in the original has to
lie inside the region that got frosted — and the script refuses to write
the clip when one does not.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "brand" / "make_demo_clip.py"
LEDGER = ROOT / "docs" / "screenshot-dispositions.tsv"
SHOT = "24-transcript-edit.png"


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _code() -> str:
    """Source with comments and docstrings stripped.

    This file's own explanation names the things it forbids, and the
    script's docstring describes the failures it protects against. A raw
    search finds those and passes on the prose.
    """
    src = _src()
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docstrings.add(d)
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    for d in docstrings:
        body = body.replace(d, "")
    return body


def test_the_script_exists_and_parses():
    assert SCRIPT.is_file(), "the clip builder is gone; the shot cannot be re-taken"
    ast.parse(_src())


def test_it_refuses_to_write_when_a_face_escapes_the_frosting():
    """The whole safety argument rests on this. A build that reports a
    miss and writes the file anyway is worse than no check at all."""
    code = _code()
    assert "escaped" in code, "the containment check is gone"
    m = re.search(r"if escaped:(.*?)\n    args\.out", code, re.S)
    assert m, "the containment check no longer guards the write"
    guarded = m.group(1)
    assert re.search(r"return\s+1", guarded), (
        "a face outside the frosted region no longer stops the write")


def test_it_does_not_verify_by_re_running_the_detector_on_the_output():
    """Stated as a rule because it is the plausible wrong answer, and I
    tried it first: the detector fires on the frosting itself."""
    code = _code()
    after = code.split("escaped = []", 1)
    assert len(after) == 2, "containment block not found"
    assert "FaceDetector.create_from_options" not in after[1], (
        "the script detects faces on its own output; that measures the "
        "blur, not the face")


def test_the_clip_carries_no_metadata_into_the_repository():
    """GoPro files carry GPMF telemetry, the original path and a device
    tag. None of that belongs in a public repository."""
    code = _code()
    assert '"-map_metadata", "-1"' in code, (
        "the encode no longer strips metadata; GPS and the source path "
        "would ride along")


def test_gaps_are_interpolated_rather_than_bounded():
    """The first cut took the union of every box within half a second,
    which on a moving subject buried a third of the frame under grey and
    still left the head showing above it."""
    code = _code()
    assert "wgt" in code and "prev" in code and "nxt" in code, (
        "gap filling is no longer interpolating between the nearest real "
        "detections")


def test_the_dilation_is_enough_to_cover_and_not_so_much_it_takes_over():
    m = re.search(r"^DILATE\s*=\s*([\d.]+)", _src(), re.M)
    assert m, "DILATE is gone"
    val = float(m.group(1))
    assert 0.12 <= val <= 0.35, (
        f"DILATE is {val}; below ~0.12 the treatment misses a turned chin, "
        "above ~0.35 it becomes the subject of the picture")


def test_the_shot_says_who_checked_it_and_when():
    """Real footage of a real person is a claim about screening, so the
    ledger has to carry one."""
    rows = [l for l in LEDGER.read_text(encoding="utf-8").splitlines()
            if l.startswith(SHOT)]
    assert rows, f"{SHOT} has no row in the ledger"
    parts = rows[0].split("\t")
    assert parts[1] in ("manual-verified", "scripted"), (
        f"{SHOT} is real footage and is dispositioned {parts[1]!r}")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[2]), (
        f"{SHOT}: 'last confirmed' is not a date")
    assert "frost" in parts[3].lower() or "遮" in parts[3], (
        f"{SHOT}: the note does not say the faces were treated")


def test_the_readme_says_the_footage_is_real_now():
    """It said 'synthetic end to end' for fourteen months. Leaving that
    in place beside real footage of a real person would be the same
    defect pointed the other way."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "synthetic end to end" not in text, (
        "the README still calls this capture synthetic")
    assert "make_demo_clip.py" in text, (
        "the README does not say how the clip is rebuilt")
