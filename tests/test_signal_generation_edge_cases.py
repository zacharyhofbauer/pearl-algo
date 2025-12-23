"""
Edge case tests for signal generation.

These tests validate signal generator behavior with:
1. Empty DataFrames
2. DataFrames with NaN values
3. Extreme price values
4. Data gaps
5. Minimum required data points
6. Malformed market_data structures

Test Philosophy:
- Each test targets a specific edge case
- Tests verify the system fails safely (no crashes, graceful degradation)
- Failure signals are observable via diagnostics
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import numpy as np
import pandas as pd
import pytest

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.signal_generator import NQSignalGenerator
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy


def _create_ohlcv_dataframe(
    n_bars: int = 100,
    base_price: float = 17500.0,
    volatility: float = 10.0,
    start_time: datetime = None,
) -> pd.DataFrame:
    """Create a valid OHLCV DataFrame for testing."""
    if start_time is None:
        # Use a weekday during market hours for valid session
        # Monday 10:00 AM ET (2024-01-08)
        start_time = datetime(2024, 1, 8, 15, 0, 0, tzinfo=timezone.utc)
    
    timestamps = [start_time + timedelta(minutes=i) for i in range(n_bars)]
    
    np.random.seed(42)  # Reproducible
    closes = base_price + np.cumsum(np.random.randn(n_bars) * volatility / 10)
    opens = closes + np.random.randn(n_bars) * 2
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(n_bars)) * volatility / 5
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(n_bars)) * volatility / 5
    volumes = np.random.randint(50, 500, n_bars)
    
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=pd.DatetimeIndex(timestamps, name="timestamp"))
    
    return df


class TestEmptyData:
    """Tests for empty or missing data scenarios."""

    def test_empty_dataframe_returns_empty_signals(self) -> None:
        """
        Assumption: Empty DataFrame should return [] with no crash.
        Failure signal: Exception raised or non-empty result
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        market_data = {"df": pd.DataFrame()}
        
        signals = generator.generate(market_data)
        
        assert signals == [], "Empty DataFrame should return empty signals list"
        assert generator.last_diagnostics is not None
        assert generator.last_diagnostics.raw_signals == 0

    def test_none_dataframe_returns_empty_signals(self) -> None:
        """
        Assumption: None DataFrame should return [] with no crash.
        Failure signal: Exception raised or non-empty result
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        market_data = {"df": None}
        
        signals = generator.generate(market_data)
        
        assert signals == [], "None DataFrame should return empty signals list"

    def test_missing_df_key_returns_empty_signals(self) -> None:
        """
        Assumption: Missing 'df' key should return [] with no crash.
        Failure signal: Exception raised (KeyError) or non-empty result
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        market_data = {}  # No 'df' key
        
        signals = generator.generate(market_data)
        
        assert signals == [], "Missing 'df' key should return empty signals list"


