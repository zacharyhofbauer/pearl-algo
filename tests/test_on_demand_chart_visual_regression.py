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
from typing import Optional

import numpy as np
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from tests.fixtures.deterministic_data import (  # noqa: E402
    FIXED_TITLE_TIME,
    generate_deterministic_ohlcv,
)


# Paths
FIXTURES_DIR = project_root / "tests" / "fixtures" / "charts"
BASELINE_PATH = FIXTURES_DIR / "on_demand_chart_12h_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"

# Tolerance for image comparison (allows for minor font rendering differences)
PIXEL_TOLERANCE = 2.0
MAX_DIFF_PIXELS_PCT = 1.0

# PNG magic bytes
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def validate_png_file(path: Path) -> tuple[bool, str]:
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
    try:
        from PIL import Image

        img = Image.open(path)
        return np.array(img)
    except ImportError:
        import matplotlib.pyplot as plt

        img = plt.imread(str(path))
        if img.dtype in (np.float32, np.float64):
            img = (img * 255).astype(np.uint8)
        return img
    except Exception:
        return None


def compare_images(
    actual: np.ndarray,
    expected: np.ndarray,
    *,
    tolerance: float = PIXEL_TOLERANCE,
    max_diff_pct: float = MAX_DIFF_PIXELS_PCT,
) -> tuple[bool, float, float, Optional[np.ndarray]]:
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


def save_diff_artifact(
    actual: np.ndarray,
    expected: np.ndarray,
    diff: Optional[np.ndarray],
    name: str,
) -> None:
    DIFF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image

        Image.fromarray(actual).save(DIFF_OUTPUT_DIR / f"{name}_actual.png")
        Image.fromarray(expected).save(DIFF_OUTPUT_DIR / f"{name}_expected.png")
        if diff is not None:
            Image.fromarray(diff).save(DIFF_OUTPUT_DIR / f"{name}_diff.png")
    except ImportError:
        import matplotlib.pyplot as plt

        plt.imsave(str(DIFF_OUTPUT_DIR / f"{name}_actual.png"), actual)
        plt.imsave(str(DIFF_OUTPUT_DIR / f"{name}_expected.png"), expected)
        if diff is not None:
            plt.imsave(str(DIFF_OUTPUT_DIR / f"{name}_diff.png"), diff)


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
            save_diff_artifact(actual, expected, diff_img, name="on_demand_chart_12h")

        # Clean up
        try:
            chart_path.unlink()
        except Exception:
            pass

        assert passed, (
            "On-demand chart visual regression failed.\n"
            f"Mean pixel diff: {mean_diff:.2f} (tolerance {PIXEL_TOLERANCE})\n"
            f"Diff pixels: {diff_pct:.2f}% (max {MAX_DIFF_PIXELS_PCT}%)\n"
            f"To update baseline (intentional change):\n"
            f"  python3 scripts/testing/generate_on_demand_chart_baseline.py\n"
            f"Artifacts saved to: {DIFF_OUTPUT_DIR}\n"
        )




