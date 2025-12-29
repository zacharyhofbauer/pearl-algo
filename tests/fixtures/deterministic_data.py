"""
Shared deterministic synthetic data generators for testing.

This module provides reproducible OHLCV data generation for:
- Visual regression tests (dashboard chart comparison)
- Baseline image generation scripts

All functions use fixed seeds and parameters for cross-environment reproducibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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