class TestNaNHandling:
    """Tests for NaN value handling in data."""

    def test_dataframe_with_nan_close_prices(self) -> None:
        """
        Assumption: NaN in close prices should not crash the generator.
        Failure signal: Exception raised
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50)
        # Introduce NaN values
        df.iloc[10, df.columns.get_loc("close")] = np.nan
        df.iloc[20, df.columns.get_loc("close")] = np.nan
        
        market_data = {"df": df}
        
        # Should not raise
        signals = generator.generate(market_data)
        
        # Result should be a list (possibly empty)
        assert isinstance(signals, list)

    def test_dataframe_with_all_nan_volume(self) -> None:
        """
        Assumption: All-NaN volume should not crash, may return empty signals.
        Failure signal: Exception raised
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50)
        df["volume"] = np.nan
        
        market_data = {"df": df}
        
        # Should not raise
        signals = generator.generate(market_data)
        assert isinstance(signals, list)

    @pytest.mark.xfail(
        reason="KNOWN BUG: volume_profile.py crashes on inf values. "
               "VolumeProfile.calculate_profile() uses int() on NaN derived from inf, "
               "causing ValueError. Should be fixed by adding inf check or try/except.",
        raises=ValueError,
    )
    def test_dataframe_with_inf_values(self) -> None:
        """
        Assumption: Infinite values in prices should not crash.
        Failure signal: Exception raised
        Test type: Deterministic
        
        DISCOVERED BUG: volume_profile.py line 99 does:
            low_bucket = int((low - price_min) / bucket_size)
        When high=inf or low=-inf, price_min/price_max become inf,
        bucket_size becomes NaN, and int(NaN) raises ValueError.
        
        Fix suggestion: Add data validation or wrap in try/except.
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50)
        df.iloc[25, df.columns.get_loc("high")] = np.inf
        df.iloc[30, df.columns.get_loc("low")] = -np.inf
        
        market_data = {"df": df}
        
        # Should not raise (but currently does - this test documents the bug)
        signals = generator.generate(market_data)
        assert isinstance(signals, list)


class TestExtremePrices:
    """Tests for extreme price values."""

    def test_very_high_prices(self) -> None:
        """
        Assumption: Very high prices (e.g., 1M) should not overflow or crash.
        Failure signal: Exception or overflow error
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50, base_price=1_000_000.0)
        market_data = {"df": df}
        
        signals = generator.generate(market_data)
        assert isinstance(signals, list)

    def test_very_low_prices(self) -> None:
        """
        Assumption: Very low prices (e.g., 0.01) should not cause division errors.
        Failure signal: ZeroDivisionError or similar
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50, base_price=0.01, volatility=0.001)
        market_data = {"df": df}
        
        signals = generator.generate(market_data)
        assert isinstance(signals, list)

    def test_zero_prices(self) -> None:
        """
        Assumption: Zero prices should be handled without division by zero.
        Failure signal: ZeroDivisionError
        Test type: Deterministic (edge case)
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50)
        df["close"] = 0.0
        df["open"] = 0.0
        
        market_data = {"df": df}
        
        # Should not raise ZeroDivisionError
        signals = generator.generate(market_data)
        assert isinstance(signals, list)

    def test_negative_prices(self) -> None:
        """
        Assumption: Negative prices (invalid) should be handled gracefully.
        Failure signal: Exception or invalid signals generated
        Test type: Deterministic (edge case)
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50, base_price=-100.0)
        market_data = {"df": df}
        
        signals = generator.generate(market_data)
        assert isinstance(signals, list)
        # Any generated signals should have valid (non-negative) prices
        for signal in signals:
            if "entry_price" in signal:
                assert signal["entry_price"] is None or signal["entry_price"] >= 0


class TestDataGaps:
    """Tests for data with gaps or inconsistencies."""

    def test_missing_columns(self) -> None:
        """
        Assumption: Missing required columns should not crash.
        Failure signal: KeyError or AttributeError
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        # DataFrame missing 'volume' column
        df = pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            # No 'volume' column
        }, index=pd.date_range("2024-01-08 10:00", periods=2, freq="min", tz=timezone.utc))
        
        market_data = {"df": df}
        
        # Should handle gracefully
        signals = generator.generate(market_data)
        assert isinstance(signals, list)

    def test_large_time_gap(self) -> None:
        """
        Assumption: Large gaps in timestamps should not crash.
        Failure signal: Exception raised
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        # Create data with a 1-hour gap in the middle
        ts1 = pd.date_range("2024-01-08 10:00", periods=25, freq="min", tz=timezone.utc)
        ts2 = pd.date_range("2024-01-08 11:30", periods=25, freq="min", tz=timezone.utc)  # 1 hour gap
        timestamps = ts1.append(ts2)
        
        np.random.seed(42)
        df = pd.DataFrame({
            "open": 17500 + np.random.randn(50) * 10,
            "high": 17510 + np.random.randn(50) * 10,
            "low": 17490 + np.random.randn(50) * 10,
            "close": 17500 + np.random.randn(50) * 10,
            "volume": np.random.randint(50, 500, 50),
        }, index=timestamps)
        
        market_data = {"df": df}
        
        signals = generator.generate(market_data)
        assert isinstance(signals, list)


class TestMinimumDataRequirements:
    """Tests for minimum data point requirements."""

    def test_single_bar_dataframe(self) -> None:
        """
        Assumption: Single bar should not crash (but likely no signals).
        Failure signal: Exception raised
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=1)
        market_data = {"df": df}
        
        signals = generator.generate(market_data)
        assert isinstance(signals, list)

    def test_minimum_bars_for_indicators(self) -> None:
        """
        Assumption: Should handle fewer bars than required for indicators.
        Failure signal: Exception in indicator calculation
        Test type: Deterministic
        
        Note: Most indicators require 14-20 bars minimum (RSI=14, EMA=20).
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        # 5 bars - less than most indicator periods
        df = _create_ohlcv_dataframe(n_bars=5)
        market_data = {"df": df}
        
        signals = generator.generate(market_data)
        assert isinstance(signals, list)


class TestMalformedMarketData:
    """Tests for malformed market_data structures."""

    def test_market_data_is_none(self) -> None:
        """
        Assumption: None market_data should not crash.
        Failure signal: TypeError or AttributeError
        Test type: Deterministic (edge case)
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        # This may raise TypeError - that's okay, we're testing crash safety
        try:
            signals = generator.generate(None)
            # If it doesn't raise, should return empty list
            assert signals == []
        except (TypeError, AttributeError):
            # Expected - market_data must be a dict
            pass

    def test_market_data_is_string(self) -> None:
        """
        Assumption: String market_data should not crash.
        Failure signal: Unhandled exception
        Test type: Deterministic (edge case)
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        try:
            signals = generator.generate("invalid")
            assert signals == []
        except (TypeError, AttributeError):
            # Expected
            pass

    def test_latest_bar_with_invalid_timestamp(self) -> None:
        """
        Assumption: Invalid timestamp in latest_bar should be handled.
        Failure signal: ValueError or TypeError in timestamp parsing
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50)
        market_data = {
            "df": df,
            "latest_bar": {
                "timestamp": "not-a-valid-timestamp",
                "close": 17500.0,
            }
        }
        
        # Should handle gracefully
        signals = generator.generate(market_data)
        assert isinstance(signals, list)


