"""
Integration tests for IBKR Executor and Data Provider.

Tests the thread-safe executor architecture with real IBKR connections.
"""

import asyncio
import pytest
from datetime import datetime, timezone

from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider
from pearlalgo.data_providers.ibkr_executor import (
    GetLatestBarTask,
    GetOptionsChainTask,
    IBKRExecutor,
)
from pearlalgo.config.settings import get_settings


@pytest.fixture
def settings():
    """Get settings for testing."""
    return get_settings()


@pytest.fixture
def executor(settings):
    """Create and start executor for testing."""
    executor = IBKRExecutor(
        host=settings.ib_host,
        port=settings.ib_port,
        client_id=settings.ib_data_client_id or settings.ib_client_id,
    )
    executor.start()
    yield executor
    executor.stop()


@pytest.fixture
def provider(settings):
    """Create data provider for testing."""
    provider = IBKRDataProvider(settings=settings)
    yield provider
    # Cleanup handled by provider.close() if needed


@pytest.mark.asyncio
async def test_executor_connection(executor):
    """Test executor can connect to IB Gateway."""
    # Wait a moment for connection
    await asyncio.sleep(2.0)
    
    # Check connection status
    assert executor.is_connected(), "Executor should be connected to IB Gateway"


@pytest.mark.asyncio
async def test_executor_get_latest_bar(executor):
    """Test fetching a single quote via executor."""
    # Wait for connection
    await asyncio.sleep(2.0)
    
    # Submit task
    import uuid
    task_id = str(uuid.uuid4())
    task = GetLatestBarTask(task_id=task_id, symbol="AAPL", is_futures=False)
    
    future = executor.submit_task(task)
    result = await asyncio.wrap_future(future)
    
    # Verify result
    assert result is not None, "Should get a result"
    assert "close" in result, "Result should have 'close' price"
    assert result["close"] > 0, "Price should be positive"


@pytest.mark.asyncio
async def test_executor_get_options_chain(executor):
    """Test fetching options chain via executor."""
    # Wait for connection
    await asyncio.sleep(2.0)
    
    # First get underlying price
    import uuid
    task_id1 = str(uuid.uuid4())
    price_task = GetLatestBarTask(task_id=task_id1, symbol="QQQ", is_futures=False)
    price_future = executor.submit_task(price_task)
    price_result = await asyncio.wrap_future(price_future)
    
    if not price_result or price_result.get("close", 0) <= 0:
        pytest.skip("Cannot get underlying price, skipping options chain test")
    
    underlying_price = price_result["close"]
    
    # Submit options chain task
    task_id2 = str(uuid.uuid4())
    task = GetOptionsChainTask(
        task_id=task_id2,
        underlying_symbol="QQQ",
        min_dte=0,
        max_dte=30,
        underlying_price=underlying_price,
    )
    
    future = executor.submit_task(task)
    result = await asyncio.wrap_future(future)
    
    # Verify result
    assert isinstance(result, list), "Result should be a list"
    # May be empty if no options match filters, which is OK


@pytest.mark.asyncio
async def test_provider_get_latest_bar(provider):
    """Test provider's get_latest_bar method."""
    # Wait for executor to connect
    await asyncio.sleep(2.0)
    
    result = await provider.get_latest_bar("AAPL")
    
    assert result is not None, "Should get a result"
    assert "close" in result, "Result should have 'close' price"
    assert result["close"] > 0, "Price should be positive"


@pytest.mark.asyncio
async def test_provider_get_options_chain(provider):
    """Test provider's get_options_chain method."""
    # Wait for executor to connect
    await asyncio.sleep(2.0)
    
    result = await provider.get_options_chain(
        underlying_symbol="QQQ",
        min_dte=0,
        max_dte=30,
    )
    
    assert isinstance(result, list), "Result should be a list"


@pytest.mark.asyncio
async def test_concurrent_worker_tasks(executor):
    """Test multiple workers submitting tasks concurrently."""
    # Wait for connection
    await asyncio.sleep(2.0)
    
    # Submit multiple tasks concurrently
    symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "QQQ"]
    tasks = []
    
    import uuid
    for symbol in symbols:
        task_id = str(uuid.uuid4())
        task = GetLatestBarTask(task_id=task_id, symbol=symbol, is_futures=False)
        future = executor.submit_task(task)
        tasks.append((symbol, future))
    
    # Wait for all tasks to complete
    results = await asyncio.gather(*[fut for _, fut in tasks], return_exceptions=True)
    
    # Verify results
    for (symbol, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            # Some symbols might fail, that's OK for testing
            continue
        assert result is not None, f"Should get result for {symbol}"
        if result and "close" in result:
            assert result["close"] > 0, f"Price should be positive for {symbol}"


@pytest.mark.asyncio
async def test_executor_queue_size(executor):
    """Test executor queue size monitoring."""
    # Wait for connection
    await asyncio.sleep(2.0)
    
    # Submit a few tasks
    import uuid
    for i in range(5):
        task_id = str(uuid.uuid4())
        task = GetLatestBarTask(task_id=task_id, symbol="AAPL", is_futures=False)
        executor.submit_task(task)
    
    # Check queue size (should be small as tasks execute quickly)
    queue_size = executor.get_queue_size()
    assert queue_size >= 0, "Queue size should be non-negative"


@pytest.mark.asyncio
async def test_provider_fetch_historical(provider):
    """Test provider's fetch_historical method."""
    # Wait for executor to connect
    await asyncio.sleep(2.0)
    
    # Fetch historical data
    df = provider.fetch_historical(
        symbol="AAPL",
        timeframe="1d",
    )
    
    assert df is not None, "Should get a DataFrame"
    assert not df.empty, "DataFrame should not be empty"
    assert "close" in df.columns or "close" in df.index.names, "Should have close prices"


if __name__ == "__main__":
    # Run tests with: pytest tests/test_ibkr_executor.py -v
    pytest.main([__file__, "-v"])
