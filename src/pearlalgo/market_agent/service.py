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
from pearlalgo.utils.paths import (
    get_utc_timestamp,
    get_et_timestamp,
    parse_trade_timestamp_to_utc,
    parse_utc_timestamp,
)
import pytz
_ET = pytz.timezone("America/New_York")
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
from pearlalgo.strategies import create_strategy, get_strategy_defaults
from pearlalgo.strategies.composite_intraday import check_trading_session, detect_market_regime
from pearlalgo.utils.cadence import CadenceScheduler
from pearlalgo.execution.advanced_exit_manager import AdvancedExitManager, PartialRunnerManager
from pearlalgo.utils.data_quality import DataQualityChecker
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.market_hours import configure_market_hours, get_market_hours
from pearlalgo.market_agent.service_lifecycle import ServiceLifecycleMixin
from pearlalgo.market_agent.service_loop import ServiceLoopMixin
from pearlalgo.market_agent.virtual_trade_manager import VirtualTradeManager
from pearlalgo.utils.volume_pressure import (
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)
from pearlalgo.utils.pearl_suggestions import get_suggestion_engine
from pearlalgo.market_agent.audit_logger import AuditLogger, AuditEventType
from pearlalgo.market_agent.scheduled_tasks import ScheduledTasks
from pearlalgo.market_agent.operator_handler import OperatorHandler
from pearlalgo.market_agent.order_manager import OrderManager
from pearlalgo.market_agent.signal_handler import SignalHandler
from pearlalgo.market_agent.signal_orchestrator import SignalOrchestrator
from pearlalgo.market_agent.execution_orchestrator import ExecutionOrchestrator
from pearlalgo.market_agent.observability_orchestrator import ObservabilityOrchestrator
from pearlalgo.market_agent.position_monitor import monitor_open_position as _monitor_open_position_impl
from pearlalgo.market_agent.execution_flags import check_execution_control_flags as _check_execution_control_flags_impl
from pearlalgo.market_agent.state_builder import StateBuilder
from pearlalgo.market_agent.service_status import (
    build_market_agent_status_snapshot as _canonical_build_market_agent_status_snapshot,
    build_pearl_review_message as _canonical_build_pearl_review_message,
    generate_pearl_insight as _canonical_generate_pearl_insight,
)

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

try:
    from pearlalgo.storage.trade_database import TradeDatabase
    TRADE_DB_AVAILABLE = True
except Exception:
    TRADE_DB_AVAILABLE = False
    TradeDatabase = None  # type: ignore




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


