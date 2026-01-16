"""
PEARL Bot Backtesting Adapter

Integrates PEARL bots with the existing backtesting infrastructure,
providing comprehensive backtesting capabilities for automated trading bots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from pearlalgo.strategies.nq_intraday.backtest_adapter import (
    TradeSimulator,
    VerificationSummary,
    _compute_verification_summary,
)
from pearlalgo.strategies.pearl_bots.bot_template import PearlBot, TradeSignal
from pearlalgo.utils.logger import logger, log_silence


@dataclass
class PearlBotBacktestResult:
    """Results from a pearl bot backtest."""
    
    bot_name: str
    total_bars: int
    total_signals: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    
    # Performance metrics
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    avg_win: float
    avg_loss: float
    avg_hold_time_minutes: float
    
    # Signal metrics
    avg_confidence: float
    avg_risk_reward: float
    
    # Trade journal
    trades: Optional[List[Dict]] = None
    signals: Optional[List[Dict]] = None
    skipped_signals: Optional[List[Dict]] = None
    
    # Verification diagnostics
    verification: Optional[VerificationSummary] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON export."""
        return {
            "bot_name": self.bot_name,
            "total_bars": self.total_bars,
            "total_signals": self.total_signals,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_pnl": self.total_pnl,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "avg_hold_time_minutes": self.avg_hold_time_minutes,
            "avg_confidence": self.avg_confidence,
            "avg_risk_reward": self.avg_risk_reward,
        }


def _normalize_resample_rule(timeframe: str) -> str:
    """Convert '5m'/'1m' style timeframe into pandas resample rule."""
    tf = (timeframe or "").strip().lower()
    if tf in {"1m", "1min", "1minute"}:
        return "1min"
    if tf in {"5m", "5min", "5minute"}:
        return "5min"
    if tf.endswith("m") and tf[:-1].isdigit():
        return f"{int(tf[:-1])}min"
    # Fallback: assume caller passed a valid pandas rule
    return timeframe


