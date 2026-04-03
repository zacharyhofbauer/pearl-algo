"""Extracted from server.py — computes multi-period performance statistics."""

from __future__ import annotations

import logging
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pearlalgo.utils.timezones import ET as _ET

logger = logging.getLogger(__name__)


def _coerce_utc(dt) -> Any:
    """Normalize naive-ET or aware datetimes to UTC-aware datetimes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_ET).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_performance_stats(
    state_dir: Path,
    *,
    read_json_sync,
    read_state_for_dir,
    get_start_balance,
    get_tradovate_state,
    get_paired_tradovate_trades,
    is_tv_paper_account,
    now_et_naive,
    parse_ts,
    get_challenge_status,
    get_previous_trading_day_bounds,
    tradovate_performance_for_period,
) -> Dict[str, Any]:
    """Compute performance stats for yesterday, 24h, 72h, and 30d periods.

    When Tradovate live account data is available (Tradovate Paper), use the broker's
    equity-based P&L as the single source of truth for ALL periods.  This
    avoids the mismatch between virtual exit grading and real fills.

    All helper callables are injected to avoid circular imports with server.py.
    """
    # --- Read performance.json once for all code paths below ---
    performance_file = state_dir / "performance.json"
    perf_data: Optional[list] = None  # None = missing or invalid
    try:
        _raw = read_json_sync(performance_file)
        if isinstance(_raw, list):
            perf_data = _raw
    except Exception:
        logger.debug("Failed to read/parse performance.json", exc_info=True)

    # Priority 1: Tradovate live data (Tradovate Paper accounts)
    try:
        _sd = read_state_for_dir(state_dir)
        if _sd:
            tv = _sd.get("tradovate_account")
            if tv and isinstance(tv, dict) and tv.get("equity"):
                start_balance = get_start_balance(state_dir)
                equity = float(tv.get("equity", 0))
                open_pnl = float(tv.get("open_pnl", 0))
                pnl = round(equity - start_balance, 2)
                # Build a single stat block used for every period
                tv_stats = {"pnl": pnl, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                            "tradovate_equity": round(equity, 2), "tradovate_open_pnl": round(open_pnl, 2)}
                # Use Tradovate fills for trade counts (not performance.json which has virtual data)
                try:
                    _, tv_fills = get_tradovate_state(state_dir)
                    if tv_fills:
                        paired = get_paired_tradovate_trades(state_dir, tv_fills)
                        tv_stats["trades"] = len(paired)
                        tv_stats["wins"] = sum(1 for t in paired if (t.get("pnl") or 0) > 0)
                        tv_stats["losses"] = len(paired) - tv_stats["wins"]
                        tv_stats["win_rate"] = round(tv_stats["wins"] / len(paired) * 100, 1) if paired else 0.0
                except Exception as e:
                    logger.debug(f"Tradovate fills unavailable for trade counts, falling back to performance.json: {e}")
                    # Fallback to performance.json if Tradovate fills unavailable
                    if tv_stats["trades"] == 0 and perf_data:
                        tv_stats["trades"] = len(perf_data)
                        tv_stats["wins"] = sum(1 for t in perf_data if (t.get("pnl") or 0) > 0)
                        tv_stats["losses"] = len(perf_data) - tv_stats["wins"]
                        tv_stats["win_rate"] = round(tv_stats["wins"] / len(perf_data) * 100, 1)
                return {p: tv_stats.copy() for p in ("yesterday", "24h", "72h", "30d")}
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # Priority 2: Tradovate fills (TV Paper accounts without live equity)
    # This avoids falling through to performance.json which may contain
    # duplicated/corrupted virtual exit data.
    try:
        if is_tv_paper_account(state_dir):
            _, tv_fills = get_tradovate_state(state_dir)
            if tv_fills:
                paired = get_paired_tradovate_trades(state_dir, tv_fills)
                now_utc = _coerce_utc(now_et_naive())
                prev_day_s, prev_day_e = get_previous_trading_day_bounds()
                prev_day_s = _coerce_utc(prev_day_s)
                prev_day_e = _coerce_utc(prev_day_e)
                fills_stats = {
                    "yesterday": tradovate_performance_for_period(tv_fills, prev_day_s, prev_day_e, paired_trades=paired),
                    "24h": tradovate_performance_for_period(tv_fills, now_utc - timedelta(hours=24), paired_trades=paired),
                    "72h": tradovate_performance_for_period(tv_fills, now_utc - timedelta(hours=72), paired_trades=paired),
                    "30d": tradovate_performance_for_period(tv_fills, now_utc - timedelta(days=30), paired_trades=paired),
                }
                return fills_stats
    except Exception as e:
        logger.debug(f"Tradovate fills fallback failed: {e}")

    # Tradovate Paper: if both live equity and fills failed, return zeros
    # rather than falling through to performance.json which mixes virtual + real trades.
    if is_tv_paper_account(state_dir):
        logger.warning("TV Paper: both live equity and fills unavailable — returning zero performance stats")
        empty_stats = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
        return {p: empty_stats.copy() for p in ("yesterday", "24h", "72h", "30d")}

    if perf_data is None:
        empty_stats = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
        result = {"yesterday": empty_stats.copy(), "24h": empty_stats.copy(), "72h": empty_stats.copy(), "30d": empty_stats.copy()}
        # Fallback: populate from challenge_state.json when performance.json is missing
        try:
            challenge = get_challenge_status(state_dir)
            if challenge and challenge.get("trades", 0) > 0:
                ch_pnl = round(challenge.get("pnl", 0.0), 2)
                ch_trades = challenge.get("trades", 0)
                ch_wins = challenge.get("wins", 0)
                ch_losses = ch_trades - ch_wins
                ch_wr = round(ch_wins / ch_trades * 100, 1) if ch_trades > 0 else 0.0
                ch_stats = {"pnl": ch_pnl, "trades": ch_trades, "wins": ch_wins, "losses": ch_losses, "win_rate": ch_wr}
                for period in result:
                    result[period] = ch_stats.copy()
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
        return result

    now = _coerce_utc(now_et_naive())
    prev_day_start, prev_day_end = get_previous_trading_day_bounds()
    prev_day_start = _coerce_utc(prev_day_start)
    prev_day_end = _coerce_utc(prev_day_end)

    cutoffs = {
        "24h": now - timedelta(hours=24),
        "72h": now - timedelta(hours=72),
        "30d": now - timedelta(days=30),
    }

    stats = {period: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0} for period in cutoffs}
    stats["yesterday"] = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}

    try:
        data = perf_data if perf_data is not None else []

        for trade in data:
            exit_time_str = trade.get("exit_time")
            if not exit_time_str:
                continue
            try:
                exit_time = _coerce_utc(parse_ts(exit_time_str))
            except (ValueError, TypeError):
                continue

            pnl = trade.get("pnl", 0.0) or 0.0
            is_win = trade.get("is_win", pnl > 0)

            # Check rolling periods (24h, 72h, 30d)
            for period, cutoff in cutoffs.items():
                if exit_time >= cutoff:
                    stats[period]["pnl"] += pnl
                    stats[period]["trades"] += 1
                    if is_win:
                        stats[period]["wins"] += 1
                    else:
                        stats[period]["losses"] += 1

            # Check yesterday (previous complete trading day window)
            if prev_day_start <= exit_time < prev_day_end:
                stats["yesterday"]["pnl"] += pnl
                stats["yesterday"]["trades"] += 1
                if is_win:
                    stats["yesterday"]["wins"] += 1
                else:
                    stats["yesterday"]["losses"] += 1
    except Exception as e:
        logger.warning(f"Non-critical: {e}")

    # Calculate win rates and compute streaks for 24h
    for period in stats:
        total = stats[period]["trades"]
        stats[period]["pnl"] = round(stats[period]["pnl"], 2)
        stats[period]["win_rate"] = round(stats[period]["wins"] / total * 100, 1) if total > 0 else 0.0

    # Compute current streak for 24h
    stats["24h"]["streak"] = 0
    stats["24h"]["streak_type"] = "none"
    try:
        if perf_data:
            cutoff_24h = cutoffs["24h"]
            recent_trades = []
            for trade in perf_data:
                exit_time_str = trade.get("exit_time")
                if not exit_time_str:
                    continue
                try:
                    exit_time = _coerce_utc(parse_ts(exit_time_str))
                    if exit_time >= cutoff_24h:
                        recent_trades.append((exit_time, trade.get("is_win", trade.get("pnl", 0) > 0)))
                except (ValueError, TypeError):
                    continue
            # Sort by exit time descending
            recent_trades.sort(key=lambda x: x[0], reverse=True)
            if recent_trades:
                streak = 0
                streak_type = "win" if recent_trades[0][1] else "loss"
                for _, is_win in recent_trades:
                    if (streak_type == "win" and is_win) or (streak_type == "loss" and not is_win):
                        streak += 1
                    else:
                        break
                stats["24h"]["streak"] = streak
                stats["24h"]["streak_type"] = streak_type
    except Exception as e:
        logger.warning(f"Non-critical: {e}")

    # Fallback: if performance.json had zero trades but challenge has data,
    # populate all periods from the challenge so the PERFORMANCE panel isn't blank.
    total_trades = sum(stats[p]["trades"] for p in ("24h", "72h", "30d"))
    if total_trades == 0:
        try:
            challenge = get_challenge_status(state_dir)
            if challenge and challenge.get("trades", 0) > 0:
                ch_pnl = round(challenge.get("pnl", 0.0), 2)
                ch_trades = challenge.get("trades", 0)
                ch_wins = challenge.get("wins", 0)
                ch_losses = ch_trades - ch_wins
                ch_wr = round(ch_wins / ch_trades * 100, 1) if ch_trades > 0 else 0.0
                ch_stats = {"pnl": ch_pnl, "trades": ch_trades, "wins": ch_wins, "losses": ch_losses, "win_rate": ch_wr}
                for period in ("yesterday", "24h", "72h", "30d"):
                    stats[period] = {**stats[period], **ch_stats}
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

    return stats
