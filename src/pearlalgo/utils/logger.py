"""
Centralized logger setup.

Provides a single logger instance for use across the codebase.
Uses loguru if available, falls back to standard logging.
"""

from __future__ import annotations

import logging

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger("pearlalgo")

__all__ = ["logger"]




