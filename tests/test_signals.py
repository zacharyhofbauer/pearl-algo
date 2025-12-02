"""
Comprehensive tests for signal generation strategies.
"""
from __future__ import annotations

import pandas as pd
import pytest

from pearlalgo.futures.signals import (
    generate_signal,
    ma_cross_signal,
    sr_strategy,
    breakout_strategy,
    mean_reversion_strategy,
    calculate_signal_confidence,
    SignalQuality,
    calculate_rsi,
    calculate_bollinger_bands,
)


def create_sample_data(length: int = 100, trend: str = "up") -> pd.DataFrame:
    """Create sample OHLCV data for testing."""
    import numpy as np
    
    base_price = 100.0
    prices = []
    volumes = []
    
    for i in range(length):
        if trend == "up":
            price = base_price + i * 0.1 + np.random.normal(0, 0.5)
        elif trend == "down":
            price = base_price - i * 0.1 + np.random.normal(0, 0.5)
        else:  # sideways
            price = base_price + np.random.normal(0, 1.0)
        
        prices.append(price)
        volumes.append(1000 + np.random.randint(-100, 100))
    
    df = pd.DataFrame({
        "Open": prices,
        "High": [p + abs(np.random.normal(0, 0.3)) for p in prices],
        "Low": [p - abs(np.random.normal(0, 0.3)) for p in prices],
        "Close": prices,
        "Volume": volumes,
    })
    
    return df


def test_ma_cross_signal():
    """Test MA cross signal generation."""
    # Upward trend
    df_up = create_sample_data(100, trend="up")
    signal = ma_cross_signal(df_up, fast=20, slow=50)
    assert signal in ["long", "short", "flat"]
    
    # Downward trend
    df_down = create_sample_data(100, trend="down")
    signal = ma_cross_signal(df_down, fast=20, slow=50)
    assert signal in ["long", "short", "flat"]
    
    # Insufficient data
    df_short = create_sample_data(10)
    signal = ma_cross_signal(df_short, fast=20, slow=50)
    assert signal == "flat"


def test_sr_strategy():
    """Test Support/Resistance strategy."""
    df = create_sample_data(100)
    result = sr_strategy("ES", df, fast=20, slow=50, tolerance=0.002)
    
    assert "symbol" in result
    assert "strategy_name" in result
    assert "side" in result
    assert result["strategy_name"] == "sr"
    assert result["side"] in ["long", "short", "flat"]
    assert "confidence" in result
    assert 0.0 <= result["confidence"] <= 1.0


def test_breakout_strategy():
    """Test breakout strategy."""
    df = create_sample_data(100)
    result = breakout_strategy("ES", df, lookback=20, volume_multiplier=1.5)
    
    assert "symbol" in result
    assert "strategy_name" in result
    assert result["strategy_name"] == "breakout"
    assert result["side"] in ["long", "short", "flat"]
    assert "confidence" in result
    assert 0.0 <= result["confidence"] <= 1.0
    
    # Test with insufficient data
    df_short = create_sample_data(10)
    result_short = breakout_strategy("ES", df_short)
    assert result_short["side"] == "flat"


def test_mean_reversion_strategy():
    """Test mean-reversion strategy."""
    df = create_sample_data(100)
    result = mean_reversion_strategy("ES", df, bb_period=20, rsi_period=14)
    
    assert "symbol" in result
    assert "strategy_name" in result
    assert result["strategy_name"] == "mean_reversion"
    assert result["side"] in ["long", "short", "flat"]
    assert "confidence" in result
    assert 0.0 <= result["confidence"] <= 1.0
    assert "rsi" in result
    assert "upper_bb" in result
    assert "lower_bb" in result
    
    # Test with insufficient data
    df_short = create_sample_data(10)
    result_short = mean_reversion_strategy("ES", df_short)
    assert result_short["side"] == "flat"


def test_generate_signal():
    """Test signal generation wrapper."""
    df = create_sample_data(100)
    
    # Test SR strategy
    signal = generate_signal("ES", df, strategy_name="sr")
    assert "side" in signal
    assert "strategy_name" in signal
    assert signal["strategy_name"] == "sr"
    
    # Test MA cross strategy
    signal = generate_signal("ES", df, strategy_name="ma_cross")
    assert "side" in signal
    assert signal["strategy_name"] == "ma_cross"
    
    # Test breakout strategy
    signal = generate_signal("ES", df, strategy_name="breakout")
    assert "side" in signal
    assert signal["strategy_name"] == "breakout"
    
    # Test mean-reversion strategy
    signal = generate_signal("ES", df, strategy_name="mean_reversion")
    assert "side" in signal
    assert signal["strategy_name"] == "mean_reversion"
    
    # Test invalid strategy
    with pytest.raises(ValueError):
        generate_signal("ES", df, strategy_name="invalid_strategy")


