#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: External watchdog for market agent state freshness validation
# Usage:
#   python3 scripts/monitoring/watchdog_agent.py --market NQ [--telegram] [--verbose]
# ============================================================================
"""
Agent Watchdog - External state freshness validator.

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


def _resolve_state_file(market: str, state_dir_override: str | None = None) -> Path:
    market_upper = str(market or "NQ").strip().upper()
    if state_dir_override:
        return Path(state_dir_override) / "state.json"

    env_state_dir = os.getenv("PEARLALGO_STATE_DIR")
    if env_state_dir:
        return Path(env_state_dir) / "state.json"

    return project_root / "data" / "agent_state" / market_upper / "state.json"


def load_state(state_file: Path) -> dict:
    """Load state.json from the resolved location."""
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
    details: list[str] = []
    issues: list[str] = []

    # Check for state loading errors
    if "error" in state:
        error_type = state.get("error", "unknown")
        if error_type == "state_file_missing":
            return (3, "State file missing", [f"Path: {state.get('path', 'unknown')}"])
        if error_type == "state_file_corrupt":
            return (3, "State file corrupt", [state.get("detail", "")])
        return (3, f"State read error: {error_type}", [state.get("detail", "")])

    # Extract key values
    running = state.get("running", False)
    paused = state.get("paused", False)
    pause_reason = state.get("pause_reason")
    last_updated = parse_timestamp(state.get("last_updated"))
    last_successful_cycle = parse_timestamp(state.get("last_successful_cycle"))
    futures_market_open = state.get("futures_market_open")
    strategy_session_open = state.get("strategy_session_open")
    data_fresh = state.get("data_fresh")
    missed_cycles = int(state.get("missed_cycles", 0) or 0)
    cycle_lag_seconds = float(state.get("cycle_lag_seconds", 0.0) or 0.0)
    signals_send_failures = int(state.get("signals_send_failures", 0) or 0)
    consecutive_errors = int(state.get("consecutive_errors", 0) or 0)

    if verbose:
        details.append(f"running={running}, paused={paused}, market_open={futures_market_open}, session_open={strategy_session_open}")

    # Thresholds
    state_stale_threshold = timedelta(minutes=5)
    cycle_stale_threshold = timedelta(minutes=10)

    # Check 1: Agent running
    if not running:
        issues.append("Agent not running (running=false)")

    # Check 2: Paused state (circuit breaker)
    if paused:
        issues.append(f"Agent paused: {pause_reason or 'unknown reason'}")

    # Check 3: State freshness
    if last_updated:
        age = now - last_updated
        if age > state_stale_threshold:
            issues.append(f"State stale: last_updated {age.total_seconds():.0f}s ago")
    else:
        issues.append("Missing last_updated timestamp")

    # Check 4: Cycle freshness
    if last_successful_cycle:
        age = now - last_successful_cycle
        if age > cycle_stale_threshold:
            issues.append(f"No successful cycle recently: {age.total_seconds():.0f}s ago")
    else:
        issues.append("Missing last_successful_cycle timestamp")

    # Check 5: Data freshness while market open
    if futures_market_open is True and data_fresh is False:
        issues.append("Data is stale while futures market is open (data_fresh=false)")

    # Check 6: Cadence drift
    if missed_cycles > 0:
        issues.append(f"Cadence drift: missed_cycles={missed_cycles}")
    if cycle_lag_seconds > 60:
        issues.append(f"Cadence lag: cycle_lag_seconds={cycle_lag_seconds:.0f}s")

    # Check 7: Telegram failures
    if signals_send_failures > 0 and consecutive_errors > 0:
        issues.append(f"Telegram delivery failures accumulating: signals_send_failures={signals_send_failures}, consecutive_errors={consecutive_errors}")

    # Market-aware suppression
    if futures_market_open is False:
        if verbose:
            details.append("Futures market closed (expected quiet)")
        issues = [i for i in issues if "data is stale" not in i.lower()]
        issues = [i for i in issues if "state stale" not in i.lower()]

    if strategy_session_open is False:
        if verbose:
            details.append("Strategy session closed (expected quiet)")
        issues = [i for i in issues if "no successful cycle" not in i.lower()]

    # Final determination
    if not issues:
        return (0, "All checks passed", details)

    critical_keywords = ["stale", "no successful cycle", "paused", "data is stale", "cadence drift"]
    is_critical = any(any(kw in issue.lower() for kw in critical_keywords) for issue in issues)
    if is_critical:
        return (2, f"Critical: {len(issues)} issue(s) detected", details + issues)
    return (1, f"Warning: {len(issues)} issue(s) detected", details + issues)


async def send_telegram_alert(message: str, market: str, is_critical: bool = False) -> bool:
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
        full_message = f"{prefix}: Agent Watchdog ({str(market).strip().upper()})\n\n{message}"

        return await telegram.send_message(full_message, dedupe=True)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent Watchdog - External state freshness validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--market",
        default=os.getenv("PEARLALGO_MARKET", "NQ"),
        help="Market label (default: PEARLALGO_MARKET or NQ)",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override state directory (defaults to PEARLALGO_STATE_DIR or data/agent_state/<MARKET>)",
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
    market = str(args.market or "NQ").strip().upper()

    state_file = _resolve_state_file(market=market, state_dir_override=args.state_dir)
    state = load_state(state_file)
    exit_code, summary, details = check_state(state, verbose=args.verbose)

    if args.json:
        result = {
            "market": market,
            "state_file": str(state_file),
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
            print(f"   market={market}")
            print(f"   state_file={state_file}")
            for detail in details:
                print(f"   {detail}")

    if args.telegram and exit_code > 0:
        message = f"{summary}\n\n" + "\n".join(f"• {d}" for d in details if d)
        asyncio.run(send_telegram_alert(message, market=market, is_critical=(exit_code >= 2)))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

