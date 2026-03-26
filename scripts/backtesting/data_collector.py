#!/usr/bin/env python3
"""
PearlAlgo Historical Data Collector

Downloads 1m and 5m bars from IBKR and stores them in SQLite for backtesting.
Supports incremental updates (only fetches new bars since last timestamp).

Usage:
    python scripts/backtesting/data_collector.py --days 30
    python scripts/backtesting/data_collector.py --days 7 --timeframe 5m
    python scripts/backtesting/data_collector.py --days 14 --from-cache
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DB_DIR = PROJECT_ROOT / "data" / "backtest"
DB_PATH = DB_DIR / "bars.db"


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Create the bars database and tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bars_1m (
            timestamp TEXT PRIMARY KEY,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bars_5m (
            timestamp TEXT PRIMARY KEY,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def get_last_timestamp(conn: sqlite3.Connection, table: str) -> Optional[datetime]:
    """Get the most recent timestamp in a table."""
    row = conn.execute(f"SELECT MAX(timestamp) FROM {table}").fetchone()
    if row and row[0]:
        return pd.Timestamp(row[0]).to_pydatetime().replace(tzinfo=timezone.utc)
    return None


def insert_bars(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    """Insert bars into the database, ignoring duplicates. Returns count inserted."""
    if df.empty:
        return 0
    rows = []
    for _, r in df.iterrows():
        ts = r["timestamp"]
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        rows.append((str(ts), float(r["open"]), float(r["high"]),
                      float(r["low"]), float(r["close"]), float(r.get("volume", 0))))
    conn.executemany(
        f"INSERT OR IGNORE INTO {table} (timestamp, open, high, low, close, volume) "
        f"VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def load_bars_from_db(
    conn: sqlite3.Connection, table: str, days: Optional[int] = None
) -> pd.DataFrame:
    """Load bars from the database, optionally filtered to last N days."""
    query = f"SELECT timestamp, open, high, low, close, volume FROM {table}"
    params: list = []
    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        query += " WHERE timestamp >= ?"
        params.append(cutoff)
    query += " ORDER BY timestamp ASC"
    df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def load_from_cache_files(timeframe: str = "1m") -> pd.DataFrame:
    """Load bars from existing candle cache JSON files."""
    data_dir = PROJECT_ROOT / "data"
    frames: List[pd.DataFrame] = []

    pattern = f"candle_cache_MNQ_{timeframe}_*.json"
    for cache_file in sorted(data_dir.glob(pattern)):
        try:
            with open(cache_file) as f:
                data = json.load(f)
            candles = data.get("candles", data) if isinstance(data, dict) else data
            if not candles:
                continue
            rows = []
            for c in candles:
                ts = c.get("time") or c.get("timestamp")
                if isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(ts, tz=timezone.utc)
                rows.append({
                    "timestamp": ts,
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c.get("volume", 0)),
                })
            df = pd.DataFrame(rows)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            frames.append(df)
            print(f"  Loaded {len(df)} bars from {cache_file.name}")
        except Exception as e:
            print(f"  Warning: Failed to load {cache_file.name}: {e}")

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return combined


def resample_1m_to_5m(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m bars to 5m bars."""
    if df_1m.empty:
        return pd.DataFrame()
    df = df_1m.set_index("timestamp").sort_index()
    resampled = df.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    resampled = resampled.reset_index()
    return resampled


