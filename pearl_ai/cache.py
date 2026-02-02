"""
Pearl AI Response Cache - Semantic Caching with TTL

Caches LLM responses to reduce redundant API calls.
Uses semantic hashing based on query and state context.
Includes request deduplication to prevent duplicate LLM calls.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable, Awaitable
from enum import Enum
import hashlib
import json
import logging
import asyncio
from collections import OrderedDict

logger = logging.getLogger(__name__)


class CacheMissReason(Enum):
    """Categorizes why a cache miss occurred."""
    EXPIRED = "expired"
    NEVER_SEEN = "never_seen"
    SKIPPED_PATTERN = "skipped_pattern"
    STATE_CHANGED = "state_changed"


@dataclass
class CacheMissInfo:
    """Information about a cache miss."""
    reason: CacheMissReason
    key: Optional[str] = None
    context_hash: Optional[str] = None


@dataclass
class CacheEntry:
    """A single cache entry with TTL."""
    response: str
    created_at: datetime
    ttl_seconds: int
    hit_count: int = 0
    context_hash: str = ""  # Store context hash for state change detection

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return datetime.now() > self.created_at + timedelta(seconds=self.ttl_seconds)

    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return (datetime.now() - self.created_at).total_seconds()


class RequestDeduplicator:
    """
    Deduplicates concurrent requests within a time window.

    Prevents the same query from hitting the LLM multiple times
    when rapid-fire requests come in (e.g., user double-clicks).
    """

    def __init__(self, window_ms: int = 2000):
        """
        Initialize the deduplicator.

        Args:
            window_ms: Time window in milliseconds to consider requests as duplicates
        """
        self.window_ms = window_ms
        self._pending: Dict[str, asyncio.Future] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    async def dedupe(
        self,
        key: str,
        generator: Callable[[], Awaitable[str]],
    ) -> str:
        """
        Deduplicate a request.

        If a request with the same key is already pending, wait for its result.
        Otherwise, execute the generator and share the result with any
        concurrent requests that come in during execution.

        Args:
            key: Unique key for this request (usually cache key)
            generator: Async function that generates the response

        Returns:
            The response string (either freshly generated or shared from pending)
        """
        # Check if there's already a pending request for this key
        if key in self._pending:
            logger.debug(f"Dedup hit: waiting for pending request {key[:16]}...")
            try:
                return await self._pending[key]
            except Exception:
                # If the pending request failed, we'll try again
                pass

        # Create a future for this request
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[key] = future

        try:
            # Execute the generator
            result = await generator()
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            # Schedule cleanup after the window expires
            asyncio.get_event_loop().call_later(
                self.window_ms / 1000,
                self._cleanup_key,
                key
            )

    def _cleanup_key(self, key: str) -> None:
        """Remove a key from pending requests."""
        self._pending.pop(key, None)

    def is_pending(self, key: str) -> bool:
        """Check if a request is currently pending."""
        return key in self._pending

    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        return {
            "pending_requests": len(self._pending),
            "window_ms": self.window_ms,
        }


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

        # Cache miss categorization (A2.4)
        self._misses_by_reason: Dict[str, int] = {
            CacheMissReason.EXPIRED.value: 0,
            CacheMissReason.NEVER_SEEN.value: 0,
            CacheMissReason.SKIPPED_PATTERN.value: 0,
            CacheMissReason.STATE_CHANGED.value: 0,
        }

        # Track last context hash for state change detection
        self._last_context_hash: Optional[str] = None

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
            self._misses_by_reason[CacheMissReason.SKIPPED_PATTERN.value] += 1
            return None

        context_hash = self._context_hash(state)
        key = self._make_key(query, context_hash)

        entry = self.cache.get(key)

        if entry is None:
            self._misses += 1
            # Determine if it's a state change or never seen
            # Check if we have any entry for this normalized query with different context
            normalized = self._normalize_query(query)
            query_seen_before = any(
                self._normalize_query_from_key_partial(k, normalized)
                for k in self.cache.keys()
            )
            if query_seen_before:
                self._misses_by_reason[CacheMissReason.STATE_CHANGED.value] += 1
                logger.debug(f"Cache miss: state changed for query")
            else:
                self._misses_by_reason[CacheMissReason.NEVER_SEEN.value] += 1
                logger.debug(f"Cache miss: never seen query")
            return None

        if entry.is_expired:
            # Remove expired entry
            del self.cache[key]
            self._misses += 1
            self._misses_by_reason[CacheMissReason.EXPIRED.value] += 1
            logger.debug(f"Cache miss: expired entry (age: {entry.age_seconds:.0f}s)")
            return None

        # Cache hit - move to end (LRU) and increment hit count
        self.cache.move_to_end(key)
        entry.hit_count += 1
        self._hits += 1

        logger.debug(f"Cache hit for query (age: {entry.age_seconds:.0f}s)")
        return entry.response

    def _normalize_query_from_key_partial(self, key: str, normalized_query: str) -> bool:
        """Check if a cache key might match a normalized query (heuristic)."""
        # Since keys are hashes, we can't reverse them, but we track this
        # by storing normalized queries. For now, return False as we'd need
        # a reverse index for accurate detection.
        return False

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
            context_hash=context_hash,
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

        # Calculate miss reason percentages
        total_misses = self._misses if self._misses > 0 else 1
        misses_by_reason_pct = {
            reason: round(count / total_misses * 100, 1)
            for reason, count in self._misses_by_reason.items()
        }

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3),
            "evictions": self._evictions,
            "avg_entry_age_seconds": round(avg_age, 1),
            "misses_by_reason": self._misses_by_reason.copy(),
            "misses_by_reason_pct": misses_by_reason_pct,
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
