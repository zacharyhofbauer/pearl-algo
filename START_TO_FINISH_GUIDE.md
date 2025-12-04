# PearlAlgo v2 - Complete Start-to-Finish Guide

## 🎯 Overview

This guide walks you through setting up, testing, and using the new PearlAlgo v2 system from scratch. The system is **completely independent of IBKR** and ready for professional quant trading.

---

## 📋 Prerequisites

### Required
- Python 3.12+
- pip
- Basic command line knowledge

### Optional (for full functionality)
- Polygon.io API key (for real-time data)
- Tradier API key (for options chains)
- Git (for version control)

---

## Step 1: Initial Setup

### 1.1 Navigate to Project Directory

```bash
cd ~/pearlalgo-dev-ai-agents
```

### 1.2 Activate Virtual Environment

```bash
# Create virtual environment if it doesn't exist
python3 -m venv .venv

# Activate it
source .venv/bin/activate  # Linux/Mac
# OR
# .venv\Scripts\activate  # Windows
```

### 1.3 Install/Update Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install the project and all dependencies
pip install -e .

# Verify installation
python -c "import pearlalgo; print('✅ PearlAlgo installed successfully')"
```

### 1.4 Verify New Dependencies

Check that new dependencies are installed:
```bash
python -c "import pyarrow; import requests; print('✅ New dependencies installed')"
```

---

## Step 2: Configure Data Providers

### 2.1 Set Up Environment Variables

Create/edit `.env` file in project root:

```bash
# Copy example if exists, or create new
nano .env
```

Add these variables:

```bash
# Polygon.io (Recommended - for real-time data)
POLYGON_API_KEY=your_polygon_key_here

# Tradier (Optional - for options chains, free with trading account)
TRADIER_API_KEY=your_tradier_key_here
TRADIER_ACCOUNT_ID=your_account_id  # Optional

# Trading Profile
PEARLALGO_PROFILE=paper  # paper, live, backtest, dummy

# IBKR (OPTIONAL - deprecated, only if you want to use IBKR)
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
```

### 2.2 Get API Keys

**Polygon.io (Recommended):**
1. Go to https://polygon.io
2. Sign up for Developer plan ($99/mo) or Starter plan ($29/mo)
3. Get your API key from dashboard
4. Add to `.env` file

**Tradier (Optional - for options):**
1. Go to https://tradier.com
2. Sign up for brokerage account (options data is free with account)
3. Get API key from developer settings
4. Add to `.env` file

### 2.3 Verify Configuration

```bash
# Test configuration loading
python scripts/debug_env.py
```

Expected output should show your API keys (masked) and configuration.

---

## Step 3: Test Data Providers

### 3.1 Test Polygon Provider

Create a test script `test_polygon.py`:

```python
import asyncio
from pearlalgo.data_providers.factory import create_data_provider

async def test_polygon():
    provider = create_data_provider("polygon", api_key="your_key_here")
    
    # Test historical data
    df = provider.fetch_historical(
        symbol="QQQ",
        start=None,  # Will default to 1 year ago
        end=None,    # Will default to now
        timeframe="15m"
    )
    
    print(f"✅ Retrieved {len(df)} rows for QQQ")
    print(df.head())
    
    # Close provider
    await provider.close()

if __name__ == "__main__":
    asyncio.run(test_polygon())
```

Run it:
```bash
python test_polygon.py
```

### 3.2 Test Local Parquet Provider

```python
from pearlalgo.data_providers.factory import create_data_provider
import pandas as pd
from datetime import datetime

# Create provider
provider = create_data_provider("local_parquet", root_dir="data/historical")

# Create sample data
dates = pd.date_range(start="2024-01-01", end="2024-01-10", freq="D")
df = pd.DataFrame({
    "open": 100.0,
    "high": 105.0,
    "low": 95.0,
    "close": 102.0,
    "volume": 1000,
}, index=dates)

# Save
provider.save_historical(df=df, symbol="QQQ", timeframe="1d", overwrite=True)

