"""
Opportunity Tracker - Track ALL trading opportunities for learning.

This module tracks every signal opportunity, including those that were filtered,
to enable comprehensive learning about filter effectiveness and missed opportunities.

Key Features:
- Log all signal opportunities with full indicator snapshots
- Track which filters passed/blocked each signal
- Monitor hypothetical outcomes for filtered signals
- Calculate filter effectiveness metrics
- Support auto-adjustment recommendations
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple
from enum import Enum

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir


class OpportunityDecision(Enum):
    """Decision made for an opportunity."""
    ALLOW = "ALLOW"      # Signal was allowed (may or may not have been entered)
    BLOCK = "BLOCK"      # Signal was blocked by a filter
    SHADOW = "SHADOW"    # Signal was measured in shadow mode
    SKIP = "SKIP"        # Signal was skipped for other reasons


@dataclass
class FilterEvaluation:
    """Result of evaluating a single filter."""
    name: str
    passed: bool
    reason: str
    threshold: Optional[float] = None
    actual_value: Optional[float] = None
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
            "threshold": self.threshold,
            "actual_value": self.actual_value,
            "details": self.details,
        }


@dataclass
class SignalOpportunity:
    """
    Complete record of a signal opportunity.
    
    This captures everything about a potential trade signal, including:
    - Full indicator snapshot at the time
    - All filter evaluations
    - Key level proximity
    - The final decision
    - Hypothetical outcome (filled in later)
    """
    # Identity
    opportunity_id: str
    timestamp: datetime
    
    # Signal details
    direction: str  # LONG or SHORT
    price: float
    confidence: float
    signal_type: str
    
    # Full indicator snapshot
    indicators: dict[str, float] = field(default_factory=dict)
    
    # Key levels nearby
    key_levels: list[dict[str, Any]] = field(default_factory=list)
    
    # Market context
    regime: str = ""
    regime_confidence: float = 0.0
    volume_ratio: float = 0.0
    atr: float = 0.0
    
    # Filter evaluations
    filters_evaluated: list[FilterEvaluation] = field(default_factory=list)
    
    # Decision
    decision: OpportunityDecision = OpportunityDecision.ALLOW
    blocking_filter: Optional[str] = None
    
    # Proposed trade parameters (if signal was generated)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward: float = 0.0
    
    # Hypothetical outcome (filled in later by price monitoring)
    hypothetical_entry_filled: bool = False
    price_after_1m: Optional[float] = None
    price_after_5m: Optional[float] = None
    price_after_15m: Optional[float] = None
    price_after_30m: Optional[float] = None
    
    # Calculated hypothetical outcome
    would_have_won: Optional[bool] = None
    hypothetical_pnl: Optional[float] = None
    hypothetical_exit_reason: Optional[str] = None
    
    def add_filter_result(
        self,
        name: str,
        passed: bool,
        reason: str,
        threshold: Optional[float] = None,
        actual_value: Optional[float] = None,
        **details,
    ) -> None:
        """Add a filter evaluation result."""
        self.filters_evaluated.append(FilterEvaluation(
            name=name,
            passed=passed,
            reason=reason,
            threshold=threshold,
            actual_value=actual_value,
            details=details,
        ))
        
        # Track first blocking filter
        if not passed and self.blocking_filter is None:
            self.blocking_filter = name
            self.decision = OpportunityDecision.BLOCK
    
    def get_passing_filters(self) -> list[FilterEvaluation]:
        """Get all filters that passed."""
        return [f for f in self.filters_evaluated if f.passed]
    
    def get_blocking_filters(self) -> list[FilterEvaluation]:
        """Get all filters that blocked."""
        return [f for f in self.filters_evaluated if not f.passed]
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "opportunity_id": self.opportunity_id,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "price": self.price,
            "confidence": self.confidence,
            "signal_type": self.signal_type,
            "indicators": self.indicators,
            "key_levels": self.key_levels,
            "regime": self.regime,
            "regime_confidence": self.regime_confidence,
            "volume_ratio": self.volume_ratio,
            "atr": self.atr,
            "filters_evaluated": [f.to_dict() for f in self.filters_evaluated],
            "decision": self.decision.value,
            "blocking_filter": self.blocking_filter,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "hypothetical_entry_filled": self.hypothetical_entry_filled,
            "price_after_1m": self.price_after_1m,
            "price_after_5m": self.price_after_5m,
            "price_after_15m": self.price_after_15m,
            "price_after_30m": self.price_after_30m,
            "would_have_won": self.would_have_won,
            "hypothetical_pnl": self.hypothetical_pnl,
            "hypothetical_exit_reason": self.hypothetical_exit_reason,
        }


class OpportunityTracker:
    """
    Tracks all signal opportunities for learning.
    
    Features:
    - Store all opportunities with full context
    - Track hypothetical outcomes for blocked signals
    - Calculate filter effectiveness
    - Generate learning reports
    
    Usage:
        tracker = OpportunityTracker()
        
        # Log an opportunity
        opp = SignalOpportunity(
            opportunity_id="opp-001",
            timestamp=datetime.now(timezone.utc),
            direction="LONG",
            price=21450.25,
            confidence=0.72,
            signal_type="unified_strategy",
        )
        opp.add_filter_result("session_filter", True, "Overnight allowed")
        opp.add_filter_result("key_level", False, "Too close to PWH", threshold=0.15, actual_value=0.02)
        
        tracker.log_opportunity(opp)
        
        # Update hypothetical outcome
        tracker.update_hypothetical_prices("opp-001", price_after_5m=21460.50)
        
        # Get filter effectiveness
        report = tracker.get_filter_effectiveness("session_filter", period_days=7)
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize opportunity tracker.
        
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path or (ensure_state_dir(None) / "opportunities.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_schema()
        
        logger.info(f"OpportunityTracker initialized: {self.db_path}")
    
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
            conn.executescript("""
                -- Main opportunities table
                CREATE TABLE IF NOT EXISTS signal_opportunities (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    price REAL NOT NULL,
                    confidence REAL NOT NULL,
                    signal_type TEXT NOT NULL,
                    
                    -- Full context as JSON
                    indicators_json TEXT,
                    key_levels_json TEXT,
                    
                    -- Market regime
                    regime TEXT,
                    regime_confidence REAL,
                    volume_ratio REAL,
                    atr REAL,
                    
                    -- Filter evaluation
                    filters_evaluated_json TEXT,
                    decision TEXT NOT NULL,
                    blocking_filter TEXT,
                    
                    -- Proposed trade
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    risk_reward REAL,
                    
                    -- Hypothetical outcome
                    hypothetical_entry_filled INTEGER DEFAULT 0,
                    price_after_1m REAL,
                    price_after_5m REAL,
                    price_after_15m REAL,
                    price_after_30m REAL,
                    would_have_won INTEGER,
                    hypothetical_pnl REAL,
                    hypothetical_exit_reason TEXT,
                    
                    -- Metadata
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_opportunities_timestamp 
                    ON signal_opportunities(timestamp);
                CREATE INDEX IF NOT EXISTS idx_opportunities_decision 
                    ON signal_opportunities(decision);
                CREATE INDEX IF NOT EXISTS idx_opportunities_blocking_filter 
                    ON signal_opportunities(blocking_filter);
                CREATE INDEX IF NOT EXISTS idx_opportunities_signal_type 
                    ON signal_opportunities(signal_type);
                CREATE INDEX IF NOT EXISTS idx_opportunities_would_have_won 
                    ON signal_opportunities(would_have_won);
                
                -- Filter analytics aggregation table
                CREATE TABLE IF NOT EXISTS filter_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filter_name TEXT NOT NULL,
                    time_bucket TEXT NOT NULL,
                    
                    -- Counts
                    signals_evaluated INTEGER DEFAULT 0,
                    signals_blocked INTEGER DEFAULT 0,
                    
                    -- Hypothetical outcomes
                    would_have_won INTEGER DEFAULT 0,
                    would_have_lost INTEGER DEFAULT 0,
                    
                    -- P&L impact
                    saved_pnl REAL DEFAULT 0.0,
                    missed_pnl REAL DEFAULT 0.0,
                    
                    -- Effectiveness score
                    effectiveness_score REAL,
                    
                    -- Metadata
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    
                    UNIQUE(filter_name, time_bucket)
                );
                
                CREATE INDEX IF NOT EXISTS idx_filter_analytics_name 
                    ON filter_analytics(filter_name);
                CREATE INDEX IF NOT EXISTS idx_filter_analytics_bucket 
                    ON filter_analytics(time_bucket);
                
                -- Pending price checks for hypothetical tracking
                CREATE TABLE IF NOT EXISTS pending_price_checks (
                    opportunity_id TEXT NOT NULL,
                    check_time TEXT NOT NULL,
                    interval_name TEXT NOT NULL,  -- 1m, 5m, 15m, 30m
                    completed INTEGER DEFAULT 0,
                    
                    PRIMARY KEY (opportunity_id, interval_name),
                    FOREIGN KEY (opportunity_id) REFERENCES signal_opportunities(id)
                );
            """)
            conn.commit()
    
    def log_opportunity(self, opportunity: SignalOpportunity) -> None:
        """
        Log a signal opportunity.
        
        Args:
            opportunity: The opportunity to log
        """
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO signal_opportunities (
                    id, timestamp, direction, price, confidence, signal_type,
                    indicators_json, key_levels_json,
                    regime, regime_confidence, volume_ratio, atr,
                    filters_evaluated_json, decision, blocking_filter,
                    entry_price, stop_loss, take_profit, risk_reward,
                    hypothetical_entry_filled, price_after_1m, price_after_5m,
                    price_after_15m, price_after_30m, would_have_won,
                    hypothetical_pnl, hypothetical_exit_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                opportunity.opportunity_id,
                opportunity.timestamp.isoformat(),
                opportunity.direction,
                opportunity.price,
                opportunity.confidence,
                opportunity.signal_type,
                json.dumps(opportunity.indicators),
                json.dumps(opportunity.key_levels),
                opportunity.regime,
                opportunity.regime_confidence,
                opportunity.volume_ratio,
                opportunity.atr,
                json.dumps([f.to_dict() for f in opportunity.filters_evaluated]),
                opportunity.decision.value,
                opportunity.blocking_filter,
                opportunity.entry_price,
                opportunity.stop_loss,
                opportunity.take_profit,
                opportunity.risk_reward,
                1 if opportunity.hypothetical_entry_filled else 0,
                opportunity.price_after_1m,
                opportunity.price_after_5m,
                opportunity.price_after_15m,
                opportunity.price_after_30m,
                1 if opportunity.would_have_won else (0 if opportunity.would_have_won is False else None),
                opportunity.hypothetical_pnl,
                opportunity.hypothetical_exit_reason,
            ))
            
            # Schedule price checks for blocked signals
            if opportunity.decision == OpportunityDecision.BLOCK:
                now = datetime.now(timezone.utc)
                for interval, delta in [
                    ("1m", timedelta(minutes=1)),
                    ("5m", timedelta(minutes=5)),
                    ("15m", timedelta(minutes=15)),
                    ("30m", timedelta(minutes=30)),
                ]:
                    check_time = (now + delta).isoformat()
                    conn.execute("""
                        INSERT OR IGNORE INTO pending_price_checks 
                        (opportunity_id, check_time, interval_name)
                        VALUES (?, ?, ?)
                    """, (opportunity.opportunity_id, check_time, interval))
            
            conn.commit()
        
        logger.debug(f"Logged opportunity {opportunity.opportunity_id}: {opportunity.decision.value}")
    
    def update_hypothetical_prices(
        self,
        opportunity_id: str,
        price_after_1m: Optional[float] = None,
        price_after_5m: Optional[float] = None,
        price_after_15m: Optional[float] = None,
        price_after_30m: Optional[float] = None,
    ) -> None:
        """
        Update hypothetical price data for an opportunity.
        
        Args:
            opportunity_id: ID of the opportunity
            price_after_*: Price at various intervals
        """
        with self._get_connection() as conn:
            updates = []
            values = []
            
            if price_after_1m is not None:
                updates.append("price_after_1m = ?")
                values.append(price_after_1m)
            if price_after_5m is not None:
                updates.append("price_after_5m = ?")
                values.append(price_after_5m)
            if price_after_15m is not None:
                updates.append("price_after_15m = ?")
                values.append(price_after_15m)
            if price_after_30m is not None:
                updates.append("price_after_30m = ?")
                values.append(price_after_30m)
            
            if updates:
                values.append(opportunity_id)
                conn.execute(
                    f"UPDATE signal_opportunities SET {', '.join(updates)} WHERE id = ?",
                    values
                )
                conn.commit()
    
    def calculate_hypothetical_outcome(
        self,
        opportunity_id: str,
    ) -> Optional[Tuple[bool, float, str]]:
        """
        Calculate the hypothetical outcome for a blocked signal.
        
        Returns:
            Tuple of (would_have_won, hypothetical_pnl, exit_reason) or None
        """
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT direction, entry_price, stop_loss, take_profit,
                       price_after_1m, price_after_5m, price_after_15m, price_after_30m
                FROM signal_opportunities
                WHERE id = ?
            """, (opportunity_id,)).fetchone()
            
            if not row:
                return None
            
            direction = row["direction"]
            entry = row["entry_price"]
            stop = row["stop_loss"]
            target = row["take_profit"]
            
            # Get all price points
            prices = []
            for col in ["price_after_1m", "price_after_5m", "price_after_15m", "price_after_30m"]:
                if row[col] is not None:
                    prices.append(row[col])
            
            if not prices or not entry or not stop or not target:
                return None
            
            # Simulate trade outcome
            would_have_won = False
            exit_reason = "timeout"
            exit_price = prices[-1]  # Last known price
            
            for price in prices:
                if direction == "LONG":
                    if price >= target:
                        would_have_won = True
                        exit_reason = "take_profit"
                        exit_price = target
                        break
                    elif price <= stop:
                        would_have_won = False
                        exit_reason = "stop_loss"
                        exit_price = stop
                        break
                else:  # SHORT
                    if price <= target:
                        would_have_won = True
                        exit_reason = "take_profit"
                        exit_price = target
                        break
                    elif price >= stop:
                        would_have_won = False
                        exit_reason = "stop_loss"
                        exit_price = stop
                        break
            
            # Calculate P&L (assuming 1 MNQ contract = $2/point)
            point_value = 2.0
            if direction == "LONG":
                pnl = (exit_price - entry) * point_value
            else:
                pnl = (entry - exit_price) * point_value
            
            # Update database
            conn.execute("""
                UPDATE signal_opportunities
                SET would_have_won = ?, hypothetical_pnl = ?, hypothetical_exit_reason = ?
                WHERE id = ?
            """, (1 if would_have_won else 0, pnl, exit_reason, opportunity_id))
            conn.commit()
            
            return (would_have_won, pnl, exit_reason)
    
    def get_pending_price_checks(self) -> list[Tuple[str, str]]:
        """
        Get opportunities that need price updates.
        
        Returns:
            List of (opportunity_id, interval_name) tuples
        """
        now = datetime.now(timezone.utc).isoformat()
        
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT opportunity_id, interval_name
                FROM pending_price_checks
                WHERE check_time <= ? AND completed = 0
                ORDER BY check_time
            """, (now,)).fetchall()
            
            return [(row["opportunity_id"], row["interval_name"]) for row in rows]
    
    def mark_price_check_complete(self, opportunity_id: str, interval_name: str) -> None:
        """Mark a price check as completed."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE pending_price_checks
                SET completed = 1
                WHERE opportunity_id = ? AND interval_name = ?
            """, (opportunity_id, interval_name))
            conn.commit()
    
    def get_filter_effectiveness(
        self,
        filter_name: str,
        period_days: int = 30,
    ) -> dict[str, Any]:
        """
        Get effectiveness metrics for a filter.
        
        Args:
            filter_name: Name of the filter
            period_days: Period to analyze
            
        Returns:
            Dictionary with effectiveness metrics
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
        
        with self._get_connection() as conn:
            # Get blocked signals by this filter
            blocked = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as would_have_won,
                       SUM(CASE WHEN would_have_won = 0 THEN 1 ELSE 0 END) as would_have_lost,
                       SUM(CASE WHEN would_have_won = 1 THEN hypothetical_pnl ELSE 0 END) as missed_pnl,
                       SUM(CASE WHEN would_have_won = 0 THEN ABS(hypothetical_pnl) ELSE 0 END) as saved_pnl
                FROM signal_opportunities
                WHERE blocking_filter = ?
                  AND timestamp >= ?
                  AND would_have_won IS NOT NULL
            """, (filter_name, cutoff)).fetchone()
            
            total = blocked["total"] or 0
            would_have_won = blocked["would_have_won"] or 0
            would_have_lost = blocked["would_have_lost"] or 0
            missed_pnl = blocked["missed_pnl"] or 0.0
            saved_pnl = blocked["saved_pnl"] or 0.0
            
            # Calculate metrics
            hypothetical_win_rate = would_have_won / total if total > 0 else 0.0
            net_pnl = saved_pnl - missed_pnl
            effectiveness = net_pnl / (saved_pnl + missed_pnl) if (saved_pnl + missed_pnl) > 0 else 0.0
            
            # Recommendation
            if total < 10:
                recommendation = "Insufficient data"
            elif hypothetical_win_rate > 0.55:
                recommendation = f"Consider relaxing (hypothetical WR: {hypothetical_win_rate:.0%})"
            elif effectiveness > 0.5:
                recommendation = "Keep (effective)"
            else:
                recommendation = "Review thresholds"
            
            return {
                "filter_name": filter_name,
                "period_days": period_days,
                "signals_blocked": total,
                "would_have_won": would_have_won,
                "would_have_lost": would_have_lost,
                "hypothetical_win_rate": hypothetical_win_rate,
                "saved_pnl": saved_pnl,
                "missed_pnl": missed_pnl,
                "net_pnl": net_pnl,
                "effectiveness_score": effectiveness,
                "recommendation": recommendation,
            }
    
    def get_all_filter_effectiveness(
        self,
        period_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get effectiveness for all filters."""
        with self._get_connection() as conn:
            filters = conn.execute("""
                SELECT DISTINCT blocking_filter
                FROM signal_opportunities
                WHERE blocking_filter IS NOT NULL
            """).fetchall()
            
            return [
                self.get_filter_effectiveness(row["blocking_filter"], period_days)
                for row in filters
            ]
    
    def get_opportunities(
        self,
        decision: Optional[OpportunityDecision] = None,
        signal_type: Optional[str] = None,
        blocking_filter: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Query opportunities with filters.
        
        Args:
            decision: Filter by decision type
            signal_type: Filter by signal type
            blocking_filter: Filter by blocking filter
            start_time: Start of time range
            end_time: End of time range
            limit: Maximum results
            
        Returns:
            List of opportunity dictionaries
        """
        conditions = []
        params = []
        
        if decision:
            conditions.append("decision = ?")
            params.append(decision.value)
        
        if signal_type:
            conditions.append("signal_type = ?")
            params.append(signal_type)
        
        if blocking_filter:
            conditions.append("blocking_filter = ?")
            params.append(blocking_filter)
        
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())
        
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)
        
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT * FROM signal_opportunities
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """, params).fetchall()
            
            return [dict(row) for row in rows]
    
    def get_summary(self, period_days: int = 7) -> dict[str, Any]:
        """Get a summary of opportunities over a period."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
        
        with self._get_connection() as conn:
            summary = conn.execute("""
                SELECT 
                    COUNT(*) as total_opportunities,
                    SUM(CASE WHEN decision = 'ALLOW' THEN 1 ELSE 0 END) as allowed,
                    SUM(CASE WHEN decision = 'BLOCK' THEN 1 ELSE 0 END) as blocked,
                    SUM(CASE WHEN decision = 'SHADOW' THEN 1 ELSE 0 END) as shadow,
                    SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as blocked_would_have_won,
                    SUM(CASE WHEN would_have_won = 0 THEN 1 ELSE 0 END) as blocked_would_have_lost,
                    SUM(CASE WHEN would_have_won = 1 THEN hypothetical_pnl ELSE 0 END) as missed_pnl,
                    SUM(CASE WHEN would_have_won = 0 THEN ABS(hypothetical_pnl) ELSE 0 END) as saved_pnl
                FROM signal_opportunities
                WHERE timestamp >= ?
            """, (cutoff,)).fetchone()
            
            return {
                "period_days": period_days,
                "total_opportunities": summary["total_opportunities"] or 0,
                "allowed": summary["allowed"] or 0,
                "blocked": summary["blocked"] or 0,
                "shadow": summary["shadow"] or 0,
                "blocked_would_have_won": summary["blocked_would_have_won"] or 0,
                "blocked_would_have_lost": summary["blocked_would_have_lost"] or 0,
                "blocked_hypothetical_win_rate": (
                    (summary["blocked_would_have_won"] or 0) / 
                    ((summary["blocked_would_have_won"] or 0) + (summary["blocked_would_have_lost"] or 0))
                    if (summary["blocked_would_have_won"] or 0) + (summary["blocked_would_have_lost"] or 0) > 0
                    else 0.0
                ),
                "missed_pnl": summary["missed_pnl"] or 0.0,
                "saved_pnl": summary["saved_pnl"] or 0.0,
                "net_filter_value": (summary["saved_pnl"] or 0.0) - (summary["missed_pnl"] or 0.0),
            }


# Global tracker instance
_tracker: Optional[OpportunityTracker] = None


def get_opportunity_tracker() -> OpportunityTracker:
    """Get the global opportunity tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = OpportunityTracker()
    return _tracker
