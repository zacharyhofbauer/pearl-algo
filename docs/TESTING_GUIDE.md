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
python3 scripts/testing/test_all.py arch

# Architecture check with strict enforcement (fails on violations)
PEARLALGO_ARCH_ENFORCE=1 python3 scripts/testing/test_all.py arch
```

### Option 2: Multi-market smoke check
```bash
# Verify config + state isolation across NQ/ES/GC
python3 scripts/testing/smoke_multi_market.py
```

## ✅ Testing Principles (non-negotiable)

1. **No code duplication**: tests import production code from `src/pearlalgo/` directly.
2. **Development mode required**: install with `pip install -e .` so imports resolve.
3. **Mock external services**: IBKR/Telegram mocked; internal logic uses real code.
4. **Type safety**: Run mypy to catch type errors before runtime.

### Option 3: Automated Test Script
```bash
# Run unit tests (pytest)
./scripts/testing/run_tests.sh

# Or run pytest directly:
pytest tests/
```

### Option 4: Pearl AI prompt regression eval (fast, no API calls)
```bash
# Core golden suite (mock mode)
python3 -m pearlalgo.pearl_ai.eval.ci --mock

# Expanded suite
python3 -m pearlalgo.pearl_ai.eval.ci --dataset golden_expanded.json --mock

# Only run if prompt files changed (handy before committing)
python3 -m pearlalgo.pearl_ai.eval.ci --changed-only --mock
```

**Optional pre-commit hook (runs eval when prompt files are staged):**
```bash
ln -sf ../../scripts/pre-commit-eval.sh .git/hooks/pre-commit
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
  Buffer: 300 bars
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

**Expected:** Short signals may be generated, or signal count may vary based on confidence thresholds

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

# Run unit-only tests (by marker)
pytest tests/ -m unit -v
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
pytest tests/ -m integration -v
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
./scripts/gateway/gateway.sh status

# Check agent status
./scripts/ops/status.sh --market NQ
```

**Expected:**
- ✅ IB Gateway: RUNNING
- ✅ Agent: RUNNING
- ✅ Connection: CONNECTED

#### 2. Data Quality
Monitor logs for:
- Foreground mode: logs are printed in your terminal.
- systemd: `journalctl -u pearlalgo-mnq.service -f`
- Docker: `docker logs -f <container>`

**What to Check:**
- ✅ No connection errors
- ✅ Data is fresh (not stale)
- ✅ Buffer size is stable (300 bars)
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

#### 4. Dashboard Updates
Check Telegram for periodic dashboard updates (hourly by default):

**What to Verify:**
- ✅ Dashboard shows "RUNNING" status
- ✅ Market status (OPEN/CLOSED)
- ✅ Cycle count increases
- ✅ Buffer size is reasonable
- ✅ Error count is low (ideally 0)
- ✅ Connection status is "connected"
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
cat data/agent_state/NQ/state.json | jq

# Check performance metrics
cat data/agent_state/NQ/performance.json | jq
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

**Closing (15:30-15:45 ET):**
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

## 🏗️ Architecture Boundary Testing

The codebase enforces module boundary rules to maintain clean layering and prevent accidental coupling.
See `docs/PROJECT_SUMMARY.md` (Module Boundaries section) for the full dependency matrix.

### Quick Check (Warn-Only)

```bash
# Runs in warn-only mode (reports violations but doesn't fail)
python3 scripts/testing/test_all.py arch
```

### Strict Enforcement

```bash
# Fails (exit 1) if any boundary violations are found
PEARLALGO_ARCH_ENFORCE=1 python3 scripts/testing/test_all.py arch
```

### Direct Script Usage

```bash
# Warn-only (default)
python3 scripts/testing/check_architecture_boundaries.py

# Enforce mode
python3 scripts/testing/check_architecture_boundaries.py --enforce

