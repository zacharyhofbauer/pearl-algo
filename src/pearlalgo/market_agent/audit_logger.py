"""
Audit Event Logger

Persistent audit trail backed by SQLite. Captures all auditable events:
- Signal generation and rejection decisions
- Trade entries and exits
- System events (restarts, circuit breaker trips, connection drops)
- Equity snapshots (daily)
- Reconciliation results

Architecture:
- Non-blocking writes via background thread (never slows the scan loop)
- Shared database file (trades.db) with dedicated audit_events table
- Composite index for fast time-range + account + event-type queries
- Automatic retention (configurable, default 90 days; equity snapshots 1 year)
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from pearlalgo.utils.logger import logger


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

class AuditEventType:
    """Known audit event types."""

    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_REJECTED = "signal_rejected"
    TRADE_ENTERED = "trade_entered"
    TRADE_EXITED = "trade_exited"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    CIRCUIT_BREAKER_TRIP = "circuit_breaker_trip"
    CONNECTION_DROP = "connection_drop"
    CONNECTION_RECOVER = "connection_recover"
    ERROR_THRESHOLD = "error_threshold"
    EQUITY_SNAPSHOT = "equity_snapshot"
    RECONCILIATION = "reconciliation"


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------

class AuditLogger:
    """
    Non-blocking audit event logger backed by SQLite.

    All ``log_*`` methods enqueue events for background writing.  The caller
    never blocks on I/O.  If the queue is full or the worker is down, events
    are dropped with a warning -- audit logging must *never* crash the
    trading loop.
    """

    def __init__(
        self,
        db_path: Path,
        account: str = "unknown",
        *,
        max_queue_size: int = 5000,
        retention_days: int = 90,
        snapshot_retention_days: int = 365,
    ) -> None:
        self.db_path = db_path
        self.account = account
        self._retention_days = retention_days
        self._snapshot_retention_days = snapshot_retention_days

        # Background writer
        self._queue: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue(
            maxsize=max_queue_size,
        )
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._running = False

        # Metrics (thread-safe via GIL for simple increments)
        self._total_writes = 0
        self._total_drops = 0
        self._total_errors = 0

        # Schema initialisation (runs on the calling thread -- fast, once)
        self._init_schema()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background writer thread."""
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="AuditLoggerWorker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("AuditLogger worker started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background writer, flushing pending events."""
        if not self._running:
            return
        logger.info(
            f"Stopping AuditLogger (pending={self._queue.qsize()}, "
            f"writes={self._total_writes}, drops={self._total_drops}, "
            f"errors={self._total_errors})"
        )
        self._shutdown_event.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logger.warning("AuditLogger worker did not stop within timeout")
        self._running = False

    # ------------------------------------------------------------------
    # Typed event methods (public API)
    # ------------------------------------------------------------------

    def log_signal_generated(self, signal_data: Dict[str, Any]) -> None:
        """Log a signal generation event."""
        self._enqueue(
            AuditEventType.SIGNAL_GENERATED,
            {
                "signal_id": str(signal_data.get("signal_id", "")),
                "direction": str(signal_data.get("direction", "")),
                "symbol": str(signal_data.get("symbol", "")),
                "entry_price": float(signal_data.get("entry_price", 0)),
                "stop_loss": float(signal_data.get("stop_loss", 0)),
                "take_profit": float(signal_data.get("take_profit", 0)),
                "confidence": float(signal_data.get("confidence", 0)),
                "trade_type": str(signal_data.get("trade_type", "")),
            },
            source="signal_handler",
        )

    def log_signal_rejected(
        self,
        signal_id: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a signal rejection with the reason and details."""
        self._enqueue(
            AuditEventType.SIGNAL_REJECTED,
            {
                "signal_id": str(signal_id),
                "reason": str(reason),
                "details": details or {},
            },
            source="signal_handler",
        )

    def log_trade_entered(
        self,
        signal_id: str,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a trade entry event."""
        result = execution_result or {}
        self._enqueue(
            AuditEventType.TRADE_ENTERED,
            {
                "signal_id": str(signal_id),
                "execution_status": str(result.get("execution_status", "virtual")),
                "order_id": str(result.get("order_id", "")),
                "entry_price": float(result.get("entry_price", 0)),
                "direction": str(result.get("direction", "")),
                "position_size": int(result.get("position_size", 0)),
            },
            source="execution",
        )

    def log_trade_exited(
        self,
        signal_id: str,
        exit_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a trade exit event."""
        data = exit_data or {}
        self._enqueue(
            AuditEventType.TRADE_EXITED,
            {
                "signal_id": str(signal_id),
                "exit_price": float(data.get("exit_price", 0)),
                "exit_reason": str(data.get("exit_reason", "")),
                "pnl": float(data.get("pnl", 0)),
                "is_win": bool(data.get("is_win", False)),
                "hold_duration_minutes": float(data.get("hold_duration_minutes", 0)),
                "direction": str(data.get("direction", "")),
            },
            source="virtual_trade_manager",
        )

    def log_system_event(
        self,
        event_type: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a system-level event (restarts, errors, circuit breakers, connections)."""
        self._enqueue(
            event_type,
            details or {},
            source="system",
        )

    def log_equity_snapshot(
        self,
        account: str,
        equity: float,
        cash_balance: float = 0.0,
        open_pnl: float = 0.0,
        realized_pnl: float = 0.0,
    ) -> None:
        """Log a daily equity snapshot."""
        self._enqueue(
            AuditEventType.EQUITY_SNAPSHOT,
            {
                "account": str(account),
                "equity": float(equity),
                "cash_balance": float(cash_balance),
                "open_pnl": float(open_pnl),
                "realized_pnl": float(realized_pnl),
            },
            source="scheduled_task",
        )

    def log_reconciliation(
        self,
        account: str,
        agent_pnl: float,
        broker_pnl: float,
        drift: float,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a reconciliation result."""
        self._enqueue(
            AuditEventType.RECONCILIATION,
            {
                "account": str(account),
                "agent_pnl": float(agent_pnl),
                "broker_pnl": float(broker_pnl),
                "drift": float(drift),
                "drift_pct": round(
                    abs(drift / broker_pnl) * 100 if broker_pnl else 0.0, 2
                ),
                "status": "within_tolerance" if abs(drift) < 5.0 else "drift_detected",
                "details": details or {},
            },
            source="reconciliation",
        )

    # ------------------------------------------------------------------
    # Query helpers (synchronous -- intended for API layer / threads)
    # ------------------------------------------------------------------

    def query_events(
        self,
        *,
        event_type: Optional[str] = None,
        account: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query audit events with optional filters.

        Returns a list of event dicts ordered by timestamp descending.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if account:
            clauses.append("account = ?")
            params.append(account)
        if start_date:
            clauses.append("timestamp >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("timestamp <= ?")
            params.append(end_date)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT id, timestamp, event_type, account, data_json, source "
            f"FROM audit_events{where} "
            f"ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        try:
            with self._get_connection() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"AuditLogger.query_events error: {e}")
            return []

    def count_events(
        self,
        *,
        event_type: Optional[str] = None,
        account: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """Count audit events matching filters."""
        clauses: list[str] = []
        params: list[Any] = []

        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if account:
            clauses.append("account = ?")
            params.append(account)
        if start_date:
            clauses.append("timestamp >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("timestamp <= ?")
            params.append(end_date)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT COUNT(*) FROM audit_events{where}"

        try:
            with self._get_connection() as conn:
                row = conn.execute(sql, params).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.warning(f"AuditLogger.count_events error: {e}")
            return 0

    def query_equity_history(
        self,
        *,
        account: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query equity snapshot history for charting."""
        return self.query_events(
            event_type=AuditEventType.EQUITY_SNAPSHOT,
            account=account,
            start_date=start_date,
            end_date=end_date,
            limit=10000,  # equity snapshots are small
            offset=0,
        )

    def query_reconciliation(
        self,
        *,
        account: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query reconciliation results."""
        return self.query_events(
            event_type=AuditEventType.RECONCILIATION,
            account=account,
            start_date=start_date,
            end_date=end_date,
            limit=1000,
            offset=0,
        )

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def run_retention(self) -> Dict[str, int]:
        """Delete events older than retention period.

        - General events: ``retention_days`` (default 90)
        - Equity snapshots: ``snapshot_retention_days`` (default 365)

        Returns counts of deleted rows per category.
        """
        now = datetime.now(timezone.utc)
        general_cutoff = (now - timedelta(days=self._retention_days)).isoformat()
        snapshot_cutoff = (now - timedelta(days=self._snapshot_retention_days)).isoformat()

        deleted_general = 0
        deleted_snapshots = 0

        try:
            with self._get_connection() as conn:
                # Delete old general events (everything except equity snapshots)
                cursor = conn.execute(
                    "DELETE FROM audit_events WHERE event_type != ? AND timestamp < ?",
                    (AuditEventType.EQUITY_SNAPSHOT, general_cutoff),
                )
                deleted_general = cursor.rowcount

                # Delete old equity snapshots (longer retention)
                cursor = conn.execute(
                    "DELETE FROM audit_events WHERE event_type = ? AND timestamp < ?",
                    (AuditEventType.EQUITY_SNAPSHOT, snapshot_cutoff),
                )
                deleted_snapshots = cursor.rowcount

                conn.commit()
        except Exception as e:
            logger.warning(f"AuditLogger.run_retention error: {e}")

        if deleted_general > 0 or deleted_snapshots > 0:
            logger.info(
                f"Audit retention: deleted {deleted_general} general events "
                f"(>{self._retention_days}d), {deleted_snapshots} equity snapshots "
                f"(>{self._snapshot_retention_days}d)"
            )

        return {"deleted_general": deleted_general, "deleted_snapshots": deleted_snapshots}

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, Any]:
        """Return observability metrics."""
        return {
            "queue_depth": self._queue.qsize(),
            "total_writes": self._total_writes,
            "total_drops": self._total_drops,
            "total_errors": self._total_errors,
            "worker_running": self._running
            and self._worker_thread is not None
            and self._worker_thread.is_alive(),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _enqueue(
        self,
        event_type: str,
        data: Dict[str, Any],
        source: str = "",
    ) -> None:
        """Enqueue an audit event for background writing.

        Never raises -- audit logging must not crash the trading loop.
        """
        try:
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "account": self.account,
                "data_json": json.dumps(data, default=str),
                "source": source,
            }
            self._queue.put_nowait(event)
        except queue.Full:
            self._total_drops += 1
            logger.warning(
                f"AuditLogger queue full -- dropping {event_type} event "
                f"(total_drops={self._total_drops})"
            )
        except Exception as e:
            self._total_drops += 1
            logger.warning(f"AuditLogger enqueue error: {e}")

    def _worker_loop(self) -> None:
        """Background thread: drain queue and write to SQLite."""
        logger.debug("AuditLogger worker loop started")
        conn: Optional[sqlite3.Connection] = None

        try:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")

            while not self._shutdown_event.is_set():
                try:
                    event = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if event is None:
                    # Poison pill
                    break

                try:
                    conn.execute(
                        "INSERT INTO audit_events "
                        "(timestamp, event_type, account, data_json, source) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            event["timestamp"],
                            event["event_type"],
                            event["account"],
                            event["data_json"],
                            event["source"],
                        ),
                    )
                    conn.commit()
                    self._total_writes += 1
                except Exception as e:
                    self._total_errors += 1
                    logger.debug(f"AuditLogger write error (non-fatal): {e}")

            # Flush remaining on shutdown
            flushed = 0
            while not self._queue.empty():
                try:
                    event = self._queue.get_nowait()
                    if event is None:
                        continue
                    conn.execute(
                        "INSERT INTO audit_events "
                        "(timestamp, event_type, account, data_json, source) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            event["timestamp"],
                            event["event_type"],
                            event["account"],
                            event["data_json"],
                            event["source"],
                        ),
                    )
                    flushed += 1
                except queue.Empty:
                    break
                except Exception as e:
                    self._total_errors += 1
                    logger.debug(f"AuditLogger flush error: {e}")

            if flushed > 0:
                conn.commit()
                self._total_writes += flushed
                logger.info(f"AuditLogger flushed {flushed} events on shutdown")

        except Exception as e:
            logger.error(f"AuditLogger worker fatal error: {e}", exc_info=True)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            logger.debug("AuditLogger worker loop exited")

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a read-only connection for queries (separate from the writer)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Create the audit_events table and indexes if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        account TEXT NOT NULL DEFAULT 'unknown',
                        data_json TEXT,
                        source TEXT DEFAULT ''
                    )
                """)

                # Composite index for the three most common query patterns:
                # time-range, account filter, event-type filter
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_ts_account_type "
                    "ON audit_events(timestamp, account, event_type)"
                )
                # Additional index for event_type-first queries (e.g. all equity snapshots)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_type_ts "
                    "ON audit_events(event_type, timestamp)"
                )

                conn.commit()
            finally:
                conn.close()

            logger.info(f"AuditLogger schema initialized: {self.db_path}")
        except Exception as e:
            logger.error(f"AuditLogger schema init error: {e}", exc_info=True)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to a plain dict, parsing data_json."""
        d = dict(row)
        raw_json = d.get("data_json")
        if raw_json:
            try:
                d["data"] = json.loads(raw_json)
            except (json.JSONDecodeError, TypeError):
                d["data"] = {}
        else:
            d["data"] = {}
        return d
