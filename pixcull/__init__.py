"""PixCull — AI photo culling & scoring."""

import sys

# v2.19 — single-source the version from package metadata (pyproject);
# the literal is only the fallback for running from a raw source tree.
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("pixcull")
except Exception:
    __version__ = "2.28.0"


def _check_numpy_compatibility() -> None:
    """ROADMAP INFRA-5 — runtime guard against the numpy 2.x regression.

    We've been bitten twice (V18.1 and V22.0.1) when a transitive
    ``pip install`` upgraded numpy to 2.x. The symptoms are subtle:
    mediapipe imports cleanly but its face detector silently returns
    empty results, and pre-V18.3 rescorer joblibs fail to unpickle
    because the ``numpy.random._pcg64.PCG64`` paths differ between
    1.x and 2.x. Neither failure is loud — face_count just stays 0
    on all images, the rescorer silently falls back to rule-only.

    Pin in pyproject.toml is ``numpy>=1.26,<2``, but a third-party
    install command (``pip install some-other-package``) can still
    blow past the pin. We don't fail hard here — that would break
    perfectly fine pipelines that don't touch faces — but we DO
    print a loud warning on every import so the regression is
    visible at the top of the log.
    """
    try:
        import numpy
    except ImportError:
        return  # numpy missing is a different problem; let downstream report
    ver = getattr(numpy, "__version__", "")
    try:
        major = int(ver.split(".")[0])
    except (ValueError, IndexError):
        return
    if major >= 2:
        print(
            "\n"
            "⚠ PixCull: numpy " + ver + " detected.\n"
            "  mediapipe (face detector) and the V18.3 rescorer joblibs\n"
            "  need numpy 1.x. Run:\n"
            "      pip install 'numpy<2'\n"
            "  to fix. Without this, faces won't be detected (face_count\n"
            "  will be 0 on every photo) and the rescorer falls back to\n"
            "  rule-only mode.\n",
            file=sys.stderr,
        )


_check_numpy_compatibility()
