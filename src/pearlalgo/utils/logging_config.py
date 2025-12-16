"""
Logging configuration and setup utilities.

This module provides structured logging setup with correlation IDs and timing metrics.
It is separate from `logger.py` which provides the logger instance used throughout the codebase.

**When to use this module:**
- For initial logging setup (e.g., in main.py)
- For structured logging configuration
- For correlation ID management
- For timing decorators

**When to use `logger.py` instead:**
- For actual logging calls in production code
- For simple logger instance access
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from loguru import logger as loguru_logger
    HAS_LOGURU = True
except ImportError:
    HAS_LOGURU = False
from rich.logging import RichHandler

# Context variable for correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID from context."""
    return correlation_id_var.get()


def set_correlation_id(cid: Optional[str] = None) -> str:
    """
    Set correlation ID in context.
    
    Args:
        cid: Optional correlation ID. If None, generates a new UUID.
        
    Returns:
        The correlation ID (newly generated or provided).
    """
    if cid is None:
        cid = str(uuid.uuid4())
    correlation_id_var.set(cid)
    return cid


def clear_correlation_id() -> None:
    """Clear correlation ID from context."""
    correlation_id_var.set(None)


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        
        # Add extra fields if present
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        
        # Add timing if present
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    structured: bool = True,
    json_output: bool = False,
) -> None:
    """
    Setup logging with structured logging support.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        structured: Enable structured logging with correlation IDs
        json_output: Output logs as JSON (for log aggregation)
    """
    if HAS_LOGURU and not json_output:
        # Use loguru for rich console output
        import sys
        from loguru import logger
        
        logger.remove()  # Remove default handler
        
        # Console handler with rich formatting
        logger.add(
            sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
            level=level,
            colorize=True,
        )
        
        # File handler if specified
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logger.add(
                log_path,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
                level=level,
                rotation="10 MB",
                retention="7 days",
                serialize=structured,  # JSON output if structured
            )
        # Return early when using loguru - no need for standard logging setup
        return
    
    # Use standard logging (when loguru not available or json_output requested)
    handlers = []
    
    if json_output:
        # JSON formatter for structured logs
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(StructuredFormatter())
        handlers.append(console_handler)
    else:
        # Rich handler for console
        handlers.append(RichHandler(rich_tracebacks=True))

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        if structured:
            file_handler.setFormatter(StructuredFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format="%(message)s" if not json_output else "",
        datefmt="[%X]",
        handlers=handlers,
    )


def log_timing(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to log function execution time.
    
    Adds duration_ms to log records.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.time()
        correlation_id = get_correlation_id() or set_correlation_id()
        
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            
            logger = logging.getLogger(func.__module__)
            logger.info(
                f"{func.__name__} completed",
                extra={
                    "duration_ms": duration_ms,
                    "correlation_id": correlation_id,
                    "function": func.__name__,
                },
            )
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger = logging.getLogger(func.__module__)
            logger.error(
                f"{func.__name__} failed: {e}",
                exc_info=True,
                extra={
                    "duration_ms": duration_ms,
                    "correlation_id": correlation_id,
                    "function": func.__name__,
                },
            )
            raise
    
    return wrapper


def async_log_timing(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to log async function execution time.
    
    Adds duration_ms to log records.
    """
    import asyncio
    
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.time()
        correlation_id = get_correlation_id() or set_correlation_id()
        
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            
            logger = logging.getLogger(func.__module__)
            logger.info(
                f"{func.__name__} completed",
                extra={
                    "duration_ms": duration_ms,
                    "correlation_id": correlation_id,
                    "function": func.__name__,
                },
            )
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger = logging.getLogger(func.__module__)
            logger.error(
                f"{func.__name__} failed: {e}",
                exc_info=True,
                extra={
                    "duration_ms": duration_ms,
                    "correlation_id": correlation_id,
                    "function": func.__name__,
                },
            )
            raise
    
    return wrapper