def test_calculate_signal_confidence():
    """Test signal confidence calculation."""
    df = create_sample_data(100)
    
    # Test long signal
    indicators = {
        "fast_ma": 101.0,
        "slow_ma": 100.0,
        "vwap": 100.5,
        "support1": 99.0,
    }
    confidence = calculate_signal_confidence(df, "long", indicators)
    assert 0.0 <= confidence <= 1.0
    
    # Test short signal
    indicators_short = {
        "fast_ma": 99.0,
        "slow_ma": 100.0,
        "vwap": 100.5,
        "resistance1": 101.0,
    }
    confidence = calculate_signal_confidence(df, "short", indicators_short)
    assert 0.0 <= confidence <= 1.0
    
    # Test flat signal
    confidence = calculate_signal_confidence(df, "flat", {})
    assert confidence == 0.0


def test_signal_quality():
    """Test SignalQuality class."""
    quality = SignalQuality()
    
    assert quality.accuracy() == 0.0
    assert quality.precision() == 0.0
    assert quality.recall() == 0.0
    assert quality.signal_to_noise_ratio() == 0.0
    assert quality.win_rate() == 0.0
    
    # Add some metrics
    quality.true_positives = 10
    quality.false_positives = 5
    quality.true_negatives = 20
    quality.false_negatives = 5
    quality.total_signals = 15
    quality.profitable_signals = 10
    
    assert quality.accuracy() > 0.0
    assert quality.precision() > 0.0
    assert quality.recall() > 0.0
    assert quality.win_rate() > 0.0


def test_calculate_rsi():
    """Test RSI calculation."""
    df = create_sample_data(50)
    prices = df["Close"]
    
    rsi = calculate_rsi(prices, period=14)
    
    # RSI should be between 0 and 100
    if rsi is not None:
        assert 0.0 <= rsi <= 100.0
    
    # Test with insufficient data
    rsi_short = calculate_rsi(prices[:10], period=14)
    assert rsi_short is None


def test_calculate_bollinger_bands():
    """Test Bollinger Bands calculation."""
    df = create_sample_data(50)
    prices = df["Close"]
    
    upper, middle, lower = calculate_bollinger_bands(prices, period=20, num_std=2.0)
    
    if upper is not None and middle is not None and lower is not None:
        assert upper >= middle >= lower
        assert middle > 0
        assert upper > 0
        assert lower > 0
    
    # Test with insufficient data
    upper_short, middle_short, lower_short = calculate_bollinger_bands(prices[:10], period=20)
    assert upper_short is None
    assert middle_short is None
    assert lower_short is None


def test_strategy_parameters():
    """Test strategy parameter passing."""
    df = create_sample_data(100)
    
    # Test SR with custom parameters
    result = generate_signal("ES", df, strategy_name="sr", fast=10, slow=30, tolerance=0.001)
    assert result["params"]["fast"] == 10
    assert result["params"]["slow"] == 30
    assert result["params"]["tolerance"] == 0.001
    
    # Test breakout with custom parameters
    result = generate_signal("ES", df, strategy_name="breakout", lookback=30, volume_multiplier=2.0)
    assert result["params"]["lookback"] == 30
    assert result["params"]["volume_multiplier"] == 2.0
    
    # Test mean-reversion with custom parameters
    result = generate_signal("ES", df, strategy_name="mean_reversion", bb_period=30, rsi_period=21)
    assert result["params"]["bb_period"] == 30
    assert result["params"]["rsi_period"] == 21


def test_signal_consistency():
    """Test that signals are consistent across multiple calls with same data."""
    df = create_sample_data(100)
    
    signal1 = generate_signal("ES", df, strategy_name="sr")
    signal2 = generate_signal("ES", df, strategy_name="sr")
    
    # Signals should be the same for identical data
    assert signal1["side"] == signal2["side"]
    assert signal1["strategy_name"] == signal2["strategy_name"]




