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

from pearlalgo.utils.logger import logger
from pearlalgo.utils.market_hours import ET, is_within_trading_window


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

    # Mode: enforce blocks signals, warn_only emits telemetry only
    mode: str = "enforce"

    # Kill switch: block all short/sell signals when enabled
    kill_switch_short: bool = False
    
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
    
    # =========================================================================
    # Phase 1: Direction gating by market regime
    # Based on data: shorts underperform longs (40% vs 47% WR), shorts are 0W/2L today
    # trending_up: 74% WR, ranging: 0% WR, volatile: 0% WR, trending_down: 40% WR
    # =========================================================================
    enable_direction_gating: bool = True
    direction_gating_min_confidence: float = 0.70  # Only apply strict gating if regime confidence >= this
    # Direction rules per regime (when confidence is met):
    # - trending_up -> long only
    # - trending_down -> short only
    # - ranging/volatile/unknown -> long only (conservative given short-side leak)
    
    # =========================================================================
    # Phase 2: Optional regime avoidance (default OFF for observation)
    # =========================================================================
    enable_regime_avoidance: bool = False  # Start with logging "would-have-blocked"
    blocked_regimes: List[str] = field(default_factory=lambda: ["ranging", "volatile"])
    regime_avoidance_min_confidence: float = 0.70
    
    # =========================================================================
    # Phase 3: Trigger-based de-risking filters
    # =========================================================================
    enable_trigger_filters: bool = False  # Start OFF
    # ema_cross trigger requires volume confirmation when enabled
    ema_cross_require_volume: bool = True
    # In ranging/volatile regimes, require volume confirmation for all entries
    low_regime_require_volume: bool = True
    
    # =========================================================================
    # Phase 4: ML chop shield (adaptive blocking)
    # Only enable after sufficient data proves lift
    # =========================================================================
    enable_ml_chop_shield: bool = False  # Requires external validation
    ml_min_scored_trades: int = 50  # Minimum trades for lift validation
    ml_min_winrate_delta: float = 0.15  # PASS vs FAIL must differ by 15+ percentage points
    ml_chop_shield_regimes: List[str] = field(default_factory=lambda: ["ranging", "volatile"])

    # =========================================================================
    # Tradovate Paper Evaluation Gate (prop firm rule enforcement)
    # =========================================================================
    enable_tv_paper_eval_gate: bool = False  # Enable for Tradovate Paper prop firm accounts
    tv_paper_max_contracts_mini: int = 5
    tv_paper_max_contracts_micro: int = 50
    tv_paper_trading_start_hour_et: int = 18  # 6 PM ET (session open)
    tv_paper_trading_end_hour_et: int = 16    # 4 PM ET
    tv_paper_trading_end_minute_et: int = 10  # 4:10 PM ET (session close)
    tv_paper_near_max_loss_buffer: float = 200.0  # Block new entries within $200 of floor
    tv_paper_enable_news_blackout: bool = True


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
        self._would_block_total: int = 0
        self._would_block_by_reason: Dict[str, int] = {}
        self._last_would_block_at: Optional[str] = None
        
        # "Would have blocked" counters for shadow measurement (Phase 2 & 3)
        self._would_have_blocked_regime: int = 0
        self._would_have_blocked_trigger: int = 0
        
        # Shadow outcome tracking: what happened to signals CB would have blocked vs allowed
        # These accumulate as virtual trades exit (TP/SL hit) and reset daily.
        self._shadow_blocked_wins: int = 0
        self._shadow_blocked_losses: int = 0
        self._shadow_blocked_pnl: float = 0.0
        self._shadow_allowed_wins: int = 0
        self._shadow_allowed_losses: int = 0
        self._shadow_allowed_pnl: float = 0.0
        
        # Direction gating statistics
        self._direction_gating_blocks: int = 0
        
        logger.info(
            f"TradingCircuitBreaker initialized: "
            f"max_consecutive_losses={self.config.max_consecutive_losses}, "
            f"max_session_drawdown=${self.config.max_session_drawdown}, "
            f"max_concurrent_positions={self.config.max_concurrent_positions}, "
            f"direction_gating={self.config.enable_direction_gating}"
        )
    
    def should_allow_signal(
        self,
        signal: Dict[str, Any],
        performance_stats: Optional[Dict[str, Any]] = None,
        active_positions: Optional[List[Dict[str, Any]]] = None,
        market_data: Optional[Dict[str, Any]] = None,
        ml_stats: Optional[Dict[str, Any]] = None,
    ) -> CircuitBreakerDecision:
        """
        Evaluate whether a new signal should be allowed.
        
        Args:
            signal: The trading signal to evaluate
            performance_stats: Recent performance statistics from PerformanceTracker
            active_positions: List of currently open positions
            market_data: Market data including ATR, volatility metrics
            ml_stats: ML filter statistics for chop shield validation
        
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
        
        # Kill switch: block all short/sell signals
        if self.config.kill_switch_short:
            direction = str(signal.get("direction", "")).lower()
            if direction in ("short", "sell"):
                logger.warning(
                    "Kill switch active: blocked short signal | "
                    "direction=%s, type=%s", direction, signal.get("type", "unknown")
                )
                self._record_block("kill_switch_short")
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="kill_switch_short",
                    severity="critical",
                    details={
                        "direction": direction,
                        "message": "Short trade kill switch is active - all short/sell signals blocked",
                    },
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
        
        # =======================================================================
        # Phase 1: Direction gating by market regime (ENABLED by default)
        # =======================================================================
        if self.config.enable_direction_gating:
            decision = self._check_direction_gating(signal)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
        
        # =======================================================================
        # Phase 2: Regime avoidance (OFF by default - log "would-have-blocked")
        # =======================================================================
        if self.config.enable_regime_avoidance:
            decision = self._check_regime_avoidance(signal)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
        else:
            # Log "would-have-blocked" for measurement (only in debug mode)
            would_block_decision = self._check_regime_avoidance(signal)
            if not would_block_decision.allowed:
                self._would_have_blocked_regime = self._would_have_blocked_regime + 1
                logger.debug(
                    f"[Phase 2 shadow] Would have blocked: {would_block_decision.reason} | "
                    f"details={would_block_decision.details}"
                )
        
        # =======================================================================
        # Phase 3: Trigger filters (OFF by default)
        # =======================================================================
        if self.config.enable_trigger_filters:
            decision = self._check_trigger_filters(signal)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
        else:
            # Log "would-have-blocked" for measurement
            would_block_decision = self._check_trigger_filters(signal)
            if not would_block_decision.allowed:
                self._would_have_blocked_trigger = self._would_have_blocked_trigger + 1
                logger.debug(
                    f"[Phase 3 shadow] Would have blocked: {would_block_decision.reason} | "
                    f"details={would_block_decision.details}"
                )
        
        # =======================================================================
        # Phase 4: ML chop shield (OFF by default - requires proven lift)
        # =======================================================================
        if self.config.enable_ml_chop_shield and ml_stats is not None:
            decision = self._check_ml_chop_shield(signal, ml_stats)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision

        # =======================================================================
        # Tradovate Paper Evaluation Gate (prop firm rule enforcement)
        # =======================================================================
        if self.config.enable_tv_paper_eval_gate:
            decision = self._check_tv_paper_eval_gate(signal, active_positions)
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
            "exit_time": trade.get("exit_time", datetime.now(ET).strftime('%Y-%m-%dT%H:%M:%S')),  # FIXED 2026-03-25: store ET not UTC
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

    def hydrate_daily_pnl(self, state_dir: Optional[str] = None) -> None:
        """Load today's realized P&L from paired Tradovate fills on startup.

        Uses get_paired_tradovate_trades (same source as /api/trades and the
        dashboard) so the circuit breaker sees the same P&L as everything else.
        Uses the 6pm ET trading-day boundary so overnight trades are attributed
        to the correct trading day — matching Tradovate's own daily grouping.

        Prevents the daily drawdown limit from resetting to $0 after an agent
        restart mid-trading-day (nightly SIGTERM / crash).
        """
        try:
            from pathlib import Path
            from pearlalgo.market_agent.stats_computation import get_trading_day_start
            from pearlalgo.api.tradovate_helpers import get_paired_tradovate_trades

            if state_dir is None:
                here = Path(__file__).resolve()
                workspace = here.parents[3]
                state_dir = str(workspace / "data" / "tradovate" / "paper")

            state_path = Path(state_dir)
            if not state_path.exists():
                logger.warning(f"hydrate_daily_pnl: state_dir not found at {state_dir}, skipping")
                return

            trading_day_start_utc = get_trading_day_start()
            start_iso = trading_day_start_utc.isoformat()

            trades = get_paired_tradovate_trades(state_path)
            today_trades = [t for t in trades if (t.get("entry_time") or "") >= start_iso]
            realized_pnl = sum(t.get("pnl", 0.0) for t in today_trades)

            self._daily_pnl = realized_pnl
            logger.info(
                "Circuit breaker hydrated daily_pnl=$%.2f from %d paired fills "
                "(trading day started %s)" % (realized_pnl, len(today_trades), start_iso)
            )

            if self._daily_pnl <= -self.config.max_daily_drawdown:
                now = datetime.now(timezone.utc)
                from pearlalgo.utils.market_hours import ET
                now_et = now.astimezone(ET)
                if now_et.hour < 18:
                    next_reset_et = now_et.replace(hour=18, minute=0, second=0, microsecond=0)
                else:
                    next_reset_et = (now_et + timedelta(days=1)).replace(
                        hour=18, minute=0, second=0, microsecond=0)
                remaining = max(60, (next_reset_et.astimezone(timezone.utc) - now).total_seconds() / 60)
                self._activate_cooldown("daily_drawdown_on_startup", int(remaining))
                logger.warning(
                    "Circuit breaker startup: daily limit already hit "
                    "(daily_pnl=$%.2f, limit=$%.2f). Cooldown %.0fmin." % (
                        self._daily_pnl, self.config.max_daily_drawdown, remaining)
                )
        except Exception as e:
            logger.error("hydrate_daily_pnl failed (non-fatal): %s" % e, exc_info=True)

    def force_cooldown(self, reason: str, minutes: int) -> None:
        """Force a cooldown period."""
        self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self._cooldown_reason = reason
        logger.warning(f"Circuit breaker cooldown activated: {reason} for {minutes} minutes")
    
    def clear_cooldown(self) -> None:
        """Manually clear any active cooldown."""
        self._clear_cooldown()
        logger.info("Circuit breaker cooldown cleared manually")

    def record_would_block(self, reason: str) -> None:
        """Record a would-block decision (warn-only mode telemetry)."""
        self._would_block_total += 1
        self._would_block_by_reason[reason] = self._would_block_by_reason.get(reason, 0) + 1
        self._last_would_block_at = datetime.now(timezone.utc).isoformat()

    def record_shadow_outcome(self, pnl: float, is_win: bool, was_would_block: bool) -> None:
        """Record the outcome of a virtual trade for shadow performance comparison.
        
        Called at virtual exit time with the trade's actual PnL and whether the
        circuit breaker would have blocked it in enforce mode.
        
        Args:
            pnl: Realized PnL of the virtual trade
            is_win: Whether the trade was profitable
            was_would_block: True if CB would have blocked this signal
        """
        if was_would_block:
            if is_win:
                self._shadow_blocked_wins += 1
            else:
                self._shadow_blocked_losses += 1
            self._shadow_blocked_pnl += pnl
        else:
            if is_win:
                self._shadow_allowed_wins += 1
            else:
                self._shadow_allowed_losses += 1
            self._shadow_allowed_pnl += pnl

    def get_shadow_outcome_stats(self) -> Dict[str, Any]:
        """Get shadow outcome comparison stats for API/UI consumption."""
        blocked_total = self._shadow_blocked_wins + self._shadow_blocked_losses
        allowed_total = self._shadow_allowed_wins + self._shadow_allowed_losses
        # Net saved = negative of blocked PnL (if blocked trades lost money, we saved it)
        net_saved = -self._shadow_blocked_pnl
        return {
            "blocked_wins": self._shadow_blocked_wins,
            "blocked_losses": self._shadow_blocked_losses,
            "blocked_total": blocked_total,
            "blocked_pnl": round(self._shadow_blocked_pnl, 2),
            "allowed_wins": self._shadow_allowed_wins,
            "allowed_losses": self._shadow_allowed_losses,
            "allowed_total": allowed_total,
            "allowed_pnl": round(self._shadow_allowed_pnl, 2),
            "net_saved": round(net_saved, 2),
        }

    def validate_config(self) -> List[str]:
        """
        Validate the circuit breaker configuration at startup.
        
        Returns:
            List of warning messages (empty if all valid)
        """
        warnings = []
        if str(self.config.mode) not in ("warn_only", "shadow", "enforce"):
            warnings.append(
                f"mode={self.config.mode} should be 'warn_only' or 'enforce'"
            )
        
        # Phase 1: Direction gating sanity checks
        if self.config.enable_direction_gating:
            if not (0.0 <= self.config.direction_gating_min_confidence <= 1.0):
                warnings.append(
                    f"direction_gating_min_confidence={self.config.direction_gating_min_confidence} "
                    "should be between 0.0 and 1.0"
                )
        
        # Phase 2: Regime avoidance sanity checks
        if self.config.enable_regime_avoidance:
            if not self.config.blocked_regimes:
                warnings.append(
                    "enable_regime_avoidance=true but blocked_regimes is empty"
                )
        
        # Phase 3: Trigger filters sanity checks
        if self.config.enable_trigger_filters:
            if not self.config.ema_cross_require_volume and not self.config.low_regime_require_volume:
                warnings.append(
                    "enable_trigger_filters=true but both volume requirements are disabled"
                )
        
        # Phase 4: ML chop shield sanity checks
        if self.config.enable_ml_chop_shield:
            if self.config.ml_min_scored_trades < 30:
                warnings.append(
                    f"ml_min_scored_trades={self.config.ml_min_scored_trades} is low; "
                    "recommend at least 30-50 for reliable lift validation"
                )
            if not (0.0 <= self.config.ml_min_winrate_delta <= 1.0):
                warnings.append(
                    f"ml_min_winrate_delta={self.config.ml_min_winrate_delta} "
                    "should be between 0.0 and 1.0"
                )
            if not self.config.ml_chop_shield_regimes:
                warnings.append(
                    "enable_ml_chop_shield=true but ml_chop_shield_regimes is empty"
                )
        
        # Log warnings
        for w in warnings:
            logger.warning(f"[TradingCircuitBreaker config] {w}")
        
        return warnings
    
    def get_rollback_instructions(self) -> Dict[str, str]:
        """
        Get instructions for rolling back each phase via config changes.
        
        Returns:
            Dict mapping phase name to rollback instruction
        """
        return {
            "phase1_direction_gating": (
                "Set `enable_direction_gating: false` in config.yaml under trading_circuit_breaker. "
                "This disables direction gating and allows both longs and shorts in all regimes."
            ),
            "phase2_regime_avoidance": (
                "Set `enable_regime_avoidance: false` in config.yaml under trading_circuit_breaker. "
                "This disables blocking of signals in ranging/volatile regimes (already OFF by default)."
            ),
            "phase3_trigger_filters": (
                "Set `enable_trigger_filters: false` in config.yaml under trading_circuit_breaker. "
                "This disables volume requirements for ema_cross and low-regime entries (already OFF by default)."
            ),
            "phase4_ml_chop_shield": (
                "Set `enable_ml_chop_shield: false` in config.yaml under trading_circuit_breaker. "
                "This disables ML FAIL blocking in ranging/volatile regimes (already OFF by default)."
            ),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status."""
        recent_win_rate = self._calculate_rolling_win_rate()
        current_session, et_hour = self._get_current_session()
        session_allowed = current_session in self.config.allowed_sessions
        
        return {
            "enabled": True,
            "mode": str(self.config.mode),
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
            "would_block_total": self._would_block_total,
            "would_block_by_reason": self._would_block_by_reason.copy(),
            "last_would_block_at": self._last_would_block_at,
            # Session filter status
            "session_filter_enabled": self.config.enable_session_filter,
            "current_session": current_session,
            "et_hour": et_hour,
            "session_allowed": session_allowed,
            "allowed_sessions": self.config.allowed_sessions,
            # Phase 1: Direction gating
            "direction_gating_enabled": self.config.enable_direction_gating,
            "direction_gating_min_confidence": self.config.direction_gating_min_confidence,
            # Phase 2: Regime avoidance (shadow measurement)
            "regime_avoidance_enabled": self.config.enable_regime_avoidance,
            "blocked_regimes": self.config.blocked_regimes,
            "would_have_blocked_regime": self._would_have_blocked_regime,
            # Phase 3: Trigger filters (shadow measurement)
            "trigger_filters_enabled": self.config.enable_trigger_filters,
            "would_have_blocked_trigger": self._would_have_blocked_trigger,
            # Phase 4: ML chop shield
            "ml_chop_shield_enabled": self.config.enable_ml_chop_shield,
            "ml_min_scored_trades": self.config.ml_min_scored_trades,
            "ml_chop_shield_regimes": self.config.ml_chop_shield_regimes,
            # Shadow outcome tracking (what happened to would-block vs allowed signals)
            "shadow_outcomes": self.get_shadow_outcome_stats(),
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
    
    def _get_current_session(self, now: Optional[datetime] = None) -> Tuple[str, int]:
        """
        Get the current trading session based on Eastern Time.
        
        Returns:
            Tuple of (session_name, et_hour)
        """
        now = now or datetime.now(timezone.utc)
        et_dt = now.astimezone(ET)
        et_hour = et_dt.hour
        
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
    
    def _check_direction_gating(self, signal: Dict[str, Any]) -> CircuitBreakerDecision:
        """
        Phase 1: Check if signal direction is allowed for the current market regime.
        
        Rules (when regime confidence >= threshold):
        - trending_up -> allow long only
        - trending_down -> allow short only
        - ranging/volatile/unknown -> allow long only (conservative)
        
        Data basis:
        - Shorts all-time: 40% WR vs Longs 47% WR
        - trending_up: 74% WR, ranging: 0% WR, volatile: 0% WR
        """
        direction = str(signal.get("direction", "")).lower()
        if direction not in ("long", "short"):
            # Unknown direction - allow (shouldn't happen in practice)
            return CircuitBreakerDecision(
                allowed=True,
                reason="direction_gating_unknown_direction",
                details={"direction": direction},
            )
        
        # Extract market regime from signal
        market_regime = signal.get("market_regime") or {}
        if not isinstance(market_regime, dict):
            market_regime = {}
        
        regime_type = str(market_regime.get("regime", "unknown")).lower()
        regime_confidence = 0.0
        try:
            regime_confidence = float(market_regime.get("confidence", 0.0))
        except (TypeError, ValueError):
            regime_confidence = 0.0
        
        # If confidence is below threshold, treat regime as "unknown"
        effective_regime = regime_type
        if regime_confidence < self.config.direction_gating_min_confidence:
            effective_regime = "unknown"
        
        # Direction rules by regime
        allowed_direction = "long"  # Default conservative
        if effective_regime == "trending_up":
            allowed_direction = "long"
        elif effective_regime == "trending_down":
            allowed_direction = "short"
        else:
            # ranging, volatile, unknown -> long only (conservative given short-side leak)
            allowed_direction = "long"
        
        if direction == allowed_direction:
            return CircuitBreakerDecision(
                allowed=True,
                reason="direction_gating_ok",
                details={
                    "direction": direction,
                    "regime": regime_type,
                    "effective_regime": effective_regime,
                    "regime_confidence": regime_confidence,
                    "allowed_direction": allowed_direction,
                },
            )
        
        return CircuitBreakerDecision(
            allowed=False,
            reason="direction_gating",
            severity="info",
            details={
                "direction": direction,
                "regime": regime_type,
                "effective_regime": effective_regime,
                "regime_confidence": regime_confidence,
                "allowed_direction": allowed_direction,
                "message": f"Direction '{direction}' not allowed in regime '{effective_regime}' (only '{allowed_direction}' permitted)",
            },
        )
    
    def _check_regime_avoidance(self, signal: Dict[str, Any]) -> CircuitBreakerDecision:
        """
        Phase 2: Optionally block signals in historically poor-performing regimes.
        
        Blocked regimes by default: ranging (0W/12L), volatile (0W/2L)
        """
        market_regime = signal.get("market_regime") or {}
        if not isinstance(market_regime, dict):
            market_regime = {}
        
        regime_type = str(market_regime.get("regime", "unknown")).lower()
        regime_confidence = 0.0
        try:
            regime_confidence = float(market_regime.get("confidence", 0.0))
        except (TypeError, ValueError):
            regime_confidence = 0.0
        
        # Only apply if confidence meets threshold
        if regime_confidence < self.config.regime_avoidance_min_confidence:
            return CircuitBreakerDecision(
                allowed=True,
                reason="regime_avoidance_low_confidence",
                details={
                    "regime": regime_type,
                    "regime_confidence": regime_confidence,
                    "min_confidence": self.config.regime_avoidance_min_confidence,
                },
            )
        
        # Check if regime is in blocked list
        blocked_regimes_lower = [r.lower() for r in self.config.blocked_regimes]
        if regime_type in blocked_regimes_lower:
            return CircuitBreakerDecision(
                allowed=False,
                reason="regime_avoidance",
                severity="info",
                details={
                    "regime": regime_type,
                    "regime_confidence": regime_confidence,
                    "blocked_regimes": self.config.blocked_regimes,
                    "message": f"Regime '{regime_type}' is historically poor-performing - signal skipped",
                },
            )
        
        return CircuitBreakerDecision(
            allowed=True,
            reason="regime_avoidance_ok",
            details={"regime": regime_type, "regime_confidence": regime_confidence},
        )
    
    def _check_trigger_filters(self, signal: Dict[str, Any]) -> CircuitBreakerDecision:
        """
        Phase 3: De-risk low-quality trigger types.
        
        Rules:
        - ema_cross requires volume_confirmed=true (39% WR vs better triggers)
        - In ranging/volatile regimes, require volume confirmation for all entries
        """
        entry_trigger = str(signal.get("entry_trigger", signal.get("type", ""))).lower()
        volume_confirmed = bool(signal.get("volume_confirmed", False))
        
        market_regime = signal.get("market_regime") or {}
        if not isinstance(market_regime, dict):
            market_regime = {}
        regime_type = str(market_regime.get("regime", "unknown")).lower()
        
        # Check ema_cross volume requirement
        if self.config.ema_cross_require_volume and entry_trigger == "ema_cross":
            if not volume_confirmed:
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="trigger_ema_cross_no_volume",
                    severity="info",
                    details={
                        "entry_trigger": entry_trigger,
                        "volume_confirmed": volume_confirmed,
                        "message": "ema_cross trigger requires volume confirmation",
                    },
                )
        
        # Check volume requirement in poor regimes
        if self.config.low_regime_require_volume and regime_type in ("ranging", "volatile"):
            if not volume_confirmed:
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="trigger_low_regime_no_volume",
                    severity="info",
                    details={
                        "regime": regime_type,
                        "entry_trigger": entry_trigger,
                        "volume_confirmed": volume_confirmed,
                        "message": f"Entries in '{regime_type}' regime require volume confirmation",
                    },
                )
        
        return CircuitBreakerDecision(
            allowed=True,
            reason="trigger_filters_ok",
            details={
                "entry_trigger": entry_trigger,
                "volume_confirmed": volume_confirmed,
                "regime": regime_type,
            },
        )
    
    def _check_ml_chop_shield(
        self, signal: Dict[str, Any], ml_stats: Optional[Dict[str, Any]] = None
    ) -> CircuitBreakerDecision:
        """
        Phase 4: Block ML FAIL signals in poor regimes when lift is proven.
        
        Preconditions (must all be met):
        1. ML stats provided with sufficient scored trades (>= ml_min_scored_trades)
        2. PASS vs FAIL win-rate delta >= ml_min_winrate_delta
        3. Signal marked as ML FAIL
        4. Current regime is in ml_chop_shield_regimes
        """
        if ml_stats is None:
            return CircuitBreakerDecision(
                allowed=True,
                reason="ml_chop_shield_no_stats",
            )
        
        # Check if enough trades have been scored
        scored_trades = int(ml_stats.get("scored_trades", 0))
        if scored_trades < self.config.ml_min_scored_trades:
            return CircuitBreakerDecision(
                allowed=True,
                reason="ml_chop_shield_insufficient_data",
                details={
                    "scored_trades": scored_trades,
                    "required": self.config.ml_min_scored_trades,
                },
            )
        
        # Check lift (PASS vs FAIL win-rate delta)
        pass_win_rate = float(ml_stats.get("pass_win_rate", 0.0))
        fail_win_rate = float(ml_stats.get("fail_win_rate", 0.0))
        win_rate_delta = pass_win_rate - fail_win_rate
        
        if win_rate_delta < self.config.ml_min_winrate_delta:
            return CircuitBreakerDecision(
                allowed=True,
                reason="ml_chop_shield_insufficient_lift",
                details={
                    "pass_win_rate": pass_win_rate,
                    "fail_win_rate": fail_win_rate,
                    "win_rate_delta": win_rate_delta,
                    "required_delta": self.config.ml_min_winrate_delta,
                },
            )
        
        # Check if signal is ML FAIL
        ml_prediction = signal.get("_ml_prediction") or {}
        ml_pass = ml_prediction.get("pass_filter", True)  # Default to pass if no data
        if ml_pass:
            return CircuitBreakerDecision(
                allowed=True,
                reason="ml_chop_shield_signal_passed",
                details={"ml_pass": ml_pass},
            )
        
        # Check if current regime is in chop shield regimes
        market_regime = signal.get("market_regime") or {}
        if not isinstance(market_regime, dict):
            market_regime = {}
        regime_type = str(market_regime.get("regime", "unknown")).lower()
        
        shield_regimes_lower = [r.lower() for r in self.config.ml_chop_shield_regimes]
        if regime_type not in shield_regimes_lower:
            return CircuitBreakerDecision(
                allowed=True,
                reason="ml_chop_shield_regime_not_targeted",
                details={
                    "regime": regime_type,
                    "shield_regimes": self.config.ml_chop_shield_regimes,
                },
            )
        
        # All conditions met - block the signal
        return CircuitBreakerDecision(
            allowed=False,
            reason="ml_chop_shield",
            severity="info",
            details={
                "regime": regime_type,
                "ml_pass": ml_pass,
                "pass_win_rate": pass_win_rate,
                "fail_win_rate": fail_win_rate,
                "win_rate_delta": win_rate_delta,
                "scored_trades": scored_trades,
                "message": f"ML FAIL signal blocked in '{regime_type}' regime (lift validated: {win_rate_delta:.1%})",
            },
        )


    def _check_tv_paper_eval_gate(
        self,
        signal: Dict[str, Any],
        active_positions: Optional[List[Dict[str, Any]]] = None,
    ) -> CircuitBreakerDecision:
        """
        Tradovate Paper Evaluation Gate: enforce prop firm rules before order placement.

        Checks:
        1. Max contracts (5 mini / 50 micro)
        2. Trading hours (6 PM ET - 4:10 PM ET)
        3. No hedging (no opposite direction on same underlying)
        4. News blackout (2 min before/after any release)
        """
        from datetime import time as _time_cls
        now_utc = datetime.now(timezone.utc)
        in_session = is_within_trading_window(
            now_utc,
            start_hour_et=self.config.tv_paper_trading_start_hour_et,
            start_minute_et=0,
            end_hour_et=self.config.tv_paper_trading_end_hour_et,
            end_minute_et=self.config.tv_paper_trading_end_minute_et,
        )
        if not in_session:
            try:
                now_et = now_utc.astimezone(ET)
                et_time = now_et.time()
            except Exception:
                et_time = now_utc.time()
            session_open = _time_cls(self.config.tv_paper_trading_start_hour_et, 0)
            session_close = _time_cls(
                self.config.tv_paper_trading_end_hour_et,
                self.config.tv_paper_trading_end_minute_et,
            )
            return CircuitBreakerDecision(
                allowed=False,
                reason="tv_paper_outside_trading_hours",
                severity="warning",
                details={
                    "current_time_et": str(et_time),
                    "session_open": str(session_open),
                    "session_close": str(session_close),
                },
            )

        # ── Check 2: Max contracts ────────────────────────────────────
        if active_positions:
            total_qty = sum(
                abs(int(p.get("position_size", 0) or p.get("quantity", 0) or 1))
                for p in active_positions
            )
            new_qty = int(signal.get("position_size", 1))
            if total_qty + new_qty > self.config.tv_paper_max_contracts_mini:
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="tv_paper_max_contracts_exceeded",
                    severity="critical",
                    details={
                        "current_contracts": total_qty,
                        "new_contracts": new_qty,
                        "max_allowed": self.config.tv_paper_max_contracts_mini,
                    },
                )

        # ── Check 3: No hedging ───────────────────────────────────────
        if active_positions:
            signal_direction = str(signal.get("direction", "")).lower()
            for pos in active_positions:
                pos_direction = str(pos.get("direction", "")).lower()
                if pos_direction and signal_direction and pos_direction != signal_direction:
                    return CircuitBreakerDecision(
                        allowed=False,
                        reason="tv_paper_hedging_prohibited",
                        severity="critical",
                        details={
                            "signal_direction": signal_direction,
                            "existing_direction": pos_direction,
                            "message": "Tradovate Paper prohibits hedging (simultaneous long + short on same underlying)",
                        },
                    )

        # ── Check 4: News blackout ────────────────────────────────────
        if self.config.tv_paper_enable_news_blackout:
            try:
                from pearlalgo.utils.news_calendar import get_news_calendar
                calendar = get_news_calendar()
                in_blackout, event_name = calendar.is_in_blackout(now_utc)
                if in_blackout:
                    return CircuitBreakerDecision(
                        allowed=False,
                        reason="tv_paper_news_blackout",
                        severity="warning",
                        details={
                            "event": event_name,
                            "message": f"News blackout: {event_name} (2 min before/after)",
                        },
                    )
            except Exception as e:
                logger.debug(f"News calendar check failed (allowing trade): {e}")

        return CircuitBreakerDecision(
            allowed=True,
            reason="tv_paper_eval_gate_passed",
            severity="info",
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
        mode=str(config.get("mode", "enforce") or "enforce"),
        kill_switch_short=config.get("kill_switch_short", False),
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
        # Phase 1: Direction gating
        enable_direction_gating=config.get("enable_direction_gating", True),
        direction_gating_min_confidence=config.get("direction_gating_min_confidence", 0.70),
        # Phase 2: Regime avoidance
        enable_regime_avoidance=config.get("enable_regime_avoidance", False),
        blocked_regimes=config.get("blocked_regimes", ["ranging", "volatile"]),
        regime_avoidance_min_confidence=config.get("regime_avoidance_min_confidence", 0.70),
        # Phase 3: Trigger filters
        enable_trigger_filters=config.get("enable_trigger_filters", False),
        ema_cross_require_volume=config.get("ema_cross_require_volume", True),
        low_regime_require_volume=config.get("low_regime_require_volume", True),
        # Phase 4: ML chop shield
        enable_ml_chop_shield=config.get("enable_ml_chop_shield", False),
        ml_min_scored_trades=config.get("ml_min_scored_trades", 50),
        ml_min_winrate_delta=config.get("ml_min_winrate_delta", 0.15),
        ml_chop_shield_regimes=config.get("ml_chop_shield_regimes", ["ranging", "volatile"]),
        # Tradovate Paper Evaluation Gate
        enable_tv_paper_eval_gate=config.get("enable_tv_paper_eval_gate", False),
        tv_paper_max_contracts_mini=config.get("tv_paper_max_contracts_mini", 5),
        tv_paper_max_contracts_micro=config.get("tv_paper_max_contracts_micro", 50),
        tv_paper_trading_start_hour_et=config.get("tv_paper_trading_start_hour_et", 18),
        tv_paper_trading_end_hour_et=config.get("tv_paper_trading_end_hour_et", 16),
        tv_paper_trading_end_minute_et=config.get("tv_paper_trading_end_minute_et", 10),
        tv_paper_near_max_loss_buffer=config.get("tv_paper_near_max_loss_buffer", 200.0),
        tv_paper_enable_news_blackout=config.get("tv_paper_enable_news_blackout", True),
    )
    
    return TradingCircuitBreaker(cb_config)
