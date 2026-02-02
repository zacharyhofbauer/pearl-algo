"""
Pearl AI Response Cache - Semantic Caching with TTL

Caches LLM responses to reduce redundant API calls.
Uses semantic hashing based on query and state context.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import hashlib
import json
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A single cache entry with TTL."""
    response: str
    created_at: datetime
    ttl_seconds: int
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return datetime.now() > self.created_at + timedelta(seconds=self.ttl_seconds)

    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return (datetime.now() - self.created_at).total_seconds()


class ResponseCache:
    """
    LRU cache with TTL for Pearl AI responses.

    Features:
    - Semantic key generation based on query and context
    - Configurable TTL per entry type
    - LRU eviction when max size reached
    - Skip cache for personalized content
    """

    # Default TTL values (seconds)
    TTL_SHORT = 300      # 5 minutes - state-dependent queries
    TTL_MEDIUM = 1800    # 30 minutes - general questions
    TTL_LONG = 3600      # 1 hour - static content

    # Queries that should skip cache (personalized/dynamic content)
    NO_CACHE_PATTERNS = [
        "coaching",
        "advice",
        "suggest",
        "should i",
        "what should",
        "help me",
        "streak",
        "consecutive",
    ]

    def __init__(self, max_size: int = 100):
        """
        Initialize response cache.

        Args:
            max_size: Maximum number of entries to keep
        """
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size

        # Stats
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def _normalize_query(self, query: str) -> str:
        """Normalize query for consistent hashing."""
        # Lowercase, strip whitespace, remove punctuation
        normalized = query.lower().strip()
        # Remove common filler words
        for word in ["please", "can you", "could you", "tell me", "what is", "what's"]:
            normalized = normalized.replace(word, "")
        return " ".join(normalized.split())  # Collapse whitespace

    def _context_hash(self, state: Dict[str, Any]) -> str:
        """
        Hash relevant state for cache invalidation.

        Only includes state that affects responses:
        - Market regime
        - P&L bucket (rounded to avoid cache thrashing)
        - Win rate bucket
        - Active position state

        Uses SHA256 for cryptographically stronger hashing (P1.3).
        """
        relevant = {
            "regime": state.get("market_regime", {}).get("regime"),
            "pnl_bucket": self._bucket_value(state.get("daily_pnl", 0), 50),  # $50 buckets
            "win_rate_bucket": self._bucket_rate(state),
            "has_position": state.get("active_trades_count", 0) > 0,
        }

        hash_input = json.dumps(relevant, sort_keys=True)
        return hashlib.sha256(hash_input.encode()).hexdigest()[:8]

    def _bucket_value(self, value: float, bucket_size: float) -> int:
        """Round value to nearest bucket."""
        return int(round(value / bucket_size) * bucket_size)

    def _bucket_rate(self, state: Dict[str, Any]) -> int:
        """Bucket win rate to nearest 10%."""
        wins = state.get("daily_wins", 0)
        trades = state.get("daily_trades", 1)
        if trades == 0:
            return 0
        rate = wins / trades
        return int(round(rate * 10) * 10)  # 0, 10, 20, ..., 100

    def _make_key(self, query: str, context_hash: str) -> str:
        """Create cache key from query and context. Uses SHA256 (P1.3)."""
        normalized = self._normalize_query(query)
        key_input = f"{normalized}:{context_hash}"
        return hashlib.sha256(key_input.encode()).hexdigest()

    def _should_skip_cache(self, query: str) -> bool:
        """Check if query should skip cache."""
        query_lower = query.lower()
        return any(pattern in query_lower for pattern in self.NO_CACHE_PATTERNS)

    def _determine_ttl(self, query: str) -> int:
        """Determine TTL based on query type."""
        query_lower = query.lower()

        # Static/general questions - longer TTL
        if any(word in query_lower for word in ["what is", "how does", "explain", "define"]):
            return self.TTL_LONG

        # Time-sensitive questions - shorter TTL
        if any(word in query_lower for word in ["today", "now", "current", "active"]):
            return self.TTL_SHORT

        # Default to medium TTL
        return self.TTL_MEDIUM

    def get(self, query: str, state: Dict[str, Any]) -> Optional[str]:
        """
        Get cached response if valid.

        Args:
            query: User's query
            state: Current trading state

        Returns:
            Cached response or None if not found/expired
        """
        # Skip cache for certain query types
        if self._should_skip_cache(query):
            self._misses += 1
            return None

        context_hash = self._context_hash(state)
        key = self._make_key(query, context_hash)

        entry = self.cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired:
            # Remove expired entry
            del self.cache[key]
            self._misses += 1
            return None

        # Cache hit - move to end (LRU) and increment hit count
        self.cache.move_to_end(key)
        entry.hit_count += 1
        self._hits += 1

        logger.debug(f"Cache hit for query (age: {entry.age_seconds:.0f}s)")
        return entry.response

    def set(
        self,
        query: str,
        state: Dict[str, Any],
        response: str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Cache a response.

        Args:
            query: User's query
            state: Current trading state
            response: LLM response to cache
            ttl_seconds: Optional custom TTL
        """
        # Don't cache if query should skip
        if self._should_skip_cache(query):
            return

        # Don't cache very short responses (likely errors)
        if len(response) < 20:
            return

        context_hash = self._context_hash(state)
        key = self._make_key(query, context_hash)

        # Determine TTL
        ttl = ttl_seconds or self._determine_ttl(query)

        # Create entry
        entry = CacheEntry(
            response=response,
            created_at=datetime.now(),
            ttl_seconds=ttl,
        )

        # Add to cache (will be at end = most recently used)
        self.cache[key] = entry

        # Evict if needed
        self._evict_if_needed()

        logger.debug(f"Cached response (TTL: {ttl}s)")

    def _evict_if_needed(self) -> None:
        """Evict oldest entries if cache is full."""
        while len(self.cache) > self.max_size:
            # Remove oldest (first) entry
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            self._evictions += 1

    def invalidate(self, pattern: Optional[str] = None) -> int:
        """
        Invalidate cache entries.

        Args:
            pattern: Optional pattern to match keys. If None, clears all.

        Returns:
            Number of entries invalidated
        """
        if pattern is None:
            count = len(self.cache)
            self.cache.clear()
            return count

        # Find and remove matching entries
        to_remove = [
            key for key in self.cache.keys()
            if pattern in key
        ]

        for key in to_remove:
            del self.cache[key]

        return len(to_remove)

    def cleanup_expired(self) -> int:
        """
        Remove expired entries.

        Returns:
            Number of entries removed
        """
        expired_keys = [
            key for key, entry in self.cache.items()
            if entry.is_expired
        ]

        for key in expired_keys:
            del self.cache[key]

        return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0

        # Calculate average age of entries
        ages = [entry.age_seconds for entry in self.cache.values()]
        avg_age = sum(ages) / len(ages) if ages else 0

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3),
            "evictions": self._evictions,
            "avg_entry_age_seconds": round(avg_age, 1),
        }

    def get_entries(self) -> List[Dict[str, Any]]:
        """Get all cache entries for debugging."""
        return [
            {
                "key": key[:16] + "...",  # Truncate for readability
                "age_seconds": round(entry.age_seconds, 1),
                "ttl_seconds": entry.ttl_seconds,
                "hit_count": entry.hit_count,
                "expired": entry.is_expired,
                "response_preview": entry.response[:50] + "..." if len(entry.response) > 50 else entry.response,
            }
            for key, entry in self.cache.items()
        ]
