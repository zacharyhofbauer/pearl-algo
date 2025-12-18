# Testing Guide

**Complete guide to testing the NQ Agent system**

This guide covers testing procedures from quick validation to comprehensive strategy testing and performance validation.

---

## 📋 Table of Contents

1. [Quick Start](#-quick-start)
2. [Testing Levels](#-testing-levels)
3. [Level 1: Quick Validation](#-level-1-quick-validation)
4. [Level 2: Signal Quality Testing](#-level-2-signal-quality-testing)
5. [Level 3: Integration Testing](#-level-3-integration-testing)
6. [Level 4: Live Data Validation](#-level-4-live-data-validation)
7. [Level 5: Performance Validation](#-level-5-performance-validation)
8. [Mock Data Provider](#-mock-data-provider)
9. [Troubleshooting](#-troubleshooting)
10. [Testing Best Practices](#-testing-best-practices)

---

## 🚀 Quick Start

### Option 1: Unified Test Runner (Recommended)
```bash
# Run all tests
python3 scripts/testing/test_all.py

# Run specific test mode
python3 scripts/testing/test_all.py telegram
python3 scripts/testing/test_all.py signals
python3 scripts/testing/test_all.py service
```

### Option 2: Comprehensive Validation
```bash
# Run complete validation suite
python3 scripts/testing/validate_strategy.py
```

### Option 3: Automated Test Script
```bash
# Run all unit tests
./scripts/testing/run_tests.sh
```

---

## 🎯 Testing Levels

### Level 1: Quick Validation (5 minutes)
**Purpose:** Verify basic functionality works

### Level 2: Signal Quality Testing (15 minutes)
**Purpose:** Validate signal generation logic and quality

### Level 3: Integration Testing (30 minutes)
**Purpose:** Test full service with mock data

### Level 4: Live Data Validation (Ongoing)
**Purpose:** Monitor strategy with real market data

### Level 5: Performance Validation (Days/Weeks)
**Purpose:** Track actual trading performance

---

## 📋 Level 1: Quick Validation

### Test 1: Signal Generation Logic
**Time:** 30 seconds  
**Command:**
```bash
python3 scripts/testing/test_all.py signals
```

**What to Check:**
- ✅ Script runs without errors
- ✅ Mock data is generated
- ✅ Strategy analysis completes
- ✅ Signals may or may not be generated (depends on conditions)

**Expected Output:**
```
Signal Generation Test with Mock Data
============================================================

Creating mock data provider...
✅ Mock data provider created

Generating historical data...
✅ Generated 120 bars

✅ Latest bar: $17500.25

Creating strategy...
✅ Strategy created

Generating signals...
✅ Generated 1 signal(s)
```

**If No Signals Generated:**
- This is normal - signals require specific market conditions
- Try increasing volatility or trend in the mock data
- Signals are filtered by quality thresholds

### Test 2: Telegram Notifications
**Time:** 1 minute  
**Command:**
```bash
python3 scripts/testing/test_all.py telegram
```

**What to Check:**
- ✅ All notification types are sent
- ✅ Messages appear in Telegram
- ✅ Formatting looks correct
- ✅ No errors in output

**Expected:** 10 different notification types sent to Telegram

### Test 3: Full Service Test
**Time:** 2 minutes  
**Command:**
```bash
python3 scripts/testing/test_all.py service
```

**What to Check:**
- ✅ Service starts successfully
- ✅ Startup notification received
- ✅ Status updates appear
- ✅ Service runs without crashes
- ✅ Shutdown notification received

**Expected Output:**
```
Service statistics:
  Cycles: 24
  Signals: 0-2 (depends on conditions)
  Errors: 0
  Buffer: 100 bars
```

---

## 🔍 Level 2: Signal Quality Testing

### Test Signal Generation with Different Market Conditions

#### Test Uptrend Scenario
```python
# Edit scripts/testing/test_all.py or create custom test
mock_provider = MockDataProvider(
    base_price=17500.0,
    volatility=50.0,
    trend=2.0,  # Strong uptrend
)
```

**Expected:** Momentum long signals should be generated

#### Test Downtrend Scenario
```python
mock_provider = MockDataProvider(
    base_price=17500.0,
    volatility=50.0,
    trend=-2.0,  # Downtrend
)
```

**Expected:** Fewer or no long signals (strategy is long-only)

#### Test High Volatility
```python
mock_provider = MockDataProvider(
    base_price=17500.0,
    volatility=150.0,  # High volatility
    trend=0.0,
)
```

**Expected:** Breakout signals may be generated

#### Test Low Volatility
```python
mock_provider = MockDataProvider(
    base_price=17500.0,
    volatility=10.0,  # Low volatility
    trend=0.0,
)
```

**Expected:** Fewer signals (volatility threshold may filter them)

### Validate Signal Quality Metrics

Run the signal generation test and check:

1. **Confidence Scores**
   - Should be between 0.50 and 1.0
   - Higher is better
   - Signals below 0.50 are filtered out (configurable in `config.yaml`)

2. **Risk/Reward Ratios**
   - Should be at least 1.5:1 (configurable)
   - Check: `(take_profit - entry) / (entry - stop_loss) >= 1.5`

3. **Stop Loss Placement**
   - Should be below entry for long signals
   - Should use ATR-based calculation
   - Should not be too tight or too wide

4. **Take Profit Targets**
   - Should be above entry for long signals
   - Should respect risk/reward ratio
   - Should be realistic (not too far)

### Run Unit Tests
```bash
# Run all unit tests
pytest tests/ -v

# Run signal-specific tests
pytest tests/test_nq_agent_signals.py -v
```

**What to Check:**
- ✅ All tests pass
- ✅ Signal validation works correctly
- ✅ Confidence calculations are correct
- ✅ Risk/reward ratios meet thresholds

---

## 🔧 Level 3: Integration Testing

### Test Complete Service Flow

```bash
# Run integration tests
pytest tests/test_nq_agent_integration.py -v
```

**What to Check:**
- ✅ Service starts and stops gracefully
- ✅ Data fetching works
- ✅ Signal generation works
- ✅ State management works
- ✅ Error handling works

### Test with Extended Mock Data

Run the unified test runner for longer:
```bash
# Edit scripts/testing/test_all.py to increase timeout
# Or run service directly with longer timeout
python3 scripts/testing/test_all.py service
```

**What to Monitor:**
- Number of cycles completed
- Number of signals generated
- Error rate (should be 0)
- Buffer size (should be stable)
- Telegram notifications received

---

## 📊 Level 4: Live Data Validation

### Prerequisites
1. IB Gateway running and connected
2. Agent service running
3. Telegram notifications enabled

### Validation Checklist

#### 1. Connection Status
```bash
# Check IB Gateway
./scripts/gateway/check_gateway_status.sh

# Check agent status
./scripts/lifecycle/check_nq_agent_status.sh
```

**Expected:**
- ✅ IB Gateway: RUNNING
- ✅ Agent: RUNNING
- ✅ Connection: CONNECTED

#### 2. Data Quality
Monitor logs for:
```bash
tail -f logs/nq_agent.log
```

**What to Check:**
- ✅ No connection errors
- ✅ Data is fresh (not stale)
- ✅ Buffer size is stable (50-100 bars)
- ✅ No data quality alerts

**Red Flags:**
- ❌ "ConnectionRefusedError" - IB Gateway not running
- ❌ "Data is stale" warnings - Connection issues
- ❌ "No market data available" - Data fetch failures

#### 3. Signal Generation During Market Hours

**When to Test:**
- During market hours (9:30 AM - 4:00 PM ET)
- During active trading periods (avoid lunch lull)

**What to Monitor:**
- Telegram for signal notifications
- Logs for signal generation
- Status updates showing signal count

**Expected Behavior:**
- Signals may or may not be generated (depends on market conditions)
- If signals are generated, they should have:
  - Confidence >= 50%
  - Valid entry/stop/target prices
  - Risk/reward >= 1.5:1

#### 4. Status Updates
Check Telegram for periodic status updates (every 30 minutes):

**What to Verify:**
- ✅ Status shows "RUNNING"
- ✅ Market status (OPEN/CLOSED)
- ✅ Cycle count increases
- ✅ Buffer size is reasonable
- ✅ Error count is low (ideally 0)
- ✅ Connection status is "connected"

#### 5. Heartbeat Messages
Check Telegram for heartbeat messages (every hour):

**What to Verify:**
- ✅ Heartbeats arrive on schedule
- ✅ Uptime increases correctly
- ✅ Activity metrics are reasonable

---

## 📈 Level 5: Performance Validation

### Track Key Metrics

#### 1. Signal Generation Rate
**Monitor:** Number of signals per day/week

**Expected:**
- 0-10 signals per day (depends on market conditions)
- Higher during volatile periods
- Lower during ranging markets

**Red Flags:**
- 0 signals for multiple days (check filters/thresholds)
- Too many signals (>20/day) - filters may be too loose

#### 2. Signal Quality Metrics

Track in performance tracker:
- **Win Rate:** Should be > 50% for profitable strategy
- **Average R:R:** Should be > 1.5:1
- **Average Hold Time:** Should be reasonable for intraday (15-60 min)

#### 3. Risk Metrics

Monitor:
- **Max Drawdown:** Should stay within limits
- **Risk per Trade:** Should respect max_risk_per_trade config
- **Consecutive Losses:** Should not exceed thresholds

### Performance Dashboard

Check performance metrics via Telegram weekly summary or state file:

```bash
# Check state file
cat data/nq_agent_state/state.json | jq

# Check performance metrics
cat data/nq_agent_state/performance.json | jq
```

**Key Metrics to Track:**
- Total signals generated
- Signals exited (completed trades)
- Win rate
- Total P&L
- Average P&L per trade
- Average hold time

---

## 🧪 Advanced Testing Scenarios

### Test 1: Market Regime Detection
Verify strategy adapts to different market regimes:

**Ranging Market:**
- Should favor mean reversion signals
- Momentum signals should be filtered

**Trending Market:**
- Should favor momentum signals
- Mean reversion signals should be filtered

**High Volatility:**
- Should use wider stops
- Should favor breakout signals

**Low Volatility:**
- Should use tighter stops
- Should filter low-quality signals

### Test 2: Multi-Timeframe Analysis
Verify MTF alignment works:

**Aligned (1m/5m/15m all bullish):**
- Should boost confidence
- Should generate more signals

**Conflicting (1m bullish, 15m bearish):**
- Should reduce confidence
- Should filter signals

### Test 3: VWAP Integration
Verify VWAP-based adjustments:

**Price Above VWAP:**
- Long signals should have higher confidence
- Short signals should be filtered

**Price Below VWAP:**
- Long signals should have lower confidence
- Mean reversion signals may be favored

### Test 4: Session-Based Filtering
Verify session filters work:

**Opening (9:30-10:00 ET):**
- High volatility expected
- Momentum signals may be filtered

**Lunch Lull (11:30-13:00 ET):**
- Momentum signals should be disabled
- Mean reversion may be favored

**Closing (15:30-16:00 ET):**
- Reversal signals may be favored
- Tight stops recommended

---

## 🧪 Mock Data Provider

The `tests/mock_data_provider.py` provides **synthetic** OHLCV data for testing.

**What mock data is good for:**
- Fast, repeatable tests without market hours
- Controlled scenarios (uptrend, downtrend, high/low volatility)
- Verifying that strategy logic, data pipelines, and notifications work end‑to‑end

**What mock data is *not* good for:**
- Real market performance evaluation
- Live trading decisions
- Realistic risk metrics

Always validate strategy performance with **real market data** (IB Gateway + NQ Agent service) before using in production.

---

## 🐛 Troubleshooting

### No Signals Generated

**Possible Causes:**
1. Market conditions don't meet thresholds
2. Filters are too strict
3. Data quality issues
4. Market is closed

**Solutions:**
1. Check market hours (09:30-16:00 ET)
2. Review confidence thresholds in `config.yaml`
3. Check data quality logs
4. Adjust filter parameters if needed

### Connection Errors

**Possible Causes:**
1. IB Gateway not running
2. Port 4002 not accessible
3. Network issues

**Solutions:**
1. Start IB Gateway: `./scripts/gateway/start_ibgateway_ibc.sh`
2. Check port: `netstat -tlnp | grep 4002`
3. Verify connection: `./scripts/gateway/check_gateway_status.sh`

### Telegram Notifications Not Working

**Possible Causes:**
1. Missing credentials
2. Invalid bot token
3. Chat ID incorrect

**Solutions:**
1. Check env vars: `echo $TELEGRAM_BOT_TOKEN`
2. Test connection: `python3 scripts/testing/test_all.py telegram`
3. Verify bot is started in Telegram

### Service Won't Start

**Possible Causes:**
1. IB Gateway not running
2. Missing dependencies
3. Configuration errors

**Solutions:**
1. Check IB Gateway: `./scripts/gateway/check_gateway_status.sh`
2. Install dependencies: `pip install -e .`
3. Check logs: `tail -50 logs/nq_agent.log`

### ModuleNotFoundError

**Problem:** `ModuleNotFoundError: No module named 'pearlalgo'` or `'pandas'`

**Solutions:**
1. Activate virtual environment: `source .venv/bin/activate`
2. Install package: `pip install -e .`
3. Or use automated script: `./scripts/testing/run_tests.sh`

---

## ✅ Validation Checklist

### Before Going Live

- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Signal generation works with mock data
- [ ] Telegram notifications work
- [ ] IB Gateway connection works
- [ ] Data fetching works
- [ ] Status updates work
- [ ] Error handling works
- [ ] Circuit breaker works
- [ ] State management works

### During Live Operation

- [ ] Monitor logs daily
- [ ] Check Telegram notifications
- [ ] Verify signal quality
- [ ] Track performance metrics
- [ ] Monitor error rates
- [ ] Check connection status
- [ ] Review status updates
- [ ] Validate risk metrics

### Weekly Review

- [ ] Review signal generation rate
- [ ] Analyze signal quality
- [ ] Check performance metrics
- [ ] Review error logs
- [ ] Validate risk management
- [ ] Adjust parameters if needed

---

## 📝 Testing Best Practices

1. **Test Before Deploying**
   - Always run tests before making changes
   - Test with mock data first
   - Validate with live data before trusting signals

2. **Monitor Continuously**
   - Check logs regularly
   - Monitor Telegram notifications
   - Track performance metrics

3. **Validate Signal Quality**
   - Review each signal's confidence
   - Check risk/reward ratios
   - Verify stop/target placement

4. **Test Edge Cases**
   - Market closed scenarios
   - Connection failures
   - Data quality issues
   - High volatility periods

5. **Document Results**
   - Keep test logs
   - Track performance over time
   - Note any issues or improvements

---

## 🎯 Quick Reference

### Test Commands
```bash
# Unified test runner (recommended)
python3 scripts/testing/test_all.py [mode]

# Comprehensive validation
python3 scripts/testing/validate_strategy.py

# Unit tests
pytest tests/ -v

# Integration tests
pytest tests/test_nq_agent_integration.py -v

# Check status
./scripts/lifecycle/check_nq_agent_status.sh
```

### Key Files
- `scripts/testing/test_all.py` - Unified test runner
- `scripts/testing/validate_strategy.py` - Comprehensive validation
- `tests/test_nq_agent_signals.py` - Signal unit tests
- `tests/test_nq_agent_integration.py` - Integration tests
- `tests/mock_data_provider.py` - Mock data provider
- `logs/nq_agent.log` - Service logs
- `data/nq_agent_state/state.json` - Service state

### Key Metrics
- **Cycles:** Number of analysis cycles completed
- **Signals:** Number of trading signals generated
- **Errors:** Number of errors encountered
- **Buffer:** Size of data buffer (bars)
- **Connection Status:** IB Gateway connection state

---

## 📚 Additional Resources

- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Complete system reference
- **[NQ_AGENT_GUIDE.md](NQ_AGENT_GUIDE.md)** - Operational guide
- **[GATEWAY.md](GATEWAY.md)** - IBKR Gateway setup
- **[MOCK_DATA_WARNING.md](MOCK_DATA_WARNING.md)** - Mock data limitations

---

**Remember:** Testing is an ongoing process. Regularly validate your strategy's performance and adjust parameters as needed based on real-world results.
