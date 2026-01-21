"""
Visual regression tests for the on-demand `/chart` dashboard chart.

This intentionally targets the 12h lookback variant used by the Telegram /chart
command (default), to catch regressions in that specific zoom/window.

Usage:
    pytest tests/test_on_demand_chart_visual_regression.py -v

To update the baseline image after intentional changes:
    python3 scripts/testing/generate_on_demand_chart_baseline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from tests.fixtures.deterministic_data import (  # noqa: E402
    FIXED_TITLE_TIME,
    generate_deterministic_ohlcv,
)

# Import shared visual regression utilities
from tests.fixtures.visual_regression_utils import (  # noqa: E402
    validate_png_file,
    load_image_as_array,
    compare_images,
    save_diff_artifact,
    format_regression_failure_message,
    DEFAULT_PIXEL_TOLERANCE,
    DEFAULT_MAX_DIFF_PIXELS_PCT,
)

# Paths
FIXTURES_DIR = project_root / "tests" / "fixtures" / "charts"
BASELINE_PATH = FIXTURES_DIR / "on_demand_chart_12h_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"

# Use default tolerances from shared module
PIXEL_TOLERANCE = DEFAULT_PIXEL_TOLERANCE
MAX_DIFF_PIXELS_PCT = DEFAULT_MAX_DIFF_PIXELS_PCT


class TestBaselineValidity:
    def test_baseline_exists(self) -> None:
        assert BASELINE_PATH.exists(), (
            f"Baseline image not found: {BASELINE_PATH}\n"
            f"Run: python3 scripts/testing/generate_on_demand_chart_baseline.py"
        )

    def test_baseline_is_valid_png(self) -> None:
        if not BASELINE_PATH.exists():
            pytest.skip("Baseline file does not exist")
        is_valid, error = validate_png_file(BASELINE_PATH)
        assert is_valid, (
            f"Baseline image is invalid: {error}\n"
            f"Regenerate with: python3 scripts/testing/generate_on_demand_chart_baseline.py"
        )


class TestOnDemandChartVisualRegression:
    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.data = generate_deterministic_ohlcv()
        try:
            from pearlalgo.nq_agent.chart_generator import ChartConfig, ChartGenerator

            self.ChartConfig = ChartConfig
            self.ChartGenerator = ChartGenerator
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_on_demand_chart_renders_without_error(self) -> None:
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)

        lookback_bars = 12 * 60 // 5  # 12h of 5m bars

        chart_path = generator.generate_dashboard_chart(
            data=self.data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=min(int(lookback_bars), len(self.data)),
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

        assert chart_path is not None and chart_path.exists(), "Chart generation failed"

        # Clean up
        try:
            chart_path.unlink()
        except Exception:
            pass

    def test_on_demand_chart_visual_regression(self) -> None:
        if not BASELINE_PATH.exists():
            pytest.skip("Baseline file does not exist")

        expected = load_image_as_array(BASELINE_PATH)
        assert expected is not None, "Failed to load baseline image"

        config = self.ChartConfig()
        generator = self.ChartGenerator(config)

        lookback_bars = 12 * 60 // 5

        chart_path = generator.generate_dashboard_chart(
            data=self.data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=min(int(lookback_bars), len(self.data)),
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

        assert chart_path is not None and chart_path.exists(), "Chart generation failed"

        actual = load_image_as_array(chart_path)
        assert actual is not None, "Failed to load generated image"

        passed, mean_diff, diff_pct, diff_img = compare_images(actual, expected)

        if not passed:
            artifact_dir = save_diff_artifact(
                actual, expected, diff_img, "on_demand_chart_12h", output_dir=DIFF_OUTPUT_DIR
            )

        # Clean up
        try:
            chart_path.unlink()
        except Exception:
            pass

        if not passed:
            pytest.fail(
                format_regression_failure_message(
                    mean_diff=mean_diff,
                    diff_pct=diff_pct,
                    tolerance=PIXEL_TOLERANCE,
                    max_diff_pct=MAX_DIFF_PIXELS_PCT,
                    artifact_dir=artifact_dir,
                    baseline_update_command="python3 scripts/testing/generate_on_demand_chart_baseline.py",
                )
            )






