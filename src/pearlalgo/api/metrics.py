"""
Pure risk-metric computation functions for the Pearl API server.

All functions in this module are pure (no I/O, no side effects) and operate
on lists of P&L values and/or trade dicts.  This makes them trivially testable
and shared between the MFFU (Tradovate) and Inception (IBKR) code paths.

Extracted from server.py to eliminate duplicated math.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Default (empty) metrics dict
# ---------------------------------------------------------------------------

DEFAULT_RISK_METRICS: Dict[str, Any] = {
    "max_drawdown": 0.0,
    "max_drawdown_pct": 0.0,
    "sharpe_ratio": None,
    "sortino_ratio": None,
    "calmar_ratio": None,
    "profit_factor": None,
    "avg_win": 0.0,
    "avg_loss": 0.0,
    "avg_rr": None,
    "largest_win": 0.0,
    "largest_loss": 0.0,
    "expectancy": 0.0,
    "kelly_criterion": None,
    "max_consecutive_wins": 0,
    "max_consecutive_losses": 0,
    "current_streak": 0,
    "max_drawdown_duration_seconds": None,
    "max_concurrent_positions_peak": 0,
    "max_stop_risk_exposure": 0.0,
    "top_losses": [],
}


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_risk_metrics(
    pnls: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute risk metrics from a list of per-trade P&L values.

    Parameters
    ----------
    pnls:
        Ordered list of per-trade P&L (USD).  Order must reflect execution
        sequence so drawdown and streak calculations are meaningful.
    trades:
        Optional list of trade dicts (with ``exit_time``, ``pnl``,
        ``signal_id``, ``exit_reason`` keys).  Used for top-losses detail
        and daily-return-based Sharpe/Sortino.  When *None*, those metrics
        that require trade metadata will use *pnls* directly.

    Returns
    -------
    dict  – see :data:`DEFAULT_RISK_METRICS` for the full key set.
    """
    if not pnls:
        return dict(DEFAULT_RISK_METRICS)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # -- Max drawdown + duration -----------------------------------------------
    max_dd, max_dd_pct, max_dd_duration_s = _compute_drawdown(pnls, trades)

    # -- Profit factor ---------------------------------------------------------
    total_wins = sum(wins) if wins else 0.0
    total_losses = abs(sum(losses)) if losses else 0.0
    profit_factor = round(total_wins / total_losses, 2) if total_losses > 0 else None

    # -- Averages --------------------------------------------------------------
    avg_win = round(statistics.mean(wins), 2) if wins else 0.0
    avg_loss = round(statistics.mean(losses), 2) if losses else 0.0
    avg_rr = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else None

    # -- Win rate + expectancy -------------------------------------------------
    win_rate = len(wins) / len(pnls)
    expectancy = round((win_rate * avg_win) + ((1 - win_rate) * avg_loss), 2)

    # -- Sharpe & Sortino (daily-return based) ---------------------------------
    sharpe = _compute_sharpe(pnls, trades)
    sortino = _compute_sortino(pnls, trades)

    # -- Calmar ----------------------------------------------------------------
    calmar = _compute_calmar(pnls, trades, max_dd)

    # -- Kelly criterion -------------------------------------------------------
    kelly = None
    if avg_rr is not None and avg_rr > 0:
        kelly = round(win_rate - ((1 - win_rate) / avg_rr), 4)

    # -- Streaks ---------------------------------------------------------------
    max_consec_w, max_consec_l, current_streak = _compute_streaks(pnls)

    # -- Top losses ------------------------------------------------------------
    top_losses = _compute_top_losses(pnls, trades)

    return {
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 1),
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_rr": avg_rr,
        "largest_win": round(max(wins), 2) if wins else 0.0,
        "largest_loss": round(min(losses), 2) if losses else 0.0,
        "expectancy": expectancy,
        "kelly_criterion": kelly,
        "max_consecutive_wins": max_consec_w,
        "max_consecutive_losses": max_consec_l,
        "current_streak": current_streak,
        "max_drawdown_duration_seconds": max_dd_duration_s,
        # Exposure metrics are populated by the caller when signals data is
        # available (they require entry/exit timestamps, not just P&L).
        "max_concurrent_positions_peak": 0,
        "max_stop_risk_exposure": 0.0,
        "top_losses": top_losses,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_drawdown(
    pnls: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
) -> tuple:
    """Return ``(max_dd, max_dd_pct, max_dd_duration_seconds)``.

    Duration is only computed when *trades* carry ``exit_time`` metadata.
    """
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    # For duration tracking
    peak_idx = 0
    dd_start_idx = 0
    max_dd_start_idx = 0
    max_dd_end_idx = 0

    for i, pnl in enumerate(pnls):
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
            peak_idx = i
            dd_start_idx = i
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
            max_dd_start_idx = dd_start_idx
            max_dd_end_idx = i

    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0.0

    # Compute duration in seconds if we have trade timestamps
    max_dd_duration_s: Optional[int] = None
    if trades and max_dd > 0:
        try:
            start_time = _parse_exit_time(trades, max_dd_start_idx)
            end_time = _parse_exit_time(trades, max_dd_end_idx)
            if start_time and end_time:
                max_dd_duration_s = int((end_time - start_time).total_seconds())
        except Exception:
            pass

    return max_dd, max_dd_pct, max_dd_duration_s


