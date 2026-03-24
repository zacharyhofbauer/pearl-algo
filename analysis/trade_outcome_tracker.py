#!/usr/bin/env python3
"""
Trade Outcome Tracker — Core analysis engine for PearlAlgo.

Pulls fills from Tradovate API, matches to PearlAlgo signals for setup type context,
computes MFE/MAE and what-if analysis for each trade, and outputs structured JSON.

Usage:
    python3 trade_outcome_tracker.py --date 2026-03-04 --json --what-if
    python3 trade_outcome_tracker.py --date 2026-03-04          # human-readable output
    python3 trade_outcome_tracker.py                             # defaults to today
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# PearlAlgo imports (must run from PearlAlgoWorkspace with venv activated)
sys.path.insert(0, "/home/pearlalgo/pearl-algo-workspace/src")

try:
    from pearlalgo.execution.tradovate.client import TradovateClient
    from pearlalgo.execution.tradovate.config import TradovateConfig
except ImportError:
    print("ERROR: Cannot import PearlAlgo modules. Ensure you are running from")
    print("       /home/pearlalgo/pearl-algo-workspace with .venv activated.")
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None

# --- Constants ---

PEARLALGO_API = "http://127.0.0.1:8001"
SECRETS_ENV = Path("/home/pearlalgo/.config/pearlalgo/secrets.env")
CANDLE_CACHE_1M = Path("/home/pearlalgo/pearl-algo-workspace/data/candle_cache_MNQ_1m_500.json")
CANDLE_CACHE_5M = Path("/home/pearlalgo/pearl-algo-workspace/data/candle_cache_MNQ_5m_500.json")
MNQ_TICK_VALUE = 0.50   # $0.50 per tick (0.25 points)
MNQ_POINT_VALUE = 2.00  # $2.00 per point per contract
ET = ZoneInfo("America/New_York")

# Session boundaries in ET hours
SESSION_BOUNDARIES = {
    "morning": (9, 30, 11, 0),
    "midday": (11, 0, 13, 0),
    "afternoon": (13, 0, 15, 0),
    "close": (15, 0, 15, 40),
}

# Setup type patterns found in signal `reason` field
SETUP_PATTERNS = {
    "vwap_cross": re.compile(r"VWAP_(?:ABOVE|BELOW)(?!.*RETEST)", re.IGNORECASE),
    "vwap_retest": re.compile(r"VWAP_RETEST", re.IGNORECASE),
    "trend_momentum": re.compile(r"EMA_TREND(?!.*BREAKOUT)", re.IGNORECASE),
    "trend_breakout": re.compile(r"TREND_BREAKOUT", re.IGNORECASE),
}


def _load_api_key() -> str:
    """Load PearlAlgo API key from secrets.env."""
    if SECRETS_ENV.exists():
        for line in SECRETS_ENV.read_text().splitlines():
            if line.startswith("PEARL_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get("PEARL_API_KEY", "")


def _parse_utc(ts_str: str) -> datetime:
    """Parse a timestamp string to timezone-aware UTC datetime."""
    s = str(ts_str).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _to_et(dt: datetime) -> datetime:
    """Convert a datetime to Eastern Time."""
    return dt.astimezone(ET)


def _classify_setup_from_reason(reason: str) -> str:
    """Extract setup type from signal reason string.

    Examples:
        'LONG[4]: EMA_TREND | TREND_BREAKOUT | VWAP_ABOVE | VWAP_EXTENDED_CAUTION'
            → 'trend_breakout'
        'SHORT[5]: EMA_TREND | VWAP_RETEST_DOWN | VWAP_BELOW | VOL_CONFIRM'
            → 'vwap_retest'
    """
    if not reason:
        return "unknown"
    # Check from most specific to least specific
    if SETUP_PATTERNS["vwap_retest"].search(reason):
        return "vwap_retest"
    if SETUP_PATTERNS["trend_breakout"].search(reason):
        return "trend_breakout"
    if SETUP_PATTERNS["vwap_cross"].search(reason):
        return "vwap_cross"
    if SETUP_PATTERNS["trend_momentum"].search(reason):
        return "trend_momentum"
    return "unknown"


# --- Data Fetching ---

async def fetch_fills(client: TradovateClient, target_date: datetime) -> list[dict]:
    """Fetch today's fills from Tradovate API."""
    try:
        fills = await client.get_fills()
    except Exception as e:
        print(f"WARNING: Could not fetch fills: {e}", file=sys.stderr)
        fills = []

    # Filter to target date (compare in ET since tradeDate is market-day)
    date_str = target_date.strftime("%Y-%m-%d")
    filtered = []
    for fill in fills:
        ts = fill.get("timestamp", fill.get("time", fill.get("fillTime", "")))
        if date_str in str(ts):
            filtered.append(fill)

    return filtered


