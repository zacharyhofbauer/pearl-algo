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

**Environment variables (systemd/journald friendly):**
- PEARLALGO_LOG_LEVEL: Override log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- PEARLALGO_LOG_JSON: Set to "1" or "true" to emit JSON logs to stdout (useful for log aggregation)
- PEARLALGO_LOG_EXTRA: Set to "1" or "true" to append extra={...} context to text log lines

When stdout is not a TTY (e.g., under systemd), ANSI colors are automatically disabled.
"""
from __future__ import annotations

import json
import logging
import os
import sys
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

# Context variable for correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)

# Context variable for run ID (stable across the entire process lifetime)
run_id_var: ContextVar[Optional[str]] = ContextVar("run_id", default=None)


def _is_truthy_env(name: str) -> bool:
    """Check if an environment variable is set to a truthy value."""
    val = os.getenv(name, "").lower().strip()
    return val in ("1", "true", "yes", "on")


def _is_tty() -> bool:
    """Check if stdout is a TTY (interactive terminal)."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


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


def get_run_id() -> Optional[str]:
    """Get current run ID from context (stable for process lifetime)."""
    return run_id_var.get()


def set_run_id(rid: Optional[str] = None) -> str:
    """
    Set run ID in context.
    
    This should be called once at process startup. The run_id is stable
    for the entire process lifetime and helps correlate all logs from
    a single service run.
    
    Args:
        rid: Optional run ID. If None, generates a short UUID prefix.
        
    Returns:
        The run ID (newly generated or provided).
    """
    if rid is None:
        # Use first 8 chars of UUID for brevity in logs
        rid = str(uuid.uuid4())[:8]
    run_id_var.set(rid)
    return rid


def clear_run_id() -> None:
    """Clear run ID from context."""
    run_id_var.set(None)


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging (systemd/journald friendly)."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": get_run_id(),
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


class SystemdFriendlyFormatter(logging.Formatter):
    """
    Text formatter that appends extra context for systemd/journald readability.
    
    When PEARLALGO_LOG_EXTRA is set, includes extra={...} context in text output.
    Always includes run_id if set.
    """
    
    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        include_extra: bool = False,
    ):
        super().__init__(fmt, datefmt)
        self.include_extra = include_extra
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with optional extra context."""
        # Build base message
        base = super().format(record)
        
        # Collect context fields
        context_parts = []
        
        # Always include run_id if set
        run_id = get_run_id()
        if run_id:
            context_parts.append(f"run_id={run_id}")
        
        # Include extra fields if enabled
        if self.include_extra:
            # Common extra fields to surface
            extra_keys = ["cycle", "signals", "data_fresh", "market_open", "buffer_size",
                          "error_count", "connection_failures", "quiet_reason", "duration_ms"]
            extras = {}
            for key in extra_keys:
                if hasattr(record, key):
                    extras[key] = getattr(record, key)
            if extras:
                context_parts.append(f"extra={extras}")
        
        if context_parts:
            return f"{base} | {' '.join(context_parts)}"
        return base


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    structured: bool = True,
    json_output: bool = False,
) -> None:
    """
    Setup logging with structured logging support.
    
    Respects environment variables:
    - PEARLALGO_LOG_LEVEL: Override log level
    - PEARLALGO_LOG_JSON: Enable JSON output to stdout
    - PEARLALGO_LOG_EXTRA: Include extra={...} context in text logs
    
    When stdout is not a TTY (e.g., under systemd), ANSI colors are disabled.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        structured: Enable structured logging with correlation IDs
        json_output: Output logs as JSON (for log aggregation)
    """
    # Environment variable overrides
    env_level = os.getenv("PEARLALGO_LOG_LEVEL", "").upper().strip()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = env_level
    
    env_json = _is_truthy_env("PEARLALGO_LOG_JSON")
    if env_json:
        json_output = True
    
    include_extra = _is_truthy_env("PEARLALGO_LOG_EXTRA")
    
    # Detect TTY for color decisions
    is_tty = _is_tty()
    
    if HAS_LOGURU and not json_output:
        # Use loguru for console output
        from loguru import logger
        
        logger.remove()  # Remove default handler
        
        # Choose format based on TTY detection
        if is_tty:
            # Rich colored output for interactive terminals
            console_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
            colorize = True
        else:
            # Plain text for systemd/journald (no ANSI codes)
            # Include run_id placeholder that loguru can interpolate via bind()
            console_format = (
                "{time:YYYY-MM-DD HH:mm:ss} | "
                "{level: <8} | "
                "{name}:{function}:{line} | "
                "{message}"
            )
            # Append extra context if enabled
            if include_extra:
                console_format += " | {extra}"
            colorize = False
        
        logger.add(
            sys.stdout,
            format=console_format,
            level=level,
            colorize=colorize,
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
    handlers: list[logging.Handler] = []
    
    if json_output:
        # JSON formatter for structured logs (ideal for log aggregation)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(StructuredFormatter())
        handlers.append(console_handler)
    else:
        # Text output with optional extra context
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            SystemdFriendlyFormatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                include_extra=include_extra,
            )
        )
        handlers.append(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        if structured:
            file_handler.setFormatter(StructuredFormatter())
        else:
            file_handler.setFormatter(
                SystemdFriendlyFormatter(
                    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                    include_extra=include_extra,
                )
            )
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format="%(message)s" if json_output else "",
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
