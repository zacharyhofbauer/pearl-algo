"""
Risk Metrics for Virtual P&L Tracking

Computes advanced risk-adjusted performance metrics:
- Sharpe Ratio
- Sortino Ratio  
- Maximum Drawdown
- Kelly Criterion position sizing
- Win rate by regime/time
- Slippage modeling
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pearlalgo.utils.logger import logger


@dataclass
class RiskMetricsConfig:
    """Configuration for risk metrics calculation."""
    # Risk-free rate for Sharpe/Sortino (annualized)
    risk_free_rate: float = 0.05  # 5% annual
    
    # Trading days per year (for annualization)
    trading_days_per_year: int = 252
    
    # Slippage model
    base_slippage_ticks: float = 0.5
    volatility_slippage_mult: float = 0.5  # Additional slippage in high vol
    
    # Kelly fraction (use fractional Kelly for safety)
    kelly_fraction: float = 0.25  # 1/4 Kelly is common
    max_kelly_size: float = 2.0   # Cap at 2x base size
    min_kelly_size: float = 0.25  # Floor at 0.25x base size
    
    # MNQ-specific
    tick_value: float = 0.5      # MNQ = $0.50 per tick
    point_value: float = 2.0     # MNQ = $2.00 per point
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "RiskMetricsConfig":
        """Create from dictionary."""
        return cls(
            risk_free_rate=float(config.get("risk_free_rate", 0.05)),
            trading_days_per_year=int(config.get("trading_days_per_year", 252)),
            base_slippage_ticks=float(config.get("base_slippage_ticks", 0.5)),
            volatility_slippage_mult=float(config.get("volatility_slippage_mult", 0.5)),
            kelly_fraction=float(config.get("kelly_fraction", 0.25)),
            max_kelly_size=float(config.get("max_kelly_size", 2.0)),
            min_kelly_size=float(config.get("min_kelly_size", 0.25)),
            tick_value=float(config.get("tick_value", 0.5)),
            point_value=float(config.get("point_value", 2.0)),
        )


@dataclass
class TradeResult:
    """Single trade result for analysis."""
    signal_id: str
    signal_type: str
    direction: str  # "long" or "short"
    entry_price: float
    exit_price: float
    pnl: float
    is_win: bool
    hold_duration_minutes: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str  # "stop_loss", "take_profit", "manual", etc.
    regime: Optional[str] = None  # Market regime at entry
    contracts: int = 1
    slippage: float = 0.0  # Estimated slippage in dollars
    
    @property
    def net_pnl(self) -> float:
        """P&L after slippage."""
        return self.pnl - self.slippage
    
    @property
    def return_pct(self) -> float:
        """Return as percentage of entry price."""
        if self.direction == "long":
            return (self.exit_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.exit_price) / self.entry_price
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "net_pnl": self.net_pnl,
            "is_win": self.is_win,
            "hold_duration_minutes": self.hold_duration_minutes,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_reason": self.exit_reason,
            "regime": self.regime,
            "contracts": self.contracts,
            "slippage": self.slippage,
            "return_pct": self.return_pct,
        }


@dataclass
class PerformanceMetrics:
    """Computed performance metrics."""
    # Basic stats
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    
    # P&L
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    profit_factor: float = 0.0
    
    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    calmar_ratio: float = 0.0  # Annualized return / max drawdown
    
    # Kelly
    kelly_criterion: float = 0.0
    optimal_size_multiplier: float = 1.0
    
    # Timing
    avg_hold_minutes: float = 0.0
    avg_win_hold_minutes: float = 0.0
    avg_loss_hold_minutes: float = 0.0
    
    # Slippage
    total_slippage: float = 0.0
    avg_slippage: float = 0.0
    
    # Breakdown
    by_signal_type: Dict[str, Dict] = field(default_factory=dict)
    by_regime: Dict[str, Dict] = field(default_factory=dict)
    by_hour: Dict[int, Dict] = field(default_factory=dict)
    by_day_of_week: Dict[int, Dict] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 2),
            "avg_pnl": round(self.avg_pnl, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "largest_win": round(self.largest_win, 2),
            "largest_loss": round(self.largest_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "kelly_criterion": round(self.kelly_criterion, 4),
            "optimal_size_multiplier": round(self.optimal_size_multiplier, 2),
            "avg_hold_minutes": round(self.avg_hold_minutes, 1),
            "avg_win_hold_minutes": round(self.avg_win_hold_minutes, 1),
            "avg_loss_hold_minutes": round(self.avg_loss_hold_minutes, 1),
            "total_slippage": round(self.total_slippage, 2),
            "avg_slippage": round(self.avg_slippage, 2),
            "by_signal_type": self.by_signal_type,
            "by_regime": self.by_regime,
            "by_hour": self.by_hour,
            "by_day_of_week": self.by_day_of_week,
        }


class RiskMetricsCalculator:
    """
    Calculates risk-adjusted performance metrics.
    
    Provides:
    - Sharpe and Sortino ratios
    - Maximum drawdown tracking
    - Kelly Criterion position sizing
    - Performance breakdown by various dimensions
    - Slippage estimation
    """
    
    def __init__(self, config: Optional[RiskMetricsConfig] = None):
        """
        Initialize risk metrics calculator.
        
        Args:
            config: Configuration (defaults if not provided)
        """
        self.config = config or RiskMetricsConfig()
        self._trades: List[TradeResult] = []
        self._equity_curve: List[float] = [0.0]  # Starting equity = 0
        
        logger.info("RiskMetricsCalculator initialized")
    
    def add_trade(self, trade: TradeResult) -> None:
        """
        Add a completed trade for analysis.
        
        Args:
            trade: Completed trade result
        """
        self._trades.append(trade)
        self._equity_curve.append(self._equity_curve[-1] + trade.net_pnl)
        
        logger.debug(f"Trade added: {trade.signal_type} | PnL=${trade.pnl:.2f} | Net=${trade.net_pnl:.2f}")
    
    def add_trade_from_dict(self, trade_dict: Dict) -> None:
        """
        Add trade from dictionary format.
        
        Args:
            trade_dict: Trade dictionary (from performance tracker)
        """
        # Parse entry/exit times
        entry_time = trade_dict.get("entry_time")
        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
            except:
                entry_time = datetime.now(timezone.utc)
        elif not entry_time:
            entry_time = datetime.now(timezone.utc)
        
        exit_time = trade_dict.get("exit_time")
        if isinstance(exit_time, str):
            try:
                exit_time = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
            except:
                exit_time = datetime.now(timezone.utc)
        elif not exit_time:
            exit_time = datetime.now(timezone.utc)
        
        # Estimate slippage
        slippage = self.estimate_slippage(
            entry_price=float(trade_dict.get("entry_price", 0)),
            contracts=int(trade_dict.get("contracts", 1)),
            volatility_percentile=float(trade_dict.get("volatility_percentile", 0.5)),
        )
        
        trade = TradeResult(
            signal_id=str(trade_dict.get("signal_id", "")),
            signal_type=str(trade_dict.get("signal_type", "unknown")),
            direction=str(trade_dict.get("direction", "long")),
            entry_price=float(trade_dict.get("entry_price", 0)),
            exit_price=float(trade_dict.get("exit_price", 0)),
            pnl=float(trade_dict.get("pnl", 0)),
            is_win=bool(trade_dict.get("is_win", False)),
            hold_duration_minutes=float(trade_dict.get("hold_duration_minutes", 0)),
            entry_time=entry_time,
            exit_time=exit_time,
            exit_reason=str(trade_dict.get("exit_reason", "")),
            regime=trade_dict.get("regime"),
            contracts=int(trade_dict.get("contracts", 1)),
            slippage=slippage,
        )
        
        self.add_trade(trade)
    
    def estimate_slippage(
        self,
        entry_price: float,
        contracts: int = 1,
        volatility_percentile: float = 0.5,
    ) -> float:
        """
        Estimate slippage for a trade.
        
        Args:
            entry_price: Entry price
            contracts: Number of contracts
            volatility_percentile: Current volatility percentile (0-1)
            
        Returns:
            Estimated slippage in dollars (round-trip)
        """
        # Base slippage per contract (entry + exit)
        base_slippage = self.config.base_slippage_ticks * self.config.tick_value * 2  # Round-trip
        
        # Add volatility component
        vol_slippage = self.config.volatility_slippage_mult * volatility_percentile * base_slippage
        
        # Total per contract
        slippage_per_contract = base_slippage + vol_slippage
        
        return slippage_per_contract * contracts
    
    def compute_metrics(self, lookback_days: Optional[int] = None) -> PerformanceMetrics:
        """
        Compute all performance metrics.
        
        Args:
            lookback_days: Only consider trades from last N days (None = all)
            
        Returns:
            PerformanceMetrics with all computed values
        """
        if not self._trades:
            return PerformanceMetrics()
        
        # Filter trades by lookback
        trades = self._trades
        if lookback_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            trades = [t for t in trades if t.exit_time >= cutoff]
        
        if not trades:
            return PerformanceMetrics()
        
        metrics = PerformanceMetrics()
        
        # Basic stats
        metrics.total_trades = len(trades)
        metrics.wins = sum(1 for t in trades if t.is_win)
        metrics.losses = metrics.total_trades - metrics.wins
        metrics.win_rate = metrics.wins / metrics.total_trades
        
        # P&L
        pnls = [t.net_pnl for t in trades]
        metrics.total_pnl = sum(pnls)
        metrics.avg_pnl = np.mean(pnls)
        
        win_pnls = [t.net_pnl for t in trades if t.is_win]
        loss_pnls = [t.net_pnl for t in trades if not t.is_win]
        
        metrics.avg_win = np.mean(win_pnls) if win_pnls else 0.0
        metrics.avg_loss = np.mean(loss_pnls) if loss_pnls else 0.0
        metrics.largest_win = max(pnls) if pnls else 0.0
        metrics.largest_loss = min(pnls) if pnls else 0.0
        
        # Profit factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        metrics.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Risk metrics
        metrics.sharpe_ratio = self._compute_sharpe_ratio(pnls)
        metrics.sortino_ratio = self._compute_sortino_ratio(pnls)
        metrics.max_drawdown, metrics.max_drawdown_pct = self._compute_max_drawdown(pnls)
        
        # Calmar ratio (annualized return / max drawdown)
        if metrics.max_drawdown > 0:
            # Estimate annualized return
            trade_days = (trades[-1].exit_time - trades[0].entry_time).days or 1
            annualized_return = (metrics.total_pnl / trade_days) * self.config.trading_days_per_year
            metrics.calmar_ratio = annualized_return / metrics.max_drawdown
        
        # Kelly Criterion
        metrics.kelly_criterion = self._compute_kelly_criterion(metrics.win_rate, metrics.avg_win, abs(metrics.avg_loss))
        metrics.optimal_size_multiplier = self._compute_optimal_size(metrics.kelly_criterion)
        
        # Timing
        hold_times = [t.hold_duration_minutes for t in trades]
        metrics.avg_hold_minutes = np.mean(hold_times) if hold_times else 0.0
        
        win_holds = [t.hold_duration_minutes for t in trades if t.is_win]
        loss_holds = [t.hold_duration_minutes for t in trades if not t.is_win]
        metrics.avg_win_hold_minutes = np.mean(win_holds) if win_holds else 0.0
        metrics.avg_loss_hold_minutes = np.mean(loss_holds) if loss_holds else 0.0
        
        # Slippage
        metrics.total_slippage = sum(t.slippage for t in trades)
        metrics.avg_slippage = metrics.total_slippage / metrics.total_trades
        
        # Breakdowns
        metrics.by_signal_type = self._breakdown_by_signal_type(trades)
        metrics.by_regime = self._breakdown_by_regime(trades)
        metrics.by_hour = self._breakdown_by_hour(trades)
        metrics.by_day_of_week = self._breakdown_by_day(trades)
        
        return metrics
    
    def _compute_sharpe_ratio(self, pnls: List[float]) -> float:
        """Compute Sharpe ratio."""
        if len(pnls) < 2:
            return 0.0
        
        returns = np.array(pnls)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.0
        
        # Daily risk-free rate
        daily_rf = self.config.risk_free_rate / self.config.trading_days_per_year
        
        # Sharpe ratio (annualized)
        sharpe = (mean_return - daily_rf) / std_return
        sharpe_annualized = sharpe * np.sqrt(self.config.trading_days_per_year)
        
        return sharpe_annualized
    
    def _compute_sortino_ratio(self, pnls: List[float]) -> float:
        """Compute Sortino ratio (only downside deviation)."""
        if len(pnls) < 2:
            return 0.0
        
        returns = np.array(pnls)
        mean_return = np.mean(returns)
        
        # Downside deviation (only negative returns)
        negative_returns = returns[returns < 0]
        if len(negative_returns) == 0:
            return float('inf')  # No losses
        
        downside_std = np.std(negative_returns)
        if downside_std == 0:
            return float('inf')
        
        # Daily risk-free rate
        daily_rf = self.config.risk_free_rate / self.config.trading_days_per_year
        
        # Sortino ratio (annualized)
        sortino = (mean_return - daily_rf) / downside_std
        sortino_annualized = sortino * np.sqrt(self.config.trading_days_per_year)
        
        return sortino_annualized
    
    def _compute_max_drawdown(self, pnls: List[float]) -> Tuple[float, float]:
        """Compute maximum drawdown."""
        if not pnls:
            return 0.0, 0.0
        
        cumulative = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative)
        drawdown = peak - cumulative
        
        max_dd = np.max(drawdown)
        
        # Max drawdown as percentage of peak
        peak_at_max_dd = peak[np.argmax(drawdown)]
        max_dd_pct = max_dd / peak_at_max_dd if peak_at_max_dd > 0 else 0.0
        
        return max_dd, max_dd_pct
    
    def _compute_kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Compute Kelly Criterion for optimal position sizing.
        
        Kelly% = (W * R - L) / R
        where W = win rate, L = loss rate, R = avg_win / avg_loss
        
        Returns:
            Optimal fraction of capital to risk
        """
        if avg_loss == 0 or win_rate == 0:
            return 0.0
        
        loss_rate = 1 - win_rate
        win_loss_ratio = avg_win / avg_loss
        
        kelly = (win_rate * win_loss_ratio - loss_rate) / win_loss_ratio
        
        # Kelly can be negative (don't trade) or very high
        return max(kelly, 0.0)
    
    def _compute_optimal_size(self, kelly: float) -> float:
        """
        Compute optimal position size multiplier.
        
        Uses fractional Kelly for safety.
        """
        # Apply Kelly fraction
        adjusted_kelly = kelly * self.config.kelly_fraction
        
        # Clamp to min/max
        return max(min(adjusted_kelly + 1.0, self.config.max_kelly_size), self.config.min_kelly_size)
    
    def _breakdown_by_signal_type(self, trades: List[TradeResult]) -> Dict[str, Dict]:
        """Breakdown metrics by signal type."""
        by_type: Dict[str, List[TradeResult]] = {}
        
        for trade in trades:
            if trade.signal_type not in by_type:
                by_type[trade.signal_type] = []
            by_type[trade.signal_type].append(trade)
        
        result = {}
        for signal_type, type_trades in by_type.items():
            wins = sum(1 for t in type_trades if t.is_win)
            pnls = [t.net_pnl for t in type_trades]
            
            result[signal_type] = {
                "count": len(type_trades),
                "wins": wins,
                "losses": len(type_trades) - wins,
                "win_rate": round(wins / len(type_trades), 4),
                "total_pnl": round(sum(pnls), 2),
                "avg_pnl": round(np.mean(pnls), 2),
                "sharpe": round(self._compute_sharpe_ratio(pnls), 2),
            }
        
        return result
    
    def _breakdown_by_regime(self, trades: List[TradeResult]) -> Dict[str, Dict]:
        """Breakdown metrics by market regime."""
        by_regime: Dict[str, List[TradeResult]] = {}
        
        for trade in trades:
            regime = trade.regime or "unknown"
            if regime not in by_regime:
                by_regime[regime] = []
            by_regime[regime].append(trade)
        
        result = {}
        for regime, regime_trades in by_regime.items():
            wins = sum(1 for t in regime_trades if t.is_win)
            pnls = [t.net_pnl for t in regime_trades]
            
            result[regime] = {
                "count": len(regime_trades),
                "wins": wins,
                "win_rate": round(wins / len(regime_trades), 4),
                "total_pnl": round(sum(pnls), 2),
                "avg_pnl": round(np.mean(pnls), 2),
            }
        
        return result
    
    def _breakdown_by_hour(self, trades: List[TradeResult]) -> Dict[int, Dict]:
        """Breakdown metrics by hour of day."""
        by_hour: Dict[int, List[TradeResult]] = {}
        
        for trade in trades:
            hour = trade.entry_time.hour
            if hour not in by_hour:
                by_hour[hour] = []
            by_hour[hour].append(trade)
        
        result = {}
        for hour, hour_trades in by_hour.items():
            wins = sum(1 for t in hour_trades if t.is_win)
            pnls = [t.net_pnl for t in hour_trades]
            
            result[hour] = {
                "count": len(hour_trades),
                "wins": wins,
                "win_rate": round(wins / len(hour_trades), 4),
                "total_pnl": round(sum(pnls), 2),
            }
        
        return result
    
    def _breakdown_by_day(self, trades: List[TradeResult]) -> Dict[int, Dict]:
        """Breakdown metrics by day of week."""
        by_day: Dict[int, List[TradeResult]] = {}
        
        for trade in trades:
            day = trade.entry_time.weekday()
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(trade)
        
        day_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
        
        result = {}
        for day, day_trades in by_day.items():
            wins = sum(1 for t in day_trades if t.is_win)
            pnls = [t.net_pnl for t in day_trades]
            
            result[day_names.get(day, str(day))] = {
                "count": len(day_trades),
                "wins": wins,
                "win_rate": round(wins / len(day_trades), 4),
                "total_pnl": round(sum(pnls), 2),
            }
        
        return result
    
    def get_equity_curve(self) -> List[float]:
        """Get cumulative equity curve."""
        return self._equity_curve.copy()
    
    def get_trade_count(self) -> int:
        """Get total number of trades."""
        return len(self._trades)
    
    def get_recent_trades(self, n: int = 10) -> List[TradeResult]:
        """Get N most recent trades."""
        return self._trades[-n:]
    
    def clear(self) -> None:
        """Clear all trades and reset."""
        self._trades.clear()
        self._equity_curve = [0.0]
        logger.info("RiskMetricsCalculator cleared")