def _resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample OHLCV data to desired timeframe."""
    if df.empty:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df must have a DateTimeIndex")

    rule = _normalize_resample_rule(timeframe)
    if rule in {"1min"}:
        return df

    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    return df.resample(rule).agg(agg).dropna()


class PearlBotBacktestAdapter:
    """
    Backtesting adapter for PEARL bots.
    
    Integrates pearl bots with the existing TradeSimulator infrastructure
    to provide comprehensive backtesting capabilities.
    """
    
    def __init__(
        self,
        bot: PearlBot,
        tick_value: float = 2.0,  # MNQ: $2 per point
        slippage_ticks: float = 0.5,
        max_concurrent_trades: int = 1,
        account_balance: Optional[float] = None,
        max_risk_per_trade: float = 0.01,
        max_contracts: int = 10,
        max_stop_points: Optional[float] = None,
    ):
        """
        Initialize backtest adapter.
        
        Args:
            bot: PearlBot instance to backtest
            tick_value: Dollar value per point
            slippage_ticks: Slippage in ticks
            max_concurrent_trades: Maximum concurrent positions
            account_balance: Account balance for risk-based sizing
            max_risk_per_trade: Max risk per trade as fraction
            max_contracts: Maximum contracts per trade
            max_stop_points: Maximum allowed stop distance in points
        """
        self.bot = bot
        self.tick_value = tick_value
        self.slippage_ticks = slippage_ticks
        self.max_concurrent_trades = max_concurrent_trades
        self.account_balance = account_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.max_contracts = max_contracts
        self.max_stop_points = max_stop_points
        
        # Reset bot performance for clean backtest
        self.bot.reset_performance()
    
    def run_backtest(
        self,
        df: pd.DataFrame,
        timeframe: str = "5m",
        return_signals: bool = True,
        return_trades: bool = True,
    ) -> PearlBotBacktestResult:
        """
        Run backtest on historical data.
        
        Args:
            df: OHLCV DataFrame with DateTimeIndex
            timeframe: Timeframe string (e.g., "5m", "1m")
            return_signals: Include signals in result
            return_trades: Include trades in result
            
        Returns:
            PearlBotBacktestResult with comprehensive metrics
        """
        if df.empty:
            return PearlBotBacktestResult(
                bot_name=self.bot.name,
                total_bars=0,
                total_signals=0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                profit_factor=0.0,
                max_drawdown=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                avg_hold_time_minutes=0.0,
                avg_confidence=0.0,
                avg_risk_reward=0.0,
            )
        
        # Ensure sorted and resample (historical datasets are 1m; bots default to 5m logic)
        df = df.sort_index()
        df_tf = _resample_ohlcv(df, timeframe=timeframe)

        if df_tf.empty:
            return PearlBotBacktestResult(
                bot_name=self.bot.name,
                total_bars=0,
                total_signals=0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                profit_factor=0.0,
                max_drawdown=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                avg_hold_time_minutes=0.0,
                avg_confidence=0.0,
                avg_risk_reward=0.0,
            )

        # Precompute indicators ONCE for speed.
        #
        # Some indicator suites return a full computed dataframe under key "df"
        # (e.g., mean reversion / breakout). Others intentionally do NOT return
        # the full dataframe for memory reasons (e.g., cached trend follower).
        # For backtests, we need the full indicator series; so we fall back to
        # a suite-provided internal method if available.
        indicator_suite = self.bot.get_indicator_suite()
        df_ind: pd.DataFrame
        try:
            suite_out = indicator_suite.calculate_signals(df_tf)
            df_candidate = suite_out.get("df") if isinstance(suite_out, dict) else None
            if isinstance(df_candidate, pd.DataFrame) and not df_candidate.empty:
                df_ind = df_candidate
            else:
                raise ValueError("indicator suite did not return df")
        except Exception:
            calc_full = getattr(indicator_suite, "_calculate_base_indicators", None)
            if callable(calc_full):
                try:
                    df_ind = calc_full(df_tf)
                except Exception:
                    df_ind = df_tf.copy()
            else:
                df_ind = df_tf.copy()

        # Generate signals bar-by-bar without recomputing rolling indicators.
        signals: List[TradeSignal] = []
        signal_dicts: List[Dict] = []
        confidences: List[float] = []
        risk_rewards: List[float] = []

        warmup_bars = 200

        with log_silence():
            for idx in range(warmup_bars, len(df_tf)):
                window = df_tf.iloc[: idx + 1]
                row = df_ind.iloc[idx]
                ts = df_tf.index[idx]

                st = (getattr(self.bot, "strategy_type", "") or "").lower()
                indicators: Dict[str, Any]

                if st == "trend_following":
                    indicators = {
                        "trend_direction": float(row.get("trend_direction", 0.0)),
                        "trend_strength": float(row.get("trend_strength", 0.0)),
                        "pullback_pct": float(row.get("pullback_pct", 0.0)),
                        "momentum": float(row.get("momentum", 0.0)),
                        "volatility": float(row.get("volatility", 0.0)),
                        "current_price": float(row.get("close", 0.0)),
                    }
                elif st == "breakout":
                    vol_ratio = float(row.get("volatility_ratio", 1.0))
                    volume_ratio = float(row.get("volume_ratio", 0.0))
                    vol_mult = float(getattr(indicator_suite, "breakout_volume_mult", 1.5))
                    range_size = float(row.get("range_size", 0.0))
                    range_mid = float(row.get("range_midpoint", 0.0))
                    range_size_pct = (range_size / range_mid) if range_mid else 0.0
                    indicators = {
                        "in_consolidation": bool(vol_ratio < 0.7),
                        "upper_breakout": bool(row.get("upper_breakout", False)),
                        "lower_breakout": bool(row.get("lower_breakout", False)),
                        "volume_confirmed": bool(volume_ratio > vol_mult),
                        "momentum": float(row.get("momentum", 0.0)),
                        "momentum_acceleration": float(row.get("momentum_acceleration", 0.0)),
                        "pattern_strength": float(row.get("pattern_strength", 0.0)),
                        "range_size_pct": float(range_size_pct),
                        "current_price": float(row.get("close", 0.0)),
                        "range_high": float(row.get("high_max", 0.0)),
                        "range_low": float(row.get("low_min", 0.0)),
                    }
                elif st == "mean_reversion":
                    indicators = {
                        "oversold_signal": bool(row.get("oversold_signal", False)),
                        "overbought_signal": bool(row.get("overbought_signal", False)),
                        "bullish_divergence": bool(row.get("bullish_divergence", False)),
                        "bearish_divergence": bool(row.get("bearish_divergence", False)),
                        "mr_strength": float(row.get("mr_strength", 0.0)),
                        "current_price": float(row.get("close", 0.0)),
                        "bb_middle": float(row.get("bb_middle", 0.0)),
                        "bb_upper": float(row.get("bb_upper", 0.0)),
                        "bb_lower": float(row.get("bb_lower", 0.0)),
                        "rsi": float(row.get("rsi", 50.0)),
                        "stoch_k": float(row.get("stoch_k", 50.0)),
                        "cci": float(row.get("cci", 0.0)),
                        "bb_position": float(row.get("bb_position", 0.5)),
                    }
                else:
                    # Unknown bot type: skip (backtest adapter expects known PEARL bots)
                    continue

                signal = self.bot.generate_signal_logic(window, indicators)
                if signal is None:
                    continue

                # Ensure timestamps match the dataframe index for TradeSimulator equality checks.
                try:
                    signal.timestamp = ts
                except Exception:
                    pass

                signal = self.bot._apply_risk_management(signal, window)

                # Basic validation (avoid max_positions blocking during backtests).
                if signal.confidence < float(self.bot.config.min_confidence):
                    continue
                if float(getattr(signal, "risk_reward_ratio", 0.0) or 0.0) < 1.0:
                    continue

                signals.append(signal)
                sd = signal.to_dict()
                sd["timestamp"] = ts.isoformat()
                signal_dicts.append(sd)
                confidences.append(float(signal.confidence))
                rr = float(getattr(signal, "risk_reward_ratio", 0.0) or 0.0)
                if rr > 0:
                    risk_rewards.append(rr)

        # Convert signals to format expected by TradeSimulator
        simulator_signals: List[Dict] = []
        for signal in signals:
            simulator_signals.append({
                "timestamp": signal.timestamp.isoformat(),
                "type": signal.bot_name,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "signal_id": signal.signal_id,
            })
        
        # Run trade simulation
        simulator = TradeSimulator(
            tick_value=self.tick_value,
            slippage_ticks=self.slippage_ticks,
            max_concurrent_trades=self.max_concurrent_trades,
            account_balance=self.account_balance,
            max_risk_per_trade=self.max_risk_per_trade,
            max_contracts=self.max_contracts,
            max_stop_points=self.max_stop_points,
        )
        
        with log_silence():
            closed_trades, metrics = simulator.simulate(df_tf, simulator_signals, position_size=1)
        
        # Calculate averages
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        avg_rr = sum(risk_rewards) / len(risk_rewards) if risk_rewards else 0.0
        
        # Convert trades to dict format
        trades_list = [t.to_dict() for t in closed_trades] if return_trades else None
        skipped_list = [s.to_dict() for s in simulator.skipped_signals] if return_trades else None
        
        # Compute verification summary
        bottleneck_counts: Dict[str, int] = {}
        verification = _compute_verification_summary(
            signals=signal_dicts,
            df=df_tf,
            bottleneck_counts=bottleneck_counts,
            gate_reasons=[],
        )
        
        # Calculate max drawdown percentage
        max_equity = max(simulator.equity_curve) if simulator.equity_curve else 0
        max_dd_pct = (metrics["max_drawdown"] / max_equity * 100) if max_equity > 0 else 0.0
        
        return PearlBotBacktestResult(
            bot_name=self.bot.name,
            total_bars=len(df_tf),
            total_signals=len(signals),
            total_trades=metrics["total_trades"],
            winning_trades=metrics["winning_trades"],
            losing_trades=metrics["losing_trades"],
            win_rate=metrics["win_rate"],
            total_pnl=metrics["total_pnl"],
            profit_factor=metrics["profit_factor"],
            max_drawdown=metrics["max_drawdown"],
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=metrics["sharpe_ratio"],
            sortino_ratio=0.0,  # Not calculated by TradeSimulator
            avg_win=metrics["avg_win"],
            avg_loss=metrics["avg_loss"],
            avg_hold_time_minutes=metrics["avg_hold_time_minutes"],
            avg_confidence=avg_conf,
            avg_risk_reward=avg_rr,
            trades=trades_list,
            signals=signal_dicts if return_signals else None,
            skipped_signals=skipped_list,
            verification=verification,
        )


def backtest_pearl_bot(
    bot: PearlBot,
    df: pd.DataFrame,
    tick_value: float = 2.0,
    slippage_ticks: float = 0.5,
    max_concurrent_trades: int = 1,
    account_balance: Optional[float] = None,
    max_risk_per_trade: float = 0.01,
    max_contracts: int = 10,
    max_stop_points: Optional[float] = None,
    return_signals: bool = True,
    return_trades: bool = True,
) -> PearlBotBacktestResult:
    """
    Convenience function to backtest a pearl bot.
    
    Args:
        bot: PearlBot instance
        df: OHLCV DataFrame
        tick_value: Dollar value per point
        slippage_ticks: Slippage in ticks
        max_concurrent_trades: Max concurrent positions
        account_balance: Account balance for risk sizing
        max_risk_per_trade: Max risk per trade fraction
        max_contracts: Max contracts per trade
        max_stop_points: Max stop distance cap
        return_signals: Include signals in result
        return_trades: Include trades in result
        
    Returns:
        PearlBotBacktestResult
    """
    adapter = PearlBotBacktestAdapter(
        bot=bot,
        tick_value=tick_value,
        slippage_ticks=slippage_ticks,
        max_concurrent_trades=max_concurrent_trades,
        account_balance=account_balance,
        max_risk_per_trade=max_risk_per_trade,
        max_contracts=max_contracts,
        max_stop_points=max_stop_points,
    )
    
    return adapter.run_backtest(
        df=df,
        return_signals=return_signals,
        return_trades=return_trades,
    )
