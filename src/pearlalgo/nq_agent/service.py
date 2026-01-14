"""
NQ Agent Service

Main 24/7 service for running NQ intraday strategy.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import math

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp, parse_utc_timestamp

from pearlalgo.config.config_loader import load_service_config, parse_market_hours_overrides
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
from pearlalgo.nq_agent.health_monitor import HealthMonitor
from pearlalgo.nq_agent.performance_tracker import PerformanceTracker
from pearlalgo.nq_agent.state_manager import NQAgentStateManager
from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.strategies.nq_intraday.trade_manager import TradeManager
from pearlalgo.utils.cadence import CadenceMetrics, CadenceScheduler
from pearlalgo.utils.data_quality import DataQualityChecker
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.market_hours import configure_market_hours, get_market_hours
from pearlalgo.utils.volume_pressure import (
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)

# Execution layer imports (optional - only used if execution.enabled)
try:
    from pearlalgo.execution.base import ExecutionAdapter, ExecutionConfig
    from pearlalgo.execution.ibkr.adapter import IBKRExecutionAdapter
    EXECUTION_AVAILABLE = True
except ImportError:
    EXECUTION_AVAILABLE = False
    ExecutionAdapter = None  # type: ignore
    ExecutionConfig = None  # type: ignore
    IBKRExecutionAdapter = None  # type: ignore

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

# Drift guard (optional - enabled via drift_guard.enabled)
try:
    from pearlalgo.policy.drift_guard import DriftGuard, DriftGuardConfig
    DRIFT_GUARD_AVAILABLE = True
except ImportError:
    DRIFT_GUARD_AVAILABLE = False
    DriftGuard = None  # type: ignore
    DriftGuardConfig = None  # type: ignore

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

# Prop firm guard imports (optional - enabled via prop_firm.enabled)
try:
    from pearlalgo.prop_firm.guard import PropFirmConfig, PropFirmDecision, PropFirmGuard, PropFirmStatus
    PROP_FIRM_AVAILABLE = True
except ImportError:
    PROP_FIRM_AVAILABLE = False
    PropFirmConfig = None  # type: ignore
    PropFirmDecision = None  # type: ignore
    PropFirmGuard = None  # type: ignore
    PropFirmStatus = None  # type: ignore

# LLM Signal Annotator (optional - enabled via llm_signal_annotation.enabled)
try:
    from pearlalgo.nq_agent.signal_annotator import (
        LLMSignalAnnotator,
        SignalAnnotation,
        get_signal_annotator,
    )
    LLM_ANNOTATOR_AVAILABLE = True
except ImportError:
    LLM_ANNOTATOR_AVAILABLE = False
    LLMSignalAnnotator = None  # type: ignore
    SignalAnnotation = None  # type: ignore
    get_signal_annotator = lambda config: None  # type: ignore

# LLM Risk Assessor (optional - enabled via llm_risk_assessment.enabled)
try:
    from pearlalgo.nq_agent.risk_assessor import (
        RealTimeRiskAssessor,
        RiskAssessment,
        get_risk_assessor,
    )
    LLM_RISK_ASSESSOR_AVAILABLE = True
except ImportError:
    LLM_RISK_ASSESSOR_AVAILABLE = False
    RealTimeRiskAssessor = None  # type: ignore
    RiskAssessment = None  # type: ignore
    get_risk_assessor = lambda config: None  # type: ignore


class NQAgentService:
    """
    24/7 service for NQ intraday trading strategy.
    
    Runs independently, fetches data, generates signals, and sends to Telegram.
    """

    def __init__(
        self,
        data_provider: DataProvider,
        config: Optional[NQIntradayConfig] = None,
        state_dir: Optional[Path] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        """
        Initialize NQ agent service.
        
        Args:
            data_provider: Data provider instance
            config: Strategy configuration (optional)
            state_dir: State directory (optional)
            telegram_bot_token: Telegram bot token (optional)
            telegram_chat_id: Telegram chat ID (optional)
        """
        self.config = config or NQIntradayConfig()
        self.strategy = NQIntradayStrategy(config=self.config)
        self.data_fetcher = NQAgentDataFetcher(data_provider, config=self.config)
        
        # Initialize TradeManager for trailing stops and swing trade management
        service_config = load_service_config()
        self.trade_manager = TradeManager(service_config)
        self.state_manager = NQAgentStateManager(state_dir=state_dir)
        self.performance_tracker = PerformanceTracker(
            state_dir=state_dir,
            state_manager=self.state_manager,
        )
        self.telegram_notifier = NQAgentTelegramNotifier(
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
        )
        
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
        
        self.health_monitor = HealthMonitor(state_dir=state_dir)

        # Load service configuration
        service_config = load_service_config()
        service_settings = service_config.get("service", {})
        circuit_breaker_settings = service_config.get("circuit_breaker", {})
        data_settings = service_config.get("data", {})
        telegram_ui_settings = service_config.get("telegram_ui", {}) or {}

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
                            from pearlalgo.storage.async_sqlite_queue import AsyncSQLiteQueue, WritePriority
                            
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
                self.state_manager._async_sqlite_queue = self._async_sqlite_queue
                self.performance_tracker._async_sqlite_queue = self._async_sqlite_queue
            except Exception as e:
                logger.debug(f"Could not inject async queue into state/performance trackers: {e}")

        # ==========================================================================
        # 50K CHALLENGE TRACKER (Pass/Fail Rules)
        # ==========================================================================
        # Tracks account attempts with pass/fail thresholds.
        # PnL shown in Telegram = current attempt only (not all-time).
        self._challenge_tracker: Optional["ChallengeTracker"] = None
        self._challenge_enabled = False
        try:
            from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker, ChallengeConfig
            
            challenge_cfg = service_config.get("challenge", {}) or {}
            self._challenge_enabled = bool(challenge_cfg.get("enabled", False))
            if self._challenge_enabled:
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
        except Exception as e:
            logger.warning(f"Challenge tracker init failed (continuing without): {e}")
            self._challenge_tracker = None
            self._challenge_enabled = False

        # ==========================================================================
        # DRIFT GUARD (Risk-Off Cooldown)
        # ==========================================================================
        # Tightens filters + reduces sizing when performance degrades or volatility shocks.
        self._drift_guard: Optional["DriftGuard"] = None
        self._drift_guard_config: Optional["DriftGuardConfig"] = None
        self._drift_guard_state: Optional[Dict] = None
        self._drift_guard_last_alert_at: Optional[datetime] = None
        self._last_regime_snapshot: Optional[Dict] = None
        if DRIFT_GUARD_AVAILABLE and DriftGuard is not None and DriftGuardConfig is not None:
            try:
                self._drift_guard_config = DriftGuardConfig.from_dict(service_config)
                if self._drift_guard_config.enabled:
                    self._drift_guard = DriftGuard(
                        self._drift_guard_config,
                        state_path=(self.state_manager.state_dir / "drift_guard_state.json"),
                    )
                    self._drift_guard_state = self._drift_guard.state.to_dict(self._drift_guard_config)
                    logger.info(
                        "Drift guard enabled: cooldown=%sm lookback=%s min_trades=%s floor=%s size_mult=%s",
                        self._drift_guard_config.cooldown_minutes,
                        self._drift_guard_config.lookback_trades,
                        self._drift_guard_config.min_trades,
                        self._drift_guard_config.win_rate_floor,
                        self._drift_guard_config.size_multiplier,
                    )
                else:
                    logger.info("Drift guard disabled (drift_guard.enabled=false)")
            except Exception as e:
                logger.warning(f"Drift guard init failed (continuing without): {e}")
                self._drift_guard = None
                self._drift_guard_config = None
                self._drift_guard_state = None

        # ==========================================================================
        # ML LIFT GATING (Shadow A/B → allow blocking only if it shows lift)
        # ==========================================================================
        ml_cfg = service_config.get("ml_filter", {}) or {}
        self._ml_filter_mode = str(ml_cfg.get("mode", "shadow") or "shadow").lower()
        if self._ml_filter_mode not in ("shadow", "live"):
            self._ml_filter_mode = "shadow"
        self._ml_require_lift_to_block = bool(ml_cfg.get("require_lift_to_block", True))
        self._ml_lift_lookback_trades = int(ml_cfg.get("lift_lookback_trades", 200) or 200)
        self._ml_lift_min_trades = int(ml_cfg.get("lift_min_trades", 50) or 50)
        self._ml_lift_min_winrate_delta = float(ml_cfg.get("lift_min_winrate_delta", 0.05) or 0.05)
        # Default safe: do NOT allow live blocking until we have evaluated lift.
        self._ml_blocking_allowed: bool = False
        self._ml_lift_metrics: Dict[str, Any] = {}
        self._ml_lift_last_eval_at: Optional[datetime] = None

        # Telegram UI formatting (Home Card / dashboards)
        try:
            self._telegram_ui_compact_metrics_enabled = bool(
                telegram_ui_settings.get("compact_metrics_enabled", True)
            )
        except Exception:
            self._telegram_ui_compact_metrics_enabled = True
        try:
            self._telegram_ui_show_progress_bars = bool(
                telegram_ui_settings.get("show_progress_bars", False)
            )
        except Exception:
            self._telegram_ui_show_progress_bars = False
        try:
            self._telegram_ui_show_volume_metrics = bool(
                telegram_ui_settings.get("show_volume_metrics", True)
            )
        except Exception:
            self._telegram_ui_show_volume_metrics = True
        try:
            w = int(telegram_ui_settings.get("compact_metric_width", 10) or 10)
        except Exception:
            w = 10
        self._telegram_ui_compact_metric_width = max(5, min(20, w))

        # Configure optional market-hours overrides (disabled by default).
        # Keeps the declared boundary intact: config drives utils, never the reverse.
        try:
            holidays, early_closes = parse_market_hours_overrides(service_config)
            configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
        except Exception as e:
            logger.warning(f"Could not configure market hours overrides: {e}")

        # ==========================================================================
        # PROP FIRM GUARD (optional)
        # ==========================================================================
        # This is *separate* from strategy risk parameters and is intended to:
        # - Protect evaluation accounts (max contracts, max loss, consistency)
        # - Annotate signals (manual workflow) and/or gate ATS execution (auto workflow)
        self.prop_firm_guard: Optional["PropFirmGuard"] = None
        self._prop_firm_config: Optional["PropFirmConfig"] = None
        self._prop_firm_status: Optional["PropFirmStatus"] = None

        prop_firm_settings = service_config.get("prop_firm", {}) or {}
        if PROP_FIRM_AVAILABLE and isinstance(prop_firm_settings, dict):
            try:
                # Build config from service config with session-aware defaults
                self._prop_firm_config = PropFirmConfig.from_dict(
                    prop_firm_settings,
                    session_start_time=str(getattr(self.config, "start_time", "") or ""),
                    session_end_time=str(getattr(self.config, "end_time", "") or ""),
                )
                if self._prop_firm_config.enabled:
                    self.prop_firm_guard = PropFirmGuard(
                        self._prop_firm_config,
                        state_dir=self.state_manager.state_dir,
                    )
                    # Seed status for first cycle (best-effort)
                    try:
                        self._prop_firm_status = self.prop_firm_guard.compute_status()
                    except Exception:
                        self._prop_firm_status = None
                    logger.info(
                        f"Prop firm guard enabled: profile={self._prop_firm_config.profile}, "
                        f"account_size=${self._prop_firm_config.account_size:,.0f}"
                    )
                else:
                    logger.info("Prop firm guard disabled (prop_firm.enabled=false)")
            except Exception as e:
                logger.error(f"Failed to initialize prop firm guard: {e}", exc_info=True)
                self.prop_firm_guard = None
                self._prop_firm_config = None
                self._prop_firm_status = None
        else:
            if not PROP_FIRM_AVAILABLE:
                logger.debug("Prop firm guard not available (import failed)")

        # ==========================================================================
        # LLM SIGNAL ANNOTATOR (optional)
        # ==========================================================================
        # Provides AI-powered analysis/explanation of signals for Telegram messages.
        # Non-blocking with timeout - failures don't affect signal processing.
        self.signal_annotator: Optional["LLMSignalAnnotator"] = None
        
        llm_annotation_settings = service_config.get("llm_signal_annotation", {}) or {}
        if LLM_ANNOTATOR_AVAILABLE and isinstance(llm_annotation_settings, dict):
            try:
                if llm_annotation_settings.get("enabled", False):
                    self.signal_annotator = get_signal_annotator(service_config)
                    if self.signal_annotator and self.signal_annotator.is_available:
                        logger.info(
                            f"LLM signal annotator enabled: model={self.signal_annotator.model}, "
                            f"timeout={self.signal_annotator.timeout_seconds}s"
                        )
                    else:
                        logger.info("LLM signal annotator enabled but unavailable (API key missing?)")
                        self.signal_annotator = None
                else:
                    logger.info("LLM signal annotator disabled (llm_signal_annotation.enabled=false)")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM signal annotator: {e}")
                self.signal_annotator = None
        else:
            if not LLM_ANNOTATOR_AVAILABLE:
                logger.debug("LLM signal annotator not available (import failed)")

        # ==========================================================================
        # LLM RISK ASSESSOR (optional)
        # ==========================================================================
        # Provides a fast, best-effort pre-trade risk check.
        # This does NOT block signals by default; it adds context to Telegram.
        self.risk_assessor: Optional["RealTimeRiskAssessor"] = None

        llm_risk_settings = service_config.get("llm_risk_assessment", {}) or {}
        if LLM_RISK_ASSESSOR_AVAILABLE and isinstance(llm_risk_settings, dict):
            try:
                if llm_risk_settings.get("enabled", False):
                    self.risk_assessor = get_risk_assessor(service_config)
                    if self.risk_assessor and self.risk_assessor.is_available:
                        logger.info(
                            f"LLM risk assessor enabled: model={self.risk_assessor.model}, "
                            f"timeout={self.risk_assessor.timeout_seconds}s, "
                            f"block_on_critical={self.risk_assessor.block_on_critical}"
                        )
                    else:
                        logger.info("LLM risk assessor enabled but unavailable (API key missing?)")
                        self.risk_assessor = None
                else:
                    logger.info("LLM risk assessor disabled (llm_risk_assessment.enabled=false)")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM risk assessor: {e}")
                self.risk_assessor = None
        else:
            if not LLM_RISK_ASSESSOR_AVAILABLE:
                logger.debug("LLM risk assessor not available (import failed)")

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
            # Count actual signals in signals file for accuracy
            signals_file = self.state_manager.signals_file
            if signals_file.exists():
                actual_signal_count = sum(1 for _ in open(signals_file)) if signals_file.exists() else 0
                self.signal_count = max(saved_signal_count, actual_signal_count)
                logger.info(f"Restored signal_count: {self.signal_count} (from state: {saved_signal_count}, from file: {actual_signal_count})")
            else:
                self.signal_count = saved_signal_count
                logger.info(f"Restored signal_count: {self.signal_count} (from state, no signals file yet)")
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
        # Dashboard chart (hourly mplfinance screenshot)
        self.last_dashboard_chart_sent: Optional[datetime] = None
        self.dashboard_chart_enabled = bool(service_settings.get("dashboard_chart_enabled", True))  # can disable auto charts
        self.dashboard_chart_interval = service_settings.get("dashboard_chart_interval", 3600)  # 1 hour default
        self.dashboard_chart_lookback_hours = float(service_settings.get("dashboard_chart_lookback_hours", 48) or 48)
        self.dashboard_chart_timeframe = str(service_settings.get("dashboard_chart_timeframe", "auto") or "auto")
        self.dashboard_chart_max_bars = int(service_settings.get("dashboard_chart_max_bars", 420) or 420)
        self.dashboard_chart_show_pressure = bool(service_settings.get("dashboard_chart_show_pressure", True))
        # Buy/Sell pressure (dashboard observability)
        self.pressure_lookback_bars = int(service_settings.get("pressure_lookback_bars", 24) or 24)
        self.pressure_baseline_bars = int(service_settings.get("pressure_baseline_bars", 120) or 120)
        self.state_save_interval = service_settings.get("state_save_interval", 10)
        self.connection_failure_alert_interval = service_settings.get("connection_failure_alert_interval", 600)
        self.data_quality_alert_interval = service_settings.get("data_quality_alert_interval", 300)
        self.consecutive_errors = 0
        self.max_consecutive_errors = circuit_breaker_settings.get("max_consecutive_errors", 10)
        self.data_fetch_errors = 0
        self.max_data_fetch_errors = circuit_breaker_settings.get("max_data_fetch_errors", 5)
        self.connection_failures = 0
        self.max_connection_failures = circuit_breaker_settings.get("max_connection_failures", 10)
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
        self._effective_interval: float = float(self.config.scan_interval)  # Current effective interval
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
            (execution_settings or {}).get("adapter", "ibkr")
        ).strip().lower()
        
        if EXECUTION_AVAILABLE and execution_settings.get("enabled", False):
            try:
                self._execution_config = ExecutionConfig.from_dict(execution_settings)
                if execution_adapter_name in ("ibkr", "", "interactivebrokers"):
                    self.execution_adapter = IBKRExecutionAdapter(self._execution_config)
                elif execution_adapter_name in ("tradovate", "tdv"):
                    from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
                    self.execution_adapter = TradovateExecutionAdapter(self._execution_config)
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
        # LEARNING (Adaptive Bandit Policy)
        # ==========================================================================
        # Initialize adaptive policy for signal type selection.
        # SAFETY: Default is shadow mode - learns but does NOT affect execution.
        self.bandit_policy: Optional["BanditPolicy"] = None
        self._bandit_config: Optional["BanditConfig"] = None
        self.contextual_policy: Optional["ContextualBanditPolicy"] = None
        self._contextual_config: Optional["ContextualBanditConfig"] = None
        learning_settings = service_config.get("learning", {})
        
        if LEARNING_AVAILABLE and learning_settings.get("enabled", True):
            try:
                self._bandit_config = BanditConfig.from_dict(learning_settings)
                # Use state_manager.state_dir to ensure policy_state.json is written
                # alongside state.json (where Telegram commands expect it)
                self.bandit_policy = BanditPolicy(
                    config=self._bandit_config,
                    state_dir=self.state_manager.state_dir,
                )
                logger.info(
                    f"Bandit policy initialized: mode={self._bandit_config.mode}, "
                    f"threshold={self._bandit_config.decision_threshold}, "
                    f"explore_rate={self._bandit_config.explore_rate}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize bandit policy: {e}", exc_info=True)
                self.bandit_policy = None
        else:
            if not LEARNING_AVAILABLE:
                logger.debug("Learning layer not available (import failed)")
            else:
                logger.info("Bandit policy disabled (learning.enabled=false)")

        # Contextual learning (optional): learns signal quality per session/regime/time bucket.
        # This is safe in manual mode because it only annotates signals + records outcomes.
        if CONTEXTUAL_BANDIT_AVAILABLE:
            contextual_settings = learning_settings.get("contextual", {})
            if not isinstance(contextual_settings, dict):
                contextual_settings = {}
            if bool(contextual_settings.get("enabled", False)):
                try:
                    self._contextual_config = ContextualBanditConfig.from_dict(contextual_settings)
                    self.contextual_policy = ContextualBanditPolicy(
                        config=self._contextual_config,
                        state_dir=self.state_manager.state_dir,
                    )
                    logger.info(
                        "Contextual policy initialized: mode=%s threshold=%s explore_rate=%s",
                        getattr(self._contextual_config, "mode", "shadow"),
                        getattr(self._contextual_config, "decision_threshold", 0.3),
                        getattr(self._contextual_config, "explore_rate", 0.1),
                    )
                except Exception as e:
                    logger.error(f"Failed to initialize contextual bandit policy: {e}", exc_info=True)
                    self.contextual_policy = None
            else:
                logger.info("Contextual policy disabled (learning.contextual.enabled=false)")
        else:
            logger.debug("Contextual bandit not available (import failed)")

        logger.info("NQAgentService initialized")

    async def start(self) -> None:
        """Start the service."""
        if self.running:
            logger.warning("Service already running")
            return

        self.running = True
        self.shutdown_requested = False
        self.start_time = datetime.now(timezone.utc)
        # Establish session baselines for derived counters (cycles/signals since start)
        self._cycle_count_at_start = int(self.cycle_count or 0)
        self._signal_count_at_start = int(self.signal_count or 0)
        self._signals_sent_at_start = int(self.signals_sent or 0)
        self._signals_fail_at_start = int(self.signals_send_failures or 0)

        # Setup signal handlers
        # Note: These set shutdown_requested flag, stop() is called in finally block
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("NQ Agent Service starting...")

        # Send startup notification immediately (before connection attempts)
        # This ensures user gets notified even if connection fails
        try:
            config_dict = {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
                "stop_loss_atr_multiplier": self.config.stop_loss_atr_multiplier,
                "take_profit_risk_reward": self.config.take_profit_risk_reward,
                "max_risk_per_trade": self.config.max_risk_per_trade,
                "current_time": get_utc_timestamp(),
            }

            # Include explicit market/session gates so startup never shows UNKNOWN in Telegram UI.
            try:
                config_dict["futures_market_open"] = bool(get_market_hours().is_market_open())
            except Exception:
                config_dict["futures_market_open"] = None
            try:
                config_dict["strategy_session_open"] = bool(self.strategy.scanner.is_market_hours())
            except Exception:
                config_dict["strategy_session_open"] = None
            
            # Try to get latest price for startup message (non-blocking, timeout quickly)
            try:
                market_data = await asyncio.wait_for(
                    self.data_fetcher.fetch_latest_data(),
                    timeout=5.0
                )
                if market_data.get("latest_bar"):
                    latest_bar = market_data["latest_bar"]
                    if isinstance(latest_bar, dict) and "close" in latest_bar:
                        config_dict["latest_price"] = latest_bar["close"]
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"Could not fetch price for startup notification: {e}")
                # Continue without price - service will still start
            
            await self.telegram_notifier.send_startup_notification(config_dict)
            logger.info("Startup notification sent to Telegram")
        except Exception as e:
            logger.error(f"Could not send startup notification: {e}", exc_info=True)

        # Connect execution adapter if enabled
        if self.execution_adapter is not None:
            try:
                connected = await self.execution_adapter.connect()
                if connected:
                    logger.info(
                        f"✅ Execution adapter connected (mode={self._execution_config.mode.value}, "
                        f"armed={self.execution_adapter.armed})"
                    )
                else:
                    logger.warning("⚠️ Execution adapter failed to connect - orders will not be placed")
            except Exception as e:
                logger.error(f"Error connecting execution adapter: {e}", exc_info=True)

        try:
            await self._run_loop()
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt, shutting down gracefully...")
            await self.stop("Keyboard interrupt (Ctrl+C)")
        except Exception as e:
            logger.error(f"Service error: {e}", exc_info=True)
            await self.stop(f"Error: {str(e)[:50]}")
        finally:
            # Ensure stop is called even if exception occurred
            if self.running:
                await self.stop("Final cleanup")

    async def stop(self, shutdown_reason: str = "Normal shutdown") -> None:
        """Stop the service."""
        if not self.running:
            return

        logger.info(f"Stopping NQ Agent Service... ({shutdown_reason})")
        self.shutdown_requested = True

        # Flush async SQLite queue before shutdown
        if self._async_sqlite_queue is not None:
            try:
                self._async_sqlite_queue.stop(timeout=5.0)
            except Exception as e:
                logger.warning(f"Error stopping async SQLite queue: {e}")

        # Save final state
        try:
            self._save_state()
        except Exception as e:
            logger.warning(f"Could not save final state: {e}")

        # Send shutdown notification (with timeout to ensure it doesn't block)
        # IMPORTANT: Send this BEFORE setting running=False so Telegram is still available
        try:
            uptime_delta = datetime.now(timezone.utc) - self.start_time if self.start_time else None
            summary = {
                "uptime_hours": int(uptime_delta.total_seconds() / 3600) if uptime_delta else 0,
                "uptime_minutes": int((uptime_delta.total_seconds() % 3600) / 60) if uptime_delta else 0,
                "cycle_count": self.cycle_count,
                "signal_count": self.signal_count,
                "error_count": self.error_count,
                "shutdown_reason": shutdown_reason,
            }

            # Add performance metrics if available
            try:
                performance = self.performance_tracker.get_performance_metrics(days=7)
                summary["wins"] = performance.get("wins", 0)
                summary["losses"] = performance.get("losses", 0)
                summary["total_pnl"] = performance.get("total_pnl", 0)
            except Exception:
                pass

            # Send with timeout to ensure it doesn't hang, but log if it fails
            logger.info(f"Sending shutdown notification: {shutdown_reason}")
            try:
                await asyncio.wait_for(
                    self.telegram_notifier.send_shutdown_notification(summary),
                    timeout=10.0  # Increased timeout to give more time
                )
                logger.info("✅ Shutdown notification sent to Telegram")
            except asyncio.TimeoutError:
                logger.error("❌ Timeout sending shutdown notification - Telegram may be slow or unreachable")
                # Try one more time without timeout as last resort
                try:
                    await self.telegram_notifier.send_shutdown_notification(summary)
                    logger.info("✅ Shutdown notification sent on retry")
                except Exception as retry_e:
                    logger.error(f"❌ Failed to send shutdown notification on retry: {retry_e}")
        except Exception as e:
            logger.error(f"❌ Error sending shutdown notification: {e}", exc_info=True)

        # Disconnect execution adapter
        if self.execution_adapter is not None:
            try:
                # Disarm first as safety measure
                self.execution_adapter.disarm()
                await self.execution_adapter.disconnect()
                logger.info("Execution adapter disconnected")
            except Exception as e:
                logger.warning(f"Error disconnecting execution adapter: {e}")

        self.running = False
        logger.info("NQ Agent Service stopped")

    async def _run_loop(self) -> None:
        """Main service loop."""
        logger.info(
            "Starting main loop",
            extra={
                "scan_interval": self.config.scan_interval,
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "cadence_mode": self.cadence_mode,
            },
        )

        while not self.shutdown_requested:
            # Check for execution control flag files (from Telegram commands)
            await self._check_execution_control_flags()
            
            # Reset execution daily counters if new trading day
            self._check_daily_reset()
            
            # Check execution adapter connection health and alert on issues
            await self._check_execution_health()
            
            # Adaptive cadence: compute effective interval for this cycle (includes velocity mode)
            if self._adaptive_cadence_enabled:
                self._effective_interval = self._compute_effective_interval()
                if self._effective_interval != self._last_effective_interval:
                    # Log interval change (velocity transitions are logged separately in _compute_effective_interval)
                    if not self._velocity_mode_active:
                        logger.info(
                            f"Adaptive cadence: interval changed {self._last_effective_interval}s → {self._effective_interval}s",
                            extra={
                                "old_interval": self._last_effective_interval,
                                "new_interval": self._effective_interval,
                                "cycle": self.cycle_count,
                            },
                        )
                    # Update cadence scheduler with new interval (velocity mode state already set in _compute_effective_interval)
                    if self.cadence_scheduler and not self._velocity_mode_active:
                        self.cadence_scheduler.set_interval(self._effective_interval, velocity_mode=False)
                    self._last_effective_interval = self._effective_interval

            # Mark cycle start for cadence tracking (fixed-cadence mode)
            if self.cadence_scheduler:
                cadence_lag = self.cadence_scheduler.mark_cycle_start()
                if cadence_lag > 1000:  # More than 1s lag
                    logger.warning(
                        f"Cadence lag detected: {cadence_lag:.0f}ms behind schedule",
                        extra={"cycle": self.cycle_count, "cadence_lag_ms": cadence_lag},
                    )

            try:
                # Skip if paused
                if self.paused:
                    logger.info(
                        "Service paused; skipping cycle",
                        extra={
                            "cycle": self.cycle_count,
                            "pause_reason": self.pause_reason,
                        },
                    )
                    # Reset cadence scheduler on pause to avoid catch-up storm on resume
                    if self.cadence_scheduler:
                        self.cadence_scheduler.reset()
                    # SAFETY: Use interruptible sleep so kill commands are processed even when paused
                    await self._interruptible_sleep(self._scan_interval_paused)
                    continue

                # Fetch latest data with error handling
                try:
                    market_data = await self.data_fetcher.fetch_latest_data()

                    # Check if data is empty due to connection issues
                    is_connection_error = ErrorHandler.is_connection_error_from_data(
                        market_data,
                        data_provider=self.data_fetcher.data_provider,
                        last_successful_cycle=self.last_successful_cycle,
                    )

                    if is_connection_error:
                        # This is a connection issue, not just empty data
                        self.connection_failures += 1
                        self.data_fetch_errors += 1
                        self.error_count += 1

                        # Alert on connection failures
                        await self._handle_connection_failure()

                        # Circuit breaker: pause service if too many connection failures
                        if self.connection_failures >= self.max_connection_failures:
                            logger.error(
                                "Circuit breaker triggered: connection failures",
                                extra={
                                    "connection_failures": self.connection_failures,
                                    "max_connection_failures": self.max_connection_failures,
                                    "cycle": self.cycle_count,
                                },
                            )
                            await self.telegram_notifier.send_circuit_breaker_alert(
                                "IB Gateway connection lost",
                                {
                                    "connection_failures": self.connection_failures,
                                    "error_type": "connection",
                                    "action_taken": "Service paused - IB Gateway appears to be down",
                                }
                            )
                            self.paused = True
                            self.pause_reason = "connection_failures"

                        await self._sleep_until_next_cycle()
                        continue

                    # Success - reset error counters
                    self.data_fetch_errors = 0
                    self.connection_failures = 0
                    self.last_successful_cycle = datetime.now(timezone.utc)

                    # Check data quality
                    await self._check_data_quality(market_data)

                except Exception as e:
                    # Use ErrorHandler for standardized error handling
                    error_info = ErrorHandler.handle_data_fetch_error(
                        e,
                        context={"cycle_count": self.cycle_count},
                    )
                    self.data_fetch_errors += 1
                    self.error_count += 1

                    # Check if this is a connection error
                    if error_info.get("is_connection_error", False):
                        self.connection_failures += 1
                        await self._handle_connection_failure()

                    # Alert on consecutive fetch failures
                    if self.data_fetch_errors >= 3:
                        await self.telegram_notifier.send_data_quality_alert(
                            "fetch_failure",
                            f"Consecutive data fetch failures: {self.data_fetch_errors}",
                            {"consecutive_failures": self.data_fetch_errors},
                        )

                    # Circuit breaker: if too many data fetch errors, wait longer
                    if self.data_fetch_errors >= self.max_data_fetch_errors:
                        logger.warning(
                            "Data fetch error threshold reached; backing off",
                            extra={
                                "data_fetch_errors": self.data_fetch_errors,
                                "max_data_fetch_errors": self.max_data_fetch_errors,
                                "backoff_seconds": self.config.scan_interval * 2,
                                "cycle": self.cycle_count,
                            },
                        )
                        await self._notify_error("Data fetch failures", f"{self.data_fetch_errors} consecutive errors")
                        # Backoff: sleep longer than normal cycle, reset cadence scheduler
                        if self.cadence_scheduler:
                            self.cadence_scheduler.reset()
                        # SAFETY: Use interruptible sleep so kill commands are processed during backoff
                        await self._interruptible_sleep(self.config.scan_interval * 2)
                    else:
                        await self._sleep_until_next_cycle()
                    continue

                if market_data["df"].empty:
                    # Empty data could be normal (market closed) or a problem
                    # Check if we've had recent successful cycles
                    if self.last_successful_cycle:
                        time_since_success = (datetime.now(timezone.utc) - self.last_successful_cycle).total_seconds()
                        timeout_seconds = self.connection_timeout_minutes * 60
                        if time_since_success > timeout_seconds:
                            logger.warning(f"No market data for {self.connection_timeout_minutes}+ minutes - possible connection issue")
                            await self._handle_connection_failure()

                    # Determine quiet reason for observability
                    quiet_reason = self._get_quiet_reason(market_data, has_data=False)
                    
                    # Persist to instance variables for _save_state() (surfaced in /status)
                    self._last_quiet_reason = quiet_reason
                    self._last_signal_diagnostics = None
                    
                    logger.debug(
                        "No market data available, waiting",
                        extra={
                            "cycle": self.cycle_count,
                            "connection_failures": self.connection_failures,
                            "quiet_reason": quiet_reason,
                        },
                    )
                    
                    # Still emit dashboard even when quiet (observability)
                    await self._check_dashboard(market_data, quiet_reason=quiet_reason)
                    self.cycle_count += 1
                    
                    await self._sleep_until_next_cycle()
                    continue

                # New-bar gating: skip heavy analysis if df hasn't advanced (performance optimization).
                # When enabled, we only run strategy.analyze() when a new bar arrives.
                # This is high leverage for configs like 5m bars + 30s scan interval.
                skip_analysis = False
                current_bar_ts = None
                if self._enable_new_bar_gating and not market_data["df"].empty:
                    # Extract latest bar timestamp from df
                    df = market_data["df"]
                    if "timestamp" in df.columns:
                        current_bar_ts = df["timestamp"].max()
                        if isinstance(current_bar_ts, pd.Timestamp):
                            current_bar_ts = current_bar_ts.to_pydatetime()
                        if current_bar_ts is not None and current_bar_ts.tzinfo is None:
                            current_bar_ts = current_bar_ts.replace(tzinfo=timezone.utc)
                        
                        # Check if bar has advanced since last analyzed cycle
                        if self._last_analyzed_bar_ts is not None and current_bar_ts == self._last_analyzed_bar_ts:
                            skip_analysis = True
                            self._analysis_skip_count += 1
                            logger.debug(
                                "New-bar gating: skipping analysis (bar unchanged)",
                                extra={
                                    "bar_ts": current_bar_ts.isoformat() if current_bar_ts else None,
                                    "skip_count": self._analysis_skip_count,
                                    "run_count": self._analysis_run_count,
                                    "cycle": self.cycle_count,
                                },
                            )

                # Inject safety/learning state into market_data so downstream signal generation can:
                # - run ML filter in score-only or lift-gated blocking mode
                # - apply drift guard cooldown adjustments (tighten filters + reduce size)
                try:
                    if isinstance(market_data, dict):
                        market_data["ml_blocking_allowed"] = bool(getattr(self, "_ml_blocking_allowed", False))
                        market_data["drift_guard"] = self._drift_guard_state or {"active": False}
                except Exception:
                    pass

                # Generate signals (or skip if no new bar)
                signals = []
                if skip_analysis:
                    # Lightweight cycle: skip heavy analysis, but still run health/status/exit grading
                    pass
                else:
                    # Full analysis: new bar arrived
                    signals = self.strategy.analyze(market_data)
                    self._analysis_run_count += 1
                    # Update last analyzed bar timestamp
                    if current_bar_ts is not None:
                        self._last_analyzed_bar_ts = current_bar_ts
                
                # Log cycle summary for observability
                data_fresh = True
                latest_bar_time: Optional[datetime] = None
                if market_data.get("latest_bar"):
                    raw_bar_time = market_data["latest_bar"].get("timestamp")
                    if raw_bar_time:
                        if isinstance(raw_bar_time, str):
                            latest_bar_time = parse_utc_timestamp(raw_bar_time)
                        else:
                            latest_bar_time = raw_bar_time
                        # Timezone-safe age computation: convert to UTC if aware, assume UTC if naive
                        if latest_bar_time.tzinfo is None:
                            latest_bar_time = latest_bar_time.replace(tzinfo=timezone.utc)
                        else:
                            latest_bar_time = latest_bar_time.astimezone(timezone.utc)
                        age_seconds = (datetime.now(timezone.utc) - latest_bar_time).total_seconds()
                        stale_threshold_seconds = self.stale_data_threshold_minutes * 60
                        data_fresh = age_seconds < stale_threshold_seconds
                
                # Prefer latest_bar timestamp for session check (reduces wall-clock drift issues).
                # Fall back to wall-clock time if no latest_bar available.
                strategy_session_open = self.strategy.scanner.is_market_hours(dt=latest_bar_time)
                futures_market_open = False
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = False
                regime_info = "unknown"
                if hasattr(self.strategy, 'scanner') and hasattr(self.strategy.scanner, 'regime_detector'):
                    # Try to get last detected regime (would need to store it)
                    regime_info = "detected"
                
                logger.info(
                    "Cycle completed",
                    extra={
                        "cycle": self.cycle_count,
                        "signals": len(signals),
                        "data_fresh": data_fresh,
                        # Keep legacy field name for backward compatibility, but make semantics explicit.
                        # Historically this has meant the strategy trading session window (09:30–16:00 ET).
                        "market_open": strategy_session_open,
                        "strategy_session_open": strategy_session_open,
                        "futures_market_open": futures_market_open,
                        "buffer_size": self.data_fetcher.get_buffer_size(),
                        "error_count": self.error_count,
                        "consecutive_errors": self.consecutive_errors,
                        "connection_failures": self.connection_failures,
                        "data_fetch_errors": self.data_fetch_errors,
                    },
                )

                # Process signals
                if signals:
                    logger.info(f"🔔 Processing {len(signals)} signal(s) from strategy analysis")
                    for i, signal in enumerate(signals, 1):
                        signal_type = signal.get('type', 'unknown')
                        signal_direction = signal.get('direction', 'unknown')
                        trade_type = signal.get('trade_type', 'scalp')
                        logger.info(f"  Signal {i}/{len(signals)}: {signal_type} {signal_direction} ({trade_type})")
                        
                        # Notify if swing trade detected
                        if trade_type == "swing":
                            try:
                                await self.telegram_notifier.send_message(
                                    f"📈 Swing Trade Detected: {signal_type} {signal_direction}\n"
                                    f"Confidence: {signal.get('confidence', 0):.1%}\n"
                                    f"Target: ${signal.get('take_profit', 0):.2f}"
                                )
                            except Exception:
                                pass  # Non-fatal
                        
                        # Add trade to TradeManager for trailing stop management
                        # Get buffer data for chart generation
                        buffer_data = market_data.get("df", pd.DataFrame())
                        await self._process_signal(signal, buffer_data=buffer_data)
                else:
                    logger.debug(f"No signals generated in cycle {self.cycle_count}")

                # Update active trades with trailing stops (NO LIMITS - can handle 100+ trades)
                try:
                    # Prepare market data for TradeManager
                    df = market_data.get("df", pd.DataFrame())
                    latest_bar = market_data.get("latest_bar", {})
                    current_price = float(latest_bar.get("close", 0)) if latest_bar else (float(df["close"].iloc[-1]) if not df.empty else 0)
                    previous_price = float(df["close"].iloc[-2]) if len(df) >= 2 else current_price
                    
                    # Get ATR from scanner if available
                    atr = 10.0  # Default
                    if hasattr(self.strategy.scanner, "get_atr") and not df.empty:
                        try:
                            atr = float(self.strategy.scanner.get_atr(df))
                        except Exception:
                            pass
                    
                    # Update trades with current market data
                    trade_market_data = {
                        "current_price": current_price,
                        "previous_price": previous_price,
                        "atr": atr,
                        "rolling_atr": atr,  # Could calculate rolling ATR if needed
                        "market_open": market_data.get("market_open", True),
                    }
                    
                    # Track stop updates for notifications
                    active_trades_before = len(self.trade_manager.get_active_trades())
                    exit_signals = self.trade_manager.update_trades(trade_market_data)
                    
                    # Notify on significant stop updates (breakeven moves, large trailing updates)
                    for trade in self.trade_manager.get_active_trades():
                        # Persist stop changes so virtual exit grading uses the latest stop_loss.
                        # (Virtual exits read stop_loss from the nested `signal` in signals.jsonl.)
                        try:
                            if (
                                getattr(trade, "last_stop_update", None)
                                and str(getattr(trade, "signal_id", "") or "")
                                and float(getattr(trade, "stop_loss", 0.0) or 0.0) > 0
                            ):
                                current_stop = float(trade.stop_loss)
                                prev_stop = getattr(trade, "last_persisted_stop_loss", None)
                                if (prev_stop is None) or (abs(current_stop - float(prev_stop)) > 1e-9):
                                    self.performance_tracker.update_signal_prices(
                                        signal_id=str(trade.signal_id),
                                        stop_loss=current_stop,
                                        updated_at=trade.last_stop_update,
                                        source="trailing_stop",
                                    )
                                    trade.last_persisted_stop_loss = current_stop
                        except Exception:
                            pass

                        if trade.breakeven_moved and trade.last_stop_update:
                            # Check if this is a recent breakeven move (within last cycle)
                            time_since_update = (datetime.now(timezone.utc) - trade.last_stop_update).total_seconds()
                            if time_since_update < 120:  # Within 2 minutes
                                try:
                                    await self.telegram_notifier.send_message(
                                        f"🛡️ Stop to Breakeven: {trade.signal_id[:8]}\n"
                                        f"Entry: ${trade.entry_price:.2f}\n"
                                        f"Stop: ${trade.stop_loss:.2f}"
                                    )
                                except Exception:
                                    pass  # Non-fatal
                    
                    # Process exit signals (could trigger notifications, execution, etc.)
                    for exit_signal in exit_signals:
                        signal_id = exit_signal.get("signal_id")
                        exit_reason = exit_signal.get("exit_reason")
                        exit_price = exit_signal.get("exit_price")
                        
                        logger.info(
                            "Trade exit detected: signal_id=%s, reason=%s, price=%.2f",
                            signal_id,
                            exit_reason,
                            exit_price,
                        )
                        
                        # Send Telegram notification for trade exit
                        try:
                            await self.telegram_notifier.send_message(
                                f"🔄 Trade Exit: {signal_id[:8]}\n"
                                f"Reason: {exit_reason}\n"
                                f"Exit Price: ${exit_price:.2f}"
                            )
                        except Exception as e:
                            logger.debug(f"Failed to send exit notification (non-fatal): {e}")
                        
                        # TODO: Update virtual PnL tracking
                except Exception as e:
                    logger.debug(f"Trade manager update failed (non-fatal): {e}")
                
                # Virtual PnL lifecycle: exit signals when TP/SL is touched (no Telegram spam).
                # This grades signal quality without auto-trading.
                try:
                    self._update_virtual_trade_exits(market_data)
                except Exception as e:
                    logger.debug(f"Virtual exit update failed (non-fatal): {e}")

                # Refresh drift guard + ML lift metrics AFTER we grade exits (so decisions use latest outcomes).
                try:
                    await self._refresh_drift_guard()
                except Exception as e:
                    logger.debug(f"Drift guard refresh failed (non-fatal): {e}")
                try:
                    self._refresh_ml_lift()
                except Exception as e:
                    logger.debug(f"ML lift refresh failed (non-fatal): {e}")

                # Send periodic dashboard (replaces status + heartbeat)
                # Determine quiet reason (for observability) and capture diagnostics every cycle (for SQLite rollups).
                quiet_reason = "Active" if signals else self._get_quiet_reason(market_data, has_data=True, no_signals=True)
                signal_diagnostics = None
                signal_diagnostics_raw = None

                # Note: NQIntradayStrategy uses `signal_generator` (not `generator`)
                try:
                    if hasattr(self.strategy, "signal_generator") and hasattr(self.strategy.signal_generator, "last_diagnostics"):
                        diag = self.strategy.signal_generator.last_diagnostics
                        if diag is not None:
                            # Render as compact string for Telegram (e.g., "Raw: 3 → Valid: 0 | Filtered: 2 conf")
                            signal_diagnostics = diag.format_compact() if hasattr(diag, "format_compact") else str(diag)
                            try:
                                signal_diagnostics_raw = diag.to_dict() if hasattr(diag, "to_dict") else None
                            except Exception:
                                signal_diagnostics_raw = None
                except Exception:
                    pass
                
                # Persist to instance variables for _save_state() (surfaced in /status)
                self._last_quiet_reason = quiet_reason
                self._last_signal_diagnostics = signal_diagnostics
                self._last_signal_diagnostics_raw = signal_diagnostics_raw

                # SQLite observability: persist per-cycle diagnostics for 24h /doctor summaries.
                self._persist_cycle_diagnostics(
                    quiet_reason=quiet_reason,
                    diagnostics_raw=signal_diagnostics_raw,
                )
                
                await self._check_dashboard(market_data, quiet_reason=quiet_reason, signal_diagnostics=signal_diagnostics)

                # Save state periodically
                if self.cycle_count % self.state_save_interval == 0:
                    self._save_state()

                self.cycle_count += 1

                # Wait for next cycle (fixed-cadence or legacy sleep-after-work)
                await self._sleep_until_next_cycle()

            except asyncio.CancelledError:
                logger.info("Service loop cancelled", extra={"cycle": self.cycle_count})
                break
            except Exception as e:
                logger.error(
                    f"Error in service loop: {e}",
                    exc_info=True,
                    extra={"cycle": self.cycle_count},
                )
                self.error_count += 1
                self.consecutive_errors += 1

                # Circuit breaker: if too many consecutive errors, pause service
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.error(
                        "Circuit breaker triggered: consecutive errors",
                        extra={
                            "consecutive_errors": self.consecutive_errors,
                            "max_consecutive_errors": self.max_consecutive_errors,
                            "cycle": self.cycle_count,
                        },
                    )
                    await self.telegram_notifier.send_circuit_breaker_alert(
                        "Too many consecutive errors",
                        {
                            "consecutive_errors": self.consecutive_errors,
                            "error_type": "general",
                            "action_taken": "Service paused",
                        },
                    )
                    self.paused = True
                    self.pause_reason = "consecutive_errors"

                await self._sleep_until_next_cycle()
            else:
                # Reset consecutive errors on successful cycle
                had_errors = self.consecutive_errors > 0
                self.consecutive_errors = 0

                # Send recovery notification if we had errors and now recovered
                if had_errors:
                    try:
                        await self.telegram_notifier.send_recovery_notification({
                            "issue": "Consecutive errors resolved",
                            "recovery_time_seconds": 0,
                        })
                    except Exception as e:
                        logger.warning(f"Could not send recovery notification: {e}")

    def _build_context_features_for_signal(self, signal: Dict) -> Optional["ContextFeatures"]:
        """
        Build lightweight contextual features for contextual learning.

        This is intentionally "best-effort": missing fields fall back to defaults
        so the agent keeps running even if a signal is sparse.
        """
        if not (CONTEXTUAL_BANDIT_AVAILABLE and self.contextual_policy is not None and ContextFeatures is not None):
            return None

        # Parse timestamp (prefer signal timestamp for determinism)
        dt_utc = None
        try:
            raw_ts = signal.get("timestamp")
            if raw_ts:
                dt_utc = parse_utc_timestamp(str(raw_ts))
        except Exception:
            dt_utc = None
        if dt_utc is None:
            dt_utc = datetime.now(timezone.utc)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)

        # Convert to ET for time buckets (Asia/London/NY make more sense in ET)
        et_dt = dt_utc
        minutes_since_session_open = 0
        is_first_hour = False
        is_last_hour = False
        try:
            from zoneinfo import ZoneInfo
            from datetime import time as _time

            et_tz = ZoneInfo("America/New_York")
            et_dt = dt_utc.astimezone(et_tz)

            start_s = str(getattr(self.config, "start_time", "18:00") or "18:00")
            end_s = str(getattr(self.config, "end_time", "16:10") or "16:10")

            sh, sm = [int(x) for x in start_s.split(":")[:2]]
            eh, em = [int(x) for x in end_s.split(":")[:2]]
            start_minutes = sh * 60 + sm
            end_minutes = eh * 60 + em
            now_minutes = et_dt.hour * 60 + et_dt.minute
            overnight = start_minutes > end_minutes

            if overnight:
                session_start_date = et_dt.date() if now_minutes >= start_minutes else (et_dt - timedelta(days=1)).date()
                session_end_date = session_start_date + timedelta(days=1)
            else:
                session_start_date = et_dt.date()
                session_end_date = et_dt.date()

            session_start = datetime.combine(session_start_date, _time(sh, sm), tzinfo=et_tz)
            session_end = datetime.combine(session_end_date, _time(eh, em), tzinfo=et_tz)

            minutes_since_session_open = int((et_dt - session_start).total_seconds() / 60)
            minutes_to_end = int((session_end - et_dt).total_seconds() / 60)
            is_first_hour = 0 <= minutes_since_session_open < 60
            is_last_hour = 0 <= minutes_to_end < 60
        except Exception:
            # Keep safe defaults
            pass

        # Regime + volatility from signal context (if present)
        regime = signal.get("regime", {}) or {}
        regime_name = str(regime.get("regime") or "unknown")
        vol_label = str(regime.get("volatility") or "normal").lower()
        if vol_label in ("low", "quiet"):
            vol_pct = 0.2
        elif vol_label in ("high", "volatile"):
            vol_pct = 0.8
        else:
            vol_pct = 0.5

        return ContextFeatures(
            regime=regime_name,
            volatility_percentile=float(vol_pct),
            hour_of_day=int(et_dt.hour),
            minutes_since_session_open=int(minutes_since_session_open),
            is_first_hour=bool(is_first_hour),
            is_last_hour=bool(is_last_hour),
            recent_win_rate=0.5,
            recent_streak=0,
            volume_percentile=0.5,
            trend_strength=0.5,
        )

    async def _process_signal(self, signal: Dict, buffer_data: Optional[pd.DataFrame] = None) -> None:
        """
        Process a trading signal.
        
        Args:
            signal: Signal dictionary
            buffer_data: Optional DataFrame with OHLCV data for chart generation
        """
        try:
            # Track signal generation (delegates to state_manager for persistence)
            signal_id = self.performance_tracker.track_signal_generated(signal)
            self.last_signal_generated_at = get_utc_timestamp()
            self.last_signal_id_prefix = str(signal_id)[:16]

            # Virtual entry: enter immediately at the signal's entry price.
            # This enables per-signal PnL tracking without requiring IBKR fills.
            entry_tracked = False
            entry_price = 0.0
            try:
                entry_price = float(signal.get("entry_price") or 0.0)
                signal_direction = signal.get("direction", "unknown")
                if entry_price > 0:
                    # SANITY CHECK: Log direction at entry
                    logger.info(
                        f"🔍 VIRTUAL ENTRY: signal_id={signal_id[:16]} | direction={signal_direction.upper()} | "
                        f"entry={entry_price:.2f} | stop={signal.get('stop_loss', 'N/A')} | "
                        f"target={signal.get('take_profit', 'N/A')}"
                    )
                    self.performance_tracker.track_entry(
                        signal_id=signal_id,
                        entry_price=entry_price,
                        entry_time=datetime.now(timezone.utc),
                    )
                    entry_tracked = True
            except Exception as e:
                logger.debug(f"Could not track virtual entry for {signal_id}: {e}")

            # Add to TradeManager for trailing stop / breakeven management AFTER signal_id exists.
            try:
                tm = getattr(self, "trade_manager", None)
                if entry_tracked and tm is not None:
                    tm.add_trade(signal)
            except Exception as e:
                logger.debug(f"Failed to add trade to TradeManager (non-fatal): {e}")

            # ==========================================================================
            # BANDIT POLICY: Evaluate signal type and decide whether to execute
            # ==========================================================================
            policy_decision = None
            policy_status = "not_evaluated"
            
            if self.bandit_policy is not None:
                try:
                    policy_decision = self.bandit_policy.decide(signal)
                    policy_status = f"{policy_decision.mode}:{policy_decision.reason}"
                    
                    logger.info(
                        f"Policy decision: {signal.get('type')} -> "
                        f"execute={policy_decision.execute} | "
                        f"score={policy_decision.sampled_score:.2f} | "
                        f"mode={policy_decision.mode}"
                    )
                except Exception as policy_e:
                    policy_status = f"error:{str(policy_e)[:50]}"
                    logger.error(f"Policy evaluation error: {policy_e}", exc_info=True)
            
            # Store policy status in signal
            signal["_policy_status"] = policy_status
            if policy_decision:
                # Full structured policy payload for transparency (Telegram details, miniapp, exports)
                try:
                    signal["_policy"] = policy_decision.to_dict()
                except Exception:
                    # Never let optional explainability break signal processing
                    signal["_policy"] = None
                signal["_policy_execute"] = policy_decision.execute
                signal["_policy_score"] = policy_decision.sampled_score
                signal["_policy_size_multiplier"] = policy_decision.size_multiplier

            # ==========================================================================
            # CONTEXTUAL POLICY (optional): learn by session/regime/time bucket
            # ==========================================================================
            ctx_decision = None
            if self.contextual_policy is not None:
                try:
                    ctx_features = self._build_context_features_for_signal(signal)
                    if ctx_features is not None:
                        ctx_decision = self.contextual_policy.decide(signal, ctx_features)
                        # Persist context + decision on the signal for later audits and outcome learning
                        try:
                            signal["_context_features"] = ctx_features.to_dict()
                        except Exception:
                            signal["_context_features"] = None
                        try:
                            signal["_policy_ctx"] = ctx_decision.to_dict()
                        except Exception:
                            signal["_policy_ctx"] = None
                except Exception as e:
                    # Never let optional contextual learning break the scan loop
                    signal["_policy_ctx"] = {"error": str(e)[:120]}
            
            # ==========================================================================
            # EXECUTION: Place bracket order if execution adapter is enabled + armed
            # ==========================================================================
            execution_result = None
            execution_status = "not_attempted"
            
            # Gate execution by policy decision (only in live mode)
            should_execute = True
            if (policy_decision is not None 
                and self._bandit_config is not None 
                and self._bandit_config.mode == "live"):
                should_execute = policy_decision.execute
                if not should_execute:
                    execution_status = f"policy_skip:{policy_decision.reason}"
                    logger.info(
                        f"Execution blocked by policy (live mode): {policy_decision.reason}"
                    )

            # ==========================================================================
            # PROP FIRM GUARD: annotate signal + optionally block/cap execution
            # ==========================================================================
            # This runs even when execution is disabled so manual traders still get
            # "would this violate rules?" guidance in the Telegram alert.
            if self.prop_firm_guard is not None:
                try:
                    pf_status = self.prop_firm_guard.compute_status()
                    self._prop_firm_status = pf_status
                    pf_decision = self.prop_firm_guard.evaluate_signal(signal, status=pf_status)

                    # Apply size adjustment (affects both Telegram display and execution)
                    if pf_decision.adjusted_size is not None:
                        try:
                            original_size = int(signal.get("position_size") or 1)
                        except Exception:
                            original_size = 1
                        signal["position_size"] = int(pf_decision.adjusted_size)
                        # Recompute risk amount when possible (keeps message consistent)
                        try:
                            entry = float(signal.get("entry_price") or 0.0)
                            stop = float(signal.get("stop_loss") or 0.0)
                            tick_value = float(signal.get("tick_value") or 0.0)
                            if entry > 0 and stop > 0 and tick_value > 0:
                                risk_per_contract = abs(entry - stop) * tick_value
                                signal["risk_amount"] = risk_per_contract * int(signal["position_size"])
                        except Exception:
                            pass

                        logger.info(
                            f"Prop firm size cap applied: {original_size} -> {signal['position_size']} "
                            f"(reason={pf_decision.reason})"
                        )

                    # Attach compact prop firm context for downstream consumers (Telegram, state)
                    signal["_prop_firm"] = {
                        "enabled": True,
                        "profile": pf_status.profile,
                        "allow": pf_decision.allow,
                        "reason": pf_decision.reason,
                        "adjusted_size": pf_decision.adjusted_size,
                        "equity_est": pf_status.equity_est,
                        "min_balance": pf_status.min_balance,
                        "remaining_drawdown": pf_status.remaining_drawdown,
                        "available_drawdown": pf_status.available_drawdown,
                        "daily_pnl": pf_status.daily_pnl,
                        "daily_profit_cap": pf_status.daily_profit_cap,
                        "days_traded": pf_status.days_traded,
                        "min_trading_days": pf_status.min_trading_days,
                    }

                    # If we were going to execute, allow the prop firm guard to block it.
                    if should_execute and not pf_decision.allow:
                        should_execute = False
                        execution_status = f"prop_firm_block:{pf_decision.reason}"
                        logger.info(f"Execution blocked by prop firm guard: {pf_decision.reason}")
                except Exception as pf_e:
                    signal["_prop_firm"] = {
                        "enabled": True,
                        "error": str(pf_e)[:120],
                    }
            
            if should_execute and self.execution_adapter is not None:
                try:
                    # Check preconditions (enabled, armed, limits, cooldowns)
                    decision = self.execution_adapter.check_preconditions(signal)
                    
                    if decision.execute:
                        # Apply size multiplier from policy (if in live mode)
                        if (policy_decision is not None 
                            and self._bandit_config is not None 
                            and self._bandit_config.mode == "live"):
                            original_size = signal.get("position_size", 1)
                            adjusted_size = int(original_size * policy_decision.size_multiplier)
                            adjusted_size = max(1, adjusted_size)  # At least 1 contract
                            signal["position_size"] = adjusted_size
                            logger.info(
                                f"Position size adjusted by policy: {original_size} -> {adjusted_size} "
                                f"(multiplier={policy_decision.size_multiplier})"
                            )
                        
                        # Place bracket order
                        execution_result = await self.execution_adapter.place_bracket(signal)
                        
                        if execution_result.success:
                            execution_status = "placed"
                            logger.info(
                                f"✅ Order placed: {signal.get('type')} {signal.get('direction')} | "
                                f"order_id={execution_result.parent_order_id}"
                            )
                        else:
                            execution_status = f"place_failed:{execution_result.error_message}"
                            logger.warning(
                                f"⚠️ Order placement failed: {execution_result.error_message}"
                            )
                    else:
                        # Preconditions not met - log why
                        execution_status = f"skipped:{decision.reason}"
                        logger.info(
                            f"Order skipped: {decision.reason} | signal_id={signal_id[:16]}"
                        )
                        
                except Exception as exec_e:
                    execution_status = f"error:{str(exec_e)[:50]}"
                    logger.error(f"Execution error: {exec_e}", exc_info=True)
            
            # Store execution status in signal for state persistence
            signal["_execution_status"] = execution_status
            if execution_result:
                signal["_execution_order_id"] = execution_result.parent_order_id

            # ==========================================================================
            # LLM ANNOTATION: AI-powered signal analysis (non-blocking, best-effort)
            # ==========================================================================
            # Adds human-readable explanation to the signal before Telegram delivery.
            # Failures are graceful - annotation is optional enhancement only.
            if self.signal_annotator is not None and self.signal_annotator.is_available:
                try:
                    # Get performance metrics for context
                    perf_metrics = None
                    try:
                        perf = self.performance_tracker.get_performance_metrics()
                        if perf:
                            perf_metrics = {
                                "win_rate": perf.get("win_rate", 0.5),
                                "total_trades": perf.get("total_trades", 0),
                            }
                    except Exception:
                        pass
                    
                    # Annotate signal asynchronously with timeout
                    annotation = await self.signal_annotator.annotate_signal_async(
                        signal=signal,
                        market_context=None,  # Could add more context here
                        performance_metrics=perf_metrics,
                    )
                    
                    if annotation and not annotation.error:
                        signal["_llm_annotation"] = annotation.to_dict()
                        logger.debug(
                            f"LLM annotation added: {annotation.confidence_note} "
                            f"(latency={annotation.latency_ms}ms)"
                        )
                    elif annotation and annotation.error:
                        logger.debug(f"LLM annotation skipped: {annotation.error}")
                except Exception as ann_e:
                    # Never let annotation failures affect signal processing
                    logger.debug(f"LLM annotation failed (non-blocking): {ann_e}")

            # ==========================================================================
            # LLM RISK ASSESSMENT: fast pre-trade risk check (non-blocking, best-effort)
            # ==========================================================================
            # Adds a compact risk label to the signal before Telegram delivery.
            # Failures are graceful; timeout defaults to "proceed".
            if self.risk_assessor is not None and self.risk_assessor.is_available:
                try:
                    consider_n = int(getattr(self.risk_assessor, "consider_recent_trades", 20) or 20)

                    # Build a small recent-trades cache for the assessor (best-effort).
                    recent_records: List[Dict] = []
                    try:
                        recent_records = self.state_manager.get_recent_signals(limit=max(200, consider_n * 10))
                    except Exception:
                        recent_records = []

                    exited: List[Dict[str, Any]] = []
                    for rec in recent_records:
                        if not isinstance(rec, dict):
                            continue
                        if rec.get("_is_test", False):
                            continue
                        if rec.get("status") != "exited":
                            continue
                        sig = rec.get("signal", {}) or {}
                        exited.append(
                            {
                                "type": sig.get("type", rec.get("type", "unknown")),
                                "is_win": bool(rec.get("is_win", False)),
                                "confidence": sig.get("confidence"),
                                "pnl_points": rec.get("pnl"),
                                "exit_reason": rec.get("exit_reason"),
                                "exit_time": rec.get("exit_time"),
                            }
                        )

                    if exited:
                        self.risk_assessor.update_recent_trades(exited[-consider_n:])

                    # Current exposure summary (best-effort)
                    exposure = "none"
                    try:
                        open_positions = []
                        for rec in self.state_manager.get_recent_signals(limit=200):
                            if isinstance(rec, dict) and rec.get("status") == "entered":
                                open_positions.append(rec)
                        if open_positions:
                            exposure = f"{len(open_positions)} active"
                    except Exception:
                        pass

                    assessment = await self.risk_assessor.assess_signal_async(
                        signal=signal,
                        market_state={"regime": signal.get("regime", {})},
                        current_exposure=exposure,
                    )

                    # Attach only when meaningful to avoid bloating persisted signals.
                    if assessment and not assessment.error:
                        if (
                            assessment.risk_level in ("medium", "high", "critical")
                            or (assessment.primary_concern is not None)
                            or (abs(float(assessment.size_adjustment or 1.0) - 1.0) >= 0.05)
                        ):
                            signal["_llm_risk_assessment"] = assessment.to_dict()
                            logger.debug(
                                f"LLM risk assessment: {assessment.risk_level} "
                                f"(proceed={assessment.proceed}, latency={assessment.latency_ms}ms)"
                            )
                except Exception as risk_e:
                    logger.debug(f"LLM risk assessment failed (non-blocking): {risk_e}")

            # Send to Telegram (await async call) with buffer data for chart generation
            signal_type = signal.get('type', 'unknown')
            signal_direction = signal.get('direction', 'unknown')
            logger.info(f"Processing signal: {signal_type} {signal_direction}")
            
            success = await self.telegram_notifier.send_signal(signal, buffer_data=buffer_data)

            if success:
                logger.info(f"✅ Signal sent to Telegram: {signal_type} {signal_direction}")
                self.signals_sent += 1
                self.last_signal_sent_at = get_utc_timestamp()
                # Clear last error on success to avoid stale operator confusion.
                self.last_signal_send_error = None
            else:
                logger.error(
                    f"❌ Failed to send signal to Telegram: {signal_type} {signal_direction}. "
                    f"Telegram enabled: {self.telegram_notifier.enabled}, "
                    f"Telegram instance: {self.telegram_notifier.telegram is not None}"
                )
                self.signals_send_failures += 1
                try:
                    err = None
                    if self.telegram_notifier.telegram is not None:
                        err = getattr(self.telegram_notifier.telegram, "last_error", None)
                    if err:
                        self.last_signal_send_error = str(err)[:200]
                except Exception:
                    # Keep prior error if we can't read the latest reason.
                    pass

            self.signal_count += 1

            # Optional: send a dedicated ENTRY notification for virtual trades (with chart).
            # This is config-gated to preserve the default "no entry spam" behavior.
            try:
                if (
                    entry_tracked
                    and bool(getattr(self.config, "virtual_pnl_enabled", True))
                    and bool(getattr(self.config, "virtual_pnl_notify_entry", False))
                ):
                    # Fire-and-forget to avoid delaying the scan loop on chart generation.
                    asyncio.create_task(
                        self.telegram_notifier.send_entry_notification(
                            signal_id=str(signal_id),
                            entry_price=float(entry_price),
                            signal=signal,
                            buffer_data=buffer_data,
                        )
                    )
            except Exception as e:
                logger.debug(f"Could not schedule entry notification for {str(signal_id)[:16]}: {e}")

        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
            self.error_count += 1

    def _update_virtual_trade_exits(self, market_data: Dict) -> None:
        """
        Update virtual trade exits for any `entered` signals when TP/SL is touched.

        Rules:
        - Gated by `config.virtual_pnl_enabled` (default True).
        - Entry is immediate at signal generation time.
        - Exit occurs on first *touch* of TP/SL using **bars from market_data['df']**
          that are strictly after the entry time (avoids Level1 daily high/low artifacts).
        - If TP and SL are both touched in the same bar, tiebreak is determined by
          config.virtual_pnl_tiebreak ("stop_loss" = conservative, "take_profit" = optimistic).

        Performance: Uses vectorized pandas operations instead of iterrows() for O(signals)
        instead of O(signals × bars) complexity.
        """
        # Gate by config.virtual_pnl_enabled
        if not getattr(self.config, "virtual_pnl_enabled", True):
            return

        # Get bars DataFrame - use actual OHLCV bars, NOT Level1 latest_bar
        # Level1 latest_bar may contain daily high/low which includes pre-entry extremes.
        df = market_data.get("df") if isinstance(market_data, dict) else None
        if df is None or df.empty:
            return

        # Ensure we have required columns
        required_cols = {"timestamp", "high", "low"}
        if not required_cols.issubset(set(df.columns)):
            return

        # Get tiebreak preference from config (default to conservative "stop_loss")
        tiebreak = getattr(self.config, "virtual_pnl_tiebreak", "stop_loss")

        # Consider only recently tracked signals for performance; active trades should be among them.
        try:
            recent = self.state_manager.get_recent_signals(limit=300)
        except Exception:
            return

        # Precompute bar arrays once (vectorized) for all signals
        try:
            # Convert timestamps to tz-aware datetimes for comparison
            bar_times = pd.to_datetime(df["timestamp"])
            # Ensure timezone-aware (UTC) for comparison
            if bar_times.dt.tz is None:
                bar_times = bar_times.dt.tz_localize("UTC")
            else:
                bar_times = bar_times.dt.tz_convert("UTC")
            bar_times_arr = bar_times.values  # numpy array of datetime64[ns, UTC]
            
            bar_highs = df["high"].fillna(df.get("close", 0)).astype(float).values
            bar_lows = df["low"].fillna(df.get("close", 0)).astype(float).values
        except Exception:
            return

        exited_this_cycle: set[str] = set()
        for rec in recent:
            try:
                if not isinstance(rec, dict) or rec.get("status") != "entered":
                    continue
                sig_id = str(rec.get("signal_id") or "")
                if not sig_id or sig_id in exited_this_cycle:
                    continue

                # Parse entry time (UTC)
                entry_time_str = rec.get("entry_time")
                entry_time: Optional[datetime] = None
                if entry_time_str:
                    try:
                        entry_time = parse_utc_timestamp(str(entry_time_str))
                        if entry_time and entry_time.tzinfo is None:
                            entry_time = entry_time.replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

                sig = rec.get("signal", {}) or {}
                direction = str(sig.get("direction") or "long").lower()
                try:
                    stop = float(sig.get("stop_loss") or 0.0)
                    target = float(sig.get("take_profit") or 0.0)
                except Exception:
                    continue
                if stop <= 0 or target <= 0:
                    continue

                # Vectorized: compute hit masks for all bars at once
                if direction == "short":
                    tp_mask = bar_lows <= target
                    sl_mask = bar_highs >= stop
                else:  # long
                    tp_mask = bar_highs >= target
                    sl_mask = bar_lows <= stop

                # Mask for bars strictly after entry time
                if entry_time:
                    import numpy as _np  # local import to avoid polluting namespace
                    # numpy datetime64 has no timezone concept; normalize to UTC then strip tz
                    # to avoid noisy warnings and ensure a stable comparison baseline.
                    entry_ts = pd.Timestamp(entry_time)
                    if entry_ts.tzinfo is None:
                        entry_ts = entry_ts.tz_localize("UTC")
                    else:
                        entry_ts = entry_ts.tz_convert("UTC")
                    entry_ts_np = entry_ts.tz_localize(None).to_datetime64()
                    after_entry_mask = bar_times_arr > entry_ts_np
                else:
                    import numpy as _np
                    after_entry_mask = _np.ones(len(df), dtype=bool)

                # Mask for valid bars (positive high/low)
                valid_mask = (bar_highs > 0) & (bar_lows > 0)

                # Combined exit mask: (TP or SL hit) AND after entry AND valid
                exit_mask = (tp_mask | sl_mask) & after_entry_mask & valid_mask

                if not exit_mask.any():
                    continue

                # Find first bar index where exit condition is met
                first_exit_idx = exit_mask.argmax()  # argmax returns first True index

                # Get values at exit bar
                exit_bar_ts_raw = bar_times_arr[first_exit_idx]
                hit_tp = tp_mask[first_exit_idx]
                hit_sl = sl_mask[first_exit_idx]

                # Determine exit reason and price based on tiebreak
                exit_reason: Optional[str] = None
                exit_price: Optional[float] = None

                if hit_tp and hit_sl:
                    # Both touched in same bar - use configured tiebreak
                    if tiebreak == "take_profit":
                        exit_reason = "take_profit"
                        exit_price = target
                    else:  # Default to conservative "stop_loss"
                        exit_reason = "stop_loss"
                        exit_price = stop
                elif hit_sl:
                    exit_reason = "stop_loss"
                    exit_price = stop
                elif hit_tp:
                    exit_reason = "take_profit"
                    exit_price = target

                if exit_reason and exit_price is not None:
                    # Convert numpy datetime64 to python datetime
                    exit_bar_ts: Optional[datetime] = None
                    try:
                        exit_bar_ts = pd.Timestamp(exit_bar_ts_raw).to_pydatetime()
                        if exit_bar_ts and exit_bar_ts.tzinfo is None:
                            exit_bar_ts = exit_bar_ts.replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

                    # SANITY CHECK: Log direction consistency
                    logger.info(
                        f"🔍 VIRTUAL EXIT: signal_id={sig_id} | direction={direction.upper()} | "
                        f"entry={sig.get('entry_price', 'N/A')} | exit={exit_price:.2f} | "
                        f"reason={exit_reason} | stop={stop:.2f} | target={target:.2f}"
                    )

                    perf = self.performance_tracker.track_exit(
                        signal_id=sig_id,
                        exit_price=float(exit_price),
                        exit_reason=str(exit_reason),
                        exit_time=exit_bar_ts,
                    )
                    exited_this_cycle.add(sig_id)

                    # Keep TradeManager in sync with virtual exits (avoid managing already-exited trades)
                    try:
                        tm = getattr(self, "trade_manager", None)
                        if tm is not None:
                            tm.remove_trade(sig_id)
                    except Exception:
                        pass

                    if perf:
                        pnl_value = float(perf.get('pnl', 0.0))
                        is_win = bool(perf.get("is_win", pnl_value > 0))
                        logger.info(
                            "Virtual exit: %s | %s | exit=%s | pnl=%s",
                            sig_id[:16],
                            exit_reason,
                            f"{float(exit_price):.2f}",
                            f"{pnl_value:.2f}",
                        )
                        
                        # Record trade with 50k challenge tracker (pass/fail rules)
                        if self._challenge_tracker is not None:
                            try:
                                challenge_result = self._challenge_tracker.record_trade(
                                    pnl=pnl_value,
                                    is_win=is_win,
                                )
                                if challenge_result.get("triggered"):
                                    outcome = challenge_result.get("outcome", "")
                                    attempt = challenge_result.get("attempt", {})
                                    attempt_pnl = attempt.get("pnl", 0.0)
                                    attempt_id = attempt.get("attempt_id", 0)
                                    logger.info(
                                        f"🏆 Challenge attempt #{attempt_id} ended: {outcome.upper()} | "
                                        f"Final PnL: ${attempt_pnl:.2f}"
                                    )
                                    # Send Telegram alert for pass/fail
                                    if self.telegram_notifier.enabled:
                                        try:
                                            emoji = "🎉" if outcome == "pass" else "❌"
                                            msg = (
                                                f"{emoji} *50k Challenge: {outcome.upper()}*\n\n"
                                                f"Attempt #{attempt_id} ended\n"
                                                f"Final PnL: `${attempt_pnl:,.2f}`\n"
                                                f"Trades: {attempt.get('trades', 0)} | "
                                                f"WR: {attempt.get('win_rate', 0):.0f}%\n\n"
                                                f"_New attempt starting..._"
                                            )
                                            asyncio.create_task(
                                                self.telegram_notifier.telegram.send_message(
                                                    msg, parse_mode="Markdown", dedupe=False
                                                )
                                            )
                                        except Exception as tg_err:
                                            logger.debug(f"Could not send challenge alert: {tg_err}")
                            except Exception as challenge_err:
                                logger.debug(f"Could not record challenge trade: {challenge_err}")
                        
                        # Record outcome with bandit policy for learning
                        if self.bandit_policy is not None:
                            try:
                                signal_type = str(sig.get("type") or "unknown")
                                # Use perf["is_win"] which is computed from actual PnL
                                # (more accurate than exit_reason == "take_profit")
                                is_win = bool(perf.get("is_win", pnl_value > 0))
                                self.bandit_policy.record_outcome(
                                    signal_id=sig_id,
                                    signal_type=signal_type,
                                    is_win=is_win,
                                    pnl=pnl_value,
                                )
                            except Exception as policy_err:
                                logger.debug(f"Could not record policy outcome: {policy_err}")

                        # Record outcome with contextual policy (if available)
                        if self.contextual_policy is not None and ContextFeatures is not None:
                            try:
                                signal_type = str(sig.get("type") or "unknown")
                                is_win = bool(perf.get("is_win", pnl_value > 0))
                                raw_ctx = sig.get("_context_features")
                                if isinstance(raw_ctx, dict):
                                    ctx = ContextFeatures.from_dict(raw_ctx)
                                    self.contextual_policy.record_outcome(
                                        signal_id=sig_id,
                                        signal_type=signal_type,
                                        context=ctx,
                                        is_win=is_win,
                                        pnl=pnl_value,
                                    )
                                    
                                    # Log learning metrics (what the brain learned)
                                    try:
                                        context_key = ctx.to_dict().get("context_key", "unknown")
                                        # Get expected win rate for this signal type in this context
                                        expected_wr = self.contextual_policy.get_expected_win_rate(
                                            signal_type, ctx
                                        )
                                        logger.info(
                                            f"🧠 Learning: {signal_type} in {context_key} -> "
                                            f"{'WIN' if is_win else 'LOSS'} (${pnl_value:+.0f}) | "
                                            f"Expected WR: {expected_wr:.0%}"
                                        )
                                    except Exception:
                                        # Log basic learning info if detailed metrics unavailable
                                        logger.info(
                                            f"🧠 Learning: {signal_type} -> "
                                            f"{'WIN' if is_win else 'LOSS'} (${pnl_value:+.0f})"
                                        )
                            except Exception as ctx_err:
                                logger.debug(f"Could not record contextual policy outcome: {ctx_err}")
                        
                        # Update execution adapter's daily PnL for kill switch threshold
                        # This ensures max_daily_loss limit triggers correctly
                        if self.execution_adapter is not None:
                            try:
                                self.execution_adapter.update_daily_pnl(pnl_value)
                                logger.debug(f"Updated execution daily PnL: {pnl_value:.2f}")
                            except Exception as pnl_err:
                                logger.debug(f"Could not update execution daily PnL: {pnl_err}")

                        # Optional: send Telegram EXIT notification (with chart) for virtual trades.
                        # This is config-gated to preserve default "no Telegram spam" behavior.
                        try:
                            if (
                                bool(getattr(self.config, "virtual_pnl_enabled", True))
                                and bool(getattr(self.config, "virtual_pnl_notify_exit", False))
                            ):
                                hold_mins = perf.get("hold_duration_minutes")
                                try:
                                    hold_mins = float(hold_mins) if hold_mins is not None else None
                                except Exception:
                                    hold_mins = None

                                # Fire-and-forget: chart generation + Telegram send can take time.
                                asyncio.create_task(
                                    self.telegram_notifier.send_exit_notification(
                                        signal_id=str(sig_id),
                                        exit_price=float(exit_price),
                                        exit_reason=str(exit_reason),
                                        pnl=float(pnl_value),
                                        signal=sig,
                                        hold_duration_minutes=hold_mins,
                                        buffer_data=df,
                                    )
                                )
                        except Exception as e:
                            logger.debug(f"Could not schedule exit notification for {sig_id[:16]}: {e}")
            except Exception:
                continue

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
        except Exception:
            # If we can't load prefs, default to enabled
            pass

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

        # When chart is due, send BOTH together (chart first, then text) as a combined notification
        if chart_due:
            await self._send_dashboard_chart()
            self.last_dashboard_chart_sent = now
            # Always send text immediately after chart so they appear together
            await self._send_dashboard(market_data, quiet_reason=quiet_reason, signal_diagnostics=signal_diagnostics)
            self.last_status_update = now
        elif text_due:
            # Text-only update (between chart intervals)
            await self._send_dashboard(market_data, quiet_reason=quiet_reason, signal_diagnostics=signal_diagnostics)
            self.last_status_update = now

    async def _send_dashboard_chart(self) -> None:
        """
        Generate and send a 24h/5m mplfinance dashboard chart.
        
        Fetches 24h of 5m historical data and generates a TradingView-style chart.
        """
        try:
            # Check if chart generator is available
            if not self.telegram_notifier.chart_generator:
                logger.debug("Chart generator not available for dashboard chart")
                return

            # Fetch lookback window for chart (prefer direct historical fetch; fallback to buffers)
            # Ensure we always show at least a useful minimum window (operator request: >= 6h),
            # and cap the window for Telegram readability (operator request: <= 24h).
            min_lookback_hours = 6.0
            max_lookback_hours = 24.0
            lookback_hours = float(self.dashboard_chart_lookback_hours or max_lookback_hours)
            if lookback_hours < min_lookback_hours:
                lookback_hours = min_lookback_hours
            if lookback_hours > max_lookback_hours:
                lookback_hours = max_lookback_hours
            chart_tf = (self.dashboard_chart_timeframe or "auto").strip().lower()

            def _choose_timeframe(hours: float, max_bars: int) -> str:
                # Keep candle count under max_bars for readability.
                candidates = ["5m", "15m", "30m", "1h"]
                if chart_tf in candidates:
                    return chart_tf
                # auto
                for tf in candidates:
                    mins = timeframe_to_minutes(tf) or 0
                    if mins <= 0:
                        continue
                    bars = int((hours * 60.0) / float(mins))
                    if bars <= max_bars:
                        return tf
                return "1h"

            chosen_tf = _choose_timeframe(lookback_hours, int(self.dashboard_chart_max_bars or 420))
            max_bars = int(self.dashboard_chart_max_bars or 420)
            tf_mins = float(timeframe_to_minutes(chosen_tf) or 5)
            bars_target = int((lookback_hours * 60.0) / tf_mins)
            # Guarantee at least 6h of history regardless of timeframe selection.
            min_bars_for_min_hours = int(math.ceil((min_lookback_hours * 60.0) / tf_mins))
            bars_target = max(50, min_bars_for_min_hours, min(max_bars, bars_target))

            logger.debug(
                f"Fetching dashboard chart data: lookback_hours={lookback_hours}, timeframe={chosen_tf}, bars={bars_target}"
            )

            chart_data = None
            try:
                end = datetime.now(timezone.utc)
                start = end - timedelta(hours=lookback_hours)
                loop = asyncio.get_event_loop()
                df_hist = await loop.run_in_executor(
                    None,
                    lambda: self.data_fetcher.data_provider.fetch_historical(
                        self.config.symbol,
                        start=start,
                        end=end,
                        timeframe=chosen_tf,
                    ),
                )
                if isinstance(df_hist, pd.DataFrame) and not df_hist.empty:
                    chart_data = df_hist.tail(min(int(bars_target), len(df_hist))).copy()
            except Exception as e:
                logger.debug(f"Direct historical fetch for dashboard chart failed: {e}")

            # If the full lookback request failed, retry with the minimum window (less load, more likely to succeed).
            if chart_data is None or chart_data.empty:
                try:
                    end = datetime.now(timezone.utc)
                    start = end - timedelta(hours=min_lookback_hours)
                    loop = asyncio.get_event_loop()
                    df_hist = await loop.run_in_executor(
                        None,
                        lambda: self.data_fetcher.data_provider.fetch_historical(
                            self.config.symbol,
                            start=start,
                            end=end,
                            timeframe=chosen_tf,
                        ),
                    )
                    if isinstance(df_hist, pd.DataFrame) and not df_hist.empty:
                        chart_data = df_hist.tail(min(int(bars_target), len(df_hist))).copy()
                except Exception as e:
                    logger.debug(f"Min-window historical fetch for dashboard chart failed: {e}")
            
            def _resample_ohlcv(df_in: pd.DataFrame, target_tf: str) -> pd.DataFrame:
                """Best-effort resample of OHLCV data to target timeframe."""
                try:
                    mins = timeframe_to_minutes(target_tf)
                    if not mins or mins <= 0:
                        return df_in
                    rule = f"{int(mins)}T"
                    df = df_in.copy()
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                        df = df.dropna(subset=["timestamp"]).set_index("timestamp")
                    elif isinstance(df.index, pd.DatetimeIndex):
                        pass
                    else:
                        return df_in

                    need_cols = {"open", "high", "low", "close"}
                    if not need_cols.issubset(set(df.columns)):
                        return df_in

                    ohlc = df[["open", "high", "low", "close"]].resample(rule).agg(
                        {"open": "first", "high": "max", "low": "min", "close": "last"}
                    )
                    if "volume" in df.columns:
                        vol = df["volume"].resample(rule).sum()
                        ohlc["volume"] = vol
                    ohlc = ohlc.dropna(subset=["open", "high", "low", "close"]).reset_index()
                    return ohlc
                except Exception:
                    return df_in

            def _clip_to_lookback_hours(
                df_in: Optional[pd.DataFrame], hours: float
            ) -> Optional[pd.DataFrame]:
                """Best-effort clip to a wall-clock window ending at the most recent bar."""
                try:
                    if df_in is None:
                        return None
                    if df_in.empty:
                        return df_in

                    if hours <= 0:
                        return df_in

                    if "timestamp" in df_in.columns:
                        ts = pd.to_datetime(df_in["timestamp"], errors="coerce")
                        if ts.isna().all():
                            return df_in
                        tmax = ts.max()
                        cutoff = tmax - timedelta(hours=float(hours))
                        return df_in.loc[ts >= cutoff].copy()

                    if isinstance(df_in.index, pd.DatetimeIndex) and len(df_in.index) > 0:
                        tmax = df_in.index.max()
                        cutoff = tmax - timedelta(hours=float(hours))
                        return df_in.loc[df_in.index >= cutoff].copy()

                    return df_in
                except Exception:
                    return df_in

            # Buffer fallback (timeframe-aware). This should be rare; used only if historical fetch fails.
            if chart_data is None or chart_data.empty:
                buf = None
                try:
                    if chosen_tf == "15m":
                        buf = getattr(self.data_fetcher, "_data_buffer_15m", None)
                    elif chosen_tf == "5m":
                        buf = getattr(self.data_fetcher, "_data_buffer_5m", None)
                    # If we don't have a matching buffer, resample from whatever we do have.
                    if buf is None or not isinstance(buf, pd.DataFrame) or buf.empty:
                        base = (
                            getattr(self.data_fetcher, "_data_buffer", None)
                            or getattr(self.data_fetcher, "_data_buffer_5m", None)
                            or getattr(self.data_fetcher, "_data_buffer_15m", None)
                        )
                        if isinstance(base, pd.DataFrame) and not base.empty:
                            buf = _resample_ohlcv(base, chosen_tf)
                except Exception:
                    buf = None

                if isinstance(buf, pd.DataFrame) and not buf.empty:
                    chart_data = buf.tail(min(int(bars_target), len(buf))).copy()
                    logger.debug(f"Using buffer fallback for dashboard chart: {len(chart_data)} bars (tf={chosen_tf})")
            
            # Enforce wall-clock cap (prevents market gaps from inflating the displayed range).
            chart_data = _clip_to_lookback_hours(chart_data, lookback_hours)

            if chart_data is None or chart_data.empty or len(chart_data) < 20:
                logger.debug("Not enough data for dashboard chart (need at least 20 bars)")
                return
            
            # Generate the chart
            # Prefer an accurate label based on the actual data window (avoids "48h" when fallback data is shorter).
            range_label = None
            try:
                tmin = None
                tmax = None
                if isinstance(chart_data, pd.DataFrame):
                    if "timestamp" in chart_data.columns:
                        ts = pd.to_datetime(chart_data["timestamp"], errors="coerce")
                        if not ts.isna().all():
                            tmin = ts.min()
                            tmax = ts.max()
                    elif isinstance(chart_data.index, pd.DatetimeIndex) and len(chart_data.index) > 0:
                        tmin = chart_data.index.min()
                        tmax = chart_data.index.max()
                if tmin is not None and tmax is not None and pd.notna(tmin) and pd.notna(tmax):
                    hrs = float((tmax - tmin).total_seconds()) / 3600.0
                    hrs = min(float(hrs), float(lookback_hours))
                    if hrs >= 72:
                        range_label = f"{max(1, int(round(hrs / 24.0)))}d"
                    else:
                        range_label = f"{max(1, int(round(hrs)))}h"
            except Exception:
                range_label = None
            if not range_label:
                range_label = f"{int(lookback_hours)}h" if lookback_hours < 72 else f"{int(round(lookback_hours/24))}d"

            chart_path = self.telegram_notifier.chart_generator.generate_dashboard_chart(
                data=chart_data,
                symbol=self.config.symbol,
                timeframe=chosen_tf,
                lookback_bars=min(int(bars_target), len(chart_data)),
                range_label=range_label,
                figsize=(16, 7),
                dpi=150,
                show_ma=True,  # Show moving averages to match TradingView-style chart
                ma_periods=[20, 50, 200],  # Common MA periods
                show_pressure=self.dashboard_chart_show_pressure,
                # Overlay recent trades (entries/exits) for transparency.
                trades=self._get_trades_for_chart(chart_data),
            )
            
            if chart_path and chart_path.exists():
                # Send the chart with current lookback for toggle button highlighting
                success = await self.telegram_notifier.send_dashboard_chart(
                    chart_path=chart_path,
                    symbol=self.config.symbol,
                    timeframe=chosen_tf,
                    range_label=range_label,
                    current_hours=lookback_hours,
                )
                
                # Clean up temp file
                try:
                    chart_path.unlink()
                except Exception:
                    pass
                
                if success:
                    logger.info("Dashboard chart sent to Telegram")
                else:
                    logger.warning("Failed to send dashboard chart")
            else:
                logger.debug("Dashboard chart generation returned no path")
                
        except Exception as e:
            logger.error(f"Error generating/sending dashboard chart: {e}", exc_info=True)

    async def _send_dashboard(
        self,
        market_data: Optional[Dict] = None,
        quiet_reason: Optional[str] = None,
        signal_diagnostics=None,
    ) -> None:
        """
        Send consolidated dashboard to Telegram.
        
        Args:
            market_data: Current market data (may be empty)
            quiet_reason: Why the agent is quiet (for observability)
            signal_diagnostics: SignalDiagnostics from the signal generator
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
            except Exception:
                pass

            # Track price source for UI confidence cues (e.g., Level 1 vs historical fallback).
            try:
                if market_data and isinstance(market_data.get("latest_bar"), dict):
                    status["latest_price_source"] = market_data["latest_bar"].get("_data_level")
            except Exception:
                pass

            # Active trades + unrealized PnL (virtual lifecycle: status="entered").
            try:
                active = []
                try:
                    recent_signals = self.state_manager.get_recent_signals(limit=300)
                except Exception:
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
                    except Exception:
                        current_price = None
                    if current_price and current_price > 0:
                        total_upnl = 0.0
                        for rec in active:
                            sig = rec.get("signal", {}) or {}
                            direction = str(sig.get("direction") or "long").lower()
                            try:
                                entry_price = float(sig.get("entry_price") or 0.0)
                            except Exception:
                                entry_price = 0.0
                            if entry_price <= 0:
                                continue
                            try:
                                tick_value = float(sig.get("tick_value") or 2.0)
                            except Exception:
                                tick_value = 2.0
                            try:
                                position_size = float(sig.get("position_size") or 1.0)
                            except Exception:
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
                except Exception:
                    pass
            except Exception:
                # Never let optional PnL UI break dashboard delivery.
                pass
            
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
            except Exception:
                # Never let optional observability break the dashboard.
                pass
            
            await self.telegram_notifier.send_dashboard(status)
        except Exception as e:
            logger.error(f"Error sending dashboard: {e}", exc_info=True)
    
    def _get_recent_closes(self, market_data: Optional[Dict] = None) -> list:
        """Extract recent close prices for sparkline."""
        try:
            if market_data and "df" in market_data and not market_data["df"].empty:
                df = market_data["df"]
                if "close" in df.columns:
                    # Get last 50 closes (about 4 hours of 5m data)
                    closes = df["close"].tail(50).tolist()
                    return [float(c) for c in closes if c is not None]
            
            # Fallback to buffer
            if self.data_fetcher._data_buffer is not None and not self.data_fetcher._data_buffer.empty:
                df = self.data_fetcher._data_buffer
                if "close" in df.columns:
                    closes = df["close"].tail(50).tolist()
                    return [float(c) for c in closes if c is not None]
        except Exception as e:
            logger.debug(f"Could not get recent closes for sparkline: {e}")
        
        return []

    def _get_trades_for_chart(self, chart_data: Optional[pd.DataFrame]) -> list[dict]:
        """
        Build a compact list of recent trades (entries/exits) that fall within the chart window.

        Used to overlay trade markers on the periodic dashboard chart for transparency.
        """
        try:
            if chart_data is None or not isinstance(chart_data, pd.DataFrame) or chart_data.empty:
                return []

            # Determine chart time window (normalize to naive UTC for stable comparisons)
            tmin = None
            tmax = None
            if "timestamp" in chart_data.columns:
                ts = pd.to_datetime(chart_data["timestamp"], errors="coerce")
                ts = ts.dropna()
                if ts.empty:
                    return []
                tmin = pd.Timestamp(ts.min())
                tmax = pd.Timestamp(ts.max())
            elif isinstance(chart_data.index, pd.DatetimeIndex) and len(chart_data.index) > 0:
                tmin = pd.Timestamp(chart_data.index.min())
                tmax = pd.Timestamp(chart_data.index.max())
            if tmin is None or tmax is None:
                return []

            def _to_utc_naive(x):
                if not x:
                    return None
                try:
                    tsx = pd.Timestamp(x)
                except Exception:
                    return None
                try:
                    if tsx.tzinfo is not None:
                        tsx = tsx.tz_convert("UTC").tz_localize(None)
                except Exception:
                    # If tz_convert fails, fall back to stripping tz
                    try:
                        tsx = tsx.tz_localize(None)
                    except Exception:
                        pass
                return tsx

            tmin_u = _to_utc_naive(tmin)
            tmax_u = _to_utc_naive(tmax)
            if tmin_u is None or tmax_u is None:
                return []

            # Pull recent signals (append-only), filter to entered/exited within the window.
            try:
                recent = self.state_manager.get_recent_signals(limit=500)
            except Exception:
                recent = []

            symbol_norm = str(getattr(self.config, "symbol", "MNQ") or "MNQ").upper()
            trades: list[dict] = []
            for rec in recent:
                if not isinstance(rec, dict):
                    continue
                status = str(rec.get("status") or "").lower()
                if status not in ("entered", "exited"):
                    continue
                sig = rec.get("signal", {}) or {}
                sym = str(sig.get("symbol") or symbol_norm).upper()
                if sym != symbol_norm:
                    continue

                entry_time_raw = rec.get("entry_time") or sig.get("timestamp") or rec.get("timestamp")
                entry_time = _to_utc_naive(entry_time_raw)
                if entry_time is None:
                    continue

                exit_time_raw = rec.get("exit_time") if status == "exited" else None
                exit_time = _to_utc_naive(exit_time_raw) if exit_time_raw else None

                # Include if entry or exit is inside window, or trade spans across it.
                in_window = (tmin_u <= entry_time <= tmax_u)
                if exit_time is not None:
                    in_window = in_window or (tmin_u <= exit_time <= tmax_u) or (entry_time <= tmax_u and exit_time >= tmin_u)
                if not in_window:
                    continue

                # Prices
                entry_price = rec.get("entry_price") or sig.get("entry_price")
                exit_price = rec.get("exit_price") if status == "exited" else None
                pnl = rec.get("pnl") if status == "exited" else None

                trades.append(
                    {
                        "signal_id": str(rec.get("signal_id") or ""),
                        "direction": str(sig.get("direction") or "long"),
                        "entry_time": entry_time_raw,
                        "entry_price": entry_price,
                        "exit_time": exit_time_raw,
                        "exit_price": exit_price,
                        "exit_reason": rec.get("exit_reason"),
                        "pnl": pnl,
                        "status": status,
                    }
                )

            # Keep only the most recent N to avoid chart clutter.
            trades = trades[-20:]
            return trades
        except Exception:
            return []
    
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
                    if len(closes) >= 2:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["5m"] = float(slope)
            
            # 15m trend from df_15m
            if market_data and "df_15m" in market_data:
                df_15m = market_data["df_15m"]
                if df_15m is not None and not df_15m.empty and "close" in df_15m.columns and len(df_15m) >= 5:
                    closes = df_15m["close"].tail(5)
                    if len(closes) >= 2:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["15m"] = float(slope)
            
            # Compute longer timeframes from 15m data (higher TF = fewer bars needed)
            if market_data and "df_15m" in market_data:
                df_15m = market_data["df_15m"]
                if df_15m is not None and not df_15m.empty and "close" in df_15m.columns:
                    # 1h: look at 4 bars of 15m data
                    if len(df_15m) >= 4:
                        closes_1h = df_15m["close"].tail(4)
                        if len(closes_1h) >= 2:
                            slope = (closes_1h.iloc[-1] - closes_1h.iloc[0]) / closes_1h.iloc[0] * 100
                            trends["1h"] = float(slope)
                    
                    # 4h: look at 16 bars of 15m data
                    if len(df_15m) >= 16:
                        closes_4h = df_15m["close"].tail(16)
                        if len(closes_4h) >= 2:
                            slope = (closes_4h.iloc[-1] - closes_4h.iloc[0]) / closes_4h.iloc[0] * 100
                            trends["4h"] = float(slope)
                    
                    # 1D: look at all available 15m data (up to 96 bars = 24h)
                    if len(df_15m) >= 20:
                        closes_1d = df_15m["close"].tail(min(96, len(df_15m)))
                        if len(closes_1d) >= 2:
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
        except Exception:
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
        except Exception:
            bar_time = None
        
        session_open = False
        try:
            session_open = bool(self.strategy.scanner.is_market_hours(dt=bar_time))
        except Exception:
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
        except Exception:
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
            strategy_session_open = self.strategy.scanner.is_market_hours(dt=bar_time)
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

    async def _check_status_update(self) -> None:
        """Send periodic status updates to Telegram (legacy, now uses dashboard)."""
        # Kept for backward compatibility - now handled by _check_dashboard
        pass

    async def _send_status_update(self) -> None:
        """Send status update to Telegram (legacy, now uses dashboard)."""
        try:
            # Use enhanced status with performance metrics
            status = self.get_status()
            await self.telegram_notifier.send_enhanced_status(status)
        except Exception as e:
            logger.error(f"Error sending status update: {e}", exc_info=True)

    def pause(self) -> None:
        """Pause the service."""
        self.paused = True
        self.pause_reason = "manual"
        logger.info("Service paused", extra={"pause_reason": self.pause_reason})

    def resume(self) -> None:
        """Resume the service."""
        self.paused = False
        self.pause_reason = None
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
        """Notify about errors via Telegram."""
        try:
            if self.telegram_notifier.enabled and self.telegram_notifier.telegram:
                await self.telegram_notifier.telegram.notify_risk_warning(
                    f"{title}\n\n{message}",
                    risk_status="ERROR",
                )
        except Exception as e:
            logger.error(f"Error sending error notification: {e}")

    def _check_daily_reset(self) -> None:
        """
        Reset execution daily counters at start of new trading day.
        
        This ensures:
        - _orders_today counter resets to 0 each day
        - _daily_pnl resets to 0.0 each day (for kill switch threshold)
        - Per-signal-type cooldowns clear
        
        Called at start of each scan cycle in the main loop.
        """
        if self.execution_adapter is None:
            return
        
        today = datetime.now(timezone.utc).date()
        
        if self._last_trading_day is None:
            # First cycle - initialize but don't reset (may be mid-day startup)
            self._last_trading_day = today
            return
        
        if self._last_trading_day != today:
            # New trading day - reset counters
            self.execution_adapter.reset_daily_counters()
            logger.info(
                f"Execution daily counters reset for {today} "
                f"(previous day: {self._last_trading_day})"
            )
            self._last_trading_day = today

    async def _check_execution_health(self) -> None:
        """
        Check execution adapter connection health and send alerts on state changes.
        
        Sends Telegram alert when:
        - Connection is lost (was connected, now disconnected)
        - Connection is restored (was disconnected, now connected)
        
        Deduplicates alerts using cooldown to prevent spam.
        """
        if self.execution_adapter is None:
            return
        
        # Only check if execution is enabled
        if self._execution_config is None or not self._execution_config.enabled:
            return
        
        is_connected = self.execution_adapter.is_connected()
        now = datetime.now(timezone.utc)
        
        # Initialize state on first check
        if self._execution_was_connected is None:
            self._execution_was_connected = is_connected
            return
        
        # Check for state change
        if is_connected != self._execution_was_connected:
            # Check cooldown to avoid alert spam
            should_alert = True
            if self._last_connection_alert_time is not None:
                elapsed = (now - self._last_connection_alert_time).total_seconds()
                if elapsed < self._connection_alert_cooldown_seconds:
                    should_alert = False
            
            if should_alert:
                self._last_connection_alert_time = now
                
                if is_connected:
                    # Connection restored
                    message = (
                        "✅ *IBKR Execution Connected*\n\n"
                        "Connection to IBKR Gateway has been restored.\n"
                        f"Execution adapter is now {'armed' if self.execution_adapter.armed else 'disarmed'}."
                    )
                    logger.info("IBKR execution connection restored")
                else:
                    # Connection lost
                    message = (
                        "🔴 *IBKR Execution Disconnected*\n\n"
                        "⚠️ Connection to IBKR Gateway has been lost.\n\n"
                        "• Orders cannot be placed\n"
                        "• Auto-reconnection will be attempted\n"
                        "• Use `/positions` to check status"
                    )
                    logger.warning("IBKR execution connection lost")
                
                # Send Telegram alert
                try:
                    await self.telegram_notifier.telegram.send_message(
                        message,
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"Failed to send connection alert: {e}")
            
            # Update state
            self._execution_was_connected = is_connected

    async def _check_execution_control_flags(self) -> None:
        """
        Check for execution control flag files (from Telegram commands).
        
        Flag files:
        - arm_request.flag: Arm the execution adapter
        - disarm_request.flag: Disarm the execution adapter
        - kill_request.flag: Cancel all orders and disarm
        
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
            except Exception:
                # If we can't determine age, treat as stale for safety
                return True
        
        try:
            state_dir = self.state_manager.state_dir
            
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
            
            # ==========================================================================
            # If execution adapter is None, clear any remaining flags and warn
            # ==========================================================================
            if self.execution_adapter is None:
                for flag_file, action in [(kill_file, "kill"), (disarm_file, "disarm"), (arm_file, "arm")]:
                    if flag_file.exists():
                        logger.warning(
                            f"Clearing {action} flag - execution adapter is disabled. "
                            f"Enable execution.enabled in config to use /arm, /disarm, /kill commands."
                        )
                        flag_file.unlink(missing_ok=True)
                        # Notify user that the command was ignored
                        try:
                            await self.telegram_notifier.telegram.send_message(
                                f"⚠️ *{action.upper()} IGNORED*\n\n"
                                f"Execution adapter is disabled.\n"
                                f"Set `execution.enabled: true` in config and restart to enable ATS.",
                                parse_mode="Markdown",
                            )
                        except Exception:
                            pass
                return
            
            # ==========================================================================
            # Process kill flag (highest priority)
            # ==========================================================================
            if kill_file.exists():
                logger.warning("🚨 KILL flag detected - cancelling all orders and disarming")
                cancelled_count = 0
                cancel_errors: list[str] = []
                try:
                    # SAFETY: Disarm FIRST to prevent new orders while cancelling
                    self.execution_adapter.disarm()
                    logger.warning("Kill switch: execution adapter disarmed")
                    
                    # Cancel all open orders
                    results = await self.execution_adapter.cancel_all()
                    cancelled_count = sum(1 for r in results if r.success)
                    cancel_errors = [r.error_message for r in results if not r.success and r.error_message]
                    logger.warning(f"Kill switch: cancelled {cancelled_count} orders")
                    if cancel_errors:
                        logger.warning(f"Kill switch: {len(cancel_errors)} cancellation errors: {cancel_errors[:3]}")
                except Exception as e:
                    logger.error(f"Error executing kill switch: {e}", exc_info=True)
                    # Even if cancel_all fails, ensure we're disarmed
                    try:
                        self.execution_adapter.disarm()
                    except Exception:
                        pass
                finally:
                    kill_file.unlink(missing_ok=True)
                    # Also remove any pending disarm flag (kill already disarms)
                    disarm_file.unlink(missing_ok=True)
                
                # Notify via Telegram (outside try/finally to ensure flag is always cleared)
                try:
                    error_note = ""
                    if cancel_errors:
                        error_note = f"\n⚠️ Errors: {len(cancel_errors)}"
                    await self.telegram_notifier.telegram.send_message(
                        f"🚨 *KILL SWITCH EXECUTED*\n\n"
                        f"Cancelled: `{cancelled_count}` orders\n"
                        f"Execution: `DISARMED`{error_note}",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
                return  # Skip arm/disarm after kill
            
            # ==========================================================================
            # Process disarm flag
            # ==========================================================================
            if disarm_file.exists():
                logger.info("🔒 DISARM flag detected - disarming execution adapter")
                self.execution_adapter.disarm()
                disarm_file.unlink(missing_ok=True)
                
                # Notify via Telegram
                try:
                    await self.telegram_notifier.telegram.send_message(
                        "🔒 *Execution DISARMED*\n\n"
                        "No new orders will be placed.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
                return  # Skip arm after disarm
            
            # ==========================================================================
            # Process arm flag
            # ==========================================================================
            if arm_file.exists():
                logger.info("🔫 ARM flag detected - arming execution adapter")
                success = self.execution_adapter.arm()
                arm_file.unlink(missing_ok=True)
                
                if success:
                    # Notify via Telegram
                    try:
                        mode = self._execution_config.mode.value if self._execution_config else "unknown"
                        await self.telegram_notifier.telegram.send_message(
                            f"🔫 *Execution ARMED*\n\n"
                            f"Mode: `{mode}`\n"
                            f"Orders will be placed for signals.\n\n"
                            f"⚠️ Use `/disarm` to stop or `/kill` to cancel all.",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
                else:
                    logger.warning("Could not arm execution adapter - preconditions not met")
                    try:
                        await self.telegram_notifier.telegram.send_message(
                            "⚠️ *ARM FAILED*\n\n"
                            "Could not arm execution adapter.\n"
                            "Check that execution is enabled in config.",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
            
            # ==========================================================================
            # Process grade request (manual feedback for learning)
            # ==========================================================================
            grade_file = state_dir / "grade_request.json"
            if grade_file.exists():
                await self._process_grade_request(grade_file)
                        
        except Exception as e:
            logger.error(f"Error checking execution control flags: {e}", exc_info=True)

    async def _process_grade_request(self, grade_file: Path) -> None:
        """Process a grade request from Telegram /grade command.
        
        The grade request contains:
        - signal_id: The signal to grade
        - signal_type: The type of signal (for learning)
        - is_win: Whether it was a win
        - pnl: Optional P&L value
        - force: Whether to apply even if signal already exited
        """
        try:
            with open(grade_file, "r") as f:
                grade_req = json.load(f)
            
            signal_id = grade_req.get("signal_id", "")
            signal_type = grade_req.get("signal_type", "unknown")
            is_win = grade_req.get("is_win", False)
            pnl = grade_req.get("pnl")
            force = grade_req.get("force", False)
            
            logger.info(f"Processing grade request: {signal_id} -> {'win' if is_win else 'loss'} (force={force})")
            
            # Check if signal already has an exit recorded
            signals_file = self.state_manager.signals_file
            already_exited = False
            if signals_file.exists():
                with open(signals_file, "r") as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            if record.get("signal_id") == signal_id:
                                already_exited = record.get("status") == "exited"
                                break
                        except json.JSONDecodeError:
                            continue
            
            # Apply to learning if: not already exited, or force is True
            applied = False
            if self.bandit_policy is not None:
                if not already_exited or force:
                    self.bandit_policy.record_outcome(
                        signal_id=signal_id,
                        signal_type=signal_type,
                        is_win=is_win,
                        pnl=pnl or 0.0,
                    )
                    applied = True
                    logger.info(f"Grade applied to learning: {signal_type} {'win' if is_win else 'loss'}")
                else:
                    logger.info(f"Grade skipped (already exited, force=False): {signal_id}")
            
            # Update feedback.jsonl to mark as applied
            feedback_file = self.state_manager.state_dir / "feedback.jsonl"
            if feedback_file.exists():
                try:
                    # Read all feedback, update the matching one
                    updated_lines = []
                    with open(feedback_file, "r") as f:
                        for line in f:
                            try:
                                rec = json.loads(line.strip())
                                if rec.get("signal_id") == signal_id and not rec.get("applied_to_learning"):
                                    rec["applied_to_learning"] = applied
                                    rec["applied_at"] = datetime.now(timezone.utc).isoformat()
                                updated_lines.append(json.dumps(rec))
                            except json.JSONDecodeError:
                                updated_lines.append(line.strip())
                    with open(feedback_file, "w") as f:
                        f.write("\n".join(updated_lines) + "\n")
                except Exception as e:
                    logger.warning(f"Could not update feedback file: {e}")
            
            # Notify via Telegram
            try:
                if applied:
                    await self.telegram_notifier.telegram.send_message(
                        f"✅ *Grade Applied*\n\n"
                        f"Signal: `{signal_id[:25]}...`\n"
                        f"Type: `{signal_type}`\n"
                        f"Outcome: {'Win' if is_win else 'Loss'}\n"
                        f"Applied to learning policy.",
                        parse_mode="Markdown",
                    )
                else:
                    await self.telegram_notifier.telegram.send_message(
                        f"ℹ️ *Grade Logged*\n\n"
                        f"Signal: `{signal_id[:25]}...`\n"
                        f"Already exited - feedback logged but not applied.\n"
                        f"_Use `force` to override._",
                        parse_mode="Markdown",
                    )
            except Exception:
                pass
            
        except Exception as e:
            logger.error(f"Error processing grade request: {e}", exc_info=True)
        finally:
            # Always clean up the request file
            grade_file.unlink(missing_ok=True)

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
        except Exception:
            pass  # Ignore errors when getting latest bar for status

        # Market/session status
        futures_market_open = None
        try:
            futures_market_open = bool(get_market_hours().is_market_open())
        except Exception:
            futures_market_open = None

        strategy_session_open = None
        try:
            strategy_session_open = bool(self.strategy.scanner.is_market_hours())
        except Exception:
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
            # Learning/policy status
            "learning": (
                self.bandit_policy.get_status()
                if self.bandit_policy is not None
                else {"enabled": False, "mode": "disabled"}
            ),
            # Contextual learning (optional)
            "learning_contextual": (
                self.contextual_policy.get_status()
                if self.contextual_policy is not None
                else {"enabled": False, "mode": "disabled"}
            ),
            # Drift guard (risk-off cooldown)
            "drift_guard": (self._drift_guard_state or {"active": False}),
            # ML filter operational status (shadow/live + lift gating)
            "ml_filter": {
                "mode": getattr(self, "_ml_filter_mode", "shadow"),
                "require_lift_to_block": bool(getattr(self, "_ml_require_lift_to_block", True)),
                "blocking_allowed": bool(getattr(self, "_ml_blocking_allowed", False)),
                "lift": getattr(self, "_ml_lift_metrics", {}) or {},
                "last_eval_at": (
                    self._ml_lift_last_eval_at.isoformat()
                    if getattr(self, "_ml_lift_last_eval_at", None) is not None
                    else None
                ),
            },
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

    def _compute_ml_lift_metrics(self, trades: list) -> Dict[str, Any]:
        """
        Compute shadow A/B lift for ML gating:
        Compare outcomes for trades where ML would PASS vs would BLOCK.

        Expects trade dicts from TradeDatabase.get_recent_trades_by_exit(), including:
        - is_win (bool)
        - pnl (float)
        - features.ml_pass_filter (0/1)
        - features.ml_fallback_used (0/1)
        """
        if not isinstance(trades, list) or not trades:
            return {"status": "no_trades", "lift_ok": False, "blocking_allowed": False}

        # Filter to trades that have real ML predictions (exclude fallback-only periods).
        scored = []
        for t in trades:
            if not isinstance(t, dict):
                continue
            feats = t.get("features", {})
            if not isinstance(feats, dict):
                continue
            if "ml_pass_filter" not in feats:
                continue
            # If model wasn't ready, ML filter is in neutral fallback (no gating signal).
            try:
                if float(feats.get("ml_fallback_used", 0.0) or 0.0) >= 0.5:
                    continue
            except Exception:
                pass
            scored.append(t)

        total_scored = len(scored)
        if total_scored < int(getattr(self, "_ml_lift_min_trades", 50) or 50):
            return {
                "status": "insufficient_data",
                "scored_trades": total_scored,
                "min_trades": int(getattr(self, "_ml_lift_min_trades", 50) or 50),
                "lift_ok": False,
                "blocking_allowed": False,
            }

        pass_group = []
        fail_group = []
        for t in scored:
            feats = t.get("features", {}) or {}
            try:
                pass_flag = float(feats.get("ml_pass_filter", 1.0) or 0.0) >= 0.5
            except Exception:
                pass_flag = True
            if pass_flag:
                pass_group.append(t)
            else:
                fail_group.append(t)

        if not pass_group or not fail_group:
            return {
                "status": "no_split",
                "scored_trades": total_scored,
                "pass_trades": len(pass_group),
                "fail_trades": len(fail_group),
                "lift_ok": False,
                "blocking_allowed": False,
                "reason": "Need both pass+fail groups to measure lift",
            }

        def _wr(xs: list) -> float:
            wins = 0
            for t in xs:
                try:
                    if bool(t.get("is_win", False)):
                        wins += 1
                except Exception:
                    continue
            return wins / max(1, len(xs))

        def _avg_pnl(xs: list) -> float:
            vals = []
            for t in xs:
                try:
                    vals.append(float(t.get("pnl", 0.0) or 0.0))
                except Exception:
                    continue
            return float(sum(vals) / max(1, len(vals))) if vals else 0.0

        wr_pass = _wr(pass_group)
        wr_fail = _wr(fail_group)
        lift_wr = wr_pass - wr_fail
        avg_pnl_pass = _avg_pnl(pass_group)
        avg_pnl_fail = _avg_pnl(fail_group)
        lift_pnl = avg_pnl_pass - avg_pnl_fail

        min_delta = float(getattr(self, "_ml_lift_min_winrate_delta", 0.05) or 0.05)
        lift_ok = bool(lift_wr >= min_delta)

        # Actual blocking permission depends on mode + lift gating config.
        if bool(getattr(self, "_ml_require_lift_to_block", True)):
            blocking_allowed = bool((getattr(self, "_ml_filter_mode", "shadow") == "live") and lift_ok)
        else:
            blocking_allowed = bool(getattr(self, "_ml_filter_mode", "shadow") == "live")

        return {
            "status": "ok",
            "scored_trades": total_scored,
            "pass_trades": len(pass_group),
            "fail_trades": len(fail_group),
            "win_rate_pass": float(wr_pass),
            "win_rate_fail": float(wr_fail),
            "lift_win_rate": float(lift_wr),
            "avg_pnl_pass": float(avg_pnl_pass),
            "avg_pnl_fail": float(avg_pnl_fail),
            "lift_avg_pnl": float(lift_pnl),
            "lift_ok": bool(lift_ok),
            "lift_min_winrate_delta": float(min_delta),
            "mode": getattr(self, "_ml_filter_mode", "shadow"),
            "require_lift_to_block": bool(getattr(self, "_ml_require_lift_to_block", True)),
            "blocking_allowed": bool(blocking_allowed),
        }

    def _refresh_ml_lift(self, *, force: bool = False) -> None:
        """Refresh ML lift metrics + blocking allowance (best-effort)."""
        try:
            # Only meaningful when SQLite is enabled
            if not getattr(self, "_sqlite_enabled", False) or self._trade_db is None:
                self._ml_lift_metrics = {"status": "sqlite_disabled", "lift_ok": False, "blocking_allowed": False}
                self._ml_blocking_allowed = False
                return

            now = datetime.now(timezone.utc)
            # Rate limit lift evaluation (cheap, but no need every 5s)
            if (not force) and self._ml_lift_last_eval_at is not None:
                if (now - self._ml_lift_last_eval_at).total_seconds() < 300:
                    return

            trades = self._trade_db.get_recent_trades_by_exit(limit=int(self._ml_lift_lookback_trades or 200))
            metrics = self._compute_ml_lift_metrics(trades)
            self._ml_lift_metrics = metrics
            self._ml_blocking_allowed = bool(metrics.get("blocking_allowed", False))
            self._ml_lift_last_eval_at = now
        except Exception as e:
            logger.debug(f"Could not refresh ML lift metrics: {e}")

    async def _refresh_drift_guard(self) -> None:
        """Update drift guard state and send operator alerts on transitions."""
        if self._drift_guard is None or self._drift_guard_config is None:
            return

        now = datetime.now(timezone.utc)
        # Snapshot previous active state so we don't spam operators when the guard extends
        # its cooldown window every cycle.
        prev_active = False
        try:
            prev_active = bool((self._drift_guard_state or {}).get("active", False))
        except Exception:
            prev_active = False
        recent_trades = []
        if getattr(self, "_sqlite_enabled", False) and self._trade_db is not None:
            try:
                # Pull enough to evaluate lookback and min_trades
                n = max(int(self._drift_guard_config.lookback_trades), int(self._drift_guard_config.min_trades))
                recent_trades = self._trade_db.get_recent_trades_by_exit(limit=max(1, n))
            except Exception:
                recent_trades = []

        # Current regime snapshot from scanner (best-effort)
        regime = None
        try:
            regime = getattr(self.strategy.scanner, "last_regime", None)
        except Exception:
            regime = None

        state, transition = self._drift_guard.update(regime=regime, recent_trades=recent_trades, now=now)
        self._drift_guard_state = state.to_dict(self._drift_guard_config)

        # Operator alerts (deduped):
        # Only alert when the guard *enters* cooldown (OFF -> ON) or *ends*.
        send_on = bool(transition.get("triggered") and not prev_active)
        send_off = bool(transition.get("ended"))
        if (not send_on and not send_off) or not self.telegram_notifier.enabled or self.telegram_notifier.telegram is None:
            return

        # Hard cooldown to avoid spam (even if state toggles quickly)
        if self._drift_guard_last_alert_at is not None:
            if (now - self._drift_guard_last_alert_at).total_seconds() < 300:
                return

        try:
            if send_on:
                adj = state.adjustments(self._drift_guard_config)
                msg = (
                    "🛡 Drift Guard: ON\n"
                    f"- reason: {transition.get('reason', '')}\n"
                    f"- until (UTC): {state.until}\n"
                    f"- tighten: +{adj.get('min_confidence_delta', 0):.2f} conf, +{adj.get('min_risk_reward_delta', 0):.2f} R:R\n"
                    f"- size mult: ×{adj.get('size_multiplier', 1.0):.2f}\n"
                )
                await self.telegram_notifier.telegram.send_message(msg, parse_mode=None, dedupe=False)
                self._drift_guard_last_alert_at = now
            elif send_off:
                msg = "🛡 Drift Guard: OFF (cooldown ended)"
                await self.telegram_notifier.telegram.send_message(msg, parse_mode=None, dedupe=False)
                self._drift_guard_last_alert_at = now
        except Exception as e:
            logger.debug(f"Could not send drift guard alert: {e}")

    def _save_state(self) -> None:
        """Save current service state."""
        # Include lightweight data freshness metadata for Telegram UI / operators.
        latest_bar_timestamp = None
        latest_bar_age_minutes = None
        data_fresh = None
        latest_bar = None
        
        # Get market status for market-aware freshness check
        futures_market_open: Optional[bool] = None
        try:
            futures_market_open = bool(get_market_hours().is_market_open())
        except Exception:
            pass
        
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            # Use market-aware freshness check to avoid false "stale" warnings when market is closed
            freshness = self.data_quality_checker.check_data_freshness(
                last_market_data.get("latest_bar"),
                last_market_data.get("df"),
                market_open=futures_market_open,
            )
            ts = freshness.get("timestamp")
            if ts:
                latest_bar_timestamp = ts.isoformat()
                latest_bar_age_minutes = float(freshness.get("age_minutes", 0.0))
                data_fresh = bool(freshness.get("is_fresh", False))
            # Persist latest_bar for Telegram command UI (order book transparency)
            raw_bar = last_market_data.get("latest_bar")
            if raw_bar and isinstance(raw_bar, dict):
                # Ensure JSON-serializable (timestamps as ISO strings)
                latest_bar = {}
                for k, v in raw_bar.items():
                    if hasattr(v, "isoformat"):
                        latest_bar[k] = v.isoformat()
                    elif hasattr(v, "item"):  # numpy scalar
                        latest_bar[k] = v.item()
                    else:
                        latest_bar[k] = v
        except Exception:
            # Never let status persistence fail due to optional metadata.
            pass

        # Get run_id for log correlation (if set by logging_config)
        run_id = None
        try:
            from pearlalgo.utils.logging_config import get_run_id
            run_id = get_run_id()
        except Exception:
            pass

        # Get version for operational visibility
        version = None
        try:
            from importlib.metadata import version as get_version
            version = get_version("pearlalgo-dev-ai-agents")
        except Exception:
            version = "0.2.2"  # Fallback to known version

        state = {
            # Core service state
            "running": self.running,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            # Counters (lifetime)
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "signals_sent": self.signals_sent,
            "signals_send_failures": self.signals_send_failures,
            "last_signal_send_error": self.last_signal_send_error,
            "last_signal_generated_at": self.last_signal_generated_at,
            "last_signal_sent_at": self.last_signal_sent_at,
            "last_signal_id_prefix": self.last_signal_id_prefix,
            # Counters (session - since start)
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
            # Error/health counters (for watchdog + Telegram UI)
            "error_count": self.error_count,
            "consecutive_errors": self.consecutive_errors,
            "connection_failures": self.connection_failures,
            "data_fetch_errors": self.data_fetch_errors,
            # Data quality
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "buffer_size_target": self.buffer_size_target,
            "data_fresh": data_fresh,
            "latest_bar_timestamp": latest_bar_timestamp,
            "latest_bar_age_minutes": latest_bar_age_minutes,
            "latest_bar": latest_bar,
            "last_successful_cycle": (
                self.last_successful_cycle.isoformat() if self.last_successful_cycle else None
            ),
            # Market/session status used by Telegram UI and operators.
            # - futures_market_open: CME ETH + maintenance break semantics
            # - strategy_session_open: configurable strategy window (default 18:00–16:10 ET)
            "futures_market_open": None,
            "strategy_session_open": None,
            # Config thresholds (for external tools to compare against)
            "data_stale_threshold_minutes": self.stale_data_threshold_minutes,
            "connection_timeout_minutes": self.connection_timeout_minutes,
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
                # Session window (for Telegram UI observability)
                "session_start_time": getattr(self.config, "start_time", "18:00"),
                "session_end_time": getattr(self.config, "end_time", "16:10"),
                # Adaptive cadence config
                "adaptive_cadence_enabled": self._adaptive_cadence_enabled,
                "scan_interval_active": self._scan_interval_active,
                "scan_interval_idle": self._scan_interval_idle,
                "scan_interval_market_closed": self._scan_interval_market_closed,
                "scan_interval_paused": self._scan_interval_paused,
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
            # Buy/Sell pressure (volume-based proxy) for /status parity with push dashboard
            "buy_sell_pressure": None,
            "buy_sell_pressure_raw": None,
            # Market regime snapshot (computed each scan by scanner.regime_detector)
            # Used by Claude Monitor and operator UI to detect "market changed" events.
            "regime": None,
            "regime_timestamp": None,
            # Quiet reason / signal diagnostics observability (why no signals?)
            # These are set each cycle and surfaced in /status and dashboards.
            "quiet_reason": self._last_quiet_reason,
            "signal_diagnostics": self._last_signal_diagnostics,
            "signal_diagnostics_raw": self._last_signal_diagnostics_raw,
            # Quiet period duration: how long since last signal was generated
            # Useful for monitoring signal generation health
            "quiet_period_minutes": self._compute_quiet_period_minutes(),
            # Operational metadata
            "run_id": run_id,
            "version": version,
        }
        # Reuse futures_market_open from earlier check (avoid duplicate API call)
        state["futures_market_open"] = futures_market_open
        try:
            state["strategy_session_open"] = bool(self.strategy.scanner.is_market_hours())
        except Exception:
            state["strategy_session_open"] = None

        # Persist current regime snapshot from scanner (best-effort)
        try:
            reg = getattr(self.strategy.scanner, "last_regime", None)
            if isinstance(reg, dict):
                # Ensure JSON serializable (convert numpy scalars, timestamps, etc.)
                reg_safe: Dict[str, Any] = {}
                for k, v in reg.items():
                    if hasattr(v, "isoformat"):
                        reg_safe[k] = v.isoformat()
                    elif hasattr(v, "item"):  # numpy scalar
                        reg_safe[k] = v.item()
                    else:
                        reg_safe[k] = v
                state["regime"] = reg_safe
            else:
                state["regime"] = None
            state["regime_timestamp"] = getattr(self.strategy.scanner, "last_regime_timestamp", None)
        except Exception:
            state["regime"] = None
            state["regime_timestamp"] = None

        # Compute and persist buy/sell pressure from last market data (best-effort)
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            df_for_pressure = last_market_data.get("df")
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
                    state["buy_sell_pressure_raw"] = summary.to_dict()
                    state["buy_sell_pressure"] = format_volume_pressure(
                        summary,
                        timeframe_minutes=tf_min,
                        data_fresh=data_fresh,
                    )
        except Exception:
            pass

        # ==========================================================================
        # PROP FIRM status (best-effort)
        # ==========================================================================
        # Persist prop firm metrics so Telegram UI can show "how close to limits?"
        # even if execution is disabled (manual trading workflow).
        state["prop_firm"] = (
            {"enabled": bool(getattr(self._prop_firm_config, "enabled", False)), "profile": getattr(self._prop_firm_config, "profile", None)}
            if self._prop_firm_config is not None
            else {"enabled": False}
        )
        if self.prop_firm_guard is not None:
            try:
                pf_status = self.prop_firm_guard.compute_status()
                self._prop_firm_status = pf_status
                state["prop_firm"] = pf_status.to_dict()
            except Exception as pf_e:
                state["prop_firm"] = {
                    "enabled": True,
                    "profile": getattr(self._prop_firm_config, "profile", None) if self._prop_firm_config else None,
                    "error": str(pf_e)[:120],
                }

        # ==========================================================================
        # ATS (Automated Trading System) status - for Telegram commands
        # ==========================================================================
        # Persist execution and learning status so /arm, /positions, /policy commands
        # can read accurate state even when service is running.
        state["execution"] = (
            self.execution_adapter.get_status()
            if self.execution_adapter is not None
            else {"enabled": False, "armed": False, "mode": "disabled"}
        )
        state["learning"] = (
            self.bandit_policy.get_status()
            if self.bandit_policy is not None
            else {"enabled": False, "mode": "disabled"}
        )

        self.state_manager.save_state(state)

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
            
            await self.telegram_notifier.send_heartbeat(status)
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
        except Exception:
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
                    await self.telegram_notifier.send_data_quality_alert(
                        "stale_data",
                        f"Data is {age_minutes:.1f} minutes old",
                        {"age_minutes": age_minutes, "bucket": bucket},
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
                await self.telegram_notifier.send_data_quality_alert(
                    "recovery",
                    "Market data recovered (fresh bars again)",
                    {},
                )
                self.last_data_quality_alert = now
            self._was_stale_during_market = False
            self._last_stale_bucket = None

        # 2) Data gap (empty dataframe)
        df = market_data.get("df")
        if df is not None and df.empty:
            self._was_data_gap = True
            if (self._last_stale_data_alert_type != "data_gap") and (not throttled):
                await self.telegram_notifier.send_data_quality_alert(
                    "data_gap",
                    "No market data available",
                    {},
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
                await self.telegram_notifier.send_data_quality_alert(
                    "recovery",
                    "Market data gap recovered",
                    {},
                )
                self.last_data_quality_alert = now
            self._was_data_gap = False

        # 3) Buffer size issues (only send when severity changes)
        if not validation["buffer_size"]["is_adequate"]:
            buffer_size = int(validation["buffer_size"].get("buffer_size", 0) or 0)
            severity = _buffer_severity(buffer_size)
            if (self._last_buffer_severity != severity) and (not throttled):
                await self.telegram_notifier.send_data_quality_alert(
                    "buffer_issue",
                    f"Buffer size is low: {buffer_size} bars",
                    {"buffer_size": buffer_size, "severity": severity},
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
                await self.telegram_notifier.send_data_quality_alert(
                    "recovery",
                    "Buffer recovered (enough bars for strategy)",
                    {},
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
            await self.telegram_notifier.send_data_quality_alert(
                "fetch_failure",
                f"IB Gateway connection issue detected ({self.connection_failures} failures). "
                "Check if IB Gateway is running.",
                {
                    "connection_failures": self.connection_failures,
                    "error_type": "connection",
                    "suggestion": "Run: ./scripts/gateway/gateway.sh status or ./scripts/gateway/gateway.sh start",
                },
            )
            self.last_connection_failure_alert = now

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        signal_names = {
            signal.SIGINT: "SIGINT (Ctrl+C)",
            signal.SIGTERM: "SIGTERM",
        }
        signal_name = signal_names.get(signum, f"Signal {signum}")
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self.shutdown_requested = True
