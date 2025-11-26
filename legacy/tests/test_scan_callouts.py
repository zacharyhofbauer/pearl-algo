from pathlib import Path

import pandas as pd

from pearlalgo.agents.research_agent import scan_for_entries
from pearlalgo.data_providers.local_csv_provider import LocalCSVProvider
from pearlalgo.strategies.base import BaseStrategy


class AlwaysLongStrategy(BaseStrategy):
    name = "always_long_for_scan"

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["entry"] = 1
        df["size"] = 1
        return df


def test_scan_for_entries_returns_callout(tmp_path: Path):
    csv = tmp_path / "ES.csv"
    csv.write_text("Date,Open,High,Low,Close,Volume\n2024-01-01,1,2,0.5,1.5,100\n")
    provider = LocalCSVProvider(tmp_path)
    results = scan_for_entries(
        symbols=["ES"],
        provider=provider,
        strategy_name="unused",
        strategy_factory=lambda: AlwaysLongStrategy(),
    )
    assert results, "Expected a callout"
    assert results[0]["direction"] == "LONG"
