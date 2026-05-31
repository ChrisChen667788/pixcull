"""pixcull.scoring — lazily-resolved package exports (PEP 562).

Importing this package (or a light submodule like ``color_grade``) must
stay cheap.  ``color_grade`` only needs numpy, yet eagerly importing the
four public names here used to drag in ``decision`` → ``pixcull.config``
→ pydantic, plus ``aesthetic``.  That made
``from pixcull.scoring.color_grade import …`` — done lazily on every
``/video/data`` request in ``serve_demo`` and on cold CLI paths — pay
for modules it never uses (and, before the aesthetic fix, ~30s of torch).

So the four public names are resolved on first attribute access via
``__getattr__`` instead of at package import.  Every existing access
pattern still works:

  * ``from pixcull.scoring import AestheticScorer``  → __getattr__
  * ``import pixcull.scoring; pixcull.scoring.decide`` → __getattr__
  * ``import pixcull.scoring.color_grade``           → normal submodule
    import, no longer triggers decision/fusion/aesthetic.
"""
from typing import TYPE_CHECKING

__all__ = ["AestheticScorer", "Decision", "decide", "fuse_score"]

if TYPE_CHECKING:  # keep static analysers / IDEs seeing the real symbols
    from pixcull.scoring.aesthetic import AestheticScorer
    from pixcull.scoring.decision import Decision, decide
    from pixcull.scoring.fusion import fuse_score


def __getattr__(name: str):
    if name == "AestheticScorer":
        from pixcull.scoring.aesthetic import AestheticScorer
        return AestheticScorer
    if name in ("Decision", "decide"):
        from pixcull.scoring import decision
        return getattr(decision, name)
    if name == "fuse_score":
        from pixcull.scoring.fusion import fuse_score
        return fuse_score
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
