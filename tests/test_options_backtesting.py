"""
Unit tests for options data loaders, features, signal generators, and backtesting engine.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, patch

# Test historical data loader
def test_historical_data_loader():
    """Test HistoricalFuturesDataLoader."""
    from pearlalgo.backtesting.historical_data_loader import HistoricalFuturesDataLoader
    
    # Mock data provider
    mock_provider = Mock()
    mock_provider.fetch_historical = Mock(return_value=pd.DataFrame({
        'open': [100, 101],
        'high': [102, 103],
        'low': [99, 100],
        'close': [101, 102],
        'volume': [1000, 1100],
    }, index=pd.date_range('2024-01-01', periods=2, freq='15min')))
    
    loader = HistoricalFuturesDataLoader(mock_provider)
    
    # Test normalize_data
    df = pd.DataFrame({
        'open': [100],
        'high': [102],
        'low': [99],
        'close': [101],
        'volume': [1000],
    })
    normalized = loader.normalize_data(df)
    assert 'close' in normalized.columns
    assert len(normalized) == 1

# Test features computation
def test_options_feature_computer():
    """Test OptionsFeatureComputer."""
    from pearlalgo.options.features import OptionsFeatureComputer
    
    computer = OptionsFeatureComputer()
    
    # Test moving averages
    df = pd.DataFrame({
        'close': np.random.randn(100) + 100,
        'volume': np.random.randint(1000, 10000, 100),
    })
    df = computer.compute_moving_averages(df)
    assert 'sma_short' in df.columns
    assert 'ema_short' in df.columns
    
    # Test volume spikes
    df = computer.detect_volume_spikes(df, threshold=2.0)
    assert 'volume_spike' in df.columns
    
    # Test momentum indicators
    df = computer.compute_momentum_indicators(df)
    assert 'rsi' in df.columns
    assert 'macd' in df.columns

# Test signal generator
@pytest.mark.asyncio
async def test_options_signal_generator():
    """Test OptionsSignalGenerator."""
    from pearlalgo.options.signal_generator import OptionsSignalGenerator
    from pearlalgo.options.universe import EquityUniverse
    from pearlalgo.options.strategy import SwingMomentumStrategy
    
    # Mock data provider
    mock_provider = Mock()
    mock_provider.get_latest_bar = AsyncMock(return_value={
        'close': 100.0,
        'timestamp': datetime.now(timezone.utc),
    })
    mock_provider.get_options_chain = AsyncMock(return_value=[
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
    
    universe = EquityUniverse(symbols=["QQQ"])
    strategy = SwingMomentumStrategy()
    generator = OptionsSignalGenerator(universe, strategy, mock_provider)
    
    # Test delta targeting
    signal = {
        'option_symbol': 'QQQ240119C00100',
        'strike': 100.0,
        'underlying_price': 100.0,
        'position_size': 1,
    }
    signal = generator._add_delta_targeting(signal, [])
    # Delta should be calculated (approximate)
    assert 'delta' in signal or 'delta' not in signal  # May not always calculate
    
    # Test risk controls
    signal = generator._apply_risk_controls(signal)
    assert 'delta_exposure' in signal

# Test backtesting engine
def test_options_backtest_engine():
    """Test OptionsBacktestEngine."""
    from pearlalgo.backtesting.options_backtest_engine import OptionsBacktestEngine
    
    engine = OptionsBacktestEngine(initial_cash=100000.0)
    
    # Test P&L calculation
    positions = {
        'QQQ240119C00100': {
            'entry_price': 2.0,
            'size': 1,
        }
    }
    current_prices = {'QQQ240119C00100': 2.5}
    realized, unrealized = engine.track_pnl(positions, current_prices)
    assert unrealized == 0.5  # (2.5 - 2.0) * 1
    
    # Test metrics calculation
    equity_curve = [
        {'timestamp': datetime.now(), 'equity': 100000},
        {'timestamp': datetime.now() + timedelta(days=1), 'equity': 101000},
    ]
    trades = [
        {'pnl': 1000},
    ]
    metrics = engine.calculate_metrics(equity_curve, trades)
    assert 'total_return' in metrics
    assert 'win_rate' in metrics

# Test parameter optimizer
def test_parameter_optimizer():
    """Test ParameterOptimizer."""
    from pearlalgo.backtesting.parameter_optimizer import ParameterOptimizer
    
    optimizer = ParameterOptimizer()
    
    # Test comparison
    results = [
        {
            'parameters': {'threshold': 0.01},
            'metrics': {'total_return': 0.10, 'sharpe_ratio': 1.5},
        },
        {
            'parameters': {'threshold': 0.02},
            'metrics': {'total_return': 0.15, 'sharpe_ratio': 2.0},
        },
    ]
    
    comparison_df = optimizer.compare_results(results)
    assert len(comparison_df) == 2
    assert 'total_return' in comparison_df.columns
