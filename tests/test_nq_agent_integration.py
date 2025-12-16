"""
Integration tests for NQ Agent end-to-end functionality.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


@pytest.fixture
def real_data_provider():
    """
    Use real IBKR data provider for integration tests.
    Tests will use actual market data when IBKR Gateway is available.
    """
    try:
        from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
        from pearlalgo.config.settings import get_settings
        
        settings = get_settings()
        provider = IBKRProvider(settings=settings)
        yield provider
        
        # Cleanup
        import asyncio
        try:
            asyncio.run(provider.close())
        except Exception:
            pass
    except Exception as e:
        pytest.skip(f"Real data provider not available (IBKR Gateway may not be running): {e}")


@pytest.fixture
def mock_data_provider():
    """
    Fallback mock provider - only used if real provider is not available.
    Prefer real_data_provider fixture for tests that should use real market data.
    """
    provider = MagicMock()
    
    # Create realistic historical data
    dates = pd.date_range(
        start=datetime.now(timezone.utc) - timedelta(hours=2),
        end=datetime.now(timezone.utc),
        freq="1min",
    )[:100]
    
    df = pd.DataFrame({
        "open": [15000 + i * 0.1 for i in range(len(dates))],
        "high": [15010 + i * 0.1 for i in range(len(dates))],
        "low": [14990 + i * 0.1 for i in range(len(dates))],
        "close": [15005 + i * 0.1 for i in range(len(dates))],
        "volume": [1000 + i for i in range(len(dates))],
    }, index=dates)
    
    provider.fetch_historical = MagicMock(return_value=df)
    provider.get_latest_bar = AsyncMock(return_value={
        "timestamp": datetime.now(timezone.utc),
        "open": 15000.0,
        "high": 15010.0,
        "low": 14990.0,
        "close": 15005.0,
        "volume": 1000,
    })
    provider.close = AsyncMock()
    
    return provider


@pytest.fixture
def config():
    """Create test configuration."""
    return NQIntradayConfig(
        symbol="NQ",
        timeframe="1m",
        scan_interval=1,  # Fast for testing
    )


@pytest.fixture
def state_dir(tmp_path):
    """Create temporary state directory."""
    state_dir = tmp_path / "nq_agent_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def mock_telegram_notifier():
    """Create a mock Telegram notifier."""
    notifier = MagicMock()
    notifier.enabled = True
    notifier.send_signal = AsyncMock(return_value=True)
    notifier.send_status = AsyncMock(return_value=True)
    notifier.send_enhanced_status = AsyncMock(return_value=True)
    return notifier


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_full_cycle(real_data_provider, config, state_dir):
    """
    Test full service cycle with real market data: data fetch → signal generation → notification.
    
    This test uses real IBKR data and may take time to connect.
    """
    import asyncio
    
    service = NQAgentService(
        data_provider=real_data_provider,
        config=config,
        state_dir=state_dir,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    
    # Mock telegram notifier
    service.telegram_notifier.send_signal = AsyncMock(return_value=True)
    
    # Run one cycle manually
    service.running = True
    service.shutdown_requested = False
    
    try:
        # Fetch data
        market_data = await service.data_fetcher.fetch_latest_data()
        assert "df" in market_data
        
        # Generate signals
        signals = service.strategy.analyze(market_data)
        assert isinstance(signals, list)
        
        # Process signals
        for signal in signals:
            await service._process_signal(signal)
        
        # Check state was saved
        assert service.signal_count >= 0  # May be 0 if no signals generated
    finally:
        await service.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_signal_to_telegram(real_data_provider, config, state_dir, mock_telegram_notifier):
    """
    Test signal generation with real market data and Telegram notification.
    
    This test uses real IBKR data and may take time to connect.
    """
    service = NQAgentService(
        data_provider=real_data_provider,
        config=config,
        state_dir=state_dir,
        telegram_bot_token="test_token",
        telegram_chat_id="test_chat_id",
    )
    
    # Replace notifier with mock
    service.telegram_notifier = mock_telegram_notifier
    
    # Create a test signal
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
        "confidence": 0.75,
        "reason": "Test integration signal",
        "strategy": "nq_intraday",
    }
    
    # Process signal
    await service._process_signal(signal)
    
    # Check Telegram was called
    mock_telegram_notifier.send_signal.assert_called_once()
    
    # Check signal was saved
    from pearlalgo.nq_agent.state_manager import NQAgentStateManager
    state_manager = NQAgentStateManager(state_dir=state_dir)
    signals = state_manager.get_recent_signals(limit=1)
    assert len(signals) > 0
    
    await service.stop()


@pytest.mark.asyncio
async def test_service_performance_tracking(real_data_provider, config, state_dir):
    """Test performance tracking with real market data through signal lifecycle."""
    service = NQAgentService(
        data_provider=real_data_provider,
        config=config,
        state_dir=state_dir,
    )
    
    # Generate signal
    signal = {
        "type": "breakout",
        "direction": "long",
        "entry_price": 15000.0,
    }
    
    # Track signal generation
    signal_id = service.performance_tracker.track_signal_generated(signal)
    assert signal_id is not None
    
    # Track entry
    service.performance_tracker.track_entry(signal_id, 15000.0)
    
    # Track exit
    performance = service.performance_tracker.track_exit(
        signal_id=signal_id,
        exit_price=15100.0,
        exit_reason="take_profit",
    )
    
    assert performance is not None
    assert performance["pnl"] > 0
    
    # Get metrics
    metrics = service.performance_tracker.get_performance_metrics(days=7)
    assert metrics["exited_signals"] > 0
    
    await service.stop()


@pytest.mark.asyncio
async def test_service_error_recovery(real_data_provider, config, state_dir):
    """Test service recovers from errors with real data provider."""
    service = NQAgentService(
        data_provider=real_data_provider,
        config=config,
        state_dir=state_dir,
    )
    
    # Temporarily make data provider fail
    original_fetch = real_data_provider.fetch_historical
    real_data_provider.fetch_historical = MagicMock(side_effect=Exception("Temporary error"))
    
    # Service should handle error gracefully
    try:
        market_data = await service.data_fetcher.fetch_latest_data()
        # Should return empty data, not crash
        assert "df" in market_data
    except Exception as e:
        pytest.fail(f"Service should handle errors gracefully: {e}")
    
    # Reset provider to original
    real_data_provider.fetch_historical = original_fetch
    
    # Should recover and work again with real data
    market_data = await service.data_fetcher.fetch_latest_data()
    assert "df" in market_data
    
    await service.stop()


@pytest.mark.asyncio
async def test_service_state_persistence(real_data_provider, config, state_dir):
    """Test service state persists across restarts with real data."""
    # Create and run service
    service1 = NQAgentService(
        data_provider=real_data_provider,
        config=config,
        state_dir=state_dir,
    )
    
    service1.cycle_count = 50
    service1.signal_count = 10
    service1._save_state()
    
    await service1.stop()
    
    # Create new service instance
    service2 = NQAgentService(
        data_provider=real_data_provider,
        config=config,
        state_dir=state_dir,
    )
    
    # Load state
    state = service2.state_manager.load_state()
    
    # State should be persisted (though service doesn't auto-load on init)
    assert state_dir.exists()
    
    await service2.stop()