async def fetch_signals(target_date: datetime) -> list[dict]:
    """Fetch signals from PearlAlgo API for setup type matching."""
    if httpx is None:
        print("WARNING: httpx not available, skipping signal fetch", file=sys.stderr)
        return []

    date_str = target_date.strftime("%Y-%m-%d")
    api_key = _load_api_key()
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(f"{PEARLALGO_API}/api/signals", params={"limit": 200}, headers=headers)
            resp.raise_for_status()
            signals = resp.json()

            # Filter to target date, only keep "entered" or "exited" status
            filtered = []
            for sig in signals if isinstance(signals, list) else signals.get("signals", []):
                ts = sig.get("timestamp", sig.get("time", ""))
                if date_str in str(ts):
                    filtered.append(sig)
            return filtered
    except Exception as e:
        print(f"WARNING: Could not fetch signals: {e}", file=sys.stderr)
        return []


def _epoch_to_bar(c: dict) -> dict:
    """Convert a candle dict with unix epoch `time` to bar dict with ISO timestamp."""
    epoch = c.get("time", 0)
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return {
        "timestamp": dt.isoformat(),
        "open": float(c.get("open", 0)),
        "high": float(c.get("high", 0)),
        "low": float(c.get("low", 0)),
        "close": float(c.get("close", 0)),
        "volume": int(c.get("volume", 0)),
    }


def _load_candle_cache(cache_path: Path) -> list[dict]:
    """Load candle cache JSON file into bar dicts with ISO timestamps."""
    if not cache_path.exists():
        return []
    try:
        with open(cache_path) as f:
            data = json.load(f)
        candles = data.get("candles", data) if isinstance(data, dict) else data
        bars = [_epoch_to_bar(c) for c in candles]
        return sorted(bars, key=lambda b: b["timestamp"])
    except Exception as e:
        print(f"WARNING: Could not load candle cache {cache_path}: {e}", file=sys.stderr)
        return []


async def fetch_candles_from_api(bars: int = 200, timeframe: str = "1m") -> list[dict]:
    """Fetch candles from PearlAlgo API (/api/candles endpoint)."""
    if httpx is None:
        return []
    api_key = _load_api_key()
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                f"{PEARLALGO_API}/api/candles",
                params={"symbol": "MNQ", "timeframe": timeframe, "bars": bars},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                candles = data if isinstance(data, list) else data.get("candles", [])
                return sorted([_epoch_to_bar(c) for c in candles], key=lambda b: b["timestamp"])
    except Exception as e:
        print(f"WARNING: Could not fetch candles from API: {e}", file=sys.stderr)
    return []


def get_bars_for_window(all_bars: list[dict], start_time: datetime, end_time: datetime) -> list[dict]:
    """Filter bars to a time window."""
    start_iso = start_time.isoformat()
    end_iso = end_time.isoformat()
    return [b for b in all_bars if start_iso <= b["timestamp"] <= end_iso]


# --- Trade Reconstruction ---

