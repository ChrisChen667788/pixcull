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


#: v3.28 — keywords PixCull owns inside a photograph. Everything else in
#: the file belongs to whoever put it there.
PIXCULL_KEYWORD_PREFIX = "PixCull:"


def read_embedded(image_path) -> dict:
    """Rating, label and keywords already inside the file.

    Returns {} when exiftool is unavailable or the read fails.  {} means
    "we could not tell", and every caller treats that as "assume nothing
    is there" — which is the WRONG side to be wrong on, so the write path
    only clears anything when `preserve_existing` is explicitly False.
    """
    import json as _json
    exiftool = _exiftool_path()
    if exiftool is None:
        return {}
    try:
        res = subprocess.run(
            [exiftool, "-q", "-j", "-XMP:Rating", "-XMP:Label",
             "-IPTC:Keywords", "-XMP-dc:Subject", str(image_path)],
            capture_output=True, timeout=30, check=False, text=True)
        rows = _json.loads(res.stdout or "[]")
    except Exception:  # noqa: BLE001
        return {}
    if not rows:
        return {}
    row = rows[0]
    kw = row.get("Keywords") or row.get("Subject") or []
    if isinstance(kw, str):
        kw = [kw]
    try:
        rating = int(row.get("Rating") or 0)
    except (TypeError, ValueError):
        rating = 0
    return {"rating": rating,
            "color_label": str(row.get("Label") or "").strip(),
            "keywords": [str(k) for k in kw]}


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


def build_args(exiftool: str, image_path, *, rating=None, color_label="",
               keywords=None, description="", headline="",
               overwrite_original: bool = True,
               preserve_existing: bool = True, prior=None) -> list[str]:
    """The exiftool command line, as a pure function.

    Extracted so the v3.28 rules can be asserted without exiftool
    installed — which it is not on every machine, and a rule about
    somebody's photographs should not go untested because a binary is
    missing.  `prior` is injected for the same reason.
    """
    prior = prior if prior is not None else (
        read_embedded(image_path) if preserve_existing else {})
    args = [exiftool, "-q"]
    if overwrite_original:
        args.append("-overwrite_original")

    # v3.28 — this path writes INTO the photograph, so the v3.23 rule
    # applies with more force here than it did to a sidecar.
    #
    # What it used to do: overwrite XMP:Rating and XMP:Label
    # unconditionally, and clear IPTC:Keywords and XMP-dc:Subject
    # entirely before appending PixCull's.  A photographer who had
    # keyworded and rated their originals in Lightroom or Capture One
    # lost all of it — inside the file, with `-overwrite_original`, so
    # not even exiftool's `_original` backup existed to recover from.
    #
    # Same treatment as the sidecar: their rating and label win, their
    # keywords stay, and only PixCull's own are replaced.
    if rating is not None and not prior.get("rating"):
        args.append(f"-XMP:Rating={max(0, min(5, int(rating)))}")
    if color_label and not prior.get("color_label"):
        args.append(f"-XMP:Label={color_label}")

    if keywords:
        if preserve_existing:
            # Remove ONLY our own previous keywords, by value, so a
            # re-export does not leave PixCull:keep beside PixCull:cull
            # and does not touch anything the photographer added.
            for k in prior.get("keywords", []):
                if str(k).startswith(PIXCULL_KEYWORD_PREFIX):
                    args.append(f"-IPTC:Keywords-={k}")
                    args.append(f"-XMP-dc:Subject-={k}")
        else:
            args.append("-IPTC:Keywords=")
            args.append("-XMP-dc:Subject=")
        existing = set(prior.get("keywords", []))
        for k in keywords:
            k_clean = str(k).strip()
            if not k_clean or (preserve_existing and k_clean in existing
                               and not k_clean.startswith(
                                   PIXCULL_KEYWORD_PREFIX)):
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
    return args


def write_iptc_to_file(
    image_path: Path,
    *,
    rating: int | None = None,
    color_label: str = "",
    keywords: list[str] | None = None,
    description: str = "",
    headline: str = "",
    overwrite_original: bool = True,
    preserve_existing: bool = True,
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

    args = build_args(
        exiftool, image_path, rating=rating, color_label=color_label,
        keywords=keywords, description=description, headline=headline,
        overwrite_original=overwrite_original,
        preserve_existing=preserve_existing)

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
