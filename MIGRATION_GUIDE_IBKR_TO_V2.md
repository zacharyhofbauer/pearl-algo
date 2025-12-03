# Migration Guide: IBKR to PearlAlgo v2

## Overview

This guide helps you migrate from IBKR-dependent PearlAlgo to the new vendor-agnostic PearlAlgo v2 architecture.

---

## What Changed

### ✅ New Capabilities

1. **Vendor-Agnostic Data Layer**
   - Multiple data providers (Polygon, Tradier, Local Parquet)
   - Automatic fallback between providers
   - No IBKR Gateway required

2. **Professional Paper Trading**
   - Realistic futures simulation
   - Options simulation with Greeks
   - Deterministic backtesting

3. **Enhanced Risk Management**
   - SPAN-like futures margin
   - Greeks-based options risk
   - Portfolio-level aggregation

4. **Complete Audit Trail**
   - SQLite trade ledger
   - Account snapshots
   - Performance metrics

5. **Mirror Trading Support**
   - Manual fill entry
   - PnL reconciliation
   - Position sync

### ⚠️ Breaking Changes

1. **IBKR is now optional** - System works without it
2. **Configuration format updated** - New `data_providers.yaml`
3. **Broker selection changed** - Use `paper` broker for internal simulation

---

## Migration Steps

### Step 1: Install New Dependencies

```bash
cd pearlalgo-dev-ai-agents
pip install -e .
```

New dependencies will be installed:
- `pyarrow>=14.0.0` - Parquet support
- `requests>=2.31.0` - Tradier API
- `py-vollib>=1.0.1` - Options pricing

### Step 2: Configure Data Providers

**Option A: Use Polygon.io (Recommended)**