class MarketAgentService(ServiceLoopMixin, ServiceLifecycleMixin):
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
                config=ConfigView(config or get_strategy_defaults()) if config is not None else None,
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

        # Strategy adapter remains monkeypatch-friendly for tests, but the live
        # implementation now comes from the canonical strategies package.
        self.strategy = create_strategy(self.config)

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
        guardrails_settings = service_config.get("guardrails", {}) or {}

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
        active_strategy = str(self._strategy_settings.get("active", "") or "")
        legacy_signal_gate_enabled = bool(guardrails_settings.get("signal_gate_enabled", False))
        allow_legacy_signal_gate = legacy_signal_gate_enabled or not active_strategy
        if trading_circuit_breaker_settings.get("enabled", True) and allow_legacy_signal_gate:
            self.trading_circuit_breaker = create_trading_circuit_breaker(trading_circuit_breaker_settings)
            # Validate config at startup
            config_warnings = self.trading_circuit_breaker.validate_config()
            if config_warnings:
                logger.warning(f"Trading circuit breaker config warnings: {config_warnings}")
            # FIXED 2026-03-25: Log effective CB mode at startup so
            # warn_only/shadow drift is never silently missed.
            cb_mode = self.trading_circuit_breaker.config.mode
            if cb_mode != "enforce":
                logger.warning(
                    "TRADING CIRCUIT BREAKER MODE IS '%s' — signals will "
                    "NOT be blocked! Set mode=enforce for production.",
                    cb_mode,
                )
            logger.info(
                f"Trading circuit breaker enabled: "
                f"mode={cb_mode}, "
                f"max_consecutive_losses={self.trading_circuit_breaker.config.max_consecutive_losses}, "
                f"max_session_drawdown=${self.trading_circuit_breaker.config.max_session_drawdown}, "
                f"max_positions={self.trading_circuit_breaker.config.max_concurrent_positions}"
            )
            # Hydrate daily P&L from DB so restart does not reset the daily loss counter
            self.trading_circuit_breaker.hydrate_daily_pnl()
        else:
            logger.info(
                "Legacy signal gate disabled for active runtime path "
                "(strategy=%s, signal_gate_enabled=%s)",
                active_strategy or "legacy",
                legacy_signal_gate_enabled,
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
        # Tradovate Paper evaluation tracking
        # ==========================================================================
        # TradeSyncer is the source of truth for evaluation lifecycle. Keep the
        # local tracker disabled to avoid duplicate/stale eval state and alerts.
        self._tv_paper_tracker = None
        self._tv_paper_enabled = False

        # Tradovate account cache (polled each cycle when execution adapter is Tradovate)
        self._tradovate_account: Dict[str, Any] = {}
        self._tv_paper_was_connected: Optional[bool] = None

        # ==========================================================================
        # DRIFT GUARD (Risk-Off Cooldown)
        # ==========================================================================
        # Strategy execution is intentionally rule-based here.

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
        self._state_dirty: bool = False  # Set True when state changes; reset after save
        self.connection_failure_alert_interval = service_settings.get("connection_failure_alert_interval", 600)
        self.data_quality_alert_interval = service_settings.get("data_quality_alert_interval", 300)
        self.consecutive_errors = 0
        self.max_consecutive_errors = circuit_breaker_settings.get("max_consecutive_errors", 10)
        self.data_fetch_errors = 0
        self.max_data_fetch_errors = circuit_breaker_settings.get("max_data_fetch_errors", 5)
        self.connection_failures = 0
        self.max_connection_failures = circuit_breaker_settings.get("max_connection_failures", 10)
        self.pause_on_connection_failures = circuit_breaker_settings.get("pause_on_connection_failures", True)
        self._cb_connection_notified = False  # Guard: only send circuit breaker notification once per event
        
        # Virtual trade exit manager (extracted from this class)
        self.virtual_trade_manager = VirtualTradeManager(
            state_manager=self.state_manager,
            performance_tracker=self.performance_tracker,
            notification_queue=self.notification_queue,
            trading_circuit_breaker=self.trading_circuit_breaker,
            telegram_notifier=self.telegram_notifier,
            execution_adapter=getattr(self, "execution_adapter", None),
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
                # Tradovate Paper: use follower path so every strategy signal goes to Tradovate
                if execution_adapter_name == "tradovate":
                    self._signal_follower_mode = True
                    logger.info(
                        "Tradovate Paper: signal follower mode ON — strategy signals execute via "
                        "follower_execute -> place_bracket (Tradovate)"
                    )
            except Exception as e:
                logger.error(f"Failed to initialize execution adapter: {e}", exc_info=True)
                self.execution_adapter = None
        else:
            if not EXECUTION_AVAILABLE:
                logger.debug("Execution layer not available (import failed)")
            else:
                logger.info("Execution adapter disabled (execution.enabled=false)")
        
        # Trailing stop manager (initialized if configured and execution adapter available)
        self._trailing_stop_manager = None
        if self.execution_adapter is not None:
            try:
                from pearlalgo.execution.tradovate.trailing_stop import TrailingStopManager
                self._trailing_stop_manager = TrailingStopManager(service_config)
                if self._trailing_stop_manager.enabled:
                    logger.info("Trailing stop manager: ENABLED")
                else:
                    logger.info("Trailing stop manager: initialized but disabled")
            except Exception as e:
                logger.debug(f"Trailing stop manager not available: {e}")

        # Partial Profit Runner manager (runner_mode config)
        self._runner_manager = None
        runner_cfg = service_config.get("runner_mode", {})
        if runner_cfg.get("enabled", False) and self.execution_adapter is not None:
            try:
                self._runner_manager = PartialRunnerManager({"runner_mode": runner_cfg})
                if self._runner_manager.enabled:
                    logger.info("Runner mode: ENABLED (breakeven→runner→tight trail)")
                else:
                    self._runner_manager = None
            except Exception as e:
                logger.debug(f"Runner mode not available: {e}")

        # Track last trading day for daily counter reset
        self._last_trading_day: Optional[date] = None
        
        # Track execution connection state for alerts (avoid duplicate alerts)
        self._execution_was_connected: Optional[bool] = None
        self._last_connection_alert_time: Optional[datetime] = None
        self._connection_alert_cooldown_seconds: int = 300  # 5 minutes between alerts

        # ------------------------------------------------------------------
        # SignalHandler: extracted signal processing pipeline (Arch-1B)
        # ------------------------------------------------------------------
        self._order_manager = OrderManager(
            risk_settings=self._risk_settings,
            strategy_settings=self._strategy_settings,
        )
        self._signal_handler = SignalHandler(
            state_manager=self.state_manager,
            performance_tracker=self.performance_tracker,
            notification_queue=self.notification_queue,
            order_manager=self._order_manager,
            trading_circuit_breaker=self.trading_circuit_breaker,
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
    # All signal processing logic (circuit breaker, sizing,
    # performance tracking, execution, notifications)
    # now lives in signal_handler.py::SignalHandler.process_signal().
    # Call sites updated to use self._signal_handler.process_signal() directly.
    # Helper methods below (_compute_base_position_size)
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

    async def _monitor_open_position(self, market_data: Dict) -> None:
        """Log real-time metrics for open positions: unrealized P&L, distance to stop/TP, MFE/MAE.
        Also triggers trailing stop updates when enabled.

        Delegated to position_monitor.monitor_open_position().
        """
        await _monitor_open_position_impl(self, market_data)

    def _find_initial_stop_price(self, direction: str) -> float:
        """Find the initial stop price from active virtual trades."""
        try:
            active = self.virtual_trade_manager.position_tracker.get_active_virtual_trades(limit=5)
            for sig_rec in (active or []):
                sig = sig_rec.get('signal') or sig_rec or {}
                if sig.get('direction', '').lower() == direction:
                    return float(sig.get('stop_loss') or 0)
        except Exception:
            pass
        return 0.0
    async def _find_initial_stop_from_broker(self, direction: str, entry_price: float, current_atr: float = 0) -> float:
        """
        Find initial stop price from actual broker stop orders.
        
        Priority:
        1. Actual working stop order from Tradovate
        2. Reasonable default based on ATR (entry ± 2*ATR)
        3. Fixed percentage (2% from entry)
        
        Args:
            direction: 'long' or 'short'
            entry_price: Position entry price
            current_atr: Current ATR value (if available)
            
        Returns:
            Stop price, or 0.0 if unable to determine
        """
        # Try to find actual working stop order
        try:
            orders = await self.execution_adapter._client.get_orders()
            stop_action = "Sell" if direction == "long" else "Buy"
            for order in orders:
                if (order.get("orderType") == "Stop"
                        and order.get("action") == stop_action
                        and order.get("ordStatus") in ("Working", "Accepted")):
                    stop_price = float(order.get("stopPrice", 0))
                    if stop_price > 0:
                        logger.info(f"Found broker stop order for {direction}: ${stop_price:.2f}")
                        return stop_price
        except Exception as e:
            logger.debug(f"Could not query broker stop orders: {e}")
        
        # Fallback 1: Use ATR-based default
        if current_atr > 0:
            if direction == "long":
                stop_price = entry_price - (2.0 * current_atr)
            else:
                stop_price = entry_price + (2.0 * current_atr)
            logger.info(f"Using ATR-based default stop for {direction}: ${stop_price:.2f} (2*ATR=${current_atr*2:.2f})")
            return stop_price
        
        # Fallback 2: Fixed 2% from entry
        if direction == "long":
            stop_price = entry_price * 0.98
        else:
            stop_price = entry_price * 1.02
        logger.info(f"Using 2% default stop for {direction}: ${stop_price:.2f}")
        return stop_price


    def _get_current_atr(self, market_data: Dict) -> float:
        """Compute current ATR from the bar buffer."""
        try:
            df = market_data.get('df')
            if df is None or len(df) < 14:
                return 0.0
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs(),
            ], axis=1).max(axis=1)
            return float(tr.iloc[-14:].mean())
        except Exception:
            return 0.0

    def _ingest_trailing_stop_override(self) -> None:
        """Check for trailing_stop_override.json flag file and apply if present."""
        try:
            if not self._trailing_stop_manager or not self._trailing_stop_manager.allow_external_override:
                return
            state_dir = self.state_manager.state_dir

            # Check for clear-override flag first
            clear_file = state_dir / "trailing_stop_clear_override.flag"
            if clear_file.exists():
                clear_file.unlink(missing_ok=True)
                self._trailing_stop_manager.clear_override()
                logger.info("Trailing stop override cleared via flag file")

            override_file = state_dir / "trailing_stop_override.json"
            if not override_file.exists():
                return

            raw = json.loads(override_file.read_text())
            override_file.unlink(missing_ok=True)

            from pearlalgo.execution.tradovate.trailing_stop import TrailingOverride

            ttl_minutes = min(
                int(raw.get("ttl_minutes", 30)),
                self._trailing_stop_manager.max_override_ttl_minutes,
            )
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

            override = TrailingOverride(
                trail_atr_multiplier=float(raw.get("trail_atr_multiplier", 1.0)),
                activation_atr_multiplier=float(raw.get("activation_atr_multiplier", 1.0)),
                force_phase=raw.get("force_phase"),
                min_move_override=raw.get("min_move_override"),
                expires_at=expires_at,
                source=str(raw.get("source", "external")),
                reason=str(raw.get("reason", "")),
            )
            self._trailing_stop_manager.apply_override(override)

            # Write ack file
            ack_file = state_dir / "trailing_stop_override_ack.json"
            ack_data = {
                "applied": True,
                "at": datetime.now(timezone.utc).isoformat(),
                "effective_params": self._trailing_stop_manager.get_override(),
            }
            ack_file.write_text(json.dumps(ack_data, default=str))
            logger.info(f"Trailing stop override ingested: source={override.source}, reason={override.reason}")
        except Exception as e:
            logger.warning(f"Failed to ingest trailing stop override: {e}")

    def _apply_regime_trailing_preset(self, market_data: Dict) -> None:
        """Apply regime-adaptive trailing stop preset based on current market conditions."""
        try:
            if not self._trailing_stop_manager or not self._trailing_stop_manager.regime_adaptive:
                return
            df = market_data.get('df')
            if df is None or len(df) < 50:
                return

            regime_result = detect_market_regime(df)
            # Normalize regime names: trending_up/trending_down -> trending
            regime = regime_result.regime
            if regime.startswith("trending"):
                regime = "trending"
            self._trailing_stop_manager.apply_regime_preset(regime)
        except Exception as e:
            logger.debug(f"Regime trailing preset failed (non-fatal): {e}")

    async def _find_stop_order_id(self, direction: str) -> Optional[int]:
        """Find the working stop order ID for the current position.

        Uses the raw Tradovate /order/list response, handling both ``orderType``
        and ``ordType`` field variants.  Falls back to OCO-linked sell orders
        when the order type is missing (sparse Tradovate rows).
        """
        summary_method = getattr(self.execution_adapter, "get_account_summary", None)
        if callable(summary_method):
            try:
                summary = await summary_method()
                working_orders = summary.get("working_orders") or []
                stop_action = "sell" if direction == "long" else "buy"

                best_candidate = None
                for order in working_orders:
                    action = str(order.get("action") or "").strip().lower()
                    if action != stop_action:
                        continue

                    order_type = str(order.get("order_type") or "").strip().lower()
                    if "stop" in order_type or "trailing" in order_type:
                        return int(order["id"])

                    stop_px = order.get("stop_price")
                    if stop_px is not None and best_candidate is None:
                        best_candidate = int(order["id"])

                if best_candidate is not None:
                    return best_candidate
            except Exception as e:
                logger.debug(f"Could not find stop order from account summary: {e}")

        try:
            orders = await self.execution_adapter._client.get_orders()
            stop_action = "Sell" if direction == "long" else "Buy"
            working_states = {"Working", "Accepted", "working", "accepted"}

            best_candidate = None
            for order in orders:
                action = order.get("action", "")
                if action != stop_action:
                    continue

                status = (
                    order.get("ordStatus")
                    or order.get("status")
                    or ""
                )
                if status not in working_states:
                    continue

                order_type = str(
                    order.get("orderType")
                    or order.get("ordType")
                    or order.get("type")
                    or ""
                ).strip()

                # Direct match: order is explicitly a Stop
                if order_type.lower() in ("stop", "stoplimit", "stopmarket"):
                    return int(order["id"])

                # Fallback: order has a stopPrice (even without explicit type)
                stop_px = order.get("stopPrice") or order.get("triggerPrice")
                if stop_px is not None:
                    best_candidate = int(order["id"])

            # Return the best fallback if no explicit Stop type found
            if best_candidate:
                return best_candidate
        except Exception as e:
            logger.debug(f"Could not find stop order: {e}")
        return None

    async def _find_tp_order_id(self, direction: str) -> Optional[int]:
        """Find the working take-profit (Limit) order ID for the current position.

        For a long position, the TP is a Sell Limit; for short, a Buy Limit.
        """
        summary_method = getattr(self.execution_adapter, "get_account_summary", None)
        if callable(summary_method):
            try:
                summary = await summary_method()
                working_orders = summary.get("working_orders") or []
                tp_action = "sell" if direction == "long" else "buy"

                best_candidate = None
                for order in working_orders:
                    action = str(order.get("action") or "").strip().lower()
                    if action != tp_action:
                        continue

                    order_type = str(order.get("order_type") or "").strip().lower()
                    if "limit" in order_type:
                        return int(order["id"])

                    price = order.get("price")
                    stop_px = order.get("stop_price")
                    if price is not None and stop_px is None and best_candidate is None:
                        best_candidate = int(order["id"])

                if best_candidate is not None:
                    return best_candidate
            except Exception as e:
                logger.debug(f"Could not find TP order from account summary: {e}")

        try:
            orders = await self.execution_adapter._client.get_orders()
            tp_action = "Sell" if direction == "long" else "Buy"
            working_states = {"Working", "Accepted", "working", "accepted"}

            for order in orders:
                action = order.get("action", "")
                if action != tp_action:
                    continue

                status = (
                    order.get("ordStatus")
                    or order.get("status")
                    or ""
                )
                if status not in working_states:
                    continue

                order_type = str(
                    order.get("orderType")
                    or order.get("ordType")
                    or order.get("type")
                    or ""
                ).strip().lower()

                # TP orders are Limit orders (not Stop orders)
                if order_type in ("limit", "limitorder"):
                    return int(order["id"])

                # Fallback: order has a price but no stopPrice (i.e. it's a limit/TP)
                price = order.get("price") or order.get("limitPrice")
                stop_px = order.get("stopPrice") or order.get("triggerPrice")
                if price is not None and stop_px is None:
                    return int(order["id"])

        except Exception as e:
            logger.debug(f"Could not find TP order: {e}")
        return None

    def _update_virtual_trade_exits(self, market_data: Dict) -> None:
        """Delegate to VirtualTradeManager (extracted for testability)."""
        self.virtual_trade_manager.process_exits(market_data)

    async def _sync_virtual_trades_with_broker(self) -> None:
        """Close stale virtual trades that no longer have a matching broker position.

        When virtual PnL is disabled (Tradovate is source of truth), virtual
        trades in signals.jsonl can accumulate as "entered" forever because
        ``process_exits()`` is a no-op.  This method checks the broker for
        actual open positions and closes any virtual trades that don't have
        a corresponding broker position.
        """
        if self.execution_adapter is None:
            return

        # Only run every 60 seconds to avoid API spam
        now = datetime.now(_ET).replace(tzinfo=None)  # FIXED 2026-03-25: store ET not UTC
        last_sync = getattr(self, '_last_virtual_trade_sync', None)
        if last_sync and (now - last_sync).total_seconds() < 60:
            return
        self._last_virtual_trade_sync = now

        try:
            broker_positions = await self.execution_adapter.get_positions()
            broker_has_position = any(
                getattr(p, 'quantity', 0) != 0 for p in broker_positions
            )

            # Get virtual trades that are "entered"
            recent_signals = self.state_manager.get_recent_signals(limit=300)
            latest_by_id: Dict[str, Dict] = {}
            for rec in recent_signals:
                if isinstance(rec, dict):
                    sig_id = str(rec.get("signal_id") or "")
                    if sig_id:
                        latest_by_id[sig_id] = rec

            entered_count = sum(
                1 for rec in latest_by_id.values()
                if rec.get("status") == "entered"
            )

            # If broker is flat but virtual trades show "entered", close them
            if not broker_has_position and entered_count > 0:
                closed = 0
                for sig_id, rec in latest_by_id.items():
                    if rec.get("status") == "entered":
                        self.state_manager.append_signal({
                            "signal_id": sig_id,
                            "status": "exited",
                            "exit_reason": "broker_flat_sync",
                            "exit_time": now.isoformat(),
                        })
                        closed += 1
                if closed > 0:
                    logger.info(
                        f"Broker sync: closed {closed} stale virtual trade(s) "
                        f"(broker is flat, virtual trades were still 'entered')"
                    )
        except Exception as e:
            logger.debug(f"Virtual trade broker sync check failed: {e}")

    def _get_status_snapshot(self) -> Dict[str, Any]:
        """Get current status snapshot for Pearl suggestions."""
        return _canonical_build_market_agent_status_snapshot(
            running=self.running,
            paused=self.paused,
            start_time=self.start_time,
            last_market_data=getattr(self.data_fetcher, "_last_market_data", None),
            data_quality_checker=self.data_quality_checker,
            performance_tracker=self.performance_tracker,
            connection_failures=self.connection_failures,
            max_connection_failures=self.max_connection_failures,
            signal_count=self.signal_count,
            quiet_period_minutes=self._compute_quiet_period_minutes(),
            config=self.config,
            trading_circuit_breaker=self.trading_circuit_breaker,
            streak_count=getattr(self, "_streak_count", 0),
            streak_type=getattr(self, "_streak_type", ""),
        )

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

            # Generate suggestion (engine handles cooldowns)
            suggestion = self.suggestion_engine.generate_suggestion(
                state,
                prefs=prefs
            )

            if suggestion:
                logger.info(f"Sending proactive PEARL suggestion: {suggestion.message}")

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

    def _build_pearl_review_message(self, state: Dict[str, Any]) -> Optional[str]:
        """Build PEARL check-in content (plain text, will be converted to MarkdownV2 by sender).
        
        Returns the message body only - header is added by send_pearl_notification.
        Focus on unique insights: streaks, observations, recommendations.
        """
        try:
            perf_trades = []
            try:
                perf_trades = self.performance_tracker.load_performance_data()
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
            return _canonical_build_pearl_review_message(
                state,
                perf_trades=perf_trades,
            )
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
        return _canonical_generate_pearl_insight(
            is_running=is_running,
            is_session_open=is_session_open,
            is_futures_open=is_futures_open,
            daily_pnl=daily_pnl,
            today_trades=today_trades,
        )

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
                        bar_time = parse_trade_timestamp_to_utc(raw_ts)
                    else:
                        bar_time = raw_ts
                    if bar_time and bar_time.tzinfo is None:
                        bar_time = bar_time.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.warning(f"Failed to parse bar timestamp in MTF trends: {e}")
            bar_time = None
        
        session_open = False
        try:
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
                            bar_time = parse_trade_timestamp_to_utc(bar_time)
                        elif bar_time.tzinfo is None:
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
        """Reset execution counters and circuit breaker at 6pm ET trading-day boundary."""
        from pearlalgo.market_agent.stats_computation import get_trading_day_start
        from datetime import date as _date
        today = get_trading_day_start().date()
        if not hasattr(self, "_cb_last_trading_day"):
            self._cb_last_trading_day = today
        if self._cb_last_trading_day != today:
            self._cb_last_trading_day = today
            if self.trading_circuit_breaker is not None:
                self.trading_circuit_breaker.reset_daily()
                logger.info(f"Trading circuit breaker daily reset for {today} (6pm ET)")
        self.execution_orchestrator.check_daily_reset()

    async def _check_execution_health(self) -> None:
        """Check execution adapter connection health and send alerts on state changes.

        Delegated to ExecutionOrchestrator.check_execution_health().
        """
        await self.execution_orchestrator.check_execution_health()

    async def _check_execution_control_flags(self) -> None:
        """Check for execution control flag files (from Telegram commands).

        Delegated to execution_flags.check_execution_control_flags().
        """
        await _check_execution_control_flags_impl(self)

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
            logger.debug(f"Non-critical connection check: {e}")

        # Fallback: if executor check failed but we're getting fresh data, we're connected
        if connection_status in ("unknown", "disconnected"):
            try:
                if self.data_fetcher.get_buffer_size() > 0 and self.connection_failures == 0:
                    connection_status = "connected"
            except Exception:
                pass

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

        now = datetime.now(_ET).replace(tzinfo=None)  # FIXED 2026-03-25: store ET not UTC
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

        now = datetime.now(_ET).replace(tzinfo=None)  # FIXED 2026-03-25: store ET not UTC
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

    def _os_signal_handler(self, signum, frame) -> None:
        """Handle OS shutdown signals (SIGINT/SIGTERM)."""
        signal_names = {
            signal.SIGINT: "SIGINT (Ctrl+C)",
            signal.SIGTERM: "SIGTERM",
        }
        signal_name = signal_names.get(signum, f"Signal {signum}")
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self.shutdown_requested = True
