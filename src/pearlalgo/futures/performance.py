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
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    fast_ma: Optional[float] = None
    slow_ma: Optional[float] = None
    risk_status: str = "UNKNOWN"
    notes: str | None = None


DEFAULT_COLUMNS = [
    "timestamp",
    "symbol",
    "sec_type",
    "strategy_name",
    "side",
    "requested_size",
    "filled_size",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "unrealized_pnl",
    "fast_ma",
    "slow_ma",
    "risk_status",
    "notes",
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
    with outfile.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS)
        writer.writerow({col: data.get(col) for col in DEFAULT_COLUMNS})


def load_performance(path: Path | str = DEFAULT_PERF_PATH) -> pd.DataFrame:
    infile = Path(path)
    if not infile.exists():
        return pd.DataFrame(columns=DEFAULT_COLUMNS)
    return pd.read_csv(infile, parse_dates=["timestamp"])


def summarize_daily_performance(
    path: str | Path = DEFAULT_PERF_PATH,
    date: str | None = None,
) -> dict[str, float]:
    df = load_performance(path)
    if df.empty:
        return {}
    if date:
        df = df[df["timestamp"].dt.date == pd.to_datetime(date).date()]
    if df.empty:
        return {}
    trades = df.dropna(subset=["realized_pnl"])
    wins = trades[trades["realized_pnl"] > 0] if not trades.empty else pd.DataFrame()
    return {
        "rows": float(len(df)),
        "trades": float(len(trades)),
        "win_rate": float(len(wins) / len(trades)) if len(trades) > 0 else 0.0,
        "avg_realized_pnl": float(trades["realized_pnl"].mean()) if len(trades) > 0 else 0.0,
    }