# Load
loaded = provider.fetch_historical(symbol="QQQ", timeframe="1d")
print(f"✅ Loaded {len(loaded)} rows")
```

---

## Step 4: Download Historical Data

### 4.1 Download Data for Backtesting

```bash
# Download QQQ, SPY, AAPL data (last year, 15-minute bars)
python scripts/download_historical_data.py \
    --symbols QQQ SPY AAPL \
    --provider polygon \
    --start-date 2023-12-01 \
    --timeframe 15m \
    --output-dir data/historical
```

This will:
- Download historical data from Polygon.io
- Store in Parquet format in `data/historical/`
- Enable deterministic backtesting

### 4.2 Verify Downloaded Data

```python
from pearlalgo.data_providers.local_parquet_provider import LocalParquetProvider

provider = LocalParquetProvider(root_dir="data/historical")

# List available symbols
symbols = provider.list_symbols(timeframe="15m")
print(f"Available symbols: {symbols}")

# Check data for one symbol
df = provider.fetch_historical("QQQ", timeframe="15m")
print(f"QQQ data: {len(df)} rows from {df.index.min()} to {df.index.max()}")
```

---

## Step 5: Test Paper Trading Engines

### 5.1 Test Futures Engine

Create `test_futures_engine.py`:

```python
from datetime import datetime
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from pearlalgo.paper_trading.futures_engine import PaperFuturesEngine

# Create portfolio
portfolio = Portfolio(cash=50000.0)

# Create price lookup function
def price_lookup(symbol: str):
    prices = {"ES": 4000.0, "NQ": 15000.0}
    return prices.get(symbol)

# Create engine
engine = PaperFuturesEngine(
    portfolio=portfolio,
    price_lookup=price_lookup,
)

# Submit an order
order = OrderEvent(
    timestamp=datetime.now(),
    symbol="ES",
    side="BUY",
    quantity=1.0,
)

fill = engine.submit_order(order)
print(f"✅ Order filled: {fill.symbol} @ {fill.price:.2f}")

# Check positions
positions = engine.get_positions()
print(f"✅ Positions: {positions}")

# Check account
print(f"✅ Cash remaining: ${portfolio.cash:.2f}")
```

Run it:
```bash
python test_futures_engine.py
```

### 5.2 Test Options Engine

Create `test_options_engine.py`:

```python
from datetime import datetime
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from pearlalgo.paper_trading.options_engine import PaperOptionsEngine

# Create portfolio
portfolio = Portfolio(cash=10000.0)

# Create options chain lookup
def options_chain(underlying: str):
    if underlying == "QQQ":
        return [{
            "symbol": "QQQ_20241220_C_400",
            "strike": 400.0,
            "expiration": "2024-12-20",
            "option_type": "call",
            "bid": 2.45,
            "ask": 2.55,
            "last": 2.50,
        }]
    return []

# Create engine
engine = PaperOptionsEngine(
    portfolio=portfolio,
    options_chain_lookup=options_chain,
)

# Update options chain
engine.update_options_chain("QQQ", options_chain("QQQ"))

# Submit order
order = OrderEvent(
    timestamp=datetime.now(),
    symbol="QQQ_20241220_C_400",
    side="BUY",
    quantity=1.0,
)

fill = engine.submit_order(order)
if fill:
    print(f"✅ Options fill: {fill.symbol} @ ${fill.price:.2f}")
```

---

## Step 6: Test Paper Broker

### 6.1 Basic Paper Broker Test

Create `test_paper_broker.py`:

```python
from datetime import datetime
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from pearlalgo.brokers.paper_broker import PaperBroker

# Create portfolio
portfolio = Portfolio(cash=50000.0)

# Create broker
def price_lookup(symbol: str):
    return 4000.0 if symbol == "ES" else None

broker = PaperBroker(
    portfolio=portfolio,
    price_lookup=price_lookup,
)

# Submit order
order = OrderEvent(
    timestamp=datetime.now(),
    symbol="ES",
    side="BUY",
    quantity=1.0,
)

order_id = broker.submit_order(order)
print(f"✅ Order submitted: {order_id}")

# Get fills
fills = list(broker.fetch_fills())
print(f"✅ Fills: {len(fills)}")

