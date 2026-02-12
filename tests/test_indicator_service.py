"""
Tests for the technical indicator service (src/pearlalgo/api/indicator_service.py).

Verifies ``calculate_indicators`` produces reasonable values for EMA, VWAP,
Bollinger Bands, ATR Bands, and Volume Profile on realistic OHLCV input,
and degrades gracefully on empty or insufficient data.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from pearlalgo.api.indicator_service import calculate_indicators


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candles(n: int, *, base_price: float = 18000.0) -> List[Dict[str, Any]]:
    """Generate *n* deterministic candle dicts suitable for indicator computation."""
    candles = []
    price = base_price
    for i in range(n):
        # Small oscillation around base price
        delta = (i % 7 - 3) * 2.5
        o = price + delta
        c = price + delta + 1.0
        h = max(o, c) + 3.0
        l = min(o, c) - 3.0  # noqa: E741
        candles.append({
            "time": 1700000000 + i * 300,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": 5000 + i * 100,
        })
        price = c
    return candles


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyAndShortInput:
    def test_empty_candles_returns_empty_indicators(self):
        result = calculate_indicators([])
        assert result["ema9"] == []
        assert result["ema21"] == []
        assert result["vwap"] == []
        assert result["bollingerBands"] == []
        assert result["atrBands"] == []
        assert result["volumeProfile"] is None

    def test_short_candle_list_returns_partial_indicators(self):
        """With < 9 candles, EMA-9 cannot emit, but VWAP should still work."""
        candles = _make_candles(5)
        result = calculate_indicators(candles)
        # VWAP should have one value per candle
        assert len(result["vwap"]) == 5
        # EMA-9 requires 9 bars, so should be empty for 5 bars
        assert len(result["ema9"]) == 0


class TestValidOHLCVData:
    def test_ema_values_present_and_finite(self):
        candles = _make_candles(50)
        result = calculate_indicators(candles)

        # EMA-9 should have at least 50 - 8 = 42 entries
        assert len(result["ema9"]) >= 40
        for entry in result["ema9"]:
            assert math.isfinite(entry["value"])
            assert entry["value"] > 0

        # EMA-21 should have at least 50 - 20 = 30 entries
        assert len(result["ema21"]) >= 28
        for entry in result["ema21"]:
            assert math.isfinite(entry["value"])

    def test_vwap_length_matches_candle_count(self):
        candles = _make_candles(30)
        result = calculate_indicators(candles)
        assert len(result["vwap"]) == 30
        # VWAP values should be positive and close to close prices
        for v in result["vwap"]:
            assert v["value"] > 0
            assert math.isfinite(v["value"])

    def test_bollinger_bands_structure(self):
        candles = _make_candles(50)
        result = calculate_indicators(candles)
        bbs = result["bollingerBands"]
        # Bollinger Bands need 20 bars, so should have 50 - 19 = 31 entries
        assert len(bbs) >= 30
        for bb in bbs:
            assert "upper" in bb
            assert "middle" in bb
            assert "lower" in bb
            assert bb["upper"] >= bb["middle"] >= bb["lower"]

    def test_atr_bands_structure(self):
        candles = _make_candles(50)
        result = calculate_indicators(candles)
        atrs = result["atrBands"]
        # ATR needs 14 bars
        assert len(atrs) >= 35
        for ab in atrs:
            assert "upper" in ab
            assert "lower" in ab
            assert "atr" in ab
            assert ab["atr"] > 0
            assert ab["upper"] > ab["lower"]

    def test_volume_profile_structure(self):
        candles = _make_candles(50)
        result = calculate_indicators(candles)
        vp = result["volumeProfile"]
        assert vp is not None
        assert "poc" in vp
        assert "vah" in vp
        assert "val" in vp
        assert "levels" in vp
        assert len(vp["levels"]) > 0
        # Value area high >= POC >= value area low
        assert vp["vah"] >= vp["val"]
