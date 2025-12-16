# PearlAlgo Codebase Cleanup & Consolidation Plan

**Authoritative Reference**: `docs/PROJECT_SUMMARY.md`  
**Status**: Analysis Complete - Ready for Implementation  
**Date**: 2025-12-16

---

## Executive Summary

This plan identifies consolidation opportunities across Python modules, scripts, documentation, and configuration while preserving all functionality and maintaining the existing modular architecture. All recommendations follow the constraint: **do not change runtime behavior, do not remove features, do not collapse modular boundaries**.

---

## 1. Python Code Consolidation

### 1.1 Duplicated Logic Analysis

#### A. State Directory Initialization (DUPLICATED)

**Location**: Found in 4 files
- `src/pearlalgo/nq_agent/state_manager.py:36-40`
- `src/pearlalgo/nq_agent/performance_tracker.py:40-44`
- `src/pearlalgo/nq_agent/health_monitor.py:40`
- `src/pearlalgo/strategies/nq_intraday/signal_quality.py:46-49`

**Current Pattern**:
```python
if state_dir is None:
    state_dir = Path("data/nq_agent_state")
self.state_dir = Path(state_dir)
self.state_dir.mkdir(parents=True, exist_ok=True)
```

**Recommendation**: Extract to `src/pearlalgo/utils/paths.py`
- Create `ensure_state_dir(state_dir: Optional[Path] = None) -> Path` function
- All components use this utility
- **Why**: Single source of truth for state directory logic, easier to change default location

**Files to Modify**:
- `src/pearlalgo/utils/paths.py` (NEW)
- `src/pearlalgo/nq_agent/state_manager.py` (use utility)
- `src/pearlalgo/nq_agent/performance_tracker.py` (use utility)
- `src/pearlalgo/nq_agent/health_monitor.py` (use utility)
- `src/pearlalgo/strategies/nq_intraday/signal_quality.py` (use utility)

---

#### B. Error Handling Patterns (SIMILAR, NOT DUPLICATED)

**Location**: Multiple files with similar but context-specific patterns
- `service.py`: Circuit breaker logic (lines 79-84, 296-310)
- `data_fetcher.py`: Graceful degradation (lines 200-208)
- `ibkr_executor.py`: Connection retry logic (lines 521-566)
- `telegram_notifier.py`: Send retry logic (via `async_retry_with_backoff`)

**Analysis**: 
- Service has **circuit breaker** (pause after N errors) - **KEEP SEPARATE**
- Data fetcher has **graceful degradation** (return empty on error) - **KEEP SEPARATE**
- Executor has **connection retry** (exponential backoff) - **KEEP SEPARATE**
- Telegram uses **decorator retry** - **KEEP SEPARATE**

**Recommendation**: **NO CHANGE** - Each serves distinct purpose, different contexts

---

#### C. Signal File Path Logic (DUPLICATED)

**Location**: 
- `state_manager.py:42` → `self.signals_file = self.state_dir / "signals.jsonl"`
- `performance_tracker.py:46` → `self.signals_file = self.state_dir / "signals.jsonl"`
- `signal_quality.py:52` → `self.signals_file = self.state_dir / "signals.jsonl"`

**Recommendation**: Extract to `utils/paths.py`
- Create `get_signals_file(state_dir: Path) -> Path` function
- Create `get_state_file(state_dir: Path) -> Path` function
- Create `get_performance_file(state_dir: Path) -> Path` function

**Files to Modify**:
- `src/pearlalgo/utils/paths.py` (add functions)
- `src/pearlalgo/nq_agent/state_manager.py` (use utility)
- `src/pearlalgo/nq_agent/performance_tracker.py` (use utility)
- `src/pearlalgo/strategies/nq_intraday/signal_quality.py` (use utility)

---

#### D. Timestamp/ISO Format Conversion (DUPLICATED)

**Location**: Multiple files
- `state_manager.py:97` → `datetime.now(timezone.utc).isoformat()`
- `performance_tracker.py:65, 98, 129` → Multiple ISO conversions
- `service.py:101, 143, 359, 434` → Multiple ISO conversions
- `telegram_notifier.py`: Multiple timestamp handling

**Pattern Found**:
```python
datetime.now(timezone.utc).isoformat()
timestamp.replace("Z", "+00:00")
datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
```

