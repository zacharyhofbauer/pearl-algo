#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: External watchdog for NQ Agent state freshness validation
# Usage: python3 scripts/monitoring/watchdog_nq_agent.py [--telegram] [--verbose]
# 
# This script is designed to run via cron or systemd timer to detect:
# - Stale state (agent not updating state.json)
# - Silent failures (running=true but no recent successful cycles)
# - Telegram delivery failures accumulating
#
# Exit codes:
#   0 = OK (healthy or expected quiet state)
#   1 = Warning (operator should review, but not critical)
#   2 = Critical (action required)
#   3 = Error reading state (state file missing or corrupt)
#
# Example cron (every 5 minutes):
#   */5 * * * * cd /path/to/pearlalgo-dev-ai-agents && python3 scripts/monitoring/watchdog_nq_agent.py --telegram
# ============================================================================
"""
NQ Agent Watchdog - External state freshness validator.

Designed for cron/systemd timer invocation. Reads state.json and alerts
if the agent appears stalled or has silent failures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Load .env if available
try:
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def load_state() -> dict:
    """Load state.json from the default location."""
    state_file = project_root / "data" / "nq_agent_state" / "state.json"
    
    if not state_file.exists():
        return {"error": "state_file_missing", "path": str(state_file)}
    
    try:
        with open(state_file, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        return {"error": "state_file_corrupt", "detail": str(e)}
    except Exception as e:
        return {"error": "state_file_read_error", "detail": str(e)}


def parse_timestamp(ts_str: str | None) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if not ts_str:
        return None
    
    try:
        # Handle various ISO formats
        ts_str = str(ts_str)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def check_state(state: dict, verbose: bool = False) -> tuple[int, str, list[str]]:
    """
    Check state for issues.
    
    Returns:
        (exit_code, summary, details)
        - exit_code: 0=OK, 1=Warning, 2=Critical, 3=Error
        - summary: One-line summary
        - details: List of detail messages
    """
    now = datetime.now(timezone.utc)
    details = []
    issues = []
    
    # Check for state loading errors
    if "error" in state:
        error_type = state.get("error", "unknown")
        if error_type == "state_file_missing":
            return (3, "State file missing", [f"Path: {state.get('path', 'unknown')}"])
        elif error_type == "state_file_corrupt":
            return (3, "State file corrupt", [state.get("detail", "")])
        else:
            return (3, f"State read error: {error_type}", [state.get("detail", "")])
    
    # Extract key values
    running = state.get("running", False)
    last_updated = parse_timestamp(state.get("last_updated"))
    last_successful_cycle = parse_timestamp(state.get("last_successful_cycle"))
    scan_interval = state.get("config", {}).get("scan_interval", 30)
    signals_send_failures = int(state.get("signals_send_failures", 0) or 0)
    signals_send_failures_session = int(state.get("signals_send_failures_session", 0) or 0)
    futures_market_open = state.get("futures_market_open")
    strategy_session_open = state.get("strategy_session_open")
    
    if verbose:
        details.append(f"Running: {running}")
        details.append(f"Last updated: {last_updated}")
        details.append(f"Last successful cycle: {last_successful_cycle}")
        details.append(f"Scan interval: {scan_interval}s")
        details.append(f"Futures market open: {futures_market_open}")
        details.append(f"Strategy session open: {strategy_session_open}")
    
    # Calculate stale thresholds
    # Dashboard updates every 15 minutes (900s), so we use 2x that for stale threshold
    dashboard_interval = 900
    stale_threshold = max(scan_interval * 4, dashboard_interval * 2)  # At least 4 scan intervals or 2x dashboard
    
    # Check 1: State freshness (last_updated)
    if last_updated:
        state_age_seconds = (now - last_updated).total_seconds()
        if verbose:
            details.append(f"State age: {state_age_seconds:.0f}s (threshold: {stale_threshold}s)")
        
        if state_age_seconds > stale_threshold:
            issues.append(f"State stale: {state_age_seconds/60:.1f} minutes old (threshold: {stale_threshold/60:.1f}m)")
    else:
        issues.append("State has no last_updated timestamp")
    
    # Check 2: Cycle freshness (if running)
    if running:
        if last_successful_cycle:
            cycle_age_seconds = (now - last_successful_cycle).total_seconds()
            cycle_stale_threshold = scan_interval * 10  # 10x scan interval = ~5 minutes for 30s interval
            
            if verbose:
                details.append(f"Last cycle age: {cycle_age_seconds:.0f}s (threshold: {cycle_stale_threshold}s)")
            
            if cycle_age_seconds > cycle_stale_threshold:
                issues.append(f"Last successful cycle stale: {cycle_age_seconds/60:.1f} minutes ago")
        else:
            # Only warn if running but no successful cycle
            issues.append("Running but no successful cycle recorded")
    
    # Check 3: Telegram send failures accumulating
    failure_threshold = 5  # Warn if more than 5 failures in session
    if signals_send_failures_session > failure_threshold:
        issues.append(f"Telegram send failures in session: {signals_send_failures_session}")
    
    # Determine severity
    if not running:
        if verbose:
            details.append("Agent is not running (expected if manually stopped)")
        return (0, "Agent not running", details)
    
    # Check if market is closed (expected quiet)
    if futures_market_open is False:
        if verbose:
            details.append("Futures market closed (expected quiet)")
        # Clear stale issues if market is closed - expected to be quiet
        issues = [i for i in issues if "stale" not in i.lower()]
    
    if strategy_session_open is False:
        if verbose:
            details.append("Strategy session closed (expected quiet)")
        # Clear cycle stale issues if session is closed
        issues = [i for i in issues if "cycle stale" not in i.lower()]
    
    # Final determination
    if not issues:
        return (0, "All checks passed", details)
    
    # Classify severity
    critical_keywords = ["stale", "no successful cycle"]
    is_critical = any(any(kw in issue.lower() for kw in critical_keywords) for issue in issues)
    
    if is_critical:
        return (2, f"Critical: {len(issues)} issue(s) detected", details + issues)
    else:
        return (1, f"Warning: {len(issues)} issue(s) detected", details + issues)


async def send_telegram_alert(message: str, is_critical: bool = False) -> bool:
    """Send alert to Telegram if configured."""
    try:
        from pearlalgo.utils.telegram_alerts import TelegramAlerts
        
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not bot_token or not chat_id:
            print("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
            return False
        
        telegram = TelegramAlerts(bot_token=bot_token, chat_id=chat_id, enabled=True)
        
        prefix = "🚨 *CRITICAL*" if is_critical else "⚠️ *Warning*"
        full_message = f"{prefix}: NQ Agent Watchdog\n\n{message}"
        
        success = await telegram.send_message(full_message, dedupe=True)
        return success
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="NQ Agent Watchdog - External state freshness validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0 = OK (healthy or expected quiet state)
  1 = Warning (operator should review)
  2 = Critical (action required)
  3 = Error reading state

Example cron (every 5 minutes):
  */5 * * * * cd /path/to/project && python3 scripts/monitoring/watchdog_nq_agent.py --telegram
        """
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Send alerts to Telegram (requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    
    args = parser.parse_args()
    
    # Load and check state
    state = load_state()
    exit_code, summary, details = check_state(state, verbose=args.verbose)
    
    # Output results
    if args.json:
        result = {
            "exit_code": exit_code,
            "summary": summary,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(result, indent=2))
    else:
        status_emoji = {0: "✅", 1: "⚠️", 2: "🚨", 3: "❌"}
        print(f"{status_emoji.get(exit_code, '?')} {summary}")
        if args.verbose or exit_code > 0:
            for detail in details:
                print(f"   {detail}")
    
    # Send Telegram alert if requested and there are issues
    if args.telegram and exit_code > 0:
        message = f"{summary}\n\n" + "\n".join(f"• {d}" for d in details if d)
        asyncio.run(send_telegram_alert(message, is_critical=(exit_code >= 2)))
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()



