"""
Trading Circuit Breaker - Risk management module to prevent excessive losses.

Implements multiple protective measures:
1. Consecutive loss limit (pause after N consecutive losses)
2. Daily drawdown limit (pause after losing $X in a session)
3. Rolling win rate filter (pause if win rate drops below threshold)
4. Position clustering prevention (no new entries near existing positions)
5. Volatility/chop filter (reduce activity in ranging markets)

Usage:
    circuit_breaker = TradingCircuitBreaker(config)
    
    # Before processing a signal:
    decision = circuit_breaker.should_allow_signal(signal, performance_stats, active_positions, market_data)
    if not decision.allowed:
        logger.info(f"Signal blocked: {decision.reason}")
        return
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerDecision:
    """Result of circuit breaker evaluation."""
    allowed: bool
    reason: str
    severity: str = "info"  # info, warning, critical
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass
class TradingCircuitBreakerConfig:
    """Configuration for the trading circuit breaker."""
    
    # Consecutive loss limits
    max_consecutive_losses: int = 5
    consecutive_loss_cooldown_minutes: int = 30
    
    # Daily/session drawdown limits
    max_session_drawdown: float = 500.0  # USD
    max_daily_drawdown: float = 1000.0  # USD
    drawdown_cooldown_minutes: int = 60
    
    # Rolling win rate filter
    rolling_window_trades: int = 20
    min_rolling_win_rate: float = 0.30  # 30%
    win_rate_cooldown_minutes: int = 30
    
    # Position limits
    max_concurrent_positions: int = 5
    min_price_distance_pct: float = 0.5  # Don't enter within 0.5% of existing position
    
    # Volatility/chop filter
    enable_volatility_filter: bool = True
    min_atr_ratio: float = 0.8  # ATR must be >= 80% of recent average
    max_atr_ratio: float = 2.5  # ATR must be <= 250% of recent average (avoid extreme volatility)
    chop_detection_window: int = 10  # Number of recent trades to check
    chop_win_rate_threshold: float = 0.35  # If win rate in window < 35%, market is choppy
    
    # Auto-recovery
    auto_resume_after_cooldown: bool = True
    require_winning_trade_to_resume: bool = False
    
    # Session filter - skip signals during historically poor-performing sessions (ET hours)
    # Based on data analysis: overnight/close/midday perform well, morning/afternoon/premarket perform poorly
    enable_session_filter: bool = True
    # Sessions to ALLOW (all others blocked when filter is enabled)
    # Default: overnight (6PM-4AM), midday (10AM-2PM), close (5PM-6PM)
    allowed_sessions: List[str] = field(default_factory=lambda: ["overnight", "midday", "close"])
    # Session definitions (start_hour, end_hour) in ET (Eastern Time, UTC-5)
    # overnight: 18-4 (6PM-4AM), premarket: 4-6, morning: 6-10, midday: 10-14, afternoon: 14-17, close: 17-18


class TradingCircuitBreaker:
    """
    Trading circuit breaker to prevent excessive losses.
    
    Tracks trading performance and blocks new signals when risk thresholds are breached.
    """
    
    def __init__(self, config: Optional[TradingCircuitBreakerConfig] = None):
        """Initialize the trading circuit breaker."""
        self.config = config or TradingCircuitBreakerConfig()
        
        # State tracking
        self._consecutive_losses: int = 0
        self._session_pnl: float = 0.0
        self._daily_pnl: float = 0.0
        self._session_start: datetime = datetime.now(timezone.utc)
        self._daily_start: datetime = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Cooldown tracking
        self._cooldown_until: Optional[datetime] = None
        self._cooldown_reason: Optional[str] = None
        
        # Trade history for rolling calculations
        self._recent_trades: List[Dict[str, Any]] = []
        
        # Statistics
        self._total_blocks: int = 0
        self._blocks_by_reason: Dict[str, int] = {}
        
        logger.info(
            f"TradingCircuitBreaker initialized: "
            f"max_consecutive_losses={self.config.max_consecutive_losses}, "
            f"max_session_drawdown=${self.config.max_session_drawdown}, "
            f"max_concurrent_positions={self.config.max_concurrent_positions}"
        )
    
    def should_allow_signal(
        self,
        signal: Dict[str, Any],
        performance_stats: Optional[Dict[str, Any]] = None,
        active_positions: Optional[List[Dict[str, Any]]] = None,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> CircuitBreakerDecision:
        """
        Evaluate whether a new signal should be allowed.
        
        Args:
            signal: The trading signal to evaluate
            performance_stats: Recent performance statistics from PerformanceTracker
            active_positions: List of currently open positions
            market_data: Market data including ATR, volatility metrics
        
        Returns:
            CircuitBreakerDecision indicating whether the signal is allowed
        """
        # Check cooldown first
        if self._is_in_cooldown():
            return CircuitBreakerDecision(
                allowed=False,
                reason=f"in_cooldown:{self._cooldown_reason}",
                severity="warning",
                details={
                    "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
                    "cooldown_reason": self._cooldown_reason,
                    "remaining_minutes": self._get_cooldown_remaining_minutes(),
                }
            )
        
        # Check consecutive losses
        decision = self._check_consecutive_losses()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision
        
        # Check session drawdown
        decision = self._check_session_drawdown()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision
        
        # Check daily drawdown
        decision = self._check_daily_drawdown()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision
        
        # Check rolling win rate
        decision = self._check_rolling_win_rate()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision
        
        # Check position limits
        if active_positions is not None:
            decision = self._check_position_limits(signal, active_positions)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
        
        # Check volatility/chop filter
        if self.config.enable_volatility_filter and market_data is not None:
            decision = self._check_volatility_filter(market_data)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
        
        # Check session filter (time-of-day based filtering)
        if self.config.enable_session_filter:
            decision = self._check_session_filter()
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
        
        return CircuitBreakerDecision(
            allowed=True,
            reason="passed_all_checks",
            severity="info",
            details={
                "consecutive_losses": self._consecutive_losses,
                "session_pnl": self._session_pnl,
                "daily_pnl": self._daily_pnl,
            }
        )
    
    def record_trade_result(self, trade: Dict[str, Any]) -> None:
        """
        Record a completed trade result.
        
        Args:
            trade: Trade result with 'is_win', 'pnl', 'exit_time' fields
        """
        is_win = trade.get("is_win", False)
        pnl = trade.get("pnl", 0.0)
        
        # Update consecutive losses
        if is_win:
            self._consecutive_losses = 0
            # Check if we should clear cooldown on winning trade
            if (self.config.require_winning_trade_to_resume 
                and self._cooldown_reason in ["consecutive_losses", "rolling_win_rate"]):
                self._clear_cooldown()
        else:
            self._consecutive_losses += 1
        
        # Update P&L tracking
        self._session_pnl += pnl
        self._daily_pnl += pnl
        
        # Add to recent trades
        self._recent_trades.append({
            "is_win": is_win,
            "pnl": pnl,
            "exit_time": trade.get("exit_time", datetime.now(timezone.utc).isoformat()),
        })
        
        # Trim to rolling window
        max_history = max(self.config.rolling_window_trades, self.config.chop_detection_window) * 2
        if len(self._recent_trades) > max_history:
            self._recent_trades = self._recent_trades[-max_history:]
        
        logger.debug(
            f"Trade recorded: win={is_win}, pnl=${pnl:.2f}, "
            f"consecutive_losses={self._consecutive_losses}, "
            f"session_pnl=${self._session_pnl:.2f}"
        )
    
    def reset_session(self) -> None:
        """Reset session-level tracking (call at start of new trading session)."""
        self._session_pnl = 0.0
        self._session_start = datetime.now(timezone.utc)
        self._consecutive_losses = 0
        logger.info("Trading circuit breaker session reset")
    
    def reset_daily(self) -> None:
        """Reset daily-level tracking (call at start of new trading day)."""
        self._daily_pnl = 0.0
        self._daily_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.reset_session()
        logger.info("Trading circuit breaker daily reset")
    
    def force_cooldown(self, reason: str, minutes: int) -> None:
        """Force a cooldown period."""
        self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self._cooldown_reason = reason
        logger.warning(f"Circuit breaker cooldown activated: {reason} for {minutes} minutes")
    
    def clear_cooldown(self) -> None:
        """Manually clear any active cooldown."""
        self._clear_cooldown()
        logger.info("Circuit breaker cooldown cleared manually")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status."""
        recent_win_rate = self._calculate_rolling_win_rate()
        current_session, et_hour = self._get_current_session()
        session_allowed = current_session in self.config.allowed_sessions
        
        return {
            "enabled": True,
            "in_cooldown": self._is_in_cooldown(),
            "cooldown_reason": self._cooldown_reason,
            "cooldown_remaining_minutes": self._get_cooldown_remaining_minutes(),
            "consecutive_losses": self._consecutive_losses,
            "max_consecutive_losses": self.config.max_consecutive_losses,
            "session_pnl": self._session_pnl,
            "max_session_drawdown": self.config.max_session_drawdown,
            "daily_pnl": self._daily_pnl,
            "max_daily_drawdown": self.config.max_daily_drawdown,
            "rolling_win_rate": recent_win_rate,
            "min_rolling_win_rate": self.config.min_rolling_win_rate,
            "recent_trades_count": len(self._recent_trades),
            "total_blocks": self._total_blocks,
            "blocks_by_reason": self._blocks_by_reason.copy(),
            # Session filter status
            "session_filter_enabled": self.config.enable_session_filter,
            "current_session": current_session,
            "et_hour": et_hour,
            "session_allowed": session_allowed,
            "allowed_sessions": self.config.allowed_sessions,
        }
    
    # =========================================================================
    # Private methods
    # =========================================================================
    
    def _is_in_cooldown(self) -> bool:
        """Check if currently in cooldown period."""
        if self._cooldown_until is None:
            return False
        if datetime.now(timezone.utc) >= self._cooldown_until:
            if self.config.auto_resume_after_cooldown:
                self._clear_cooldown()
            return False
        return True
    
    def _get_cooldown_remaining_minutes(self) -> float:
        """Get remaining cooldown time in minutes."""
        if self._cooldown_until is None:
            return 0.0
        remaining = (self._cooldown_until - datetime.now(timezone.utc)).total_seconds() / 60
        return max(0.0, remaining)
    
    def _clear_cooldown(self) -> None:
        """Clear the cooldown state."""
        self._cooldown_until = None
        self._cooldown_reason = None
    
    def _activate_cooldown(self, reason: str, minutes: int) -> None:
        """Activate a cooldown period."""
        self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self._cooldown_reason = reason
        logger.warning(f"Circuit breaker cooldown activated: {reason} for {minutes} minutes")
    
    def _record_block(self, reason: str) -> None:
        """Record a blocked signal."""
        self._total_blocks += 1
        self._blocks_by_reason[reason] = self._blocks_by_reason.get(reason, 0) + 1
    
    def _check_consecutive_losses(self) -> CircuitBreakerDecision:
        """Check if consecutive losses exceed limit."""
        if self._consecutive_losses >= self.config.max_consecutive_losses:
            self._activate_cooldown("consecutive_losses", self.config.consecutive_loss_cooldown_minutes)
            return CircuitBreakerDecision(
                allowed=False,
                reason="consecutive_losses",
                severity="critical",
                details={
                    "consecutive_losses": self._consecutive_losses,
                    "max_allowed": self.config.max_consecutive_losses,
                    "cooldown_minutes": self.config.consecutive_loss_cooldown_minutes,
                }
            )
        return CircuitBreakerDecision(allowed=True, reason="consecutive_losses_ok")
    
    def _check_session_drawdown(self) -> CircuitBreakerDecision:
        """Check if session drawdown exceeds limit."""
        if self._session_pnl <= -self.config.max_session_drawdown:
            self._activate_cooldown("session_drawdown", self.config.drawdown_cooldown_minutes)
            return CircuitBreakerDecision(
                allowed=False,
                reason="session_drawdown",
                severity="critical",
                details={
                    "session_pnl": self._session_pnl,
                    "max_drawdown": self.config.max_session_drawdown,
                    "cooldown_minutes": self.config.drawdown_cooldown_minutes,
                }
            )
        return CircuitBreakerDecision(allowed=True, reason="session_drawdown_ok")
    
    def _check_daily_drawdown(self) -> CircuitBreakerDecision:
        """Check if daily drawdown exceeds limit."""
        if self._daily_pnl <= -self.config.max_daily_drawdown:
            # Calculate remaining time until midnight ET
            now = datetime.now(timezone.utc)
            tomorrow = (now + timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)  # 5 AM UTC = midnight ET
            remaining_minutes = max(60, (tomorrow - now).total_seconds() / 60)
            
            self._activate_cooldown("daily_drawdown", int(remaining_minutes))
            return CircuitBreakerDecision(
                allowed=False,
                reason="daily_drawdown",
                severity="critical",
                details={
                    "daily_pnl": self._daily_pnl,
                    "max_drawdown": self.config.max_daily_drawdown,
                    "cooldown_minutes": remaining_minutes,
                }
            )
        return CircuitBreakerDecision(allowed=True, reason="daily_drawdown_ok")
    
    def _calculate_rolling_win_rate(self) -> float:
        """Calculate win rate over recent trades."""
        window = self.config.rolling_window_trades
        recent = self._recent_trades[-window:] if len(self._recent_trades) >= window else self._recent_trades
        if not recent:
            return 0.5  # Neutral when no data
        wins = sum(1 for t in recent if t.get("is_win", False))
        return wins / len(recent)
    
    def _check_rolling_win_rate(self) -> CircuitBreakerDecision:
        """Check if rolling win rate is below threshold."""
        # Need minimum trades to evaluate
        if len(self._recent_trades) < self.config.rolling_window_trades // 2:
            return CircuitBreakerDecision(allowed=True, reason="insufficient_data")
        
        win_rate = self._calculate_rolling_win_rate()
        
        if win_rate < self.config.min_rolling_win_rate:
            self._activate_cooldown("rolling_win_rate", self.config.win_rate_cooldown_minutes)
            return CircuitBreakerDecision(
                allowed=False,
                reason="rolling_win_rate",
                severity="warning",
                details={
                    "win_rate": win_rate,
                    "min_required": self.config.min_rolling_win_rate,
                    "window_trades": len(self._recent_trades[-self.config.rolling_window_trades:]),
                    "cooldown_minutes": self.config.win_rate_cooldown_minutes,
                }
            )
        return CircuitBreakerDecision(allowed=True, reason="rolling_win_rate_ok")
    
    def _check_position_limits(
        self, 
        signal: Dict[str, Any], 
        active_positions: List[Dict[str, Any]]
    ) -> CircuitBreakerDecision:
        """Check position limits and clustering."""
        # Check max positions
        if len(active_positions) >= self.config.max_concurrent_positions:
            return CircuitBreakerDecision(
                allowed=False,
                reason="max_positions",
                severity="info",
                details={
                    "active_positions": len(active_positions),
                    "max_allowed": self.config.max_concurrent_positions,
                }
            )
        
        # Check clustering - don't enter too close to existing positions
        signal_entry = signal.get("entry_price", 0)
        signal_direction = signal.get("direction", "unknown")
        
        if signal_entry > 0:
            for pos in active_positions:
                pos_entry = pos.get("entry_price", 0)
                pos_direction = pos.get("direction", "unknown")
                
                if pos_entry > 0:
                    distance_pct = abs(signal_entry - pos_entry) / pos_entry * 100
                    
                    # Block if too close AND same direction (would amplify risk)
                    if distance_pct < self.config.min_price_distance_pct and signal_direction == pos_direction:
                        return CircuitBreakerDecision(
                            allowed=False,
                            reason="position_clustering",
                            severity="info",
                            details={
                                "signal_entry": signal_entry,
                                "existing_entry": pos_entry,
                                "distance_pct": distance_pct,
                                "min_required_pct": self.config.min_price_distance_pct,
                                "same_direction": True,
                            }
                        )
        
        return CircuitBreakerDecision(allowed=True, reason="position_limits_ok")
    
    def _check_volatility_filter(self, market_data: Dict[str, Any]) -> CircuitBreakerDecision:
        """Check volatility and chop conditions."""
        # Check ATR ratio
        atr_current = market_data.get("atr_current", 0)
        atr_average = market_data.get("atr_average", 0)
        
        if atr_average > 0 and atr_current > 0:
            atr_ratio = atr_current / atr_average
            
            if atr_ratio < self.config.min_atr_ratio:
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="low_volatility",
                    severity="info",
                    details={
                        "atr_ratio": atr_ratio,
                        "min_required": self.config.min_atr_ratio,
                        "message": "Market volatility too low (choppy conditions likely)",
                    }
                )
            
            if atr_ratio > self.config.max_atr_ratio:
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="extreme_volatility",
                    severity="warning",
                    details={
                        "atr_ratio": atr_ratio,
                        "max_allowed": self.config.max_atr_ratio,
                        "message": "Market volatility too extreme (high risk)",
                    }
                )
        
        # Check chop detection based on recent trade performance
        if len(self._recent_trades) >= self.config.chop_detection_window:
            recent = self._recent_trades[-self.config.chop_detection_window:]
            recent_win_rate = sum(1 for t in recent if t.get("is_win", False)) / len(recent)
            
            if recent_win_rate < self.config.chop_win_rate_threshold:
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="chop_detected",
                    severity="warning",
                    details={
                        "recent_win_rate": recent_win_rate,
                        "threshold": self.config.chop_win_rate_threshold,
                        "window_size": self.config.chop_detection_window,
                        "message": "Recent performance indicates choppy market conditions",
                    }
                )
        
        return CircuitBreakerDecision(allowed=True, reason="volatility_ok")
    
    def _get_current_session(self) -> Tuple[str, int]:
        """
        Get the current trading session based on Eastern Time.
        
        Returns:
            Tuple of (session_name, et_hour)
        """
        now = datetime.now(timezone.utc)
        # Convert UTC to ET (UTC-5, simplified - doesn't account for DST)
        et_hour = (now.hour - 5) % 24
        
        # Session definitions (in ET hours)
        sessions = {
            'overnight': (18, 4),      # 6PM - 4AM ET
            'premarket': (4, 6),       # 4AM - 6AM ET
            'morning': (6, 10),        # 6AM - 10AM ET (morning open)
            'midday': (10, 14),        # 10AM - 2PM ET
            'afternoon': (14, 17),     # 2PM - 5PM ET
            'close': (17, 18),         # 5PM - 6PM ET
        }
        
        for session_name, (start, end) in sessions.items():
            if start > end:  # overnight wraps around midnight
                if et_hour >= start or et_hour < end:
                    return session_name, et_hour
            elif start <= et_hour < end:
                return session_name, et_hour
        
        return 'other', et_hour
    
    def _check_session_filter(self) -> CircuitBreakerDecision:
        """
        Check if current session is allowed for trading.
        
        Based on historical data analysis:
        - Good sessions: overnight (63% WR), close (78% WR), midday (45% WR)
        - Bad sessions: morning (19% WR), afternoon (19% WR), premarket (22% WR)
        """
        current_session, et_hour = self._get_current_session()
        
        if current_session in self.config.allowed_sessions:
            return CircuitBreakerDecision(
                allowed=True, 
                reason="session_allowed",
                details={
                    "current_session": current_session,
                    "et_hour": et_hour,
                    "allowed_sessions": self.config.allowed_sessions,
                }
            )
        
        return CircuitBreakerDecision(
            allowed=False,
            reason="session_filtered",
            severity="info",
            details={
                "current_session": current_session,
                "et_hour": et_hour,
                "allowed_sessions": self.config.allowed_sessions,
                "message": f"Session '{current_session}' historically underperforms - signal skipped",
            }
        )


