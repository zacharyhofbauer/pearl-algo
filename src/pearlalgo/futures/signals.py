from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import pandas as pd

from pearlalgo.futures.sr import Bar, calculate_support_resistance, sr_signal_from_levels

Side = Literal["long", "short", "flat"]


@dataclass
class SignalQuality:
    """Track signal quality metrics."""
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    total_signals: int = 0
    profitable_signals: int = 0
    
    def accuracy(self) -> float:
        """Calculate signal accuracy."""
        total = self.true_positives + self.false_positives + self.true_negatives + self.false_negatives
        if total == 0:
            return 0.0
        return (self.true_positives + self.true_negatives) / total
    
    def precision(self) -> float:
        """Calculate precision (true positives / (true positives + false positives))."""
        total_positive = self.true_positives + self.false_positives
        if total_positive == 0:
            return 0.0
        return self.true_positives / total_positive
    
    def recall(self) -> float:
        """Calculate recall (true positives / (true positives + false negatives))."""
        total_actual_positive = self.true_positives + self.false_negatives
        if total_actual_positive == 0:
            return 0.0
        return self.true_positives / total_actual_positive
    
    def signal_to_noise_ratio(self) -> float:
        """Calculate signal-to-noise ratio (precision / (1 - precision))."""
        precision = self.precision()
        if precision == 0.0 or precision == 1.0:
            return 0.0
        return precision / (1.0 - precision)
    
    def win_rate(self) -> float:
        """Calculate win rate from profitable signals."""
        if self.total_signals == 0:
            return 0.0
        return self.profitable_signals / self.total_signals


