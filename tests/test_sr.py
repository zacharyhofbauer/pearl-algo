from __future__ import annotations

import pandas as pd

from pearlalgo.futures.sr import Bar, calculate_support_resistance, compute_vwap, identify_pivots


def test_identify_pivots_and_vwap():
    bars = [
        Bar(timestamp=pd.Timestamp("2025-01-01 00:00:00"), high=10, low=8, close=9, volume=100),
        Bar(timestamp=pd.Timestamp("2025-01-01 00:01:00"), high=12, low=9, close=11, volume=100),
        Bar(timestamp=pd.Timestamp("2025-01-01 00:02:00"), high=11, low=9, close=10, volume=100),
    ]
    pivots = identify_pivots(bars, lookback=3, sensitivity=1)
    assert len(pivots) >= 1
    vwap = compute_vwap(bars)
    assert vwap > 0


def test_calculate_support_resistance():
    bars = [
        Bar(timestamp=pd.Timestamp("2025-01-01 00:00:00"), high=10, low=8, close=9, volume=100),
        Bar(timestamp=pd.Timestamp("2025-01-01 00:01:00"), high=12, low=9, close=11, volume=150),
        Bar(timestamp=pd.Timestamp("2025-01-01 00:02:00"), high=11, low=9, close=10, volume=120),
        Bar(timestamp=pd.Timestamp("2025-01-01 00:03:00"), high=13, low=10, close=12, volume=130),
        Bar(timestamp=pd.Timestamp("2025-01-01 00:04:00"), high=12, low=10, close=11, volume=110),
    ]
    sr = calculate_support_resistance(bars)
    assert "support1" in sr and "resistance1" in sr and "vwap" in sr
    assert sr["vwap"] > 0


def test_premarket_and_swing_levels():
    """Test that pre-market and swing levels are computed."""
    from pearlalgo.futures.sr import compute_premarket_levels, compute_swing_levels
    
    bars = [
        Bar(timestamp=pd.Timestamp("2025-01-01 08:00:00"), high=100, low=98, close=99, volume=1000),  # Pre-market
        Bar(timestamp=pd.Timestamp("2025-01-01 08:15:00"), high=101, low=99, close=100, volume=1100),  # Pre-market
        Bar(timestamp=pd.Timestamp("2025-01-01 09:30:00"), high=102, low=100, close=101, volume=1200),  # Session
        Bar(timestamp=pd.Timestamp("2025-01-01 09:45:00"), high=103, low=101, close=102, volume=1300),  # Session
    ]
    
    premarket = compute_premarket_levels(bars, session_start_hour=9)
    assert "premarket_high" in premarket
    assert "premarket_low" in premarket
    assert premarket["premarket_high"] is not None
    assert premarket["premarket_low"] is not None
    
    swing = compute_swing_levels(bars, lookback=20)
    assert "swing_high" in swing
    assert "swing_low" in swing
    assert swing["swing_high"] is not None
    assert swing["swing_low"] is not None