def reconstruct_trades(fills: list[dict], signals: list[dict]) -> list[dict]:
    """Match fills into entry/exit pairs and attach signal context.

    Tradovate fills have action=Buy/Sell. The bot trades 1 contract at a time.
    Buy opens a long (or closes a short), Sell opens a short (or closes a long).
    """
    trades = []
    open_positions: list[dict] = []  # stack of open entries

    # Sort fills by timestamp
    sorted_fills = sorted(fills, key=lambda f: f.get("timestamp", ""))

    for fill in sorted_fills:
        action = fill.get("action", fill.get("side", "")).capitalize()
        qty = abs(int(fill.get("qty", fill.get("quantity", 1))))
        price = float(fill.get("price", fill.get("fillPrice", 0)))
        ts_str = fill.get("timestamp", fill.get("time", ""))

        try:
            ts = _parse_utc(ts_str)
        except (ValueError, TypeError):
            continue

        if action == "Buy":
            # Does this close an existing short?
            matching_short = None
            for i, pos in enumerate(open_positions):
                if pos["direction"] == "SHORT":
                    matching_short = i
                    break

            if matching_short is not None:
                entry = open_positions.pop(matching_short)
                pnl = (entry["price"] - price) * MNQ_POINT_VALUE * min(qty, entry["qty"])
                trades.append(_build_trade(entry, price, ts, pnl, signals))
            else:
                # Opens a long
                open_positions.append({"direction": "LONG", "price": price, "time": ts, "qty": qty})

        elif action == "Sell":
            # Does this close an existing long?
            matching_long = None
            for i, pos in enumerate(open_positions):
                if pos["direction"] == "LONG":
                    matching_long = i
                    break

            if matching_long is not None:
                entry = open_positions.pop(matching_long)
                pnl = (price - entry["price"]) * MNQ_POINT_VALUE * min(qty, entry["qty"])
                trades.append(_build_trade(entry, price, ts, pnl, signals))
            else:
                # Opens a short
                open_positions.append({"direction": "SHORT", "price": price, "time": ts, "qty": qty})

    return trades


def _build_trade(entry: dict, exit_price: float, exit_time: datetime, pnl: float, signals: list[dict]) -> dict:
    """Build a trade dict with signal matching.

    Matching strategy: find a signal with matching direction + entry_price (exact).
    If no exact match, fall back to direction + closest entry_price within 2 points.
    Extract setup type from signal's `reason` field.
    """
    duration = (exit_time - entry["time"]).total_seconds() / 60.0
    entry_dir = entry["direction"].lower()

    # Build index of entered/exited signals for matching
    setup_type = "unknown"
    exit_reason = None
    signal_reason = None
    matched_signal = None

    # Pass 1: exact match on direction + entry_price
    for sig in signals:
        sig_dir = sig.get("direction", "").lower()
        sig_price = sig.get("entry_price")
        sig_status = sig.get("status", "")
        if sig_dir == entry_dir and sig_price == entry["price"]:
            matched_signal = sig
            break

    # Pass 2: closest price within 2 points, same direction
    if matched_signal is None:
        best_dist = float("inf")
        for sig in signals:
            sig_dir = sig.get("direction", "").lower()
            sig_price = sig.get("entry_price")
            if sig_dir != entry_dir or sig_price is None:
                continue
            dist = abs(sig_price - entry["price"])
            if dist < best_dist and dist <= 2.0:
                best_dist = dist
                matched_signal = sig

    if matched_signal:
        signal_reason = matched_signal.get("reason", "")
        setup_type = _classify_setup_from_reason(signal_reason)
        # If the matched signal has status=exited, grab exit_reason
        if matched_signal.get("status") == "exited":
            exit_reason = matched_signal.get("exit_reason")

    # Classify outcome
    if pnl > 5:
        if exit_reason == "take_profit":
            outcome = "WIN_TARGET"
        elif exit_reason == "manual" or exit_reason == "flatten":
            outcome = "WIN_PARTIAL"
        else:
            outcome = "WIN_TARGET"
    elif pnl > -5:
        outcome = "BREAKEVEN"
    else:
        if exit_reason == "stop_loss":
            outcome = "LOSS_STOP"
        elif exit_reason in ("manual", "flatten", "timeout"):
            outcome = "LOSS_MANUAL"
        elif exit_reason == "timeout" or exit_reason == "mff_close":
            outcome = "LOSS_TIMEOUT"
        else:
            outcome = "LOSS_STOP"

    return {
        "entry_time": entry["time"].isoformat(),
        "entry_price": entry["price"],
        "exit_time": exit_time.isoformat(),
        "exit_price": exit_price,
        "direction": entry["direction"],
        "pnl": round(pnl, 2),
        "duration_minutes": round(duration, 1),
        "setup_type": setup_type,
        "outcome_class": outcome,
        "exit_reason": exit_reason,
        "signal_reason": signal_reason,
        "qty": entry.get("qty", 1),
    }


