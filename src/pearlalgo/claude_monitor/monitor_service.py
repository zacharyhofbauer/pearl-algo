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

# Claude client (optional [llm] extra)
try:
    from pearlalgo.utils.claude_client import ClaudeClient, get_claude_client, ANTHROPIC_AVAILABLE
except ImportError:
    ClaudeClient = None  # type: ignore
    get_claude_client = lambda: None  # type: ignore
    ANTHROPIC_AVAILABLE = False


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
        )
        
        self.alert_manager = AlertManager(
            dedup_window_seconds=self.config.get("dedup_window_seconds", 900),
            quiet_start=self.config.get("quiet_hours_start"),
            quiet_end=self.config.get("quiet_hours_end"),
            timezone_name=self.timezone_name,
            suppress_info_during_quiet=self.config.get("suppress_info_during_quiet", True),
            max_alerts_per_hour=self.config.get("max_alerts_per_hour", 20),
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
        
        logger.info(
            f"Claude Monitor Service initialized "
            f"(auto_apply={self.auto_apply_enabled}, max_auto={self.max_auto_changes_per_day})"
        )

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
        if not ANTHROPIC_AVAILABLE:
            logger.warning("Claude not available: anthropic package not installed")
            return
        
        try:
            self._claude = get_claude_client()
            if self._claude:
                logger.info("Claude client initialized for monitoring")
            else:
                logger.warning("Claude client not available (check ANTHROPIC_API_KEY)")
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
            self.monitor_state.record_analysis(
                analysis=analysis,
                suggestions=[s.to_dict() for s in suggestions],
            )
            
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
            
            try:
                logger.info(f"Auto-applying suggestion {suggestion_id}: {sug_dict.get('title')}")
                result = await self.apply_suggestion(suggestion_id, dry_run=False)
                
                if result.get("success"):
                    self._auto_apply_count_today += 1
                    
                    # Send Telegram notification
                    await self._send_auto_apply_notification(sug_dict, result, success=True)
                    
                    logger.info(
                        f"Auto-apply SUCCESS: {suggestion_id} "
                        f"({sug_dict.get('config_path')} = {sug_dict.get('new_value')})"
                    )
                else:
                    # Send failure notification
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
    ) -> None:
        """Send Telegram notification for auto-applied changes."""
        if not self._telegram:
            return
        
        try:
            if success:
                message = (
                    "🤖 *Auto-Applied Config Change*\n\n"
                    f"*{suggestion.get('title', 'Config Update')}*\n\n"
                    f"*Path:* `{suggestion.get('config_path')}`\n"
                    f"*Old:* `{suggestion.get('old_value')}`\n"
                    f"*New:* `{suggestion.get('new_value')}`\n\n"
                    f"*Request ID:* `{result.get('request_id')}`\n"
                    f"*Rollback:* `/rollback_suggestion {result.get('request_id')}`\n\n"
                    f"_{suggestion.get('rationale', '')[:150]}_"
                )
            else:
                message = (
                    "⚠️ *Auto-Apply Failed*\n\n"
                    f"*{suggestion.get('title', 'Config Update')}*\n\n"
                    f"*Path:* `{suggestion.get('config_path')}`\n"
                    f"*Error:* {result.get('error', 'Unknown')[:150]}\n\n"
                    "The suggestion was not applied."
                )
            
            await self._telegram.send_message(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Could not send auto-apply notification: {e}")
    
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
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if signals_file.exists():
                with open(signals_file, "r") as f:
                    for line in f:
                        if line.strip():
                            signal = json.loads(line)
                            # Filter by timestamp if available
                            ts = signal.get("timestamp") or signal.get("generated_at")
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
        }
    
    async def _send_alert(self, alert: Alert) -> None:
        """Send an alert via Telegram."""
        if not self._telegram:
            logger.info(f"Alert (no Telegram): {alert.title}")
            return
        
        try:
            message = alert.format_telegram()
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
            self.monitor_state.update_suggestion_status(
                suggestion_id,
                "failed",
                {
                    "error": result.error,
                    "timestamp": get_utc_timestamp(),
                    "request_id": result.request_id,
                },
            )
        
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
    from pearlalgo.config.config_loader import load_service_config
    
    # Load configuration
    config = load_service_config()
    claude_config = config.get("claude_monitor", {})
    
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




