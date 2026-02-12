#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: Automated health monitor with Telegram alerts and exit codes
# Replaces: scripts/monitoring/health_check.py + scripts/monitoring/watchdog_agent.py
#
# Usage:
#   python3 scripts/monitoring/monitor.py --market NQ
#   python3 scripts/monitoring/monitor.py --market NQ --telegram --verbose
#   python3 scripts/monitoring/monitor.py --market NQ --json
#
# Exit codes: 0=OK, 1=WARNING, 2=CRITICAL, 3=ERROR
#
# Designed for cron/systemd-timer invocation:
#   */5 * * * * cd /path/to/project && .venv/bin/python scripts/monitoring/monitor.py --market NQ --telegram
# ============================================================================
"""
PearlAlgo Automated Monitor

Consolidates agent health checks, gateway/API/webapp probes, Telegram
alerting with deduplication, and structured exit codes into a single script.

Uses ``HealthEvaluator`` from ``pearlalgo.utils.health_evaluator`` for the
canonical agent-state health evaluation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project bootstrap
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from pearlalgo.utils.health_evaluator import HealthEvaluator, HealthStatus

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
API_URL = os.getenv("PEARL_API_URL", "http://localhost:8000")
WEBAPP_URL = os.getenv("PEARL_WEBAPP_URL", "http://localhost:3001")
STALE_THRESHOLD_MINUTES = 15

_STATUS_TO_EXIT = {
    HealthStatus.OK: 0,
    HealthStatus.WARNING: 1,
    HealthStatus.CRITICAL: 2,
    HealthStatus.ERROR: 3,
}


# ---------------------------------------------------------------------------
# Resolve state file path
# ---------------------------------------------------------------------------
def _resolve_state_file(market: str, state_dir_override: str | None = None) -> Path:
    market_upper = str(market or "NQ").strip().upper()
    if state_dir_override:
        return Path(state_dir_override) / "state.json"

    env_state_dir = os.getenv("PEARLALGO_STATE_DIR")
    if env_state_dir:
        return Path(env_state_dir) / "state.json"

    return PROJECT_ROOT / "data" / "agent_state" / market_upper / "state.json"


def _resolve_alert_state_file(state_file: Path) -> Path:
    return state_file.parent / "alert_state.json"


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
def check_agent(state_file: Path) -> tuple[int, str, list[str]]:
    """Check agent health via HealthEvaluator. Returns (exit_code, summary, details)."""
    evaluator = HealthEvaluator(
        state_file=state_file,
        stale_threshold_minutes=STALE_THRESHOLD_MINUTES,
        max_consecutive_errors=5,
    )
    result = evaluator.evaluate()
    exit_code = _STATUS_TO_EXIT.get(result.status, 3)

    # Watchdog semantics: "agent not running" is a WARNING, not OK
    if not result.details.get("running", True) and exit_code == 0:
        exit_code = 1

    summary = result.message
    if exit_code == 1 and result.status == HealthStatus.OK:
        summary = "Warning: Agent not running"

    details: list[str] = []
    details.extend(result.details.get("issue_messages", []))
    if not result.details.get("running", True):
        details.append("Agent not running (running=false)")

    return exit_code, summary, details


def check_gateway() -> tuple[bool, str]:
    """Check if IBKR Gateway process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "java.*IBC\\.jar|ibgateway|IB Gateway|java.*jts|IbcGateway"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "OK"
        return False, "Gateway process not found"
    except Exception as e:
        return False, f"Gateway check error: {e}"


def check_api() -> tuple[bool, str]:
    """Check if API server is responding."""
    import requests

    try:
        resp = requests.get(f"{API_URL}/api/state", timeout=5)
        if resp.status_code == 200:
            return True, "OK"
        return False, f"API returned status {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "API server not responding"
    except Exception as e:
        return False, f"API check error: {e}"


def check_webapp() -> tuple[bool, str]:
    """Check if web app is responding."""
    import requests

    try:
        resp = requests.get(WEBAPP_URL, timeout=5)
        if resp.status_code == 200:
            return True, "OK"
        return False, f"Web app returned status {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Web app not responding"
    except Exception as e:
        return False, f"Web app check error: {e}"


# ---------------------------------------------------------------------------
# Alert state persistence (deduplication)
# ---------------------------------------------------------------------------
def _load_alert_state(alert_state_file: Path) -> dict:
    if alert_state_file.exists():
        try:
            return json.loads(alert_state_file.read_text())
        except Exception:
            pass
    return {"alerts_sent": {}}


def _save_alert_state(alert_state_file: Path, state: dict) -> None:
    alert_state_file.parent.mkdir(parents=True, exist_ok=True)
    alert_state_file.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Telegram alerting
# ---------------------------------------------------------------------------
async def _send_telegram_via_lib(message: str, market: str, is_critical: bool = False) -> bool:
    """Try the project's TelegramAlerts helper first."""
    try:
        from pearlalgo.utils.telegram_alerts import TelegramAlerts

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            return False

        telegram = TelegramAlerts(bot_token=bot_token, chat_id=chat_id, enabled=True)
        prefix = "🚨 *CRITICAL*" if is_critical else "⚠️ *Warning*"
        full_message = f"{prefix}: PearlAlgo Monitor ({market})\n\n{message}"
        return await telegram.send_message(full_message, dedupe=True)
    except Exception:
        return False


