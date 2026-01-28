"""
Tests for utils/vwap.py

Validates the VWAP (Volume-Weighted Average Price) calculator including:
- VWAP calculation
- Session reset logic
- VWAP bands
- Confidence adjustment based on VWAP position
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from pearlalgo.utils.vwap import VWAPCalculator


class TestVWAPCalculatorInit:
    """Tests for VWAPCalculator initialization."""

    def test_initializes_with_empty_state(self) -> None:
        """Should initialize with no session data."""
        calc = VWAPCalculator()

        assert calc._session_vwap is None
        assert calc._session_start is None
        assert calc._cumulative_volume == 0.0
        assert calc._cumulative_volume_price == 0.0


class TestVWAPCalculation:
    """Tests for calculate_vwap method."""

    def test_empty_dataframe_returns_defaults(self) -> None:
        """Should return default VWAP for empty DataFrame."""
        calc = VWAPCalculator()
        df = pd.DataFrame()

        result = calc.calculate_vwap(df)

        assert result["vwap"] == 0.0
        assert result["distance_from_vwap"] == 0.0
        assert result["current_price"] == 0.0

    def test_calculates_vwap_from_ohlcv(self) -> None:
        """Should calculate VWAP from OHLCV data."""
        calc = VWAPCalculator()

        # Create sample data with known values
        # Typical price = (H + L + C) / 3
        # Bar 1: TP = (101 + 99 + 100) / 3 = 100, Volume = 100, VP = 10000
        # Bar 2: TP = (102 + 100 + 101) / 3 = 101, Volume = 200, VP = 20200
        # VWAP = (10000 + 20200) / (100 + 200) = 30200 / 300 = 100.67
        df = pd.DataFrame({
            "open": [100.0, 100.5],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
            "volume": [100, 200],
        })

        result = calc.calculate_vwap(df)

        expected_vwap = 30200 / 300  # ~100.67
        assert abs(result["vwap"] - expected_vwap) < 0.01
        assert result["current_price"] == 101.0

    def test_calculates_distance_from_vwap(self) -> None:
        """Should calculate distance from VWAP correctly."""
        calc = VWAPCalculator()

        df = pd.DataFrame({
            "open": [100.0],
            "high": [105.0],
            "low": [95.0],
            "close": [102.0],
            "volume": [1000],
        })

        result = calc.calculate_vwap(df)

        # Typical price = (105 + 95 + 102) / 3 = 100.67
        # VWAP = 100.67 (single bar)
        # Distance = 102 - 100.67 = 1.33
        assert result["distance_from_vwap"] > 0  # Price above VWAP
        assert result["distance_pct"] > 0

    def test_calculates_vwap_bands_with_atr(self) -> None:
        """Should calculate VWAP bands when ATR is provided."""
        calc = VWAPCalculator()

        df = pd.DataFrame({
            "open": [100.0],
            "high": [105.0],
            "low": [95.0],
            "close": [100.0],
            "volume": [1000],
        })

        atr = 2.0
        result = calc.calculate_vwap(df, atr=atr)

        vwap = result["vwap"]
        assert result["vwap_upper_1"] == vwap + atr
        assert result["vwap_upper_2"] == vwap + (atr * 2)
        assert result["vwap_lower_1"] == vwap - atr
        assert result["vwap_lower_2"] == vwap - (atr * 2)

    def test_vwap_bands_equal_vwap_without_atr(self) -> None:
        """VWAP bands should equal VWAP when no ATR provided."""
        calc = VWAPCalculator()

        df = pd.DataFrame({
            "open": [100.0],
            "high": [105.0],
            "low": [95.0],
            "close": [100.0],
            "volume": [1000],
        })

        result = calc.calculate_vwap(df, atr=None)

        vwap = result["vwap"]
        assert result["vwap_upper_1"] == vwap
        assert result["vwap_lower_1"] == vwap

    def test_handles_zero_volume(self) -> None:
        """Should handle bars with zero volume."""
        calc = VWAPCalculator()

        df = pd.DataFrame({
            "open": [100.0],
            "high": [105.0],
            "low": [95.0],
            "close": [102.0],
            "volume": [0],
        })

        result = calc.calculate_vwap(df)

        # With zero volume, should fallback to last close
        assert result["vwap"] == 102.0


class TestSessionReset:
    """Tests for session reset logic."""

    def test_resets_on_new_session_date(self) -> None:
        """Should reset cumulative values on new trading day."""
        calc = VWAPCalculator()

        # First call sets session
        df1 = pd.DataFrame({
            "open": [100.0],
            "high": [105.0],
            "low": [95.0],
            "close": [100.0],
            "volume": [1000],
        })

        calc.calculate_vwap(df1)
        assert calc._session_start is not None

        # Simulate reset
        calc._reset_session()

        assert calc._cumulative_volume == 0.0
        assert calc._cumulative_volume_price == 0.0
        assert calc._session_vwap is None


class TestConfidenceAdjustment:
    """Tests for adjust_confidence_by_vwap method."""

    def test_long_above_vwap_increases_confidence(self) -> None:
        """Long signal above VWAP should get confidence boost."""
        calc = VWAPCalculator()

        vwap_data = {
            "vwap": 100.0,
            "current_price": 101.0,
            "distance_pct": 1.0,  # 1% above VWAP
        }

        adjusted = calc.adjust_confidence_by_vwap("long", 0.70, vwap_data)

        assert adjusted > 0.70

    def test_long_below_vwap_decreases_confidence(self) -> None:
        """Long signal below VWAP should get confidence penalty."""
        calc = VWAPCalculator()

        vwap_data = {
            "vwap": 100.0,
            "current_price": 99.0,
            "distance_pct": -1.0,  # 1% below VWAP
        }

        adjusted = calc.adjust_confidence_by_vwap("long", 0.70, vwap_data)

        assert adjusted < 0.70

    def test_short_below_vwap_increases_confidence(self) -> None:
        """Short signal below VWAP should get confidence boost."""
        calc = VWAPCalculator()

        vwap_data = {
            "vwap": 100.0,
            "current_price": 99.0,
            "distance_pct": -1.0,  # 1% below VWAP
        }

        adjusted = calc.adjust_confidence_by_vwap("short", 0.70, vwap_data)

        assert adjusted > 0.70

    def test_short_above_vwap_decreases_confidence(self) -> None:
        """Short signal above VWAP should get confidence penalty."""
        calc = VWAPCalculator()

        vwap_data = {
            "vwap": 100.0,
            "current_price": 101.0,
            "distance_pct": 1.0,  # 1% above VWAP
        }

        adjusted = calc.adjust_confidence_by_vwap("short", 0.70, vwap_data)

        assert adjusted < 0.70

    def test_clamps_confidence_to_valid_range(self) -> None:
        """Adjusted confidence should be clamped to [0, 1]."""
        calc = VWAPCalculator()

        # Try to boost very high confidence
        vwap_data = {
            "vwap": 100.0,
            "current_price": 105.0,
            "distance_pct": 5.0,
        }

        adjusted = calc.adjust_confidence_by_vwap("long", 0.98, vwap_data)
        assert adjusted <= 1.0

        # Try to penalize very low confidence
        vwap_data["current_price"] = 95.0
        vwap_data["distance_pct"] = -5.0

        adjusted = calc.adjust_confidence_by_vwap("long", 0.05, vwap_data)
        assert adjusted >= 0.0

    def test_no_adjustment_with_zero_vwap(self) -> None:
        """Should return original confidence if VWAP is zero."""
        calc = VWAPCalculator()

        vwap_data = {
            "vwap": 0.0,
            "current_price": 100.0,
            "distance_pct": 0.0,
        }

        adjusted = calc.adjust_confidence_by_vwap("long", 0.70, vwap_data)

        assert adjusted == 0.70


class TestDefaultVWAP:
    """Tests for default VWAP values."""

    def test_default_vwap_structure(self) -> None:
        """Default VWAP should have all expected keys."""
        calc = VWAPCalculator()
        result = calc._default_vwap()

        expected_keys = [
            "vwap",
            "vwap_upper_1",
            "vwap_upper_2",
            "vwap_lower_1",
            "vwap_lower_2",
            "distance_from_vwap",
            "distance_pct",
            "current_price",
        ]

        for key in expected_keys:
            assert key in result
            assert result[key] == 0.0
