"""Extracted circuit breaker filter functions.

Each filter is a standalone function that takes config and relevant context,
returning a CircuitBreakerDecision. This keeps the main TradingCircuitBreaker
class focused on orchestration and state management.

All filters follow the signature:
    def check_*(config, ...) -> CircuitBreakerDecision
"""

from __future__ import annotations

from datetime import datetime, timezone, time as _time_cls
from typing import Any, Dict, List, Optional, Tuple

from pearlalgo.market_agent.circuit_breaker_types import (
    CircuitBreakerDecision,
    TradingCircuitBreakerConfig,
)
from pearlalgo.utils.logger import logger
from pearlalgo.utils.market_hours import ET, is_within_trading_window


# ============================================================================
# Time-based filters
# ============================================================================


def check_hour_filter(config: TradingCircuitBreakerConfig) -> CircuitBreakerDecision:
    """Block signals outside allowed trading hours (ET)."""
    now_et = datetime.now(ET)
    current_hour = now_et.hour
    if current_hour not in config.allowed_trading_hours_et:
        logger.info(
            "Hour filter: blocked signal at hour %d ET (allowed: %s)",
            current_hour, config.allowed_trading_hours_et,
        )
        return CircuitBreakerDecision(
            allowed=False,
            reason="hour_filter",
            severity="info",
            details={
                "current_hour_et": current_hour,
                "allowed_hours": config.allowed_trading_hours_et,
                "message": f"Hour {current_hour} ET is not in the allowed trading hours",
            },
        )
    return CircuitBreakerDecision(allowed=True, reason="hour_filter_passed")


def check_weekday_filter(config: TradingCircuitBreakerConfig) -> CircuitBreakerDecision:
    """Block signals on historically unprofitable weekdays."""
    now_et = datetime.now(ET)
    current_weekday = now_et.weekday()  # Mon=0, Sun=6
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if current_weekday in config.blocked_weekdays:
        day_name = day_names[current_weekday]
        logger.info(
            "Weekday filter: blocked signal on %s (weekday=%d)",
            day_name, current_weekday,
        )
        return CircuitBreakerDecision(
            allowed=False,
            reason="weekday_filter",
            severity="info",
            details={
                "current_weekday": current_weekday,
                "day_name": day_name,
                "blocked_weekdays": config.blocked_weekdays,
                "message": f"Trading is blocked on {day_name}",
            },
        )
    return CircuitBreakerDecision(allowed=True, reason="weekday_filter_passed")