**Recommendation**: Extract to `src/pearlalgo/utils/datetime_utils.py`
- `utc_now_iso() -> str` - Get current UTC as ISO string
- `parse_iso_timestamp(ts: str) -> datetime` - Parse ISO with Z handling
- `format_iso_timestamp(dt: datetime) -> str` - Format datetime to ISO

**Files to Modify**:
- `src/pearlalgo/utils/datetime_utils.py` (NEW)
- All files using timestamp conversion (use utilities)

---

#### E. Magic Numbers - Time Intervals (SHOULD BE CONFIGURED)

**Location**: `service.py` (lines 76-89)
```python
self.status_update_interval = 1800  # 30 minutes in seconds
self.heartbeat_interval = 3600  # 1 hour in seconds
self.connection_failure_alert_interval = 600  # 10 minutes
self.data_quality_alert_interval = 300  # 5 minutes
```

**Also Found**:
- `data_fetcher.py:68` → `timedelta(hours=2)` - Historical data window
- `data_fetcher.py:222-223` → `timedelta(hours=4)`, `timedelta(hours=12)` - MTF windows
- `signal_generator.py:49` → `300  # 5 minutes` - Duplicate signal window
- `service.py:258` → `1800  # 30 minutes` - Data staleness threshold
- `service.py:564` → `600  # 10 minutes` - Connection error window

**Recommendation**: Move to `NQIntradayConfig` class
- Add `service_intervals` section to config
- Load from `config.yaml` with sensible defaults
- **Why**: Centralized, configurable, documented in one place

**Files to Modify**:
- `src/pearlalgo/strategies/nq_intraday/config.py` (add intervals)
- `config/config.yaml` (add service_intervals section)
- `src/pearlalgo/nq_agent/service.py` (use config values)
- `src/pearlalgo/nq_agent/data_fetcher.py` (use config values)
- `src/pearlalgo/strategies/nq_intraday/signal_generator.py` (use config values)

---

#### F. Circuit Breaker Thresholds (SHOULD BE CONFIGURED)

**Location**: `service.py` (lines 79-84)
```python
self.max_consecutive_errors = 10  # Circuit breaker threshold
self.max_data_fetch_errors = 5
self.max_connection_failures = 10
```

**Recommendation**: Move to config
- Add to `config.yaml` under `service.circuit_breaker` section
- Load via `NQIntradayConfig`
- **Why**: Allows tuning without code changes, documented in config

**Files to Modify**:
- `config/config.yaml` (add circuit_breaker section)
- `src/pearlalgo/strategies/nq_intraday/config.py` (add properties)
- `src/pearlalgo/nq_agent/service.py` (use config values)

---

#### G. Buffer Sizes (SHOULD BE CONFIGURED)

**Location**:
- `data_fetcher.py:50` → `self._buffer_size = 100  # Keep last 100 bars`
- `data_fetcher.py:251, 253` → `tail(50)` for MTF buffers
- `performance_tracker.py:326` → `if len(performances) > 1000:`

**Recommendation**: Move to config
- Add `data.buffer_sizes` section to config
- Document prop-firm rationale (100 bars = ~1.5 hours of 1m data)

**Files to Modify**:
- `config/config.yaml` (add buffer_sizes)
- `src/pearlalgo/strategies/nq_intraday/config.py` (add properties)
- `src/pearlalgo/nq_agent/data_fetcher.py` (use config values)
- `src/pearlalgo/nq_agent/performance_tracker.py` (use config value)

---

### 1.2 Ownership Clarification

#### State Changes
**Current**: `state_manager.py` owns state persistence
- ✅ **CORRECT** - Keep as-is
- Service calls `state_manager.save_state()` - proper separation

#### Performance Tracking
**Current**: `performance_tracker.py` owns performance metrics
- ✅ **CORRECT** - Keep as-is
- Service calls `performance_tracker.track_*()` - proper separation

#### Error Handling
**Current**: Distributed by context
- `service.py` - Circuit breaker, error counting
- `data_fetcher.py` - Graceful degradation (returns empty)
- `ibkr_executor.py` - Connection retries
- `telegram_notifier.py` - Send retries (via decorator)
- ✅ **CORRECT** - Each handles errors appropriate to its context

