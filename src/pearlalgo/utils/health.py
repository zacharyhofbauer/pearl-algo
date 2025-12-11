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
        
        # Check 1: Core imports
        try:
            from pearlalgo.agents.langgraph_state import TradingState
            from pearlalgo.core.portfolio import Portfolio
            checks["imports"] = "ok"
        except Exception as e:
            checks["imports"] = "failed"
            errors.append(f"Import error: {e}")
            overall_status = "unhealthy"
        
        # Check 2: State creation
        try:
            portfolio = Portfolio(cash=100000.0)
            state = TradingState(portfolio=portfolio)
            checks["state_creation"] = "ok"
        except Exception as e:
            checks["state_creation"] = "failed"
            errors.append(f"State creation error: {e}")
            overall_status = "unhealthy"
        
        # Check 3: Configuration loading
        try:
            from pearlalgo.config.settings import get_settings
            settings = get_settings()
            checks["config_loading"] = "ok"
        except Exception as e:
            checks["config_loading"] = "failed"
            errors.append(f"Config loading error: {e}")
            overall_status = "unhealthy"
        
        # Check 4: Data provider availability
        try:
            # Dummy provider removed - health check only validates real data providers
        
        # Check 5: Agent initialization
        try:
            from pearlalgo.agents.market_data_agent import MarketDataAgent
            agent = MarketDataAgent(symbols=["ES"], config={})
            checks["agent_initialization"] = "ok"
        except Exception as e:
            checks["agent_initialization"] = "failed"
            errors.append(f"Agent initialization error: {e}")
            overall_status = "unhealthy"
        
        # Check 6: State persistence
        try:
            from pearlalgo.agents.state_store import StateStore
            import tempfile
            temp_dir = tempfile.mkdtemp()
            store = StateStore(storage_path=temp_dir)
            checks["state_persistence"] = "ok"
            import shutil
            shutil.rmtree(temp_dir)
        except Exception as e:
            checks["state_persistence"] = "failed"
            errors.append(f"State persistence error: {e}")
            # Don't fail overall health for state persistence
        
        # Check 7: Environment variables (optional)
        import os
        env_checks = {}
        optional_vars = ["POLYGON_API_KEY", "TELEGRAM_BOT_TOKEN", "GROQ_API_KEY"]
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

