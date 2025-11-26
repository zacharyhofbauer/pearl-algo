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
