"""PixCull — AI photo culling & scoring."""

import sys

# v2.19 — single-source the version from package metadata (pyproject);
# the literal is only the fallback for running from a raw source tree.
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("pixcull")
except Exception:
    __version__ = "3.69.0"

#: The band pyproject.toml pins. Kept next to the check that reads it so
#: the two cannot say different things — until v3.64 this guard was still
#: telling people to run ``pip install 'numpy<2'`` while the pin had moved
#: to 2.x, which is advice that breaks a working install.
_NUMPY_MIN = (2, 0)
_NUMPY_MAX_EXCLUSIVE = (2, 5)


def _check_numpy_compatibility() -> None:
    """ROADMAP INFRA-5 — runtime guard against a numpy outside the pin.

    The pin is enforced at install time, but a later third-party
    ``pip install`` can still move numpy underneath us, and the failures
    it causes are quiet ones: mediapipe imports cleanly and its face
    detector returns nothing, so ``face_count`` stays 0 on every frame;
    the rescorer joblibs fail to unpickle and scoring silently drops to
    rule-only. Nothing in a normal run says why.

    v3.64 — the band is ``>=2.0,<2.5`` now, and both directions are worth
    warning about. Below 2.0 is the old world the rescorer models are no
    longer serialized for; 2.5 and above is where numba refuses to import
    ("Numba needs NumPy 2.4 or less"), which takes the audio path on
    video with it. We don't fail hard — plenty of pipelines never touch
    faces, audio or the rescorer — but we say so, loudly, once.
    """
    try:
        import numpy
    except ImportError:
        return  # numpy missing is a different problem; let downstream report
    ver = getattr(numpy, "__version__", "")
    try:
        parts = tuple(int(x) for x in ver.split(".")[:2])
    except (ValueError, IndexError):
        return
    if len(parts) < 2 or _NUMPY_MIN <= parts < _NUMPY_MAX_EXCLUSIVE:
        return
    want = ">=%d.%d,<%d.%d" % (_NUMPY_MIN + _NUMPY_MAX_EXCLUSIVE)
    print(
        "\n"
        "⚠ PixCull: numpy " + ver + " is outside the supported range.\n"
        "  PixCull is tested against numpy " + want + ".\n"
        "  Run:\n"
        "      pip install 'numpy" + want + "'\n"
        "  Without this, faces may not be detected (face_count stays 0),\n"
        "  the rescorer can fall back to rule-only, and the audio path\n"
        "  used by video review may fail to import.\n",
        file=sys.stderr,
    )


_check_numpy_compatibility()
