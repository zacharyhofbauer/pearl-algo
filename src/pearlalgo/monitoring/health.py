"""
Health Check System - HTTP endpoints and component monitoring.

Provides:
- System health endpoint (/healthz)
- Component health checks (data provider, workers, Telegram)
- Memory/CPU usage monitoring
- Alerting on health degradation
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

try:
    import psutil
except ImportError:
    psutil = None

try:
    from aiohttp import web
    from aiohttp.web import Response
except ImportError:
    web = None
    Response = None

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class HealthChecker:
    """Health checker for system components."""

    def __init__(
        self,
        worker_pool=None,
        data_feed_manager=None,
        telegram_alerts=None,
    ):
        """
        Initialize health checker.

        Args:
            worker_pool: WorkerPool instance (optional)
            data_feed_manager: DataFeedManager instance (optional)
            telegram_alerts: TelegramAlerts instance (optional)
        """
        self.worker_pool = worker_pool
        self.data_feed_manager = data_feed_manager
        self.telegram_alerts = telegram_alerts

        logger.info("HealthChecker initialized")

    async def check_data_provider(self) -> Dict:
        """Check data provider health."""
        if not self.data_feed_manager:
            return {"status": "unknown", "message": "Data feed manager not configured"}

        health = self.data_feed_manager.get_health_status()
        is_healthy = health["connected"] and health["success_rate"] > 0.8

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "connected": health["connected"],
            "success_rate": health["success_rate"],
            "total_requests": health["total_requests"],
            "failed_requests": health["failed_requests"],
            "last_error": health["last_error"],
        }

    async def check_workers(self) -> Dict:
        """Check worker pool health."""
        if not self.worker_pool:
            return {"status": "unknown", "message": "Worker pool not configured"}

        health = self.worker_pool.get_health_status()
        is_healthy = health["healthy"]

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "total_workers": len(self.worker_pool.workers),
            "healthy_workers": sum(
                1 for w in health["workers"].values() if w["healthy"]
            ),
            "workers": health["workers"],
        }

    async def check_telegram(self) -> Dict:
        """Check Telegram connectivity."""
        if not self.telegram_alerts:
            return {"status": "unknown", "message": "Telegram alerts not configured"}

        try:
            # Try to send a test message (or just check if bot is initialized)
            if hasattr(self.telegram_alerts, "bot") and self.telegram_alerts.bot:
                # Simple check - just verify bot exists
                return {
                    "status": "healthy",
                    "enabled": self.telegram_alerts.enabled,
                    "bot_initialized": True,
                }
            else:
                return {
                    "status": "unhealthy",
                    "enabled": self.telegram_alerts.enabled,
                    "bot_initialized": False,
                    "message": "Telegram bot not initialized",
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    async def check_system_resources(self) -> Dict:
        """Check system resource usage."""
        if psutil is None:
            return {
                "status": "unknown",
                "message": "psutil not installed",
            }
        
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            cpu_percent = process.cpu_percent(interval=0.1)

            # System-wide
            system_memory = psutil.virtual_memory()
            system_cpu = psutil.cpu_percent(interval=0.1)

            return {
                "status": "healthy",
                "process": {
                    "memory_mb": memory_info.rss / 1024 / 1024,
                    "cpu_percent": cpu_percent,
                },
                "system": {
                    "memory_percent": system_memory.percent,
                    "memory_available_mb": system_memory.available / 1024 / 1024,
                    "cpu_percent": system_cpu,
                },
            }
        except Exception as e:
            return {
                "status": "unknown",
                "error": str(e),
            }

    async def check_all(self) -> Dict:
        """Check all components."""
        checks = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_status": "healthy",
            "components": {},
        }

        # Check each component
        data_provider_health = await self.check_data_provider()
        checks["components"]["data_provider"] = data_provider_health
        if data_provider_health.get("status") != "healthy":
            checks["overall_status"] = "degraded"

        workers_health = await self.check_workers()
        checks["components"]["workers"] = workers_health
        if workers_health.get("status") != "healthy":
            checks["overall_status"] = "degraded"

        telegram_health = await self.check_telegram()
        checks["components"]["telegram"] = telegram_health
        # Telegram failure is not critical, so don't degrade overall status

        system_resources = await self.check_system_resources()
        checks["components"]["system_resources"] = system_resources

        return checks


async def health_handler(request) -> Response:
    """HTTP handler for /healthz endpoint."""
    health_checker = request.app.get("health_checker")
    if not health_checker:
        return web.json_response(
            {"status": "error", "message": "Health checker not configured"}, status=500
        )

    checks = await health_checker.check_all()
    status_code = 200 if checks["overall_status"] == "healthy" else 503

    return web.json_response(checks, status=status_code)


async def readiness_handler(request) -> Response:
    """HTTP handler for /ready endpoint (Kubernetes readiness probe)."""
    health_checker = request.app.get("health_checker")
    if not health_checker:
        return web.json_response({"ready": False}, status=503)

    # Check critical components only
    data_provider = await health_checker.check_data_provider()
    workers = await health_checker.check_workers()

    ready = (
        data_provider.get("status") == "healthy"
        and workers.get("status") == "healthy"
    )

    status_code = 200 if ready else 503
    return web.json_response({"ready": ready}, status=status_code)


async def liveness_handler(request) -> Response:
    """HTTP handler for /live endpoint (Kubernetes liveness probe)."""
    # Simple check - if we can respond, we're alive
    return web.json_response({"alive": True}, status=200)


def create_health_server(
    health_checker: HealthChecker,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> web.Application:
    """
    Create aiohttp application with health check endpoints.

    Args:
        health_checker: HealthChecker instance
        host: Host to bind to
        port: Port to bind to

    Returns:
        aiohttp Application
    """
    if web is None:
        raise ImportError("aiohttp is required for health server")

    app = web.Application()
    app["health_checker"] = health_checker

    # Add routes
    app.router.add_get("/healthz", health_handler)
    app.router.add_get("/ready", readiness_handler)
    app.router.add_get("/live", liveness_handler)

    logger.info(f"Created health server: http://{host}:{port}/healthz")

    return app


async def run_health_server(
    health_checker: HealthChecker,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> None:
    """
    Run health check HTTP server.

    Args:
        health_checker: HealthChecker instance
        host: Host to bind to
        port: Port to bind to
    """
    if web is None:
        logger.warning("aiohttp not available, health server disabled")
        return

    app = create_health_server(health_checker, host=host, port=port)
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info(f"Health server started on http://{host}:{port}/healthz")

    # Keep running
    try:
        await asyncio.Event().wait()  # Wait forever
    except asyncio.CancelledError:
        logger.info("Health server stopped")
    finally:
        await runner.cleanup()