# Verbose output (show all scanned files)
python3 scripts/testing/check_architecture_boundaries.py --verbose
```

### What It Checks

The boundary checker scans all Python files under `src/pearlalgo/` and verifies that:

- `utils/` does not import from `config`, `data_providers`, `trading_bots`, `execution`, `learning`, or `market_agent`
- `config/` does not import from `data_providers`, `trading_bots`, `execution`, `learning`, or `market_agent`
- `data_providers/` does not import from `trading_bots`, `execution`, `learning`, or `market_agent`
- `trading_bots/` does not import from `data_providers`, `execution`, `learning`, or `market_agent`
- `execution/` does not import from `data_providers`, `trading_bots`, `learning`, or `market_agent`
- `learning/` does not import from `data_providers`, `trading_bots`, `execution`, or `market_agent`
- `market_agent/` may import from any internal layer (it's the orchestration layer)

### When to Run

- **Before committing**: Run `python3 scripts/testing/test_all.py arch` to catch accidental cross-layer imports
- **In CI**: Set `PEARLALGO_ARCH_ENFORCE=1` to fail builds on violations
- **During code review**: Reviewers can run the check to verify architectural compliance

## 🔍 Type Checking with mypy

Static type checking catches type-related bugs before runtime. The project uses mypy for type validation.

### Quick Start

```bash
# Run type checking
mypy src/pearlalgo

# Run with verbose output
mypy src/pearlalgo --verbose

# Check specific module
mypy src/pearlalgo/market_agent/
```

### Configuration

mypy is configured via `mypy.ini` at the project root:

- **Python version**: 3.12
- **Mode**: Relaxed (warn, don't fail) - suitable for gradual adoption
- **External libraries**: Missing imports ignored for third-party libs without stubs

### What It Catches

| Bug Type | Example |
|----------|---------|
| None access | `signal.get("entry")["price"]` when signal could be None |
| Wrong return type | Function returns float but caller expects int |
| Missing dict key | `config["nonexistent_key"]` |
| Argument mismatch | Passing wrong number/types of arguments |

### CI Integration

mypy runs in CI as an informational check (continue-on-error). To enforce strictly:

```bash
# Local strict check
mypy src/pearlalgo --strict

# In CI, set continue-on-error: false to enforce
```

### Adding Type Annotations

When adding new code, include type hints:

```python
# Good
def calculate_position_size(
    confidence: float,
    risk_pct: float,
    account_balance: float,
) -> int:
    return int(confidence * risk_pct * account_balance)

# Avoid
def calculate_position_size(confidence, risk_pct, account_balance):
    return confidence * risk_pct * account_balance
```

### Common Fixes

**1. Optional types:**
```python
# Before (mypy error: Item "None" has no attribute "x")
def process(data):
    return data.value

# After
def process(data: Optional[Data]) -> int:
    if data is None:
        return 0
    return data.value
```

**2. Dict access:**
```python
# Before (mypy error: TypedDict has no key "foo")
config["foo"]

# After
config.get("foo", default_value)
```

---

## 🐛 Troubleshooting

### No Signals Generated

**Possible Causes:**
1. Market conditions don't meet thresholds
2. Filters are too strict
3. Data quality issues
4. Market is closed

**Solutions:**
1. Check strategy session window (default 18:00–15:45 ET, NY time)
2. Review confidence thresholds in `config.yaml`
3. Check data quality logs
4. Adjust filter parameters if needed

### Connection Errors

**Possible Causes:**
1. IB Gateway not running
2. Port 4002 not accessible
3. Network issues

**Solutions:**
1. Start IB Gateway: `./scripts/gateway/gateway.sh start`
2. Check port: `netstat -tlnp | grep 4002`
3. Verify connection: `./scripts/gateway/gateway.sh status`

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
1. Check IB Gateway: `./scripts/gateway/gateway.sh status`
2. Install dependencies: `pip install -e .`
3. Check logs: foreground terminal output or `journalctl -u pearlalgo-mnq.service --since -10m`

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

## 🔧 Parameter Tuning Protocol

When adjusting strategy or service parameters in live operation, follow this bounded tuning protocol to avoid compounding changes and ensure accountability.

### Single-Change Rule

1. **One change at a time**: Only modify one parameter per tuning cycle.
2. **Document before changing**:
   - Parameter name and current value
   - Proposed new value
   - Rationale (why this change?)
   - Success metric (what will improvement look like?)
   - Rollback trigger (under what conditions will you revert?)
3. **Observation period**: Run for at least 1-2 full trading sessions before evaluating.
4. **Measure, don't assume**: Use `/performance`, `signals.jsonl`, or watchdog output to verify impact.

### Example Tuning Cycle

```
# Before
Parameter: signals.min_confidence
Current: 0.50
Proposed: 0.55
Rationale: Too many low-quality signals; want to filter more aggressively
Success metric: Fewer signals per day (target: 20% reduction) with same or better win rate
Rollback trigger: Win rate drops below 45% OR signal count drops to zero for 2 consecutive sessions

