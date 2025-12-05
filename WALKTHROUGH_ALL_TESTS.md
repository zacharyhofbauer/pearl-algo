# Complete Walkthrough: Testing PearlAlgo v2 System

## 🎯 Overview

This document provides a **complete start-to-finish walkthrough** of all tests and system verification for PearlAlgo v2. Follow these steps to verify everything is working correctly.

---

## Prerequisites Check

### Step 0: Environment Setup

```bash
# Navigate to project
cd ~/pearlalgo-dev-ai-agents

# Activate virtual environment
source .venv/bin/activate

# Verify Python version (3.12+)
python --version

# Verify installation
python -c "import pearlalgo; print('✅ PearlAlgo installed')"
```

**Expected Output:**
```
Python 3.12.x
✅ PearlAlgo installed
```

---

## Part 1: Quick System Test

### Test 1.1: Run Quick System Verification

```bash
python scripts/test_new_system.py
```

**What This Tests:**
- Data provider factory
- Paper broker creation
- Trade ledger initialization
- Risk calculators
- Paper trading engines
- Portfolio risk aggregator

**Expected Output:**
```
============================================================
PearlAlgo v2 System Test
============================================================

1. Testing Data Providers...
   ✅ Available providers: polygon, tradier, local_csv, local_parquet

2. Testing Paper Broker...
   ✅ PaperBroker created successfully
   ✅ Order submitted: PAPER_000001
   ✅ Positions: {'ES': 1.0}

3. Testing Trade Ledger...
   ✅ TradeLedger created successfully
   ✅ Order recorded successfully

4. Testing Risk Calculators...
   ✅ Futures margin calculated: $4000.00
   ✅ Options delta exposure: $200.00

5. Testing Paper Trading Engines...
   ✅ PaperFuturesEngine created successfully

6. Testing Portfolio Risk Aggregator...
   ✅ Portfolio metrics calculated
      Equity: $50000.00

============================================================
Test Complete!
============================================================
```

**If any test fails:** Check error messages and verify dependencies are installed.

---

## Part 2: Unit Tests (Comprehensive)

### Test 2.1: Fill Models Tests

```bash
pytest tests/test_fill_models.py -v
```

**What This Tests:**
- Slippage calculations
- Execution delay simulation
- Deterministic vs. random modes
- Fill price adjustments

**Expected:** All tests pass (typically 5-10 tests)

### Test 2.2: Margin Models Tests

```bash
pytest tests/test_margin_models.py -v
```

**What This Tests:**
- Futures margin calculations (SPAN-like)
- Options margin calculations
- Margin requirement lookups
- Position sizing

**Expected:** All tests pass (typically 8-12 tests)

### Test 2.3: Paper Trading Engines Tests

```bash
pytest tests/test_paper_trading_engines.py -v
```

**What This Tests:**
- Futures engine order processing
- Options engine order processing
- Fill generation
- Position tracking
- PnL calculations

**Expected:** All tests pass (typically 15-20 tests)

### Test 2.4: Data Providers Tests

```bash
pytest tests/test_data_providers.py -v
```

**What This Tests:**
- Polygon provider
- Tradier provider
- Local Parquet provider
- Data normalization
- Error handling

**Expected:** Most tests pass (some may skip if API keys not configured)

**Note:** Tests that require API keys will be skipped if keys are not set. This is expected.

### Test 2.5: Risk Calculators Tests

```bash
pytest tests/test_risk_calculators.py -v
```

**What This Tests:**
- Futures risk metrics
- Options risk metrics (Greeks)
- Portfolio risk aggregation
- Margin calculations
- Risk limits

**Expected:** All tests pass (typically 10-15 tests)

### Test 2.6: Trade Ledger Tests

```bash
pytest tests/test_trade_ledger.py -v
```

**What This Tests:**
- Trade recording
- Fill storage
- Order tracking
- Query functionality
- Data integrity

**Expected:** All tests pass (typically 8-12 tests)

### Test 2.7: Run All Tests at Once

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=pearlalgo --cov-report=html --cov-report=term

# View coverage report
open htmlcov/index.html  # Mac
xdg-open htmlcov/index.html  # Linux
```

**Expected:** 
- All unit tests pass
- Coverage should be >80% for new modules
- No critical failures

---

## Part 3: Integration Tests

### Test 3.1: End-to-End Workflow Test

Create file: `test_e2e_workflow.py`

```python
"""
End-to-end workflow test:
1. Download data
2. Create broker
3. Submit orders
4. Record trades
5. Calculate performance
"""

from datetime import datetime
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from pearlalgo.brokers.paper_broker import PaperBroker
from pearlalgo.persistence.trade_ledger import TradeLedger
from pearlalgo.risk.futures_risk import FuturesRiskCalculator

print("=" * 60)
print("End-to-End Workflow Test")
print("=" * 60)