#### Retry Logic
**Current**: 
- `utils/retry.py` - Generic async retry decorator
- `ibkr_executor.py` - Connection-specific retry with backoff
- ✅ **CORRECT** - Different retry strategies for different contexts

---

### 1.3 Method Signature Consistency

#### Data Provider Interface
**Current**: Mixed sync/async patterns
- `fetch_historical()` - sync, wrapped in executor
- `get_latest_bar()` - async in `IBKRProvider`, sync in base interface

**Recommendation**: **NO CHANGE** - Interface is correct, implementation handles async properly

#### Signal Processing
**Current**: Consistent across components
- `strategy.analyze(market_data)` → returns `List[Dict]`
- `signal_generator.generate(market_data)` → returns `List[Dict]`
- ✅ **CORRECT** - Keep as-is

---

### 1.4 Proposed New Utilities

#### `src/pearlalgo/utils/paths.py` (NEW)
```python
"""Path utilities for consistent file/directory handling."""

from pathlib import Path
from typing import Optional

DEFAULT_STATE_DIR = Path("data/nq_agent_state")

def ensure_state_dir(state_dir: Optional[Path] = None) -> Path:
    """Ensure state directory exists and return Path."""
    if state_dir is None:
        state_dir = DEFAULT_STATE_DIR
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    return state_path

def get_signals_file(state_dir: Path) -> Path:
    """Get signals.jsonl file path."""
    return state_dir / "signals.jsonl"

def get_state_file(state_dir: Path) -> Path:
    """Get state.json file path."""
    return state_dir / "state.json"

def get_performance_file(state_dir: Path) -> Path:
    """Get performance.json file path."""
    return state_dir / "performance.json"
```

#### `src/pearlalgo/utils/datetime_utils.py` (NEW)
```python
"""DateTime utilities for consistent timestamp handling."""

from datetime import datetime, timezone

def utc_now_iso() -> str:
    """Get current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()

def parse_iso_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp string, handling Z suffix."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def format_iso_timestamp(dt: datetime) -> str:
    """Format datetime to ISO string."""
    return dt.isoformat()
```

---

## 2. Script Rationalization

### 2.1 Current Script Inventory

**Lifecycle Scripts** (4):
- `start_nq_agent.sh` - Simple foreground start
- `start_nq_agent_service.sh` - Background start with PID management
- `stop_nq_agent_service.sh` - Stop service
- `check_nq_agent_status.sh` - Check service status

**Gateway Scripts** (5):
- `start_ibgateway.sh` - Start IB Gateway (legacy, uses xvfb)
- `start_ibgateway_ibc.sh` - Start IB Gateway with IBC (preferred)
- `check_gateway_status.sh` - Check Gateway status
- `configure_ibgateway_api.sh` - Configure API settings
- `configure_ibc_readonly.sh` - Configure IBC for read-only

**Setup Scripts** (2):
- `setup_ibgateway_readonly.sh` - Setup Gateway in read-only mode
- `setup_vnc_for_login.sh` - Setup VNC for Gateway login
- `disable_auto_sleep.sh` - Disable system sleep

**Testing Scripts** (4):
- `test_telegram_notifications.py` - Test all notification types
- `test_signal_generation.py` - Test signal logic
- `test_nq_agent_with_mock.py` - Test full service with mock data
- `run_tests.sh` - Run all test scripts
- `smoke_test_ibkr.py` - Quick IBKR connection test

**Validation Scripts** (1):
- `validate_strategy.py` - Comprehensive strategy validation

---

### 2.2 Consolidation Recommendations

#### A. Lifecycle Scripts - MERGE

**Current**:
- `start_nq_agent.sh` - Simple, no PID management
- `start_nq_agent_service.sh` - Full-featured with PID/logging

**Recommendation**: **KEEP BOTH, ADD DEPRECATION NOTICE**
- `start_nq_agent.sh` → Add comment: "For testing only. Use start_nq_agent_service.sh for production."
- `start_nq_agent_service.sh` → Mark as primary production script
- **Why**: Simple script useful for quick testing, production script has proper lifecycle management

**Action**: Add deprecation notice to `start_nq_agent.sh` header

---

#### B. Gateway Scripts - CONSOLIDATE