def fetch_from_ibkr(
    symbol: str = "MNQ",
    timeframe: str = "1m",
    days: int = 30,
    start_from: Optional[datetime] = None,
) -> pd.DataFrame:
    """Fetch historical bars from IBKR provider."""
    try:
        from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
    except ImportError as e:
        print(f"  ERROR: Cannot import IBKRProvider: {e}")
        return pd.DataFrame()

    end = datetime.now(timezone.utc)
    if start_from:
        start = start_from
    else:
        start = end - timedelta(days=days)

    print(f"  Fetching {symbol} {timeframe} bars from IBKR: {start.date()} to {end.date()}")

    try:
        provider = IBKRProvider()
        df = provider.fetch_historical(symbol=symbol, start=start, end=end, timeframe=timeframe)
        if df is not None and not df.empty:
            if "timestamp" not in df.columns and df.index.name == "timestamp":
                df = df.reset_index()
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            print(f"  Fetched {len(df)} bars from IBKR")
            return df
        else:
            print("  WARNING: IBKR returned no data")
            return pd.DataFrame()
    except Exception as e:
        print(f"  ERROR: IBKR fetch failed: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Main collection logic
# ---------------------------------------------------------------------------

def collect_data(
    days: int = 30,
    from_cache: bool = False,
    from_ibkr: bool = True,
    db_path: Path = DB_PATH,
) -> dict:
    """Collect historical data and store in SQLite.

    Returns:
        Summary dict with counts.
    """
    conn = init_db(db_path)
    summary = {"bars_1m": 0, "bars_5m": 0, "source": "none"}

    # Check what we already have
    last_1m = get_last_timestamp(conn, "bars_1m")
    last_5m = get_last_timestamp(conn, "bars_5m")
    if last_1m:
        print(f"  Existing 1m data up to: {last_1m.isoformat()}")
    if last_5m:
        print(f"  Existing 5m data up to: {last_5m.isoformat()}")

    # Load from cache files first (always available)
    if from_cache or not from_ibkr:
        print("\nLoading from cache files...")
        df_1m = load_from_cache_files("1m")
        if not df_1m.empty:
            n = insert_bars(conn, "bars_1m", df_1m)
            summary["bars_1m"] += n
            summary["source"] = "cache"
            print(f"  Inserted {n} 1m bars from cache")

        df_5m = load_from_cache_files("5m")
        if not df_5m.empty:
            n = insert_bars(conn, "bars_5m", df_5m)
            summary["bars_5m"] += n
            print(f"  Inserted {n} 5m bars from cache")
        elif not df_1m.empty:
            # Resample 1m to 5m
            df_5m = resample_1m_to_5m(df_1m)
            if not df_5m.empty:
                n = insert_bars(conn, "bars_5m", df_5m)
                summary["bars_5m"] += n
                print(f"  Inserted {n} 5m bars (resampled from 1m)")

    # Fetch from IBKR (incremental)
    if from_ibkr:
        print("\nFetching from IBKR...")
        start_from = last_1m if last_1m else None
        df_1m = fetch_from_ibkr("MNQ", "1m", days=days, start_from=start_from)
        if not df_1m.empty:
            n = insert_bars(conn, "bars_1m", df_1m)
            summary["bars_1m"] += n
            summary["source"] = "ibkr"
            print(f"  Inserted {n} new 1m bars")

        start_from_5m = last_5m if last_5m else None
        df_5m = fetch_from_ibkr("MNQ", "5m", days=days, start_from=start_from_5m)
        if not df_5m.empty:
            n = insert_bars(conn, "bars_5m", df_5m)
            summary["bars_5m"] += n
            print(f"  Inserted {n} new 5m bars")

    # Report totals
    total_1m = conn.execute("SELECT COUNT(*) FROM bars_1m").fetchone()[0]
    total_5m = conn.execute("SELECT COUNT(*) FROM bars_5m").fetchone()[0]
    print(f"\nDatabase totals: {total_1m} 1m bars, {total_5m} 5m bars")

    range_1m = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM bars_1m"
    ).fetchone()
    if range_1m[0]:
        print(f"  1m range: {range_1m[0]} to {range_1m[1]}")
    range_5m = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM bars_5m"
    ).fetchone()
    if range_5m[0]:
        print(f"  5m range: {range_5m[0]} to {range_5m[1]}")

    summary["total_1m"] = total_1m
    summary["total_5m"] = total_5m
    conn.close()
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="PearlAlgo Historical Data Collector")
    parser.add_argument("--days", type=int, default=30, help="Days of history to fetch (default: 30)")
    parser.add_argument("--from-cache", action="store_true", help="Load from local cache files only (no IBKR)")
    parser.add_argument("--no-ibkr", action="store_true", help="Skip IBKR fetch (use cache only)")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="SQLite database path")
    args = parser.parse_args()

    print(f"\nPearlAlgo Data Collector")
    print(f"{'='*40}")
    print(f"  Days: {args.days}")
    print(f"  Database: {args.db}")

    use_ibkr = not args.no_ibkr and not args.from_cache
    summary = collect_data(
        days=args.days,
        from_cache=args.from_cache or args.no_ibkr,
        from_ibkr=use_ibkr,
        db_path=Path(args.db),
    )
    print(f"\nCollection complete: {summary}")


if __name__ == "__main__":
    main()