# 1. Setup
portfolio = Portfolio(cash=50000.0)
ledger = TradeLedger("data/e2e_test.db")
risk_calc = FuturesRiskCalculator()

# 2. Create broker
def price_lookup(symbol: str):
    prices = {"ES": 4000.0, "QQQ": 400.0}
    return prices.get(symbol)

broker = PaperBroker(portfolio=portfolio, price_lookup=price_lookup)

# 3. Submit orders
orders = [
    OrderEvent(datetime.now(), "ES", "BUY", 1.0),
    OrderEvent(datetime.now(), "ES", "SELL", 1.0),  # Close position
]

print("\n📋 Submitting orders...")
for i, order in enumerate(orders, 1):
    order_id = broker.submit_order(order)
    print(f"   ✅ Order {i}: {order_id}")

# 4. Check positions
positions = broker.sync_positions()
print(f"\n📊 Positions: {positions}")

# 5. Get fills and record
fills = list(broker.fetch_fills())
print(f"\n💰 Fills: {len(fills)}")
for fill in fills:
    print(f"   {fill.symbol} {fill.side} {fill.quantity} @ ${fill.price:.2f}")
    # Record in ledger
    from pearlalgo.core.events import FillEvent
    if isinstance(fill, FillEvent):
        ledger.record_fill(fill)

# 6. Calculate risk
margin = risk_calc.calculate_margin_requirement("ES", 1.0)
print(f"\n⚖️  Margin requirement: ${margin['total_required']:.2f}")

# 7. Account summary
summary = broker.get_account_summary()
print(f"\n💵 Account Summary:")
print(f"   Equity: ${summary.equity:.2f}")
print(f"   Cash: ${summary.cash:.2f}")
print(f"   Unrealized PnL: ${summary.unrealized_pnl:.2f}")

print("\n" + "=" * 60)
print("✅ End-to-End Test Complete!")
print("=" * 60)
```

Run it:
```bash
python test_e2e_workflow.py
```

**Expected Output:**
- Orders submitted successfully
- Positions tracked correctly
- Fills recorded
- Risk calculated
- Account summary accurate

---

## Part 4: Data Provider Tests (With API Keys)

### Test 4.1: Test Polygon Provider (Requires API Key)

Create file: `test_polygon_live.py`

```python
"""Test Polygon.io provider with live API."""
import asyncio
from pearlalgo.data_providers.factory import create_data_provider

async def test():
    # Set your API key
    provider = create_data_provider("polygon", api_key="YOUR_KEY_HERE")
    
    # Test historical data
    print("Fetching QQQ historical data...")
    df = provider.fetch_historical(
        symbol="QQQ",
        start=None,
        end=None,
        timeframe="1d"
    )
    
    print(f"✅ Retrieved {len(df)} rows")
    print(df.head())
    
    await provider.close()

if __name__ == "__main__":
    asyncio.run(test())
```

Run it:
```bash
export POLYGON_API_KEY=your_key_here
python test_polygon_live.py
```

**Expected:**
- Data retrieved successfully
- DataFrame contains OHLCV columns
- Data is recent and accurate

### Test 4.2: Test Local Parquet Provider

Create file: `test_local_data.py`

```python
"""Test local Parquet data provider."""
from pearlalgo.data_providers.factory import create_data_provider
import pandas as pd

# Create provider
provider = create_data_provider("local_parquet", root_dir="data/historical")

# Check available symbols
try:
    # List available files
    import os
    files = os.listdir("data/historical") if os.path.exists("data/historical") else []
    print(f"Available data files: {files}")
    
    # Try to load if exists
    if files:
        symbol = files[0].split("_")[0]
        df = provider.fetch_historical(symbol=symbol, timeframe="15m")
        print(f"✅ Loaded {len(df)} rows for {symbol}")
    else:
        print("ℹ️  No local data files found. Download data first:")
        print("   python scripts/download_historical_data.py --symbols QQQ")
        
except Exception as e:
    print(f"❌ Error: {e}")
```

Run it:
```bash
python test_local_data.py
```

---

## Part 5: Performance & Stress Tests

### Test 5.1: Paper Trading Performance

Create file: `test_performance.py`

```python
"""Performance test for paper trading engine."""
import time
from datetime import datetime
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from pearlalgo.paper_trading.futures_engine import PaperFuturesEngine

portfolio = Portfolio(cash=100000.0)

def price_lookup(symbol: str):
    return 4000.0

engine = PaperFuturesEngine(portfolio=portfolio, price_lookup=price_lookup)

# Submit many orders
start = time.time()
num_orders = 1000

for i in range(num_orders):
    order = OrderEvent(
        timestamp=datetime.now(),
        symbol="ES",
        side="BUY" if i % 2 == 0 else "SELL",
        quantity=1.0,
    )
    engine.submit_order(order)

