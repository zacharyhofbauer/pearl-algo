"""
Pearl AI Data Access - Trade Database RAG Layer

Read-only access to the trade database for grounded AI responses.
Enables Pearl to answer questions about historical performance,
find similar trades, and analyze patterns.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class TradeDataAccess:
    """
    Read-only access to trade database for Pearl AI RAG.

    Provides safe, queryable access to historical trades
    without exposing write operations.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize data access layer.

        Args:
            db_path: Path to SQLite database. If None, uses default location.
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            # Default to state directory
            from pathlib import Path
            state_dir = Path.home() / ".pearl" / "state"
            self.db_path = state_dir / "trades.db"

        self._verify_database()

    def _verify_database(self) -> bool:
        """Verify database exists and is accessible."""
        if not self.db_path.exists():
            logger.warning(f"Trade database not found: {self.db_path}")
            return False
        return True

    @contextmanager
    def _connection(self):
        """Get read-only database connection."""
        # Use URI with mode=ro for read-only
        conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=5.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def is_available(self) -> bool:
        """Check if database is available."""
        return self.db_path.exists()

    def get_regime_performance(
        self,
        regime: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get performance stats for a specific market regime.

        Args:
            regime: Market regime (e.g., "trending", "ranging", "volatile")
            days: Number of days to look back

        Returns:
            Performance dict with win rate, P&L, trade count
        """
        if not self.is_available():
            return {}

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                        SUM(pnl) as total_pnl,
                        AVG(pnl) as avg_pnl,
                        MIN(pnl) as worst_trade,
                        MAX(pnl) as best_trade,
                        AVG(hold_duration_minutes) as avg_hold_minutes
                    FROM trades
                    WHERE regime = ?
                    AND exit_time > datetime('now', ?)
                """, (regime, f'-{days} days'))
                row = cursor.fetchone()

                if not row or row["total_trades"] == 0:
                    return {"total_trades": 0, "regime": regime}

                total = row["total_trades"]
                wins = row["wins"] or 0

                return {
                    "regime": regime,
                    "days": days,
                    "total_trades": total,
                    "wins": wins,
                    "losses": total - wins,
                    "win_rate": round(wins / total, 3) if total > 0 else 0,
                    "total_pnl": round(row["total_pnl"] or 0, 2),
                    "avg_pnl": round(row["avg_pnl"] or 0, 2),
                    "best_trade": round(row["best_trade"] or 0, 2),
                    "worst_trade": round(row["worst_trade"] or 0, 2),
                    "avg_hold_minutes": round(row["avg_hold_minutes"] or 0, 1),
                }

        except Exception as e:
            logger.error(f"Error querying regime performance: {e}")
            return {}

    def get_similar_trades(
        self,
        direction: str,
        regime: Optional[str] = None,
        signal_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Find historical trades similar to current context.

        Args:
            direction: Trade direction ("long" or "short")
            regime: Optional market regime filter
            signal_type: Optional signal type filter
            limit: Maximum number of trades to return

        Returns:
            List of similar trade dicts
        """
        if not self.is_available():
            return []

        try:
            query = """
                SELECT
                    signal_id, direction, entry_price, exit_price,
                    pnl, is_win, exit_reason, regime, signal_type,
                    hold_duration_minutes, entry_time, exit_time
                FROM trades
                WHERE direction = ?
            """
            params: List[Any] = [direction.lower()]

            if regime:
                query += " AND regime = ?"
                params.append(regime)

            if signal_type:
                query += " AND signal_type = ?"
                params.append(signal_type)

            query += " ORDER BY exit_time DESC LIMIT ?"
            params.append(limit)

            with self._connection() as conn:
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

                return [
                    {
                        "signal_id": row["signal_id"],
                        "direction": row["direction"],
                        "entry_price": row["entry_price"],
                        "exit_price": row["exit_price"],
                        "pnl": round(row["pnl"], 2),
                        "is_win": bool(row["is_win"]),
                        "exit_reason": row["exit_reason"],
                        "regime": row["regime"],
                        "signal_type": row["signal_type"],
                        "hold_minutes": round(row["hold_duration_minutes"] or 0, 1),
                        "entry_time": row["entry_time"],
                        "exit_time": row["exit_time"],
                    }
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Error querying similar trades: {e}")
            return []

    def get_performance_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        Get overall performance summary.

        Args:
            days: Number of days to look back

        Returns:
            Summary dict with P&L, win rate, trade count
        """
        if not self.is_available():
            return {}

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                        SUM(pnl) as total_pnl,
                        AVG(pnl) as avg_pnl,
                        MAX(pnl) as best_trade,
                        MIN(pnl) as worst_trade,
                        AVG(hold_duration_minutes) as avg_hold_minutes,
                        COUNT(DISTINCT regime) as regime_count,
                        COUNT(DISTINCT signal_type) as signal_type_count
                    FROM trades
                    WHERE exit_time > datetime('now', ?)
                """, (f'-{days} days',))
                row = cursor.fetchone()

                if not row or row["total"] == 0:
                    return {"total_trades": 0, "days": days}

                total = row["total"]
                wins = row["wins"] or 0

                return {
                    "days": days,
                    "total_trades": total,
                    "wins": wins,
                    "losses": total - wins,
                    "win_rate": round(wins / total, 3) if total > 0 else 0,
                    "total_pnl": round(row["total_pnl"] or 0, 2),
                    "avg_pnl": round(row["avg_pnl"] or 0, 2),
                    "best_trade": round(row["best_trade"] or 0, 2),
                    "worst_trade": round(row["worst_trade"] or 0, 2),
                    "avg_hold_minutes": round(row["avg_hold_minutes"] or 0, 1),
                    "regime_count": row["regime_count"],
                    "signal_type_count": row["signal_type_count"],
                }

        except Exception as e:
            logger.error(f"Error querying performance summary: {e}")
            return {}

    def get_direction_performance(
        self,
        days: int = 30,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get performance breakdown by direction (long vs short).

        Args:
            days: Number of days to look back

        Returns:
            Dict with "long" and "short" performance stats
        """
        if not self.is_available():
            return {}

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT
                        direction,
                        COUNT(*) as total,
                        SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                        SUM(pnl) as total_pnl,
                        AVG(pnl) as avg_pnl
                    FROM trades
                    WHERE exit_time > datetime('now', ?)
                    GROUP BY direction
                """, (f'-{days} days',))
                rows = cursor.fetchall()

                result = {}
                for row in rows:
                    direction = row["direction"]
                    total = row["total"]
                    wins = row["wins"] or 0
                    result[direction] = {
                        "total_trades": total,
                        "wins": wins,
                        "losses": total - wins,
                        "win_rate": round(wins / total, 3) if total > 0 else 0,
                        "total_pnl": round(row["total_pnl"] or 0, 2),
                        "avg_pnl": round(row["avg_pnl"] or 0, 2),
                    }

                return result

        except Exception as e:
            logger.error(f"Error querying direction performance: {e}")
            return {}

    def get_hourly_performance(
        self,
        days: int = 30,
    ) -> Dict[int, Dict[str, Any]]:
        """
        Get performance breakdown by hour of day.

        Args:
            days: Number of days to look back

        Returns:
            Dict with hour (0-23) as key and performance stats
        """
        if not self.is_available():
            return {}

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT
                        CAST(strftime('%H', entry_time) AS INTEGER) as hour,
                        COUNT(*) as total,
                        SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                        SUM(pnl) as total_pnl,
                        AVG(pnl) as avg_pnl
                    FROM trades
                    WHERE exit_time > datetime('now', ?)
                    GROUP BY hour
                    ORDER BY hour
                """, (f'-{days} days',))
                rows = cursor.fetchall()

                result = {}
                for row in rows:
                    hour = row["hour"]
                    total = row["total"]
                    wins = row["wins"] or 0
                    result[hour] = {
                        "total_trades": total,
                        "wins": wins,
                        "win_rate": round(wins / total, 3) if total > 0 else 0,
                        "total_pnl": round(row["total_pnl"] or 0, 2),
                        "avg_pnl": round(row["avg_pnl"] or 0, 2),
                    }

                return result

        except Exception as e:
            logger.error(f"Error querying hourly performance: {e}")
            return {}

    def get_recent_trades(
        self,
        limit: int = 10,
        direction: Optional[str] = None,
        is_win: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent trades for context.

        Args:
            limit: Maximum number of trades
            direction: Optional direction filter
            is_win: Optional win/loss filter

        Returns:
            List of recent trade dicts
        """
        if not self.is_available():
            return []

        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params: List[Any] = []

            if direction:
                query += " AND direction = ?"
                params.append(direction.lower())

            if is_win is not None:
                query += " AND is_win = ?"
                params.append(1 if is_win else 0)

            query += " ORDER BY exit_time DESC LIMIT ?"
            params.append(limit)

            with self._connection() as conn:
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error querying recent trades: {e}")
            return []

    def get_regime_breakdown(self, days: int = 30) -> Dict[str, Dict[str, Any]]:
        """
        Get performance breakdown by market regime.

        Args:
            days: Number of days to look back

        Returns:
            Dict with regime name as key and performance stats
        """
        if not self.is_available():
            return {}

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT
                        regime,
                        COUNT(*) as total,
                        SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                        SUM(pnl) as total_pnl,
                        AVG(pnl) as avg_pnl
                    FROM trades
                    WHERE regime IS NOT NULL
                    AND exit_time > datetime('now', ?)
                    GROUP BY regime
                    ORDER BY total DESC
                """, (f'-{days} days',))
                rows = cursor.fetchall()

                result = {}
                for row in rows:
                    regime = row["regime"]
                    total = row["total"]
                    wins = row["wins"] or 0
                    result[regime] = {
                        "total_trades": total,
                        "wins": wins,
                        "losses": total - wins,
                        "win_rate": round(wins / total, 3) if total > 0 else 0,
                        "total_pnl": round(row["total_pnl"] or 0, 2),
                        "avg_pnl": round(row["avg_pnl"] or 0, 2),
                    }

                return result

        except Exception as e:
            logger.error(f"Error querying regime breakdown: {e}")
            return {}

    def get_streak_stats(self, days: int = 30) -> Dict[str, Any]:
        """
        Get win/loss streak statistics.

        Args:
            days: Number of days to look back

        Returns:
            Dict with streak statistics
        """
        if not self.is_available():
            return {}

        try:
            with self._connection() as conn:
                # Get trades ordered by time
                cursor = conn.execute("""
                    SELECT is_win FROM trades
                    WHERE exit_time > datetime('now', ?)
                    ORDER BY exit_time ASC
                """, (f'-{days} days',))
                rows = cursor.fetchall()

                if not rows:
                    return {"max_win_streak": 0, "max_loss_streak": 0}

                # Calculate streaks
                max_win_streak = 0
                max_loss_streak = 0
                current_streak = 0
                current_is_win = None

                for row in rows:
                    is_win = bool(row["is_win"])

                    if is_win == current_is_win:
                        current_streak += 1
                    else:
                        # Streak ended
                        if current_is_win is True:
                            max_win_streak = max(max_win_streak, current_streak)
                        elif current_is_win is False:
                            max_loss_streak = max(max_loss_streak, current_streak)

                        current_is_win = is_win
                        current_streak = 1

                # Check final streak
                if current_is_win is True:
                    max_win_streak = max(max_win_streak, current_streak)
                elif current_is_win is False:
                    max_loss_streak = max(max_loss_streak, current_streak)

                return {
                    "max_win_streak": max_win_streak,
                    "max_loss_streak": max_loss_streak,
                    "total_trades": len(rows),
                }

        except Exception as e:
            logger.error(f"Error calculating streak stats: {e}")
            return {}

    def format_for_context(
        self,
        query: str,
        current_state: Dict[str, Any],
    ) -> str:
        """
        Format relevant trade data for LLM context based on query.

        Args:
            query: User's query to determine what data is relevant
            current_state: Current trading state

        Returns:
            Formatted string with relevant historical data
        """
        query_lower = query.lower()
        context_parts = []

        # Detect what data is relevant
        regime = current_state.get("market_regime", {}).get("regime")

        # If asking about regime performance
        if regime and any(word in query_lower for word in ["regime", "market", "trending", "ranging"]):
            perf = self.get_regime_performance(regime, days=30)
            if perf.get("total_trades", 0) > 0:
                wr = perf["win_rate"] * 100
                context_parts.append(
                    f"In {regime} markets (last 30d): {perf['wins']}/{perf['total_trades']} wins "
                    f"({wr:.0f}%), avg P&L ${perf['avg_pnl']:.2f}"
                )

        # If asking about direction
        if any(word in query_lower for word in ["long", "short", "direction", "side"]):
            dir_perf = self.get_direction_performance(days=30)
            for direction, stats in dir_perf.items():
                wr = stats["win_rate"] * 100
                context_parts.append(
                    f"{direction.upper()} trades: {stats['wins']}/{stats['total_trades']} wins "
                    f"({wr:.0f}%), total ${stats['total_pnl']:.2f}"
                )

        # If asking about patterns or similar trades
        if any(word in query_lower for word in ["similar", "pattern", "like this", "before"]):
            direction = current_state.get("last_trade_direction", "")
            if direction:
                similar = self.get_similar_trades(direction, regime=regime, limit=3)
                if similar:
                    context_parts.append("Similar recent trades:")
                    for t in similar:
                        result = "WIN" if t["is_win"] else "LOSS"
                        context_parts.append(
                            f"  - {t['direction'].upper()} ${t['pnl']:+.2f} ({result}, {t['exit_reason']})"
                        )

        # If asking about performance over time
        if any(word in query_lower for word in ["today", "week", "performance", "how am i"]):
            # Get 7-day summary
            summary = self.get_performance_summary(days=7)
            if summary.get("total_trades", 0) > 0:
                wr = summary["win_rate"] * 100
                context_parts.append(
                    f"Last 7 days: {summary['total_trades']} trades, {wr:.0f}% win rate, "
                    f"${summary['total_pnl']:.2f} total P&L"
                )

        # If asking about time of day
        if any(word in query_lower for word in ["hour", "morning", "afternoon", "time", "when"]):
            hourly = self.get_hourly_performance(days=30)
            if hourly:
                # Find best and worst hours
                best_hour = max(hourly.items(), key=lambda x: x[1].get("avg_pnl", 0))
                worst_hour = min(hourly.items(), key=lambda x: x[1].get("avg_pnl", 0))
                context_parts.append(
                    f"Best hour: {best_hour[0]}:00 (avg ${best_hour[1]['avg_pnl']:.2f}), "
                    f"Worst hour: {worst_hour[0]}:00 (avg ${worst_hour[1]['avg_pnl']:.2f})"
                )

        return "\n".join(context_parts) if context_parts else ""
