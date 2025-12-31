"""
Edge case stress tests for chart generation.

This module tests chart behavior under challenging conditions:
- High volatility data (extreme price moves)
- Data gaps (missing time periods)
- Zero/minimal volume bars
- Overlapping session boundaries
- Extreme price levels (very high/low values)

These tests verify the chart generator handles edge cases gracefully
without crashing or producing invalid output.

Usage:
    pytest tests/test_chart_edge_cases.py -v
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from tests.fixtures.deterministic_data import SEED


def generate_high_volatility_data(
    num_bars: int = 100,
    base_price: float = 25000.0,
    seed: int = SEED,
) -> pd.DataFrame:
    """
    Generate extreme volatility data with 50-100+ point candles.
    
    This simulates major news events or flash crashes where
    price moves are 5-10x normal volatility.
    """
    np.random.seed(seed)
    base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
    
    data = []
    price = base_price
    
    for i in range(num_bars):
        ts = base_timestamp + timedelta(minutes=5 * i)
        
        # Extreme moves: 50-150 point candles (vs normal 5-15)
        change = np.random.randn() * 50
        price += change
        
        # Huge candle bodies
        candle_range = abs(np.random.randn() * 60) + 30
        
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.4
            close_price = price + candle_range * 0.4
        else:
            open_price = price + candle_range * 0.4
            close_price = price - candle_range * 0.4
        
        # Extreme wicks
        high = max(open_price, close_price) + abs(np.random.randn() * 30) + 20
        low = min(open_price, close_price) - abs(np.random.randn() * 30) - 20
        
        volume = int(np.random.uniform(10000, 50000))  # High volume during volatility
        
        data.append({
            "timestamp": ts,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })
    
    return pd.DataFrame(data)


def generate_data_with_gaps(
    num_bars: int = 100,
    gap_size: int = 10,
    gap_positions: Optional[List[int]] = None,
    base_price: float = 25000.0,
    seed: int = SEED,
) -> pd.DataFrame:
    """
    Generate data with time gaps (missing bars).
    
    This simulates data gaps from connectivity issues or
    exchange outages.
    """
    np.random.seed(seed)
    base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
    
    gap_positions = gap_positions or [30, 60]  # Default gaps at bar 30 and 60
    
    data = []
    price = base_price
    current_bar = 0
    
    for i in range(num_bars):
        # Add gap if at gap position
        if current_bar in gap_positions:
            current_bar += gap_size  # Skip forward
        
        ts = base_timestamp + timedelta(minutes=5 * current_bar)
        
        change = np.random.randn() * 8
        price += change
        
        candle_range = abs(np.random.randn() * 6) + 4
        
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.3
            close_price = price + candle_range * 0.3
        else:
            open_price = price + candle_range * 0.3
            close_price = price - candle_range * 0.3
        
        high = max(open_price, close_price) + abs(np.random.randn() * 3) + 2
        low = min(open_price, close_price) - abs(np.random.randn() * 3) - 2
        
        volume = int(np.random.uniform(1000, 5000))
        
        data.append({
            "timestamp": ts,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })
        
        current_bar += 1
    
    return pd.DataFrame(data)


def generate_zero_volume_data(
    num_bars: int = 100,
    zero_volume_pct: float = 0.3,
    base_price: float = 25000.0,
    seed: int = SEED,
) -> pd.DataFrame:
    """
    Generate data with many zero-volume bars.
    
    This simulates low-liquidity periods or data issues.
    """
    np.random.seed(seed)
    base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
    
    data = []
    price = base_price
    
    for i in range(num_bars):
        ts = base_timestamp + timedelta(minutes=5 * i)
        
        change = np.random.randn() * 5
        price += change
        
        candle_range = abs(np.random.randn() * 4) + 2
        
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.3
            close_price = price + candle_range * 0.3
        else:
            open_price = price + candle_range * 0.3
            close_price = price - candle_range * 0.3
        
        high = max(open_price, close_price) + abs(np.random.randn() * 2) + 1
        low = min(open_price, close_price) - abs(np.random.randn() * 2) - 1
        
        # Zero volume for specified percentage of bars
        if np.random.random() < zero_volume_pct:
            volume = 0
        else:
            volume = int(np.random.uniform(500, 3000))
        
        data.append({
            "timestamp": ts,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })
    
    return pd.DataFrame(data)


def generate_extreme_price_data(
    num_bars: int = 100,
    base_price: float = 100000.0,  # Very high price
    seed: int = SEED,
) -> pd.DataFrame:
    """
    Generate data with extreme (very high) price levels.
    
    This tests label formatting and axis scaling with large numbers.
    """
    np.random.seed(seed)
    base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
    
    data = []
    price = base_price
    
    for i in range(num_bars):
        ts = base_timestamp + timedelta(minutes=5 * i)
        
        change = np.random.randn() * 50
        price += change
        
        candle_range = abs(np.random.randn() * 30) + 20
        
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.3
            close_price = price + candle_range * 0.3
        else:
            open_price = price + candle_range * 0.3
            close_price = price - candle_range * 0.3
        
        high = max(open_price, close_price) + abs(np.random.randn() * 15) + 10
        low = min(open_price, close_price) - abs(np.random.randn() * 15) - 10
        
        volume = int(np.random.uniform(1000, 5000))
        
        data.append({
            "timestamp": ts,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })
    
    return pd.DataFrame(data)


def generate_flat_market_data(
    num_bars: int = 100,
    base_price: float = 25000.0,
    seed: int = SEED,
) -> pd.DataFrame:
    """
    Generate data with minimal price movement (flat/ranging market).
    
    This tests label merging and zone visibility when price is tight.
    """
    np.random.seed(seed)
    base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
    
    data = []
    price = base_price
    
    for i in range(num_bars):
        ts = base_timestamp + timedelta(minutes=5 * i)
        
        # Very small moves (0.5-2 points vs normal 5-15)
        change = np.random.randn() * 0.5
        price += change
        # Mean revert to stay in tight range
        price = base_price + (price - base_price) * 0.95
        
        candle_range = abs(np.random.randn() * 1) + 0.5
        
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.3
            close_price = price + candle_range * 0.3
        else:
            open_price = price + candle_range * 0.3
            close_price = price - candle_range * 0.3
        
        high = max(open_price, close_price) + abs(np.random.randn() * 0.5) + 0.25
        low = min(open_price, close_price) - abs(np.random.randn() * 0.5) - 0.25
        
        volume = int(np.random.uniform(500, 2000))
        
        data.append({
            "timestamp": ts,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })
    
    return pd.DataFrame(data)


def generate_test_signal(data: pd.DataFrame, direction: str = "long") -> Dict:
    """Generate a test signal for chart generation."""
    entry_idx = len(data) // 2
    entry_price = float(data["close"].iloc[entry_idx])
    entry_timestamp = data["timestamp"].iloc[entry_idx]
    
    if direction == "long":
        stop_loss = entry_price - 15.0
        take_profit = entry_price + 22.5
    else:
        stop_loss = entry_price + 15.0
        take_profit = entry_price - 22.5
    
    return {
        "type": "momentum_breakout",
        "direction": direction,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "timestamp": entry_timestamp.isoformat() if hasattr(entry_timestamp, "isoformat") else str(entry_timestamp),
        "reason": "test_edge_case",
    }


class TestHighVolatilityCharts:
    """Test chart generation with extreme volatility data."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_high_volatility_entry_chart(self):
        """Verify entry charts render with extreme volatility data."""
        data = generate_high_volatility_data()
        signal = generate_test_signal(data, direction="long")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "High volatility entry chart failed"
        assert Path(chart_path).exists()
        assert Path(chart_path).stat().st_size > 0
        
        Path(chart_path).unlink(missing_ok=True)
    
    def test_high_volatility_dashboard_chart(self):
        """Verify dashboard charts render with extreme volatility data."""
        data = generate_high_volatility_data(num_bars=200)
        
        chart_path = self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=100,
            title_time="12:00 UTC",
        )
        
        assert chart_path is not None, "High volatility dashboard chart failed"
        assert Path(chart_path).exists()
        
        Path(chart_path).unlink(missing_ok=True)


