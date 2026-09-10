"""v3.44 — where a model file actually lives.

`RescorerConfig.model_path` has always defaulted to
`models/rescorer_v1.joblib`, which is relative to the working directory.
Inside a git checkout that resolves. After `pip install pixcull` it
never does, and the eight artifacts were not in the wheel either, so
every PyPI user has been running rule-only since the rescorer shipped —
loudly (`load_rescorer` prints `— running rule-only` to stderr) but
unmentioned by a README that lists the learned head as something you
get. Found by v3.38's reachability column.

The artifacts now live inside the package. The working-directory path
still wins when it exists, because that is where `scripts/train_*.py`
write and a photographer's own retrained head must beat the one we
shipped.
"""
from __future__ import annotations

from pathlib import Path

#: The copies that ship in the wheel.
PACKAGED_MODELS = Path(__file__).resolve().parent / "models"


def resolve(path: Path | str | None) -> Path | None:
    """Return where to actually read ``path`` from.

    Order: an absolute path as given; a relative path that exists in the
    working directory (a checkout, or a head the user trained); then the
    packaged copy of the same filename. When none of those exist the
    original is returned unchanged, so the caller's "not found" message
    still names what the user asked for rather than an internal path.
    """
    if path is None:
        return None
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p
    packaged = PACKAGED_MODELS / p.name
    return packaged if packaged.is_file() else p


# v3.44.1 — there is deliberately no directory-level version of this.
# The first cut had one, and it asked whether `models/` existed rather
# than whether the file did. In a checkout that directory exists and is
# empty, so it shadowed all six packaged per-axis models and a real run
# produced no `model_<axis>_stars`. Resolve one file at a time.


def from_pretrained(cls, name: str, **kwargs):
    """``cls.from_pretrained(name)``, but working when there is no network.

    v3.64 — the product's first claim is that it runs on your machine.
    It did not. `transformers` contacts the hub before it will use a
    model it already has: with the weights sitting in
    ``~/.cache/huggingface`` and the network away, every frame failed
    with

        OSError: Can't load processor for 'openai/clip-vit-base-patch32'

    and the run ended `Analyzed 0/32 images`. A photographer on a plane,
    or on a shoot with no signal — the situation local-first exists for —
    got nothing, with the model on their disk the whole time.

    Setting ``HF_HUB_OFFLINE=1`` fixes it, which is the tell: the files
    are there and usable, and only the lookup was failing. So try the
    normal path first, because it is the one that picks up an updated
    model, and fall back to the copy on disk rather than to an error.
    """
    try:
        return cls.from_pretrained(name, **kwargs)
    except Exception as first:          # noqa: BLE001 — any network shape
        try:
            return cls.from_pretrained(name, local_files_only=True, **kwargs)
        except Exception:               # noqa: BLE001
            # Genuinely not on disk. The first error describes what the
            # user has to fix (no network, and nothing cached), so it is
            # the one worth showing.
            raise first
