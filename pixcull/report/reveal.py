"""Open a frame's original file from a run.

The page never serves the original. ``/full/`` is a 1600px render, and
a run stores only the ``path`` column in ``scores.csv`` plus a
thumbnail — PixCull does not copy the photographer's RAW files. So
"show me the file" means: look the filename up in that column and hand
the resolved path to the desktop file manager.

A filename is only resolvable when it is a row of this run. The lookup
returns ``None`` for anything else, which also means a crafted name
cannot reach the filesystem.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path


def source_path_for(
    output_dir: Path,
    filename: str,
    base: Path | None = None,
) -> Path | None:
    """The original file for ``filename`` in this run, or ``None``.

    ``base`` resolves the relative paths a demo run writes
    (``samples/input/A.JPG``); absolute paths are used as they are.
    """
    if not filename or "/" in filename or "\\" in filename:
        return None
    path = Path(output_dir) / "scores.csv"
    if not path.is_file():
        return None
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("filename") or "") != filename:
                    continue
                raw = (row.get("path") or "").strip()
                if not raw:
                    return None
                found = Path(raw)
                if not found.is_absolute():
                    found = (base / found) if base else (Path.cwd() / found)
                return found
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    return None


def reveal_command(target: Path) -> list[str]:
    """The platform's "show this file" command."""
    if sys.platform == "darwin":
        return ["open", "-R", str(target)]
    if sys.platform.startswith("win"):
        # explorer wants the argument joined, not split.
        return ["explorer", f"/select,{target}"]
    return ["xdg-open", str(target.parent)]


def reveal_in_file_manager(target: Path) -> None:
    """Best effort: the caller reports success from the file, not this."""
    subprocess.run(reveal_command(target), check=False)