# After observation
Result: Signal count reduced by 25%, win rate improved from 52% to 58%
Decision: Keep change
```

### Parameters Safe for Bounded Tuning

| Parameter | Location | Safe Range | Notes |
|-----------|----------|------------|-------|
| `signals.min_confidence` | config.yaml | 0.40 – 0.70 | Higher = fewer signals |
| `signals.min_risk_reward` | config.yaml | 1.2 – 2.5 | Higher = stricter R:R filter |
| `service.status_update_interval` | config.yaml | 300 – 3600 | Dashboard frequency (seconds) |
| `data.stale_data_threshold_minutes` | config.yaml | 5 – 30 | Staleness alert threshold |
| `circuit_breaker.max_consecutive_errors` | config.yaml | 5 – 20 | Circuit breaker sensitivity |

### Parameters Requiring Extra Caution

- `timeframe`: Changes affect buffer sizes, MTF alignment, and indicator calculations.
- `session.start_time` / `session.end_time`: Affects when signals are generated.
- `risk.*` parameters: Directly impact position sizing and stop/target placement.
- `virtual_pnl.intrabar_tiebreak`: Affects signal grading (conservative vs optimistic).

### Anti-Patterns to Avoid

- **Stacking changes**: Don't tune multiple parameters simultaneously.
- **Premature optimization**: Wait for statistically significant sample (minimum 20-30 trades).
- **Overfitting to recent data**: A good week doesn't justify aggressive changes.
- **Ignoring rollback triggers**: If the trigger condition is met, revert immediately.

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

# Unit tests
pytest tests/ -v

# Integration tests
pytest tests/ -m integration -v

# Architecture boundary check (warn-only)
python3 scripts/testing/test_all.py arch

# Architecture boundary check (strict enforcement)
PEARLALGO_ARCH_ENFORCE=1 python3 scripts/testing/test_all.py arch

# Check status
./scripts/ops/status.sh --market NQ

# Multi-market smoke check
python3 scripts/testing/smoke_multi_market.py
```

### Key Files
- `scripts/testing/test_all.py` - Unified test runner
- `scripts/testing/check_architecture_boundaries.py` - Module boundary enforcement
- `scripts/testing/smoke_multi_market.py` - Multi-market config + state smoke
- `scripts/testing/smoke_test_ibkr.py` - IBKR connectivity smoke
- `scripts/testing/check_no_secrets.py` - Secret detection guardrail
- `scripts/testing/check_doc_references.py` - Doc path/reference audit
- `tests/test_edge_cases.py` - Edge-case coverage (market hours/data quality/service)
- `tests/test_error_recovery.py` - Circuit breaker and recovery behaviors
- `tests/test_service_pause.py` - Service pause: connection failures, consecutive errors, data fetch backoff, manual pause/resume, counter reset, edge cases
- `tests/mock_data_provider.py` - Mock data provider
- Service logs are emitted to stdout/stderr (terminal output, systemd journal, or Docker logs)
- `data/agent_state/<MARKET>/state.json` - Service state

