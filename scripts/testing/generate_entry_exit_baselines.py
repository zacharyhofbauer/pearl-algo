#!/usr/bin/env python3
"""
Generate deterministic entry/exit chart baseline images for visual regression testing.

This script creates fixed synthetic OHLCV data with deterministic signals and renders
entry and exit charts for use as baselines in image-diff tests.

Usage:
    python3 scripts/testing/generate_entry_exit_baselines.py

The baseline images are saved to tests/fixtures/charts/ by default.
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
    generate_deterministic_entry_signal,
    generate_deterministic_exit_data,
    NUM_BARS,
    SEED,
)


def generate_entry_baseline(output_path: Path) -> bool:
    """
    Generate the deterministic entry chart baseline image.

    Args:
        output_path: Path to save the baseline PNG

    Returns:
        True if successful, False otherwise
    """
    try:
        from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

        # Generate deterministic data (100 bars for entry chart)
        print(f"Generating deterministic OHLCV data (100 bars, seed={SEED})...")
        data = generate_deterministic_ohlcv(num_bars=100)
        print(f"  Timestamp range: {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")
        print(f"  Price range: {data['low'].min():.2f} to {data['high'].max():.2f}")

        # Generate deterministic signal
        signal = generate_deterministic_entry_signal(data, direction="long")
        print(f"  Entry signal: {signal['direction']} @ {signal['entry_price']}")
        print(f"  Stop: {signal['stop_loss']}, Target: {signal['take_profit']}")

        # Create chart generator with default config
        config = ChartConfig()
        generator = ChartGenerator(config)

        print("Generating entry chart...")
        chart_path = generator.generate_entry_chart(
            signal=signal,
            buffer_data=data,
            symbol="MNQ",
            timeframe="5m",
        )

        if chart_path and chart_path.exists():
            # Move to output path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(chart_path, output_path)
            chart_path.unlink()  # Clean up temp file
            print(f"Entry baseline image saved: {output_path}")
            return True
        else:
            print("ERROR: Entry chart generation returned no path")
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_exit_baseline(output_path: Path) -> bool:
    """
    Generate the deterministic exit chart baseline image.

    Args:
        output_path: Path to save the baseline PNG

    Returns:
        True if successful, False otherwise
    """
    try:
        from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

        # Generate deterministic data (150 bars for exit chart - more context)
        print(f"Generating deterministic OHLCV data (150 bars, seed={SEED})...")
        data = generate_deterministic_ohlcv(num_bars=150)
        print(f"  Timestamp range: {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")
        print(f"  Price range: {data['low'].min():.2f} to {data['high'].max():.2f}")

        # Generate deterministic signal and exit
        signal = generate_deterministic_entry_signal(data, direction="long")
        exit_price, exit_reason, pnl = generate_deterministic_exit_data(data, signal)
        print(f"  Entry signal: {signal['direction']} @ {signal['entry_price']}")
        print(f"  Exit: {exit_reason} @ {exit_price}, PnL: ${pnl}")

        # Create chart generator with default config
        config = ChartConfig()
        generator = ChartGenerator(config)

        print("Generating exit chart...")
        chart_path = generator.generate_exit_chart(
            signal=signal,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            buffer_data=data,
            symbol="MNQ",
            timeframe="5m",
        )

        if chart_path and chart_path.exists():
            # Move to output path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(chart_path, output_path)
            chart_path.unlink()  # Clean up temp file
            print(f"Exit baseline image saved: {output_path}")
            return True
        else:
            print("ERROR: Exit chart generation returned no path")
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic entry/exit baseline images for visual regression testing."
    )
    parser.add_argument(
        "--entry-output",
        type=Path,
        default=project_root / "tests" / "fixtures" / "charts" / "entry_baseline.png",
        help="Output path for entry chart baseline",
    )
    parser.add_argument(
        "--exit-output",
        type=Path,
        default=project_root / "tests" / "fixtures" / "charts" / "exit_baseline.png",
        help="Output path for exit chart baseline",
    )
    parser.add_argument(
        "--entry-only",
        action="store_true",
        help="Generate only the entry chart baseline",
    )
    parser.add_argument(
        "--exit-only",
        action="store_true",
        help="Generate only the exit chart baseline",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Entry/Exit Baseline Image Generator")
    print("=" * 60)
    print()

    success = True

    if not args.exit_only:
        print("-" * 60)
        print("ENTRY CHART BASELINE")
        print("-" * 60)
        print(f"Output: {args.entry_output}")
        print()
        if not generate_entry_baseline(args.entry_output):
            success = False
        print()

    if not args.entry_only:
        print("-" * 60)
        print("EXIT CHART BASELINE")
        print("-" * 60)
        print(f"Output: {args.exit_output}")
        print()
        if not generate_exit_baseline(args.exit_output):
            success = False
        print()

    print("=" * 60)
    if success:
        print("SUCCESS: All baseline images generated")
    else:
        print("FAILED: Some baseline images could not be generated")
        sys.exit(1)


if __name__ == "__main__":
    main()


