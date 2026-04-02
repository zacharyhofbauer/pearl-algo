"""Shared types for the trading circuit breaker subsystem.

Extracted to break circular imports between trading_circuit_breaker.py and
circuit_breaker_filters.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


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

    # Phase 4: ML chop shield
    enable_ml_chop_shield: bool = False
    ml_min_scored_trades: int = 50
    ml_min_winrate_delta: float = 0.15
    ml_chop_shield_regimes: List[str] = field(default_factory=lambda: ["ranging", "volatile"])

    # Tradovate Paper Evaluation Gate
    enable_tv_paper_eval_gate: bool = False
    tv_paper_max_contracts_mini: int = 5
    tv_paper_max_contracts_micro: int = 50
    tv_paper_trading_start_hour_et: int = 18
    tv_paper_trading_end_hour_et: int = 16
    tv_paper_trading_end_minute_et: int = 10
    tv_paper_near_max_loss_buffer: float = 200.0
    tv_paper_enable_news_blackout: bool = True
