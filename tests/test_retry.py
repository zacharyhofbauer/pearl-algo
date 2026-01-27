"""
Tests for Retry Logic.

Validates async retry decorator with exponential backoff.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from pearlalgo.utils.retry import async_retry_with_backoff


class TestAsyncRetryWithBackoff:
    """Test async retry decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        """Should return immediately on success."""
        call_count = 0
        
        @async_retry_with_backoff(max_retries=3)
        async def succeeds():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await succeeds()
        
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        """Should retry on failure."""
        call_count = 0
        
        @async_retry_with_backoff(max_retries=3, initial_delay=0.01)
        async def fails_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary failure")
            return "success"
        
        result = await fails_twice()
        
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        """Should raise after exhausting retries."""
        call_count = 0
        
        @async_retry_with_backoff(max_retries=3, initial_delay=0.01)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("Permanent failure")
        
        with pytest.raises(ValueError, match="Permanent failure"):
            await always_fails()
        
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_respects_max_retries(self):
        """Should not exceed max retries."""
        call_count = 0
        
        @async_retry_with_backoff(max_retries=5, initial_delay=0.01)
        async def fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Error")
        
        try:
            await fails()
        except RuntimeError:
            pass
        
        assert call_count == 5

    @pytest.mark.asyncio
    async def test_passes_arguments(self):
        """Should pass through function arguments."""
        @async_retry_with_backoff(max_retries=2)
        async def add(a, b, c=0):
            return a + b + c
        
        result = await add(1, 2, c=3)
        assert result == 6

    @pytest.mark.asyncio
    async def test_specific_exceptions(self):
        """Should only retry specified exceptions."""
        call_count = 0
        
        @async_retry_with_backoff(
            max_retries=3, 
            exceptions=(ValueError,), 
            initial_delay=0.01
        )
        async def conditional_fail():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TypeError("Not retried")
            return "success"
        
        with pytest.raises(TypeError):
            await conditional_fail()
        
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self):
        """Should apply exponential backoff."""
        call_count = 0
        delays = []
        
        original_sleep = asyncio.sleep
        
        async def mock_sleep(duration):
            delays.append(duration)
            await original_sleep(0.001)  # Minimal actual sleep
        
        @async_retry_with_backoff(
            max_retries=4,
            initial_delay=0.1,
            exponential_base=2.0,
            max_delay=10.0,
        )
        async def track_delay():
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise ValueError("Retry")
            return "done"
        
        with patch("pearlalgo.utils.retry.asyncio.sleep", mock_sleep):
            result = await track_delay()
        
        assert result == "done"
        # Should have recorded delays for retries 1, 2, 3
        assert len(delays) == 3
        # Each delay should be >= previous (exponential)
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i-1]

    @pytest.mark.asyncio
    async def test_max_delay_cap(self):
        """Should cap delay at max_delay."""
        delays = []
        
        original_sleep = asyncio.sleep
        
        async def mock_sleep(duration):
            delays.append(duration)
            await original_sleep(0.001)
        
        @async_retry_with_backoff(
            max_retries=10,
            initial_delay=1.0,
            exponential_base=10.0,  # Would grow very fast
            max_delay=5.0,  # But capped here
        )
        async def fails():
            raise ValueError("Error")
        
        with patch("pearlalgo.utils.retry.asyncio.sleep", mock_sleep):
            try:
                await fails()
            except ValueError:
                pass
        
        # All delays should be <= max_delay
        for delay in delays:
            assert delay <= 5.0

    @pytest.mark.asyncio
    async def test_preserves_function_metadata(self):
        """Should preserve original function name and docstring."""
        @async_retry_with_backoff(max_retries=2)
        async def my_documented_function():
            """This is my docstring."""
            return "result"
        
        assert my_documented_function.__name__ == "my_documented_function"
        assert "This is my docstring" in (my_documented_function.__doc__ or "")
