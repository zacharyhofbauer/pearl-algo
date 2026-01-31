"""
Pearl Suggestions Engine - Pearl-style proactive suggestions for the Telegram bot.

Pearl can proactively suggest helpful actions based on system state, but:
- Always asks permission before taking action
- Suggestions are dismissible
- Respects cooldowns to avoid being annoying
- Users can call /pearl anytime to chat directly

Design principles:
- Polite: "Want me to...?", "Shall I...?"
- Concise: Gets to the point
- Helpful: Anticipates needs based on context
- Respectful: Accepts "no" gracefully (suggestion just disappears)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Optional

from pearlalgo.utils.logger import logger


class SuggestionPriority(IntEnum):
    """Priority levels for suggestions. Lower = higher priority."""
    CRITICAL = 1   # Problems that need attention (gateway down, etc.)
    IMPORTANT = 2  # Milestones, end of day, etc.
    HELPFUL = 3    # Tips, insights, greetings


@dataclass
class PearlSuggestion:
    """A dismissible suggestion from Pearl."""
    
    message: str
    """The suggestion text (Pearl's voice)."""
    
    accept_label: str
    """Button label for accepting (e.g., "Yes please", "Show me")."""
    
    accept_action: str
    """Callback data when user accepts."""
    
    priority: SuggestionPriority = SuggestionPriority.HELPFUL
    """Priority level (1=critical, 2=important, 3=helpful)."""
    
    cooldown_key: str = ""
    """Key for cooldown tracking (prevents same suggestion repeating)."""
    
    decline_label: str = "Dismiss"
    """Button label for dismissing (default: "Dismiss")."""


@dataclass
class SuggestionState:
    """Tracks suggestion cooldowns and user interactions."""
    
    cooldowns: dict[str, float] = field(default_factory=dict)
    """Map of cooldown_key -> last_shown_timestamp."""
    
    last_greeting_date: Optional[str] = None
    """Date (YYYY-MM-DD) of last greeting shown."""
    
    interaction_count: int = 0
    """Number of interactions in current session (for tips)."""
    
    last_interaction_time: float = 0.0
    """Timestamp of last user interaction."""


class PearlSuggestionEngine:
    """
    Generates contextual, polite suggestions based on system state.
    
    All suggestions are dismissible - user can tap [Dismiss] and they go away.
    Cooldowns prevent the same suggestion from repeating too quickly.
    """
    
    # Default cooldown periods (in seconds)
    DEFAULT_COOLDOWN_MINUTES = 30
    GREETING_COOLDOWN_HOURS = 8
    PROBLEM_COOLDOWN_MINUTES = 5  # Problems can repeat more frequently
    
    def __init__(self, state_dir: Optional[str] = None):
        """
        Initialize the suggestion engine.
        
        Args:
            state_dir: Optional directory to persist suggestion state
        """
        self._state = SuggestionState()
        self._state_dir = state_dir
        self._load_state()
    
    def _load_state(self) -> None:
        """Load suggestion state from disk."""
        if not self._state_dir:
            return
        
        import json
        from pathlib import Path
        
        state_file = Path(self._state_dir) / "pearl_suggestion_state.json"
        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    data = json.load(f)
                self._state.cooldowns = data.get("cooldowns", {})
                self._state.last_greeting_date = data.get("last_greeting_date")
            except Exception as e:
                logger.warning(f"Could not load Pearl suggestion state: {e}")
    
    def _save_state(self) -> None:
        """Save suggestion state to disk."""
        if not self._state_dir:
            return
        
        import json
        from pathlib import Path
        
        state_file = Path(self._state_dir) / "pearl_suggestion_state.json"
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(state_file, "w") as f:
                json.dump({
                    "cooldowns": self._state.cooldowns,
                    "last_greeting_date": self._state.last_greeting_date,
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save Pearl suggestion state: {e}")
    
    def _is_on_cooldown(self, key: str, cooldown_minutes: float) -> bool:
        """Check if a suggestion is on cooldown."""
        if not key:
            return False
        last_shown = self._state.cooldowns.get(key, 0)
        cooldown_seconds = cooldown_minutes * 60
        return (time.time() - last_shown) < cooldown_seconds
    
    def _mark_shown(self, key: str) -> None:
        """Mark a suggestion as shown (start cooldown)."""
        if key:
            self._state.cooldowns[key] = time.time()
            self._save_state()
    
    def mark_dismissed(self, key: str) -> None:
        """
        Mark a suggestion as dismissed by user.
        
        This starts the cooldown timer so the same suggestion won't
        appear again for a while.
        """
        self._mark_shown(key)
    
    def generate_suggestion(
        self,
        state: dict[str, Any],
        prefs: Optional[dict[str, Any]] = None,
        context: str = "dashboard",
    ) -> Optional[PearlSuggestion]:
        """
        Generate a suggestion based on current system state.
        
        Args:
            state: System state dictionary with keys like:
                - agent_running: bool
                - gateway_running: bool
                - data_stale: bool
                - data_age_minutes: float
                - daily_pnl: float
                - wins_today: int
                - losses_today: int
                - signals_today: int
                - last_signal_minutes: float
                - session_open: bool
                - futures_open: bool
                - agent_uptime_hours: float
            prefs: User preferences (optional)
            context: Where suggestion will appear ("dashboard", "activity", etc.)
        
        Returns:
            PearlSuggestion if one is appropriate, None otherwise.
        """
        prefs = prefs or {}
        
        # Check if suggestions are enabled
        if not prefs.get("pearl_suggestions_enabled", True):
            return None
        
        # User-configurable cooldown
        cooldown_minutes = prefs.get(
            "pearl_suggestion_cooldown_minutes",
            self.DEFAULT_COOLDOWN_MINUTES
        )
        
        # Priority order: problems > milestones > greetings > tips
        suggestions = [
            self._check_problem(state, cooldown_minutes),
            self._check_risk_drawdown(state, cooldown_minutes),
            self._check_milestone(state, cooldown_minutes),
            self._check_greeting(state, prefs),
            self._check_end_of_day(state, cooldown_minutes),
            self._check_market_quiet(state, cooldown_minutes),
        ]
        
        # Return first non-None suggestion (highest priority first)
        for suggestion in suggestions:
            if suggestion is not None:
                # Mark as shown to start cooldown
                self._mark_shown(suggestion.cooldown_key)
                return suggestion
        
        return None
    
    def _check_problem(
        self,
        state: dict[str, Any],
        cooldown_minutes: float,
    ) -> Optional[PearlSuggestion]:
        """Check for problems that need attention (Priority 1)."""
        
        # Gateway down
        if state.get("gateway_running") is False:
            key = "problem_gateway_down"
            if not self._is_on_cooldown(key, self.PROBLEM_COOLDOWN_MINUTES):
                return PearlSuggestion(
                    message="Heads up - the gateway is disconnected. Want me to try reconnecting?",
                    accept_label="Yes, reconnect",
                    accept_action="pearl:reconnect_gateway",
                    priority=SuggestionPriority.CRITICAL,
                    cooldown_key=key,
                )
        
        # Data stale
        data_age = state.get("data_age_minutes", 0)
        if state.get("data_stale") is True or data_age > 10:
            key = "problem_data_stale"
            if not self._is_on_cooldown(key, self.PROBLEM_COOLDOWN_MINUTES):
                age_str = f"{int(data_age)}m" if data_age < 60 else f"{data_age/60:.1f}h"
                return PearlSuggestion(
                    message=f"Data hasn't updated in {age_str}. Want me to check the connection?",
                    accept_label="Yes, check it",
                    accept_action="pearl:check_data",
                    priority=SuggestionPriority.CRITICAL,
                    cooldown_key=key,
                )
        
        # Agent stopped but should be running (during market hours)
        if (state.get("agent_running") is False and 
            state.get("futures_open") is True and
            state.get("session_open") is True):
            key = "problem_agent_stopped"
            if not self._is_on_cooldown(key, self.PROBLEM_COOLDOWN_MINUTES):
                return PearlSuggestion(
                    message="Agent is stopped but markets are open. Want me to start it?",
                    accept_label="Yes, start",
                    accept_action="pearl:start_agent",
                    priority=SuggestionPriority.CRITICAL,
                    cooldown_key=key,
                )
        
        return None
    
    def _check_milestone(
        self,
        state: dict[str, Any],
        cooldown_minutes: float,
    ) -> Optional[PearlSuggestion]:
        """Check for performance milestones (Priority 2)."""
        
        daily_pnl = state.get("daily_pnl", 0)
        state.get("wins_today", 0)
        
        # Big profit day ($300+)
        if daily_pnl >= 300:
            key = f"milestone_profit_{int(daily_pnl // 100) * 100}"
            if not self._is_on_cooldown(key, cooldown_minutes):
                return PearlSuggestion(
                    message=f"Nice! You're up ${daily_pnl:.0f} today. Want to see what's working?",
                    accept_label="Show me",
                    accept_action="pearl:show_performance",
                    priority=SuggestionPriority.IMPORTANT,
                    cooldown_key=key,
                )
        
        # Win streak (3+)
        win_streak = state.get("win_streak", 0)
        if win_streak >= 3:
            key = f"milestone_streak_{win_streak}"
            if not self._is_on_cooldown(key, cooldown_minutes):
                return PearlSuggestion(
                    message=f"You're on a {win_streak}-win streak! Want the breakdown?",
                    accept_label="Show me",
                    accept_action="pearl:show_performance",
                    priority=SuggestionPriority.IMPORTANT,
                    cooldown_key=key,
                )
        
        return None

    def _check_risk_drawdown(
        self,
        state: dict[str, Any],
        cooldown_minutes: float,
    ) -> Optional[PearlSuggestion]:
        """Warn about drawdown (Priority 2)."""
        session_pnl = float(state.get("risk_session_pnl", 0) or 0.0)
        daily_pnl = float(state.get("risk_daily_pnl", 0) or 0.0)

        if daily_pnl <= -500 or session_pnl <= -500:
            key = "risk_drawdown"
            if not self._is_on_cooldown(key, cooldown_minutes):
                pnl_val = daily_pnl if daily_pnl != 0 else session_pnl
                sign = "-" if pnl_val < 0 else "+"
                return PearlSuggestion(
                    message=f"You’re down {sign}${abs(pnl_val):.0f}. Want the incident report?",
                    accept_label="Show report",
                    accept_action="pearl:show_risk_report",
                    priority=SuggestionPriority.IMPORTANT,
                    cooldown_key=key,
                )

        return None
    
    def _check_greeting(
        self,
        state: dict[str, Any],
        prefs: dict[str, Any],
    ) -> Optional[PearlSuggestion]:
        """Check if we should show a greeting (Priority 3)."""
        
        if not prefs.get("pearl_greeting_enabled", True):
            return None
        
        # Get current time in ET
        try:
            import pytz
            et_tz = pytz.timezone('US/Eastern')
            now_et = datetime.now(et_tz)
            today_str = now_et.strftime("%Y-%m-%d")
            hour = now_et.hour
        except Exception:
            return None
        
        # Only greet once per day
        if self._state.last_greeting_date == today_str:
            return None
        
        # Morning greeting (5 AM - 10 AM ET)
        if 5 <= hour < 10:
            uptime_hours = state.get("agent_uptime_hours", 0)
            overnight_pnl = state.get("overnight_pnl", 0)
            
            if uptime_hours > 6:
                msg = f"Good morning! Agent's been running for {uptime_hours:.0f}h."
                if overnight_pnl != 0:
                    sign = "+" if overnight_pnl >= 0 else ""
                    msg += f" {sign}${overnight_pnl:.0f} overnight."
                msg += " Want the overnight summary?"
            else:
                msg = "Good morning! Ready to trade. Want a quick status check?"
            
            self._state.last_greeting_date = today_str
            self._save_state()
            
            return PearlSuggestion(
                message=msg,
                accept_label="Yes please",
                accept_action="pearl:show_overnight",
                priority=SuggestionPriority.HELPFUL,
                cooldown_key="greeting_morning",
            )
        
        return None
    
    def _check_end_of_day(
        self,
        state: dict[str, Any],
        cooldown_minutes: float,
    ) -> Optional[PearlSuggestion]:
        """Check if it's end of day (Priority 2)."""
        
        try:
            import pytz
            et_tz = pytz.timezone('US/Eastern')
            now_et = datetime.now(et_tz)
            hour = now_et.hour
            minute = now_et.minute
        except Exception:
            return None
        
        # End of day window: 3:45 PM - 3:55 PM ET
        if not (hour == 15 and 45 <= minute <= 55):
            return None
        
        key = "eod_summary"
        if self._is_on_cooldown(key, cooldown_minutes * 2):  # Longer cooldown for EOD
            return None
        
        daily_pnl = state.get("daily_pnl", 0)
        wins = state.get("wins_today", 0)
        losses = state.get("losses_today", 0)
        trades = wins + losses
        
        if trades > 0:
            wr = (wins / trades) * 100
            sign = "+" if daily_pnl >= 0 else ""
            msg = (
                "Safety window active: stop new trades after 3:45 PM ET; "
                "flatten by 3:55 PM ET. "
                f"Today: {trades} trades, {sign}${daily_pnl:.0f}, {wr:.0f}% WR. "
                "Want the summary?"
            )
        else:
            msg = (
                "Safety window active: stop new trades after 3:45 PM ET; "
                "flatten by 3:55 PM ET. "
                "No trades today. Want to review the signals?"
            )
        
        return PearlSuggestion(
            message=msg,
            accept_label="Yes",
            accept_action="pearl:show_daily_summary",
            priority=SuggestionPriority.IMPORTANT,
            cooldown_key=key,
        )
    
    def _check_market_quiet(
        self,
        state: dict[str, Any],
        cooldown_minutes: float,
    ) -> Optional[PearlSuggestion]:
        """Check if markets have been quiet (Priority 3)."""
        
        # Only during market hours
        if not state.get("session_open"):
            return None
        
        last_signal_minutes = state.get("last_signal_minutes", 0)
        
        # No signals in 2+ hours
        if last_signal_minutes >= 120:
            key = "quiet_market"
            if self._is_on_cooldown(key, cooldown_minutes):
                return None
            
            hours = last_signal_minutes / 60
            return PearlSuggestion(
                message=f"Markets have been quiet - no signals in {hours:.1f}h. Want a performance check while we wait?",
                accept_label="Sure",
                accept_action="pearl:show_performance",
                priority=SuggestionPriority.HELPFUL,
                cooldown_key=key,
            )
        
        return None


# Singleton instance (lazily initialized)
_engine: Optional[PearlSuggestionEngine] = None


def get_suggestion_engine(state_dir: Optional[str] = None) -> PearlSuggestionEngine:
    """Get or create the global suggestion engine instance."""
    global _engine
    if _engine is None:
        _engine = PearlSuggestionEngine(state_dir)
    return _engine