**Current**:
- `start_ibgateway.sh` - Legacy, uses xvfb directly
- `start_ibgateway_ibc.sh` - Preferred, uses IBC

**Recommendation**: **KEEP BOTH, DOCUMENT PREFERENCE**
- `start_ibgateway.sh` → Add comment: "Legacy method. Prefer start_ibgateway_ibc.sh"
- `start_ibgateway_ibc.sh` → Mark as preferred method
- **Why**: Legacy script may be needed for specific setups, IBC is preferred

**Action**: Update script headers with usage guidance

---

#### C. Testing Scripts - ORGANIZE

**Current**: Mix of Python scripts and shell script

**Recommendation**: **ORGANIZE INTO CATEGORIES**
- Keep all test scripts (they serve different purposes)
- Update `run_tests.sh` to clearly document what each test does
- Add test categories to script headers

**Action**: 
- Update script headers with category tags
- Update `run_tests.sh` with better documentation

---

#### D. Script Naming Consistency

**Current**: Mix of naming patterns
- `start_*.sh` - Lifecycle scripts
- `check_*.sh` - Status scripts
- `test_*.py` - Test scripts
- `validate_*.py` - Validation scripts
- `configure_*.sh` - Setup scripts

**Recommendation**: **NO CHANGE** - Naming is already consistent

---

### 2.3 Script Taxonomy (Final Structure)

```
scripts/
├── lifecycle/           # Service lifecycle (KEEP AS-IS)
│   ├── start_nq_agent.sh (testing only)
│   ├── start_nq_agent_service.sh (production)
│   ├── stop_nq_agent_service.sh
│   └── check_nq_agent_status.sh
│
├── gateway/             # IBKR Gateway management (KEEP AS-IS)
│   ├── start_ibgateway.sh (legacy)
│   ├── start_ibgateway_ibc.sh (preferred)
│   ├── check_gateway_status.sh
│   ├── configure_ibgateway_api.sh
│   └── configure_ibc_readonly.sh
│
├── setup/              # Initial setup (KEEP AS-IS)
│   ├── setup_ibgateway_readonly.sh
│   ├── setup_vnc_for_login.sh
│   └── disable_auto_sleep.sh
│
└── testing/            # Testing and validation (KEEP AS-IS)
    ├── test_telegram_notifications.py
    ├── test_signal_generation.py
    ├── test_nq_agent_with_mock.py
    ├── smoke_test_ibkr.py
    ├── validate_strategy.py
    └── run_tests.sh
```

**Recommendation**: **DO NOT REORGANIZE** - Current flat structure is fine, just add comments

**Action**: Add category comments to each script header

---

## 3. Documentation Cleanup and Unification

### 3.1 Current Documentation Structure

**Primary Docs**:
- `docs/PROJECT_SUMMARY.md` (983 lines) - **AUTHORITATIVE SOURCE**
- `docs/NQ_AGENT_GUIDE.md` (423 lines) - Operational guide
- `docs/TESTING_GUIDE.md` (354 lines) - Testing procedures
- `docs/STRATEGY_TESTING_GUIDE.md` - Strategy validation
- `docs/GATEWAY.md` - IBKR Gateway setup
- `docs/MOCK_DATA_WARNING.md` - Mock data notes

**Root Docs**:
- `README.md` - Quick start
- `TEST_SUMMARY.md` - Test status
- `CLEANUP_SUMMARY.md` - Cleanup notes
- `REAL_DATA_UPDATE_SUMMARY.md` - Real data changes
- `FINAL_TEST_SUMMARY.md` - Test summary
- `TEST_FIXES_COMPLETE.md` - Test fixes
- `TEST_EXECUTION_GUIDE.md` - Test execution
- `REAL_DATA_TESTING.md` - Real data testing

---

### 3.2 Redundancy Analysis

#### A. PROJECT_SUMMARY.md vs NQ_AGENT_GUIDE.md

**Overlap**:
- Both cover: Quick start, configuration, service management
- Both document: Prop firm settings, risk parameters
- Both explain: Telegram notifications, monitoring

**Recommendation**: **CLARIFY ROLES**
- `PROJECT_SUMMARY.md` → **Architecture & Reference** (keep comprehensive)
  - System architecture
  - Component descriptions
  - Data flows
  - Technology stack
  - Project structure
