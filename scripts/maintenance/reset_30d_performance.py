#!/usr/bin/env python3
"""
Reset 30-day performance to a specific value.

This script:
1. Deletes all trades from the last 30 days
2. Inserts a single trade with the specified PNL to set the 30d performance
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

def reset_30d_performance(db_path: Path, target_pnl: float) -> None:
    """Reset 30-day performance to target_pnl."""
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    
    # Generate a unique trade_id
    trade_id = f"reset_30d_{int(datetime.now(timezone.utc).timestamp())}"
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        cursor = conn.cursor()
        
        # Get current 30d performance
        cursor.execute(
            "SELECT SUM(pnl) as total_pnl, COUNT(*) as count FROM trades WHERE entry_time >= ?",
            (cutoff_date,)
        )
        row = cursor.fetchone()
        current_pnl = row["total_pnl"] or 0.0
        current_count = row["count"] or 0
        
        print(f"Current 30d performance: ${current_pnl:.2f} ({current_count} trades)")
        print(f"Target 30d performance: ${target_pnl:.2f}")
        
        # Delete all trades from the last 30 days
        cursor.execute("DELETE FROM trades WHERE entry_time >= ?", (cutoff_date,))
        deleted_count = cursor.rowcount
        print(f"Deleted {deleted_count} trades from the last 30 days")
        
        # Insert a single trade with the target PNL
        # Use a date 15 days ago (within the 30-day window)
        trade_date = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        
        cursor.execute("""
            INSERT INTO trades (
                trade_id, signal_id, signal_type, direction,
                entry_price, exit_price, stop_loss, take_profit,
                pnl, is_win, exit_reason,
                entry_time, exit_time, hold_duration_minutes,
                regime, context_key, volatility_percentile, volume_percentile,
                features_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_id,
            f"signal_{trade_id}",
            "reset",
            "long" if target_pnl >= 0 else "short",
            100.0,  # entry_price (arbitrary)
            100.0 + (target_pnl / 10.0),  # exit_price (arbitrary, adjusted for PNL)
            None,  # stop_loss
            None,  # take_profit
            target_pnl,
            1 if target_pnl >= 0 else 0,  # is_win
            "Reset 30d performance",
            trade_date,  # entry_time
            trade_date,  # exit_time
            0.0,  # hold_duration_minutes
            None,  # regime
            None,  # context_key
            None,  # volatility_percentile
            None,  # volume_percentile
            None,  # features_json
            now  # created_at
        ))
        
        conn.commit()
        
        # Verify the new 30d performance
        cursor.execute(
            "SELECT SUM(pnl) as total_pnl, COUNT(*) as count FROM trades WHERE entry_time >= ?",
            (cutoff_date,)
        )
        row = cursor.fetchone()
        new_pnl = row["total_pnl"] or 0.0
        new_count = row["count"] or 0
        
        print(f"New 30d performance: ${new_pnl:.2f} ({new_count} trades)")
        
        if abs(new_pnl - target_pnl) < 0.01:
            print("✅ Successfully reset 30d performance!")
        else:
            print(f"⚠️  Warning: Expected ${target_pnl:.2f}, got ${new_pnl:.2f}")
            
    finally:
        conn.close()

def main():
    if len(sys.argv) < 2:
        print("Usage: python reset_30d_performance.py <target_pnl> [market]")
        print("Example: python reset_30d_performance.py 41.14 NQ")
        sys.exit(1)
    
    target_pnl = float(sys.argv[1])
    market = sys.argv[2] if len(sys.argv) > 2 else "NQ"
    
    # Find the trades.db file
    repo_root = Path(__file__).resolve().parents[1]
    db_path = repo_root / "data" / "agent_state" / market / "trades.db"
    
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)
    
    print(f"Database: {db_path}")
    reset_30d_performance(db_path, target_pnl)

if __name__ == "__main__":
    main()
