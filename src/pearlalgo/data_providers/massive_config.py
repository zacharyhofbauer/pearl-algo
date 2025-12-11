"""
Massive.com Configuration

Centralized configuration for Massive API including API keys, URLs, rate limits, and retry settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class MassiveConfig:
    """Massive.com API configuration."""
    
    api_key: str
    base_url: str = "https://api.massive.com"
    rate_limit_delay: float = 0.25  # seconds between requests (4 req/sec default)
    
    # Rate limit settings
    requests_per_minute: int = 200  # Developer tier default
    burst_limit: int = 10  # Burst requests allowed
    
    # Retry settings
    max_retries: int = 3
    initial_backoff: float = 1.0  # seconds
    max_backoff: float = 60.0  # seconds
    backoff_multiplier: float = 2.0
    
    # Circuit breaker settings
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 60.0  # seconds
    
    # Request timeout
    request_timeout: float = 30.0  # seconds
    
    @classmethod
    def from_env(cls, api_key: Optional[str] = None) -> MassiveConfig:
        """
        Create configuration from environment variables.
        
        Args:
            api_key: API key (if None, reads from MASSIVE_API_KEY env var)
            
        Returns:
            MassiveConfig instance
            
        Raises:
            ValueError: If API key is not provided
        """
        api_key = api_key or os.getenv("MASSIVE_API_KEY")
        if not api_key:
            raise ValueError(
                "Massive API key required. Set MASSIVE_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        base_url = os.getenv("MASSIVE_BASE_URL", "https://api.massive.com")
        
        return cls(
            api_key=api_key,
            base_url=base_url,
            rate_limit_delay=float(os.getenv("MASSIVE_RATE_LIMIT_DELAY", "0.25")),
            requests_per_minute=int(os.getenv("MASSIVE_REQUESTS_PER_MINUTE", "200")),
            burst_limit=int(os.getenv("MASSIVE_BURST_LIMIT", "10")),
            max_retries=int(os.getenv("MASSIVE_MAX_RETRIES", "3")),
            initial_backoff=float(os.getenv("MASSIVE_INITIAL_BACKOFF", "1.0")),
            max_backoff=float(os.getenv("MASSIVE_MAX_BACKOFF", "60.0")),
            backoff_multiplier=float(os.getenv("MASSIVE_BACKOFF_MULTIPLIER", "2.0")),
            circuit_breaker_failure_threshold=int(
                os.getenv("MASSIVE_CIRCUIT_BREAKER_THRESHOLD", "5")
            ),
            circuit_breaker_recovery_timeout=float(
                os.getenv("MASSIVE_CIRCUIT_BREAKER_TIMEOUT", "60.0")
            ),
            request_timeout=float(os.getenv("MASSIVE_REQUEST_TIMEOUT", "30.0")),
        )
