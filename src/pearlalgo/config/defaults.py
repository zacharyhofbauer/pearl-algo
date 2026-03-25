"""
Centralized configuration defaults for the PearlAlgo trading system.

This module is the **SINGLE SOURCE OF TRUTH** for all default configuration
values.  Other modules (``config_loader._SERVICE_DEFAULTS``,
``config_schema.py`` Pydantic models) **import from here** rather than
hardcoding their own defaults.

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

IBKR_HOST: str = "127.0.0.1"
IBKR_PORT: int = 4001
IBKR_CLIENT_ID: int = 1
IBKR_TRADING_CLIENT_ID: int = 20
IBKR_LIVE_CHART_CLIENT_ID: int = 99


# =============================================================================
# CHART / API SERVER DEFAULTS
# =============================================================================

CHART_PORT: int = 3001
API_SERVER_HOST: str = "127.0.0.1"
API_SERVER_PORT: int = 8000
CHART_URL: str = f"http://localhost:{CHART_PORT}"


# =============================================================================
# EXECUTION LAYER DEFAULTS
# =============================================================================

EXECUTION_ENABLED: bool = False
EXECUTION_ARMED: bool = False
EXECUTION_MODE: str = "dry_run"
MAX_POSITIONS: int = 1
MAX_ORDERS_PER_DAY: int = 20
MAX_DAILY_LOSS: float = 500.0
COOLDOWN_SECONDS: int = 60
DEFAULT_SYMBOL_WHITELIST: list[str] = ["MNQ"]


# =============================================================================
# LEARNING LAYER DEFAULTS
# =============================================================================

LEARNING_ENABLED: bool = True
LEARNING_MODE: str = "shadow"
MIN_SAMPLES_PER_TYPE: int = 10
EXPLORE_RATE: float = 0.1
DECISION_THRESHOLD: float = 0.3
MAX_SIZE_MULTIPLIER: float = 1.5
MIN_SIZE_MULTIPLIER: float = 0.5
PRIOR_ALPHA: float = 2.0
PRIOR_BETA: float = 2.0
DECAY_FACTOR: float = 0.0


# =============================================================================
# SERVICE DEFAULTS
# =============================================================================

DEFAULT_SCAN_INTERVAL: int = 30
STATUS_UPDATE_INTERVAL: int = 1800
HEARTBEAT_INTERVAL: int = 3600
STATE_SAVE_INTERVAL: int = 10
CADENCE_MODE: str = "fixed"
ENABLE_NEW_BAR_GATING: bool = True
PRESSURE_LOOKBACK_BARS: int = 24
PRESSURE_BASELINE_BARS: int = 120
DASHBOARD_CHART_ENABLED: bool = True
DASHBOARD_CHART_INTERVAL: int = 3600
DASHBOARD_CHART_LOOKBACK_HOURS: int = 8
DASHBOARD_CHART_TIMEFRAME: str = "auto"
DASHBOARD_CHART_MAX_BARS: int = 420
DASHBOARD_CHART_SHOW_PRESSURE: bool = True
CONNECTION_FAILURE_ALERT_INTERVAL: int = 600
DATA_QUALITY_ALERT_INTERVAL: int = 300


# =============================================================================
# TELEGRAM UI DEFAULTS
# =============================================================================

TELEGRAM_UI_COMPACT_METRICS: bool = True
TELEGRAM_UI_SHOW_PROGRESS_BARS: bool = False
TELEGRAM_UI_SHOW_VOLUME_METRICS: bool = True
TELEGRAM_UI_COMPACT_METRIC_WIDTH: int = 10


# =============================================================================
# CIRCUIT BREAKER DEFAULTS
# =============================================================================

MAX_CONSECUTIVE_ERRORS: int = 10
MAX_CONNECTION_FAILURES: int = 10
MAX_DATA_FETCH_ERRORS: int = 5


# =============================================================================
# TRADING CIRCUIT BREAKER DEFAULTS
# =============================================================================

# FIXED 2026-03-25: Explicit mode default so _SERVICE_DEFAULTS includes it
# and startup validation can detect warn_only/shadow drift.
TCB_MODE: str = "enforce"
TCB_ENABLED: bool = True
TCB_MAX_CONSECUTIVE_LOSSES: int = 5
TCB_CONSECUTIVE_LOSS_COOLDOWN_MINUTES: int = 30
TCB_MAX_SESSION_DRAWDOWN: float = 500.0
TCB_MAX_DAILY_DRAWDOWN: float = 1000.0
TCB_DRAWDOWN_COOLDOWN_MINUTES: int = 60
TCB_ROLLING_WINDOW_TRADES: int = 20
TCB_MIN_ROLLING_WIN_RATE: float = 0.30
TCB_WIN_RATE_COOLDOWN_MINUTES: int = 30
TCB_MAX_CONCURRENT_POSITIONS: int = 5
TCB_MIN_PRICE_DISTANCE_PCT: float = 0.5
TCB_ENABLE_VOLATILITY_FILTER: bool = True
TCB_MIN_ATR_RATIO: float = 0.8
TCB_MAX_ATR_RATIO: float = 2.5
TCB_CHOP_DETECTION_WINDOW: int = 10
TCB_CHOP_WIN_RATE_THRESHOLD: float = 0.35
TCB_AUTO_RESUME_AFTER_COOLDOWN: bool = True
TCB_REQUIRE_WINNING_TRADE_TO_RESUME: bool = False
TCB_ENABLE_SESSION_FILTER: bool = True
TCB_ALLOWED_SESSIONS: list[str] = ["overnight", "midday", "close"]

# Phase 1: Direction gating
TCB_ENABLE_DIRECTION_GATING: bool = True
TCB_DIRECTION_GATING_MIN_CONFIDENCE: float = 0.70

# Phase 2: Regime avoidance
TCB_ENABLE_REGIME_AVOIDANCE: bool = False
TCB_BLOCKED_REGIMES: list[str] = ["ranging", "volatile"]
TCB_REGIME_AVOIDANCE_MIN_CONFIDENCE: float = 0.70

# Phase 3: Trigger filters
TCB_ENABLE_TRIGGER_FILTERS: bool = False

# Phase 4: ML chop shield
TCB_ENABLE_ML_CHOP_SHIELD: bool = False


# =============================================================================
# DATA DEFAULTS
# =============================================================================

DATA_BUFFER_SIZE: int = 100
DATA_BUFFER_SIZE_5M: int = 50
DATA_BUFFER_SIZE_15M: int = 50
HISTORICAL_HOURS: int = 2
MULTITIMEFRAME_5M_HOURS: int = 25
MULTITIMEFRAME_15M_HOURS: int = 25
PERFORMANCE_HISTORY_LIMIT: int = 1000
STALE_DATA_THRESHOLD_MINUTES: float = 10.0
CONNECTION_TIMEOUT_MINUTES: float = 30.0
ENABLE_BASE_CACHE: bool = True
BASE_REFRESH_SECONDS: int = 60
ENABLE_MTF_CACHE: bool = True
MTF_REFRESH_SECONDS_5M: int = 300
MTF_REFRESH_SECONDS_15M: int = 900
IBKR_VERBOSE_LOGGING: bool = False


# =============================================================================
# STORAGE DEFAULTS
# =============================================================================

# SQLite is the primary write path (single source of truth).
# JSON files are generated as periodic exports for external tools.
STORAGE_SQLITE_ENABLED: bool = True
STORAGE_DB_PATH: str = "data/agent_state/NQ/trades.db"
# Dual-write is DEPRECATED — kept only for transition.
# Set to False to use SQLite-only mode (recommended).
STORAGE_DUAL_WRITE_FILES: bool = False


# =============================================================================
# ML FILTER DEFAULTS
# =============================================================================

ML_FILTER_ENABLED: bool = False
ML_FILTER_MODEL_PATH: str | None = None
ML_FILTER_MODEL_VERSION: str = "v1.0.0"
ML_FILTER_MIN_PROBABILITY: float = 0.55
ML_FILTER_HIGH_PROBABILITY: float = 0.70
ML_FILTER_ADJUST_SIZING: bool = False
ML_FILTER_SIZE_MULTIPLIER_MIN: float = 1.0
ML_FILTER_SIZE_MULTIPLIER_MAX: float = 1.5
ML_FILTER_MIN_TRAINING_SAMPLES: int = 30
ML_FILTER_RETRAIN_INTERVAL_DAYS: int = 7
ML_FILTER_N_ESTIMATORS: int = 100
ML_FILTER_MAX_DEPTH: int = 6
ML_FILTER_LEARNING_RATE: float = 0.1
ML_FILTER_CALIBRATE_PROBABILITIES: bool = True


# =============================================================================
# RISK DEFAULTS
# =============================================================================

MAX_RISK_PER_TRADE: float = 0.01
MAX_DRAWDOWN: float = 0.10
MIN_POSITION_SIZE: int = 5
MAX_POSITION_SIZE: int = 25


# =============================================================================
# SIGNAL DEFAULTS
# =============================================================================

MIN_CONFIDENCE: float = 0.50
MIN_RISK_REWARD: float = 1.5
DUPLICATE_WINDOW_SECONDS: int = 300


# =============================================================================
# PERFORMANCE DEFAULTS
# =============================================================================

PERFORMANCE_MAX_RECORDS: int = 1000
PERFORMANCE_DEFAULT_LOOKBACK_DAYS: int = 7


# =============================================================================
# VIRTUAL PNL DEFAULTS
# =============================================================================

VIRTUAL_PNL_ENABLED: bool = True
VIRTUAL_PNL_INTRABAR_TIEBREAK: str = "stop_loss"
VIRTUAL_PNL_NOTIFY_ENTRY: bool = False
VIRTUAL_PNL_NOTIFY_EXIT: bool = False


# =============================================================================
# AUTO-FLAT DEFAULTS
# =============================================================================

AUTO_FLAT_ENABLED: bool = True
AUTO_FLAT_FRIDAY_ENABLED: bool = True
AUTO_FLAT_FRIDAY_TIME: str = "16:55"
AUTO_FLAT_WEEKEND_ENABLED: bool = True
AUTO_FLAT_TIMEZONE: str = "America/New_York"
AUTO_FLAT_NOTIFY: bool = True


# =============================================================================
# MARKET HOURS DEFAULTS
# =============================================================================

MARKET_HOURS_ENABLE_CONFIG_OVERRIDES: bool = False
MARKET_HOURS_HOLIDAY_OVERRIDES: list = []
MARKET_HOURS_EARLY_CLOSES: dict = {}


# =============================================================================
# SIGNAL FORWARDING DEFAULTS
# =============================================================================

# Signal forwarding removed (restructure Phase 1D)


# =============================================================================
# ORDER SIZING DEFAULTS — ML Opportunity Sizing (WS6 / Issue 12)
# =============================================================================
# Used by ``order_manager.py`` for ML-based opportunity sizing tiers.

ML_HIGH_OPPORTUNITY_THRESHOLD: float = 0.8
ML_HIGH_OPPORTUNITY_MULTIPLIER: float = 1.5
ML_GOOD_OPPORTUNITY_THRESHOLD: float = 0.6
ML_GOOD_OPPORTUNITY_MULTIPLIER: float = 1.25
ML_NORMAL_OPPORTUNITY_MULTIPLIER: float = 1.0
ML_LOW_OPPORTUNITY_THRESHOLD: float = 0.4
ML_LOW_OPPORTUNITY_MULTIPLIER: float = 0.75
DEFAULT_MARGIN_PER_CONTRACT: int = 5000


# =============================================================================
# CONFIDENCE TIER SIZING DEFAULTS (WS6)
# =============================================================================
# Shared by ``contextual_bandit.py`` and ``ensemble_scorer.py`` for
# confidence-based position-size adjustments.

CONFIDENCE_HIGH_SIZE_MULTIPLIER: float = 1.3
CONFIDENCE_MEDIUM_SIZE_MULTIPLIER: float = 1.0
CONFIDENCE_LOW_SIZE_MULTIPLIER: float = 0.7
CONFIDENCE_MEDIUM_THRESHOLD: float = 0.5
