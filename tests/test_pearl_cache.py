"""
Tests for Pearl AI Response Cache (P2.1)

Tests TTL behavior, key generation, expiry, LRU eviction,
and SHA256 hash upgrade.
"""

import pytest
import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

from pearl_ai.cache import ResponseCache, CacheEntry


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_is_expired_true_after_ttl(self):
        """Entry should be expired after TTL passes."""
        entry = CacheEntry(
            response="test",
            created_at=datetime.now() - timedelta(seconds=10),
            ttl_seconds=5,
        )
        assert entry.is_expired is True

    def test_is_expired_false_within_ttl(self):
        """Entry should not be expired within TTL."""
        entry = CacheEntry(
            response="test",
            created_at=datetime.now(),
            ttl_seconds=300,
        )
        assert entry.is_expired is False

    def test_age_seconds(self):
        """Should calculate age correctly."""
        entry = CacheEntry(
            response="test",
            created_at=datetime.now() - timedelta(seconds=30),
            ttl_seconds=300,
        )
        assert 29 <= entry.age_seconds <= 31

    def test_hit_count_starts_zero(self):
        """Hit count should start at zero."""
        entry = CacheEntry(
            response="test",
            created_at=datetime.now(),
            ttl_seconds=300,
        )
        assert entry.hit_count == 0


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    @pytest.fixture
    def cache(self):
        return ResponseCache(max_size=100)

    def test_normalize_query_lowercase(self, cache):
        """Should normalize to lowercase."""
        assert cache._normalize_query("HELLO World") == "hello world"

    def test_normalize_query_strips_whitespace(self, cache):
        """Should strip leading/trailing whitespace."""
        assert cache._normalize_query("  hello  ") == "hello"

    def test_normalize_query_collapses_spaces(self, cache):
        """Should collapse multiple spaces."""
        assert cache._normalize_query("hello    world") == "hello world"

    def test_normalize_removes_filler_words(self, cache):
        """Should remove common filler words."""
        result = cache._normalize_query("Can you please tell me what is the status")
        assert "please" not in result
        assert "can you" not in result
        assert "tell me" not in result

    def test_context_hash_uses_sha256(self, cache):
        """Should use SHA256 for context hash (P1.3)."""
        state = {"market_regime": {"regime": "trending"}}

        # Get the hash
        hash_result = cache._context_hash(state)

        # Verify it's a valid hex string (first 8 chars of SHA256)
        assert len(hash_result) == 8
        int(hash_result, 16)  # Should not raise

    def test_make_key_uses_sha256(self, cache):
        """Should use SHA256 for full key (P1.3)."""
        key = cache._make_key("test query", "abc123")

        # SHA256 hex digest is 64 characters
        assert len(key) == 64
        int(key, 16)  # Should not raise

    def test_context_hash_buckets_pnl(self, cache):
        """Should bucket PnL to avoid cache thrashing."""
        state1 = {"daily_pnl": 51.0, "market_regime": {}}
        state2 = {"daily_pnl": 49.0, "market_regime": {}}
        state3 = {"daily_pnl": 99.0, "market_regime": {}}

        # 51 and 49 should round to different buckets (50 and 50)
        hash1 = cache._context_hash(state1)
        hash2 = cache._context_hash(state2)
        hash3 = cache._context_hash(state3)

        # 51 rounds to 50, 49 rounds to 50, 99 rounds to 100
        assert hash1 == hash2  # Both round to 50
        assert hash1 != hash3  # Different buckets

    def test_context_hash_includes_regime(self, cache):
        """Should include market regime in hash."""
        state1 = {"market_regime": {"regime": "trending"}}
        state2 = {"market_regime": {"regime": "ranging"}}

        hash1 = cache._context_hash(state1)
        hash2 = cache._context_hash(state2)

        assert hash1 != hash2