class TestDataGapCharts:
    """Test chart generation with missing data periods."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_data_gap_entry_chart(self):
        """Verify entry charts render with data gaps."""
        data = generate_data_with_gaps(num_bars=100, gap_size=20)
        signal = generate_test_signal(data, direction="long")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Data gap entry chart failed"
        assert Path(chart_path).exists()
        
        Path(chart_path).unlink(missing_ok=True)
    
    def test_multiple_data_gaps(self):
        """Verify charts handle multiple gaps in data."""
        data = generate_data_with_gaps(
            num_bars=100,
            gap_size=15,
            gap_positions=[20, 40, 60, 80]
        )
        signal = generate_test_signal(data, direction="short")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Multiple gaps entry chart failed"
        Path(chart_path).unlink(missing_ok=True)


class TestZeroVolumeCharts:
    """Test chart generation with zero/minimal volume bars."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_sparse_volume_entry_chart(self):
        """Verify entry charts render with 30% zero-volume bars."""
        data = generate_zero_volume_data(num_bars=100, zero_volume_pct=0.3)
        signal = generate_test_signal(data, direction="long")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Sparse volume entry chart failed"
        Path(chart_path).unlink(missing_ok=True)
    
    def test_mostly_zero_volume(self):
        """Verify charts handle 80% zero-volume bars."""
        data = generate_zero_volume_data(num_bars=100, zero_volume_pct=0.8)
        signal = generate_test_signal(data, direction="short")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Mostly zero volume chart failed"
        Path(chart_path).unlink(missing_ok=True)
    
    def test_zero_volume_dashboard(self):
        """Verify dashboard renders with zero-volume periods."""
        data = generate_zero_volume_data(num_bars=200, zero_volume_pct=0.5)
        
        chart_path = self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=100,
            title_time="12:00 UTC",
        )
        
        assert chart_path is not None, "Zero volume dashboard failed"
        Path(chart_path).unlink(missing_ok=True)


