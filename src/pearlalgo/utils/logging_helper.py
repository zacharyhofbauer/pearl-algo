"""
Logging helper - Provides loguru logger with fallback to standard logging.
"""
import logging

try:
    from loguru import logger
except ImportError:
    # Fallback to standard logging if loguru not available
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

