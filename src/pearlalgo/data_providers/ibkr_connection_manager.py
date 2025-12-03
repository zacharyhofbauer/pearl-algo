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
        
        ALWAYS connects in a dedicated thread to avoid ANY event loop conflicts.
        This is the most reliable approach - ib_insync connections work best
        when created in their own thread with their own event loop.
        """
        with self._connection_lock:
            if self._ib is not None and self._ib.isConnected():
                return self._ib
            
            # Always use thread-based connection to avoid event loop conflicts
            # This works reliably in both sync and async contexts
            return self._connect_in_thread()
    
    
    def _connect_in_thread(self) -> IB:
        """
        Connect to IBKR in a dedicated thread with its own event loop.
        
        This avoids "This event loop is already running" errors by ensuring
        ib.connect() runs in a thread with no running event loop.
        """
        import queue
        import time
        
        result_queue = queue.Queue()
        error_queue = queue.Queue()
        
        def connect_thread():
            """Connect in thread - this is the ONLY reliable way."""
            new_loop = None
            try:
                # Create a completely fresh event loop for this thread
                # This thread has NO existing event loop, so ib_insync can create its own
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                
                ib = IB()
                
                # Use sync connect - it will work because we're in a fresh thread
                # with no running event loop. ib_insync will create its own loop internally.
                ib.connect(
                    self.connection.host,
                    self.connection.port,
                    clientId=self.connection.client_id,
                    timeout=15,  # Longer timeout for reliability
                )
                
                # Store connection and event loop
                self._ib = ib
                self._event_loop = new_loop
                
                logger.info(
                    f"IBKR connected: {self.connection.host}:{self.connection.port} "
                    f"clientId={self.connection.client_id}"
                )
                
                result_queue.put(ib)
                connection_ready.set()
                
                # Keep the connection alive by running the event loop
                # ib_insync needs the event loop to stay running
                try:
                    new_loop.run_forever()
                except:
                    pass
            except Exception as e:
                import traceback
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"IBKR connection failed in thread: {error_msg}")
                logger.debug(traceback.format_exc())
                error_queue.put(e)
                connection_ready.set()
                if new_loop:
                    try:
                        new_loop.close()
                    except:
                        pass
        
        # Start connection thread
        connection_ready = threading.Event()
        thread = threading.Thread(target=connect_thread, daemon=True, name=f"IBKR-Conn-{self.connection.client_id}")
        thread.start()
        
        # Wait for connection (with timeout)
        if connection_ready.wait(timeout=25):  # Wait up to 25 seconds
            if not error_queue.empty():
                error = error_queue.get()
                raise error
            if not result_queue.empty():
                ib = result_queue.get()
                # Give it a moment to fully establish
                time.sleep(0.5)
                if ib.isConnected():
                    return ib
                else:
                    raise RuntimeError("Connection established but not connected")
            else:
                raise RuntimeError("Connection thread finished but no result")
        else:
            raise TimeoutError(
                f"IBKR connection timed out after 25 seconds "
                f"(clientId={self.connection.client_id})"
            )
    
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
                    # Stop the event loop in the thread
                    self._event_loop.call_soon_threadsafe(self._event_loop.stop)
                except:
                    pass
                self._event_loop = None

