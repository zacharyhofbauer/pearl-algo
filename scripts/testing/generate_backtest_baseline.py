#!/usr/bin/env python3
"""
Generate deterministic backtest chart baseline image for visual regression testing.

This script creates fixed synthetic OHLCV data with deterministic signals and renders
a backtest chart for use as a baseline in image-diff tests.

Usage:
    python3 scripts/testing/generate_backtest_baseline.py

The baseline image is saved to tests/fixtures/charts/backtest_baseline.png by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path (for both src/ and tests/)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

# Import shared deterministic data generator
from tests.fixtures.deterministic_data import (
    generate_deterministic_ohlcv,
    generate_deterministic_backtest_signals,
    NUM_BARS,
    SEED,
)


def generate_backtest_baseline(output_path: Path) -> bool:
    """
    Generate the deterministic backtest chart baseline image.

    Args:
        output_path: Path to save the baseline PNG

    Returns:
        True if successful, False otherwise
    """
    try:
        from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

        # Generate deterministic data (300 bars for backtest - enough for multiple signals)
        num_bars = 300
        print(f"Generating deterministic OHLCV data ({num_bars} bars, seed={SEED})...")
        data = generate_deterministic_ohlcv(num_bars=num_bars)
        print(f"  Timestamp range: {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")
        print(f"  Price range: {data['low'].min():.2f} to {data['high'].max():.2f}")

        # Generate deterministic signals
        signals = generate_deterministic_backtest_signals(data, num_signals=8)
        print(f"  Generated {len(signals)} signals:")
        for i, sig in enumerate(signals):
            outcome = "WIN" if sig["pnl"] > 0 else "LOSS"
            print(f"    [{i}] {sig['direction']} @ {sig['entry_price']:.2f} -> ${sig['pnl']:.2f} ({outcome})")

        # Create chart generator with default config
        config = ChartConfig()
        generator = ChartGenerator(config)

        # Performance data for title
        total_pnl = sum(s["pnl"] for s in signals)
        wins = sum(1 for s in signals if s["pnl"] > 0)
        losses = len(signals) - wins
        performance_data = {
            "total_pnl": total_pnl,
            "total_trades": len(signals),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(signals) * 100 if signals else 0,
        }

        print("Generating backtest chart...")
        chart_path = generator.generate_backtest_chart(
            backtest_data=data,
            signals=signals,
            symbol="MNQ",
            title="Backtest Results",
            performance_data=performance_data,
            timeframe="5m",
        )

        if chart_path and chart_path.exists():
            # Move to output path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(chart_path, output_path)
            chart_path.unlink()  # Clean up temp file
            print(f"Backtest baseline image saved: {output_path}")
            return True
        else:
            print("ERROR: Backtest chart generation returned no path")
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic backtest baseline image for visual regression testing."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "tests" / "fixtures" / "charts" / "backtest_baseline.png",
        help="Output path for baseline image",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Backtest Baseline Image Generator")
    print("=" * 60)
    print(f"Output: {args.output}")
    print()

    success = generate_backtest_baseline(args.output)

    print()
    print("=" * 60)
    if success:
        print("SUCCESS: Baseline image generated")
    else:
        print("FAILED: Could not generate baseline image")
        sys.exit(1)


if __name__ == "__main__":
    main()