def create_trading_circuit_breaker(config: Optional[Dict[str, Any]] = None) -> TradingCircuitBreaker:
    """
    Factory function to create a TradingCircuitBreaker from a config dict.
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        Configured TradingCircuitBreaker instance
    """
    if config is None:
        return TradingCircuitBreaker()
    
    cb_config = TradingCircuitBreakerConfig(
        max_consecutive_losses=config.get("max_consecutive_losses", 5),
        consecutive_loss_cooldown_minutes=config.get("consecutive_loss_cooldown_minutes", 30),
        max_session_drawdown=config.get("max_session_drawdown", 500.0),
        max_daily_drawdown=config.get("max_daily_drawdown", 1000.0),
        drawdown_cooldown_minutes=config.get("drawdown_cooldown_minutes", 60),
        rolling_window_trades=config.get("rolling_window_trades", 20),
        min_rolling_win_rate=config.get("min_rolling_win_rate", 0.30),
        win_rate_cooldown_minutes=config.get("win_rate_cooldown_minutes", 30),
        max_concurrent_positions=config.get("max_concurrent_positions", 5),
        min_price_distance_pct=config.get("min_price_distance_pct", 0.5),
        enable_volatility_filter=config.get("enable_volatility_filter", True),
        min_atr_ratio=config.get("min_atr_ratio", 0.8),
        max_atr_ratio=config.get("max_atr_ratio", 2.5),
        chop_detection_window=config.get("chop_detection_window", 10),
        chop_win_rate_threshold=config.get("chop_win_rate_threshold", 0.35),
        auto_resume_after_cooldown=config.get("auto_resume_after_cooldown", True),
        require_winning_trade_to_resume=config.get("require_winning_trade_to_resume", False),
        # Session filter settings
        enable_session_filter=config.get("enable_session_filter", True),
        allowed_sessions=config.get("allowed_sessions", ["overnight", "midday", "close"]),
    )
    
    return TradingCircuitBreaker(cb_config)
