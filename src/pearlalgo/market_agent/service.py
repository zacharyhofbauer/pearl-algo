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
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp, parse_utc_timestamp

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
from pearlalgo.utils.volume_pressure import (
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)
from pearlalgo.utils.pearl_suggestions import get_suggestion_engine
from pearlalgo.ai.shadow_tracker import get_shadow_tracker, SuggestionType

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

# Tradovate execution adapter (optional - only for prop firm / MFFU)
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
    """
    et_tz = ZoneInfo("America/New_York")
    now_et = datetime.now(et_tz)

    if now_et.hour < 18:
        # Before 6pm ET - still in previous day's trading session
        return (now_et - timedelta(days=1)).date()
    else:
        # After 6pm ET - in current day's trading session
        return now_et.date()


class MarketAgentService:
    """
    24/7 service for NQ intraday trading strategy.
    
    Runs independently, fetches data, generates signals, and sends to Telegram.
    """

    def __init__(
        self,
        data_provider: DataProvider,
        config: Optional[Dict] = None,
        state_dir: Optional[Path] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        """
        Initialize market agent service.
        
        Args:
            data_provider: Data provider instance
            config: Strategy configuration (optional)
            state_dir: State directory (optional)
            telegram_bot_token: Telegram bot token (optional)
            telegram_chat_id: Telegram chat ID (optional)
        """
        # Use PearlBot Auto config (from Pine Scripts)
        self.config = ConfigView(config or PEARL_BOT_CONFIG.copy())
        self.symbol = str(self.config.get("symbol", "MNQ"))
        self.timeframe = str(self.config.get("timeframe", "5m"))
        self.scan_interval = float(self.config.get("scan_interval", 30))
        
        # Strategy adapter (kept so tests can monkeypatch `service.strategy.analyze`).
        # Internally it delegates to `pearlalgo.trading_bots.pearl_bot_auto.generate_signals`.
        class _StrategyAdapter:
            def __init__(self, config: ConfigView):
                self.config = config

            def analyze(self, df: pd.DataFrame, *, current_time: Optional[datetime] = None) -> list[dict]:
                return generate_signals(df, config=self.config, current_time=current_time)

        self.strategy = _StrategyAdapter(self.config)
        
        # Create a simple config dict for data_fetcher compatibility
        nq_config_dict = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }
        self.data_fetcher = MarketAgentDataFetcher(data_provider, config=nq_config_dict)

        self.state_manager = MarketAgentStateManager(state_dir=state_dir)
        self.performance_tracker = PerformanceTracker(
            state_dir=state_dir,
            state_manager=self.state_manager,
        )
        # Derive account label for Telegram messages (e.g. "MFFU" for prop firm)
        challenge_cfg = (config or {}).get("challenge", {}) if isinstance(config, dict) else {}
        if not challenge_cfg:
            try:
                from pearlalgo.config.config_loader import load_service_config
                challenge_cfg = load_service_config().get("challenge", {}) or {}
            except Exception:
                challenge_cfg = {}
        _mffu_stage = str(challenge_cfg.get("stage", "") or "").strip().lower()
        _account_label = "MFFU" if _mffu_stage in ("mffu_eval", "evaluation", "sim_funded", "live") else None

        self.telegram_notifier = MarketAgentTelegramNotifier(
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
            state_dir=state_dir,
            account_label=_account_label,
        )
        
        # Initialize notification queue for non-blocking Telegram delivery
        # Load service config early for telegram tier (full config loaded later at line ~237)
        try:
            _early_cfg = load_service_config()
            telegram_settings = _early_cfg.get("telegram", {}) or {}
        except Exception:
            telegram_settings = {}
        _min_tier = str(telegram_settings.get("notification_tier", "important") or "important")
        self.notification_queue = NotificationQueue(
            telegram_notifier=self.telegram_notifier,
            max_queue_size=1000,
            batch_delay_seconds=0.5,
            max_retries=3,
            min_tier=_min_tier,
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
        trading_circuit_breaker_settings = service_config.get("trading_circuit_breaker", {}) or {}
        data_settings = service_config.get("data", {})
        telegram_ui_settings = service_config.get("telegram_ui", {}) or {}
        auto_flat_settings = service_config.get("auto_flat", {}) or {}
        signal_settings = service_config.get("signals", {}) or {}
        self._risk_settings = service_config.get("risk", {}) or {}
        self._strategy_settings = service_config.get("strategy", {}) or {}

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
            from pearlalgo.market_agent.challenge_tracker import ChallengeTracker, ChallengeConfig
            
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
        # MFFU EVALUATION TRACKER (Prop Firm Rules)
        # ==========================================================================
        self._mffu_tracker = None
        self._mffu_enabled = False
        try:
            challenge_cfg = service_config.get("challenge", {}) or {}
            mffu_stage = str(challenge_cfg.get("stage", "") or "").strip().lower()
            if mffu_stage in ("mffu_eval", "evaluation", "sim_funded", "live"):
                from pearlalgo.market_agent.mffu_eval_tracker import (
                    MFFUEvaluationTracker,
                    MFFUEvalConfig,
                )
                mffu_cfg = MFFUEvalConfig(
                    enabled=True,
                    stage=mffu_stage if mffu_stage != "mffu_eval" else "evaluation",
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
                self._mffu_tracker = MFFUEvaluationTracker(
                    config=mffu_cfg,
                    state_dir=self.state_manager.state_dir,
                )
                self._mffu_enabled = True
                logger.info(
                    f"MFFU Eval Tracker enabled: stage={mffu_cfg.stage}, "
                    f"target=+${mffu_cfg.profit_target:,.0f}, "
                    f"max_loss=-${mffu_cfg.max_loss_distance:,.0f}"
                )
        except Exception as e:
            logger.warning(f"MFFU tracker init failed (continuing without): {e}")
            self._mffu_tracker = None
            self._mffu_enabled = False

        # ==========================================================================
        # DRIFT GUARD (Risk-Off Cooldown)
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
        # Shadow-only threshold for lift measurement (does NOT affect trading; only pass/fail labels).
        self._ml_shadow_threshold: Optional[float] = None
        try:
            st = ml_cfg.get("shadow_threshold", None)
            if st is not None:
                self._ml_shadow_threshold = float(st)
        except Exception:
            self._ml_shadow_threshold = None
        # Default safe: do NOT allow live blocking until we have evaluated lift.
        self._ml_blocking_allowed: bool = False
        self._ml_lift_metrics: Dict[str, Any] = {}
        self._ml_lift_last_eval_at: Optional[datetime] = None

        # ML sizing/priority adjustments (shadow-safe; does not bypass risk gates)
        self._ml_adjust_sizing = bool(ml_cfg.get("adjust_sizing", False))
        try:
            self._ml_size_multiplier_min = float(ml_cfg.get("size_multiplier_min", 1.0) or 1.0)
            self._ml_size_multiplier_max = float(ml_cfg.get("size_multiplier_max", 1.5) or 1.5)
        except Exception:
            self._ml_size_multiplier_min = 1.0
            self._ml_size_multiplier_max = 1.5
        try:
            self._ml_size_threshold = float(ml_cfg.get("high_probability", 0.7) or 0.7)
        except Exception:
            self._ml_size_threshold = 0.7

        # ML signal filter (shadow-only measurement by default; never blocks unless explicitly enabled elsewhere)
        self._ml_filter_enabled: bool = bool(ml_cfg.get("enabled", False))
        self._ml_signal_filter: Optional["MLSignalFilter"] = None
        self._ml_filter_init_status: Dict[str, Any] = {}
        if self._ml_filter_enabled:
            if not ML_FILTER_AVAILABLE or get_ml_signal_filter is None:
                logger.warning("ML filter enabled in config, but dependencies unavailable (skipping)")
                self._ml_filter_enabled = False
            else:
                try:
                    # Train from recent exited signals (shadow dataset) so predictions are non-trivial.
                    train_limit = int(ml_cfg.get("training_max_samples", 2000) or 2000)
                    trades_for_training = self._build_ml_training_trades_from_signals(limit=train_limit)
                    self._ml_signal_filter = get_ml_signal_filter(config=service_config, trades=trades_for_training)
                    self._ml_filter_init_status = {
                        "enabled": True,
                        "mode": str(self._ml_filter_mode),
                        "trained": bool(getattr(self._ml_signal_filter, "is_ready", False)),
                        "training_samples": int(len(trades_for_training)),
                    }
                    logger.info(
                        "ML filter initialized",
                        extra={
                            "mode": self._ml_filter_mode,
                            "trained": bool(getattr(self._ml_signal_filter, "is_ready", False)),
                            "training_samples": int(len(trades_for_training)),
                        },
                    )
                except Exception as e:
                    logger.warning(f"ML filter init failed (continuing without): {e}")
                    self._ml_signal_filter = None
                    self._ml_filter_enabled = False

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
        self.connection_failure_alert_interval = service_settings.get("connection_failure_alert_interval", 600)
        self.data_quality_alert_interval = service_settings.get("data_quality_alert_interval", 300)
        self.consecutive_errors = 0
        self.max_consecutive_errors = circuit_breaker_settings.get("max_consecutive_errors", 10)
        self.data_fetch_errors = 0
        self.max_data_fetch_errors = circuit_breaker_settings.get("max_data_fetch_errors", 5)
        self.connection_failures = 0
        self.max_connection_failures = circuit_breaker_settings.get("max_connection_failures", 10)
        
        # Streak tracking for alerts (win/loss streaks)
        self._streak_count = 0
        self._streak_type: Optional[str] = None  # 'win' or 'loss'
        self._streak_alert_threshold = 3  # Alert at 3+ streak
        self._last_streak_alert_count = 0  # Avoid duplicate alerts
        
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

        # Initialize Pearl AI shadow tracker (tracks suggestion outcomes)
        self.shadow_tracker = get_shadow_tracker(state_dir=self.state_manager.state_dir)

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
            (execution_settings or {}).get("adapter", "ibkr")
        ).strip().lower()
        
        if EXECUTION_AVAILABLE and execution_settings.get("enabled", False):
            try:
                self._execution_config = ExecutionConfig.from_dict(execution_settings)
                if execution_adapter_name in ("ibkr", "", "interactivebrokers"):
                    self.execution_adapter = IBKRExecutionAdapter(self._execution_config)
                elif execution_adapter_name == "tradovate" and TRADOVATE_AVAILABLE:
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

        logger.info("MarketAgentService initialized")

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

        # Start notification queue for async Telegram delivery
        await self.notification_queue.start()
        logger.info("Notification queue started")

        # Startup flow:
        # 1) Rich startup notification (stable)
        # 2) Immediately follow with the /start-style visual dashboard (chart + caption + buttons)
        market_data = {}
        try:
            # Try to fetch a bar quickly so startup can include price.
            try:
                market_data = await asyncio.wait_for(self.data_fetcher.fetch_latest_data(), timeout=5.0) or {}
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"Could not fetch market data for startup: {e}")
                market_data = {}

            config_dict = {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
                "current_time": get_utc_timestamp(),
            }

            # Gates (explicit so startup never shows UNKNOWN).
            try:
                config_dict["futures_market_open"] = bool(get_market_hours().is_market_open())
            except Exception:
                config_dict["futures_market_open"] = None
            try:
                from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
                config_dict["strategy_session_open"] = check_trading_session(datetime.now(timezone.utc), self.config)
            except Exception:
                config_dict["strategy_session_open"] = None

            try:
                lb = (market_data or {}).get("latest_bar")
                if isinstance(lb, dict) and "close" in lb:
                    config_dict["latest_price"] = lb.get("close")
            except Exception:
                pass

            await self.notification_queue.enqueue_startup(config_dict, priority=Priority.NORMAL)
            logger.info("Startup notification queued")
        except Exception as e:
            logger.debug(f"Could not send startup notification: {e}")

        # Skip automatic dashboard on startup - user can type /start for full dashboard
        # This keeps startup notifications clean and gives user control
        now = datetime.now(timezone.utc)
        self.last_status_update = now
        self.last_dashboard_chart_sent = now  # Prevent auto-chart on first cycle
        logger.info("Startup complete - user can use /start for dashboard")

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

        # Stop notification queue gracefully (drains pending notifications)
        try:
            await self.notification_queue.stop(timeout=10.0)
            queue_stats = self.notification_queue.get_stats()
            logger.info(f"Notification queue stopped: {queue_stats}")
        except Exception as e:
            logger.warning(f"Error stopping notification queue: {e}")

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
        # Persist a final state with running=False so /start doesn't show stale "ON"
        # after a stop/shutdown notification.
        try:
            self._save_state()
        except Exception as e:
            logger.warning(f"Could not save stopped state: {e}")
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

            # Check for morning briefing (6:30 AM ET)
            await self._check_morning_briefing()

            # Check for safety close daily summary (3:55 PM ET / 4:00 PM ET)
            await self._check_market_close_summary()

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
                    try:
                        self.state_manager.append_event(
                            "paused_cycle_skipped",
                            {"cycle": int(self.cycle_count or 0), "pause_reason": str(self.pause_reason or "")},
                            level="info",
                        )
                    except Exception:
                        pass
                    # Reset cadence scheduler on pause to avoid catch-up storm on resume
                    if self.cadence_scheduler:
                        self.cadence_scheduler.reset()
                    # SAFETY: Use interruptible sleep so kill commands are processed even when paused
                    await self._interruptible_sleep(self._scan_interval_paused)
                    continue

                # Fetch latest data with error handling
                try:
                    try:
                        self.state_manager.append_event(
                            "scan_started",
                            {
                                "cycle": int(self.cycle_count or 0),
                                "scan_interval_effective": float(getattr(self, "_effective_interval", self.config.scan_interval) or 0),
                                "symbol": str(self.config.symbol),
                            },
                            level="info",
                        )
                    except Exception:
                        pass
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
                            await self.notification_queue.enqueue_circuit_breaker(
                                "IB Gateway connection lost",
                                {
                                    "connection_failures": self.connection_failures,
                                    "error_type": "connection",
                                    "action_taken": "Service paused - IB Gateway appears to be down",
                                },
                                priority=Priority.CRITICAL,
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

                    # Close-all handler (manual flag + auto-flat rules)
                    try:
                        await self._handle_close_all_requests(market_data)
                    except Exception as e:
                        logger.debug(f"Close-all handler error: {e}")

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
                        await self.notification_queue.enqueue_data_quality_alert(
                            "fetch_failure",
                            f"Consecutive data fetch failures: {self.data_fetch_errors}",
                            {"consecutive_failures": self.data_fetch_errors},
                            priority=Priority.NORMAL,
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
                    
                    # Check for proactive Pearl suggestions (agentic)
                    await self._check_pearl_suggestions()

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
                except Exception:
                    pass

                # Generate signals (or skip if no new bar)
                signals = []
                if skip_analysis:
                    # Lightweight cycle: skip heavy analysis, but still run health/status/exit grading
                    pass
                else:
                    # Full analysis: new bar arrived - use pearl_bot_auto
                    df = market_data.get("df")
                    if df is not None and not df.empty:
                        signals = self.strategy.analyze(df, current_time=datetime.now(timezone.utc))
                    else:
                        signals = []
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
                from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
                check_time = latest_bar_time if latest_bar_time else datetime.now(timezone.utc)
                strategy_session_open = check_trading_session(check_time, self.config)
                futures_market_open = False
                try:
                    futures_market_open = bool(get_market_hours().is_market_open())
                except Exception:
                    futures_market_open = False
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
                                await self.notification_queue.enqueue_raw_message(
                                    f"📈 Swing Trade Detected: {signal_type} {signal_direction}\n"
                                    f"Confidence: {signal.get('confidence', 0):.1%}\n"
                                    f"Target: ${signal.get('take_profit', 0):.2f}",
                                    priority=Priority.NORMAL,
                                )
                            except Exception:
                                pass  # Non-fatal
                        
                        # Get buffer data for chart generation
                        buffer_data = market_data.get("df", pd.DataFrame())
                        try:
                            self.state_manager.append_event(
                                "signal_generated",
                                {
                                    "cycle": int(self.cycle_count or 0),
                                    "symbol": str(signal.get("symbol") or self.config.symbol),
                                    "type": str(signal.get("type") or "unknown"),
                                    "direction": str(signal.get("direction") or "unknown"),
                                    "trade_type": str(signal.get("trade_type") or ""),
                                    "confidence": float(signal.get("confidence") or 0.0),
                                    "entry_price": float(signal.get("entry_price") or 0.0),
                                    "stop_loss": float(signal.get("stop_loss") or 0.0),
                                    "take_profit": float(signal.get("take_profit") or 0.0),
                                },
                                level="info",
                            )
                        except Exception:
                            pass
                        await self._process_signal(signal, buffer_data=buffer_data)
                else:
                    logger.debug(f"No signals generated in cycle {self.cycle_count}")

                # Virtual PnL lifecycle: exit signals when TP/SL is touched (no Telegram spam).
                # This grades signal quality without auto-trading.
                try:
                    self._update_virtual_trade_exits(market_data)
                except Exception as e:
                    logger.debug(f"Virtual exit update failed (non-fatal): {e}")

                # Refresh ML lift metrics AFTER we grade exits (so decisions use latest outcomes).
                try:
                    self._refresh_ml_lift()
                except Exception as e:
                    logger.debug(f"ML lift refresh failed (non-fatal): {e}")

                # Send periodic dashboard (replaces status + heartbeat)
                # Determine quiet reason (for observability) and capture diagnostics every cycle (for SQLite rollups).
                quiet_reason = "Active" if signals else self._get_quiet_reason(market_data, has_data=True, no_signals=True)
                signal_diagnostics = None
                signal_diagnostics_raw = None

                # Persist to instance variables for _save_state() (surfaced in /status)
                self._last_quiet_reason = quiet_reason
                self._last_signal_diagnostics = signal_diagnostics
                self._last_signal_diagnostics_raw = signal_diagnostics_raw

                # SQLite observability: persist per-cycle diagnostics for 24h /doctor summaries.
                self._persist_cycle_diagnostics(
                    quiet_reason=quiet_reason,
                    diagnostics_raw=signal_diagnostics_raw,
                )
                
                # Check for proactive Pearl suggestions (agentic)
                await self._check_pearl_suggestions()

                await self._check_dashboard(market_data, quiet_reason=quiet_reason, signal_diagnostics=signal_diagnostics)
                try:
                    self.state_manager.append_event(
                        "scan_finished",
                        {
                            "cycle": int(self.cycle_count or 0),
                            "signals": int(len(signals) if signals else 0),
                            "quiet_reason": str(quiet_reason or ""),
                            "signal_diagnostics": str(signal_diagnostics or "") if signal_diagnostics is not None else None,
                            "data_fresh": bool(data_fresh),
                            "strategy_session_open": bool(strategy_session_open),
                            "futures_market_open": bool(futures_market_open),
                            "buffer_size": int(self.data_fetcher.get_buffer_size() or 0),
                            "error_count": int(self.error_count or 0),
                        },
                        level="info",
                    )
                except Exception:
                    pass

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
                try:
                    self.state_manager.append_event(
                        "error",
                        {"cycle": int(self.cycle_count or 0), "message": str(e)[:500]},
                        level="error",
                    )
                except Exception:
                    pass
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
                    try:
                        self.state_manager.append_event(
                            "circuit_breaker",
                            {
                                "cycle": int(self.cycle_count or 0),
                                "type": "consecutive_errors",
                                "consecutive_errors": int(self.consecutive_errors or 0),
                                "max_consecutive_errors": int(self.max_consecutive_errors or 0),
                            },
                            level="error",
                        )
                    except Exception:
                        pass
                    await self.notification_queue.enqueue_circuit_breaker(
                        "Too many consecutive errors",
                        {
                            "consecutive_errors": self.consecutive_errors,
                            "error_type": "general",
                            "action_taken": "Service paused",
                        },
                        priority=Priority.CRITICAL,
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
                        await self.notification_queue.enqueue_recovery(
                            {
                                "issue": "Consecutive errors resolved",
                                "recovery_time_seconds": 0,
                            },
                            priority=Priority.NORMAL,
                        )
                    except Exception as e:
                        logger.warning(f"Could not queue recovery notification: {e}")

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
            # ==========================================================================
            # TRADING CIRCUIT BREAKER: Check if signal should be allowed
            # ==========================================================================
            if self.trading_circuit_breaker is not None:
                # Get active positions for clustering check
                active_positions = []
                try:
                    recent_signals = self.state_manager.get_recent_signals(limit=100)
                    for rec in recent_signals:
                        if isinstance(rec, dict) and rec.get("status") == "entered":
                            active_positions.append(rec)
                except Exception:
                    pass
                
                # Get market data for volatility filter
                market_data = {}
                if buffer_data is not None and len(buffer_data) > 0:
                    try:
                        from pearlalgo.trading_bots.pearl_bot_auto import calculate_atr
                        atr_series = calculate_atr(buffer_data, period=14)
                        if len(atr_series) > 20:
                            atr_current = float(atr_series.iloc[-1])
                            atr_average = float(atr_series.iloc[-20:].mean())
                            market_data = {
                                "atr_current": atr_current,
                                "atr_average": atr_average,
                            }
                    except Exception:
                        pass
                
                # Check if signal should be allowed
                cb_decision = self.trading_circuit_breaker.should_allow_signal(
                    signal=signal,
                    active_positions=active_positions,
                    market_data=market_data,
                )
                
                if not cb_decision.allowed:
                    signal.setdefault("_risk_warnings", []).append(cb_decision.to_dict())

                    cb_mode = str(getattr(self.trading_circuit_breaker.config, "mode", "enforce"))
                    # MFFU eval gate rules ALWAYS enforce (even in warn_only mode)
                    is_mffu_block = str(cb_decision.reason or "").startswith("mffu_")
                    if cb_mode == "warn_only" and not is_mffu_block:
                        # Standard checks: warn only, don't block
                        signal["_cb_would_block"] = True
                        signal["_cb_would_block_reason"] = cb_decision.reason
                        self.trading_circuit_breaker.record_would_block(cb_decision.reason)
                        logger.warning(
                            f"⚠️ Trading circuit breaker would block (warn-only): {cb_decision.reason} | "
                            f"details={cb_decision.details}"
                        )
                        if cb_decision.severity == "critical":
                            asyncio.create_task(
                                self.notification_queue.enqueue_circuit_breaker(
                                    f"Risk warning (warn-only): {cb_decision.reason}",
                                    cb_decision.details,
                                    priority=Priority.HIGH,
                                )
                            )
                    else:
                        logger.warning(
                            f"🛑 Trading circuit breaker blocked signal: {cb_decision.reason} | "
                            f"details={cb_decision.details}"
                        )
                        # Notify via Telegram for critical blocks
                        if cb_decision.severity == "critical":
                            asyncio.create_task(
                                self.notification_queue.enqueue_circuit_breaker(
                                    f"Trading paused: {cb_decision.reason}",
                                    cb_decision.details,
                                    priority=Priority.HIGH,
                                )
                            )
                        return  # Skip this signal

            # ==========================================================================
            # ML FILTER (shadow): attach prediction for later analytics/lift measurement
            # NOTE: In shadow mode we NEVER block. We only record `_ml_prediction` on the signal.
            # ==========================================================================
            try:
                if self._ml_filter_enabled and self._ml_signal_filter is not None:
                    ctx: Dict[str, Any] = {}
                    # Best-effort regime mapping if available on signal
                    try:
                        mr = signal.get("market_regime") or {}
                        if isinstance(mr, dict):
                            regime_type = str(mr.get("regime") or "")
                            # bucket volatility if we only have ratio
                            vol_bucket = ""
                            try:
                                vr = mr.get("volatility_ratio")
                                if vr is not None:
                                    v = float(vr)
                                    if v < 0.8:
                                        vol_bucket = "low"
                                    elif v > 1.5:
                                        vol_bucket = "high"
                                    else:
                                        vol_bucket = "normal"
                            except Exception:
                                vol_bucket = ""
                            ctx["regime"] = {
                                "regime": regime_type,
                                "volatility": vol_bucket,
                                "session": str(mr.get("session") or ""),
                            }
                    except Exception:
                        ctx = {}

                    _should_exec, pred = self._ml_signal_filter.should_execute(signal, ctx)
                    try:
                        signal["_ml_prediction"] = pred.to_dict()
                        # Shadow-only note (helps audits; not used for gating).
                        # For lift measurement we can optionally use a separate shadow threshold
                        # so we get a meaningful PASS/FAIL split without affecting trading.
                        pass_for_lift = bool(_should_exec)
                        try:
                            if (
                                getattr(self, "_ml_filter_mode", "shadow") == "shadow"
                                and getattr(self, "_ml_shadow_threshold", None) is not None
                            ):
                                pass_for_lift = float(getattr(pred, "win_probability", 0.0) or 0.0) >= float(
                                    self._ml_shadow_threshold  # type: ignore[arg-type]
                                )
                                signal["_ml_shadow_threshold"] = float(self._ml_shadow_threshold)  # type: ignore[arg-type]
                        except Exception:
                            pass_for_lift = bool(_should_exec)
                        signal["_ml_shadow_pass_filter"] = bool(pass_for_lift)
                    except Exception:
                        signal["_ml_prediction"] = None
            except Exception as e:
                logger.debug(f"ML prediction failed (non-fatal): {e}")

            # ==========================================================================
            # ML OPPORTUNITY SIZING (shadow-safe): adjust size/priority within risk gates
            # ==========================================================================
            try:
                self._apply_ml_opportunity_sizing(signal)
            except Exception as e:
                logger.debug(f"ML sizing adjustment failed (non-fatal): {e}")
            
            # Track signal generation (delegates to state_manager for persistence)
            signal_id = self.performance_tracker.track_signal_generated(signal)
            self.last_signal_generated_at = get_utc_timestamp()
            self.last_signal_id_prefix = str(signal_id)[:16]

            # Virtual entry: enter immediately at the signal's entry price.
            # This enables per-signal PnL tracking without requiring IBKR fills.
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
            except Exception as e:
                logger.debug(f"Could not track virtual entry for {signal_id}: {e}")

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

            # Queue entry alert to Telegram (non-blocking)
            signal_type = signal.get('type', 'unknown')
            signal_direction = signal.get('direction', 'unknown')
            logger.info(f"Processing signal: {signal_type} {signal_direction}")

            # Always send entry notification as the canonical alert
            entry_priority = Priority.HIGH
            try:
                if bool(signal.get("_ml_priority") == "critical"):
                    entry_priority = Priority.CRITICAL
            except Exception:
                entry_priority = Priority.HIGH
            queued = await self.notification_queue.enqueue_entry(
                signal_id=str(signal_id),
                entry_price=float(entry_price),
                signal=signal,
                buffer_data=buffer_data,
                priority=entry_priority,
            )
            if queued:
                logger.info(f"✅ Entry queued for Telegram: {signal_type} {signal_direction}")
                self.signals_sent += 1
                self.last_signal_sent_at = get_utc_timestamp()
                self.last_signal_send_error = None
            else:
                logger.error(
                    f"❌ Failed to queue entry to Telegram (queue full): {signal_type} {signal_direction}. "
                    f"Telegram enabled: {self.telegram_notifier.enabled}, "
                    f"Telegram instance: {self.telegram_notifier.telegram is not None}"
                )
                self.signals_send_failures += 1
                self.last_signal_send_error = "Notification queue full - entry dropped"

            self.signal_count += 1

            # Entry notification is delivered via NotificationQueue when enabled, so it
            # inherits retry/backoff behavior and preserves consistent delivery ordering.

        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
            self.error_count += 1

    def _compute_base_position_size(self, signal: Dict) -> int:
        """Compute a base position size from config + signal confidence."""
        try:
            existing = signal.get("position_size")
            if existing is not None:
                return max(1, int(float(existing)))
        except Exception:
            pass

        cfg = self._strategy_settings or {}
        enable_dynamic = bool(cfg.get("enable_dynamic_sizing", False))
        base_contracts = int(cfg.get("base_contracts", 1) or 1)
        high_contracts = int(cfg.get("high_conf_contracts", base_contracts) or base_contracts)
        max_contracts = int(cfg.get("max_conf_contracts", high_contracts) or high_contracts)
        try:
            conf = float(signal.get("confidence") or 0.0)
        except Exception:
            conf = 0.0
        try:
            high_th = float(cfg.get("high_conf_threshold", 0.8) or 0.8)
        except Exception:
            high_th = 0.8
        try:
            max_th = float(cfg.get("max_conf_threshold", 0.9) or 0.9)
        except Exception:
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
        except Exception:
            pass

        # Clamp to risk min/max
        try:
            min_size = int(self._risk_settings.get("min_position_size", 1) or 1)
        except Exception:
            min_size = 1
        try:
            max_size = int(self._risk_settings.get("max_position_size", size) or size)
        except Exception:
            max_size = size

        size = max(min_size, min(max_size, size))
        return max(1, size)

    def _apply_ml_opportunity_sizing(self, signal: Dict) -> None:
        """Adjust size and priority based on ML opportunity signal."""
        if not getattr(self, "_ml_adjust_sizing", False):
            return

        pred = signal.get("_ml_prediction") or {}
        try:
            win_prob = float(pred.get("win_probability"))
        except Exception:
            return

        base_size = self._compute_base_position_size(signal)
        multiplier = (
            self._ml_size_multiplier_max
            if win_prob >= getattr(self, "_ml_size_threshold", 0.7)
            else self._ml_size_multiplier_min
        )
        try:
            adjusted = int(round(base_size * float(multiplier)))
        except Exception:
            adjusted = base_size

        # Clamp to risk min/max
        try:
            min_size = int(self._risk_settings.get("min_position_size", 1) or 1)
        except Exception:
            min_size = 1
        try:
            max_size = int(self._risk_settings.get("max_position_size", adjusted) or adjusted)
        except Exception:
            max_size = adjusted

        adjusted = max(min_size, min(max_size, adjusted))
        adjusted = max(1, adjusted)

        signal["position_size"] = adjusted
        signal["_ml_size_multiplier"] = float(multiplier)
        signal["_ml_size_adjusted"] = True

        if win_prob >= getattr(self, "_ml_size_threshold", 0.7):
            signal["_ml_priority"] = "critical"
        else:
            signal["_ml_priority"] = "high"

        if adjusted != base_size:
            logger.info(
                f"ML sizing adjusted position size: {base_size} -> {adjusted} "
                f"(p={win_prob:.2f}, mult={multiplier:.2f})"
            )

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
                        
                        # Record trade with trading circuit breaker (risk management)
                        if self.trading_circuit_breaker is not None:
                            try:
                                self.trading_circuit_breaker.record_trade_result({
                                    "is_win": is_win,
                                    "pnl": pnl_value,
                                    "exit_time": exit_bar_ts.isoformat() if exit_bar_ts else None,
                                    "exit_reason": exit_reason,
                                })
                            except Exception as cb_err:
                                logger.debug(f"Could not record circuit breaker trade: {cb_err}")
                            
                            # Shadow outcome: track whether this was a would-block signal
                            try:
                                was_would_block = bool(sig.get("_cb_would_block", False))
                                self.trading_circuit_breaker.record_shadow_outcome(
                                    pnl=pnl_value,
                                    is_win=is_win,
                                    was_would_block=was_would_block,
                                )
                            except Exception as shadow_err:
                                logger.debug(f"Could not record shadow outcome: {shadow_err}")
                        
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
                                    # Send Telegram alert for pass/fail (fire-and-forget via queue)
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
                                                self.notification_queue.enqueue_raw_message(
                                                    msg, parse_mode="Markdown", dedupe=False,
                                                    priority=Priority.HIGH, tier=NotificationTier.CRITICAL,
                                                )
                                            )
                                        except Exception as tg_err:
                                            logger.debug(f"Could not queue challenge alert: {tg_err}")
                            except Exception as challenge_err:
                                logger.debug(f"Could not record challenge trade: {challenge_err}")

                        # Record trade with MFFU evaluation tracker (prop firm rules)
                        if self._mffu_tracker is not None:
                            try:
                                from datetime import date as _date_cls
                                trade_date_str = _date_cls.today().isoformat()
                                mffu_result = self._mffu_tracker.record_trade(
                                    pnl=pnl_value,
                                    is_win=is_win,
                                    trade_date=trade_date_str,
                                )
                                if mffu_result.get("triggered"):
                                    mffu_outcome = mffu_result.get("outcome", "")
                                    mffu_attempt = mffu_result.get("attempt", {})
                                    logger.info(
                                        f"MFFU attempt #{mffu_attempt.get('attempt_id', 0)} ended: "
                                        f"{mffu_outcome.upper()} | PnL: ${mffu_attempt.get('pnl', 0):.2f}"
                                    )
                                    # On FAIL: flatten all positions immediately
                                    if mffu_outcome == "fail" and self.execution_adapter is not None:
                                        try:
                                            self.execution_adapter.disarm()
                                            asyncio.create_task(
                                                self.execution_adapter.flatten_all_positions()
                                            )
                                            logger.warning("MFFU FAIL: execution disarmed + positions flattened")
                                        except Exception:
                                            pass
                            except Exception as mffu_err:
                                logger.debug(f"Could not record MFFU trade: {mffu_err}")
                        
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
                            virtual_pnl_enabled = bool(getattr(self.config, "virtual_pnl_enabled", True))
                            virtual_pnl_notify_exit = bool(getattr(self.config, "virtual_pnl_notify_exit", False))
                            
                            # Check if Telegram notifier is available and enabled
                            notifier_available = (
                                self.telegram_notifier is not None
                                and self.telegram_notifier.enabled
                                and self.telegram_notifier.telegram is not None
                            )
                            
                            if virtual_pnl_enabled and virtual_pnl_notify_exit and notifier_available:
                                hold_mins = perf.get("hold_duration_minutes")
                                try:
                                    hold_mins = float(hold_mins) if hold_mins is not None else None
                                except Exception:
                                    hold_mins = None

                                logger.info(
                                    f"📤 Queuing exit notification for {sig_id[:16]}: "
                                    f"exit={exit_price:.2f} | reason={exit_reason} | pnl=${pnl_value:.2f}"
                                )
                                
                                # Queue exit notification (fire-and-forget via queue)
                                asyncio.create_task(
                                    self.notification_queue.enqueue_exit(
                                        signal_id=str(sig_id),
                                        exit_price=float(exit_price),
                                        exit_reason=str(exit_reason),
                                        pnl=float(pnl_value),
                                        signal=sig,
                                        hold_duration_minutes=hold_mins,
                                        buffer_data=df,
                                        priority=Priority.HIGH,
                                    )
                                )
                            else:
                                if not virtual_pnl_enabled:
                                    logger.debug(f"Exit notification skipped for {sig_id[:16]}: virtual_pnl_enabled=False")
                                elif not virtual_pnl_notify_exit:
                                    logger.debug(f"Exit notification skipped for {sig_id[:16]}: virtual_pnl_notify_exit=False")
                                elif not notifier_available:
                                    logger.warning(
                                        f"Exit notification skipped for {sig_id[:16]}: Telegram notifier not available "
                                        f"(enabled={self.telegram_notifier.enabled if self.telegram_notifier else 'N/A'}, "
                                        f"telegram={self.telegram_notifier.telegram is not None if self.telegram_notifier else 'N/A'})"
                                    )
                        except Exception as e:
                            logger.error(
                                f"Could not schedule exit notification for {sig_id[:16]}: {e}",
                                exc_info=True
                            )
                        
                        # ==========================================================================
                        # STREAK ALERT - notify on 3+ consecutive wins or losses
                        # ==========================================================================
                        try:
                            # Update streak tracking
                            if is_win:
                                if self._streak_type == 'win':
                                    self._streak_count += 1
                                else:
                                    # Streak type changed - reset alert tracking
                                    self._streak_type = 'win'
                                    self._streak_count = 1
                                    self._last_streak_alert_count = 0
                            else:
                                if self._streak_type == 'loss':
                                    self._streak_count += 1
                                else:
                                    # Streak type changed - reset alert tracking
                                    self._streak_type = 'loss'
                                    self._streak_count = 1
                                    self._last_streak_alert_count = 0
                            
                            # Send alert when streak reaches threshold (and only once per new streak level)
                            if (self._streak_count >= self._streak_alert_threshold 
                                and self._streak_count > self._last_streak_alert_count
                                and self.telegram_notifier 
                                and self.telegram_notifier.enabled):
                                
                                self._last_streak_alert_count = self._streak_count
                                
                                if self._streak_type == 'win':
                                    emoji = "🔥"
                                    msg = f"{emoji} *{self._streak_count} Win Streak!*\n\n"
                                    msg += "You're on fire! Consider:\n"
                                    msg += "• Locking in profits\n"
                                    msg += "• Staying disciplined"
                                else:
                                    emoji = "❄️"
                                    msg = f"{emoji} *{self._streak_count} Loss Streak*\n\n"
                                    msg += "Consider taking a break.\n"
                                    msg += "Circuit breaker is monitoring."
                                
                                asyncio.create_task(
                                    self.notification_queue.enqueue_raw_message(
                                        msg, parse_mode="Markdown", dedupe=False, priority=Priority.MEDIUM
                                    )
                                )
                                logger.info(f"Streak alert sent: {self._streak_type} x{self._streak_count}")
                        except Exception as streak_err:
                            logger.debug(f"Could not send streak alert: {streak_err}")
            except Exception:
                continue

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
        except Exception:
            pass
            
        # Get performance stats
        daily_pnl = 0.0
        wins_today = 0
        losses_today = 0
        try:
            perf = self.performance_tracker.get_daily_performance()
            daily_pnl = perf.get("total_pnl", 0.0)
            wins_today = perf.get("wins", 0)
            losses_today = perf.get("losses", 0)
        except Exception:
            pass
            
        # Get market status
        futures_open = False
        session_open = False
        try:
            futures_open = bool(get_market_hours().is_market_open())
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            session_open = check_trading_session(datetime.now(timezone.utc), self.config)
        except Exception:
            pass

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
        except Exception:
            pass

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
                        except Exception:
                            due = True
                    if due:
                        review = self._build_pearl_review_message(state)
                        if review:
                            await self.telegram_notifier.send_pearl_notification(review, message_type="Check-In")
                            try:
                                prefs_obj.set("pearl_review_last_sent_at", datetime.now(timezone.utc).isoformat())
                            except Exception:
                                pass
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

    @staticmethod
    def _escape_markdown_v2(text: str) -> str:
        """Escape special characters for MarkdownV2."""
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        result = ""
        for char in text:
            if char in escape_chars:
                result += f"\\{char}"
            else:
                result += char
        return result

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
                perf_file = self.state_manager.state_dir / "performance.json"
                if perf_file.exists():
                    perf_trades = json.loads(perf_file.read_text(encoding="utf-8"))
                    if not isinstance(perf_trades, list):
                        perf_trades = []
                    
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
                    except Exception:
                        pass
                    
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
                            except Exception:
                                pass
            except Exception:
                pass
            
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
            pnl_sign = "+" if daily_pnl >= 0 else "-"
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
                pnl_line = f"{pnl_icon} Today: {pnl_sign}${abs(daily_pnl):,.2f} ({trades_today} {trades_word}, {wr_today:.0f}% WR)"
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
        except Exception:
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
        except Exception:
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

        # Canonical dashboard: one message (visual when chart is available).
        if chart_due:
            chart_path = None
            try:
                # Bound chart generation time so the service loop cannot stall indefinitely.
                chart_path = await asyncio.wait_for(self._generate_dashboard_chart(), timeout=30.0)
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
            except Exception:
                pass
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
        """
        Capture the Live Main Chart and export it for Telegram/UI use.

        This produces (atomically) a PNG at:
          `data/agent_state/<MARKET>/exports/dashboard_telegram_latest.png`
        """
        import os

        exports_dir = self.state_manager.state_dir / "exports"
        try:
            exports_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        export_path = exports_dir / "dashboard_telegram_latest.png"
        chart_url = os.getenv("PEARL_LIVE_CHART_URL", "http://localhost:3001")

        try:
            captured = await capture_live_chart_screenshot(output_path=export_path, url=str(chart_url))
            if captured and captured.exists():
                return captured
        except Exception as e:
            logger.debug(f"Could not capture live chart screenshot: {e}")

        # Fallback: return whatever exists on disk (may be stale) for resiliency.
        return export_path if export_path.exists() else None

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
            
            await self.notification_queue.enqueue_dashboard(status, chart_path=chart_path, priority=Priority.LOW)
        except Exception as e:
            logger.error(f"Error queuing dashboard: {e}", exc_info=True)
    
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
        Build a compact list of recent **completed** trades within the chart window.

        Used to overlay trade history markers on the periodic dashboard chart.
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
                if status not in ("exited",):
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
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            session_open = check_trading_session(bar_time, self.config) if bar_time else False
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
                await self.notification_queue.enqueue_risk_warning(
                    f"{title}\n\n{message}",
                    risk_status="ERROR",
                    priority=Priority.CRITICAL,
                )
        except Exception as e:
            logger.error(f"Error queuing error notification: {e}")

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

        # Use 6pm ET as the trading day boundary
        today = get_trading_day_date()

        if self._last_trading_day is None:
            # First cycle - initialize but don't reset (may be mid-day startup)
            self._last_trading_day = today
            return

        if self._last_trading_day != today:
            # New trading day (6pm ET boundary crossed) - reset counters
            self.execution_adapter.reset_daily_counters()
            logger.info(
                f"Execution daily counters reset for {today} "
                f"(previous day: {self._last_trading_day}) - 6pm ET boundary"
            )
            self._last_trading_day = today

    async def _check_morning_briefing(self) -> None:
        """
        Send morning briefing at 6:30 AM ET.

        Automatically sends once per day with:
        - Overnight session recap (if any trades)
        - Current P&L status
        - Key price levels
        - Market sentiment snapshot
        """
        if not self.telegram_notifier or not self.telegram_notifier.enabled:
            return

        try:
            # Check if AI briefings are enabled in config
            service_config = load_service_config()
            briefing_config = service_config.get("ai_briefings", {})
            if not briefing_config.get("enabled", True):
                return

            # Get configured time (default 6:30 AM ET)
            morning_time_str = str(briefing_config.get("morning_time", "06:30"))
            try:
                morning_hour, morning_minute = map(int, morning_time_str.split(":"))
            except Exception:
                morning_hour, morning_minute = 6, 30

            # Get current time in ET
            now_utc = datetime.now(timezone.utc)
            try:
                et_tz = ZoneInfo("America/New_York")
                now_et = now_utc.astimezone(et_tz)
            except Exception:
                from datetime import timedelta
                now_et = now_utc - timedelta(hours=5)

            et_hour = now_et.hour
            et_minute = now_et.minute
            today_str = now_et.strftime("%Y-%m-%d")

            # Check if already sent today
            if self._morning_briefing_sent_date == today_str:
                return

            # Send in a 10-minute window around configured time
            if not (et_hour == morning_hour and morning_minute <= et_minute <= morning_minute + 10):
                return

            # Mark as sent for today
            self._morning_briefing_sent_date = today_str

            # Gather overnight/previous session data
            perf_file = self.performance_tracker.performance_file
            overnight_trades = []
            if perf_file.exists():
                try:
                    perf_data = json.loads(perf_file.read_text(encoding="utf-8"))
                    if isinstance(perf_data, list):
                        trades = perf_data
                    elif isinstance(perf_data, dict):
                        trades = perf_data.get("trades", []) or []
                    else:
                        trades = []

                    # Filter overnight trades (6 PM yesterday to 6:30 AM today)
                    yesterday = (now_et - timedelta(days=1)).strftime("%Y-%m-%d")
                    for t in trades:
                        exit_time = t.get("exit_time", "")
                        if exit_time:
                            # Check if trade was overnight session
                            if exit_time[:10] == today_str or exit_time[:10] == yesterday:
                                overnight_trades.append(t)
                except Exception:
                    pass

            # Get current state for P&L
            state = self.state_manager.load_state()
            daily_pnl = float(state.get("daily_pnl", 0) or 0)
            session_pnl = float(state.get("session_pnl", 0) or 0)

            # Build briefing message
            day_name = now_et.strftime("%A")
            date_str = now_et.strftime("%b %d")

            msg_parts = [f"Good morning! {day_name}, {date_str}"]

            # Overnight recap
            if overnight_trades:
                overnight_pnl = sum(t.get("pnl", 0) for t in overnight_trades)
                overnight_wins = sum(1 for t in overnight_trades if t.get("is_win"))
                overnight_losses = len(overnight_trades) - overnight_wins
                pnl_sign = "+" if overnight_pnl >= 0 else ""
                msg_parts.append(
                    f"Overnight: {len(overnight_trades)} trades ({overnight_wins}W/{overnight_losses}L), {pnl_sign}${overnight_pnl:.0f}"
                )
            else:
                msg_parts.append("Overnight: No trades")

            # Current P&L status
            if daily_pnl != 0 or session_pnl != 0:
                pnl_to_show = daily_pnl if daily_pnl != 0 else session_pnl
                pnl_sign = "+" if pnl_to_show >= 0 else ""
                pnl_emoji = "green" if pnl_to_show >= 0 else "red"
                msg_parts.append(f"Session P&L: {pnl_sign}${pnl_to_show:.0f}")

            # Try to add AI-generated insight
            try:
                from pearlalgo.ai.chat import get_ai_chat

                ai_config = service_config.get("ai_chat", {})
                ai_chat = get_ai_chat(config=ai_config)
                if ai_chat.enabled:
                    context = {
                        "daily_pnl": daily_pnl,
                        "session_pnl": session_pnl,
                        "overnight_trades": len(overnight_trades),
                        "recent_trades": [
                            {"pnl": t.get("pnl", 0), "direction": t.get("direction", "")}
                            for t in overnight_trades[-5:]
                        ],
                    }
                    insight = await ai_chat.generate_insight("morning_briefing", context)
                    if insight:
                        msg_parts.append(f"\n{insight}")
            except Exception as e:
                logger.debug(f"Could not generate morning AI insight: {e}")

            msg = "\n".join(msg_parts)

            asyncio.create_task(
                self.notification_queue.enqueue_raw_message(
                    msg, parse_mode=None, dedupe=False, priority=Priority.MEDIUM
                )
            )
            logger.info(f"Morning briefing sent for {today_str}")

        except Exception as e:
            logger.debug(f"Could not send morning briefing: {e}")

    async def _check_market_close_summary(self) -> None:
        """
        Send daily performance summary at safety close (3:55 PM ET).
        
        Automatically sends once per day when the time hits 3:55-4:05 PM ET.
        """
        if not self.telegram_notifier or not self.telegram_notifier.enabled:
            return
        
        try:
            # Get current time in ET
            now_utc = datetime.now(timezone.utc)
            try:
                import pytz
                et_tz = pytz.timezone("US/Eastern")
                now_et = now_utc.astimezone(et_tz)
            except Exception:
                # Fallback: UTC-5 approximation
                from datetime import timedelta
                now_et = now_utc - timedelta(hours=5)
            
            et_hour = now_et.hour
            et_minute = now_et.minute
            today_str = now_et.strftime("%Y-%m-%d")
            
            # Check if already sent today
            if self._daily_summary_sent_date == today_str:
                return
            
            # Send between 3:55 PM and 4:05 PM ET (safety close window)
            if not ((et_hour == 15 and et_minute >= 55) or (et_hour == 16 and et_minute <= 5)):
                return
            
            # Mark as sent for today
            self._daily_summary_sent_date = today_str
            
            # Gather today's performance data
            perf_file = self.performance_tracker.performance_file
            if not perf_file.exists():
                return
            
            perf_data = json.loads(perf_file.read_text(encoding="utf-8"))
            # performance.json is a list of trade records (backward compatible).
            if isinstance(perf_data, list):
                trades = perf_data
            elif isinstance(perf_data, dict):
                trades = perf_data.get("trades", []) or []
            else:
                trades = []
            
            # Filter today's trades
            today_trades = [
                t for t in trades 
                if t.get("exit_time", "")[:10] == today_str
            ]
            
            if not today_trades:
                # No trades today - send brief note
                msg = (
                    f"📊 *Daily Summary* • {now_et.strftime('%b %d')}\n\n"
                    "No trades today.\n"
                    "_Session safety close at 3:55 PM ET_"
                )
            else:
                # Calculate metrics
                total_pnl = sum(t.get("pnl", 0) for t in today_trades)
                wins = sum(1 for t in today_trades if t.get("is_win"))
                losses = len(today_trades) - wins
                win_rate = (wins / len(today_trades) * 100) if today_trades else 0
                
                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                pnl_sign = "+" if total_pnl >= 0 else ""

                # Analyze what worked vs didn't
                long_trades = [t for t in today_trades if t.get("direction", "").lower() == "long"]
                short_trades = [t for t in today_trades if t.get("direction", "").lower() == "short"]
                long_pnl = sum(t.get("pnl", 0) for t in long_trades)
                short_pnl = sum(t.get("pnl", 0) for t in short_trades)

                msg_parts = [
                    f"📊 *Daily Summary* • {now_et.strftime('%b %d')}\n",
                    f"{pnl_emoji} *P&L:* {pnl_sign}${total_pnl:,.2f}",
                    f"📈 *Trades:* {len(today_trades)} ({wins}W/{losses}L)",
                    f"🎯 *Win Rate:* {win_rate:.0f}%",
                ]

                # Add direction breakdown if both directions traded
                if long_trades and short_trades:
                    long_sign = "+" if long_pnl >= 0 else ""
                    short_sign = "+" if short_pnl >= 0 else ""
                    msg_parts.append(
                        f"↗️ Longs: {long_sign}${long_pnl:.0f} • ↘️ Shorts: {short_sign}${short_pnl:.0f}"
                    )

                # Try to add AI-generated insight
                try:
                    service_config = load_service_config()
                    briefing_config = service_config.get("ai_briefings", {})
                    if briefing_config.get("enabled", True):
                        from pearlalgo.ai.chat import get_ai_chat

                        ai_config = service_config.get("ai_chat", {})
                        ai_chat = get_ai_chat(config=ai_config)
                        if ai_chat.enabled:
                            context = {
                                "daily_pnl": total_pnl,
                                "wins_today": wins,
                                "losses_today": losses,
                                "win_rate": win_rate,
                                "long_pnl": long_pnl,
                                "short_pnl": short_pnl,
                                "recent_trades": [
                                    {
                                        "pnl": t.get("pnl", 0),
                                        "direction": t.get("direction", ""),
                                        "type": t.get("type", ""),
                                        "is_win": t.get("is_win", False),
                                    }
                                    for t in today_trades
                                ],
                            }
                            insight = await ai_chat.generate_insight("eod_summary", context)
                            if insight:
                                msg_parts.append(f"\n💡 {insight}")
                except Exception as e:
                    logger.debug(f"Could not generate EOD AI insight: {e}")

                msg_parts.append("\n_Session safety close at 3:55 PM ET_")
                msg = "\n".join(msg_parts)

            asyncio.create_task(
                self.notification_queue.enqueue_raw_message(
                    msg, parse_mode="Markdown", dedupe=False, priority=Priority.MEDIUM
                )
            )
            logger.info(f"Daily summary sent for {today_str}")
            
        except Exception as e:
            logger.debug(f"Could not send daily summary: {e}")

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
                
                # Send Telegram alert (through notification queue)
                try:
                    await self.notification_queue.enqueue_raw_message(
                        message,
                        parse_mode="Markdown",
                        priority=Priority.NORMAL,
                    )
                except Exception as e:
                    logger.error(f"Failed to queue connection alert: {e}")
            
            # Update state
            self._execution_was_connected = is_connected

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
            except Exception:
                # If we can't determine age, treat as stale for safety
                return True
        
        try:
            state_dir = self.state_manager.state_dir

            # ==========================================================================
            # Process operator requests (web UI feedback, shadow-only)
            # ==========================================================================
            try:
                await self._process_operator_requests(state_dir)
            except Exception as e:
                logger.debug(f"Operator requests processing failed (non-fatal): {e}")
            
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
                        closed_virtual = await self._close_all_virtual_trades(
                            market_data=last_market_data,
                            reason="kill_switch",
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
                    except Exception:
                        pass

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
                        except Exception:
                            pass
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
                    except Exception:
                        pass
                finally:
                    kill_file.unlink(missing_ok=True)
                    # Also remove any pending disarm flag (kill already disarms)
                    disarm_file.unlink(missing_ok=True)

                # Close all virtual trades (best-effort; uses last known market data)
                try:
                    closed_virtual = await self._close_all_virtual_trades(
                        market_data=last_market_data,
                        reason="kill_switch",
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
                
                # Notify via Telegram (through notification queue)
                try:
                    await self.notification_queue.enqueue_raw_message(
                        "🔒 *Execution DISARMED*\n\n"
                        "No new orders will be placed.",
                        parse_mode="Markdown",
                        priority=Priority.HIGH,
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
                    except Exception:
                        pass
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
            
            # Notify via Telegram (through notification queue)
            try:
                if applied:
                    await self.notification_queue.enqueue_raw_message(
                        f"✅ *Grade Applied*\n\n"
                        f"Signal: `{signal_id[:25]}...`\n"
                        f"Type: `{signal_type}`\n"
                        f"Outcome: {'Win' if is_win else 'Loss'}\n"
                        f"Applied to learning policy.",
                        parse_mode="Markdown",
                        priority=Priority.NORMAL,
                    )
                else:
                    await self.notification_queue.enqueue_raw_message(
                        f"ℹ️ *Grade Logged*\n\n"
                        f"Signal: `{signal_id[:25]}...`\n"
                        f"Already exited - feedback logged but not applied.\n"
                        f"_Use `force` to override._",
                        parse_mode="Markdown",
                        priority=Priority.NORMAL,
                    )
            except Exception:
                pass
            
        except Exception as e:
            logger.error(f"Error processing grade request: {e}", exc_info=True)
        finally:
            # Always clean up the request file
            grade_file.unlink(missing_ok=True)

    async def _process_operator_requests(self, state_dir: Path) -> None:
        """
        Process operator request files written by the web API server.

        This is intentionally **shadow-only** feedback collection and MUST NOT
        affect live trading decisions.

        Currently supported request types:
        - pearl_suggestion_feedback_*.json: Accept/dismiss the active Pearl suggestion
          (updates `PearlShadowTracker` metrics).
        """
        req_dir = Path(state_dir) / "operator_requests"
        if not req_dir.exists():
            return

        try:
            files = sorted([p for p in req_dir.glob("pearl_suggestion_feedback_*.json") if p.is_file()])
        except Exception:
            return

        if not files:
            return

        # Build a lightweight context snapshot for resolution metrics.
        snap = {}
        try:
            snap = self._get_status_snapshot() or {}
        except Exception:
            snap = {}

        shadow_context = {
            "daily_pnl": snap.get("daily_pnl", 0),
            "wins_today": snap.get("wins_today", 0),
            "losses_today": snap.get("losses_today", 0),
            "active_positions": snap.get("active_trades_count", 0) or 0,
        }

        for fp in files[:50]:
            try:
                raw = fp.read_text(encoding="utf-8")
                rec = json.loads(raw) if raw else {}
                if not isinstance(rec, dict):
                    continue

                if str(rec.get("type") or "") != "pearl_suggestion_feedback":
                    continue

                action = str(rec.get("action") or "").strip().lower()
                suggestion_id = str(rec.get("suggestion_id") or "").strip()
                if not action or not suggestion_id:
                    continue

                if action == "accept":
                    self.shadow_tracker.mark_followed(suggestion_id, shadow_context)
                    logger.info(f"[Pearl] Suggestion accepted (shadow): {suggestion_id}")
                elif action == "dismiss":
                    self.shadow_tracker.mark_dismissed(suggestion_id, shadow_context)
                    logger.info(f"[Pearl] Suggestion dismissed (shadow): {suggestion_id}")
                else:
                    logger.warning(f"[Pearl] Unknown suggestion feedback action: {action}")
            except Exception as e:
                logger.warning(f"[Pearl] Failed to process operator request {fp.name}: {e}")
            finally:
                # Always remove requests (prevents double-processing on restart).
                try:
                    fp.unlink(missing_ok=True)
                except Exception:
                    pass

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
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            strategy_session_open = check_trading_session(datetime.now(timezone.utc), self.config)
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
            # ML filter operational status (shadow/live + lift gating)
            "ml_filter": {
                "enabled": bool(getattr(self, "_ml_filter_enabled", False)),
                "mode": getattr(self, "_ml_filter_mode", "shadow"),
                "trained": bool(getattr(getattr(self, "_ml_signal_filter", None), "is_ready", False)),
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

    def _build_ml_training_trades_from_signals(self, *, limit: int = 2000) -> list[dict]:
        """
        Build supervised training samples from `signals.jsonl`.

        This is intentionally lightweight and uses only data already persisted with each signal,
        so it does not add runtime overhead to the scan loop.
        """
        try:
            lim = max(1, int(limit or 2000))
        except Exception:
            lim = 2000

        try:
            path = getattr(self.state_manager, "signals_file", None)
            if not path:
                return []
            if not Path(path).exists():
                return []
        except Exception:
            return []

        # Stop-loss ATR multiplier used to derive ATR from stop distance (best-effort).
        try:
            stop_mult = float(self.config.get("stop_loss_atr_mult", 3.5) or 3.5)
            if stop_mult <= 0:
                stop_mult = 3.5
        except Exception:
            stop_mult = 3.5

        samples = deque(maxlen=lim)
        try:
            with open(str(path), "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if str(rec.get("status") or "").lower() != "exited":
                        continue

                    # Label
                    if "is_win" in rec:
                        is_win = bool(rec.get("is_win"))
                    else:
                        outcome = str(rec.get("outcome") or "").lower()
                        if outcome not in ("win", "loss"):
                            continue
                        is_win = outcome == "win"

                    sig = rec.get("signal") or {}
                    if not isinstance(sig, dict):
                        sig = {}

                    # Core features we can reliably reconstruct
                    try:
                        confidence = float(sig.get("confidence") or 0.0)
                    except Exception:
                        confidence = 0.0
                    try:
                        rr = float(sig.get("risk_reward") or 0.0)
                    except Exception:
                        rr = 0.0

                    # Derive ATR from stop distance (best-effort; consistent with how stops are constructed).
                    atr_val = 0.0
                    try:
                        entry = float(sig.get("entry_price") or rec.get("entry_price") or 0.0)
                        stop = float(sig.get("stop_loss") or 0.0)
                        if entry > 0 and stop > 0 and stop_mult > 0:
                            atr_val = abs(entry - stop) / stop_mult
                    except Exception:
                        atr_val = 0.0

                    # Volatility ratio (if present via market_regime); else neutral.
                    vol_ratio = 1.0
                    try:
                        mr = sig.get("market_regime") or {}
                        if isinstance(mr, dict) and mr.get("volatility_ratio") is not None:
                            vol_ratio = float(mr.get("volatility_ratio") or 1.0)
                    except Exception:
                        vol_ratio = 1.0

                    # Optional regime dict (used for one-hot context features in MLSignalFilter)
                    regime_dict: Dict[str, Any] = {}
                    try:
                        mr = sig.get("market_regime") or {}
                        if isinstance(mr, dict):
                            regime_type = str(mr.get("regime") or "")
                            regime_dict["regime"] = regime_type
                            # Bucket volatility from ratio
                            vb = "normal"
                            try:
                                if float(vol_ratio) < 0.8:
                                    vb = "low"
                                elif float(vol_ratio) > 1.5:
                                    vb = "high"
                            except Exception:
                                vb = "normal"
                            regime_dict["volatility"] = vb
                            regime_dict["session"] = str(mr.get("session") or "")
                    except Exception:
                        regime_dict = {}

                    sample = {
                        "signal_type": str(rec.get("signal_type") or sig.get("type") or "unknown"),
                        "is_win": bool(is_win),
                        "exit_time": str(rec.get("exit_time") or rec.get("timestamp") or ""),
                        # MLSignalFilter expected features
                        "confidence": float(confidence),
                        "risk_reward": float(rr),
                        "atr": float(atr_val),
                        "volatility_ratio": float(vol_ratio),
                        "volume_ratio": 1.0,       # not persisted today; neutral
                        "rsi": 0.0,                # not persisted today; neutral
                        "macd_histogram": 0.0,     # not persisted today; neutral
                        "bb_position": 0.0,        # not persisted today; neutral
                        "vwap_distance": 0.0,      # not persisted today; neutral
                    }
                    if regime_dict:
                        sample["regime"] = regime_dict

                    samples.append(sample)
        except Exception:
            return []

        return list(samples)

    def _compute_ml_lift_metrics(self, trades: list) -> Dict[str, Any]:
        """
        Compute shadow A/B lift for ML gating:
        Compare outcomes for trades where ML would PASS vs would BLOCK.

        Expects trade dicts from TradeDatabase.get_recent_trades_by_exit(), including:
        - is_win (bool)
        - pnl (float)
        - features.ml_win_probability (float) OR features.ml_pass_filter (0/1)
        - features.ml_pass_threshold (float, optional)
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
            has_prob = ("ml_win_probability" in feats) and (feats.get("ml_win_probability") is not None)
            has_flag = "ml_pass_filter" in feats
            if not (has_prob or has_flag):
                continue
            # If model wasn't ready, ML filter is in neutral fallback (no gating signal).
            try:
                if float(feats.get("ml_fallback_used", 0.0) or 0.0) >= 0.5:
                    continue
            except Exception:
                pass
            scored.append(t)

        total_scored = len(scored)
        # Determine pass/fail groups.
        # Prefer probability-based thresholding (shadow_threshold / stored ml_pass_threshold) so we
        # can create a meaningful split even if historical trades were written before that feature.
        pass_group: list = []
        fail_group: list = []
        threshold_used: Optional[float] = None
        for t in scored:
            feats = t.get("features", {}) or {}

            # Determine the threshold for this trade (prefer stored threshold, else current shadow threshold).
            thr = None
            try:
                if feats.get("ml_pass_threshold") is not None:
                    thr = float(feats.get("ml_pass_threshold") or 0.0)
            except Exception:
                thr = None
            if thr is None:
                try:
                    st = getattr(self, "_ml_shadow_threshold", None)
                    if getattr(self, "_ml_filter_mode", "shadow") == "shadow" and st is not None:
                        thr = float(st)
                except Exception:
                    thr = None

            pass_flag = True
            if thr is not None:
                threshold_used = float(thr)
                try:
                    p = float(feats.get("ml_win_probability", 0.0) or 0.0)
                    pass_flag = p >= float(thr)
                except Exception:
                    pass_flag = True
            else:
                # Fallback to stored boolean flag if probability/threshold missing.
                try:
                    pass_flag = float(feats.get("ml_pass_filter", 1.0) or 0.0) >= 0.5
                except Exception:
                    pass_flag = True

            if pass_flag:
                pass_group.append(t)
            else:
                fail_group.append(t)

        if total_scored < int(getattr(self, "_ml_lift_min_trades", 50) or 50):
            # Provide pass/fail split even before reaching min_trades so operators can
            # verify that lift measurement is actually meaningful (i.e. we have both groups).
            out = {
                "status": "insufficient_data",
                "scored_trades": total_scored,
                "min_trades": int(getattr(self, "_ml_lift_min_trades", 50) or 50),
                "pass_trades": int(len(pass_group)),
                "fail_trades": int(len(fail_group)),
                "lift_ok": False,
                "blocking_allowed": False,
            }
            if threshold_used is not None:
                out["pass_threshold_used"] = float(threshold_used)
            return out

        if not pass_group or not fail_group:
            out = {
                "status": "no_split",
                "scored_trades": total_scored,
                "pass_trades": len(pass_group),
                "fail_trades": len(fail_group),
                "lift_ok": False,
                "blocking_allowed": False,
                "reason": "Need both pass+fail groups to measure lift",
            }
            if threshold_used is not None:
                out["pass_threshold_used"] = float(threshold_used)
            return out

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
            "pass_threshold_used": float(threshold_used) if threshold_used is not None else None,
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
                except Exception:
                    pass
        return default

    def _get_active_virtual_trades(self, *, limit: int = 300) -> list[dict]:
        """Return active virtual trades (signals.jsonl status=entered)."""
        try:
            recent_signals = self.state_manager.get_recent_signals(limit=limit)
        except Exception:
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
            except Exception:
                latest_bar = None
        if not isinstance(latest_bar, dict):
            return {"close": None, "bid": None, "ask": None, "source": None}

        def _f(v: Any) -> Optional[float]:
            try:
                out = float(v)
                return out if out > 0 else None
            except Exception:
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
        except Exception:
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

        # MFFU Evaluation: auto-flatten at 4:08 PM ET (2 min before 4:10 session close)
        if self._mffu_enabled and self._mffu_tracker is not None:
            if local_now.time() >= time(16, 8) and local_now.time() < time(16, 11):
                if self._auto_flat_last_dates.get("mffu_session_close") != local_now.date():
                    return "mffu_session_close"

        return None

    async def _close_all_virtual_trades(self, *, market_data: Dict, reason: str) -> int:
        """Force-close all virtual trades (status=entered) using latest price."""
        if not getattr(self.config, "virtual_pnl_enabled", True):
            logger.warning("Auto/close-all requested but virtual PnL is disabled")
            return 0

        active = self._get_active_virtual_trades(limit=500)
        if not active:
            return 0

        prices = self._resolve_latest_prices(market_data)
        close_px = prices.get("close")
        if close_px is None:
            logger.warning("Close-all requested but no valid latest price available")
            return 0

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
                except Exception:
                    pass

        # Best-effort: update state immediately so the dashboard doesn't show stale active count.
        try:
            state = self.state_manager.load_state() if self.state_manager else {}
            if isinstance(state, dict):
                state["active_trades_count"] = 0
                state["active_trades_unrealized_pnl"] = 0.0
                self.state_manager.save_state(state)
        except Exception:
            pass

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
        except Exception:
            pass

        if self._auto_flat_notify and self.telegram_notifier.enabled:
            try:
                msg = (
                    f"🚫 *Close All Trades Executed*\n\n"
                    f"Reason: `{reason}`\n"
                    f"Closed: `{closed_count}`\n"
                    f"Total P&L: `${total_pnl:,.2f}`"
                )
                await self.notification_queue.enqueue_raw_message(
                    msg, parse_mode="Markdown", dedupe=False,
                    priority=Priority.HIGH, tier=NotificationTier.CRITICAL,
                )
            except Exception:
                pass

        return closed_count

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
                except Exception:
                    pass

        if closed_ids:
            logger.info(f"Closed {len(closed_ids)} specific positions: {closed_ids}, P&L: ${total_pnl:.2f}")

            # Best-effort: update active trades count in state
            try:
                remaining_active = len(active) - len(closed_ids)
                state = self.state_manager.load_state() if self.state_manager else {}
                if isinstance(state, dict):
                    state["active_trades_count"] = max(0, remaining_active)
                    self.state_manager.save_state(state)
            except Exception:
                pass

        return closed_ids

    def _clear_close_all_flag(self) -> None:
        """Clear close_all_requested flags in state.json (best-effort)."""
        state_file = getattr(self.state_manager, "state_file", None)
        if not state_file or not Path(state_file).exists():
            return
        try:
            raw = Path(state_file).read_text(encoding="utf-8")
            state = json.loads(raw) if raw else {}
        except Exception:
            state = {}
        if not isinstance(state, dict):
            return
        if "close_all_requested" in state or "close_all_requested_time" in state:
            state.pop("close_all_requested", None)
            state.pop("close_all_requested_time", None)
            try:
                Path(state_file).write_text(json.dumps(state, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _get_close_signals_requested(self) -> list:
        """Get list of signal_ids requested for close from state.json."""
        state_file = getattr(self.state_manager, "state_file", None)
        if not state_file or not Path(state_file).exists():
            return []
        try:
            raw = Path(state_file).read_text(encoding="utf-8")
            state = json.loads(raw) if raw else {}
            return list(state.get("close_signals_requested", []))
        except Exception:
            return []

    def _clear_close_signals_requested(self, signal_ids: list = None) -> None:
        """Clear specific signal close requests or all of them from state.json."""
        state_file = getattr(self.state_manager, "state_file", None)
        if not state_file or not Path(state_file).exists():
            return
        try:
            raw = Path(state_file).read_text(encoding="utf-8")
            state = json.loads(raw) if raw else {}
        except Exception:
            state = {}
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
            Path(state_file).write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def _handle_close_all_requests(self, market_data: Dict) -> None:
        """Handle manual close-all flag, individual close requests, and auto-flat rules."""
        state_file = getattr(self.state_manager, "state_file", None)
        manual_requested = False
        if state_file and Path(state_file).exists():
            try:
                raw = Path(state_file).read_text(encoding="utf-8")
                state = json.loads(raw) if raw else {}
                manual_requested = bool(state.get("close_all_requested", False))
            except Exception:
                manual_requested = False

        if manual_requested:
            logger.warning("Close-all flag detected - flattening virtual trades")
            await self._close_all_virtual_trades(market_data=market_data, reason="close_all_requested")
            self._clear_close_all_flag()

        # Handle individual signal close requests
        close_signal_ids = self._get_close_signals_requested()
        if close_signal_ids:
            logger.warning(f"Individual close requests detected: {close_signal_ids}")
            closed_ids = await self._close_specific_virtual_trades(
                signal_ids=close_signal_ids,
                market_data=market_data,
                reason="manual_close_requested"
            )
            if closed_ids:
                self._clear_close_signals_requested(closed_ids)

        # Auto-flat rules (daily + Friday + weekend safety)
        try:
            market_open = bool(get_market_hours().is_market_open())
        except Exception:
            market_open = None
        now = datetime.now(timezone.utc)
        reason = self._auto_flat_due(now, market_open=market_open)
        if reason:
            active = self._get_active_virtual_trades(limit=200)
            if active:
                logger.warning(f"Auto-flat triggered: {reason}")
                closed = await self._close_all_virtual_trades(market_data=market_data, reason=reason)
                if closed > 0:
                    try:
                        local_now = now.astimezone(ZoneInfo(self._auto_flat_timezone))
                        self._auto_flat_last_dates[reason] = local_now.date()
                    except Exception:
                        self._auto_flat_last_dates[reason] = now.date()

                    # MFFU: update EOD high-water mark after session close flatten
                    if reason == "mffu_session_close" and self._mffu_tracker is not None:
                        try:
                            self._mffu_tracker.update_eod_hwm()
                        except Exception as e:
                            logger.debug(f"Could not update MFFU EOD HWM: {e}")

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
            version = "0.2.3"  # Fallback to known version

        # Market + trading bot identity for multi-market observability (Telegram/UI/ops)
        market_label = None
        try:
            import os

            market_label = str(os.getenv("PEARLALGO_MARKET") or "NQ").strip().upper()
        except Exception:
            market_label = "NQ"

        state = {
            # Core service state
            "market": market_label,
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
            "config_warnings": self._config_warnings,
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
            # Used by operator UI to detect "market changed" events.
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
            "close_all_last_executed": self._last_close_all_at,
            "close_all_last_reason": self._last_close_all_reason,
            "close_all_last_count": self._last_close_all_count,
            "close_all_last_pnl": self._last_close_all_pnl,
            "close_all_last_price_source": self._last_close_all_price_source,
        }
        # Reuse futures_market_open from earlier check (avoid duplicate API call)
        state["futures_market_open"] = futures_market_open
        try:
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            state["strategy_session_open"] = check_trading_session(datetime.now(timezone.utc), self.config)
        except Exception:
            state["strategy_session_open"] = None

        # Compute market regime from buffer data (best-effort)
        # This populates the regime field used by the web dashboard header badges
        try:
            last_market_data = getattr(self.data_fetcher, "_last_market_data", None) or {}
            df_for_regime = last_market_data.get("df")
            if isinstance(df_for_regime, pd.DataFrame) and not df_for_regime.empty and len(df_for_regime) >= 50:
                from pearlalgo.trading_bots.pearl_bot_auto import detect_market_regime
                regime_result = detect_market_regime(df_for_regime, lookback=50)
                state["regime"] = regime_result.regime
                state["regime_confidence"] = regime_result.confidence
                state["regime_trend_strength"] = regime_result.trend_strength
                state["regime_volatility_ratio"] = regime_result.volatility_ratio
                state["regime_recommendation"] = regime_result.recommendation
                state["regime_timestamp"] = datetime.now(timezone.utc).isoformat()
            else:
                state["regime"] = None
                state["regime_timestamp"] = None
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
        state["learning_contextual"] = (
            self.contextual_policy.get_status()
            if self.contextual_policy is not None
            else {"enabled": False, "mode": "disabled"}
        )
        state["ml_filter"] = {
            "enabled": bool(getattr(self, "_ml_filter_enabled", False)),
            "mode": getattr(self, "_ml_filter_mode", "shadow"),
            "trained": bool(getattr(getattr(self, "_ml_signal_filter", None), "is_ready", False)),
            "require_lift_to_block": bool(getattr(self, "_ml_require_lift_to_block", True)),
            "blocking_allowed": bool(getattr(self, "_ml_blocking_allowed", False)),
            "lift": getattr(self, "_ml_lift_metrics", {}) or {},
            "last_eval_at": (
                self._ml_lift_last_eval_at.isoformat()
                if getattr(self, "_ml_lift_last_eval_at", None) is not None
                else None
            ),
        }

        # ==========================================================================
        # Notification queue stats (async Telegram delivery observability)
        # ==========================================================================
        state["notification_queue"] = self.notification_queue.get_stats()

        # ==========================================================================
        # Pearl AI Insights (shadow tracking for web app)
        # ==========================================================================
        try:
            shadow_metrics = self.shadow_tracker.get_metrics()
            active_suggestion = self.shadow_tracker.get_active_suggestion()

            # Get AI chat status
            ai_enabled = False
            try:
                from pearlalgo.ai.chat import get_ai_chat
                ai_chat = get_ai_chat()
                ai_enabled = ai_chat.enabled
            except Exception:
                pass

            state["pearl_insights"] = {
                "current_suggestion": active_suggestion,
                "shadow_metrics": shadow_metrics,
                "ai_enabled": ai_enabled,
                "last_insight_time": shadow_metrics.get("active_suggestion", {}).get("timestamp") if shadow_metrics.get("active_suggestion") else None,
                "suggestions_today": shadow_metrics.get("total_suggestions", 0),
                "accuracy_7d": shadow_metrics.get("accuracy_rate", 0),
            }
        except Exception as e:
            logger.debug(f"Could not build pearl_insights: {e}")
            state["pearl_insights"] = None

        # ==========================================================================
        # Trading circuit breaker status (risk management observability)
        # ==========================================================================
        state["trading_circuit_breaker"] = (
            self.trading_circuit_breaker.get_status()
            if self.trading_circuit_breaker is not None
            else {"enabled": False}
        )

        # ==========================================================================
        # Virtual positions (signals.jsonl status="entered") for Telegram command UI
        # ==========================================================================
        # The interactive Telegram command handler reads state.json. Persisting these
        # fields here keeps /start dashboards accurate (open positions + unrealized PnL).
        state["active_trades_count"] = 0
        try:
            # Surface latest price source (Level 1 vs historical) for UI confidence cues.
            if isinstance(latest_bar, dict):
                state["latest_price_source"] = latest_bar.get("_data_level") or latest_bar.get("_data_source")
        except Exception:
            pass

        try:
            recent_signals = self.state_manager.get_recent_signals(limit=300)
            active: list[dict] = []
            for rec in recent_signals:
                if isinstance(rec, dict) and rec.get("status") == "entered":
                    active.append(rec)
            state["active_trades_count"] = int(len(active))

            # Total unrealized PnL (USD) across active trades using freshest available price.
            latest_price = None
            try:
                if isinstance(latest_bar, dict):
                    latest_price = latest_bar.get("close")
            except Exception:
                latest_price = None

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

                    state["active_trades_unrealized_pnl"] = float(total_upnl)
        except Exception:
            # Never allow optional UI fields to break state persistence.
            pass

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

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        signal_names = {
            signal.SIGINT: "SIGINT (Ctrl+C)",
            signal.SIGTERM: "SIGTERM",
        }
        signal_name = signal_names.get(signum, f"Signal {signum}")
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self.shutdown_requested = True
