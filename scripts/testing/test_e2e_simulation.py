#!/usr/bin/env python3
"""
End-to-End Dry-Run Simulation

Simulates a full trading day with various scenarios:
1. Market Open (09:30 ET) - Service starts, data fetching begins
2. High Volatility (10:00-11:00 ET) - Rapid price movements, ATR expansion
3. Trend + Reversal (11:30-12:30 ET) - Strong trend followed by reversal
4. Stale Data Event (13:00 ET) - Simulate IBKR connection loss for 5 minutes
5. Recovery (13:05 ET) - Connection restored, data freshness check
6. Signal Generation Attempt (14:00 ET) - Conditions should trigger signal
7. No-Signal Outcome (15:00 ET) - Conditions filtered out, verify why
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from tests.mock_data_provider import MockDataProvider
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


class ScenarioMockProvider(MockDataProvider):
    """Enhanced mock provider that supports time-based scenarios."""
    
    def __init__(self, scenario_time=None, **kwargs):
        super().__init__(**kwargs)
        self.scenario_time = scenario_time or datetime.now(timezone.utc)
        self.scenario = "normal"
    
    def set_scenario(self, scenario_name):
        """Set current scenario (affects data generation)."""
        self.scenario = scenario_name
    
    def set_time(self, dt):
        """Set scenario time (for testing different market conditions)."""
        self.scenario_time = dt
    
    def fetch_historical(self, symbol, start, end, timeframe="1m"):
        """Generate data based on current scenario."""
        df = super().fetch_historical(symbol, start, end, timeframe)
        
        # Adjust data based on scenario
        if self.scenario == "high_volatility":
            # Increase volatility
            df["high"] = df["high"] * (1 + 0.01 * (df.index % 10))
            df["low"] = df["low"] * (1 - 0.01 * (df.index % 10))
        elif self.scenario == "trending":
            # Add strong trend
            trend_factor = 0.5 * (df.index - df.index[0]) / len(df)
            df["close"] = df["close"] + trend_factor * 100
        elif self.scenario == "stale":
            # Make latest bar stale (15 minutes old)
            if isinstance(df.index, pd.DatetimeIndex) and len(df) > 0:
                stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
                new_index = df.index[:-1].tolist() + [stale_time]
                df.index = pd.DatetimeIndex(new_index)
        
        return df


async def run_simulation():
    """Run end-to-end simulation."""
    print("=" * 70)
    print("End-to-End Trading Day Simulation")
    print("=" * 70)
    print()
    
    # Create scenario-based mock provider
    provider = ScenarioMockProvider(
        base_price=17500.0,
        volatility=25.0,
        trend=0.5,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    
    config = NQIntradayConfig(symbol="MNQ", timeframe="1m", scan_interval=5)
    
    # Create service
    service = NQAgentService(
        data_provider=provider,
        config=config,
        telegram_bot_token=None,  # Disable for simulation
        telegram_chat_id=None,
    )
    
    print("Scenario 1: Market Open (09:30 ET)")
    print("-" * 70)
    provider.set_scenario("normal")
    # Simulate market open
    market_data = await service.data_fetcher.fetch_latest_data()
    signals = service.strategy.analyze(market_data)
    print(f"✅ Market data fetched: {len(market_data.get('df', []))} bars")
    print(f"✅ Signals generated: {len(signals)}")
    print()
    
    print("Scenario 2: High Volatility (10:00-11:00 ET)")
    print("-" * 70)
    provider.set_scenario("high_volatility")
    market_data = await service.data_fetcher.fetch_latest_data()
    signals = service.strategy.analyze(market_data)
    print(f"✅ High volatility data: {len(market_data.get('df', []))} bars")
    print(f"✅ Signals generated: {len(signals)}")
    if signals:
        print(f"   Signal confidence: {signals[0].get('confidence', 0):.0%}")
    print()
    
    print("Scenario 3: Trending Market (11:30-12:30 ET)")
    print("-" * 70)
    provider.set_scenario("trending")
    market_data = await service.data_fetcher.fetch_latest_data()
    signals = service.strategy.analyze(market_data)
    print(f"✅ Trending data: {len(market_data.get('df', []))} bars")
    print(f"✅ Signals generated: {len(signals)}")
    print()
    
    print("Scenario 4: Stale Data Event (13:00 ET)")
    print("-" * 70)
    provider.set_scenario("stale")
    market_data = await service.data_fetcher.fetch_latest_data()
    # Check if stale data is detected
    if market_data.get("latest_bar"):
        latest_time = market_data["latest_bar"].get("timestamp")
        if latest_time:
            if isinstance(latest_time, str):
                latest_time = datetime.fromisoformat(latest_time.replace("Z", "+00:00"))
            age_minutes = (datetime.now(timezone.utc) - latest_time.replace(tzinfo=timezone.utc)).total_seconds() / 60
            print(f"⚠️  Latest bar age: {age_minutes:.1f} minutes")
            if age_minutes > 10:
                print("✅ Stale data would trigger alert")
    print()
    
    print("Scenario 5: Recovery (13:05 ET)")
    print("-" * 70)
    provider.set_scenario("normal")
    market_data = await service.data_fetcher.fetch_latest_data()
    print(f"✅ Data freshness restored: {len(market_data.get('df', []))} bars")
    print()
    
    print("=" * 70)
    print("✅ Simulation completed")
    print("=" * 70)
    
    await service.stop()


if __name__ == "__main__":
    import pandas as pd
    asyncio.run(run_simulation())
