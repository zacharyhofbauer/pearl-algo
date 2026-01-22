"""
Shared deterministic synthetic data generators for testing.

This module provides reproducible OHLCV data generation for:
- Visual regression tests (dashboard chart comparison)
- Baseline image generation scripts

All functions use fixed seeds and parameters for cross-environment reproducibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# === Deterministic Constants ===

# Fixed seed for reproducibility
SEED = 42

# Fixed base timestamp (2024-12-20 00:00:00 UTC) - a Friday, ensuring sessions are visible
BASE_TIMESTAMP = datetime(2024, 12, 20, 0, 0, 0, tzinfo=timezone.utc)

# Number of 5-minute bars (288 = 24h, 576 = 48h)
NUM_BARS = 432  # 36h of 5m bars

# Fixed title time for chart generation determinism
FIXED_TITLE_TIME = "12:00 UTC"


def generate_deterministic_ohlcv(
    num_bars: int = NUM_BARS,
    base_timestamp: datetime = BASE_TIMESTAMP,
    seed: int = SEED,
    base_price: float = 25000.0,
) -> pd.DataFrame:
    """
    Generate deterministic synthetic OHLCV data for MNQ-style futures.

    Args:
        num_bars: Number of 5-minute bars to generate
        base_timestamp: Starting timestamp (UTC)
        seed: Random seed for reproducibility
        base_price: Starting price level

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    np.random.seed(seed)

    # Generate timestamps (5-minute intervals)
    timestamps = [base_timestamp + timedelta(minutes=5 * i) for i in range(num_bars)]

    # Generate price series with realistic MNQ volatility
    # MNQ typically moves 5-15 points per 5m bar
    price_changes = np.random.randn(num_bars) * 8
    prices = base_price + np.cumsum(price_changes)

    data = []
    for i, (ts, price) in enumerate(zip(timestamps, prices)):
        # Realistic candle range: 5-20 points (MNQ typical 5m range)
        candle_range = abs(np.random.randn() * 8) + 5

        # Random direction for candle body
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.3
            close_price = price + candle_range * 0.3
        else:
            open_price = price + candle_range * 0.3
            close_price = price - candle_range * 0.3

        # Wicks extend beyond body
        high = max(open_price, close_price) + abs(np.random.randn() * 3) + 2
        low = min(open_price, close_price) - abs(np.random.randn() * 3) - 2

        # Volume with some variance
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


def generate_deterministic_entry_signal(
    data: pd.DataFrame,
    direction: str = "long",
) -> dict:
    """
    Generate a deterministic signal for entry chart testing.
    
    Args:
        data: OHLCV DataFrame from generate_deterministic_ohlcv()
        direction: "long" or "short"
    
    Returns:
        Signal dict compatible with ChartGenerator.generate_entry_chart()
    """
    # Use close price at bar 80 as entry (gives context before and after)
    entry_bar_idx = 80
    entry_price = float(data["close"].iloc[entry_bar_idx])
    entry_timestamp = data["timestamp"].iloc[entry_bar_idx]
    
    if direction == "long":
        stop_loss = entry_price - 20.0  # 20 point stop
        take_profit = entry_price + 30.0  # 30 point target (1.5:1 R:R)
    else:
        stop_loss = entry_price + 20.0
        take_profit = entry_price - 30.0
    
    return {
        "type": "momentum_breakout",
        "direction": direction,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "timestamp": entry_timestamp.isoformat() if hasattr(entry_timestamp, "isoformat") else str(entry_timestamp),
        "reason": "test_deterministic_signal",
    }


def generate_deterministic_exit_data(
    data: pd.DataFrame,
    signal: dict,
) -> tuple[float, str, float]:
    """
    Generate deterministic exit data for exit chart testing.
    
    Args:
        data: OHLCV DataFrame
        signal: Entry signal dict
    
    Returns:
        (exit_price, exit_reason, pnl)
    """
    direction = signal.get("direction", "long")
    entry_price = float(signal.get("entry_price", 0))
    take_profit = float(signal.get("take_profit", 0))
    
    # Simulate hitting take profit
    exit_price = take_profit
    exit_reason = "take_profit"
    
    if direction == "long":
        pnl = (exit_price - entry_price) * 2.0  # $2 per point for MNQ
    else:
        pnl = (entry_price - exit_price) * 2.0
    
    return exit_price, exit_reason, round(pnl, 2)


def generate_deterministic_backtest_signals(
    data: pd.DataFrame,
    num_signals: int = 8,
) -> list[dict]:
    """
    Generate deterministic signals for backtest chart testing.
    
    Creates a mix of long/short signals with win/loss outcomes
    spread across the data range for visual regression testing.
    
    Args:
        data: OHLCV DataFrame from generate_deterministic_ohlcv()
        num_signals: Number of signals to generate (default 8)
    
    Returns:
        List of signal dicts compatible with ChartGenerator.generate_backtest_chart()
    """
    signals = []
    num_bars = len(data)
    
    # Spread signals evenly across data range (skip first/last 10%)
    start_idx = int(num_bars * 0.1)
    end_idx = int(num_bars * 0.9)
    step = (end_idx - start_idx) // num_signals
    
    for i in range(num_signals):
        idx = start_idx + (i * step)
        if idx >= len(data):
            break
            
        # Alternate long/short
        direction = "long" if i % 2 == 0 else "short"
        
        entry_price = float(data["close"].iloc[idx])
        entry_timestamp = data["timestamp"].iloc[idx]
        
        # Alternating win/loss pattern for visual variety
        is_win = i % 3 != 0  # 2 wins, 1 loss pattern
        
        if direction == "long":
            stop_loss = entry_price - 15.0
            take_profit = entry_price + 22.5
            if is_win:
                exit_price = take_profit
                pnl = (exit_price - entry_price) * 2.0
            else:
                exit_price = stop_loss
                pnl = (exit_price - entry_price) * 2.0
        else:
            stop_loss = entry_price + 15.0
            take_profit = entry_price - 22.5
            if is_win:
                exit_price = take_profit
                pnl = (entry_price - exit_price) * 2.0
            else:
                exit_price = stop_loss
                pnl = (entry_price - exit_price) * 2.0
        
        signals.append({
            "type": "momentum_breakout",
            "direction": direction,
            "entry_price": round(entry_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "exit_price": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "timestamp": entry_timestamp.isoformat() if hasattr(entry_timestamp, "isoformat") else str(entry_timestamp),
            "reason": f"test_signal_{i}",
        })
    
    return signals


# === Edge Case Data Generators ===

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


def generate_test_signal(data: pd.DataFrame, direction: str = "long") -> Dict[str, Any]:
    """
    Generate a test signal for chart generation.
    
    This is a generic signal generator that can be used across different test scenarios.
    For deterministic signals, use generate_deterministic_entry_signal() instead.
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
        "reason": "test_edge_case",
    }


# === Cross-Timeframe Data Generators ===

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






def _high_volatility_data(
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


def generate_test_signal(data: pd.DataFrame, direction: str = "long") -> Dict[str, Any]:
    """
    Generate a test signal for chart generation.
    
    This is a generic signal generator that can be used across different test scenarios.
    For deterministic signals, use generate_deterministic_entry_signal() instead.
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
        "reason": "test_edge_case",
    }


# === Cross-Timeframe Data Generators ===

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