def _parse_exit_time(
    trades: List[Dict[str, Any]], idx: int
) -> Optional[datetime]:
    """Safely parse ``exit_time`` from trade at *idx*."""
    if idx >= len(trades):
        return None
    ts = trades[idx].get("exit_time", "")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _group_pnls_by_day(
    pnls: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
) -> List[float]:
    """Group per-trade P&L into daily sums.

    If *trades* have ``exit_time``, group by calendar date.  Otherwise
    fall back to treating each P&L as an independent observation (i.e.
    return *pnls* unchanged).
    """
    if not trades or len(trades) != len(pnls):
        return pnls

    daily: Dict[str, float] = defaultdict(float)
    for pnl, trade in zip(pnls, trades):
        ts = trade.get("exit_time", "")
        if not ts:
            # Can't group → use a unique key so it stays separate
            daily[f"__no_ts_{id(trade)}"] = pnl
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            day_key = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            day_key = f"__bad_ts_{id(trade)}"
        daily[day_key] += pnl

    return list(daily.values())


def _compute_sharpe(
    pnls: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
) -> Optional[float]:
    """Annualised Sharpe ratio based on **daily** returns.

    Groups trade P&L by calendar day (when timestamps are available) before
    computing mean / std.  Requires >= 5 observations.
    """
    daily_returns = _group_pnls_by_day(pnls, trades)
    if len(daily_returns) < 5:
        return None
    mean_r = statistics.mean(daily_returns)
    std_r = statistics.stdev(daily_returns)
    if std_r <= 0:
        return None
    return round((mean_r / std_r) * (252 ** 0.5), 2)


def _compute_sortino(
    pnls: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
) -> Optional[float]:
    """Annualised Sortino ratio (downside deviation only).

    Like Sharpe but the denominator uses only negative daily returns.
    Requires >= 5 observations.
    """
    daily_returns = _group_pnls_by_day(pnls, trades)
    if len(daily_returns) < 5:
        return None
    mean_r = statistics.mean(daily_returns)
    neg_returns = [r for r in daily_returns if r < 0]
    if not neg_returns:
        return None  # No downside → infinite Sortino, return None
    downside_std = statistics.stdev(neg_returns) if len(neg_returns) > 1 else abs(neg_returns[0])
    if downside_std <= 0:
        return None
    return round((mean_r / downside_std) * (252 ** 0.5), 2)


def _compute_calmar(
    pnls: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
    max_dd: float = 0.0,
) -> Optional[float]:
    """Calmar ratio: annualised return / max drawdown.

    Requires trade timestamps to estimate the number of trading days.
    Falls back to ``len(pnls) / 5`` as a rough day estimate when timestamps
    are unavailable.
    """
    if max_dd <= 0:
        return None
    total_pnl = sum(pnls)

    # Estimate number of trading days
    n_days = _estimate_trading_days(trades) if trades else None
    if n_days is None or n_days < 1:
        # Rough heuristic: assume ~5 trades per day
        n_days = max(len(pnls) / 5.0, 1.0)

    annualised_return = (total_pnl / n_days) * 252
    return round(annualised_return / max_dd, 2)


def _estimate_trading_days(trades: List[Dict[str, Any]]) -> Optional[float]:
    """Estimate the number of unique trading days from trade exit timestamps."""
    days = set()
    for t in trades:
        ts = t.get("exit_time", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            days.add(dt.strftime("%Y-%m-%d"))
        except (ValueError, TypeError):
            continue
    return len(days) if days else None


def _compute_streaks(pnls: List[float]) -> tuple:
    """Return ``(max_consecutive_wins, max_consecutive_losses, current_streak)``.

    ``current_streak`` is positive for a winning streak, negative for a
    losing streak, and 0 when *pnls* is empty.
    """
    max_w = 0
    max_l = 0
    cur = 0  # positive = wins, negative = losses

    for pnl in pnls:
        if pnl > 0:
            cur = cur + 1 if cur > 0 else 1
            max_w = max(max_w, cur)
        elif pnl < 0:
            cur = cur - 1 if cur < 0 else -1
            max_l = max(max_l, abs(cur))
        # pnl == 0 → break-even, reset streak
        else:
            cur = 0

    return max_w, max_l, cur


def _compute_top_losses(
    pnls: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
    n: int = 3,
) -> List[Dict[str, Any]]:
    """Return the top *n* worst losses with optional trade metadata."""
    if trades and len(trades) == len(pnls):
        loss_trades = [
            t for t in trades if (t.get("pnl") or 0) < 0
        ]
        loss_trades.sort(key=lambda t: t.get("pnl", 0))
        return [
            {
                "signal_id": t.get("signal_id", "unknown"),
                "pnl": round(t.get("pnl", 0), 2),
                "exit_reason": t.get("exit_reason", ""),
            }
            for t in loss_trades[:n]
        ]
    else:
        sorted_losses = sorted(p for p in pnls if p < 0)
        return [{"pnl": round(p, 2)} for p in sorted_losses[:n]]
