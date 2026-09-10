"""v3.66 — the committed demo run must be provably local.

`samples/output` is a `pixcull run` over the owner's photographs, and it
is committed and published. Regenerating it is a normal thing to do —
v3.63 and v3.64 both did — and `pixcull run` with a key on the machine
and consent recorded once sends every frame to a cloud judge by default.
That happened during v3.64: six frames went to MiniMax before the run was
redone locally. Clearing `MINIMAX_API_KEY` does not prevent it; on macOS
the key is read from the keychain too, and consent from a previous month
still counts. `--vlm-mode off` is the switch that holds.

A README paragraph is not a guard — the person about to make this mistake
is regenerating a fixture, not reading the model card. So the property is
checked on the artifact, at the point it would become public: a run that
used the cloud judge carries nine extra `vlm_*` columns in `scores.csv`,
and a run that stayed on the machine carries none.

This does not prove no upload ever happened; it proves the run that
shipped did not use one. That is the part that can be checked from the
repository, and it is the part that would have caught v3.64.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "samples" / "output" / "scores.csv"

#: Written only when the cloud judge scored the frame.
CLOUD_MARKERS = ("vlm_", "judge_")


def test_the_committed_sample_run_has_no_cloud_judge_columns():
    assert SCORES.is_file(), "samples/output/scores.csv is missing"
    with SCORES.open(encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    leaked = [c for c in header
              if any(c.lower().startswith(m) for m in CLOUD_MARKERS)]
    assert not leaked, (
        "the committed demo run carries cloud-judge columns "
        f"{leaked} — it was produced by a run that uploaded the owner's "
        "photographs. Regenerate it with:\n"
        "    pixcull run samples/input --output /tmp/samrun --vlm-mode off\n"
        "and copy scores.csv / rubric.jsonl / embeddings.npz across. "
        "Unsetting MINIMAX_API_KEY is NOT enough — on macOS the key is "
        "also read from the keychain.")


def test_the_rebuild_recipe_pins_the_local_switch():
    """The instruction that tells the next person how to rebuild this is
    the only thing standing between them and the same upload, so it has
    to carry `--vlm-mode off` rather than assume they know."""
    recipe = (ROOT / "scripts" / "brand" / "prepare_samples.py").read_text("utf-8")
    assert "--vlm-mode off" in recipe, (
        "scripts/brand/prepare_samples.py does not tell the reader to "
        "rebuild the run with --vlm-mode off")


def test_both_front_doors_carry_the_keychain_caveat():
    """v3.52's defect: a claim corrected on one front door and not the
    other. The English README carried the warning that clearing the
    environment variable is not enough; the ModelScope model card — read
    by the audience whose MiniMax endpoint this actually is — did not."""
    # Each file is written in one language or the other, so accept the
    # word in either — asserting the English one everywhere is how the
    # first cut of this test failed on a page that carried the warning.
    missing = []
    for rel in ("README.md", "modelscope/README.md", "docs/USER-GUIDE.md"):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        if "keychain" not in text and "钥匙串" not in text:
            missing.append(rel)
    assert not missing, (
        "these do not warn that clearing MINIMAX_API_KEY is insufficient "
        f"because the key is also read from the OS keychain: {missing}")
