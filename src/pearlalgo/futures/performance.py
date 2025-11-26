from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class PerformanceRow:
    timestamp: datetime
    symbol: str
    sec_type: str
    strategy_name: str
    signal: str
    proposed_size: int
    executed_size: int
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    fast_ma: Optional[float] = None
    slow_ma: Optional[float] = None
    atr: Optional[float] = None
    risk_state: str = "UNKNOWN"
    notes: str | None = None


DEFAULT_COLUMNS = [
    "timestamp",
    "symbol",
    "sec_type",
    "strategy_name",
    "signal",
    "proposed_size",
    "executed_size",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "unrealized_pnl",
    "fast_ma",
    "slow_ma",
    "atr",
    "risk_state",
    "notes",
]


def _ensure_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS)
        writer.writeheader()


def log_decision(row: PerformanceRow, path: str | Path = "data/performance/futures_decisions.csv") -> None:
    outfile = Path(path)
    _ensure_file(outfile)
    data = asdict(row)
    data["timestamp"] = row.timestamp.isoformat()
    with outfile.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS)
        writer.writerow({col: data.get(col) for col in DEFAULT_COLUMNS})


def summarize_daily_performance(
    path: str | Path = "data/performance/futures_decisions.csv",
    date: str | None = None,
) -> dict[str, float]:
    import pandas as pd

    infile = Path(path)
    if not infile.exists():
        return {}
    df = pd.read_csv(infile, parse_dates=["timestamp"])
    if df.empty:
        return {}
    if date:
        df = df[df["timestamp"].dt.date == pd.to_datetime(date).date()]
    trades = df.dropna(subset=["realized_pnl"])
    if trades.empty:
        return {}
    wins = trades[trades["realized_pnl"] > 0]
    return {
        "trades": float(len(trades)),
        "win_rate": float(len(wins) / len(trades)),
        "avg_realized_pnl": float(trades["realized_pnl"].mean()),
    }
