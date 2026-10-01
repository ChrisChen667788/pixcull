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

import os
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
    """``cls.from_pretrained(name)``, reading the copy on disk first.

    v3.64 — the product's first claim is that it runs on your machine.
    It did not. `transformers` contacts the hub before it will use a
    model it already has: with the weights sitting in
    ``~/.cache/huggingface`` and the network away, every frame failed
    with

        OSError: Can't load processor for 'openai/clip-vit-base-patch32'

    and the run ended `Analyzed 0/32 images`. v3.64 made it fall back to
    the disk after the network attempt failed.

    v3.89 — that still paid for the attempt, every time. Blocking the
    socket layer on a warm cache and running 32 photos: 48 connection
    attempts, all from here, CLIP and DINOv2 in each of four workers. A
    refused connection fails at once; an unanswered one waits for the OS
    connect timeout, about 21 s on Windows, which is issue #3: 149 s for
    nothing on a machine with every model on disk.

    So the disk comes first and the network is for a model that is not
    there. Reading the cache first also means a model cannot change
    between two runs of the same folder because the hub published a new
    revision — the verdict follows the model, and v3.84 spent a release
    making verdicts reproducible. To update a cached model, delete it from
    the hub cache (or ``huggingface-cli download <name>``) and run again.
    """
    # Loading a cached `.bin` checkpoint makes `transformers` start a
    # background thread that asks the hub to convert the repo to
    # safetensors "for next time" — `local_files_only` does not stop it,
    # only offline mode or this flag does. A local-first tool should not
    # be triggering conversion jobs on someone else's servers, and on a
    # machine with no network it is one more connection that times out.
    # setdefault: an explicit value in the user's environment wins.
    os.environ.setdefault("DISABLE_SAFETENSORS_CONVERSION", "1")
    if kwargs.get("local_files_only"):
        return cls.from_pretrained(name, **kwargs)
    try:
        return cls.from_pretrained(name, local_files_only=True, **kwargs)
    except Exception as not_on_disk:    # noqa: BLE001 — any cache-miss shape
        try:
            return cls.from_pretrained(name, **kwargs)
        except Exception as network:    # noqa: BLE001
            # Not cached and not downloadable. The network error names
            # what the user has to fix, so it is the one raised; the cache
            # miss rides along as the cause.
            raise network from not_on_disk
