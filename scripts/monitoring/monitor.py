#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: Automated health monitor with structured exit codes
# Replaces: scripts/monitoring/health_check.py + scripts/monitoring/watchdog_agent.py
#
# Usage:
#   python3 scripts/monitoring/monitor.py --market NQ
#   python3 scripts/monitoring/monitor.py --market NQ --json
#
# Exit codes: 0=OK, 1=WARNING, 2=CRITICAL, 3=ERROR
#
# Designed for cron/systemd-timer invocation:
#   */5 * * * * cd /path/to/project && .venv/bin/python scripts/monitoring/monitor.py --market NQ
# ============================================================================
"""
PearlAlgo Automated Monitor

Consolidates agent health checks, gateway/API/webapp probes, and structured
exit codes into a single script.

Uses ``HealthEvaluator`` from ``pearlalgo.utils.health_evaluator`` for the
canonical agent-state health evaluation.
"""

from __future__ import annotations

import argparse
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
API_URL = os.getenv("PEARL_API_URL", "http://localhost:8001")
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
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="PearlAlgo Automated Monitor — health checks with structured exit codes",
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

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
