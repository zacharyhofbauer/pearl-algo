#!/usr/bin/env python3
"""
PearlAlgo Health Check & Monitoring Script (Python) - Automated with Telegram Alerts

This is the AUTOMATED version for cron/systemd scheduling.
For a QUICK MANUAL status check, use:
  ./scripts/ops/quick_status.sh

Checks system health and sends Telegram alerts when issues are detected.
Run periodically via cron: */5 * * * * /path/to/health_check.py

Issues detected:
- Agent not running or stalled
- Gateway not running
- Data stale (no updates in 15 minutes)
- Web app not responding
- API server not responding
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Configuration
STATE_FILE = PROJECT_ROOT / "data/agent_state/NQ/state.json"
ALERT_STATE_FILE = PROJECT_ROOT / "data/agent_state/NQ/alert_state.json"
STALE_THRESHOLD_MINUTES = 15
API_URL = "http://localhost:8000"
WEBAPP_URL = "http://localhost:3001"

# Telegram config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_alert(message: str, is_recovery: bool = False):
    """Send alert via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[ALERT] {message}")
        return

    icon = "✅" if is_recovery else "🚨"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"{icon} *PearlAlgo Monitor*\n\n{message}",
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")


def load_alert_state() -> dict:
    """Load previous alert state to avoid duplicate alerts."""
    if ALERT_STATE_FILE.exists():
        try:
            return json.loads(ALERT_STATE_FILE.read_text())
        except:
            pass
    return {"alerts_sent": {}}


def save_alert_state(state: dict):
    """Save alert state."""
    ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE_FILE.write_text(json.dumps(state, indent=2))


def check_agent_state() -> tuple[bool, str]:
    """Check if agent is running and data is fresh."""
    if not STATE_FILE.exists():
        return False, "Agent state file not found"

    try:
        state = json.loads(STATE_FILE.read_text())

        # Check if running
        if not state.get("running", False):
            return False, "Agent is not running"

        # Check if paused
        if state.get("paused", False):
            reason = state.get("pause_reason", "unknown")
            return False, f"Agent is paused: {reason}"

        # Check data freshness
        last_update = state.get("last_updated")
        if last_update:
            last_dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
            age_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            if age_minutes > STALE_THRESHOLD_MINUTES:
                return False, f"Data stale: last update {age_minutes:.0f} minutes ago"

        # Check for high error count
        consecutive_errors = state.get("consecutive_errors", 0)
        if consecutive_errors >= 5:
            return False, f"High error count: {consecutive_errors} consecutive errors"

        return True, "OK"

    except Exception as e:
        return False, f"Error reading state: {e}"


def check_api_server() -> tuple[bool, str]:
    """Check if API server is responding."""
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
    try:
        resp = requests.get(WEBAPP_URL, timeout=5)
        if resp.status_code == 200:
            return True, "OK"
        return False, f"Web app returned status {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Web app not responding"
    except Exception as e:
        return False, f"Web app check error: {e}"


def check_gateway() -> tuple[bool, str]:
    """Check if IBKR gateway is running."""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "IbcGateway"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            return True, "OK"
        return False, "Gateway process not found"
    except Exception as e:
        return False, f"Gateway check error: {e}"


def main():
    """Run all health checks and send alerts."""
    alert_state = load_alert_state()
    alerts_sent = alert_state.get("alerts_sent", {})

    checks = {
        "agent": check_agent_state,
        "api": check_api_server,
        "webapp": check_webapp,
        "gateway": check_gateway,
    }

    issues = []
    recoveries = []

    for name, check_fn in checks.items():
        ok, message = check_fn()
        was_alerting = alerts_sent.get(name, False)

        if not ok:
            issues.append(f"*{name.upper()}*: {message}")
            if not was_alerting:
                # New issue - send alert
                alerts_sent[name] = True
        else:
            if was_alerting:
                # Issue resolved - send recovery
                recoveries.append(f"*{name.upper()}*: Recovered")
                alerts_sent[name] = False

    # Send alerts for new issues
    if issues:
        send_telegram_alert("\n".join(issues))

    # Send recovery notifications
    if recoveries:
        send_telegram_alert("\n".join(recoveries), is_recovery=True)

    # Save state
    alert_state["alerts_sent"] = alerts_sent
    alert_state["last_check"] = datetime.now(timezone.utc).isoformat()
    save_alert_state(alert_state)

    # Print status
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Health check complete")
    if issues:
        print(f"  Issues: {len(issues)}")
    if recoveries:
        print(f"  Recoveries: {len(recoveries)}")


if __name__ == "__main__":
    main()
