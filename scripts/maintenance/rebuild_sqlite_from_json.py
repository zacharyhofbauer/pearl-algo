#!/usr/bin/env python3
"""
Rebuild SQLite Database from JSON Sources

This script rebuilds the SQLite database (trades.db) from the authoritative
JSON sources (signals.jsonl). Use this when:
- SQLite database is corrupted
- SQLite is out of sync with JSON
- After a crash or unclean shutdown

Usage:
    python scripts/maintenance/rebuild_sqlite_from_json.py --market NQ
    python scripts/maintenance/rebuild_sqlite_from_json.py --market NQ --dry-run
    python scripts/maintenance/rebuild_sqlite_from_json.py --market NQ --backup

See docs/architecture/state_management.md for more details on the dual-write
state management pattern.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_state_dir(market: str) -> Path:
    """Get the state directory for a market."""
    # Try to import from pearlalgo if available
    try:
        from pearlalgo.utils.paths import ensure_state_dir
        return ensure_state_dir(market)
    except ImportError:
        # Fallback: use default path
        base = Path(__file__).resolve().parent.parent.parent / "data" / "agent_state"
        state_dir = base / market
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir


def backup_database(db_path: Path) -> Path | None:
    """Create a backup of the existing database."""
    if not db_path.exists():
        return None
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_suffix(f".backup_{timestamp}.db")
    shutil.copy2(db_path, backup_path)
    return backup_path


def parse_signals_jsonl(signals_file: Path) -> list[dict]:
    """Parse all records from signals.jsonl."""
    records = []
    if not signals_file.exists():
        return records
    
    with open(signals_file, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError as e:
                print(f"  Warning: Invalid JSON on line {line_num}: {e}")
    
    return records


def extract_trades(records: list[dict]) -> list[dict]:
    """Extract completed trades from signal records."""
    trades = []
    
    for record in records:
        status = record.get("status", "")
        if status != "exited":
            continue
        
        signal = record.get("signal", {})
        if not isinstance(signal, dict):
            continue
        
        # Extract trade data
        pnl = record.get("pnl") or signal.get("pnl") or signal.get("virtual_pnl", 0.0)
        
        try:
            pnl = float(pnl)
        except (TypeError, ValueError):
            pnl = 0.0
        
        # Skip records without exit info
        exit_time = record.get("exit_time") or record.get("timestamp")
        if not exit_time:
            continue
        
        entry_time = signal.get("timestamp") or record.get("entry_time") or record.get("timestamp")
        
        trade = {
            "trade_id": f"trade_{record.get('signal_id', '')}",
            "signal_id": record.get("signal_id", ""),
            "signal_type": signal.get("type", "unknown"),
            "direction": signal.get("direction", "unknown"),
            "entry_price": float(signal.get("entry_price", 0) or 0),
            "exit_price": float(record.get("exit_price") or signal.get("exit_price", 0) or 0),
            "stop_loss": float(signal.get("stop_loss", 0) or 0),
            "take_profit": float(signal.get("take_profit", 0) or 0),
            "pnl": pnl,
            "is_win": pnl > 0,
            "exit_reason": record.get("exit_reason") or signal.get("exit_reason", ""),
            "entry_time": str(entry_time),
            "exit_time": str(exit_time),
            "hold_duration_minutes": None,
            "regime": signal.get("regime"),
            "context_key": signal.get("context_key"),
            "volatility_percentile": signal.get("volatility_percentile"),
            "volume_percentile": signal.get("volume_percentile"),
            "features": signal.get("features", {}),
        }
        
        # Calculate hold duration if possible
        try:
            from dateutil import parser as date_parser
            entry_dt = date_parser.parse(str(entry_time))
            exit_dt = date_parser.parse(str(exit_time))
            trade["hold_duration_minutes"] = (exit_dt - entry_dt).total_seconds() / 60
        except Exception:
            pass
        
        trades.append(trade)
    
    return trades


def extract_signal_events(records: list[dict]) -> list[dict]:
    """Extract signal events from all records."""
    events = []
    
    for record in records:
        signal_id = record.get("signal_id", "")
        if not signal_id:
            continue
        
        event = {
            "signal_id": signal_id,
            "status": record.get("status", "generated"),
            "timestamp": record.get("timestamp", ""),
            "payload": record,
        }
        events.append(event)
    
    return events


def rebuild_database(
    state_dir: Path,
    dry_run: bool = False,
    create_backup: bool = False,
) -> dict:
    """Rebuild the SQLite database from JSON sources."""
    signals_file = state_dir / "signals.jsonl"
    db_path = state_dir / "trades.db"
    
    stats = {
        "signals_file": str(signals_file),
        "db_path": str(db_path),
        "total_records": 0,
        "trades_found": 0,
        "signal_events_found": 0,
        "backup_path": None,
        "success": False,
    }
    
    # Check if signals file exists
    if not signals_file.exists():
        print(f"Error: signals.jsonl not found at {signals_file}")
        return stats
    
    # Parse signals
    print(f"Reading {signals_file}...")
    records = parse_signals_jsonl(signals_file)
    stats["total_records"] = len(records)
    print(f"  Found {len(records)} records")
    
    # Extract trades and events
    trades = extract_trades(records)
    stats["trades_found"] = len(trades)
    print(f"  Found {len(trades)} completed trades")
    
    events = extract_signal_events(records)
    stats["signal_events_found"] = len(events)
    print(f"  Found {len(events)} signal events")
    
    if dry_run:
        print("\n[DRY RUN] Would rebuild database with:")
        print(f"  - {len(trades)} trades")
        print(f"  - {len(events)} signal events")
        stats["success"] = True
        return stats
    
    # Create backup if requested
    if create_backup and db_path.exists():
        backup_path = backup_database(db_path)
        if backup_path:
            stats["backup_path"] = str(backup_path)
            print(f"  Created backup: {backup_path}")
    
    # Delete existing database
    if db_path.exists():
        print(f"  Removing existing database: {db_path}")
        db_path.unlink()
    
    # Import TradeDatabase (creates fresh schema)
    try:
        from pearlalgo.storage.trade_database import TradeDatabase
    except ImportError:
        print("Error: Could not import TradeDatabase. Make sure pearlalgo is installed.")
        return stats
    
    print(f"  Creating new database: {db_path}")
    db = TradeDatabase(db_path=db_path, cache_connection=True)
    
    # Insert trades
    print(f"  Inserting {len(trades)} trades...")
    for i, trade in enumerate(trades, 1):
        try:
            db.add_trade(
                trade_id=trade["trade_id"],
                signal_id=trade["signal_id"],
                signal_type=trade["signal_type"],
                direction=trade["direction"],
                entry_price=trade["entry_price"],
                exit_price=trade["exit_price"],
                pnl=trade["pnl"],
                is_win=trade["is_win"],
                entry_time=trade["entry_time"],
                exit_time=trade["exit_time"],
                stop_loss=trade.get("stop_loss"),
                take_profit=trade.get("take_profit"),
                exit_reason=trade.get("exit_reason"),
                hold_duration_minutes=trade.get("hold_duration_minutes"),
                regime=trade.get("regime"),
                context_key=trade.get("context_key"),
                volatility_percentile=trade.get("volatility_percentile"),
                volume_percentile=trade.get("volume_percentile"),
                features=trade.get("features"),
            )
        except Exception as e:
            print(f"    Warning: Failed to insert trade {trade['trade_id']}: {e}")
        
        if i % 100 == 0:
            print(f"    Inserted {i}/{len(trades)} trades...")
    
    # Insert signal events
    print(f"  Inserting {len(events)} signal events...")
    for i, event in enumerate(events, 1):
        try:
            db.add_signal_event(
                signal_id=event["signal_id"],
                status=event["status"],
                timestamp=event["timestamp"],
                payload=event["payload"],
            )
        except Exception as e:
            print(f"    Warning: Failed to insert event {event['signal_id']}: {e}")
        
        if i % 500 == 0:
            print(f"    Inserted {i}/{len(events)} events...")
    
    # Close database
    db.close()
    
    # Verify
    print("\nVerifying rebuilt database...")
    db = TradeDatabase(db_path=db_path)
    summary = db.get_summary()
    db.close()
    
    print(f"  Total trades: {summary.get('total_trades', 0)}")
    print(f"  Win rate: {summary.get('win_rate', 0):.1%}")
    print(f"  Total P&L: ${summary.get('total_pnl', 0):.2f}")
    
    stats["success"] = True
    print("\nDatabase rebuild complete!")
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild SQLite database from JSON sources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--market",
        type=str,
        default="NQ",
        help="Market symbol (default: NQ)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create backup of existing database before rebuild",
    )
    parser.add_argument(
        "--state-dir",
        type=str,
        help="Override state directory path",
    )
    
    args = parser.parse_args()
    
    # Get state directory
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        state_dir = get_state_dir(args.market)
    
    print(f"Rebuilding SQLite database for market: {args.market}")
    print(f"State directory: {state_dir}")
    print()
    
    stats = rebuild_database(
        state_dir=state_dir,
        dry_run=args.dry_run,
        create_backup=args.backup,
    )
    
    if not stats["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
