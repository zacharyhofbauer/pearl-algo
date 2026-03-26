#!/usr/bin/env python3
"""
One-time migration: Convert all entry_time/exit_time/created_at from UTC to ET (naive).
FIXED 2026-03-25: ET timezone migration

DST boundary: March 8 2026, 2:00 AM ET = March 8 2026 07:00:00 UTC
  - Before: EST = UTC-5
  - After:  EDT = UTC-4
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB = Path("/home/pearlalgo/pearl-algo-workspace/data/tradovate/paper/trades.db")

# DST boundary in UTC: March 8 2026 07:00:00 UTC
DST_BOUNDARY = datetime(2026, 3, 8, 7, 0, 0)

TIME_COLUMNS = ["entry_time", "exit_time", "created_at"]


def utc_naive_to_et_naive(ts_str: str) -> str:
    """Convert a naive-UTC timestamp string to naive-ET string."""
    if not ts_str:
        return ts_str
    # Strip any tz suffix if present
    clean = ts_str.replace("+00:00", "").replace("Z", "").strip()
    try:
        dt = datetime.fromisoformat(clean)
    except ValueError:
        return ts_str  # leave unparseable values alone

    if dt >= DST_BOUNDARY:
        et_dt = dt - timedelta(hours=4)  # EDT
    else:
        et_dt = dt - timedelta(hours=5)  # EST
    return et_dt.strftime("%Y-%m-%dT%H:%M:%S")


def dry_run(conn):
    """Print before/after for 10 sample rows."""
    print("=== DRY RUN: 10 sample conversions ===\n")
    rows = conn.execute(
        "SELECT rowid, entry_time, exit_time, created_at FROM trades ORDER BY rowid LIMIT 5"
    ).fetchall()
    rows += conn.execute(
        "SELECT rowid, entry_time, exit_time, created_at FROM trades ORDER BY rowid DESC LIMIT 5"
    ).fetchall()

    for rowid, entry, exit_, created in rows:
        new_entry = utc_naive_to_et_naive(entry)
        new_exit = utc_naive_to_et_naive(exit_)
        new_created = utc_naive_to_et_naive(created)
        print(f"Row {rowid}:")
        print(f"  entry_time:  {entry:30s} -> {new_entry}")
        print(f"  exit_time:   {exit_:30s} -> {new_exit}")
        print(f"  created_at:  {created:30s} -> {new_created}")
        print()


def migrate(conn):
    """Run the full migration in a transaction."""
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT rowid, entry_time, exit_time, created_at FROM trades"
    ).fetchall()

    updated = 0
    for rowid, entry, exit_, created in rows:
        new_entry = utc_naive_to_et_naive(entry)
        new_exit = utc_naive_to_et_naive(exit_)
        new_created = utc_naive_to_et_naive(created)

        if new_entry != entry or new_exit != exit_ or new_created != created:
            cursor.execute(
                "UPDATE trades SET entry_time=?, exit_time=?, created_at=? WHERE rowid=?",
                (new_entry, new_exit, new_created, rowid),
            )
            updated += 1

    return updated


def spot_check(conn):
    """Spot-check 5 random rows after migration."""
    print("\n=== SPOT CHECK: 5 random rows ===\n")
    for row in conn.execute(
        "SELECT rowid, entry_time, exit_time, pnl FROM trades ORDER BY RANDOM() LIMIT 5"
    ).fetchall():
        print(f"  Row {row[0]}: entry={row[1]}  exit={row[2]}  pnl={row[3]}")


def main():
    conn = sqlite3.connect(DB)

    total = conn.execute("SELECT count(*) FROM trades").fetchone()[0]
    print(f"Database: {DB}")
    print(f"Total trades: {total}\n")

    # Always dry run first
    dry_run(conn)

    if "--execute" not in sys.argv:
        print("\n>>> Dry run only. Pass --execute to apply migration.")
        conn.close()
        return

    print("\n=== EXECUTING MIGRATION ===\n")
    try:
        updated = migrate(conn)
        conn.commit()
        print(f"Migration complete: {updated}/{total} rows updated.")
        spot_check(conn)
    except Exception as e:
        conn.rollback()
        print(f"ERROR — rolled back: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
