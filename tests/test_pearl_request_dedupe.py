"""
Tests for request deduplication.
"""

import asyncio
import pytest

from pearlalgo.pearl_ai.cache import RequestDeduplicator


@pytest.mark.asyncio
async def test_request_deduplicator_shares_result():
    """Concurrent requests with same key should share result."""
    deduper = RequestDeduplicator(window_ms=2000)
    calls = 0

    async def generator():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "result"

    async def run_call():
        return await deduper.dedupe("shared-key", generator)

    results = await asyncio.gather(run_call(), run_call())
    shared_flags = sorted([shared for shared, _ in results])

    assert calls == 1
    assert shared_flags == [False, True]