- `NQ_AGENT_GUIDE.md` → **Operational Guide** (keep focused)
  - How to run the service
  - Daily operations
  - Troubleshooting
  - Quick reference commands

**Action**: 
- Update `NQ_AGENT_GUIDE.md` to reference `PROJECT_SUMMARY.md` for architecture
- Remove duplicate architecture sections from `NQ_AGENT_GUIDE.md`
- Keep operational content in `NQ_AGENT_GUIDE.md`

---

#### B. TESTING_GUIDE.md vs STRATEGY_TESTING_GUIDE.md

**Overlap**:
- Both cover testing procedures
- Both mention test scripts

**Recommendation**: **MERGE INTO SINGLE GUIDE**
- `TESTING_GUIDE.md` → **Comprehensive Testing Guide**
  - Unit tests
  - Integration tests
  - Strategy validation
  - Test scripts
  - Mock data usage
- `STRATEGY_TESTING_GUIDE.md` → **DELETE** (merge content into TESTING_GUIDE.md)

**Action**: Merge strategy testing content into `TESTING_GUIDE.md`, delete `STRATEGY_TESTING_GUIDE.md`

---

#### C. Root-Level Summary Files

**Current**: Multiple summary files created during cleanup
- `TEST_SUMMARY.md`
- `CLEANUP_SUMMARY.md`
- `REAL_DATA_UPDATE_SUMMARY.md`
- `FINAL_TEST_SUMMARY.md`
- `TEST_FIXES_COMPLETE.md`
- `TEST_EXECUTION_GUIDE.md`
- `REAL_DATA_TESTING.md`

**Recommendation**: **CONSOLIDATE**
- Keep: `TEST_EXECUTION_GUIDE.md` (move to `docs/`)
- Delete: All other summary files (temporary cleanup artifacts)
- Update: `docs/TESTING_GUIDE.md` to include execution guide content

**Action**:
- Move `TEST_EXECUTION_GUIDE.md` → `docs/TEST_EXECUTION_GUIDE.md`
- Delete other summary files
- Update `docs/TESTING_GUIDE.md` with execution guide reference

---

### 3.3 Documentation Hierarchy (Final Structure)

```
docs/
├── PROJECT_SUMMARY.md          # AUTHORITATIVE - Architecture & reference
├── NQ_AGENT_GUIDE.md          # Operational guide (references PROJECT_SUMMARY)
├── TESTING_GUIDE.md           # Comprehensive testing (includes strategy validation)
├── TEST_EXECUTION_GUIDE.md    # Quick test execution reference
├── GATEWAY.md                 # IBKR Gateway setup (standalone)
└── MOCK_DATA_WARNING.md       # Mock data notes (standalone)
```

**Root Level**:
- `README.md` - Quick start (references docs/)

---

### 3.4 Terminology Normalization

**Issues Found**:
- "NQ" vs "MNQ" - Inconsistent usage
- "signal" vs "trading signal" - Inconsistent
- "prop firm" vs "prop-firm" - Inconsistent hyphenation

**Recommendation**: **STANDARDIZE**
- Use "MNQ" (not "NQ") when referring to the trading symbol
- Use "trading signal" (not just "signal") in user-facing docs
- Use "prop firm" (no hyphen) consistently

**Action**: Update all docs with consistent terminology

---

## 4. Configuration and Constants Audit

### 4.1 Current Configuration Structure

**config/config.yaml**:
- Symbol, timeframe, scan_interval
- IBKR connection settings
- Telegram settings
- Risk management (prop firm style)
- Logging settings
- Data provider selection

**Environment Variables** (.env):
- IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- PEARLALGO_DATA_PROVIDER

**Code Constants** (should be in config):
- Service intervals (1800, 3600, 600, 300 seconds)
- Circuit breaker thresholds (10, 5, 10)
- Buffer sizes (100, 50, 1000)
- Data fetch windows (2 hours, 4 hours, 12 hours)
- Signal duplicate window (300 seconds)

---

### 4.2 Recommended Config Layout

