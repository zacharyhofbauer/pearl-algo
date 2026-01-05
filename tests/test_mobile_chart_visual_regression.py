"""
Visual regression tests for mobile-sized chart generation.

This module validates that charts rendered at mobile figsize (8x5) maintain
visual integrity for Telegram mobile viewing. Mobile is the primary use case
for PearlAlgo charts, so this test ensures readability on small screens.

Usage:
    pytest tests/test_mobile_chart_visual_regression.py -v

To update the baseline image after intentional changes:
    python3 scripts/testing/generate_mobile_baseline.py
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
    SEED,
    FIXED_TITLE_TIME,
)

# === Constants ===

# Paths
FIXTURES_DIR = project_root / "tests" / "fixtures" / "charts"
MOBILE_BASELINE_PATH = FIXTURES_DIR / "mobile_dashboard_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"

# Mobile figsize (must match generate_mobile_baseline.py)
MOBILE_FIGSIZE = (8, 5)
MOBILE_DPI = 150

# Tolerance for image comparison (allows for minor font rendering differences)
PIXEL_TOLERANCE = 2.5  # Slightly higher tolerance for mobile (font scaling)
MAX_DIFF_PIXELS_PCT = 2.0  # Allow up to 2% of pixels to differ for mobile

# PNG magic bytes
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def validate_png_file(path: Path) -> tuple[bool, str]:
    """Validate that a file is a valid PNG image."""
    if not path.exists():
        return False, f"File does not exist: {path}"
    
    if path.stat().st_size == 0:
        return False, f"File is empty: {path}"
    
    try:
        with open(path, "rb") as f:
            header = f.read(8)
        if header != PNG_MAGIC:
            return False, f"Invalid PNG header: got {header!r}, expected {PNG_MAGIC!r}"
    except Exception as e:
        return False, f"Could not read file: {e}"
    
    try:
        try:
            from PIL import Image
            img = Image.open(path)
            img.verify()
        except ImportError:
            import matplotlib.pyplot as plt
            plt.imread(str(path))
    except Exception as e:
        return False, f"Image file is corrupt or unreadable: {e}"
    
    return True, ""


def load_image_as_array(path: Path) -> Optional[np.ndarray]:
    """Load an image file as a numpy array."""
    try:
        from PIL import Image
        img = Image.open(path)
        return np.array(img)
    except ImportError:
        import matplotlib.pyplot as plt
        img = plt.imread(str(path))
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
    """Compare two images with tolerance for rendering differences."""
    if actual.shape != expected.shape:
        h = min(actual.shape[0], expected.shape[0])
        w = min(actual.shape[1], expected.shape[1])
        actual = actual[:h, :w]
        expected = expected[:h, :w]
        
        if actual.shape != expected.shape:
            return False, 255.0, 100.0, None

    diff = np.abs(actual.astype(np.float32) - expected.astype(np.float32))
    mean_diff = float(np.mean(diff))
    
    diff_pixels = np.any(diff > tolerance, axis=-1) if diff.ndim == 3 else (diff > tolerance)
    diff_pct = float(np.mean(diff_pixels) * 100)
    
    diff_image = expected.copy()
    if diff.ndim == 3:
        mask = np.any(diff > tolerance, axis=-1)
        diff_image[mask] = [255, 0, 0, 255] if diff_image.shape[-1] == 4 else [255, 0, 0]
    
    passed = (mean_diff <= tolerance) and (diff_pct <= max_diff_pct)
    return passed, mean_diff, diff_pct, diff_image


class TestMobileBaselineValidity:
    """Test that the mobile baseline image is valid and not corrupted."""
    
    def test_mobile_baseline_exists(self):
        """Mobile baseline image must exist."""
        assert MOBILE_BASELINE_PATH.exists(), (
            f"Mobile baseline image not found at {MOBILE_BASELINE_PATH}. "
            "Run: python3 scripts/testing/generate_mobile_baseline.py"
        )
    
    def test_mobile_baseline_is_valid_png(self):
        """Mobile baseline must be a valid PNG file."""
        if not MOBILE_BASELINE_PATH.exists():
            pytest.skip("Mobile baseline image not found - run generate_mobile_baseline.py first")
        
        valid, error = validate_png_file(MOBILE_BASELINE_PATH)
        assert valid, f"Mobile baseline is invalid: {error}"
    
    def test_mobile_baseline_has_reasonable_size(self):
        """Mobile baseline should be smaller than desktop baseline (sanity check)."""
        if not MOBILE_BASELINE_PATH.exists():
            pytest.skip("Mobile baseline image not found")
        
        desktop_baseline = FIXTURES_DIR / "dashboard_baseline.png"
        if not desktop_baseline.exists():
            pytest.skip("Desktop baseline not found for comparison")
        
        mobile_size = MOBILE_BASELINE_PATH.stat().st_size
        desktop_size = desktop_baseline.stat().st_size
        
        # Mobile should be smaller (fewer pixels)
        assert mobile_size < desktop_size, (
            f"Mobile baseline ({mobile_size} bytes) should be smaller than "
            f"desktop baseline ({desktop_size} bytes)"
        )


class TestMobileDashboardChartVisualRegression:
    """Visual regression tests for mobile-sized dashboard charts."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_mobile_dashboard_renders_without_error(self):
        """Verify mobile dashboard chart renders without exception."""
        data = generate_deterministic_ohlcv()
        
        chart_path = self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=144,
            range_label="12h",
            figsize=MOBILE_FIGSIZE,
            dpi=MOBILE_DPI,
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50],
            show_rsi=True,
            show_pressure=False,
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None, "Mobile dashboard chart generation failed"
        assert Path(chart_path).exists(), "Mobile dashboard chart file not found"
        assert Path(chart_path).stat().st_size > 0, "Mobile dashboard chart is empty"
        
        # Cleanup
        Path(chart_path).unlink(missing_ok=True)
    
    def test_mobile_dashboard_visual_regression(self):
        """Compare generated mobile chart against baseline."""
        if not MOBILE_BASELINE_PATH.exists():
            pytest.skip("Mobile baseline image not found - run generate_mobile_baseline.py first")
        
        data = generate_deterministic_ohlcv()
        
        chart_path = self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=144,
            range_label="12h",
            figsize=MOBILE_FIGSIZE,
            dpi=MOBILE_DPI,
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50],
            show_rsi=True,
            show_pressure=False,
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None, "Mobile chart generation failed"
        
        actual = load_image_as_array(Path(chart_path))
        expected = load_image_as_array(MOBILE_BASELINE_PATH)
        
        assert actual is not None, "Could not load generated mobile chart"
        assert expected is not None, "Could not load mobile baseline image"
        
        passed, mean_diff, diff_pct, _ = compare_images(actual, expected)
        
        Path(chart_path).unlink(missing_ok=True)
        
        assert passed, (
            f"Mobile visual regression failed: mean_diff={mean_diff:.2f}, "
            f"diff_pct={diff_pct:.2f}%"
        )
    
    def test_mobile_dashboard_determinism(self):
        """Verify mobile charts are deterministic (same inputs = same outputs)."""
        data = generate_deterministic_ohlcv()
        
        # Generate two charts with identical inputs
        chart1_path = self.generator.generate_dashboard_chart(
            data=data.copy(),
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=144,
            range_label="12h",
            figsize=MOBILE_FIGSIZE,
            dpi=MOBILE_DPI,
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50],
            show_rsi=True,
            show_pressure=False,
            title_time=FIXED_TITLE_TIME,
        )
        
        chart2_path = self.generator.generate_dashboard_chart(
            data=data.copy(),
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=144,
            range_label="12h",
            figsize=MOBILE_FIGSIZE,
            dpi=MOBILE_DPI,
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50],
            show_rsi=True,
            show_pressure=False,
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart1_path is not None
        assert chart2_path is not None
        
        img1 = load_image_as_array(Path(chart1_path))
        img2 = load_image_as_array(Path(chart2_path))
        
        Path(chart1_path).unlink(missing_ok=True)
        Path(chart2_path).unlink(missing_ok=True)
        
        passed, mean_diff, diff_pct, _ = compare_images(img1, img2, tolerance=0.5, max_diff_pct=0.1)
        
        assert passed, (
            f"Mobile chart non-determinism detected: mean_diff={mean_diff:.2f}, "
            f"diff_pct={diff_pct:.2f}%"
        )


