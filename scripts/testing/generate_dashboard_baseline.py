#!/usr/bin/env python3
"""
Generate deterministic dashboard baseline image for visual regression testing.

This script creates a fixed synthetic OHLCV dataset and renders a dashboard chart
with deterministic parameters for use as a baseline in image-diff tests.

Usage:
    python3 scripts/testing/generate_dashboard_baseline.py [--output PATH]

The baseline image is saved to tests/fixtures/charts/dashboard_baseline.png by default.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))


# === Deterministic Synthetic Data ===

# Fixed seed for reproducibility
SEED = 42

# Fixed base timestamp (2024-12-20 00:00:00 UTC) - a Friday, ensuring sessions are visible
BASE_TIMESTAMP = datetime(2024, 12, 20, 0, 0, 0, tzinfo=timezone.utc)

# Number of 5-minute bars (288 = 24h, 576 = 48h)
NUM_BARS = 432  # 36h of 5m bars


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


def generate_baseline_image(output_path: Path) -> bool:
    """
    Generate the deterministic dashboard baseline image.

    Args:
        output_path: Path to save the baseline PNG

    Returns:
        True if successful, False otherwise
    """
    try:
        from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

        # Generate deterministic data
        print(f"Generating deterministic OHLCV data ({NUM_BARS} bars, seed={SEED})...")
        data = generate_deterministic_ohlcv()
        print(f"  Timestamp range: {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")
        print(f"  Price range: {data['low'].min():.2f} to {data['high'].max():.2f}")

        # Create chart generator with default config
        config = ChartConfig()
        generator = ChartGenerator(config)

        # Fixed title timestamp for determinism
        fixed_title_time = "12:00 UTC"

        print("Generating dashboard chart...")
        chart_path = generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=min(288, len(data)),  # 24h of 5m bars
            range_label="36h",
            figsize=(16, 7),
            dpi=150,
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50, 200],
            show_rsi=True,
            show_pressure=True,
            # Determinism hook (will be added to chart_generator.py)
            title_time=fixed_title_time,
        )

        if chart_path and chart_path.exists():
            # Move to output path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(chart_path, output_path)
            chart_path.unlink()  # Clean up temp file
            print(f"Baseline image saved: {output_path}")
            return True
        else:
            print("ERROR: Chart generation returned no path")
            return False

    except TypeError as e:
        # title_time parameter not yet implemented - generate without it for now
        if "title_time" in str(e):
            print("NOTE: title_time parameter not yet implemented, generating without it...")
            return _generate_baseline_without_title_time(output_path)
        raise
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def _generate_baseline_without_title_time(output_path: Path) -> bool:
    """Fallback generator without title_time parameter."""
    try:
        from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

        data = generate_deterministic_ohlcv()
        config = ChartConfig()
        generator = ChartGenerator(config)

        chart_path = generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=min(288, len(data)),
            range_label="36h",
            figsize=(16, 7),
            dpi=150,
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50, 200],
            show_rsi=True,
            show_pressure=True,
        )

        if chart_path and chart_path.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(chart_path, output_path)
            chart_path.unlink()
            print(f"Baseline image saved (without title_time): {output_path}")
            return True
        else:
            print("ERROR: Chart generation returned no path")
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic dashboard baseline image for visual regression testing."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "tests" / "fixtures" / "charts" / "dashboard_baseline.png",
        help="Output path for baseline image",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Dashboard Baseline Image Generator")
    print("=" * 60)
    print(f"Output: {args.output}")
    print()

    success = generate_baseline_image(args.output)

    print()
    print("=" * 60)
    if success:
        print("SUCCESS: Baseline image generated")
    else:
        print("FAILED: Could not generate baseline image")
        sys.exit(1)


if __name__ == "__main__":
    main()


