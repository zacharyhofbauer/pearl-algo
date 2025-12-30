from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
import json

import pandas as pd
import numpy as np

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

try:
    _ET_TZ = ZoneInfo("America/New_York") if ZoneInfo is not None else None
except Exception:  # pragma: no cover
    _ET_TZ = None

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
    
    # Regime context (for trade-type-by-regime analysis)
    regime: Optional[str] = None  # e.g., "trending_bullish", "ranging"
    volatility: Optional[str] = None  # e.g., "low", "normal", "high"
    session: Optional[str] = None  # e.g., "opening", "morning_trend"
    
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
            "regime": self.regime,
            "volatility": self.volatility,
            "session": self.session,
        }


@dataclass
class VerificationSummary:
    """Backtest verification diagnostics for strategy health assessment.
    
    Answers the key questions:
    - Does the strategy generate signals at all?
    - Under what conditions do signals appear?
    - What are the bottlenecks preventing signals?
    """
    
    # Signal presence & density
    signals_per_day: float = 0.0
    signals_per_hour: float = 0.0
    trading_days: int = 0
    trading_hours: int = 0
    
    # Signal distribution by type
    signal_type_distribution: Dict[str, int] = field(default_factory=dict)
    
    # Regime activation (where signals occur)
    regime_distribution: Dict[str, int] = field(default_factory=dict)  # trending_bullish, etc.
    volatility_distribution: Dict[str, int] = field(default_factory=dict)  # low, normal, high
    session_distribution: Dict[str, int] = field(default_factory=dict)  # opening, morning_trend, etc.
    
    # Condition bottlenecks (why signals were rejected or not generated)
    bottleneck_summary: Dict[str, int] = field(default_factory=dict)  # e.g., {"low_volume": 42, ...}
    top_gate_reasons: List[str] = field(default_factory=list)  # Most common scanner gate reasons

    # Execution / trade simulation explainability (why trades < signals)
    # Populated only in full backtests that run TradeSimulator.
    execution_summary: Dict[str, int] = field(default_factory=dict)
    
    # Data coverage
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON export."""
        return {
            "signals_per_day": self.signals_per_day,
            "signals_per_hour": self.signals_per_hour,
            "trading_days": self.trading_days,
            "trading_hours": self.trading_hours,
            "signal_type_distribution": self.signal_type_distribution,
            "regime_distribution": self.regime_distribution,
            "volatility_distribution": self.volatility_distribution,
            "session_distribution": self.session_distribution,
            "bottleneck_summary": self.bottleneck_summary,
            "top_gate_reasons": self.top_gate_reasons,
            "execution_summary": self.execution_summary,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
        }
    
    def format_compact(self) -> str:
        """Format as compact string for Telegram display."""
        def _label(key: str) -> str:
            # Avoid underscores which can be interpreted by Telegram Markdown.
            mapping = {
                "rejected_confidence": "Confidence",
                "rejected_risk_reward": "R:R",
                "rejected_quality_scorer": "Quality",
                "rejected_order_book": "Order book",
                "rejected_invalid_prices": "Bad prices",
                "duplicates_filtered": "Duplicates",
                "rejected_market_hours": "Session closed",
                "rejected_regime_filter": "Regime",
                "stop_cap_applied": "Stop capped",
            }
            if key in mapping:
                return mapping[key]
            return key.replace("_", " ")

        lines = []
        
        # Signal density
        if self.signals_per_day > 0:
            lines.append(f"📊 {self.signals_per_day:.1f} signals/day ({self.trading_days} days)")
        else:
            lines.append("⚠️ No signals generated")
        
        # Top regimes
        if self.regime_distribution:
            top_regime = max(self.regime_distribution.items(), key=lambda x: x[1], default=(None, 0))
            if top_regime[0]:
                lines.append(f"📈 Top regime: {top_regime[0]} ({top_regime[1]} signals)")
        
        # Top bottlenecks
        if self.bottleneck_summary:
            sorted_bottlenecks = sorted(self.bottleneck_summary.items(), key=lambda x: x[1], reverse=True)[:3]
            if sorted_bottlenecks:
                bottleneck_str = ", ".join([f"{_label(k)}: {v}" for k, v in sorted_bottlenecks])
                lines.append(f"🚧 Bottlenecks: {bottleneck_str}")

        # Execution explainability (why trades < signals)
        if self.execution_summary:
            opened = self.execution_summary.get("signals_opened", 0)
            skipped_concurrency = self.execution_summary.get("signals_skipped_concurrency", 0)
            skipped_risk = self.execution_summary.get("signals_skipped_risk_budget", 0)
            skipped_stop_cap = self.execution_summary.get("signals_skipped_stop_cap", 0)
            skipped_invalid = self.execution_summary.get("signals_skipped_invalid_prices", 0)
            max_pos = self.execution_summary.get("max_concurrent_trades", 0)
            
            total_skipped = skipped_concurrency + skipped_risk + skipped_stop_cap + skipped_invalid
            
            if opened or total_skipped:
                max_part = f" (max {max_pos})" if max_pos else ""
                # Show breakdown if multiple skip reasons
                skip_parts = []
                if skipped_concurrency:
                    skip_parts.append(f"{skipped_concurrency} concurrency")
                if skipped_risk:
                    skip_parts.append(f"{skipped_risk} risk")
                if skipped_stop_cap:
                    skip_parts.append(f"{skipped_stop_cap} stop cap")
                if skipped_invalid:
                    skip_parts.append(f"{skipped_invalid} invalid")
                
                if len(skip_parts) > 1:
                    skip_str = ", ".join(skip_parts)
                    lines.append(f"🎯 Trades: {opened} opened, {total_skipped} skipped ({skip_str}){max_part}")
                else:
                    lines.append(f"🎯 Trades: {opened} opened, {total_skipped} skipped{max_part}")
        
        return "\n".join(lines) if lines else "No verification data"


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
    skipped_signals: Optional[List[Dict]] = field(default=None)  # Skipped signals with reasons
    # Verification diagnostics
    verification: Optional[VerificationSummary] = None


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


def _compute_verification_summary(
    signals: List[Dict],
    df: pd.DataFrame,
    bottleneck_counts: Optional[Dict[str, int]] = None,
    gate_reasons: Optional[List[str]] = None,
) -> VerificationSummary:
    """Compute verification diagnostics from backtest signals and data.
    
    Args:
        signals: List of signal dictionaries from backtest
        df: DataFrame with the backtest data (for date range)
        bottleneck_counts: Optional aggregated bottleneck counts
        gate_reasons: Optional list of scanner gate reasons encountered
    
    Returns:
        VerificationSummary with computed diagnostics
    """
    summary = VerificationSummary()
    
    # Date range
    if not df.empty and isinstance(df.index, pd.DatetimeIndex):
        summary.date_range_start = df.index[0].isoformat()
        summary.date_range_end = df.index[-1].isoformat()
        
        # Compute trading days and hours
        unique_dates = df.index.normalize().unique()
        summary.trading_days = len(unique_dates)
        summary.trading_hours = len(df.index.floor("h").unique())
    
    # Signal density
    if signals:
        summary.signals_per_day = len(signals) / max(summary.trading_days, 1)
        summary.signals_per_hour = len(signals) / max(summary.trading_hours, 1)
        
        # Signal type distribution
        type_dist: Dict[str, int] = {}
        regime_dist: Dict[str, int] = {}
        vol_dist: Dict[str, int] = {}
        session_dist: Dict[str, int] = {}
        
        for sig in signals:
            # Type distribution
            sig_type = sig.get("type", "unknown")
            type_dist[sig_type] = type_dist.get(sig_type, 0) + 1
            
            # Regime distribution (from signal context)
            regime = sig.get("regime", {})
            if isinstance(regime, dict):
                regime_type = regime.get("regime", "unknown")
                volatility = regime.get("volatility", "unknown")
                session = regime.get("session", "unknown")
                
                regime_dist[regime_type] = regime_dist.get(regime_type, 0) + 1
                vol_dist[volatility] = vol_dist.get(volatility, 0) + 1
                session_dist[session] = session_dist.get(session, 0) + 1
        
        summary.signal_type_distribution = type_dist
        summary.regime_distribution = regime_dist
        summary.volatility_distribution = vol_dist
        summary.session_distribution = session_dist
    
    # Bottleneck summary
    if bottleneck_counts:
        summary.bottleneck_summary = bottleneck_counts
    
    # Top gate reasons
    if gate_reasons:
        # Count and sort gate reasons
        reason_counts: Dict[str, int] = {}
        for reason in gate_reasons:
            # Simplify reason (extract key part).
            # IMPORTANT: do NOT split on ":" blindly because many reasons contain
            # time strings like "11:30-13:00" which would get truncated.
            # We only split on ": " (colon+space), which is the common pattern
            # for "Label: details" reasons (e.g., "Low volume: 42 < 100").
            if ": " in reason:
                key = reason.split(": ", 1)[0].strip()
            else:
                key = reason[:80]
            reason_counts[key] = reason_counts.get(key, 0) + 1
        
        sorted_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
        summary.top_gate_reasons = [f"{k} ({v}x)" for k, v in sorted_reasons[:5]]
    
    return summary


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
    - Config timeframe is overridden to match decision_rule so scanner threshold scaling is correct.
    """
    if config is None:
        config = NQIntradayConfig()
    
    # Override timeframe to match decision bars for correct threshold scaling
    # Scanner uses config.timeframe to scale volume/volatility thresholds
    # E.g., "5min" -> "5m", "1min" -> "1m"
    decision_timeframe = decision_rule.replace("min", "m")
    if config.timeframe != decision_timeframe:
        # Create a shallow copy to avoid mutating the original config
        from dataclasses import replace
        config = replace(config, timeframe=decision_timeframe)

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
    
    # Verification diagnostics collectors
    all_gate_reasons: List[str] = []
    bottleneck_counts: Dict[str, int] = {
        "rejected_confidence": 0,
        "rejected_risk_reward": 0,
        "rejected_quality_scorer": 0,
        "rejected_order_book": 0,
        "rejected_invalid_prices": 0,
        "duplicates_filtered": 0,
        "rejected_market_hours": 0,
        "rejected_regime_filter": 0,
        "stop_cap_applied": 0,
    }

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
            
            # Collect verification diagnostics from signal generator
            if hasattr(strategy, 'signal_generator') and hasattr(strategy.signal_generator, 'last_diagnostics'):
                diag = strategy.signal_generator.last_diagnostics
                if diag:
                    bottleneck_counts["rejected_confidence"] += diag.rejected_confidence
                    bottleneck_counts["rejected_risk_reward"] += diag.rejected_risk_reward
                    bottleneck_counts["rejected_quality_scorer"] += diag.rejected_quality_scorer
                    bottleneck_counts["rejected_order_book"] += diag.rejected_order_book
                    bottleneck_counts["rejected_invalid_prices"] += diag.rejected_invalid_prices
                    bottleneck_counts["duplicates_filtered"] += diag.duplicates_filtered
                    bottleneck_counts["rejected_regime_filter"] += diag.rejected_regime_filter
                    bottleneck_counts["stop_cap_applied"] += diag.stop_cap_applied
                    if diag.rejected_market_hours:
                        bottleneck_counts["rejected_market_hours"] += 1
                    all_gate_reasons.extend(diag.scanner_gate_reasons)
                    all_gate_reasons.extend(diag.regime_filter_reasons)
            
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

    # Compute verification summary
    # Filter out zero-count bottlenecks for cleaner output
    filtered_bottlenecks = {k: v for k, v in bottleneck_counts.items() if v > 0}
    verification = _compute_verification_summary(
        signals=signals,
        df=df_decision,
        bottleneck_counts=filtered_bottlenecks,
        gate_reasons=all_gate_reasons,
    )

    return BacktestResult(
        total_bars=len(df_decision),
        total_signals=len(signals),
        avg_confidence=avg_conf,
        avg_risk_reward=avg_rr,
        signals=signals if return_signals else None,
        signal_distribution=signal_distribution if signal_distribution else None,
        verification=verification,
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
    
    # Verification diagnostics collectors
    all_gate_reasons: List[str] = []
    bottleneck_counts: Dict[str, int] = {
        "rejected_confidence": 0,
        "rejected_risk_reward": 0,
        "rejected_quality_scorer": 0,
        "rejected_order_book": 0,
        "rejected_invalid_prices": 0,
        "duplicates_filtered": 0,
        "rejected_market_hours": 0,
        "rejected_regime_filter": 0,
        "stop_cap_applied": 0,
    }

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
            
            # Collect verification diagnostics from signal generator
            if hasattr(strategy, 'signal_generator') and hasattr(strategy.signal_generator, 'last_diagnostics'):
                diag = strategy.signal_generator.last_diagnostics
                if diag:
                    bottleneck_counts["rejected_confidence"] += diag.rejected_confidence
                    bottleneck_counts["rejected_risk_reward"] += diag.rejected_risk_reward
                    bottleneck_counts["rejected_quality_scorer"] += diag.rejected_quality_scorer
                    bottleneck_counts["rejected_order_book"] += diag.rejected_order_book
                    bottleneck_counts["rejected_invalid_prices"] += diag.rejected_invalid_prices
                    bottleneck_counts["duplicates_filtered"] += diag.duplicates_filtered
                    bottleneck_counts["rejected_regime_filter"] += diag.rejected_regime_filter
                    bottleneck_counts["stop_cap_applied"] += diag.stop_cap_applied
                    if diag.rejected_market_hours:
                        bottleneck_counts["rejected_market_hours"] += 1
                    all_gate_reasons.extend(diag.scanner_gate_reasons)
                    all_gate_reasons.extend(diag.regime_filter_reasons)
            
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
    
    # Compute verification summary
    filtered_bottlenecks = {k: v for k, v in bottleneck_counts.items() if v > 0}
    verification = _compute_verification_summary(
        signals=signals,
        df=df_1m,
        bottleneck_counts=filtered_bottlenecks,
        gate_reasons=all_gate_reasons,
    )
    
    return BacktestResult(
        total_bars=len(df_1m),
        total_signals=len(signals),
        avg_confidence=avg_conf,
        avg_risk_reward=avg_rr,
        signals=signals if return_signals else None,
        signal_distribution=signal_distribution if signal_distribution else None,
        verification=verification,
    )


@dataclass
class SkippedSignal:
    """Record of a skipped signal with reason."""
    timestamp: str
    signal_type: str
    direction: str
    stop_distance_points: float
    skip_reason: str
    computed_contracts: Optional[int] = None
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "stop_distance_points": self.stop_distance_points,
            "skip_reason": self.skip_reason,
            "computed_contracts": self.computed_contracts,
        }


