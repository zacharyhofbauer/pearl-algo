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
            suppress_info_during_quiet=self.config.get("suppress_info_during_quiet", True),
            max_alerts_per_hour=self.config.get("max_alerts_per_hour", 20),
        )
        
        self.suggestion_engine = SuggestionEngine(
            claude_client=self._claude,
            max_suggestions_per_analysis=self.config.get("max_suggestions_per_analysis", 5),
        )
        
        self.monitor_state = MonitorState(state_dir=state_dir)
        
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
        self._last_daily_report: Optional[datetime] = None
        self._last_weekly_report: Optional[datetime] = None
        self._cycle_count = 0
        
        logger.info("Claude Monitor Service initialized")
    
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
            
            # Check for scheduled reports
            await self._check_scheduled_reports()
            
        except Exception as e:
            logger.error(f"Monitor cycle error: {e}")
    
    def _get_next_interval(self) -> float:
        """Determine next monitoring interval."""
        if self.realtime_monitoring:
            return self.realtime_interval
        return self.frequent_interval
    
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
        """Load performance data from performance.json."""
        try:
            perf_file = self.state_dir / "performance.json"
            if perf_file.exists():
                with open(perf_file, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Could not load performance data: {e}")
        return None
    
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
        
        # Check weekly report
        if self.weekly_report_enabled:
            if self._should_send_weekly_report(now):
                await self._send_weekly_report()
                self._last_weekly_report = now
    
    def _should_send_daily_report(self, now: datetime) -> bool:
        """Check if daily report should be sent."""
        if self._last_daily_report:
            # Don't send more than once per day
            if (now - self._last_daily_report) < timedelta(hours=20):
                return False
        
        # Check if it's the right time (approximate)
        try:
            hour, minute = map(int, self.daily_report_time.split(":"))
            if now.hour == hour and now.minute < 15:  # Within first 15 min of hour
                return True
        except (ValueError, AttributeError):
            pass
        
        return False
    
    def _should_send_weekly_report(self, now: datetime) -> bool:
        """Check if weekly report should be sent."""
        if self._last_weekly_report:
            if (now - self._last_weekly_report) < timedelta(days=6):
                return False
        
        # Check day of week
        days = {
            "monday": 0, "tuesday": 1, "wednesday": 2,
            "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
        }
        target_day = days.get(self.weekly_report_day.lower(), 0)
        
        if now.weekday() != target_day:
            return False
        
        # Check time
        try:
            hour, minute = map(int, self.weekly_report_time.split(":"))
            if now.hour == hour and now.minute < 15:
                return True
        except (ValueError, AttributeError):
            pass
        
        return False
    
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
    
    async def force_analysis(self) -> Dict[str, Any]:
        """Force immediate comprehensive analysis."""
        logger.info("Forcing comprehensive analysis...")
        
        agent_state = self._load_agent_state() or {}
        signals_data = self._load_recent_signals()
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
    
    def apply_suggestion(self, suggestion_id: str) -> Dict[str, Any]:
        """Apply a suggestion (placeholder for action executor)."""
        # This will be expanded in the action executor task
        suggestion = self.monitor_state.get_suggestion(suggestion_id)
        if not suggestion:
            return {"success": False, "error": "Suggestion not found"}
        
        # For now, just mark as applied
        self.monitor_state.update_suggestion_status(
            suggestion_id,
            "applied",
            {"applied_by": "manual", "timestamp": get_utc_timestamp()},
        )
        
        return {"success": True, "suggestion": suggestion}
    
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