### Key Metrics
- **Cycles:** Number of analysis cycles completed
- **Signals:** Number of trading signals generated
- **Errors:** Number of errors encountered
- **Buffer:** Size of data buffer (bars)
- **Connection Status:** IB Gateway connection state

---

## 📊 Test Coverage and Gaps

This section summarizes the current test coverage and highlights areas for future expansion.

### Existing Tests

#### Unified Test Runner (`scripts/testing/test_all.py`)

**Modes:**
- `all` – runs all integrated tests
- `telegram` – runs `test_telegram_notifications()`
- `signals` – runs `test_signal_generation()` with `MockDataProvider`
- `service` – runs service‑level tests with mock data

**Exercises:**
- Telegram notifier formatting and sending
- Strategy signal generation with mock data
- NQ Agent service with mock provider

#### Tests under `scripts/testing/`

- `smoke_test_ibkr.py` – IBKR connectivity smoke test
- `smoke_multi_market.py` – multi-market config + state isolation smoke test
- `check_no_secrets.py` – secret detection guardrail
- `check_doc_references.py` – documentation path reference audit

#### Tests under `tests/`

- `mock_data_provider.py` – common mock provider for unit/integration tests
- `test_base_cache.py` – base historical caching behavior (cache hits, buffer shape, timestamp extraction)
- `test_config_wiring.py` – config propagation from `config.yaml` to `MarketAgentService` and `MarketAgentDataFetcher`
- `test_edge_cases.py` – focused edge-case tests (no-data fetch + short-run service lifecycle)
- `test_error_recovery.py` – circuit-breaker behavior (connection-failure pause) using a stub provider
- `test_service_pause.py` – comprehensive service pause/resume tests: connection failure pause, consecutive errors pause, data fetch errors (backoff only, not pause), counter reset on success, manual pause/resume, status reflects circuit breaker state, edge cases for thresholds
- `test_signal_generation_edge_cases.py` – edge cases for signal generation (NaN, inf, extreme prices, malformed data)
- `test_service_core.py` – 20 targeted tests for the 5 highest-risk service.py methods (VirtualTradeManager, save_state, init, connection failure, stop)
- `test_tradovate_client.py` – 22 tests for Tradovate REST/WebSocket client with mocked HTTP responses (auth, token refresh, error handling, rate limiting)
- `test_ibkr_adapter_unit.py` – 10 tests for IBKR adapter with mocked ib_insync (order placement, position management, error handling, fills)
- `test_signal_pipeline_integration.py` – signal pipeline integration tests, including 5 execution scenarios (adapter called, ML filter rejects, circuit breaker blocks, execution succeeds)

#### Web app tests under `pearlalgo_web_app/__tests__/`

- `middleware.test.ts` – 22 tests for Next.js authentication middleware (auth bypass, session validation, redirects)
- `useWebSocket.test.ts` – 32 tests for WebSocket hook (connection, reconnection, message parsing, cleanup)
- `login-actions.test.ts` – 20 tests for login/logout flow (credentials, cookies, session management)

### Observed Gaps

These gaps are **observational only** and do not change behavior.

1. **Market hours edge cases** (`test_edge_cases.py`)
   - DST transitions are covered (see `test_dst_transitions.py`), but full CME holiday/early-close calendar behavior is not yet comprehensively tested.

2. **Circuit breaker thresholds** (`test_error_recovery.py`, `test_service_pause.py`)
   - Connection-failure pause, consecutive errors pause, data-fetch backoff, manual pause/resume, and counter reset are now tested via `test_service_pause.py`. Edge cases for threshold boundaries are also covered.

3. **IBKR connectivity and fallback behavior**
   - `smoke_test_ibkr.py` tests basic connectivity. `test_ibkr_adapter_unit.py` now covers adapter-level order placement, position management, and error handling with mocked ib_insync. Detailed reconnection/staleness recovery paths could use further expansion.

4. **Command handler behavior**
   - The Telegram command handler (`telegram_command_handler.py`) is exercised indirectly via manual testing. The handler now uses 6 mixin base classes for code organization, but individual command flow tests are not yet automated.