# Get account summary
summary = broker.get_account_summary()
print(f"✅ Equity: ${summary.equity:.2f}")
print(f"✅ Cash: ${summary.cash:.2f}")
print(f"✅ Positions: {broker.sync_positions()}")
```

---

## Step 7: Run All Tests

### 7.1 Run Unit Tests

```bash
# Run all new tests
pytest tests/test_fill_models.py -v
pytest tests/test_margin_models.py -v
pytest tests/test_paper_trading_engines.py -v
pytest tests/test_data_providers.py -v
pytest tests/test_risk_calculators.py -v
pytest tests/test_trade_ledger.py -v
```

### 7.2 Run All Tests at Once

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=pearlalgo --cov-report=html
```

### 7.3 Expected Results

All tests should pass. If any fail:
1. Check error messages
2. Verify API keys are set
3. Check dependencies are installed

---

## Step 8: Test Trade Ledger

### 8.1 Test Trade Ledger

Create `test_ledger.py`:

```python
from datetime import datetime
from pearlalgo.persistence.trade_ledger import TradeLedger
from pearlalgo.core.events import FillEvent, OrderEvent

# Create ledger
ledger = TradeLedger(db_path="data/test_ledger.db")

# Record an order
order = OrderEvent(
    timestamp=datetime.now(),
    symbol="QQQ",
    side="BUY",
    quantity=1.0,
)
ledger.record_order(order, order_id="TEST_001", status="Pending")

# Record a fill
fill = FillEvent(
    timestamp=datetime.now(),
    symbol="QQQ",
    side="BUY",
    quantity=1.0,
    price=400.0,
    commission=1.0,
)
ledger.record_fill(fill, order_id="TEST_001")

# Query fills
fills = ledger.get_fills(symbol="QQQ")
print(f"✅ Recorded {len(fills)} fills")

# Get daily PnL
daily_pnl = ledger.get_daily_pnl()
print(f"✅ Daily PnL: ${daily_pnl['realized_pnl']:.2f}")
```

---

## Step 9: End-to-End Workflow Test

### 9.1 Complete Trading Workflow

Create `test_complete_workflow.py`:

```python
"""
Complete end-to-end workflow test:
1. Download data
2. Generate signals
3. Paper trade
4. Record trades
5. Calculate performance
"""

from datetime import datetime
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from pearlalgo.brokers.paper_broker import PaperBroker
from pearlalgo.persistence.trade_ledger import TradeLedger
from pearlalgo.risk.portfolio_risk import PortfolioRiskAggregator

# 1. Setup
portfolio = Portfolio(cash=50000.0)
ledger = TradeLedger("data/workflow_test.db")
risk_aggregator = PortfolioRiskAggregator()

# 2. Create broker
def price_lookup(symbol: str):
    prices = {"ES": 4000.0, "QQQ": 400.0}
    return prices.get(symbol)

broker = PaperBroker(portfolio=portfolio, price_lookup=price_lookup)

# 3. Submit some orders
orders = [
    OrderEvent(datetime.now(), "ES", "BUY", 1.0),
    OrderEvent(datetime.now(), "QQQ", "BUY", 10.0),
]

for i, order in enumerate(orders, 1):
    order_id = broker.submit_order(order)
    print(f"✅ Order {i}: {order_id}")
    
    # Record in ledger
    ledger.record_order(order, order_id, status="Filled")
    
    # Get fill and record
    fills = list(broker.fetch_fills())
    if fills:
        latest_fill = fills[-1]
        ledger.record_fill(latest_fill, order_id)

# 4. Calculate risk metrics
prices = {"ES": 4010.0, "QQQ": 405.0}  # Updated prices
metrics = risk_aggregator.calculate_portfolio_risk_metrics(
    portfolio=portfolio,
    prices=prices
)

print(f"\n✅ Portfolio Metrics:")
print(f"  Equity: ${metrics['total_equity']:.2f}")
print(f"  Unrealized PnL: ${metrics['unrealized_pnl']:.2f}")
print(f"  Margin Usage: {metrics['margin_usage_pct']:.2f}%")

# 5. Get account summary
summary = broker.get_account_summary()
print(f"\n✅ Account Summary:")
print(f"  Equity: ${summary.equity:.2f}")
print(f"  Cash: ${summary.cash:.2f}")
print(f"  Positions: {broker.sync_positions()}")
```

