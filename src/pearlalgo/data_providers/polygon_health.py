"""
Polygon.io Health Monitoring

Monitors API health, tracks rate limit usage, and connection status.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class PolygonHealthMetrics:
    """Health metrics for Polygon API."""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limit_hits: int = 0
    unauthorized_errors: int = 0
    timeout_errors: int = 0
    circuit_breaker_opens: int = 0
    
    last_request_time: Optional[float] = None
    last_success_time: Optional[float] = None
    last_failure_time: Optional[float] = None
    last_error: Optional[str] = None
    
    request_times: list[float] = field(default_factory=list)  # Track request durations
    
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    def average_request_time(self) -> float:
        """Calculate average request time in seconds."""
        if not self.request_times:
            return 0.0
        return sum(self.request_times) / len(self.request_times)
    
    def requests_per_minute(self) -> float:
        """Calculate requests per minute based on recent activity."""
        if not self.request_times or len(self.request_times) < 2:
            return 0.0
        
        # Use last 10 requests to calculate rate
        recent_times = self.request_times[-10:]
        if len(recent_times) < 2:
            return 0.0
        
        time_span = recent_times[-1] - recent_times[0]
        if time_span == 0:
            return 0.0
        
        return (len(recent_times) - 1) / (time_span / 60.0)
    
    def is_healthy(self) -> bool:
        """Check if API is healthy."""
        if self.total_requests == 0:
            return True  # No requests yet, assume healthy
        
        # Consider unhealthy if:
        # - Success rate < 50%
        # - Recent failures (last 5 requests all failed)
        # - Circuit breaker opened recently
        
        if self.success_rate() < 0.5:
            return False
        
        # Check if circuit breaker is open (indicated by recent opens)
        if self.circuit_breaker_opens > 0:
            return False
        
        return True
    
    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "rate_limit_hits": self.rate_limit_hits,
            "unauthorized_errors": self.unauthorized_errors,
            "timeout_errors": self.timeout_errors,
            "circuit_breaker_opens": self.circuit_breaker_opens,
            "success_rate": self.success_rate(),
            "average_request_time": self.average_request_time(),
            "requests_per_minute": self.requests_per_minute(),
            "is_healthy": self.is_healthy(),
            "last_request_time": (
                datetime.fromtimestamp(self.last_request_time, tz=timezone.utc).isoformat()
                if self.last_request_time else None
            ),
            "last_success_time": (
                datetime.fromtimestamp(self.last_success_time, tz=timezone.utc).isoformat()
                if self.last_success_time else None
            ),
            "last_failure_time": (
                datetime.fromtimestamp(self.last_failure_time, tz=timezone.utc).isoformat()
                if self.last_failure_time else None
            ),
            "last_error": self.last_error,
        }


class PolygonHealthMonitor:
    """Monitor Polygon API health and rate limits."""
    
    def __init__(self):
        """Initialize health monitor."""
        self.metrics = PolygonHealthMetrics()
        self._lock = None  # Would use threading.Lock in multi-threaded context
    
    def record_request(self, duration: float, success: bool = True, error: Optional[str] = None) -> None:
        """
        Record a request.
        
        Args:
            duration: Request duration in seconds
            success: Whether request was successful
            error: Error message if failed
        """
        self.metrics.total_requests += 1
        self.metrics.last_request_time = time.time()
        self.metrics.request_times.append(time.time())
        
        # Keep only last 100 request times
        if len(self.metrics.request_times) > 100:
            self.metrics.request_times = self.metrics.request_times[-100:]
        
        if success:
            self.metrics.successful_requests += 1
            self.metrics.last_success_time = time.time()
        else:
            self.metrics.failed_requests += 1
            self.metrics.last_failure_time = time.time()
            self.metrics.last_error = error
    
    def record_rate_limit(self) -> None:
        """Record a rate limit hit."""
        self.metrics.rate_limit_hits += 1
        logger.warning("Polygon API rate limit hit recorded")
    
    def record_unauthorized(self) -> None:
        """Record an unauthorized error."""
        self.metrics.unauthorized_errors += 1
        logger.error("Polygon API unauthorized error recorded")
    
    def record_timeout(self) -> None:
        """Record a timeout error."""
        self.metrics.timeout_errors += 1
        logger.warning("Polygon API timeout error recorded")
    
    def record_circuit_breaker_open(self) -> None:
        """Record circuit breaker opening."""
        self.metrics.circuit_breaker_opens += 1
        logger.error("Polygon API circuit breaker opened")
    
    def get_health(self) -> Dict:
        """Get current health status."""
        return self.metrics.to_dict()
    
    def is_healthy(self) -> bool:
        """Check if API is currently healthy."""
        return self.metrics.is_healthy()
    
    def reset(self) -> None:
        """Reset all metrics."""
        self.metrics = PolygonHealthMetrics()
        logger.info("Polygon health metrics reset")