class TestMobileReadability:
    """Tests focused on mobile-specific readability concerns."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up chart generator."""
        try:
            from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")
    
    def test_mobile_chart_not_empty(self):
        """Verify mobile chart has visible content (not blank)."""
        data = generate_deterministic_ohlcv()
        
        chart_path = self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=144,
            figsize=MOBILE_FIGSIZE,
            dpi=MOBILE_DPI,
            title_time=FIXED_TITLE_TIME,
        )
        
        assert chart_path is not None
        
        img = load_image_as_array(Path(chart_path))
        Path(chart_path).unlink(missing_ok=True)
        
        # Check that the image has variation (not a solid color)
        if img is not None:
            std_dev = np.std(img)
            assert std_dev > 10, "Mobile chart appears to be blank or nearly solid"
    
    def test_mobile_entry_chart_renders(self):
        """Verify entry charts render at mobile size."""
        from tests.fixtures.deterministic_data import (
            generate_deterministic_entry_signal,
        )
        
        data = generate_deterministic_ohlcv()
        signal = generate_deterministic_entry_signal(data, direction="long")
        
        # Entry charts don't have figsize parameter, so just verify they render
        chart_path = self.generator.generate_entry_chart(
            signal=signal,
            buffer_data=data.tail(100),
            symbol="MNQ",
            timeframe="5m",
        )
        
        assert chart_path is not None, "Entry chart failed to render"
        assert Path(chart_path).stat().st_size > 0, "Entry chart is empty"
        
        Path(chart_path).unlink(missing_ok=True)