---

## Step 10: Integration with LangGraph (Optional)

### 10.1 Update LangGraph to Use Paper Broker

The LangGraph workflow can now use the paper broker. Update your workflow file to use:

```python
from pearlalgo.brokers.factory import get_broker
from pearlalgo.core.portfolio import Portfolio

# Create paper broker
portfolio = Portfolio(cash=50000.0)
broker = get_broker("paper", portfolio=portfolio)

# Use in LangGraph workflow as before
```

---

## Step 11: Production Checklist

### ✅ Pre-Production Checklist

- [ ] All tests passing
- [ ] API keys configured
- [ ] Historical data downloaded
- [ ] Paper broker tested
- [ ] Trade ledger working
- [ ] Risk calculations verified
- [ ] Configuration files updated
- [ ] Documentation reviewed

### ✅ Production Setup

1. **Configure Primary Broker:**
   ```yaml
   # config/config.yaml
   broker:
     primary: "paper"  # Use paper broker
   ```

2. **Set Trading Profile:**
   ```bash
   export PEARLALGO_PROFILE=paper  # Always start with paper
   ```

3. **Download Required Historical Data:**
   ```bash
   python scripts/download_historical_data.py \
       --symbols QQQ SPY AAPL \
       --provider polygon
   ```

4. **Test Complete Workflow:**
   ```bash
   python test_complete_workflow.py
   ```

---

## Step 12: Daily Usage

### 12.1 Start Paper Trading

```bash
# Activate environment
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Start trading (example)
python -m pearlalgo.live.langgraph_trader \
    --symbols QQQ SPY \
    --strategy sr \
    --mode paper
```

### 12.2 Monitor Trading

```bash
# In another terminal
tail -f logs/langgraph_trading.log

# Or use dashboard
python scripts/dashboard.py
```

### 12.3 Update Historical Data

```bash
# Update existing data (appends new data)
python scripts/update_historical_data.py \
    --symbols QQQ SPY \
    --provider polygon \
    --timeframe 15m
```

---

## Step 13: Troubleshooting

### Common Issues

**Issue: "No data provider available"**
```bash
# Solution: Configure at least one provider
export POLYGON_API_KEY=your_key
# OR use local data only
python scripts/download_historical_data.py --symbols QQQ
```

**Issue: "Module not found"**
```bash
# Solution: Reinstall dependencies
pip install -e .
```

**Issue: "API rate limit exceeded"**
```bash
# Solution: Wait and retry, or upgrade Polygon plan
# Or use local data for backtesting
```

**Issue: "Test failures"**
```bash
# Solution: Check that all dependencies installed
pip install pyarrow requests py-vollib
```

---

## Step 14: Next Steps

### Recommended Next Steps

1. **Download More Historical Data**
   - Download data for all symbols you trade
   - Store in Parquet format for fast access

2. **Test Your Strategies**
   - Run backtests using local data
   - Validate signals with paper trading

3. **Monitor Performance**
   - Check trade ledger regularly
   - Review account snapshots
   - Analyze PnL

4. **Scale Up**
   - Add more symbols
   - Optimize strategies
   - Enhance risk management

---

## 📚 Additional Resources

- `ARCHITECTURE_V2.md` - System architecture details
- `MIGRATION_GUIDE_IBKR_TO_V2.md` - Migration from IBKR
- `COMPLETE_IMPLEMENTATION_REPORT.md` - Full implementation report
- `tests/` - All test files for examples

---

## ✅ Success Criteria

You've successfully set up PearlAlgo v2 when:

- ✅ All tests pass
- ✅ Data providers working (Polygon/local)
- ✅ Paper broker executes orders
- ✅ Trade ledger records trades
- ✅ Risk calculations work
- ✅ System runs without IBKR

**Congratulations! You now have a professional, vendor-agnostic quant trading system!** 🎉


