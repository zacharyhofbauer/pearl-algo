"""
Visual regression tests for dashboard chart generation.

This module provides required image-diff regression testing for the dashboard chart
to detect unintended visual changes. It uses deterministic synthetic data and
fixed timestamps for reproducible renders.

Usage:
    pytest tests/test_dashboard_chart_visual_regression.py -v

To update the baseline image after intentional changes:
    python3 scripts/testing/generate_dashboard_baseline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Import shared deterministic data generator
from tests.fixtures.deterministic_data import (
    generate_deterministic_ohlcv,
    SEED,
    FIXED_TITLE_TIME,
)

# Import shared visual regression utilities
from tests.fixtures.visual_regression_utils import (
    validate_png_file,
    load_image_as_array,
    compare_images,
    save_diff_artifact,
    format_regression_failure_message,
    DEFAULT_PIXEL_TOLERANCE,
    DEFAULT_MAX_DIFF_PIXELS_PCT,
    DETERMINISM_PIXEL_TOLERANCE,
    DETERMINISM_MAX_DIFF_PIXELS_PCT,
)

# === Constants ===

# Paths
FIXTURES_DIR = project_root / "tests" / "fixtures" / "charts"
BASELINE_PATH = FIXTURES_DIR / "dashboard_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"

# Use default tolerances from shared module
PIXEL_TOLERANCE = DEFAULT_PIXEL_TOLERANCE
MAX_DIFF_PIXELS_PCT = DEFAULT_MAX_DIFF_PIXELS_PCT


class TestBaselineValidity:
    """
    Baseline artifact health checks.
    
    These tests validate that the committed baseline image is a valid PNG file.
    They run before visual regression to catch silent corruption early.
    """

    def test_baseline_exists(self):
        """Baseline file must exist for visual regression to work."""
        assert BASELINE_PATH.exists(), (
            f"Baseline image not found: {BASELINE_PATH}\n"
            f"Run: python3 scripts/testing/generate_dashboard_baseline.py"
        )

    def test_baseline_is_valid_png(self):
        """
        Baseline must be a valid PNG file.
        
        This catches:
        - Corrupted files (truncated, damaged)
        - Wrong file type (e.g., Git LFS pointer instead of actual image)
        - Empty files
        """
        if not BASELINE_PATH.exists():
            pytest.skip("Baseline file does not exist")
        
        is_valid, error = validate_png_file(BASELINE_PATH)
        assert is_valid, (
            f"Baseline image is invalid: {error}\n"
            f"Regenerate with: python3 scripts/testing/generate_dashboard_baseline.py"
        )

    def test_baseline_has_reasonable_size(self):
        """Baseline should be a reasonable size for a chart image."""
        if not BASELINE_PATH.exists():
            pytest.skip("Baseline file does not exist")
        
        size_bytes = BASELINE_PATH.stat().st_size
        
        # Dashboard charts are typically 200KB-500KB at 150dpi
        min_size = 50 * 1024  # 50KB minimum
        max_size = 2 * 1024 * 1024  # 2MB maximum
        
        assert size_bytes >= min_size, (
            f"Baseline image too small ({size_bytes} bytes). "
            f"May be corrupted or a placeholder."
        )
        assert size_bytes <= max_size, (
            f"Baseline image unexpectedly large ({size_bytes} bytes). "
            f"Check for accidental inclusion of debug data."
        )


class TestDashboardChartVisualRegression:
    """Visual regression tests for dashboard chart generation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        self.data = generate_deterministic_ohlcv()
        
        # Skip if mplfinance not available
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_dashboard_chart_renders_without_error(self):
        """Sanity check: dashboard chart renders successfully."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_dashboard_chart(
            data=self.data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=288,
            range_label="36h",
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None, "Chart generation returned None"
        assert chart_path.exists(), f"Chart file not created: {chart_path}"
        assert chart_path.stat().st_size > 0, "Chart file is empty"
        
        # Clean up
        chart_path.unlink()

    def test_dashboard_chart_object_level_assertions(self):
        """Object-level assertions to catch structural changes."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        # Verify config defaults are as expected
        assert config.show_right_labels is True
        assert config.max_right_labels <= 15, "max_right_labels should be bounded"
        assert config.show_sessions is True
        assert config.show_rsi is True
        
        # Verify MA colors are defined
        from pearlalgo.nq_agent.chart_generator import MA_COLORS, VWAP_COLOR
        assert len(MA_COLORS) >= 3, "Should have at least 3 MA colors"
        assert VWAP_COLOR is not None

    def test_dashboard_chart_visual_regression(self):
        """
        Required image-diff regression test.
        
        Compares rendered dashboard chart against committed baseline.
        Fails if visual output differs beyond tolerance.
        """
        if not BASELINE_PATH.exists():
            pytest.skip(
                f"Baseline image not found: {BASELINE_PATH}\n"
                f"Run: python3 scripts/testing/generate_dashboard_baseline.py"
            )
        
        # Generate chart with deterministic settings
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_dashboard_chart(
            data=self.data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=288,
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
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None, "Chart generation failed"
        
        try:
            # Load images
            actual = load_image_as_array(chart_path)
            expected = load_image_as_array(BASELINE_PATH)
            
            assert actual is not None, f"Could not load actual chart: {chart_path}"
            assert expected is not None, f"Could not load baseline: {BASELINE_PATH}"
            
            # Compare
            passed, mean_diff, diff_pct, diff_image = compare_images(actual, expected)
            
            if not passed:
                # Save diff artifacts for debugging
                artifact_dir = save_diff_artifact(
                    actual, expected, diff_image, "dashboard", output_dir=DIFF_OUTPUT_DIR
                )
                pytest.fail(
                    format_regression_failure_message(
                        mean_diff=mean_diff,
                        diff_pct=diff_pct,
                        tolerance=PIXEL_TOLERANCE,
                        max_diff_pct=MAX_DIFF_PIXELS_PCT,
                        artifact_dir=artifact_dir,
                        baseline_update_command="python3 scripts/testing/generate_dashboard_baseline.py",
                    )
                )
        finally:
            # Clean up
            if chart_path.exists():
                chart_path.unlink()

    def test_monitor_render_mode_resolution_contract(self):
        """Monitor render mode must produce stable pixel dimensions (no bbox_inches='tight')."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)

        chart_path = generator.generate_dashboard_chart(
            data=self.data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=288,
            range_label="36h",
            figsize=(16, 4.5),  # 2560x720 @ 160 dpi
            dpi=160,
            render_mode="monitor",
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50, 200],
            show_rsi=True,
            show_pressure=True,
            title_time=FIXED_TITLE_TIME,
        )

        assert chart_path is not None and chart_path.exists(), "Monitor-mode chart generation failed"

        try:
            try:
                from PIL import Image

                with Image.open(chart_path) as img:
                    w, h = img.size
            except ImportError:
                import matplotlib.pyplot as plt

                arr = plt.imread(str(chart_path))
                h, w = int(arr.shape[0]), int(arr.shape[1])

            assert (w, h) == (2560, 720), f"Unexpected monitor PNG size: {(w, h)}"
        finally:
            try:
                chart_path.unlink()
            except Exception:
                pass

    def test_dashboard_chart_determinism(self):
        """Verify that same inputs produce identical outputs."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        # Generate twice with same parameters
        path1 = generator.generate_dashboard_chart(
            data=self.data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=288,
            range_label="36h",
            title_time=FIXED_TITLE_TIME,
        )
        
        # Reset random state for HUD context calculations
        np.random.seed(SEED)
        
        path2 = generator.generate_dashboard_chart(
            data=self.data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=288,
            range_label="36h",
            title_time=FIXED_TITLE_TIME,
        )
        
        try:
            assert path1 is not None and path2 is not None
            
            img1 = load_image_as_array(path1)
            img2 = load_image_as_array(path2)
            
            assert img1 is not None and img2 is not None
            
            # Should be nearly identical (allow for minor floating-point variance)
            passed, mean_diff, diff_pct, _ = compare_images(
                img1, img2,
                tolerance=DETERMINISM_PIXEL_TOLERANCE,
                max_diff_pct=DETERMINISM_MAX_DIFF_PIXELS_PCT,
            )
            
            assert passed, (
                f"Determinism violation: same inputs produced different outputs\n"
                f"  Mean diff: {mean_diff:.4f}, Diff pct: {diff_pct:.4f}%"
            )
        finally:
            if path1 and path1.exists():
                path1.unlink()
            if path2 and path2.exists():
                path2.unlink()


class TestDashboardChartStressScenarios:
    """Stress tests for dashboard chart edge cases."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_high_volatility_data(self):
        """Chart handles high-volatility data without crashing."""
        np.random.seed(SEED)
        
        # Generate high-volatility data
        data = generate_deterministic_ohlcv()
        data["high"] = data["high"] + np.random.randn(len(data)) * 50
        data["low"] = data["low"] - np.random.randn(len(data)) * 50
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()

    def test_low_volume_data(self):
        """Chart handles low/zero volume data."""
        data = generate_deterministic_ohlcv()
        data["volume"] = 0  # Zero volume
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()

    def test_minimal_data(self):
        """Chart handles minimal bar count."""
        data = generate_deterministic_ohlcv(num_bars=30)  # Just 30 bars
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=30,
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()

    def test_gaps_in_data(self):
        """Chart handles gaps (missing bars) gracefully."""
        data = generate_deterministic_ohlcv()
        # Remove some bars to simulate gaps
        data = data.drop(data.index[100:110])  # 10-bar gap
        data = data.reset_index(drop=True)
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


