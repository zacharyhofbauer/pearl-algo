#!/usr/bin/env python3
"""
Quick Test Script for PearlAlgo v2 System

Tests all major components to verify the system is working correctly.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from pearlalgo.brokers.paper_broker import PaperBroker
from pearlalgo.persistence.trade_ledger import TradeLedger
from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.risk.portfolio_risk import PortfolioRiskAggregator

print("=" * 60)
print("PearlAlgo v2 System Test")
print("=" * 60)

# Test 1: Data Providers
print("\n1. Testing Data Providers...")
try:
    # Test factory
    from pearlalgo.data_providers.factory import list_available_providers
    providers = list_available_providers()
    print(f"   ✅ Available providers: {', '.join(providers)}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 2: Paper Broker
print("\n2. Testing Paper Broker...")
try:
    portfolio = Portfolio(cash=50000.0)
    
    def price_lookup(symbol: str):
        prices = {"ES": 4000.0, "QQQ": 400.0}
        return prices.get(symbol)
    
    broker = PaperBroker(portfolio=portfolio, price_lookup=price_lookup)
    print("   ✅ PaperBroker created successfully")
    
    # Test order submission
    order = OrderEvent(
        timestamp=datetime.now(),
        symbol="ES",
        side="BUY",
        quantity=1.0,
    )
    order_id = broker.submit_order(order)
    print(f"   ✅ Order submitted: {order_id}")
    
    positions = broker.sync_positions()
    print(f"   ✅ Positions: {positions}")
    
except Exception as e:
    print(f"   ❌ Error: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Trade Ledger
print("\n3. Testing Trade Ledger...")
try:
    ledger = TradeLedger(db_path="data/test_ledger_quick.db")
    print("   ✅ TradeLedger created successfully")
    
    # Test recording
    fill = OrderEvent(
        timestamp=datetime.now(),
        symbol="ES",
        side="BUY",
        quantity=1.0,
    )
    ledger.record_order(fill, order_id="TEST_001", status="Filled")
    print("   ✅ Order recorded successfully")
    
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 4: Risk Calculators
print("\n4. Testing Risk Calculators...")
try:
    from pearlalgo.risk.futures_risk import FuturesRiskCalculator
    from pearlalgo.risk.options_risk import OptionsRiskCalculator
    
    futures_calc = FuturesRiskCalculator()
    margin = futures_calc.calculate_margin_requirement("ES", quantity=1.0)
    print(f"   ✅ Futures margin calculated: ${margin['total_required']:.2f}")
    
    options_calc = OptionsRiskCalculator()
    delta_exposure = options_calc.calculate_delta_exposure(
        position_quantity=1.0,
        option_delta=0.5,
        underlying_price=400.0
    )
    print(f"   ✅ Options delta exposure: ${delta_exposure:.2f}")
    
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 5: Paper Trading Engines
print("\n5. Testing Paper Trading Engines...")
try:
    from pearlalgo.paper_trading.futures_engine import PaperFuturesEngine
    
    portfolio = Portfolio(cash=50000.0)
    engine = PaperFuturesEngine(
        portfolio=portfolio,
        price_lookup=lambda s: 4000.0 if s == "ES" else None,
    )
    print("   ✅ PaperFuturesEngine created successfully")
    
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 6: Portfolio Risk
print("\n6. Testing Portfolio Risk Aggregator...")
try:
    portfolio = Portfolio(cash=50000.0)
    aggregator = PortfolioRiskAggregator()
    
    metrics = aggregator.calculate_portfolio_risk_metrics(
        portfolio=portfolio,
        prices={}
    )
    print(f"   ✅ Portfolio metrics calculated")
    print(f"      Equity: ${metrics['total_equity']:.2f}")
    
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 60)
print("Test Complete!")
print("=" * 60)
print("\nIf all tests passed, your PearlAlgo v2 system is ready!")
print("\nNext steps:")
print("1. Configure API keys in .env file")
print("2. Download historical data: python scripts/download_historical_data.py")
print("3. Start trading: See START_TO_FINISH_GUIDE.md")