**config/config.yaml** (enhanced):
```yaml
# Trading Symbol (Prop Firm Style)
symbol: "MNQ"
timeframe: "1m"
scan_interval: 30

# IBKR Connection
ibkr:
  host: "${IBKR_HOST:-127.0.0.1}"
  port: "${IBKR_PORT:-4002}"
  client_id: "${IBKR_CLIENT_ID:-10}"
  data_client_id: "${IBKR_DATA_CLIENT_ID:-11}"

# Telegram Notifications
telegram:
  enabled: true
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
  notify_on:
    - "signal"
    - "entry"
    - "exit"
    - "error"

# Risk Management (Prop Firm Style)
risk:
  max_risk_per_trade: 0.01
  max_drawdown: 0.10
  stop_loss_atr_multiplier: 1.5
  take_profit_risk_reward: 1.5
  min_position_size: 5
  max_position_size: 15

# Service Intervals (NEW)
service:
  status_update_interval: 1800  # 30 minutes
  heartbeat_interval: 3600  # 1 hour
  connection_failure_alert_interval: 600  # 10 minutes
  data_quality_alert_interval: 300  # 5 minutes
  state_save_interval: 10  # Save state every N cycles

# Circuit Breaker (NEW)
circuit_breaker:
  max_consecutive_errors: 10
  max_data_fetch_errors: 5
  max_connection_failures: 10

# Data Buffers (NEW)
data:
  buffer_size: 100  # Main buffer (1m bars)
  buffer_size_5m: 50  # 5m timeframe buffer
  buffer_size_15m: 50  # 15m timeframe buffer
  historical_window_hours: 2  # Historical data fetch window
  mtf_window_5m_hours: 4  # 5m MTF window
  mtf_window_15m_hours: 12  # 15m MTF window
  performance_history_limit: 1000  # Max performance records

# Signal Generation (NEW)
signals:
  duplicate_window_seconds: 300  # 5 minutes
  stale_data_threshold_minutes: 10  # Alert if data older than this
  connection_error_window_seconds: 600  # 10 minutes

# Logging
logging:
  level: "INFO"
  file: "logs/nq_agent.log"
  console: true

# Data Provider
data_provider: "ibkr"
```

---

### 4.3 Magic Numbers to Relocate

**From `service.py`**:
- `1800` → `config.service.status_update_interval`
- `3600` → `config.service.heartbeat_interval`
- `600` → `config.service.connection_failure_alert_interval`
- `300` → `config.service.data_quality_alert_interval`
- `10` → `config.service.state_save_interval` (cycles)
- `10` → `config.circuit_breaker.max_consecutive_errors`
- `5` → `config.circuit_breaker.max_data_fetch_errors`
- `10` → `config.circuit_breaker.max_connection_failures`
- `1800` → `config.signals.connection_error_window_seconds` (line 258)

**From `data_fetcher.py`**:
- `100` → `config.data.buffer_size`
- `50` → `config.data.buffer_size_5m` and `buffer_size_15m`
- `2` hours → `config.data.historical_window_hours`
- `4` hours → `config.data.mtf_window_5m_hours`
- `12` hours → `config.data.mtf_window_15m_hours`

**From `signal_generator.py`**:
- `300` → `config.signals.duplicate_window_seconds`

**From `performance_tracker.py`**:
- `1000` → `config.data.performance_history_limit`

**From `service.py` (data quality)**:
- `10` minutes → `config.signals.stale_data_threshold_minutes`

---

### 4.4 Values to Keep Hard-Coded (Intentional)

**Rationale**: These are implementation details, not business logic
- `ibkr_executor.py:reconnect_delay=2.0` - Implementation detail
- `ibkr_executor.py:max_reconnect_attempts=3` - Implementation detail
- `retry.py:max_retries=3` - Default for utility, can be overridden
- `signal_generator.py:min_edge_threshold=0.55` - Strategy parameter (already in signal_quality.py)
- `data_fetcher.py:time.sleep(0.5)` - Implementation detail for IBKR API

---

## 5. Testing Alignment

### 5.1 Current Test Structure

**Unit Tests** (12 files):
- `test_config_loading.py` - Config validation
- `test_nq_agent_state.py` - State management
- `test_nq_agent_performance.py` - Performance tracking
- `test_nq_agent_signals.py` - Signal generation
- `test_nq_agent_service.py` - Service lifecycle
- `test_nq_agent_data_fetcher.py` - Data fetching
- `test_nq_agent_integration.py` - Integration tests
- `test_ibkr_provider.py` - IBKR provider
- `test_ibkr_executor.py` - IBKR executor (integration)
- `test_telegram_integration.py` - Telegram notifications
- `test_data_providers.py` - **DELETED** (was broken)
- `conftest.py` - Test configuration

