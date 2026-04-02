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

from pearlalgo.utils.health_evaluator import HealthEvaluator, HealthStatus

PROJECT_ROOT = Path(__file__).parent.parent.parent

DEFAULT_PORT = 9100
DEFAULT_HOST = "127.0.0.1"


def _resolve_state_file(market: str, state_dir_override: str | None = None) -> Path:
    market_upper = str(market or "NQ").strip().upper()
    if state_dir_override:
        return Path(state_dir_override) / "state.json"

    env_state_dir = os.getenv("PEARLALGO_STATE_DIR")
    if env_state_dir:
        return Path(env_state_dir) / "state.json"

    return PROJECT_ROOT / "data" / "agent_state" / market_upper / "state.json"


def evaluate_health(state: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """
    Evaluate agent health based on state.

    Contract (used by tests + operators):
    - running=false is treated as a healthy, intentional stop (status=agent_stopped)
    - paused=true is unhealthy (status includes agent_paused)
    - stale state/cycle/data while market open is unhealthy
    - details always includes "status" and may include "issues"
    """
    evaluator = HealthEvaluator(state_file=Path("/unused"))
    result = evaluator.evaluate_state(state)
    details = dict(result.details)

    # Additional serve_agent_status-specific field
    connection_failures = int(state.get("connection_failures", 0) or 0)
    details["connection_failures"] = connection_failures

    if result.status == HealthStatus.ERROR:
        status = details.get("status", f"state_error:{details.get('error', 'unknown')}")
        return (False, status, details)

    if not details.get("running", True):
        return (True, "agent_stopped", details)

    issues = list(details.get("issues", []))

    # Additional serve_agent_status-specific check
    if connection_failures >= 5 and "connection_failures" not in issues:
        issues.append("connection_failures")
        details["issues"] = issues
        issue_msgs = list(details.get("issue_messages", []))
        issue_msgs.append(f"Connection failures: {connection_failures}")
        details["issue_messages"] = issue_msgs

    if issues:
        status = "unhealthy:" + ",".join(issues)
        details["status"] = status
        return (False, status, details)

    details["status"] = "healthy"
    return (True, "healthy", details)


def generate_metrics(state: dict[str, Any]) -> str:
    """Generate Prometheus metrics from state (used by tests + sidecar).
    
    Metrics exposed (grouped by category):
    
    **Agent Status:**
    - pearlalgo_state_error: State file error flag
    - pearlalgo_agent_running: Agent running flag
    - pearlalgo_agent_paused: Agent paused flag
    - pearlalgo_cycles_total: Total scan cycles completed
    - pearlalgo_cycles_session_total: Cycles this session
    
    **Trading Performance:**
    - pearlalgo_signals_generated_total: Total signals generated
    - pearlalgo_daily_pnl_dollars: Daily P&L
    - pearlalgo_daily_trades_total: Trades today
    - pearlalgo_daily_wins_total: Winning trades
    - pearlalgo_daily_losses_total: Losing trades
    - pearlalgo_daily_win_rate_percent: Win rate
    - pearlalgo_active_trades: Active positions
    - pearlalgo_cumulative_pnl_dollars: All-time P&L
    
    **Market Status:**
    - pearlalgo_futures_market_open: Market open flag
    - pearlalgo_session_open: Strategy session flag
    - pearlalgo_data_fresh: Data freshness flag
    - pearlalgo_data_age_seconds: Age of latest bar
    - pearlalgo_buffer_size: Current buffer size
    
    **Error Tracking:**
    - pearlalgo_errors_total: Total errors
    - pearlalgo_consecutive_errors: Current streak
    - pearlalgo_connection_failures: Connection failures
    - pearlalgo_data_fetch_errors: Data fetch errors
    - pearlalgo_signals_send_failures_total: Telegram failures
    
    **Circuit Breaker:**
    - pearlalgo_circuit_breaker_active: CB paused flag
    - pearlalgo_circuit_breaker_consecutive_losses: Loss streak
    - pearlalgo_circuit_breaker_session_pnl: Session P&L
    - pearlalgo_circuit_breaker_daily_pnl: Daily P&L
    - pearlalgo_session_filter_enabled: Session filter flag
    - pearlalgo_session_allowed: Current session allowed
    
    **Cadence/Latency:**
    - pearlalgo_cycle_duration_seconds: Last cycle duration
    - pearlalgo_cycle_duration_p50_seconds: Median cycle time
    - pearlalgo_cycle_duration_p99_seconds: 99th percentile
    - pearlalgo_cadence_mode: Current cadence (0=closed, 1=idle, 2=active, 3=velocity)
    """
    def _b(v: Any) -> int:
        return 1 if bool(v) else 0
    
    def _f(v: Any, default: float = 0.0) -> float:
        try:
            return float(v) if v is not None else default
        except (ValueError, TypeError):
            return default
    
    def _i(v: Any, default: int = 0) -> int:
        try:
            return int(v) if v is not None else default
        except (ValueError, TypeError):
            return default

    state_error = 1 if "_error" in state else 0
    
    # === AGENT STATUS ===
    running = _b(state.get("running", False)) if state_error == 0 else 0
    paused = _b(state.get("paused", False)) if state_error == 0 else 0
    pause_reason = state.get("pause_reason", "") or ""
    cycles_total = _i(state.get("cycle_count", 0)) if state_error == 0 else 0
    cycles_session = _i(state.get("cycle_count_session", 0)) if state_error == 0 else 0
    signals_total = _i(state.get("signal_count", 0)) if state_error == 0 else 0
    signals_session = _i(state.get("signal_count_session", 0)) if state_error == 0 else 0
    errors_total = _i(state.get("error_count", 0)) if state_error == 0 else 0
    
    # === TRADING PERFORMANCE ===
    daily_pnl = _f(state.get("daily_pnl", 0.0)) if state_error == 0 else 0.0
    cumulative_pnl = _f(state.get("cumulative_pnl", 0.0)) if state_error == 0 else 0.0
    daily_trades = _i(state.get("daily_trades", 0)) if state_error == 0 else 0
    daily_wins = _i(state.get("daily_wins", 0)) if state_error == 0 else 0
    daily_losses = _i(state.get("daily_losses", 0)) if state_error == 0 else 0
    daily_signals = _i(state.get("daily_signals", 0)) if state_error == 0 else 0
    active_trades = _i(state.get("active_trades_count", 0)) if state_error == 0 else 0
    signals_sent = _i(state.get("signals_sent", 0)) if state_error == 0 else 0
    signals_send_failures = _i(state.get("signals_send_failures", 0)) if state_error == 0 else 0
    daily_win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0.0
    
    # === MARKET STATUS ===
    futures_open = _b(state.get("futures_market_open", False)) if state_error == 0 else 0
    session_open = _b(state.get("strategy_session_open", False)) if state_error == 0 else 0
    data_fresh = _b(state.get("data_fresh", False)) if state_error == 0 else 0
    data_age_minutes = _f(state.get("latest_bar_age_minutes", 0.0)) if state_error == 0 else 0.0
    buffer_size = _i(state.get("buffer_size", 0)) if state_error == 0 else 0
    buffer_target = _i(state.get("buffer_size_target", 300)) if state_error == 0 else 300
    
    # === ERROR TRACKING ===
    consecutive_errors = _i(state.get("consecutive_errors", 0)) if state_error == 0 else 0
    connection_failures = _i(state.get("connection_failures", 0)) if state_error == 0 else 0
    data_fetch_errors = _i(state.get("data_fetch_errors", 0)) if state_error == 0 else 0
    
    # === CIRCUIT BREAKER ===
    circuit_breaker = state.get("trading_circuit_breaker", {}) if state_error == 0 else {}
    cb_active = _b(circuit_breaker.get("is_paused", False))
    cb_consecutive_losses = _i(circuit_breaker.get("consecutive_losses", 0))
    cb_session_pnl = _f(circuit_breaker.get("session_pnl", 0.0))
    cb_daily_pnl = _f(circuit_breaker.get("daily_pnl", 0.0))
    session_filter_enabled = _b(circuit_breaker.get("session_filter_enabled", True))
    session_allowed = _b(circuit_breaker.get("session_allowed", True))
    et_hour = _i(circuit_breaker.get("et_hour", 0)) if state_error == 0 else 0
    
    # === CADENCE/LATENCY ===
    cadence = state.get("cadence_metrics", {}) if state_error == 0 else {}
    cycle_duration = _f(cadence.get("last_cycle_duration_seconds", 0.0))
    cycle_p50 = _f(cadence.get("cycle_duration_p50_seconds", 0.0))
    cycle_p99 = _f(cadence.get("cycle_duration_p99_seconds", 0.0))
    missed_cycles = _i(cadence.get("missed_cycles", 0))
    cadence_mode_str = cadence.get("current_mode", "idle") if state_error == 0 else "idle"
    cadence_mode = {"closed": 0, "idle": 1, "active": 2, "velocity": 3}.get(cadence_mode_str, 1)

    lines = [
        # === AGENT STATUS ===
        "# HELP pearlalgo_state_error State file error flag (1=error, 0=ok)",
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
        "# HELP pearlalgo_cycles_total Total scan cycles completed (all-time)",
        "# TYPE pearlalgo_cycles_total counter",
        f"pearlalgo_cycles_total {cycles_total}",
        "",
        "# HELP pearlalgo_cycles_session_total Scan cycles this session",
        "# TYPE pearlalgo_cycles_session_total gauge",
        f"pearlalgo_cycles_session_total {cycles_session}",
        "",
        
        # === TRADING PERFORMANCE ===
        "# HELP pearlalgo_signals_generated_total Total signals generated (all-time)",
        "# TYPE pearlalgo_signals_generated_total counter",
        f"pearlalgo_signals_generated_total {signals_total}",
        "",
        "# HELP pearlalgo_signals_session_total Signals generated this session",
        "# TYPE pearlalgo_signals_session_total gauge",
        f"pearlalgo_signals_session_total {signals_session}",
        "",
        "# HELP pearlalgo_signals_sent_total Signals successfully sent to Telegram",
        "# TYPE pearlalgo_signals_sent_total counter",
        f"pearlalgo_signals_sent_total {signals_sent}",
        "",
        "# HELP pearlalgo_daily_pnl_dollars Daily profit/loss in dollars",
        "# TYPE pearlalgo_daily_pnl_dollars gauge",
        f"pearlalgo_daily_pnl_dollars {daily_pnl:.2f}",
        "",
        "# HELP pearlalgo_cumulative_pnl_dollars All-time cumulative P&L in dollars",
        "# TYPE pearlalgo_cumulative_pnl_dollars gauge",
        f"pearlalgo_cumulative_pnl_dollars {cumulative_pnl:.2f}",
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
        
        # === MARKET STATUS ===
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
        "# HELP pearlalgo_data_age_seconds Age of latest market data in seconds",
        "# TYPE pearlalgo_data_age_seconds gauge",
        f"pearlalgo_data_age_seconds {data_age_minutes * 60:.1f}",
        "",
        "# HELP pearlalgo_buffer_size Current number of bars in data buffer",
        "# TYPE pearlalgo_buffer_size gauge",
        f"pearlalgo_buffer_size {buffer_size}",
        "",
        "# HELP pearlalgo_buffer_target Target buffer size from config",
        "# TYPE pearlalgo_buffer_target gauge",
        f"pearlalgo_buffer_target {buffer_target}",
        "",
        
        # === ERROR TRACKING ===
        "# HELP pearlalgo_errors_total Total errors encountered (all-time)",
        "# TYPE pearlalgo_errors_total counter",
        f"pearlalgo_errors_total {errors_total}",
        "",
        "# HELP pearlalgo_consecutive_errors Current consecutive error count",
        "# TYPE pearlalgo_consecutive_errors gauge",
        f"pearlalgo_consecutive_errors {consecutive_errors}",
        "",
        "# HELP pearlalgo_connection_failures Current connection failure count",
        "# TYPE pearlalgo_connection_failures gauge",
        f"pearlalgo_connection_failures {connection_failures}",
        "",
        "# HELP pearlalgo_data_fetch_errors Current data fetch error count",
        "# TYPE pearlalgo_data_fetch_errors gauge",
        f"pearlalgo_data_fetch_errors {data_fetch_errors}",
        "",
        "# HELP pearlalgo_signals_send_failures_total Telegram send failures (all-time)",
        "# TYPE pearlalgo_signals_send_failures_total counter",
        f"pearlalgo_signals_send_failures_total {signals_send_failures}",
        "",
        
        # === CIRCUIT BREAKER ===
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
        "# HELP pearlalgo_current_et_hour Current hour in Eastern Time (0-23)",
        "# TYPE pearlalgo_current_et_hour gauge",
        f"pearlalgo_current_et_hour {et_hour}",
        "",
        # === CADENCE/LATENCY ===
        "# HELP pearlalgo_cycle_duration_seconds Duration of last scan cycle",
        "# TYPE pearlalgo_cycle_duration_seconds gauge",
        f"pearlalgo_cycle_duration_seconds {cycle_duration:.3f}",
        "",
        "# HELP pearlalgo_cycle_duration_p50_seconds Median (p50) cycle duration",
        "# TYPE pearlalgo_cycle_duration_p50_seconds gauge",
        f"pearlalgo_cycle_duration_p50_seconds {cycle_p50:.3f}",
        "",
        "# HELP pearlalgo_cycle_duration_p99_seconds 99th percentile cycle duration",
        "# TYPE pearlalgo_cycle_duration_p99_seconds gauge",
        f"pearlalgo_cycle_duration_p99_seconds {cycle_p99:.3f}",
        "",
        "# HELP pearlalgo_missed_cycles_total Cycles missed due to slow processing",
        "# TYPE pearlalgo_missed_cycles_total counter",
        f"pearlalgo_missed_cycles_total {missed_cycles}",
        "",
        "# HELP pearlalgo_cadence_mode Current cadence mode (0=closed, 1=idle, 2=active, 3=velocity)",
        "# TYPE pearlalgo_cadence_mode gauge",
        f"pearlalgo_cadence_mode {cadence_mode}",
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
        state = HealthEvaluator.load_state(self.state_file)
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
