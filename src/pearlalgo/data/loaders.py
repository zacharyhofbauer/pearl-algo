from __future__ import annotations

import pandas as pd
from pathlib import Path


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.title()
    df = df.drop(columns=[c for c in df.columns if "Unnamed" in c])
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
    return df