def _send_telegram_via_requests(message: str, is_recovery: bool = False) -> bool:
    """Fallback: send via raw requests (no dedupe beyond alert_state.json)."""
    import requests

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("[ALERT] Telegram not configured:", message)
        return False

    icon = "✅" if is_recovery else "🚨"
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"{icon} *PearlAlgo Monitor*\n\n{message}",
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        return True
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
        return False


def send_alert(message: str, market: str, *, is_recovery: bool = False, is_critical: bool = False) -> None:
    """Send a Telegram alert, trying the project library first then raw requests."""
    if not is_recovery:
        sent = asyncio.run(_send_telegram_via_lib(message, market=market, is_critical=is_critical))
        if sent:
            return
    # Fallback / recovery notifications
    _send_telegram_via_requests(message, is_recovery=is_recovery)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="PearlAlgo Automated Monitor — health checks with Telegram alerts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit codes:
  0  OK       — all checks passed
  1  WARNING  — non-critical issue (e.g. agent stopped, infra probe failed)
  2  CRITICAL — agent stale/paused/data issues
  3  ERROR    — state file missing or corrupt
""",
    )
    parser.add_argument(
        "--market",
        default=os.getenv("PEARLALGO_MARKET", "NQ"),
        help="Market label (default: PEARLALGO_MARKET or NQ)",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override state directory (contains state.json)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Send alerts to Telegram on failures (requires TELEGRAM_BOT_TOKEN/CHAT_ID)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )

    args = parser.parse_args()
    market = str(args.market or "NQ").strip().upper()

    state_file = _resolve_state_file(market=market, state_dir_override=args.state_dir)
    alert_state_file = _resolve_alert_state_file(state_file)

    # ── Run all checks ────────────────────────────────────────────────────
    agent_exit, agent_summary, agent_details = check_agent(state_file)
    gw_ok, gw_msg = check_gateway()
    api_ok, api_msg = check_api()
    webapp_ok, webapp_msg = check_webapp()

    # Worst exit code wins
    exit_code = agent_exit
    if not gw_ok and exit_code < 1:
        exit_code = 1
    if not api_ok and exit_code < 1:
        exit_code = 1
    if not webapp_ok and exit_code < 1:
        exit_code = 1

    # Build infra details
    infra_issues: list[str] = []
    if not gw_ok:
        infra_issues.append(f"GATEWAY: {gw_msg}")
    if not api_ok:
        infra_issues.append(f"API: {api_msg}")
    if not webapp_ok:
        infra_issues.append(f"WEBAPP: {webapp_msg}")

    all_details = agent_details + infra_issues

    # ── Output ────────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)

    if args.json:
        result = {
            "market": market,
            "state_file": str(state_file),
            "exit_code": exit_code,
            "summary": agent_summary,
            "checks": {
                "agent": {"exit_code": agent_exit, "summary": agent_summary, "details": agent_details},
                "gateway": {"ok": gw_ok, "message": gw_msg},
                "api": {"ok": api_ok, "message": api_msg},
                "webapp": {"ok": webapp_ok, "message": webapp_msg},
            },
            "details": all_details,
            "timestamp": now.isoformat(),
        }
        print(json.dumps(result, indent=2))
    else:
        status_emoji = {0: "✅", 1: "⚠️", 2: "🚨", 3: "❌"}
        print(f"{status_emoji.get(exit_code, '?')} {agent_summary}")

        if args.verbose or exit_code > 0:
            print(f"   market={market}")
            print(f"   state_file={state_file}")
            print(f"   gateway={'OK' if gw_ok else gw_msg}")
            print(f"   api={'OK' if api_ok else api_msg}")
            print(f"   webapp={'OK' if webapp_ok else webapp_msg}")
            for detail in all_details:
                print(f"   {detail}")

        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Monitor check complete")

    # ── Telegram alerts with deduplication ────────────────────────────────
    if args.telegram:
        alert_state = _load_alert_state(alert_state_file)
        alerts_sent = alert_state.get("alerts_sent", {})

        check_results = {
            "agent": (agent_exit == 0, agent_summary),
            "gateway": (gw_ok, gw_msg),
            "api": (api_ok, api_msg),
            "webapp": (webapp_ok, webapp_msg),
        }

        new_issues: list[str] = []
        recoveries: list[str] = []

        for name, (ok, message) in check_results.items():
            was_alerting = alerts_sent.get(name, False)

            if not ok:
                if not was_alerting:
                    new_issues.append(f"*{name.upper()}*: {message}")
                alerts_sent[name] = True
            else:
                if was_alerting:
                    recoveries.append(f"*{name.upper()}*: Recovered")
                    alerts_sent[name] = False

        if new_issues:
            msg = "\n".join(new_issues)
            send_alert(msg, market=market, is_critical=(exit_code >= 2))

        if recoveries:
            msg = "\n".join(recoveries)
            send_alert(msg, market=market, is_recovery=True)

        # Persist alert state
        alert_state["alerts_sent"] = alerts_sent
        alert_state["last_check"] = now.isoformat()
        _save_alert_state(alert_state_file, alert_state)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
