"""
Adaptive Position Sizing with Kelly Criterion

Intelligent position sizing that adapts to:
- Kelly Criterion based on historical win rate and payoff
- Market regime favorability
- Trading session (reduced size during Tokyo/London)
- Recent performance (winning/losing streaks)
- Volatility conditions
- Signal confidence

Replaces simple confidence-based sizing with mathematically optimal sizing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pearlalgo.utils.logger import logger


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class AdaptiveSizingConfig:
    """Configuration for adaptive position sizing."""
    
    # Kelly Criterion settings
    method: str = "kelly_criterion"  # "kelly_criterion", "fixed", or "hybrid"
    kelly_fraction: float = 0.25     # Conservative Kelly (1/4 Kelly)
    
    # Position size limits
    min_contracts: int = 1
    max_contracts: int = 15
    
    # Feature toggles
    confidence_scaling: bool = True
    regime_scaling: bool = True
    session_scaling: bool = True
    streak_adjustment: bool = True
    volatility_scaling: bool = True
    
    # Streak settings
    max_losing_streak_reduction: float = 0.5  # Reduce to 50% after losing streak
    losing_streak_threshold: int = 3          # Start reducing after 3 losses
    winning_streak_boost: float = 1.2         # Boost to 120% during win streak
    winning_streak_threshold: int = 3         # Start boosting after 3 wins
    
    # Session multipliers
    session_multipliers: Dict[str, float] = field(default_factory=lambda: {
        "tokyo": 0.5,
        "asia": 0.5,
        "london": 0.7,
        "new_york": 1.0,
        "overlap": 0.8,
        "unknown": 0.6,
    })
    
    # Volatility multipliers
    volatility_multipliers: Dict[str, float] = field(default_factory=lambda: {
        "low": 1.0,
        "normal": 1.0,
        "high": 0.7,
        "extreme": 0.4,
    })
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "AdaptiveSizingConfig":
        """Create from dictionary configuration."""
        sizing_config = config.get("adaptive_sizing", {})
        
        return cls(
            method=sizing_config.get("method", "kelly_criterion"),
            kelly_fraction=sizing_config.get("kelly_fraction", 0.25),
            min_contracts=sizing_config.get("min_contracts", 1),
            max_contracts=sizing_config.get("max_contracts", 15),
            confidence_scaling=sizing_config.get("confidence_scaling", True),
            regime_scaling=sizing_config.get("regime_scaling", True),
            session_scaling=sizing_config.get("session_scaling", True),
            streak_adjustment=sizing_config.get("streak_adjustment", True),
            volatility_scaling=sizing_config.get("volatility_scaling", True),
        )


# =============================================================================
# Signal Type Statistics
# =============================================================================

@dataclass
class SignalTypeStats:
    """Statistics for a signal type used in sizing calculations."""
    signal_type: str
    
    # Historical performance
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    
    # Payoff statistics
    total_profit: float = 0.0
    total_loss: float = 0.0
    avg_win: float = 200.0
    avg_loss: float = 150.0
    
    # Calculated metrics
    win_rate: float = 0.5
    profit_factor: float = 1.0
    expectancy: float = 0.0
    
    # Kelly optimal fraction
    kelly_fraction: float = 0.0
    
    def update_from_trades(self, trades: List[Dict]) -> None:
        """Update statistics from list of trades."""
        if not trades:
            return
        
        wins = [t for t in trades if t.get("is_win", False)]
        losses = [t for t in trades if not t.get("is_win", False)]
        
        self.total_trades = len(trades)
        self.wins = len(wins)
        self.losses = len(losses)
        
        # Calculate average win/loss
        if wins:
            self.total_profit = sum(t.get("pnl", 0) for t in wins)
            self.avg_win = self.total_profit / len(wins)
        
        if losses:
            self.total_loss = abs(sum(t.get("pnl", 0) for t in losses))
            self.avg_loss = self.total_loss / len(losses)
        
        # Calculate metrics
        if self.total_trades > 0:
            self.win_rate = self.wins / self.total_trades
        
        if self.total_loss > 0:
            self.profit_factor = self.total_profit / self.total_loss
        
        # Expectancy = (WR * AvgWin) - ((1-WR) * AvgLoss)
        self.expectancy = (
            self.win_rate * self.avg_win -
            (1 - self.win_rate) * self.avg_loss
        )
        
        # Kelly fraction = WR - ((1-WR) / (AvgWin/AvgLoss))
        if self.avg_loss > 0:
            b = self.avg_win / self.avg_loss  # Payoff ratio
            p = self.win_rate
            q = 1 - p
            
            if b > 0:
                self.kelly_fraction = max(0, (p * b - q) / b)
            else:
                self.kelly_fraction = 0.0
        else:
            self.kelly_fraction = 0.0


# =============================================================================
# Sizing Result
# =============================================================================

@dataclass
class PositionSizeResult:
    """Result of position size calculation."""
    contracts: int
    
    # Base calculation
    kelly_optimal: float
    kelly_adjusted: float  # After fractional Kelly
    
    # Adjustment factors
    confidence_factor: float = 1.0
    regime_factor: float = 1.0
    session_factor: float = 1.0
    streak_factor: float = 1.0
    volatility_factor: float = 1.0
    
    # Metadata
    signal_type: str = ""
    raw_size: float = 0.0
    capped_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "contracts": self.contracts,
            "kelly_optimal": self.kelly_optimal,
            "kelly_adjusted": self.kelly_adjusted,
            "confidence_factor": self.confidence_factor,
            "regime_factor": self.regime_factor,
            "session_factor": self.session_factor,
            "streak_factor": self.streak_factor,
            "volatility_factor": self.volatility_factor,
            "signal_type": self.signal_type,
            "raw_size": self.raw_size,
            "capped_reason": self.capped_reason,
        }


# =============================================================================
# Adaptive Position Sizer
# =============================================================================

class AdaptivePositionSizer:
    """
    Adaptive position sizing using Kelly Criterion and context adjustments.
    
    The Kelly Criterion provides mathematically optimal bet sizing:
    f* = (p * b - q) / b
    
    Where:
    - p = probability of winning (win rate)
    - q = probability of losing (1 - p)
    - b = payoff ratio (avg win / avg loss)
    - f* = optimal fraction of capital to risk
    
    We use fractional Kelly (typically 1/4 Kelly) to reduce variance.
    """
    
    def __init__(
        self,
        config: Optional[AdaptiveSizingConfig] = None,
        base_contracts: int = 5,
        account_balance: float = 50000.0,
        risk_per_trade_pct: float = 0.01,  # 1% risk per trade
    ):
        """
        Initialize the adaptive position sizer.
        
        Args:
            config: Sizing configuration
            base_contracts: Base position size when stats unavailable
            account_balance: Account balance for sizing calculations
            risk_per_trade_pct: Maximum risk per trade as percentage
        """
        self.config = config or AdaptiveSizingConfig()
        self.base_contracts = base_contracts
        self.account_balance = account_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        
        # Signal type statistics
        self._signal_stats: Dict[str, SignalTypeStats] = {}
        
        # Recent trades for streak tracking
        self._recent_trades: List[Dict] = []
        self._max_recent_trades = 50
        
        logger.info(
            f"AdaptivePositionSizer initialized: "
            f"method={self.config.method}, "
            f"kelly_fraction={self.config.kelly_fraction}, "
            f"base={base_contracts}, "
            f"limits=[{self.config.min_contracts}, {self.config.max_contracts}]"
        )
    
    def calculate_position_size(
        self,
        signal: Dict[str, Any],
        context: Dict[str, Any],
        stop_distance_points: float,
    ) -> PositionSizeResult:
        """
        Calculate adaptive position size.
        
        Args:
            signal: Signal dictionary with type, confidence, etc.
            context: Market context with regime, session, volatility
            stop_distance_points: Stop loss distance in points
            
        Returns:
            PositionSizeResult with calculated size and factors
        """
        signal_type = signal.get("type", "unknown")
        confidence = signal.get("confidence", 0.5)
        
        # Get signal type statistics
        stats = self._get_signal_stats(signal_type)
        
        # Calculate Kelly optimal size
        kelly_optimal = self._calculate_kelly_size(stats, stop_distance_points)
        
        # Apply fractional Kelly
        kelly_adjusted = kelly_optimal * self.config.kelly_fraction
        
        # Start with Kelly-adjusted size
        raw_size = kelly_adjusted
        
        # If no meaningful Kelly (insufficient data), use base contracts
        if kelly_adjusted <= 0 or stats.total_trades < 10:
            raw_size = float(self.base_contracts)
        
        # Apply adjustment factors
        confidence_factor = 1.0
        regime_factor = 1.0
        session_factor = 1.0
        streak_factor = 1.0
        volatility_factor = 1.0
        
        # 1. Confidence adjustment
        if self.config.confidence_scaling:
            confidence_factor = self._calculate_confidence_factor(confidence)
        
        # 2. Regime adjustment
        if self.config.regime_scaling:
            regime_factor = self._calculate_regime_factor(
                signal_type, context.get("regime", {})
            )
        
        # 3. Session adjustment
        if self.config.session_scaling:
            session = context.get("regime", {}).get("session", "unknown")
            session_factor = self._calculate_session_factor(session)
        
        # 4. Streak adjustment
        if self.config.streak_adjustment:
            streak_factor = self._calculate_streak_factor()
        
        # 5. Volatility adjustment
        if self.config.volatility_scaling:
            volatility = context.get("regime", {}).get("volatility", "normal")
            volatility_factor = self._calculate_volatility_factor(volatility)
        
        # Apply all factors
        final_size = (
            raw_size *
            confidence_factor *
            regime_factor *
            session_factor *
            streak_factor *
            volatility_factor
        )
        
        # Determine capping reason
        capped_reason = ""
        if final_size < self.config.min_contracts:
            capped_reason = f"Below minimum ({self.config.min_contracts})"
        elif final_size > self.config.max_contracts:
            capped_reason = f"Above maximum ({self.config.max_contracts})"
        
        # Apply limits
        contracts = int(np.clip(
            round(final_size),
            self.config.min_contracts,
            self.config.max_contracts,
        ))
        
        result = PositionSizeResult(
            contracts=contracts,
            kelly_optimal=kelly_optimal,
            kelly_adjusted=kelly_adjusted,
            confidence_factor=confidence_factor,
            regime_factor=regime_factor,
            session_factor=session_factor,
            streak_factor=streak_factor,
            volatility_factor=volatility_factor,
            signal_type=signal_type,
            raw_size=final_size,
            capped_reason=capped_reason,
        )
        
        logger.debug(
            f"Position size for {signal_type}: {contracts} contracts "
            f"(kelly={kelly_optimal:.1f}, factors: conf={confidence_factor:.2f}, "
            f"regime={regime_factor:.2f}, session={session_factor:.2f}, "
            f"streak={streak_factor:.2f}, vol={volatility_factor:.2f})"
        )
        
        return result
    
    def _calculate_kelly_size(
        self,
        stats: SignalTypeStats,
        stop_distance_points: float,
    ) -> float:
        """
        Calculate Kelly optimal position size.
        
        Args:
            stats: Signal type statistics
            stop_distance_points: Stop distance in points
            
        Returns:
            Kelly optimal number of contracts
        """
        if stats.kelly_fraction <= 0 or stop_distance_points <= 0:
            return 0.0
        
        # Kelly fraction is fraction of capital to risk
        kelly_capital = self.account_balance * stats.kelly_fraction
        
        # Convert to contracts based on stop distance
        # For MNQ: 1 point = $2
        risk_per_contract = stop_distance_points * 2.0  # MNQ point value
        
        if risk_per_contract > 0:
            kelly_contracts = kelly_capital / risk_per_contract
        else:
            kelly_contracts = 0.0
        
        return kelly_contracts
    
    def _calculate_confidence_factor(self, confidence: float) -> float:
        """
        Calculate confidence adjustment factor.
        
        Higher confidence = larger position (up to 1.5x)
        Lower confidence = smaller position (down to 0.5x)
        """
        # Linear scaling: conf 0.5 -> 0.7x, conf 0.7 -> 1.0x, conf 0.9 -> 1.3x
        if confidence >= 0.9:
            return 1.3
        elif confidence >= 0.8:
            return 1.15
        elif confidence >= 0.7:
            return 1.0
        elif confidence >= 0.6:
            return 0.85
        else:
            return 0.7
    
    def _calculate_regime_factor(
        self,
        signal_type: str,
        regime: Dict[str, Any],
    ) -> float:
        """
        Calculate regime adjustment factor.
        
        Favorable regime = 1.0 (full size)
        Unfavorable regime = 0.5-0.7 (reduced size)
        """
        regime_type = regime.get("regime", "unknown").lower()
        
        # Define favorable regimes per signal type
        favorable_regimes = {
            "mean_reversion_long": ["ranging", "trending_bullish"],
            "mean_reversion_short": ["ranging", "trending_bearish"],
            "momentum_long": ["trending_bullish"],
            "momentum_short": ["trending_bearish"],
            "sr_bounce_long": ["ranging", "trending_bullish"],
            "sr_bounce_short": ["ranging", "trending_bearish"],
            "breakout_long": ["trending_bullish"],
            "breakout_short": ["trending_bearish"],
        }
        
        # Check if current regime is favorable
        signal_favorable = favorable_regimes.get(signal_type, [])
        
        if regime_type in signal_favorable:
            return 1.0  # Full size in favorable regime
        elif regime_type in ["ranging"]:
            return 0.9  # Slightly reduced in ranging
        else:
            return 0.6  # Significantly reduced in unfavorable regime
    
    def _calculate_session_factor(self, session: str) -> float:
        """Calculate session adjustment factor."""
        return self.config.session_multipliers.get(session.lower(), 0.6)
    
    def _calculate_streak_factor(self) -> float:
        """
        Calculate streak adjustment factor.
        
        Losing streak = reduce size
        Winning streak = boost size (cautiously)
        """
        if not self._recent_trades:
            return 1.0
        
        # Calculate current streak
        streak_count = 0
        streak_type: Optional[bool] = None
        
        for trade in reversed(self._recent_trades):
            is_win = trade.get("is_win", False)
            
            if streak_type is None:
                streak_type = is_win
                streak_count = 1
            elif is_win == streak_type:
                streak_count += 1
            else:
                break
        
        # Apply streak adjustments
        if streak_type is False:  # Losing streak
            if streak_count >= self.config.losing_streak_threshold:
                # Reduce size progressively
                reduction = max(
                    self.config.max_losing_streak_reduction,
                    1.0 - (streak_count - self.config.losing_streak_threshold + 1) * 0.1,
                )
                return reduction
        elif streak_type is True:  # Winning streak
            if streak_count >= self.config.winning_streak_threshold:
                # Boost size cautiously
                boost = min(
                    self.config.winning_streak_boost,
                    1.0 + (streak_count - self.config.winning_streak_threshold + 1) * 0.05,
                )
                return boost
        
        return 1.0
    
    def _calculate_volatility_factor(self, volatility: str) -> float:
        """Calculate volatility adjustment factor."""
        return self.config.volatility_multipliers.get(volatility.lower(), 1.0)
    
    def _get_signal_stats(self, signal_type: str) -> SignalTypeStats:
        """Get or create statistics for a signal type."""
        if signal_type not in self._signal_stats:
            self._signal_stats[signal_type] = SignalTypeStats(
                signal_type=signal_type
            )
        return self._signal_stats[signal_type]
    
    def update_from_trades(self, trades: List[Dict]) -> None:
        """
        Update statistics from trade history.
        
        Args:
            trades: List of completed trade dictionaries
        """
        # Update recent trades for streak tracking
        self._recent_trades = trades[-self._max_recent_trades:]
        
        # Group trades by signal type
        trades_by_type: Dict[str, List[Dict]] = {}
        for trade in trades:
            signal_type = trade.get("signal_type", "unknown")
            if signal_type not in trades_by_type:
                trades_by_type[signal_type] = []
            trades_by_type[signal_type].append(trade)
        
        # Update stats for each signal type
        for signal_type, type_trades in trades_by_type.items():
            if signal_type not in self._signal_stats:
                self._signal_stats[signal_type] = SignalTypeStats(
                    signal_type=signal_type
                )
            self._signal_stats[signal_type].update_from_trades(type_trades)
        
        logger.debug(
            f"Updated position sizer from {len(trades)} trades, "
            f"{len(trades_by_type)} signal types"
        )
    
    def add_completed_trade(self, trade: Dict) -> None:
        """
        Add a single completed trade.
        
        Args:
            trade: Completed trade dictionary
        """
        self._recent_trades.append(trade)
        if len(self._recent_trades) > self._max_recent_trades:
            self._recent_trades = self._recent_trades[-self._max_recent_trades:]
        
        # Update signal type stats
        signal_type = trade.get("signal_type", "unknown")
        stats = self._get_signal_stats(signal_type)
        
        # Simple incremental update
        stats.total_trades += 1
        if trade.get("is_win", False):
            stats.wins += 1
            pnl = trade.get("pnl", 0)
            stats.total_profit += pnl
            if stats.wins > 0:
                stats.avg_win = stats.total_profit / stats.wins
        else:
            stats.losses += 1
            pnl = abs(trade.get("pnl", 0))
            stats.total_loss += pnl
            if stats.losses > 0:
                stats.avg_loss = stats.total_loss / stats.losses
        
        # Recalculate metrics
        if stats.total_trades > 0:
            stats.win_rate = stats.wins / stats.total_trades
        
        if stats.total_loss > 0:
            stats.profit_factor = stats.total_profit / stats.total_loss
        
        stats.expectancy = (
            stats.win_rate * stats.avg_win -
            (1 - stats.win_rate) * stats.avg_loss
        )
        
        # Recalculate Kelly
        if stats.avg_loss > 0 and stats.avg_win > 0:
            b = stats.avg_win / stats.avg_loss
            p = stats.win_rate
            q = 1 - p
            stats.kelly_fraction = max(0, (p * b - q) / b)
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """Get summary of all signal type statistics."""
        return {
            signal_type: {
                "total_trades": stats.total_trades,
                "win_rate": stats.win_rate,
                "avg_win": stats.avg_win,
                "avg_loss": stats.avg_loss,
                "expectancy": stats.expectancy,
                "kelly_fraction": stats.kelly_fraction,
                "profit_factor": stats.profit_factor,
            }
            for signal_type, stats in self._signal_stats.items()
        }
    
    def get_current_streak(self) -> Tuple[str, int]:
        """Get current streak type and length."""
        if not self._recent_trades:
            return "none", 0
        
        streak_count = 0
        streak_type: Optional[bool] = None
        
        for trade in reversed(self._recent_trades):
            is_win = trade.get("is_win", False)
            
            if streak_type is None:
                streak_type = is_win
                streak_count = 1
            elif is_win == streak_type:
                streak_count += 1
            else:
                break
        
        type_str = "win" if streak_type else "loss" if streak_type is False else "none"
        return type_str, streak_count


# =============================================================================
# Factory Function
# =============================================================================

def get_adaptive_position_sizer(
    config: Optional[Dict[str, Any]] = None,
    trades: Optional[List[Dict]] = None,
) -> AdaptivePositionSizer:
    """
    Create an AdaptivePositionSizer from configuration.
    
    Args:
        config: Configuration dictionary
        trades: Optional list of historical trades for initialization
        
    Returns:
        AdaptivePositionSizer instance
    """
    if config is None:
        config = {}
    
    sizing_config = AdaptiveSizingConfig.from_dict(config)
    
    # Get base contracts from strategy config
    strategy_config = config.get("strategy", {})
    base_contracts = strategy_config.get("base_contracts", 5)
    
    # Get risk settings
    risk_config = config.get("risk", {})
    risk_per_trade = risk_config.get("max_risk_per_trade", 0.01)
    
    # Create sizer
    sizer = AdaptivePositionSizer(
        config=sizing_config,
        base_contracts=base_contracts,
        risk_per_trade_pct=risk_per_trade,
    )
    
    # Initialize from trades if provided
    if trades:
        sizer.update_from_trades(trades)
    
    return sizer

