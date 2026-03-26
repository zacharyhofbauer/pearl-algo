#!/usr/bin/env python3
"""
Migrate trades.db timestamps from UTC to ET (America/New_York).

FIXED 2026-03-25: ET timezone migration
- All entry_time/exit_time stored as naive ET strings: YYYY-MM-DDTHH:MM:SS
- DST handled by pytz: EST (UTC-5) before March 8 2026, EDT (UTC-4) after
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytz

ET = pytz.timezone("America/New_York")

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "tradovate" / "paper"
DB_PATH = DATA_DIR / "trades.db"

TIME_COLUMNS = [
    ("entry_time", "trades"),
    ("exit_time", "trades"),
    ("created_at", "trades"),
]


def convert_utc_to_et_naive(iso_str: str) -> str:
    """Convert a UTC ISO string to naive ET string."""
    if not iso_str or iso_str.strip() == "":
        return iso_str

    try:
        # Parse the UTC ISO string
        s = iso_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"

        dt = datetime.fromisoformat(s)

        # If naive, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert to ET
        dt_et = dt.astimezone(ET)

        # Return naive ET string (no tz suffix)
        return dt_et.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as e:
        print(f"  WARNING: Could not convert '{iso_str}': {e}")
        return iso_str


def dry_run(conn: sqlite3.Connection):
    """Print before/after for 10 sample rows spanning both EST and EDT."""
    print("=== DRY RUN: Sample conversions ===\n")

    cur = conn.cursor()

    # Get 5 rows from before DST (Feb) and 5 from after (March 9+)
    cur.execute("""
        SELECT rowid, entry_time, exit_time, created_at FROM trades
        WHERE entry_time < '2026-03-08' ORDER BY rowid LIMIT 5
    """)
    pre_dst = cur.fetchall()

    cur.execute("""
        SELECT rowid, entry_time, exit_time, created_at FROM trades
        WHERE entry_time >= '2026-03-09' ORDER BY rowid DESC LIMIT 5
    """)
    post_dst = cur.fetchall()

    samples = pre_dst + post_dst
    if not samples:
        # Fallback: just get 10 rows
        cur.execute("SELECT rowid, entry_time, exit_time, created_at FROM trades LIMIT 10")
        samples = cur.fetchall()

    for rowid, entry, exit_t, created in samples:
        new_entry = convert_utc_to_et_naive(entry) if entry else entry
        new_exit = convert_utc_to_et_naive(exit_t) if exit_t else exit_t
        new_created = convert_utc_to_et_naive(created) if created else created
        print(f"Row {rowid}:")
        print(f"  entry_time:  {entry}")
        print(f"            -> {new_entry}")
        print(f"  exit_time:   {exit_t}")
        print(f"            -> {new_exit}")
        print(f"  created_at:  {created}")
        print(f"            -> {new_created}")
        print()


def migrate(conn: sqlite3.Connection):
    """Migrate all timestamps in a single transaction."""
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM trades")
    total = cur.fetchone()[0]
    print(f"Migrating {total} rows...")

    # Fetch all rows
    cur.execute("SELECT rowid, entry_time, exit_time, created_at FROM trades")
    rows = cur.fetchall()

    updated = 0
    for rowid, entry, exit_t, created in rows:
        new_entry = convert_utc_to_et_naive(entry) if entry else entry
        new_exit = convert_utc_to_et_naive(exit_t) if exit_t else exit_t
        new_created = convert_utc_to_et_naive(created) if created else created

        if new_entry != entry or new_exit != exit_t or new_created != created:
            cur.execute(
                "UPDATE trades SET entry_time=?, exit_time=?, created_at=? WHERE rowid=?",
                (new_entry, new_exit, new_created, rowid),
            )
            updated += 1

    print(f"Updated {updated}/{total} rows.")
    return updated


def spot_check(conn: sqlite3.Connection):
    """Spot-check 5 random rows after migration."""
    print("\n=== SPOT CHECK: 5 random rows after migration ===\n")
    cur = conn.cursor()
    cur.execute("SELECT rowid, entry_time, exit_time FROM trades ORDER BY RANDOM() LIMIT 5")
    for rowid, entry, exit_t in cur.fetchall():
        print(f"Row {rowid}: entry={entry}  exit={exit_t}")

    # Verify no UTC offset markers remain
    cur.execute("SELECT COUNT(*) FROM trades WHERE entry_time LIKE '%+00:00'")
    utc_remaining = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades WHERE exit_time LIKE '%+00:00'")
    utc_remaining += cur.fetchone()[0]
    print(f"\nRows still containing '+00:00': {utc_remaining}")
    if utc_remaining > 0:
        print("WARNING: Some rows were not converted!")


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)

    mode = sys.argv[1] if len(sys.argv) > 1 else "dry-run"

    conn = sqlite3.connect(str(DB_PATH))

    if mode == "dry-run":
        dry_run(conn)
        print("To run for real: python migrate_utc_to_et.py migrate")
    elif mode == "migrate":
        try:
            dry_run(conn)
            print("\n=== MIGRATING FOR REAL ===\n")
            migrate(conn)
            conn.commit()
            spot_check(conn)
            print("\nMigration committed successfully.")
        except Exception as e:
            conn.rollback()
            print(f"\nERROR: Migration rolled back: {e}")
            sys.exit(1)
    else:
        print(f"Usage: {sys.argv[0]} [dry-run|migrate]")

    conn.close()
