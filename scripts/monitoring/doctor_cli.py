#!/usr/bin/env python3
"""
Doctor CLI - 24h rollup for local/ops use.

CLI wrapper for the doctor report business logic.
Business logic is in: src/pearlalgo/analytics/doctor_report.py

Mirrors the Telegram `/doctor` view:
- signal event counts (generated/entered/exited/expired)
- trade exit summary (WR, P&L, avg hold)
- cycle diagnostics aggregates (rejections, stop caps, etc.)
- stop distance + position size distributions (from generated signals)

Usage:
  python scripts/monitoring/doctor_cli.py
  python scripts/monitoring/doctor_cli.py --hours 6
  python scripts/monitoring/doctor_cli.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.analytics.doctor_report import build_doctor_rollup, format_doctor_rollup_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Doctor rollup (local/ops)")
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours (default: 24)")
    parser.add_argument("--db-path", type=str, default="", help="Override SQLite db path")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    # Load config to locate DB + ensure sqlite is enabled
    from pearlalgo.config.config_loader import load_service_config
    from pearlalgo.learning.trade_database import TradeDatabase

    cfg = load_service_config(validate=False) or {}
    storage_cfg = cfg.get("storage", {}) or {}
    sqlite_enabled = bool(storage_cfg.get("sqlite_enabled", False))
    if not sqlite_enabled and not args.db_path:
        print("SQLite storage disabled. Enable `storage.sqlite_enabled: true` in config/config.yaml.")
        return 2

    db_path = args.db_path or str(storage_cfg.get("db_path") or "data/agent_state/NQ/trades.db")
    db = TradeDatabase(Path(db_path))

    rollup = build_doctor_rollup(db, hours=args.hours)
    if args.json:
        print(json.dumps(rollup, indent=2, ensure_ascii=False))
    else:
        print(format_doctor_rollup_text(rollup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