**Test Scripts** (4):
- `test_telegram_notifications.py` - Manual notification testing
- `test_signal_generation.py` - Manual signal testing
- `test_nq_agent_with_mock.py` - Full service test
- `smoke_test_ibkr.py` - IBKR connection test

---

### 5.2 Test Coverage Gaps

**Missing Tests**:
1. **Error Recovery Scenarios**
   - Service recovery after circuit breaker
   - Data provider reconnection after failure
   - Telegram reconnection after failure

2. **Edge Cases**
   - Market hours boundary conditions
   - Data gaps (missing bars)
   - Very high volatility scenarios
   - Buffer overflow handling

3. **Configuration Validation**
   - Invalid config values
   - Missing required config
   - Environment variable substitution edge cases

4. **State Persistence**
   - State corruption recovery
   - Concurrent access handling (already tested, but could expand)

**Recommendation**: **ADD TESTS** (not urgent, but valuable)
- Create `tests/test_error_recovery.py`
- Expand `tests/test_nq_agent_service.py` with edge cases
- Add config validation tests to `tests/test_config_loading.py`

---

### 5.3 Tests to Keep/Remove

**Keep All Current Tests**: ✅ All serve distinct purposes

**Remove**: None (already removed `test_data_providers.py`)

---

## 6. File-Level Change Summary

### 6.1 New Files to Create

1. **`src/pearlalgo/utils/paths.py`** (NEW)
   - State directory utilities
   - File path helpers

2. **`src/pearlalgo/utils/datetime_utils.py`** (NEW)
   - Timestamp conversion utilities
   - ISO format helpers

---

### 6.2 Files to Modify

**Python Code**:
1. `src/pearlalgo/nq_agent/service.py`
   - Use `paths.ensure_state_dir()`
   - Use `datetime_utils` functions
   - Load intervals from config
   - Load circuit breaker thresholds from config

2. `src/pearlalgo/nq_agent/data_fetcher.py`
   - Use `datetime_utils` functions
   - Load buffer sizes from config
   - Load data windows from config

3. `src/pearlalgo/nq_agent/state_manager.py`
   - Use `paths` utilities
   - Use `datetime_utils` functions

4. `src/pearlalgo/nq_agent/performance_tracker.py`
   - Use `paths` utilities
   - Use `datetime_utils` functions
   - Load performance_history_limit from config

5. `src/pearlalgo/nq_agent/telegram_notifier.py`
   - Use `datetime_utils` functions

6. `src/pearlalgo/strategies/nq_intraday/signal_generator.py`
   - Use `datetime_utils` functions
   - Load duplicate_window from config

7. `src/pearlalgo/strategies/nq_intraday/signal_quality.py`
   - Use `paths` utilities

8. `src/pearlalgo/strategies/nq_intraday/config.py`
   - Add service intervals properties
   - Add circuit breaker properties
   - Add data buffer properties
   - Add signal generation properties

**Configuration**:
9. `config/config.yaml`
   - Add `service` section
   - Add `circuit_breaker` section
   - Add `data` section
   - Add `signals` section

**Documentation**:
10. `docs/NQ_AGENT_GUIDE.md`
    - Remove duplicate architecture sections
    - Add reference to PROJECT_SUMMARY.md
    - Focus on operational content

11. `docs/TESTING_GUIDE.md`
    - Merge content from STRATEGY_TESTING_GUIDE.md
    - Add reference to TEST_EXECUTION_GUIDE.md

12. `docs/STRATEGY_TESTING_GUIDE.md`
    - **DELETE** (content merged into TESTING_GUIDE.md)

**Scripts**:
13. `scripts/start_nq_agent.sh`
    - Add deprecation notice in header

14. `scripts/start_ibgateway.sh`
    - Add legacy notice in header

15. All script files
    - Add category comments to headers

