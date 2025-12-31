"""
Visual regression tests for entry and exit chart generation.

This module provides required image-diff regression testing for entry and exit charts
to detect unintended visual changes. It uses deterministic synthetic data and
signals for reproducible renders.

Usage:
    pytest tests/test_entry_exit_chart_visual_regression.py -v

To update baseline images after intentional changes:
    python3 scripts/testing/generate_entry_exit_baselines.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Import shared deterministic data generator
from tests.fixtures.deterministic_data import (
    generate_deterministic_ohlcv,
    generate_deterministic_entry_signal,
    generate_deterministic_exit_data,
    SEED,
)

# Reuse validation and comparison utilities from dashboard tests
from tests.test_dashboard_chart_visual_regression import (
    validate_png_file,
    load_image_as_array,
    compare_images,
    save_diff_artifact,
    PIXEL_TOLERANCE,
    MAX_DIFF_PIXELS_PCT,
)

# === Constants ===

# Paths
FIXTURES_DIR = project_root / "tests" / "fixtures" / "charts"
ENTRY_BASELINE_PATH = FIXTURES_DIR / "entry_baseline.png"
EXIT_BASELINE_PATH = FIXTURES_DIR / "exit_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"


class TestEntryExitBaselineValidity:
    """
    Baseline artifact health checks for entry/exit charts.
    
    These tests validate that the committed baseline images are valid PNG files.
    """

    def test_entry_baseline_exists(self):
        """Entry baseline file must exist for visual regression to work."""
        assert ENTRY_BASELINE_PATH.exists(), (
            f"Entry baseline not found: {ENTRY_BASELINE_PATH}\n"
            f"Run: python3 scripts/testing/generate_entry_exit_baselines.py"
        )

    def test_entry_baseline_is_valid_png(self):
        """Entry baseline must be a valid PNG file."""
        if not ENTRY_BASELINE_PATH.exists():
            pytest.skip("Entry baseline file does not exist")
        
        is_valid, error = validate_png_file(ENTRY_BASELINE_PATH)
        assert is_valid, (
            f"Entry baseline is invalid: {error}\n"
            f"Regenerate with: python3 scripts/testing/generate_entry_exit_baselines.py"
        )

    def test_exit_baseline_exists(self):
        """Exit baseline file must exist for visual regression to work."""
        assert EXIT_BASELINE_PATH.exists(), (
            f"Exit baseline not found: {EXIT_BASELINE_PATH}\n"
            f"Run: python3 scripts/testing/generate_entry_exit_baselines.py"
        )

    def test_exit_baseline_is_valid_png(self):
        """Exit baseline must be a valid PNG file."""
        if not EXIT_BASELINE_PATH.exists():
            pytest.skip("Exit baseline file does not exist")
        
        is_valid, error = validate_png_file(EXIT_BASELINE_PATH)
        assert is_valid, (
            f"Exit baseline is invalid: {error}\n"
            f"Regenerate with: python3 scripts/testing/generate_entry_exit_baselines.py"
        )


class TestEntryChartVisualRegression:
    """Visual regression tests for entry chart generation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        # Generate deterministic data (100 bars for entry chart)
        self.data = generate_deterministic_ohlcv(num_bars=100)
        self.signal = generate_deterministic_entry_signal(self.data, direction="long")
        
        # Skip if mplfinance not available
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_entry_chart_renders_without_error(self):
        """Sanity check: entry chart renders successfully."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_entry_chart(
            signal=self.signal,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Entry chart generation returned None"
        assert chart_path.exists(), f"Entry chart file not created: {chart_path}"
        assert chart_path.stat().st_size > 0, "Entry chart file is empty"
        
        # Clean up
        chart_path.unlink()

    def test_entry_chart_visual_regression(self):
        """
        Required image-diff regression test for entry chart.
        
        Compares rendered entry chart against committed baseline.
        """
        if not ENTRY_BASELINE_PATH.exists():
            pytest.skip(
                f"Entry baseline not found: {ENTRY_BASELINE_PATH}\n"
                f"Run: python3 scripts/testing/generate_entry_exit_baselines.py"
            )
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_entry_chart(
            signal=self.signal,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Entry chart generation failed"
        
        try:
            # Load images
            actual = load_image_as_array(chart_path)
            expected = load_image_as_array(ENTRY_BASELINE_PATH)
            
            assert actual is not None, f"Could not load actual chart: {chart_path}"
            assert expected is not None, f"Could not load baseline: {ENTRY_BASELINE_PATH}"
            
            # Compare
            passed, mean_diff, diff_pct, diff_image = compare_images(actual, expected)
            
            if not passed:
                artifact_dir = save_diff_artifact(actual, expected, diff_image, "entry")
                pytest.fail(
                    f"Entry chart visual regression detected!\n"
                    f"  Mean pixel difference: {mean_diff:.2f} (tolerance: {PIXEL_TOLERANCE})\n"
                    f"  Pixels differing: {diff_pct:.2f}% (tolerance: {MAX_DIFF_PIXELS_PCT}%)\n"
                    f"  Diff artifacts saved to: {artifact_dir}\n"
                    f"\n"
                    f"If this change is intentional, update the baseline:\n"
                    f"  python3 scripts/testing/generate_entry_exit_baselines.py --entry-only"
                )
        finally:
            if chart_path.exists():
                chart_path.unlink()

    def test_entry_chart_determinism(self):
        """Verify that same inputs produce identical entry chart outputs."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        # Generate twice with same parameters
        path1 = generator.generate_entry_chart(
            signal=self.signal,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        np.random.seed(SEED)
        
        path2 = generator.generate_entry_chart(
            signal=self.signal,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        try:
            assert path1 is not None and path2 is not None
            
            img1 = load_image_as_array(path1)
            img2 = load_image_as_array(path2)
            
            assert img1 is not None and img2 is not None
            
            passed, mean_diff, diff_pct, _ = compare_images(
                img1, img2,
                tolerance=0.5,
                max_diff_pct=0.1,
            )
            
            assert passed, (
                f"Entry chart determinism violation\n"
                f"  Mean diff: {mean_diff:.4f}, Diff pct: {diff_pct:.4f}%"
            )
        finally:
            if path1 and path1.exists():
                path1.unlink()
            if path2 and path2.exists():
                path2.unlink()


class TestExitChartVisualRegression:
    """Visual regression tests for exit chart generation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        # Generate deterministic data (150 bars for exit chart)
        self.data = generate_deterministic_ohlcv(num_bars=150)
        self.signal = generate_deterministic_entry_signal(self.data, direction="long")
        self.exit_price, self.exit_reason, self.pnl = generate_deterministic_exit_data(
            self.data, self.signal
        )
        
        # Skip if mplfinance not available
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_exit_chart_renders_without_error(self):
        """Sanity check: exit chart renders successfully."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_exit_chart(
            signal=self.signal,
            exit_price=self.exit_price,
            exit_reason=self.exit_reason,
            pnl=self.pnl,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Exit chart generation returned None"
        assert chart_path.exists(), f"Exit chart file not created: {chart_path}"
        assert chart_path.stat().st_size > 0, "Exit chart file is empty"
        
        # Clean up
        chart_path.unlink()

    def test_exit_chart_visual_regression(self):
        """
        Required image-diff regression test for exit chart.
        
        Compares rendered exit chart against committed baseline.
        """
        if not EXIT_BASELINE_PATH.exists():
            pytest.skip(
                f"Exit baseline not found: {EXIT_BASELINE_PATH}\n"
                f"Run: python3 scripts/testing/generate_entry_exit_baselines.py"
            )
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_exit_chart(
            signal=self.signal,
            exit_price=self.exit_price,
            exit_reason=self.exit_reason,
            pnl=self.pnl,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Exit chart generation failed"
        
        try:
            # Load images
            actual = load_image_as_array(chart_path)
            expected = load_image_as_array(EXIT_BASELINE_PATH)
            
            assert actual is not None, f"Could not load actual chart: {chart_path}"
            assert expected is not None, f"Could not load baseline: {EXIT_BASELINE_PATH}"
            
            # Compare
            passed, mean_diff, diff_pct, diff_image = compare_images(actual, expected)
            
            if not passed:
                artifact_dir = save_diff_artifact(actual, expected, diff_image, "exit")
                pytest.fail(
                    f"Exit chart visual regression detected!\n"
                    f"  Mean pixel difference: {mean_diff:.2f} (tolerance: {PIXEL_TOLERANCE})\n"
                    f"  Pixels differing: {diff_pct:.2f}% (tolerance: {MAX_DIFF_PIXELS_PCT}%)\n"
                    f"  Diff artifacts saved to: {artifact_dir}\n"
                    f"\n"
                    f"If this change is intentional, update the baseline:\n"
                    f"  python3 scripts/testing/generate_entry_exit_baselines.py --exit-only"
                )
        finally:
            if chart_path.exists():
                chart_path.unlink()

    def test_exit_chart_determinism(self):
        """Verify that same inputs produce identical exit chart outputs."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        # Generate twice with same parameters
        path1 = generator.generate_exit_chart(
            signal=self.signal,
            exit_price=self.exit_price,
            exit_reason=self.exit_reason,
            pnl=self.pnl,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        np.random.seed(SEED)
        
        path2 = generator.generate_exit_chart(
            signal=self.signal,
            exit_price=self.exit_price,
            exit_reason=self.exit_reason,
            pnl=self.pnl,
            buffer_data=self.data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        try:
            assert path1 is not None and path2 is not None
            
            img1 = load_image_as_array(path1)
            img2 = load_image_as_array(path2)
            
            assert img1 is not None and img2 is not None
            
            passed, mean_diff, diff_pct, _ = compare_images(
                img1, img2,
                tolerance=0.5,
                max_diff_pct=0.1,
            )
            
            assert passed, (
                f"Exit chart determinism violation\n"
                f"  Mean diff: {mean_diff:.4f}, Diff pct: {diff_pct:.4f}%"
            )
        finally:
            if path1 and path1.exists():
                path1.unlink()
            if path2 and path2.exists():
                path2.unlink()


class TestEntryExitChartEdgeCases:
    """Edge case tests for entry/exit charts."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_short_direction_entry_chart(self):
        """Entry chart renders correctly for short signals."""
        data = generate_deterministic_ohlcv(num_bars=100)
        signal = generate_deterministic_entry_signal(data, direction="short")
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_entry_chart(
            signal=signal,
            buffer_data=data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()

    def test_loss_exit_chart(self):
        """Exit chart renders correctly for losing trades."""
        data = generate_deterministic_ohlcv(num_bars=150)
        signal = generate_deterministic_entry_signal(data, direction="long")
        
        # Simulate hitting stop loss (loss)
        exit_price = signal["stop_loss"]
        exit_reason = "stop_loss"
        pnl = (exit_price - signal["entry_price"]) * 2.0  # Negative for loss
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_exit_chart(
            signal=signal,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            buffer_data=data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()

    def test_minimal_data_entry_chart(self):
        """Entry chart handles minimal bar count."""
        data = generate_deterministic_ohlcv(num_bars=30)
        signal = {
            "type": "test",
            "direction": "long",
            "entry_price": float(data["close"].iloc[-1]),
            "stop_loss": float(data["close"].iloc[-1]) - 10,
            "take_profit": float(data["close"].iloc[-1]) + 15,
            "timestamp": str(data["timestamp"].iloc[-1]),
        }
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_entry_chart(
            signal=signal,
            buffer_data=data,
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])






