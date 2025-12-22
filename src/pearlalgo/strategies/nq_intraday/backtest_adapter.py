from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.utils.logger import logger


@dataclass
class BacktestResult:
    """Lightweight summary of a signal-only backtest run."""

    total_bars: int
    total_signals: int
    avg_confidence: float
    avg_risk_reward: float
    signals: Optional[List[Dict]] = field(default=None)  # Optional: actual signals from backtest
    # Performance metrics (optional, calculated if signals available)
    win_rate: Optional[float] = None
    total_pnl: Optional[float] = None
    signal_distribution: Optional[Dict[str, int]] = None


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
