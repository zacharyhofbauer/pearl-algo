"""
Persistent Trade Database

SQLite-based secondary store for queryable trade history and signal/cycle
observability. JSON state remains authoritative for recovery.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

import pytz

from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir

_ET = pytz.timezone("America/New_York")


@dataclass
class TradeRecord:
    """Queryable trade record."""

    trade_id: str
    signal_id: str
    signal_type: str
    direction: str
    entry_price: float
    exit_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    pnl: float
    is_win: bool
    exit_reason: Optional[str]
    entry_time: str
    exit_time: str
    hold_duration_minutes: Optional[float]
    regime: Optional[str]
    context_key: Optional[str]
    volatility_percentile: Optional[float]
    volume_percentile: Optional[float]
    features_json: Optional[str]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        try:
            features = json.loads(self.features_json or "{}")
            if not isinstance(features, dict):
                features = {}
        except Exception:
            features = {}
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
            "features": features,
            "created_at": self.created_at,
        }


class TradeDatabase:
    """SQLite database for trade history, signal events, and diagnostics."""

    def __init__(
        self, db_path: Optional[Union[str, Path]] = None, cache_connection: bool = False
    ):
        self.db_path = Path(db_path) if db_path is not None else (ensure_state_dir(None) / "trades.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_connection = cache_connection
        self._cached_conn: Optional[sqlite3.Connection] = None
        self._init_schema()
        logger.info(
            f"TradeDatabase initialized: {self.db_path} "
            f"(WAL mode, cache_connection={cache_connection})"
        )

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._cache_connection:
            if self._cached_conn is None:
                self._cached_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                self._cached_conn.row_factory = sqlite3.Row
                self._cached_conn.execute("PRAGMA journal_mode=WAL")
                self._cached_conn.execute("PRAGMA synchronous=NORMAL")
                self._cached_conn.execute("PRAGMA busy_timeout=5000")
            yield self._cached_conn
            return

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def close(self) -> None:
        if self._cached_conn is not None:
            try:
                self._cached_conn.close()
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "TradeDatabase.close", e, level="warning", category="sqlite"
                )
            self._cached_conn = None

    def _init_schema(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")

            cursor.execute(
                """
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
                """
            )

            for col, col_type in [
                ("max_price", "REAL"),
                ("min_price", "REAL"),
                ("mfe_points", "REAL"),
                ("mae_points", "REAL"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
                except Exception:
                    pass

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT NOT NULL,
                    feature_name TEXT NOT NULL,
                    feature_value REAL NOT NULL,
                    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS regime_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    regime TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    volatility_percentile REAL,
                    trend_strength REAL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT
                )
                """
            )
            cursor.execute(
                """
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
                """
            )

            for sql in [
                "CREATE INDEX IF NOT EXISTS idx_trades_signal_type ON trades(signal_type)",
                "CREATE INDEX IF NOT EXISTS idx_trades_direction ON trades(direction)",
                "CREATE INDEX IF NOT EXISTS idx_trades_regime ON trades(regime)",
                "CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)",
                "CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time)",
                "CREATE INDEX IF NOT EXISTS idx_trades_pnl ON trades(pnl)",
                "CREATE INDEX IF NOT EXISTS idx_signal_events_signal_id ON signal_events(signal_id)",
                "CREATE INDEX IF NOT EXISTS idx_signal_events_timestamp ON signal_events(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_signal_events_status ON signal_events(status)",
                "CREATE INDEX IF NOT EXISTS idx_cycle_diag_timestamp ON cycle_diagnostics(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_cycle_diag_quiet_reason ON cycle_diagnostics(quiet_reason)",
                "CREATE INDEX IF NOT EXISTS idx_regime_timestamp ON regime_history(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_features_trade_id ON trade_features(trade_id)",
                "CREATE INDEX IF NOT EXISTS idx_features_name ON trade_features(feature_name)",
            ]:
                cursor.execute(sql)

            conn.commit()

    @staticmethod
    def _now_et() -> str:
        return datetime.now(_ET).strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def _json_dumps(payload: Any) -> str:
        try:
            return json.dumps(payload or {}, ensure_ascii=False)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "TradeDatabase JSON serialization", e, level="warning", category="serialization"
            )
            return "{}"

    @staticmethod
    def _json_loads(payload_json: Optional[str]) -> Dict[str, Any]:
        if not payload_json:
            return {}
        try:
            payload = json.loads(payload_json)
            return payload if isinstance(payload, dict) else {}
        except Exception as e:
            ErrorHandler.log_and_continue(
                "TradeDatabase JSON parse", e, level="warning", category="serialization"
            )
            return {}

    def add_signal_event(
        self,
        signal_id: str,
        status: str,
        timestamp: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO signal_events (signal_id, status, timestamp, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (str(signal_id), str(status), str(timestamp), self._json_dumps(payload)),
            )
            conn.commit()

    def get_signal_event_by_id(self, signal_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT signal_id, status, timestamp, payload_json
                FROM signal_events
                WHERE signal_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(signal_id),),
            ).fetchone()

        if not row:
            return None
        payload = self._json_loads(row["payload_json"])
        payload.setdefault("signal_id", row["signal_id"])
        payload.setdefault("status", row["status"])
        payload.setdefault("timestamp", row["timestamp"])
        return payload

    def get_recent_signal_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT signal_id, status, timestamp, payload_json
                FROM signal_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "signal_id": row["signal_id"],
                "status": row["status"],
                "timestamp": row["timestamp"],
                "payload": self._json_loads(row["payload_json"]),
            }
            for row in rows
        ]

    def get_signal_events(
        self,
        *,
        status: Optional[str] = None,
        from_time: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
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
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "signal_id": row["signal_id"],
                "status": row["status"],
                "timestamp": row["timestamp"],
                "payload": self._json_loads(row["payload_json"]),
            }
            for row in rows
        ]

    def get_signal_event_counts(self, *, from_time: Optional[str] = None) -> Dict[str, int]:
        query = "SELECT status, COUNT(*) AS count FROM signal_events WHERE 1=1"
        params: List[Any] = []
        if from_time:
            query += " AND timestamp >= ?"
            params.append(str(from_time))
        query += " GROUP BY status"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return {str(row["status"]): int(row["count"] or 0) for row in rows}

    def get_all_signal_ids(self) -> set[str]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT signal_id FROM signal_events").fetchall()
        return {str(row[0]) for row in rows}

    def add_cycle_diagnostics(
        self,
        *,
        timestamp: str,
        cycle_count: Optional[int] = None,
        quiet_reason: Optional[str] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        diag = diagnostics or {}

        def _int(name: str) -> Optional[int]:
            value = diag.get(name)
            if value is None:
                return None
            try:
                return int(value)
            except Exception as e:
                ErrorHandler.log_and_continue(
                    f"cycle_diagnostics {name}", e, level="warning", category="serialization"
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
            "rejected_market_hours": _int("rejected_market_hours"),
            "rejected_confidence": _int("rejected_confidence"),
            "rejected_risk_reward": _int("rejected_risk_reward"),
            "rejected_quality_scorer": _int("rejected_quality_scorer"),
            "rejected_order_book": _int("rejected_order_book"),
            "rejected_invalid_prices": _int("rejected_invalid_prices"),
            "rejected_regime_filter": _int("rejected_regime_filter"),
            "rejected_ml_filter": _int("rejected_ml_filter"),
            "adaptive_sizing_applied": _int("adaptive_sizing_applied"),
            "payload_json": self._json_dumps(diag),
        }

        with self._get_connection() as conn:
            conn.execute(
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

    def get_cycle_diagnostics_aggregate(self, *, from_time: Optional[str] = None) -> Dict[str, Any]:
        query = """
            SELECT
                COUNT(*) AS cycles,
                SUM(COALESCE(raw_signals, 0)) AS raw_signals,
                SUM(COALESCE(validated_signals, 0)) AS validated_signals,
                SUM(COALESCE(actionable_signals, 0)) AS actionable_signals,
                SUM(COALESCE(explore_signals, 0)) AS explore_signals,
                SUM(COALESCE(duplicates_filtered, 0)) AS duplicates_filtered,
                SUM(COALESCE(stop_cap_applied, 0)) AS stop_cap_applied,
                SUM(COALESCE(session_scaling_applied, 0)) AS session_scaling_applied,
                SUM(COALESCE(rejected_market_hours, 0)) AS rejected_market_hours,
                SUM(COALESCE(rejected_confidence, 0)) AS rejected_confidence,
                SUM(COALESCE(rejected_risk_reward, 0)) AS rejected_risk_reward,
                SUM(COALESCE(rejected_quality_scorer, 0)) AS rejected_quality_scorer,
                SUM(COALESCE(rejected_order_book, 0)) AS rejected_order_book,
                SUM(COALESCE(rejected_invalid_prices, 0)) AS rejected_invalid_prices,
                SUM(COALESCE(rejected_regime_filter, 0)) AS rejected_regime_filter,
                SUM(COALESCE(rejected_ml_filter, 0)) AS rejected_ml_filter,
                SUM(COALESCE(adaptive_sizing_applied, 0)) AS adaptive_sizing_applied
            FROM cycle_diagnostics
            WHERE 1=1
        """
        params: List[Any] = []
        if from_time:
            query += " AND timestamp >= ?"
            params.append(str(from_time))
        with self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
        if row is None:
            return {"cycles": 0}
        return {k: row[k] for k in row.keys()}

    def get_quiet_reason_counts(self, *, from_time: Optional[str] = None, limit: int = 10) -> Dict[str, int]:
        query = """
            SELECT quiet_reason, COUNT(*) AS count
            FROM cycle_diagnostics
            WHERE quiet_reason IS NOT NULL AND quiet_reason != ''
        """
        params: List[Any] = []
        if from_time:
            query += " AND timestamp >= ?"
            params.append(str(from_time))
        query += " GROUP BY quiet_reason ORDER BY count DESC LIMIT ?"
        params.append(int(limit))

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return {str(row["quiet_reason"]): int(row["count"] or 0) for row in rows}

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
        features_json = self._json_dumps(features) if features else None
        with self._get_connection() as conn:
            conn.execute("DELETE FROM trade_features WHERE trade_id = ?", (trade_id,))
            conn.execute(
                """
                INSERT OR REPLACE INTO trades (
                    trade_id, signal_id, signal_type, direction,
                    entry_price, exit_price, stop_loss, take_profit,
                    pnl, is_win, exit_reason,
                    entry_time, exit_time, hold_duration_minutes,
                    regime, context_key, volatility_percentile, volume_percentile,
                    features_json, created_at,
                    max_price, min_price, mfe_points, mae_points
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(trade_id),
                    str(signal_id),
                    str(signal_type),
                    str(direction),
                    float(entry_price),
                    float(exit_price),
                    stop_loss,
                    take_profit,
                    float(pnl),
                    1 if is_win else 0,
                    exit_reason,
                    str(entry_time),
                    str(exit_time),
                    hold_duration_minutes,
                    regime,
                    context_key,
                    volatility_percentile,
                    volume_percentile,
                    features_json,
                    self._now_et(),
                    max_price,
                    min_price,
                    mfe_points,
                    mae_points,
                ),
            )
            if features:
                conn.executemany(
                    """
                    INSERT INTO trade_features (trade_id, feature_name, feature_value)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (str(trade_id), str(name), float(value))
                        for name, value in features.items()
                    ],
                )
            conn.commit()

    def add_regime_snapshot(
        self,
        regime: str,
        confidence: float,
        timestamp: Optional[str] = None,
        volatility_percentile: Optional[float] = None,
        trend_strength: Optional[float] = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO regime_history (regime, confidence, timestamp, volatility_percentile, trend_strength)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(regime),
                    float(confidence),
                    str(timestamp or self._now_et()),
                    volatility_percentile,
                    trend_strength,
                ),
            )
            conn.commit()

    def get_trade_count(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        return int(row[0] if row else 0)

    def get_summary(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(is_win), 0) AS wins,
                    COALESCE(SUM(pnl), 0.0) AS total_pnl,
                    COUNT(DISTINCT signal_type) AS signal_types,
                    MIN(entry_time) AS first_trade,
                    MAX(entry_time) AS last_trade
                FROM trades
                """
            ).fetchone()
        total = int(row["total"] or 0) if row else 0
        wins = int(row["wins"] or 0) if row else 0
        total_pnl = float(row["total_pnl"] or 0.0) if row else 0.0
        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 4) if total else 0.0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total else 0.0,
            "signal_types": int(row["signal_types"] or 0) if row else 0,
            "first_trade": row["first_trade"] if row else None,
            "last_trade": row["last_trade"] if row else None,
        }

    def get_trade_summary(self, *, from_exit_time: Optional[str] = None) -> Dict[str, Any]:
        query = """
            SELECT
                COUNT(*) AS total,
                SUM(is_win) AS wins,
                SUM(pnl) AS total_pnl,
                AVG(pnl) AS avg_pnl,
                AVG(hold_duration_minutes) AS avg_hold
            FROM trades
            WHERE 1=1
        """
        params: List[Any] = []
        if from_exit_time:
            query += " AND exit_time >= ?"
            params.append(str(from_exit_time))

        with self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()

        total = int(row["total"] or 0) if row else 0
        wins = int(row["wins"] or 0) if row else 0
        return {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": (wins / total) if total else 0.0,
            "total_pnl": float(row["total_pnl"] or 0.0) if row else 0.0,
            "avg_pnl": float(row["avg_pnl"] or 0.0) if row else 0.0,
            "avg_hold_minutes": (
                float(row["avg_hold"]) if row and row["avg_hold"] is not None else None
            ),
        }

    def get_recent_trades_by_exit(
        self,
        *,
        limit: int = 200,
        from_exit_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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
            rows = conn.execute(query, params).fetchall()

        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "signal_id": str(row["signal_id"]),
                    "signal_type": str(row["signal_type"]),
                    "direction": str(row["direction"]),
                    "pnl": float(row["pnl"] or 0.0),
                    "is_win": bool(row["is_win"]),
                    "exit_time": str(row["exit_time"]),
                    "features": self._json_loads(row["features_json"]),
                }
            )
        return result

    def get_performance_by_signal_type(self, days: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
        query = "SELECT signal_type, COUNT(*) AS count, SUM(is_win) AS wins, SUM(pnl) AS total_pnl FROM trades"
        params: List[Any] = []
        if days:
            cutoff = (datetime.now(_ET) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
            query += " WHERE entry_time >= ?"
            params.append(cutoff)
        query += " GROUP BY signal_type"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return {
            str(row["signal_type"]): {
                "count": int(row["count"] or 0),
                "wins": int(row["wins"] or 0),
                "losses": int(row["count"] or 0) - int(row["wins"] or 0),
                "win_rate": (float(row["wins"] or 0) / float(row["count"] or 1)) if row["count"] else 0.0,
                "total_pnl": float(row["total_pnl"] or 0.0),
                "avg_pnl": (float(row["total_pnl"] or 0.0) / float(row["count"] or 1)) if row["count"] else 0.0,
            }
            for row in rows
        }
