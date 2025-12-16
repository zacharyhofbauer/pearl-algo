"""
IBKR Connection Manager - Handles connection lifecycle and resilience.

Manages:
- Connection state machine (disconnected → connecting → connected)
- Automatic reconnection with exponential backoff
- Connection health monitoring
- Stale data detection
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional

from ib_insync import IB

from pearlalgo.utils.logger import logger


class ConnectionState(Enum):
    """Connection state machine states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class IBKRConnectionManager:
    """
    Manages IBKR connection lifecycle with automatic reconnection.
    
    Features:
    - State machine for connection tracking
    - Exponential backoff for reconnection
    - Health monitoring
    - Stale data detection
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 5,
        health_check_interval: float = 30.0,
        stale_data_threshold: float = 30.0,
    ):
        """
        Initialize connection manager.
        
        Args:
            host: IB Gateway host
            port: IB Gateway port
            client_id: Client ID for connection
            reconnect_delay: Initial delay between reconnection attempts (seconds)
            max_reconnect_attempts: Maximum reconnection attempts before giving up
            health_check_interval: Interval for health checks (seconds)
            stale_data_threshold: Time in seconds before data is considered stale
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.health_check_interval = health_check_interval
        self.stale_data_threshold = stale_data_threshold

        self.ib = IB()
        self.state = ConnectionState.DISCONNECTED
        self.reconnect_attempts = 0
        self.last_health_check: Optional[float] = None
        self.last_data_update: Optional[float] = None
        self._lock = asyncio.Lock()

        logger.info(
            f"IBKRConnectionManager initialized: host={host}, port={port}, client_id={client_id}"
        )

    async def connect(self, timeout: float = 10.0) -> bool:
        """
        Connect to IB Gateway.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected successfully, False otherwise
        """
        async with self._lock:
            if self.state == ConnectionState.CONNECTED:
                if self.ib.isConnected():
                    logger.debug("Already connected to IB Gateway")
                    return True
                else:
                    # Connection state says connected but IB says disconnected
                    self.state = ConnectionState.DISCONNECTED

            if self.state == ConnectionState.CONNECTING:
                logger.debug("Connection already in progress")
                return False

            self.state = ConnectionState.CONNECTING
            logger.info(f"Connecting to IB Gateway at {self.host}:{self.port}...")

        try:
            # Connect in a thread to avoid blocking
            loop = asyncio.get_event_loop()
            connected = await loop.run_in_executor(
                None,
                lambda: self.ib.connect(
                    host=self.host,
                    port=self.port,
                    clientId=self.client_id,
                    timeout=timeout,
                ),
            )

            async with self._lock:
                if connected and self.ib.isConnected():
                    self.state = ConnectionState.CONNECTED
                    self.reconnect_attempts = 0
                    self.last_health_check = time.time()
                    self.last_data_update = time.time()
                    logger.info(
                        f"Successfully connected to IB Gateway (client_id={self.client_id})"
                    )
                    return True
                else:
                    self.state = ConnectionState.DISCONNECTED
                    logger.error("Failed to connect to IB Gateway")
                    return False

        except Exception as e:
            async with self._lock:
                self.state = ConnectionState.DISCONNECTED
            logger.error(f"Error connecting to IB Gateway: {e}", exc_info=True)
            return False

    async def disconnect(self) -> None:
        """Disconnect from IB Gateway."""
        async with self._lock:
            if self.state == ConnectionState.DISCONNECTED:
                return

            logger.info("Disconnecting from IB Gateway...")
            try:
                if self.ib.isConnected():
                    self.ib.disconnect()
                self.state = ConnectionState.DISCONNECTED
                logger.info("Disconnected from IB Gateway")
            except Exception as e:
                logger.error(f"Error disconnecting from IB Gateway: {e}")
                self.state = ConnectionState.DISCONNECTED

    async def reconnect(self) -> bool:
        """
        Attempt to reconnect with exponential backoff.
        
        Returns:
            True if reconnected successfully, False otherwise
        """
        async with self._lock:
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logger.error(
                    f"Max reconnection attempts ({self.max_reconnect_attempts}) reached. "
                    "Connection failed."
                )
                self.state = ConnectionState.FAILED
                return False

            self.state = ConnectionState.RECONNECTING
            self.reconnect_attempts += 1

        # Exponential backoff
        delay = self.reconnect_delay * (2 ** (self.reconnect_attempts - 1))
        logger.info(
            f"Reconnecting to IB Gateway (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}) "
            f"after {delay:.1f}s delay..."
        )

        await asyncio.sleep(delay)

        return await self.connect()

    async def ensure_connected(self) -> bool:
        """
        Ensure connection is active, reconnect if needed.
        
        Returns:
            True if connected, False otherwise
        """
        async with self._lock:
            if self.state == ConnectionState.CONNECTED and self.ib.isConnected():
                return True

        # Not connected, try to reconnect
        if self.state == ConnectionState.FAILED:
            logger.warning("Connection is in failed state, attempting to reconnect...")
            return await self.reconnect()

        return await self.connect()

    async def health_check(self) -> bool:
        """
        Perform health check on connection.
        
        Returns:
            True if healthy, False otherwise
        """
        async with self._lock:
            if self.state != ConnectionState.CONNECTED:
                return False

            if not self.ib.isConnected():
                logger.warning("IB connection lost during health check")
                self.state = ConnectionState.DISCONNECTED
                return False

            self.last_health_check = time.time()
            return True

    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self.state == ConnectionState.CONNECTED and self.ib.isConnected()

    def get_state(self) -> ConnectionState:
        """Get current connection state."""
        return self.state

    def mark_data_update(self) -> None:
        """Mark that data was received (for stale data detection)."""
        self.last_data_update = time.time()

    def is_data_stale(self) -> bool:
        """
        Check if data is stale (no updates for threshold time).
        
        Returns:
            True if data is stale, False otherwise
        """
        if self.last_data_update is None:
            return True

        elapsed = time.time() - self.last_data_update
        return elapsed > self.stale_data_threshold

    def get_connection_info(self) -> dict:
        """Get connection information for logging/debugging."""
        return {
            "state": self.state.value,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "reconnect_attempts": self.reconnect_attempts,
            "is_connected": self.is_connected(),
            "last_health_check": self.last_health_check,
            "last_data_update": self.last_data_update,
            "is_data_stale": self.is_data_stale(),
        }
