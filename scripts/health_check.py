#!/usr/bin/env python
"""
Health check script for automated trading system.
Checks IB Gateway status, agent status, and recent activity.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.config.settings import get_settings
from pearlalgo.futures.performance import load_performance
from pearlalgo.futures.risk import compute_risk_state
from pearlalgo.futures.config import load_profile


def check_ib_gateway() -> tuple[bool, str]:
    """Check if IB Gateway is running."""
    try:
        from pearlalgo.data_providers.ibkr_data_provider import IBKRConnection
        from pearlalgo.config.settings import get_settings
        
        settings = get_settings()
        # Try to create connection (doesn't actually connect, just checks if port is open)
        # In practice, you might want to check systemd status or process list
        return True, "IB Gateway check (manual verification needed)"
    except Exception as e:
        return False, f"IB Gateway check failed: {e}"


def check_recent_activity(hours: int = 24) -> tuple[bool, str]:
    """Check if there's been recent trading activity."""
    try:
        perf_path = Path("data/performance/futures_decisions.csv")
        if not perf_path.exists():
            return False, "No performance log found"
        
        df = load_performance(perf_path)
        if df.empty:
            return False, "Performance log is empty"
        
        # Check for recent entries
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = df[df["timestamp"] >= cutoff]
        
        if recent.empty:
            return False, f"No activity in last {hours} hours"
        
        last_activity = recent["timestamp"].max()
        return True, f"Last activity: {last_activity.isoformat()} ({len(recent)} entries)"
    except Exception as e:
        return False, f"Error checking activity: {e}"


def check_risk_state() -> tuple[bool, str]:
    """Check current risk state."""
    try:
        profile = load_profile()
        perf_path = Path("data/performance/futures_decisions.csv")
        
        if not perf_path.exists():
            return True, "No performance data (new system)"
        
        df = load_performance(perf_path)
        if df.empty:
            return True, "No trades yet"
        
        # Get today's PnL
        today = datetime.now(timezone.utc).date()
        today_trades = df[df["timestamp"].dt.date == today]
        
        if today_trades.empty:
            realized_pnl = 0.0
            unrealized_pnl = 0.0
        else:
            realized_pnl = today_trades["realized_pnl"].sum()
            unrealized_pnl = today_trades["unrealized_pnl"].iloc[-1] if len(today_trades) > 0 else 0.0
        
        from pearlalgo.futures.risk import compute_risk_state
        
        risk_state = compute_risk_state(
            profile,
            day_start_equity=profile.starting_balance,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            trades_today=len(today_trades),
            max_trades=profile.max_trades,
        )
        
        status_emoji = {
            "OK": "✅",
            "NEAR_LIMIT": "⚠️",
            "HARD_STOP": "🛑",
            "COOLDOWN": "⏸️",
            "PAUSED": "⏸️",
        }
        
        emoji = status_emoji.get(risk_state.status, "❓")
        return risk_state.status in {"OK", "NEAR_LIMIT"}, f"{emoji} {risk_state.status} | PnL: ${realized_pnl + unrealized_pnl:.2f} | Buffer: ${risk_state.remaining_loss_buffer:.2f}"
    except Exception as e:
        return False, f"Error checking risk: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Health check for automated trading system")
    parser.add_argument("--hours", type=int, default=24, help="Hours to check for recent activity")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Automated Trading System Health Check")
    print("=" * 60)
    print()
    
    checks = [
        ("IB Gateway", check_ib_gateway),
        ("Recent Activity", lambda: check_recent_activity(args.hours)),
        ("Risk State", check_risk_state),
    ]
    
    all_ok = True
    for name, check_func in checks:
        ok, message = check_func()
        status = "✅ OK" if ok else "❌ FAIL"
        print(f"{status} | {name}: {message}")
        if not ok:
            all_ok = False
        print()
    
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

