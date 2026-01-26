"""
Retry utility functions.

Provides async retry decorator with exponential backoff.

Example usage:
    ```python
    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def fetch_data():
        # Your async function
        pass
    ```
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Awaitable, Callable, TypeVar

from pearlalgo.utils.logger import logger

T = TypeVar("T")


def async_retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator to retry async functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        exceptions: Tuple of exception types to catch and retry
        
    Returns:
        Decorated async function with retry logic
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}"
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * exponential_base, max_delay)
                    else:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded for {func.__name__}"
                        )

            # If we get here, all retries failed
            if last_exception is not None:
                raise last_exception
            raise RuntimeError("Retry failed but no exception was captured")

        return wrapper
    return decorator

