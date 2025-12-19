from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy


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

    strategy = NQIntradayStrategy(config=config)
    mtf = _build_mtf(df_1m, config)

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

    # Iterate bar-by-bar using a rolling window to mimic live behavior
    for idx in range(len(df_1m)):
        window = df_1m.iloc[: idx + 1]
        latest = window.iloc[-1]

        market_data = {
            "df": window,
            "df_5m": mtf["df_5m"].loc[: latest.name] if not mtf["df_5m"].empty else None,
            "df_15m": mtf["df_15m"].loc[: latest.name] if not mtf["df_15m"].empty else None,
            "latest_bar": {
                "timestamp": latest.name.isoformat(),
                "open": float(latest.get("open", latest["close"])),
                "high": float(latest.get("high", latest["close"])),
                "low": float(latest.get("low", latest["close"])),
                "close": float(latest["close"]),
                "volume": float(latest.get("volume", 0.0)),
            },
        }

        new_signals = strategy.analyze(market_data)
        for s in new_signals:
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