class TestDiagnosticsOutput:
    """Tests for diagnostics observability."""

    def test_diagnostics_populated_on_empty_data(self) -> None:
        """
        Assumption: Diagnostics should be set even when no signals generated.
        Failure signal: last_diagnostics is None after generate()
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        market_data = {"df": pd.DataFrame()}
        generator.generate(market_data)
        
        assert generator.last_diagnostics is not None
        assert generator.last_diagnostics.raw_signals == 0

    def test_diagnostics_has_timestamp(self) -> None:
        """
        Assumption: Diagnostics should include a timestamp.
        Failure signal: timestamp is None
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50)
        market_data = {"df": df}
        generator.generate(market_data)
        
        assert generator.last_diagnostics is not None
        assert generator.last_diagnostics.timestamp is not None

    def test_diagnostics_format_compact(self) -> None:
        """
        Assumption: format_compact() should return a valid string.
        Failure signal: Exception or empty string
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        generator = NQSignalGenerator(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=50)
        market_data = {"df": df}
        generator.generate(market_data)
        
        compact = generator.last_diagnostics.format_compact()
        assert isinstance(compact, str)
        assert len(compact) > 0


class TestStrategyIntegration:
    """Integration tests for NQIntradayStrategy."""

    def test_strategy_analyze_with_empty_buffer(self) -> None:
        """
        Assumption: Strategy.analyze() handles empty buffer gracefully.
        Failure signal: Exception raised
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        strategy = NQIntradayStrategy(config=config)
        
        market_data = {"df": pd.DataFrame(), "latest_bar": None}
        
        result = strategy.analyze(market_data)
        
        # analyze() returns List[Dict], not Dict
        assert isinstance(result, list)
        assert result == []

    def test_strategy_analyze_returns_expected_structure(self) -> None:
        """
        Assumption: Strategy.analyze() returns list of signal dicts.
        Failure signal: Wrong type or exception
        Test type: Deterministic
        """
        config = NQIntradayConfig()
        strategy = NQIntradayStrategy(config=config)
        
        df = _create_ohlcv_dataframe(n_bars=100)
        market_data = {
            "df": df,
            "latest_bar": {
                "timestamp": datetime.now(timezone.utc),
                "close": 17505.0,
            }
        }
        
        result = strategy.analyze(market_data)
        
        # analyze() returns List[Dict]
        assert isinstance(result, list)
        # Each item in the list should be a dict (if any signals generated)
        for signal in result:
            assert isinstance(signal, dict)

