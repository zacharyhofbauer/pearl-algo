"""
State Persistence Store for LangGraph Trading System.

Supports both file-based (default) and Redis (optional) backends for state persistence.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

from pearlalgo.agents.langgraph_state import TradingState

logger = logging.getLogger(__name__)


class StateStore:
    """
    State persistence store with file-based (default) and Redis (optional) backends.
    
    Automatically falls back to file-based storage if Redis is unavailable.
    """
    
    def __init__(
        self,
        storage_path: str = "state_cache/trading_state.json",
        use_redis: bool = False,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None,
    ):
        """
        Initialize state store.
        
        Args:
            storage_path: Path to file-based storage (default)
            use_redis: Whether to use Redis backend (requires redis package)
            redis_host: Redis host
            redis_port: Redis port
            redis_db: Redis database number
            redis_password: Redis password (if required)
        """
        self.storage_path = Path(storage_path)
        self.use_redis = use_redis and HAS_REDIS
        self.redis_client = None
        
        # Ensure storage directory exists for file-based storage
        if self.storage_path:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize Redis if requested and available
        if self.use_redis:
            try:
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password,
                    decode_responses=False,  # We'll handle JSON encoding
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                # Test connection
                self.redis_client.ping()
                logger.info(f"Connected to Redis at {redis_host}:{redis_port}")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}. Falling back to file-based storage.")
                self.use_redis = False
                self.redis_client = None
    
    def save(self, state: TradingState, key: str = "trading_state") -> bool:
        """
        Save trading state to storage.
        
        Args:
            state: TradingState to save
            key: Storage key (for Redis) or filename (for file-based)
            
        Returns:
            True if save was successful, False otherwise
        """
        try:
            # Convert state to JSON-serializable dict
            state_dict = state.model_dump(mode='json')
            
            if self.use_redis and self.redis_client:
                # Save to Redis
                try:
                    state_json = json.dumps(state_dict)
                    self.redis_client.set(key, state_json)
                    logger.debug(f"Saved state to Redis with key: {key}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to save to Redis: {e}. Falling back to file.")
                    self.use_redis = False
            
            # Fall back to file-based storage
            with open(self.storage_path, 'w') as f:
                json.dump(state_dict, f, indent=2, default=str)
            logger.debug(f"Saved state to file: {self.storage_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return False
    
    def load(self, key: str = "trading_state") -> Optional[TradingState]:
        """
        Load trading state from storage.
        
        Args:
            key: Storage key (for Redis) or filename (for file-based)
            
        Returns:
            TradingState if loaded successfully, None otherwise
        """
        try:
            state_dict = None
            
            if self.use_redis and self.redis_client:
                # Load from Redis
                try:
                    state_json = self.redis_client.get(key)
                    if state_json:
                        state_dict = json.loads(state_json)
                        logger.debug(f"Loaded state from Redis with key: {key}")
                except Exception as e:
                    logger.warning(f"Failed to load from Redis: {e}. Trying file-based storage.")
            
            # Fall back to file-based storage if Redis failed or not used
            if state_dict is None and self.storage_path.exists():
                with open(self.storage_path, 'r') as f:
                    state_dict = json.load(f)
                logger.debug(f"Loaded state from file: {self.storage_path}")
            
            if state_dict is None:
                logger.warning("No saved state found")
                return None
            
            # Reconstruct TradingState from dict
            # Note: Portfolio and RiskState need special handling
            # For now, we'll load basic fields and let the workflow reconstruct complex objects
            state = TradingState.model_validate(state_dict)
            logger.info("Successfully loaded trading state")
            return state
            
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None
    
    def exists(self, key: str = "trading_state") -> bool:
        """
        Check if state exists in storage.
        
        Args:
            key: Storage key (for Redis) or filename (for file-based)
            
        Returns:
            True if state exists, False otherwise
        """
        if self.use_redis and self.redis_client:
            try:
                return self.redis_client.exists(key) > 0
            except Exception:
                pass
        
        return self.storage_path.exists()
    
    def delete(self, key: str = "trading_state") -> bool:
        """
        Delete state from storage.
        
        Args:
            key: Storage key (for Redis) or filename (for file-based)
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            if self.use_redis and self.redis_client:
                try:
                    self.redis_client.delete(key)
                    logger.debug(f"Deleted state from Redis with key: {key}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to delete from Redis: {e}")
            
            if self.storage_path.exists():
                self.storage_path.unlink()
                logger.debug(f"Deleted state file: {self.storage_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to delete state: {e}")
            return False


def create_state_store(
    storage_path: Optional[str] = None,
    use_redis: Optional[bool] = None,
    redis_host: Optional[str] = None,
    redis_port: Optional[int] = None,
    redis_db: Optional[int] = None,
    redis_password: Optional[str] = None,
) -> StateStore:
    """
    Factory function to create a StateStore with environment-based configuration.
    
    Args:
        storage_path: Path to file-based storage (defaults to state_cache/trading_state.json)
        use_redis: Whether to use Redis (defaults to False, or True if REDIS_HOST is set)
        redis_host: Redis host (defaults to localhost or REDIS_HOST env var)
        redis_port: Redis port (defaults to 6379 or REDIS_PORT env var)
        redis_db: Redis database (defaults to 0 or REDIS_DB env var)
        redis_password: Redis password (defaults to None or REDIS_PASSWORD env var)
        
    Returns:
        Configured StateStore instance
    """
    import os
    
    # Get defaults from environment or use provided values
    storage_path = storage_path or os.getenv("STATE_STORAGE_PATH", "state_cache/trading_state.json")
    
    if use_redis is None:
        use_redis = os.getenv("REDIS_HOST") is not None
    
    redis_host = redis_host or os.getenv("REDIS_HOST", "localhost")
    redis_port = redis_port or int(os.getenv("REDIS_PORT", "6379"))
    redis_db = redis_db or int(os.getenv("REDIS_DB", "0"))
    redis_password = redis_password or os.getenv("REDIS_PASSWORD")
    
    return StateStore(
        storage_path=storage_path,
        use_redis=use_redis,
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        redis_password=redis_password,
    )

