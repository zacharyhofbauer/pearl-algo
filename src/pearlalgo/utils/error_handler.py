"""
Centralized error handling utilities.

Provides standardized error detection and handling patterns.

Example usage:
    ```python
    try:
        data = await fetch_data()
    except Exception as e:
        error_info = ErrorHandler.handle_data_fetch_error(e, context={"symbol": "MNQ"})
        if error_info.get("is_connection_error"):
            # Handle connection error
            pass
    ```
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pearlalgo.utils.logger import logger


class ErrorHandler:
    """Centralized error handling utilities."""

    @staticmethod
    def is_connection_error(error: Exception) -> bool:
        """
        Detect if error is connection-related.
        
        Args:
            error: Exception to check
            
        Returns:
            True if error appears to be connection-related
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        connection_keywords = [
            "connection",
            "refused",
            "timeout",
            "connect",
            "network",
            "unreachable",
            "reset",
            "broken pipe",
        ]
        
        return any(keyword in error_str or keyword in error_type for keyword in connection_keywords)

    @staticmethod
    def is_connection_error_from_data(
        market_data: Dict,
        data_provider=None,
        last_successful_cycle: Optional[datetime] = None,
    ) -> bool:
        """
        Check if empty data is due to connection error vs normal market closure.
        
        Args:
            market_data: Market data dictionary
            data_provider: Data provider instance (optional)
            last_successful_cycle: Last successful cycle timestamp (optional)
            
        Returns:
            True if this appears to be a connection error
        """
        # Check if data provider executor is connected
        try:
            if data_provider and hasattr(data_provider, '_executor'):
                executor = data_provider._executor
                if hasattr(executor, 'is_connected'):
                    if not executor.is_connected():
                        return True
        except Exception:
            pass  # If we can't check, assume it might be a connection issue

        # If data is empty and we have no latest_bar, likely a connection issue
        if market_data.get("df") is not None and market_data["df"].empty:
            if market_data.get("latest_bar") is None:
                # If we've had recent successful cycles but now getting empty data,
                # it's likely a connection issue (not just market closed)
                if last_successful_cycle:
                    time_since_success = (datetime.now(timezone.utc) - last_successful_cycle).total_seconds()
                    if time_since_success < 600:  # Had data within last 10 minutes
                        return True
        return False

    @staticmethod
    def handle_data_fetch_error(error: Exception, context: Optional[Dict] = None) -> Dict:
        """
        Standardized data fetch error handling.
        
        Args:
            error: Exception that occurred
            context: Optional context dictionary
            
        Returns:
            Dictionary with error information and standardized response
        """
        context = context or {}
        is_connection = ErrorHandler.is_connection_error(error)
        
        error_info = {
            "error": str(error),
            "error_type": type(error).__name__,
            "is_connection_error": is_connection,
            "context": context,
        }
        
        if is_connection:
            logger.warning(f"Data fetch connection error: {error}", extra=context)
        else:
            logger.error(f"Data fetch error: {error}", exc_info=True, extra=context)
        
        return error_info

    @staticmethod
    def handle_telegram_error(error: Exception, notification_type: str) -> None:
        """
        Standardized Telegram error handling.
        
        Args:
            error: Exception that occurred
            notification_type: Type of notification that failed
        """
        logger.error(
            f"Telegram notification error ({notification_type}): {error}",
            exc_info=True,
            extra={"notification_type": notification_type},
        )
