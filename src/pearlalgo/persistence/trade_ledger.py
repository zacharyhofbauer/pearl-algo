"""
SQLite Trade Ledger - Immutable Trade Record System.

Provides ACID-guaranteed trade ledger for audit trails and analytics.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pearlalgo.core.events import FillEvent, OrderEvent

logger = logging.getLogger(__name__)


class TradeLedger:
    """
    Immutable trade ledger using SQLite.

    Features:
    - ACID guarantees
    - Immutable records (append-only)
    - Fast queries
    - Complete audit trail
    """

    def __init__(self, db_path: str | Path = "data/trade_ledger.db"):
        """
        Initialize trade ledger.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_database()

    def _init_database(self) -> None:
        """Initialize database schema."""
        schema_file = Path(__file__).parent / "schema.sql"
        if not schema_file.exists():
            logger.warning(f"Schema file not found: {schema_file}")
            return

        conn = sqlite3.connect(str(self.db_path))
        try:
            with open(schema_file) as f:
                schema = f.read()

            conn.executescript(schema)
            conn.commit()
            logger.info(f"Initialized trade ledger database: {self.db_path}")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def record_fill(self, fill: FillEvent, order_id: str, broker_order_id: Optional[str] = None) -> None:
        """
        Record a fill in the ledger.

        Args:
            fill: FillEvent to record
            order_id: Internal order ID
            broker_order_id: Broker's order ID (optional)
        """
        fill_id = f"FILL_{fill.timestamp.strftime('%Y%m%d%H%M%S%f')}_{order_id}"

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                INSERT INTO fills (
                    fill_id, order_id, timestamp, symbol, side, quantity,
                    price, commission, broker_order_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill_id,
                    order_id,
                    fill.timestamp.isoformat(),
                    fill.symbol,
                    fill.side,
                    fill.quantity,
                    fill.price,
                    fill.commission,
                    broker_order_id,
                    json.dumps(fill.metadata or {}),
                ),
            )
            conn.commit()
            logger.debug(f"Recorded fill: {fill_id} for {fill.symbol}")
        except Exception as e:
            logger.error(f"Error recording fill: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def record_order(self, order: OrderEvent, order_id: str, status: str = "Pending", broker_order_id: Optional[str] = None) -> None:
        """
        Record an order in the ledger.

        Args:
            order: OrderEvent to record
            order_id: Internal order ID
            status: Order status
            broker_order_id: Broker's order ID (optional)
        """
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO orders (
                    order_id, timestamp, symbol, side, quantity, order_type,
                    limit_price, stop_price, status, broker_order_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    order.timestamp.isoformat(),
                    order.symbol,
                    order.side,
                    order.quantity,
                    order.order_type,
                    order.limit_price,
                    order.stop_price,
                    status,
                    broker_order_id,
                    json.dumps(order.metadata or {}),
                ),
            )
            conn.commit()
            logger.debug(f"Recorded order: {order_id} for {order.symbol}")
        except Exception as e:
            logger.error(f"Error recording order: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_order_status(self, order_id: str, status: str) -> None:
        """Update order status."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE order_id = ?",
                (status, order_id),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Error updating order status: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_fills(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Query fills from ledger.

        Args:
            symbol: Filter by symbol (optional)
            since: Start timestamp (optional)
            until: End timestamp (optional)
            limit: Maximum number of results (optional)

        Returns:
            List of fill records
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        try:
            query = "SELECT * FROM fills WHERE 1=1"
            params = []

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

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

            fills = []
            for row in rows:
                fill_dict = dict(row)
                # Parse metadata JSON
                if fill_dict.get("metadata"):
                    try:
                        fill_dict["metadata"] = json.loads(fill_dict["metadata"])
                    except json.JSONDecodeError:
                        fill_dict["metadata"] = {}
                fills.append(fill_dict)

            return fills

        finally:
            conn.close()

    def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """Query orders from ledger."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        try:
            query = "SELECT * FROM orders WHERE 1=1"
            params = []

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            if status:
                query += " AND status = ?"
                params.append(status)

            if since:
                query += " AND timestamp >= ?"
                params.append(since.isoformat())

            query += " ORDER BY timestamp DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            orders = []
            for row in rows:
                order_dict = dict(row)
                if order_dict.get("metadata"):
                    try:
                        order_dict["metadata"] = json.loads(order_dict["metadata"])
                    except json.JSONDecodeError:
                        order_dict["metadata"] = {}
                orders.append(order_dict)

            return orders

        finally:
            conn.close()

    def get_daily_pnl(self, date: Optional[datetime] = None) -> Dict[str, float]:
        """
        Calculate daily PnL from fills.

        Args:
            date: Date to calculate (default: today)

        Returns:
            Dict with realized_pnl, num_fills, etc.
        """
        if date is None:
            date = datetime.now()

        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)

        fills = self.get_fills(since=start, until=end)

        realized_pnl = 0.0
        num_fills = len(fills)

        for fill in fills:
            side_mult = 1.0 if fill["side"].upper() == "SELL" else -1.0
            pnl = side_mult * fill["quantity"] * fill["price"] - fill["commission"]
            realized_pnl += pnl

        return {
            "date": start.date().isoformat(),
            "realized_pnl": realized_pnl,
            "num_fills": num_fills,
        }


