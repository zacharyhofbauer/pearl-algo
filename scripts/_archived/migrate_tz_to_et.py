#!/usr/bin/env python3
"""
One-time migration: Convert trades.db timestamps from UTC to ET (America/New_York).

- Trades before 2026-03-09 02:00 UTC are EST (UTC-5)
- Trades on/after 2026-03-09 02:00 UTC are EDT (UTC-4)
- Output format: naive ISO string 'YYYY-MM-DDTHH:MM:SS' (implicitly ET)

Usage:
  python scripts/migrate_tz_to_et.py --dry-run   # preview 10 rows
  python scripts/migrate_tz_to_et.py              # run for real
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB = Path('/home/pearlalgo/pearl-algo-workspace/data/tradovate/paper/trades.db')

# DST boundary: clocks spring forward at 2026-03-08 02:00 EST = 2026-03-08 07:00 UTC
DST_BOUNDARY_UTC = datetime(2026, 3, 8, 7, 0, 0)

def utc_to_et(ts_str: str) -> str:
    """Convert a UTC ISO timestamp string to naive ET string."""
    if not ts_str:
        return ts_str
    # Parse - handle +00:00 suffix
    normalized = ts_str.replace("Z", "+00:00")
    # Strip tz suffix for parsing as naive, then apply offset
    # fromisoformat handles +00:00
    dt = datetime.fromisoformat(normalized)
    # Make naive UTC
    dt_naive = dt.replace(tzinfo=None)

    if dt_naive >= DST_BOUNDARY_UTC:
        # EDT: UTC-4
        et = dt_naive - timedelta(hours=4)
    else:
        # EST: UTC-5
        et = dt_naive - timedelta(hours=5)

    return et.strftime('%Y-%m-%dT%H:%M:%S')

def migrate(dry_run=False):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT trade_id, entry_time, exit_time FROM trades ORDER BY entry_time")
    rows = c.fetchall()
    print(f"Total rows to migrate: {len(rows)}")

    if dry_run:
        print("\n=== DRY RUN — first 10 rows ===")
        for row in rows[:10]:
            et_entry = utc_to_et(row["entry_time"])
            et_exit = utc_to_et(row["exit_time"])
            print(f"  {row['trade_id'][:16]}...")
            print(f"    entry: {row['entry_time']}  →  {et_entry}")
            print(f"    exit:  {row['exit_time']}  →  {et_exit}")
        print("\n=== Last 5 rows ===")
        for row in rows[-5:]:
            et_entry = utc_to_et(row["entry_time"])
            et_exit = utc_to_et(row["exit_time"])
            print(f"  {row['trade_id'][:16]}...")
            print(f"    entry: {row['entry_time']}  →  {et_entry}")
            print(f"    exit:  {row['exit_time']}  →  {et_exit}")
        return

    # Real migration in a transaction
    try:
        updates = []
        for row in rows:
            et_entry = utc_to_et(row["entry_time"])
            et_exit = utc_to_et(row["exit_time"])
            updates.append((et_entry, et_exit, row["trade_id"]))

        c.executemany(
            "UPDATE trades SET entry_time = ?, exit_time = ? WHERE trade_id = ?",
            updates
        )

        # Also migrate created_at column
        c.execute("SELECT trade_id, created_at FROM trades WHERE created_at IS NOT NULL")
        ca_rows = c.fetchall()
        ca_updates = []
        for row in ca_rows:
            if row["created_at"]:
                ca_updates.append((utc_to_et(row["created_at"]), row["trade_id"]))
        if ca_updates:
            c.executemany("UPDATE trades SET created_at = ? WHERE trade_id = ?", ca_updates)
            print(f"Migrated {len(ca_updates)} created_at values")

        conn.commit()
        print(f"Successfully migrated {len(updates)} trades to ET")

        # Spot-check
        print("\n=== Spot check (5 random rows) ===")
        c.execute("SELECT trade_id, entry_time, exit_time FROM trades ORDER BY RANDOM() LIMIT 5")
        for row in c.fetchall():
            print(f"  {row['trade_id'][:16]}  entry={row['entry_time']}  exit={row['exit_time']}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR — rolled back: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    migrate(dry_run=dry_run)
