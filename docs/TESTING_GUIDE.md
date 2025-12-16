# Testing Guide

## Quick Testing Without Live Data

This guide shows you how to test the NQ Agent system without waiting for live market data or market hours.

---

## 🧪 Test Scripts

### Quick Start (Recommended)

**Easiest way to run all tests:**
```bash
# This script handles environment setup automatically
./scripts/run_tests.sh
```

This script will:
- Activate virtual environment (if exists)
- Install package if needed
- Run all three test scripts

### 1. Test All Telegram Notifications

**Purpose:** Verify all notification types work correctly

**Command:**
```bash
# Make sure virtual environment is activated
source .venv/bin/activate  # if using venv
python3 scripts/test_telegram_notifications.py
```

**What it does:**
- Tests all 10 notification types:
  - Signal notifications
  - Heartbeat messages
  - Status updates
  - Data quality alerts
  - Startup/shutdown notifications
  - Performance summaries
  - Circuit breaker alerts
  - Recovery notifications

**Requirements:**
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` environment variables

**Expected output:**
- All notifications sent to Telegram
- Success/failure status for each test

---

### 2. Test Signal Generation

**Purpose:** Test signal generation logic with mock data

**Command:**
```bash
# Make sure virtual environment is activated
source .venv/bin/activate  # if using venv
python3 scripts/test_signal_generation.py
```

**What it does:**
- Creates mock data provider
- Generates fake historical data
- Runs strategy analysis
- Shows generated signals (if any)

**Expected output:**
- Number of bars generated
- Latest bar price
- Number of signals generated
- Signal details (if any)

**Note:** May not generate signals if market conditions aren't met (this is normal)

---

### 3. Test Full Service with Mock Data

**Purpose:** Run the complete service with mock data for 2 minutes

**Command:**
```bash
# Make sure virtual environment is activated
source .venv/bin/activate  # if using venv
python3 scripts/test_nq_agent_with_mock.py
```

**What it does:**
- Creates mock data provider
- Starts NQ agent service
- Runs for 2 minutes (or until Ctrl+C)
- Sends all notifications to Telegram
- Shows service statistics

**Requirements:**
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (optional, but recommended)

**Expected output:**
- Startup notification in Telegram
- Heartbeat messages
- Status updates
- Signal notifications (if generated)
- Shutdown notification
- Service statistics

**To run longer:**
- Edit the script and change `timeout=120.0` to a longer value
- Or remove the timeout to run indefinitely

---

## 🔧 Mock Data Provider

The `tests/mock_data_provider.py` provides fake market data for testing.

**Features:**
- Generates realistic OHLCV data
- Configurable base price, volatility, and trend
- No external dependencies
- Fast and reliable

**Usage:**
```python
from tests.mock_data_provider import MockDataProvider

# Create provider
provider = MockDataProvider(
    base_price=15000.0,  # Starting price
    volatility=50.0,      # Price volatility
    trend=0.5,           # Price trend per bar
)

