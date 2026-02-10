"""
Shared sliding-window rate limiter.

Replaces the duplicate implementations in ``ai/chat.py`` and
``api/server.py`` with a single, tested utility.

Usage::

    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)

    if limiter.is_allowed():
        limiter.record()
        # ... proceed ...
    else:
        wait = limiter.time_until_allowed()
        # ... reject or wait ...
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import List


@dataclass
class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter.

    Maintains a list of request timestamps and evicts entries older than
    *window_seconds* on each check.
    """

    max_requests: int = 5
    window_seconds: float = 60.0
    _timestamps: List[float] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _evict_expired(self, now: float) -> None:
        """Remove timestamps outside the current window (must hold lock)."""
        cutoff = now - self.window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def is_allowed(self) -> bool:
        """Return ``True`` if a request is allowed under the current limit."""
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            return len(self._timestamps) < self.max_requests

    def record(self) -> None:
        """Record a request timestamp."""
        now = time.monotonic()
        with self._lock:
            self._timestamps.append(now)

    def check_and_record(self) -> bool:
        """Atomically check and record in one call.

        Returns ``True`` if allowed (and records), ``False`` if rate-limited.
        """
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return True
            return False

    def time_until_allowed(self) -> float:
        """Return seconds until the next request would be allowed.

        Returns ``0.0`` if a request is allowed right now.
        """
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if len(self._timestamps) < self.max_requests:
                return 0.0
            oldest = min(self._timestamps)
            return max(0.0, self.window_seconds - (now - oldest))

    def reset(self) -> None:
        """Clear all recorded timestamps."""
        with self._lock:
            self._timestamps.clear()
