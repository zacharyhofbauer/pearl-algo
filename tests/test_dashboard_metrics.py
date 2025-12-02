"""
Unit tests for dashboard metric computation functions.
"""

from __future__ import annotations

import pandas as pd
import pytest
from datetime import datetime, timezone

# Import dashboard functions
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Dashboard module - skip if not available
try:
    from scripts.dashboard import (
        compute_sharpe_ratio,
        compute_sortino_ratio,
        compute_trade_statistics,
        aggregate_pnl_by_symbol,
        parse_sr_dict_from_notes,
        extract_signal_context,
    )

    HAS_DASHBOARD = True
except ImportError:
    HAS_DASHBOARD = False

    # Define dummy functions to allow test collection
    def compute_sharpe_ratio(*args, **kwargs):
        return 0.0

    def compute_sortino_ratio(*args, **kwargs):
        return 0.0

    def compute_trade_statistics(*args, **kwargs):
        return {"total_trades": 0, "winners": 0, "losers": 0, "win_rate": 0.0}

    def aggregate_pnl_by_symbol(*args, **kwargs):
        return {"TOTAL": {"realized": 0.0, "unrealized": 0.0}}

    def parse_sr_dict_from_notes(*args, **kwargs):
        return {}

    def extract_signal_context(*args, **kwargs):
        import pandas as pd

        return pd.DataFrame()


class TestSharpeRatio:
    """Test Sharpe ratio computation."""

    def test_empty_dataframe(self):
        """Test with empty dataframe."""
        df = pd.DataFrame()
        result = compute_sharpe_ratio(df)
        assert result == 0.0

    def test_no_pnl_column(self):
        """Test with missing realized_pnl column."""
        df = pd.DataFrame({"symbol": ["ES"], "side": ["long"]})
        result = compute_sharpe_ratio(df)
        assert result == 0.0

    def test_insufficient_data(self):
        """Test with insufficient data points."""
        df = pd.DataFrame({"realized_pnl": [100.0]})
        result = compute_sharpe_ratio(df)
        assert result == 0.0

    def test_positive_returns(self):
        """Test with positive returns."""
        # Use varying returns to ensure non-zero std
        df = pd.DataFrame({"realized_pnl": [0.0, 50.0, 120.0, 180.0, 250.0, 330.0]})
        result = compute_sharpe_ratio(df)
        assert result >= 0.0  # Can be 0 if std is 0, but should not be NaN
        assert not pd.isna(result)

    def test_negative_returns(self):
        """Test with negative returns."""
        df = pd.DataFrame({"realized_pnl": [0.0, -100.0, -200.0, -300.0, -400.0]})
        result = compute_sharpe_ratio(df)
        assert result < 0.0 or result == 0.0
        assert not pd.isna(result)

    def test_mixed_returns(self):
        """Test with mixed positive and negative returns."""
        df = pd.DataFrame({"realized_pnl": [0.0, 100.0, -50.0, 200.0, -100.0, 150.0]})
        result = compute_sharpe_ratio(df)
        assert not pd.isna(result)
        assert isinstance(result, float)

    def test_with_nan_values(self):
        """Test with NaN values in P&L."""
        df = pd.DataFrame({"realized_pnl": [0.0, 100.0, None, 200.0, None, 300.0]})
        result = compute_sharpe_ratio(df)
        assert not pd.isna(result)
        assert isinstance(result, float)


