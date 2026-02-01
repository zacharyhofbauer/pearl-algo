"""
Pearl AI Shadow Tracker - Track AI suggestions and their hypothetical outcomes.

This module tracks what would have happened if the trader had followed Pearl's
suggestions. It operates in "shadow mode" - recording outcomes without affecting
actual trading, to build confidence in the AI's recommendations.

Key Metrics Tracked:
- Suggestions made vs followed vs dismissed
- "Would have saved" - losses avoided by following suggestions
- "Would have made" - gains from following suggestions
- Suggestion accuracy rate
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger


class SuggestionType(str, Enum):
    """Types of suggestions Pearl can make."""
    RISK_ALERT = "risk_alert"           # Warning about drawdown/losses
    PATTERN_INSIGHT = "pattern_insight"  # Trading pattern identified
    DIRECTION_BIAS = "direction_bias"    # Long/short bias suggestion
    SIZE_REDUCTION = "size_reduction"    # Reduce position size
    PAUSE_TRADING = "pause_trading"      # Take a break
    OPPORTUNITY = "opportunity"          # Good setup identified
    SESSION_ADVICE = "session_advice"    # Time-of-day guidance


class SuggestionOutcome(str, Enum):
    """Outcome of a suggestion."""
    PENDING = "pending"      # Suggestion active, not yet resolved
    FOLLOWED = "followed"    # User accepted the suggestion
    DISMISSED = "dismissed"  # User dismissed the suggestion
    EXPIRED = "expired"      # Suggestion expired (no action taken)


@dataclass
class TrackedSuggestion:
    """A suggestion with tracking data."""
    id: str
    timestamp: str
    suggestion_type: str
    message: str
    action: str
    outcome: str = SuggestionOutcome.PENDING.value

    # Context at time of suggestion
    pnl_at_suggestion: float = 0.0
    wins_at_suggestion: int = 0
    losses_at_suggestion: int = 0
    active_positions: int = 0

    # Outcome tracking (filled in after resolution)
    resolved_at: Optional[str] = None
    pnl_at_resolution: Optional[float] = None
    actual_pnl_change: Optional[float] = None

    # Hypothetical outcome (what would have happened if followed)
    hypothetical_pnl_change: Optional[float] = None
    would_have_saved: Optional[float] = None
    would_have_made: Optional[float] = None

    # For shadow tracking specific suggestions
    trades_after: int = 0
    wins_after: int = 0
    losses_after: int = 0


@dataclass
class ShadowMetrics:
    """Aggregate shadow tracking metrics."""
    total_suggestions: int = 0
    suggestions_followed: int = 0
    suggestions_dismissed: int = 0
    suggestions_expired: int = 0

    # Financial impact tracking
    total_would_have_saved: float = 0.0  # Losses avoided
    total_would_have_made: float = 0.0   # Additional gains
    net_shadow_impact: float = 0.0       # Total hypothetical benefit

    # Accuracy metrics
    correct_suggestions: int = 0
    incorrect_suggestions: int = 0
    accuracy_rate: float = 0.0

    # By type breakdown
    by_type: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Recent suggestions for display
    recent_suggestions: List[Dict[str, Any]] = field(default_factory=list)

    # Current active suggestion
    active_suggestion: Optional[Dict[str, Any]] = None


class PearlShadowTracker:
    """
    Tracks Pearl AI suggestions and their hypothetical outcomes.

    This enables "shadow mode" - the AI makes suggestions, we track what
    would have happened if they were followed, building a track record
    before enabling actual automated actions.
    """

    # How long a suggestion stays active before expiring (seconds)
    SUGGESTION_TTL_SECONDS = 3600  # 1 hour

    # Max recent suggestions to keep in memory
    MAX_RECENT_SUGGESTIONS = 50

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize the shadow tracker.

        Args:
            state_dir: Directory to persist tracking data
        """
        self.state_dir = state_dir
        self._suggestions: List[TrackedSuggestion] = []
        self._active_suggestion: Optional[TrackedSuggestion] = None
        self._metrics = ShadowMetrics()
        self._last_pnl: float = 0.0
        self._last_wins: int = 0
        self._last_losses: int = 0

        if state_dir:
            self._load_state()

    def _get_state_file(self) -> Optional[Path]:
        """Get path to state file."""
        if not self.state_dir:
            return None
        return Path(self.state_dir) / "pearl_shadow_state.json"

    def _load_state(self) -> None:
        """Load tracking state from disk."""
        state_file = self._get_state_file()
        if not state_file or not state_file.exists():
            return

        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))

            # Restore suggestions
            self._suggestions = [
                TrackedSuggestion(**s) for s in data.get("suggestions", [])
            ]

            # Restore active suggestion
            active = data.get("active_suggestion")
            if active:
                self._active_suggestion = TrackedSuggestion(**active)

            # Restore metrics
            metrics_data = data.get("metrics", {})
            self._metrics = ShadowMetrics(
                total_suggestions=metrics_data.get("total_suggestions", 0),
                suggestions_followed=metrics_data.get("suggestions_followed", 0),
                suggestions_dismissed=metrics_data.get("suggestions_dismissed", 0),
                suggestions_expired=metrics_data.get("suggestions_expired", 0),
                total_would_have_saved=metrics_data.get("total_would_have_saved", 0.0),
                total_would_have_made=metrics_data.get("total_would_have_made", 0.0),
                net_shadow_impact=metrics_data.get("net_shadow_impact", 0.0),
                correct_suggestions=metrics_data.get("correct_suggestions", 0),
                incorrect_suggestions=metrics_data.get("incorrect_suggestions", 0),
                accuracy_rate=metrics_data.get("accuracy_rate", 0.0),
                by_type=metrics_data.get("by_type", {}),
            )

            logger.debug(f"Loaded Pearl shadow state: {len(self._suggestions)} suggestions")

        except Exception as e:
            logger.warning(f"Could not load Pearl shadow state: {e}")

    def _save_state(self) -> None:
        """Save tracking state to disk."""
        state_file = self._get_state_file()
        if not state_file:
            return

        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)

            # Only keep recent suggestions in persistent storage
            recent = self._suggestions[-self.MAX_RECENT_SUGGESTIONS:]

            data = {
                "suggestions": [asdict(s) for s in recent],
                "active_suggestion": asdict(self._active_suggestion) if self._active_suggestion else None,
                "metrics": {
                    "total_suggestions": self._metrics.total_suggestions,
                    "suggestions_followed": self._metrics.suggestions_followed,
                    "suggestions_dismissed": self._metrics.suggestions_dismissed,
                    "suggestions_expired": self._metrics.suggestions_expired,
                    "total_would_have_saved": self._metrics.total_would_have_saved,
                    "total_would_have_made": self._metrics.total_would_have_made,
                    "net_shadow_impact": self._metrics.net_shadow_impact,
                    "correct_suggestions": self._metrics.correct_suggestions,
                    "incorrect_suggestions": self._metrics.incorrect_suggestions,
                    "accuracy_rate": self._metrics.accuracy_rate,
                    "by_type": self._metrics.by_type,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        except Exception as e:
            logger.warning(f"Could not save Pearl shadow state: {e}")

    def record_suggestion(
        self,
        suggestion_type: str,
        message: str,
        action: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Record a new suggestion from Pearl AI.

        Args:
            suggestion_type: Type of suggestion (risk_alert, pattern_insight, etc.)
            message: The suggestion message
            action: The suggested action
            context: Current trading context (pnl, wins, losses, etc.)

        Returns:
            Suggestion ID
        """
        # Expire any existing active suggestion
        if self._active_suggestion:
            self._resolve_suggestion(
                self._active_suggestion.id,
                SuggestionOutcome.EXPIRED,
                context,
            )

        # Create new suggestion
        suggestion_id = f"pearl_{int(time.time() * 1000)}"

        suggestion = TrackedSuggestion(
            id=suggestion_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            suggestion_type=suggestion_type,
            message=message,
            action=action,
            pnl_at_suggestion=float(context.get("daily_pnl", 0) or 0),
            wins_at_suggestion=int(context.get("wins_today", 0) or 0),
            losses_at_suggestion=int(context.get("losses_today", 0) or 0),
            active_positions=int(context.get("active_positions", 0) or 0),
        )

        self._active_suggestion = suggestion
        self._suggestions.append(suggestion)
        self._metrics.total_suggestions += 1

        # Update by-type metrics
        if suggestion_type not in self._metrics.by_type:
            self._metrics.by_type[suggestion_type] = {
                "count": 0,
                "followed": 0,
                "dismissed": 0,
                "would_have_saved": 0.0,
                "would_have_made": 0.0,
            }
        self._metrics.by_type[suggestion_type]["count"] += 1

        # Store last known state for comparison
        self._last_pnl = suggestion.pnl_at_suggestion
        self._last_wins = suggestion.wins_at_suggestion
        self._last_losses = suggestion.losses_at_suggestion

        self._save_state()
        logger.info(f"Pearl suggestion recorded: {suggestion_type} - {message[:50]}...")

        return suggestion_id

    def mark_followed(
        self,
        suggestion_id: str,
        context: Dict[str, Any],
    ) -> None:
        """Mark a suggestion as followed by the user."""
        self._resolve_suggestion(suggestion_id, SuggestionOutcome.FOLLOWED, context)

    def mark_dismissed(
        self,
        suggestion_id: str,
        context: Dict[str, Any],
    ) -> None:
        """Mark a suggestion as dismissed by the user."""
        self._resolve_suggestion(suggestion_id, SuggestionOutcome.DISMISSED, context)

    def _resolve_suggestion(
        self,
        suggestion_id: str,
        outcome: SuggestionOutcome,
        context: Dict[str, Any],
    ) -> None:
        """Resolve a suggestion and calculate hypothetical impact."""
        suggestion = None
        for s in self._suggestions:
            if s.id == suggestion_id:
                suggestion = s
                break

        if not suggestion:
            logger.warning(f"Suggestion not found: {suggestion_id}")
            return

        if suggestion.outcome != SuggestionOutcome.PENDING.value:
            return  # Already resolved

        # Record outcome
        suggestion.outcome = outcome.value
        suggestion.resolved_at = datetime.now(timezone.utc).isoformat()

        # Get current state
        current_pnl = float(context.get("daily_pnl", 0) or 0)
        current_wins = int(context.get("wins_today", 0) or 0)
        current_losses = int(context.get("losses_today", 0) or 0)

        suggestion.pnl_at_resolution = current_pnl
        suggestion.actual_pnl_change = current_pnl - suggestion.pnl_at_suggestion
        suggestion.trades_after = (current_wins + current_losses) - (suggestion.wins_at_suggestion + suggestion.losses_at_suggestion)
        suggestion.wins_after = current_wins - suggestion.wins_at_suggestion
        suggestion.losses_after = current_losses - suggestion.losses_at_suggestion

        # Calculate hypothetical impact based on suggestion type
        self._calculate_hypothetical_impact(suggestion, context)

        # Update metrics
        if outcome == SuggestionOutcome.FOLLOWED:
            self._metrics.suggestions_followed += 1
            if suggestion.suggestion_type in self._metrics.by_type:
                self._metrics.by_type[suggestion.suggestion_type]["followed"] += 1
        elif outcome == SuggestionOutcome.DISMISSED:
            self._metrics.suggestions_dismissed += 1
            if suggestion.suggestion_type in self._metrics.by_type:
                self._metrics.by_type[suggestion.suggestion_type]["dismissed"] += 1
        else:
            self._metrics.suggestions_expired += 1

        # Update totals
        if suggestion.would_have_saved:
            self._metrics.total_would_have_saved += suggestion.would_have_saved
            if suggestion.suggestion_type in self._metrics.by_type:
                self._metrics.by_type[suggestion.suggestion_type]["would_have_saved"] += suggestion.would_have_saved

        if suggestion.would_have_made:
            self._metrics.total_would_have_made += suggestion.would_have_made
            if suggestion.suggestion_type in self._metrics.by_type:
                self._metrics.by_type[suggestion.suggestion_type]["would_have_made"] += suggestion.would_have_made

        self._metrics.net_shadow_impact = (
            self._metrics.total_would_have_saved + self._metrics.total_would_have_made
        )

        # Update accuracy
        if suggestion.would_have_saved and suggestion.would_have_saved > 0:
            self._metrics.correct_suggestions += 1
        elif suggestion.would_have_made and suggestion.would_have_made > 0:
            self._metrics.correct_suggestions += 1
        elif suggestion.actual_pnl_change and suggestion.actual_pnl_change > 0:
            # Suggestion was wrong - user did better ignoring it
            self._metrics.incorrect_suggestions += 1

        total_resolved = self._metrics.correct_suggestions + self._metrics.incorrect_suggestions
        if total_resolved > 0:
            self._metrics.accuracy_rate = self._metrics.correct_suggestions / total_resolved

        # Clear active suggestion if this was it
        if self._active_suggestion and self._active_suggestion.id == suggestion_id:
            self._active_suggestion = None

        self._save_state()
        logger.info(
            f"Pearl suggestion resolved: {suggestion_id} -> {outcome.value}, "
            f"would_have_saved=${suggestion.would_have_saved or 0:.0f}, "
            f"would_have_made=${suggestion.would_have_made or 0:.0f}"
        )

    def _calculate_hypothetical_impact(
        self,
        suggestion: TrackedSuggestion,
        context: Dict[str, Any],
    ) -> None:
        """Calculate what would have happened if suggestion was followed."""
        actual_change = suggestion.actual_pnl_change or 0

        # Risk alert / Pause trading suggestions
        if suggestion.suggestion_type in (
            SuggestionType.RISK_ALERT.value,
            SuggestionType.PAUSE_TRADING.value,
        ):
            # If user continued and lost money, that's what they would have saved
            if actual_change < 0:
                suggestion.would_have_saved = abs(actual_change)
            # If user continued and made money, suggestion was wrong
            suggestion.hypothetical_pnl_change = 0  # Would have been flat if paused

        # Size reduction suggestions
        elif suggestion.suggestion_type == SuggestionType.SIZE_REDUCTION.value:
            # Assume 50% size reduction would have halved the P&L change
            if actual_change < 0:
                suggestion.would_have_saved = abs(actual_change) * 0.5
            else:
                # Would have made less
                pass
            suggestion.hypothetical_pnl_change = actual_change * 0.5

        # Direction bias suggestions
        elif suggestion.suggestion_type == SuggestionType.DIRECTION_BIAS.value:
            # Track if following the bias would have helped
            # This requires more context about actual trade directions
            # For now, use a simplified heuristic
            losses_after = suggestion.losses_after or 0
            if losses_after > 0:
                # Assume some losses were from wrong direction
                avg_loss = abs(actual_change) / max(1, losses_after) if actual_change < 0 else 50
                suggestion.would_have_saved = avg_loss * min(losses_after, 2)

        # Opportunity suggestions
        elif suggestion.suggestion_type == SuggestionType.OPPORTUNITY.value:
            # If dismissed and market moved favorably, track missed gains
            if suggestion.outcome == SuggestionOutcome.DISMISSED.value:
                # Check if there was a favorable move we missed
                # This would need price data - simplified for now
                pass

        # Pattern insight
        elif suggestion.suggestion_type == SuggestionType.PATTERN_INSIGHT.value:
            # Track if pattern played out
            if actual_change < 0 and suggestion.outcome == SuggestionOutcome.DISMISSED.value:
                suggestion.would_have_saved = abs(actual_change) * 0.3  # Conservative estimate

    def update_context(self, context: Dict[str, Any]) -> None:
        """
        Update tracking with latest context (call on each cycle).

        This allows continuous tracking of outcomes even when suggestions
        haven't been explicitly resolved.
        """
        self._last_pnl = float(context.get("daily_pnl", 0) or 0)
        self._last_wins = int(context.get("wins_today", 0) or 0)
        self._last_losses = int(context.get("losses_today", 0) or 0)

        # Auto-expire old active suggestion
        if self._active_suggestion:
            try:
                suggestion_time = datetime.fromisoformat(
                    self._active_suggestion.timestamp.replace("Z", "+00:00")
                )
                age_seconds = (datetime.now(timezone.utc) - suggestion_time).total_seconds()
                if age_seconds > self.SUGGESTION_TTL_SECONDS:
                    self._resolve_suggestion(
                        self._active_suggestion.id,
                        SuggestionOutcome.EXPIRED,
                        context,
                    )
            except Exception:
                pass

    def get_metrics(self) -> Dict[str, Any]:
        """Get shadow tracking metrics for the web app."""
        # Build recent suggestions list
        recent = []
        for s in self._suggestions[-10:]:
            recent.append({
                "id": s.id,
                "type": s.suggestion_type,
                "message": s.message[:100],
                "outcome": s.outcome,
                "would_have_saved": s.would_have_saved,
                "would_have_made": s.would_have_made,
                "timestamp": s.timestamp,
            })

        return {
            "total_suggestions": self._metrics.total_suggestions,
            "suggestions_followed": self._metrics.suggestions_followed,
            "suggestions_dismissed": self._metrics.suggestions_dismissed,
            "suggestions_expired": self._metrics.suggestions_expired,
            "total_would_have_saved": round(self._metrics.total_would_have_saved, 2),
            "total_would_have_made": round(self._metrics.total_would_have_made, 2),
            "net_shadow_impact": round(self._metrics.net_shadow_impact, 2),
            "accuracy_rate": round(self._metrics.accuracy_rate * 100, 1),
            "correct_suggestions": self._metrics.correct_suggestions,
            "incorrect_suggestions": self._metrics.incorrect_suggestions,
            "by_type": self._metrics.by_type,
            "recent_suggestions": recent,
            "active_suggestion": {
                "id": self._active_suggestion.id,
                "type": self._active_suggestion.suggestion_type,
                "message": self._active_suggestion.message,
                "action": self._active_suggestion.action,
                "timestamp": self._active_suggestion.timestamp,
                "pnl_at_suggestion": self._active_suggestion.pnl_at_suggestion,
            } if self._active_suggestion else None,
            "mode": "shadow",  # Always shadow for now
        }

    def get_active_suggestion(self) -> Optional[Dict[str, Any]]:
        """Get the current active suggestion (if any)."""
        if not self._active_suggestion:
            return None

        return {
            "id": self._active_suggestion.id,
            "type": self._active_suggestion.suggestion_type,
            "message": self._active_suggestion.message,
            "action": self._active_suggestion.action,
        }


# Singleton instance
_tracker: Optional[PearlShadowTracker] = None


def get_shadow_tracker(state_dir: Optional[Path] = None) -> PearlShadowTracker:
    """Get or create the global shadow tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = PearlShadowTracker(state_dir)
    return _tracker
