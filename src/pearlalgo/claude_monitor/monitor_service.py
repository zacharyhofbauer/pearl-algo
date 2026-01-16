"""
Claude Monitor Service - Main 24/7 monitoring service for the trading agent.

Runs alongside the NQ Agent, continuously analyzing performance, health,
and market conditions to provide intelligent alerts and suggestions.
"""

from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_signals_file,
    get_state_file,
    get_utc_timestamp,
)

from pearlalgo.claude_monitor.analysis_engine import AnalysisEngine
from pearlalgo.claude_monitor.alert_manager import AlertManager, Alert, AlertLevel
from pearlalgo.claude_monitor.suggestion_engine import SuggestionEngine, Suggestion
from pearlalgo.claude_monitor.monitor_state import MonitorState
from pearlalgo.claude_monitor.action_executor import (
    ActionExecutor,
    ActionRequest,
    ActionResult,
    ActionType,
    ActionStatus,
)

# Timezone handling (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# OpenAI client (optional [llm] extra)
try:
    from pearlalgo.utils.claude_client import ClaudeClient, get_claude_client, OPENAI_AVAILABLE
except ImportError:
    ClaudeClient = None  # type: ignore
    get_claude_client = lambda: None  # type: ignore
    OPENAI_AVAILABLE = False

# Backward compatibility
ANTHROPIC_AVAILABLE = OPENAI_AVAILABLE


