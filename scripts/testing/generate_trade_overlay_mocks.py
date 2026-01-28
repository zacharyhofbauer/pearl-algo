"""
Generate side-by-side mock images for trade history overlay clarity.

Goal:
- Produce Telegram-style dashboard PNGs that demonstrate trade-history clutter and
  two safer visualization options:
  1) Connector pairing without letters (reduces cognitive load in static PNGs)
  2) Clean mode: show only last N trades (prevents overplotting)

This script does NOT change any production defaults. It only renders variants
by toggling ChartConfig flags at runtime and saving artifacts.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Ensure imports work when invoked from repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.market_agent.chart_generator import ChartConfig, ChartGenerator  # noqa: E402
from pearlalgo.market_agent.chart_profiles import apply_telegram_unified_profile  # noqa: E402
from tests.fixtures.deterministic_data import (  # noqa: E402
    FIXED_TITLE_TIME,
    generate_deterministic_ohlcv,
)


def _apply_telegram_profile(generator: ChartGenerator) -> None:
    """
    Match the service-layer Telegram/mobile render profile (best-effort).

    We intentionally mutate the generator's config, mirroring production usage.
    """
    apply_telegram_unified_profile(generator.config)


def _make_trade(
    *,
    direction: str,
    entry_time,
    entry_price: float,
    exit_time,
    exit_price: float,
) -> Dict[str, Any]:
    """
    Create a trade dict compatible with ChartGenerator's smart marker overlay.
    """
    dir_norm = str(direction or "long").lower()
    if dir_norm not in {"long", "short"}:
        dir_norm = "long"

    tick_value = 2.0  # MNQ-ish dollars per point (for display-only mock)
    if dir_norm == "long":
        pnl = (float(exit_price) - float(entry_price)) * tick_value
    else:
        pnl = (float(entry_price) - float(exit_price)) * tick_value

    return {
        "direction": dir_norm,
        "entry_time": entry_time,
        "entry_price": float(entry_price),
        "exit_time": exit_time,
        "exit_price": float(exit_price),
        "pnl": float(pnl),
    }


def build_trade_list(
    data: pd.DataFrame,
    *,
    lookback_bars: int,
    num_trades: int,
    spacing_bars: int,
    hold_bars: int,
    start_offset_into_window: int = 6,
) -> List[Dict[str, Any]]:
    """
    Build a deterministic set of trades within the visible lookback window.

    This is intentionally synthetic: we are testing readability, not strategy logic.
    """
    if data is None or data.empty:
        return []

    df = data.copy()
    if "timestamp" not in df.columns:
        return []
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    if df.empty:
        return []

    n = len(df)
    window_start = max(0, n - int(lookback_bars))
    start_idx = min(n - 2, window_start + max(0, int(start_offset_into_window)))

    trades: List[Dict[str, Any]] = []
    for i in range(int(num_trades)):
        entry_idx = start_idx + (i * int(spacing_bars))
        if entry_idx >= n - 2:
            break
        exit_idx = min(n - 1, entry_idx + max(1, int(hold_bars)))

        entry_time = df["timestamp"].iloc[entry_idx]
        exit_time = df["timestamp"].iloc[exit_idx]

        # Use OHLC-derived prices so markers sit near real candles.
        entry_price = float(df["close"].iloc[entry_idx])

        # Alternate direction; for each, nudge exit to create a mix of wins/losses.
        direction = "long" if i % 2 == 0 else "short"
        base_exit_price = float(df["close"].iloc[exit_idx])
        delta = 10.0 + (i % 4) * 2.5  # deterministic variety
        if direction == "long":
            exit_price = base_exit_price + (delta if (i % 3 != 0) else -delta)
        else:
            exit_price = base_exit_price - (delta if (i % 3 != 0) else -delta)

        trades.append(
            _make_trade(
                direction=direction,
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=exit_time,
                exit_price=exit_price,
            )
        )

    return trades


def render_dashboard_variant(
    *,
    generator: ChartGenerator,
    data: pd.DataFrame,
    trades: List[Dict[str, Any]],
    output_path: Path,
    title_time: Optional[str],
    lookback_bars: int,
    range_label: str,
    trade_markers_max: int,
    show_letters: bool,
    show_entry: bool = True,
    show_exit: bool = True,
    show_path: bool = True,
    figsize: tuple[float, float] = (8, 12),
) -> Path:
    cfg = generator.config
    cfg.smart_marker_show_letters = bool(show_letters)
    cfg.smart_marker_show_entry = bool(show_entry)
    cfg.smart_marker_show_exit = bool(show_exit)
    cfg.smart_marker_show_path = bool(show_path)

    # Build a compact P&L overlay (and sparkline) from the same trades shown on-chart.
    # This is a visualization-only convenience for Telegram static PNGs.
    pnl_overlay = None
    try:
        closed = [t for t in trades if isinstance(t, dict) and t.get("pnl") is not None]
        # Sort by exit_time if present (fallback to entry_time)
        def _ts(x):
            try:
                return pd.Timestamp(x)
            except Exception:
                return pd.Timestamp.min
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
        pnl_overlay = {
            "daily_pnl": total_pnl,
            "trades": trades_count,
            "win_rate": win_rate,
            "label": f"{range_label} PnL",
            "pnl_curve": curve,
            # Show the in-chart performance panel (equity + drawdown) in mocks.
            "detailed": True,
        }
    except Exception:
        pnl_overlay = None

    tmp = generator.generate_dashboard_chart(
        data=data,
        symbol="MNQ",
        timeframe="5m",
        lookback_bars=int(lookback_bars),
        range_label=str(range_label),
        figsize=figsize,
        dpi=200,
        render_mode="telegram",
        show_sessions=True,
        show_key_levels=True,
        show_vwap=True,
        show_ma=True,
        ma_periods=[20, 50, 200],
        show_rsi=True,
        show_pressure=True,
        title_time=title_time,
        trades=trades,
        pnl_overlay=pnl_overlay,
        show_ema_crossover_markers=False,
        show_trade_overlay_legend=True,
        trade_markers_max=int(trade_markers_max),
        save_pad_inches=0.12,
        telegram_top_headroom_pct=0.045,
        optimize_png=False,
    )

    if tmp is None:
        raise RuntimeError("Chart generation returned None")

    tmp_path = Path(tmp)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(tmp_path.read_bytes())

    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass

    return output_path


def main() -> int:
    artifacts_dir = PROJECT_ROOT / "tests" / "artifacts" / "trade_overlay_mocks"

    # Data: base price aligned with the provided screenshot’s ~26k scale.
    data = generate_deterministic_ohlcv(num_bars=220, base_price=26300.0)

    config = ChartConfig()
    generator = ChartGenerator(config)
    _apply_telegram_profile(generator)

    # Scenarios
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

    # Variants: show multiple trade overlay encodings, and compare portrait vs landscape.
    outputs: List[Path] = []
    figsizes = {
        "portrait": (8, 12),
        "landscape": (16, 7),
        # Middle-ground Telegram candidates (neither portrait nor landscape).
        "mid_4x3": (12, 9),
        "mid_6x5": (12, 10),
        "mid_10x9": (10, 9),
    }
    trade_views = {
        # Current conservative pairing: triangles+circles+connector, no letters.
        "pairs": dict(show_entry=True, show_exit=True, show_path=True, show_letters=False),
        # Markers only: triangles+circles, no connector (reduces line spaghetti).
        "markers_only": dict(show_entry=True, show_exit=True, show_path=False, show_letters=False),
        # Entries only: triangles only (lowest clutter, weakest lifecycle context).
        "entry_only": dict(show_entry=True, show_exit=False, show_path=False, show_letters=False),
        # Paths only: connector lines only (no markers; endpoints are tiny dots).
        "path_only": dict(show_entry=False, show_exit=False, show_path=True, show_letters=False),
        # Path-only with TradingView-inspired detail.
        "path_only_detailed": dict(show_entry=False, show_exit=False, show_path=True, show_letters=False),
    }

    for scenario_name, trades in [("dense", dense_trades), ("normal", normal_trades)]:
        for aspect_name, fs in figsizes.items():
            for view_name, flags in trade_views.items():
                # Enable path-only enhancements only for the dedicated detailed variant.
                if view_name == "path_only_detailed":
                    generator.config.smart_marker_path_arrowheads = True
                    generator.config.smart_marker_path_fade_by_age = True
                    generator.config.smart_marker_path_label_last_pnl = True
                else:
                    generator.config.smart_marker_path_arrowheads = False
                    generator.config.smart_marker_path_fade_by_age = False
                    generator.config.smart_marker_path_label_last_pnl = False
                outputs.append(
                    render_dashboard_variant(
                        generator=generator,
                        data=data,
                        trades=trades,
                        output_path=artifacts_dir / f"{scenario_name}_{aspect_name}_{view_name}_max20.png",
                        title_time="15:46 UTC",
                        lookback_bars=lookback,
                        range_label="8h",
                        trade_markers_max=20,
                        figsize=fs,
                        **flags,
                    )
                )

            # Clean mode sample (last 3 trades) for the most common pair encoding.
            outputs.append(
                render_dashboard_variant(
                    generator=generator,
                    data=data,
                    trades=trades,
                    output_path=artifacts_dir / f"{scenario_name}_{aspect_name}_pairs_clean3.png",
                    title_time="15:46 UTC",
                    lookback_bars=lookback,
                    range_label="8h",
                    trade_markers_max=3,
                    figsize=fs,
                    **trade_views["pairs"],
                )
            )

        # Also produce a distinguished P&L/equity chart (separate image) for the same trade list.
        # This uses the production ChartGenerator method `generate_equity_curve_chart`.
        try:
            closed = [t for t in trades if isinstance(t, dict) and t.get("exit_time") and t.get("pnl") is not None]
            if closed:
                wins = 0
                pnls = []
                # Sort by exit_time for stable curve
                closed_sorted = sorted(closed, key=lambda t: pd.Timestamp(t.get("exit_time")))
                for t in closed_sorted:
                    try:
                        v = float(t.get("pnl") or 0.0)
                    except Exception:
                        v = 0.0
                    pnls.append(v)
                    if v > 0:
                        wins += 1
                total_pnl = float(sum(pnls))
                total_trades = int(len(pnls))
                win_rate = float(wins / total_trades) if total_trades > 0 else 0.0
                # Approx max drawdown from cumulative curve
                cum = pd.Series(pnls).cumsum()
                dd = cum - cum.cummax()
                max_dd = float(abs(dd.min())) if len(dd) else 0.0

                perf = {
                    "total_trades": total_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "max_drawdown": max_dd,
                    "sharpe_ratio": 0.0,
                }
                tmp_eq = generator.generate_equity_curve_chart(
                    trades=closed_sorted,
                    symbol="MNQ",
                    title=f"MNQ {scenario_name.title()} Trades • Equity & Drawdown",
                    performance_data=perf,
                    figsize=(16, 7),
                    dpi=200,
                )
                if tmp_eq:
                    out_eq = artifacts_dir / f"{scenario_name}_equity_curve.png"
                    out_eq.write_bytes(Path(tmp_eq).read_bytes())
                    try:
                        Path(tmp_eq).unlink(missing_ok=True)
                    except Exception:
                        pass
                    outputs.append(out_eq)
        except Exception:
            pass

    # Print paths for convenience when running from terminal.
    for p in outputs:
        print(str(p))

    # Also generate a single deterministic reference (useful when eyeballing output)
    _ = FIXED_TITLE_TIME  # referenced to keep import intentional
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

