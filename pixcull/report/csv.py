from pathlib import Path

import pandas as pd


def export_csv(df: pd.DataFrame, out_path: Path) -> Path:
    """Write scores CSV, dropping binary-heavy columns (embedding, mask)."""
    drop = [c for c in ("embedding", "mask") if c in df.columns]
    exp = df.drop(columns=drop).copy()
    for col in exp.columns:
        if exp[col].apply(lambda x: isinstance(x, (dict, list))).any():
            exp[col] = exp[col].apply(str)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exp.to_csv(out_path, index=False)
    return out_path