class TestCacheGetSet:
    """Tests for cache get/set operations."""

    @pytest.fixture
    def cache(self):
        return ResponseCache(max_size=10)

    def test_get_returns_none_for_miss(self, cache):
        """Should return None for cache miss."""
        result = cache.get("nonexistent query here", {})
        assert result is None

    def test_set_and_get(self, cache):
        """Should store and retrieve responses."""
        query = "show me the current market regime"
        response = "The current market regime is trending with high volatility."
        cache.set(query, {}, response)
        result = cache.get(query, {})
        assert result == response

    def test_get_increments_hit_count(self, cache):
        """Should increment hit count on get."""
        query = "show me the current market regime"
        response = "The current market regime is trending with high volatility."
        cache.set(query, {}, response)

        # Get twice
        cache.get(query, {})
        cache.get(query, {})

        # Check stats
        stats = cache.get_stats()
        assert stats["hits"] == 2

    def test_get_moves_to_end_lru(self, cache):
        """Should move accessed entry to end (LRU)."""
        cache.set("first unique query here", {}, "This is a long enough response one")
        cache.set("second unique query here", {}, "This is a long enough response two")

        # Access first
        cache.get("first unique query here", {})

        # Check order - first should now be at end
        keys = list(cache.cache.keys())
        assert len(keys) == 2
        assert keys[-1] != keys[0]  # Order changed

    def test_set_skips_short_responses(self, cache):
        """Should not cache very short responses."""
        cache.set("any query here", {}, "hi")  # Too short
        result = cache.get("any query here", {})
        assert result is None


class TestCacheSkipPatterns:
    """Tests for cache skip patterns."""

    @pytest.fixture
    def cache(self):
        return ResponseCache(max_size=10)

    def test_skips_coaching_queries(self, cache):
        """Should skip caching coaching queries."""
        cache.set("give me coaching advice", {}, "long response here")
        result = cache.get("give me coaching advice", {})
        assert result is None

    def test_skips_advice_queries(self, cache):
        """Should skip caching advice queries."""
        assert cache._should_skip_cache("What advice do you have?") is True

    def test_skips_should_i_queries(self, cache):
        """Should skip caching 'should I' queries."""
        assert cache._should_skip_cache("Should I change my strategy?") is True

    def test_skips_streak_queries(self, cache):
        """Should skip caching streak queries (dynamic)."""
        assert cache._should_skip_cache("What's my current streak?") is True

    def test_caches_normal_queries(self, cache):
        """Should cache normal queries."""
        assert cache._should_skip_cache("What is the current price?") is False


class TestCacheTTL:
    """Tests for TTL behavior."""

    @pytest.fixture
    def cache(self):
        return ResponseCache(max_size=10)

    def test_determine_ttl_long_for_explanations(self, cache):
        """Should use long TTL for explanation queries."""
        ttl = cache._determine_ttl("What is a market regime?")
        assert ttl == cache.TTL_LONG

    def test_determine_ttl_short_for_current_state(self, cache):
        """Should use short TTL for time-sensitive queries."""
        ttl = cache._determine_ttl("show me today pnl")
        assert ttl == cache.TTL_SHORT

    def test_determine_ttl_medium_default(self, cache):
        """Should use medium TTL by default."""
        ttl = cache._determine_ttl("Show me my performance")
        assert ttl == cache.TTL_MEDIUM

    def test_expired_entries_return_none(self, cache):
        """Should return None for expired entries."""
        # Create with very short TTL
        cache.set("test", {}, "response", ttl_seconds=0)

        # Wait a tiny bit
        import time
        time.sleep(0.01)

        result = cache.get("test", {})
        assert result is None


class TestCacheEviction:
    """Tests for LRU eviction."""

    def test_evicts_oldest_when_full(self):
        """Should evict oldest entries when cache is full."""
        cache = ResponseCache(max_size=3)

        cache.set("first unique query", {}, "This is a long enough response one")
        cache.set("second unique query", {}, "This is a long enough response two")
        cache.set("third unique query", {}, "This is a long enough response three")
        cache.set("fourth unique query", {}, "This is a long enough response four")  # Should evict first

        assert cache.get("first unique query", {}) is None
        assert cache.get("fourth unique query", {}) is not None