### Recently Resolved Gaps

The following gaps have been addressed with explicit test coverage:

1. **Configuration wiring** (`test_config_wiring.py`)
   - Tests verify that values from `config/config.yaml` and `Settings` correctly propagate into `MarketAgentService` (intervals, thresholds, flags) and `MarketAgentDataFetcher` (buffer sizes, cache settings).

2. **Volume profile edge cases** (`test_signal_generation_edge_cases.py`)
   - The previously-xfail test for `inf` values is now passing. `VolumeProfile.calculate_profile()` sanitizes non-finite values before computing buckets.

3. **Base historical cache** (`test_base_cache.py`)
   - Tests validate cache hit behavior, dataframe shape consistency (no column accumulation), and historical fallback timestamp extraction from both index-based and column-based dataframes.

4. **Service core methods** (`test_service_core.py`)
   - 20 targeted tests covering VirtualTradeManager (TP/SL hit, tiebreak, empty data), save_state round-trips, service init with various configs, connection failure handling, and graceful shutdown.

5. **Execution clients** (`test_tradovate_client.py`, `test_ibkr_adapter_unit.py`)
   - 32 tests covering Tradovate REST/WebSocket client (auth, token refresh, order placement, error codes, rate limiting) and IBKR adapter (bracket orders, positions, fills, disconnect handling).

6. **Signal-to-execution pipeline** (`test_signal_pipeline_integration.py`)
   - Extended with 5 scenarios: execution adapter integration, ML filter rejection, circuit breaker blocking, and full success path with state verification.

7. **Web app auth and real-time** (`middleware.test.ts`, `useWebSocket.test.ts`, `login-actions.test.ts`)
   - 74 tests covering Next.js authentication middleware, WebSocket hook (connection/reconnection/cleanup), and login/logout flow (credentials, session cookies, open-redirect prevention).

8. **Circuit breaker / service pause** (`test_service_pause.py`)
   - Comprehensive tests for connection failure pause, consecutive errors pause, data fetch errors (backoff only, not pause), counter reset on success, manual pause/resume, status reflects circuit breaker state, and edge cases for thresholds. Replaces the former `test_circuit_breaker.py`.

### Suggested Future Tests

1. **Settings/IBKR normalization tests**
   - Unit tests for `get_settings()` and env normalization paths, ensuring `IBKR_*` and `PEARLALGO_IB_*` precedence behaves as documented.

2. **Circuit breaker integration tests**
   - Controlled tests that simulate repeated errors through a stub data provider and assert:
     - `connection_failures` threshold triggers pause
     - consecutive error pause triggers when strategy/processing raises repeatedly
     - data-fetch error backoff behavior activates at `max_data_fetch_errors`
     - Telegram circuit‑breaker alerts are sent (using a mock notifier).

3. **Command handler tests**
   - Async tests for `TelegramCommandHandler` that mock Telegram `Update` objects and verify:
     - `/status` returns correctly formatted status and buttons
     - `/signals` and `/performance` read from state/performance files and render expected output
     - Unauthorized chat IDs are rejected.

4. **Market hours / data quality edge cases**
   - Add DST/holiday tests using mocked `market_hours` and timestamped data frames (no placeholders).

### Tests Potentially Safe to Refine

- Existing tests can be expanded to cover additional circuit breaker paths and market-hours corner cases.
- No tests are currently marked for deletion; all files remain part of the suite as of this audit.

---

## 📚 Additional Resources

- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Complete system reference
- **[MARKET_AGENT_GUIDE.md](MARKET_AGENT_GUIDE.md)** - Operational guide
- **[GATEWAY.md](GATEWAY.md)** - IBKR Gateway setup
- **[MOCK_DATA_WARNING.md](MOCK_DATA_WARNING.md)** - Mock data limitations

---

**Remember:** Testing is an ongoing process. Regularly validate your strategy's performance and adjust parameters as needed based on real-world results.
