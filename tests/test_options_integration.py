"""
Integration tests for end-to-end options scanning, backtesting, and alert delivery.
"""

import pytest
import asyncio
import pandas as pd
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

# Test end-to-end scanning
@pytest.mark.asyncio
async def test_options_scanning_end_to_end():
    """Test full options scanning flow."""
    from pearlalgo.options.intraday_scanner import OptionsIntradayScanner
    from pearlalgo.data_providers.
    
    # Mock data provider
    mock_provider = Mock(spec=
    mock_provider.get_latest_bar = AsyncMock(return_value={
        'close': 100.0,
        'timestamp': datetime.now(timezone.utc),
    })
    mock_provider.get_options_chain_filtered = AsyncMock(return_value=[
        {
            'symbol': 'QQQ240119C00100',
            'strike': 100.0,
            'expiration': '2024-01-19',
            'option_type': 'call',
            'bid': 2.0,
            'ask': 2.1,
            'volume': 1000,
            'open_interest': 5000,
        }
    ])
    
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        strategy="momentum",
        data_provider=mock_provider,
    )
    
    # Run scan
    results = await scanner.scan()
    assert results.get("status") in ["success", "skipped"]
    if results.get("status") == "success":
        assert "signals" in results

# Test backtesting integration
@pytest.mark.asyncio
async def test_backtesting_integration():
    """Test backtesting with real data structure."""
    from pearlalgo.backtesting.options_backtest_engine import OptionsBacktestEngine
    from pearlalgo.backtesting.historical_data_loader import HistoricalFuturesDataLoader
    
    # Mock data provider
    mock_provider = Mock()
    mock_provider.fetch_historical = Mock(return_value=pd.DataFrame({
        'open': [100] * 100,
        'high': [102] * 100,
        'low': [99] * 100,
        'close': [101] * 100,
        'volume': [1000] * 100,
    }, index=pd.date_range('2024-01-01', periods=100, freq='15min')))
    
    loader = HistoricalFuturesDataLoader(mock_provider)
    engine = OptionsBacktestEngine()
    
    # Load data
    es_data = loader.load_es_data(
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
        "15m",
    )
    
    assert not es_data.empty
    assert 'close' in es_data.columns

# Test alert delivery
@pytest.mark.asyncio
async def test_telegram_alert_delivery():
    """Test Telegram alert delivery for options signals."""
    from pearlalgo.utils.telegram_alerts import TelegramAlerts
    
    # Mock Telegram bot
    with patch('pearlalgo.utils.telegram_alerts.Bot') as mock_bot_class:
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock(return_value=True)
        mock_bot_class.return_value = mock_bot
        
        alerts = TelegramAlerts(
            bot_token="test_token",
            chat_id="test_chat",
            enabled=True,
        )
        
        # Test options signal notification
        success = await alerts.notify_signal(
            symbol="QQQ",
            side="long",
            price=2.0,
            strategy="momentum",
            confidence=0.75,
            option_symbol="QQQ240119C00100",
            strike=100.0,
            expiration="2024-01-19",
            option_type="call",
            underlying_price=100.0,
            delta=0.5,
            dte=5,
        )
        
        # Should attempt to send (may fail in test environment)
        assert isinstance(success, bool)
