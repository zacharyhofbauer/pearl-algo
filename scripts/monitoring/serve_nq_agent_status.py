#!/usr/bin/env python3
# ============================================================================
# Category: Monitoring
# Purpose: Localhost HTTP server for /healthz and /metrics endpoints
# Usage: python3 scripts/monitoring/serve_nq_agent_status.py [--port PORT]
#
# This is a sidecar process that reads state.json and exposes:
#   GET /healthz  -> 200 OK / 503 Unhealthy (JSON body with details)
#   GET /metrics  -> Prometheus text exposition format
#   GET /         -> Simple status page
#
# The server binds to localhost (127.0.0.1) by default for security.
# It does NOT affect the trading agent - it only reads state.json.
#
# Example:
#   python3 scripts/monitoring/serve_nq_agent_status.py --port 9100
#   curl http://localhost:9100/healthz
#   curl http://localhost:9100/metrics
#
# systemd integration:
#   Create a simple service that runs this script alongside the agent.
# ============================================================================
"""
NQ Agent Status Server - Localhost HTTP endpoint for health and metrics.

Designed for standard VM tooling (curl, Prometheus, systemd health checks)
without requiring changes to the trading agent itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

# Project root for state file access
PROJECT_ROOT = Path(__file__).parent.parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "nq_agent_state" / "state.json"

# Default configuration
DEFAULT_PORT = 9100
DEFAULT_HOST = "127.0.0.1"  # Localhost only for security

# Health check thresholds (seconds)
STATE_STALE_THRESHOLD = 120  # 2 minutes - state file should update every 30s * 10 = 5 min max
CYCLE_STALE_THRESHOLD = 300  # 5 minutes - last_successful_cycle should be recent


def load_state() -> dict[str, Any]:
    """Load state.json from the default location."""
    if not STATE_FILE.exists():
        return {"_error": "state_file_missing", "_path": str(STATE_FILE)}
    
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        return {"_error": "state_file_corrupt", "_detail": str(e)}
    except Exception as e:
        return {"_error": "state_file_read_error", "_detail": str(e)}


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


def evaluate_health(state: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """
    Evaluate agent health based on state.
    
    Returns:
        (is_healthy, status_message, details_dict)
    """
    now = datetime.now(timezone.utc)
    details: dict[str, Any] = {"timestamp": now.isoformat()}
    issues: list[str] = []
    
    # Check for state loading errors
    if "_error" in state:
        error_type = state.get("_error", "unknown")
        return (False, f"state_error:{error_type}", {
            "error": error_type,
            "detail": state.get("_detail", ""),
        })
    
    # Extract key values
    running = state.get("running", False)
    paused = state.get("paused", False)
    last_updated = parse_timestamp(state.get("last_updated"))
    last_successful_cycle = parse_timestamp(state.get("last_successful_cycle"))
    futures_market_open = state.get("futures_market_open")
    data_fresh = state.get("data_fresh")
    consecutive_errors = int(state.get("consecutive_errors", 0) or 0)
    connection_failures = int(state.get("connection_failures", 0) or 0)
    
    details["running"] = running
    details["paused"] = paused
    details["futures_market_open"] = futures_market_open
    details["data_fresh"] = data_fresh
    
    # Check 1: Agent running
    if not running:
        # Not running is not necessarily unhealthy if intentionally stopped
        details["status"] = "stopped"
        return (True, "agent_stopped", details)
    
    # Check 2: Agent paused (circuit breaker)
    if paused:
        issues.append("agent_paused")
        details["pause_reason"] = state.get("pause_reason")
    
    # Check 3: State freshness
    if last_updated:
        state_age_seconds = (now - last_updated).total_seconds()
        details["state_age_seconds"] = round(state_age_seconds, 1)
        
        if state_age_seconds > STATE_STALE_THRESHOLD:
            issues.append(f"state_stale:{int(state_age_seconds)}s")
    else:
        issues.append("no_last_updated")
    
    # Check 4: Cycle freshness (only if running and market open)
    if running and last_successful_cycle:
        cycle_age_seconds = (now - last_successful_cycle).total_seconds()
        details["cycle_age_seconds"] = round(cycle_age_seconds, 1)
        
        # Only flag as issue if market is open or unknown
        if futures_market_open is not False:
            if cycle_age_seconds > CYCLE_STALE_THRESHOLD:
                issues.append(f"cycle_stale:{int(cycle_age_seconds)}s")
    
    # Check 5: Error accumulation
    if consecutive_errors >= 5:
        issues.append(f"consecutive_errors:{consecutive_errors}")
    if connection_failures >= 3:
        issues.append(f"connection_failures:{connection_failures}")
    
    # Check 6: Data freshness (only during market hours)
    if futures_market_open is True and data_fresh is False:
        issues.append("data_stale")
    
    # Determine overall health
    if issues:
        details["issues"] = issues
        return (False, ",".join(issues[:3]), details)  # Limit to top 3 issues in status
    
    details["status"] = "healthy"
    return (True, "healthy", details)


def generate_metrics(state: dict[str, Any]) -> str:
    """
    Generate Prometheus text exposition format metrics from state.
    
    Metric naming follows Prometheus conventions:
    - pearlalgo_agent_* for agent-level metrics
    - pearlalgo_data_* for data quality metrics
    - pearlalgo_signals_* for signal metrics
    - pearlalgo_errors_* for error metrics
    """
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    
    def add_metric(name: str, value: float | int, help_text: str, metric_type: str = "gauge", labels: dict[str, str] | None = None):
        """Add a metric with optional labels."""
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    
    # Handle state loading errors
    if "_error" in state:
        add_metric("pearlalgo_state_error", 1, "State file read error (1=error)")
        return "\n".join(lines) + "\n"
    
    # Agent status
    running = 1 if state.get("running", False) else 0
    add_metric("pearlalgo_agent_running", running, "Agent process running (1=yes, 0=no)")
    
    paused = 1 if state.get("paused", False) else 0
    add_metric("pearlalgo_agent_paused", paused, "Agent paused due to circuit breaker (1=yes, 0=no)")
    
    # State file age
    last_updated = parse_timestamp(state.get("last_updated"))
    if last_updated:
        state_age = (now - last_updated).total_seconds()
        add_metric("pearlalgo_state_age_seconds", round(state_age, 1), "Seconds since state.json was last updated")
    
    # Last successful cycle age
    last_cycle = parse_timestamp(state.get("last_successful_cycle"))
    if last_cycle:
        cycle_age = (now - last_cycle).total_seconds()
        add_metric("pearlalgo_cycle_age_seconds", round(cycle_age, 1), "Seconds since last successful scan cycle")
    
    # Market status
    futures_open = state.get("futures_market_open")
    if futures_open is not None:
        add_metric("pearlalgo_futures_market_open", 1 if futures_open else 0, "Futures market open (1=open, 0=closed)")
    
    session_open = state.get("strategy_session_open")
    if session_open is not None:
        add_metric("pearlalgo_strategy_session_open", 1 if session_open else 0, "Strategy session open (1=open, 0=closed)")
    
    # Data quality
    data_fresh = state.get("data_fresh")
    if data_fresh is not None:
        add_metric("pearlalgo_data_fresh", 1 if data_fresh else 0, "Market data is fresh (1=fresh, 0=stale)")
    
    latest_bar_age = state.get("latest_bar_age_minutes")
    if latest_bar_age is not None:
        add_metric("pearlalgo_latest_bar_age_minutes", round(float(latest_bar_age), 2), "Age of latest bar in minutes")
    
    buffer_size = state.get("buffer_size")
    if buffer_size is not None:
        add_metric("pearlalgo_buffer_size", int(buffer_size), "Number of bars in data buffer")
    
    buffer_target = state.get("buffer_size_target")
    if buffer_target is not None:
        add_metric("pearlalgo_buffer_target", int(buffer_target), "Target buffer size")
    
    # Counters (lifetime)
    cycle_count = state.get("cycle_count")
    if cycle_count is not None:
        add_metric("pearlalgo_cycles_total", int(cycle_count), "Total scan cycles since agent start", metric_type="counter")
    
    signal_count = state.get("signal_count")
    if signal_count is not None:
        add_metric("pearlalgo_signals_generated_total", int(signal_count), "Total signals generated", metric_type="counter")
    
    signals_sent = state.get("signals_sent")
    if signals_sent is not None:
        add_metric("pearlalgo_signals_sent_total", int(signals_sent), "Total signals sent to Telegram", metric_type="counter")
    
    signals_failed = state.get("signals_send_failures")
    if signals_failed is not None:
        add_metric("pearlalgo_telegram_failures_total", int(signals_failed), "Total Telegram send failures", metric_type="counter")
    
    # Error counters
    error_count = state.get("error_count")
    if error_count is not None:
        add_metric("pearlalgo_errors_total", int(error_count), "Total errors encountered", metric_type="counter")
    
    consecutive_errors = state.get("consecutive_errors")
    if consecutive_errors is not None:
        add_metric("pearlalgo_consecutive_errors", int(consecutive_errors), "Current consecutive error count")
    
    connection_failures = state.get("connection_failures")
    if connection_failures is not None:
        add_metric("pearlalgo_connection_failures", int(connection_failures), "Current connection failure count")
    
    data_fetch_errors = state.get("data_fetch_errors")
    if data_fetch_errors is not None:
        add_metric("pearlalgo_data_fetch_errors", int(data_fetch_errors), "Current data fetch error count")
    
    # Cadence metrics (if available)
    cadence = state.get("cadence_metrics")
    if cadence and isinstance(cadence, dict):
        duration_ms = cadence.get("cycle_duration_ms")
        if duration_ms is not None:
            add_metric("pearlalgo_cycle_duration_ms", round(float(duration_ms), 1), "Last cycle duration in milliseconds")
        
        p50 = cadence.get("duration_p50_ms")
        if p50 is not None:
            add_metric("pearlalgo_cycle_duration_p50_ms", round(float(p50), 1), "Cycle duration 50th percentile (ms)")
        
        p95 = cadence.get("duration_p95_ms")
        if p95 is not None:
            add_metric("pearlalgo_cycle_duration_p95_ms", round(float(p95), 1), "Cycle duration 95th percentile (ms)")
        
        missed = cadence.get("missed_cycles")
        if missed is not None:
            add_metric("pearlalgo_missed_cycles_total", int(missed), "Total missed cycles due to slow processing", metric_type="counter")
    
    # Version info (as labels on an info metric)
    version = state.get("version")
    run_id = state.get("run_id")
    if version or run_id:
        labels = {}
        if version:
            labels["version"] = str(version)
        if run_id:
            labels["run_id"] = str(run_id)
        add_metric("pearlalgo_agent_info", 1, "Agent info with version and run_id labels", labels=labels)
    
    return "\n".join(lines) + "\n"


class StatusHandler(BaseHTTPRequestHandler):
    """HTTP request handler for status endpoints."""
    
    def log_message(self, format: str, *args) -> None:
        """Suppress default logging to stderr."""
        pass
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/healthz" or self.path == "/health":
            self.handle_healthz()
        elif self.path == "/metrics":
            self.handle_metrics()
        elif self.path == "/":
            self.handle_index()
        else:
            self.send_error(404, "Not Found")
    
    def handle_healthz(self):
        """Handle /healthz endpoint."""
        state = load_state()
        is_healthy, status, details = evaluate_health(state)
        
        response = {
            "status": "healthy" if is_healthy else "unhealthy",
            "message": status,
            "details": details,
        }
        
        body = json.dumps(response, indent=2).encode("utf-8")
        
        self.send_response(200 if is_healthy else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def handle_metrics(self):
        """Handle /metrics endpoint (Prometheus format)."""
        state = load_state()
        metrics = generate_metrics(state)
        body = metrics.encode("utf-8")
        
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def handle_index(self):
        """Handle / endpoint with simple status page."""
        state = load_state()
        is_healthy, status, details = evaluate_health(state)
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>NQ Agent Status</title>
    <style>
        body {{ font-family: monospace; padding: 20px; background: #1a1a1a; color: #e0e0e0; }}
        .healthy {{ color: #4caf50; }}
        .unhealthy {{ color: #f44336; }}
        pre {{ background: #2d2d2d; padding: 15px; border-radius: 4px; overflow-x: auto; }}
        a {{ color: #64b5f6; }}
    </style>
</head>
<body>
    <h1>NQ Agent Status Server</h1>
    <p>Status: <span class="{'healthy' if is_healthy else 'unhealthy'}">{status}</span></p>
    <h2>Endpoints</h2>
    <ul>
        <li><a href="/healthz">/healthz</a> - Health check (JSON)</li>
        <li><a href="/metrics">/metrics</a> - Prometheus metrics</li>
    </ul>
    <h2>Current State</h2>
    <pre>{json.dumps(details, indent=2)}</pre>
</body>
</html>"""
        
        body = html.encode("utf-8")
        
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(
        description="NQ Agent Status Server - Localhost HTTP endpoint for health and metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Endpoints:
  GET /         Simple status page (HTML)
  GET /healthz  Health check (JSON, returns 200 or 503)
  GET /metrics  Prometheus metrics (text format)

Examples:
  # Start server on default port
  python3 scripts/monitoring/serve_nq_agent_status.py

  # Start on custom port
  python3 scripts/monitoring/serve_nq_agent_status.py --port 9200

  # Test endpoints
  curl http://localhost:9100/healthz
  curl http://localhost:9100/metrics
        """
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST}, use 0.0.0.0 for network access)",
    )
    
    args = parser.parse_args()
    
    server_address = (args.host, args.port)
    httpd = HTTPServer(server_address, StatusHandler)
    
    print(f"NQ Agent Status Server starting on http://{args.host}:{args.port}")
    print(f"  GET /         -> Status page")
    print(f"  GET /healthz  -> Health check (JSON)")
    print(f"  GET /metrics  -> Prometheus metrics")
    print(f"\nReading state from: {STATE_FILE}")
    print("\nPress Ctrl+C to stop")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.shutdown()


if __name__ == "__main__":
    main()





