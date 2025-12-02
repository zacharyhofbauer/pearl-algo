from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_PERF_PATH = Path("data/performance/futures_decisions.csv")


@dataclass
class PerformanceRow:
    timestamp: datetime
    symbol: str
    sec_type: str
    strategy_name: str
    side: str
    requested_size: int
    filled_size: int
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    fast_ma: Optional[float] = None
    slow_ma: Optional[float] = None
    risk_status: str = "UNKNOWN"
    drawdown_remaining: Optional[float] = None
    trade_reason: str | None = None
    emotion_state: str | None = None
    notes: str | None = None
    # Enhanced metrics
    hold_time_minutes: Optional[float] = None
    profit_factor: Optional[float] = None
    time_of_day_hour: Optional[int] = None
    day_of_week: Optional[str] = None


DEFAULT_COLUMNS = [
    "timestamp",
    "symbol",
    "sec_type",
    "strategy_name",
    "side",
    "requested_size",
    "filled_size",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "unrealized_pnl",
    "fast_ma",
    "slow_ma",
    "risk_status",
    "drawdown_remaining",
    "trade_reason",
    "emotion_state",
    "notes",
    "hold_time_minutes",
    "profit_factor",
    "time_of_day_hour",
    "day_of_week",
]


def _ensure_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS)
        writer.writeheader()


def log_performance_row(row: PerformanceRow, path: Path | str = DEFAULT_PERF_PATH) -> None:
    outfile = Path(path)
    _ensure_file(outfile)
    data = asdict(row)
    ts = row.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    data["timestamp"] = ts.isoformat()
    if row.entry_time:
        et = row.entry_time if row.entry_time.tzinfo else row.entry_time.replace(tzinfo=timezone.utc)
        data["entry_time"] = et.isoformat()
    if row.exit_time:
        xt = row.exit_time if row.exit_time.tzinfo else row.exit_time.replace(tzinfo=timezone.utc)
        data["exit_time"] = xt.isoformat()
    
    # Calculate enhanced metrics if not already set
    if row.hold_time_minutes is None and row.entry_time and row.exit_time:
        entry = row.entry_time if row.entry_time.tzinfo else row.entry_time.replace(tzinfo=timezone.utc)
        exit_t = row.exit_time if row.exit_time.tzinfo else row.exit_time.replace(tzinfo=timezone.utc)
        data["hold_time_minutes"] = (exit_t - entry).total_seconds() / 60.0
    
    if row.time_of_day_hour is None and row.entry_time:
        entry = row.entry_time if row.entry_time.tzinfo else row.entry_time.replace(tzinfo=timezone.utc)
        data["time_of_day_hour"] = entry.hour
    
    if row.day_of_week is None:
        data["day_of_week"] = ts.strftime("%A")
    
    with outfile.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS)
        writer.writerow({col: data.get(col) for col in DEFAULT_COLUMNS})


def load_performance(path: Path | str = DEFAULT_PERF_PATH) -> pd.DataFrame:
    infile = Path(path)
    if not infile.exists():
        return pd.DataFrame(columns=DEFAULT_COLUMNS)
    df = pd.read_csv(infile)
    # Parse datetime columns
    date_cols = ["timestamp", "entry_time", "exit_time"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def calculate_profit_factor(df: pd.DataFrame) -> float:
    """Calculate profit factor: sum of wins / abs(sum of losses)."""
    if df.empty or "realized_pnl" not in df.columns:
        return 0.0
    pnl = df["realized_pnl"].dropna()
    if len(pnl) == 0:
        return 0.0
    wins = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses) if wins > 0 else 0.0


