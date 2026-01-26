#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: Localhost HTTP server for /healthz and /metrics endpoints (per market)
# Usage:
#   python3 scripts/monitoring/serve_agent_status.py --market NQ --port 9100
# ============================================================================
"""
Agent Status Server - Localhost HTTP endpoint for health and metrics.

This is a sidecar process that reads state.json and exposes:
  GET /healthz  -> 200 OK / 503 Unhealthy (JSON body)
  GET /metrics  -> Prometheus text exposition format
  GET /         -> Simple status page
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent

DEFAULT_PORT = 9100
DEFAULT_HOST = "127.0.0.1"

# Thresholds (seconds)
STATE_STALE_THRESHOLD = 120
CYCLE_STALE_THRESHOLD = 300


def _resolve_state_file(market: str, state_dir_override: str | None = None) -> Path:
    market_upper = str(market or "NQ").strip().upper()
    if state_dir_override:
        return Path(state_dir_override) / "state.json"

    env_state_dir = os.getenv("PEARLALGO_STATE_DIR")
    if env_state_dir:
        return Path(env_state_dir) / "state.json"

    return PROJECT_ROOT / "data" / "agent_state" / market_upper / "state.json"


def _load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {"_error": "state_file_missing", "_path": str(state_file)}
    try:
        return json.loads(state_file.read_text())
    except json.JSONDecodeError as e:
        return {"_error": "state_file_corrupt", "_detail": str(e)}
    except Exception as e:
        return {"_error": "state_file_read_error", "_detail": str(e)}


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        ts_str = str(ts_str)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def evaluate_health(state: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """
    Evaluate agent health based on state.

    Contract (used by tests + operators):
    - running=false is treated as a healthy, intentional stop (status=agent_stopped)
    - paused=true is unhealthy (status includes agent_paused)
    - stale state/cycle/data while market open is unhealthy
    - details always includes "status" and may include "issues"
    """
    now = datetime.now(timezone.utc)
    details: dict[str, Any] = {"timestamp": now.isoformat()}

    # State file errors
    if "_error" in state:
        error_type = str(state.get("_error", "unknown"))
        status = f"state_error:{error_type}"
        details.update(
            {
                "status": status,
                "error": error_type,
                "detail": state.get("_detail", ""),
                "path": state.get("_path", ""),
            }
        )
        return (False, status, details)

    running = bool(state.get("running", False))
    paused = bool(state.get("paused", False))
    pause_reason = state.get("pause_reason")
    futures_market_open = state.get("futures_market_open")
    strategy_session_open = state.get("strategy_session_open")
    data_fresh = state.get("data_fresh")
    consecutive_errors = int(state.get("consecutive_errors", 0) or 0)
    connection_failures = int(state.get("connection_failures", 0) or 0)

    last_updated = _parse_ts(state.get("last_updated"))
    last_successful_cycle = _parse_ts(state.get("last_successful_cycle"))

    details.update(
        {
            "running": running,
            "paused": paused,
            "pause_reason": pause_reason,
            "futures_market_open": futures_market_open,
            "strategy_session_open": strategy_session_open,
            "data_fresh": data_fresh,
            "consecutive_errors": consecutive_errors,
            "connection_failures": connection_failures,
        }
    )

    # Intentional stop is healthy
    if not running:
        details["status"] = "agent_stopped"
        return (True, "agent_stopped", details)

    issues: list[str] = []

    if paused:
        issues.append("agent_paused")

    if last_updated is None:
        issues.append("missing_last_updated")
    else:
        age = (now - last_updated).total_seconds()
        details["state_age_seconds"] = age
        if age > STATE_STALE_THRESHOLD:
            issues.append("state_stale")

    if last_successful_cycle is None:
        issues.append("missing_last_successful_cycle")
    else:
        age = (now - last_successful_cycle).total_seconds()
        details["cycle_age_seconds"] = age
        if age > CYCLE_STALE_THRESHOLD:
            issues.append("cycle_stale")

    # Suppress cycle staleness while market is closed or session is closed
    if futures_market_open is False or strategy_session_open is False:
        issues = [i for i in issues if i != "cycle_stale"]

    if futures_market_open is True and data_fresh is False:
        issues.append("data_stale")

    # Operator threshold (kept simple; test expects 10 to trigger)
    if consecutive_errors >= 10:
        issues.append("consecutive_errors")

    if connection_failures >= 5:
        issues.append("connection_failures")

    if issues:
        status = "unhealthy:" + ",".join(issues)
        details["status"] = status
        details["issues"] = issues
        return (False, status, details)

    details["status"] = "healthy"
    return (True, "healthy", details)


def generate_metrics(state: dict[str, Any]) -> str:
    """Generate Prometheus metrics from state (used by tests + sidecar)."""
    def _b(v: Any) -> int:
        return 1 if bool(v) else 0
    
    def _f(v: Any, default: float = 0.0) -> float:
        try:
            return float(v) if v is not None else default
        except (ValueError, TypeError):
            return default

    state_error = 1 if "_error" in state else 0
    running = _b(state.get("running", False)) if state_error == 0 else 0
    paused = _b(state.get("paused", False)) if state_error == 0 else 0
    cycles_total = int(state.get("cycle_count", 0) or 0) if state_error == 0 else 0
    signals_total = int(state.get("signal_count", 0) or 0) if state_error == 0 else 0
    errors_total = int(state.get("error_count", 0) or 0) if state_error == 0 else 0
    
    # Trading metrics
    daily_pnl = _f(state.get("daily_pnl", 0.0)) if state_error == 0 else 0.0
    daily_trades = int(state.get("daily_trades", 0) or 0) if state_error == 0 else 0
    daily_wins = int(state.get("daily_wins", 0) or 0) if state_error == 0 else 0
    daily_losses = int(state.get("daily_losses", 0) or 0) if state_error == 0 else 0
    daily_signals = int(state.get("daily_signals", 0) or 0) if state_error == 0 else 0
    active_trades = int(state.get("active_trades_count", 0) or 0) if state_error == 0 else 0
    
    # Calculate win rate
    daily_win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0.0
    
    # Market status
    futures_open = _b(state.get("futures_market_open", False)) if state_error == 0 else 0
    session_open = _b(state.get("strategy_session_open", False)) if state_error == 0 else 0
    data_fresh = _b(state.get("data_fresh", False)) if state_error == 0 else 0
    
    # Error tracking
    consecutive_errors = int(state.get("consecutive_errors", 0) or 0) if state_error == 0 else 0
    connection_failures = int(state.get("connection_failures", 0) or 0) if state_error == 0 else 0
    
    # Circuit breaker status
    circuit_breaker = state.get("trading_circuit_breaker", {}) if state_error == 0 else {}
    cb_active = _b(circuit_breaker.get("is_paused", False))
    cb_consecutive_losses = int(circuit_breaker.get("consecutive_losses", 0) or 0)
    cb_session_pnl = _f(circuit_breaker.get("session_pnl", 0.0))
    cb_daily_pnl = _f(circuit_breaker.get("daily_pnl", 0.0))
    
    # Session filter status
    session_filter_enabled = _b(circuit_breaker.get("session_filter_enabled", True))
    session_allowed = _b(circuit_breaker.get("session_allowed", True))
    current_session = circuit_breaker.get("current_session", "unknown") if state_error == 0 else "unknown"
    et_hour = int(circuit_breaker.get("et_hour", 0) or 0) if state_error == 0 else 0

    lines = [
        "# HELP pearlalgo_state_error State file error flag",
        "# TYPE pearlalgo_state_error gauge",
        f"pearlalgo_state_error {state_error}",
        "",
        "# HELP pearlalgo_agent_running Agent running flag (1=running, 0=stopped)",
        "# TYPE pearlalgo_agent_running gauge",
        f"pearlalgo_agent_running {running}",
        "",
        "# HELP pearlalgo_agent_paused Agent paused flag (1=paused, 0=active)",
        "# TYPE pearlalgo_agent_paused gauge",
        f"pearlalgo_agent_paused {paused}",
        "",
        "# HELP pearlalgo_cycles_total Total scan cycles completed",
        "# TYPE pearlalgo_cycles_total counter",
        f"pearlalgo_cycles_total {cycles_total}",
        "",
        "# HELP pearlalgo_signals_generated_total Total signals generated",
        "# TYPE pearlalgo_signals_generated_total counter",
        f"pearlalgo_signals_generated_total {signals_total}",
        "",
        "# HELP pearlalgo_errors_total Total errors encountered",
        "# TYPE pearlalgo_errors_total counter",
        f"pearlalgo_errors_total {errors_total}",
        "",
        "# HELP pearlalgo_daily_pnl_dollars Daily profit/loss in dollars",
        "# TYPE pearlalgo_daily_pnl_dollars gauge",
        f"pearlalgo_daily_pnl_dollars {daily_pnl:.2f}",
        "",
        "# HELP pearlalgo_daily_trades_total Total trades completed today",
        "# TYPE pearlalgo_daily_trades_total gauge",
        f"pearlalgo_daily_trades_total {daily_trades}",
        "",
        "# HELP pearlalgo_daily_wins_total Winning trades today",
        "# TYPE pearlalgo_daily_wins_total gauge",
        f"pearlalgo_daily_wins_total {daily_wins}",
        "",
        "# HELP pearlalgo_daily_losses_total Losing trades today",
        "# TYPE pearlalgo_daily_losses_total gauge",
        f"pearlalgo_daily_losses_total {daily_losses}",
        "",
        "# HELP pearlalgo_daily_win_rate_percent Daily win rate percentage",
        "# TYPE pearlalgo_daily_win_rate_percent gauge",
        f"pearlalgo_daily_win_rate_percent {daily_win_rate:.1f}",
        "",
        "# HELP pearlalgo_daily_signals_total Signals generated today",
        "# TYPE pearlalgo_daily_signals_total gauge",
        f"pearlalgo_daily_signals_total {daily_signals}",
        "",
        "# HELP pearlalgo_active_trades Current number of active virtual trades",
        "# TYPE pearlalgo_active_trades gauge",
        f"pearlalgo_active_trades {active_trades}",
        "",
        "# HELP pearlalgo_futures_market_open Futures market open flag (1=open, 0=closed)",
        "# TYPE pearlalgo_futures_market_open gauge",
        f"pearlalgo_futures_market_open {futures_open}",
        "",
        "# HELP pearlalgo_session_open Strategy session open flag (1=open, 0=closed)",
        "# TYPE pearlalgo_session_open gauge",
        f"pearlalgo_session_open {session_open}",
        "",
        "# HELP pearlalgo_data_fresh Data freshness flag (1=fresh, 0=stale)",
        "# TYPE pearlalgo_data_fresh gauge",
        f"pearlalgo_data_fresh {data_fresh}",
        "",
        "# HELP pearlalgo_consecutive_errors Current consecutive error count",
        "# TYPE pearlalgo_consecutive_errors gauge",
        f"pearlalgo_consecutive_errors {consecutive_errors}",
        "",
        "# HELP pearlalgo_connection_failures Current connection failure count",
        "# TYPE pearlalgo_connection_failures gauge",
        f"pearlalgo_connection_failures {connection_failures}",
        "",
        "# HELP pearlalgo_circuit_breaker_active Circuit breaker paused flag (1=paused, 0=active)",
        "# TYPE pearlalgo_circuit_breaker_active gauge",
        f"pearlalgo_circuit_breaker_active {cb_active}",
        "",
        "# HELP pearlalgo_circuit_breaker_consecutive_losses Consecutive losses tracked by circuit breaker",
        "# TYPE pearlalgo_circuit_breaker_consecutive_losses gauge",
        f"pearlalgo_circuit_breaker_consecutive_losses {cb_consecutive_losses}",
        "",
        "# HELP pearlalgo_circuit_breaker_session_pnl Session P&L tracked by circuit breaker",
        "# TYPE pearlalgo_circuit_breaker_session_pnl gauge",
        f"pearlalgo_circuit_breaker_session_pnl {cb_session_pnl:.2f}",
        "",
        "# HELP pearlalgo_circuit_breaker_daily_pnl Daily P&L tracked by circuit breaker",
        "# TYPE pearlalgo_circuit_breaker_daily_pnl gauge",
        f"pearlalgo_circuit_breaker_daily_pnl {cb_daily_pnl:.2f}",
        "",
        "# HELP pearlalgo_session_filter_enabled Session filter enabled flag (1=enabled, 0=disabled)",
        "# TYPE pearlalgo_session_filter_enabled gauge",
        f"pearlalgo_session_filter_enabled {session_filter_enabled}",
        "",
        "# HELP pearlalgo_session_allowed Current session trading allowed (1=allowed, 0=blocked)",
        "# TYPE pearlalgo_session_allowed gauge",
        f"pearlalgo_session_allowed {session_allowed}",
        "",
        f'# HELP pearlalgo_current_et_hour Current hour in Eastern Time (0-23)',
        "# TYPE pearlalgo_current_et_hour gauge",
        f"pearlalgo_current_et_hour {et_hour}",
        "",
    ]
    return "\n".join(lines)


class _Handler(BaseHTTPRequestHandler):
    state_file: Path
    market: str

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        state = _load_state(self.state_file)
        healthy, status, details = evaluate_health(state)

        if self.path == "/healthz":
            self._send_json(200 if healthy else 503, {"status": status, "market": self.market, **details})
            return

        if self.path == "/metrics":
            body = generate_metrics(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Default: simple HTML
        html = f"""<html><head><title>PearlAlgo Agent Status</title></head>
<body>
<h2>Agent Status (market={self.market})</h2>
<p><b>{status}</b></p>
<pre>{json.dumps(details, indent=2)}</pre>
<p>State file: <code>{self.state_file}</code></p>
</body></html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent status server (healthz + metrics)")
    parser.add_argument("--market", default=os.getenv("PEARLALGO_MARKET", "NQ"))
    parser.add_argument("--state-dir", default=None, help="Override state directory (contains state.json)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    market = str(args.market or "NQ").strip().upper()
    state_file = _resolve_state_file(market=market, state_dir_override=args.state_dir)

    class Handler(_Handler):
        pass

    Handler.state_file = state_file
    Handler.market = market

    server = HTTPServer((args.host, args.port), Handler)
    print(f"Serving agent status on http://{args.host}:{args.port} (market={market})")
    print(f"Reading: {state_file}")
    server.serve_forever()


if __name__ == "__main__":
    main()

