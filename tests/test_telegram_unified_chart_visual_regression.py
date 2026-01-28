"""
Visual regression tests for the unified Telegram chart template.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from tests.fixtures.deterministic_data import (  # noqa: E402
    FIXED_TITLE_TIME,
    generate_deterministic_ohlcv,
)
from tests.fixtures.trade_overlay_fixtures import (  # noqa: E402
    apply_telegram_render_profile,
    build_trade_list,
)
from tests.fixtures.visual_regression_utils import (  # noqa: E402
    compare_images,
    load_image_as_array,
    validate_png_file,
    MOBILE_PIXEL_TOLERANCE,
    MOBILE_MAX_DIFF_PIXELS_PCT,
    DETERMINISM_PIXEL_TOLERANCE,
    DETERMINISM_MAX_DIFF_PIXELS_PCT,
)
from pearlalgo.market_agent.chart_profiles import (  # noqa: E402
    TELEGRAM_UNIFIED_FIGSIZE,
    TELEGRAM_UNIFIED_DPI,
)

FIXTURES_DIR = project_root / "tests" / "fixtures" / "charts"
UNIFIED_BASELINE_PATH = FIXTURES_DIR / "telegram_unified_dashboard_baseline.png"
DIFF_OUTPUT_DIR = project_root / "tests" / "artifacts"

PIXEL_TOLERANCE = MOBILE_PIXEL_TOLERANCE
MAX_DIFF_PIXELS_PCT = MOBILE_MAX_DIFF_PIXELS_PCT


def _build_pnl_overlay(trades: list[dict], *, range_label: str) -> dict | None:
    closed = [t for t in trades if isinstance(t, dict) and t.get("pnl") is not None]
    if not closed:
        return None
    try:
        def _ts(x):
            try:
                return x if x is not None else ""
            except Exception:
                return ""
        closed.sort(key=lambda t: _ts(t.get("exit_time") or t.get("entry_time")))
        pnl_vals = []
        wins = 0
        for t in closed:
            try:
                v = float(t.get("pnl") or 0.0)
            except Exception:
                v = 0.0
            pnl_vals.append(v)
            if v > 0:
                wins += 1
        total_pnl = float(sum(pnl_vals)) if pnl_vals else 0.0
        trades_count = int(len(pnl_vals))
        win_rate = float((wins / trades_count) * 100.0) if trades_count > 0 else 0.0
        curve = []
        run = 0.0
        for v in pnl_vals:
            run += float(v)
            curve.append(run)
        return {
            "daily_pnl": total_pnl,
            "trades": trades_count,
            "win_rate": win_rate,
            "label": f"{range_label} PnL",
            "pnl_curve": curve,
            "detailed": True,
        }
    except Exception:
        return None


class TestTelegramUnifiedBaselineValidity:
    def test_unified_baseline_exists(self):
        assert UNIFIED_BASELINE_PATH.exists(), (
            f"Unified baseline not found at {UNIFIED_BASELINE_PATH}."
        )

    def test_unified_baseline_is_valid_png(self):
        if not UNIFIED_BASELINE_PATH.exists():
            pytest.skip("Unified baseline image not found.")
        valid, error = validate_png_file(UNIFIED_BASELINE_PATH)
        assert valid, f"Unified baseline is invalid: {error}"


class TestTelegramUnifiedDashboardVisualRegression:
    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            from pearlalgo.market_agent.chart_generator import ChartGenerator, ChartConfig
            self.generator = ChartGenerator(ChartConfig())
        except ImportError as e:
            pytest.skip(f"Chart generator not available: {e}")

    def _render_unified_dashboard(self):
        data = generate_deterministic_ohlcv(num_bars=220, base_price=26300.0)
        apply_telegram_render_profile(self.generator.config)

        lookback = 8 * 60 // 5  # 8h of 5m bars
        trades = build_trade_list(
            data,
            lookback_bars=lookback,
            num_trades=6,
            spacing_bars=14,
            hold_bars=8,
            start_offset_into_window=8,
        )
        pnl_overlay = _build_pnl_overlay(trades, range_label="8h")

        return self.generator.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=int(lookback),
            range_label="8h",
            figsize=TELEGRAM_UNIFIED_FIGSIZE,
            dpi=TELEGRAM_UNIFIED_DPI,
            render_mode="telegram",
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50, 200],
            show_rsi=True,
            show_pressure=False,
            show_trade_recap=True,
            title_time=FIXED_TITLE_TIME,
            trades=trades,
            pnl_overlay=pnl_overlay,
            show_ema_crossover_markers=False,
            show_trade_overlay_legend=True,
            trade_markers_max=12,
        )

    def test_unified_dashboard_renders_without_error(self):
        chart_path = self._render_unified_dashboard()
        assert chart_path is not None, "Unified Telegram chart generation failed"
        assert Path(chart_path).exists(), "Unified Telegram chart file not found"
        assert Path(chart_path).stat().st_size > 0, "Unified Telegram chart is empty"
        Path(chart_path).unlink(missing_ok=True)

    def test_unified_dashboard_visual_regression(self):
        if not UNIFIED_BASELINE_PATH.exists():
            pytest.skip("Unified baseline image not found.")
        chart_path = self._render_unified_dashboard()
        assert chart_path is not None, "Unified chart generation failed"

        actual = load_image_as_array(Path(chart_path))
        expected = load_image_as_array(UNIFIED_BASELINE_PATH)
        assert actual is not None, "Could not load generated unified chart"
        assert expected is not None, "Could not load unified baseline image"

        passed, mean_diff, diff_pct, _ = compare_images(
            actual,
            expected,
            tolerance=PIXEL_TOLERANCE,
            max_diff_pct=MAX_DIFF_PIXELS_PCT,
        )
        Path(chart_path).unlink(missing_ok=True)

        assert passed, (
            f"Unified visual regression failed: mean_diff={mean_diff:.2f}, "
            f"diff_pct={diff_pct:.2f}%"
        )

    def test_unified_dashboard_determinism(self):
        chart1_path = self._render_unified_dashboard()
        chart2_path = self._render_unified_dashboard()
        assert chart1_path is not None and chart2_path is not None

        img1 = load_image_as_array(Path(chart1_path))
        img2 = load_image_as_array(Path(chart2_path))
        assert img1 is not None and img2 is not None

        passed, mean_diff, diff_pct, _ = compare_images(
            img1,
            img2,
            tolerance=DETERMINISM_PIXEL_TOLERANCE,
            max_diff_pct=DETERMINISM_MAX_DIFF_PIXELS_PCT,
        )
        Path(chart1_path).unlink(missing_ok=True)
        Path(chart2_path).unlink(missing_ok=True)

        assert passed, (
            f"Unified determinism failed: mean_diff={mean_diff:.2f}, "
            f"diff_pct={diff_pct:.2f}%"
        )
