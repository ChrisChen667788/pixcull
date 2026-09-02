"""v3.11 — reference frames from this photographer, and the circularity
that would have made them worthless.

v3.4 put worked critiques into the prompt as text.  This is the other
half: reference images.  The canon says what good composition is; an
exemplar shows the model one this photographer kept and one they binned.

The obvious design — a per-axis bank of their highest and lowest scoring
frames per axis — cannot be built honestly.  `annotations.jsonl` holds
keep/maybe/cull and nothing per-axis; the axis stars are
`rubric_decompose`'s own output with `source="auto"`.  Selecting on them
would calibrate the model against the system's own opinion while
presenting itself as the photographer's judgement.
"""
import json
import tempfile
from pathlib import Path

from pixcull.scoring import exemplar_bank as EB


def _run(tmp: Path, records, images=()) -> Path:
    out = tmp / "shoot" / "output"
    out.mkdir(parents=True)
    (out / "annotations.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8")
    for name in images:
        (out / name).write_bytes(b"\xff\xd8\xff")
    return tmp


def test_selection_never_reads_an_axis_column():
    """The load-bearing guard. A future edit adding "just one" axis-based
    tie-break would reintroduce the circularity silently.

    Checked against the parsed code with docstrings and comments removed,
    not against the file text — the module talks about axis stars at
    length precisely because it must not read them, and a text search
    would be satisfied by deleting the explanation.
    """
    import ast
    import inspect

    def _code_only(fn):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                node.value.value = ""      # drop docstrings
        return ast.unparse(tree)

    src = _code_only(EB.select) + _code_only(EB._human_decisions)
    for forbidden in ("rubric_", "stars", "scores.csv", "axes"):
        assert forbidden not in src, (
            f"selection touches {forbidden!r} — the axis stars are the "
            f"system's own output and selecting on them makes the "
            f"grounding a mirror"
        )


def test_only_the_photographers_own_decisions_are_used():
    with tempfile.TemporaryDirectory() as d:
        root = _run(Path(d), [
            {"filename": "a.jpg", "overall_label": "keep", "source": "human"},
            {"filename": "b.jpg", "overall_label": "cull",
             "source": "compare_rejected"},
            {"filename": "c.jpg", "overall_label": "cull",
             "source": "lr_catalog"},
            {"filename": "d.jpg", "overall_label": "cull", "source": "human"},
        ], images=["a.jpg", "b.jpg", "c.jpg", "d.jpg"])
        got = {e.filename for e in EB.select(root)}
        assert got == {"a.jpg", "d.jpg"}


def test_a_record_with_no_source_is_treated_as_a_hand_annotation():
    """Records predate v3.9's source field; they were all hand-made."""
    with tempfile.TemporaryDirectory() as d:
        root = _run(Path(d), [{"filename": "a.jpg", "overall_label": "keep"}],
                    images=["a.jpg"])
        assert [e.filename for e in EB.select(root)] == ["a.jpg"]


def test_relabelling_to_maybe_removes_a_frame_from_the_bank():
    with tempfile.TemporaryDirectory() as d:
        root = _run(Path(d), [
            {"filename": "a.jpg", "overall_label": "keep", "source": "human"},
            {"filename": "a.jpg", "overall_label": "maybe", "source": "human"},
        ], images=["a.jpg"])
        assert EB.select(root) == []


def test_a_frame_whose_image_is_gone_is_skipped_not_guessed_at():
    """An exemplar pointing at the wrong photograph is worse than none —
    the label travels with it into the prompt."""
    with tempfile.TemporaryDirectory() as d:
        root = _run(Path(d),
                    [{"filename": "missing.jpg", "overall_label": "keep",
                      "source": "human"}])
        assert EB.select(root) == []


def test_the_bank_is_one_of_each_side():
    with tempfile.TemporaryDirectory() as d:
        recs = [{"filename": f"k{i}.jpg", "overall_label": "keep",
                 "source": "human"} for i in range(5)]
        recs += [{"filename": f"c{i}.jpg", "overall_label": "cull",
                  "source": "human"} for i in range(5)]
        root = _run(Path(d), recs, images=[r["filename"] for r in recs])
        got = EB.select(root)
        assert len(got) == 2
        assert {e.decision for e in got} == {"keep", "cull"}


def test_the_note_says_which_frame_to_judge():
    """Three photographs and no reason to treat two differently is a good
    way to have the model critique the wrong one."""
    note = EB.prompt_note([EB.Exemplar(Path("a"), "keep", "a"),
                           EB.Exemplar(Path("b"), "cull", "b")])
    assert "只评第一张" in note
    assert "不要描述它们" in note


def test_no_exemplars_produces_no_note():
    assert EB.prompt_note([]) == ""


# -- the call -------------------------------------------------------

def test_reference_frames_are_attached_after_the_frame_under_judgement():
    """The prompt says "只评第一张". A reference arriving first makes that
    sentence point at the wrong photograph."""
    import inspect
    from pixcull.scoring import m3
    src = inspect.getsource(m3.MiniMaxM3Judge.score)
    first = src.index('"url": self._image_data_uri(image_path)')
    later = src.index("for ref in (reference_images or []):")
    assert first < later


def test_attaching_references_changes_the_cache_slot():
    """Otherwise turning grounding on reads back the ungrounded answer
    and the A/B compares an arm against itself."""
    from pixcull.scoring.m3 import _refs_key, cache_extra
    base = dict(model="m", scene="s", vertical="v", evidence_arm="technical",
                evidence_len=1, prompt_override=None)
    assert cache_extra(**base) != cache_extra(
        **base, refs=_refs_key(["a.jpg"]))


def test_different_reference_sets_do_not_collide():
    from pixcull.scoring.m3 import _refs_key
    assert _refs_key(["a.jpg"]) != _refs_key(["b.jpg"])
    assert _refs_key(["a.jpg", "b.jpg"]) != _refs_key(["b.jpg", "a.jpg"])
    assert _refs_key([]) == "" and _refs_key(None) == ""


def test_an_unreadable_reference_does_not_fail_the_judgement():
    """Grounding is an improvement to a judgement, not a precondition."""
    import inspect
    from pixcull.scoring import m3
    src = inspect.getsource(m3.MiniMaxM3Judge.score)
    block = src[src.index("for ref in (reference_images or []):"):]
    assert "except Exception" in block.split("messages =")[0]
