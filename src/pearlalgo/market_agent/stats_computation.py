"""
Shared Statistics Computation Module.

This module provides a single source of truth for computing daily and rolling
performance statistics. Both the API server and Telegram bot MUST use these
functions to ensure data consistency.

Key functions:
- compute_daily_stats(): Daily P&L from signals.jsonl since 6pm ET
- compute_performance_stats(): 24h/72h/30d rolling stats from performance.json
- get_trading_day_start(): Calculate current trading day start (6pm ET)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pearlalgo.utils.state_io import load_json_file, load_jsonl_file
from pearlalgo.utils.paths import parse_trade_timestamp_to_utc

from pearlalgo.utils.timezones import ET as _ET

# ---------------------------------------------------------------------------
# Simple caching mechanism
# ---------------------------------------------------------------------------

_cache: Dict[str, Tuple[float, Any]] = {}
_DEFAULT_CACHE_TTL = 5.0  # 5 seconds


def _get_cached(key: str, ttl: float = _DEFAULT_CACHE_TTL) -> Optional[Any]:
    """Get value from cache if not expired."""
    if key in _cache:
        cached_time, value = _cache[key]
        if time.time() - cached_time < ttl:
            return value
    return None


def _set_cached(key: str, value: Any) -> None:
    """Store value in cache with current timestamp."""
    _cache[key] = (time.time(), value)


def clear_stats_cache() -> None:
    """Clear all cached statistics. Call when data changes."""
    global _cache
    _cache = {}


# ---------------------------------------------------------------------------
# Trading Day Calculations
# ---------------------------------------------------------------------------

def get_trading_day_start() -> datetime:
    """
    Get the start of the current trading day (6pm ET).

    Futures trading day runs from 6pm ET to 6pm ET next day.
    Example: Trading day "Jan 29" starts at 6pm ET on Jan 28.

    Returns:
        UTC-aware datetime for the 6pm ET trading-day boundary.
    """
    now_et = datetime.now(_ET)

    if now_et.hour < 18:
        # Before 6pm ET - trading day started yesterday at 6pm
        trading_day_start = now_et.replace(
            hour=18, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
    else:
        # After 6pm ET - trading day started today at 6pm
        trading_day_start = now_et.replace(
            hour=18, minute=0, second=0, microsecond=0
        )

    return trading_day_start.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Daily Stats Computation
# ---------------------------------------------------------------------------

def compute_daily_stats(
    state_dir: Path,
    use_cache: bool = True,
    cache_ttl: float = _DEFAULT_CACHE_TTL,
) -> Dict[str, Any]:
    """
    Compute daily P&L and trade stats from signals.jsonl since 6pm ET.

    This is the single source of truth for daily statistics. Both the API
    server and Telegram bot use this function.

    Args:
        state_dir: Path to the agent state directory
        use_cache: Whether to use cached results (default True)
        cache_ttl: Cache time-to-live in seconds (default 5)

    Returns:
        Dict with keys:
            - daily_pnl: Total P&L for today (float, rounded to 2 decimals)
            - daily_trades: Number of trades today
            - daily_wins: Number of winning trades
            - daily_losses: Number of losing trades
            - win_rate: Win rate as percentage (0-100)
    """
    cache_key = f"daily_stats:{state_dir}"

    if use_cache:
        cached = _get_cached(cache_key, cache_ttl)
        if cached is not None:
            return cached

    signals_file = state_dir / "signals.jsonl"
    if not signals_file.exists():
        result = {
            "daily_pnl": 0.0,
            "daily_trades": 0,
            "daily_wins": 0,
            "daily_losses": 0,
            "win_rate": 0.0,
        }
        _set_cached(cache_key, result)
        return result

    # Get trading day start (6pm ET)
    trading_day_start = get_trading_day_start()

    daily_pnl = 0.0
    daily_wins = 0
    daily_losses = 0

    try:
        signals = load_jsonl_file(signals_file, max_lines=2000)
        for s in signals:
            if s.get("status") != "exited":
                continue

            # Check if trade exited after trading day start (6pm ET)
            exit_time_str = s.get("exit_time") or s.get("timestamp")
            if not exit_time_str:
                continue

            try:
                exit_time = parse_trade_timestamp_to_utc(str(exit_time_str))
                if exit_time < trading_day_start:
                    continue
            except (ValueError, AttributeError):
                continue

            # Count this trade
            pnl = s.get("pnl", 0.0)
            if pnl is not None:
                daily_pnl += pnl
                if pnl >= 0:
                    daily_wins += 1
                else:
                    daily_losses += 1
    except Exception as e:
        from pearlalgo.utils.logger import logger
        logger.warning(f"Daily stats computation failed: {e}", exc_info=True)

    daily_trades = daily_wins + daily_losses
    win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0.0

    result = {
        "daily_pnl": round(daily_pnl, 2),
        "daily_trades": daily_trades,
        "daily_wins": daily_wins,
        "daily_losses": daily_losses,
        "win_rate": round(win_rate, 1),
    }

    _set_cached(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Rolling Performance Stats Computation
# ---------------------------------------------------------------------------

def compute_performance_stats(
    state_dir: Path,
    use_cache: bool = True,
    cache_ttl: float = _DEFAULT_CACHE_TTL,
) -> Dict[str, Any]:
    """
    Compute performance stats for 24h, 72h, and 30d periods.

    Reads from performance.json which contains all completed trades.

    Args:
        state_dir: Path to the agent state directory
        use_cache: Whether to use cached results (default True)
        cache_ttl: Cache time-to-live in seconds (default 5)

    Returns:
        Dict with period keys (24h, 72h, 30d), each containing:
            - pnl: Total P&L for the period
            - trades: Number of trades
            - wins: Number of winning trades
            - losses: Number of losing trades
            - win_rate: Win rate as percentage
            - streak (24h only): Current win/loss streak count
            - streak_type (24h only): "win", "loss", or "none"
    """
    cache_key = f"performance_stats:{state_dir}"

    if use_cache:
        cached = _get_cached(cache_key, cache_ttl)
        if cached is not None:
            return cached

    empty_stats = {
        "pnl": 0.0,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
    }

    performance_file = state_dir / "performance.json"
    if not performance_file.exists():
        result = {
            "24h": {**empty_stats, "streak": 0, "streak_type": "none"},
            "72h": empty_stats.copy(),
            "30d": empty_stats.copy(),
        }
        _set_cached(cache_key, result)
        return result

    now = datetime.now(timezone.utc)
    cutoffs = {
        "24h": now - timedelta(hours=24),
        "72h": now - timedelta(hours=72),
        "30d": now - timedelta(days=30),
    }

    stats: Dict[str, Dict[str, Any]] = {
        period: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
        for period in cutoffs
    }

    recent_trades_24h: List[Tuple[datetime, bool]] = []

    try:
        data = load_json_file(performance_file)
        if not isinstance(data, list):
            data = []

        for trade in data:
            exit_time_str = trade.get("exit_time")
            if not exit_time_str:
                continue
            try:
                exit_time = parse_trade_timestamp_to_utc(str(exit_time_str))
            except (ValueError, TypeError):
                continue

            pnl = trade.get("pnl", 0.0) or 0.0
            is_win = trade.get("is_win", pnl > 0)

            for period, cutoff in cutoffs.items():
                if exit_time >= cutoff:
                    stats[period]["pnl"] += pnl
                    stats[period]["trades"] += 1
                    if is_win:
                        stats[period]["wins"] += 1
                    else:
                        stats[period]["losses"] += 1

            # Track for streak calculation
            if exit_time >= cutoffs["24h"]:
                recent_trades_24h.append((exit_time, is_win))
    except Exception as e:
        from pearlalgo.utils.logger import logger
        logger.warning(f"Performance stats computation failed: {e}", exc_info=True)

    # Calculate win rates
    for period in stats:
        total = stats[period]["trades"]
        stats[period]["pnl"] = round(stats[period]["pnl"], 2)
        stats[period]["win_rate"] = (
            round(stats[period]["wins"] / total * 100, 1) if total > 0 else 0.0
        )

    # Compute current streak for 24h
    streak = 0
    streak_type = "none"
    if recent_trades_24h:
        recent_trades_24h.sort(key=lambda x: x[0], reverse=True)
        streak_type = "win" if recent_trades_24h[0][1] else "loss"
        for _, is_win in recent_trades_24h:
            if (streak_type == "win" and is_win) or (
                streak_type == "loss" and not is_win
            ):
                streak += 1
            else:
                break

    stats["24h"]["streak"] = streak
    stats["24h"]["streak_type"] = streak_type

    _set_cached(cache_key, stats)
    return stats
