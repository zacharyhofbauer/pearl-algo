"""
Centralized configuration defaults for the PearlAlgo trading system.

This module is the SINGLE SOURCE OF TRUTH for all default configuration values.
Other modules should import these constants rather than hardcoding defaults.

**Purpose:**
- Eliminate configuration drift across modules
- Make defaults explicit and documented
- Simplify maintenance and auditing

**Usage:**
    ```python
    from pearlalgo.config.defaults import IBKR_HOST, IBKR_PORT
    
    host = os.getenv("IBKR_HOST", IBKR_HOST)
    port = int(os.getenv("IBKR_PORT", str(IBKR_PORT)))
    ```

**Configuration Precedence:**
    1. Environment variables (highest priority)
    2. config/config.yaml values
    3. These defaults (lowest priority)
"""

from __future__ import annotations

# =============================================================================
# IBKR CONNECTION DEFAULTS
# =============================================================================

# Default host for IBKR Gateway/TWS connection
IBKR_HOST: str = "127.0.0.1"

# Default port for IBKR Gateway (paper trading)
# Note: TWS default is 7497, Gateway default is 4002
IBKR_PORT: int = 4002

# Default client ID for main connection
IBKR_CLIENT_ID: int = 1

# Default client ID for execution (separate to avoid conflicts)
IBKR_TRADING_CLIENT_ID: int = 20

# Default client ID for live chart API server
IBKR_LIVE_CHART_CLIENT_ID: int = 99


# =============================================================================
# CHART/API SERVER DEFAULTS
# =============================================================================

# Default port for the live chart Next.js frontend
CHART_PORT: int = 3001

# Default host for the API server
API_SERVER_HOST: str = "127.0.0.1"

# Default port for the API server
API_SERVER_PORT: int = 8000

# Default chart URL for Telegram screenshots
CHART_URL: str = f"http://localhost:{CHART_PORT}"


# =============================================================================
# EXECUTION LAYER DEFAULTS
# =============================================================================

# Master enable flag for execution layer (safety default: disabled)
EXECUTION_ENABLED: bool = False

# Armed flag for execution (safety default: disarmed)
EXECUTION_ARMED: bool = False

# Execution mode (dry_run, paper, live)
EXECUTION_MODE: str = "dry_run"

# Maximum concurrent positions
MAX_POSITIONS: int = 1

# Maximum orders per trading day
MAX_ORDERS_PER_DAY: int = 20

# Kill switch: maximum daily loss in dollars
MAX_DAILY_LOSS: float = 500.0

# Minimum seconds between orders for same signal type
COOLDOWN_SECONDS: int = 60

# Default symbol whitelist
DEFAULT_SYMBOL_WHITELIST: list[str] = ["MNQ"]


# =============================================================================
# LEARNING LAYER DEFAULTS
# =============================================================================

# Learning layer enabled by default (observes but doesn't block)
LEARNING_ENABLED: bool = True

# Learning mode (shadow, live)
LEARNING_MODE: str = "shadow"

# Minimum samples before policy has opinion
MIN_SAMPLES_PER_TYPE: int = 10

# Random exploration rate (epsilon-greedy)
EXPLORE_RATE: float = 0.1

# Skip signal if P(win) < threshold
DECISION_THRESHOLD: float = 0.3

# Position sizing multipliers
MAX_SIZE_MULTIPLIER: float = 1.5
MIN_SIZE_MULTIPLIER: float = 0.5

# Beta distribution priors (optimistic start)
PRIOR_ALPHA: float = 2.0
PRIOR_BETA: float = 2.0

# Decay factor for older observations (0 = no decay)
DECAY_FACTOR: float = 0.0


# =============================================================================
# CHALLENGE TRACKER DEFAULTS
# =============================================================================

CHALLENGE_ENABLED: bool = False
CHALLENGE_START_BALANCE: float = 50000.0
CHALLENGE_MAX_DRAWDOWN: float = 2000.0
CHALLENGE_PROFIT_TARGET: float = 3000.0
CHALLENGE_AUTO_RESET_ON_PASS: bool = True
CHALLENGE_AUTO_RESET_ON_FAIL: bool = True


# =============================================================================
# SERVICE DEFAULTS
# =============================================================================

# Default scan interval (seconds)
DEFAULT_SCAN_INTERVAL: int = 30

# Default status update interval (seconds)
STATUS_UPDATE_INTERVAL: int = 300

# Default heartbeat interval (seconds)
HEARTBEAT_INTERVAL: int = 1800

# Default state save interval (cycles)
STATE_SAVE_INTERVAL: int = 10

# Default data buffer size (bars)
DATA_BUFFER_SIZE: int = 100

# Default historical data hours
HISTORICAL_HOURS: int = 2

# Default stale data threshold (minutes)
STALE_DATA_THRESHOLD_MINUTES: float = 5.0

# Default connection timeout (minutes)
CONNECTION_TIMEOUT_MINUTES: float = 10.0


# =============================================================================
# CIRCUIT BREAKER DEFAULTS
# =============================================================================

# Maximum consecutive errors before pausing
MAX_CONSECUTIVE_ERRORS: int = 10

# Maximum connection failures before alerting
MAX_CONNECTION_FAILURES: int = 3


# =============================================================================
# SIGNAL DEFAULTS
# =============================================================================

# Minimum confidence threshold for signals
MIN_CONFIDENCE: float = 0.55

# Minimum risk/reward ratio
MIN_RISK_REWARD: float = 1.3

# Duplicate signal window (seconds)
DUPLICATE_WINDOW_SECONDS: int = 300


# =============================================================================
# RISK DEFAULTS
# =============================================================================

# Maximum risk per trade (as fraction of account)
MAX_RISK_PER_TRADE: float = 0.015

# Maximum drawdown (as fraction of account)
MAX_DRAWDOWN: float = 0.10

# ATR multiplier for stop loss
STOP_LOSS_ATR_MULTIPLIER: float = 4.0

# Risk/reward ratio for take profit
TAKE_PROFIT_RISK_REWARD: float = 1.5

# Minimum position size (contracts)
MIN_POSITION_SIZE: int = 5

# Maximum position size (contracts)
MAX_POSITION_SIZE: int = 50
