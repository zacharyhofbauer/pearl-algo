"""
Market Agent Service

Main 24/7 service for running market trading strategies.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
import signal
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

if TYPE_CHECKING:
    from pearlalgo.market_agent.service_factory import ServiceDependencies

from pearlalgo.utils.config_helpers import safe_get_bool, safe_get_int
from pearlalgo.utils.formatting import fmt_currency
from pearlalgo.utils.logger import logger
from pearlalgo.utils.state_io import atomic_write_json
from pearlalgo.utils.paths import get_utc_timestamp, parse_utc_timestamp
from pearlalgo.market_agent.stats_computation import get_trading_day_start

from pearlalgo.config.config_loader import load_service_config, parse_market_hours_overrides
from pearlalgo.config.config_view import ConfigView
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.market_agent.data_fetcher import MarketAgentDataFetcher
from pearlalgo.market_agent.health_monitor import HealthMonitor
from pearlalgo.market_agent.live_chart_screenshot import capture_live_chart_screenshot
from pearlalgo.market_agent.performance_tracker import PerformanceTracker
from pearlalgo.market_agent.state_manager import MarketAgentStateManager
from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
from pearlalgo.market_agent.notification_queue import NotificationQueue, NotificationTier, Priority
from pearlalgo.market_agent.trading_circuit_breaker import (
    TradingCircuitBreaker,
    create_trading_circuit_breaker,
)
from pearlalgo.trading_bots.pearl_bot_auto import generate_signals, CONFIG as PEARL_BOT_CONFIG
from pearlalgo.utils.cadence import CadenceScheduler
from pearlalgo.utils.data_quality import DataQualityChecker
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.market_hours import configure_market_hours, get_market_hours
from pearlalgo.market_agent.service_lifecycle import ServiceLifecycleMixin
from pearlalgo.market_agent.service_loop import ServiceLoopMixin
from pearlalgo.market_agent.service_notifications import ServiceNotificationsMixin
from pearlalgo.market_agent.virtual_trade_manager import VirtualTradeManager
from pearlalgo.utils.volume_pressure import (
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)
from pearlalgo.utils.pearl_suggestions import get_suggestion_engine
# AI shadow tracker removed (restructure Phase 2D)
# Stub replacements for removed AI module
def get_shadow_tracker():
    """No-op stub: AI shadow tracker was removed."""
    return None

class SuggestionType:
    """No-op stub: AI suggestion types were removed."""
    RISK_WARNING = "risk_warning"
    STRATEGY_HINT = "strategy_hint"
from pearlalgo.market_agent.ml_manager import MLManager
from pearlalgo.market_agent.audit_logger import AuditLogger, AuditEventType
from pearlalgo.market_agent.scheduled_tasks import ScheduledTasks
from pearlalgo.market_agent.operator_handler import OperatorHandler
from pearlalgo.market_agent.order_manager import OrderManager
from pearlalgo.market_agent.signal_handler import SignalHandler
from pearlalgo.market_agent.signal_orchestrator import SignalOrchestrator
from pearlalgo.market_agent.execution_orchestrator import ExecutionOrchestrator
from pearlalgo.market_agent.observability_orchestrator import ObservabilityOrchestrator
from pearlalgo.market_agent.state_builder import StateBuilder

# Execution layer imports (optional - only used if execution.enabled)
# IBKR execution is inactive; see execution/_inactive/ibkr/
try:
    from pearlalgo.execution.base import ExecutionAdapter, ExecutionConfig
    EXECUTION_AVAILABLE = True
except ImportError:
    EXECUTION_AVAILABLE = False
    ExecutionAdapter = None  # type: ignore
    ExecutionConfig = None  # type: ignore

# Tradovate execution adapter (optional - only for prop firm / Tradovate Paper)
try:
    from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
    from pearlalgo.execution.tradovate.config import TradovateConfig
    TRADOVATE_AVAILABLE = True
except ImportError:
    TRADOVATE_AVAILABLE = False
    TradovateExecutionAdapter = None  # type: ignore
    TradovateConfig = None  # type: ignore

# Learning layer imports (optional - only used if learning.enabled)
try:
    from pearlalgo.learning.bandit_policy import BanditPolicy, BanditConfig, BanditDecision
    LEARNING_AVAILABLE = True
except ImportError:
    LEARNING_AVAILABLE = False
    BanditPolicy = None  # type: ignore
    BanditConfig = None  # type: ignore
    BanditDecision = None  # type: ignore

# SQLite "forever memory" (optional - enabled via storage.sqlite_enabled)
try:
    from pearlalgo.learning.trade_database import TradeDatabase
    TRADE_DB_AVAILABLE = True
except ImportError:
    TRADE_DB_AVAILABLE = False
    TradeDatabase = None  # type: ignore

# Contextual learning (optional - used for richer "learn by session/regime" analytics)
try:
    from pearlalgo.learning.contextual_bandit import (
        ContextualBanditPolicy,
        ContextualBanditConfig,
        ContextFeatures,
        ContextualDecision,
    )
    CONTEXTUAL_BANDIT_AVAILABLE = True
except ImportError:
    CONTEXTUAL_BANDIT_AVAILABLE = False
    ContextualBanditPolicy = None  # type: ignore
    ContextualBanditConfig = None  # type: ignore
    ContextFeatures = None  # type: ignore
    ContextualDecision = None  # type: ignore

# ML signal filter (optional - shadow measurement / lift evaluation)
try:
    from pearlalgo.learning.ml_signal_filter import get_ml_signal_filter, MLSignalFilter
    ML_FILTER_AVAILABLE = True
except ImportError:
    ML_FILTER_AVAILABLE = False
    get_ml_signal_filter = None  # type: ignore
    MLSignalFilter = None  # type: ignore




def get_trading_day_date() -> date:
    """
    Get the current trading day date based on 6pm ET boundary.

    Futures trading day runs from 6pm ET to 6pm ET next day.
    - Before 6pm ET: returns previous calendar day
    - After 6pm ET: returns current calendar day

    Example: At 5pm ET on Jan 29, returns Jan 28 (still in Jan 28's trading session).
             At 7pm ET on Jan 29, returns Jan 29 (now in Jan 29's trading session).

    Delegates to stats_computation.get_trading_day_start() for the 6pm ET logic.
    """
    return get_trading_day_start().date()


class MarketAgentService(ServiceNotificationsMixin, ServiceLoopMixin, ServiceLifecycleMixin):
    """
    24/7 service for NQ intraday trading strategy.
    
    Runs independently, fetches data, generates signals, and sends to Telegram.
    
    Lifecycle (start/stop) is provided by ServiceLifecycleMixin.
    """

    def __init__(
        self,
        data_provider: Optional[DataProvider] = None,
        config: Optional[Dict] = None,
        state_dir: Optional[Path] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        *,
        deps: Optional["ServiceDependencies"] = None,
    ):
        """
        Initialize market agent service.

        There are two construction paths:

        1. **Legacy / direct** — pass ``data_provider`` and optional kwargs.
           Dependencies are built inline (existing behavior).
        2. **Factory** — pass a pre-built :class:`ServiceDependencies` via
           ``deps``.  All other positional args are ignored.  This is the
           preferred path for tests and for ``main.py`` via
           :func:`build_service_dependencies`.

        Args:
            data_provider: Data provider instance (legacy path)
            config: Strategy configuration (legacy path, optional)
            state_dir: State directory (legacy path, optional)
            telegram_bot_token: Telegram bot token (legacy path, optional)
            telegram_chat_id: Telegram chat ID (legacy path, optional)
            deps: Pre-built dependencies (factory path, keyword-only)
        """
        # --- resolve dependencies -------------------------------------------------
        # Build a ServiceDependencies from legacy kwargs when not provided,
        # then let resolve_defaults() fill in any remaining Nones.
        from pearlalgo.market_agent.service_factory import ServiceDependencies

        if deps is None:
            deps = ServiceDependencies(
                data_provider=data_provider,
                config=ConfigView(config or PEARL_BOT_CONFIG.copy()) if config is not None else None,
                service_config=load_service_config(),
                state_dir=state_dir,
                telegram_bot_token=telegram_bot_token,
                telegram_chat_id=telegram_chat_id,
            )

        deps.resolve_defaults()

        self.config = deps.config
        service_config = deps.service_config
        state_dir = deps.state_dir
        telegram_bot_token = deps.telegram_bot_token
        telegram_chat_id = deps.telegram_chat_id

        self.symbol = str(self.config.get("symbol", "MNQ"))
        self.timeframe = str(self.config.get("timeframe", "5m"))
        self.scan_interval = float(self.config.get("scan_interval", 30))
        self._service_config = service_config

        # Strategy adapter (kept so tests can monkeypatch `service.strategy.analyze`).
        class _StrategyAdapter:
            def __init__(self, config: ConfigView):
                self.config = config

            def analyze(self, df: pd.DataFrame, *, current_time: Optional[datetime] = None) -> list[dict]:
                return generate_signals(df, config=self.config, current_time=current_time)

        self.strategy = _StrategyAdapter(self.config)

        # --- assign resolved dependencies (no branching) -----------------------
        self.data_fetcher = deps.data_fetcher
        self.state_manager = deps.state_manager
        self.performance_tracker = deps.performance_tracker
        self.telegram_notifier = deps.telegram_notifier
        self.notification_queue = deps.notification_queue

        # Log Telegram configuration status
        if self.telegram_notifier.enabled:
            logger.info(
                f"Telegram notifications enabled: bot_token={'***' if telegram_bot_token else 'MISSING'}, "
                f"chat_id={'***' if telegram_chat_id else 'MISSING'}, "
                f"telegram_instance={self.telegram_notifier.telegram is not None}"
            )
        else:
            logger.warning(
                "Telegram notifications DISABLED - signals will not be sent to Telegram. "
                f"bot_token={'present' if telegram_bot_token else 'MISSING'}, "
                f"chat_id={'present' if telegram_chat_id else 'MISSING'}"
            )

        self.health_monitor = deps.health_monitor
        self.audit_logger: Optional[AuditLogger] = deps.audit_logger
        service_settings = service_config.get("service", {})
        circuit_breaker_settings = service_config.get("circuit_breaker", {})
        trading_circuit_breaker_settings = service_config.get("trading_circuit_breaker", {}) or {}
        data_settings = service_config.get("data", {})
        telegram_ui_settings = service_config.get("telegram_ui", {}) or {}
        auto_flat_settings = service_config.get("auto_flat", {}) or {}
        signal_settings = service_config.get("signals", {}) or {}
        self._risk_settings = service_config.get("risk", {}) or {}
        self._strategy_settings = service_config.get("strategy", {}) or {}

        # Signal forwarding removed (restructure Phase 1D).
        # Each agent now runs its own strategy with its own broker data.
        self._signal_follower_mode = False
        self._signal_writer_mode = False

        # Track config flags that are currently non-enforced (warn-only telemetry)
        self._config_warnings: list[dict[str, Any]] = []
        for key in ("skip_overnight", "avoid_lunch_lull", "prioritize_ny_session"):
            if signal_settings.get(key):
                warning = {
                    "key": f"signals.{key}",
                    "value": signal_settings.get(key),
                    "status": "not_enforced",
                    "message": f"{key} is configured but not enforced (warn-only telemetry).",
                }
                self._config_warnings.append(warning)
                logger.warning(f"Config flag not enforced: signals.{key}=True")
        
        # ==========================================================================
        # TRADING CIRCUIT BREAKER (risk management for consecutive losses/drawdown)
        # ==========================================================================
        self.trading_circuit_breaker: Optional[TradingCircuitBreaker] = None
        if trading_circuit_breaker_settings.get("enabled", True):
            self.trading_circuit_breaker = create_trading_circuit_breaker(trading_circuit_breaker_settings)
            # Validate config at startup
            config_warnings = self.trading_circuit_breaker.validate_config()
            if config_warnings:
                logger.warning(f"Trading circuit breaker config warnings: {config_warnings}")
            logger.info(
                f"Trading circuit breaker enabled: "
                f"max_consecutive_losses={self.trading_circuit_breaker.config.max_consecutive_losses}, "
                f"max_session_drawdown=${self.trading_circuit_breaker.config.max_session_drawdown}, "
                f"max_positions={self.trading_circuit_breaker.config.max_concurrent_positions}, "
                f"direction_gating={self.trading_circuit_breaker.config.enable_direction_gating}"
            )

        # ==========================================================================
        # STORAGE (SQLite dual-write; keeps Telegram/mobile compatibility)
        # ==========================================================================
        self._sqlite_enabled = False
        self._trade_db: Optional["TradeDatabase"] = None
        self._async_sqlite_queue: Optional["AsyncSQLiteQueue"] = None
        self._async_writes_enabled = False
        
        if TRADE_DB_AVAILABLE:
            try:
                storage_cfg = service_config.get("storage", {}) or {}
                self._sqlite_enabled = bool(storage_cfg.get("sqlite_enabled", False))
                if self._sqlite_enabled:
                    db_path_raw = storage_cfg.get("db_path") or str(self.state_manager.state_dir / "trades.db")
                    self._trade_db = TradeDatabase(Path(str(db_path_raw)))
                    logger.info(f"SQLite storage enabled (dual-write): db_path={db_path_raw}")
                    
                    # Async writes (performance): non-blocking SQLite writes via background thread
                    self._async_writes_enabled = bool(storage_cfg.get("async_writes_enabled", False))
                    if self._async_writes_enabled:
                        try:
                            from pearlalgo.storage.async_sqlite_queue import AsyncSQLiteQueue
                            
                            max_queue_size = int(storage_cfg.get("async_queue_max_size", 1000) or 1000)
                            priority_trades = bool(storage_cfg.get("async_queue_priority_trades", True))
                            self._async_sqlite_queue = AsyncSQLiteQueue(
                                trade_db=self._trade_db,
                                max_queue_size=max_queue_size,
                                priority_trades=priority_trades,
                            )
                            self._async_sqlite_queue.start()
                            logger.info(
                                f"Async SQLite writes enabled: max_queue={max_queue_size}, priority_trades={priority_trades}"
                            )
                        except Exception as e:
                            logger.warning(f"Async SQLite init failed (using blocking writes): {e}")
                            self._async_writes_enabled = False
                            self._async_sqlite_queue = None
            except Exception as e:
                logger.warning(f"SQLite storage init failed (continuing without DB): {e}")
                self._sqlite_enabled = False
                self._trade_db = None
                self._async_sqlite_queue = None
        
        # Inject async queue into state_manager + performance_tracker (if enabled)
        if self._async_sqlite_queue is not None:
            try:
                self.state_manager.set_sqlite_queue(self._async_sqlite_queue)
                self.performance_tracker.set_sqlite_queue(self._async_sqlite_queue)
            except Exception as e:
                logger.warning(f"Critical path error: {e}", exc_info=True)

        # ==========================================================================
        # 50K CHALLENGE TRACKER (Pass/Fail Rules)
        # ==========================================================================
        # Tracks account attempts with pass/fail thresholds.
        # PnL shown in Telegram = current attempt only (not all-time).
        self._challenge_tracker: Optional["ChallengeTracker"] = None
        self._challenge_enabled = False
        try:
            from pearlalgo.market_agent.challenge_tracker import ChallengeTracker, ChallengeConfig
            
            challenge_cfg = service_config.get("challenge", {}) or {}
            self._challenge_enabled = bool(challenge_cfg.get("enabled", False))
            # Skip ChallengeTracker for Tradovate Paper accounts — TvPaperEvalTracker handles
            # challenge state for those. Running both causes them to overwrite the same
            # challenge_state.json with incompatible formats.
            tv_paper_stage = str(challenge_cfg.get("stage", "") or "").strip().lower()
            is_tv_paper = tv_paper_stage in ("evaluation", "sim_funded", "live")
            if self._challenge_enabled and not is_tv_paper:
                cfg = ChallengeConfig(
                    enabled=True,
                    start_balance=float(challenge_cfg.get("start_balance", 50_000.0)),
                    max_drawdown=float(challenge_cfg.get("max_drawdown", 2_000.0)),
                    profit_target=float(challenge_cfg.get("profit_target", 3_000.0)),
                    auto_reset_on_pass=bool(challenge_cfg.get("auto_reset_on_pass", True)),
                    auto_reset_on_fail=bool(challenge_cfg.get("auto_reset_on_fail", True)),
                )
                self._challenge_tracker = ChallengeTracker(
                    config=cfg,
                    state_dir=self.state_manager.state_dir,
                    trade_db=self._trade_db,
                )
                logger.info(
                    f"50k Challenge enabled: balance=${cfg.start_balance:,.0f}, "
                    f"target=+${cfg.profit_target:,.0f}, max_dd=-${cfg.max_drawdown:,.0f}"
                )
            elif is_tv_paper:
                logger.info("ChallengeTracker skipped — Tradovate Paper account uses TvPaperEvalTracker")
        except Exception as e:
            logger.warning(f"Challenge tracker init failed (continuing without): {e}")
            self._challenge_tracker = None
            self._challenge_enabled = False

        # ==========================================================================
        # Tradovate Paper EVALUATION TRACKER (Prop Firm Rules)
        # ==========================================================================
        self._tv_paper_tracker = None
        self._tv_paper_enabled = False
        try:
            challenge_cfg = service_config.get("challenge", {}) or {}
            tv_paper_stage = str(challenge_cfg.get("stage", "") or "").strip().lower()
            if tv_paper_stage in ("evaluation", "sim_funded", "live"):
                from pearlalgo.market_agent.tv_paper_eval_tracker import (
                    TvPaperEvalTracker,
                    TvPaperEvalConfig,
                )
                tv_paper_cfg = TvPaperEvalConfig(
                    enabled=True,
                    stage=tv_paper_stage,
                    start_balance=float(challenge_cfg.get("start_balance", 50_000.0)),
                    profit_target=float(challenge_cfg.get("profit_target", 3_000.0)),
                    max_loss_distance=float(challenge_cfg.get("max_drawdown", 2_000.0)),
                    max_contracts_mini=int(challenge_cfg.get("max_contracts_mini", 5)),
                    max_contracts_micro=int(challenge_cfg.get("max_contracts_micro", 50)),
                    consistency_pct=float(challenge_cfg.get("consistency_pct", 0.50)),
                    min_trading_days=int(challenge_cfg.get("min_trading_days", 2)),
                    t1_news_allowed=bool(challenge_cfg.get("t1_news_allowed", True)),
                    auto_reset_on_pass=bool(challenge_cfg.get("auto_reset_on_pass", True)),
                    auto_reset_on_fail=bool(challenge_cfg.get("auto_reset_on_fail", True)),
                )
                self._tv_paper_tracker = TvPaperEvalTracker(
                    config=tv_paper_cfg,
                    state_dir=self.state_manager.state_dir,
                )
                self._tv_paper_enabled = True
                logger.info(
                    f"Tradovate Paper Eval Tracker enabled: stage={tv_paper_cfg.stage}, "
                    f"target=+${tv_paper_cfg.profit_target:,.0f}, "
                    f"max_loss=-${tv_paper_cfg.max_loss_distance:,.0f}"
                )
        except Exception as e:
            logger.warning(f"Tradovate Paper tracker init failed (continuing without): {e}")
            self._tv_paper_tracker = None
            self._tv_paper_enabled = False

        # Tradovate account cache (polled each cycle when execution adapter is Tradovate)
        self._tradovate_account: Dict[str, Any] = {}
        self._tv_paper_was_connected: Optional[bool] = None

        # ==========================================================================
        # DRIFT GUARD (Risk-Off Cooldown)
        # ==========================================================================
        # ML / LEARNING (WS8: extracted to MLManager)
        # ==========================================================================
        self._ml_manager = MLManager(
            service_config=service_config,
            state_dir=self.state_manager.state_dir,
            trade_db=self._trade_db,
            sqlite_enabled=self._sqlite_enabled,
            signals_file_path=getattr(self.state_manager, "signals_file", None),
        )

        # ==========================================================================
        # AUTO-FLAT (Virtual trades) - Daily + Friday/Weekend safety
        # ==========================================================================
        self._auto_flat_enabled = bool(auto_flat_settings.get("enabled", False))
        self._auto_flat_daily_enabled = bool(auto_flat_settings.get("daily_enabled", False))
        self._auto_flat_friday_enabled = bool(auto_flat_settings.get("friday_enabled", True))
        self._auto_flat_weekend_enabled = bool(auto_flat_settings.get("weekend_enabled", True))
        self._auto_flat_timezone = str(auto_flat_settings.get("timezone", "America/New_York") or "America/New_York")
        self._auto_flat_notify = bool(auto_flat_settings.get("notify", True))
        self._auto_flat_daily_time = self._parse_hhmm(
            auto_flat_settings.get("daily_time"),
            default=(15, 55),
        )
        self._auto_flat_friday_time = self._parse_hhmm(
            auto_flat_settings.get("friday_time"),
            default=(16, 55),
        )
        self._auto_flat_last_dates: Dict[str, Optional[date]] = {
            "daily_auto_flat": None,
            "friday_auto_flat": None,
            "weekend_auto_flat": None,
        }
        self._last_close_all_at: Optional[str] = None
        self._last_close_all_reason: Optional[str] = None
        self._last_close_all_count: Optional[int] = None
        self._last_close_all_pnl: Optional[float] = None
        self._last_close_all_price_source: Optional[str] = None

        # Telegram UI formatting (Home Card / dashboards)
        self._telegram_ui_compact_metrics_enabled = safe_get_bool(telegram_ui_settings, "compact_metrics_enabled", True)
        self._telegram_ui_show_progress_bars = safe_get_bool(telegram_ui_settings, "show_progress_bars", False)
        self._telegram_ui_show_volume_metrics = safe_get_bool(telegram_ui_settings, "show_volume_metrics", True)
        self._telegram_ui_compact_metric_width = safe_get_int(telegram_ui_settings, "compact_metric_width", 10, lo=5, hi=20)

        # Configure optional market-hours overrides (disabled by default).
        # Keeps the declared boundary intact: config drives utils, never the reverse.
        try:
            holidays, early_closes = parse_market_hours_overrides(service_config)
            configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
        except Exception as e:
            logger.warning(f"Could not configure market hours overrides: {e}")

        self.running = False
        self.shutdown_requested = False
        self.paused = False
        self.pause_reason: Optional[str] = None
        self.start_time: Optional[datetime] = None
        
        # Load persisted state to restore counters
        saved_state = self.state_manager.load_state()
        self.cycle_count = saved_state.get("cycle_count", 0)
        # Restore signal_count from saved state OR count from signals file (more accurate)
        saved_signal_count = saved_state.get("signal_count", 0)
        try:
            # Use state_manager's incremental signal count (O(1) after first call)
            actual_signal_count = self.state_manager.get_signal_count()
            self.signal_count = max(saved_signal_count, actual_signal_count)
            logger.info(f"Restored signal_count: {self.signal_count} (from state: {saved_signal_count}, from file: {actual_signal_count})")
        except Exception as e:
            logger.warning(f"Could not count signals from file, using saved state: {e}")
            self.signal_count = saved_signal_count
        
        self.error_count = saved_state.get("error_count", 0)
        # Telegram delivery observability (backward-compatible defaults)
        self.signals_sent = int(saved_state.get("signals_sent", 0) or 0)
        self.signals_send_failures = int(saved_state.get("signals_send_failures", 0) or 0)
        self.last_signal_send_error: Optional[str] = saved_state.get("last_signal_send_error")
        self.last_signal_generated_at: Optional[str] = saved_state.get("last_signal_generated_at")
        self.last_signal_sent_at: Optional[str] = saved_state.get("last_signal_sent_at")
        self.last_signal_id_prefix: Optional[str] = saved_state.get("last_signal_id_prefix")

        # Session baselines (initialized on start)
        self._cycle_count_at_start: Optional[int] = None
        self._signal_count_at_start: Optional[int] = None
        self._signals_sent_at_start: Optional[int] = None
        self._signals_fail_at_start: Optional[int] = None
        self.last_status_update: Optional[datetime] = None
        self.status_update_interval = service_settings.get("status_update_interval", 1800)
        self.last_heartbeat: Optional[datetime] = None
        self.heartbeat_interval = service_settings.get("heartbeat_interval", 3600)
        # Dashboard chart (hourly Live Main Chart screenshot)
        self.last_dashboard_chart_sent: Optional[datetime] = None
        self.dashboard_chart_enabled = bool(service_settings.get("dashboard_chart_enabled", True))  # can disable auto charts
        self.dashboard_chart_interval = service_settings.get("dashboard_chart_interval", 3600)  # 1 hour default
        self.dashboard_chart_lookback_hours = float(service_settings.get("dashboard_chart_lookback_hours", 8) or 8)
        self.dashboard_chart_timeframe = str(service_settings.get("dashboard_chart_timeframe", "auto") or "auto")
        self.dashboard_chart_max_bars = int(service_settings.get("dashboard_chart_max_bars", 420) or 420)
        self.dashboard_chart_show_pressure = bool(service_settings.get("dashboard_chart_show_pressure", True))
        # Buy/Sell pressure (dashboard observability)
        self.pressure_lookback_bars = int(service_settings.get("pressure_lookback_bars", 24) or 24)
        self.pressure_baseline_bars = int(service_settings.get("pressure_baseline_bars", 120) or 120)
        self.state_save_interval = service_settings.get("state_save_interval", 10)
        self._state_dirty: bool = False  # Set True when state changes; reset after save
        self.connection_failure_alert_interval = service_settings.get("connection_failure_alert_interval", 600)
        self.data_quality_alert_interval = service_settings.get("data_quality_alert_interval", 300)
        self.consecutive_errors = 0
        self.max_consecutive_errors = circuit_breaker_settings.get("max_consecutive_errors", 10)
        self.data_fetch_errors = 0
        self.max_data_fetch_errors = circuit_breaker_settings.get("max_data_fetch_errors", 5)
        self.connection_failures = 0
        self.max_connection_failures = circuit_breaker_settings.get("max_connection_failures", 10)
        self._cb_connection_notified = False  # Guard: only send circuit breaker notification once per event
        
        # Virtual trade exit manager (extracted from this class)
        self.virtual_trade_manager = VirtualTradeManager(
            state_manager=self.state_manager,
            performance_tracker=self.performance_tracker,
            notification_queue=self.notification_queue,
            trading_circuit_breaker=self.trading_circuit_breaker,
            telegram_notifier=self.telegram_notifier,
            execution_adapter=getattr(self, "execution_adapter", None),
            bandit_policy=getattr(self, "bandit_policy", None),
            contextual_policy=getattr(self, "contextual_policy", None),
            challenge_tracker=getattr(self, "_challenge_tracker", None),
            tv_paper_tracker=getattr(self, "_tv_paper_tracker", None),
            virtual_pnl_enabled=getattr(self.config, "virtual_pnl_enabled", True),
            virtual_pnl_tiebreak=getattr(self.config, "virtual_pnl_tiebreak", "stop_loss"),
            virtual_pnl_notify_exit=getattr(self.config, "virtual_pnl_notify_exit", False),
            symbol=getattr(self.config, "symbol", "MNQ"),
            audit_logger=self.audit_logger,
        )
        
        # Daily summary tracking (sent at safety close 3:55 PM ET)
        self._daily_summary_sent_date: Optional[str] = None
        # Morning briefing tracking (sent at 6:30 AM ET)
        self._morning_briefing_sent_date: Optional[str] = None
        self.last_connection_failure_alert: Optional[datetime] = None
        self.last_successful_cycle: Optional[datetime] = None
        self.last_data_quality_alert: Optional[datetime] = None
        self._last_stale_data_alert_type: Optional[str] = None  # Track last alert type to prevent duplicates
        # Smarter alert cadence state (reduce Telegram spam)
        self._last_stale_bucket: Optional[int] = None
        self._last_buffer_severity: Optional[str] = None
        self._was_stale_during_market: bool = False
        self._was_data_gap: bool = False
        self._was_buffer_inadequate: bool = False
        self.stale_data_threshold_minutes = data_settings.get("stale_data_threshold_minutes", 10)
        self.connection_timeout_minutes = data_settings.get("connection_timeout_minutes", 30)
        self.buffer_size_target = int(data_settings.get("buffer_size", 100) or 100)
        
        # Initialize data quality checker
        self.data_quality_checker = DataQualityChecker(
            stale_data_threshold_minutes=self.stale_data_threshold_minutes
        )
        
        # Initialize Pearl suggestion engine
        self.suggestion_engine = get_suggestion_engine(state_dir=str(self.state_manager.state_dir))

        # Shadow tracker now lives in MLManager (WS8).
        # self.shadow_tracker delegates via property below.

        # ------------------------------------------------------------------
        # Extracted sub-modules (Phase 3: Arch-1B decomposition)
        # ------------------------------------------------------------------
        self.scheduled_tasks = ScheduledTasks(
            telegram_notifier=self.telegram_notifier,
            notification_queue=self.notification_queue,
            state_manager=self.state_manager,
            performance_tracker=self.performance_tracker,
            service_config=service_config,
        )
        if self.audit_logger is not None:
            self.scheduled_tasks.set_audit_logger(self.audit_logger)
        self.operator_handler = OperatorHandler(
            state_manager=self.state_manager,
            notification_queue=self.notification_queue,
            shadow_tracker=self.shadow_tracker,
            bandit_policy=getattr(self, "bandit_policy", None),
            get_status_snapshot=lambda: getattr(self, "_get_status_snapshot", lambda: {})(),
        )

        # New-bar gating: skip heavy analysis when df hasn't advanced (performance optimization).
        # This is high leverage when using 5m bars with 30s scan interval (5 of 6 cycles are repeats).
        self._enable_new_bar_gating = bool(service_settings.get("enable_new_bar_gating", True))
        self._last_analyzed_bar_ts: Optional[datetime] = None
        self._analysis_skip_count: int = 0
        self._analysis_run_count: int = 0

        # Quiet reason / signal diagnostics observability (persisted to state.json)
        # These track why the bot is quiet so `/status` and dashboards can show it.
        self._last_quiet_reason: Optional[str] = None
        self._last_signal_diagnostics: Optional[str] = None
        self._last_signal_diagnostics_raw: Optional[Dict] = None

        # Adaptive cadence configuration (fast-active profile + velocity mode)
        # Dynamically adjusts scan interval based on market/session state.
        self._adaptive_cadence_enabled = bool(service_settings.get("adaptive_cadence_enabled", False))
        self._scan_interval_active = float(service_settings.get("scan_interval_active_seconds", 5))
        self._scan_interval_idle = float(service_settings.get("scan_interval_idle_seconds", 30))
        self._scan_interval_market_closed = float(service_settings.get("scan_interval_market_closed_seconds", 300))
        self._scan_interval_paused = float(service_settings.get("scan_interval_paused_seconds", 60))
        self._effective_interval: float = float(self.scan_interval)  # Current effective interval
        self._last_effective_interval: float = self._effective_interval  # For detecting changes
        
        # Velocity mode: ultra-fast scans during ATR expansion or volume spikes (catch fast moves)
        self._velocity_mode_enabled = bool(service_settings.get("velocity_mode_enabled", False))
        self._scan_interval_velocity = float(service_settings.get("scan_interval_velocity_seconds", 1.5))
        self._velocity_atr_expansion_threshold = float(service_settings.get("velocity_atr_expansion_threshold", 1.20))
        self._velocity_volume_spike_threshold = float(service_settings.get("velocity_volume_spike_threshold", 2.0))
        self._velocity_mode_active = False  # Runtime state (updated each cycle)

        # Cadence scheduler for fixed-interval timing (start-to-start)
        # "fixed" = start-to-start timing with skip-ahead for missed cycles
        # "sleep_after" = legacy sleep-after-work semantics
        self.cadence_mode = service_settings.get("cadence_mode", "fixed")
        self.cadence_scheduler: Optional[CadenceScheduler] = None
        if self.cadence_mode == "fixed":
            self.cadence_scheduler = CadenceScheduler(
                interval_seconds=float(self.config.scan_interval),
            )
            logger.info(
                f"Cadence scheduler initialized: mode=fixed, interval={self.config.scan_interval}s"
            )
        else:
            logger.info(
                f"Cadence scheduler disabled: mode={self.cadence_mode} (legacy sleep-after-work)"
            )

        # ==========================================================================
        # EXECUTION ADAPTER (ATS - Automated Trading System)
        # ==========================================================================
        # Initialize execution adapter for automated order placement.
        # SAFETY: Default is disabled + disarmed. Must explicitly enable and /arm.
        self.execution_adapter: Optional["ExecutionAdapter"] = None
        self._execution_config: Optional["ExecutionConfig"] = None
        execution_settings = service_config.get("execution", {})
        execution_adapter_name = str(
            (execution_settings or {}).get("adapter", "tradovate")
        ).strip().lower()
        
        if EXECUTION_AVAILABLE and execution_settings.get("enabled", False):
            try:
                if execution_adapter_name in ("ibkr", "interactivebrokers"):
                    raise NotImplementedError(
                        "IBKR execution is inactive. Use Tradovate (execution.adapter: tradovate). "
                        "See execution/_inactive/ibkr/ for legacy code."
                    )
                self._execution_config = ExecutionConfig.from_dict(execution_settings)
                if execution_adapter_name in ("tradovate", "") and TRADOVATE_AVAILABLE:
                    tv_config = TradovateConfig.from_env()
                    self.execution_adapter = TradovateExecutionAdapter(
                        self._execution_config, tradovate_config=tv_config,
                    )
                else:
                    raise ValueError(f"Unknown execution.adapter: {execution_adapter_name!r}")
                logger.info(
                    f"Execution adapter initialized: adapter={execution_adapter_name}, "
                    f"mode={self._execution_config.mode.value}, "
                    f"armed={self._execution_config.armed}, "
                    f"max_positions={self._execution_config.max_positions}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize execution adapter: {e}", exc_info=True)
                self.execution_adapter = None
        else:
            if not EXECUTION_AVAILABLE:
                logger.debug("Execution layer not available (import failed)")
            else:
                logger.info("Execution adapter disabled (execution.enabled=false)")
        
        # Track last trading day for daily counter reset
        self._last_trading_day: Optional[date] = None
        
        # Track execution connection state for alerts (avoid duplicate alerts)
        self._execution_was_connected: Optional[bool] = None
        self._last_connection_alert_time: Optional[datetime] = None
        self._connection_alert_cooldown_seconds: int = 300  # 5 minutes between alerts

        # ==========================================================================
        # LEARNING (Adaptive Bandit Policy) -- now managed by MLManager (WS8)
        # ==========================================================================
        # bandit_policy, contextual_policy, and _bandit_config are accessed
        # via backward-compatible properties that delegate to self._ml_manager.

        # ------------------------------------------------------------------
        # SignalHandler: extracted signal processing pipeline (Arch-1B)
        # ------------------------------------------------------------------
        self._order_manager = OrderManager(
            risk_settings=self._risk_settings,
            strategy_settings=self._strategy_settings,
            ml_signal_filter=self._ml_manager.signal_filter,
            ml_adjust_sizing=self._ml_manager.adjust_sizing,
        )
        self._signal_handler = SignalHandler(
            state_manager=self.state_manager,
            performance_tracker=self.performance_tracker,
            notification_queue=self.notification_queue,
            order_manager=self._order_manager,
            trading_circuit_breaker=self.trading_circuit_breaker,
            bandit_policy=self._ml_manager.bandit_policy,
            bandit_config=self._ml_manager.bandit_config,
            contextual_policy=self._ml_manager.contextual_policy,
            ml_signal_filter=self._ml_manager.signal_filter,
            ml_filter_enabled=self._ml_manager.filter_enabled,
            ml_filter_mode=self._ml_manager.filter_mode,
            ml_shadow_threshold=self._ml_manager.shadow_threshold,
            execution_adapter=self.execution_adapter,
            telegram_notifier=self.telegram_notifier,
            audit_logger=self.audit_logger,
        )
        # Propagate persisted counters so handler continues from saved state
        self._signal_handler.signal_count = self.signal_count
        self._signal_handler.signals_sent = self.signals_sent
        self._signal_handler.signals_send_failures = self.signals_send_failures
        self._signal_handler.last_signal_generated_at = self.last_signal_generated_at
        self._signal_handler.last_signal_sent_at = self.last_signal_sent_at
        self._signal_handler.last_signal_send_error = self.last_signal_send_error
        self._signal_handler.last_signal_id_prefix = self.last_signal_id_prefix
        # Handler error_count starts at 0; service error_count includes non-signal errors
        self._prev_sh_error_count = 0

        # ------------------------------------------------------------------
        # Orchestrators (Arch-2 decomposition: thin delegation layer)
        # ------------------------------------------------------------------
        self.signal_orchestrator = SignalOrchestrator(
            signal_handler=self._signal_handler,
            order_manager=self._order_manager,
            state_manager=self.state_manager,
            ml_signal_filter=self._ml_manager.signal_filter,
            bandit_policy=self._ml_manager.bandit_policy,
            ml_filter_enabled=self._ml_manager.filter_enabled,
            ml_filter_mode=self._ml_manager.filter_mode,
            ml_manager=self._ml_manager,
        )
        self.execution_orchestrator = ExecutionOrchestrator(
            virtual_trade_manager=self.virtual_trade_manager,
            order_manager=self._order_manager,
            state_manager=self.state_manager,
            execution_adapter=self.execution_adapter,
            execution_config=self._execution_config,
            notification_queue=self.notification_queue,
            connection_alert_cooldown_seconds=self._connection_alert_cooldown_seconds,
        )
        self.observability_orchestrator = ObservabilityOrchestrator(
            performance_tracker=self.performance_tracker,
            notification_queue=self.notification_queue,
            telegram_notifier=self.telegram_notifier,
            state_manager=self.state_manager,
        )

        # State builder (extracted from _save_state for modularity)
        self._state_builder = StateBuilder(self)

        logger.info("MarketAgentService initialized")


    # start() and stop() are provided by ServiceLifecycleMixin (service_lifecycle.py)
    # _run_loop() is provided by ServiceLoopMixin (service_loop.py)

    # _build_context_features_for_signal: removed (lives in signal_handler.py)

    # Signal processing delegated to self._signal_handler (see signal_handler.py)

    def _sync_signal_handler_counters(self) -> None:
        """Sync counters from SignalHandler back to service for state persistence."""
        sh = self._signal_handler
        self.signal_count = sh.signal_count
        self.signals_sent = sh.signals_sent
        self.signals_send_failures = sh.signals_send_failures
        # Error count: add handler delta (service error_count includes non-signal errors)
        new_errors = sh.error_count - self._prev_sh_error_count
        if new_errors > 0:
            self.error_count += new_errors
            self._prev_sh_error_count = sh.error_count
        if sh.last_signal_generated_at:
            self.last_signal_generated_at = sh.last_signal_generated_at
        if sh.last_signal_sent_at:
            self.last_signal_sent_at = sh.last_signal_sent_at
        self.last_signal_send_error = sh.last_signal_send_error
        if sh.last_signal_id_prefix:
            self.last_signal_id_prefix = sh.last_signal_id_prefix

    # -- DELETED: ~350-line inline _process_signal method --
    # All signal processing logic (circuit breaker, ML filter, ML sizing,
    # performance tracking, bandit/contextual policy, execution, notifications)
    # now lives in signal_handler.py::SignalHandler.process_signal().
    # Call sites updated to use self._signal_handler.process_signal() directly.
    # Helper methods below (_compute_base_position_size, _apply_ml_opportunity_sizing)
    # were only called from _process_signal but are kept for other code paths.
    # Note: _build_context_features_for_signal was removed (now in signal_handler.py).

    def _compute_base_position_size(self, signal: Dict) -> int:
        """Compute a base position size from config + signal confidence."""
        try:
            existing = signal.get("position_size")
            if existing is not None:
                return max(1, int(float(existing)))
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)

        cfg = self._strategy_settings or {}
        enable_dynamic = bool(cfg.get("enable_dynamic_sizing", False))
        base_contracts = int(cfg.get("base_contracts", 1) or 1)
        high_contracts = int(cfg.get("high_conf_contracts", base_contracts) or base_contracts)
        max_contracts = int(cfg.get("max_conf_contracts", high_contracts) or high_contracts)
        try:
            conf = float(signal.get("confidence") or 0.0)
        except Exception as e:
            logger.warning(f"Failed to parse signal confidence for position sizing: {e}")
            conf = 0.0
        try:
            high_th = float(cfg.get("high_conf_threshold", 0.8) or 0.8)
        except Exception as e:
            logger.warning(f"Failed to parse high confidence threshold: {e}")
            high_th = 0.8
        try:
            max_th = float(cfg.get("max_conf_threshold", 0.9) or 0.9)
        except Exception as e:
            logger.warning(f"Failed to parse max confidence threshold: {e}")
            max_th = 0.9

        size = base_contracts
        if enable_dynamic:
            if conf >= max_th:
                size = max_contracts
            elif conf >= high_th:
                size = high_contracts
            else:
                size = base_contracts

        # Optional per-signal-type sizing multiplier (strategy settings)
        try:
            multipliers = cfg.get("signal_type_size_multipliers", {}) or {}
            sig_type = str(signal.get("type") or "")
            if sig_type in multipliers:
                size = int(round(size * float(multipliers.get(sig_type) or 1.0)))
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)

        # Clamp to risk min/max
        try:
            min_size = int(self._risk_settings.get("min_position_size", 1) or 1)
        except Exception as e:
            logger.warning(f"Failed to parse min position size from risk settings: {e}")
            min_size = 1
        try:
            max_size = int(self._risk_settings.get("max_position_size", size) or size)
        except Exception as e:
            logger.warning(f"Failed to parse max position size from risk settings: {e}")
            max_size = size

        size = max(min_size, min(max_size, size))
        return max(1, size)

    def _apply_ml_opportunity_sizing(self, signal: Dict) -> None:
        """Adjust size and priority based on ML opportunity signal (delegates to MLManager)."""
        base_size = self._compute_base_position_size(signal)
        self._ml_manager.apply_opportunity_sizing(
            signal, base_size=base_size, risk_settings=self._risk_settings
        )

    def _update_virtual_trade_exits(self, market_data: Dict) -> None:
        """Delegate to VirtualTradeManager (extracted for testability)."""
        self.virtual_trade_manager.process_exits(market_data)

    def _get_status_snapshot(self) -> Dict[str, Any]:
        """Get current status snapshot for Pearl suggestions."""
        # Calculate uptime
        uptime_hours = 0.0
        if self.start_time:
            uptime_hours = (datetime.now(timezone.utc) - self.start_time).total_seconds() / 3600.0
            
        # Calculate data age
        data_age_minutes = 0.0
        data_stale = False
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            freshness = self.data_quality_checker.check_data_freshness(
                last_market_data.get("latest_bar"),
                last_market_data.get("df")
            )
            data_age_minutes = float(freshness.get("age_minutes", 0.0))
            data_stale = not bool(freshness.get("is_fresh", False))
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            
        # Get performance stats
        daily_pnl = 0.0
        wins_today = 0
        losses_today = 0
        try:
            perf = self.performance_tracker.get_daily_performance()
            daily_pnl = perf.get("total_pnl", 0.0)
            wins_today = perf.get("wins", 0)
            losses_today = perf.get("losses", 0)
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            
        # Get market status
        futures_open = False
        session_open = False
        try:
            futures_open = bool(get_market_hours().is_market_open())
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            session_open = check_trading_session(datetime.now(timezone.utc), self.config)
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        risk_daily_pnl = 0.0
        risk_session_pnl = 0.0
        risk_would_block_total = 0
        risk_mode = "unknown"
        try:
            if self.trading_circuit_breaker is not None:
                cb = self.trading_circuit_breaker.get_status()
                risk_daily_pnl = float(cb.get("daily_pnl", 0.0) or 0.0)
                risk_session_pnl = float(cb.get("session_pnl", 0.0) or 0.0)
                risk_would_block_total = int(cb.get("would_block_total", 0) or 0)
                risk_mode = str(cb.get("mode", "unknown") or "unknown")
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        return {
            "agent_running": self.running and not self.paused,
            "gateway_running": self.connection_failures < self.max_connection_failures,
            "data_stale": data_stale,
            "data_age_minutes": data_age_minutes,
            "daily_pnl": daily_pnl,
            "wins_today": wins_today,
            "losses_today": losses_today,
            "signals_today": self.signal_count,
            "last_signal_minutes": self._compute_quiet_period_minutes(),
            "session_open": session_open,
            "futures_open": futures_open,
            "agent_uptime_hours": uptime_hours,
            "win_streak": getattr(self, "_streak_count", 0) if getattr(self, "_streak_type", "") == "win" else 0,
            "risk_daily_pnl": risk_daily_pnl,
            "risk_session_pnl": risk_session_pnl,
            "risk_would_block_total": risk_would_block_total,
            "risk_mode": risk_mode,
        }

    async def _check_pearl_suggestions(self) -> None:
        """
        Check for proactive Pearl suggestions and send them if appropriate.
        Also records suggestions in shadow tracker for outcome measurement.
        """
        if not self.telegram_notifier.enabled:
            return

        try:
            # Get current state for suggestion engine
            state = self._get_status_snapshot()
            prefs_obj = self.telegram_notifier._get_prefs()
            prefs = prefs_obj.all()

            # Update shadow tracker with current context (for ongoing tracking)
            try:
                shadow_context = {
                    "daily_pnl": state.get("daily_pnl", 0),
                    "wins_today": state.get("wins_today", 0),
                    "losses_today": state.get("losses_today", 0),
                    "active_positions": state.get("active_trades_count", 0),
                }
                self.shadow_tracker.update_context(shadow_context)
            except Exception as e:
                logger.debug(f"Shadow tracker update failed (non-fatal): {e}")

            # Generate suggestion (engine handles cooldowns)
            suggestion = self.suggestion_engine.generate_suggestion(
                state,
                prefs=prefs
            )

            if suggestion:
                logger.info(f"Sending proactive PEARL suggestion: {suggestion.message}")

                # Record suggestion in shadow tracker
                try:
                    # Map cooldown_key to suggestion type
                    suggestion_type = self._map_suggestion_type(suggestion.cooldown_key)
                    shadow_context = {
                        "daily_pnl": state.get("daily_pnl", 0),
                        "wins_today": state.get("wins_today", 0),
                        "losses_today": state.get("losses_today", 0),
                        "active_positions": state.get("active_trades_count", 0),
                    }
                    self.shadow_tracker.record_suggestion(
                        suggestion_type=suggestion_type,
                        message=suggestion.message,
                        action=suggestion.accept_label,
                        context=shadow_context,
                    )
                except Exception as e:
                    logger.debug(f"Failed to record suggestion in shadow tracker: {e}")

                # Pass plain text - send_pearl_notification will escape for MarkdownV2
                await self.telegram_notifier.send_pearl_notification(suggestion.message, message_type="Suggestion")

            # Periodic Pearl-style review (status + ML snapshot)
            if prefs.get("pearl_review_enabled", True):
                try:
                    last_sent = prefs.get("pearl_review_last_sent_at")
                    interval_min = float(prefs.get("pearl_review_interval_minutes", 15) or 15)
                    due = True
                    if last_sent:
                        try:
                            last_dt = parse_utc_timestamp(str(last_sent))
                            if last_dt and last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            if last_dt:
                                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
                                due = elapsed >= interval_min
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}")
                            due = True
                    if due:
                        review = self._build_pearl_review_message(state)
                        if review:
                            await self.telegram_notifier.send_pearl_notification(review, message_type="Check-In")
                            try:
                                prefs_obj.set("pearl_review_last_sent_at", datetime.now(timezone.utc).isoformat())
                            except Exception as e:
                                logger.debug(f"Non-critical: {e}")
                except Exception as e:
                    logger.debug(f"Pearl review check failed (non-fatal): {e}")
                
        except Exception as e:
            logger.warning(f"Error checking Pearl suggestions: {e}")

    def _map_suggestion_type(self, cooldown_key: str) -> str:
        """Map suggestion cooldown key to shadow tracker suggestion type."""
        key = str(cooldown_key or "").lower()
        if "problem" in key or "gateway" in key or "data" in key or "agent" in key:
            return SuggestionType.RISK_ALERT.value
        elif "risk" in key or "drawdown" in key:
            return SuggestionType.RISK_ALERT.value
        elif "milestone" in key or "streak" in key or "profit" in key:
            return SuggestionType.PATTERN_INSIGHT.value
        elif "eod" in key or "quiet" in key:
            return SuggestionType.SESSION_ADVICE.value
        elif "greeting" in key:
            return SuggestionType.SESSION_ADVICE.value
        elif "pattern" in key or "direction" in key or "bias" in key:
            return SuggestionType.DIRECTION_BIAS.value
        elif "opportunity" in key or "volatility" in key or "volume" in key:
            return SuggestionType.OPPORTUNITY.value
        else:
            return SuggestionType.PATTERN_INSIGHT.value

    def _build_pearl_review_message(self, state: Dict[str, Any]) -> Optional[str]:
        """Build PEARL check-in content (plain text, will be converted to MarkdownV2 by sender).
        
        Returns the message body only - header is added by send_pearl_notification.
        Focus on unique insights: streaks, observations, recommendations.
        """
        try:
            import json
            
            # Basic state
            is_running = state.get("agent_running")
            is_session_open = state.get("session_open")
            is_futures_open = state.get("futures_open")
            
            # Load performance data for deeper insights
            perf_trades = []
            today_trades = []
            streak_info = ""
            time_since_trade = ""
            daily_pnl = 0.0
            
            try:
                perf_trades = self.performance_tracker.load_performance_data()

                # Today's trades
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                today_trades = [t for t in perf_trades if today_str in str(t.get("exit_time", "") or "")]

                # De-duplicate by signal_id to avoid double-counting
                try:
                    by_id = {}
                    no_id = []
                    for t in today_trades:
                        sid = str(t.get("signal_id") or "").strip() if isinstance(t, dict) else ""
                        if not sid:
                            no_id.append(t)
                            continue
                        by_id[sid] = t  # keep most recent occurrence
                    if by_id:
                        today_trades = list(by_id.values()) + no_id
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

                # Calculate daily P&L from actual trades (not state which may be stale)
                if today_trades:
                    daily_pnl = sum(float(t.get("pnl", 0) or 0) for t in today_trades)

                # Calculate streak
                if today_trades:
                    sorted_trades = sorted(today_trades, key=lambda t: str(t.get("exit_time", "") or ""), reverse=True)
                    streak = 0
                    streak_type = None
                    for t in sorted_trades:
                        is_win = t.get("is_win", False)
                        if streak_type is None:
                            streak_type = "W" if is_win else "L"
                            streak = 1
                        elif (is_win and streak_type == "W") or (not is_win and streak_type == "L"):
                            streak += 1
                        else:
                            break
                    if streak >= 2:
                        streak_icon = "🔥" if streak_type == "W" else "❄️"
                        streak_word = "wins" if streak_type == "W" else "losses"
                        streak_info = f"{streak_icon} Streak: {streak} {streak_word} in a row"

                # Time since last trade
                if perf_trades:
                    last_trade = max(perf_trades, key=lambda t: str(t.get("exit_time", "") or ""), default=None)
                    if last_trade and last_trade.get("exit_time"):
                        try:
                            last_exit = datetime.fromisoformat(str(last_trade["exit_time"]).replace("Z", "+00:00"))
                            mins_ago = (datetime.now(timezone.utc) - last_exit).total_seconds() / 60
                            if mins_ago > 60:
                                hours = int(mins_ago / 60)
                                time_since_trade = f"⏰ Last Trade: {hours}h ago"
                            else:
                                time_since_trade = f"⏰ Last Trade: {int(mins_ago)}m ago"
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}")
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
            
            # Generate PEARL insight (context-aware observation)
            insight = self._generate_pearl_insight(
                is_running=is_running,
                is_session_open=is_session_open,
                is_futures_open=is_futures_open,
                daily_pnl=daily_pnl,
                today_trades=today_trades,
            )
            
            # Build status line (plain text)
            status_parts = []
            if is_running:
                status_parts.append("🟢 Running")
            else:
                status_parts.append("🔴 Stopped")
            if is_session_open and is_futures_open:
                status_parts.append("📊 Markets Open")
            elif not is_futures_open:
                status_parts.append("🌙 Futures Closed")
            else:
                status_parts.append("⏸️ Session Closed")
            
            status_line = " • ".join(status_parts)
            
            # P&L summary (plain text)
            pnl_icon = "📈" if daily_pnl > 0 else ("📉" if daily_pnl < 0 else "➖")
            trades_today = len(today_trades)
            wins_today = sum(1 for t in today_trades if t.get("is_win"))
            wr_today = (wins_today / trades_today * 100) if trades_today > 0 else 0
            
            # Build plain text message (will be escaped by sender)
            lines = [status_line]
            
            # Add performance if there are trades
            if trades_today > 0:
                lines.append("")
                trades_word = "trade" if trades_today == 1 else "trades"
                pnl_line = f"{pnl_icon} Today: {fmt_currency(daily_pnl, show_sign=True)} ({trades_today} {trades_word}, {wr_today:.0f}% WR)"
                lines.append(pnl_line)
            
            # Add streak if notable
            if streak_info:
                lines.append(streak_info)
            
            # Add time since last trade
            if time_since_trade:
                lines.append(time_since_trade)
            
            # Add PEARL's insight
            if insight:
                lines.append("")
                lines.append(f"💬 {insight}")

            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            return None
    
    def _generate_pearl_insight(
        self,
        is_running: bool,
        is_session_open: bool,
        is_futures_open: bool,
        daily_pnl: float,
        today_trades: list,
    ) -> str:
        """Generate a contextual PEARL insight based on current state."""
        try:
            trades_count = len(today_trades)
            wins = sum(1 for t in today_trades if t.get("is_win"))
            losses = trades_count - wins
            
            # Session-based insights
            if not is_futures_open:
                return "Markets are closed. Rest up for the next session!"
            
            if not is_session_open:
                return "Strategy session is paused. I'm watching but not trading."
            
            if not is_running:
                return "I'm currently stopped. Start me when you're ready to trade."
            
            # Performance-based insights
            if trades_count == 0:
                return "No trades yet today. Waiting for the right setup..."
            
            wr = (wins / trades_count * 100) if trades_count > 0 else 0
            
            if daily_pnl > 100:
                return f"Great day! Up ${daily_pnl:,.0f}. Consider protecting these gains."
            elif daily_pnl < -100:
                return f"Tough day, down ${abs(daily_pnl):,.0f}. Stay disciplined."
            elif wr >= 70 and trades_count >= 3:
                return f"Strong {wr:.0f}% win rate today. Execution is sharp!"
            elif wr < 40 and trades_count >= 3:
                return f"{wr:.0f}% WR so far. Market may be choppy."
            elif losses >= 3 and wins == 0:
                return "Multiple losses in a row. Consider taking a break."
            else:
                return "All systems normal. Scanning for opportunities..."
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            return "All systems normal."

    async def _check_dashboard(
        self,
        market_data: Optional[Dict] = None,
        quiet_reason: Optional[str] = None,
        signal_diagnostics=None,
    ) -> None:
        """
        Send periodic dashboard message (replaces status + heartbeat).
        
        Args:
            market_data: Current market data (may be empty)
            quiet_reason: Why the agent is quiet (e.g., "StrategySessionClosed")
            signal_diagnostics: SignalDiagnostics from the signal generator
        """
        # Check if interval notifications are enabled (user preference)
        try:
            from pearlalgo.utils.telegram_alerts import TelegramPrefs
            prefs = TelegramPrefs(state_dir=self.state_manager.state_dir)
            if not prefs.get("interval_notifications", True):
                return  # Notifications disabled
        except Exception as e:
            # If we can't load prefs, default to enabled
            logger.debug(f"Non-critical: {e}")

        now = datetime.now(timezone.utc)

        # Check if it's time for a dashboard chart (every 60m by default)
        # Respect dashboard_chart_enabled config (can be disabled to reduce noise)
        chart_due = self.dashboard_chart_enabled and (
            self.last_dashboard_chart_sent is None
            or (now - self.last_dashboard_chart_sent).total_seconds() >= self.dashboard_chart_interval
        )

        # Check if it's time for a text dashboard update (every 15m by default)
        text_due = (
            self.last_status_update is None
            or (now - self.last_status_update).total_seconds() >= self.status_update_interval
        )

        # Canonical dashboard: one message (visual when chart is available).
        if chart_due:
            chart_path = None
            try:
                # Bound chart generation time so the service loop cannot stall indefinitely.
                chart_path = await asyncio.wait_for(self.observability_orchestrator.generate_dashboard_chart(), timeout=30.0)
            except Exception as e:
                logger.debug(f"Could not generate dashboard chart: {e}")
                chart_path = None
            self.last_dashboard_chart_sent = now
            await self._send_dashboard(
                market_data,
                quiet_reason=quiet_reason,
                signal_diagnostics=signal_diagnostics,
                chart_path=chart_path,
            )
            # Clean up any temp chart file returned on export failure.
            try:
                if (
                    chart_path
                    and getattr(chart_path, "name", "") not in {"dashboard_latest.png", "dashboard_telegram_latest.png"}
                    and chart_path.exists()
                ):
                    chart_path.unlink()
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
            self.last_status_update = now
        elif text_due:
            # Text-only update (no chart refresh); keep layout identical.
            await self._send_dashboard(
                market_data,
                quiet_reason=quiet_reason,
                signal_diagnostics=signal_diagnostics,
                chart_path=None,
            )
            self.last_status_update = now

    async def _generate_dashboard_chart(self) -> Optional[Path]:
        """Capture the Live Main Chart and export it for Telegram/UI use.

        Delegated to ObservabilityOrchestrator.generate_dashboard_chart().
        """
        return await self.observability_orchestrator.generate_dashboard_chart()

    async def _send_dashboard(
        self,
        market_data: Optional[Dict] = None,
        quiet_reason: Optional[str] = None,
        signal_diagnostics=None,
        chart_path: Optional[Path] = None,
    ) -> None:
        """
        Send consolidated dashboard to Telegram.
        
        Args:
            market_data: Current market data (may be empty)
            quiet_reason: Why the agent is quiet (for observability)
            signal_diagnostics: SignalDiagnostics from the signal generator
            chart_path: Optional path to chart PNG for a visual dashboard message
        """
        try:
            # Get base status
            status = self.get_status()
            
            # Add current time
            status["current_time"] = datetime.now(timezone.utc)
            status["symbol"] = self.config.symbol
            
            # Add quiet reason for observability (why no signals)
            if quiet_reason:
                status["quiet_reason"] = quiet_reason
            
            # Add signal diagnostics when no signals (for observability)
            if signal_diagnostics is not None:
                # Handle both SignalDiagnostics object and pre-formatted string
                if hasattr(signal_diagnostics, 'format_compact'):
                    status["signal_diagnostics"] = signal_diagnostics.format_compact()
                    status["signal_diagnostics_raw"] = signal_diagnostics.to_dict() if hasattr(signal_diagnostics, 'to_dict') else {}
                else:
                    # Already a formatted string
                    status["signal_diagnostics"] = str(signal_diagnostics)
                    status["signal_diagnostics_raw"] = {}
            
            # Try to get latest price
            try:
                if market_data and market_data.get("latest_bar"):
                    latest_bar = market_data["latest_bar"]
                    if isinstance(latest_bar, dict) and "close" in latest_bar:
                        status["latest_price"] = latest_bar["close"]
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

            # Track price source for UI confidence cues (e.g., Level 1 vs historical fallback).
            try:
                if market_data and isinstance(market_data.get("latest_bar"), dict):
                    status["latest_price_source"] = market_data["latest_bar"].get("_data_level")
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

            # Active trades + unrealized PnL (virtual lifecycle: status="entered").
            try:
                active = []
                try:
                    recent_signals = self.state_manager.get_recent_signals(limit=300)
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
                    recent_signals = []
                for rec in recent_signals:
                    if isinstance(rec, dict) and rec.get("status") == "entered":
                        active.append(rec)

                status["active_trades_count"] = len(active)

                # Total unrealized PnL across active trades (USD), computed using the freshest available price.
                latest_price = status.get("latest_price")
                if latest_price is not None and len(active) > 0:
                    try:
                        current_price = float(latest_price)
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")
                        current_price = None
                    if current_price and current_price > 0:
                        total_upnl = 0.0
                        for rec in active:
                            sig = rec.get("signal", {}) or {}
                            direction = str(sig.get("direction") or "long").lower()
                            try:
                                entry_price = float(sig.get("entry_price") or 0.0)
                            except Exception as e:
                                logger.debug(f"Non-critical: {e}")
                                entry_price = 0.0
                            if entry_price <= 0:
                                continue
                            try:
                                tick_value = float(sig.get("tick_value") or 2.0)
                            except Exception as e:
                                logger.debug(f"Non-critical: {e}")
                                tick_value = 2.0
                            try:
                                position_size = float(sig.get("position_size") or 1.0)
                            except Exception as e:
                                logger.debug(f"Non-critical: {e}")
                                position_size = 1.0

                            pnl_pts = (current_price - entry_price) if direction == "long" else (entry_price - current_price)
                            total_upnl += float(pnl_pts) * float(tick_value) * float(position_size)

                        status["active_trades_unrealized_pnl"] = float(total_upnl)

                # Recent exits (compact transparency list for dashboards).
                try:
                    exited = []
                    for rec in recent_signals:
                        if not isinstance(rec, dict) or rec.get("status") != "exited":
                            continue
                        pnl = rec.get("pnl")
                        if pnl is None:
                            continue
                        sig = rec.get("signal", {}) or {}
                        exited.append(
                            {
                                "signal_id": str(rec.get("signal_id") or ""),
                                "type": str(sig.get("type") or "unknown"),
                                "direction": str(sig.get("direction") or "long"),
                                "pnl": pnl,
                                "exit_reason": str(rec.get("exit_reason") or ""),
                                "exit_time": rec.get("exit_time") or rec.get("timestamp") or sig.get("timestamp"),
                            }
                        )
                    # Keep only the most recent few (signals.jsonl is append-only, so reverse is safe)
                    exited = list(reversed(exited))[:3]
                    if exited:
                        status["recent_exits"] = exited
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
            except Exception as e:
                # Never let optional PnL UI break dashboard delivery.
                logger.debug(f"Non-critical: {e}")
            
            # Get recent closes for sparkline
            recent_closes = self._get_recent_closes(market_data)
            status["recent_closes"] = recent_closes
            
            # Get MTF trend arrows
            mtf_trends = self._compute_mtf_trends(market_data)
            status["mtf_trends"] = mtf_trends

            # Buy/Sell pressure (volume-based proxy) for 15m dashboard notifications
            try:
                df_for_pressure = None
                if market_data and "df" in market_data and market_data["df"] is not None:
                    df_for_pressure = market_data["df"]
                elif getattr(self.data_fetcher, "_data_buffer", None) is not None:
                    df_for_pressure = getattr(self.data_fetcher, "_data_buffer")

                if isinstance(df_for_pressure, pd.DataFrame) and not df_for_pressure.empty:
                    summary = compute_volume_pressure_summary(
                        df_for_pressure,
                        lookback_bars=self.pressure_lookback_bars,
                        baseline_bars=self.pressure_baseline_bars,
                        open_col="open",
                        close_col="close",
                        volume_col="volume",
                    )
                    if summary is not None:
                        tf_min = timeframe_to_minutes(getattr(self.config, "timeframe", "") or "")
                        status["buy_sell_pressure_raw"] = summary.to_dict()
                        status["buy_sell_pressure"] = format_volume_pressure(
                            summary,
                            timeframe_minutes=tf_min,
                            data_fresh=status.get("data_fresh"),
                        )
            except Exception as e:
                # Never let optional observability break the dashboard.
                logger.debug(f"Non-critical: {e}")
            
            await self.notification_queue.enqueue_dashboard(status, chart_path=chart_path, priority=Priority.LOW)
        except Exception as e:
            logger.error(f"Error queuing dashboard: {e}", exc_info=True)
    
    # _get_recent_closes and _get_trades_for_chart are inherited from ServiceNotificationsMixin

    def _compute_mtf_trends(self, market_data: Optional[Dict] = None) -> dict:
        """
        Compute compact trend arrows for multiple timeframes.
        
        Uses df_5m and df_15m from market_data for accurate MTF trends,
        regardless of the base decision timeframe (1m/5m).
        
        Returns dict mapping timeframe -> slope value for trend_arrow() conversion.
        """
        trends = {}
        
        try:
            # 5m trend from df_5m (explicit MTF data, not base buffer)
            if market_data and "df_5m" in market_data:
                df_5m = market_data["df_5m"]
                if df_5m is not None and not df_5m.empty and "close" in df_5m.columns and len(df_5m) >= 10:
                    closes = df_5m["close"].tail(10)
                    if len(closes) >= 2 and closes.iloc[0] != 0:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["5m"] = float(slope)
            
            # 15m trend from df_15m
            if market_data and "df_15m" in market_data:
                df_15m = market_data["df_15m"]
                if df_15m is not None and not df_15m.empty and "close" in df_15m.columns and len(df_15m) >= 5:
                    closes = df_15m["close"].tail(5)
                    if len(closes) >= 2 and closes.iloc[0] != 0:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["15m"] = float(slope)
            
            # Compute longer timeframes from 15m data (higher TF = fewer bars needed)
            if market_data and "df_15m" in market_data:
                df_15m = market_data["df_15m"]
                if df_15m is not None and not df_15m.empty and "close" in df_15m.columns:
                    # 1h: look at 4 bars of 15m data
                    if len(df_15m) >= 4:
                        closes_1h = df_15m["close"].tail(4)
                        if len(closes_1h) >= 2 and closes_1h.iloc[0] != 0:
                            slope = (closes_1h.iloc[-1] - closes_1h.iloc[0]) / closes_1h.iloc[0] * 100
                            trends["1h"] = float(slope)
                    
                    # 4h: look at 16 bars of 15m data
                    if len(df_15m) >= 16:
                        closes_4h = df_15m["close"].tail(16)
                        if len(closes_4h) >= 2 and closes_4h.iloc[0] != 0:
                            slope = (closes_4h.iloc[-1] - closes_4h.iloc[0]) / closes_4h.iloc[0] * 100
                            trends["4h"] = float(slope)
                    
                    # 1D: look at all available 15m data (up to 96 bars = 24h)
                    if len(df_15m) >= 20:
                        closes_1d = df_15m["close"].tail(min(96, len(df_15m)))
                        if len(closes_1d) >= 2 and closes_1d.iloc[0] != 0:
                            slope = (closes_1d.iloc[-1] - closes_1d.iloc[0]) / closes_1d.iloc[0] * 100
                            trends["1D"] = float(slope)
        except Exception as e:
            logger.debug(f"Could not compute MTF trends: {e}")
        
        return trends

    def _compute_effective_interval(self) -> float:
        """
        Compute the effective scan interval based on current market/session state.
        
        Adaptive cadence profile (fast-active + velocity):
        - paused: scan_interval_paused_seconds (60s default)
        - futures_market_closed: scan_interval_market_closed_seconds (300s default)
        - futures_open, strategy_session_closed: scan_interval_idle_seconds (30s default)
        - strategy_session_open: scan_interval_active_seconds (5s default)
        - VELOCITY MODE: scan_interval_velocity_seconds (1.5s) when ATR expands or volume spikes
        
        Uses cached latest_bar timestamp when available to reduce wall-clock drift.
        
        Returns:
            Effective interval in seconds.
        """
        # If adaptive cadence is disabled, use base config interval
        if not self._adaptive_cadence_enabled:
            return float(self.config.scan_interval)
        
        # Priority 1: paused state
        if self.paused:
            self._velocity_mode_active = False
            return self._scan_interval_paused
        
        # Priority 2: check futures market
        futures_open = False
        try:
            futures_open = bool(get_market_hours().is_market_open())
        except Exception as e:
            logger.warning(f"Market hours check failed in MTF trends: {e}")
            # If market hours check fails, assume open (conservative)
            futures_open = True
        
        if not futures_open:
            self._velocity_mode_active = False
            return self._scan_interval_market_closed
        
        # Priority 3: check strategy session (prefer cached bar time over wall-clock)
        bar_time: Optional[datetime] = None
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            latest_bar = last_market_data.get("latest_bar")
            if latest_bar and isinstance(latest_bar, dict):
                raw_ts = latest_bar.get("timestamp")
                if raw_ts:
                    if isinstance(raw_ts, str):
                        bar_time = parse_utc_timestamp(raw_ts)
                    else:
                        bar_time = raw_ts
                    if bar_time and bar_time.tzinfo is None:
                        bar_time = bar_time.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.warning(f"Failed to parse bar timestamp in MTF trends: {e}")
            bar_time = None
        
        session_open = False
        try:
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            session_open = check_trading_session(bar_time, self.config) if bar_time else False
        except Exception as e:
            logger.warning(f"Session check failed in MTF trends: {e}")
            # If session check fails, assume closed (conservative)
            session_open = False
        
        # Priority 4: velocity mode (only when session is open + velocity conditions met)
        # Check ATR expansion and volume spike to trigger ultra-fast scans (1-2s)
        if session_open and self._velocity_mode_enabled:
            velocity_reason = self._check_velocity_conditions()
            if velocity_reason:
                self._velocity_mode_active = True
                # Update cadence scheduler with velocity reason for observability
                if self.cadence_scheduler:
                    self.cadence_scheduler.set_interval(
                        self._scan_interval_velocity,
                        velocity_mode=True,
                        velocity_reason=velocity_reason
                    )
                logger.info(
                    f"🚀 Velocity mode ACTIVE: {velocity_reason} | interval: {self._scan_interval_velocity}s",
                    extra={"velocity_reason": velocity_reason, "interval": self._scan_interval_velocity}
                )
                return self._scan_interval_velocity
        
        # Default: return session-appropriate interval
        self._velocity_mode_active = False
        if session_open:
            return self._scan_interval_active
        else:
            return self._scan_interval_idle
    
    def _check_velocity_conditions(self) -> str:
        """
        Check if velocity mode should be active (fast market moves).
        
        Velocity triggers:
        - ATR expansion (20%+ increase in ATR vs 5 bars ago)
        - Volume spike (2x+ recent average)
        
        Returns:
            Reason string if velocity should be active, empty string otherwise.
        """
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            df = last_market_data.get("df")
            if df is None or df.empty or len(df) < 20:
                return ""
            
            latest = df.iloc[-1]
            
            # Check ATR expansion (20%+ increase)
            if "atr" in df.columns and len(df) >= 6:
                current_atr = float(latest.get("atr", 0) or 0)
                atr_5bars_ago = float(df.iloc[-6].get("atr", 0) or 0)
                if current_atr > 0 and atr_5bars_ago > 0:
                    atr_ratio = current_atr / atr_5bars_ago
                    if atr_ratio >= self._velocity_atr_expansion_threshold:
                        return f"atr_expansion_{atr_ratio:.2f}x"
            
            # Check volume spike (2x+ recent average)
            if "volume" in df.columns and len(df) >= 20:
                current_volume = float(latest.get("volume", 0) or 0)
                recent_avg_volume = float(df["volume"].tail(20).mean() or 0)
                if current_volume > 0 and recent_avg_volume > 0:
                    volume_ratio = current_volume / recent_avg_volume
                    if volume_ratio >= self._velocity_volume_spike_threshold:
                        return f"volume_spike_{volume_ratio:.2f}x"
            
            return ""
        except Exception as e:
            logger.debug(f"Velocity condition check failed (non-fatal): {e}")
            return ""

    def _compute_quiet_period_minutes(self) -> Optional[float]:
        """
        Compute how long since the last signal was generated.
        
        Returns:
            Minutes since last signal, or None if no signals generated yet.
        """
        if not self.last_signal_generated_at:
            return None
        try:
            # Parse the ISO timestamp
            if isinstance(self.last_signal_generated_at, str):
                last_signal_dt = datetime.fromisoformat(self.last_signal_generated_at.replace("Z", "+00:00"))
            else:
                last_signal_dt = self.last_signal_generated_at
            
            if last_signal_dt.tzinfo is None:
                last_signal_dt = last_signal_dt.replace(tzinfo=timezone.utc)
            
            delta = datetime.now(timezone.utc) - last_signal_dt
            return round(delta.total_seconds() / 60.0, 2)
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            return None

    def _get_quiet_reason(
        self,
        market_data: Optional[Dict] = None,
        has_data: bool = True,
        no_signals: bool = False,
    ) -> str:
        """
        Determine why the agent is quiet (not generating signals).
        
        Returns a human-readable reason for observability.
        
        Args:
            market_data: Current market data
            has_data: Whether we have any data (False = empty DataFrame)
            no_signals: Whether we had data but no signals were generated
            
        Returns:
            String reason code like "StrategySessionClosed", "FuturesMarketClosed", etc.
        """
        try:
            # Extract latest_bar timestamp for session check (prefer bar time over wall-clock)
            bar_time: Optional[datetime] = None
            if market_data and market_data.get("latest_bar"):
                raw_ts = market_data["latest_bar"].get("timestamp")
                if raw_ts:
                    if isinstance(raw_ts, str):
                        bar_time = parse_utc_timestamp(raw_ts)
                    else:
                        bar_time = raw_ts
                    if bar_time and bar_time.tzinfo is None:
                        bar_time = bar_time.replace(tzinfo=timezone.utc)
            
            # Check strategy session first (more specific)
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            check_time = bar_time if bar_time else datetime.now(timezone.utc)
            strategy_session_open = check_trading_session(check_time, self.config)
            if not strategy_session_open:
                return "StrategySessionClosed"
            
            # Check futures market hours
            futures_market_open = get_market_hours().is_market_open()
            if not futures_market_open:
                return "FuturesMarketClosed"
            
            # Check if we have no data
            if not has_data or (market_data and market_data.get("df") is not None and market_data["df"].empty):
                # Could be a data gap or stale data
                if self.last_successful_cycle:
                    time_since_success = (datetime.now(timezone.utc) - self.last_successful_cycle).total_seconds()
                    if time_since_success > self.stale_data_threshold_minutes * 60:
                        return "StaleData"
                    elif time_since_success > 60:
                        return "DataGap"
                return "NoData"
            
            # We have data but no signals
            if no_signals:
                # Check data freshness
                latest_bar = market_data.get("latest_bar") if market_data else None
                if latest_bar:
                    bar_time = latest_bar.get("timestamp")
                    if bar_time:
                        if isinstance(bar_time, str):
                            bar_time = parse_utc_timestamp(bar_time)
                        # Timezone-safe age computation: convert to UTC if aware, assume UTC if naive
                        if bar_time.tzinfo is None:
                            bar_time = bar_time.replace(tzinfo=timezone.utc)
                        else:
                            bar_time = bar_time.astimezone(timezone.utc)
                        age_seconds = (datetime.now(timezone.utc) - bar_time).total_seconds()
                        if age_seconds > self.stale_data_threshold_minutes * 60:
                            return "StaleData"
                    
                    # NOTE: It's common to have fresh 1m bars even when _data_level is "historical"
                    # (e.g., IBKR historical bars feed updating continuously). This should NOT be used
                    # as the primary "quiet reason" because it doesn't explain why patterns weren't found.
                    # Surface feed type in Data Quality instead; keep quiet reason focused on opportunity.
                
                # No signals but data is fresh - strategy just didn't find opportunities
                return "NoOpportunity"
            
            return "Active"
            
        except Exception as e:
            logger.debug(f"Could not determine quiet reason: {e}")
            return "Unknown"

    def pause(self) -> None:
        """Pause the service."""
        self.paused = True
        self.pause_reason = "manual"
        logger.info("Service paused", extra={"pause_reason": self.pause_reason})

    def resume(self) -> None:
        """Resume the service."""
        self.paused = False
        self.pause_reason = None
        # Reset circuit breaker notification guard so a fresh CB event can notify again
        self.connection_failures = 0
        self._cb_connection_notified = False
        # Reset cadence scheduler to avoid catch-up storm
        if self.cadence_scheduler:
            self.cadence_scheduler.reset()
        logger.info("Service resumed")

    async def _sleep_until_next_cycle(self) -> None:
        """
        Sleep until the next cycle should start.
        
        In fixed-cadence mode, computes sleep time to maintain start-to-start timing.
        In legacy mode, sleeps for the full scan_interval after work completes.
        
        SAFETY: Breaks long sleeps into 5-second chunks to check control flags
        (kill/disarm/arm) promptly, even when scan_interval_market_closed is long.
        """
        if self.cadence_scheduler:
            # Fixed-cadence mode: compute sleep time based on cycle end
            sleep_time = self.cadence_scheduler.mark_cycle_end()
            metrics = self.cadence_scheduler.get_metrics()
            
            # Log if we're running behind schedule
            if metrics.missed_cycles > 0:
                logger.debug(
                    f"Cadence: {metrics.cycle_duration_ms:.0f}ms work, "
                    f"sleeping {sleep_time*1000:.0f}ms, "
                    f"{metrics.missed_cycles} cycles skipped total"
                )
            
            # SAFETY: Break long sleeps into chunks to check control flags promptly
            await self._interruptible_sleep(sleep_time)
        else:
            # Legacy mode: sleep full interval after work
            await self._interruptible_sleep(self.config.scan_interval)
    
    async def _interruptible_sleep(self, total_seconds: float) -> None:
        """
        Sleep for the specified duration, checking control flags every 5 seconds.
        
        This ensures kill/disarm commands are processed promptly even during
        long sleep intervals (e.g., market_closed = 300s).
        
        Args:
            total_seconds: Total sleep duration in seconds
        """
        FLAG_CHECK_INTERVAL = 5.0  # Check flags every 5 seconds
        
        remaining = total_seconds
        while remaining > 0 and not self.shutdown_requested:
            chunk = min(remaining, FLAG_CHECK_INTERVAL)
            await asyncio.sleep(chunk)
            remaining -= chunk
            
            # Check for control flags during long sleeps
            if remaining > 0:
                await self._check_execution_control_flags()

    async def _notify_error(self, title: str, message: str) -> None:
        """Notify about errors via Telegram (through notification queue)."""
        try:
            if self.telegram_notifier.enabled and self.telegram_notifier.telegram:
                acct_label = getattr(self.telegram_notifier, "account_label", None)
                acct_tag = f"[{acct_label}] " if acct_label else ""
                await self.notification_queue.enqueue_risk_warning(
                    f"{acct_tag}{title}\n\n{message}",
                    risk_status="ERROR",
                    priority=Priority.CRITICAL,
                )
        except Exception as e:
            logger.error(f"Error queuing error notification: {e}")

    def _check_daily_reset(self) -> None:
        """Reset execution daily counters at start of new trading day.

        Delegated to ExecutionOrchestrator.check_daily_reset().
        """
        self.execution_orchestrator.check_daily_reset()

    async def _check_execution_health(self) -> None:
        """Check execution adapter connection health and send alerts on state changes.

        Delegated to ExecutionOrchestrator.check_execution_health().
        """
        await self.execution_orchestrator.check_execution_health()

    async def _check_execution_control_flags(self) -> None:
        """
        Check for execution control flag files (from Telegram commands).
        
        Flag files:
        - arm_request.flag: Arm the execution adapter
        - disarm_request.flag: Disarm the execution adapter
        - kill_request.flag: Disarm, cancel all orders, flatten positions, and close virtual trades
        
        Safety features:
        - Flags older than FLAG_TTL_SECONDS are ignored and deleted (prevents stale flags)
        - Flags are always cleared even when execution_adapter is None (prevents accumulation)
        """
        FLAG_TTL_SECONDS = 300  # 5 minutes - ignore flags older than this
        
        def _is_flag_stale(flag_file: Path) -> bool:
            """Check if a flag file is stale (older than TTL)."""
            try:
                content = flag_file.read_text()
                # Parse timestamp from "xxx_requested_at=2025-01-01T00:00:00+00:00"
                if "requested_at=" in content:
                    ts_str = content.split("requested_at=")[1].strip()
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
                    return age_seconds > FLAG_TTL_SECONDS
                # If no timestamp, check file modification time
                mtime = datetime.fromtimestamp(flag_file.stat().st_mtime, tz=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - mtime).total_seconds()
                return age_seconds > FLAG_TTL_SECONDS
            except Exception as e:
                logger.warning(f"Failed to determine flag staleness in execution control: {e}")
                # If we can't determine age, treat as stale for safety
                return True
        
        try:
            state_dir = self.state_manager.state_dir

            # ==========================================================================
            # Process operator requests (web UI feedback, shadow-only)
            # ==========================================================================
            try:
                await self.operator_handler.process_operator_requests(state_dir)
            except Exception as e:
                logger.debug(f"Operator requests processing failed (non-fatal): {e}")

            # ==========================================================================
            # Ingest close-trade requests & close-all flag from web API
            # ==========================================================================
            try:
                await self.operator_handler.process_close_trade_requests(state_dir)
            except Exception as e:
                logger.debug(f"Close-trade request ingestion failed (non-fatal): {e}")
            try:
                await self.operator_handler.process_close_all_flag(state_dir)
            except Exception as e:
                logger.debug(f"Close-all flag ingestion failed (non-fatal): {e}")

            # Define flag files
            kill_file = state_dir / "kill_request.flag"
            disarm_file = state_dir / "disarm_request.flag"
            arm_file = state_dir / "arm_request.flag"
            
            # ==========================================================================
            # Always clear stale flags (prevents accumulation when adapter is disabled)
            # ==========================================================================
            for flag_file in [kill_file, disarm_file, arm_file]:
                if flag_file.exists() and _is_flag_stale(flag_file):
                    logger.warning(f"Clearing stale flag file: {flag_file.name} (older than {FLAG_TTL_SECONDS}s)")
                    flag_file.unlink(missing_ok=True)

            # Use last known market data for close/flatten helpers (best-effort).
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            if not isinstance(last_market_data, dict):
                last_market_data = {}
            
            # ==========================================================================
            # If execution adapter is None, clear any remaining flags and warn
            # ==========================================================================
            if self.execution_adapter is None:
                # Kill switch still closes virtual trades even if execution is disabled.
                if kill_file.exists():
                    logger.warning("🚨 KILL flag detected but execution adapter is disabled - closing virtual trades only")
                    closed_virtual = 0
                    close_err: Optional[str] = None
                    try:
                        closed_virtual, _ = await self._close_all_virtual_trades(
                            market_data=last_market_data,
                            reason="kill_switch",
                            notify=False,
                        )
                    except Exception as e:
                        close_err = str(e)
                        logger.error(f"Kill switch (no execution adapter): failed to close virtual trades: {e}", exc_info=True)
                    finally:
                        kill_file.unlink(missing_ok=True)

                    try:
                        err_note = f"\n⚠️ Close error: `{close_err[:80]}`" if close_err else ""
                        await self.notification_queue.enqueue_raw_message(
                            "🚨 *KILL SWITCH EXECUTED*\n\n"
                            "Execution adapter: `DISABLED`\n"
                            f"Closed Trades: `{closed_virtual}` (virtual){err_note}",
                            parse_mode="Markdown",
                            priority=Priority.CRITICAL,
                            dedupe=False,
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")

                # Arm/disarm are execution-only; clear + warn if requested.
                for flag_file, action in [(disarm_file, "disarm"), (arm_file, "arm")]:
                    if flag_file.exists():
                        logger.warning(
                            f"Clearing {action} flag - execution adapter is disabled. "
                            f"Enable execution.enabled in config to use /arm, /disarm, /kill commands."
                        )
                        flag_file.unlink(missing_ok=True)
                        # Notify user that the command was ignored (through notification queue)
                        try:
                            await self.notification_queue.enqueue_raw_message(
                                f"⚠️ *{action.upper()} IGNORED*\n\n"
                                f"Execution adapter is disabled.\n"
                                f"Set `execution.enabled: true` in config and restart to enable ATS.",
                                parse_mode="Markdown",
                                priority=Priority.NORMAL,
                            )
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}")
                return
            
            # ==========================================================================
            # Process kill flag (highest priority)
            # ==========================================================================
            if kill_file.exists():
                logger.warning("🚨 KILL flag detected - cancelling orders, flattening positions, and disarming")
                cancelled_order_ids: list[str] = []
                cancel_errors: list[str] = []
                flattened_order_ids: list[str] = []
                flatten_errors: list[str] = []
                closed_virtual = 0
                close_virtual_err: Optional[str] = None
                try:
                    # SAFETY: Disarm FIRST to prevent new orders while cancelling
                    self.execution_adapter.disarm()
                    logger.warning("Kill switch: execution adapter disarmed")
                    
                    # Cancel all open orders
                    cancel_results = await self.execution_adapter.cancel_all()
                    cancelled_order_ids = [
                        str(r.order_id) for r in cancel_results
                        if r.success and r.order_id
                    ]
                    cancel_errors = [r.error_message for r in cancel_results if not r.success and r.error_message]
                    logger.warning(f"Kill switch: cancelled {len(cancelled_order_ids)} orders")
                    if cancel_errors:
                        logger.warning(f"Kill switch: {len(cancel_errors)} cancellation errors: {cancel_errors[:3]}")

                    # Flatten open broker positions (market orders)
                    flatten_results = await self.execution_adapter.flatten_all_positions()
                    flattened_order_ids = [
                        str(r.order_id) for r in flatten_results
                        if r.success and r.order_id
                    ]
                    flatten_errors = [r.error_message for r in flatten_results if not r.success and r.error_message]
                    logger.warning(f"Kill switch: submitted {len(flattened_order_ids)} flatten order(s)")
                    if flatten_errors:
                        logger.warning(f"Kill switch: {len(flatten_errors)} flatten errors: {flatten_errors[:3]}")
                except Exception as e:
                    logger.error(f"Error executing kill switch: {e}", exc_info=True)
                    # Even if cancel_all fails, ensure we're disarmed
                    try:
                        self.execution_adapter.disarm()
                    except Exception as e:
                        logger.warning(f"Critical path error: {e}", exc_info=True)
                finally:
                    kill_file.unlink(missing_ok=True)
                    # Also remove any pending disarm flag (kill already disarms)
                    disarm_file.unlink(missing_ok=True)

                # Close all virtual trades (best-effort; uses last known market data)
                try:
                    closed_virtual, _ = await self._close_all_virtual_trades(
                        market_data=last_market_data,
                        reason="kill_switch",
                        notify=False,
                    )
                except Exception as e:
                    close_virtual_err = str(e)
                    logger.error(f"Kill switch: failed to close virtual trades: {e}", exc_info=True)
                    
                # Notify via Telegram (through notification queue)
                try:
                    errors_total = len(cancel_errors) + len(flatten_errors) + (1 if close_virtual_err else 0)
                    error_note = f"\n⚠️ Errors: {errors_total}" if errors_total else ""
                    first_err = None
                    if cancel_errors:
                        first_err = cancel_errors[0]
                    elif flatten_errors:
                        first_err = flatten_errors[0]
                    elif close_virtual_err:
                        first_err = close_virtual_err
                    first_err_note = f"\n`{str(first_err)[:80]}`" if first_err else ""
                    await self.notification_queue.enqueue_raw_message(
                        f"🚨 *KILL SWITCH EXECUTED*\n\n"
                        f"Cancelled Orders: `{len(cancelled_order_ids)}`\n"
                        f"Flattened Positions: `{len(flattened_order_ids)}`\n"
                        f"Closed Trades: `{closed_virtual}` (virtual)\n"
                        f"Execution: `DISARMED`{error_note}{first_err_note}",
                        parse_mode="Markdown",
                        priority=Priority.CRITICAL,
                        dedupe=False,
                    )
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
                return  # Skip arm/disarm after kill
            
            # ==========================================================================
            # Process disarm flag
            # ==========================================================================
            if disarm_file.exists():
                logger.info("🔒 DISARM flag detected - disarming execution adapter")
                self.execution_adapter.disarm()
                disarm_file.unlink(missing_ok=True)
                
                # Notify via Telegram (through notification queue)
                try:
                    await self.notification_queue.enqueue_raw_message(
                        "🔒 *Execution DISARMED*\n\n"
                        "No new orders will be placed.",
                        parse_mode="Markdown",
                        priority=Priority.HIGH,
                    )
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
                return  # Skip arm after disarm
            
            # ==========================================================================
            # Process arm flag
            # ==========================================================================
            if arm_file.exists():
                logger.info("🔫 ARM flag detected - arming execution adapter")
                success = self.execution_adapter.arm()
                arm_file.unlink(missing_ok=True)
                
                if success:
                    # Notify via Telegram (through notification queue)
                    try:
                        mode = self._execution_config.mode.value if self._execution_config else "unknown"
                        await self.notification_queue.enqueue_raw_message(
                            f"🔫 *Execution ARMED*\n\n"
                            f"Mode: `{mode}`\n"
                            f"Orders will be placed for signals.\n\n"
                            f"⚠️ Use `/disarm` to stop or `/kill` to cancel all.",
                            parse_mode="Markdown",
                            priority=Priority.HIGH,
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")
                else:
                    logger.warning("Could not arm execution adapter - preconditions not met")
                    try:
                        await self.notification_queue.enqueue_raw_message(
                            "⚠️ *ARM FAILED*\n\n"
                            "Could not arm execution adapter.\n"
                            "Check that execution is enabled in config.",
                            parse_mode="Markdown",
                            priority=Priority.HIGH,
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")
            
            # ==========================================================================
            # Process grade request (manual feedback for learning)
            # ==========================================================================
            grade_file = state_dir / "grade_request.json"
            if grade_file.exists():
                await self.operator_handler.process_grade_request(grade_file)
                        
        except Exception as e:
            logger.error(f"Error checking execution control flags: {e}", exc_info=True)

    def get_status(self) -> Dict:
        """Get current service status."""
        uptime = None
        if self.start_time:
            uptime_delta = datetime.now(timezone.utc) - self.start_time
            uptime = {
                "hours": int(uptime_delta.total_seconds() / 3600),
                "minutes": int((uptime_delta.total_seconds() % 3600) / 60),
            }

        # Get performance metrics
        performance = self.performance_tracker.get_performance_metrics(days=7)

        # Get health status
        health = self.health_monitor.get_overall_health(
            data_provider=self.data_fetcher.data_provider,
            telegram_notifier=self.telegram_notifier,
        )

        # Extract data source health
        data_source_health = health.get("components", {}).get("data_provider", {})

        # Check connection status
        connection_status = "unknown"
        try:
            if hasattr(self.data_fetcher.data_provider, '_executor'):
                executor = self.data_fetcher.data_provider._executor
                if hasattr(executor, 'is_connected'):
                    connection_status = "connected" if executor.is_connected() else "disconnected"
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        # Get latest bar for order book info
        latest_bar = None
        try:
            # Try to get latest market data (non-blocking)
            if hasattr(self, 'data_fetcher'):
                # Get the last fetched market data if available
                if hasattr(self.data_fetcher, '_last_market_data'):
                    market_data = self.data_fetcher._last_market_data
                    latest_bar = market_data.get("latest_bar")
        except Exception as e:
            logger.debug(f"Non-critical: {e}")  # Ignore errors when getting latest bar for status

        # Market/session status
        futures_market_open = None
        try:
            futures_market_open = bool(get_market_hours().is_market_open())
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            futures_market_open = None

        strategy_session_open = None
        try:
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            strategy_session_open = check_trading_session(datetime.now(timezone.utc), self.config)
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            strategy_session_open = None

        return {
            "running": self.running,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime": uptime,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "signals_sent": self.signals_sent,
            "signals_send_failures": self.signals_send_failures,
            "last_signal_send_error": self.last_signal_send_error,
            "last_signal_generated_at": self.last_signal_generated_at,
            "last_signal_sent_at": self.last_signal_sent_at,
            "last_signal_id_prefix": self.last_signal_id_prefix,
            "cycle_count_session": (
                (self.cycle_count - self._cycle_count_at_start)
                if self._cycle_count_at_start is not None
                else None
            ),
            "signal_count_session": (
                (self.signal_count - self._signal_count_at_start)
                if self._signal_count_at_start is not None
                else None
            ),
            "signals_sent_session": (
                (self.signals_sent - self._signals_sent_at_start)
                if self._signals_sent_at_start is not None
                else None
            ),
            "signals_send_failures_session": (
                (self.signals_send_failures - self._signals_fail_at_start)
                if self._signals_fail_at_start is not None
                else None
            ),
            "latest_bar": latest_bar,  # Include for order book transparency
            "error_count": self.error_count,
            "connection_failures": self.connection_failures,
            "connection_status": connection_status,
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "buffer_size_target": self.buffer_size_target,
            "futures_market_open": futures_market_open,
            "strategy_session_open": strategy_session_open,
            "performance": performance,
            "data_source_health": data_source_health,
            # Cache stats for observability
            "cache_stats": self.data_fetcher.get_cache_stats(),
            # New-bar gating stats (performance optimization observability)
            "new_bar_gating": {
                "enabled": self._enable_new_bar_gating,
                "analysis_skips": self._analysis_skip_count,
                "analysis_runs": self._analysis_run_count,
                "skip_rate": round(
                    self._analysis_skip_count / max(1, self._analysis_skip_count + self._analysis_run_count),
                    3,
                ),
                "last_analyzed_bar_ts": (
                    self._last_analyzed_bar_ts.isoformat()
                    if self._last_analyzed_bar_ts
                    else None
                ),
            },
            "last_successful_cycle": (
                self.last_successful_cycle.isoformat() if self.last_successful_cycle else None
            ),
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
                # Session window (for Telegram UI observability)
                "session_start_time": getattr(self.config, "start_time", "18:00"),
                "session_end_time": getattr(self.config, "end_time", "16:10"),
                # Adaptive cadence config
                "adaptive_cadence_enabled": self._adaptive_cadence_enabled,
                "scan_interval_effective": self._effective_interval,
            },
            "telegram_ui": {
                "compact_metrics_enabled": getattr(self, "_telegram_ui_compact_metrics_enabled", True),
                "show_progress_bars": getattr(self, "_telegram_ui_show_progress_bars", False),
                "show_volume_metrics": getattr(self, "_telegram_ui_show_volume_metrics", True),
                "compact_metric_width": getattr(self, "_telegram_ui_compact_metric_width", 10),
            },
            # Cadence metrics for observability
            "cadence_mode": "adaptive" if self._adaptive_cadence_enabled else self.cadence_mode,
            "cadence_metrics": (
                self.cadence_scheduler.get_metrics().to_dict()
                if self.cadence_scheduler
                else None
            ),
            # Execution status (ATS)
            "execution": (
                self.execution_adapter.get_status()
                if self.execution_adapter is not None
                else {"enabled": False, "armed": False, "mode": "disabled"}
            ),
            # Learning/policy status (WS8: delegated to MLManager)
            "learning": self._ml_manager.get_learning_status(),
            "learning_contextual": self._ml_manager.get_contextual_status(),
            "ml_filter": self._ml_manager.get_filter_status(),
        }

    def _persist_cycle_diagnostics(
        self,
        *,
        quiet_reason: Optional[str],
        diagnostics_raw: Optional[Dict],
    ) -> None:
        """
        Persist per-cycle observability to SQLite (best-effort, non-blocking if async enabled).

        This enables 24h rollups (e.g. Telegram /doctor) without parsing log files.
        """
        try:
            if not getattr(self, "_sqlite_enabled", False) or self._trade_db is None:
                return
            ts = get_utc_timestamp()
            
            # Async write if enabled (non-blocking)
            if self._async_writes_enabled and self._async_sqlite_queue is not None:
                from pearlalgo.storage.async_sqlite_queue import WritePriority
                
                self._async_sqlite_queue.enqueue(
                    "add_cycle_diagnostics",
                    priority=WritePriority.LOW,  # Cycle diagnostics are lowest priority (drop first if queue full)
                    timestamp=ts,
                    cycle_count=int(getattr(self, "cycle_count", 0) or 0),
                    quiet_reason=str(quiet_reason) if quiet_reason is not None else None,
                    diagnostics=diagnostics_raw or {},
                )
            else:
                # Blocking write (legacy path)
                self._trade_db.add_cycle_diagnostics(
                    timestamp=ts,
                    cycle_count=int(getattr(self, "cycle_count", 0) or 0),
                    quiet_reason=str(quiet_reason) if quiet_reason is not None else None,
                    diagnostics=diagnostics_raw or {},
                )
        except Exception as e:
            # Never allow observability writes to affect runtime.
            logger.debug(f"Could not persist cycle diagnostics to SQLite: {e}")

    def _build_ml_training_trades_from_signals(self, *, limit: int = 2000) -> list[dict]:
        """Build supervised training samples.

        Delegated to SignalOrchestrator.build_ml_training_trades_from_signals().
        """
        return self.signal_orchestrator.build_ml_training_trades_from_signals(limit=limit)

    async def _build_ml_training_trades_from_signals_async(self, *, limit: int = 2000) -> list[dict]:
        """Async wrapper.

        Delegated to SignalOrchestrator.build_ml_training_trades_from_signals_async().
        """
        return await self.signal_orchestrator.build_ml_training_trades_from_signals_async(limit=limit)

    def _compute_ml_lift_metrics(self, trades: list) -> Dict[str, Any]:
        """Compute shadow A/B lift for ML gating.

        Delegated to SignalOrchestrator.compute_ml_lift_metrics().
        """
        return self.signal_orchestrator.compute_ml_lift_metrics(trades)

    def _refresh_ml_lift(self, *, force: bool = False) -> None:
        """Refresh ML lift metrics + blocking allowance.

        Delegated to SignalOrchestrator.refresh_ml_lift().
        """
        self.signal_orchestrator.refresh_ml_lift(force=force)

    @staticmethod
    def _parse_hhmm(value: Any, *, default: tuple[int, int]) -> tuple[int, int]:
        """Parse HH:MM string into (hour, minute), fallback to default."""
        if isinstance(value, str):
            parts = value.strip().split(":")
            if len(parts) == 2:
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return hour, minute
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")
        return default

    def _get_active_virtual_trades(self, *, limit: int = 300) -> list[dict]:
        """Return active virtual trades (signals.jsonl status=entered)."""
        try:
            recent_signals = self.state_manager.get_recent_signals(limit=limit)
        except Exception as e:
            logger.warning(f"Failed to retrieve active virtual trades: {e}")
            return []
        active: list[dict] = []
        for rec in recent_signals:
            if isinstance(rec, dict) and rec.get("status") == "entered":
                active.append(rec)
        return active

    def _resolve_latest_prices(self, market_data: Optional[Dict]) -> dict:
        """Resolve latest bid/ask/close prices from market_data or cached data."""
        latest_bar = None
        if isinstance(market_data, dict):
            latest_bar = market_data.get("latest_bar")
        if not isinstance(latest_bar, dict):
            try:
                cached = getattr(self.data_fetcher, "_last_market_data", None) or {}
                latest_bar = cached.get("latest_bar")
            except Exception as e:
                logger.warning(f"Failed to resolve latest bar data: {e}")
                latest_bar = None
        if not isinstance(latest_bar, dict):
            return {"close": None, "bid": None, "ask": None, "source": None}

        def _f(v: Any) -> Optional[float]:
            try:
                out = float(v)
                return out if out > 0 else None
            except Exception as e:
                logger.warning(f"Failed to parse latest price: {e}")
                return None

        close_px = _f(latest_bar.get("close"))
        bid_px = _f(latest_bar.get("bid"))
        ask_px = _f(latest_bar.get("ask"))
        source = latest_bar.get("_data_level") or latest_bar.get("_data_source")
        return {
            "close": close_px,
            "bid": bid_px,
            "ask": ask_px,
            "source": str(source) if source is not None else None,
        }

    def _auto_flat_due(self, now_utc: datetime, *, market_open: Optional[bool]) -> Optional[str]:
        """Return auto-flat reason if daily/Friday/weekend rule should trigger."""
        try:
            tz = ZoneInfo(self._auto_flat_timezone)
        except Exception as e:
            logger.warning(f"Failed to parse auto-flat timezone: {e}")
            tz = ZoneInfo("America/New_York")

        local_now = now_utc.astimezone(tz)
        weekday = local_now.weekday()  # 0=Mon .. 6=Sun

        # Daily auto-flat is gated by the master toggle; Friday/weekend are safety rules
        # that may remain enabled even when daily auto-flat is disabled.
        if self._auto_flat_enabled and self._auto_flat_daily_enabled:
            dh, dm = self._auto_flat_daily_time
            if local_now.time() >= time(dh, dm):
                if self._auto_flat_last_dates.get("daily_auto_flat") != local_now.date():
                    return "daily_auto_flat"

        if self._auto_flat_friday_enabled and weekday == 4:
            fh, fm = self._auto_flat_friday_time
            if local_now.time() >= time(fh, fm):
                if self._auto_flat_last_dates.get("friday_auto_flat") != local_now.date():
                    return "friday_auto_flat"

        if self._auto_flat_weekend_enabled and market_open is False:
            is_weekend_window = (
                weekday == 5  # Saturday
                or (weekday == 6 and local_now.time() < time(18, 0))  # Sunday pre-open
                or (weekday == 4 and local_now.time() >= time(17, 0))  # Friday after close
            )
            if is_weekend_window:
                if self._auto_flat_last_dates.get("weekend_auto_flat") != local_now.date():
                    return "weekend_auto_flat"

        # Tradovate Paper Evaluation: auto-flatten at 4:08 PM ET (2 min before 4:10 session close)
        if self._tv_paper_enabled and self._tv_paper_tracker is not None:
            if local_now.time() >= time(16, 8) and local_now.time() < time(16, 11):
                if self._auto_flat_last_dates.get("tv_paper_session_close") != local_now.date():
                    return "tv_paper_session_close"

        return None

    async def _close_all_virtual_trades(
        self, *, market_data: Dict, reason: str, notify: bool = True,
    ) -> tuple[int, float]:
        """Force-close all virtual trades (status=entered) using latest price.

        Returns (closed_count, total_pnl).

        Args:
            notify: If False, suppress the internal Telegram notification.
                    Callers that send their own consolidated notification should
                    pass ``notify=False`` to avoid duplicates.
        """
        if not getattr(self.config, "virtual_pnl_enabled", True):
            logger.warning("Auto/close-all requested but virtual PnL is disabled")
            return 0, 0.0

        active = self._get_active_virtual_trades(limit=500)
        if not active:
            return 0, 0.0

        prices = self._resolve_latest_prices(market_data)
        close_px = prices.get("close")
        if close_px is None:
            logger.warning("Close-all requested but no valid latest price available")
            return 0, 0.0

        bid_px = prices.get("bid")
        ask_px = prices.get("ask")
        price_source = prices.get("source")

        now = datetime.now(timezone.utc)
        closed_count = 0
        total_pnl = 0.0

        for rec in active:
            sig_id = str(rec.get("signal_id") or "").strip()
            if not sig_id:
                continue
            sig = rec.get("signal", {}) or {}
            direction = str(sig.get("direction") or "long").lower()

            # Conservative fill: long exits at bid, short exits at ask.
            exit_px = close_px
            if direction == "long" and isinstance(bid_px, float):
                exit_px = bid_px
            elif direction == "short" and isinstance(ask_px, float):
                exit_px = ask_px

            perf = self.performance_tracker.track_exit(
                signal_id=sig_id,
                exit_price=float(exit_px),
                exit_reason=str(reason),
                exit_time=now,
            )
            closed_count += 1
            if isinstance(perf, dict):
                try:
                    total_pnl += float(perf.get("pnl") or 0.0)
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

        # Best-effort: update state immediately so the dashboard doesn't show stale active count.
        try:
            state = self.state_manager.load_state() if self.state_manager else {}
            if isinstance(state, dict):
                state["active_trades_count"] = 0
                state["active_trades_unrealized_pnl"] = 0.0
                self.state_manager.save_state(state)
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        self._last_close_all_at = now.isoformat()
        self._last_close_all_reason = str(reason)
        self._last_close_all_count = int(closed_count)
        self._last_close_all_pnl = float(total_pnl)
        self._last_close_all_price_source = str(price_source) if price_source else None

        try:
            self.state_manager.append_event(
                "close_all_trades",
                {
                    "reason": str(reason),
                    "count": int(closed_count),
                    "total_pnl": float(total_pnl),
                    "price_source": self._last_close_all_price_source,
                },
                level="warning",
            )
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        if notify and self._auto_flat_notify and self.telegram_notifier.enabled:
            try:
                acct_label = getattr(self.telegram_notifier, "account_label", None)
                acct_tag = f"[{acct_label}] " if acct_label else ""
                msg = (
                    f"{acct_tag}🚫 *Close All Trades Executed*\n\n"
                    f"Reason: `{reason}`\n"
                    f"Closed: `{closed_count}`\n"
                    f"Total P&L: `{fmt_currency(total_pnl)}`"
                )
                await self.notification_queue.enqueue_raw_message(
                    msg, parse_mode="Markdown", dedupe=False,
                    priority=Priority.HIGH, tier=NotificationTier.CRITICAL,
                )
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

        return closed_count, total_pnl

    async def _close_specific_virtual_trades(
        self, *, signal_ids: list, market_data: Dict, reason: str
    ) -> list:
        """Force-close specific virtual trades by signal_id using latest price.

        Returns list of signal_ids that were successfully closed.
        """
        if not getattr(self.config, "virtual_pnl_enabled", True):
            logger.warning("Close requested but virtual PnL is disabled")
            return []

        if not signal_ids:
            return []

        active = self._get_active_virtual_trades(limit=500)
        if not active:
            return []

        # Filter to only requested signal_ids
        to_close = [rec for rec in active if rec.get("signal_id") in signal_ids]
        if not to_close:
            logger.warning(f"Requested signal_ids not found in active trades: {signal_ids}")
            return []

        prices = self._resolve_latest_prices(market_data)
        close_px = prices.get("close")
        if close_px is None:
            logger.warning("Close requested but no valid latest price available")
            return []

        bid_px = prices.get("bid")
        ask_px = prices.get("ask")

        now = datetime.now(timezone.utc)
        closed_ids = []
        total_pnl = 0.0

        for rec in to_close:
            sig_id = str(rec.get("signal_id") or "").strip()
            if not sig_id:
                continue
            sig = rec.get("signal", {}) or {}
            direction = str(sig.get("direction") or "long").lower()

            # Conservative fill: long exits at bid, short exits at ask.
            exit_px = close_px
            if direction == "long" and isinstance(bid_px, float):
                exit_px = bid_px
            elif direction == "short" and isinstance(ask_px, float):
                exit_px = ask_px

            perf = self.performance_tracker.track_exit(
                signal_id=sig_id,
                exit_price=float(exit_px),
                exit_reason=str(reason),
                exit_time=now,
            )
            closed_ids.append(sig_id)
            if isinstance(perf, dict):
                try:
                    total_pnl += float(perf.get("pnl") or 0.0)
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

        if closed_ids:
            logger.info(f"Closed {len(closed_ids)} specific positions: {closed_ids}, P&L: {fmt_currency(total_pnl)}")

            # Best-effort: update active trades count in state
            try:
                remaining_active = len(active) - len(closed_ids)
                state = self.state_manager.load_state() if self.state_manager else {}
                if isinstance(state, dict):
                    state["active_trades_count"] = max(0, remaining_active)
                    self.state_manager.save_state(state)
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

        return closed_ids

    def _clear_close_all_flag(self) -> None:
        """Clear close_all_requested flags in state.json (best-effort)."""
        if self.execution_orchestrator:
            self.execution_orchestrator.clear_close_all_flag()
        else:
            # Fallback if orchestrator not initialized
            try:
                state = self.state_manager.load_state()
            except Exception as e:
                logger.warning(f"Failed to load state for close-all flag: {e}")
                return
            if not isinstance(state, dict):
                return
            if "close_all_requested" in state or "close_all_requested_time" in state:
                state.pop("close_all_requested", None)
                state.pop("close_all_requested_time", None)
                try:
                    self.state_manager.save_state(state)
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

    def _get_close_signals_requested(self) -> list:
        """Get list of signal_ids requested for close from state.json."""
        if self.execution_orchestrator:
            return self.execution_orchestrator.get_close_signals_requested()
        else:
            # Fallback if orchestrator not initialized
            try:
                state = self.state_manager.load_state()
                return list(state.get("close_signals_requested", []))
            except Exception as e:
                logger.warning(f"Failed to retrieve close signals requested: {e}")
                return []

    def _clear_close_signals_requested(self, signal_ids: list = None) -> None:
        """Clear specific signal close requests or all of them from state.json."""
        if self.execution_orchestrator:
            self.execution_orchestrator.clear_close_signals_requested(signal_ids)
        else:
            # Fallback if orchestrator not initialized
            try:
                state = self.state_manager.load_state()
            except Exception as e:
                logger.warning(f"Failed to load state for close signals: {e}")
                return
            if not isinstance(state, dict):
                return

            current_requests = state.get("close_signals_requested", [])
            if signal_ids is None:
                # Clear all
                state.pop("close_signals_requested", None)
                state.pop("close_signals_requested_time", None)
            else:
                # Remove specific signal_ids
                state["close_signals_requested"] = [s for s in current_requests if s not in signal_ids]
                if not state["close_signals_requested"]:
                    state.pop("close_signals_requested", None)
                    state.pop("close_signals_requested_time", None)

            try:
                self.state_manager.save_state(state)
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

    async def _handle_close_all_requests(self, market_data: Dict) -> None:
        """Handle manual close-all flag, individual close requests, and auto-flat rules."""
        manual_requested = False
        try:
            state = self.state_manager.load_state()
            manual_requested = bool(state.get("close_all_requested", False))
        except Exception as e:
            logger.warning(f"Failed to load state for close-all flag: {e}")
            manual_requested = False

        if manual_requested:
            logger.warning("Close-all flag detected - flattening virtual trades")
            closed_virtual, virtual_pnl = await self._close_all_virtual_trades(
                market_data=market_data, reason="close_all_requested", notify=False,
            )
            self._clear_close_all_flag()

            # Also flatten real broker positions (Tradovate/IBKR) if execution adapter is present
            cancelled_count = 0
            flattened_count = 0
            broker_errors: list[str] = []
            if self.execution_adapter is not None:
                try:
                    # Cancel open orders first
                    cancel_results = await self.execution_adapter.cancel_all()
                    cancelled_count = sum(1 for r in cancel_results if r.success)
                    broker_errors.extend(r.error_message for r in cancel_results if not r.success and r.error_message)
                    if cancelled_count:
                        logger.warning(f"Close-all: cancelled {cancelled_count} open orders")

                    # Flatten open broker positions
                    flatten_results = await self.execution_adapter.flatten_all_positions()
                    flattened_count = sum(1 for r in flatten_results if r.success)
                    broker_errors.extend(r.error_message for r in flatten_results if not r.success and r.error_message)
                    if flattened_count:
                        logger.warning(f"Close-all: submitted {flattened_count} flatten order(s)")
                    if broker_errors:
                        logger.warning(f"Close-all: {len(broker_errors)} broker errors: {broker_errors[:3]}")
                except Exception as e:
                    logger.error(f"Close-all: broker flatten failed: {e}", exc_info=True)
                    broker_errors.append(str(e)[:80])

            # Send single consolidated Telegram notification
            try:
                acct_label = getattr(self.telegram_notifier, "account_label", None)
                acct_tag = f"[{acct_label}] " if acct_label else ""
                parts = [f"{acct_tag}🛑 *Close All Executed*\n"]
                parts.append(f"Closed: `{closed_virtual}`")
                parts.append(f"Total P&L: `{fmt_currency(virtual_pnl)}`")
                if self.execution_adapter is not None:
                    parts.append(f"Orders cancelled: `{cancelled_count}`")
                    parts.append(f"Positions flattened: `{flattened_count}`")
                if broker_errors:
                    parts.append(f"⚠️ Errors: `{broker_errors[0][:60]}`")
                asyncio.create_task(
                    self.notification_queue.enqueue_raw_message(
                        "\n".join(parts),
                        parse_mode="Markdown",
                        priority=Priority.CRITICAL,
                        dedupe=False,
                    )
                )
            except Exception as e:
                logger.debug(f"Non-critical: {e}")

        # Handle individual signal close requests
        close_signal_ids = self._get_close_signals_requested()
        if close_signal_ids:
            logger.warning(f"Individual close requests detected: {close_signal_ids}")
            closed_ids = await self._close_specific_virtual_trades(
                signal_ids=close_signal_ids,
                market_data=market_data,
                reason="manual_close_requested"
            )
            # Always clear the requests (even if no virtual trades matched --
            # the signal_id may be a Tradovate position ID for Tradovate Paper, not a
            # virtual trade signal_id).
            self._clear_close_signals_requested(close_signal_ids)

            # Also close the corresponding broker positions (Tradovate/Tradovate Paper).
            # This runs regardless of whether virtual trades matched, because
            # for Tradovate Paper the real Tradovate position may exist without a
            # matching virtual trade (e.g. after auto-flat closed virtuals
            # but the broker position stayed open).
            if self.execution_adapter is not None:
                    broker_errors: list[str] = []
                    cancelled_count = 0
                    flattened_count = 0
                    try:
                        # Cancel open orders (TP/SL brackets) first
                        cancel_results = await self.execution_adapter.cancel_all()
                        cancelled_count = sum(1 for r in cancel_results if r.success)
                        broker_errors.extend(
                            r.error_message for r in cancel_results
                            if not r.success and r.error_message
                        )
                        if cancelled_count:
                            logger.warning(f"Close-trade: cancelled {cancelled_count} open orders")

                        # Flatten the broker position
                        flatten_results = await self.execution_adapter.flatten_all_positions()
                        flattened_count = sum(1 for r in flatten_results if r.success)
                        broker_errors.extend(
                            r.error_message for r in flatten_results
                            if not r.success and r.error_message
                        )
                        if flattened_count:
                            logger.warning(f"Close-trade: submitted {flattened_count} flatten order(s)")
                        if broker_errors:
                            logger.warning(f"Close-trade: broker errors: {broker_errors[:3]}")
                    except Exception as e:
                        logger.error(f"Close-trade: broker flatten failed: {e}", exc_info=True)
                        broker_errors.append(str(e)[:80])

                    # Notify
                    try:
                        acct_label = getattr(self.telegram_notifier, "account_label", None)
                        acct_tag = f"[{acct_label}] " if acct_label else ""
                        parts = [f"{acct_tag}\U0001f6d1 *Close Trade Executed*\n"]
                        parts.append(f"Virtual closed: `{closed_ids}`")
                        parts.append(f"Orders cancelled: `{cancelled_count}`")
                        parts.append(f"Positions flattened: `{flattened_count}`")
                        if broker_errors:
                            parts.append(f"\u26a0\ufe0f Errors: `{broker_errors[0][:60]}`")
                        asyncio.create_task(
                            self.notification_queue.enqueue_raw_message(
                                "\n".join(parts),
                                parse_mode="Markdown",
                                priority=Priority.CRITICAL,
                                dedupe=False,
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")

        # Auto-flat rules (daily + Friday + weekend safety)
        try:
            market_open = bool(get_market_hours().is_market_open())
        except Exception as e:
            logger.warning(f"Market hours check failed in close-all handler: {e}")
            market_open = None
        now = datetime.now(timezone.utc)
        reason = self._auto_flat_due(now, market_open=market_open)
        if reason:
            active = self._get_active_virtual_trades(limit=200)
            if active:
                logger.warning(f"Auto-flat triggered: {reason}")
                closed, _ = await self._close_all_virtual_trades(market_data=market_data, reason=reason)
                if closed > 0:
                    try:
                        local_now = now.astimezone(ZoneInfo(self._auto_flat_timezone))
                        self._auto_flat_last_dates[reason] = local_now.date()
                    except Exception as e:
                        logger.warning(f"Failed to record auto-flat date: {e}")
                        self._auto_flat_last_dates[reason] = now.date()

                    # Tradovate Paper: update EOD high-water mark after session close flatten
                    if reason == "tv_paper_session_close" and self._tv_paper_tracker is not None:
                        try:
                            self._tv_paper_tracker.update_eod_hwm()
                        except Exception as e:
                            logger.debug(f"Could not update Tradovate Paper EOD HWM: {e}")

    def mark_state_dirty(self) -> None:
        """Mark the service state as needing a save on the next cycle-end."""
        self._state_dirty = True

    def _save_state(self, *, force: bool = False) -> None:
        """Save current service state.

        When *force* is False (default), only saves if ``_state_dirty`` is True.
        Shutdown and error paths should pass ``force=True`` to guarantee
        persistence regardless of the dirty flag.
        """
        if not force and not self._state_dirty:
            return
        state = self._state_builder.build_state()
        self.state_manager.save_state(state)
        self._state_dirty = False

    async def _check_heartbeat(self) -> None:
        """Send periodic heartbeat messages."""
        now = datetime.now(timezone.utc)

        # Check if it's time for a heartbeat
        if (
            self.last_heartbeat is None
            or (now - self.last_heartbeat).total_seconds() >= self.heartbeat_interval
        ):
            status = self.get_status()
            status["last_successful_cycle"] = (
                self.last_successful_cycle.isoformat() if self.last_successful_cycle else None
            )
            
            # Add current time and latest price to heartbeat
            status["current_time"] = now
            status["symbol"] = self.config.symbol
            
            # Try to get latest price and order book info
            try:
                market_data = await self.data_fetcher.fetch_latest_data()
                if market_data.get("latest_bar"):
                    latest_bar = market_data["latest_bar"]
                    if isinstance(latest_bar, dict) and "close" in latest_bar:
                        status["latest_price"] = latest_bar["close"]
                        # Include latest_bar for order book transparency in heartbeat
                        status["latest_bar"] = latest_bar
            except Exception as e:
                logger.debug(f"Could not fetch price for heartbeat: {e}")
            
            await self.notification_queue.enqueue_heartbeat(status, priority=Priority.LOW)
            self.last_heartbeat = now

    async def _check_data_quality(self, market_data: Dict) -> None:
        """Check data quality and send alerts if needed."""
        now = datetime.now(timezone.utc)

        # Use DataQualityChecker for validation
        validation = self.data_quality_checker.validate_market_data(market_data)

        # Global throttling (safety): don’t emit too often even if state oscillates.
        throttled = (
            self.last_data_quality_alert is not None
            and (now - self.last_data_quality_alert).total_seconds() < self.data_quality_alert_interval
        )

        # Market open/closed matters for stale data interpretation
        is_market_open = False
        try:
            from pearlalgo.utils.market_hours import get_market_hours

            is_market_open = bool(get_market_hours().is_market_open())
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            # Fail quiet to avoid spam outside market hours if market-hours util breaks
            is_market_open = False

        def _stale_bucket(age_min: float) -> int:
            # Send only when age crosses key thresholds to reduce spam.
            base = [5, 10, 20, 40, 60, int(self.stale_data_threshold_minutes)]
            thresholds = sorted({t for t in base if t > 0})
            for t in reversed(thresholds):
                if age_min >= t:
                    return t
            return int(self.stale_data_threshold_minutes)

        def _buffer_severity(buf: int) -> str:
            # Buffer is “inadequate” only when < 10 bars (DataQualityChecker default).
            if buf <= 0:
                return "empty"
            if buf <= 3:
                return "critical"
            if buf <= 7:
                return "warning"
            return "low"

        # 1) Stale data (only alert during market hours)
        if not validation["freshness"]["is_fresh"]:
            age_minutes = float(validation["freshness"].get("age_minutes", 0.0) or 0.0)
            if is_market_open:
                bucket = _stale_bucket(age_minutes)
                # Only send when bucket changes (10→20→40→60...) AND we’re not throttled.
                if (self._last_stale_bucket != bucket) and (not throttled):
                    await self.notification_queue.enqueue_data_quality_alert(
                        "stale_data",
                        f"Data is {age_minutes:.1f} minutes old",
                        {"age_minutes": age_minutes, "bucket": bucket},
                        priority=Priority.NORMAL,
                    )
                    self.last_data_quality_alert = now
                    self._last_stale_data_alert_type = "stale_data"
                self._last_stale_bucket = bucket
                self._was_stale_during_market = True
            else:
                logger.debug(
                    f"Data is {age_minutes:.1f} minutes old but market is closed - expected"
                )
            return

        # Recovery: data is fresh again after being stale during market hours.
        if self._was_stale_during_market and is_market_open:
            # Avoid “flapping” recovery spam; allow recovery after 60s even if main throttle is 5m.
            can_recover = (
                self.last_data_quality_alert is None
                or (now - self.last_data_quality_alert).total_seconds() >= 60
            )
            if can_recover:
                await self.notification_queue.enqueue_data_quality_alert(
                    "recovery",
                    "Market data recovered (fresh bars again)",
                    {},
                    priority=Priority.NORMAL,
                )
                self.last_data_quality_alert = now
            self._was_stale_during_market = False
            self._last_stale_bucket = None

        # 2) Data gap (empty dataframe)
        df = market_data.get("df")
        if df is not None and df.empty:
            self._was_data_gap = True
            if (self._last_stale_data_alert_type != "data_gap") and (not throttled):
                await self.notification_queue.enqueue_data_quality_alert(
                    "data_gap",
                    "No market data available",
                    {},
                    priority=Priority.NORMAL,
                )
                self.last_data_quality_alert = now
                self._last_stale_data_alert_type = "data_gap"
            return
        if self._was_data_gap:
            can_recover = (
                self.last_data_quality_alert is None
                or (now - self.last_data_quality_alert).total_seconds() >= 60
            )
            if can_recover:
                await self.notification_queue.enqueue_data_quality_alert(
                    "recovery",
                    "Market data gap recovered",
                    {},
                    priority=Priority.NORMAL,
                )
                self.last_data_quality_alert = now
            self._was_data_gap = False

        # 3) Buffer size issues (only send when severity changes)
        if not validation["buffer_size"]["is_adequate"]:
            buffer_size = int(validation["buffer_size"].get("buffer_size", 0) or 0)
            severity = _buffer_severity(buffer_size)
            if (self._last_buffer_severity != severity) and (not throttled):
                await self.notification_queue.enqueue_data_quality_alert(
                    "buffer_issue",
                    f"Buffer size is low: {buffer_size} bars",
                    {"buffer_size": buffer_size, "severity": severity},
                    priority=Priority.NORMAL,
                )
                self.last_data_quality_alert = now
                self._last_stale_data_alert_type = "buffer_issue"
            self._last_buffer_severity = severity
            self._was_buffer_inadequate = True
            return

        # Recovery: buffer is adequate again
        if self._was_buffer_inadequate:
            can_recover = (
                self.last_data_quality_alert is None
                or (now - self.last_data_quality_alert).total_seconds() >= 60
            )
            if can_recover:
                await self.notification_queue.enqueue_data_quality_alert(
                    "recovery",
                    "Buffer recovered (enough bars for strategy)",
                    {},
                    priority=Priority.NORMAL,
                )
                self.last_data_quality_alert = now
            self._was_buffer_inadequate = False
            self._last_buffer_severity = None


    async def _handle_connection_failure(self) -> None:
        """Handle connection failure and send alerts if needed."""
        now = datetime.now(timezone.utc)

        # Throttle connection failure alerts
        if (
            self.last_connection_failure_alert is None
            or (now - self.last_connection_failure_alert).total_seconds() >= self.connection_failure_alert_interval
        ):
            await self.notification_queue.enqueue_data_quality_alert(
                "fetch_failure",
                f"IB Gateway connection issue detected ({self.connection_failures} failures). "
                "Check if IB Gateway is running.",
                {
                    "connection_failures": self.connection_failures,
                    "error_type": "connection",
                    "suggestion": "Run: ./scripts/gateway/gateway.sh status or ./scripts/gateway/gateway.sh start",
                },
                priority=Priority.NORMAL,
            )
            self.last_connection_failure_alert = now

    # ------------------------------------------------------------------
    # Backward-compatible delegation properties (WS8: MLManager extraction)
    # ------------------------------------------------------------------
    # These properties let existing code (and submodules that read via
    # getattr(self, "_ml_*", default)) keep working without changes.

    @property
    def _ml_signal_filter(self):
        return self._ml_manager.signal_filter

    @property
    def _ml_adjust_sizing(self):
        return self._ml_manager.adjust_sizing

    @property
    def _ml_filter_enabled(self):
        return self._ml_manager.filter_enabled

    @property
    def _ml_filter_mode(self):
        return self._ml_manager.filter_mode

    @property
    def _ml_shadow_threshold(self):
        return self._ml_manager.shadow_threshold

    @property
    def _ml_blocking_allowed(self):
        return self._ml_manager.blocking_allowed

    @property
    def _ml_lift_metrics(self):
        return self._ml_manager.lift_metrics

    @property
    def _ml_lift_last_eval_at(self):
        return self._ml_manager.lift_last_eval_at

    @property
    def _ml_require_lift_to_block(self):
        return self._ml_manager.require_lift_to_block

    @property
    def _ml_lift_lookback_trades(self):
        return self._ml_manager.lift_lookback_trades

    @property
    def _ml_lift_min_trades(self):
        return self._ml_manager.lift_min_trades

    @property
    def _ml_lift_min_winrate_delta(self):
        return self._ml_manager.lift_min_winrate_delta

    @property
    def _ml_size_multiplier_min(self):
        return self._ml_manager.size_multiplier_min

    @property
    def _ml_size_multiplier_max(self):
        return self._ml_manager.size_multiplier_max

    @property
    def _ml_size_threshold(self):
        return self._ml_manager.size_threshold

    @property
    def _ml_filter_init_status(self):
        return self._ml_manager.filter_init_status

    @property
    def _bandit_config(self):
        return self._ml_manager.bandit_config

    @property
    def bandit_policy(self):
        return self._ml_manager.bandit_policy

    @property
    def contextual_policy(self):
        return self._ml_manager.contextual_policy

    @property
    def _contextual_config(self):
        return self._ml_manager.contextual_config

    @property
    def shadow_tracker(self):
        return self._ml_manager.shadow_tracker

    def _os_signal_handler(self, signum, frame) -> None:
        """Handle OS shutdown signals (SIGINT/SIGTERM)."""
        signal_names = {
            signal.SIGINT: "SIGINT (Ctrl+C)",
            signal.SIGTERM: "SIGTERM",
        }
        signal_name = signal_names.get(signum, f"Signal {signum}")
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self.shutdown_requested = True