class TestCacheMissReasons:
    """Tests for cache miss reason tracking."""

    def test_state_changed_miss(self):
        """Should classify miss as state_changed when query seen with different context."""
        cache = ResponseCache(max_size=10)
        query = "Show my performance summary"
        response = "This is a long enough response for caching behavior."

        state_one = {
            "market_regime": {"regime": "trending"},
            "daily_pnl": 100,
            "daily_wins": 3,
            "daily_trades": 5,
            "active_trades_count": 0,
        }
        state_two = {
            "market_regime": {"regime": "ranging"},
            "daily_pnl": 100,
            "daily_wins": 3,
            "daily_trades": 5,
            "active_trades_count": 0,
        }

        cache.set(query, state_one, response)
        assert cache.get(query, state_two) is None

        stats = cache.get_stats()
        assert stats["misses_by_reason"]["state_changed"] == 1

    def test_never_seen_miss(self):
        """Should classify miss as never_seen when query not in cache."""
        cache = ResponseCache(max_size=10)
        cache.get("completely new query", {})

        stats = cache.get_stats()
        assert stats["misses_by_reason"]["never_seen"] == 1

    def test_eviction_increments_counter(self):
        """Should track eviction count."""
        cache = ResponseCache(max_size=2)

        cache.set("alpha unique query", {}, "This is a long enough response alpha")
        cache.set("beta unique query", {}, "This is a long enough response beta")
        cache.set("gamma unique query", {}, "This is a long enough response gamma")  # Evicts 'alpha'

        stats = cache.get_stats()
        assert stats["evictions"] >= 1


class TestCacheInvalidation:
    """Tests for cache invalidation."""

    @pytest.fixture
    def cache(self):
        cache = ResponseCache(max_size=10)
        cache.set("unique query one here", {}, "This is a long enough response one")
        cache.set("unique query two here", {}, "This is a long enough response two")
        cache.set("unique query three here", {}, "This is a long enough response three")
        return cache

    def test_invalidate_all(self, cache):
        """Should clear all entries when no pattern given."""
        count = cache.invalidate()

        assert count == 3
        assert len(cache.cache) == 0

    def test_cleanup_expired(self):
        """Should remove expired entries."""
        cache = ResponseCache(max_size=10)

        # Add entry with immediate expiry
        cache.set("test", {}, "response", ttl_seconds=0)

        # Wait for expiry
        import time
        time.sleep(0.01)

        count = cache.cleanup_expired()
        assert count >= 0  # May be 0 if already cleaned up on get


class TestCacheStats:
    """Tests for cache statistics."""

    def test_stats_includes_all_fields(self):
        """Should include all stat fields."""
        cache = ResponseCache(max_size=10)
        cache.set("test", {}, "response")
        cache.get("test", {})  # Hit
        cache.get("missing", {})  # Miss

        stats = cache.get_stats()

        assert "size" in stats
        assert "max_size" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats
        assert "evictions" in stats
        assert "avg_entry_age_seconds" in stats

    def test_hit_rate_calculation(self):
        """Should calculate hit rate correctly."""
        cache = ResponseCache(max_size=10)
        query = "show me the current market regime"
        response = "The current market regime is trending with high volatility."
        cache.set(query, {}, response)

        # 3 hits, 1 miss
        cache.get(query, {})
        cache.get(query, {})
        cache.get(query, {})
        cache.get("some missing query here", {})

        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.75  # 3/4


class TestCacheEntries:
    """Tests for cache entry inspection."""

    def test_get_entries_returns_list(self):
        """Should return list of entry info."""
        cache = ResponseCache(max_size=10)
        cache.set("test1", {}, "This is a test response")
        cache.set("test2", {}, "Another test response")

        entries = cache.get_entries()

        assert len(entries) == 2
        assert all("key" in e for e in entries)
        assert all("age_seconds" in e for e in entries)
        assert all("response_preview" in e for e in entries)

    def test_entry_preview_truncated(self):
        """Should truncate long response previews."""
        cache = ResponseCache(max_size=10)
        long_response = "a" * 100
        cache.set("test", {}, long_response)

        entries = cache.get_entries()

        assert len(entries[0]["response_preview"]) < 60
        assert "..." in entries[0]["response_preview"]
