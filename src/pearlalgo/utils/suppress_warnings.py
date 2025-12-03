"""
Utility to suppress noisy warnings from third-party libraries.
"""
import warnings
import sys
import logging

# Suppress "Task exception was never retrieved" warnings from ib_insync
# These happen when async tasks fail but aren't awaited
def suppress_async_task_warnings():
    """Suppress noisy async task warnings from ib_insync."""
    import asyncio
    
    def custom_exception_handler(loop, context):
        """Custom exception handler that suppresses ConnectionRefusedError from ib_insync."""
        exception = context.get('exception')
        if exception and isinstance(exception, (ConnectionRefusedError, OSError)):
            # Suppress connection errors - these are expected when Gateway isn't running
            return
        # For other exceptions, use default handler
        loop.default_exception_handler(context)
    
    # Set custom exception handler for the event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't set handler on running loop, but we can suppress warnings
            warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*Task exception.*')
        else:
            loop.set_exception_handler(custom_exception_handler)
    except RuntimeError:
        # No event loop, create one with custom handler
        pass

# Suppress specific warnings
warnings.filterwarnings('ignore', message='.*Task exception was never retrieved.*')
warnings.filterwarnings('ignore', message='.*This event loop is already running.*')

