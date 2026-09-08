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


def resolve_dir(model_dir: Path | str | None) -> Path:
    """Same rule for a directory of per-axis models."""
    if model_dir is None:
        return PACKAGED_MODELS
    d = Path(model_dir)
    if d.is_absolute() or d.is_dir():
        return d
    return PACKAGED_MODELS if PACKAGED_MODELS.is_dir() else d
