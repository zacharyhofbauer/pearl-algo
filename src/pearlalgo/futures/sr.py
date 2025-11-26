from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import pandas as pd


@dataclass
class Bar:
    timestamp: pd.Timestamp
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SRSignal:
    signal_type: str  # long | short | flat
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    context: Dict[str, float]


def identify_pivots(bars: Iterable[Bar], lookback: int = 20, sensitivity: int = 3) -> List[Tuple[str, float]]:
    """
    Identify pivot highs/lows in a sequence of bars.
    Returns list of (iso_timestamp, price) for highs and lows combined, ordered by time.
    """
    bar_list = list(bars)
    pivots: List[Tuple[str, float]] = []
    for i in range(sensitivity, min(len(bar_list), lookback)):
        window = bar_list[max(0, i - sensitivity) : i + sensitivity + 1]
        if len(window) < (2 * sensitivity + 1):
            continue
        center = bar_list[i]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        if center.high == max(highs):
            pivots.append((center.timestamp.isoformat(), center.high))
        if center.low == min(lows):
            pivots.append((center.timestamp.isoformat(), center.low))
    return pivots


def compute_vwap(bars: Iterable[Bar]) -> float:
    """
    Compute VWAP using typical price * volume / total volume.
    """
    total_vol = 0.0
    total_pv = 0.0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3
        total_vol += b.volume
        total_pv += typical * b.volume
    return total_pv / total_vol if total_vol > 0 else 0.0


def compute_daily_pivots(prev_close: float, prev_high: float, prev_low: float) -> Dict[str, float]:
    """
    Floor-trader pivots: P, R1-3, S1-3.
    """
    p = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * p - prev_low
    s1 = 2 * p - prev_high
    r2 = p + (prev_high - prev_low)
    s2 = p - (prev_high - prev_low)
    r3 = prev_high + 2 * (p - prev_low)
    s3 = prev_low - 2 * (prev_high - p)
    return {"pivot": p, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3}


def chartprime_sr(indicators: Dict[str, float] | None = None) -> Dict[str, float]:
    """
    Stub for external high-timeframe support/resistance (e.g., ChartPrime).
    Accepts optional precomputed indicators; returns dict with possible keys 'htf_support', 'htf_resistance'.
    """
    return indicators or {}


def calculate_support_resistance(bars: Iterable[Bar], indicators: Dict[str, float] | None = None) -> Dict[str, float]:
    """
    Combine pivots, VWAP, and optional external levels into a simple SR dict.
    Picks most recent pivot low as support1 and most recent pivot high as resistance1.
    """
    bar_list = list(bars)
    pivots = identify_pivots(bar_list)
    vwap = compute_vwap(bar_list)

    pivot_highs = [(ts, price) for ts, price in pivots if price >= max(b.low for b in bar_list)]
    pivot_lows = [(ts, price) for ts, price in pivots if price <= max(b.high for b in bar_list)]

    support1 = pivot_lows[-1][1] if pivot_lows else None
    resistance1 = pivot_highs[-1][1] if pivot_highs else None

    sr = {
        "support1": support1,
        "resistance1": resistance1,
        "vwap": vwap,
    }
    sr.update(chartprime_sr(indicators))
    return sr


def sr_signal_from_levels(close: float, sr: Dict[str, float], tolerance: float = 0.002) -> SRSignal:
    support = sr.get("support1")
    resistance = sr.get("resistance1")
    vwap = sr.get("vwap")

    def near(level: float | None) -> bool:
        if level is None:
            return False
        return abs(close - level) <= level * tolerance

    if vwap and close > vwap and near(support):
        entry = close
        stop = support * (1 - tolerance) if support else None
        target = sr.get("resistance1") or sr.get("r1")
        return SRSignal("long", entry, stop, target, context=sr)
    if vwap and close < vwap and near(resistance):
        entry = close
        stop = resistance * (1 + tolerance) if resistance else None
        target = sr.get("support1") or sr.get("s1")
        return SRSignal("short", entry, stop, target, context=sr)

    return SRSignal("flat", None, None, None, context=sr)
