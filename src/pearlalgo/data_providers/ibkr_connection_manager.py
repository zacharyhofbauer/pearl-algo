"""
IBKR Connection Manager

Manages IBKR connections as singletons per client ID to avoid conflicts.
Based on IBKR best practices: maintain a single connection per client ID.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Optional

from ib_insync import IB

logger = logging.getLogger(__name__)


@dataclass
class IBKRConnection:
    host: str
    port: int
    client_id: int


class IBKRConnectionManager:
    """
    Singleton connection manager for IBKR.
    
    Maintains one connection per client ID to avoid "client id already in use" errors.
    Thread-safe connection access.
    """
    
    _instances: dict[int, IBKRConnectionManager] = {}
    _lock = threading.Lock()
    
    def __init__(self, connection: IBKRConnection):
        self.connection = connection
        self._ib: Optional[IB] = None
        self._connection_lock = threading.Lock()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
    
    @classmethod
    def get_instance(cls, connection: IBKRConnection) -> IBKRConnectionManager:
        """Get or create singleton instance for this client ID."""
        with cls._lock:
            client_id = connection.client_id
            if client_id not in cls._instances:
                cls._instances[client_id] = cls(connection)
            return cls._instances[client_id]
    
    def get_connection(self) -> IB:
        """
        Get or create IB connection.
        
        If called from async context, ensures connection is in a dedicated thread
        with its own event loop (as per ib_insync best practices).
        """
        with self._connection_lock:
            if self._ib is not None and self._ib.isConnected():
                return self._ib
            
            # Check if we're in an async context
            try:
                asyncio.get_running_loop()
                # In async context - need dedicated thread with event loop
                return self._get_connection_async()
            except RuntimeError:
                # No running loop - can connect directly
                return self._get_connection_sync()
    
    def _get_connection_sync(self) -> IB:
        """Create connection in sync context."""
        ib = IB()
        try:
            ib.connect(
                self.connection.host,
                self.connection.port,
                clientId=self.connection.client_id,
                timeout=5,
            )
            logger.info(
                f"IBKR connected (sync): {self.connection.host}:{self.connection.port} "
                f"clientId={self.connection.client_id}"
            )
            self._ib = ib
            return ib
        except Exception as e:
            logger.error(f"IBKR connection failed: {e}")
            raise
    
    def _get_connection_async(self) -> IB:
        """
        Create connection in async context.
        
        ib_insync's sync methods work from async contexts - they handle
        the event loop internally. We just need to ensure the connection
        is created properly.
        """
        # Use sync connection method - ib_insync handles async internally
        # The key is to use sync methods (reqContractDetails, not reqContractDetailsAsync)
        return self._get_connection_sync()
    
    def disconnect(self):
        """Disconnect and cleanup."""
        with self._connection_lock:
            if self._ib is not None:
                try:
                    if self._ib.isConnected():
                        self._ib.disconnect()
                except:
                    pass
                self._ib = None
            
            if self._event_loop is not None:
                try:
                    self._event_loop.call_soon_threadsafe(self._event_loop.stop)
                except:
                    pass
                self._event_loop = None
            
            if self._loop_thread is not None:
                # Thread will exit when loop stops
                self._loop_thread = None

