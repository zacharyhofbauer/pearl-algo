"""
Key Level Tracker - Track and learn from key level interactions.

This module tracks every interaction with key levels (PDH, PWH, DO, etc.)
and builds probabilistic models of level behavior to improve trading decisions.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Generator, Optional
from enum import Enum

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir


class LevelType(Enum):
    """Types of key levels."""
    DO = "DO"
    PDH = "PDH"
    PDL = "PDL"
    PDM = "PDM"
    WO = "WO"
    PWH = "PWH"
    PWL = "PWL"
    PWM = "PWM"
    MO = "MO"
    PMH = "PMH"
    PML = "PML"
    PMM = "PMM"
    VWAP = "VWAP"
    EMA50 = "EMA50"
    EMA200 = "EMA200"


class InteractionType(Enum):
    """Types of interactions with key levels."""
    TOUCH = "touch"
    BOUNCE = "bounce"
    BREAKOUT = "breakout"
    FALSE_BREAKOUT = "false_breakout"
    RETEST = "retest"


@dataclass
class LevelInteraction:
    """Record of an interaction with a key level."""
    id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    level_type: LevelType = LevelType.PDH
    level_price: float = 0.0
    interaction_type: InteractionType = InteractionType.TOUCH
    approach_direction: str = ""
    price_at_touch: float = 0.0
    price_after_5m: Optional[float] = None
    price_after_15m: Optional[float] = None
    price_after_30m: Optional[float] = None
    regime: str = ""
    volume_ratio: float = 0.0
    atr: float = 0.0
    rsi: float = 0.0
    outcome_direction: str = ""
    outcome_magnitude: float = 0.0
    trade_id: Optional[str] = None
    trade_pnl: Optional[float] = None


@dataclass
class LevelAnalytics:
    """Analytics for a specific key level type."""
    level_type: LevelType
    total_touches: int = 0
    total_bounces: int = 0
    total_breakouts: int = 0
    total_false_breakouts: int = 0
    bounce_probability: float = 0.5
    breakout_probability: float = 0.5
    trades_at_level: int = 0
    trades_won: int = 0
    total_pnl: float = 0.0
    sample_count: int = 0
    confidence: float = 0.0

    def update_probabilities(self) -> None:
        total = self.total_bounces + self.total_breakouts
        if total > 0:
            self.bounce_probability = self.total_bounces / total
            self.breakout_probability = self.total_breakouts / total
        self.sample_count = self.total_touches
        self.confidence = min(0.9, self.sample_count / 50)


class KeyLevelTracker:
    """Tracks key level interactions and learns level behavior."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (ensure_state_dir(None) / "key_levels.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"KeyLevelTracker initialized: {self.db_path}")

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS level_interactions (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    level_type TEXT NOT NULL,
                    level_price REAL NOT NULL,
                    interaction_type TEXT NOT NULL,
                    approach_direction TEXT,
                    price_at_touch REAL,
                    price_after_5m REAL,
                    price_after_15m REAL,
                    price_after_30m REAL,
                    regime TEXT,
                    volume_ratio REAL,
                    atr REAL,
                    rsi REAL,
                    outcome_direction TEXT,
                    outcome_magnitude REAL,
                    trade_id TEXT,
                    trade_pnl REAL
                );
                CREATE INDEX IF NOT EXISTS idx_level_type ON level_interactions(level_type);
                CREATE INDEX IF NOT EXISTS idx_timestamp ON level_interactions(timestamp);

                CREATE TABLE IF NOT EXISTS level_analytics_cache (
                    level_type TEXT PRIMARY KEY,
                    total_touches INTEGER DEFAULT 0,
                    total_bounces INTEGER DEFAULT 0,
                    total_breakouts INTEGER DEFAULT 0,
                    total_false_breakouts INTEGER DEFAULT 0,
                    trades_at_level INTEGER DEFAULT 0,
                    trades_won INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0.0,
                    last_updated TEXT
                );
            """)
            conn.commit()

    def log_interaction(self, interaction: LevelInteraction) -> str:
        if not interaction.id:
            interaction.id = f"lvl-{uuid.uuid4().hex[:12]}"
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO level_interactions (
                    id, timestamp, level_type, level_price, interaction_type,
                    approach_direction, price_at_touch, regime, volume_ratio,
                    atr, rsi, outcome_direction, outcome_magnitude, trade_id, trade_pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                interaction.id, interaction.timestamp.isoformat(),
                interaction.level_type.value, interaction.level_price,
                interaction.interaction_type.value, interaction.approach_direction,
                interaction.price_at_touch, interaction.regime, interaction.volume_ratio,
                interaction.atr, interaction.rsi, interaction.outcome_direction,
                interaction.outcome_magnitude, interaction.trade_id, interaction.trade_pnl,
            ))
            self._update_cache(conn, interaction.level_type)
            conn.commit()
        return interaction.id

    def _update_cache(self, conn: sqlite3.Connection, level_type: LevelType) -> None:
        stats = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN interaction_type = 'bounce' THEN 1 ELSE 0 END) as bounces,
                   SUM(CASE WHEN interaction_type = 'breakout' THEN 1 ELSE 0 END) as breakouts,
                   SUM(CASE WHEN interaction_type = 'false_breakout' THEN 1 ELSE 0 END) as false_breakouts,
                   SUM(CASE WHEN trade_id IS NOT NULL THEN 1 ELSE 0 END) as trades,
                   SUM(CASE WHEN trade_pnl > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(COALESCE(trade_pnl, 0)) as pnl
            FROM level_interactions WHERE level_type = ?
        """, (level_type.value,)).fetchone()
        conn.execute("""
            INSERT OR REPLACE INTO level_analytics_cache (
                level_type, total_touches, total_bounces, total_breakouts,
                total_false_breakouts, trades_at_level, trades_won, total_pnl, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (level_type.value, stats["total"], stats["bounces"], stats["breakouts"],
              stats["false_breakouts"], stats["trades"], stats["wins"], stats["pnl"],
              datetime.now(timezone.utc).isoformat()))

    def get_level_analytics(self, level_type: LevelType) -> LevelAnalytics:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM level_analytics_cache WHERE level_type = ?",
                (level_type.value,)
            ).fetchone()
            if not row:
                return LevelAnalytics(level_type=level_type)
            analytics = LevelAnalytics(
                level_type=level_type,
                total_touches=row["total_touches"],
                total_bounces=row["total_bounces"],
                total_breakouts=row["total_breakouts"],
                total_false_breakouts=row["total_false_breakouts"],
                trades_at_level=row["trades_at_level"],
                trades_won=row["trades_won"],
                total_pnl=row["total_pnl"],
            )
            analytics.update_probabilities()
            return analytics

    def get_confidence_adjustment(
        self, level_type: LevelType, approach_direction: str, signal_direction: str
    ) -> float:
        """Get confidence adjustment based on level behavior history."""
        analytics = self.get_level_analytics(level_type)
        if analytics.sample_count < 5:
            return 0.0
        if approach_direction == "from_below":
            if signal_direction == "LONG":
                adj = -(analytics.bounce_probability - 0.5) * analytics.confidence
            else:
                adj = (analytics.bounce_probability - 0.5) * analytics.confidence
        else:
            if signal_direction == "LONG":
                adj = (analytics.bounce_probability - 0.5) * analytics.confidence
            else:
                adj = -(analytics.bounce_probability - 0.5) * analytics.confidence
        return max(-0.2, min(0.2, adj))

    def get_summary(self, period_days: int = 30) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT level_type, COUNT(*) as total,
                       SUM(CASE WHEN interaction_type = 'bounce' THEN 1 ELSE 0 END) as bounces,
                       SUM(COALESCE(trade_pnl, 0)) as pnl
                FROM level_interactions WHERE timestamp >= ?
                GROUP BY level_type ORDER BY total DESC
            """, (cutoff,)).fetchall()
            return {
                "period_days": period_days,
                "levels": [{
                    "type": row["level_type"],
                    "interactions": row["total"],
                    "bounce_rate": row["bounces"] / row["total"] if row["total"] > 0 else 0,
                    "pnl": row["pnl"],
                } for row in rows],
            }


_tracker: Optional[KeyLevelTracker] = None

def get_key_level_tracker() -> KeyLevelTracker:
    global _tracker
    if _tracker is None:
        _tracker = KeyLevelTracker()
    return _tracker
