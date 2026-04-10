"""
Trading Circuit Breaker - hard-risk containment for live execution.

Implements protective measures such as:
1. Consecutive loss limit (pause after N consecutive losses)
2. Daily/session drawdown limits
3. Daily profit cap
4. Position/exposure clustering prevention
5. Tradovate paper-eval rule enforcement

Usage:
    circuit_breaker = TradingCircuitBreaker(config)
    
    # Before processing a signal:
    decision = circuit_breaker.should_allow_signal(signal, performance_stats, active_positions, market_data)
    if not decision.allowed:
        logger.info(f"Signal blocked: {decision.reason}")
        return
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple

from pearlalgo.utils.logger import logger
from pearlalgo.utils.market_hours import ET, is_within_trading_window

# Shared types (extracted to break circular imports)
from pearlalgo.market_agent.circuit_breaker_types import (
    CircuitBreakerDecision,
    TradingCircuitBreakerConfig,
)

# Extracted filter functions (Phase 2a refactor)
from pearlalgo.market_agent.circuit_breaker_filters import (
    check_hour_filter as _check_hour_filter_fn,
    check_weekday_filter as _check_weekday_filter_fn,
    check_session_filter as _check_session_filter_fn,
    check_direction_gating as _check_direction_gating_fn,
    check_regime_avoidance as _check_regime_avoidance_fn,
    check_trigger_filters as _check_trigger_filters_fn,
    check_tv_paper_eval_gate as _check_tv_paper_eval_gate_fn,
    get_current_session as _get_current_session_fn,
)


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
        
        # Retained for backward-compatible state payloads. These remain zero now
        # that market-quality gating has been retired from the breaker.
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

        Returns a CircuitBreakerDecision. When ``allowed=True`` the caller
        should also inspect ``risk_scale`` (0.0-1.0) and multiply position
        size accordingly.  A risk_scale of 0.0 with allowed=True should be
        treated as a block (edge case safety).
        """
        # Check cooldown first
        if self._is_in_cooldown():
            return CircuitBreakerDecision(
                allowed=False,
                reason=f"in_cooldown:{self._cooldown_reason}",
                severity="warning",
                risk_scale=0.0,
                details={
                    "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
                    "cooldown_reason": self._cooldown_reason,
                    "remaining_minutes": self._get_cooldown_remaining_minutes(),
                }
            )

        # Accumulate the minimum risk_scale across all scaling checks.
        # Hard-block checks still return allowed=False immediately.
        min_risk_scale = 1.0
        scale_reasons: List[str] = []

        # --- Hard-block checks (return immediately if tripped) ---

        # Tiered consecutive loss response (replaces binary check when enabled)
        if self.config.enable_tiered_loss_response:
            decision = self._check_tiered_losses()
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
            if decision.risk_scale < min_risk_scale:
                min_risk_scale = decision.risk_scale
                scale_reasons.append(f"tiered_loss:{decision.risk_scale:.2f}")
        else:
            decision = self._check_consecutive_losses()
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision

        # Session drawdown
        decision = self._check_session_drawdown()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision

        # Daily drawdown
        decision = self._check_daily_drawdown()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision

        # Daily profit cap
        decision = self._check_daily_profit_cap()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision

        # Rolling win rate
        decision = self._check_rolling_win_rate()
        if not decision.allowed:
            self._record_block(decision.reason)
            return decision

        # Position limits
        if active_positions is not None:
            decision = self._check_position_limits(signal, active_positions)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision

        if self.config.enable_direction_gating:
            decision = self._check_direction_gating(signal)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision

        regime_decision = self._check_regime_avoidance(signal)
        if self.config.enable_regime_avoidance:
            if not regime_decision.allowed:
                self._record_block(regime_decision.reason)
                return regime_decision
        elif not regime_decision.allowed:
            self._would_have_blocked_regime += 1

        trigger_decision = self._check_trigger_filters(signal)
        if self.config.enable_trigger_filters:
            if not trigger_decision.allowed:
                self._record_block(trigger_decision.reason)
                return trigger_decision
        elif not trigger_decision.allowed:
            self._would_have_blocked_trigger += 1

        if self.config.enable_volatility_filter and market_data is not None:
            decision = self._check_volatility_filter(market_data)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision

        # --- Scaling checks (reduce risk_scale but don't hard-block) ---

        # Equity curve filter
        if self.config.enable_equity_curve_filter:
            decision = self._check_equity_curve()
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
            if decision.risk_scale < min_risk_scale:
                min_risk_scale = decision.risk_scale
                scale_reasons.append(f"equity_curve:{decision.risk_scale:.2f}")

        # Time-of-day risk scaling
        if self.config.enable_tod_risk_scaling:
            decision = self._check_tod_risk_scaling()
            if decision.risk_scale < min_risk_scale:
                min_risk_scale = decision.risk_scale
                scale_reasons.append(f"tod:{decision.risk_scale:.2f}")

        # Volatility risk scaling
        if self.config.enable_volatility_risk_scaling and market_data:
            decision = self._check_volatility_risk_scaling(market_data)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision
            if decision.risk_scale < min_risk_scale:
                min_risk_scale = decision.risk_scale
                scale_reasons.append(f"volatility:{decision.risk_scale:.2f}")

        # Tradovate Paper Evaluation Gate
        if self.config.enable_tv_paper_eval_gate:
            decision = self._check_tv_paper_eval_gate(signal, active_positions)
            if not decision.allowed:
                self._record_block(decision.reason)
                return decision

        # Final: if risk_scale is effectively zero, block
        if min_risk_scale <= 0.0:
            self._record_block("risk_scale_zero")
            return CircuitBreakerDecision(
                allowed=False, reason="risk_scale_zero", severity="warning",
                risk_scale=0.0, details={"scale_reasons": scale_reasons},
            )

        if scale_reasons:
            logger.info(
                f"CB risk scaling applied: scale={min_risk_scale:.2f}, "
                f"reasons={scale_reasons}"
            )

        return CircuitBreakerDecision(
            allowed=True,
            reason="passed_all_checks",
            severity="info",
            risk_scale=min_risk_scale,
            details={
                "consecutive_losses": self._consecutive_losses,
                "session_pnl": self._session_pnl,
                "daily_pnl": self._daily_pnl,
                "risk_scale": min_risk_scale,
                "scale_reasons": scale_reasons,
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
    
    def sync_broker_pnl(self, broker_realized_pnl: float, broker_open_pnl: float = 0.0) -> None:
        """Sync P&L from the broker's actual account data (Tradovate).

        This is the **source of truth** — overrides any internally tracked
        P&L derived from virtual trade exits.  Called every scan cycle
        after polling the broker's account summary.

        Args:
            broker_realized_pnl: Tradovate's daily realized P&L (resets at session boundary)
            broker_open_pnl: Tradovate's current unrealized P&L on open positions
        """
        old_daily = self._daily_pnl
        self._daily_pnl = broker_realized_pnl
        # Session PnL tracks the same as daily for now (resets at 6pm ET)
        self._session_pnl = broker_realized_pnl

        if abs(old_daily - broker_realized_pnl) > 1.0:
            logger.info(
                "CB broker P&L sync: daily=$%.2f (was $%.2f), open=$%.2f",
                broker_realized_pnl, old_daily, broker_open_pnl,
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

        if self.config.enable_direction_gating and not (0.0 <= self.config.direction_gating_min_confidence <= 1.0):
            warnings.append(
                "direction_gating_min_confidence must be between 0.0 and 1.0"
            )

        if self.config.enable_regime_avoidance:
            if not self.config.blocked_regimes:
                warnings.append(
                    "regime avoidance is enabled but blocked_regimes is empty"
                )
            if not (0.0 <= self.config.regime_avoidance_min_confidence <= 1.0):
                warnings.append(
                    "regime_avoidance_min_confidence must be between 0.0 and 1.0"
                )

        if self.config.enable_trigger_filters:
            if not self.config.ema_cross_require_volume and not self.config.low_regime_require_volume:
                warnings.append(
                    "trigger filters are enabled but no volume-confirmation rule is active"
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
        return {}
    
    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status."""
        recent_win_rate = self._calculate_rolling_win_rate()
        current_session, et_hour = self._get_current_session()
        
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
            # Observability only; legacy session gating is retired.
            "session_filter_enabled": self.config.enable_session_filter,
            "direction_gating_enabled": self.config.enable_direction_gating,
            "regime_avoidance_enabled": self.config.enable_regime_avoidance,
            "trigger_filters_enabled": self.config.enable_trigger_filters,
            "volatility_filter_enabled": self.config.enable_volatility_filter,
            "current_session": current_session,
            "et_hour": et_hour,
            # Shadow outcome tracking (what happened to would-block vs allowed signals)
            "shadow_outcomes": self.get_shadow_outcome_stats(),
        }
    
    # =========================================================================
    # State persistence (Issue 2)
    # =========================================================================

    def get_persisted_state(self) -> Dict[str, Any]:
        """Return critical CB state for persistence to state.json.

        Only the fields that must survive an agent restart are included:
        cooldown, daily P&L, consecutive losses, and session P&L.
        """
        return {
            "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
            "cooldown_reason": self._cooldown_reason,
            "daily_pnl": self._daily_pnl,
            "session_pnl": self._session_pnl,
            "consecutive_losses": self._consecutive_losses,
        }

    def restore_persisted_state(self, data: Optional[Dict[str, Any]]) -> None:
        """Restore CB state from a previously persisted snapshot.

        Called after ``__init__`` and ``hydrate_daily_pnl``.  Hydration from
        Tradovate fills takes precedence for ``daily_pnl`` if it produced a
        non-zero value; otherwise the persisted value is used as fallback.
        """
        if not data:
            return

        # Cooldown — restore only if the saved cooldown hasn't expired yet.
        saved_until = data.get("cooldown_until")
        if saved_until:
            try:
                cooldown_dt = datetime.fromisoformat(saved_until)
                if cooldown_dt > datetime.now(timezone.utc):
                    self._cooldown_until = cooldown_dt
                    self._cooldown_reason = data.get("cooldown_reason")
                    remaining = (cooldown_dt - datetime.now(timezone.utc)).total_seconds() / 60
                    logger.info(
                        "Restored CB cooldown: reason=%s, remaining=%.1f min",
                        self._cooldown_reason, remaining,
                    )
                else:
                    logger.debug("Persisted cooldown already expired, ignoring")
            except (ValueError, TypeError) as exc:
                logger.warning("Could not parse persisted cooldown_until: %s", exc)

        # Daily P&L — hydrate_daily_pnl already ran; only use persisted value
        # as fallback when hydration returned zero (e.g. no fills file yet).
        if self._daily_pnl == 0.0 and data.get("daily_pnl"):
            self._daily_pnl = float(data["daily_pnl"])
            logger.info("Restored CB daily_pnl=$%.2f from persisted state", self._daily_pnl)

        # Session P&L
        if data.get("session_pnl"):
            self._session_pnl = float(data["session_pnl"])

        # Consecutive losses
        saved_losses = data.get("consecutive_losses", 0)
        if saved_losses and saved_losses > self._consecutive_losses:
            self._consecutive_losses = int(saved_losses)
            logger.info("Restored CB consecutive_losses=%d from persisted state", self._consecutive_losses)

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
    
    # ==================================================================
    # NEW: Tiered consecutive loss response
    # ==================================================================
    def _check_tiered_losses(self) -> CircuitBreakerDecision:
        """Tiered response to consecutive losses — scale down before halting.

        Walks configured tiers from highest to lowest.  Returns the matching
        tier's risk_scale.  If the tier action is 'halt' or 'halt_session',
        returns allowed=False.
        """
        if self._consecutive_losses == 0:
            return CircuitBreakerDecision(allowed=True, reason="no_losses", risk_scale=1.0)

        # Sort tiers descending by loss count so we match the *highest* tier first
        tiers = sorted(
            self.config.tiered_loss_levels,
            key=lambda t: t.get("losses", 0),
            reverse=True,
        )

        for tier in tiers:
            threshold = int(tier.get("losses", 999))
            if self._consecutive_losses >= threshold:
                action = str(tier.get("action", "reduce"))
                scale = float(tier.get("risk_scale", 0.5))

                if action in ("halt", "halt_session"):
                    cooldown_min = int(tier.get("cooldown_minutes", 30))
                    if action == "halt_session":
                        # Halt until next session (long cooldown)
                        cooldown_min = max(cooldown_min, 240)
                    self._activate_cooldown("tiered_loss_halt", cooldown_min)
                    logger.warning(
                        f"🛑 Tiered loss halt: {self._consecutive_losses} consecutive losses "
                        f"(tier threshold={threshold}, cooldown={cooldown_min}min)"
                    )
                    return CircuitBreakerDecision(
                        allowed=False,
                        reason="tiered_loss_halt",
                        severity="critical",
                        risk_scale=0.0,
                        details={
                            "consecutive_losses": self._consecutive_losses,
                            "tier_threshold": threshold,
                            "action": action,
                            "cooldown_minutes": cooldown_min,
                        },
                    )
                else:
                    # Reduce size
                    logger.info(
                        f"📉 Tiered loss scaling: {self._consecutive_losses} consecutive losses "
                        f"→ risk_scale={scale:.2f} (tier threshold={threshold})"
                    )
                    return CircuitBreakerDecision(
                        allowed=True,
                        reason="tiered_loss_reduce",
                        risk_scale=scale,
                        details={
                            "consecutive_losses": self._consecutive_losses,
                            "tier_threshold": threshold,
                            "risk_scale": scale,
                        },
                    )

        # No tier matched
        return CircuitBreakerDecision(allowed=True, reason="tiered_loss_ok", risk_scale=1.0)

    # ==================================================================
    # NEW: Equity curve filter
    # ==================================================================
    def _check_equity_curve(self) -> CircuitBreakerDecision:
        """Equity curve filter — trade only when equity is above its EMA.

        Uses the running P&L from recent trades to build a mini equity curve,
        then compares the current equity to its EMA.
        """
        lookback = self.config.equity_curve_lookback
        if len(self._recent_trades) < lookback:
            # Not enough data yet — allow full size
            return CircuitBreakerDecision(
                allowed=True, reason="equity_curve_insufficient_data", risk_scale=1.0,
            )

        # Build equity curve from recent trades (cumulative PnL)
        recent = self._recent_trades[-lookback * 2:]  # extra for EMA warmup
        equity = []
        running = 0.0
        for t in recent:
            running += t.get("pnl", 0.0)
            equity.append(running)

        if len(equity) < lookback:
            return CircuitBreakerDecision(
                allowed=True, reason="equity_curve_insufficient_data", risk_scale=1.0,
            )

        # Compute EMA of equity curve
        multiplier = 2.0 / (lookback + 1)
        ema = equity[0]
        for val in equity[1:]:
            ema = (val - ema) * multiplier + ema

        current_equity = equity[-1]
        equity_diff = current_equity - ema

        # Compute "ATR" of equity curve (avg absolute change per trade)
        changes = [abs(equity[i] - equity[i - 1]) for i in range(1, len(equity))]
        equity_atr = sum(changes) / len(changes) if changes else 1.0
        equity_atr = max(equity_atr, 1.0)  # avoid division by zero

        if equity_diff < -equity_atr * self.config.equity_curve_halt_atr_mult:
            # Equity far below MA — halt
            logger.warning(
                f"🛑 Equity curve halt: equity={current_equity:.2f}, "
                f"ema={ema:.2f}, diff={equity_diff:.2f}, "
                f"threshold={-equity_atr * self.config.equity_curve_halt_atr_mult:.2f}"
            )
            self._activate_cooldown("equity_curve_halt", 15)
            return CircuitBreakerDecision(
                allowed=False,
                reason="equity_curve_halt",
                severity="critical",
                risk_scale=0.0,
                details={
                    "equity": current_equity,
                    "ema": ema,
                    "diff": equity_diff,
                    "equity_atr": equity_atr,
                },
            )
        elif equity_diff < 0 and self.config.equity_curve_half_size_below_ma:
            # Equity below MA — half size
            logger.info(
                f"📉 Equity curve below MA: equity={current_equity:.2f}, "
                f"ema={ema:.2f} → risk_scale=0.5"
            )
            return CircuitBreakerDecision(
                allowed=True,
                reason="equity_curve_below_ma",
                risk_scale=0.5,
                details={
                    "equity": current_equity,
                    "ema": ema,
                    "diff": equity_diff,
                },
            )

        return CircuitBreakerDecision(
            allowed=True, reason="equity_curve_ok", risk_scale=1.0,
        )

    # ==================================================================
    # NEW: Time-of-day risk scaling
    # ==================================================================
    def _check_tod_risk_scaling(self) -> CircuitBreakerDecision:
        """Scale down risk during historically weak hours."""
        now_et = datetime.now(ET)
        current_hour = now_et.hour

        for window in self.config.tod_risk_windows:
            start = int(window.get("start_hour_et", 0))
            end = int(window.get("end_hour_et", 0))
            scale = float(window.get("risk_scale", 1.0))

            # Handle windows that cross midnight (e.g. 22-02)
            if start <= end:
                in_window = start <= current_hour < end
            else:
                in_window = current_hour >= start or current_hour < end

            if in_window:
                return CircuitBreakerDecision(
                    allowed=True,
                    reason="tod_risk_scaling",
                    risk_scale=scale,
                    details={
                        "hour_et": current_hour,
                        "window": f"{start:02d}-{end:02d}",
                        "risk_scale": scale,
                    },
                )

        return CircuitBreakerDecision(allowed=True, reason="tod_ok", risk_scale=1.0)

    # ==================================================================
    # NEW: Volatility-adjusted risk scaling
    # ==================================================================
    def _check_volatility_risk_scaling(
        self, market_data: Dict[str, Any],
    ) -> CircuitBreakerDecision:
        """Scale risk based on current ATR vs average ATR."""
        atr_current = market_data.get("atr_current", 0)
        atr_average = market_data.get("atr_average", 0)
        if not atr_average or atr_average <= 0:
            return CircuitBreakerDecision(allowed=True, reason="vol_no_data", risk_scale=1.0)

        ratio = atr_current / atr_average

        if ratio >= self.config.volatility_extreme_atr_ratio:
            scale = self.config.volatility_extreme_risk_scale
            if scale <= 0:
                logger.warning(
                    f"🛑 Extreme volatility halt: ATR ratio={ratio:.2f} "
                    f"(threshold={self.config.volatility_extreme_atr_ratio})"
                )
                return CircuitBreakerDecision(
                    allowed=False,
                    reason="extreme_volatility",
                    severity="warning",
                    risk_scale=0.0,
                    details={"atr_ratio": ratio, "threshold": self.config.volatility_extreme_atr_ratio},
                )
            return CircuitBreakerDecision(
                allowed=True, reason="extreme_vol_scale", risk_scale=scale,
                details={"atr_ratio": ratio},
            )
        elif ratio >= self.config.volatility_high_atr_ratio:
            scale = self.config.volatility_high_risk_scale
            logger.info(
                f"📉 High volatility scaling: ATR ratio={ratio:.2f} → risk_scale={scale:.2f}"
            )
            return CircuitBreakerDecision(
                allowed=True, reason="high_vol_scale", risk_scale=scale,
                details={"atr_ratio": ratio, "risk_scale": scale},
            )

        return CircuitBreakerDecision(allowed=True, reason="vol_ok", risk_scale=1.0)

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

    def _check_daily_profit_cap(self) -> CircuitBreakerDecision:
        """Check if daily realized P&L has reached the profit target."""
        if self.config.max_daily_profit <= 0:
            return CircuitBreakerDecision(allowed=True, reason="daily_profit_cap_disabled")

        if self._daily_pnl >= self.config.max_daily_profit:
            now = datetime.now(timezone.utc)
            from pearlalgo.utils.market_hours import ET
            now_et = now.astimezone(ET)
            # Cooldown until next 6 PM ET session reset
            if now_et.hour < 18:
                next_reset_et = now_et.replace(hour=18, minute=0, second=0, microsecond=0)
            else:
                next_reset_et = (now_et + timedelta(days=1)).replace(
                    hour=18, minute=0, second=0, microsecond=0)
            remaining = max(60, (next_reset_et.astimezone(timezone.utc) - now).total_seconds() / 60)

            self._activate_cooldown("daily_profit_cap", int(remaining))
            logger.info(
                "Daily profit cap reached: daily_pnl=$%.2f >= target=$%.2f. "
                "Trading paused for %.0f min.",
                self._daily_pnl, self.config.max_daily_profit, remaining,
            )
            return CircuitBreakerDecision(
                allowed=False,
                reason="daily_profit_cap",
                severity="info",
                details={
                    "daily_pnl": self._daily_pnl,
                    "max_daily_profit": self.config.max_daily_profit,
                    "cooldown_minutes": remaining,
                    "message": "Profit target reached for the day - preserving gains",
                },
            )
        return CircuitBreakerDecision(allowed=True, reason="daily_profit_cap_ok")

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
        """Get the current trading session based on Eastern Time."""
        return _get_current_session_fn(now)
    
    def _check_hour_filter(self) -> CircuitBreakerDecision:
        """Block signals outside allowed trading hours (ET)."""
        return _check_hour_filter_fn(self.config)

    def _check_weekday_filter(self) -> CircuitBreakerDecision:
        """Block signals on historically unprofitable weekdays."""
        return _check_weekday_filter_fn(self.config)

    def _check_session_filter(self) -> CircuitBreakerDecision:
        """Check if current session is allowed for trading."""
        return _check_session_filter_fn(self.config)
    
    def _check_direction_gating(self, signal: Dict[str, Any]) -> CircuitBreakerDecision:
        """Phase 1: Check if signal direction is allowed for the current market regime."""
        return _check_direction_gating_fn(self.config, signal)
    
    def _check_regime_avoidance(self, signal: Dict[str, Any]) -> CircuitBreakerDecision:
        """Phase 2: Optionally block signals in historically poor-performing regimes."""
        return _check_regime_avoidance_fn(self.config, signal)
    
    def _check_trigger_filters(self, signal: Dict[str, Any]) -> CircuitBreakerDecision:
        """Phase 3: De-risk low-quality trigger types."""
        return _check_trigger_filters_fn(self.config, signal)
    
    def _check_tv_paper_eval_gate(
        self,
        signal: Dict[str, Any],
        active_positions: Optional[List[Dict[str, Any]]] = None,
    ) -> CircuitBreakerDecision:
        """Tradovate Paper Evaluation Gate: enforce prop firm rules before order placement."""
        return _check_tv_paper_eval_gate_fn(self.config, signal, active_positions)


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
        kill_switch_short=False,
        max_consecutive_losses=config.get("max_consecutive_losses", 5),
        consecutive_loss_cooldown_minutes=config.get("consecutive_loss_cooldown_minutes", 30),
        max_session_drawdown=config.get("max_session_drawdown", 500.0),
        max_daily_drawdown=config.get("max_daily_drawdown", 1000.0),
        max_daily_profit=config.get("max_daily_profit", 3000.0),
        drawdown_cooldown_minutes=config.get("drawdown_cooldown_minutes", 60),
        rolling_window_trades=config.get("rolling_window_trades", 20),
        min_rolling_win_rate=config.get("min_rolling_win_rate", 0.30),
        win_rate_cooldown_minutes=config.get("win_rate_cooldown_minutes", 30),
        max_concurrent_positions=config.get("max_concurrent_positions", 5),
        min_price_distance_pct=config.get("min_price_distance_pct", 0.5),
        enable_volatility_filter=config.get("enable_volatility_filter", False),
        min_atr_ratio=config.get("min_atr_ratio", 0.8),
        max_atr_ratio=config.get("max_atr_ratio", 2.5),
        chop_detection_window=config.get("chop_detection_window", 10),
        chop_win_rate_threshold=config.get("chop_win_rate_threshold", 0.35),
        auto_resume_after_cooldown=config.get("auto_resume_after_cooldown", True),
        require_winning_trade_to_resume=config.get("require_winning_trade_to_resume", False),
        # Session filter settings
        enable_session_filter=config.get("enable_session_filter", False),
        allowed_sessions=config.get("allowed_sessions", []),
        # Hour-level filter
        enable_hour_filter=False,
        allowed_short_hours_et=[],
        allowed_trading_hours_et=config.get("allowed_trading_hours_et", list(range(24))),
        # Weekday filter
        blocked_weekdays=config.get("blocked_weekdays", []),
        enable_direction_gating=config.get("enable_direction_gating", False),
        direction_gating_min_confidence=config.get("direction_gating_min_confidence", 0.70),
        enable_regime_avoidance=config.get("enable_regime_avoidance", False),
        blocked_regimes=config.get("blocked_regimes", []),
        regime_avoidance_min_confidence=config.get("regime_avoidance_min_confidence", 0.70),
        enable_trigger_filters=config.get("enable_trigger_filters", False),
        ema_cross_require_volume=config.get("ema_cross_require_volume", True),
        low_regime_require_volume=config.get("low_regime_require_volume", True),
        # Equity curve filter
        enable_equity_curve_filter=config.get("enable_equity_curve_filter", False),
        equity_curve_lookback=config.get("equity_curve_lookback", 20),
        equity_curve_half_size_below_ma=config.get("equity_curve_half_size_below_ma", True),
        equity_curve_halt_atr_mult=config.get("equity_curve_halt_atr_mult", 1.5),
        # Tiered loss response
        enable_tiered_loss_response=config.get("enable_tiered_loss_response", False),
        tiered_loss_levels=config.get("tiered_loss_levels", [
            {"losses": 3, "risk_scale": 0.5, "action": "reduce"},
            {"losses": 5, "risk_scale": 0.25, "action": "reduce"},
            {"losses": 7, "risk_scale": 0.0, "action": "halt", "cooldown_minutes": 30},
            {"losses": 10, "risk_scale": 0.0, "action": "halt_session"},
        ]),
        # TOD risk scaling
        enable_tod_risk_scaling=config.get("enable_tod_risk_scaling", False),
        tod_risk_windows=config.get("tod_risk_windows", []),
        # Volatility risk scaling
        enable_volatility_risk_scaling=config.get("enable_volatility_risk_scaling", False),
        volatility_high_atr_ratio=config.get("volatility_high_atr_ratio", 1.5),
        volatility_high_risk_scale=config.get("volatility_high_risk_scale", 0.5),
        volatility_extreme_atr_ratio=config.get("volatility_extreme_atr_ratio", 2.0),
        volatility_extreme_risk_scale=config.get("volatility_extreme_risk_scale", 0.0),
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
