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
        signal_tracker=None,
        exit_signal_generator=None,
    ):
        """
        Initialize health checker.

        Args:
            worker_pool: WorkerPool instance (optional)
            data_feed_manager: DataFeedManager instance (optional)
            telegram_alerts: TelegramAlerts instance (optional)
            signal_tracker: SignalTracker instance (optional)
            exit_signal_generator: ExitSignalGenerator instance (optional)
        """
        self.worker_pool = worker_pool
        self.data_feed_manager = data_feed_manager
        self.telegram_alerts = telegram_alerts
        self.signal_tracker = signal_tracker
        self.exit_signal_generator = exit_signal_generator

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
    
    async def check_signal_tracker(self) -> Dict:
        """Check signal tracker health."""
        if not self.signal_tracker:
            return {"status": "unknown", "message": "Signal tracker not configured"}
        
        try:
            metrics = self.signal_tracker.get_metrics()
            persistence = metrics.get("persistence_operations", {})
            success_rate = persistence.get("success_rate", 1.0)
            
            # Check for issues
            is_healthy = True
            issues = []
            
            if success_rate < 0.95:
                is_healthy = False
                issues.append(f"Low persistence success rate: {success_rate:.2%}")
            
            if metrics.get("validation_errors", 0) > 10:
                is_healthy = False
                issues.append(f"High validation errors: {metrics['validation_errors']}")
            
            # Check persistence file
            persistence_file_healthy = True
            persistence_file_size = 0
            if hasattr(self.signal_tracker, 'persistence_path'):
                persistence_path = self.signal_tracker.persistence_path
                if persistence_path.exists():
                    persistence_file_size = persistence_path.stat().st_size
                    # Check if file is too large (potential issue)
                    if persistence_file_size > 10 * 1024 * 1024:  # 10MB
                        persistence_file_healthy = False
                        issues.append(f"Persistence file too large: {persistence_file_size / 1024 / 1024:.1f}MB")
                else:
                    persistence_file_healthy = False
                    issues.append("Persistence file missing")
            
            return {
                "status": "healthy" if (is_healthy and persistence_file_healthy) else "unhealthy",
                "active_signals": metrics.get("active_signals_count", 0),
                "total_pnl": metrics.get("total_pnl", 0.0),
                "persistence": {
                    "success_rate": success_rate,
                    "save_count": persistence.get("save_count", 0),
                    "load_count": persistence.get("load_count", 0),
                    "error_count": persistence.get("error_count", 0),
                    "file_size_bytes": persistence_file_size,
                    "file_healthy": persistence_file_healthy,
                },
                "validation_errors": metrics.get("validation_errors", 0),
                "issues": issues,
                "metrics": metrics,
            }
        except Exception as e:
            logger.error(f"Error checking signal tracker health: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
            }
    
    async def check_exit_signal_generator(self) -> Dict:
        """Check exit signal generator health."""
        if not self.exit_signal_generator:
            return {"status": "unknown", "message": "Exit signal generator not configured"}
        
        try:
            metrics = self.exit_signal_generator.get_exit_metrics()
            exit_gen = metrics.get("exit_generation", {})
            fallback = metrics.get("fallback_fetching", {})
            data_quality = metrics.get("data_quality", {})
            
            is_healthy = True
            issues = []
            
            # Check exit generation success rate
            exit_success_rate = exit_gen.get("success_rate", 0.0)
            if exit_gen.get("total_attempts", 0) > 0 and exit_success_rate < 0.5:
                is_healthy = False
                issues.append(f"Low exit generation success rate: {exit_success_rate:.2%}")
            
            # Check fallback fetch success rate
            fallback_success_rate = fallback.get("success_rate", 0.0)
            if fallback.get("total_attempts", 0) > 10 and fallback_success_rate < 0.3:
                is_healthy = False
                issues.append(f"Low fallback fetch success rate: {fallback_success_rate:.2%}")
            
            # Check data quality issues
            if data_quality.get("price_validation_failures", 0) > 20:
                is_healthy = False
                issues.append(f"High price validation failures: {data_quality['price_validation_failures']}")
            
            if data_quality.get("stale_data_warnings", 0) > 50:
                is_healthy = False
                issues.append(f"High stale data warnings: {data_quality['stale_data_warnings']}")
            
            return {
                "status": "healthy" if is_healthy else "unhealthy",
                "exit_generation": {
                    "total_attempts": exit_gen.get("total_attempts", 0),
                    "successful_exits": exit_gen.get("successful_exits", 0),
                    "success_rate": exit_success_rate,
                },
                "fallback_fetching": {
                    "total_attempts": fallback.get("total_attempts", 0),
                    "successful_fetches": fallback.get("successful_fetches", 0),
                    "success_rate": fallback_success_rate,
                },
                "data_quality": {
                    "price_validation_failures": data_quality.get("price_validation_failures", 0),
                    "stale_data_warnings": data_quality.get("stale_data_warnings", 0),
                },
                "issues": issues,
                "metrics": metrics,
            }
        except Exception as e:
            logger.error(f"Error checking exit signal generator health: {e}", exc_info=True)
            return {
                "status": "error",
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
        
        # Check signal tracker
        if self.signal_tracker:
            signal_tracker_health = await self.check_signal_tracker()
            checks["components"]["signal_tracker"] = signal_tracker_health
            if signal_tracker_health.get("status") not in ["healthy", "unknown"]:
                checks["overall_status"] = "degraded"
        
        # Check exit signal generator
        if self.exit_signal_generator:
            exit_generator_health = await self.check_exit_signal_generator()
            checks["components"]["exit_signal_generator"] = exit_generator_health
            if exit_generator_health.get("status") not in ["healthy", "unknown"]:
                checks["overall_status"] = "degraded"

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
