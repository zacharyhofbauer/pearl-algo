"""
Persistent Trade Database

SQLite-based storage for queryable trade history.
Enables:
- Query trades by signal type, regime, time, P&L
- Analyze performance across dimensions
- Never forget any lesson

Architecture Note: Dual-Write State Management
==============================================
This module is the SECONDARY state store using SQLite. It's designed for:
- Analytics and aggregations (/doctor, performance reports)
- Long-term queryable storage with indexes
- Offline analysis tools

The PRIMARY store is JSON files managed by:
- market_agent/state_manager.py (signals.jsonl, state.json)

JSON is authoritative for recovery. SQLite may lag slightly in async mode.
See docs/architecture/state_management.md for full details.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir


@dataclass
class TradeRecord:
    """Complete trade record with all context."""
    # Core trade info
    trade_id: str
    signal_id: str
    signal_type: str
    direction: str
    
    # Prices
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    
    # Outcome
    pnl: float
    is_win: bool
    exit_reason: str
    
    # Timing
    entry_time: str
    exit_time: str
    hold_duration_minutes: float
    
    # Context
    regime: str
    context_key: str
    volatility_percentile: float
    volume_percentile: float
    
    # Features (JSON)
    features_json: str
    
    # Metadata
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trade_id": self.trade_id,
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "pnl": self.pnl,
            "is_win": self.is_win,
            "exit_reason": self.exit_reason,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "hold_duration_minutes": self.hold_duration_minutes,
            "regime": self.regime,
            "context_key": self.context_key,
            "volatility_percentile": self.volatility_percentile,
            "volume_percentile": self.volume_percentile,
            "features": json.loads(self.features_json) if self.features_json else {},
            "created_at": self.created_at,
        }


class TradeDatabase:
    """
    SQLite database for trade history.
    
    Provides:
    - Persistent storage of all trades
    - Rich querying capabilities
    - Performance analytics
    
    Performance optimizations:
    - WAL mode for better concurrent read/write performance
    - Connection caching option for background workers
    """
    
    def __init__(self, db_path: Optional[Path] = None, cache_connection: bool = False):
        """
        Initialize trade database.
        
        Args:
            db_path: Path to SQLite database file
            cache_connection: If True, keep a persistent connection (for background workers)
        """
        self.db_path = db_path or (ensure_state_dir(None) / "trades.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._cache_connection = cache_connection
        self._cached_conn: Optional[sqlite3.Connection] = None
        
        self._init_schema()
        
        logger.info(f"TradeDatabase initialized: {self.db_path} (WAL mode, cache_connection={cache_connection})")
    
    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get database connection.
        
        If cache_connection is True, reuses a single connection (more efficient
        for background workers). Otherwise, creates a new connection per operation
        (safer for multi-threaded access from different contexts).

        THREAD SAFETY: When cache_connection=True, the cached connection is NOT
        thread-safe.  Only use cached mode from a single thread (e.g. the
        dedicated async_sqlite_queue worker thread).  Multi-threaded callers
        should use the default cache_connection=False mode.
        """
        if self._cache_connection:
            # Use cached connection (for background workers)
            if self._cached_conn is None:
                self._cached_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                self._cached_conn.row_factory = sqlite3.Row
                # Optimize for write-heavy workload
                self._cached_conn.execute("PRAGMA journal_mode=WAL")
                self._cached_conn.execute("PRAGMA synchronous=NORMAL")  # Safe with WAL
                self._cached_conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            yield self._cached_conn
            # Don't close cached connection - it's reused
        else:
            # Create new connection (default behavior)
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()
    
    def close(self) -> None:
        """Close cached connection if any."""
        if self._cached_conn is not None:
            try:
                self._cached_conn.close()
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "TradeDatabase.close", e, level="warning", category="sqlite",
                )
            self._cached_conn = None
    
    def _init_schema(self) -> None:
        """Initialize database schema with WAL mode and optimized settings."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Enable WAL mode for better concurrent read/write performance
            # This is especially important when the main loop reads while the worker writes
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")  # Safe with WAL, faster than FULL
            cursor.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s for locks
            
            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    pnl REAL NOT NULL,
                    is_win INTEGER NOT NULL,
                    exit_reason TEXT,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    hold_duration_minutes REAL,
                    regime TEXT,
                    context_key TEXT,
                    volatility_percentile REAL,
                    volume_percentile REAL,
                    features_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            
            # MFE/MAE columns (safe migration for existing DBs)
            for col, col_type in [
                ("max_price", "REAL"),
                ("min_price", "REAL"),
                ("mfe_points", "REAL"),
                ("mae_points", "REAL"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists

            # Indices for common queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_signal_type ON trades(signal_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_direction ON trades(direction)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit_reason ON trades(exit_reason)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_mfe_points ON trades(mfe_points)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_mae_points ON trades(mae_points)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_hold_duration ON trades(hold_duration_minutes)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_regime ON trades(regime)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_is_win ON trades(is_win)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_pnl ON trades(pnl)")
            # Indexes for exit_time queries (used by pearl_ai/data_access.py)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_regime_exit ON trades(regime, exit_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_direction_exit ON trades(direction, exit_time)")
            
            # Composite indexes for common multi-column query patterns
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_signal_type_entry ON trades(signal_type, entry_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_regime_entry ON trades(regime, entry_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_direction_win_entry ON trades(direction, is_win, entry_time)")
            
            # Features table (for feature-level analysis)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT NOT NULL,
                    feature_name TEXT NOT NULL,
                    feature_value REAL NOT NULL,
                    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_features_trade_id ON trade_features(trade_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_features_name ON trade_features(feature_name)")
            
            # Regime history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS regime_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    regime TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    volatility_percentile REAL,
                    trend_strength REAL
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_regime_timestamp ON regime_history(timestamp)")

            # Signal events table (append-only) - mirrors signals.jsonl but queryable.
            # We keep it generic: payload_json stores the full event record.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_events_signal_id ON signal_events(signal_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_events_timestamp ON signal_events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_events_status ON signal_events(status)")

            # Cycle diagnostics (append-only) - per-scan observability for "why quiet / why rejected".
            # We store key counters as columns for easy aggregation, plus full JSON payload for debug.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cycle_diagnostics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cycle_count INTEGER,
                    quiet_reason TEXT,
                    raw_signals INTEGER,
                    validated_signals INTEGER,
                    actionable_signals INTEGER,
                    explore_signals INTEGER,
                    duplicates_filtered INTEGER,
                    stop_cap_applied INTEGER,
                    session_scaling_applied INTEGER,
                    rejected_market_hours INTEGER,
                    rejected_confidence INTEGER,
                    rejected_risk_reward INTEGER,
                    rejected_quality_scorer INTEGER,
                    rejected_order_book INTEGER,
                    rejected_invalid_prices INTEGER,
                    rejected_regime_filter INTEGER,
                    rejected_ml_filter INTEGER,
                    adaptive_sizing_applied INTEGER,
                    payload_json TEXT
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cycle_diag_timestamp ON cycle_diagnostics(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cycle_diag_quiet_reason ON cycle_diagnostics(quiet_reason)")

            conn.commit()

    def add_signal_event(
        self,
        signal_id: str,
        status: str,
        timestamp: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Append a signal event (generated/entered/exited/expired/etc).

        This is the SQLite equivalent of appending/updating signals.jsonl.

        Args:
            signal_id: Signal identifier
            status: Event status (e.g., generated, entered, exited, expired)
            timestamp: ISO timestamp string
            payload: Optional payload dict (stored as JSON)
        """
        try:
            payload_json = json.dumps(payload or {}, ensure_ascii=False)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "add_signal_event payload serialization", e,
                level="warning", category="serialization",
            )
            payload_json = "{}"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO signal_events (signal_id, status, timestamp, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (str(signal_id), str(status), str(timestamp), payload_json),
            )
            conn.commit()

    def add_signal_events_batch(self, events: list[Dict[str, Any]]) -> None:
        """Append multiple signal events in a single transaction.

        Args:
            events: List of event dicts, each with signal_id, status, timestamp, and optional payload.
        """
        if not events:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = []
            for event in events:
                signal_id = str(event.get("signal_id", ""))
                status = str(event.get("status", ""))
                timestamp = str(event.get("timestamp", ""))
                payload = event.get("payload") or event.get("payload_json") or {}
                try:
                    payload_json = json.dumps(payload, ensure_ascii=False)
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "add_signal_events_batch payload serialization", e,
                        level="warning", category="serialization",
                    )
                    payload_json = "{}"
                rows.append((signal_id, status, timestamp, payload_json))
            
            cursor.executemany(
                """
                INSERT INTO signal_events (signal_id, status, timestamp, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def get_signal_events_by_ids(self, signal_ids: list[str]) -> list[Dict[str, Any]]:
        """Get the most recent signal event for each signal_id in a batch.

        Args:
            signal_ids: List of signal identifiers

        Returns:
            List of record dicts with all accumulated fields (one per signal_id).
        """
        if not signal_ids:
            return []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(signal_ids))
            params = [str(sid) for sid in signal_ids]
            cursor.execute(
                f"""
                SELECT signal_id, status, timestamp, payload_json
                FROM signal_events
                WHERE id IN (
                    SELECT MAX(id)
                    FROM signal_events
                    WHERE signal_id IN ({placeholders})
                    GROUP BY signal_id
                )
                ORDER BY id DESC
                """,
                params,
            )
            rows = cursor.fetchall()
        
        results = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload.setdefault("signal_id", row["signal_id"])
            payload.setdefault("status", row["status"])
            payload.setdefault("timestamp", row["timestamp"])
            results.append(payload)
        return results

    def get_signal_event_by_id(self, signal_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent signal event for a given signal_id.

        Reconstructs the record from the latest event's payload.
        Uses the ``idx_signal_events_signal_id`` index for O(1) lookup.

        Args:
            signal_id: Signal identifier

        Returns:
            Record dict with all accumulated fields, or ``None`` if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT signal_id, status, timestamp, payload_json
                FROM signal_events
                WHERE signal_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(signal_id),),
            )
            row = cursor.fetchone()

        if not row:
            return None

        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        # Ensure top-level fields are present for compatibility
        payload.setdefault("signal_id", row["signal_id"])
        payload.setdefault("status", row["status"])
        payload.setdefault("timestamp", row["timestamp"])
        return payload

    def get_recent_signal_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Get most recent signal events (newest first)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT signal_id, status, timestamp, payload_json
                FROM signal_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cursor.fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "get_recent_signal_events JSON parse", e, category="serialization",
                )
                payload = {}
            out.append(
                {
                    "signal_id": r["signal_id"],
                    "status": r["status"],
                    "timestamp": r["timestamp"],
                    "payload": payload,
                }
            )
        return out

    def get_signal_events(
        self,
        *,
        status: Optional[str] = None,
        from_time: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Get signal events with optional status/time filtering (newest first)."""
        query = "SELECT signal_id, status, timestamp, payload_json FROM signal_events WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(str(status))
        if from_time:
            query += " AND timestamp >= ?"
            params.append(str(from_time))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "get_signal_events JSON parse", e, category="serialization",
                )
                payload = {}
            out.append(
                {
                    "signal_id": r["signal_id"],
                    "status": r["status"],
                    "timestamp": r["timestamp"],
                    "payload": payload,
                }
            )
        return out

    def add_cycle_diagnostics(
        self,
        *,
        timestamp: str,
        cycle_count: Optional[int] = None,
        quiet_reason: Optional[str] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Append per-cycle diagnostics (observability).

        Args:
            timestamp: ISO timestamp string
            cycle_count: Optional cycle counter
            quiet_reason: Optional reason string (Active/NoOpportunity/etc)
            diagnostics: Optional raw diagnostics dict (from SignalDiagnostics.to_dict())
        """
        diag = diagnostics or {}
        try:
            payload_json = json.dumps(diag, ensure_ascii=False)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "add_cycle_diagnostics payload serialization", e,
                level="warning", category="serialization",
            )
            payload_json = "{}"

        def _int(key: str) -> Optional[int]:
            try:
                v = diag.get(key)
                if v is None:
                    return None
                return int(v)
            except Exception as e:
                ErrorHandler.log_and_continue(
                    f"cycle_diagnostics int conversion for '{key}'", e,
                    category="serialization",
                )
                return None

        def _bool_int(key: str) -> Optional[int]:
            try:
                v = diag.get(key)
                if v is None:
                    return None
                return 1 if bool(v) else 0
            except Exception as e:
                ErrorHandler.log_and_continue(
                    f"cycle_diagnostics bool conversion for '{key}'", e,
                    category="serialization",
                )
                return None

        row = {
            "timestamp": str(timestamp),
            "cycle_count": int(cycle_count) if cycle_count is not None else None,
            "quiet_reason": str(quiet_reason) if quiet_reason else None,
            "raw_signals": _int("raw_signals"),
            "validated_signals": _int("validated_signals"),
            "actionable_signals": _int("actionable_signals"),
            "explore_signals": _int("explore_signals"),
            "duplicates_filtered": _int("duplicates_filtered"),
            "stop_cap_applied": _int("stop_cap_applied"),
            "session_scaling_applied": _int("session_scaling_applied"),
            "rejected_market_hours": _bool_int("rejected_market_hours"),
            "rejected_confidence": _int("rejected_confidence"),
            "rejected_risk_reward": _int("rejected_risk_reward"),
            "rejected_quality_scorer": _int("rejected_quality_scorer"),
            "rejected_order_book": _int("rejected_order_book"),
            "rejected_invalid_prices": _int("rejected_invalid_prices"),
            "rejected_regime_filter": _int("rejected_regime_filter"),
            "rejected_ml_filter": _int("rejected_ml_filter"),
            "adaptive_sizing_applied": _int("adaptive_sizing_applied"),
            "payload_json": payload_json,
        }

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO cycle_diagnostics (
                    timestamp, cycle_count, quiet_reason,
                    raw_signals, validated_signals, actionable_signals, explore_signals,
                    duplicates_filtered, stop_cap_applied, session_scaling_applied,
                    rejected_market_hours, rejected_confidence, rejected_risk_reward, rejected_quality_scorer,
                    rejected_order_book, rejected_invalid_prices, rejected_regime_filter, rejected_ml_filter,
                    adaptive_sizing_applied, payload_json
                ) VALUES (
                    :timestamp, :cycle_count, :quiet_reason,
                    :raw_signals, :validated_signals, :actionable_signals, :explore_signals,
                    :duplicates_filtered, :stop_cap_applied, :session_scaling_applied,
                    :rejected_market_hours, :rejected_confidence, :rejected_risk_reward, :rejected_quality_scorer,
                    :rejected_order_book, :rejected_invalid_prices, :rejected_regime_filter, :rejected_ml_filter,
                    :adaptive_sizing_applied, :payload_json
                )
                """,
                row,
            )
            conn.commit()

    def get_signal_event_counts(self, *, from_time: Optional[str] = None) -> Dict[str, int]:
        """Get counts of signal events by status."""
        query = "SELECT status, COUNT(*) as count FROM signal_events WHERE 1=1"
        params: List[Any] = []
        if from_time:
            query += " AND timestamp >= ?"
            params.append(from_time)
        query += " GROUP BY status"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        return {str(r["status"]): int(r["count"]) for r in rows}

    def get_all_signal_ids(self) -> set:
        """Get all distinct signal_ids from the signal_events table.

        Used by reconciliation to efficiently batch-check which signals
        already exist in SQLite without querying per-signal_id.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT signal_id FROM signal_events")
            return {str(row[0]) for row in cursor.fetchall()}

    def get_cycle_diagnostics_aggregate(self, *, from_time: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate per-cycle diagnostics into a single summary dict."""
        query = """
            SELECT
                COUNT(*) as cycles,
                SUM(COALESCE(raw_signals, 0)) as raw_signals,
                SUM(COALESCE(validated_signals, 0)) as validated_signals,
                SUM(COALESCE(actionable_signals, 0)) as actionable_signals,
                SUM(COALESCE(explore_signals, 0)) as explore_signals,
                SUM(COALESCE(duplicates_filtered, 0)) as duplicates_filtered,
                SUM(COALESCE(stop_cap_applied, 0)) as stop_cap_applied,
                SUM(COALESCE(session_scaling_applied, 0)) as session_scaling_applied,
                SUM(COALESCE(rejected_market_hours, 0)) as rejected_market_hours,
                SUM(COALESCE(rejected_confidence, 0)) as rejected_confidence,
                SUM(COALESCE(rejected_risk_reward, 0)) as rejected_risk_reward,
                SUM(COALESCE(rejected_quality_scorer, 0)) as rejected_quality_scorer,
                SUM(COALESCE(rejected_order_book, 0)) as rejected_order_book,
                SUM(COALESCE(rejected_invalid_prices, 0)) as rejected_invalid_prices,
                SUM(COALESCE(rejected_regime_filter, 0)) as rejected_regime_filter,
                SUM(COALESCE(rejected_ml_filter, 0)) as rejected_ml_filter,
                SUM(COALESCE(adaptive_sizing_applied, 0)) as adaptive_sizing_applied
            FROM cycle_diagnostics
            WHERE 1=1
        """
        params: List[Any] = []
        if from_time:
            query += " AND timestamp >= ?"
            params.append(from_time)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()

        if not row:
            return {"cycles": 0}

        return {k: row[k] for k in row.keys()}

    def get_quiet_reason_counts(self, *, from_time: Optional[str] = None, limit: int = 10) -> Dict[str, int]:
        """Count quiet reasons over time window (top N)."""
        query = """
            SELECT quiet_reason, COUNT(*) as count
            FROM cycle_diagnostics
            WHERE quiet_reason IS NOT NULL AND quiet_reason != ''
        """
        params: List[Any] = []
        if from_time:
            query += " AND timestamp >= ?"
            params.append(from_time)
        query += " GROUP BY quiet_reason ORDER BY count DESC LIMIT ?"
        params.append(int(limit))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        return {str(r["quiet_reason"]): int(r["count"]) for r in rows}
    
    def add_trade(
        self,
        trade_id: str,
        signal_id: str,
        signal_type: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        is_win: bool,
        entry_time: str,
        exit_time: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        exit_reason: Optional[str] = None,
        hold_duration_minutes: Optional[float] = None,
        regime: Optional[str] = None,
        context_key: Optional[str] = None,
        volatility_percentile: Optional[float] = None,
        volume_percentile: Optional[float] = None,
        features: Optional[Dict[str, float]] = None,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
        mfe_points: Optional[float] = None,
        mae_points: Optional[float] = None,
    ) -> None:
        """
        Add a completed trade to the database.

        Args:
            trade_id: Unique trade identifier
            signal_id: Signal that generated this trade
            signal_type: Type of signal
            direction: "long" or "short"
            entry_price: Entry price
            exit_price: Exit price
            pnl: Profit/loss in dollars
            is_win: Whether trade was profitable
            entry_time: Entry timestamp (ISO format)
            exit_time: Exit timestamp (ISO format)
            stop_loss: Stop loss price
            take_profit: Take profit price
            exit_reason: Reason for exit
            hold_duration_minutes: Trade duration
            regime: Market regime at entry
            context_key: Context key for bandit
            volatility_percentile: Volatility at entry
            volume_percentile: Volume at entry
            features: Feature dictionary at signal time
            max_price: Highest price during hold period
            min_price: Lowest price during hold period
            mfe_points: Max favorable excursion in points
            mae_points: Max adverse excursion in points
        """
        features_json = json.dumps(features) if features else None

        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO trades (
                    trade_id, signal_id, signal_type, direction,
                    entry_price, exit_price, stop_loss, take_profit,
                    pnl, is_win, exit_reason,
                    entry_time, exit_time, hold_duration_minutes,
                    regime, context_key, volatility_percentile, volume_percentile,
                    features_json, created_at,
                    max_price, min_price, mfe_points, mae_points
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_id, signal_id, signal_type, direction,
                entry_price, exit_price, stop_loss, take_profit,
                pnl, 1 if is_win else 0, exit_reason,
                entry_time, exit_time, hold_duration_minutes,
                regime, context_key, volatility_percentile, volume_percentile,
                features_json, datetime.now(timezone.utc).isoformat(),
                max_price, min_price, mfe_points, mae_points,
            ))
            
            # Add features to features table for analysis (bulk insert)
            if features:
                cursor.executemany(
                    """
                    INSERT INTO trade_features (trade_id, feature_name, feature_value)
                    VALUES (?, ?, ?)
                    """,
                    [(trade_id, name, value) for name, value in features.items()],
                )
            
            conn.commit()
        
        logger.debug(f"Trade added to database: {trade_id}")

    def add_regime_snapshot(
        self,
        regime: str,
        confidence: float,
        timestamp: Optional[str] = None,
        volatility_percentile: Optional[float] = None,
        trend_strength: Optional[float] = None,
    ) -> None:
        """Add regime snapshot to history."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO regime_history (regime, confidence, timestamp, volatility_percentile, trend_strength)
                VALUES (?, ?, ?, ?, ?)
            """, (regime, confidence, timestamp, volatility_percentile, trend_strength))
            conn.commit()
    
    def get_trades(
        self,
        signal_type: Optional[str] = None,
        regime: Optional[str] = None,
        direction: Optional[str] = None,
        is_win: Optional[bool] = None,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
        min_pnl: Optional[float] = None,
        max_pnl: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TradeRecord]:
        """
        Query trades with filters.
        
        Args:
            signal_type: Filter by signal type
            regime: Filter by market regime
            direction: Filter by direction
            is_win: Filter by outcome
            from_time: Start time (ISO format)
            to_time: End time (ISO format)
            min_pnl: Minimum P&L
            max_pnl: Maximum P&L
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of TradeRecord objects
        """
        query = "SELECT * FROM trades WHERE 1=1"
        params: List[Any] = []
        
        if signal_type:
            query += " AND signal_type = ?"
            params.append(signal_type)
        
        if regime:
            query += " AND regime = ?"
            params.append(regime)
        
        if direction:
            query += " AND direction = ?"
            params.append(direction)
        
        if is_win is not None:
            query += " AND is_win = ?"
            params.append(1 if is_win else 0)
        
        if from_time:
            query += " AND entry_time >= ?"
            params.append(from_time)
        
        if to_time:
            query += " AND entry_time <= ?"
            params.append(to_time)
        
        if min_pnl is not None:
            query += " AND pnl >= ?"
            params.append(min_pnl)
        
        if max_pnl is not None:
            query += " AND pnl <= ?"
            params.append(max_pnl)
        
        query += " ORDER BY entry_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        
        return [self._row_to_record(row) for row in rows]
    
    def _row_to_record(self, row: sqlite3.Row) -> TradeRecord:
        """Convert database row to TradeRecord."""
        return TradeRecord(
            trade_id=row["trade_id"],
            signal_id=row["signal_id"],
            signal_type=row["signal_type"],
            direction=row["direction"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            pnl=row["pnl"],
            is_win=bool(row["is_win"]),
            exit_reason=row["exit_reason"],
            entry_time=row["entry_time"],
            exit_time=row["exit_time"],
            hold_duration_minutes=row["hold_duration_minutes"],
            regime=row["regime"],
            context_key=row["context_key"],
            volatility_percentile=row["volatility_percentile"],
            volume_percentile=row["volume_percentile"],
            features_json=row["features_json"],
            created_at=row["created_at"],
        )
    
    def get_performance_by_signal_type(self, days: Optional[int] = None) -> Dict[str, Dict]:
        """Get performance breakdown by signal type."""
        query = "SELECT signal_type, COUNT(*) as count, SUM(is_win) as wins, SUM(pnl) as total_pnl FROM trades"
        params: List[Any] = []
        
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query += " WHERE entry_time >= ?"
            params.append(cutoff)
        
        query += " GROUP BY signal_type"
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        
        return {
            row["signal_type"]: {
                "count": row["count"],
                "wins": row["wins"],
                "losses": row["count"] - row["wins"],
                "win_rate": round(row["wins"] / row["count"], 4) if row["count"] > 0 else 0,
                "total_pnl": round(row["total_pnl"], 2),
                "avg_pnl": round(row["total_pnl"] / row["count"], 2) if row["count"] > 0 else 0,
            }
            for row in rows
        }
    
    def get_performance_by_regime(self, days: Optional[int] = None) -> Dict[str, Dict]:
        """Get performance breakdown by market regime."""
        query = "SELECT regime, COUNT(*) as count, SUM(is_win) as wins, SUM(pnl) as total_pnl FROM trades WHERE regime IS NOT NULL"
        params: List[Any] = []
        
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query += " AND entry_time >= ?"
            params.append(cutoff)
        
        query += " GROUP BY regime"
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        
        return {
            row["regime"]: {
                "count": row["count"],
                "wins": row["wins"],
                "win_rate": round(row["wins"] / row["count"], 4) if row["count"] > 0 else 0,
                "total_pnl": round(row["total_pnl"], 2),
            }
            for row in rows
        }
    
    def get_performance_by_hour(self, days: Optional[int] = None) -> Dict[int, Dict]:
        """Get performance breakdown by hour of day."""
        query = """
            SELECT 
                CAST(strftime('%H', entry_time) AS INTEGER) as hour,
                COUNT(*) as count,
                SUM(is_win) as wins,
                SUM(pnl) as total_pnl
            FROM trades
        """
        params: List[Any] = []
        
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query += " WHERE entry_time >= ?"
            params.append(cutoff)
        
        query += " GROUP BY hour ORDER BY hour"
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        
        return {
            row["hour"]: {
                "count": row["count"],
                "wins": row["wins"],
                "win_rate": round(row["wins"] / row["count"], 4) if row["count"] > 0 else 0,
                "total_pnl": round(row["total_pnl"], 2),
            }
            for row in rows
        }
    
    def get_feature_correlations(self, feature_name: str) -> Dict[str, float]:
        """Get correlation between a feature and trade outcomes."""
        query = """
            SELECT 
                tf.feature_value,
                t.is_win,
                t.pnl
            FROM trade_features tf
            JOIN trades t ON tf.trade_id = t.trade_id
            WHERE tf.feature_name = ?
        """
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (feature_name,))
            rows = cursor.fetchall()
        
        if not rows:
            return {"count": 0}
        
        import numpy as np
        
        values = [row[0] for row in rows]
        outcomes = [row[1] for row in rows]
        pnls = [row[2] for row in rows]
        
        # Calculate correlations
        win_corr = np.corrcoef(values, outcomes)[0, 1] if len(values) > 1 else 0
        pnl_corr = np.corrcoef(values, pnls)[0, 1] if len(values) > 1 else 0
        
        return {
            "count": len(rows),
            "win_correlation": round(float(win_corr), 4) if not np.isnan(win_corr) else 0,
            "pnl_correlation": round(float(pnl_corr), 4) if not np.isnan(pnl_corr) else 0,
            "mean_value": round(float(np.mean(values)), 4),
            "std_value": round(float(np.std(values)), 4),
        }
    
    def get_trade_count(self) -> int:
        """Get total number of trades."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades")
            return int(cursor.fetchone()[0])
    
    def get_summary(self) -> Dict[str, Any]:
        """Get database summary."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COALESCE(SUM(is_win), 0) as wins,
                    COALESCE(SUM(pnl), 0.0) as total_pnl,
                    COUNT(DISTINCT signal_type) as signal_types,
                    MIN(entry_time) as first_trade,
                    MAX(entry_time) as last_trade
                FROM trades
            """)
            row = cursor.fetchone()
        
        total = row["total"]
        wins = row["wins"]
        total_pnl = row["total_pnl"]
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 4) if total > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total > 0 else 0,
            "signal_types": row["signal_types"],
            "first_trade": row["first_trade"],
            "last_trade": row["last_trade"],
        }

    def get_trade_summary(self, *, from_exit_time: Optional[str] = None) -> Dict[str, Any]:
        """Get summary stats for trades over a time window (by exit_time)."""
        query = """
            SELECT
                COUNT(*) as total,
                SUM(is_win) as wins,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl,
                AVG(hold_duration_minutes) as avg_hold
            FROM trades
            WHERE 1=1
        """
        params: List[Any] = []
        if from_exit_time:
            query += " AND exit_time >= ?"
            params.append(str(from_exit_time))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()

        if not row:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "total_pnl": 0.0, "avg_pnl": 0.0, "avg_hold": None}

        total = int(row["total"] or 0)
        wins = int(row["wins"] or 0)
        total_pnl = float(row["total_pnl"] or 0.0)
        avg_pnl = float(row["avg_pnl"] or 0.0)
        avg_hold = row["avg_hold"]
        try:
            avg_hold_f = float(avg_hold) if avg_hold is not None else None
        except Exception as e:
            ErrorHandler.log_and_continue(
                "get_trade_summary avg_hold conversion", e, category="serialization",
            )
            avg_hold_f = None

        return {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": (wins / total) if total > 0 else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "avg_hold_minutes": avg_hold_f,
        }

    def get_recent_trades_by_exit(
        self,
        *,
        limit: int = 200,
        from_exit_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent trades ordered by exit_time (newest first).

        This is used for:
        - drift detection (based on realized outcomes)
        - ML lift measurement (pass vs would-block groups)
        """
        query = """
            SELECT signal_id, signal_type, direction, pnl, is_win, exit_time, features_json
            FROM trades
            WHERE 1=1
        """
        params: List[Any] = []
        if from_exit_time:
            query += " AND exit_time >= ?"
            params.append(str(from_exit_time))
        query += " ORDER BY exit_time DESC LIMIT ?"
        params.append(int(limit))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                features = json.loads(r["features_json"] or "{}")
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "get_recent_trades_by_exit features JSON parse", e,
                    category="serialization",
                )
                features = {}
            if not isinstance(features, dict):
                features = {}
            out.append(
                {
                    "signal_id": str(r["signal_id"]),
                    "signal_type": str(r["signal_type"]),
                    "direction": str(r["direction"]),
                    "pnl": float(r["pnl"] or 0.0),
                    "is_win": bool(r["is_win"]),
                    "exit_time": str(r["exit_time"]),
                    "features": features,
                }
            )
        return out
    # ==================================================================
    # Advanced Analysis Methods (for agent consumption)
    # ==================================================================

    def get_excursion_analysis(self, *, days: Optional[int] = None, direction: Optional[str] = None) -> Dict[str, Any]:
        """MFE/MAE analysis for evaluating stop/TP placement."""
        where_clauses = ["mfe_points IS NOT NULL"]
        params: list = []
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            where_clauses.append("exit_time >= ?")
            params.append(cutoff)
        if direction:
            where_clauses.append("direction = ?")
            params.append(direction)
        where = " AND ".join(where_clauses)

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Overall MFE/MAE stats
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total,
                    AVG(mfe_points) as avg_mfe,
                    AVG(mae_points) as avg_mae,
                    MAX(mfe_points) as max_mfe,
                    MAX(mae_points) as max_mae,
                    AVG(CASE WHEN is_win=1 THEN mfe_points END) as avg_mfe_winners,
                    AVG(CASE WHEN is_win=0 THEN mfe_points END) as avg_mfe_losers,
                    AVG(CASE WHEN is_win=1 THEN mae_points END) as avg_mae_winners,
                    AVG(CASE WHEN is_win=0 THEN mae_points END) as avg_mae_losers,
                    AVG(max_price) as avg_max_price,
                    AVG(min_price) as avg_min_price
                FROM trades WHERE {where}
            """, params)
            row = cursor.fetchone()

            # Losers that had enough MFE to be winners (TP too far)
            cursor.execute(f"""
                SELECT COUNT(*) as count, AVG(mfe_points) as avg_mfe, AVG(pnl) as avg_pnl
                FROM trades
                WHERE {where} AND is_win=0 AND mfe_points > mae_points
            """, params)
            losers_with_mfe = cursor.fetchone()

            # Winners MFE utilization (how much of MFE did TP capture)
            cursor.execute(f"""
                SELECT
                    AVG(CASE WHEN direction='long'
                        THEN (exit_price - entry_price) / NULLIF(mfe_points, 0)
                        ELSE (entry_price - exit_price) / NULLIF(mfe_points, 0)
                    END) as avg_tp_efficiency
                FROM trades
                WHERE {where} AND is_win=1 AND mfe_points > 0
            """, params)
            tp_eff = cursor.fetchone()

            # By exit_reason breakdown
            cursor.execute(f"""
                SELECT exit_reason,
                    COUNT(*) as count,
                    AVG(mfe_points) as avg_mfe,
                    AVG(mae_points) as avg_mae,
                    AVG(pnl) as avg_pnl,
                    SUM(pnl) as total_pnl
                FROM trades WHERE {where}
                GROUP BY exit_reason
            """, params)
            by_exit_reason = {r["exit_reason"]: dict(r) for r in cursor.fetchall()}

        return {
            "total_trades_with_excursion": row["total"] if row else 0,
            "avg_mfe": round(row["avg_mfe"] or 0, 2) if row else 0,
            "avg_mae": round(row["avg_mae"] or 0, 2) if row else 0,
            "max_mfe": round(row["max_mfe"] or 0, 2) if row else 0,
            "max_mae": round(row["max_mae"] or 0, 2) if row else 0,
            "avg_mfe_winners": round(row["avg_mfe_winners"] or 0, 2) if row else 0,
            "avg_mfe_losers": round(row["avg_mfe_losers"] or 0, 2) if row else 0,
            "avg_mae_winners": round(row["avg_mae_winners"] or 0, 2) if row else 0,
            "avg_mae_losers": round(row["avg_mae_losers"] or 0, 2) if row else 0,
            "losers_with_positive_mfe": {
                "count": losers_with_mfe["count"] if losers_with_mfe else 0,
                "avg_mfe": round(losers_with_mfe["avg_mfe"] or 0, 2) if losers_with_mfe else 0,
                "insight": "Trades that went in your favor but still lost — TP may be too far or stop too tight",
            },
            "tp_efficiency": round(tp_eff["avg_tp_efficiency"] or 0, 3) if tp_eff else 0,
            "by_exit_reason": by_exit_reason,
        }

    def get_performance_by_direction(self, *, days: Optional[int] = None) -> Dict[str, Dict]:
        """Performance breakdown by direction (long vs short)."""
        where = "1=1"
        params: list = []
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            where = "exit_time >= ?"
            params.append(cutoff)

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT direction,
                    COUNT(*) as total,
                    SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN is_win=0 THEN 1 ELSE 0 END) as losses,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl,
                    AVG(mfe_points) as avg_mfe,
                    AVG(mae_points) as avg_mae,
                    AVG(hold_duration_minutes) as avg_hold_min,
                    MAX(pnl) as best_trade,
                    MIN(pnl) as worst_trade
                FROM trades WHERE {where}
                GROUP BY direction
            """, params)
            result = {}
            for row in cursor.fetchall():
                total = row["total"]
                wins = row["wins"]
                result[row["direction"]] = {
                    "total": total,
                    "wins": wins,
                    "losses": row["losses"],
                    "win_rate": round(wins / total, 4) if total > 0 else 0,
                    "total_pnl": round(row["total_pnl"] or 0, 2),
                    "avg_pnl": round(row["avg_pnl"] or 0, 2),
                    "avg_mfe": round(row["avg_mfe"] or 0, 2) if row["avg_mfe"] else None,
                    "avg_mae": round(row["avg_mae"] or 0, 2) if row["avg_mae"] else None,
                    "avg_hold_min": round(row["avg_hold_min"] or 0, 1) if row["avg_hold_min"] else None,
                    "best_trade": round(row["best_trade"] or 0, 2),
                    "worst_trade": round(row["worst_trade"] or 0, 2),
                }
        return result

    def get_comprehensive_analysis(self, *, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Single method for agents to get complete trade analysis.
        Returns everything needed to evaluate and improve the strategy.
        """
        where = "1=1"
        params: list = []
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            where = "exit_time >= ?"
            params.append(cutoff)

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Overall summary
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END) as wins,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl,
                    MAX(pnl) as best_trade,
                    MIN(pnl) as worst_trade,
                    AVG(hold_duration_minutes) as avg_hold_min,
                    AVG(mfe_points) as avg_mfe,
                    AVG(mae_points) as avg_mae,
                    SUM(CASE WHEN exit_reason='stop_loss' THEN 1 ELSE 0 END) as stop_losses,
                    SUM(CASE WHEN exit_reason='take_profit' THEN 1 ELSE 0 END) as take_profits,
                    MIN(entry_time) as first_trade,
                    MAX(exit_time) as last_trade
                FROM trades WHERE {where}
            """, params)
            summary = dict(cursor.fetchone())
            total = summary["total"] or 0
            wins = summary["wins"] or 0
            summary["losses"] = total - wins
            summary["win_rate"] = round(wins / total, 4) if total > 0 else 0

            # Running equity curve (cumulative PnL)
            cursor.execute(f"""
                SELECT exit_time, pnl,
                    SUM(pnl) OVER (ORDER BY exit_time) as cumulative_pnl
                FROM trades WHERE {where}
                ORDER BY exit_time
            """, params)
            equity = []
            max_equity = 0
            max_drawdown = 0
            for row in cursor.fetchall():
                cum = row["cumulative_pnl"] or 0
                max_equity = max(max_equity, cum)
                dd = max_equity - cum
                max_drawdown = max(max_drawdown, dd)
                equity.append({"time": row["exit_time"], "pnl": row["pnl"], "cumulative": round(cum, 2)})

            # Streak analysis
            cursor.execute(f"""
                SELECT is_win FROM trades WHERE {where} ORDER BY exit_time
            """, params)
            wins_list = [r["is_win"] for r in cursor.fetchall()]
            max_win_streak = max_lose_streak = cur_streak = 0
            last_win = None
            for w in wins_list:
                if w == last_win:
                    cur_streak += 1
                else:
                    cur_streak = 1
                    last_win = w
                if w:
                    max_win_streak = max(max_win_streak, cur_streak)
                else:
                    max_lose_streak = max(max_lose_streak, cur_streak)

        return {
            "summary": {k: round(v, 2) if isinstance(v, float) else v for k, v in summary.items()},
            "max_drawdown": round(max_drawdown, 2),
            "max_equity_peak": round(max_equity, 2),
            "max_win_streak": max_win_streak,
            "max_lose_streak": max_lose_streak,
            "by_direction": self.get_performance_by_direction(days=days),
            "by_signal_type": self.get_performance_by_signal_type(days=days),
            "excursion": self.get_excursion_analysis(days=days),
            "equity_curve_len": len(equity),
            "equity_last_10": equity[-10:] if equity else [],
        }


