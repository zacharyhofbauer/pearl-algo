# 🚀 PearlAlgo v2 - Start Here!

## Welcome to PearlAlgo v2!

You now have a **professional, vendor-agnostic quant trading system** that is **completely independent of IBKR**. This document will get you started quickly.

---

## ⚡ Quick Start (5 Minutes)

### 1. Install & Verify

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
pip install -e .
python scripts/test_new_system.py
```

### 2. Configure (Optional - for live data)

```bash
# Add to .env file
echo "POLYGON_API_KEY=your_key_here" >> .env
```

### 3. Start Trading!

```python
from pearlalgo.brokers.paper_broker import PaperBroker
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.core.events import OrderEvent
from datetime import datetime

portfolio = Portfolio(cash=50000.0)
broker = PaperBroker(
    portfolio=portfolio,
    price_lookup=lambda s: 4000.0 if s == "ES" else None
)

order = OrderEvent(datetime.now(), "ES", "BUY", 1.0)
order_id = broker.submit_order(order)
print(f"Order {order_id} submitted!")
```

**That's it! You're trading with PearlAlgo v2!** 🎉

---

## 📚 Documentation Guide

### For Quick Start:
👉 **[QUICK_START_V2.md](QUICK_START_V2.md)** - 5-minute setup guide

### For Complete Walkthrough:
👉 **[START_TO_FINISH_GUIDE.md](START_TO_FINISH_GUIDE.md)** - Detailed step-by-step guide

### For Testing Everything:
👉 **[WALKTHROUGH_ALL_TESTS.md](WALKTHROUGH_ALL_TESTS.md)** - Complete testing guide

### For Understanding Architecture:
👉 **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design & architecture

### For Migration from IBKR:
👉 **[MIGRATION_GUIDE_IBKR_TO_V2.md](MIGRATION_GUIDE_IBKR_TO_V2.md)** - Step-by-step migration

### For Understanding What Changed:
👉 **[CLEANUP_SUMMARY.md](CLEANUP_SUMMARY.md)** - What was built & organized

---

## 🎯 What's New in v2?

### ✅ No More IBKR Dependency
- System runs **completely independently**
- IBKR is now optional (deprecated)
- Multiple data providers available

### ✅ Professional Paper Trading
- Realistic futures engine (SPAN-like margin)
- Options engine (Greeks-based risk)
- Realistic fill simulation (slippage, delays)

### ✅ Multiple Data Providers
- Polygon.io (recommended)
- Tradier (options-focused)
- Local Parquet storage
- CSV files supported

### ✅ Comprehensive Risk Engine
- Futures risk (SPAN-like)
- Options risk (Greeks-based)
- Portfolio-level aggregation

### ✅ Immutable Trade Ledger
- SQLite-based audit trail
- ACID guarantees
- Complete trade history

### ✅ Mirror Trading Support
- Manual fill interface
- Position synchronization
- Prop firm integration ready

---

## 🔧 System Overview

```
┌─────────────────────────────────────┐
│     Data Providers (Multiple)       │
│  Polygon │ Tradier │ Local Parquet  │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│      Paper Trading Engines          │
│   Futures Engine │ Options Engine   │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│      Risk Engine v2                 │
│  Futures │ Options │ Portfolio      │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│      Trade Ledger (SQLite)          │
│      Immutable Audit Trail          │
└─────────────────────────────────────┘
```

---

## 📋 Quick Checklist

- [ ] System installed (`pip install -e .`)
- [ ] Quick test passed (`python scripts/test_new_system.py`)
- [ ] Read QUICK_START_V2.md
- [ ] (Optional) Configure API keys in `.env`
- [ ] (Optional) Download historical data
- [ ] Start using paper broker!

---

## 🚨 Important Notes

### IBKR is Now Optional
- IBKR broker/data provider still exists but is deprecated
- System runs fine without IBKR
- See `IBKR_DEPRECATION_NOTICE.md` for details

### Default Broker is "paper"
- System defaults to paper trading
- No external connections required
- Perfect for backtesting and development

### API Keys Optional
- Can use local data only
- API keys needed for live data
- See data provider docs for details

---

## 📖 Next Steps

1. **Read Quick Start**: [QUICK_START_V2.md](QUICK_START_V2.md)
2. **Run Tests**: [WALKTHROUGH_ALL_TESTS.md](WALKTHROUGH_ALL_TESTS.md)
3. **Understand Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md)
4. **Start Trading**: Use paper broker in your strategies

---

## 🆘 Need Help?

1. **Quick Issues**: Check [QUICK_START_V2.md](QUICK_START_V2.md) troubleshooting section
2. **Detailed Guide**: See [START_TO_FINISH_GUIDE.md](START_TO_FINISH_GUIDE.md)
3. **Testing Issues**: See [WALKTHROUGH_ALL_TESTS.md](WALKTHROUGH_ALL_TESTS.md)
4. **Migration Help**: See [MIGRATION_GUIDE_IBKR_TO_V2.md](MIGRATION_GUIDE_IBKR_TO_V2.md)

---

## ✅ Success Criteria

You're ready when:

- ✅ Quick test passes (`python scripts/test_new_system.py`)
- ✅ You understand the new architecture
- ✅ You know how to use the paper broker
- ✅ You've configured your data providers (optional)

---

## 🎉 You're All Set!

Your PearlAlgo v2 system is:
- ✅ **Vendor-agnostic** - No single point of failure
- ✅ **Professional-grade** - Built like quant firms use
- ✅ **Fully tested** - Comprehensive test suite
- ✅ **Well documented** - Complete guides available
- ✅ **Production-ready** - Ready for real trading

**Happy Trading!** 🚀

---

*For detailed information, see the individual documentation files listed above.*




