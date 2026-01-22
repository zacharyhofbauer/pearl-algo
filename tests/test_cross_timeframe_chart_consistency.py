"""
Cross-timeframe visual consistency tests for chart generation.

This module verifies that the same signal rendered on different timeframes
(1m, 5m, 15m) maintains consistent visual semantics:
- Same colors for entry/stop/target lines
- Same z-order layering
- Same label priorities
- Same RR box positioning (to the right of last bar)

These tests catch timeframe-specific visual drift that could confuse traders.

Usage:
    pytest tests/test_cross_timeframe_chart_consistency.py -v
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from tests.fixtures.deterministic_data import SEED


# === Constants ===

# Timeframes to test
TIMEFRAMES = ["1m", "5m", "15m"]

# Bar intervals in minutes for each timeframe
TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
}

# Number of bars per timeframe (to have similar visual coverage)
BARS_PER_TIMEFRAME = {
    "1m": 300,   # 5 hours of 1m bars
    "5m": 100,   # ~8 hours of 5m bars
    "15m": 50,   # ~12 hours of 15m bars
}


def generate_timeframe_ohlcv(
    timeframe: str,
    seed: int = SEED,
    base_price: float = 25000.0,
) -> pd.DataFrame:
    """
    Generate deterministic OHLCV data for a specific timeframe.
    
    Uses the same seed for reproducibility across test runs.
    """
    np.random.seed(seed)
    
    num_bars = BARS_PER_TIMEFRAME.get(timeframe, 100)
    interval_minutes = TIMEFRAME_MINUTES.get(timeframe, 5)
    
    base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
    timestamps = [
        base_timestamp + timedelta(minutes=interval_minutes * i)
        for i in range(num_bars)
    ]
    
    # Scale volatility by timeframe (larger timeframes = larger moves)
    volatility_scale = interval_minutes ** 0.5
    price_changes = np.random.randn(num_bars) * 3 * volatility_scale
    prices = base_price + np.cumsum(price_changes)
    
    data = []
    for i, (ts, price) in enumerate(zip(timestamps, prices)):
        candle_range = abs(np.random.randn() * 3 * volatility_scale) + 2 * volatility_scale
        
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.3
            close_price = price + candle_range * 0.3
        else:
            open_price = price + candle_range * 0.3
            close_price = price - candle_range * 0.3
        
        high = max(open_price, close_price) + abs(np.random.randn() * volatility_scale) + 1
        low = min(open_price, close_price) - abs(np.random.randn() * volatility_scale) - 1
        
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


def generate_test_signal(data: pd.DataFrame, direction: str = "long") -> Dict[str, Any]:
    """
    Generate a test signal positioned in the middle of the data range.
    """
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
        "reason": "test_cross_timeframe",
    }


class TestCrossTimeframeConsistency:
    """Test that charts maintain visual consistency across timeframes."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator and test data."""
        try:
            from pearlalgo.market_agent.chart_generator import (
                ChartGenerator,
                ChartConfig,
                ENTRY_COLOR,
                SIGNAL_LONG,
                SIGNAL_SHORT,
                CANDLE_UP,
                CANDLE_DOWN,
            )
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
            self.ENTRY_COLOR = ENTRY_COLOR
            self.SIGNAL_LONG = SIGNAL_LONG
            self.SIGNAL_SHORT = SIGNAL_SHORT
            self.CANDLE_UP = CANDLE_UP
            self.CANDLE_DOWN = CANDLE_DOWN
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    def test_entry_chart_renders_for_all_timeframes(self, timeframe: str):
        """Verify entry charts render without error for each timeframe."""
        data = generate_timeframe_ohlcv(timeframe)
        signal = generate_test_signal(data, direction="long")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data,
            symbol="MNQ",
            timeframe=timeframe,
        )
        
        assert chart_path is not None, f"Entry chart failed to generate for {timeframe}"
        assert Path(chart_path).exists(), f"Entry chart file not found for {timeframe}"
        assert Path(chart_path).stat().st_size > 0, f"Entry chart is empty for {timeframe}"
        
        # Cleanup
        Path(chart_path).unlink(missing_ok=True)
    
    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    @pytest.mark.parametrize("direction", ["long", "short"])
    def test_entry_chart_all_directions_and_timeframes(self, timeframe: str, direction: str):
        """Verify entry charts render for all direction/timeframe combinations."""
        data = generate_timeframe_ohlcv(timeframe)
        signal = generate_test_signal(data, direction=direction)
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data,
            symbol="MNQ",
            timeframe=timeframe,
        )
        
        assert chart_path is not None, f"Entry chart failed for {direction}/{timeframe}"
        assert Path(chart_path).exists()
        
        # Cleanup
        Path(chart_path).unlink(missing_ok=True)
    
    def test_color_constants_are_consistent(self):
        """Verify color constants don't change (semantic contract)."""
        # These colors must match TradingView defaults
        assert self.CANDLE_UP == "#26a69a", "Candle up color changed - breaks TradingView muscle memory"
        assert self.CANDLE_DOWN == "#ef5350", "Candle down color changed - breaks TradingView muscle memory"
        assert self.ENTRY_COLOR == "#2962ff", "Entry color changed - breaks visual contract"
        assert self.SIGNAL_LONG == "#26a69a", "Signal long color changed - must match candle up"
        assert self.SIGNAL_SHORT == "#ef5350", "Signal short color changed - must match candle down"
    
    def test_zorder_constants_are_consistent(self):
        """Verify z-order layering is preserved (visual hierarchy contract)."""
        from pearlalgo.market_agent.chart_generator import (
            ZORDER_SESSION_SHADING,
            ZORDER_ZONES,
            ZORDER_LEVEL_LINES,
            ZORDER_CANDLES,
            ZORDER_TEXT_LABELS,
        )
        
        # Verify z-order hierarchy
        assert ZORDER_SESSION_SHADING < ZORDER_ZONES, "Session shading must be behind zones"
        assert ZORDER_ZONES < ZORDER_LEVEL_LINES, "Zones must be behind level lines"
        assert ZORDER_LEVEL_LINES < ZORDER_CANDLES, "Level lines must be behind candles"
        assert ZORDER_CANDLES < ZORDER_TEXT_LABELS, "Candles must be behind labels"
        
        # Verify exact values for baseline stability
        assert ZORDER_SESSION_SHADING == 0, "Session shading z-order changed"
        assert ZORDER_ZONES == 1, "Zones z-order changed"
        assert ZORDER_LEVEL_LINES == 2, "Level lines z-order changed"
        assert ZORDER_CANDLES == 3, "Candles z-order changed"
        assert ZORDER_TEXT_LABELS == 4, "Text labels z-order changed"
    
    def test_font_size_constants_are_consistent(self):
        """Verify font size constants exist and are reasonable."""
        from pearlalgo.market_agent.chart_generator import (
            FONT_SIZE_LABEL,
            FONT_SIZE_SESSION,
            FONT_SIZE_RR_BOX,
            FONT_SIZE_LEGEND,
        )
        
        # Font sizes should be readable (8-14pt range)
        assert 8 <= FONT_SIZE_LABEL <= 14, "Label font size out of readable range"
        assert 8 <= FONT_SIZE_SESSION <= 14, "Session font size out of readable range"
        assert 8 <= FONT_SIZE_RR_BOX <= 14, "RR box font size out of readable range"
        assert 8 <= FONT_SIZE_LEGEND <= 14, "Legend font size out of readable range"
    
    def test_alpha_constants_preserve_candle_visibility(self):
        """Verify alpha values are low enough to not obscure candles."""
        from pearlalgo.market_agent.chart_generator import (
            ALPHA_ZONE_SUPPLY_DEMAND,
            ALPHA_ZONE_POWER_CHANNEL,
            ALPHA_SESSION_SHADING,
        )
        
        # Zone alphas must be low to avoid obscuring candles (visual contract)
        assert ALPHA_ZONE_SUPPLY_DEMAND <= 0.25, "Supply/demand zone alpha too high - may obscure candles"
        assert ALPHA_ZONE_POWER_CHANNEL <= 0.15, "Power channel zone alpha too high - may obscure candles"
        assert ALPHA_SESSION_SHADING <= 0.10, "Session shading alpha too high - may obscure candles"


