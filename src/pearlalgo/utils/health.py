"""
Health check endpoint for trading system monitoring.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

logger = logging.getLogger(__name__)


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check endpoint."""
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/healthz" or self.path == "/health":
            self.send_health_response()
        else:
            self.send_error(404, "Not Found")
    
    def send_health_response(self):
        """Send health check response."""
        try:
            health_status = self.get_health_status()
            status_code = 200 if health_status["status"] == "healthy" else 503
            
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            response = json.dumps(health_status, indent=2)
            self.wfile.write(response.encode("utf-8"))
        except Exception as e:
            logger.error(f"Error in health check: {e}")
            self.send_error(500, "Internal Server Error")
    
    def get_health_status(self) -> dict:
        """
        Get current health status with comprehensive checks.
        
        Returns:
            Dictionary with health status information
        """
        checks = {}
        overall_status = "healthy"
        errors = []
        
        # Check 1: Configuration loading
        try:
            from pearlalgo.config.settings import get_settings
            settings = get_settings()
            checks["config_loading"] = "ok"
        except Exception as e:
            checks["config_loading"] = "failed"
            errors.append(f"Config loading error: {e}")
            overall_status = "unhealthy"
        
        # Check 2: Data provider availability
        try:
            from pearlalgo.data_providers.factory import create_data_provider
            # Just check if we can import, don't actually create (requires IBKR connection)
            checks["data_provider_import"] = "ok"
        except Exception as e:
            checks["data_provider_import"] = "failed"
            errors.append(f"Data provider import error: {e}")
            overall_status = "unhealthy"
        
        # Check 3: NQ agent imports
        try:
            from pearlalgo.nq_agent.service import NQAgentService
            from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
            checks["nq_agent_import"] = "ok"
        except Exception as e:
            checks["nq_agent_import"] = "failed"
            errors.append(f"NQ agent import error: {e}")
            overall_status = "unhealthy"
        
        # Check 4: Environment variables (optional)
        import os
        env_checks = {}
        optional_vars = ["TELEGRAM_BOT_TOKEN", "IBKR_HOST", "IBKR_PORT"]
        for var in optional_vars:
            env_checks[var] = "set" if os.getenv(var) else "not_set"
        checks["environment_variables"] = env_checks
        
        return {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "0.1.0",
            "checks": checks,
            "errors": errors if errors else None,
        }
    
    def log_message(self, format, *args):
        """Override to use logger instead of stderr."""
        logger.info(f"{self.address_string()} - {format % args}")


def run_health_server(port: int = 8080, host: str = "0.0.0.0"):
    """
    Run health check HTTP server.
    
    Args:
        port: Port to listen on (default 8080)
        host: Host to bind to (default 0.0.0.0)
    """
    server = HTTPServer((host, port), HealthCheckHandler)
    logger.info(f"Health check server started on {host}:{port}")
    logger.info(f"Health endpoint: http://{host}:{port}/healthz")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Health check server stopped")
        server.shutdown()


def main():
    """Main entry point for health check server."""
    parser = argparse.ArgumentParser(description="Health check server for PearlAlgo NQ trading agent")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    run_health_server(port=args.port, host=args.host)


if __name__ == "__main__":
    main()
