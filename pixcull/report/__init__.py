"""Report exporters.

v2.40.2 — ``export_html`` was removed, not implemented.  It was a V0.3
stub that raised NotImplementedError, yet sat in ``__all__`` as public
API: anyone who found it got a guaranteed crash.  The HTML report it was
a placeholder for has existed for years as the review workspace
(``pixcull/report/templates/results.html``, served by ``pixcull serve``),
so the stub was advertising a gap that isn't one.
"""

from pixcull.report.csv import export_csv

__all__ = ["export_csv"]
