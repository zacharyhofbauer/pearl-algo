"""Tests for pearlalgo.utils.rate_limiter -- Issue 3."""

import time

import pytest

from pearlalgo.utils.rate_limiter import SlidingWindowRateLimiter


class TestSlidingWindowRateLimiter:
    def test_allows_under_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)
        assert limiter.is_allowed() is True

    def test_blocks_at_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            limiter.record()
        assert limiter.is_allowed() is False

    def test_allows_after_window(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=0.05)
        limiter.record()
        assert limiter.is_allowed() is False
        time.sleep(0.06)
        assert limiter.is_allowed() is True

    def test_time_until_allowed_zero_when_ok(self):
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)
        assert limiter.time_until_allowed() == 0.0

    def test_time_until_allowed_positive_when_blocked(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
        limiter.record()
        wait = limiter.time_until_allowed()
        assert wait > 0
        assert wait <= 60.0

    def test_check_and_record_atomic(self):
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
        assert limiter.check_and_record() is True
        assert limiter.check_and_record() is True
        assert limiter.check_and_record() is False

    def test_reset_clears_all(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
        limiter.record()
        assert limiter.is_allowed() is False
        limiter.reset()
        assert limiter.is_allowed() is True

    def test_thread_safety(self):
        """Basic thread safety smoke test."""
        import threading
        limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60.0)
        errors = []

        def worker():
            try:
                for _ in range(50):
                    limiter.check_and_record()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
