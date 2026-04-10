"""Shared types for the trading circuit breaker subsystem.

Extracted to break circular imports between trading_circuit_breaker.py and
circuit_breaker_filters.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class CircuitBreakerDecision:
    """Result of circuit breaker evaluation.

    ``risk_scale`` (0.0-1.0) lets the CB *reduce* position size instead of
    outright blocking.  A value of 1.0 means full size; 0.5 means half; 0.0
    means block.  The signal handler multiplies the computed position_size by
    the minimum risk_scale across all checks.
    """
    allowed: bool
    reason: str
    severity: str = "info"  # info, warning, critical
    details: Dict[str, Any] = field(default_factory=dict)
    risk_scale: float = 1.0  # 0.0-1.0, applied to position size

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "severity": self.severity,
            "details": self.details,
            "risk_scale": self.risk_scale,
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
    max_daily_profit: float = 3000.0  # USD — stop trading after hitting profit target
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
    max_atr_ratio: float = 2.5  # ATR must be <= 250% of recent average
    chop_detection_window: int = 10
    chop_win_rate_threshold: float = 0.35

    # Auto-recovery
    auto_resume_after_cooldown: bool = True
    require_winning_trade_to_resume: bool = False

    # Session filter
    enable_session_filter: bool = True
    allowed_sessions: List[str] = field(default_factory=lambda: ["overnight", "midday", "close"])

    # Hour-level filter
    enable_hour_filter: bool = False
    allowed_trading_hours_et: List[int] = field(default_factory=lambda: list(range(24)))
    allowed_short_hours_et: List[int] = field(default_factory=list)

    # Weekday filter
    blocked_weekdays: List[int] = field(default_factory=list)

    # Phase 1: Direction gating by market regime
    enable_direction_gating: bool = True
    direction_gating_min_confidence: float = 0.70

    # Phase 2: Regime avoidance
    enable_regime_avoidance: bool = False
    blocked_regimes: List[str] = field(default_factory=lambda: ["ranging", "volatile"])
    regime_avoidance_min_confidence: float = 0.70

    # Phase 3: Trigger-based de-risking filters
    enable_trigger_filters: bool = False
    ema_cross_require_volume: bool = True
    low_regime_require_volume: bool = True

    # =========================================================================
    # Equity Curve Filter — trade only when equity is above its own MA
    # =========================================================================
    enable_equity_curve_filter: bool = False
    equity_curve_lookback: int = 20  # trades for EMA
    equity_curve_half_size_below_ma: bool = True  # half size when below MA
    equity_curve_halt_atr_mult: float = 1.5  # halt when equity is > 1.5 ATR below MA

    # =========================================================================
    # Tiered Consecutive Loss Response — scale down before halting
    # =========================================================================
    enable_tiered_loss_response: bool = False
    tiered_loss_levels: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"losses": 3, "risk_scale": 0.5, "action": "reduce"},
        {"losses": 5, "risk_scale": 0.25, "action": "reduce"},
        {"losses": 7, "risk_scale": 0.0, "action": "halt", "cooldown_minutes": 30},
        {"losses": 10, "risk_scale": 0.0, "action": "halt_session"},
    ])

    # =========================================================================
    # Time-of-Day Risk Windows — reduce exposure during weak hours
    # =========================================================================
    enable_tod_risk_scaling: bool = False
    tod_risk_windows: List[Dict[str, Any]] = field(default_factory=lambda: [
        # {"start_hour_et": 15, "end_hour_et": 18, "risk_scale": 0.5}
    ])

    # =========================================================================
    # Volatility-Adjusted Risk Scaling — cut size in high-ATR environments
    # =========================================================================
    enable_volatility_risk_scaling: bool = False
    volatility_high_atr_ratio: float = 1.5  # ATR/avg_ATR above this → scale down
    volatility_high_risk_scale: float = 0.5  # scale factor when ATR is elevated
    volatility_extreme_atr_ratio: float = 2.0  # above this → halt
    volatility_extreme_risk_scale: float = 0.0  # 0.0 = block

    # Tradovate Paper Evaluation Gate
    enable_tv_paper_eval_gate: bool = False
    tv_paper_max_contracts_mini: int = 5
    tv_paper_max_contracts_micro: int = 50
    tv_paper_trading_start_hour_et: int = 18
    tv_paper_trading_end_hour_et: int = 16
    tv_paper_trading_end_minute_et: int = 10
    tv_paper_near_max_loss_buffer: float = 200.0
    tv_paper_enable_news_blackout: bool = True