1. Get API key from [polygon.io](https://polygon.io)
2. Add to `.env`:
   ```bash
   POLYGON_API_KEY=your_key_here
   ```

3. Update `config/data_providers.yaml`:
   ```yaml
   primary: "polygon"
   providers:
     polygon:
       enabled: true
       api_key: "${POLYGON_API_KEY}"
   ```

**Option B: Use Tradier (If you have trading account)**

1. Get API key from Tradier
2. Add to `.env`:
   ```bash
   TRADIER_API_KEY=your_key_here
   ```

3. Enable in `config/data_providers.yaml`:
   ```yaml
   providers:
     tradier:
       enabled: true
       api_key: "${TRADIER_API_KEY}"
   ```

**Option C: Use Local Data Only**

If you have historical data:
- Place CSV/Parquet files in `data/historical/`
- System will use `local_parquet` provider automatically

### Step 3: Download Historical Data

```bash
# Download historical data for backtesting
python scripts/download_historical_data.py \
    --symbols QQQ SPY AAPL \
    --provider polygon \
    --timeframe 15m \
    --start-date 2023-01-01
```

This creates Parquet files in `data/historical/` for deterministic backtesting.

### Step 4: Switch to Paper Broker

**Before (IBKR-dependent):**
```python
from pearlalgo.brokers.factory import get_broker

broker = get_broker("ibkr", portfolio=portfolio)
# Required IBKR Gateway running
```

**After (Vendor-agnostic):**
```python
from pearlalgo.brokers.factory import get_broker

broker = get_broker("paper", portfolio=portfolio)
# No external dependencies!
```

Or update `config/config.yaml`:
```yaml
broker:
  primary: "paper"  # Changed from "ibkr"
```

### Step 5: Update Data Provider Usage

**Before (IBKR data provider):**
```python
from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider

provider = IBKRDataProvider()
data = provider.fetch_historical("ES")
```

**After (Vendor-agnostic):**
```python
from pearlalgo.data_providers.factory import create_data_provider

provider = create_data_provider("polygon", api_key="your_key")
# Or use factory with automatic fallback
provider = create_data_provider_with_fallback(
    primary="polygon",
    fallbacks=["local_parquet", "local_csv"]
)
data = provider.fetch_historical("ES")
```

### Step 6: Update LangGraph Workflow (Optional)

The LangGraph workflow can now use paper broker:

```python
from pearlalgo.brokers.factory import get_broker
from pearlalgo.core.portfolio import Portfolio

# Create paper broker instead of IBKR
portfolio = Portfolio(cash=50000.0)
broker = get_broker("paper", portfolio=portfolio)

# Use in LangGraph workflow as before
```

### Step 7: Test Migration

1. **Test Data Access:**
   ```python
   from pearlalgo.data_providers.factory import create_data_provider
   
   provider = create_data_provider("polygon", api_key="your_key")
   data = provider.fetch_historical("QQQ", timeframe="15m")
   print(f"Retrieved {len(data)} rows")
   ```

2. **Test Paper Trading:**
   ```python
   from pearlalgo.brokers.paper_broker import PaperBroker
   from pearlalgo.core.portfolio import Portfolio
   from pearlalgo.core.events import OrderEvent
   from datetime import datetime
   
   portfolio = Portfolio(cash=50000.0)
   broker = PaperBroker(portfolio=portfolio)
   
   # Simulate price update
   broker.update_price("ES", price=4000.0)
   
   # Submit order
   order = OrderEvent(
       timestamp=datetime.now(),
       symbol="ES",
       side="BUY",
       quantity=1.0
   )
   order_id = broker.submit_order(order)
   print(f"Order {order_id} submitted")
   ```

3. **Run Existing Tests:**
   ```bash
   pytest tests/ -v
   ```

---

## Configuration Changes

### Old Configuration (IBKR-focused)

```yaml
broker:
  primary: "ibkr"
  ibkr:
    host: "${IBKR_HOST:-127.0.0.1}"
    port: "${IBKR_PORT:-4002}"
    # Required IBKR Gateway
```

### New Configuration (Vendor-agnostic)

```yaml
# config/config.yaml
broker:
  primary: "paper"  # or "alpaca", "bybit", etc.

# config/data_providers.yaml (NEW)
primary: "polygon"
providers:
  polygon:
    enabled: true
    api_key: "${POLYGON_API_KEY}"
  local_parquet:
    enabled: true
    root_dir: "data/historical"
```

---

## IBKR Cleanup (Optional)

### Keep IBKR for Backward Compatibility

IBKR broker/provider is still available but **optional**:
- Can be used if needed
- Not required for core functionality
- Can be removed gradually

### Remove IBKR Completely (If Desired)

1. **Remove IBKR checks from startup:**
   - System no longer requires IBKR Gateway
   - Can start without IBKR connection

2. **Archive IBKR-specific files:**
   ```bash
   mkdir -p legacy/ibkr
   mv scripts/debug_ibkr.py legacy/ibkr/
   # Keep ibkr_broker.py but mark as optional
   ```

3. **Update documentation:**
   - Mark IBKR as optional/deprecated
   - Update quick start guides

---

## Common Migration Issues

### Issue: "No data provider available"

**Solution:** Configure at least one data provider in `config/data_providers.yaml` or set environment variables.

### Issue: "IBKR Gateway connection failed"

**Solution:** This is now expected! System works without IBKR. Use paper broker instead.

### Issue: "Missing historical data"

**Solution:** Download historical data first:
```bash
python scripts/download_historical_data.py --symbols QQQ SPY --provider polygon
```

### Issue: "Options chains not available"

**Solution:** 
- Use Tradier provider for options (free with account)
- Or configure Polygon.io Developer tier ($99/mo)

---

## Rollback Plan

If you need to rollback to IBKR:

1. Set `broker.primary: "ibkr"` in config
2. Start IBKR Gateway as before
3. System will use IBKR as before

**However, the new architecture is recommended for:**
- Better reliability
- More flexibility
- Professional-grade features
- No external dependencies

---

## Benefits of v2

1. ✅ **No IBKR Gateway Required** - Start trading immediately
2. ✅ **Multiple Data Sources** - Automatic fallback
3. ✅ **Realistic Simulation** - Professional paper trading
4. ✅ **Complete Audit Trail** - SQLite ledger
5. ✅ **Deterministic Backtesting** - Reproducible results
6. ✅ **Mirror Trading** - Sync with prop firms
7. ✅ **Professional Risk** - SPAN-like calculations

---

## Support

For issues or questions:
1. Check `IMPLEMENTATION_COMPLETE.md` for system status
2. Review `ARCHITECTURE_V2.md` for architecture details
3. See test files in `tests/` for usage examples

---

## Timeline

- **Week 1:** Install dependencies, configure providers
- **Week 2:** Download historical data, test paper trading
- **Week 3:** Migrate workflows, test thoroughly
- **Week 4:** Production use, optional IBKR cleanup

**The migration is non-destructive - IBKR still works if needed!**

