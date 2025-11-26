import pandas as pd

from pearlalgo.agents.backtest_agent import run_backtest
from pearlalgo.agents.strategy_loader import list_strategies


def make_dummy_data(rows: int = 120) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02 09:30", periods=rows, freq="15min")
    base = 4800.0
    close = base + pd.Series(range(rows)) * 0.5
    data = pd.DataFrame(
        {
            "Date": idx,
            "Open": close + 0.1,
            "High": close + 0.3,
            "Low": close - 0.3,
            "Close": close,
            "Volume": 1_000,
        }
    ).set_index("Date")
    return data


def test_run_backtest_smoke():
    data = make_dummy_data()
    strategy_name = list_strategies()[0]
    stats, _ = run_backtest(data, strategy_name, symbol="ES", cash=100_000, commission=0.0)
    assert "Return [%]" in stats.index
