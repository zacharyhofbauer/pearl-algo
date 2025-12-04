"""
Account Store - Account State Snapshots.

Stores periodic snapshots of account state for historical analysis.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pearlalgo.core.portfolio import Portfolio
from pearlalgo.brokers.interfaces import AccountSummary

logger = logging.getLogger(__name__)


class AccountStore:
    """
    Account state snapshot storage using SQLite.

    Stores periodic snapshots for:
    - Historical equity curves
    - Performance analysis
    - Risk metrics over time
    """

    def __init__(self, db_path: str | Path = "data/trade_ledger.db"):
        """
        Initialize account store.

        Args:
            db_path: Path to SQLite database (can share with trade ledger)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Schema is in schema.sql - just ensure tables exist
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure account snapshot tables exist."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            # Create table if it doesn't exist (schema.sql handles this, but ensure here too)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    buying_power REAL NOT NULL,
                    margin_used REAL NOT NULL DEFAULT 0.0,
                    margin_available REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL DEFAULT 0.0,
                    realized_pnl REAL NOT NULL DEFAULT 0.0,
                    positions TEXT,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_account_snapshots_timestamp 
                ON account_snapshots(timestamp)
            """)

            conn.commit()
        except Exception as e:
            logger.error(f"Error ensuring account_snapshots table: {e}")
            conn.rollback()
        finally:
            conn.close()

    def save_snapshot(
        self,
        account_summary: AccountSummary,
        positions: Optional[Dict[str, Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> int:
        """
        Save an account snapshot.

        Args:
            account_summary: AccountSummary object
            positions: Dict of position data (optional)
            metadata: Additional metadata (optional)

        Returns:
            Snapshot ID
        """
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute(
                """
                INSERT INTO account_snapshots (
                    timestamp, equity, cash, buying_power, margin_used,
                    margin_available, unrealized_pnl, realized_pnl,
                    positions, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_summary.timestamp.isoformat(),
                    account_summary.equity,
                    account_summary.cash,
                    account_summary.buying_power,
                    account_summary.margin_used,
                    account_summary.margin_available,
                    account_summary.unrealized_pnl,
                    account_summary.realized_pnl,
                    json.dumps(positions or {}),
                    json.dumps(metadata or {}),
                ),
            )
            snapshot_id = cursor.lastrowid
            conn.commit()
            logger.debug(f"Saved account snapshot: {snapshot_id}")
            return snapshot_id
        except Exception as e:
            logger.error(f"Error saving account snapshot: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_snapshots(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Retrieve account snapshots.

        Args:
            since: Start timestamp (optional)
            until: End timestamp (optional)
            limit: Maximum number of results (optional)

        Returns:
            List of snapshot records
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        try:
            query = "SELECT * FROM account_snapshots WHERE 1=1"
            params = []

            if since:
                query += " AND timestamp >= ?"
                params.append(since.isoformat())

            if until:
                query += " AND timestamp <= ?"
                params.append(until.isoformat())

            query += " ORDER BY timestamp DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            snapshots = []
            for row in rows:
                snapshot_dict = dict(row)
                # Parse JSON fields
                for field in ["positions", "metadata"]:
                    if snapshot_dict.get(field):
                        try:
                            snapshot_dict[field] = json.loads(snapshot_dict[field])
                        except json.JSONDecodeError:
                            snapshot_dict[field] = {}

                snapshots.append(snapshot_dict)

            return snapshots

        finally:
            conn.close()

    def get_equity_curve(
        self, since: Optional[datetime] = None
    ) -> List[tuple[datetime, float]]:
        """
        Get equity curve data.

        Args:
            since: Start timestamp (optional)

        Returns:
            List of (timestamp, equity) tuples
        """
        snapshots = self.get_snapshots(since=since)

        equity_curve = [
            (datetime.fromisoformat(s["timestamp"]), s["equity"])
            for s in snapshots
        ]

        # Sort by timestamp (ascending)
        equity_curve.sort(key=lambda x: x[0])
        return equity_curve

    def get_latest_snapshot(self) -> Optional[Dict]:
        """Get the most recent account snapshot."""
        snapshots = self.get_snapshots(limit=1)
        return snapshots[0] if snapshots else None




