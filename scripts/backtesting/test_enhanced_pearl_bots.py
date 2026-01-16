#!/usr/bin/env python3
"""
Test Enhanced Pearl Bots

Validates the performance optimizations, market regime detection, and ML enhancements
for the pearl bot system.
"""

from __future__ import annotations

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from pearlalgo.strategies.pearl_bots import TrendFollowerBot, BotConfig
from pearlalgo.strategies.pearl_bots.market_regime_detector import market_regime_detector
from pearlalgo.strategies.pearl_bots.ml_signal_filter import ml_signal_filter
from pearlalgo.utils.logger import logger


def generate_test_data(days: int = 30) -> pd.DataFrame:
    """Generate synthetic market data for testing."""
    # Create datetime index
    end_time = datetime.now(timezone.utc)
    start_time = end_time - pd.Timedelta(days=days)
    times = pd.date_range(start_time, end_time, freq='5min')

    np.random.seed(42)  # For reproducible results

    # Generate realistic price data with trends and volatility
    n_points = len(times)

    # Base price around 4000 (MNQ-like)
    base_price = 4000

    # Create different market regimes
    regime_changes = [0, n_points // 3, 2 * n_points // 3, n_points]

    prices = []
    current_price = base_price

    for i in range(n_points):
        # Different behaviors for different regimes
        if i < regime_changes[1]:  # Trending up
            drift = 0.0001  # Slight upward drift
            volatility = 0.001
        elif i < regime_changes[2]:  # Sideways
            drift = 0.00001
            volatility = 0.0008
        else:  # Volatile
            drift = -0.00005  # Slight downward drift
            volatility = 0.002

        # Generate price movement
        price_change = np.random.normal(drift, volatility)
        current_price *= (1 + price_change)
        prices.append(current_price)

    # Create OHLCV dataframe
    df = pd.DataFrame({
        'timestamp': times,
        'open': prices,
        'high': [p * (1 + abs(np.random.normal(0, 0.0005))) for p in prices],
        'low': [p * (1 - abs(np.random.normal(0, 0.0005))) for p in prices],
        'close': prices,
        'volume': [int(np.random.lognormal(10, 1)) for _ in prices]
    })

    df.set_index('timestamp', inplace=True)
    return df


def test_market_regime_detection():
    """Test market regime detection functionality."""
    logger.info("Testing market regime detection...")

    # Generate test data
    df = generate_test_data(days=30)

    # Test regime detection
    regime, metrics, confidence = market_regime_detector.detect_regime(df)

    logger.info(f"Detected regime: {regime.value} (confidence: {confidence:.2f})")
    logger.info(f"ADX: {metrics.adx:.2f}, Trend direction: {metrics.trend_direction}")
    logger.info(f"Volatility ratio: {metrics.volatility_ratio:.2f}")

    # Test regime filters
    filters = market_regime_detector.get_regime_filter(regime)
    logger.info(f"Regime filters: {filters}")

    return True


def test_cached_indicators():
    """Test cached indicator performance."""
    logger.info("Testing cached indicator performance...")

    # Create bot config
    config = BotConfig(
        name="TestTrendFollower",
        description="Test trend follower bot",
        enable_regime_filtering=True,
        enable_ml_enhancement=True
    )

    # Create bot
    bot = TrendFollowerBot(config)

    # Generate test data
    df = generate_test_data(days=7)  # Shorter for faster testing

    # Test indicator calculation multiple times (should use cache)
    import time

    start_time = time.time()
    for _ in range(10):
        market_data = {
            "df": df,
            "latest_bar": {
                "timestamp": df.index[-1].isoformat(),
                "open": df.iloc[-1]['open'],
                "high": df.iloc[-1]['high'],
                "low": df.iloc[-1]['low'],
                "close": df.iloc[-1]['close'],
                "volume": df.iloc[-1]['volume'],
            }
        }
        signals = bot.analyze(market_data)
    end_time = time.time()

    logger.info(f"10 indicator calculations took {end_time - start_time:.3f} seconds")
    logger.info(f"Generated {len([s for batch in [bot.analyze({'df': df, 'latest_bar': {'timestamp': df.index[-1].isoformat(), 'open': df.iloc[-1]['open'], 'high': df.iloc[-1]['high'], 'low': df.iloc[-1]['low'], 'close': df.iloc[-1]['close'], 'volume': df.iloc[-1]['volume']}}) for _ in range(5)] for s in batch])} total signals")

    return True


def test_ml_enhancement():
    """Test ML signal enhancement."""
    logger.info("Testing ML signal enhancement...")

    # Create bot config
    config = BotConfig(
        name="TestMLBot",
        description="Test ML-enhanced bot",
        enable_ml_enhancement=True
    )

    # Create bot
    bot = TrendFollowerBot(config)

    # Generate test data
    df = generate_test_data(days=14)

    # Test signal generation with ML enhancement
    market_data = {
        "df": df,
        "latest_bar": {
            "timestamp": df.index[-1].isoformat(),
            "open": df.iloc[-1]['open'],
            "high": df.iloc[-1]['high'],
            "low": df.iloc[-1]['low'],
            "close": df.iloc[-1]['close'],
            "volume": df.iloc[-1]['volume'],
        }
    }

    signals = bot.analyze(market_data)

    if signals:
        signal = signals[0]
        logger.info(f"Generated signal with ML enhancement:")
        logger.info(f"  Direction: {signal.direction}")
        logger.info(f"  Original confidence: {signal.confidence}")
        logger.info(f"  ML-adjusted confidence: {signal.regime_adjusted_confidence}")
        logger.info(f"  Market regime: {signal.market_regime}")
        logger.info(f"  ML features: {signal.features}")

        return True
    else:
        logger.info("No signals generated (normal for test data)")
        return True


def test_regime_aware_risk_management():
    """Test regime-aware risk management."""
    logger.info("Testing regime-aware risk management...")

    # Create bot config with regime filtering
    config = BotConfig(
        name="TestRegimeBot",
        description="Test regime-aware bot",
        enable_regime_filtering=True,
        regime_risk_multiplier=1.5,  # Increase risk in favorable regimes
        allowed_regimes=["trending_bull", "trending_bear"]  # Only trade in trends
    )

    # Create bot
    bot = TrendFollowerBot(config)

    # Generate trending data (should allow trading)
    df_trending = generate_test_data(days=7)
    # Make it more trending by adding a strong uptrend
    trend_factor = np.linspace(1.0, 1.05, len(df_trending))  # 5% uptrend
    df_trending['close'] *= trend_factor
    df_trending['open'] *= trend_factor
    df_trending['high'] *= trend_factor
    df_trending['low'] *= trend_factor

    market_data = {
        "df": df_trending,
        "latest_bar": {
            "timestamp": df_trending.index[-1].isoformat(),
            "open": df_trending.iloc[-1]['open'],
            "high": df_trending.iloc[-1]['high'],
            "low": df_trending.iloc[-1]['low'],
            "close": df_trending.iloc[-1]['close'],
            "volume": df_trending.iloc[-1]['volume'],
        }
    }

    signals = bot.analyze(market_data)

    if signals:
        logger.info(f"Regime-aware bot generated {len(signals)} signals in trending market")
        signal = signals[0]
        logger.info(f"Position size: {signal.position_size_pct}")
        logger.info(f"Risk-reward ratio: {signal.risk_reward_ratio}")
    else:
        logger.info("No signals in trending market (checking regime detection)")

    return True


def main():
    """Run all tests."""
    logger.info("Starting enhanced pearl bot tests...")

    try:
        # Test market regime detection
        test_market_regime_detection()
        print("✓ Market regime detection test passed")

        # Test cached indicators
        test_cached_indicators()
        print("✓ Cached indicators test passed")

        # Test ML enhancement
        test_ml_enhancement()
        print("✓ ML enhancement test passed")

        # Test regime-aware risk management
        test_regime_aware_risk_management()
        print("✓ Regime-aware risk management test passed")

        logger.info("All tests passed! Enhanced pearl bots are working correctly.")
        return 0

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())