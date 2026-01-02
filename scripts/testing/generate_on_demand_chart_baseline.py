#!/usr/bin/env python3
"""
Generate deterministic baseline image for the /chart (on-demand) dashboard chart.

This baseline targets the *12h lookback* variant (the /chart default), which is
distinct from the main dashboard baseline that uses a larger window.

Usage:
    python3 scripts/testing/generate_on_demand_chart_baseline.py [--output PATH]

The baseline image is saved to:
    tests/fixtures/charts/on_demand_chart_12h_baseline.png
by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path (for both src/ and tests/)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

from tests.fixtures.deterministic_data import (  # noqa: E402
    FIXED_TITLE_TIME,
    NUM_BARS,
    SEED,
    generate_deterministic_ohlcv,
)


def generate_baseline_image(output_path: Path) -> bool:
    try:
        from pearlalgo.nq_agent.chart_generator import ChartConfig, ChartGenerator

        # Generate deterministic data
        print(f"Generating deterministic OHLCV data ({NUM_BARS} bars, seed={SEED})...")
        data = generate_deterministic_ohlcv()
        print(f"  Timestamp range: {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")
        print(f"  Price range: {data['low'].min():.2f} to {data['high'].max():.2f}")

        config = ChartConfig()
        generator = ChartGenerator(config)

        # 12h of 5m bars = 144 bars
        lookback_bars = 12 * 60 // 5

        print("Generating on-demand (/chart) dashboard chart baseline (12h)...")
        chart_path = generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=min(int(lookback_bars), len(data)),
            # Keep range_label=None to match production /chart behavior (title uses "Dashboard")
            range_label=None,
            figsize=(16, 7),
            dpi=150,
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50, 200],
            show_rsi=True,
            show_pressure=True,
            title_time=FIXED_TITLE_TIME,
        )

        if chart_path and chart_path.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy(chart_path, output_path)
            chart_path.unlink()  # Clean up temp file
            print(f"Baseline image saved: {output_path}")
            return True

        print("ERROR: Chart generation returned no path")
        return False

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline image for the /chart (on-demand) dashboard chart."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root
        / "tests"
        / "fixtures"
        / "charts"
        / "on_demand_chart_12h_baseline.png",
        help="Output path for baseline image",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("On-Demand Chart Baseline Image Generator (12h)")
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