# --- MFE/MAE Analysis ---

def compute_mfe_mae(trade: dict, bars: list[dict]) -> dict:
    """Compute max favorable and max adverse excursion for a trade."""
    entry_price = trade["entry_price"]
    direction = trade["direction"]

    entry_time = _parse_utc(trade["entry_time"])
    exit_time = _parse_utc(trade["exit_time"])

    mfe_points = 0.0
    mae_points = 0.0

    for bar in bars:
        bar_ts = _parse_utc(bar["timestamp"])
        if entry_time <= bar_ts <= exit_time:
            high = bar["high"]
            low = bar["low"]

            if direction == "LONG":
                favorable = high - entry_price
                adverse = entry_price - low
            else:
                favorable = entry_price - low
                adverse = high - entry_price

            mfe_points = max(mfe_points, favorable)
            mae_points = max(mae_points, adverse)

    # If no bars matched, approximate from entry/exit prices
    if mfe_points == 0 and mae_points == 0:
        price_diff = trade["exit_price"] - entry_price
        if direction == "LONG":
            mfe_points = max(0, price_diff)
            mae_points = max(0, -price_diff)
        else:
            mfe_points = max(0, -price_diff)
            mae_points = max(0, price_diff)

    return {
        "mfe_points": round(mfe_points, 2),
        "mfe_dollars": round(mfe_points * MNQ_POINT_VALUE * trade.get("qty", 1), 2),
        "mae_points": round(mae_points, 2),
        "mae_dollars": round(mae_points * MNQ_POINT_VALUE * trade.get("qty", 1), 2),
    }


# --- What-If Analysis ---

def compute_what_if(trade: dict, bars_after_exit: list[dict], matched_signal: dict | None = None) -> dict:
    """Compute what would have happened if the trade stayed open after exit."""
    entry_price = trade["entry_price"]
    exit_price = trade["exit_price"]
    direction = trade["direction"]

    if not bars_after_exit:
        return {
            "price_after_60min": None,
            "would_target_hit": None,
            "max_favorable_after_exit": None,
            "max_favorable_after_exit_points": None,
            "time_to_target": None,
            "data_available": False,
        }

    # Use signal's take_profit as target if available, else estimate 2:1 R:R
    target = None
    if matched_signal and matched_signal.get("take_profit"):
        target = float(matched_signal["take_profit"])
    else:
        stop_distance = abs(exit_price - entry_price) if trade["pnl"] < 0 else None
        if stop_distance and stop_distance > 0:
            target = entry_price + (stop_distance * 2) if direction == "LONG" else entry_price - (stop_distance * 2)
        else:
            target = entry_price + 10 if direction == "LONG" else entry_price - 10

    max_favorable = 0.0
    price_60min = None
    target_hit = False
    time_to_target = None
    exit_time = _parse_utc(trade["exit_time"])

    for bar in bars_after_exit:
        bar_ts = _parse_utc(bar["timestamp"])
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]

        minutes_after = (bar_ts - exit_time).total_seconds() / 60.0

        if direction == "LONG":
            favorable = high - exit_price
            if target and high >= target and not target_hit:
                target_hit = True
                time_to_target = round(minutes_after, 1)
        else:
            favorable = exit_price - low
            if target and low <= target and not target_hit:
                target_hit = True
                time_to_target = round(minutes_after, 1)

        max_favorable = max(max_favorable, favorable)

        if price_60min is None and minutes_after >= 60:
            price_60min = close

    # If we didn't get a bar at 60min, use last bar
    if price_60min is None and bars_after_exit:
        price_60min = bars_after_exit[-1]["close"]

    return {
        "price_after_60min": round(price_60min, 2) if price_60min else None,
        "would_target_hit": target_hit,
        "max_favorable_after_exit": round(max_favorable * MNQ_POINT_VALUE, 2),
        "max_favorable_after_exit_points": round(max_favorable, 2),
        "time_to_target": time_to_target,
        "target_price": round(target, 2) if target else None,
        "data_available": True,
    }