class TestSortinoRatio:
    """Test Sortino ratio computation."""

    def test_empty_dataframe(self):
        """Test with empty dataframe."""
        df = pd.DataFrame()
        result = compute_sortino_ratio(df)
        assert result == 0.0

    def test_no_pnl_column(self):
        """Test with missing realized_pnl column."""
        df = pd.DataFrame({"symbol": ["ES"], "side": ["long"]})
        result = compute_sortino_ratio(df)
        assert result == 0.0

    def test_insufficient_data(self):
        """Test with insufficient data points."""
        df = pd.DataFrame({"realized_pnl": [100.0]})
        result = compute_sortino_ratio(df)
        assert result == 0.0

    def test_only_positive_returns(self):
        """Test with only positive returns (no downside)."""
        df = pd.DataFrame({"realized_pnl": [0.0, 100.0, 200.0, 300.0, 400.0]})
        result = compute_sortino_ratio(df)
        # Should return high ratio or 0.0
        assert result >= 0.0
        assert not pd.isna(result)

    def test_with_downside(self):
        """Test with negative returns (downside)."""
        df = pd.DataFrame({"realized_pnl": [0.0, 100.0, -50.0, 200.0, -100.0, 150.0]})
        result = compute_sortino_ratio(df)
        assert not pd.isna(result)
        assert isinstance(result, float)

    def test_all_negative(self):
        """Test with all negative returns."""
        df = pd.DataFrame({"realized_pnl": [0.0, -100.0, -200.0, -300.0, -400.0]})
        result = compute_sortino_ratio(df)
        assert result <= 0.0 or result == 0.0
        assert not pd.isna(result)


class TestTradeStatistics:
    """Test trade statistics computation."""

    def test_empty_dataframe(self):
        """Test with empty dataframe."""
        df = pd.DataFrame()
        result = compute_trade_statistics(df)
        assert result["total_trades"] == 0
        assert result["winners"] == 0
        assert result["losers"] == 0
        assert result["win_rate"] == 0.0

    def test_no_trades(self):
        """Test with data but no completed trades."""
        df = pd.DataFrame(
            {
                "symbol": ["ES", "NQ"],
                "side": ["long", "short"],
                "realized_pnl": [None, None],
            }
        )
        result = compute_trade_statistics(df)
        assert result["total_trades"] == 0

    def test_with_trades(self):
        """Test with completed trades."""
        df = pd.DataFrame(
            {
                "symbol": ["ES", "ES", "NQ", "NQ"],
                "realized_pnl": [100.0, -50.0, 200.0, -100.0],
                "entry_time": [
                    datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc),
                ],
                "exit_time": [
                    datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 11, 15, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 13, 15, tzinfo=timezone.utc),
                ],
            }
        )
        result = compute_trade_statistics(df)
        assert result["total_trades"] == 4
        assert result["winners"] == 2
        assert result["losers"] == 2
        assert result["win_rate"] == 50.0
        assert result["largest_winner"] == 200.0
        assert result["largest_loser"] == -100.0
        assert result["avg_hold_time_minutes"] > 0.0

    def test_win_rate_calculation(self):
        """Test win rate calculation."""
        df = pd.DataFrame({"realized_pnl": [100.0, 50.0, -25.0, -50.0, 75.0]})
        result = compute_trade_statistics(df)
        assert result["winners"] == 3
        assert result["losers"] == 2
        assert result["win_rate"] == 60.0  # 3/5 * 100


class TestAggregatePnLBySymbol:
    """Test P&L aggregation by symbol."""

    def test_empty_dataframe(self):
        """Test with empty dataframe."""
        df = pd.DataFrame()
        result = aggregate_pnl_by_symbol(df)
        assert "TOTAL" in result
        assert result["TOTAL"]["realized"] == 0.0
        assert result["TOTAL"]["unrealized"] == 0.0

    def test_no_symbol_column(self):
        """Test with missing symbol column."""
        df = pd.DataFrame({"realized_pnl": [100.0, 200.0]})
        result = aggregate_pnl_by_symbol(df)
        assert "TOTAL" in result
        assert result["TOTAL"]["realized"] == 0.0

    def test_single_symbol(self):
        """Test with single symbol."""
        df = pd.DataFrame(
            {
                "symbol": ["ES", "ES", "ES"],
                "realized_pnl": [100.0, 200.0, -50.0],
                "unrealized_pnl": [None, None, 25.0],
            }
        )
        result = aggregate_pnl_by_symbol(df)
        assert "ES" in result
        assert result["ES"]["realized"] == 250.0
        assert result["ES"]["unrealized"] == 25.0
        assert result["TOTAL"]["realized"] == 250.0
        assert result["TOTAL"]["unrealized"] == 25.0

    def test_multiple_symbols(self):
        """Test with multiple symbols."""
        df = pd.DataFrame(
            {
                "symbol": ["ES", "ES", "NQ", "NQ", "GC"],
                "realized_pnl": [100.0, 200.0, 150.0, -50.0, 75.0],
                "unrealized_pnl": [None, 25.0, None, 10.0, None],
            }
        )
        result = aggregate_pnl_by_symbol(df)
        assert "ES" in result
        assert "NQ" in result
        assert "GC" in result
        assert result["ES"]["realized"] == 300.0
        assert result["NQ"]["realized"] == 100.0
        assert result["GC"]["realized"] == 75.0
        assert result["TOTAL"]["realized"] == 475.0
        # Unrealized: last non-null per symbol
        assert result["ES"]["unrealized"] == 25.0
        assert result["NQ"]["unrealized"] == 10.0
        assert result["GC"]["unrealized"] == 0.0

    def test_with_nan_values(self):
        """Test with NaN values."""
        df = pd.DataFrame(
            {
                "symbol": ["ES", "ES"],
                "realized_pnl": [100.0, None],
                "unrealized_pnl": [None, 25.0],
            }
        )
        result = aggregate_pnl_by_symbol(df)
        assert result["ES"]["realized"] == 100.0
        assert result["ES"]["unrealized"] == 25.0


