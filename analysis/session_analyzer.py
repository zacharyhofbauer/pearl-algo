#!/usr/bin/env python3
"""
Session Analyzer — Multi-day analysis for PearlAlgo trading context.

Pulls signal history from PearlAlgo API, groups by session/setup/hour,
cross-tabulates performance, and detects current market regime.

Usage:
    python3 session_analyzer.py --days 5 --json
    python3 session_analyzer.py --days 10        # human-readable
    python3 session_analyzer.py                    # defaults to 5 days
"""

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)

PEARLALGO_API = "http://127.0.0.1:8001"
SECRETS_ENV = Path("/home/pearlalgo/.config/pearlalgo/secrets.env")
ET = ZoneInfo("America/New_York")

# Setup type patterns in signal `reason` field
SETUP_PATTERNS = {
    "vwap_cross": re.compile(r"VWAP_(?:ABOVE|BELOW)(?!.*RETEST)", re.IGNORECASE),
    "vwap_retest": re.compile(r"VWAP_RETEST", re.IGNORECASE),
    "trend_momentum": re.compile(r"EMA_TREND(?!.*BREAKOUT)", re.IGNORECASE),
    "trend_breakout": re.compile(r"TREND_BREAKOUT", re.IGNORECASE),
}

SESSION_BOUNDARIES = {
    "morning": (9, 30, 11, 0),
    "midday": (11, 0, 13, 0),
    "afternoon": (13, 0, 15, 0),
    "close": (15, 0, 15, 40),
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


def classify_session(ts_str: str) -> str:
    """Classify a UTC timestamp into an ET trading session."""
    try:
        et_dt = _parse_utc(ts_str).astimezone(ET)
        time_val = et_dt.hour * 60 + et_dt.minute

        for session, (sh, sm, eh, em) in SESSION_BOUNDARIES.items():
            start_val = sh * 60 + sm
            end_val = eh * 60 + em
            if start_val <= time_val < end_val:
                return session

        if time_val < 9 * 60 + 30:
            return "pre_market"
        return "after_hours"
    except (ValueError, TypeError):
        return "unknown"


def classify_hour(ts_str: str) -> str:
    """Extract ET hour from timestamp for hourly grouping."""
    try:
        et_dt = _parse_utc(ts_str).astimezone(ET)
        return f"{et_dt.hour:02d}:00"
    except (ValueError, TypeError):
        return "unknown"


def _deduplicate_signals(signals: list[dict]) -> list[dict]:
    """Keep one signal per signal_id, preferring exited > entered > generated."""
    priority = {"exited": 3, "entered": 2, "generated": 1}
    best: dict[str, dict] = {}
    for sig in signals:
        sid = sig.get("signal_id", "")
        status = sig.get("status", "")
        p = priority.get(status, 0)
        if sid not in best or p > priority.get(best[sid].get("status", ""), 0):
            best[sid] = sig
    return list(best.values())


async def fetch_signals(days: int) -> list[dict]:
    """Fetch signal history from PearlAlgo API."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    api_key = _load_api_key()
    headers = {"X-API-Key": api_key} if api_key else {}

    async with httpx.AsyncClient(timeout=15) as http:
        try:
            resp = await http.get(
                f"{PEARLALGO_API}/api/signals",
                params={"limit": 200},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            signals = data if isinstance(data, list) else data.get("signals", [])
            # Filter to date range and deduplicate (keep exited > entered > generated per signal_id)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            filtered = []
            for sig in signals:
                ts_str = sig.get("timestamp", sig.get("time", ""))
                try:
                    ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    if ts >= cutoff:
                        filtered.append(sig)
                except (ValueError, TypeError):
                    filtered.append(sig)
            return _deduplicate_signals(filtered)
        except httpx.HTTPStatusError as e:
            # Try with smaller limit
            try:
                resp = await http.get(f"{PEARLALGO_API}/api/signals", params={"limit": 200}, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                signals = data if isinstance(data, list) else data.get("signals", [])
                # Filter manually
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                filtered = []
                for sig in signals:
                    ts_str = sig.get("timestamp", sig.get("time", ""))
                    try:
                        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                        if ts >= cutoff:
                            filtered.append(sig)
                    except (ValueError, TypeError):
                        filtered.append(sig)
                return _deduplicate_signals(filtered)
            except Exception as e2:
                print(f"ERROR: Could not fetch signals: {e2}", file=sys.stderr)
                return []
        except Exception as e:
            print(f"ERROR: Could not fetch signals: {e}", file=sys.stderr)
            return []


def is_winner(signal: dict) -> bool:
    """Determine if a signal was a winner."""
    # Check various possible fields
    if "outcome" in signal:
        return signal["outcome"].lower() in ("win", "winner", "profit", "target")
    if "pnl" in signal and signal["pnl"] is not None:
        return float(signal["pnl"]) > 0
    if "is_win" in signal:
        return bool(signal["is_win"])
    if "result" in signal:
        return signal["result"].lower() in ("win", "winner", "profit", "target")
    if "exit_price" in signal and "entry_price" in signal:
        direction = signal.get("direction", signal.get("side", "")).upper()
        entry = float(signal["entry_price"])
        exit_p = float(signal["exit_price"])
        if direction in ("LONG", "BUY"):
            return exit_p > entry
        elif direction in ("SHORT", "SELL"):
            return exit_p < entry
    return False


def get_pnl(signal: dict) -> float:
    """Extract P&L from a signal."""
    if "pnl" in signal and signal["pnl"] is not None:
        return float(signal["pnl"])
    if "profit" in signal and signal["profit"] is not None:
        return float(signal["profit"])
    if "exit_price" in signal and "entry_price" in signal:
        entry = float(signal["entry_price"])
        exit_p = float(signal["exit_price"])
        direction = signal.get("direction", signal.get("side", "")).upper()
        if direction in ("SHORT", "SELL"):
            return (entry - exit_p) * 2.0  # MNQ point value
        return (exit_p - entry) * 2.0
    return 0.0


def get_setup_type(signal: dict) -> str:
    """Extract setup type from signal's reason field.

    Signal reason examples:
        'LONG[4]: EMA_TREND | TREND_BREAKOUT | VWAP_ABOVE | VWAP_EXTENDED_CAUTION'
        'SHORT[5]: EMA_TREND | VWAP_RETEST_DOWN | VWAP_BELOW | VOL_CONFIRM'
    """
    reason = signal.get("reason", "")
    if reason:
        if SETUP_PATTERNS["vwap_retest"].search(reason):
            return "vwap_retest"
        if SETUP_PATTERNS["trend_breakout"].search(reason):
            return "trend_breakout"
        if SETUP_PATTERNS["vwap_cross"].search(reason):
            return "vwap_cross"
        if SETUP_PATTERNS["trend_momentum"].search(reason):
            return "trend_momentum"
    # Fallback to explicit fields
    for key in ("setup_type", "type", "signal_type", "strategy"):
        if key in signal and signal[key] not in (None, "pearlbot_pinescript"):
            return str(signal[key])
    return "unknown"


def get_date(signal: dict) -> str:
    """Extract date string from signal."""
    ts_str = signal.get("timestamp", signal.get("time", ""))
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        return ts.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "unknown"


# --- Analysis Functions ---

def analyze_by_session(signals: list[dict]) -> dict:
    """Group signals by session and compute stats."""
    sessions = defaultdict(lambda: {"count": 0, "winners": 0, "pnl": 0.0})

    for sig in signals:
        ts = sig.get("timestamp", sig.get("time", ""))
        session = classify_session(ts)
        sessions[session]["count"] += 1
        if is_winner(sig):
            sessions[session]["winners"] += 1
        sessions[session]["pnl"] += get_pnl(sig)

    result = {}
    for session, data in sessions.items():
        result[session] = {
            "count": data["count"],
            "winners": data["winners"],
            "win_rate": round(data["winners"] / data["count"] * 100, 1) if data["count"] > 0 else 0,
            "pnl": round(data["pnl"], 2),
            "avg_pnl": round(data["pnl"] / data["count"], 2) if data["count"] > 0 else 0,
        }
    return result


def analyze_by_setup(signals: list[dict]) -> dict:
    """Group signals by setup type and compute stats."""
    setups = defaultdict(lambda: {"count": 0, "winners": 0, "pnl": 0.0})

    for sig in signals:
        setup = get_setup_type(sig)
        setups[setup]["count"] += 1
        if is_winner(sig):
            setups[setup]["winners"] += 1
        setups[setup]["pnl"] += get_pnl(sig)

    result = {}
    for setup, data in setups.items():
        result[setup] = {
            "count": data["count"],
            "winners": data["winners"],
            "win_rate": round(data["winners"] / data["count"] * 100, 1) if data["count"] > 0 else 0,
            "pnl": round(data["pnl"], 2),
            "avg_pnl": round(data["pnl"] / data["count"], 2) if data["count"] > 0 else 0,
        }
    return result


def analyze_by_hour(signals: list[dict]) -> dict:
    """Group signals by hour and compute stats."""
    hours = defaultdict(lambda: {"count": 0, "winners": 0, "pnl": 0.0})

    for sig in signals:
        ts = sig.get("timestamp", sig.get("time", ""))
        hour = classify_hour(ts)
        hours[hour]["count"] += 1
        if is_winner(sig):
            hours[hour]["winners"] += 1
        hours[hour]["pnl"] += get_pnl(sig)

    result = {}
    for hour, data in sorted(hours.items()):
        result[hour] = {
            "count": data["count"],
            "winners": data["winners"],
            "win_rate": round(data["winners"] / data["count"] * 100, 1) if data["count"] > 0 else 0,
            "pnl": round(data["pnl"], 2),
        }
    return result


def cross_tabulate(signals: list[dict]) -> dict:
    """Cross-tabulate setup type × session."""
    cross = defaultdict(lambda: defaultdict(lambda: {"count": 0, "winners": 0, "pnl": 0.0}))

    for sig in signals:
        setup = get_setup_type(sig)
        ts = sig.get("timestamp", sig.get("time", ""))
        session = classify_session(ts)
        cross[setup][session]["count"] += 1
        if is_winner(sig):
            cross[setup][session]["winners"] += 1
        cross[setup][session]["pnl"] += get_pnl(sig)

    result = {}
    for setup, sessions in cross.items():
        result[setup] = {}
        for session, data in sessions.items():
            result[setup][session] = {
                "count": data["count"],
                "win_rate": round(data["winners"] / data["count"] * 100, 1) if data["count"] > 0 else 0,
                "pnl": round(data["pnl"], 2),
            }
    return result


def analyze_daily(signals: list[dict]) -> dict:
    """Compute daily breakdown."""
    days = defaultdict(lambda: {"count": 0, "winners": 0, "pnl": 0.0})

    for sig in signals:
        date = get_date(sig)
        days[date]["count"] += 1
        if is_winner(sig):
            days[date]["winners"] += 1
        days[date]["pnl"] += get_pnl(sig)

    result = {}
    for date, data in sorted(days.items()):
        result[date] = {
            "count": data["count"],
            "winners": data["winners"],
            "win_rate": round(data["winners"] / data["count"] * 100, 1) if data["count"] > 0 else 0,
            "pnl": round(data["pnl"], 2),
        }
    return result


def detect_regime(signals: list[dict]) -> dict:
    """Detect current market regime from recent signals."""
    if not signals:
        return {"regime": "UNKNOWN", "confidence": 0, "evidence": []}

    # Use last 20 signals
    recent = sorted(signals, key=lambda s: s.get("timestamp", s.get("time", "")))[-20:]
    win_count = sum(1 for s in recent if is_winner(s))
    win_rate = win_count / len(recent) * 100 if recent else 0

    evidence = []
    evidence.append(f"Last {len(recent)} signals: {win_rate:.0f}% win rate")

    if win_rate > 60:
        regime = "TRENDING"
        confidence = min(90, 50 + win_rate - 60)
        evidence.append("High win rate suggests directional market")
    elif win_rate < 35:
        regime = "RANGING"
        confidence = min(90, 50 + (35 - win_rate))
        evidence.append("Low win rate suggests choppy/ranging market")
    else:
        regime = "NEUTRAL"
        confidence = 50
        evidence.append("Win rate in neutral zone — no clear regime")

    # Check for regime shift (compare first half vs second half of recent signals)
    if len(recent) >= 10:
        first_half = recent[:len(recent) // 2]
        second_half = recent[len(recent) // 2:]
        first_wr = sum(1 for s in first_half if is_winner(s)) / len(first_half) * 100
        second_wr = sum(1 for s in second_half if is_winner(s)) / len(second_half) * 100

        shift = second_wr - first_wr
        if abs(shift) > 20:
            direction = "improving" if shift > 0 else "deteriorating"
            evidence.append(f"Regime {direction}: {first_wr:.0f}% → {second_wr:.0f}%")
            if direction == "deteriorating":
                confidence = max(confidence - 10, 30)

    return {
        "regime": regime,
        "confidence": round(confidence, 1),
        "recent_win_rate": round(win_rate, 1),
        "evidence": evidence,
    }


# --- Output ---

def print_human_readable(result: dict):
    """Print results in human-readable format."""
    print("=" * 65)
    print(f"SESSION ANALYSIS — Last {result['days_analyzed']} days ({result['signal_count']} signals)")
    print("=" * 65)

    regime = result.get("regime", {})
    if regime:
        print(f"\n  REGIME: {regime['regime']} ({regime['confidence']}% confidence)")
        for ev in regime.get("evidence", []):
            print(f"    • {ev}")

    sess = result.get("by_session", {})
    if sess:
        print(f"\n{'SESSION PERFORMANCE':^65}")
        print("-" * 65)
        print(f"  {'Session':12} | {'Count':>6} | {'Win Rate':>8} | {'P&L':>10} | {'Avg P&L':>8}")
        print(f"  {'-' * 12}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 10}-+-{'-' * 8}")
        for name, data in sess.items():
            print(f"  {name:12} | {data['count']:6} | {data['win_rate']:7.1f}% | ${data['pnl']:>9,.2f} | ${data['avg_pnl']:>7,.2f}")

    setups = result.get("by_setup", {})
    if setups:
        print(f"\n{'SETUP PERFORMANCE':^65}")
        print("-" * 65)
        print(f"  {'Setup':16} | {'Count':>6} | {'Win Rate':>8} | {'P&L':>10} | {'Avg P&L':>8}")
        print(f"  {'-' * 16}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 10}-+-{'-' * 8}")
        for name, data in setups.items():
            print(f"  {name:16} | {data['count']:6} | {data['win_rate']:7.1f}% | ${data['pnl']:>9,.2f} | ${data['avg_pnl']:>7,.2f}")

    hourly = result.get("by_hour", {})
    if hourly:
        print(f"\n{'HOURLY PERFORMANCE':^65}")
        print("-" * 65)
        for hour, data in hourly.items():
            bar = "█" * int(data["win_rate"] / 5)
            print(f"  {hour} | {data['count']:4} trades | {data['win_rate']:5.1f}% | {bar}")

    cross = result.get("cross_tab", {})
    if cross:
        print(f"\n{'SETUP × SESSION CROSS-TAB':^65}")
        print("-" * 65)
        for setup, sessions in cross.items():
            print(f"\n  {setup}:")
            for session, data in sessions.items():
                print(f"    {session:12} | {data['count']:3} trades | {data['win_rate']:5.1f}% WR | ${data['pnl']:>8,.2f}")

    daily = result.get("by_day", {})
    if daily:
        print(f"\n{'DAILY BREAKDOWN':^65}")
        print("-" * 65)
        for date, data in daily.items():
            indicator = "+" if data["pnl"] >= 0 else ""
            print(f"  {date} | {data['count']:4} trades | {data['win_rate']:5.1f}% | {indicator}${data['pnl']:,.2f}")


async def main():
    parser = argparse.ArgumentParser(description="PearlAlgo Session Analyzer")
    parser.add_argument("--days", type=int, default=5, help="Number of days to analyze (default: 5)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    signals = await fetch_signals(args.days)

    if not signals:
        if args.json:
            print(json.dumps({"error": "no_signals", "days_analyzed": args.days}))
        else:
            print(f"No signals found for the last {args.days} days")
        return

    result = {
        "days_analyzed": args.days,
        "signal_count": len(signals),
        "date_range": {
            "from": get_date(min(signals, key=lambda s: s.get("timestamp", s.get("time", "")))),
            "to": get_date(max(signals, key=lambda s: s.get("timestamp", s.get("time", "")))),
        },
        "regime": detect_regime(signals),
        "by_session": analyze_by_session(signals),
        "by_setup": analyze_by_setup(signals),
        "by_hour": analyze_by_hour(signals),
        "cross_tab": cross_tabulate(signals),
        "by_day": analyze_daily(signals),
    }

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_human_readable(result)


if __name__ == "__main__":
    asyncio.run(main())
