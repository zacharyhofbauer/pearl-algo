"""
Regenerate chart visual regression baseline PNGs.

This script intentionally overwrites files under:
  tests/fixtures/charts/

Run (from repo root, inside venv):
  .venv/bin/python scripts/testing/regenerate_chart_baselines.py
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

    # Import inside main so this script fails fast if deps aren't installed.
    from tests.fixtures.deterministic_data import (  # noqa: WPS433
        FIXED_TITLE_TIME,
        generate_deterministic_backtest_signals,
        generate_deterministic_entry_signal,
        generate_deterministic_exit_data,
        generate_deterministic_ohlcv,
    )
    from pearlalgo.market_agent.chart_generator import ChartConfig, ChartGenerator  # noqa: WPS433

    cfg = ChartConfig()
    gen = ChartGenerator(cfg)

    # -----------------------------
    # Dashboard baseline (36h)
    # -----------------------------
    data = generate_deterministic_ohlcv()
    dash_path = gen.generate_dashboard_chart(
        data=data,
        symbol="MNQ",
        timeframe="5m",
        lookback_bars=288,
        range_label="36h",
        figsize=(16, 7),
        dpi=150,
        render_mode="telegram",
        show_sessions=True,
        show_key_levels=True,
        show_vwap=True,
        show_ma=True,
        ma_periods=[20, 50, 200],
        show_rsi=True,
        show_pressure=True,
        title_time=FIXED_TITLE_TIME,
    )
    if dash_path is None or not Path(dash_path).exists():
        raise RuntimeError("Failed to generate dashboard baseline")
    _copy(Path(dash_path), fixtures_dir / "dashboard_baseline.png")
    Path(dash_path).unlink(missing_ok=True)

    # -----------------------------
    # Mobile dashboard baseline (12h)
    # -----------------------------
    mobile_path = gen.generate_dashboard_chart(
        data=data,
        symbol="MNQ",
        timeframe="5m",
        lookback_bars=144,
        range_label="12h",
        figsize=(8, 5),
        dpi=150,
        render_mode="telegram",
        show_sessions=True,
        show_key_levels=True,
        show_vwap=True,
        show_ma=True,
        ma_periods=[20, 50],
        show_rsi=True,
        show_pressure=False,
        title_time=FIXED_TITLE_TIME,
    )
    if mobile_path is None or not Path(mobile_path).exists():
        raise RuntimeError("Failed to generate mobile dashboard baseline")
    _copy(Path(mobile_path), fixtures_dir / "mobile_dashboard_baseline.png")
    Path(mobile_path).unlink(missing_ok=True)

    # -----------------------------
    # On-demand baseline (12h)
    # -----------------------------
    on_path = gen.generate_dashboard_chart(
        data=data,
        symbol="MNQ",
        timeframe="5m",
        lookback_bars=min(144, len(data)),
        range_label=None,
        figsize=(16, 7),
        dpi=150,
        render_mode="telegram",
        show_sessions=True,
        show_key_levels=True,
        show_vwap=True,
        show_ma=True,
        ma_periods=[20, 50, 200],
        show_rsi=True,
        show_pressure=True,
        title_time=FIXED_TITLE_TIME,
    )
    if on_path is None or not Path(on_path).exists():
        raise RuntimeError("Failed to generate on-demand baseline")
    _copy(Path(on_path), fixtures_dir / "on_demand_chart_12h_baseline.png")
    Path(on_path).unlink(missing_ok=True)

    # -----------------------------
    # Entry/exit baselines
    # -----------------------------
    entry_data = generate_deterministic_ohlcv(num_bars=100)
    entry_signal = generate_deterministic_entry_signal(entry_data, direction="long")
    entry_path = gen.generate_entry_chart(signal=entry_signal, buffer_data=entry_data, symbol="MNQ", timeframe="5m")
    if entry_path is None or not Path(entry_path).exists():
        raise RuntimeError("Failed to generate entry baseline")
    _copy(Path(entry_path), fixtures_dir / "entry_baseline.png")
    Path(entry_path).unlink(missing_ok=True)

    exit_data = generate_deterministic_ohlcv(num_bars=150)
    exit_signal = generate_deterministic_entry_signal(exit_data, direction="long")
    exit_price, exit_reason, pnl = generate_deterministic_exit_data(exit_data, exit_signal)
    exit_path = gen.generate_exit_chart(
        signal=exit_signal,
        exit_price=float(exit_price),
        exit_reason=str(exit_reason),
        pnl=float(pnl),
        buffer_data=exit_data,
        symbol="MNQ",
        timeframe="5m",
    )
    if exit_path is None or not Path(exit_path).exists():
        raise RuntimeError("Failed to generate exit baseline")
    _copy(Path(exit_path), fixtures_dir / "exit_baseline.png")
    Path(exit_path).unlink(missing_ok=True)

    # -----------------------------
    # Backtest baseline
    # -----------------------------
    bt_data = generate_deterministic_ohlcv(num_bars=300)
    signals = generate_deterministic_backtest_signals(bt_data, num_signals=8)
    performance_data = {
        "total_pnl": sum(s["pnl"] for s in signals),
        "total_trades": len(signals),
        "wins": sum(1 for s in signals if s["pnl"] > 0),
        "losses": sum(1 for s in signals if s["pnl"] <= 0),
        "win_rate": (sum(1 for s in signals if s["pnl"] > 0) / len(signals) * 100.0) if signals else 0.0,
    }
    bt_path = gen.generate_backtest_chart(
        backtest_data=bt_data,
        signals=signals,
        symbol="MNQ",
        title="Backtest Results",
        performance_data=performance_data,
        timeframe="5m",
    )
    if bt_path is None or not Path(bt_path).exists():
        raise RuntimeError("Failed to generate backtest baseline")
    _copy(Path(bt_path), fixtures_dir / "backtest_baseline.png")
    Path(bt_path).unlink(missing_ok=True)

    print(f"Updated baselines in: {fixtures_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