def get_current_session(now: Optional[datetime] = None) -> Tuple[str, int]:
    """Get the current trading session based on Eastern Time.

    Returns:
        Tuple of (session_name, et_hour)
    """
    now = now or datetime.now(timezone.utc)
    et_dt = now.astimezone(ET)
    et_hour = et_dt.hour

    sessions = {
        'overnight': (18, 4),      # 6PM - 4AM ET
        'premarket': (4, 6),       # 4AM - 6AM ET
        'morning': (6, 10),        # 6AM - 10AM ET
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


def check_session_filter(config: TradingCircuitBreakerConfig) -> CircuitBreakerDecision:
    """Check if current session is allowed for trading.

    Based on historical data analysis:
    - Good sessions: overnight (63% WR), close (78% WR), midday (45% WR)
    - Bad sessions: morning (19% WR), afternoon (19% WR), premarket (22% WR)
    """
    current_session, et_hour = get_current_session()

    if current_session in config.allowed_sessions:
        return CircuitBreakerDecision(
            allowed=True,
            reason="session_allowed",
            details={
                "current_session": current_session,
                "et_hour": et_hour,
                "allowed_sessions": config.allowed_sessions,
            },
        )

    return CircuitBreakerDecision(
        allowed=False,
        reason="session_filtered",
        severity="info",
        details={
            "current_session": current_session,
            "et_hour": et_hour,
            "allowed_sessions": config.allowed_sessions,
            "message": f"Session '{current_session}' historically underperforms - signal skipped",
        },
    )


# ============================================================================
# Signal-quality filters
# ============================================================================


def check_direction_gating(
    config: TradingCircuitBreakerConfig,
    signal: Dict[str, Any],
) -> CircuitBreakerDecision:
    """Phase 1: Check if signal direction is allowed for the current market regime.

    Rules (when regime confidence >= threshold):
    - trending_up -> allow long only
    - trending_down -> allow short only
    - ranging/volatile/unknown -> allow long only (conservative)
    """
    direction = str(signal.get("direction", "")).lower()
    if direction not in ("long", "short"):
        return CircuitBreakerDecision(
            allowed=True,
            reason="direction_gating_unknown_direction",
            details={"direction": direction},
        )

    market_regime = signal.get("market_regime") or {}
    if not isinstance(market_regime, dict):
        market_regime = {}

    regime_type = str(market_regime.get("regime", "unknown")).lower()
    regime_confidence = 0.0
    try:
        regime_confidence = float(market_regime.get("confidence", 0.0))
    except (TypeError, ValueError):
        regime_confidence = 0.0

    effective_regime = regime_type
    if regime_confidence < config.direction_gating_min_confidence:
        effective_regime = "unknown"

    allowed_direction = "long"  # Default conservative
    if effective_regime == "trending_up":
        allowed_direction = "long"
    elif effective_regime == "trending_down":
        allowed_direction = "short"

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


def check_regime_avoidance(
    config: TradingCircuitBreakerConfig,
    signal: Dict[str, Any],
) -> CircuitBreakerDecision:
    """Phase 2: Optionally block signals in historically poor-performing regimes.

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

    if regime_confidence < config.regime_avoidance_min_confidence:
        return CircuitBreakerDecision(
            allowed=True,
            reason="regime_avoidance_low_confidence",
            details={
                "regime": regime_type,
                "regime_confidence": regime_confidence,
                "min_confidence": config.regime_avoidance_min_confidence,
            },
        )

    blocked_regimes_lower = [r.lower() for r in config.blocked_regimes]
    if regime_type in blocked_regimes_lower:
        return CircuitBreakerDecision(
            allowed=False,
            reason="regime_avoidance",
            severity="info",
            details={
                "regime": regime_type,
                "regime_confidence": regime_confidence,
                "blocked_regimes": config.blocked_regimes,
                "message": f"Regime '{regime_type}' is historically poor-performing - signal skipped",
            },
        )

    return CircuitBreakerDecision(
        allowed=True,
        reason="regime_avoidance_ok",
        details={"regime": regime_type, "regime_confidence": regime_confidence},
    )


def check_trigger_filters(
    config: TradingCircuitBreakerConfig,
    signal: Dict[str, Any],
) -> CircuitBreakerDecision:
    """Phase 3: De-risk low-quality trigger types.

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

    if config.ema_cross_require_volume and entry_trigger == "ema_cross":
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

    if config.low_regime_require_volume and regime_type in ("ranging", "volatile"):
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


def check_tv_paper_eval_gate(
    config: TradingCircuitBreakerConfig,
    signal: Dict[str, Any],
    active_positions: Optional[List[Dict[str, Any]]] = None,
) -> CircuitBreakerDecision:
    """Tradovate Paper Evaluation Gate: enforce prop firm rules before order placement."""
    now_utc = datetime.now(timezone.utc)
    in_session = is_within_trading_window(
        now_utc,
        start_hour_et=config.tv_paper_trading_start_hour_et,
        start_minute_et=0,
        end_hour_et=config.tv_paper_trading_end_hour_et,
        end_minute_et=config.tv_paper_trading_end_minute_et,
    )
    if not in_session:
        try:
            now_et = now_utc.astimezone(ET)
            et_time = now_et.time()
        except Exception:
            et_time = now_utc.time()
        session_open = _time_cls(config.tv_paper_trading_start_hour_et, 0)
        session_close = _time_cls(
            config.tv_paper_trading_end_hour_et,
            config.tv_paper_trading_end_minute_et,
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

    # Check max contracts
    if active_positions:
        total_qty = sum(
            abs(int(p.get("position_size", 0) or p.get("quantity", 0) or 1))
            for p in active_positions
        )
        new_qty = int(signal.get("position_size", 1))
        if total_qty + new_qty > config.tv_paper_max_contracts_mini:
            return CircuitBreakerDecision(
                allowed=False,
                reason="tv_paper_max_contracts_exceeded",
                severity="critical",
                details={
                    "current_contracts": total_qty,
                    "new_contracts": new_qty,
                    "max_allowed": config.tv_paper_max_contracts_mini,
                },
            )

    # No hedging
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

    # News blackout
    if config.tv_paper_enable_news_blackout:
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