class ClaudeMonitorService:
    """
    24/7 Claude monitoring service for the trading agent.
    
    Features:
    - Real-time monitoring of agent state
    - Multi-dimensional analysis (signals, system, market, code)
    - Intelligent alerts with deduplication
    - Actionable suggestions
    - Daily/weekly reports
    """
    
    def __init__(
        self,
        state_dir: Optional[Path] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize Claude monitor service.
        
        Args:
            state_dir: State directory for reading agent data
            telegram_bot_token: Telegram bot token for alerts
            telegram_chat_id: Telegram chat ID for alerts
            config: Configuration dictionary (from config.yaml claude_monitor section)
        """
        self.state_dir = ensure_state_dir(state_dir)
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.config = config or {}

        # Timezone for reports + quiet hours. Config comments default to ET.
        self.timezone_name = str(self.config.get("timezone") or "America/New_York")
        self._tzinfo = timezone.utc
        if ZoneInfo is not None:
            try:
                self._tzinfo = ZoneInfo(self.timezone_name)
            except Exception:
                logger.warning(f"Invalid claude_monitor.timezone: {self.timezone_name}; falling back to UTC")
                self.timezone_name = "UTC"
                self._tzinfo = timezone.utc
        
        # Initialize Claude client
        self._claude: Optional[ClaudeClient] = None
        self._init_claude_client()
        
        # Initialize components
        self.analysis_engine = AnalysisEngine(
            claude_client=self._claude,
            code_analysis_interval_hours=self.config.get("code_analysis_interval_hours", 1),
            code_analysis_enabled=self.config.get("code_analysis_enabled", True),
        )
        
        self.alert_manager = AlertManager(
            dedup_window_seconds=self.config.get("dedup_window_seconds", 900),
            quiet_start=self.config.get("quiet_hours_start"),
            quiet_end=self.config.get("quiet_hours_end"),
            timezone_name=self.timezone_name,
            suppress_info_during_quiet=self.config.get("suppress_info_during_quiet", True),
            max_alerts_per_hour=self.config.get("max_alerts_per_hour", 20),
            allowed_levels=self.config.get("alert_levels"),
            allowed_categories=self.config.get("alert_categories"),
        )
        
        self.suggestion_engine = SuggestionEngine(
            claude_client=self._claude,
            max_suggestions_per_analysis=self.config.get("max_suggestions_per_analysis", 5),
        )
        
        self.monitor_state = MonitorState(state_dir=state_dir)
        
        # Action executor for applying suggestions
        self.action_executor = ActionExecutor(
            state_dir=self.state_dir,
            auto_approve=self.config.get("auto_apply_enabled", False),
            dry_run_default=not self.config.get("auto_apply_enabled", False),
            max_changes_per_day=self.config.get("max_auto_changes_per_day", 3),
        )
        
        # Telegram notifier (for sending alerts)
        self._telegram = None
        self._init_telegram()
        
        # Service state
        self.running = False
        self.shutdown_requested = False
        self.start_time: Optional[datetime] = None
        
        # Intervals
        self.frequent_interval = self.config.get("frequent_interval_seconds", 900)  # 15 min
        self.realtime_interval = self.config.get("realtime_interval_seconds", 60)   # 1 min
        self.realtime_monitoring = self.config.get("realtime_monitoring", True)
        
        # Report schedule
        self.daily_report_enabled = self.config.get("daily_report_enabled", True)
        self.daily_report_time = self.config.get("daily_report_time", "09:00")
        self.weekly_report_enabled = self.config.get("weekly_report_enabled", True)
        self.weekly_report_day = self.config.get("weekly_report_day", "monday")
        self.weekly_report_time = self.config.get("weekly_report_time", "09:00")
        
        # Tracking
        self._last_analysis: Optional[datetime] = None
        self._last_daily_report: Optional[datetime] = self._parse_utc_ts(self.monitor_state.get_last_daily_report_sent_at())
        self._last_weekly_report: Optional[datetime] = self._parse_utc_ts(self.monitor_state.get_last_weekly_report_sent_at())
        self._cycle_count = 0
        
        # Auto-apply settings
        self.auto_apply_enabled = self.config.get("auto_apply_enabled", False)
        self.max_auto_changes_per_day = self.config.get("max_auto_changes_per_day", 3)
        self._auto_apply_count_today = 0
        self._auto_apply_last_reset: Optional[datetime] = None

        # Auto-apply backtest gate (prevents silently removing opportunities)
        self.auto_apply_backtest_enabled = bool(self.config.get("auto_apply_backtest_enabled", False))
        self.auto_apply_backtest_data_path = str(self.config.get("auto_apply_backtest_data_path") or "")
        # Lookback window (cap further by max_bars to keep runtime bounded)
        self.auto_apply_backtest_lookback_weeks = float(self.config.get("auto_apply_backtest_lookback_weeks", 1) or 1)
        self.auto_apply_backtest_decision = str(self.config.get("auto_apply_backtest_decision") or "1m")
        self.auto_apply_backtest_timeout_seconds = float(self.config.get("auto_apply_backtest_timeout_seconds", 120) or 120)
        self.auto_apply_backtest_max_bars = int(self.config.get("auto_apply_backtest_max_bars", 3000) or 3000)
        self.auto_apply_backtest_max_signal_drop_pct = float(self.config.get("auto_apply_backtest_max_signal_drop_pct", 0.05) or 0.05)
        self.auto_apply_backtest_min_baseline_signals = int(self.config.get("auto_apply_backtest_min_baseline_signals", 20) or 20)
        self.auto_apply_backtest_min_type_baseline_signals = int(self.config.get("auto_apply_backtest_min_type_baseline_signals", 10) or 10)
        self.auto_apply_backtest_fail_on_type_zeroed = bool(self.config.get("auto_apply_backtest_fail_on_type_zeroed", True))
        self.auto_apply_backtest_defer_minutes = int(self.config.get("auto_apply_backtest_defer_minutes", 360) or 360)
        
        logger.info(
            f"Claude Monitor Service initialized "
            f"(auto_apply={self.auto_apply_enabled}, max_auto={self.max_auto_changes_per_day})"
        )

    def _config_path_to_override_dict(self, config_path: str, new_value: Any) -> Dict[str, Any]:
        """Convert dot path (e.g. signals.min_confidence) to a nested override dict."""
        parts = [p for p in str(config_path or "").split(".") if p]
        if len(parts) < 2:
            return {}
        root = parts[0]
        cur: Dict[str, Any] = {}
        cur_root = cur
        cur_root[root] = {}
        node = cur_root[root]
        for p in parts[1:-1]:
            if not isinstance(node, dict):
                break
            node[p] = {}
            node = node[p]
        if isinstance(node, dict):
            node[parts[-1]] = new_value
        return cur

    def _apply_config_path_to_strategy_config(self, strategy_config: Any, config_path: str, new_value: Any) -> None:
        """
        Apply a subset of config.yaml dot-path changes to the NQIntradayConfig object.
        This is required for keys that are read by strategy config (not service config).
        """
        try:
            parts = [p for p in str(config_path or "").split(".") if p]
            if len(parts) < 2:
                return
            section, key = parts[0], ".".join(parts[1:])

            # Strategy config keys
            if section == "strategy":
                # These are direct attributes on NQIntradayConfig
                attr = parts[-1]
                if hasattr(strategy_config, attr):
                    # Preserve types where possible
                    current = getattr(strategy_config, attr)
                    if isinstance(current, bool):
                        setattr(strategy_config, attr, bool(new_value))
                    elif isinstance(current, int):
                        setattr(strategy_config, attr, int(new_value))
                    elif isinstance(current, float):
                        setattr(strategy_config, attr, float(new_value))
                    else:
                        setattr(strategy_config, attr, new_value)
                return

            # Signals keys that also map into strategy config fields
            if section == "signals":
                if key == "volatility_threshold":
                    setattr(strategy_config, "volatility_threshold", float(new_value))
                elif key == "min_volume":
                    setattr(strategy_config, "min_volume", int(new_value))
                elif key == "min_risk_reward":
                    # Strategy config uses take_profit_risk_reward as its TP model target
                    setattr(strategy_config, "take_profit_risk_reward", float(new_value))
                return

            # Risk keys that map into strategy config fields
            if section == "risk":
                if key == "stop_loss_atr_multiplier":
                    setattr(strategy_config, "stop_loss_atr_multiplier", float(new_value))
                elif key == "take_profit_risk_reward":
                    setattr(strategy_config, "take_profit_risk_reward", float(new_value))
                elif key == "max_risk_per_trade":
                    setattr(strategy_config, "max_risk_per_trade", float(new_value))
                elif key == "max_position_size":
                    setattr(strategy_config, "max_position_size", int(new_value))
                elif key == "min_position_size":
                    setattr(strategy_config, "min_position_size", int(new_value))
                return
        except Exception:
            return

    async def _auto_apply_backtest_gate(
        self,
        *,
        suggestion_id: str,
        config_path: str,
        old_value: Any,
        new_value: Any,
    ) -> Dict[str, Any]:
        """
        Run a fast signal-only backtest comparing baseline vs proposed config.

        Returns:
            Dict with keys: passed(bool), reason(str), baseline_total(int), candidate_total(int), ratio(float)
        """
        now = datetime.now(timezone.utc)
        try:
            from pearlalgo.config.config_loader import service_config_override
            from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
            from pearlalgo.strategies.nq_intraday.backtest_adapter import (
                run_signal_backtest,
                run_signal_backtest_5m_decision,
            )
            import pandas as pd
        except Exception as e:
            return {"passed": False, "reason": f"backtest_gate_unavailable: {e}"}

        # Resolve data path
        project_root = Path(__file__).resolve().parents[3]
        data_path = self.auto_apply_backtest_data_path.strip()
        candidate_paths = []
        if data_path:
            candidate_paths.append(project_root / data_path)
        # Fallbacks
        candidate_paths.extend([
            project_root / "data" / "historical" / "MNQ_1m_2w.parquet",
            project_root / "data" / "historical" / "MNQ_1m_1w.parquet",
        ])
        resolved = next((p for p in candidate_paths if p.exists()), None)
        if resolved is None:
            return {"passed": False, "reason": "backtest_gate_no_data: no historical data file found"}

        decision = self.auto_apply_backtest_decision.strip() or "1m"
        lookback_weeks = max(0.05, float(self.auto_apply_backtest_lookback_weeks or 1.0))

        # Load data (parquet) and slice recent lookback window
        df = pd.read_parquet(resolved)
        if not isinstance(df.index, pd.DatetimeIndex):
            for col in ("timestamp", "time", "datetime", "date"):
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], utc=True)
                    df = df.set_index(col)
                    break
        if not isinstance(df.index, pd.DatetimeIndex) or df.empty:
            return {"passed": True, "reason": "backtest_gate_skipped: empty/invalid historical data"}
        df = df.sort_index()
        cutoff = df.index[-1] - pd.Timedelta(weeks=lookback_weeks)
        df = df[df.index >= cutoff]
        # Hard cap bars for runtime predictability (e.g., 3000 ~ ~2 trading days at 1m)
        try:
            max_bars = int(self.auto_apply_backtest_max_bars or 0)
            if max_bars > 0 and len(df) > max_bars:
                df = df.tail(max_bars)
        except Exception:
            pass
        if df.empty:
            return {"passed": False, "reason": "backtest_gate_no_data: no data in lookback window"}

        # Build configs
        baseline_cfg = NQIntradayConfig.from_config_file()
        candidate_cfg = NQIntradayConfig.from_config_file()
        self._apply_config_path_to_strategy_config(candidate_cfg, config_path, new_value)

        # Service-level override (signals/risk) affects signal_generator thresholds
        overrides = self._config_path_to_override_dict(config_path, new_value)

        def _run_once(cfg: Any, override: Optional[Dict[str, Any]]) -> Any:
            if override:
                with service_config_override(override):
                    if decision == "5m":
                        return run_signal_backtest_5m_decision(df, config=cfg, return_signals=False)
                    return run_signal_backtest(df, config=cfg, return_signals=False)
            if decision == "5m":
                return run_signal_backtest_5m_decision(df, config=cfg, return_signals=False)
            return run_signal_backtest(df, config=cfg, return_signals=False)

        async def _run_with_timeout() -> Tuple[Any, Any]:
            # Run in a worker thread so monitor loop stays responsive.
            def _thread_run() -> Tuple[Any, Any]:
                # Backtests can be very chatty; silence logs for this thread context.
                try:
                    from pearlalgo.utils.logger import log_silence
                except Exception:
                    log_silence = None  # type: ignore

                if log_silence is not None:
                    with log_silence():
                        baseline = _run_once(baseline_cfg, override=None)
                        candidate = _run_once(candidate_cfg, override=overrides if overrides else None)
                        return baseline, candidate
                baseline = _run_once(baseline_cfg, override=None)
                candidate = _run_once(candidate_cfg, override=overrides if overrides else None)
                return baseline, candidate
            return await asyncio.wait_for(asyncio.to_thread(_thread_run), timeout=self.auto_apply_backtest_timeout_seconds)

        try:
            baseline_res, candidate_res = await _run_with_timeout()
        except Exception as e:
            # Fail-closed: if we can't backtest, don't auto-apply (prevents silent opportunity loss).
            return {"passed": False, "reason": f"backtest_gate_error: {type(e).__name__ or 'error'} {e}"}

        baseline_total = int(getattr(baseline_res, "total_signals", 0) or 0)
        candidate_total = int(getattr(candidate_res, "total_signals", 0) or 0)

        # Compute distributions (best-effort)
        baseline_dist = getattr(baseline_res, "signal_distribution", None) or {}
        candidate_dist = getattr(candidate_res, "signal_distribution", None) or {}
        try:
            if not baseline_dist and getattr(baseline_res, "verification", None):
                baseline_dist = getattr(baseline_res.verification, "signal_type_distribution", {}) or {}
            if not candidate_dist and getattr(candidate_res, "verification", None):
                candidate_dist = getattr(candidate_res.verification, "signal_type_distribution", {}) or {}
        except Exception:
            pass

        # Gate: do not reduce opportunities beyond threshold
        passed = True
        reason = "ok"
        ratio = 1.0
        if baseline_total >= max(1, self.auto_apply_backtest_min_baseline_signals):
            ratio = float(candidate_total) / float(baseline_total) if baseline_total > 0 else 1.0
            min_ratio = max(0.0, 1.0 - float(self.auto_apply_backtest_max_signal_drop_pct))
            if ratio < min_ratio:
                passed = False
                reason = f"signal_drop_exceeds_threshold: ratio={ratio:.3f} < min_ratio={min_ratio:.3f}"

        zeroed: List[str] = []
        if passed and self.auto_apply_backtest_fail_on_type_zeroed:
            try:
                min_type_n = max(1, int(self.auto_apply_backtest_min_type_baseline_signals))
                for t, n in (baseline_dist or {}).items():
                    try:
                        bn = int(n or 0)
                        if bn >= min_type_n and int((candidate_dist or {}).get(t, 0) or 0) == 0:
                            zeroed.append(str(t))
                    except Exception:
                        continue
                if zeroed:
                    passed = False
                    reason = f"signal_type_zeroed: {', '.join(zeroed[:5])}"
            except Exception:
                pass

        gate = {
            "passed": passed,
            "reason": reason,
            "baseline_total_signals": baseline_total,
            "candidate_total_signals": candidate_total,
            "signal_ratio": ratio,
            "max_signal_drop_pct": float(self.auto_apply_backtest_max_signal_drop_pct),
            "data_path": str(resolved),
            "lookback_weeks": lookback_weeks,
            "decision": decision,
            "config_path": config_path,
            "old_value": old_value,
            "new_value": new_value,
            "checked_at": get_utc_timestamp(),
        }

        # Persist gate result on the suggestion (so operator can review)
        try:
            payload: Dict[str, Any] = {"backtest_gate": gate, "timestamp": get_utc_timestamp()}
            if not passed:
                payload["deferred"] = True
                payload["defer_until_utc"] = (now + timedelta(minutes=max(1, self.auto_apply_backtest_defer_minutes))).isoformat()
            self.monitor_state.update_suggestion_status(suggestion_id, "pending", payload)
        except Exception:
            pass

        return gate

    def _parse_utc_ts(self, ts: Optional[str]) -> Optional[datetime]:
        """Parse a stored UTC ISO timestamp into an aware datetime (UTC)."""
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _local_now(self, now_utc: Optional[datetime] = None) -> datetime:
        """Return 'now' in the configured monitor timezone."""
        now_utc = now_utc or datetime.now(timezone.utc)
        try:
            return now_utc.astimezone(self._tzinfo)
        except Exception:
            return now_utc
    
    def _init_claude_client(self) -> None:
        """Initialize Claude client if available."""
        if not OPENAI_AVAILABLE:
            logger.warning("Claude not available: anthropic package not installed")
            return
        
        try:
            self._claude = get_claude_client()
            if self._claude:
                logger.info("Claude client initialized for monitoring")
            else:
                logger.warning("OpenAI client not available (check OPENAI_API_KEY)")
        except Exception as e:
            logger.error(f"Could not initialize Claude client: {e}")
    
    def _init_telegram(self) -> None:
        """Initialize Telegram for sending alerts."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram not configured for Claude monitor alerts")
            return
        
        try:
            from pearlalgo.utils.telegram_alerts import TelegramAlerts
            self._telegram = TelegramAlerts(
                bot_token=self.telegram_bot_token,
                chat_id=self.telegram_chat_id,
            )
            logger.info("Telegram initialized for Claude monitor alerts")
        except Exception as e:
            logger.error(f"Could not initialize Telegram: {e}")
    
    async def run(self) -> None:
        """Main monitoring loop."""
        self.running = True
        self.shutdown_requested = False
        self.start_time = datetime.now(timezone.utc)
        
        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)
        
        logger.info("Claude Monitor Service starting...")
        
        # Send startup notification
        await self._send_startup_notification()
        
        try:
            while self.running and not self.shutdown_requested:
                await self._run_cycle()
                
                # Determine next interval
                interval = self._get_next_interval()
                await asyncio.sleep(interval)
                
        except asyncio.CancelledError:
            logger.info("Claude Monitor Service cancelled")
        except Exception as e:
            logger.error(f"Claude Monitor Service error: {e}")
            await self._send_error_alert(str(e))
        finally:
            self.running = False
            await self._send_shutdown_notification()
            logger.info("Claude Monitor Service stopped")
    
    def _handle_shutdown(self) -> None:
        """Handle shutdown signal."""
        logger.info("Shutdown signal received")
        self.shutdown_requested = True
    
    async def _run_cycle(self) -> None:
        """Run a single monitoring cycle."""
        self._cycle_count += 1
        logger.debug(f"Monitor cycle {self._cycle_count}")
        
        try:
            # Load current agent state
            agent_state = self._load_agent_state()
            if not agent_state:
                logger.warning("Could not load agent state")
                return
            
            # Load signals and performance data
            signals_data = self._load_recent_signals()
            performance_data = self._load_performance_data()
            market_data = self._extract_market_data(agent_state)

            # Detect market change for strategy update prompts (best-effort).
            # We detect before analysis so we can include "from -> to" context in the prompt,
            # but we only *send* after suggestions are generated and assigned IDs.
            transition: Optional[Dict[str, Any]] = None
            try:
                prev_regime = self.monitor_state.get_last_regime_seen()
                curr_regime = market_data.get("regime") if isinstance(market_data.get("regime"), dict) else None
                transition = self._detect_strategy_update_transition(prev_regime, curr_regime)

                # Persist last seen regime (only when it changes or first-seen)
                if isinstance(curr_regime, dict) and (not isinstance(prev_regime, dict) or prev_regime != curr_regime):
                    ts = market_data.get("regime_timestamp") or market_data.get("latest_bar_timestamp")
                    self.monitor_state.set_last_regime_seen(curr_regime, timestamp=str(ts) if ts else None)
            except Exception:
                transition = None
            
            # Run analysis
            analysis = await self.analysis_engine.analyze_all(
                agent_state=agent_state,
                signals_data=signals_data,
                performance_data=performance_data,
                market_data=market_data,
            )
            
            self._last_analysis = datetime.now(timezone.utc)
            
            # Generate alerts
            alerts = self.alert_manager.process_analysis(analysis)
            
            # Send alerts
            for alert in alerts:
                await self._send_alert(alert)
                self.monitor_state.record_alert(alert.to_dict())
            
            # Generate suggestions
            suggestions = self.suggestion_engine.generate(analysis)
            
            # Record analysis
            suggestions_dicts = [s.to_dict() for s in suggestions]
            # Only persist actionable suggestions (keeps the Suggestions UI clean and prevents
            # unbounded growth from investigation-only items).
            actionable_types = {"config_change", "parameter_tune", "service_action", "code_patch"}
            try:
                from pearlalgo.claude_monitor.auto_tune_policy import DEFAULT_ALLOWLIST
                allowlisted_paths = set(DEFAULT_ALLOWLIST.keys())
            except Exception:
                allowlisted_paths = set()

            # We never want to nag with "disable/enable signals" suggestions in the active list.
            # Those can reduce trade count and must be an explicit operator decision.
            skip_config_paths = {"strategy.enabled_signals", "strategy.disabled_signals"}

            suggestions_for_state: List[Dict[str, Any]] = []
            for d in suggestions_dicts:
                d = d or {}
                s_type = str(d.get("type", "")).strip()
                if s_type not in actionable_types:
                    continue
                if s_type in ("config_change", "parameter_tune"):
                    cp = str(d.get("config_path") or "").strip()
                    nv = d.get("new_value")
                    if nv is None:
                        # Not actionable; do not persist as an "active suggestion" (prevents spam).
                        continue
                    if not cp or (allowlisted_paths and cp not in allowlisted_paths):
                        continue
                    if cp in skip_config_paths:
                        continue
                suggestions_for_state.append(d)
            self.monitor_state.record_analysis(
                analysis=analysis,
                suggestions=suggestions_for_state,
            )

            # Strategy update prompt on meaningful market change
            # In autonomous mode (auto_apply_enabled), skip the interactive proposal
            # since _auto_apply_suggestions() will apply eligible changes and notify.
            try:
                sig = str((transition or {}).get("signature") or "").strip()
                if transition and sig and self._should_send_strategy_update_prompt(sig):
                    if not self.auto_apply_enabled:
                        # Manual mode: show proposal with Apply/Dry-run buttons
                        await self._send_strategy_update_prompt(transition, suggestions_for_state)
                    self.monitor_state.set_last_regime_prompt(sig)
            except Exception as e:
                logger.debug(f"Could not send strategy update prompt: {e}")
            
            # Auto-apply eligible suggestions if enabled
            if self.auto_apply_enabled and suggestions:
                await self._auto_apply_suggestions(suggestions)
            
            # Check for scheduled reports
            await self._check_scheduled_reports()
            
        except Exception as e:
            logger.error(f"Monitor cycle error: {e}")
    
    def _get_next_interval(self) -> float:
        """Determine next monitoring interval."""
        if self.realtime_monitoring:
            return self.realtime_interval
        return self.frequent_interval
    
    async def _auto_apply_suggestions(self, suggestions: List[Suggestion]) -> None:
        """
        Automatically apply eligible suggestions.
        
        Filters for:
        - Config changes or parameter tunes (executable types)
        - Low or medium risk level
        - Has config_path and new_value
        
        Rate-limited by max_auto_changes_per_day.
        """
        # Reset daily counter if new day
        now = datetime.now(timezone.utc)
        if self._auto_apply_last_reset is None or now.date() != self._auto_apply_last_reset.date():
            self._auto_apply_count_today = 0
            self._auto_apply_last_reset = now
        
        # Check if we've hit the daily limit
        if self._auto_apply_count_today >= self.max_auto_changes_per_day:
            logger.debug(f"Auto-apply: daily limit reached ({self.max_auto_changes_per_day})")
            return
        
        # Filter for eligible suggestions
        eligible = []
        for sug in suggestions:
            sug_dict = sug.to_dict() if hasattr(sug, "to_dict") else sug
            sug_type = sug_dict.get("type", "")
            risk = sug_dict.get("risk_level", "medium")
            config_path = sug_dict.get("config_path")
            new_value = sug_dict.get("new_value")
            
            # Must be a config change type
            if sug_type not in ("config_change", "parameter_tune"):
                continue
            
            # Must have config_path and new_value
            if not config_path or new_value is None:
                continue

            # Never auto-apply changes that disable/enable signal families.
            # The operator must explicitly opt-in to changes that can reduce trade count.
            if config_path in ("strategy.enabled_signals", "strategy.disabled_signals"):
                continue
            
            # Only low or medium risk
            if risk not in ("low", "medium"):
                continue
            
            eligible.append(sug_dict)
        
        if not eligible:
            return
        
        logger.info(f"Auto-apply: {len(eligible)} eligible suggestions found")
        
        # Apply up to remaining daily quota
        remaining = self.max_auto_changes_per_day - self._auto_apply_count_today
        to_apply = eligible[:remaining]
        
        for sug_dict in to_apply:
            suggestion_id = sug_dict.get("id")
            if not suggestion_id:
                # Need to find the suggestion ID from monitor_state
                # The suggestion was just generated and recorded
                active = self.monitor_state.get_active_suggestions()
                for active_sug in active:
                    if (
                        active_sug.get("config_path") == sug_dict.get("config_path")
                        and active_sug.get("new_value") == sug_dict.get("new_value")
                    ):
                        suggestion_id = active_sug.get("id")
                        break
            
            if not suggestion_id:
                logger.warning(f"Auto-apply: could not find suggestion ID for {sug_dict.get('config_path')}")
                continue

            # If the suggestion was previously deferred (rate limit / cooldown), do not spam retries.
            try:
                stored = self.monitor_state.get_suggestion(suggestion_id) or {}
                stored_status = str(stored.get("status", ""))
                stored_result = stored.get("result", {}) or {}
                defer_until = stored_result.get("defer_until_utc")
                if stored_status == "pending" and stored_result.get("deferred") and defer_until:
                    try:
                        until_dt = datetime.fromisoformat(str(defer_until).replace("Z", "+00:00"))
                        if until_dt.tzinfo is None:
                            until_dt = until_dt.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) < until_dt.astimezone(timezone.utc):
                            continue
                    except Exception:
                        # If we can't parse, err on the side of not spamming retries.
                        continue
            except Exception:
                pass
            
            try:
                logger.info(f"Auto-applying suggestion {suggestion_id}: {sug_dict.get('title')}")

                # Backtest gate: don't auto-apply if it materially reduces opportunities.
                if self.auto_apply_backtest_enabled:
                    try:
                        gate = await self._auto_apply_backtest_gate(
                            suggestion_id=suggestion_id,
                            config_path=str(sug_dict.get("config_path") or ""),
                            old_value=sug_dict.get("old_value"),
                            new_value=sug_dict.get("new_value"),
                        )
                        if isinstance(gate, dict) and gate.get("passed") is False:
                            logger.info(
                                f"Auto-apply skipped by backtest gate: {suggestion_id} "
                                f"({gate.get('reason')})"
                            )
                            continue
                    except Exception:
                        # Never block monitor on backtest gate issues.
                        pass

                result = await self.apply_suggestion(suggestion_id, dry_run=False)

                if result.get("success"):
                    self._auto_apply_count_today += 1

                    # Auto-restart agent to load new config (only when flat / no open positions)
                    restart_outcome = await self._try_auto_restart_agent()

                    # Send Telegram notification with restart outcome
                    await self._send_auto_apply_notification(
                        sug_dict, result, success=True, restart_outcome=restart_outcome
                    )

                    logger.info(
                        f"Auto-apply SUCCESS: {suggestion_id} "
                        f"({sug_dict.get('config_path')} = {sug_dict.get('new_value')}), "
                        f"restart={restart_outcome.get('status', 'n/a')}"
                    )
                else:
                    # Send failure notification
                    # Avoid spamming failures for deferrals (daily limit/cooldown); they'll retry later.
                    try:
                        stored_after = self.monitor_state.get_suggestion(suggestion_id) or {}
                        stored_res = stored_after.get("result", {}) or {}
                        deferred = (
                            str(stored_after.get("status", "")) == "pending"
                            and bool(stored_res.get("deferred"))
                            and bool(stored_res.get("defer_until_utc"))
                        )
                    except Exception:
                        deferred = False
                    if not deferred:
                        await self._send_auto_apply_notification(sug_dict, result, success=False)

                    logger.warning(
                        f"Auto-apply FAILED: {suggestion_id} - {result.get('error', 'unknown')}"
                    )

            except Exception as e:
                logger.error(f"Auto-apply error for {suggestion_id}: {e}", exc_info=True)
    
    async def _send_auto_apply_notification(
        self,
        suggestion: Dict[str, Any],
        result: Dict[str, Any],
        success: bool,
        restart_outcome: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send Telegram notification for auto-applied changes."""
        if not self._telegram:
            return

        try:
            # Get current regime context for richer notification
            regime_ctx = ""
            try:
                last_regime = self.monitor_state.get_last_regime_seen()
                if isinstance(last_regime, dict) and last_regime.get("regime"):
                    r_type = str(last_regime.get("regime", "")).replace("_", " ").title()
                    r_vol = str(last_regime.get("volatility", "")).title()
                    regime_ctx = f"🧭 *Regime:* {r_type} | {r_vol} Vol\n"
            except Exception:
                pass

            if success:
                # Build restart status line
                restart_status = ""
                restart_deferred = False
                if restart_outcome:
                    rs = str(restart_outcome.get("status", "")).lower()
                    if rs == "restarted":
                        restart_status = "\n✅ *Agent restarted* — new config active"
                    elif rs == "deferred":
                        pos = restart_outcome.get("positions", "?")
                        restart_status = f"\n⏸️ *Restart deferred* — {pos} open position(s)"
                        restart_deferred = True
                    elif rs == "error":
                        restart_status = f"\n⚠️ *Restart failed* — {restart_outcome.get('message', 'unknown')[:60]}"
                        restart_deferred = True

                message = (
                    "🤖 *Strategy Auto-Updated*\n\n"
                    f"{regime_ctx}"
                    f"*{suggestion.get('title', 'Config Update')}*\n\n"
                    f"*Path:* `{suggestion.get('config_path')}`\n"
                    f"*Old:* `{suggestion.get('old_value')}`\n"
                    f"*New:* `{suggestion.get('new_value')}`"
                    f"{restart_status}\n\n"
                    f"*Request ID:* `{result.get('request_id')}`\n"
                    f"*Rollback:* `/rollback_suggestion {result.get('request_id')}`\n\n"
                    f"_{suggestion.get('rationale', '')[:150]}_"
                )
            else:
                restart_deferred = False
                message = (
                    "⚠️ *Auto-Apply Failed*\n\n"
                    f"*{suggestion.get('title', 'Config Update')}*\n\n"
                    f"*Path:* `{suggestion.get('config_path')}`\n"
                    f"*Error:* `{str(result.get('error', 'Unknown'))[:150]}`\n\n"
                    "The suggestion was not applied."
                )

            # Include Restart Agent button only when restart was deferred or failed
            reply_markup = None
            if success:
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    request_id = result.get("request_id", "")
                    keyboard = []
                    # Show Restart button only if restart was deferred/failed
                    if restart_deferred:
                        keyboard.append([
                            InlineKeyboardButton("🔁 Restart Agent", callback_data="confirm:restart_agent"),
                            InlineKeyboardButton("🔄 Rollback", callback_data=f"sug:rollback:{request_id}"),
                        ])
                    else:
                        # Restart succeeded — just show rollback
                        keyboard.append([
                            InlineKeyboardButton("🔄 Rollback", callback_data=f"sug:rollback:{request_id}"),
                        ])
                    keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="start")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                except Exception:
                    pass

            await self._telegram.send_message(message, parse_mode="Markdown", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Could not send auto-apply notification: {e}")

    async def _try_auto_restart_agent(self) -> Dict[str, Any]:
        """
        Attempt to auto-restart the agent to load new config.

        Only restarts when there are no open positions (safe to interrupt).

        Returns:
            Dict with status: "restarted", "deferred", or "error" and optional message.
        """
        try:
            # Reload state to get current positions
            agent_state = self._load_agent_state()
            if not agent_state:
                return {"status": "error", "message": "Could not load agent state"}

            execution = agent_state.get("execution", {})
            positions = int(execution.get("positions", 0) or 0)

            if positions > 0:
                logger.info(f"Auto-restart deferred: {positions} open position(s)")
                return {
                    "status": "deferred",
                    "message": f"Open position(s): {positions}",
                    "positions": positions,
                }

            # Safe to restart — no open positions
            logger.info("Auto-restarting agent to load new config (no open positions)")

            # Use the ActionExecutor to trigger service restart
            request = ActionRequest(
                action_type=ActionType.SERVICE_RESTART,
                description="Auto-restart agent after config update",
                changes={"reason": "auto_apply_config"},
                service_name="agent",
                action="restart",
            )
            result = await self.action_executor.execute(request)

            if result.success:
                logger.info(f"Auto-restart SUCCESS: {result.message}")
                return {"status": "restarted", "message": result.message}
            else:
                logger.warning(f"Auto-restart FAILED: {result.error}")
                return {"status": "error", "message": result.error or "Unknown error"}

        except Exception as e:
            logger.error(f"Auto-restart error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)[:100]}

    def _load_agent_state(self) -> Optional[Dict[str, Any]]:
        """Load current agent state from state.json."""
        try:
            state_file = get_state_file(self.state_dir)
            if state_file.exists():
                with open(state_file, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Could not load agent state: {e}")
        return None
    
    def _load_recent_signals(
        self,
        lookback_hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Load recent signals from signals.jsonl."""
        signals = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        
        def _normalize_signal_record(record: Dict[str, Any]) -> Dict[str, Any]:
            """
            Normalize signals.jsonl records so analyzers can rely on consistent top-level keys.
            
            The NQ agent writes records with a nested `signal` payload:
              { "signal": { "type": ..., "direction": ..., "confidence": ..., "entry_price": ... }, ... }
            
            Older monitor/analyzers expected these fields at the top level. We flatten the most
            important ones (without deleting the nested payload).
            """
            if not isinstance(record, dict):
                return {}
            
            sig: Dict[str, Any] = dict(record)
            nested = sig.get("signal")
            if isinstance(nested, dict):
                # Type/name
                if sig.get("signal_type") is None:
                    sig["signal_type"] = nested.get("type") or nested.get("signal_type")
                if sig.get("type") is None:
                    sig["type"] = sig.get("signal_type") or nested.get("type")
                
                # Core fields
                if sig.get("direction") is None:
                    sig["direction"] = nested.get("direction")
                if sig.get("confidence") is None:
                    sig["confidence"] = nested.get("confidence")
                
                # Prices
                for k in ("entry_price", "stop_loss", "take_profit"):
                    if sig.get(k) is None and nested.get(k) is not None:
                        sig[k] = nested.get(k)
                
                # Outcome/result (derive from is_win if needed)
                if sig.get("outcome") is None and sig.get("result") is None:
                    is_win = sig.get("is_win")
                    if is_win is True:
                        sig["outcome"] = "win"
                    elif is_win is False:
                        sig["outcome"] = "loss"
                
                # R:R ratio (some code uses risk_reward_ratio, others use rr)
                rr = sig.get("risk_reward_ratio") or sig.get("rr") or nested.get("risk_reward_ratio") or nested.get("rr")
                if rr is None:
                    try:
                        entry = float(sig.get("entry_price") or 0.0)
                        stop = float(sig.get("stop_loss") or 0.0)
                        tp = float(sig.get("take_profit") or 0.0)
                        risk = abs(entry - stop)
                        reward = abs(tp - entry)
                        if risk > 0:
                            rr = reward / risk
                    except Exception:
                        rr = None
                if rr is not None:
                    sig.setdefault("risk_reward_ratio", rr)
                    sig.setdefault("rr", rr)
                
                # Timestamp fallback
                if sig.get("timestamp") is None and nested.get("timestamp") is not None:
                    sig["timestamp"] = nested.get("timestamp")
            
            # If we still don't have a type but do have a signal_id, derive a best-effort label.
            if sig.get("signal_type") is None and isinstance(sig.get("signal_id"), str):
                sid = sig["signal_id"]
                # e.g. breakout_long_1767804950.04636 -> breakout_long
                base = sid.rsplit("_", 1)[0] if "_" in sid else sid
                sig["signal_type"] = base
                sig.setdefault("type", base)
            
            return sig
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if signals_file.exists():
                with open(signals_file, "r") as f:
                    for line in f:
                        if line.strip():
                            raw = json.loads(line)
                            signal = _normalize_signal_record(raw)
                            # Filter by timestamp if available
                            ts = (
                                signal.get("timestamp")
                                or signal.get("generated_at")
                                or (signal.get("signal") or {}).get("timestamp")
                                or (signal.get("signal") or {}).get("generated_at")
                            )
                            if ts:
                                try:
                                    signal_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                    if signal_time >= cutoff:
                                        signals.append(signal)
                                except (ValueError, TypeError):
                                    signals.append(signal)
                            else:
                                signals.append(signal)
        except Exception as e:
            logger.error(f"Could not load signals: {e}")
        
        return signals[-100:]  # Limit to last 100
    
    def _load_performance_data(self) -> Optional[Dict[str, Any]]:
        """
        Load performance data from performance.json.

        Supports two formats:
        - Summary dict (expected by analyzers/reports): {"win_rate": ..., "total_trades": ..., "total_pnl": ...}
        - Raw trade list (older format): [{"pnl": ..., "is_win": ...}, ...] -> summarized on load
        """
        try:
            perf_file = self.state_dir / "performance.json"
            if not perf_file.exists():
                return None

            with open(perf_file, "r") as f:
                data = json.load(f)

            if isinstance(data, dict):
                return data

            if isinstance(data, list):
                return self._summarize_trade_performance(data)

            logger.warning(f"Performance data has unexpected type {type(data).__name__}; ignoring")
            return None
        except Exception as e:
            logger.error(f"Could not load performance data: {e}")
            return None

    def _summarize_trade_performance(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Convert a list of trade records into a small summary dict."""
        total_trades = len(trades)
        wins = 0
        total_pnl = 0.0

        by_signal_type: Dict[str, Dict[str, Any]] = {}

        for t in trades:
            if not isinstance(t, dict):
                continue

            is_win = t.get("is_win")
            if is_win is True or t.get("outcome") == "win" or t.get("result") == "win":
                wins += 1

            pnl_raw = t.get("pnl", 0)
            try:
                pnl = float(pnl_raw or 0)
            except (TypeError, ValueError):
                pnl = 0.0
            total_pnl += pnl

            sig_type = t.get("signal_type") or t.get("type") or "unknown"
            m = by_signal_type.setdefault(
                str(sig_type),
                {"count": 0, "wins": 0, "losses": 0, "win_rate": None, "total_pnl": 0.0, "avg_pnl": None},
            )
            m["count"] += 1
            if is_win is True or t.get("outcome") == "win" or t.get("result") == "win":
                m["wins"] += 1
            elif is_win is False or t.get("outcome") == "loss" or t.get("result") == "loss":
                m["losses"] += 1
            m["total_pnl"] += pnl

        losses = total_trades - wins if total_trades else 0
        win_rate = (wins / total_trades) if total_trades else None
        avg_pnl = (total_pnl / total_trades) if total_trades else None

        for m in by_signal_type.values():
            count = int(m.get("count") or 0)
            w = int(m.get("wins") or 0)
            m["win_rate"] = (w / count) if count else None
            m["avg_pnl"] = (float(m.get("total_pnl") or 0.0) / count) if count else None

        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "by_signal_type": by_signal_type,
        }
    
    def _extract_market_data(
        self,
        agent_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Extract market data from agent state."""
        return {
            "futures_market_open": agent_state.get("futures_market_open"),
            "strategy_session_open": agent_state.get("strategy_session_open"),
            "latest_bar": agent_state.get("latest_bar"),
            "latest_bar_timestamp": agent_state.get("latest_bar_timestamp"),
            "data_fresh": agent_state.get("data_fresh"),
            "buy_sell_pressure": agent_state.get("buy_sell_pressure"),
            # Regime snapshot persisted by the agent service (scanner.last_regime)
            "regime": agent_state.get("regime"),
            "regime_timestamp": agent_state.get("regime_timestamp"),
        }

    # ========================================================================
    # Strategy update prompts (market change → operator-confirmed config updates)
    # ========================================================================

    def _detect_strategy_update_transition(
        self,
        prev_regime: Optional[Dict[str, Any]],
        curr_regime: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Detect a meaningful market regime transition worth prompting the operator about.

        We keep this rule-based (fast + deterministic) to avoid calling LLMs every cycle.
        """
        if not isinstance(curr_regime, dict) or not curr_regime:
            return None

        try:
            min_conf = float(self.config.get("strategy_update_min_regime_confidence", 0.55) or 0.55)
        except Exception:
            min_conf = 0.55

        curr_conf = float(curr_regime.get("confidence") or 0.0)
        if curr_conf < min_conf:
            return None

        # If we have no previous regime, we can't detect a transition yet.
        if not isinstance(prev_regime, dict) or not prev_regime:
            return None

        prev_type = str(prev_regime.get("regime") or "unknown")
        curr_type = str(curr_regime.get("regime") or "unknown")
        prev_vol = str(prev_regime.get("volatility") or "unknown")
        curr_vol = str(curr_regime.get("volatility") or "unknown")

        prev_atr_exp = bool(prev_regime.get("atr_expansion", False))
        curr_atr_exp = bool(curr_regime.get("atr_expansion", False))

        reasons: List[str] = []
        if prev_type != curr_type and "unknown" not in (prev_type, curr_type):
            reasons.append(f"regime: {prev_type}→{curr_type}")

        # Treat only *large* volatility jumps as strategy-shifting (low<->high)
        vol_rank = {"low": 1, "normal": 2, "high": 3}
        try:
            if abs(vol_rank.get(curr_vol, 2) - vol_rank.get(prev_vol, 2)) >= 2:
                reasons.append(f"volatility: {prev_vol}→{curr_vol}")
        except Exception:
            pass

        if (not prev_atr_exp) and curr_atr_exp:
            reasons.append("atr_expansion: false→true")

        if not reasons:
            return None

        signature = f"{prev_type}:{prev_vol}:{int(prev_atr_exp)}->{curr_type}:{curr_vol}:{int(curr_atr_exp)}"
        return {
            "signature": signature,
            "prev": prev_regime,
            "curr": curr_regime,
            "curr_conf": curr_conf,
            "reasons": reasons,
        }

    def _should_send_strategy_update_prompt(self, signature: str) -> bool:
        """Rate-limit/deduplicate strategy update prompts."""
        try:
            enabled = bool(self.config.get("strategy_update_prompts_enabled", False))
        except Exception:
            enabled = False
        if not enabled:
            return False

        last = self.monitor_state.get_last_regime_prompt() or {}
        last_sig = str(last.get("signature") or "")
        if last_sig and last_sig == signature:
            return False

        try:
            cooldown = int(self.config.get("strategy_update_prompt_cooldown_seconds", 1800) or 1800)
        except Exception:
            cooldown = 1800

        ts = str(last.get("timestamp") or "")
        if ts:
            try:
                last_dt = datetime.fromisoformat(ts)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < float(cooldown):
                    return False
            except Exception:
                pass

        return True

    async def _send_strategy_update_prompt(
        self,
        transition: Dict[str, Any],
        suggestions: List[Dict[str, Any]],
    ) -> None:
        """Send a Telegram prompt with one-tap buttons to review/apply the best suggestion."""
        if not self._telegram:
            return

        prev = transition.get("prev") or {}
        curr = transition.get("curr") or {}
        reasons = transition.get("reasons") or []

        prev_type = str(prev.get("regime") or "unknown")
        curr_type = str(curr.get("regime") or "unknown")
        prev_vol = str(prev.get("volatility") or "unknown")
        curr_vol = str(curr.get("volatility") or "unknown")
        session = str(curr.get("session") or "unknown")
        conf = float(transition.get("curr_conf") or 0.0)

        def _pretty(x: str) -> str:
            return x.replace("_", " ").title()

        lines: List[str] = [
            "🧠 *Strategy Update Proposed*",
            "",
            f"🔄 *Regime:* {_pretty(prev_type)} → {_pretty(curr_type)}  (conf {conf:.0%})",
            f"🌡️ *Volatility:* {_pretty(prev_vol)} → {_pretty(curr_vol)}",
            f"🕒 *Session:* {_pretty(session)}",
        ]
        if reasons:
            lines += ["", "*Why now:* " + ", ".join(str(r) for r in reasons[:3])]

        # Pick top executable suggestion (config/parameter tune) to feature
        featured = None
        for s in suggestions or []:
            st = str(s.get("type") or "")
            if st in ("config_change", "parameter_tune") and s.get("config_path") and s.get("new_value") is not None:
                featured = s
                break

        if featured:
            title = str(featured.get("title") or "Suggestion").strip()
            cfg_path = str(featured.get("config_path") or "").strip()
            old_val = str(featured.get("old_value")).replace("`", "'")
            new_val = str(featured.get("new_value")).replace("`", "'")
            desc = str(featured.get("description") or "").strip()
            rationale = str(featured.get("rationale") or "").strip()
            sid = str(featured.get("id") or "").strip()

            lines += [
                "",
                "*Top suggestion:*",
                f"🔸 *{title}*",
                f"`{cfg_path}`: `{old_val}` → `{new_val}`",
            ]
            if desc:
                lines.append(f"_{desc[:180]}{'…' if len(desc) > 180 else ''}_")
            if rationale:
                lines.append(f"_Why:_ {rationale[:180]}{'…' if len(rationale) > 180 else ''}")

            msg = "\n".join(lines)

            # Inline buttons (handled by the Telegram command handler service)
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = [
                    [
                        InlineKeyboardButton("✅ Review & Apply", callback_data=f"sug:apply:{sid}"),
                        InlineKeyboardButton("🧪 Dry-run", callback_data=f"sug:dry:{sid}"),
                    ],
                    [
                        InlineKeyboardButton("📋 Suggestions", callback_data="claude_suggestions"),
                        InlineKeyboardButton("🧠 Strategy Review", callback_data="strategy_review"),
                    ],
                    [InlineKeyboardButton("🏠 Menu", callback_data="start")],
                ]
                await self._telegram.send_message(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception:
                # Fallback: message without buttons
                await self._telegram.send_message(msg, parse_mode="Markdown")
        else:
            # No executable config suggestion found; still nudge the operator to review.
            lines += ["", "No safe config change was auto-identified. Tap *Strategy Review* or check *Suggestions*."]
            msg = "\n".join(lines)
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = [
                    [
                        InlineKeyboardButton("🧠 Strategy Review", callback_data="strategy_review"),
                        InlineKeyboardButton("📋 Suggestions", callback_data="claude_suggestions"),
                    ],
                    [InlineKeyboardButton("🏠 Menu", callback_data="start")],
                ]
                await self._telegram.send_message(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception:
                await self._telegram.send_message(msg, parse_mode="Markdown")
    
    async def _send_alert(self, alert: Alert) -> None:
        """Send an alert via Telegram."""
        if not self._telegram:
            logger.info(f"Alert (no Telegram): {alert.title}")
            return
        
        try:
            include_meta = bool(self.config.get("include_alert_metadata", True))
            message = alert.format_telegram(include_metadata=include_meta)
            await self._telegram.send_message(message, parse_mode="Markdown")
            logger.info(f"Alert sent: {alert.title}")
        except Exception as e:
            logger.error(f"Could not send alert: {e}")
    
    async def _send_startup_notification(self) -> None:
        """Send startup notification."""
        if not self._telegram:
            return
        
        try:
            message = (
                "🤖 *Claude Monitor Started*\n\n"
                f"Time: {get_utc_timestamp()}\n"
                f"Claude available: {'✅' if self._claude else '❌'}\n"
                f"Real-time monitoring: {'✅' if self.realtime_monitoring else '❌'}\n"
                f"Daily reports: {'✅' if self.daily_report_enabled else '❌'}\n"
            )
            await self._telegram.send_message(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Could not send startup notification: {e}")
    
    async def _send_shutdown_notification(self) -> None:
        """Send shutdown notification."""
        if not self._telegram:
            return
        
        try:
            uptime = ""
            if self.start_time:
                duration = datetime.now(timezone.utc) - self.start_time
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                uptime = f"Uptime: {hours}h {minutes}m\n"
            
            message = (
                "🛑 *Claude Monitor Stopped*\n\n"
                f"Time: {get_utc_timestamp()}\n"
                f"{uptime}"
                f"Cycles completed: {self._cycle_count}\n"
            )
            await self._telegram.send_message(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Could not send shutdown notification: {e}")
    
    async def _send_error_alert(self, error: str) -> None:
        """Send error alert."""
        alert = Alert(
            level=AlertLevel.CRITICAL,
            title="Claude Monitor Error",
            message=f"Monitor encountered an error:\n`{error}`",
            category="system",
            source="monitor_service",
        )
        await self._send_alert(alert)
    
    async def _check_scheduled_reports(self) -> None:
        """Check and send scheduled reports."""
        now = datetime.now(timezone.utc)
        
        # Check daily report
        if self.daily_report_enabled:
            if self._should_send_daily_report(now):
                await self._send_daily_report()
                self._last_daily_report = now
                self.monitor_state.set_last_daily_report_sent_at(get_utc_timestamp())
        
        # Check weekly report
        if self.weekly_report_enabled:
            if self._should_send_weekly_report(now):
                await self._send_weekly_report()
                self._last_weekly_report = now
                self.monitor_state.set_last_weekly_report_sent_at(get_utc_timestamp())
    
    def _should_send_daily_report(self, now: datetime) -> bool:
        """Check if daily report should be sent."""
        local_now = self._local_now(now)

        # Don't send more than once per local day
        if self._last_daily_report:
            try:
                if self._local_now(self._last_daily_report).date() == local_now.date():
                    return False
            except Exception:
                pass

        # Check time window (within 15 minutes after configured HH:MM)
        try:
            hour, minute = map(int, str(self.daily_report_time).split(":"))
        except Exception:
            return False

        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        delta = (local_now - target).total_seconds()
        return 0 <= delta < 15 * 60
    
    def _should_send_weekly_report(self, now: datetime) -> bool:
        """Check if weekly report should be sent."""
        local_now = self._local_now(now)

        # Don't send more than once per local day (prevents duplicates on restarts)
        if self._last_weekly_report:
            try:
                if self._local_now(self._last_weekly_report).date() == local_now.date():
                    return False
            except Exception:
                pass

        # Check day of week (local)
        days = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        target_day = days.get(str(self.weekly_report_day).lower(), 0)
        if local_now.weekday() != target_day:
            return False

        # Check time window (within 15 minutes after configured HH:MM)
        try:
            hour, minute = map(int, str(self.weekly_report_time).split(":"))
        except Exception:
            return False

        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        delta = (local_now - target).total_seconds()
        return 0 <= delta < 15 * 60
    
    async def _send_daily_report(self) -> None:
        """Generate and send daily report."""
        logger.info("Generating daily report...")
        
        try:
            # Load data for report
            agent_state = self._load_agent_state() or {}
            signals = self._load_recent_signals(lookback_hours=24)
            performance = self._load_performance_data() or {}
            
            # Generate report content
            report = await self._generate_daily_report(agent_state, signals, performance)
            
            if self._telegram:
                await self._telegram.send_message(report, parse_mode="Markdown")
                logger.info("Daily report sent")
        except Exception as e:
            logger.error(f"Could not send daily report: {e}")
    
    async def _generate_daily_report(
        self,
        agent_state: Dict[str, Any],
        signals: List[Dict[str, Any]],
        performance: Dict[str, Any],
    ) -> str:
        """Generate daily report content."""
        lines = [
            "📊 *Daily Claude Monitor Report*",
            f"_{get_utc_timestamp()}_",
            "",
        ]
        
        # Agent status
        running = agent_state.get("running", False)
        paused = agent_state.get("paused", False)
        status_emoji = "🟢" if running and not paused else "🟡" if paused else "🔴"
        lines.append(f"*Agent Status:* {status_emoji} {'Running' if running else 'Stopped'}")
        
        # Signal summary
        lines.append(f"\n*Signals (24h):* {len(signals)}")
        if signals:
            # Count by type
            by_type: Dict[str, int] = {}
            for sig in signals:
                sig_type = sig.get("signal_type", sig.get("type", "unknown"))
                by_type[sig_type] = by_type.get(sig_type, 0) + 1
            
            for sig_type, count in sorted(by_type.items()):
                lines.append(f"  • {sig_type}: {count}")
        
        # Performance summary
        if performance:
            win_rate = performance.get("win_rate")
            if win_rate is not None:
                lines.append(f"\n*Win Rate:* {win_rate:.1%}")
            
            total_pnl = performance.get("total_pnl")
            if total_pnl is not None:
                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                lines.append(f"*P/L:* {pnl_emoji} ${total_pnl:,.2f}")
        
        # System health
        error_count = agent_state.get("error_count", 0)
        consecutive_errors = agent_state.get("consecutive_errors", 0)
        if consecutive_errors > 0:
            lines.append(f"\n⚠️ *Consecutive Errors:* {consecutive_errors}")
        
        # Monitor stats
        stats = self.monitor_state.get_stats()
        lines.append(f"\n*Monitor Stats:*")
        lines.append(f"  • Analyses: {stats.get('analysis_count', 0)}")
        lines.append(f"  • Alerts sent: {stats.get('alert_count', 0)}")
        lines.append(f"  • Active suggestions: {stats.get('active_suggestions', 0)}")
        
        return "\n".join(lines)
    
    async def _send_weekly_report(self) -> None:
        """Generate and send weekly report."""
        logger.info("Generating weekly report...")
        
        try:
            report = await self._generate_weekly_report()
            
            if self._telegram:
                await self._telegram.send_message(report, parse_mode="Markdown")
                logger.info("Weekly report sent")
        except Exception as e:
            logger.error(f"Could not send weekly report: {e}")
    
    async def _generate_weekly_report(self) -> str:
        """Generate weekly report content."""
        lines = [
            "📈 *Weekly Claude Monitor Report*",
            f"_{get_utc_timestamp()}_",
            "",
        ]
        
        # Load week's signals
        signals = self._load_recent_signals(lookback_hours=168)  # 7 days
        
        lines.append(f"*Signals (7d):* {len(signals)}")
        
        # Performance trends
        performance = self._load_performance_data() or {}
        if performance:
            win_rate = performance.get("win_rate")
            if win_rate is not None:
                trend = "📈" if win_rate >= 0.5 else "📉"
                lines.append(f"\n*Win Rate:* {trend} {win_rate:.1%}")
        
        # Monitor statistics
        stats = self.monitor_state.get_stats()
        lines.append(f"\n*Week Summary:*")
        lines.append(f"  • Total analyses: {stats.get('analysis_count', 0)}")
        lines.append(f"  • Alerts sent: {stats.get('alert_count', 0)}")
        lines.append(f"  • Suggestions made: {stats.get('suggestion_count', 0)}")
        lines.append(f"  • Changes applied: {stats.get('applied_count', 0)}")
        
        # Recent applied changes
        changes = self.monitor_state.get_applied_changes(limit=5)
        if changes:
            lines.append(f"\n*Recent Applied Changes:*")
            for change in changes[:3]:
                lines.append(f"  • {change.get('title', 'Unknown')}")
        
        return "\n".join(lines)
    
    # Public API for external commands
    
    async def force_analysis(self, lookback_hours: Optional[int] = None) -> Dict[str, Any]:
        """Force immediate comprehensive analysis.

        Args:
            lookback_hours: Optional override for how many hours of signals to load for analysis.
        """
        logger.info("Forcing comprehensive analysis...")
        
        agent_state = self._load_agent_state() or {}
        try:
            lb = int(lookback_hours) if lookback_hours is not None else int(self.config.get("signal_analysis_lookback_hours", 24))
        except Exception:
            lb = 24
        signals_data = self._load_recent_signals(lookback_hours=lb)
        performance_data = self._load_performance_data()
        market_data = self._extract_market_data(agent_state)
        
        return await self.analysis_engine.analyze_all(
            agent_state=agent_state,
            signals_data=signals_data,
            performance_data=performance_data,
            market_data=market_data,
        )
    
    async def analyze_signals(self) -> Dict[str, Any]:
        """Run signal analysis only."""
        agent_state = self._load_agent_state() or {}
        signals_data = self._load_recent_signals()
        performance_data = self._load_performance_data()
        
        return await self.analysis_engine.analyze_signals_only(
            agent_state=agent_state,
            signals_data=signals_data,
            performance_data=performance_data,
        )
    
    async def analyze_system(self) -> Dict[str, Any]:
        """Run system analysis only."""
        agent_state = self._load_agent_state() or {}
        return await self.analysis_engine.analyze_system_only(agent_state)
    
    async def analyze_market(self) -> Dict[str, Any]:
        """Run market analysis only."""
        agent_state = self._load_agent_state() or {}
        market_data = self._extract_market_data(agent_state)
        return await self.analysis_engine.analyze_market_only(agent_state, market_data)
    
    def get_status(self) -> Dict[str, Any]:
        """Get monitor service status."""
        uptime = None
        if self.start_time:
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        return {
            "running": self.running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime_seconds": uptime,
            "cycle_count": self._cycle_count,
            "last_analysis": self._last_analysis.isoformat() if self._last_analysis else None,
            "claude_available": self._claude is not None,
            "telegram_configured": self._telegram is not None,
            "analysis_engine": self.analysis_engine.get_status(),
            "alert_manager": self.alert_manager.get_stats(),
            "monitor_state": self.monitor_state.get_stats(),
        }
    
    def get_active_suggestions(self) -> List[Dict[str, Any]]:
        """Get active suggestions."""
        return self.monitor_state.get_active_suggestions()
    
    async def apply_suggestion(
        self,
        suggestion_id: str,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Apply a suggestion using the ActionExecutor.
        
        Args:
            suggestion_id: ID of the suggestion to apply
            dry_run: If True, simulate the change without applying
            
        Returns:
            Dict with success status, result details, and rollback info
        """
        suggestion = self.monitor_state.get_suggestion(suggestion_id)
        if not suggestion:
            return {"success": False, "error": "Suggestion not found"}
        
        sug_type = suggestion.get("type", "investigation")
        config_path = suggestion.get("config_path")
        old_value = suggestion.get("old_value")
        new_value = suggestion.get("new_value")
        patch_task = suggestion.get("patch_task")
        files = suggestion.get("files")
        action = suggestion.get("action")
        
        # Determine action type
        if sug_type == "config_change" and config_path:
            action_type = ActionType.CONFIG_UPDATE
        elif sug_type == "parameter_tune" and config_path:
            action_type = ActionType.PARAMETER_TUNE
        elif sug_type == "code_patch":
            # Not safely executable yet: code patches require patch generation and review.
            # Route users to the Telegram Patch Wizard or /ai_patch flow instead of failing later.
            return {
                "success": False,
                "error": "Code patch suggestions require patch generation + manual review (use Patch Wizard or /ai_patch).",
                "suggestion": suggestion,
                "requires_manual": True,
            }
        elif sug_type == "service_action" and action:
            action_type = ActionType.SERVICE_RESTART
        else:
            # Non-executable suggestion (investigation, etc.)
            return {
                "success": False,
                "error": f"Suggestion type '{sug_type}' is not automatically executable",
                "suggestion": suggestion,
                "requires_manual": True,
            }
        
        # Build action request
        request = ActionRequest(
            action_type=action_type,
            description=suggestion.get("description", "Apply suggestion"),
            changes={
                "suggestion_id": suggestion_id,
                "title": suggestion.get("title"),
                "rationale": suggestion.get("rationale"),
            },
            suggestion_id=suggestion_id,
            dry_run=dry_run,
            config_path=config_path,
            old_value=old_value,
            new_value=new_value,
            patch_content=None,  # For code patches, would need to generate
            target_files=files,
            service_name=suggestion.get("service_name", "agent"),
            action=action,
        )
        
        # Execute the action
        try:
            result = await self.action_executor.execute(request)
        except Exception as e:
            logger.error(f"Error executing suggestion {suggestion_id}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "suggestion": suggestion,
            }
        
        # Update suggestion status based on result
        if dry_run:
            # IMPORTANT: Dry-run should not "consume" the suggestion.
            # Keep it pending so the operator can still apply later.
            self.monitor_state.update_suggestion_status(
                suggestion_id,
                "pending",
                {
                    "dry_run": True,
                    "dry_run_success": bool(result.success),
                    "timestamp": get_utc_timestamp(),
                    "request_id": result.request_id,
                    "action_type": result.action_type.value,
                    "status": result.status.value,
                    "message": result.message,
                    "error": result.error,
                },
            )
        elif result.success:
            self.monitor_state.update_suggestion_status(
                suggestion_id,
                "applied",
                {
                    "applied_by": "action_executor",
                    "timestamp": get_utc_timestamp(),
                    "request_id": result.request_id,
                    "can_rollback": result.can_rollback,
                    "rollback_data": result.rollback_data,
                    "dry_run": False,
                },
            )
        else:
            # Some failures are not "real" failures of the suggestion itself (e.g. rate limits,
            # cooldown windows). Keep the suggestion pending so it can be retried later and so
            # we avoid generating duplicate suggestions each cycle.
            status = "failed"
            payload: Dict[str, Any] = {
                "error": result.error,
                "message": result.message,
                "timestamp": get_utc_timestamp(),
                "request_id": result.request_id,
                "deferred": False,
            }

            try:
                now = datetime.now(timezone.utc)
                msg = str(result.message or "")
                err = str(result.error or "")

                def _tomorrow_utc_midnight(dt: datetime) -> datetime:
                    d = (dt + timedelta(days=1)).date()
                    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

                # ActionExecutor's top-level rate limit (daily cap)
                if err == "rate_limit_exceeded":
                    status = "pending"
                    payload["deferred"] = True
                    payload["defer_until_utc"] = _tomorrow_utc_midnight(now).isoformat()

                # Policy rejections: treat cooldown/daily limit as deferred, others as failed.
                if err == "policy_rejected":
                    low = msg.lower()
                    if "daily limit reached" in low:
                        status = "pending"
                        payload["deferred"] = True
                        payload["defer_until_utc"] = _tomorrow_utc_midnight(now).isoformat()
                    elif "cooldown active" in low:
                        # Example: "Cooldown active for 'signals.min_confidence' (3599s remaining)"
                        import re

                        m = re.search(r"\\((\\d+)s remaining\\)", msg)
                        if m:
                            seconds = int(m.group(1))
                            status = "pending"
                            payload["deferred"] = True
                            payload["defer_until_utc"] = (now + timedelta(seconds=seconds)).isoformat()
            except Exception:
                pass

            self.monitor_state.update_suggestion_status(suggestion_id, status, payload)
        
        return {
            "success": result.success,
            "message": result.message,
            "request_id": result.request_id,
            "action_type": result.action_type.value,
            "status": result.status.value,
            "can_rollback": result.can_rollback,
            "rollback_data": result.rollback_data,
            "error": result.error,
            "suggestion": suggestion,
            "dry_run": dry_run,
        }
    
    def apply_suggestion_sync(
        self,
        suggestion_id: str,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Synchronous wrapper for apply_suggestion.
        
        Creates an event loop if needed for use from sync code.
        """
        try:
            loop = asyncio.get_running_loop()
            # Already in async context, create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self.apply_suggestion(suggestion_id, dry_run)
                )
                return future.result(timeout=60)
        except RuntimeError:
            # No running loop, use asyncio.run directly
            return asyncio.run(self.apply_suggestion(suggestion_id, dry_run))
    
    async def rollback_suggestion(self, request_id: str) -> Dict[str, Any]:
        """
        Rollback a previously applied suggestion.
        
        Args:
            request_id: The request_id from the original apply result
            
        Returns:
            Dict with rollback result
        """
        try:
            result = await self.action_executor.rollback(request_id)
            return {
                "success": result.success,
                "message": result.message,
                "request_id": request_id,
                "status": result.status.value,
                "error": result.error,
            }
        except Exception as e:
            logger.error(f"Error rolling back {request_id}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "request_id": request_id,
            }
    
    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Dismiss a suggestion."""
        return self.monitor_state.update_suggestion_status(suggestion_id, "dismissed")


async def main() -> None:
    """Main entry point for running monitor service."""
    import os
    from pearlalgo.config.config_file import load_config_yaml, log_config_warnings
    
    # Load configuration
    config = load_config_yaml()
    if config:
        # Best-effort warnings (unknown sections / type mismatches) — never raises.
        try:
            log_config_warnings(config)
        except Exception:
            pass
    claude_config = (config or {}).get("claude_monitor", {}) or {}
    
    # Get Telegram credentials from environment
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    # Create and run service
    service = ClaudeMonitorService(
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        config=claude_config,
    )
    
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())




