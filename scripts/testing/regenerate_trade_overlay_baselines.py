"""
Regenerate trade-overlay visual regression baseline PNGs.

This script intentionally overwrites files under:
  tests/fixtures/charts/

Run (from repo root, inside venv):
  .venv/bin/python scripts/testing/regenerate_trade_overlay_baselines.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    fixtures_dir = repo_root / "tests" / "fixtures" / "charts"

    # Ensure `tests.*` fixtures and local `src/` imports resolve when running as a script.
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "src"))

    from tests.fixtures.deterministic_data import (  # noqa: WPS433
        FIXED_TITLE_TIME,
        generate_deterministic_ohlcv,
    )
    from tests.fixtures.trade_overlay_fixtures import (  # noqa: WPS433
        apply_telegram_render_profile,
        build_trade_list,
        deterministic_regime_info,
    )
    from pearlalgo.market_agent.chart_generator import ChartConfig, ChartGenerator  # noqa: WPS433

    data = generate_deterministic_ohlcv(num_bars=220, base_price=26300.0)
    lookback = 8 * 60 // 5  # 8h of 5m bars

    dense_trades = build_trade_list(
        data,
        lookback_bars=lookback,
        num_trades=20,
        spacing_bars=2,
        hold_bars=10,
        start_offset_into_window=10,
    )
    normal_trades = build_trade_list(
        data,
        lookback_bars=lookback,
        num_trades=5,
        spacing_bars=18,
        hold_bars=8,
        start_offset_into_window=8,
    )

    cfg = ChartConfig()
    apply_telegram_render_profile(cfg)

    # Trade overlay baseline: "pairs" (entry+exit+connector), no letters.
    cfg.smart_marker_show_letters = False
    cfg.smart_marker_show_entry = True
    cfg.smart_marker_show_exit = True
    cfg.smart_marker_show_path = True
    cfg.smart_marker_path_arrowheads = False
    cfg.smart_marker_path_fade_by_age = False
    cfg.smart_marker_path_label_last_pnl = False

    gen = ChartGenerator(cfg)
    regime_info = deterministic_regime_info(confidence=0.64)

    def _render(*, trades, trade_markers_max: int, out_name: str) -> None:
        path = gen.generate_dashboard_chart(
            data=data,
            symbol="MNQ",
            timeframe="5m",
            lookback_bars=lookback,
            range_label="8h",
            figsize=(8, 12),
            dpi=200,
            render_mode="telegram",
            show_sessions=True,
            show_key_levels=True,
            show_vwap=True,
            show_ma=True,
            ma_periods=[20, 50, 200],
            show_rsi=True,
            show_pressure=True,
            title_time=FIXED_TITLE_TIME,
            trades=trades,
            regime_info=regime_info,
            # Telegram-only render tuning (stable, tested)
            show_ema_crossover_markers=False,
            show_trade_overlay_legend=True,
            trade_markers_max=int(trade_markers_max),
            save_pad_inches=0.12,
            telegram_top_headroom_pct=0.045,
            optimize_png=False,
        )
        if path is None or not Path(path).exists():
            raise RuntimeError(f"Failed to generate trade overlay baseline: {out_name}")
        _copy(Path(path), fixtures_dir / out_name)
        Path(path).unlink(missing_ok=True)

    _render(trades=normal_trades, trade_markers_max=20, out_name="trade_overlay_normal_pairs_max20.png")
    _render(trades=dense_trades, trade_markers_max=20, out_name="trade_overlay_dense_pairs_max20.png")
    _render(trades=dense_trades, trade_markers_max=3, out_name="trade_overlay_dense_pairs_clean3.png")

    print(f"Updated trade overlay baselines in: {fixtures_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