class TradeSimulator:
    """
    Simulates trade execution from signals on historical data.
    
    Features:
    - Entry at signal price (or next bar open)
    - Stop loss and take profit tracking
    - End-of-day position close
    - P&L calculation with slippage
    - Trade journal with full details
    - Risk-based position sizing (optional)
    - Stop distance caps (optional)
    - Detailed skip tracking for execution explainability
    """

    def __init__(
        self,
        tick_value: float = 2.0,  # MNQ: $2 per point
        slippage_ticks: float = 0.5,  # Slippage in ticks
        commission_per_trade: float = 0.0,  # Commission per contract
        max_concurrent_trades: int = 1,
        eod_close_time: time = time(15, 45),  # Close positions before session end (ET, session-aware)
        session_start_time: Optional[time] = None,
        session_end_time: Optional[time] = None,
        # Risk-based sizing (optional)
        account_balance: Optional[float] = None,
        max_risk_per_trade: float = 0.01,  # 1% default
        risk_budget_dollars: Optional[float] = None,
        max_contracts: int = 10,
        max_stop_points: Optional[float] = None,  # Stop distance cap
        # Dynamic sizing (confidence-based)
        config: Optional["NQIntradayConfig"] = None,  # Pass config for dynamic sizing
    ):
        """
        Initialize trade simulator.
        
        Args:
            tick_value: Dollar value per point (MNQ = $2)
            slippage_ticks: Slippage in ticks (0.25 per tick for NQ)
            commission_per_trade: Commission per contract
            max_concurrent_trades: Maximum concurrent positions
            eod_close_time: Time to close positions (ET, compared on the *session end date*)
            session_start_time: Session start time (ET). If provided, EOD close becomes session-aware for
                                cross-midnight sessions (e.g., 18:00–16:10).
            session_end_time: Session end time (ET). See session_start_time.
            account_balance: Account balance for risk-based sizing (optional)
            max_risk_per_trade: Max risk per trade as fraction (default 0.01 = 1%)
            risk_budget_dollars: Direct dollar risk budget per trade (overrides account_balance calc)
            max_contracts: Maximum contracts per trade
            max_stop_points: Maximum allowed stop distance in points (trades exceeding this are skipped)
            config: NQIntradayConfig for dynamic sizing based on confidence and signal type
        """
        self.tick_value = tick_value
        self.slippage_ticks = slippage_ticks
        self.slippage_points = slippage_ticks * 0.25  # NQ tick = 0.25 points
        self.commission_per_trade = commission_per_trade
        self.max_concurrent_trades = max_concurrent_trades
        self.eod_close_time = eod_close_time
        self.session_start_time = session_start_time
        self.session_end_time = session_end_time
        
        # Risk-based sizing
        self.account_balance = account_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.risk_budget_dollars = risk_budget_dollars
        self.max_contracts = max_contracts
        self.max_stop_points = max_stop_points
        self.use_risk_sizing = account_balance is not None or risk_budget_dollars is not None
        
        # Dynamic sizing config
        self.config = config
        
        self.open_trades: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.skipped_signals: List[SkippedSignal] = []
        self.equity_curve: List[float] = []
        self.peak_equity: float = 0.0

    def _compute_position_size(self, signal: Dict) -> Tuple[int, Optional[str]]:
        """Compute position size from risk config and/or dynamic sizing.
        
        Dynamic sizing (if config provided with enable_dynamic_sizing=True):
        - Base: 5 contracts
        - High confidence (>0.8): 10-15 contracts  
        - Max confidence (>0.9) + winning signal type: 20-25 contracts
        
        Risk-based sizing (if account_balance or risk_budget_dollars provided):
        - Computes contracts from stop distance and risk budget
        - Capped by max_contracts
        
        Returns (contracts, skip_reason) where skip_reason is None if trade should proceed.
        """
        entry = signal.get("entry_price", 0)
        stop = signal.get("stop_loss", 0)
        direction = signal.get("direction", "long")

        if not entry or not stop or entry <= 0 or stop <= 0:
            return 0, "invalid_prices"

        # Calculate stop distance in points
        if direction == "long":
            stop_distance = abs(entry - stop)
        else:
            stop_distance = abs(stop - entry)

        if stop_distance <= 0:
            return 0, "zero_stop_distance"

        # Check stop distance cap
        if self.max_stop_points and stop_distance > self.max_stop_points:
            return 0, f"stop_exceeds_cap ({stop_distance:.1f} > {self.max_stop_points})"

        # Dynamic sizing based on confidence and signal type
        if self.config and getattr(self.config, "enable_dynamic_sizing", False):
            confidence = signal.get("confidence", 0.5)
            signal_type = signal.get("type", "unknown")
            contracts = self.config.get_position_size(confidence, signal_type)
            
            # Still apply risk-based cap if configured
            if self.use_risk_sizing:
                if self.risk_budget_dollars:
                    risk_budget = self.risk_budget_dollars
                elif self.account_balance:
                    risk_budget = self.account_balance * self.max_risk_per_trade
                else:
                    risk_budget = float("inf")
                
                risk_per_contract = stop_distance * self.tick_value
                if risk_per_contract > 0:
                    max_from_risk = int(risk_budget / risk_per_contract)
                    contracts = min(contracts, max_from_risk)
            
            return max(1, contracts), None

        # Risk-based sizing (if no dynamic sizing)
        if not self.use_risk_sizing:
            return self.max_contracts, None

        # Calculate risk budget
        if self.risk_budget_dollars:
            risk_budget = self.risk_budget_dollars
        elif self.account_balance:
            risk_budget = self.account_balance * self.max_risk_per_trade
        else:
            return self.max_contracts, None

        # Contracts = risk_budget / (stop_distance * tick_value)
        risk_per_contract = stop_distance * self.tick_value
        if risk_per_contract <= 0:
            return 0, "zero_risk_per_contract"

        contracts = int(risk_budget / risk_per_contract)

        # Clamp to max
        contracts = min(contracts, self.max_contracts)

        if contracts < 1:
            return 0, f"insufficient_risk_budget (need ${risk_per_contract:.2f}/contract, have ${risk_budget:.2f})"

        return contracts, None

    def _to_et(self, dt: datetime) -> datetime:
        """
        Convert a datetime to ET (America/New_York) if possible.

        Notes:
        - Bar timestamps are expected to be timezone-aware (UTC) in our backtests.
        - If dt is naive or ET timezone is unavailable, we return dt unchanged.
        """
        if _ET_TZ is None:
            return dt
        try:
            if dt.tzinfo is None:
                return dt
            return dt.astimezone(_ET_TZ)
        except Exception:
            return dt

    def _get_session_bounds_et(self, et_dt: datetime) -> Optional[Tuple[datetime, datetime]]:
        """
        Compute (session_start_dt, session_end_dt) for the session containing et_dt.

        If session times aren't provided, returns None (caller should fallback to naive behavior).

        Supports same-day sessions (start <= end) and cross-midnight sessions (start > end).
        """
        if self.session_start_time is None or self.session_end_time is None:
            return None

        start = self.session_start_time
        end = self.session_end_time

        # Require a date to anchor session windows.
        day = et_dt.date()
        t = et_dt.time()

        if start <= end:
            # Same-day session (e.g., 09:30–16:00).
            session_start = datetime.combine(day, start, tzinfo=et_dt.tzinfo)
            session_end = datetime.combine(day, end, tzinfo=et_dt.tzinfo)
            # If we're before start time, treat as "not in session" for windowing purposes.
            if t < start:
                return None
            return (session_start, session_end)

        # Cross-midnight session (e.g., 18:00–16:10).
        if t >= start:
            session_start = datetime.combine(day, start, tzinfo=et_dt.tzinfo)
            session_end = datetime.combine(day + timedelta(days=1), end, tzinfo=et_dt.tzinfo)
            return (session_start, session_end)

        if t <= end:
            session_start = datetime.combine(day - timedelta(days=1), start, tzinfo=et_dt.tzinfo)
            session_end = datetime.combine(day, end, tzinfo=et_dt.tzinfo)
            return (session_start, session_end)

        # Between end and start (session closed).
        return None

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
            position_size: Number of contracts per trade (can be overridden by risk-based sizing)
            
        Returns:
            Tuple of (closed_trades, metrics_dict)
        """
        self.open_trades = []
        self.closed_trades = []
        self.skipped_signals = []
        self.equity_curve = [0.0]
        self.peak_equity = 0.0
        
        # Execution explainability counters (helps explain why trades < signals)
        execution_stats: Dict[str, int] = {
            "signals_total": int(len(signals)),
            "signals_missing_timestamp": 0,
            "signals_timestamp_parse_fail": 0,
            "signals_timestamp_not_in_data": 0,
            "signals_opened": 0,
            "signals_skipped_concurrency": 0,
            "signals_skipped_risk_budget": 0,
            "signals_skipped_stop_cap": 0,
            "signals_skipped_invalid_prices": 0,
            "max_concurrent_trades": int(self.max_concurrent_trades),
        }

        # Convert signals to dict keyed by timestamp for efficient lookup
        signals_by_time: Dict[pd.Timestamp, List[Tuple[int, Dict]]] = {}
        index_tz = df.index.tz if isinstance(df.index, pd.DatetimeIndex) else None
        index_set = set(df.index) if isinstance(df.index, pd.DatetimeIndex) else set()

        for i, signal in enumerate(signals):
            ts_raw = signal.get("timestamp")
            if not ts_raw:
                execution_stats["signals_missing_timestamp"] += 1
                continue
            try:
                ts = pd.Timestamp(ts_raw) if not isinstance(ts_raw, pd.Timestamp) else ts_raw
            except Exception:
                execution_stats["signals_timestamp_parse_fail"] += 1
                continue

            # Normalize timezone semantics to match df index for equality checks.
            try:
                if index_tz is not None and ts.tzinfo is None:
                    ts = ts.tz_localize(index_tz)
                elif index_tz is None and ts.tzinfo is not None:
                    ts = ts.tz_convert(None)
            except Exception:
                # If tz normalization fails, keep original; it will likely not match any bar_time.
                pass

            if index_set and ts not in index_set:
                execution_stats["signals_timestamp_not_in_data"] += 1

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
                    # Check concurrency first
                    if len(self.open_trades) >= self.max_concurrent_trades:
                        execution_stats["signals_skipped_concurrency"] += 1
                        self._record_skipped_signal(signal, "concurrency_limit")
                        continue
                    
                    # Compute position size (with risk controls)
                    computed_size, skip_reason = self._compute_position_size(signal)
                    
                    if skip_reason:
                        # Categorize skip reason for stats
                        if "stop_exceeds_cap" in skip_reason:
                            execution_stats["signals_skipped_stop_cap"] += 1
                        elif "risk_budget" in skip_reason or "risk_per_contract" in skip_reason:
                            execution_stats["signals_skipped_risk_budget"] += 1
                        else:
                            execution_stats["signals_skipped_invalid_prices"] += 1
                        
                        self._record_skipped_signal(signal, skip_reason, computed_size)
                        continue
                    
                    # Use computed size if risk-based, otherwise use provided position_size
                    effective_size = computed_size if self.use_risk_sizing else position_size
                    
                    self._open_trade(signal, bar, bar_time, effective_size, signal_idx)
                    execution_stats["signals_opened"] += 1
            
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
        metrics.update(execution_stats)
        
        return self.closed_trades, metrics

    def _record_skipped_signal(
        self,
        signal: Dict,
        reason: str,
        computed_contracts: Optional[int] = None,
    ) -> None:
        """Record a skipped signal for execution explainability."""
        entry = signal.get("entry_price", 0)
        stop = signal.get("stop_loss", 0)
        direction = signal.get("direction", "long")
        
        if direction == "long":
            stop_distance = abs(entry - stop) if entry and stop else 0
        else:
            stop_distance = abs(stop - entry) if entry and stop else 0
        
        self.skipped_signals.append(SkippedSignal(
            timestamp=signal.get("timestamp", ""),
            signal_type=signal.get("type", "unknown"),
            direction=direction,
            stop_distance_points=stop_distance,
            skip_reason=reason,
            computed_contracts=computed_contracts,
        ))

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
        
        # Extract regime context from signal (for trade-type-by-regime analysis)
        regime_ctx = signal.get("regime", {})
        if not isinstance(regime_ctx, dict):
            regime_ctx = {}
        
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
            regime=regime_ctx.get("regime"),
            volatility=regime_ctx.get("volatility"),
            session=regime_ctx.get("session"),
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
        # IMPORTANT:
        # - eod_close_time is defined in ET (America/New_York).
        # - For cross-midnight futures sessions (e.g., 18:00–16:10), comparing only the clock time
        #   is wrong (18:30 ET would incorrectly be treated as "after 15:45").
        # - We therefore compare against the *session end date* when session bounds are known.
        et_dt = self._to_et(bar_time) if isinstance(bar_time, datetime) else bar_time

        # Session-aware close (preferred when session times are provided).
        session_bounds = self._get_session_bounds_et(et_dt) if isinstance(et_dt, datetime) else None
        if session_bounds is not None and isinstance(et_dt, datetime):
            _, session_end = session_bounds
            eod_dt = datetime.combine(session_end.date(), self.eod_close_time, tzinfo=session_end.tzinfo)

            # If we've passed the session end, force-close as well (safety net).
            if et_dt >= session_end or et_dt >= eod_dt:
                for trade in list(self.open_trades):
                    self._close_trade(trade, bar["close"], bar_time, ExitReason.END_OF_DAY)
            return

        # Fallback (legacy): compare ET clock time only. This is correct for same-day sessions,
        # but is NOT correct for cross-midnight sessions; callers should pass session_start/end.
        try:
            current_time = et_dt.time() if isinstance(et_dt, datetime) else et_dt  # type: ignore[assignment]
        except Exception:
            current_time = bar_time.time() if isinstance(bar_time, datetime) else bar_time  # type: ignore[assignment]

        if isinstance(current_time, time) and current_time >= self.eod_close_time:
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
    max_concurrent_trades: int = 1,
    return_trades: bool = True,
    # Risk-based sizing (optional)
    account_balance: Optional[float] = None,
    max_risk_per_trade: float = 0.01,
    risk_budget_dollars: Optional[float] = None,
    max_contracts: int = 10,
    max_stop_points: Optional[float] = None,
) -> BacktestResult:
    """
    Run full trade simulation backtest with P&L tracking.
    
    This combines signal generation with trade simulation to provide
    realistic performance metrics including win rate, P&L, and drawdown.
    
    Args:
        df_1m: 1-minute OHLCV DataFrame with DateTimeIndex
        config: Strategy configuration
        position_size: Number of contracts per trade (ignored if risk-based sizing is used)
        tick_value: Dollar value per point (MNQ = $2)
        slippage_ticks: Slippage in ticks
        return_trades: If True, include trade journal in result
        account_balance: Account balance for risk-based sizing (optional)
        max_risk_per_trade: Max risk per trade as fraction (default 0.01 = 1%)
        risk_budget_dollars: Direct dollar risk budget per trade
        max_contracts: Maximum contracts per trade
        max_stop_points: Maximum allowed stop distance in points
        
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
            verification=signal_result.verification,
        )
    
    # Run trade simulation
    # IMPORTANT: Pass session start/end so end-of-day close is session-aware for futures
    # cross-midnight sessions (e.g., 18:00–16:10).
    try:
        session_start = time.fromisoformat(config.start_time) if config and getattr(config, "start_time", None) else None
        session_end = time.fromisoformat(config.end_time) if config and getattr(config, "end_time", None) else None
    except Exception:
        session_start = None
        session_end = None

    simulator = TradeSimulator(
        tick_value=tick_value,
        slippage_ticks=slippage_ticks,
        max_concurrent_trades=max_concurrent_trades,
        session_start_time=session_start,
        session_end_time=session_end,
        account_balance=account_balance,
        max_risk_per_trade=max_risk_per_trade,
        risk_budget_dollars=risk_budget_dollars,
        max_contracts=max_contracts,
        max_stop_points=max_stop_points,
        config=config,  # Pass config for dynamic sizing based on confidence/signal type
    )
    
    closed_trades, metrics = simulator.simulate(
        df_1m,
        signal_result.signals,
        position_size=position_size,
    )
    
    # Convert trades to dict for JSON serialization
    trades_list = [t.to_dict() for t in closed_trades] if return_trades else None
    skipped_list = [s.to_dict() for s in simulator.skipped_signals] if return_trades else None

    # Attach execution explainability to verification (why trades < signals)
    if signal_result.verification is not None:
        signal_result.verification.execution_summary = {
            "signals_total": int(metrics.get("signals_total", 0) or 0),
            "signals_opened": int(metrics.get("signals_opened", 0) or 0),
            "signals_skipped_concurrency": int(metrics.get("signals_skipped_concurrency", 0) or 0),
            "signals_skipped_risk_budget": int(metrics.get("signals_skipped_risk_budget", 0) or 0),
            "signals_skipped_stop_cap": int(metrics.get("signals_skipped_stop_cap", 0) or 0),
            "signals_skipped_invalid_prices": int(metrics.get("signals_skipped_invalid_prices", 0) or 0),
            "signals_missing_timestamp": int(metrics.get("signals_missing_timestamp", 0) or 0),
            "signals_timestamp_not_in_data": int(metrics.get("signals_timestamp_not_in_data", 0) or 0),
            "max_concurrent_trades": int(metrics.get("max_concurrent_trades", max_concurrent_trades) or max_concurrent_trades),
        }
    
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
        skipped_signals=skipped_list,
        verification=signal_result.verification,
    )