**Root Files**:
16. Delete temporary summary files:
    - `TEST_SUMMARY.md`
    - `CLEANUP_SUMMARY.md`
    - `REAL_DATA_UPDATE_SUMMARY.md`
    - `FINAL_TEST_SUMMARY.md`
    - `TEST_FIXES_COMPLETE.md`
    - `REAL_DATA_TESTING.md`

17. Move `TEST_EXECUTION_GUIDE.md` → `docs/TEST_EXECUTION_GUIDE.md`

---

### 6.3 Files to NOT Change

**DO NOT MODIFY** (working correctly, no consolidation needed):
- `src/pearlalgo/nq_agent/health_monitor.py` - Unique functionality
- `src/pearlalgo/utils/retry.py` - Generic utility, correct as-is
- `src/pearlalgo/utils/telegram_alerts.py` - Core Telegram functionality
- `src/pearlalgo/utils/market_hours.py` - Market hours logic
- `src/pearlalgo/data_providers/ibkr_executor.py` - Connection retry logic (context-specific)
- All strategy files in `strategies/nq_intraday/` - Each has distinct purpose
- `docs/PROJECT_SUMMARY.md` - Authoritative source, do not modify
- `docs/GATEWAY.md` - Standalone guide, correct as-is

---

## 7. Execution Order

### Phase 1: Utilities (Foundation)
1. Create `src/pearlalgo/utils/paths.py`
2. Create `src/pearlalgo/utils/datetime_utils.py`
3. Update `src/pearlalgo/utils/__init__.py` to export new utilities

### Phase 2: Configuration Expansion
4. Update `config/config.yaml` with new sections
5. Update `src/pearlalgo/strategies/nq_intraday/config.py` to load new config
6. Test config loading

### Phase 3: Code Refactoring
7. Update all files to use `paths` utilities
8. Update all files to use `datetime_utils` functions
9. Update `service.py` to use config values
10. Update `data_fetcher.py` to use config values
11. Update `signal_generator.py` to use config values
12. Update `performance_tracker.py` to use config values

### Phase 4: Documentation Cleanup
13. Update `docs/NQ_AGENT_GUIDE.md` (remove duplicates, add references)
14. Merge `STRATEGY_TESTING_GUIDE.md` into `TESTING_GUIDE.md`
15. Delete `STRATEGY_TESTING_GUIDE.md`
16. Move `TEST_EXECUTION_GUIDE.md` to `docs/`
17. Delete temporary summary files
18. Normalize terminology across all docs

### Phase 5: Script Updates
19. Add category comments to all scripts
20. Add deprecation/legacy notices where appropriate

### Phase 6: Testing
21. Run full test suite
22. Verify all tests pass
23. Verify no behavior changes

---

## 8. Risk Assessment

### Low Risk Changes
- ✅ Creating new utility files (additive)
- ✅ Adding config sections (additive)
- ✅ Updating code to use utilities (refactoring, same behavior)
- ✅ Documentation cleanup (no code impact)

### Medium Risk Changes
- ⚠️ Moving magic numbers to config (verify defaults match current behavior)
- ⚠️ Updating multiple files to use utilities (test thoroughly)

### No Risk Changes
- ✅ Documentation reorganization
- ✅ Script header updates
- ✅ Deleting temporary files

---

## 9. Validation Checklist

After implementation, verify:
- [ ] All tests pass
- [ ] Service starts and runs normally
- [ ] Config values match previous hardcoded values
- [ ] No runtime behavior changes
- [ ] Documentation is consistent
- [ ] All scripts work as before
- [ ] No broken imports
- [ ] Type hints present on new utilities

---

## 10. Summary

**Total Files to Create**: 2
**Total Files to Modify**: 17
**Total Files to Delete**: 7 (6 temp summaries + 1 duplicate doc)
**Total Files to Keep Unchanged**: All core business logic files

**Key Principles Maintained**:
- ✅ No runtime behavior changes
- ✅ No feature removal
- ✅ Modular boundaries preserved
- ✅ Existing conventions followed
- ✅ Clear ownership maintained

**Benefits**:
- Centralized configuration (easier tuning)
- Reusable utilities (less duplication)
- Consistent documentation (single source of truth)
- Better maintainability (clear structure)

---

**Ready for Implementation**: Yes  
**Estimated Impact**: Low risk, high maintainability gain  
**Breaking Changes**: None
