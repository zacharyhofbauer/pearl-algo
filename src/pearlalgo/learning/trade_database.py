"""
Persistent Trade Database

SQLite-based storage for queryable trade history.
Enables:
- Query trades by signal type, regime, time, P&L
- Analyze performance across dimensions
- Never forget any lesson
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from pearlalgo.utils.logger import logger


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
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize trade database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path or Path("data/nq_agent_state/trades.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_schema()
        
        logger.info(f"TradeDatabase initialized: {self.db_path}")
    
    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
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
            
            # Indices for common queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_signal_type ON trades(signal_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_regime ON trades(regime)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_is_win ON trades(is_win)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_pnl ON trades(pnl)")
            
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
            
            conn.commit()
    
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
                    features_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_id, signal_id, signal_type, direction,
                entry_price, exit_price, stop_loss, take_profit,
                pnl, 1 if is_win else 0, exit_reason,
                entry_time, exit_time, hold_duration_minutes,
                regime, context_key, volatility_percentile, volume_percentile,
                features_json, datetime.now(timezone.utc).isoformat(),
            ))
            
            # Add features to features table for analysis
            if features:
                for name, value in features.items():
                    cursor.execute("""
                        INSERT INTO trade_features (trade_id, feature_name, feature_value)
                        VALUES (?, ?, ?)
                    """, (trade_id, name, value))
            
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
            return cursor.fetchone()[0]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get database summary."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM trades")
            total = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(is_win) FROM trades")
            wins = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT SUM(pnl) FROM trades")
            total_pnl = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(DISTINCT signal_type) FROM trades")
            signal_types = cursor.fetchone()[0]
            
            cursor.execute("SELECT MIN(entry_time), MAX(entry_time) FROM trades")
            time_range = cursor.fetchone()
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 4) if total > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total > 0 else 0,
            "signal_types": signal_types,
            "first_trade": time_range[0],
            "last_trade": time_range[1],
        }