# --- Session & Setup Breakdown ---

def classify_session(time_str: str) -> str:
    """Classify a UTC timestamp into an ET trading session."""
    try:
        utc_dt = _parse_utc(time_str)
        et_dt = _to_et(utc_dt)
        time_val = et_dt.hour * 60 + et_dt.minute

        for session, (sh, sm, eh, em) in SESSION_BOUNDARIES.items():
            start_val = sh * 60 + sm
            end_val = eh * 60 + em
            if start_val <= time_val < end_val:
                return session

        # Pre-market or after-hours
        if time_val < 9 * 60 + 30:
            return "pre_market"
        return "after_hours"
    except (ValueError, TypeError):
        return "unknown"


def compute_session_breakdown(trades: list[dict]) -> dict:
    """Group trades by session and compute stats."""
    sessions = {}
    for trade in trades:
        session = classify_session(trade["entry_time"])
        if session not in sessions:
            sessions[session] = {"count": 0, "winners": 0, "pnl": 0.0}
        sessions[session]["count"] += 1
        sessions[session]["pnl"] += trade["pnl"]
        if trade["pnl"] > 0:
            sessions[session]["winners"] += 1

    for session in sessions:
        s = sessions[session]
        s["win_rate"] = round(s["winners"] / s["count"] * 100, 1) if s["count"] > 0 else 0
        s["pnl"] = round(s["pnl"], 2)

    return sessions


def compute_setup_breakdown(trades: list[dict]) -> dict:
    """Group trades by setup type and compute stats."""
    setups = {}
    for trade in trades:
        st = trade.get("setup_type", "unknown")
        if st not in setups:
            setups[st] = {"count": 0, "winners": 0, "total_pnl": 0.0}
        setups[st]["count"] += 1
        setups[st]["total_pnl"] += trade["pnl"]
        if trade["pnl"] > 0:
            setups[st]["winners"] += 1

    for st in setups:
        s = setups[st]
        s["win_rate"] = round(s["winners"] / s["count"] * 100, 1) if s["count"] > 0 else 0
        s["avg_pnl"] = round(s["total_pnl"] / s["count"], 2) if s["count"] > 0 else 0
        s["total_pnl"] = round(s["total_pnl"], 2)

    return setups


def compute_streaks(trades: list[dict]) -> dict:
    """Compute win/loss streaks."""
    if not trades:
        return {"current_streak": 0, "current_type": "none", "max_win_streak_today": 0, "max_loss_streak_today": 0}

    sorted_trades = sorted(trades, key=lambda t: t["entry_time"])

    max_win = 0
    max_loss = 0
    streak = 0
    last_result = None

    for trade in sorted_trades:
        won = trade["pnl"] > 0
        if won:
            if last_result == "win":
                streak += 1
            else:
                streak = 1
            last_result = "win"
            max_win = max(max_win, streak)
        else:
            if last_result == "loss":
                streak += 1
            else:
                streak = 1
            last_result = "loss"
            max_loss = max(max_loss, streak)

    return {
        "current_streak": streak,
        "current_type": last_result or "none",
        "max_win_streak_today": max_win,
        "max_loss_streak_today": max_loss,
    }