# Generate data
df = provider.fetch_historical("NQ", start, end, "1m")
latest_bar = await provider.get_latest_bar("NQ")
```

---

## 📋 Testing Checklist

### Quick Test (5 minutes)
- [ ] Run `test_telegram_notifications.py` - Verify all notifications work
- [ ] Check Telegram - All 10 notification types received

### Signal Generation Test (2 minutes)
- [ ] Run `test_signal_generation.py` - Verify signal logic works
- [ ] Review output - Check if signals are generated

### Full Service Test (2 minutes)
- [ ] Run `test_nq_agent_with_mock.py` - Test complete service
- [ ] Check Telegram - Startup, heartbeats, status updates
- [ ] Review statistics - Cycles, signals, errors

### Extended Test (Optional)
- [ ] Run service for longer period
- [ ] Test with different mock data parameters
- [ ] Verify all monitoring features work

---

## 🎯 Common Test Scenarios

### Test with Uptrend
```python
provider = MockDataProvider(
    base_price=15000.0,
    volatility=50.0,
    trend=1.0,  # Strong uptrend
)
```

### Test with Downtrend
```python
provider = MockDataProvider(
    base_price=15000.0,
    volatility=50.0,
    trend=-1.0,  # Downtrend
)
```

### Test with High Volatility
```python
provider = MockDataProvider(
    base_price=15000.0,
    volatility=100.0,  # High volatility
    trend=0.0,
)
```

### Test with Low Volatility
```python
provider = MockDataProvider(
    base_price=15000.0,
    volatility=10.0,  # Low volatility
    trend=0.0,
)
```

---

## 🐛 Troubleshooting

### No Signals Generated
**Problem:** `test_signal_generation.py` shows 0 signals

**Solutions:**
- Increase volatility: `volatility=100.0`
- Add trend: `trend=2.0`
- Generate more data: Increase time range
- This is normal - signals require specific conditions

### Telegram Notifications Not Working
**Problem:** Notifications not received

**Solutions:**
1. Check credentials: `echo $TELEGRAM_BOT_TOKEN`
2. Test connection: `python3 scripts/test_telegram.py`
3. Verify bot token and chat ID are correct
4. Make sure bot is started (send `/start` to bot first)

### Service Won't Start
**Problem:** `test_nq_agent_with_mock.py` fails to start

**Solutions:**
1. Activate virtual environment: `source .venv/bin/activate`
2. Install package: `pip install -e .`
3. Check Python environment: `python3 --version`
4. Check logs for errors
5. Use automated script: `./scripts/run_tests.sh`

### ModuleNotFoundError
**Problem:** `ModuleNotFoundError: No module named 'pearlalgo'` or `'pandas'`

**Solutions:**
1. **Activate virtual environment:**
   ```bash
   source .venv/bin/activate
   ```

2. **Install package in development mode:**
   ```bash
   pip install -e .
   ```

3. **Or use the automated test script:**
   ```bash
   ./scripts/run_tests.sh
   ```
   This handles setup automatically.

---

## 📊 Expected Results

### Notification Test
- ✅ All 10 notification types sent successfully
- ✅ Messages appear in Telegram
- ✅ Formatting looks correct

### Signal Generation Test
- ✅ Mock data generated successfully
- ✅ Strategy analysis completes
- ✅ Signals may or may not be generated (depends on conditions)

### Full Service Test
- ✅ Service starts successfully
- ✅ Startup notification received
- ✅ Heartbeat messages received (if running long enough)
- ✅ Status updates received
- ✅ Service stops gracefully
- ✅ Shutdown notification received

---

## 🚀 Quick Start Testing

**Fastest way to test everything:**

**Option 1: Automated (Recommended)**
```bash
# Run all tests with automatic setup
./scripts/run_tests.sh
```

**Option 2: Manual**
```bash
# Activate virtual environment first
source .venv/bin/activate

# 1. Test notifications (30 seconds)
python3 scripts/test_telegram_notifications.py

# 2. Test signal generation (10 seconds)
python3 scripts/test_signal_generation.py

# 3. Test full service (2 minutes)
python3 scripts/test_nq_agent_with_mock.py
```

**Total time: ~3 minutes**

**Note:** If you get `ModuleNotFoundError`, make sure to:
1. Activate virtual environment: `source .venv/bin/activate`
2. Install package: `pip install -e .`
3. Or use the automated script: `./scripts/run_tests.sh`

All tests use mock data - no live market data or IBKR connection needed!

---

## 💡 Tips

1. **Run tests before deployment** - Catch issues early
2. **Test notifications regularly** - Ensure Telegram integration works
3. **Adjust mock parameters** - Test different market conditions
4. **Check Telegram** - Verify all message types look correct
5. **Review logs** - Check for any warnings or errors

---

## 📝 Notes

- All test scripts use **synthetic mock data** - no external dependencies
- Tests run quickly - no waiting for market hours
- Tests are deterministic - same inputs produce same outputs
- Tests can be run anytime - not limited to market hours
- Tests verify **functionality and logic** - NOT actual trading performance
- **Mock prices are fake** - do not represent real market data
- For real market testing, use IB Gateway with live data

⚠️ **Important:** See [Mock Data Warning](./MOCK_DATA_WARNING.md) for details on what these tests validate vs. what they don't.

---

## 🎯 Strategy Testing

For comprehensive strategy testing and validation, see:
- **[Strategy Testing Guide](./STRATEGY_TESTING_GUIDE.md)** - Complete guide to testing if your strategy is working

The strategy testing guide covers:
- Quick validation tests
- Signal quality testing
- Integration testing
- Live data validation
- Performance tracking
- Advanced testing scenarios

