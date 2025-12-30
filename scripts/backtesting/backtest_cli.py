#!/usr/bin/env python3
"""Unified backtest CLI for MNQ/NQ strategies.

Usage:
    # Signal-only mode (fast, no trade simulation)
    python scripts/backtesting/backtest_cli.py signal --data-path data/mnq_1m.parquet

    # Full trade simulation
    python scripts/backtesting/backtest_cli.py full --data-path data/mnq_1m.parquet --contracts 5

    # With risk-based sizing
    python scripts/backtesting/backtest_cli.py full --data-path data/mnq_1m.parquet \\
        --account-balance 50000 --max-risk-per-trade 0.01

    # With date range
    python scripts/backtesting/backtest_cli.py full --data-path data/mnq_1m.parquet \\
        --start 2025-12-01 --end 2025-12-15

Report outputs are written to reports/backtest_<symbol>_<decision>_<start>_<end>_<run_ts>/
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.strategies.nq_intraday.backtest_adapter import (
    BacktestResult,
    NQIntradayConfig,
    Trade,
    VerificationSummary,
    run_full_backtest,
    run_full_backtest_5m_decision,
    run_signal_backtest,
    run_signal_backtest_5m_decision,
)
from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig


# ============================================================================
# Data Loading
# ============================================================================

def load_ohlcv_data(path: Path) -> pd.DataFrame:
    """Load OHLCV data from parquet or CSV.
    
    Expects columns: open, high, low, close, volume
    Index or column: timestamp (DatetimeIndex or parseable datetime column)
    """
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    if path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    # Normalize index to DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("timestamp", "time", "datetime", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True)
                df = df.set_index(col)
                break

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DateTimeIndex or a 'timestamp' column")

    # Ensure sorted
    df = df.sort_index()

    # Validate required columns
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


# ============================================================================
# Date Range Integrity
# ============================================================================

@dataclass
class DateRangeInfo:
    """Information about dataset and sliced date ranges."""
    dataset_start: datetime
    dataset_end: datetime
    requested_start: Optional[datetime]
    requested_end: Optional[datetime]
    actual_start: datetime
    actual_end: datetime
    bars_total: int
    bars_sliced: int
    warning: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "dataset_start": self.dataset_start.isoformat(),
            "dataset_end": self.dataset_end.isoformat(),
            "requested_start": self.requested_start.isoformat() if self.requested_start else None,
            "requested_end": self.requested_end.isoformat() if self.requested_end else None,
            "actual_start": self.actual_start.isoformat(),
            "actual_end": self.actual_end.isoformat(),
            "bars_total": self.bars_total,
            "bars_sliced": self.bars_sliced,
            "warning": self.warning,
        }


def slice_by_date_range(
    df: pd.DataFrame,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    lookback_weeks: Optional[int] = None,
) -> Tuple[pd.DataFrame, DateRangeInfo]:
    """Slice DataFrame by date range with integrity checks.
    
    Returns sliced DataFrame and DateRangeInfo for reporting.
    """
    dataset_start = df.index[0].to_pydatetime()
    dataset_end = df.index[-1].to_pydatetime()
    bars_total = len(df)

    # Determine effective start/end
    effective_start = start
    effective_end = end

    if lookback_weeks and not start:
        # Compute start from lookback_weeks relative to dataset end (or provided end)
        anchor = effective_end or dataset_end
        effective_start = anchor - pd.Timedelta(weeks=lookback_weeks)

    # Slice
    sliced = df.copy()
    if effective_start:
        sliced = sliced[sliced.index >= effective_start]
    if effective_end:
        sliced = sliced[sliced.index <= effective_end]

    if sliced.empty:
        raise ValueError(
            f"No data in requested range. Dataset: {dataset_start} to {dataset_end}, "
            f"Requested: {effective_start} to {effective_end}"
        )

    actual_start = sliced.index[0].to_pydatetime()
    actual_end = sliced.index[-1].to_pydatetime()
    bars_sliced = len(sliced)

    # Check for integrity issues
    warning = None
    if effective_start and actual_start > effective_start:
        warning = f"Requested start {effective_start} is before dataset start {dataset_start}"
    elif effective_end and actual_end < effective_end:
        warning = f"Requested end {effective_end} is after dataset end {dataset_end}"

    info = DateRangeInfo(
        dataset_start=dataset_start,
        dataset_end=dataset_end,
        requested_start=effective_start,
        requested_end=effective_end,
        actual_start=actual_start,
        actual_end=actual_end,
        bars_total=bars_total,
        bars_sliced=bars_sliced,
        warning=warning,
    )

    return sliced, info


# ============================================================================
# Risk Controls
# ============================================================================

@dataclass
class RiskConfig:
    """Risk-based position sizing configuration."""
    account_balance: Optional[float] = None
    max_risk_per_trade: float = 0.01  # 1%
    risk_budget_dollars: Optional[float] = None  # Direct dollar risk
    max_contracts: int = 10
    max_stop_points: Optional[float] = None  # Max stop distance cap


@dataclass
class SkippedSignal:
    """Record of a skipped signal with reason."""
    timestamp: str
    signal_type: str
    direction: str
    stop_distance_points: float
    skip_reason: str
    computed_contracts: Optional[int] = None
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "stop_distance_points": self.stop_distance_points,
            "skip_reason": self.skip_reason,
            "computed_contracts": self.computed_contracts,
        }


def compute_position_size(
    signal: Dict,
    risk_config: RiskConfig,
    tick_value: float = 2.0,  # MNQ: $2/pt
) -> Tuple[int, Optional[str]]:
    """Compute position size from risk config.
    
    Returns (contracts, skip_reason) where skip_reason is None if trade should proceed.
    """
    entry = signal.get("entry_price", 0)
    stop = signal.get("stop_loss", 0)
    direction = signal.get("direction", "long")

    if not entry or not stop or entry <= 0 or stop <= 0:
        return 0, "invalid_prices"

    # Calculate stop distance in points
    if direction == "long":
        stop_distance = abs(entry - stop)
    else:
        stop_distance = abs(stop - entry)

    if stop_distance <= 0:
        return 0, "zero_stop_distance"

    # Check stop distance cap
    if risk_config.max_stop_points and stop_distance > risk_config.max_stop_points:
        return 0, f"stop_exceeds_cap ({stop_distance:.1f} > {risk_config.max_stop_points})"

    # Calculate risk budget
    if risk_config.risk_budget_dollars:
        risk_budget = risk_config.risk_budget_dollars
    elif risk_config.account_balance:
        risk_budget = risk_config.account_balance * risk_config.max_risk_per_trade
    else:
        # No risk-based sizing, use max_contracts
        return risk_config.max_contracts, None

    # Contracts = risk_budget / (stop_distance * tick_value)
    risk_per_contract = stop_distance * tick_value
    if risk_per_contract <= 0:
        return 0, "zero_risk_per_contract"

    contracts = int(risk_budget / risk_per_contract)

    # Clamp to max
    contracts = min(contracts, risk_config.max_contracts)

    if contracts < 1:
        return 0, f"insufficient_risk_budget (need ${risk_per_contract:.2f}/contract, have ${risk_budget:.2f})"

    return contracts, None


# ============================================================================
# Report Writer
# ============================================================================

@dataclass
class BacktestReport:
    """Complete backtest report with all artifacts."""
    symbol: str
    decision_timeframe: str
    date_range: DateRangeInfo
    result: BacktestResult
    risk_config: Optional[RiskConfig] = None
    skipped_signals: List[SkippedSignal] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))

    def get_report_dir_name(self) -> str:
        """Generate report directory name."""
        start = self.date_range.actual_start.strftime("%Y%m%d")
        end = self.date_range.actual_end.strftime("%Y%m%d")
        return f"backtest_{self.symbol}_{self.decision_timeframe}_{start}_{end}_{self.run_timestamp}"


@dataclass
class ChartOptions:
    """Options for chart generation in backtest reports."""
    mode: str = "overview"  # "none", "overview", "trade_gallery"
    trade_charts_max: int = 50
    trade_chart_lookback_bars: int = 30
    trade_chart_forward_bars: int = 15
    chart_preset: str = "default"  # "default", "wide"
    show_hud: bool = True


def write_report(
    report: BacktestReport,
    output_dir: Path,
    *,
    chart_options: Optional[ChartOptions] = None,
    ohlcv_data: Optional[pd.DataFrame] = None,
) -> Path:
    """Write backtest report to directory.
    
    Creates:
        - summary.json (all metrics + verification)
        - signals.csv
        - trades.csv (if full backtest)
        - skipped_signals.csv (if any)
        - chart_overview.png (if chart_options.mode != "none")
        - trades/ directory with per-trade PNGs (if chart_options.mode == "trade_gallery")
        - trades.html (if trade gallery enabled)
        - index.html (simple viewer)
    
    Args:
        report: BacktestReport with results
        output_dir: Base output directory
        chart_options: Optional chart generation options
        ohlcv_data: Optional OHLCV DataFrame for chart generation
    
    Returns:
        Path to report directory.
    """
    report_dir = output_dir / report.get_report_dir_name()
    report_dir.mkdir(parents=True, exist_ok=True)

    result = report.result
    opts = chart_options or ChartOptions()

    # 1. Summary JSON
    summary = {
        "symbol": report.symbol,
        "decision_timeframe": report.decision_timeframe,
        "run_timestamp": report.run_timestamp,
        "date_range": report.date_range.to_dict(),
        "metrics": {
            "total_bars": result.total_bars,
            "total_signals": result.total_signals,
            "avg_confidence": result.avg_confidence,
            "avg_risk_reward": result.avg_risk_reward,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "total_pnl": result.total_pnl,
            "profit_factor": result.profit_factor,
            "max_drawdown": result.max_drawdown,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "avg_win": result.avg_win,
            "avg_loss": result.avg_loss,
            "avg_hold_time_minutes": result.avg_hold_time_minutes,
            "signal_distribution": result.signal_distribution,
        },
        "verification": result.verification.to_dict() if result.verification else None,
        "risk_config": {
            "account_balance": report.risk_config.account_balance,
            "max_risk_per_trade": report.risk_config.max_risk_per_trade,
            "risk_budget_dollars": report.risk_config.risk_budget_dollars,
            "max_contracts": report.risk_config.max_contracts,
            "max_stop_points": report.risk_config.max_stop_points,
        } if report.risk_config else None,
        "execution_summary": _build_execution_summary(report),
    }

    with open(report_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # 2. Signals CSV
    if result.signals:
        signals_df = pd.DataFrame(result.signals)
        # Flatten nested dicts for CSV compatibility
        for col in signals_df.columns:
            if signals_df[col].apply(lambda x: isinstance(x, dict)).any():
                signals_df[col] = signals_df[col].apply(
                    lambda x: json.dumps(x) if isinstance(x, dict) else x
                )
        signals_df.to_csv(report_dir / "signals.csv", index=False)

    # 3. Trades CSV
    if result.trades:
        trades_df = pd.DataFrame(result.trades)
        trades_df.to_csv(report_dir / "trades.csv", index=False)

    # 4. Skipped signals CSV
    if report.skipped_signals:
        skipped_df = pd.DataFrame([s.to_dict() for s in report.skipped_signals])
        skipped_df.to_csv(report_dir / "skipped_signals.csv", index=False)

    # 5. Generate trade gallery (if enabled and trades exist)
    trade_chart_paths: List[str] = []
    if opts.mode == "trade_gallery" and result.trades and ohlcv_data is not None:
        trade_chart_paths = _generate_trade_gallery(
            report, report_dir, ohlcv_data, opts
        )

    # 6. Chart overview (if signals available)
    _generate_overview_chart(report, report_dir)

    # 7. Trades HTML (if trade gallery was generated)
    if trade_chart_paths:
        _generate_trades_html(report, report_dir, trade_chart_paths)

    # 8. Index HTML
    _generate_index_html(report, report_dir, has_trade_gallery=bool(trade_chart_paths))

    return report_dir


def _count_skip_reasons(skipped: List[SkippedSignal]) -> Dict[str, int]:
    """Count skip reasons."""
    counts: Dict[str, int] = {}
    for s in skipped:
        # Extract reason category
        reason = s.skip_reason.split(" (")[0]
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _build_execution_summary(report: BacktestReport) -> Optional[Dict]:
    """Build execution summary combining engine verification data and skipped signals.
    
    Returns comprehensive execution breakdown for JSON export.
    """
    # Prefer engine verification summary if available (most complete)
    if report.result.verification and report.result.verification.execution_summary:
        exec_summary = dict(report.result.verification.execution_summary)
        # Add skipped signals breakdown by reason
        if report.skipped_signals:
            exec_summary["skipped_signals_total"] = len(report.skipped_signals)
            exec_summary["skipped_by_reason"] = _count_skip_reasons(report.skipped_signals)
        return exec_summary
    
    # Fallback to skipped signals only
    if report.skipped_signals:
        return {
            "skipped_signals_total": len(report.skipped_signals),
            "skipped_by_reason": _count_skip_reasons(report.skipped_signals),
        }
    
    return None


def _generate_overview_chart(report: BacktestReport, report_dir: Path) -> Optional[Path]:
    """Generate overview chart PNG."""
    try:
        if not report.result.signals:
            return None

        # We need the original data for chart generation - skip if not available
        # (The chart will be generated by the caller if they have the data)
        return None
    except Exception:
        return None


def _generate_trade_gallery(
    report: BacktestReport,
    report_dir: Path,
    ohlcv_data: pd.DataFrame,
    opts: ChartOptions,
) -> List[str]:
    """Generate per-trade chart PNGs in trades/ subdirectory.
    
    Returns list of relative paths to generated chart files.
    """
    trades = report.result.trades
    if not trades:
        return []

    trades_dir = report_dir / "trades"
    trades_dir.mkdir(parents=True, exist_ok=True)

    # Limit number of trade charts
    max_charts = opts.trade_charts_max
    trades_to_chart = trades[-max_charts:] if len(trades) > max_charts else trades

    # Determine figsize/dpi based on preset
    if opts.chart_preset == "wide":
        figsize = (18, 10)
        dpi = 180
    else:
        figsize = (14, 9)
        dpi = 150

    chart_gen = ChartGenerator(ChartConfig())
    chart_paths: List[str] = []

    for i, trade in enumerate(trades_to_chart):
        try:
            # Generate chart
            chart_path = chart_gen.generate_trade_chart(
                trade,
                ohlcv_data,
                symbol=report.symbol,
                timeframe=report.decision_timeframe,
                lookback_bars=opts.trade_chart_lookback_bars,
                forward_bars=opts.trade_chart_forward_bars,
                show_hold_shading=True,
                show_hud=opts.show_hud,
                figsize=figsize,
                dpi=dpi,
            )
            if chart_path:
                # Move to trades directory with sequential naming
                dest_name = f"trade_{i+1:03d}.png"
                dest_path = trades_dir / dest_name
                import shutil
                shutil.move(str(chart_path), str(dest_path))
                chart_paths.append(f"trades/{dest_name}")
        except Exception as e:
            print(f"Warning: Could not generate chart for trade {i+1}: {e}")
            continue

    return chart_paths


def _generate_trades_html(
    report: BacktestReport,
    report_dir: Path,
    chart_paths: List[str],
) -> None:
    """Generate trades.html viewer with trade gallery."""
    trades = report.result.trades or []
    
    # Build table rows
    table_rows = ""
    for i, (trade, chart_path) in enumerate(zip(trades[-len(chart_paths):], chart_paths)):
        entry_time = trade.get("entry_time", "")
        exit_time = trade.get("exit_time", "")
        direction = trade.get("direction", "long")
        entry_price = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        pnl = trade.get("pnl", 0)
        exit_reason = trade.get("exit_reason", "")
        
        pnl_class = "positive" if pnl > 0 else "negative"
        pnl_sign = "+" if pnl > 0 else ""
        
        table_rows += f"""
        <tr class="trade-row" data-chart="{chart_path}">
            <td>{i+1}</td>
            <td>{entry_time[:19] if entry_time else ''}</td>
            <td>{exit_time[:19] if exit_time else ''}</td>
            <td class="{direction}">{direction.upper()}</td>
            <td>${entry_price:,.2f}</td>
            <td>${exit_price:,.2f}</td>
            <td class="{pnl_class}">{pnl_sign}${pnl:,.2f}</td>
            <td>{exit_reason}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Trade Gallery - {report.symbol}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #1a1a1a;
            color: #e0e0e0;
        }}
        h1, h2 {{ color: #fff; }}
        .container {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            max-width: 1800px;
            margin: 0 auto;
        }}
        @media (max-width: 1200px) {{
            .container {{ grid-template-columns: 1fr; }}
        }}
        .trades-panel {{
            background: #252525;
            border-radius: 8px;
            padding: 15px;
            max-height: 80vh;
            overflow-y: auto;
        }}
        .chart-panel {{
            background: #252525;
            border-radius: 8px;
            padding: 15px;
            position: sticky;
            top: 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            border: 1px solid #444;
            padding: 8px 10px;
            text-align: left;
        }}
        th {{ background: #333; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #2a2a2a; }}
        tr.trade-row {{ cursor: pointer; }}
        tr.trade-row:hover {{ background: #3a3a3a; }}
        tr.trade-row.selected {{ background: #2962ff33; border-left: 3px solid #2962ff; }}
        .positive {{ color: #26a69a; }}
        .negative {{ color: #ef5350; }}
        .long {{ color: #26a69a; }}
        .short {{ color: #ef5350; }}
        img {{
            max-width: 100%;
            border-radius: 4px;
        }}
        .back-link {{
            display: inline-block;
            margin-bottom: 15px;
            color: #64b5f6;
            text-decoration: none;
        }}
        .back-link:hover {{ text-decoration: underline; }}
        .stats {{
            display: flex;
            gap: 20px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}
        .stat {{
            background: #333;
            padding: 10px 15px;
            border-radius: 4px;
        }}
        .stat-label {{ font-size: 12px; color: #888; }}
        .stat-value {{ font-size: 18px; font-weight: bold; }}
    </style>
</head>
<body>
    <a href="index.html" class="back-link">← Back to Summary</a>
    <h1>Trade Gallery: {report.symbol}</h1>
    
    <div class="stats">
        <div class="stat">
            <div class="stat-label">Total Trades</div>
            <div class="stat-value">{len(trades)}</div>
        </div>
        <div class="stat">
            <div class="stat-label">Win Rate</div>
            <div class="stat-value">{(report.result.win_rate or 0) * 100:.1f}%</div>
        </div>
        <div class="stat">
            <div class="stat-label">Total P&L</div>
            <div class="stat-value {'positive' if (report.result.total_pnl or 0) > 0 else 'negative'}">${report.result.total_pnl or 0:,.2f}</div>
        </div>
        <div class="stat">
            <div class="stat-label">Charts Generated</div>
            <div class="stat-value">{len(chart_paths)}</div>
        </div>
    </div>
    
    <div class="container">
        <div class="trades-panel">
            <h2>Trades</h2>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Entry Time</th>
                        <th>Exit Time</th>
                        <th>Dir</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>P&L</th>
                        <th>Reason</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
        
        <div class="chart-panel">
            <h2>Trade Chart</h2>
            <img id="trade-chart" src="{chart_paths[0] if chart_paths else ''}" alt="Select a trade to view chart">
        </div>
    </div>
    
    <script>
        document.querySelectorAll('.trade-row').forEach(row => {{
            row.addEventListener('click', function() {{
                // Update selection
                document.querySelectorAll('.trade-row').forEach(r => r.classList.remove('selected'));
                this.classList.add('selected');
                
                // Update chart
                const chartPath = this.dataset.chart;
                document.getElementById('trade-chart').src = chartPath;
            }});
        }});
        
        // Select first row by default
        const firstRow = document.querySelector('.trade-row');
        if (firstRow) firstRow.classList.add('selected');
    </script>
</body>
</html>
"""
    with open(report_dir / "trades.html", "w") as f:
        f.write(html)


def _generate_index_html(
    report: BacktestReport,
    report_dir: Path,
    *,
    has_trade_gallery: bool = False,
) -> None:
    """Generate simple HTML viewer."""
    result = report.result
    dr = report.date_range

    # Metrics table
    metrics_rows = ""
    metrics = [
        ("Total Bars", f"{result.total_bars:,}"),
        ("Total Signals", f"{result.total_signals:,}"),
        ("Total Trades", f"{result.total_trades or 0:,}"),
        ("Win Rate", f"{(result.win_rate or 0) * 100:.1f}%"),
        ("Profit Factor", f"{result.profit_factor or 0:.2f}"),
        ("Total P&L", f"${result.total_pnl or 0:,.2f}"),
        ("Max Drawdown", f"${result.max_drawdown or 0:,.2f}"),
        ("Sharpe Ratio", f"{result.sharpe_ratio or 0:.2f}"),
        ("Avg Confidence", f"{result.avg_confidence:.2f}"),
        ("Avg R:R", f"{result.avg_risk_reward:.2f}:1"),
    ]
    for name, value in metrics:
        metrics_rows += f"<tr><td>{name}</td><td>{value}</td></tr>\n"

    # Verification summary with enhanced explainability
    verification_html = ""
    is_quiet_backtest = result.total_signals < 5  # Few or no signals
    
    if result.verification:
        v = result.verification
        
        # Determine alert status
        alert_class = "alert-warning" if is_quiet_backtest else ""
        alert_message = ""
        if result.total_signals == 0:
            alert_message = '<div class="alert alert-danger">No signals were generated during this backtest period. Review the bottlenecks and gate reasons below to understand why.</div>'
        elif result.total_signals < 5:
            alert_message = '<div class="alert alert-warning">Very few signals were generated. This may indicate restrictive filter conditions or unsuitable market conditions during this period.</div>'
        
        verification_html = f"""
        <h2>Strategy Health & Explainability</h2>
        {alert_message}
        
        <div class="verification-grid">
            <div class="verification-card">
                <h4>Signal Density</h4>
                <div class="stat-row">
                    <span class="stat-label">Signals/Day:</span>
                    <span class="stat-value {'low-value' if v.signals_per_day < 1 else ''}">{v.signals_per_day:.2f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Signals/Hour:</span>
                    <span class="stat-value">{v.signals_per_hour:.3f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Trading Days:</span>
                    <span class="stat-value">{v.trading_days}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Trading Hours:</span>
                    <span class="stat-value">{v.trading_hours}</span>
                </div>
            </div>
        """
        
        # Signal type distribution
        if v.signal_type_distribution:
            verification_html += """
            <div class="verification-card">
                <h4>Signal Type Distribution</h4>
            """
            for sig_type, count in sorted(v.signal_type_distribution.items(), key=lambda x: -x[1]):
                verification_html += f'<div class="stat-row"><span class="stat-label">{sig_type}:</span><span class="stat-value">{count}</span></div>'
            verification_html += "</div>"
        
        # Regime distribution
        if v.regime_distribution:
            verification_html += """
            <div class="verification-card">
                <h4>Regime Distribution</h4>
            """
            for regime, count in sorted(v.regime_distribution.items(), key=lambda x: -x[1]):
                verification_html += f'<div class="stat-row"><span class="stat-label">{regime}:</span><span class="stat-value">{count}</span></div>'
            verification_html += "</div>"
        
        # Volatility distribution
        if v.volatility_distribution:
            verification_html += """
            <div class="verification-card">
                <h4>Volatility Distribution</h4>
            """
            for vol_level, count in sorted(v.volatility_distribution.items(), key=lambda x: -x[1]):
                verification_html += f'<div class="stat-row"><span class="stat-label">{vol_level}:</span><span class="stat-value">{count}</span></div>'
            verification_html += "</div>"
        
        # Session distribution
        if v.session_distribution:
            verification_html += """
            <div class="verification-card">
                <h4>Session Distribution</h4>
            """
            for session, count in sorted(v.session_distribution.items(), key=lambda x: -x[1]):
                verification_html += f'<div class="stat-row"><span class="stat-label">{session}:</span><span class="stat-value">{count}</span></div>'
            verification_html += "</div>"
        
        verification_html += "</div>"  # Close verification-grid
        
        # Bottlenecks section (highlighted for quiet backtests)
        if v.bottleneck_summary:
            bottleneck_class = "highlight" if is_quiet_backtest else ""
            verification_html += f"""
            <div class="bottleneck-section {bottleneck_class}">
                <h3>Bottlenecks (Why Signals Were Rejected)</h3>
                <p class="section-hint">These conditions prevented potential signals from being generated:</p>
                <table class="bottleneck-table">
                    <thead><tr><th>Condition</th><th>Count</th><th>%</th></tr></thead>
                    <tbody>
            """
            total_bottlenecks = sum(v.bottleneck_summary.values())
            for k, cnt in sorted(v.bottleneck_summary.items(), key=lambda x: -x[1])[:10]:
                pct = (cnt / total_bottlenecks * 100) if total_bottlenecks > 0 else 0
                verification_html += f'<tr><td>{k}</td><td>{cnt:,}</td><td>{pct:.1f}%</td></tr>'
            verification_html += """
                    </tbody>
                </table>
            </div>
            """
        
        # Top gate reasons (most important for explaining quiet backtests)
        if v.top_gate_reasons:
            gate_class = "highlight" if is_quiet_backtest else ""
            verification_html += f"""
            <div class="gate-reasons-section {gate_class}">
                <h3>Top Gate Reasons</h3>
                <p class="section-hint">Most common reasons the scanner gate rejected potential entries:</p>
                <ol class="gate-reasons-list">
            """
            for reason in v.top_gate_reasons[:10]:
                verification_html += f'<li>{reason}</li>'
            verification_html += """
                </ol>
            </div>
            """
        
        # Execution summary (for full backtests)
        if v.execution_summary:
            verification_html += """
            <div class="execution-section">
                <h3>Execution Summary</h3>
                <p class="section-hint">Trade execution outcomes:</p>
                <table class="execution-table">
                    <tbody>
            """
            for k, cnt in v.execution_summary.items():
                verification_html += f'<tr><td>{k}</td><td>{cnt:,}</td></tr>'
            verification_html += """
                    </tbody>
                </table>
            </div>
            """

    # Date range warning
    warning_html = ""
    if dr.warning:
        warning_html = f'<p style="color: orange;">Warning: {dr.warning}</p>'

    # Trade gallery link
    trade_gallery_html = ""
    if has_trade_gallery:
        trade_gallery_html = '<a href="trades.html" class="gallery-link">View Trade Gallery</a>'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Backtest Report - {report.symbol}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #1a1a1a; color: #e0e0e0; }}
        h1, h2, h3, h4 {{ color: #fff; margin-top: 1.5em; }}
        table {{ border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #444; padding: 8px 12px; text-align: left; }}
        th {{ background: #333; }}
        tr:nth-child(even) {{ background: #252525; }}
        .metric-value {{ font-weight: bold; color: #4CAF50; }}
        .negative {{ color: #f44336; }}
        img {{ max-width: 100%; margin: 10px 0; border-radius: 8px; }}
        .files {{ margin: 20px 0; }}
        .files a {{ color: #64b5f6; margin-right: 15px; }}
        .gallery-link {{
            display: inline-block;
            background: #2962ff;
            color: white;
            padding: 12px 24px;
            border-radius: 6px;
            text-decoration: none;
            font-weight: bold;
            margin: 15px 0;
        }}
        .gallery-link:hover {{ background: #1e4bd8; }}
        
        /* Verification/Explainability styles */
        .alert {{
            padding: 12px 16px;
            border-radius: 6px;
            margin: 15px 0;
            font-weight: 500;
        }}
        .alert-danger {{
            background: #ef535033;
            border-left: 4px solid #ef5350;
            color: #ffcdd2;
        }}
        .alert-warning {{
            background: #ff980033;
            border-left: 4px solid #ff9800;
            color: #ffe0b2;
        }}
        .verification-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 15px;
            margin: 15px 0;
        }}
        .verification-card {{
            background: #252525;
            border-radius: 8px;
            padding: 15px;
        }}
        .verification-card h4 {{
            margin: 0 0 10px 0;
            font-size: 14px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .stat-row {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid #333;
        }}
        .stat-row:last-child {{ border-bottom: none; }}
        .stat-label {{ color: #aaa; }}
        .stat-value {{ font-weight: bold; color: #fff; }}
        .stat-value.low-value {{ color: #ff9800; }}
        
        .bottleneck-section, .gate-reasons-section, .execution-section {{
            background: #252525;
            border-radius: 8px;
            padding: 15px 20px;
            margin: 15px 0;
        }}
        .bottleneck-section.highlight, .gate-reasons-section.highlight {{
            border-left: 4px solid #ff9800;
            background: #2a2520;
        }}
        .section-hint {{
            color: #888;
            font-size: 13px;
            margin: 5px 0 15px 0;
        }}
        .bottleneck-table, .execution-table {{
            width: 100%;
        }}
        .gate-reasons-list {{
            margin: 0;
            padding-left: 20px;
        }}
        .gate-reasons-list li {{
            padding: 5px 0;
            color: #ddd;
        }}
    </style>
</head>
<body>
    <h1>Backtest Report: {report.symbol}</h1>
    <p>Period: {dr.actual_start.strftime('%Y-%m-%d')} to {dr.actual_end.strftime('%Y-%m-%d')}</p>
    <p>Timeframe: {report.decision_timeframe}</p>
    <p>Run: {report.run_timestamp}</p>
    {warning_html}

    {trade_gallery_html}

    <h2>Performance Metrics</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        {metrics_rows}
    </table>

    {verification_html}

    <h2>Files</h2>
    <div class="files">
        <a href="summary.json">summary.json</a>
        <a href="signals.csv">signals.csv</a>
        <a href="trades.csv">trades.csv</a>
        <a href="skipped_signals.csv">skipped_signals.csv</a>
    </div>

    <h2>Chart</h2>
    <img src="chart_overview.png" alt="Overview Chart" onerror="this.style.display='none'">
</body>
</html>
"""
    with open(report_dir / "index.html", "w") as f:
        f.write(html)


# ============================================================================
# CLI Entry Points
# ============================================================================

def run_signal_mode(args) -> BacktestReport:
    """Run signal-only backtest."""
    # Load data
    df = load_ohlcv_data(Path(args.data_path))
    print(f"Loaded {len(df):,} bars from {args.data_path}")

    # Slice by date range
    start = pd.to_datetime(args.start, utc=True) if args.start else None
    end = pd.to_datetime(args.end, utc=True) if args.end else None
    df_sliced, date_info = slice_by_date_range(df, start, end, args.lookback_weeks)

    print(f"Dataset range: {date_info.dataset_start} to {date_info.dataset_end}")
    print(f"Sliced range:  {date_info.actual_start} to {date_info.actual_end} ({date_info.bars_sliced:,} bars)")
    if date_info.warning:
        print(f"⚠️  Warning: {date_info.warning}")

    # Load config
    config = NQIntradayConfig.from_config_file()
    if args.symbol:
        config.symbol = args.symbol

    # Run backtest
    print(f"\nRunning signal-only backtest ({args.decision} decision bars)...")

    if args.decision == "5m":
        result = run_signal_backtest_5m_decision(df_sliced, config=config, return_signals=True)
    else:
        result = run_signal_backtest(df_sliced, config=config, return_signals=True)

    return BacktestReport(
        symbol=config.symbol,
        decision_timeframe=args.decision,
        date_range=date_info,
        result=result,
    )


def run_full_mode(args) -> BacktestReport:
    """Run full trade simulation backtest."""
    # Load data
    df = load_ohlcv_data(Path(args.data_path))
    print(f"Loaded {len(df):,} bars from {args.data_path}")

    # Slice by date range
    start = pd.to_datetime(args.start, utc=True) if args.start else None
    end = pd.to_datetime(args.end, utc=True) if args.end else None
    df_sliced, date_info = slice_by_date_range(df, start, end, args.lookback_weeks)

    print(f"Dataset range: {date_info.dataset_start} to {date_info.dataset_end}")
    print(f"Sliced range:  {date_info.actual_start} to {date_info.actual_end} ({date_info.bars_sliced:,} bars)")
    if date_info.warning:
        print(f"⚠️  Warning: {date_info.warning}")

    # Load config
    config = NQIntradayConfig.from_config_file()
    if args.symbol:
        config.symbol = args.symbol

    # Determine tick value based on symbol
    tick_value = 20.0 if args.symbol and args.symbol.upper() == "NQ" else 2.0  # NQ: $20/pt, MNQ: $2/pt

    # Risk config
    risk_config = RiskConfig(
        account_balance=args.account_balance,
        max_risk_per_trade=args.max_risk_per_trade,
        risk_budget_dollars=args.risk_budget,
        max_contracts=args.contracts,
        max_stop_points=args.max_stop_points,
    )

    # Run backtest
    print(f"\nRunning full backtest ({args.decision} decision bars)...")
    print(f"  Contracts: {args.contracts} | Slippage: {args.slippage_ticks} ticks | Max pos: {args.max_pos}")
    if args.account_balance:
        print(f"  Risk-based sizing: ${args.account_balance:,.0f} account, {args.max_risk_per_trade*100:.1f}% risk/trade")
    if args.max_stop_points:
        print(f"  Stop cap: {args.max_stop_points} points")

    if args.decision == "5m":
        result = run_full_backtest_5m_decision(
            df_sliced,
            config=config,
            position_size=args.contracts,
            tick_value=tick_value,
            slippage_ticks=args.slippage_ticks,
            max_concurrent_trades=args.max_pos,
            return_trades=True,
            # Risk-based sizing parameters
            account_balance=args.account_balance,
            max_risk_per_trade=args.max_risk_per_trade,
            risk_budget_dollars=args.risk_budget,
            max_contracts=args.contracts,
            max_stop_points=args.max_stop_points,
        )
    else:
        result = run_full_backtest(
            df_sliced,
            config=config,
            position_size=args.contracts,
            tick_value=tick_value,
            slippage_ticks=args.slippage_ticks,
            max_concurrent_trades=args.max_pos,
            return_trades=True,
            # Risk-based sizing parameters
            account_balance=args.account_balance,
            max_risk_per_trade=args.max_risk_per_trade,
            risk_budget_dollars=args.risk_budget,
            max_contracts=args.contracts,
            max_stop_points=args.max_stop_points,
        )

    # Convert engine skipped signals to CLI SkippedSignal format for report
    # The engine (TradeSimulator) tracks all skip reasons: concurrency, risk budget, stop cap, invalid prices
    skipped_signals: List[SkippedSignal] = []
    if result.skipped_signals:
        for skip_dict in result.skipped_signals:
            skipped_signals.append(SkippedSignal(
                timestamp=skip_dict.get("timestamp", ""),
                signal_type=skip_dict.get("signal_type", "unknown"),
                direction=skip_dict.get("direction", "long"),
                stop_distance_points=skip_dict.get("stop_distance_points", 0.0),
                skip_reason=skip_dict.get("skip_reason", "unknown"),
                computed_contracts=skip_dict.get("computed_contracts"),
            ))

    return BacktestReport(
        symbol=config.symbol,
        decision_timeframe=args.decision,
        date_range=date_info,
        result=result,
        risk_config=risk_config,
        skipped_signals=skipped_signals,
    )


def print_summary(report: BacktestReport) -> None:
    """Print backtest summary to console."""
    result = report.result
    dr = report.date_range

    print("\n" + "=" * 60)
    print(f"Backtest Results: {report.symbol} ({report.decision_timeframe} decision)")
    print("=" * 60)
    print(f"Period: {dr.actual_start.strftime('%Y-%m-%d')} to {dr.actual_end.strftime('%Y-%m-%d')}")
    print(f"Bars: {result.total_bars:,} | Signals: {result.total_signals:,}")

    if result.total_trades is not None:
        print(f"\nTrades: {result.total_trades} | Win Rate: {(result.win_rate or 0)*100:.1f}% | PF: {result.profit_factor or 0:.2f}")
        print(f"Total P&L: ${result.total_pnl or 0:,.2f} | Max DD: ${result.max_drawdown or 0:,.2f} | Sharpe: {result.sharpe_ratio or 0:.2f}")

    print(f"\nAvg Confidence: {result.avg_confidence:.2f} | Avg R:R: {result.avg_risk_reward:.2f}:1")

    # Verification summary
    if result.verification:
        print("\n" + "-" * 40)
        print("Verification Summary")
        print("-" * 40)
        print(result.verification.format_compact())
        if result.verification.top_gate_reasons:
            print("\nTop scanner gate reasons:")
            for reason in result.verification.top_gate_reasons[:5]:
                print(f"  - {reason}")

    if dr.warning:
        print(f"\n⚠️  {dr.warning}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified backtest CLI for MNQ/NQ strategies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # Common arguments
    def add_common_args(p):
        p.add_argument("--data-path", required=True, help="Path to OHLCV data (parquet/CSV)")
        p.add_argument("--symbol", default=None, help="Symbol override (default: MNQ)")
        p.add_argument("--decision", choices=["1m", "5m"], default="5m", help="Decision timeframe")
        p.add_argument("--start", help="Start date (YYYY-MM-DD)")
        p.add_argument("--end", help="End date (YYYY-MM-DD)")
        p.add_argument("--lookback-weeks", type=int, help="Alternative to --start: weeks of lookback from end")
        p.add_argument("--output-dir", default="reports", help="Output directory for reports")
        p.add_argument("--no-report", action="store_true", help="Skip writing report files")
        
        # Chart generation options
        p.add_argument(
            "--charts",
            choices=["none", "overview", "trade_gallery"],
            default="overview",
            help="Chart generation mode (default: overview)"
        )
        p.add_argument(
            "--trade-charts-max",
            type=int,
            default=50,
            help="Max number of per-trade charts to generate (default: 50)"
        )
        p.add_argument(
            "--trade-chart-lookback",
            type=int,
            default=30,
            help="Bars to show before entry in trade charts (default: 30)"
        )
        p.add_argument(
            "--trade-chart-forward",
            type=int,
            default=15,
            help="Bars to show after exit in trade charts (default: 15)"
        )
        p.add_argument(
            "--chart-preset",
            choices=["default", "wide"],
            default="default",
            help="Chart size preset (default: default, wide: larger for better readability)"
        )
        p.add_argument(
            "--no-hud",
            action="store_true",
            help="Disable HUD overlays on trade charts"
        )

    # Signal mode
    signal_parser = subparsers.add_parser("signal", help="Signal-only backtest (fast)")
    add_common_args(signal_parser)

    # Full mode
    full_parser = subparsers.add_parser("full", help="Full trade simulation backtest")
    add_common_args(full_parser)
    full_parser.add_argument("--contracts", type=int, default=5, help="Position size (contracts)")
    full_parser.add_argument("--slippage-ticks", type=float, default=0.5, help="Slippage in ticks")
    full_parser.add_argument("--max-pos", type=int, default=1, help="Max concurrent positions")
    full_parser.add_argument("--account-balance", type=float, help="Account balance for risk-based sizing")
    full_parser.add_argument("--max-risk-per-trade", type=float, default=0.01, help="Max risk per trade (fraction)")
    full_parser.add_argument("--risk-budget", type=float, help="Direct dollar risk budget per trade")
    full_parser.add_argument("--max-stop-points", type=float, help="Max stop distance cap (points)")

    args = parser.parse_args()

    try:
        # Run backtest
        if args.mode == "signal":
            report = run_signal_mode(args)
        else:
            report = run_full_mode(args)

        # Print summary
        print_summary(report)

        # Write report
        if not args.no_report:
            output_dir = Path(args.output_dir)
            
            # Build chart options from CLI args
            chart_options = ChartOptions(
                mode=args.charts,
                trade_charts_max=args.trade_charts_max,
                trade_chart_lookback_bars=args.trade_chart_lookback,
                trade_chart_forward_bars=args.trade_chart_forward,
                chart_preset=args.chart_preset,
                show_hud=not args.no_hud,
            )
            
            # Load OHLCV data for chart generation if needed
            ohlcv_data = None
            if args.charts != "none" and (report.result.signals or report.result.trades):
                try:
                    df = load_ohlcv_data(Path(args.data_path))
                    start = pd.to_datetime(args.start, utc=True) if args.start else None
                    end = pd.to_datetime(args.end, utc=True) if args.end else None
                    ohlcv_data, _ = slice_by_date_range(df, start, end, getattr(args, "lookback_weeks", None))
                except Exception as e:
                    print(f"Warning: Could not load data for charts: {e}")
            
            # Write report with chart options
            report_dir = write_report(
                report,
                output_dir,
                chart_options=chart_options,
                ohlcv_data=ohlcv_data,
            )
            print(f"\nReport written to: {report_dir}")

            # Generate overview chart if we have data and signals (and charts mode is not none)
            if args.charts != "none" and report.result.signals and ohlcv_data is not None:
                try:
                    # Determine figsize/dpi based on preset
                    if args.chart_preset == "wide":
                        figsize = (18, 10)
                        dpi = 180
                    else:
                        figsize = (14, 9)
                        dpi = 150

                    chart_gen = ChartGenerator(ChartConfig())
                    
                    # Determine date range for title
                    dr = report.date_range
                    title = f"Backtest Results ({dr.actual_start.strftime('%Y-%m-%d')} to {dr.actual_end.strftime('%Y-%m-%d')}) - {report.result.total_signals} Signals - {args.decision} decision"
                    
                    chart_path = chart_gen.generate_backtest_chart(
                        ohlcv_data,
                        report.result.signals,
                        symbol=report.symbol,
                        title=title,
                        timeframe=args.decision,
                        figsize=figsize,
                        dpi=dpi,
                    )
                    if chart_path:
                        import shutil
                        dest = report_dir / "chart_overview.png"
                        shutil.move(str(chart_path), str(dest))
                        print(f"Overview chart saved to: {dest}")
                except Exception as e:
                    print(f"Warning: Could not generate overview chart: {e}")
            
            # Print trade gallery info if generated
            if args.charts == "trade_gallery" and report.result.trades:
                trades_html = report_dir / "trades.html"
                if trades_html.exists():
                    print(f"Trade gallery available at: {trades_html}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

