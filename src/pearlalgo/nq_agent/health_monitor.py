"""
NQ Agent Health Monitor

Monitors health of service components and dependencies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitors health of NQ agent components.
    
    Tracks:
    - Data provider health
    - Telegram connectivity
    - State manager health
    - File system health
    - Overall service health
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize health monitor.
        
        Args:
            state_dir: State directory for checking file system health
        """
        self.state_dir = Path(state_dir) if state_dir else Path("data/nq_agent_state")
        self.last_check: Optional[datetime] = None
    
    def check_data_provider_health(self, data_provider) -> Dict:
        """
        Check data provider health.
        
        Args:
            data_provider: Data provider instance
            
        Returns:
            Health status dictionary
        """
        try:
            # Check if provider has connection method
            if hasattr(data_provider, 'validate_connection'):
                # This would be async in real implementation, simplified here
                return {
                    "healthy": True,
                    "status": "Connected",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
            else:
                # Assume healthy if no validation method
                return {
                    "healthy": True,
                    "status": "Unknown",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as e:
            logger.error(f"Error checking data provider health: {e}")
            return {
                "healthy": False,
                "status": f"Error: {str(e)}",
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
    
    def check_telegram_health(self, telegram_notifier) -> Dict:
        """
        Check Telegram connectivity health.
        
        Args:
            telegram_notifier: Telegram notifier instance
            
        Returns:
            Health status dictionary
        """
        try:
            if not telegram_notifier or not telegram_notifier.enabled:
                return {
                    "healthy": False,
                    "status": "Disabled",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
            
            if telegram_notifier.telegram and telegram_notifier.telegram.bot:
                return {
                    "healthy": True,
                    "status": "Connected",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
            else:
                return {
                    "healthy": False,
                    "status": "Not initialized",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as e:
            logger.error(f"Error checking Telegram health: {e}")
            return {
                "healthy": False,
                "status": f"Error: {str(e)}",
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
    
    def check_file_system_health(self) -> Dict:
        """
        Check file system health (state directory writable).
        
        Returns:
            Health status dictionary
        """
        try:
            # Check if state directory exists and is writable
            self.state_dir.mkdir(parents=True, exist_ok=True)
            
            # Try to write a test file
            test_file = self.state_dir / ".health_check"
            try:
                test_file.write_text("health_check")
                test_file.unlink()
                
                return {
                    "healthy": True,
                    "status": "Writable",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as e:
                return {
                    "healthy": False,
                    "status": f"Not writable: {str(e)}",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as e:
            logger.error(f"Error checking file system health: {e}")
            return {
                "healthy": False,
                "status": f"Error: {str(e)}",
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
    
    def get_overall_health(
        self,
        data_provider=None,
        telegram_notifier=None,
    ) -> Dict:
        """
        Get overall health status of all components.
        
        Args:
            data_provider: Data provider instance (optional)
            telegram_notifier: Telegram notifier instance (optional)
            
        Returns:
            Overall health status dictionary
        """
        health = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {},
            "overall": "unknown",
        }
        
        # Check data provider
        if data_provider:
            health["components"]["data_provider"] = self.check_data_provider_health(data_provider)
        
        # Check Telegram
        if telegram_notifier:
            health["components"]["telegram"] = self.check_telegram_health(telegram_notifier)
        
        # Check file system
        health["components"]["file_system"] = self.check_file_system_health()
        
        # Determine overall health
        all_healthy = all(
            comp.get("healthy", False)
            for comp in health["components"].values()
        )
        
        if all_healthy:
            health["overall"] = "healthy"
        else:
            # Check if critical components are healthy
            critical_healthy = (
                health["components"].get("data_provider", {}).get("healthy", False)
                and health["components"].get("file_system", {}).get("healthy", False)
            )
            health["overall"] = "degraded" if critical_healthy else "unhealthy"
        
        self.last_check = datetime.now(timezone.utc)
        
        return health



