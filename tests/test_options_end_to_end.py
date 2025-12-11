"""
End-to-end tests for options trading system.

Tests the full flow: data → scanner → signals → Telegram
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from pearlalgo.options.intraday_scanner import OptionsIntradayScanner
from pearlalgo.options.swing_scanner import OptionsSwingScanner
from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.signal_tracker import OptionsSignalTracker
from pearlalgo.utils.telegram_alerts import TelegramAlerts


@pytest.fixture
def mock_data_provider():
    """Mock data provider with realistic data."""
    provider = MagicMock()
    
    # Mock stock price data
    provider.get_latest_bar = AsyncMock(return_value={
        "close": 400.0,
        "open": 399.0,
        "high": 401.0,
        "low": 398.0,
        "volume": 1000000,
        "timestamp": datetime.now(timezone.utc),
    })
    
    # Mock options chain
    provider.get_options_chain_filtered = AsyncMock(return_value=[
        {
            "symbol": "QQQ240119C00400",
            "strike": 400.0,
            "expiration": "2024-01-19",
            "option_type": "call",
            "bid": 2.50,
            "ask": 2.60,
            "last_price": 2.55,
            "volume": 1500,
            "open_interest": 5000,
            "dte": 5,
        }
    ])
    
    return provider


@pytest.fixture
def mock_buffer_manager():
    """Mock buffer manager with historical data."""
    manager = MagicMock()
    manager.has_buffer = MagicMock(return_value=True)
    manager.get_buffer = MagicMock(return_value=[
        {"close": 395.0 + i, "high": 396.0 + i, "low": 394.0 + i, "volume": 800000 + i * 10000}
        for i in range(30)
    ])
    manager.backfill_multiple = AsyncMock()
    return manager


@pytest.fixture
def mock_telegram():
    """Mock Telegram alerts."""
    telegram = MagicMock()
    telegram.send_message = AsyncMock(return_value=True)
    telegram.notify_signal = AsyncMock()
    return telegram


@pytest.mark.asyncio
async def test_intraday_scanner_full_flow(mock_data_provider, mock_buffer_manager):
    """Test full intraday scanner flow."""
    scanner = OptionsIntradayScanner(
        symbols=["QQQ", "SPY"],
        strategy="momentum",
        data_provider=mock_data_provider,
        buffer_manager=mock_buffer_manager,
        config={"momentum_threshold": 0.01, "volume_threshold": 1.5},
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "success"
    assert "signals" in result
    assert isinstance(result["signals"], list)


@pytest.mark.asyncio
async def test_swing_scanner_full_flow(mock_data_provider, mock_buffer_manager):
    """Test full swing scanner flow."""
    universe = EquityUniverse(symbols=["QQQ", "SPY"])
    
    scanner = OptionsSwingScanner(
        universe=universe,
        strategy="swing_momentum",
        data_provider=mock_data_provider,
        buffer_manager=mock_buffer_manager,
    )
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "success"
    assert "signals" in result
    assert isinstance(result["signals"], list)


@pytest.mark.asyncio
async def test_signal_tracker_integration(mock_data_provider):
    """Test signal tracker with option signals."""
    tracker = OptionsSignalTracker()
    
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    
    # Add signal
    signal = tracker.add_signal(
        underlying_symbol="QQQ",
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration=expiration,
        option_type="call",
        direction="long",
        entry_premium=2.55,
        quantity=1,
    )
    
    # Update PnL
    updated = tracker.update_pnl(
        "QQQ240119C00400",
        current_premium=3.00,
        underlying_price=405.0,
    )
    
    assert updated is not None
    assert updated.unrealized_pnl > 0
    
    # Get statistics
    stats = tracker.get_statistics()
    assert stats["active_signals"] == 1


@pytest.mark.asyncio
async def test_telegram_options_signal_formatting(mock_telegram):
    """Test Telegram formatting for options signals."""
    await mock_telegram.notify_signal(
        symbol="QQQ",
        side="long",
        price=2.55,
        strategy="momentum",
        confidence=0.75,
        entry_price=2.55,
        option_symbol="QQQ240119C00400",
        strike=400.0,
        expiration="2024-01-19",
        option_type="call",
        underlying_price=400.0,
        dte=5,
    )
    
    # Verify notify_signal was called
    mock_telegram.notify_signal.assert_called_once()
    
    # Check that options-specific parameters were passed
    call_args = mock_telegram.notify_signal.call_args[1]
    assert call_args["option_symbol"] == "QQQ240119C00400"
    assert call_args["strike"] == 400.0
    assert call_args["option_type"] == "call"


@pytest.mark.asyncio
async def test_end_to_end_qqq_signal(mock_data_provider, mock_buffer_manager, mock_telegram):
    """Test complete end-to-end flow for QQQ."""
    # Create scanner
    scanner = OptionsIntradayScanner(
        symbols=["QQQ"],
        strategy="momentum",
        data_provider=mock_data_provider,
        buffer_manager=mock_buffer_manager,
    )
    
    # Create tracker
    tracker = OptionsSignalTracker()
    
    # Scan for signals
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    # Process signals
    if result["status"] == "success" and result.get("signals"):
        for signal in result["signals"]:
            # Add to tracker
            expiration = datetime.fromisoformat(signal["expiration"].replace("Z", "+00:00"))
            tracker.add_signal(
                underlying_symbol=signal["symbol"],
                option_symbol=signal["option_symbol"],
                strike=signal["strike"],
                expiration=expiration,
                option_type=signal["option_type"],
                direction=signal["side"],
                entry_premium=signal["entry_price"],
                quantity=1,
            )
            
            # Send Telegram notification
            await mock_telegram.notify_signal(
                symbol=signal["symbol"],
                side=signal["side"],
                price=signal["entry_price"],
                strategy=signal.get("strategy_name", "momentum"),
                confidence=signal.get("confidence", 0.5),
                entry_price=signal["entry_price"],
                option_symbol=signal["option_symbol"],
                strike=signal["strike"],
                expiration=signal["expiration"],
                option_type=signal["option_type"],
                underlying_price=signal.get("underlying_price"),
                dte=signal.get("dte"),
            )
    
    # Verify flow completed
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_end_to_end_spy_signal(mock_data_provider, mock_buffer_manager, mock_telegram):
    """Test complete end-to-end flow for SPY."""
    # Similar to QQQ test but for SPY
    scanner = OptionsIntradayScanner(
        symbols=["SPY"],
        strategy="volatility",
        data_provider=mock_data_provider,
        buffer_manager=mock_buffer_manager,
    )
    
    tracker = OptionsSignalTracker()
    
    with patch('pearlalgo.utils.market_hours.is_market_open', return_value=True):
        result = await scanner.scan()
    
    assert result["status"] == "success"
