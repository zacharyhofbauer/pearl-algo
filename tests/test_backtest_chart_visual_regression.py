"""
Visual regression tests for backtest chart generation.

This module provides required image-diff regression testing for the backtest chart
to detect unintended visual changes. It uses deterministic synthetic data and
signals for reproducible renders.

Usage:
    pytest tests/test_backtest_chart_visual_regression.py -v

To update the baseline image after intentional changes:
    python3 scripts/testing/generate_backtest_baseline.py
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
    generate_deterministic_backtest_signals,
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
BACKTEST_BASELINE_PATH = FIXTURES_DIR / "backtest_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"


class TestBacktestBaselineValidity:
    """
    Baseline artifact health checks for backtest chart.
    
    These tests validate that the committed baseline image is a valid PNG file.
    """

    def test_backtest_baseline_exists(self):
        """Backtest baseline file must exist for visual regression to work."""
        assert BACKTEST_BASELINE_PATH.exists(), (
            f"Backtest baseline not found: {BACKTEST_BASELINE_PATH}\n"
            f"Run: python3 scripts/testing/generate_backtest_baseline.py"
        )

    def test_backtest_baseline_is_valid_png(self):
        """Backtest baseline must be a valid PNG file."""
        if not BACKTEST_BASELINE_PATH.exists():
            pytest.skip("Backtest baseline file does not exist")
        
        is_valid, error = validate_png_file(BACKTEST_BASELINE_PATH)
        assert is_valid, (
            f"Backtest baseline is invalid: {error}\n"
            f"Regenerate with: python3 scripts/testing/generate_backtest_baseline.py"
        )


class TestBacktestChartVisualRegression:
    """Visual regression tests for backtest chart generation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        # Generate deterministic data (300 bars for backtest)
        self.data = generate_deterministic_ohlcv(num_bars=300)
        self.signals = generate_deterministic_backtest_signals(self.data, num_signals=8)
        
        # Performance data
        total_pnl = sum(s["pnl"] for s in self.signals)
        wins = sum(1 for s in self.signals if s["pnl"] > 0)
        self.performance_data = {
            "total_pnl": total_pnl,
            "total_trades": len(self.signals),
            "wins": wins,
            "losses": len(self.signals) - wins,
            "win_rate": wins / len(self.signals) * 100 if self.signals else 0,
        }
        
        # Skip if mplfinance not available
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_backtest_chart_renders_without_error(self):
        """Sanity check: backtest chart renders successfully."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_backtest_chart(
            backtest_data=self.data,
            signals=self.signals,
            symbol="MNQ",
            title="Backtest Results",
            performance_data=self.performance_data,
            timeframe="5m",
        )
        
        assert chart_path is not None, "Backtest chart generation returned None"
        assert chart_path.exists(), f"Backtest chart file not created: {chart_path}"
        assert chart_path.stat().st_size > 0, "Backtest chart file is empty"
        
        # Clean up
        chart_path.unlink()

    def test_backtest_chart_visual_regression(self):
        """
        Required image-diff regression test for backtest chart.
        
        Compares rendered backtest chart against committed baseline.
        """
        if not BACKTEST_BASELINE_PATH.exists():
            pytest.skip(
                f"Backtest baseline not found: {BACKTEST_BASELINE_PATH}\n"
                f"Run: python3 scripts/testing/generate_backtest_baseline.py"
            )
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_backtest_chart(
            backtest_data=self.data,
            signals=self.signals,
            symbol="MNQ",
            title="Backtest Results",
            performance_data=self.performance_data,
            timeframe="5m",
        )
        
        assert chart_path is not None, "Backtest chart generation failed"
        
        try:
            # Load images
            actual = load_image_as_array(chart_path)
            expected = load_image_as_array(BACKTEST_BASELINE_PATH)
            
            assert actual is not None, f"Could not load actual chart: {chart_path}"
            assert expected is not None, f"Could not load baseline: {BACKTEST_BASELINE_PATH}"
            
            # Compare
            passed, mean_diff, diff_pct, diff_image = compare_images(actual, expected)
            
            if not passed:
                artifact_dir = save_diff_artifact(actual, expected, diff_image, "backtest")
                pytest.fail(
                    f"Backtest chart visual regression detected!\n"
                    f"  Mean pixel difference: {mean_diff:.2f} (tolerance: {PIXEL_TOLERANCE})\n"
                    f"  Pixels differing: {diff_pct:.2f}% (tolerance: {MAX_DIFF_PIXELS_PCT}%)\n"
                    f"  Diff artifacts saved to: {artifact_dir}\n"
                    f"\n"
                    f"If this change is intentional, update the baseline:\n"
                    f"  python3 scripts/testing/generate_backtest_baseline.py"
                )
        finally:
            if chart_path.exists():
                chart_path.unlink()

    def test_backtest_chart_determinism(self):
        """Verify that same inputs produce identical backtest chart outputs."""
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        # Generate twice with same parameters
        path1 = generator.generate_backtest_chart(
            backtest_data=self.data,
            signals=self.signals,
            symbol="MNQ",
            title="Backtest Results",
            performance_data=self.performance_data,
            timeframe="5m",
        )
        
        np.random.seed(SEED)
        
        path2 = generator.generate_backtest_chart(
            backtest_data=self.data,
            signals=self.signals,
            symbol="MNQ",
            title="Backtest Results",
            performance_data=self.performance_data,
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
                f"Backtest chart determinism violation\n"
                f"  Mean diff: {mean_diff:.4f}, Diff pct: {diff_pct:.4f}%"
            )
        finally:
            if path1 and path1.exists():
                path1.unlink()
            if path2 and path2.exists():
                path2.unlink()


class TestBacktestChartEdgeCases:
    """Edge case tests for backtest charts."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.ChartGenerator = ChartGenerator
            self.ChartConfig = ChartConfig
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def test_empty_signals_backtest_chart(self):
        """Backtest chart renders correctly with no signals."""
        data = generate_deterministic_ohlcv(num_bars=100)
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_backtest_chart(
            backtest_data=data,
            signals=[],  # Empty signals
            symbol="MNQ",
            title="Backtest (No Trades)",
            timeframe="5m",
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()

    def test_single_signal_backtest_chart(self):
        """Backtest chart renders correctly with a single signal."""
        data = generate_deterministic_ohlcv(num_bars=100)
        signals = generate_deterministic_backtest_signals(data, num_signals=1)
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_backtest_chart(
            backtest_data=data,
            signals=signals,
            symbol="MNQ",
            title="Backtest (Single Trade)",
            timeframe="5m",
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()

    def test_many_signals_backtest_chart(self):
        """Backtest chart renders correctly with many signals (marker soup test)."""
        data = generate_deterministic_ohlcv(num_bars=500)
        signals = generate_deterministic_backtest_signals(data, num_signals=30)
        
        config = self.ChartConfig()
        generator = self.ChartGenerator(config)
        
        chart_path = generator.generate_backtest_chart(
            backtest_data=data,
            signals=signals,
            symbol="MNQ",
            title="Backtest (Many Trades)",
            timeframe="5m",
        )
        
        assert chart_path is not None
        assert chart_path.exists()
        chart_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])



