from __future__ import annotations

import pandas as pd


def to_session_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure Date index and sorted rows."""
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
    return df.sort_index()