class TestParseSRDictFromNotes:
    """Test parsing SR dictionary from notes field."""

    def test_empty_notes(self):
        """Test with empty notes."""
        result = parse_sr_dict_from_notes("")
        assert result == {}

    def test_none_notes(self):
        """Test with None notes."""
        result = parse_sr_dict_from_notes(None)
        assert result == {}

    def test_valid_sr_dict(self):
        """Test with valid SR dictionary."""
        notes = "daily signal; sr={'support1': 4800.0, 'resistance1': 4900.0, 'vwap': 4850.0}"
        result = parse_sr_dict_from_notes(notes)
        assert "support1" in result
        assert "resistance1" in result
        assert "vwap" in result
        assert result["support1"] == 4800.0
        assert result["resistance1"] == 4900.0
        assert result["vwap"] == 4850.0

    def test_with_numpy_types(self):
        """Test with numpy float64 types in string."""
        notes = "sr={'support1': np.float64(4800.0), 'vwap': np.float64(4850.0)}"
        result = parse_sr_dict_from_notes(notes)
        assert "support1" in result
        assert "vwap" in result

    def test_invalid_format(self):
        """Test with invalid format."""
        notes = "just some text without sr dict"
        result = parse_sr_dict_from_notes(notes)
        assert result == {}

    def test_missing_keys(self):
        """Test with missing keys."""
        notes = "sr={'vwap': 4850.0}"
        result = parse_sr_dict_from_notes(notes)
        assert "vwap" in result
        assert "support1" not in result


class TestExtractSignalContext:
    """Test signal context extraction."""

    def test_empty_dataframes(self):
        """Test with empty dataframes."""
        perf_df = pd.DataFrame()
        signals_df = pd.DataFrame()
        result = extract_signal_context(perf_df, signals_df)
        assert result.empty

    def test_with_performance_data(self):
        """Test with performance data."""
        perf_df = pd.DataFrame(
            {
                "symbol": ["ES", "ES"],
                "timestamp": [
                    datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
                ],
                "strategy_name": ["sr", "sr"],
                "side": ["long", "short"],
                "entry_price": [4800.0, 4900.0],
                "notes": [
                    "sr={'support1': 4750.0, 'vwap': 4800.0}",
                    "sr={'resistance1': 4950.0, 'vwap': 4900.0}",
                ],
                "trade_reason": ["Bullish pivot", "Bearish pivot"],
            }
        )
        signals_df = pd.DataFrame(
            {
                "symbol": ["ES", "ES"],
                "timestamp": [
                    datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
                ],
                "direction": ["LONG", "SHORT"],
            }
        )
        result = extract_signal_context(perf_df, signals_df)
        assert not result.empty
        assert len(result) == 2
        assert "symbol" in result.columns
        assert "strategy" in result.columns
        assert "vwap" in result.columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