class TestExtremePriceCharts:
    """Test chart generation with extreme price levels."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_high_price_entry_chart(self):
        """Verify entry charts render with very high price levels."""
        data = generate_extreme_price_data(num_bars=100, base_price=100000.0)
        signal = generate_test_signal(data, direction="long")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="TEST",
            timeframe="5m",
        )
        
        assert chart_path is not None, "High price entry chart failed"
        Path(chart_path).unlink(missing_ok=True)
    
    def test_low_price_entry_chart(self):
        """Verify entry charts render with very low price levels."""
        # Use enough bars for MA calculations (need at least 50 for MA50)
        data = generate_extreme_price_data(num_bars=100, base_price=1000.0)
        signal = generate_test_signal(data, direction="short")
        # Adjust signal for lower price range
        signal["stop_loss"] = signal["entry_price"] + 10.0
        signal["take_profit"] = signal["entry_price"] - 15.0
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="TEST",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Low price entry chart failed"
        Path(chart_path).unlink(missing_ok=True)


class TestFlatMarketCharts:
    """Test chart generation with flat/ranging market data."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_flat_market_entry_chart(self):
        """Verify entry charts render with flat market data."""
        data = generate_flat_market_data(num_bars=100)
        signal = generate_test_signal(data, direction="long")
        
        # Adjust signal for tight range
        signal["stop_loss"] = signal["entry_price"] - 2.0
        signal["take_profit"] = signal["entry_price"] + 3.0
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Flat market entry chart failed"
        Path(chart_path).unlink(missing_ok=True)
    
    def test_flat_market_dashboard(self):
        """Verify dashboard renders with flat market data."""
        data = generate_flat_market_data(num_bars=200)
        
        chart_path = self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=100,
            title_time="12:00 UTC",
        )
        
        assert chart_path is not None, "Flat market dashboard failed"
        Path(chart_path).unlink(missing_ok=True)


class TestChartGeneratorRobustness:
    """Test chart generator error handling and edge case robustness."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_empty_data_returns_none(self):
        """Verify empty data returns None (not crash)."""
        data = pd.DataFrame()
        
        chart_path = self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is None, "Empty data should return None"
    
    def test_missing_columns_raises_error(self):
        """Verify missing OHLCV columns raises appropriate error or returns None."""
        # Data missing 'close' column
        data = pd.DataFrame({
            "timestamp": [datetime(2024, 12, 20, 9, 30, tzinfo=timezone.utc)],
            "open": [25000.0],
            "high": [25010.0],
            "low": [24990.0],
            # missing 'close'
            "volume": [1000],
        })
        
        # Chart generator should either raise ValueError or return None gracefully
        try:
            result = self.generator.generate_dashboard_chart(
                data=data,
                symbol="MNQ",
                timeframe="5m",
            )
            # If it doesn't raise, it should return None
            assert result is None, "Missing column should fail gracefully"
        except ValueError as e:
            assert "Missing required column" in str(e)
        except Exception as e:
            # Other exceptions are acceptable as long as it doesn't crash silently
            pass
    
    def test_nan_values_in_data(self):
        """Verify charts handle NaN values gracefully."""
        np.random.seed(SEED)
        base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
        
        data = []
        for i in range(100):
            ts = base_timestamp + timedelta(minutes=5 * i)
            price = 25000.0 + np.random.randn() * 10
            
            # Insert some NaN values
            if i % 20 == 0:
                volume = np.nan
            else:
                volume = 1000
            
            data.append({
                "timestamp": ts,
                "open": round(price - 2, 2),
                "high": round(price + 3, 2),
                "low": round(price - 3, 2),
                "close": round(price + 2, 2),
                "volume": volume,
            })
        
        df = pd.DataFrame(data)
        
        # Should handle NaN volume gracefully
        chart_path = self.generator.generate_dashboard_chart(
            data=df,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=50,
            title_time="12:00 UTC",
        )
        
        # May return None or a chart - either is acceptable, just shouldn't crash
        if chart_path is not None:
            Path(chart_path).unlink(missing_ok=True)

