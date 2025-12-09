#!/usr/bin/env python
"""
Signal Generation Health Monitor

Monitors the 24/7 signal generation service and alerts on issues.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from loguru import logger
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    Bot = None
    TelegramError = Exception


class SignalHealthMonitor:
    """Monitor signal generation service health."""

    def __init__(
        self,
        service_name: str = "pearlalgo-signal_service.service",
        log_file: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        alert_threshold_minutes: int = 60,
    ):
        self.service_name = service_name
        self.log_file = log_file or str(PROJECT_ROOT / "logs" / "signal_generation.log")
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.alert_threshold_minutes = alert_threshold_minutes

        self.telegram_bot = None
        if telegram_bot_token and telegram_chat_id and Bot:
            try:
                self.telegram_bot = Bot(token=telegram_bot_token)
                logger.info("Telegram bot initialized for health alerts")
            except Exception as e:
                logger.warning(f"Failed to initialize Telegram bot: {e}")

    async def check_service_status(self) -> tuple[bool, str]:
        """
        Check if systemd service is running.

        Returns:
            Tuple of (is_running, status_message)
        """
        try:
            result = subprocess.run(
                ["systemctl", "is-active", self.service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            is_active = result.stdout.strip() == "active"
            status_msg = result.stdout.strip() or result.stderr.strip() or "unknown"

            if is_active:
                return True, f"Service is {status_msg}"
            else:
                return False, f"Service is {status_msg}"
        except subprocess.TimeoutExpired:
            return False, "Service check timed out"
        except FileNotFoundError:
            return False, "systemctl not found (not running as systemd service?)"
        except Exception as e:
            return False, f"Error checking service: {e}"

    def check_recent_activity(self, hours: int = 1) -> tuple[bool, str]:
        """
        Check for recent signal activity in log file.

        Args:
            hours: Hours to look back

        Returns:
            Tuple of (has_activity, status_message)
        """
        log_path = Path(self.log_file)
        if not log_path.exists():
            return False, f"Log file not found: {self.log_file}"

        try:
            # Read last N lines of log file
            with open(log_path, "r") as f:
                lines = f.readlines()
                if not lines:
                    return False, "Log file is empty"

                # Check for recent activity (look for "Cycle #" or "completed successfully")
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
                recent_activity = False

                # Check last 100 lines for activity
                for line in lines[-100:]:
                    if "completed successfully" in line or "Cycle #" in line:
                        # Try to parse timestamp from log line
                        try:
                            # Log format: "2025-01-01 12:00:00 | INFO | ..."
                            if "|" in line:
                                timestamp_str = line.split("|")[0].strip()
                                log_time = datetime.strptime(
                                    timestamp_str, "%Y-%m-%d %H:%M:%S"
                                )
                                # Assume UTC if no timezone
                                if log_time.tzinfo is None:
                                    log_time = log_time.replace(tzinfo=timezone.utc)

                                if log_time >= cutoff_time:
                                    recent_activity = True
                                    break
                        except Exception:
                            # If we can't parse, assume recent if line exists
                            recent_activity = True
                            break

                if recent_activity:
                    return True, f"Recent activity found in last {hours} hour(s)"
                else:
                    return False, f"No recent activity in last {hours} hour(s)"

        except Exception as e:
            return False, f"Error checking log file: {e}"

    def check_polygon_api(self) -> tuple[bool, str]:
        """
        Check Polygon API connectivity.

        Returns:
            Tuple of (is_healthy, status_message)
        """
        try:
            import os
            from pearlalgo.data_providers.polygon_provider import PolygonDataProvider

            api_key = os.getenv("POLYGON_API_KEY")
            if not api_key:
                return False, "POLYGON_API_KEY not set"

            # Try to create provider (doesn't make API call)
            provider = PolygonDataProvider(api_key=api_key)
            return True, "Polygon API key configured"

        except Exception as e:
            return False, f"Polygon API check failed: {e}"

    def check_telegram_config(self) -> tuple[bool, str]:
        """
        Check Telegram configuration.

        Returns:
            Tuple of (is_configured, status_message)
        """
        try:
            import os

            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")

            if not bot_token:
                return False, "TELEGRAM_BOT_TOKEN not set"
            if not chat_id:
                return False, "TELEGRAM_CHAT_ID not set"

            return True, "Telegram configured"

        except Exception as e:
            return False, f"Telegram check failed: {e}"

    async def send_alert(self, message: str) -> bool:
        """Send health alert to Telegram."""
        if not self.telegram_bot or not self.telegram_chat_id:
            logger.warning("Telegram not configured, cannot send alert")
            return False

        try:
            await self.telegram_bot.send_message(
                chat_id=self.telegram_chat_id,
                text=f"⚠️ *Health Alert*\n\n{message}",
                parse_mode="Markdown",
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False

    async def run_health_check(self) -> dict:
        """
        Run complete health check.

        Returns:
            Dictionary with health status
        """
        logger.info("Running health check...")

        checks = {}

        # Check service status
        is_running, status_msg = await self.check_service_status()
        checks["service"] = {"healthy": is_running, "message": status_msg}

        # Check recent activity
        has_activity, activity_msg = self.check_recent_activity(
            hours=self.alert_threshold_minutes // 60
        )
        checks["activity"] = {"healthy": has_activity, "message": activity_msg}

        # Check Polygon API
        polygon_ok, polygon_msg = self.check_polygon_api()
        checks["polygon"] = {"healthy": polygon_ok, "message": polygon_msg}

        # Check Telegram
        telegram_ok, telegram_msg = self.check_telegram_config()
        checks["telegram"] = {"healthy": telegram_ok, "message": telegram_msg}

        # Determine overall health
        all_healthy = all(c["healthy"] for c in checks.values())
        checks["overall"] = {"healthy": all_healthy, "message": "All checks passed" if all_healthy else "Some checks failed"}

        # Send alert if unhealthy
        if not all_healthy:
            failed_checks = [name for name, check in checks.items() if not check["healthy"]]
            alert_msg = f"Health check failed:\n\n"
            for name in failed_checks:
                alert_msg += f"• {name}: {checks[name]['message']}\n"
            await self.send_alert(alert_msg)

        return checks


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Signal Generation Health Monitor")
    parser.add_argument(
        "--service-name",
        type=str,
        default="pearlalgo-signal_service.service",
        help="Systemd service name",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Path to signal generation log file",
    )
    parser.add_argument(
        "--telegram-bot-token",
        type=str,
        help="Telegram bot token for alerts",
    )
    parser.add_argument(
        "--telegram-chat-id",
        type=str,
        help="Telegram chat ID for alerts",
    )
    parser.add_argument(
        "--alert-threshold",
        type=int,
        default=60,
        help="Alert threshold in minutes (default: 60)",
    )

    args = parser.parse_args()

    # Load from environment if not provided
    import os

    telegram_bot_token = args.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = args.telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")

    monitor = SignalHealthMonitor(
        service_name=args.service_name,
        log_file=args.log_file,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        alert_threshold_minutes=args.alert_threshold,
    )

    import asyncio

    health_status = await monitor.run_health_check()

    # Print results
    print("\n" + "=" * 60)
    print("Health Check Results")
    print("=" * 60)
    for name, check in health_status.items():
        status = "✅" if check["healthy"] else "❌"
        print(f"{status} {name}: {check['message']}")
    print("=" * 60)

    # Exit with error if unhealthy
    if not health_status["overall"]["healthy"]:
        sys.exit(1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

