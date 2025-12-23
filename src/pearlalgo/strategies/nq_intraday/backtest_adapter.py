from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
import json

import pandas as pd
import numpy as np

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.utils.logger import logger


class ExitReason(Enum):
    """Reason for trade exit."""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    END_OF_DAY = "end_of_day"
    TRAILING_STOP = "trailing_stop"
    TIME_STOP = "time_stop"


@dataclass
class Trade:
    """Represents a simulated trade."""
    signal_id: str
    signal_type: str
    direction: str  # "long" or "short"
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    position_size: int
    confidence: float
    
    # Exit data (filled when trade closes)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[ExitReason] = None
    pnl: Optional[float] = None
    pnl_points: Optional[float] = None
    max_favorable_excursion: float = 0.0  # Maximum profit during trade
    max_adverse_excursion: float = 0.0  # Maximum drawdown during trade
    bars_held: int = 0
    
    def to_dict(self) -> Dict:
        """Convert trade to dictionary."""
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size": self.position_size,
            "confidence": self.confidence,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_reason": self.exit_reason.value if self.exit_reason else None,
            "pnl": self.pnl,
            "pnl_points": self.pnl_points,
            "max_favorable_excursion": self.max_favorable_excursion,
            "max_adverse_excursion": self.max_adverse_excursion,
            "bars_held": self.bars_held,
        }


@dataclass
class BacktestResult:
    """Summary of a backtest run with optional trade simulation."""

    total_bars: int
    total_signals: int
    avg_confidence: float
    avg_risk_reward: float
    signals: Optional[List[Dict]] = field(default=None)  # Optional: actual signals from backtest
    # Performance metrics (calculated from trade simulation)
    win_rate: Optional[float] = None
    total_pnl: Optional[float] = None
    signal_distribution: Optional[Dict[str, int]] = None
    # Extended metrics from trade simulation
    total_trades: Optional[int] = None
    winning_trades: Optional[int] = None
    losing_trades: Optional[int] = None
    profit_factor: Optional[float] = None
    max_drawdown: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    avg_hold_time_minutes: Optional[float] = None
    trades: Optional[List[Dict]] = field(default=None)  # Optional: trade journal