elapsed = time.time() - start
orders_per_second = num_orders / elapsed

print(f"✅ Processed {num_orders} orders in {elapsed:.2f}s")
print(f"   Rate: {orders_per_second:.0f} orders/second")
```

Run it:
```bash
python test_performance.py
```

**Expected:**
- Processes orders quickly (>100 orders/second)
- No errors or crashes

---

## Part 6: Manual Verification

### Test 6.1: Verify Directory Structure

```bash
# Check new directories exist
ls -la src/pearlalgo/paper_trading/
ls -la src/pearlalgo/persistence/
ls -la src/pearlalgo/mirror_trading/
ls -la config/
```

**Expected:**
- All new directories exist
- Key files present

### Test 6.2: Verify Configuration

```bash
# Check config files
cat config/config.yaml | grep -A 5 broker
cat config/data_providers.yaml
```

**Expected:**
- Broker default is "paper"
- IBKR is optional
- Data providers configured

### Test 6.3: Check Documentation

```bash
# Verify documentation exists
ls -la *.md | grep -E "(START|QUICK|ARCHITECTURE|MIGRATION)"
```

**Expected:**
- START_TO_FINISH_GUIDE.md
- QUICK_START_V2.md
- ARCHITECTURE_V2.md
- MIGRATION_GUIDE_IBKR_TO_V2.md

---

## Part 7: Complete System Validation

### Test 7.1: Full System Test Script

Create file: `validate_system.py`

```python
"""Complete system validation."""
import sys
from pathlib import Path

tests_passed = 0
tests_failed = 0

def test(name, func):
    global tests_passed, tests_failed
    try:
        result = func()
        if result:
            print(f"✅ {name}")
            tests_passed += 1
        else:
            print(f"❌ {name}")
            tests_failed += 1
    except Exception as e:
        print(f"❌ {name}: {e}")
        tests_failed += 1

print("=" * 60)
print("Complete System Validation")
print("=" * 60)

# Test 1: Imports
test("Imports", lambda: __import__("pearlalgo"))

# Test 2: Data providers
test("Data Provider Factory", lambda: 
    __import__("pearlalgo.data_providers.factory").data_providers.factory.list_available_providers()
)

# Test 3: Paper broker
test("Paper Broker", lambda:
    __import__("pearlalgo.brokers.paper_broker").brokers.paper_broker.PaperBroker
)

# Test 4: Trading engines
test("Futures Engine", lambda:
    __import__("pearlalgo.paper_trading.futures_engine").paper_trading.futures_engine.PaperFuturesEngine
)

test("Options Engine", lambda:
    __import__("pearlalgo.paper_trading.options_engine").paper_trading.options_engine.PaperOptionsEngine
)

# Test 5: Persistence
test("Trade Ledger", lambda:
    __import__("pearlalgo.persistence.trade_ledger").persistence.trade_ledger.TradeLedger
)

# Test 6: Risk
test("Risk Calculators", lambda:
    __import__("pearlalgo.risk.futures_risk").risk.futures_risk.FuturesRiskCalculator
)

print("\n" + "=" * 60)
print(f"Results: {tests_passed} passed, {tests_failed} failed")
print("=" * 60)

sys.exit(0 if tests_failed == 0 else 1)
```

Run it:
```bash
python validate_system.py
```

---

## Summary Checklist

After completing all tests, verify:

- [ ] Quick system test passes
- [ ] All unit tests pass (pytest)
- [ ] Integration test passes
- [ ] Data providers work (or skip if no API keys)
- [ ] Performance is acceptable
- [ ] Documentation exists
- [ ] Configuration is correct
- [ ] System validation passes

---

## Next Steps After Testing

1. **Configure API Keys** (if not already done)
   ```bash
   echo "POLYGON_API_KEY=your_key" >> .env
   ```

2. **Download Historical Data**
   ```bash
   python scripts/download_historical_data.py --symbols QQQ SPY
   ```

3. **Start Trading**
   - Use paper broker in your strategies
   - Monitor trade ledger
   - Review performance

4. **Read Documentation**
   - `START_TO_FINISH_GUIDE.md` - Complete walkthrough
   - `QUICK_START_V2.md` - Quick reference
   - `ARCHITECTURE_V2.md` - System design

---

## Troubleshooting

**Tests fail with import errors:**
```bash
pip install -e .
```

**Tests fail with missing dependencies:**
```bash
pip install pyarrow requests py-vollib scipy
```

**API provider tests fail:**
- This is expected if API keys are not set
- Tests will be skipped automatically
- See test output for details

**Performance tests slow:**
- Normal for first run
- Subsequent runs should be faster
- Check system resources

---

**Congratulations! If all tests pass, your PearlAlgo v2 system is ready for production!** 🎉