def run_full_backtest_5m_decision(
    df_1m: pd.DataFrame,
    config: Optional[NQIntradayConfig] = None,
    position_size: int = 1,
    tick_value: float = 2.0,
    slippage_ticks: float = 0.5,
    max_concurrent_trades: int = 1,
    return_trades: bool = True,
    decision_rule: str = "5min",
    context_rule_1: str = "1h",
    context_rule_2: str = "4h",
    # Risk-based sizing (optional)
    account_balance: Optional[float] = None,
    max_risk_per_trade: float = 0.01,
    risk_budget_dollars: Optional[float] = None,
    max_contracts: int = 10,
    max_stop_points: Optional[float] = None,
) -> BacktestResult:
    """Full trade-simulation backtest using 5m decision bars and 1h/4h context.
    
    Args:
        df_1m: 1-minute OHLCV DataFrame
        config: Strategy configuration
        position_size: Contracts per trade (ignored if risk-based sizing used)
        tick_value: Dollar value per point (MNQ = $2)
        slippage_ticks: Slippage in ticks
        max_concurrent_trades: Max concurrent positions
        return_trades: Include trade journal in result
        decision_rule: Decision bar resample rule (default "5min")
        context_rule_1: First context timeframe (default "1h")
        context_rule_2: Second context timeframe (default "4h")
        account_balance: Account balance for risk-based sizing
        max_risk_per_trade: Max risk per trade fraction (default 0.01)
        risk_budget_dollars: Direct dollar risk budget per trade
        max_contracts: Maximum contracts per trade
        max_stop_points: Max stop distance cap (points)
    
    Note:
        Config timeframe is overridden to match decision_rule so scanner threshold scaling is correct.
    """
    if config is None:
        config = NQIntradayConfig()
    
    # Override timeframe to match decision bars for correct threshold scaling
    # Scanner uses config.timeframe to scale volume/volatility thresholds
    decision_timeframe = decision_rule.replace("min", "m")
    if config.timeframe != decision_timeframe:
        from dataclasses import replace
        config = replace(config, timeframe=decision_timeframe)

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
            verification=signal_result.verification,
        )

    # IMPORTANT: Pass session start/end so end-of-day close is session-aware for futures
    # cross-midnight sessions (e.g., 18:00–16:10).
    try:
        session_start = time.fromisoformat(config.start_time) if config and getattr(config, "start_time", None) else None
        session_end = time.fromisoformat(config.end_time) if config and getattr(config, "end_time", None) else None
    except Exception:
        session_start = None
        session_end = None

    simulator = TradeSimulator(
        tick_value=tick_value,
        slippage_ticks=slippage_ticks,
        max_concurrent_trades=max_concurrent_trades,
        session_start_time=session_start,
        session_end_time=session_end,
        account_balance=account_balance,
        max_risk_per_trade=max_risk_per_trade,
        risk_budget_dollars=risk_budget_dollars,
        max_contracts=max_contracts,
        max_stop_points=max_stop_points,
        config=config,  # Pass config for dynamic sizing based on confidence/signal type
    )

    closed_trades, metrics = simulator.simulate(
        df_decision,
        signal_result.signals,
        position_size=position_size,
    )

    trades_list = [t.to_dict() for t in closed_trades] if return_trades else None
    skipped_list = [s.to_dict() for s in simulator.skipped_signals] if return_trades else None

    # Attach execution explainability to verification (why trades < signals)
    if signal_result.verification is not None:
        signal_result.verification.execution_summary = {
            "signals_total": int(metrics.get("signals_total", 0) or 0),
            "signals_opened": int(metrics.get("signals_opened", 0) or 0),
            "signals_skipped_concurrency": int(metrics.get("signals_skipped_concurrency", 0) or 0),
            "signals_skipped_risk_budget": int(metrics.get("signals_skipped_risk_budget", 0) or 0),
            "signals_skipped_stop_cap": int(metrics.get("signals_skipped_stop_cap", 0) or 0),
            "signals_skipped_invalid_prices": int(metrics.get("signals_skipped_invalid_prices", 0) or 0),
            "signals_missing_timestamp": int(metrics.get("signals_missing_timestamp", 0) or 0),
            "signals_timestamp_not_in_data": int(metrics.get("signals_timestamp_not_in_data", 0) or 0),
            "max_concurrent_trades": int(metrics.get("max_concurrent_trades", max_concurrent_trades) or max_concurrent_trades),
        }

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
        skipped_signals=skipped_list,
        verification=signal_result.verification,
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
