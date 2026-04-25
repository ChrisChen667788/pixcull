"""HTML report with thumbnails + score breakdown. V0.3+."""

from pathlib import Path

import pandas as pd


def export_html(df: pd.DataFrame, out_path: Path, thumb_px: int = 256) -> Path:
    raise NotImplementedError("V0.3: jinja2 HTML report")
