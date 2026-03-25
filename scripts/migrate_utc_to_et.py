#!/usr/bin/env python3
"""
One-time migration: Convert all trade timestamps from UTC to ET (America/New_York).
Run with --dry-run first to verify, then without to apply.

FIXED 2026-03-25: ET timezone migration
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytz

DB = Path("/home/pearlalgo/pearl-algo-workspace/data/tradovate/paper/trades.db")
ET = pytz.timezone("America/New_York")

DRY_RUN = "--dry-run" in sys.argv


def convert_utc_to_et(ts_str: str) -> str:
    """Parse a naive UTC timestamp string, convert to ET, return naive ET string."""
    if not ts_str:
        return ts_str
    # Parse naive string as UTC
    dt_naive = datetime.fromisoformat(ts_str.replace("Z", "").split("+")[0])
    dt_utc = dt_naive.replace(tzinfo=timezone.utc)
    # Convert to ET (handles EST/EDT automatically)
    dt_et = dt_utc.astimezone(ET)
    return dt_et.strftime("%Y-%m-%dT%H:%M:%S")


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT count(*) FROM trades")
    total = c.fetchone()[0]
    print(f"Total trades: {total}")

    # Fetch all trades
    c.execute("SELECT trade_id, entry_time, exit_time, created_at FROM trades")
    rows = c.fetchall()

    updates = []
    for row in rows:
        tid = row["trade_id"]
        new_entry = convert_utc_to_et(row["entry_time"]) if row["entry_time"] else None
        new_exit = convert_utc_to_et(row["exit_time"]) if row["exit_time"] else None
        new_created = convert_utc_to_et(row["created_at"]) if row["created_at"] else None
        updates.append((new_entry, new_exit, new_created, tid))

    if DRY_RUN:
        print("\n=== DRY RUN — showing 10 sample conversions ===\n")
        c.execute("SELECT trade_id, entry_time, exit_time FROM trades ORDER BY rowid LIMIT 5")
        early = c.fetchall()
        c.execute("SELECT trade_id, entry_time, exit_time FROM trades ORDER BY rowid DESC LIMIT 5")
        late = c.fetchall()

        for row in list(early) + list(late):
            old_entry = row["entry_time"]
            old_exit = row["exit_time"]
            new_entry = convert_utc_to_et(old_entry) if old_entry else None
            new_exit = convert_utc_to_et(old_exit) if old_exit else None
            print(f"  {row['trade_id'][:16]}...")
            print(f"    entry: {old_entry}  ->  {new_entry}")
            print(f"    exit:  {old_exit}  ->  {new_exit}")
        conn.close()
        print("\nDry run complete. Run without --dry-run to apply.")
        return

    # Apply migration in a transaction
    print("\nApplying migration...")
    try:
        c.execute("BEGIN TRANSACTION")
        for new_entry, new_exit, new_created, tid in updates:
            c.execute(
                "UPDATE trades SET entry_time=?, exit_time=?, created_at=? WHERE trade_id=?",
                (new_entry, new_exit, new_created, tid),
            )
        conn.commit()
        print(f"Migration complete: {len(updates)} rows updated.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR — rolled back: {e}")
        sys.exit(1)
    finally:
        conn.close()

    # Spot-check
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT entry_time, exit_time FROM trades ORDER BY rowid DESC LIMIT 5")
    print("\nSpot-check (last 5 trades):")
    for row in c.fetchall():
        print(f"  entry={row['entry_time']}  exit={row['exit_time']}")
    conn.close()


if __name__ == "__main__":
    main()