def _build_mtf(df_1m: pd.DataFrame, config: NQIntradayConfig) -> Dict[str, pd.DataFrame]:
    """Build simple 5m/15m OHLCV bars from a 1m dataframe.

    The scanner already knows how to interpret these dataframes; we just
    resample and forward-fill volume/ohlc sensibly for backtesting.
    """

    if df_1m.empty:
        return {"df_5m": df_1m, "df_15m": df_1m}

    # Assume index is a DateTimeIndex in UTC
    df_5m = (
        df_1m.resample("5min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    df_15m = (
        df_1m.resample("15min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    return {"df_5m": df_5m, "df_15m": df_15m}


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample an OHLCV dataframe by time rule.

    Expects columns: open/high/low/close and optionally volume.
    """
    if df.empty:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df must have a DateTimeIndex to resample")

    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"

    return df.resample(rule).agg(agg).dropna()


def run_signal_backtest_5m_decision(
    df_1m: pd.DataFrame,
    config: Optional[NQIntradayConfig] = None,
    return_signals: bool = False,
    decision_rule: str = "5min",
    context_rule_1: str = "1h",
    context_rule_2: str = "4h",
) -> BacktestResult:
    """Signal-only backtest using 5m decision bars and 1h/4h context.

    This matches a common discretionary workflow:
    - Trade decisions on 5m candles
    - Higher-timeframe bias via 1h/4h
    - Execution modeled as the decision bar close (simple; no fill simulation yet)

    Notes:
    - Internally we reuse the existing strategy stack, but feed it resampled bars.
    - We pass 1h/4h into the MTF analyzer slots (df_5m/df_15m); the analyzer is generic.
    """
    if config is None:
        config = NQIntradayConfig()

    if df_1m.empty:
        return BacktestResult(
            total_bars=0,
            total_signals=0,
            avg_confidence=0.0,
            avg_risk_reward=0.0,
            signals=[] if return_signals else None,
        )

    if not isinstance(df_1m.index, pd.DatetimeIndex):
        raise ValueError("df_1m must have a DateTimeIndex")

    df_1m = df_1m.sort_index()

    df_decision = _resample_ohlcv(df_1m, decision_rule)
    df_ctx1 = _resample_ohlcv(df_1m, context_rule_1)
    df_ctx2 = _resample_ohlcv(df_1m, context_rule_2)

    strategy = NQIntradayStrategy(config=config)

    signals: List[Dict] = []
    confidences: List[float] = []
    risk_rewards: List[float] = []

    # Fixed rolling window to avoid O(n^2) slicing.
    window_size = max(200, int(config.lookback_periods * 10))

    logger.disable("pearlalgo.strategies.nq_intraday")
    try:
        for idx in range(len(df_decision)):
            start_i = max(0, idx - window_size + 1)
            window = df_decision.iloc[start_i : idx + 1]
            latest = window.iloc[-1]
            latest_ts = window.index[-1]

            ctx1 = df_ctx1.loc[:latest_ts].tail(max(50, window_size // 12 + 10)) if not df_ctx1.empty else None
            ctx2 = df_ctx2.loc[:latest_ts].tail(max(50, window_size // 48 + 10)) if not df_ctx2.empty else None

            market_data = {
                "df": window,
                "df_5m": ctx1,
                "df_15m": ctx2,
                "is_backtest": True,
                "latest_bar": {
                    "timestamp": latest_ts.isoformat(),
                    "open": float(latest.get("open", latest["close"])),
                    "high": float(latest.get("high", latest["close"])),
                    "low": float(latest.get("low", latest["close"])),
                    "close": float(latest["close"]),
                    "volume": float(latest.get("volume", 0.0)),
                },
            }

            new_signals = strategy.analyze(market_data)
            for s in new_signals:
                s.setdefault("timestamp", latest_ts.isoformat())
                signals.append(s)
                confidences.append(float(s.get("confidence", 0.0)))
                entry = s.get("entry_price")
                stop = s.get("stop_loss")
                target = s.get("take_profit")
                if entry and stop and target:
                    if s.get("direction") == "long":
                        risk = entry - stop
                        reward = target - entry
                    else:
                        risk = stop - entry
                        reward = entry - target
                    if risk > 0:
                        risk_rewards.append(float(reward / risk))
    finally:
        logger.enable("pearlalgo.strategies.nq_intraday")

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    avg_rr = sum(risk_rewards) / len(risk_rewards) if risk_rewards else 0.0

    signal_distribution = {}
    if signals:
        for signal in signals:
            signal_type = signal.get("type", "unknown")
            signal_distribution[signal_type] = signal_distribution.get(signal_type, 0) + 1

    return BacktestResult(
        total_bars=len(df_decision),
        total_signals=len(signals),
        avg_confidence=avg_conf,
        avg_risk_reward=avg_rr,
        signals=signals if return_signals else None,
        signal_distribution=signal_distribution if signal_distribution else None,
    )


def run_signal_backtest(
    df_1m: pd.DataFrame, 
    config: Optional[NQIntradayConfig] = None,
    return_signals: bool = False
) -> BacktestResult:
    """Run the MNQ intraday strategy in signal-only mode on a 1m dataframe.

    This reuses the live `NQIntradayStrategy` and `NQSignalGenerator` to
    generate signals bar-by-bar. It does **not** place trades or simulate
    fills; the goal is to understand signal frequency and quality offline.
    
    Args:
        df_1m: 1-minute OHLCV DataFrame
        config: Strategy configuration (optional)
        return_signals: If True, include actual signals in result
        
    Returns:
        BacktestResult with summary and optionally signals
    """

    if config is None:
        config = NQIntradayConfig()

    if not df_1m.empty:
        df_1m = df_1m.sort_index()

    strategy = NQIntradayStrategy(config=config)
    mtf = _build_mtf(df_1m, config)
    df_5m_all = mtf.get("df_5m")
    df_15m_all = mtf.get("df_15m")

    signals: List[Dict] = []
    confidences: List[float] = []
    risk_rewards: List[float] = []

    if df_1m.empty:
        return BacktestResult(
            total_bars=0, 
            total_signals=0, 
            avg_confidence=0.0, 
            avg_risk_reward=0.0,
            signals=[] if return_signals else None
        )

    # Iterate bar-by-bar using a FIXED rolling window (avoid O(n^2) slicing).
    # Strategy indicators only need a small lookback; keep a safety buffer.
    window_size = max(200, int(config.lookback_periods * 10))

    # Backtests are extremely chatty at INFO; silence intraday strategy logs during the loop.
    logger.disable("pearlalgo.strategies.nq_intraday")
    try:
        for idx in range(len(df_1m)):
            start_i = max(0, idx - window_size + 1)
            window = df_1m.iloc[start_i : idx + 1]
            latest = window.iloc[-1]
            latest_ts = window.index[-1]

            df_5m = None
            if df_5m_all is not None and not df_5m_all.empty:
                df_5m = df_5m_all.loc[:latest_ts].tail(max(50, window_size // 5 + 10))
            df_15m = None
            if df_15m_all is not None and not df_15m_all.empty:
                df_15m = df_15m_all.loc[:latest_ts].tail(max(50, window_size // 15 + 10))

            market_data = {
                "df": window,
                "df_5m": df_5m,
                "df_15m": df_15m,
                "is_backtest": True,
                "latest_bar": {
                    "timestamp": latest_ts.isoformat(),
                    "open": float(latest.get("open", latest["close"])),
                    "high": float(latest.get("high", latest["close"])),
                    "low": float(latest.get("low", latest["close"])),
                    "close": float(latest["close"]),
                    "volume": float(latest.get("volume", 0.0)),
                },
            }

            new_signals = strategy.analyze(market_data)
            for s in new_signals:
                # Ensure timestamp is always present for downstream charting/backtest reporting
                s.setdefault("timestamp", latest_ts.isoformat())
                signals.append(s)
                confidences.append(float(s.get("confidence", 0.0)))
                # Risk/reward if present
                entry = s.get("entry_price")
                stop = s.get("stop_loss")
                target = s.get("take_profit")
                if entry and stop and target:
                    if s.get("direction") == "long":
                        risk = entry - stop
                        reward = target - entry
                    else:
                        risk = stop - entry
                        reward = entry - target
                    if risk > 0:
                        risk_rewards.append(float(reward / risk))
    finally:
        logger.enable("pearlalgo.strategies.nq_intraday")

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    avg_rr = sum(risk_rewards) / len(risk_rewards) if risk_rewards else 0.0
    
    # Calculate signal distribution by type
    signal_distribution = {}
    if signals:
        for signal in signals:
            signal_type = signal.get("type", "unknown")
            signal_distribution[signal_type] = signal_distribution.get(signal_type, 0) + 1
    
    # Note: win_rate and total_pnl would require trade simulation
    # For signal-only backtest, these remain None
    
    return BacktestResult(
        total_bars=len(df_1m),
        total_signals=len(signals),
        avg_confidence=avg_conf,
        avg_risk_reward=avg_rr,
        signals=signals if return_signals else None,
        signal_distribution=signal_distribution if signal_distribution else None,
    )


class TradeSimulator:
    """
    Simulates trade execution from signals on historical data.
    
    Features:
    - Entry at signal price (or next bar open)
    - Stop loss and take profit tracking
    - End-of-day position close
    - P&L calculation with slippage
    - Trade journal with full details
    """

    def __init__(
        self,
        tick_value: float = 2.0,  # MNQ: $2 per point
        slippage_ticks: float = 0.5,  # Slippage in ticks
        commission_per_trade: float = 0.0,  # Commission per contract
        max_concurrent_trades: int = 1,
        eod_close_time: time = time(15, 45),  # Close positions before 4pm ET
    ):
        """
        Initialize trade simulator.
        
        Args:
            tick_value: Dollar value per point (MNQ = $2)
            slippage_ticks: Slippage in ticks (0.25 per tick for NQ)
            commission_per_trade: Commission per contract
            max_concurrent_trades: Maximum concurrent positions
            eod_close_time: Time to close positions (ET)
        """
        self.tick_value = tick_value
        self.slippage_ticks = slippage_ticks
        self.slippage_points = slippage_ticks * 0.25  # NQ tick = 0.25 points
        self.commission_per_trade = commission_per_trade
        self.max_concurrent_trades = max_concurrent_trades
        self.eod_close_time = eod_close_time
        
        self.open_trades: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.equity_curve: List[float] = []
        self.peak_equity: float = 0.0

    def simulate(
        self,
        df: pd.DataFrame,
        signals: List[Dict],
        position_size: int = 1,
    ) -> Tuple[List[Trade], Dict]:
        """
        Simulate trades from signals on price data.
        
        Args:
            df: OHLCV DataFrame with DateTimeIndex
            signals: List of signal dictionaries
            position_size: Number of contracts per trade
            
        Returns:
            Tuple of (closed_trades, metrics_dict)
        """
        self.open_trades = []
        self.closed_trades = []
        self.equity_curve = [0.0]
        self.peak_equity = 0.0
        
        # Convert signals to dict keyed by timestamp for efficient lookup
        signals_by_time = {}
        for i, signal in enumerate(signals):
            ts = signal.get("timestamp")
            if ts:
                if isinstance(ts, str):
                    ts = pd.Timestamp(ts)
                signals_by_time.setdefault(ts, []).append((i, signal))
        
        current_equity = 0.0
        max_drawdown = 0.0
        
        for idx in range(len(df)):
            bar = df.iloc[idx]
            bar_time = df.index[idx]
            
            # Update open trades with this bar
            self._update_open_trades(bar, bar_time)
            
            # Check for end of day close
            self._check_eod_close(bar, bar_time)
            
            # Look for new signals at this bar
            if bar_time in signals_by_time:
                for signal_idx, signal in signals_by_time[bar_time]:
                    if len(self.open_trades) < self.max_concurrent_trades:
                        self._open_trade(signal, bar, bar_time, position_size, signal_idx)
            
            # Update equity curve
            unrealized_pnl = sum(
                self._calculate_unrealized_pnl(trade, bar["close"])
                for trade in self.open_trades
            )
            realized_pnl = sum(trade.pnl or 0 for trade in self.closed_trades)
            current_equity = realized_pnl + unrealized_pnl
            self.equity_curve.append(current_equity)
            
            # Track drawdown
            self.peak_equity = max(self.peak_equity, current_equity)
            drawdown = self.peak_equity - current_equity
            max_drawdown = max(max_drawdown, drawdown)
        
        # Close any remaining open trades at last bar
        if self.open_trades:
            last_bar = df.iloc[-1]
            last_time = df.index[-1]
            for trade in list(self.open_trades):
                self._close_trade(trade, last_bar["close"], last_time, ExitReason.END_OF_DAY)
        
        # Calculate metrics
        metrics = self._calculate_metrics(max_drawdown)
        
        return self.closed_trades, metrics

    def _open_trade(
        self,
        signal: Dict,
        bar: pd.Series,
        bar_time: datetime,
        position_size: int,
        signal_idx: int,
    ) -> None:
        """Open a new trade from a signal."""
        direction = signal.get("direction", "long")
        entry_price = signal.get("entry_price", bar["close"])
        
        # Apply slippage (worse price for entry)
        if direction == "long":
            entry_price += self.slippage_points
        else:
            entry_price -= self.slippage_points
        
        trade = Trade(
            signal_id=f"sig_{signal_idx}_{bar_time.strftime('%Y%m%d_%H%M')}",
            signal_type=signal.get("type", "unknown"),
            direction=direction,
            entry_price=entry_price,
            entry_time=bar_time,
            stop_loss=signal.get("stop_loss", 0),
            take_profit=signal.get("take_profit", 0),
            position_size=position_size,
            confidence=signal.get("confidence", 0),
        )
        
        self.open_trades.append(trade)
        logger.debug(f"Opened {direction} trade at {entry_price:.2f} ({trade.signal_type})")

    def _update_open_trades(self, bar: pd.Series, bar_time: datetime) -> None:
        """Update open trades with current bar - check for stops and targets."""
        for trade in list(self.open_trades):
            trade.bars_held += 1
            
            # Track excursions
            if trade.direction == "long":
                favorable = bar["high"] - trade.entry_price
                adverse = trade.entry_price - bar["low"]
            else:
                favorable = trade.entry_price - bar["low"]
                adverse = bar["high"] - trade.entry_price
            
            trade.max_favorable_excursion = max(trade.max_favorable_excursion, favorable)
            trade.max_adverse_excursion = max(trade.max_adverse_excursion, adverse)
            
            # Check stop loss
            if trade.stop_loss > 0:
                if trade.direction == "long" and bar["low"] <= trade.stop_loss:
                    self._close_trade(trade, trade.stop_loss, bar_time, ExitReason.STOP_LOSS)
                    continue
                elif trade.direction == "short" and bar["high"] >= trade.stop_loss:
                    self._close_trade(trade, trade.stop_loss, bar_time, ExitReason.STOP_LOSS)
                    continue
            
            # Check take profit
            if trade.take_profit > 0:
                if trade.direction == "long" and bar["high"] >= trade.take_profit:
                    self._close_trade(trade, trade.take_profit, bar_time, ExitReason.TAKE_PROFIT)
                    continue
                elif trade.direction == "short" and bar["low"] <= trade.take_profit:
                    self._close_trade(trade, trade.take_profit, bar_time, ExitReason.TAKE_PROFIT)
                    continue

    def _check_eod_close(self, bar: pd.Series, bar_time: datetime) -> None:
        """Close positions at end of day."""
        # Extract time component
        if hasattr(bar_time, 'time'):
            current_time = bar_time.time()
        else:
            current_time = bar_time
            
        if current_time >= self.eod_close_time:
            for trade in list(self.open_trades):
                self._close_trade(trade, bar["close"], bar_time, ExitReason.END_OF_DAY)

    def _close_trade(
        self,
        trade: Trade,
        exit_price: float,
        exit_time: datetime,
        exit_reason: ExitReason,
    ) -> None:
        """Close a trade and calculate P&L."""
        # Apply slippage (worse price for exit)
        if trade.direction == "long":
            exit_price -= self.slippage_points
        else:
            exit_price += self.slippage_points
        
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = exit_reason
        
        # Calculate P&L
        if trade.direction == "long":
            trade.pnl_points = exit_price - trade.entry_price
        else:
            trade.pnl_points = trade.entry_price - exit_price
        
        trade.pnl = (trade.pnl_points * self.tick_value * trade.position_size) - self.commission_per_trade
        
        # Move from open to closed
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        
        logger.debug(
            f"Closed {trade.direction} trade at {exit_price:.2f} "
            f"({exit_reason.value}): P&L = ${trade.pnl:.2f}"
        )

    def _calculate_unrealized_pnl(self, trade: Trade, current_price: float) -> float:
        """Calculate unrealized P&L for an open trade."""
        if trade.direction == "long":
            pnl_points = current_price - trade.entry_price
        else:
            pnl_points = trade.entry_price - current_price
        return pnl_points * self.tick_value * trade.position_size

    def _calculate_metrics(self, max_drawdown: float) -> Dict:
        """Calculate performance metrics from closed trades."""
        if not self.closed_trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_hold_time_minutes": 0.0,
            }
        
        # Categorize trades
        winners = [t for t in self.closed_trades if (t.pnl or 0) > 0]
        losers = [t for t in self.closed_trades if (t.pnl or 0) <= 0]
        
        total_trades = len(self.closed_trades)
        winning_trades = len(winners)
        losing_trades = len(losers)
        
        # Win rate
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        # Total P&L
        total_pnl = sum(t.pnl or 0 for t in self.closed_trades)
        
        # Gross profit/loss
        gross_profit = sum(t.pnl or 0 for t in winners)
        gross_loss = abs(sum(t.pnl or 0 for t in losers))
        
        # Profit factor
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0
        
        # Average win/loss
        avg_win = gross_profit / winning_trades if winning_trades > 0 else 0.0
        avg_loss = gross_loss / losing_trades if losing_trades > 0 else 0.0
        
        # Max drawdown percentage
        max_equity = max(self.equity_curve) if self.equity_curve else 0
        max_drawdown_pct = (max_drawdown / max_equity * 100) if max_equity > 0 else 0.0
        
        # Sharpe ratio (simplified - daily returns)
        returns = np.diff(self.equity_curve)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe_ratio = (np.mean(returns) / np.std(returns)) * np.sqrt(252)  # Annualized
        else:
            sharpe_ratio = 0.0
        
        # Average hold time
        hold_times = []
        for t in self.closed_trades:
            if t.entry_time and t.exit_time:
                hold_time = (t.exit_time - t.entry_time).total_seconds() / 60
                hold_times.append(hold_time)
        avg_hold_time = sum(hold_times) / len(hold_times) if hold_times else 0.0
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "sharpe_ratio": sharpe_ratio,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_hold_time_minutes": avg_hold_time,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
        }


def run_full_backtest(
    df_1m: pd.DataFrame,
    config: Optional[NQIntradayConfig] = None,
    position_size: int = 1,
    tick_value: float = 2.0,
    slippage_ticks: float = 0.5,
    return_trades: bool = True,
) -> BacktestResult:
    """
    Run full trade simulation backtest with P&L tracking.
    
    This combines signal generation with trade simulation to provide
    realistic performance metrics including win rate, P&L, and drawdown.
    
    Args:
        df_1m: 1-minute OHLCV DataFrame with DateTimeIndex
        config: Strategy configuration
        position_size: Number of contracts per trade
        tick_value: Dollar value per point (MNQ = $2)
        slippage_ticks: Slippage in ticks
        return_trades: If True, include trade journal in result
        
    Returns:
        BacktestResult with full metrics and optional trade journal
    """
    # First, run signal-only backtest to get signals
    signal_result = run_signal_backtest(df_1m, config=config, return_signals=True)
    
    if not signal_result.signals:
        return BacktestResult(
            total_bars=signal_result.total_bars,
            total_signals=0,
            avg_confidence=0.0,
            avg_risk_reward=0.0,
            signals=None,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
        )
    
    # Run trade simulation
    simulator = TradeSimulator(
        tick_value=tick_value,
        slippage_ticks=slippage_ticks,
    )
    
    closed_trades, metrics = simulator.simulate(
        df_1m,
        signal_result.signals,
        position_size=position_size,
    )
    
    # Convert trades to dict for JSON serialization
    trades_list = [t.to_dict() for t in closed_trades] if return_trades else None
    
    return BacktestResult(
        total_bars=signal_result.total_bars,
        total_signals=signal_result.total_signals,
        avg_confidence=signal_result.avg_confidence,
        avg_risk_reward=signal_result.avg_risk_reward,
        signals=signal_result.signals if return_trades else None,
        signal_distribution=signal_result.signal_distribution,
        total_trades=metrics["total_trades"],
        winning_trades=metrics["winning_trades"],
        losing_trades=metrics["losing_trades"],
        win_rate=metrics["win_rate"],
        total_pnl=metrics["total_pnl"],
        profit_factor=metrics["profit_factor"],
        max_drawdown=metrics["max_drawdown"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        sharpe_ratio=metrics["sharpe_ratio"],
        avg_win=metrics["avg_win"],
        avg_loss=metrics["avg_loss"],
        avg_hold_time_minutes=metrics["avg_hold_time_minutes"],
        trades=trades_list,
    )


def run_full_backtest_5m_decision(
    df_1m: pd.DataFrame,
    config: Optional[NQIntradayConfig] = None,
    position_size: int = 1,
    tick_value: float = 2.0,
    slippage_ticks: float = 0.5,
    return_trades: bool = True,
    decision_rule: str = "5min",
    context_rule_1: str = "1h",
    context_rule_2: str = "4h",
) -> BacktestResult:
    """Full trade-simulation backtest using 5m decision bars and 1h/4h context."""
    if config is None:
        config = NQIntradayConfig()

    # Generate signals on decision bars
    signal_result = run_signal_backtest_5m_decision(
        df_1m,
        config=config,
        return_signals=True,
        decision_rule=decision_rule,
        context_rule_1=context_rule_1,
        context_rule_2=context_rule_2,
    )

    # Use decision bars for execution simulation (deterministic + faster)
    df_decision = _resample_ohlcv(df_1m.sort_index(), decision_rule)

    if not signal_result.signals or df_decision.empty:
        return BacktestResult(
            total_bars=signal_result.total_bars,
            total_signals=0,
            avg_confidence=0.0,
            avg_risk_reward=0.0,
            signals=None,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
        )

    simulator = TradeSimulator(
        tick_value=tick_value,
        slippage_ticks=slippage_ticks,
    )

    closed_trades, metrics = simulator.simulate(
        df_decision,
        signal_result.signals,
        position_size=position_size,
    )

    trades_list = [t.to_dict() for t in closed_trades] if return_trades else None

    return BacktestResult(
        total_bars=signal_result.total_bars,
        total_signals=signal_result.total_signals,
        avg_confidence=signal_result.avg_confidence,
        avg_risk_reward=signal_result.avg_risk_reward,
        signals=signal_result.signals if return_trades else None,
        signal_distribution=signal_result.signal_distribution,
        total_trades=metrics["total_trades"],
        winning_trades=metrics["winning_trades"],
        losing_trades=metrics["losing_trades"],
        win_rate=metrics["win_rate"],
        total_pnl=metrics["total_pnl"],
        profit_factor=metrics["profit_factor"],
        max_drawdown=metrics["max_drawdown"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        sharpe_ratio=metrics["sharpe_ratio"],
        avg_win=metrics["avg_win"],
        avg_loss=metrics["avg_loss"],
        avg_hold_time_minutes=metrics["avg_hold_time_minutes"],
        trades=trades_list,
    )


def export_trade_journal(
    trades: List[Dict],
    filepath: str,
    format: str = "csv",
) -> None:
    """
    Export trade journal to file.
    
    Args:
        trades: List of trade dictionaries
        filepath: Output file path
        format: "csv" or "json"
    """
    if not trades:
        logger.warning("No trades to export")
        return
    
    if format == "csv":
        df = pd.DataFrame(trades)
        df.to_csv(filepath, index=False)
        logger.info(f"Exported {len(trades)} trades to {filepath}")
    elif format == "json":
        with open(filepath, "w") as f:
            json.dump(trades, f, indent=2)
        logger.info(f"Exported {len(trades)} trades to {filepath}")
    else:
        raise ValueError(f"Unknown format: {format}")
