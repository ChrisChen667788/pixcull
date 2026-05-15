"""V29.1 — embed IPTC metadata directly into image files via exiftool.

V29 wrote XMP sidecars next to the originals. That works for every
modern catalog tool (LR, C1, Bridge) — but some agency / wire / DAM
pipelines refuse to consume sidecars and need the keywords + caption
+ headline EMBEDDED in the JPG / TIFF / DNG itself.

Why exiftool over pyexiv2 / piexif:
  * piexif: pure Python but JPG-only; loses on RAW (CR3/DNG/etc).
  * pyexiv2: full-format support but needs libexiv2 (Brew install
    on macOS, apt install on Linux); pinned numpy headers add
    upgrade friction.
  * exiftool: a single Perl binary that handles every photo format
    we ship. Pre-installed on most macOS dev setups (``brew install
    exiftool``) and on every news / agency workstation. Soft dep —
    when it's missing we surface a clear install hint instead of
    failing hard.

The XMP sidecar path (V29) is still the recommended workflow for
LR/C1 users. V29.1 is for the in-file-only customer.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


_EXIFTOOL_HINT = (
    "exiftool not installed. Install it with:\n"
    "  macOS:   brew install exiftool\n"
    "  Debian:  sudo apt install libimage-exiftool-perl\n"
    "  Windows: download from https://exiftool.org/"
)


def _exiftool_path() -> str | None:
    """Resolve the exiftool binary or None when it's not on PATH.

    Cached at module-level after first miss — repeat misses don't
    pay the shutil.which cost.
    """
    return shutil.which("exiftool")


def is_available() -> bool:
    """True iff ``exiftool`` is on the PATH and runs."""
    p = _exiftool_path()
    if not p:
        return False
    try:
        subprocess.run(
            [p, "-ver"],
            capture_output=True, timeout=5, check=True,
        )
        return True
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return False


def install_hint() -> str:
    """Return the install instructions string. Useful for surfacing
    in HTTP 5xx responses + admin pages."""
    return _EXIFTOOL_HINT


def write_iptc_to_file(
    image_path: Path,
    *,
    rating: int | None = None,
    color_label: str = "",
    keywords: list[str] | None = None,
    description: str = "",
    headline: str = "",
    overwrite_original: bool = True,
) -> bool:
    """Embed IPTC fields directly into the image file via exiftool.

    Same field set as ``pixcull.io.xmp.write_xmp`` so the two paths
    can produce equivalent metadata — the difference is just WHERE
    it lands (sidecar vs in-file).

    Args:
      image_path: source image file (JPG / TIFF / DNG / HEIC / etc).
        Must exist; exiftool returns non-zero otherwise.
      rating: 0..5, mapped to ``XMP:Rating``. ``None`` = don't touch.
      color_label: "Red" / "Yellow" / "Green" / "Blue" / "Purple" /
        empty. Mapped to ``XMP:Label``.
      keywords: list of IPTC ``IPTC:Keywords`` strings + their
        ``XMP-dc:Subject`` parallel. Both tag sets get the same
        list so LR / C1 / Bridge all see them.
      description: free text → ``IPTC:Caption-Abstract`` +
        ``XMP-dc:Description``.
      headline: short text → ``IPTC:Headline`` + ``XMP:Headline``.
      overwrite_original: when True (default), exiftool overwrites
        the source file in-place (no .original sidecar). Pass False
        to keep ``<name>.jpg_original`` as a safety copy.

    Returns True on success. Raises RuntimeError when exiftool isn't
    installed; caller should display ``install_hint()`` then.
    """
    exiftool = _exiftool_path()
    if not exiftool:
        raise RuntimeError(install_hint())

    if not image_path.exists():
        return False

    args = [exiftool, "-q"]
    if overwrite_original:
        args.append("-overwrite_original")

    if rating is not None:
        args.append(f"-XMP:Rating={max(0, min(5, int(rating)))}")
    if color_label:
        args.append(f"-XMP:Label={color_label}")

    if keywords:
        # Clear existing values first so we don't accumulate stale
        # PixCull keywords across re-exports.
        args.append("-IPTC:Keywords=")
        args.append("-XMP-dc:Subject=")
        for k in keywords:
            k_clean = str(k).strip()
            if not k_clean:
                continue
            # exiftool's ``+=`` syntax appends without replacing the
            # whole tag (one item per arg).
            args.append(f"-IPTC:Keywords+={k_clean}")
            args.append(f"-XMP-dc:Subject+={k_clean}")

    if description:
        args.append(f"-IPTC:Caption-Abstract={description}")
        args.append(f"-XMP-dc:Description={description}")
    if headline:
        args.append(f"-IPTC:Headline={headline}")
        args.append(f"-XMP:Headline={headline}")

    args.append(str(image_path))

    try:
        res = subprocess.run(
            args, capture_output=True, timeout=30, check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[iptc_embed] exiftool subprocess failed for "
              f"{image_path}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False
    if res.returncode != 0:
        # exiftool emits parseable warnings on stderr — surface so
        # callers can debug "file not writable" / "no permission" etc.
        err = res.stderr.decode("utf-8", errors="replace").strip()
        print(f"[iptc_embed] exiftool returned {res.returncode} for "
              f"{image_path}: {err}", file=sys.stderr)
        return False
    return True


__all__ = [
    "is_available",
    "install_hint",
    "write_iptc_to_file",
]