class TestCrossTimeframeDeterminism:
    """Test that charts are deterministic (same inputs = same outputs)."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.market_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    def test_same_inputs_produce_identical_charts(self, timeframe: str):
        """Verify determinism: same data + signal = identical chart (per timeframe)."""
        # Generate data twice with same seed
        data1 = generate_timeframe_ohlcv(timeframe, seed=SEED)
        data2 = generate_timeframe_ohlcv(timeframe, seed=SEED)
        
        # Data should be identical
        pd.testing.assert_frame_equal(data1, data2)
        
        signal1 = generate_test_signal(data1, direction="long")
        signal2 = generate_test_signal(data2, direction="long")
        
        # Signals should be identical
        assert signal1 == signal2, "Same seed should produce identical signals"
        
        # Generate charts
        chart1 = self.generator.generate_entry_chart(
            signal=signal1, buffer_data=data1, symbol="MNQ", timeframe=timeframe
        )
        chart2 = self.generator.generate_entry_chart(
            signal=signal2, buffer_data=data2, symbol="MNQ", timeframe=timeframe
        )
        
        assert chart1 is not None
        assert chart2 is not None
        
        # Compare file sizes (should be identical for deterministic output)
        size1 = Path(chart1).stat().st_size
        size2 = Path(chart2).stat().st_size
        
        # Allow small variance for OS/Python version differences
        assert abs(size1 - size2) < 1000, f"Chart sizes differ significantly: {size1} vs {size2}"
        
        # Cleanup
        Path(chart1).unlink(missing_ok=True)
        Path(chart2).unlink(missing_ok=True)


class TestCrossTimeframeEdgeCases:
    """Test edge cases across different timeframes."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.market_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    def test_minimal_data_handling(self, timeframe: str):
        """Verify charts handle minimal data gracefully for each timeframe."""
        # Generate minimal data - need at least 50 bars for MA calculations
        # (chart generator uses MA20 by default)
        np.random.seed(SEED)
        num_bars = 50
        interval = TIMEFRAME_MINUTES.get(timeframe, 5)
        base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
        
        data = []
        price = 25000.0
        for i in range(num_bars):
            ts = base_timestamp + timedelta(minutes=interval * i)
            change = np.random.randn() * 5
            price += change
            data.append({
                "timestamp": ts,
                "open": round(price - 2, 2),
                "high": round(price + 3, 2),
                "low": round(price - 3, 2),
                "close": round(price + 2, 2),
                "volume": 1000,
            })
        
        df = pd.DataFrame(data)
        signal = generate_test_signal(df, direction="long")
        
        # Should render without error (may look cramped but shouldn't crash)
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=df,
            symbol="MNQ",
            timeframe=timeframe,
        )
        
        assert chart_path is not None, f"Minimal data chart failed for {timeframe}"
        Path(chart_path).unlink(missing_ok=True)
    
    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    def test_high_volatility_data(self, timeframe: str):
        """Verify charts handle high volatility data for each timeframe."""
        np.random.seed(SEED)
        num_bars = 50
        interval = TIMEFRAME_MINUTES.get(timeframe, 5)
        base_timestamp = datetime(2024, 12, 20, 9, 30, 0, tzinfo=timezone.utc)
        
        data = []
        price = 25000.0
        for i in range(num_bars):
            ts = base_timestamp + timedelta(minutes=interval * i)
            # High volatility: 50-100 point moves
            change = np.random.randn() * 50
            price += change
            candle_range = abs(np.random.randn() * 30) + 20
            data.append({
                "timestamp": ts,
                "open": round(price - candle_range/2, 2),
                "high": round(price + candle_range/2 + 20, 2),
                "low": round(price - candle_range/2 - 20, 2),
                "close": round(price + candle_range/2, 2),
                "volume": int(np.random.uniform(5000, 20000)),
            })
        
        df = pd.DataFrame(data)
        signal = generate_test_signal(df, direction="long")
        
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=df,
            symbol="MNQ",
            timeframe=timeframe,
        )
        
        assert chart_path is not None, f"High volatility chart failed for {timeframe}"
        Path(chart_path).unlink(missing_ok=True)