def compute_risk_metrics(trades: list[dict]) -> dict:
    """Compute risk metrics for the day."""
    if not trades:
        return {"max_drawdown_today": 0, "max_concurrent_positions": 0, "time_in_market_minutes": 0}

    # Max drawdown: running P&L peak to trough
    running_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0
    total_time = 0.0

    for trade in sorted(trades, key=lambda t: t["entry_time"]):
        running_pnl += trade["pnl"]
        peak_pnl = max(peak_pnl, running_pnl)
        dd = peak_pnl - running_pnl
        max_dd = max(max_dd, dd)
        total_time += trade.get("duration_minutes", 0)

    return {
        "max_drawdown_today": round(max_dd, 2),
        "max_concurrent_positions": 1,
        "time_in_market_minutes": round(total_time, 1),
    }


# --- Summary ---

def compute_summary(trades: list[dict]) -> dict:
    """Compute overall summary statistics."""
    if not trades:
        return {
            "total_trades": 0, "winners": 0, "losers": 0, "win_rate": 0,
            "total_pnl": 0, "avg_winner": 0, "avg_loser": 0,
            "profit_factor": 0, "expectancy_per_trade": 0,
        }

    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]

    total_pnl = sum(t["pnl"] for t in trades)
    avg_winner = sum(t["pnl"] for t in winners) / len(winners) if winners else 0
    avg_loser = sum(t["pnl"] for t in losers) / len(losers) if losers else 0
    win_rate = len(winners) / len(trades) * 100 if trades else 0

    gross_wins = sum(t["pnl"] for t in winners)
    gross_losses = abs(sum(t["pnl"] for t in losers))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    expectancy = (win_rate / 100 * avg_winner) + ((1 - win_rate / 100) * avg_loser) if trades else 0

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_winner": round(avg_winner, 2),
        "avg_loser": round(avg_loser, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy_per_trade": round(expectancy, 2),
    }


# --- Human-Readable Output ---

def print_human_readable(result: dict):
    """Print results in human-readable format."""
    s = result["summary"]
    print("=" * 70)
    print(f"TRADE OUTCOME REPORT — {result['date']}")
    print("=" * 70)

    print(f"\n{'SUMMARY':^70}")
    print("-" * 70)
    print(f"  Total trades: {s['total_trades']}")
    print(f"  Winners: {s['winners']} | Losers: {s['losers']} | Win rate: {s['win_rate']}%")
    print(f"  Total P&L: ${s['total_pnl']:,.2f}")
    print(f"  Avg winner: ${s['avg_winner']:,.2f} | Avg loser: ${s['avg_loser']:,.2f}")
    print(f"  Profit factor: {s['profit_factor']}")
    print(f"  Expectancy/trade: ${s['expectancy_per_trade']:,.2f}")

    if result.get("trades"):
        print(f"\n{'TRADES':^70}")
        print("-" * 70)
        for t in result["trades"]:
            et_time = _to_et(_parse_utc(t["entry_time"])).strftime("%H:%M")
            arrow = "+" if t["pnl"] > 0 else ""
            mfe = f"${t.get('mfe_dollars', 0):.0f}"
            mae = f"${t.get('mae_dollars', 0):.0f}"
            print(f"  {et_time} ET | {t['direction']:5} | {t['setup_type']:16} | "
                  f"{arrow}${t['pnl']:,.2f} | MFE {mfe} / MAE {mae} | {t['outcome_class']}")

            if t.get("what_if", {}).get("data_available"):
                wi = t["what_if"]
                hit = "YES" if wi["would_target_hit"] else "NO"
                fav = wi.get("max_favorable_after_exit", "N/A")
                print(f"    what-if: target hit? {hit} | max favorable: ${fav} | "
                      f"60min: {wi.get('price_after_60min', 'N/A')}")

    sess = result.get("session_breakdown", {})
    if sess:
        print(f"\n{'SESSION BREAKDOWN (ET)':^70}")
        print("-" * 70)
        order = ["pre_market", "morning", "midday", "afternoon", "close", "after_hours"]
        for name in order:
            if name in sess:
                data = sess[name]
                print(f"  {name:12} | {data['count']:3} trades | {data['win_rate']:5.1f}% WR | ${data['pnl']:>9,.2f}")

    setups = result.get("setup_breakdown", {})
    if setups:
        print(f"\n{'SETUP BREAKDOWN':^70}")
        print("-" * 70)
        for name, data in sorted(setups.items(), key=lambda x: -x[1]["count"]):
            print(f"  {name:16} | {data['count']:3} trades | {data['win_rate']:5.1f}% WR | avg ${data['avg_pnl']:>7,.2f}")

    streaks = result.get("streaks", {})
    if streaks:
        print(f"\n  Streak: {streaks['current_streak']} {streaks['current_type']}s | "
              f"Max win: {streaks['max_win_streak_today']} | Max loss: {streaks['max_loss_streak_today']}")

    risk = result.get("risk_metrics", {})
    if risk:
        print(f"  Max drawdown today: ${risk['max_drawdown_today']:,.2f} | "
              f"Time in market: {risk['time_in_market_minutes']} min")