def calculate_enhanced_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate enhanced metrics for all trades in dataframe."""
    df = df.copy()
    
    # Calculate hold_time_minutes if entry/exit times exist
    if "entry_time" in df.columns and "exit_time" in df.columns:
        mask = df["entry_time"].notna() & df["exit_time"].notna()
        if mask.any():
            durations = (df.loc[mask, "exit_time"] - df.loc[mask, "entry_time"]).dt.total_seconds() / 60.0
            df.loc[mask, "hold_time_minutes"] = durations
    
    # Calculate time_of_day_hour from entry_time
    if "entry_time" in df.columns:
        mask = df["entry_time"].notna()
        if mask.any():
            df.loc[mask, "time_of_day_hour"] = df.loc[mask, "entry_time"].dt.hour
    
    # Calculate day_of_week from timestamp
    if "timestamp" in df.columns:
        df["day_of_week"] = df["timestamp"].dt.strftime("%A")
    
    # Calculate profit factor per strategy (rolling)
    if "strategy_name" in df.columns and "realized_pnl" in df.columns:
        for strategy in df["strategy_name"].dropna().unique():
            strategy_mask = df["strategy_name"] == strategy
            strategy_df = df[strategy_mask].sort_values("timestamp")
            if len(strategy_df) > 0:
                # Calculate cumulative profit factor
                cumulative_wins = strategy_df["realized_pnl"].clip(lower=0).cumsum()
                cumulative_losses = abs(strategy_df["realized_pnl"].clip(upper=0).cumsum())
                profit_factors = cumulative_wins / cumulative_losses.replace(0, float("inf"))
                profit_factors = profit_factors.replace([float("inf"), float("-inf")], 0.0)
                df.loc[strategy_mask, "profit_factor"] = profit_factors.values
    
    return df


def summarize_daily_performance(
    path: str | Path = DEFAULT_PERF_PATH,
    date: str | None = None,
) -> dict[str, float]:
    """
    Calculate comprehensive performance metrics including win rate, avg P&L, worst drawdown, and time in trade.
    """
    df = load_performance(path)
    if df.empty:
        return {}
    if date:
        df = df[df["timestamp"].dt.date == pd.to_datetime(date).date()]
    if df.empty:
        return {}
    
    # Calculate enhanced metrics
    df = calculate_enhanced_metrics(df)
    
    trades = df.dropna(subset=["realized_pnl"])
    if trades.empty:
        return {
            "rows": float(len(df)),
            "trades": 0.0,
            "win_rate": 0.0,
            "avg_realized_pnl": 0.0,
            "worst_drawdown": 0.0,
            "avg_time_in_trade_minutes": 0.0,
            "profit_factor": 0.0,
        }
    
    wins = trades[trades["realized_pnl"] > 0]
    losses = trades[trades["realized_pnl"] < 0]
    
    # Calculate worst drawdown from drawdown_remaining column
    worst_drawdown = 0.0
    if "drawdown_remaining" in df.columns:
        drawdowns = df["drawdown_remaining"].dropna()
        if not drawdowns.empty:
            # Worst drawdown is the minimum remaining buffer (most negative relative to starting)
            # If we track from starting balance, worst is when remaining is closest to 0
            worst_drawdown = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0
    
    # Calculate average time in trade
    avg_time_minutes = 0.0
    if "hold_time_minutes" in trades.columns:
        hold_times = trades["hold_time_minutes"].dropna()
        if len(hold_times) > 0:
            avg_time_minutes = float(hold_times.mean())
    elif "entry_time" in trades.columns and "exit_time" in trades.columns:
        completed_trades = trades.dropna(subset=["entry_time", "exit_time"])
        if not completed_trades.empty:
            durations = (completed_trades["exit_time"] - completed_trades["entry_time"]).dt.total_seconds() / 60.0
            avg_time_minutes = float(durations.mean()) if len(durations) > 0 else 0.0
    
    # Calculate profit factor
    profit_factor = calculate_profit_factor(trades)
    
    return {
        "rows": float(len(df)),
        "trades": float(len(trades)),
        "wins": float(len(wins)),
        "losses": float(len(losses)),
        "win_rate": float(len(wins) / len(trades)) if len(trades) > 0 else 0.0,
        "avg_realized_pnl": float(trades["realized_pnl"].mean()) if len(trades) > 0 else 0.0,
        "worst_drawdown": worst_drawdown,
        "avg_time_in_trade_minutes": avg_time_minutes,
        "profit_factor": profit_factor,
    }
