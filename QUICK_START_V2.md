# PearlAlgo v2 - Quick Start Guide

## ⚡ 5-Minute Setup

Get up and running with PearlAlgo v2 in 5 minutes!

---

## Step 1: Install Dependencies (1 minute)

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate  # Or create venv if needed
pip install -e .
```

---

## Step 2: Configure API Key (1 minute)

```bash
# Edit .env file
nano .env

# Add this line:
POLYGON_API_KEY=your_key_here

# OR skip API key and use local data only
```

---

## Step 3: Quick Test (1 minute)

```bash
# Run quick system test
python scripts/test_new_system.py
```

**Expected output:** All tests should pass with ✅

---

## Step 4: Download Sample Data (2 minutes)

```bash
# Download historical data for backtesting
python scripts/download_historical_data.py \
    --symbols QQQ \
    --provider polygon \
    --timeframe 15m \
    --start-date 2024-01-01
```

**OR** use existing CSV data:
```bash
# System can use existing CSV files in data/ directory
```

---

## Step 5: Start Trading! 🚀

```python
# Quick Python example
from pearlalgo.brokers.paper_broker import PaperBroker
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from datetime import datetime

# Create portfolio
portfolio = Portfolio(cash=50000.0)

# Create broker (no IBKR needed!)
broker = PaperBroker(
    portfolio=portfolio,
    price_lookup=lambda s: 4000.0 if s == "ES" else None
)

# Trade!
order = OrderEvent(
    timestamp=datetime.now(),
    symbol="ES",
    side="BUY",
    quantity=1.0
)

order_id = broker.submit_order(order)
print(f"Order {order_id} submitted!")

# Check positions
print(f"Positions: {broker.sync_positions()}")
```

---

## ✅ Success!

You're now trading with PearlAlgo v2 **without IBKR**!

**Next Steps:**
- See `START_TO_FINISH_GUIDE.md` for detailed walkthrough
- See `ARCHITECTURE_V2.md` for system architecture
- See `MIGRATION_GUIDE_IBKR_TO_V2.md` if migrating from IBKR

---

## Troubleshooting

**"No data provider available"**
→ Set `POLYGON_API_KEY` in .env or use local CSV data

**"Module not found"**
→ Run `pip install -e .` again

**Tests fail**
→ Check that all dependencies installed: `pip install pyarrow requests py-vollib`

---

**That's it! You're ready to trade!** 🎉



