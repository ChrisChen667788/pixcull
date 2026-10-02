"""Shim — the audit moved into the package in v3.93.

``python scripts/cli_audit.py …`` keeps working; the implementation is
``pixcull/report/cli_audit.py`` (``python -m pixcull.report.cli_audit``),
where an installed copy of PixCull can find it.
"""
import sys
from pathlib import Path

# Run by path from a checkout that is not installed: put the checkout on
# the import path, the way ``python -m`` from the repo root would.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pixcull.report.cli_audit import main  # noqa: E402

if __name__ == "__main__":
    main()