# --- Main ---

async def main():
    parser = argparse.ArgumentParser(description="PearlAlgo Trade Outcome Tracker")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="Target date (YYYY-MM-DD), defaults to today")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--what-if", action="store_true", dest="what_if",
                        help="Include what-if analysis for each trade")
    args = parser.parse_args()

    target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    # Load bar data for MFE/MAE and what-if
    # Try API first (live data), then fall back to file cache
    all_bars_1m = await fetch_candles_from_api(bars=200, timeframe="1m")
    bar_source = "api_1m"
    if not all_bars_1m:
        all_bars_1m = _load_candle_cache(CANDLE_CACHE_1M)
        bar_source = "file_1m_cache"
    if not all_bars_1m:
        all_bars_1m = _load_candle_cache(CANDLE_CACHE_5M)
        bar_source = "file_5m_cache"
    if not all_bars_1m:
        bar_source = "none"

    # Connect to Tradovate
    config = TradovateConfig.from_env()
    client = TradovateClient(config)

    try:
        await client.connect()

        # Fetch data
        fills = await fetch_fills(client, target_date)
        signals = await fetch_signals(target_date)

        if not fills:
            if args.json:
                print(json.dumps({"date": args.date, "error": "no_fills", "summary": compute_summary([])}))
            else:
                print(f"No fills found for {args.date}")
            return

        # Reconstruct trades
        trades = reconstruct_trades(fills, signals)

        if not trades:
            if args.json:
                print(json.dumps({"date": args.date, "error": "no_trades_reconstructed",
                                  "fills_count": len(fills), "summary": compute_summary([])}))
            else:
                print(f"Found {len(fills)} fills but could not reconstruct trades")
            return

        # MFE/MAE and what-if for each trade
        for trade in trades:
            entry_time = _parse_utc(trade["entry_time"])
            exit_time = _parse_utc(trade["exit_time"])

            # Get bars during the trade for MFE/MAE
            trade_bars = get_bars_for_window(all_bars_1m, entry_time, exit_time)
            mfe_mae = compute_mfe_mae(trade, trade_bars)
            trade.update(mfe_mae)

            # What-if: bars for 60 min after exit
            if args.what_if:
                post_bars = get_bars_for_window(all_bars_1m, exit_time, exit_time + timedelta(minutes=60))

                # Find matched signal for target price
                matched_signal = None
                entry_dir = trade["direction"].lower()
                for sig in signals:
                    if sig.get("direction", "").lower() == entry_dir and sig.get("entry_price") == trade["entry_price"]:
                        if sig.get("status") in ("entered", "exited"):
                            matched_signal = sig
                            break

                trade["what_if"] = compute_what_if(trade, post_bars, matched_signal)

        # Build result
        result = {
            "date": args.date,
            "bar_data_source": bar_source,
            "fills_count": len(fills),
            "signals_count": len(signals),
            "summary": compute_summary(trades),
            "trades": trades,
            "session_breakdown": compute_session_breakdown(trades),
            "setup_breakdown": compute_setup_breakdown(trades),
            "streaks": compute_streaks(trades),
            "risk_metrics": compute_risk_metrics(trades),
        }

        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_human_readable(result)

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