def ma_cross_signal(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> Side:
    prices = df["Close"]
    if len(prices) < max(fast, slow):
        return "flat"
    fast_ma = prices.rolling(fast).mean().iloc[-1]
    slow_ma = prices.rolling(slow).mean().iloc[-1]
    if pd.isna(fast_ma) or pd.isna(slow_ma):
        return "flat"
    if fast_ma > slow_ma:
        return "long"
    if fast_ma < slow_ma:
        return "short"
    return "flat"


def calculate_signal_confidence(
    df: pd.DataFrame,
    side: Side,
    indicators: dict[str, Any],
) -> float:
    """
    Calculate signal confidence score (0.0 to 1.0) based on multiple factors.
    Higher confidence indicates stronger signal.
    """
    if side == "flat":
        return 0.0
    
    confidence = 0.5  # Base confidence
    
    # Volume confirmation (if available)
    if "Volume" in df.columns and len(df) > 0:
        recent_volume = df["Volume"].tail(5).mean()
        avg_volume = df["Volume"].mean()
        if recent_volume > avg_volume * 1.2:
            confidence += 0.15
        elif recent_volume < avg_volume * 0.8:
            confidence -= 0.1
    
    # Trend alignment
    if "fast_ma" in indicators and "slow_ma" in indicators:
        fast_ma = indicators.get("fast_ma")
        slow_ma = indicators.get("slow_ma")
        if fast_ma and slow_ma:
            if side == "long" and fast_ma > slow_ma:
                confidence += 0.15
            elif side == "short" and fast_ma < slow_ma:
                confidence += 0.15
    
    # Support/Resistance proximity
    if side == "long" and "support1" in indicators:
        support = indicators.get("support1")
        if support:
            close = float(df["Close"].iloc[-1])
            distance_pct = abs(close - support) / support
            if distance_pct < 0.005:  # Within 0.5%
                confidence += 0.1
    
    if side == "short" and "resistance1" in indicators:
        resistance = indicators.get("resistance1")
        if resistance:
            close = float(df["Close"].iloc[-1])
            distance_pct = abs(close - resistance) / resistance
            if distance_pct < 0.005:  # Within 0.5%
                confidence += 0.1
    
    # VWAP alignment
    if "vwap" in indicators:
        vwap = indicators.get("vwap")
        if vwap:
            close = float(df["Close"].iloc[-1])
            if side == "long" and close > vwap:
                confidence += 0.1
            elif side == "short" and close < vwap:
                confidence += 0.1
    
    return max(0.0, min(1.0, confidence))


def ema_filter(df: pd.DataFrame, period: int = 20) -> tuple[float | None, bool]:
    """
    Compute EMA and return (ema_value, price_above_ema).
    Returns (None, False) if insufficient data.
    """
    if len(df) < period:
        return None, False
    prices = df["Close"]
    ema = prices.ewm(span=period, adjust=False).mean().iloc[-1]
    if pd.isna(ema):
        return None, False
    close = float(prices.iloc[-1])
    return float(ema), close > ema


def sr_strategy(symbol: str, df: pd.DataFrame, *, fast: int = 20, slow: int = 50, tolerance: float = 0.002) -> dict[str, Any]:
    """
    Support/Resistance + VWAP strategy with EMA filter.
    - Long: close > vwap, near support1, and price > 20-EMA.
    - Short: close < vwap, near resistance1, and price < 20-EMA.
    """
    bars = [
        Bar(timestamp=idx, high=row["High"], low=row["Low"], close=row["Close"], volume=row.get("Volume", 0.0))
        for idx, row in df.iterrows()
    ]
    sr_levels = calculate_support_resistance(bars)
    close = float(df["Close"].iloc[-1])
    signal_obj = sr_signal_from_levels(close, sr_levels, tolerance=tolerance)
    side: Side = signal_obj.signal_type if signal_obj.signal_type in {"long", "short"} else "flat"
    
    # EMA filter (20-period by default, using fast parameter)
    ema_value, price_above_ema = ema_filter(df, period=fast)
    
    # Build trade_reason string
    trade_reason_parts = []
    if side == "long":
        if sr_levels.get("support1"):
            trade_reason_parts.append("Bullish pivot")
        if sr_levels.get("vwap") and close > sr_levels["vwap"]:
            trade_reason_parts.append("above VWAP")
        if ema_value and price_above_ema:
            trade_reason_parts.append(f"{fast}EMA")
        # Apply EMA filter: only take long if price above EMA
        if ema_value and not price_above_ema:
            side = "flat"
            trade_reason_parts = ["flat (below EMA filter)"]
    elif side == "short":
        if sr_levels.get("resistance1"):
            trade_reason_parts.append("Bearish pivot")
        if sr_levels.get("vwap") and close < sr_levels["vwap"]:
            trade_reason_parts.append("below VWAP")
        if ema_value and not price_above_ema:
            trade_reason_parts.append(f"below {fast}EMA")
        # Apply EMA filter: only take short if price below EMA
        if ema_value and price_above_ema:
            side = "flat"
            trade_reason_parts = ["flat (above EMA filter)"]
    
    trade_reason = " + ".join(trade_reason_parts) if trade_reason_parts else None

    # Build indicators dict for confidence calculation
    indicators = {
        "fast_ma": ema_value,
        "slow_ma": float(df["Close"].rolling(slow).mean().iloc[-1]) if len(df) >= slow else None,
        "support1": sr_levels.get("support1"),
        "resistance1": sr_levels.get("resistance1"),
        "vwap": sr_levels.get("vwap"),
    }
    
    # Calculate confidence score
    confidence = calculate_signal_confidence(df, side, indicators)

    return {
        "symbol": symbol,
        "strategy_name": "sr",
        "side": side,
        "fast_ma": ema_value,  # Actually EMA now
        "slow_ma": float(df["Close"].rolling(slow).mean().iloc[-1]) if len(df) >= slow else None,
        "support1": sr_levels.get("support1"),
        "resistance1": sr_levels.get("resistance1"),
        "vwap": sr_levels.get("vwap"),
        "entry_price": signal_obj.entry_price,
        "stop_price": signal_obj.stop_price,
        "target_price": signal_obj.target_price,
        "comment": trade_reason,
        "confidence": confidence,
        "params": {"fast": fast, "slow": slow, "tolerance": tolerance},
    }


def calculate_rsi(prices: pd.Series, period: int = 14) -> float | None:
    """Calculate Relative Strength Index (RSI)."""
    if len(prices) < period + 1:
        return None
    
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None


def calculate_bollinger_bands(
    prices: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[float | None, float | None, float | None]:
    """Calculate Bollinger Bands (upper, middle, lower)."""
    if len(prices) < period:
        return None, None, None
    
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    
    middle = float(sma.iloc[-1]) if not pd.isna(sma.iloc[-1]) else None
    upper = float(sma.iloc[-1] + (std.iloc[-1] * num_std)) if middle is not None and not pd.isna(std.iloc[-1]) else None
    lower = float(sma.iloc[-1] - (std.iloc[-1] * num_std)) if middle is not None and not pd.isna(std.iloc[-1]) else None
    
    return upper, middle, lower


def mean_reversion_strategy(
    symbol: str,
    df: pd.DataFrame,
    *,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
) -> dict[str, Any]:
    """
    Mean-reversion strategy using Bollinger Bands and RSI.
    - Long: price near lower band + RSI oversold
    - Short: price near upper band + RSI overbought
    """
    if len(df) < max(bb_period, rsi_period) + 1:
        return {
            "symbol": symbol,
            "strategy_name": "mean_reversion",
            "side": "flat",
            "confidence": 0.0,
            "params": {
                "bb_period": bb_period,
                "bb_std": bb_std,
                "rsi_period": rsi_period,
                "rsi_oversold": rsi_oversold,
                "rsi_overbought": rsi_overbought,
            },
        }
    
    prices = df["Close"]
    current_price = float(prices.iloc[-1])
    
    # Calculate Bollinger Bands
    upper_bb, middle_bb, lower_bb = calculate_bollinger_bands(prices, period=bb_period, num_std=bb_std)
    
    # Calculate RSI
    rsi = calculate_rsi(prices, period=rsi_period)
    
    side: Side = "flat"
    confidence = 0.0
    trade_reason = None
    
    if upper_bb is None or middle_bb is None or lower_bb is None or rsi is None:
        return {
            "symbol": symbol,
            "strategy_name": "mean_reversion",
            "side": "flat",
            "confidence": 0.0,
            "params": {
                "bb_period": bb_period,
                "bb_std": bb_std,
                "rsi_period": rsi_period,
                "rsi_oversold": rsi_oversold,
                "rsi_overbought": rsi_overbought,
            },
        }
    
    # Calculate distance from bands
    bb_range = upper_bb - lower_bb
    distance_from_lower = (current_price - lower_bb) / bb_range if bb_range > 0 else 0.5
    distance_from_upper = (upper_bb - current_price) / bb_range if bb_range > 0 else 0.5
    
    # Long signal: price near lower band + RSI oversold
    if distance_from_lower < 0.2 and rsi < rsi_oversold:
        side = "long"
        confidence = 0.6
        if distance_from_lower < 0.1 and rsi < rsi_oversold * 0.8:
            confidence = 0.85
        trade_reason = f"Mean reversion long: price {distance_from_lower*100:.1f}% from lower BB, RSI={rsi:.1f}"
    
    # Short signal: price near upper band + RSI overbought
    elif distance_from_upper < 0.2 and rsi > rsi_overbought:
        side = "short"
        confidence = 0.6
        if distance_from_upper < 0.1 and rsi > rsi_overbought * 1.2:
            confidence = 0.85
        trade_reason = f"Mean reversion short: price {distance_from_upper*100:.1f}% from upper BB, RSI={rsi:.1f}"
    
    # Calculate indicators for confidence
    indicators = {
        "upper_bb": upper_bb,
        "middle_bb": middle_bb,
        "lower_bb": lower_bb,
        "rsi": rsi,
        "distance_from_lower": distance_from_lower,
        "distance_from_upper": distance_from_upper,
    }
    
    # Adjust confidence based on additional factors
    if side != "flat":
        base_confidence = calculate_signal_confidence(df, side, indicators)
        confidence = max(confidence, base_confidence)
    
    return {
        "symbol": symbol,
        "strategy_name": "mean_reversion",
        "side": side,
        "upper_bb": upper_bb,
        "middle_bb": middle_bb,
        "lower_bb": lower_bb,
        "rsi": rsi,
        "entry_price": current_price,
        "comment": trade_reason,
        "confidence": confidence,
        "params": {
            "bb_period": bb_period,
            "bb_std": bb_std,
            "rsi_period": rsi_period,
            "rsi_oversold": rsi_oversold,
            "rsi_overbought": rsi_overbought,
        },
    }


def breakout_strategy(
    symbol: str,
    df: pd.DataFrame,
    *,
    lookback: int = 20,
    volume_multiplier: float = 1.5,
    min_breakout_pct: float = 0.001,
) -> dict[str, Any]:
    """
    Breakout strategy with volume confirmation.
    - Long: price breaks above recent high with volume confirmation
    - Short: price breaks below recent low with volume confirmation
    """
    if len(df) < lookback + 1:
        return {
            "symbol": symbol,
            "strategy_name": "breakout",
            "side": "flat",
            "confidence": 0.0,
            "params": {"lookback": lookback, "volume_multiplier": volume_multiplier, "min_breakout_pct": min_breakout_pct},
        }
    
    prices = df["Close"]
    highs = df["High"]
    lows = df["Low"]
    volumes = df.get("Volume", pd.Series([1.0] * len(df)))
    
    current_price = float(prices.iloc[-1])
    recent_high = float(highs.iloc[-lookback:-1].max())
    recent_low = float(lows.iloc[-lookback:-1].min())
    
    current_volume = float(volumes.iloc[-1])
    avg_volume = float(volumes.iloc[-lookback:-1].mean())
    
    side: Side = "flat"
    confidence = 0.0
    trade_reason = None
    
    # Check for upward breakout
    if current_price > recent_high * (1 + min_breakout_pct):
        if current_volume >= avg_volume * volume_multiplier:
            side = "long"
            confidence = 0.7
            if current_volume >= avg_volume * (volume_multiplier * 1.5):
                confidence = 0.9
            trade_reason = f"Breakout above {recent_high:.2f} with {current_volume/avg_volume:.1f}x volume"
    
    # Check for downward breakout
    elif current_price < recent_low * (1 - min_breakout_pct):
        if current_volume >= avg_volume * volume_multiplier:
            side = "short"
            confidence = 0.7
            if current_volume >= avg_volume * (volume_multiplier * 1.5):
                confidence = 0.9
            trade_reason = f"Breakout below {recent_low:.2f} with {current_volume/avg_volume:.1f}x volume"
    
    # Calculate indicators for confidence
    indicators = {
        "recent_high": recent_high,
        "recent_low": recent_low,
        "current_price": current_price,
        "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 1.0,
    }
    
    # Adjust confidence based on additional factors
    if side != "flat":
        base_confidence = calculate_signal_confidence(df, side, indicators)
        confidence = max(confidence, base_confidence)
    
    return {
        "symbol": symbol,
        "strategy_name": "breakout",
        "side": side,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "volume_ratio": indicators["volume_ratio"],
        "entry_price": current_price,
        "comment": trade_reason,
        "confidence": confidence,
        "params": {"lookback": lookback, "volume_multiplier": volume_multiplier, "min_breakout_pct": min_breakout_pct},
    }


def generate_signal(
    symbol: str,
    df: pd.DataFrame,
    strategy_name: str = "ma_cross",
    **params: Any,
) -> dict[str, Any]:
    """
    Strategy-agnostic signal wrapper. Supports ma_cross, sr, and breakout.
    Returns a dict with side, indicators, and metadata.
    """
    fast = int(params.get("fast", 20))
    slow = int(params.get("slow", 50))
    if strategy_name == "ma_cross":
        side = ma_cross_signal(df, fast=fast, slow=slow)
        prices = df["Close"]
        fast_ma = float(prices.rolling(fast).mean().iloc[-1]) if len(prices) >= fast else None
        slow_ma = float(prices.rolling(slow).mean().iloc[-1]) if len(prices) >= slow else None
        
        # Calculate confidence
        indicators = {"fast_ma": fast_ma, "slow_ma": slow_ma}
        confidence = calculate_signal_confidence(df, side, indicators)
        
        return {
            "symbol": symbol,
            "strategy_name": strategy_name,
            "side": side,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "confidence": confidence,
            "params": {"fast": fast, "slow": slow},
        }
    if strategy_name == "sr":
        return sr_strategy(symbol, df, fast=fast, slow=slow, tolerance=float(params.get("tolerance", 0.002)))
    if strategy_name == "breakout":
        return breakout_strategy(
            symbol,
            df,
            lookback=int(params.get("lookback", 20)),
            volume_multiplier=float(params.get("volume_multiplier", 1.5)),
            min_breakout_pct=float(params.get("min_breakout_pct", 0.001)),
        )
    if strategy_name == "mean_reversion":
        return mean_reversion_strategy(
            symbol,
            df,
            bb_period=int(params.get("bb_period", 20)),
            bb_std=float(params.get("bb_std", 2.0)),
            rsi_period=int(params.get("rsi_period", 14)),
            rsi_oversold=float(params.get("rsi_oversold", 30.0)),
            rsi_overbought=float(params.get("rsi_overbought", 70.0)),
        )

    raise ValueError(f"Unsupported strategy: {strategy_name}")
