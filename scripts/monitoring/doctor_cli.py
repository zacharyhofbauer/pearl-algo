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
import os
import sqlite3
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.analytics.doctor_report import build_doctor_rollup, format_doctor_rollup_text


class SQLiteDoctorDB:
    """Minimal SQLite adapter for doctor_report.py."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, table_name: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
        return row is not None

    @staticmethod
    def _loads_json(raw: str | None) -> dict:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def missing_tables(self) -> list[str]:
        required = ["signal_events", "cycle_diagnostics", "trades"]
        return [name for name in required if not self._table_exists(name)]

    def get_signal_event_counts(self, *, from_time: str) -> dict:
        if not self._table_exists("signal_events"):
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM signal_events
                WHERE timestamp >= ?
                GROUP BY status
                """,
                (from_time,),
            ).fetchall()
        return {str(row["status"]): int(row["count"] or 0) for row in rows}

    def get_cycle_diagnostics_aggregate(self, *, from_time: str) -> dict:
        if not self._table_exists("cycle_diagnostics"):
            return {}
        columns = [
            "duplicates_filtered",
            "stop_cap_applied",
            "session_scaling_applied",
            "rejected_market_hours",
            "rejected_confidence",
            "rejected_risk_reward",
            "rejected_quality_scorer",
            "rejected_order_book",
            "rejected_invalid_prices",
            "rejected_regime_filter",
            "rejected_ml_filter",
            "adaptive_sizing_applied",
        ]
        select_sql = ", ".join(
            [f"COALESCE(SUM({column}), 0) AS {column}" for column in columns]
        )
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {select_sql} FROM cycle_diagnostics WHERE timestamp >= ?",
                (from_time,),
            ).fetchone()
        return {column: int((row[column] or 0) if row else 0) for column in columns}

    def get_quiet_reason_counts(self, *, from_time: str, limit: int = 5) -> dict:
        if not self._table_exists("cycle_diagnostics"):
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT quiet_reason, COUNT(*) AS count
                FROM cycle_diagnostics
                WHERE timestamp >= ?
                  AND quiet_reason IS NOT NULL
                  AND quiet_reason != ''
                GROUP BY quiet_reason
                ORDER BY count DESC, quiet_reason ASC
                LIMIT ?
                """,
                (from_time, int(limit)),
            ).fetchall()
        return {str(row["quiet_reason"]): int(row["count"] or 0) for row in rows}

    def get_trade_summary(self, *, from_exit_time: str) -> dict:
        if not self._table_exists("trades"):
            return {"total": 0}
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN is_win THEN 1 ELSE 0 END), 0) AS wins,
                    COALESCE(SUM(pnl), 0.0) AS total_pnl,
                    AVG(hold_duration_minutes) AS avg_hold_minutes
                FROM trades
                WHERE exit_time >= ?
                """,
                (from_exit_time,),
            ).fetchone()
        total = int(row["total"] or 0) if row else 0
        wins = int(row["wins"] or 0) if row else 0
        return {
            "total": total,
            "win_rate": float(wins / total) if total else 0.0,
            "total_pnl": float(row["total_pnl"] or 0.0) if row else 0.0,
            "avg_hold_minutes": float(row["avg_hold_minutes"]) if row and row["avg_hold_minutes"] is not None else None,
        }

    def get_signal_events(self, *, status: str, from_time: str, limit: int = 5000) -> list[dict]:
        if not self._table_exists("signal_events"):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signal_id, status, timestamp, payload_json
                FROM signal_events
                WHERE status = ?
                  AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (status, from_time, int(limit)),
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "signal_id": row["signal_id"],
                    "status": row["status"],
                    "timestamp": row["timestamp"],
                    "payload": self._loads_json(row["payload_json"]),
                }
            )
        return result

    def get_recent_trades_by_exit(self, *, limit: int = 200, from_exit_time: str) -> list[dict]:
        if not self._table_exists("trades"):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM trades
                WHERE exit_time >= ?
                ORDER BY exit_time DESC
                LIMIT ?
                """,
                (from_exit_time, int(limit)),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["features"] = self._loads_json(item.get("features_json"))
            item["is_win"] = bool(item.get("is_win", False))
            result.append(item)
        return result


def _default_db_path() -> Path:
    state_dir = os.getenv("PEARLALGO_STATE_DIR")
    if state_dir:
        return Path(state_dir) / "trades.db"
    return PROJECT_ROOT / "data" / "agent_state" / "MNQ" / "trades.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="Doctor rollup (local/ops)")
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours (default: 24)")
    parser.add_argument("--db-path", type=str, default="", help="Override SQLite db path")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    if not db_path.exists():
        print(f"Doctor rollup unavailable: SQLite DB not found at {db_path}")
        return 2

    db = SQLiteDoctorDB(db_path)
    missing_tables = db.missing_tables()
    if missing_tables:
        print(
            "Doctor rollup unavailable: DB schema is incomplete at "
            f"{db_path} (missing tables: {', '.join(missing_tables)})"
        )
        return 2

    rollup = build_doctor_rollup(db, hours=args.hours)
    if args.json:
        print(json.dumps(rollup, indent=2, ensure_ascii=False))
    else:
        print(format_doctor_rollup_text(rollup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
