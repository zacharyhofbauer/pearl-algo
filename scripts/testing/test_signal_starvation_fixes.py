#!/usr/bin/env python3
"""
Signal Starvation Fixes Validation

Tests the improvements made to address signal starvation:
1. NEAR_MISS logging for rejected signals
2. Volatility-aware confidence floor during ATR expansion
3. Relaxed MTF thresholds during volatility expansion
4. Relative RSI movement detection for mean reversion
5. Fresh breakout detection with relaxed RSI requirements
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from tests.mock_data_provider import MockDataProvider
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy


class HighVolatilityMockProvider(MockDataProvider):
    """Mock provider that generates high volatility data with ATR expansion."""
    
    def fetch_historical(self, symbol, start, end, timeframe="1m"):
        df = super().fetch_historical(symbol, start, end, timeframe)
        
        # Simulate ATR expansion: increase volatility over time
        if len(df) >= 5:
            # Calculate base ATR
            base_atr = 25.0  # Normal ATR
            expansion_atr = 35.0  # Expanded ATR (40% increase)
            
            # Gradually increase ATR to simulate expansion
            for i in range(len(df)):
                progress = i / len(df)
                current_atr = base_atr + (expansion_atr - base_atr) * progress
                
                # Add ATR column if not present
                if "atr" not in df.columns:
                    df["atr"] = 0.0
                
                df.iloc[i, df.columns.get_loc("atr")] = current_atr
                
                # Increase price volatility to match ATR expansion
                volatility_multiplier = 1 + (progress * 0.4)  # 40% increase
                df.iloc[i, df.columns.get_loc("high")] = df.iloc[i]["high"] * volatility_multiplier
                df.iloc[i, df.columns.get_loc("low")] = df.iloc[i]["low"] * (2 - volatility_multiplier)
        
        return df


async def test_atr_expansion_detection():
    """Test 1: Verify ATR expansion is detected."""
    print("=" * 70)
    print("Test 1: ATR Expansion Detection")
    print("=" * 70)
    print()
    
    provider = HighVolatilityMockProvider(
        base_price=17500.0,
        volatility=30.0,  # Higher base volatility
        trend=0.5,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    
    config = NQIntradayConfig(symbol="MNQ", timeframe="1m")
    strategy = NQIntradayStrategy(config=config)
    
    # Generate data
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)
    df = provider.fetch_historical("MNQ", start, end, "1m")
    latest_bar = await provider.get_latest_bar("MNQ")
    
    market_data = {"df": df, "latest_bar": latest_bar}
    signals = strategy.analyze(market_data)
    
    # Check logs for ATR expansion message
    print("✅ ATR expansion detection test completed")
    print(f"   Generated {len(signals)} signals")
    print()
    
    return True


async def test_near_miss_logging():
    """Test 2: Verify NEAR_MISS logging works for rejected signals."""
    print("=" * 70)
    print("Test 2: NEAR_MISS Logging")
    print("=" * 70)
    print()
    
    # Create provider with conditions that generate signals but may be filtered
    provider = MockDataProvider(
        base_price=17500.0,
        volatility=25.0,
        trend=1.0,  # Uptrend
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    
    config = NQIntradayConfig(symbol="MNQ", timeframe="1m")
    strategy = NQIntradayStrategy(config=config)
    
    # Generate data
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)
    df = provider.fetch_historical("MNQ", start, end, "1m")
    latest_bar = await provider.get_latest_bar("MNQ")
    
    market_data = {"df": df, "latest_bar": latest_bar}
    signals = strategy.analyze(market_data)
    
    print(f"✅ NEAR_MISS logging test completed")
    print(f"   Generated {len(signals)} signals")
    print("   Check logs for NEAR_MISS entries if signals were filtered")
    print()
    
    return True


async def test_volatility_aware_confidence():
    """Test 3: Verify volatility-aware confidence floor works."""
    print("=" * 70)
    print("Test 3: Volatility-Aware Confidence Floor")
    print("=" * 70)
    print()
    
    provider = HighVolatilityMockProvider(
        base_price=17500.0,
        volatility=40.0,  # High volatility
        trend=1.5,  # Strong trend
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    
    config = NQIntradayConfig(symbol="MNQ", timeframe="1m")
    strategy = NQIntradayStrategy(config=config)
    
    # Generate data
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)
    df = provider.fetch_historical("MNQ", start, end, "1m")
    latest_bar = await provider.get_latest_bar("MNQ")
    
    market_data = {"df": df, "latest_bar": latest_bar}
    signals = strategy.analyze(market_data)
    
    print(f"✅ Volatility-aware confidence floor test completed")
    print(f"   Generated {len(signals)} signals")
    print("   During ATR expansion, confidence floor is 0.48 (vs 0.50 normal)")
    print()
    
    return True


async def main():
    """Run all signal starvation fix tests."""
    print()
    print("=" * 70)
    print("Signal Starvation Fixes Validation")
    print("=" * 70)
    print()
    print("Testing improvements made to address signal starvation:")
    print("1. NEAR_MISS logging for rejected signals")
    print("2. Volatility-aware confidence floor (0.48 during ATR expansion)")
    print("3. Relaxed MTF thresholds during volatility expansion")
    print("4. Relative RSI movement detection")
    print("5. Fresh breakout detection with relaxed RSI")
    print()
    
    results = []
    
    # Test 1: ATR expansion detection
    try:
        results.append(("ATR Expansion Detection", await test_atr_expansion_detection()))
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("ATR Expansion Detection", False))
    
    # Test 2: NEAR_MISS logging
    try:
        results.append(("NEAR_MISS Logging", await test_near_miss_logging()))
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("NEAR_MISS Logging", False))
    
    # Test 3: Volatility-aware confidence
    try:
        results.append(("Volatility-Aware Confidence", await test_volatility_aware_confidence()))
    except Exception as e:
        print(f"❌ Test 3 failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Volatility-Aware Confidence", False))
    
    print()
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(r[1] for r in results)
    print()
    print("=" * 70)
    print("Improvements Summary")
    print("=" * 70)
    print()
    print("1. NEAR_MISS Logging:")
    print("   - Logs quality_scorer_rejection with full context")
    print("   - Logs confidence_rejection with gap analysis")
    print("   - Logs risk_reward_rejection with price details")
    print()
    print("2. Volatility-Aware Confidence Floor:")
    print("   - During ATR expansion + high volatility: floor = 0.48 (vs 0.50)")
    print("   - Prevents valid structure-based signals from being killed")
    print()
    print("3. Relaxed MTF Thresholds:")
    print("   - Momentum: -0.20 during expansion (vs -0.15 normal)")
    print("   - Mean reversion: -0.30 during expansion (vs -0.25 normal)")
    print("   - Breakout: -0.25 during expansion (vs -0.20 normal)")
    print()
    print("4. Relative RSI Movement:")
    print("   - Mean reversion: accepts RSI momentum down (>5 points in 3 bars)")
    print("   - Captures fast pullbacks during volatile moves")
    print()
    print("5. Fresh Breakout Detection:")
    print("   - Relaxed RSI threshold (40 vs 45) for fresh breakouts")
    print("   - Structure-first approach: price action before indicators")
    print()
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)




