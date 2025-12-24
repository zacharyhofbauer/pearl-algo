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

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# === Constants ===

# Fixed seed and timestamps for reproducibility (must match generate_dashboard_baseline.py)
SEED = 42
BASE_TIMESTAMP = datetime(2024, 12, 20, 0, 0, 0, tzinfo=timezone.utc)
NUM_BARS = 432  # 36h of 5m bars
FIXED_TITLE_TIME = "12:00 UTC"

# Paths
FIXTURES_DIR = project_root / "tests" / "fixtures" / "charts"
BASELINE_PATH = FIXTURES_DIR / "dashboard_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"

# Tolerance for image comparison (allows for minor font rendering differences)
# Measured as mean absolute difference per pixel (0-255 scale)
PIXEL_TOLERANCE = 2.0  # Allow ~0.8% variance per channel
MAX_DIFF_PIXELS_PCT = 1.0  # Allow up to 1% of pixels to differ


def generate_deterministic_ohlcv(
    num_bars: int = NUM_BARS,
    base_timestamp: datetime = BASE_TIMESTAMP,
    seed: int = SEED,
    base_price: float = 25000.0,
) -> pd.DataFrame:
    """
    Generate deterministic synthetic OHLCV data for MNQ-style futures.
    
    Must match the implementation in generate_dashboard_baseline.py.
    """
    np.random.seed(seed)

    timestamps = [base_timestamp + timedelta(minutes=5 * i) for i in range(num_bars)]
    price_changes = np.random.randn(num_bars) * 8
    prices = base_price + np.cumsum(price_changes)

    data = []
    for i, (ts, price) in enumerate(zip(timestamps, prices)):
        candle_range = abs(np.random.randn() * 8) + 5

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

    return pd.DataFrame(data)


def load_image_as_array(path: Path) -> Optional[np.ndarray]:
    """Load an image file as a numpy array."""
    try:
        from PIL import Image
        img = Image.open(path)
        return np.array(img)
    except ImportError:
        # Fallback to matplotlib
        import matplotlib.pyplot as plt
        img = plt.imread(str(path))
        # Convert to uint8 if normalized float
        if img.dtype == np.float32 or img.dtype == np.float64:
            img = (img * 255).astype(np.uint8)
        return img
    except Exception:
        return None


def compare_images(
    actual: np.ndarray,
    expected: np.ndarray,
    tolerance: float = PIXEL_TOLERANCE,
    max_diff_pct: float = MAX_DIFF_PIXELS_PCT,
) -> tuple[bool, float, float, Optional[np.ndarray]]:
    """
    Compare two images with tolerance for rendering differences.
    
    Returns:
        (passed, mean_diff, diff_pct, diff_image)
    """
    # Handle shape differences
    if actual.shape != expected.shape:
        # Try to align by cropping/padding to smaller dimensions
        h = min(actual.shape[0], expected.shape[0])
        w = min(actual.shape[1], expected.shape[1])
        actual = actual[:h, :w]
        expected = expected[:h, :w]
        
        # If still different (e.g., channel count), fail
        if actual.shape != expected.shape:
            return False, 255.0, 100.0, None

    # Compute difference
    diff = np.abs(actual.astype(np.float32) - expected.astype(np.float32))
    
    # Mean difference per pixel
    mean_diff = float(np.mean(diff))
    
    # Percentage of pixels with any difference
    diff_pixels = np.any(diff > tolerance, axis=-1) if diff.ndim == 3 else (diff > tolerance)
    diff_pct = float(np.mean(diff_pixels) * 100)
    
    # Create diff visualization (highlight differences in red)
    diff_image = expected.copy()
    if diff.ndim == 3:
        mask = np.any(diff > tolerance, axis=-1)
        diff_image[mask] = [255, 0, 0, 255] if diff_image.shape[-1] == 4 else [255, 0, 0]
    
    passed = (mean_diff <= tolerance) and (diff_pct <= max_diff_pct)
    return passed, mean_diff, diff_pct, diff_image


def save_diff_artifact(
    actual: np.ndarray,
    expected: np.ndarray,
    diff: Optional[np.ndarray],
    name: str,
) -> Path:
    """Save comparison artifacts for debugging failed tests."""
    DIFF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        from PIL import Image
        
        if actual is not None:
            Image.fromarray(actual).save(DIFF_OUTPUT_DIR / f"{name}_actual.png")
        if expected is not None:
            Image.fromarray(expected).save(DIFF_OUTPUT_DIR / f"{name}_expected.png")
        if diff is not None:
            Image.fromarray(diff).save(DIFF_OUTPUT_DIR / f"{name}_diff.png")
    except ImportError:
        import matplotlib.pyplot as plt
        
        if actual is not None:
            plt.imsave(str(DIFF_OUTPUT_DIR / f"{name}_actual.png"), actual)
        if expected is not None:
            plt.imsave(str(DIFF_OUTPUT_DIR / f"{name}_expected.png"), expected)
        if diff is not None:
            plt.imsave(str(DIFF_OUTPUT_DIR / f"{name}_diff.png"), diff)
    
    return DIFF_OUTPUT_DIR


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
                artifact_dir = save_diff_artifact(actual, expected, diff_image, "dashboard")
                pytest.fail(
                    f"Visual regression detected!\n"
                    f"  Mean pixel difference: {mean_diff:.2f} (tolerance: {PIXEL_TOLERANCE})\n"
                    f"  Pixels differing: {diff_pct:.2f}% (tolerance: {MAX_DIFF_PIXELS_PCT}%)\n"
                    f"  Diff artifacts saved to: {artifact_dir}\n"
                    f"\n"
                    f"If this change is intentional, update the baseline:\n"
                    f"  python3 scripts/testing/generate_dashboard_baseline.py"
                )
        finally:
            # Clean up
            if chart_path.exists():
                chart_path.unlink()

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
                tolerance=0.5,  # Very tight tolerance for same-run comparison
                max_diff_pct=0.1,
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


