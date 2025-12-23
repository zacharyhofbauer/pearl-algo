"""
Centralized logger setup.

Provides a single logger instance for use across the codebase.
Uses loguru if available, falls back to standard logging.

**Compatibility layer:**
This module provides a CompatLogger adapter that makes Loguru work seamlessly
with stdlib-style logging calls, including:
- extra={...} parameter (translates to loguru.bind())
- exc_info=True parameter (translates to loguru.opt(exception=True))
- printf-style %s formatting (translates to str % args)

This allows existing code to work unchanged while getting proper structured
logging and stack traces.
"""

from __future__ import annotations

import logging
from typing import Any


class CompatLogger:
    """
    A compatibility adapter that wraps Loguru to support stdlib-style logging calls.
    
    Handles three common patterns that behave differently between stdlib and Loguru:
    1. extra={...} - stdlib puts these in LogRecord, Loguru needs bind()
    2. exc_info=True - stdlib includes traceback, Loguru needs opt(exception=True)
    3. printf-style args - stdlib uses %s, Loguru uses {}
    
    This adapter translates at call time so existing code works unchanged.
    """
    
    def __init__(self, loguru_logger: Any) -> None:
        self._logger = loguru_logger
    
    def _log(self, level: str, message: str, *args: Any, **kwargs: Any) -> None:
        """
        Internal method to handle all log levels with compatibility translation.
        
        Args:
            level: Log level name (debug, info, warning, error, critical)
            message: Log message (may contain %s placeholders)
            *args: Printf-style arguments for message formatting
            **kwargs: May contain 'extra' dict and/or 'exc_info' bool
        """
        # Extract stdlib-style parameters
        extra = kwargs.pop("extra", None)
        exc_info = kwargs.pop("exc_info", False)
        
        # Handle printf-style formatting (%s, %d, etc.)
        if args:
            try:
                message = message % args
            except (TypeError, ValueError):
                # If formatting fails, append args to message
                message = f"{message} {args}"
        
        # Build the logger with bound context if extra provided
        log_fn = self._logger
        if extra:
            log_fn = log_fn.bind(**extra)
        
        # Build opt() kwargs - combine all options in a single call
        # to avoid chained opt() calls losing previous settings
        opt_kwargs: dict[str, Any] = {"depth": 1}
        if exc_info:
            opt_kwargs["exception"] = True
        
        # Apply options and get the logging method
        log_method = getattr(log_fn.opt(**opt_kwargs), level)
        log_method(message, **kwargs)
    
    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log at DEBUG level with stdlib compatibility."""
        self._log("debug", message, *args, **kwargs)
    
    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log at INFO level with stdlib compatibility."""
        self._log("info", message, *args, **kwargs)
    
    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log at WARNING level with stdlib compatibility."""
        self._log("warning", message, *args, **kwargs)
    
    def warn(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Alias for warning() for stdlib compatibility."""
        self._log("warning", message, *args, **kwargs)
    
    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log at ERROR level with stdlib compatibility."""
        self._log("error", message, *args, **kwargs)
    
    def critical(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log at CRITICAL level with stdlib compatibility."""
        self._log("critical", message, *args, **kwargs)
    
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log at ERROR level with exception info (like stdlib logger.exception())."""
        kwargs["exc_info"] = True
        self._log("error", message, *args, **kwargs)
    
    # Delegate Loguru-native methods for code that wants to use them directly
    def bind(self, **kwargs: Any) -> Any:
        """Loguru-native: return a logger with bound context."""
        return self._logger.bind(**kwargs)
    
    def opt(self, **kwargs: Any) -> Any:
        """Loguru-native: return a logger with options."""
        return self._logger.opt(**kwargs)
    
    def add(self, *args: Any, **kwargs: Any) -> Any:
        """Loguru-native: add a handler."""
        return self._logger.add(*args, **kwargs)
    
    def remove(self, *args: Any, **kwargs: Any) -> None:
        """Loguru-native: remove a handler."""
        return self._logger.remove(*args, **kwargs)
    
    def configure(self, *args: Any, **kwargs: Any) -> Any:
        """Loguru-native: configure the logger."""
        return self._logger.configure(*args, **kwargs)
    
    def complete(self) -> Any:
        """Loguru-native: wait for all handlers to complete."""
        return self._logger.complete()
    
    @property
    def level(self) -> Any:
        """Access the underlying logger's level."""
        return getattr(self._logger, "level", None)
    
    def __getattr__(self, name: str) -> Any:
        """Delegate any other attributes to the underlying logger."""
        return getattr(self._logger, name)


# Create the logger instance
try:
    from loguru import logger as loguru_logger
    # Wrap Loguru with compatibility layer
    logger = CompatLogger(loguru_logger)
    HAS_LOGURU = True
except ImportError:
    logger = logging.getLogger("pearlalgo")  # type: ignore[assignment]
    HAS_LOGURU = False

__all__ = ["logger", "CompatLogger", "HAS_LOGURU"]
