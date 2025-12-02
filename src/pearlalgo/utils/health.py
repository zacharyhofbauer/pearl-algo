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
        Get current health status.
        
        Returns:
            Dictionary with health status information
        """
        # Basic health check - can be extended with actual system checks
        try:
            # Check if we can import main modules
            from pearlalgo.agents.langgraph_state import TradingState
            from pearlalgo.core.portfolio import Portfolio
            
            # Try to create a minimal state to verify system is functional
            portfolio = Portfolio(cash=100000.0)
            state = TradingState(portfolio=portfolio)
            
            return {
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "0.1.0",
                "checks": {
                    "imports": "ok",
                    "state_creation": "ok",
                },
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "0.1.0",
                "error": str(e),
                "checks": {
                    "imports": "failed",
                    "state_creation": "failed",
                },
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
    parser = argparse.ArgumentParser(description="Health check server for PearlAlgo trading system")
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

