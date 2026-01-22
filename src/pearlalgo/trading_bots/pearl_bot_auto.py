"""
PearlBot Auto - Single-File Strategy from Pine Scripts

Converted from Pine Script indicators in resources/pinescript/pearlbot/:
- EMA_Crossover.pine
- VWAP_AA.pine
- Volume.pine
- Trading Sessions.pine
- S&R Power (ChartPrime).pine
- TBT (ChartPrime).pine
- Supply & Demand Visible Range (Lux).pine
- SpacemanBTC Key Level V13.1.pine

VIRTUAL BROKER MODE: Only generates signals, no real execution.
Perfect for testing live without using real money.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pearlalgo.config.config_view import ConfigView
from datetime import datetime, timezone, time as dt_time
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

from pearlalgo.utils.logger import logger


# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = ConfigView({
    "symbol": "MNQ",
    "timeframe": "5m",
    "scan_interval": 30,
    
    # EMA Crossover (from EMA_Crossover.pine)
    "ema_fast": 9,
    "ema_slow": 21,
    
    # VWAP (from VWAP_AA.pine)
    "vwap_std_dev": 1.0,
    "vwap_bands": 2,
    
    # Volume (from Volume.pine)
    "volume_ma_length": 20,
    
    # S&R Power Channel (from S&R Power.pine)
    "sr_length": 130,
    "sr_extend": 30,
    "sr_atr_mult": 0.5,
    
    # TBT Trendlines (from TBT.pine)
    "tbt_period": 10,
    "tbt_trend_type": "wicks",  # "wicks" or "body"
    "tbt_extend": 25,
    
    # Supply & Demand (from Supply & Demand.pine)
    "sd_threshold_pct": 10.0,
    "sd_resolution": 50,
    
    # Risk Management
    "stop_loss_atr_mult": 1.5,
    "take_profit_atr_mult": 2.5,
    "min_confidence": 0.6,
    "min_risk_reward": 1.2,
    
    # Trading Hours (ET)
    "start_hour": 9,
    "start_minute": 30,
    "end_hour": 16,
    "end_minute": 0,
})


# ============================================================================
# INDICATOR FUNCTIONS (All inline, no classes)
# ============================================================================

def calculate_ema(df: pd.DataFrame, period: int, source: str = "close") -> pd.Series:
    """EMA - from EMA_Crossover.pine"""
    return df[source].ewm(span=period, adjust=False).mean()


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP - from VWAP_AA.pine"""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    vwap = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
    return vwap.fillna(method="bfill")


def calculate_vwap_bands(df: pd.DataFrame, std_dev: float = 1.0, bands: int = 2) -> Tuple[pd.Series, List[pd.Series], List[pd.Series]]:
    """VWAP with bands - from VWAP_AA.pine"""
    vwap = calculate_vwap(df)
    vwap_std = df["close"].rolling(window=20).std()
    
    upper_bands = []
    lower_bands = []
    for i in range(1, bands + 1):
        upper_bands.append(vwap + (vwap_std * std_dev * i))
        lower_bands.append(vwap - (vwap_std * std_dev * i))
    
    return vwap, upper_bands, lower_bands


def calculate_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume MA - from Volume.pine"""
    return df["volume"].rolling(window=period).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR calculation"""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.fillna(method="bfill")


def calculate_sr_power_channel(
    df: pd.DataFrame,
    length: int = 130,
    atr_mult: float = 0.5
) -> Tuple[float, float, int, int]:
    """
    S&R Power Channel - from S&R Power (ChartPrime).pine
    
    Returns: (resistance_level, support_level, buy_power, sell_power)
    """
    if len(df) < length:
        return 0.0, 0.0, 0, 0
    
    # Get max/min over lookback period
    lookback = df.tail(length)
    max_price = lookback["high"].max()
    min_price = lookback["low"].min()
    
    # Calculate ATR for channel width
    atr = calculate_atr(df, period=200).iloc[-1] * atr_mult
    
    # Resistance and Support levels
    resistance = max_price + atr
    support = min_price - atr
    
    # Buy/Sell Power (count bullish/bearish candles)
    buy_power = int((lookback["close"] > lookback["open"]).sum())
    sell_power = int((lookback["close"] < lookback["open"]).sum())
    
    return float(resistance), float(support), buy_power, sell_power


def calculate_tbt_trendlines(
    df: pd.DataFrame,
    period: int = 10,
    trend_type: str = "wicks"
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    TBT Trendlines - from TBT (ChartPrime).pine
    
    Returns: (resistance_slope, resistance_start_price, support_slope, support_start_price)
    """
    if len(df) < period * 2:
        return None, None, None, None
    
    # Pivot detection
    if trend_type == "wicks":
        pivot_highs = df["high"].rolling(window=period * 2 + 1, center=True).max() == df["high"]
        pivot_lows = df["low"].rolling(window=period * 2 + 1, center=True).min() == df["low"]
    else:  # body
        body_high = df[["open", "close"]].max(axis=1)
        body_low = df[["open", "close"]].min(axis=1)
        pivot_highs = body_high.rolling(window=period * 2 + 1, center=True).max() == body_high
        pivot_lows = body_low.rolling(window=period * 2 + 1, center=True).min() == body_low
    
    # Get latest pivots
    pivot_high_idx = pivot_highs[pivot_highs].index
    pivot_low_idx = pivot_lows[pivot_lows].index
    
    if len(pivot_high_idx) < 2 or len(pivot_low_idx) < 2:
        return None, None, None, None
    
    # Calculate slopes from last two pivots
    latest_highs = pivot_high_idx[-2:]
    latest_lows = pivot_low_idx[-2:]
    
    if len(latest_highs) >= 2:
        idx1, idx2 = latest_highs[-2], latest_highs[-1]
        price1 = df.loc[idx1, "high"]
        price2 = df.loc[idx2, "high"]
        time_diff = (idx2 - idx1).total_seconds() if hasattr(idx2 - idx1, 'total_seconds') else len(df) - df.index.get_loc(idx1) - (len(df) - df.index.get_loc(idx2))
        if time_diff > 0:
            resistance_slope = (price2 - price1) / time_diff
            resistance_start_price = float(price2)
        else:
            resistance_slope = None
            resistance_start_price = None
    else:
        resistance_slope = None
        resistance_start_price = None
    
    if len(latest_lows) >= 2:
        idx1, idx2 = latest_lows[-2], latest_lows[-1]
        price1 = df.loc[idx1, "low"]
        price2 = df.loc[idx2, "low"]
        time_diff = (idx2 - idx1).total_seconds() if hasattr(idx2 - idx1, 'total_seconds') else len(df) - df.index.get_loc(idx1) - (len(df) - df.index.get_loc(idx2))
        if time_diff > 0:
            support_slope = (price2 - price1) / time_diff
            support_start_price = float(price2)
        else:
            support_slope = None
            support_start_price = None
    else:
        support_slope = None
        support_start_price = None
    
    return resistance_slope, resistance_start_price, support_slope, support_start_price


def calculate_supply_demand_zones(
    df: pd.DataFrame,
    threshold_pct: float = 10.0,
    resolution: int = 50
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Supply & Demand Zones - from Supply & Demand Visible Range (Lux).pine
    
    Returns: (supply_level, supply_avg, demand_level, demand_avg)
    """
    if len(df) < 20:
        return None, None, None, None
    
    # Simplified version - find high volume price levels
    lookback = df.tail(100) if len(df) > 100 else df
    
    price_range = lookback["high"].max() - lookback["low"].min()
    if price_range == 0:
        return None, None, None, None
    
    # Bin prices and accumulate volume
    bins = {}
    for _, row in lookback.iterrows():
        price_bin = int((row["close"] - lookback["low"].min()) / price_range * resolution)
        if price_bin not in bins:
            bins[price_bin] = 0
        bins[price_bin] += row["volume"]
    
    total_volume = lookback["volume"].sum()
    threshold_volume = total_volume * (threshold_pct / 100.0)
    
    # Find supply (high volume at high prices) and demand (high volume at low prices)
    supply_level = None
    supply_avg = None
    demand_level = None
    demand_avg = None
    
    sorted_bins = sorted(bins.items(), key=lambda x: x[1], reverse=True)
    for price_bin, volume in sorted_bins:
        if volume >= threshold_volume:
            price = lookback["low"].min() + (price_bin / resolution * price_range)
            if supply_level is None and price > lookback["close"].iloc[-1]:
                supply_level = float(price)
                supply_avg = float(price)
            elif demand_level is None and price < lookback["close"].iloc[-1]:
                demand_level = float(price)
                demand_avg = float(price)
                break
    
    return supply_level, supply_avg, demand_level, demand_avg


def get_key_levels(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """
    Key Levels - simplified from SpacemanBTC Key Level.pine
    
    Returns dict with daily, weekly, monthly key levels
    """
    levels = {}
    
    # Daily levels
    if len(df) >= 1:
        daily_open = df["open"].iloc[-1] if len(df) == 1 else df["open"].iloc[-2]
        levels["daily_open"] = float(daily_open)
    
    # Weekly levels (simplified - would need resampling for full implementation)
    if len(df) >= 5:
        weekly_high = df["high"].tail(5).max()
        weekly_low = df["low"].tail(5).min()
        levels["weekly_high"] = float(weekly_high)
        levels["weekly_low"] = float(weekly_low)
        levels["weekly_mid"] = float((weekly_high + weekly_low) / 2)
    
    return levels


def check_trading_session(dt: datetime, config: Dict) -> bool:
    """Check if within trading hours - from Trading Sessions.pine"""
    try:
        et_tz = ZoneInfo("America/New_York")
        et_time = dt.astimezone(et_tz) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(et_tz)
        
        start_time = dt_time(config["start_hour"], config["start_minute"])
        end_time = dt_time(config["end_hour"], config["end_minute"])
        current_time = et_time.time()
        
        return start_time <= current_time <= end_time
    except Exception:
        return True  # Default to allow trading if timezone conversion fails


# ============================================================================
# SIGNAL GENERATION LOGIC
# ============================================================================

def detect_ema_crossover(df: pd.DataFrame, config: Dict) -> Tuple[bool, bool]:
    """Detect EMA crossover signals - from EMA_Crossover.pine"""
    if len(df) < config["ema_slow"]:
        return False, False
    
    ema_fast = calculate_ema(df, config["ema_fast"])
    ema_slow = calculate_ema(df, config["ema_slow"])
    
    # Current and previous values
    fast_curr = ema_fast.iloc[-1]
    fast_prev = ema_fast.iloc[-2] if len(df) > 1 else fast_curr
    slow_curr = ema_slow.iloc[-1]
    slow_prev = ema_slow.iloc[-2] if len(df) > 1 else slow_curr
    
    # Bullish cross: fast crosses above slow
    bullish_cross = fast_prev <= slow_prev and fast_curr > slow_curr
    
    # Bearish cross: fast crosses below slow
    bearish_cross = fast_prev >= slow_prev and fast_curr < slow_curr
    
    return bullish_cross, bearish_cross


def check_vwap_position(df: pd.DataFrame, config: Dict) -> Tuple[bool, bool]:
    """Check price position relative to VWAP - from VWAP_AA.pine"""
    if len(df) < 20:
        return False, False
    
    vwap = calculate_vwap(df)
    close = df["close"].iloc[-1]
    vwap_val = vwap.iloc[-1]
    
    price_above_vwap = close > vwap_val
    price_below_vwap = close < vwap_val
    
    return price_above_vwap, price_below_vwap


def check_volume_confirmation(df: pd.DataFrame, config: Dict) -> bool:
    """Check volume confirmation - from Volume.pine"""
    if len(df) < config["volume_ma_length"]:
        return False
    
    vol_ma = calculate_volume_ma(df, config["volume_ma_length"])
    current_vol = df["volume"].iloc[-1]
    avg_vol = vol_ma.iloc[-1]
    
    return current_vol > avg_vol


def check_sr_signals(df: pd.DataFrame, config: Dict) -> Tuple[Optional[str], float]:
    """
    Check S&R Power Channel signals - from S&R Power.pine
    
    Returns: (signal_type, confidence)
    """
    resistance, support, buy_power, sell_power = calculate_sr_power_channel(
        df, config["sr_length"], config["sr_atr_mult"]
    )
    
    if resistance == 0 or support == 0:
        return None, 0.0
    
    close = df["close"].iloc[-1]
    
    # Breakout above resistance
    if close > resistance:
        confidence = min(buy_power / config["sr_length"], 1.0)
        return "sr_breakout_long", confidence
    
    # Breakout below support
    if close < support:
        confidence = min(sell_power / config["sr_length"], 1.0)
        return "sr_breakout_short", confidence
    
    # Pullback to support in uptrend
    if support < close < (support + resistance) / 2 and buy_power > sell_power:
        confidence = min(buy_power / config["sr_length"] * 0.8, 1.0)
        return "sr_pullback_long", confidence
    
    # Pullback to resistance in downtrend
    if (support + resistance) / 2 < close < resistance and sell_power > buy_power:
        confidence = min(sell_power / config["sr_length"] * 0.8, 1.0)
        return "sr_pullback_short", confidence
    
    return None, 0.0


def check_tbt_signals(df: pd.DataFrame, config: Dict) -> Tuple[Optional[str], float]:
    """
    Check TBT Trendline Breakout signals - from TBT.pine
    
    Returns: (signal_type, confidence)
    """
    res_slope, res_start, sup_slope, sup_start = calculate_tbt_trendlines(
        df, config["tbt_period"], config["tbt_trend_type"]
    )
    
    if res_slope is None or sup_slope is None:
        return None, 0.0
    
    close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2] if len(df) > 1 else close
    
    # Simplified: check if price crossed trendline
    # Long: price breaks above descending resistance
    if res_slope < 0 and prev_close < res_start and close > res_start:
        return "tbt_breakout_long", 0.7
    
    # Short: price breaks below ascending support
    if sup_slope > 0 and prev_close > sup_start and close < sup_start:
        return "tbt_breakout_short", 0.7
    
    return None, 0.0


def check_supply_demand_signals(df: pd.DataFrame, config: Dict) -> Tuple[Optional[str], float]:
    """
    Check Supply & Demand signals - from Supply & Demand.pine
    
    Returns: (signal_type, confidence)
    """
    supply_level, supply_avg, demand_level, demand_avg = calculate_supply_demand_zones(
        df, config["sd_threshold_pct"], config["sd_resolution"]
    )
    
    if supply_level is None or demand_level is None:
        return None, 0.0
    
    close = df["close"].iloc[-1]
    
    # Price near demand zone (buy signal)
    if demand_level and abs(close - demand_level) / demand_level < 0.002:  # Within 0.2%
        return "sd_demand_bounce", 0.65
    
    # Price near supply zone (sell signal)
    if supply_level and abs(close - supply_level) / supply_level < 0.002:
        return "sd_supply_rejection", 0.65
    
    return None, 0.0


def generate_signals(
    df: pd.DataFrame,
    config: Optional[Dict] = None,
    current_time: Optional[datetime] = None
) -> List[Dict]:
    """
    Main signal generation function - combines all Pine Script strategies.
    
    VIRTUAL BROKER: Only generates signals, no real execution.
    """
    if config is None:
        config = CONFIG
    
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    signals = []
    
    # Validate data
    if df.empty or len(df) < max(config["ema_slow"], 20, config["sr_length"]):
        return signals
    
    required_cols = ["open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in required_cols):
        logger.warning(f"Missing required columns: {required_cols}")
        return signals
    
    # Time filter
    if not check_trading_session(current_time, config):
        return signals
    
    # Calculate indicators
    atr = calculate_atr(df, period=14).iloc[-1]
    close = df["close"].iloc[-1]
    
    # 1. EMA Crossover signals
    bullish_cross, bearish_cross = detect_ema_crossover(df, config)
    
    # 2. VWAP position
    price_above_vwap, price_below_vwap = check_vwap_position(df, config)
    
    # 3. Volume confirmation
    volume_confirmed = check_volume_confirmation(df, config)
    
    # 4. S&R Power Channel
    sr_signal, sr_confidence = check_sr_signals(df, config)
    
    # 5. TBT Trendlines
    tbt_signal, tbt_confidence = check_tbt_signals(df, config)
    
    # 6. Supply & Demand
    sd_signal, sd_confidence = check_supply_demand_signals(df, config)
    
    # 7. Key levels
    key_levels = get_key_levels(df)
    
    # Combine signals with confidence scoring
    signal_candidates = []
    
    # Long signals
    if bullish_cross and price_above_vwap:
        confidence = 0.7
        if volume_confirmed:
            confidence += 0.1
        if sr_signal and "long" in sr_signal:
            confidence = max(confidence, sr_confidence)
        if tbt_signal and "long" in tbt_signal:
            confidence = max(confidence, tbt_confidence)
        if sd_signal and "demand" in sd_signal:
            confidence = max(confidence, sd_confidence)
        
        if confidence >= config["min_confidence"]:
            entry_price = close
            stop_loss = entry_price - (atr * config["stop_loss_atr_mult"])
            take_profit = entry_price + (atr * config["take_profit_atr_mult"])
            risk_reward = (take_profit - entry_price) / (entry_price - stop_loss) if entry_price > stop_loss else 0
            
            if risk_reward >= config["min_risk_reward"]:
                signal_candidates.append({
                    "direction": "long",
                    "entry_price": float(entry_price),
                    "stop_loss": float(stop_loss),
                    "take_profit": float(take_profit),
                    "confidence": float(confidence),
                    "risk_reward": float(risk_reward),
                    "reason": f"EMA Cross + VWAP + Volume: {sr_signal or 'N/A'} | {tbt_signal or 'N/A'} | {sd_signal or 'N/A'}",
                    "indicators": {
                        "ema_cross": True,
                        "vwap_position": "above",
                        "volume_confirmed": volume_confirmed,
                        "sr_signal": sr_signal,
                        "tbt_signal": tbt_signal,
                        "sd_signal": sd_signal,
                        "key_levels": key_levels,
                    },
                })
    
    # Short signals
    if bearish_cross and price_below_vwap:
        confidence = 0.7
        if volume_confirmed:
            confidence += 0.1
        if sr_signal and "short" in sr_signal:
            confidence = max(confidence, sr_confidence)
        if tbt_signal and "short" in tbt_signal:
            confidence = max(confidence, tbt_confidence)
        if sd_signal and "supply" in sd_signal:
            confidence = max(confidence, sd_confidence)
        
        if confidence >= config["min_confidence"]:
            entry_price = close
            stop_loss = entry_price + (atr * config["stop_loss_atr_mult"])
            take_profit = entry_price - (atr * config["take_profit_atr_mult"])
            risk_reward = (entry_price - take_profit) / (stop_loss - entry_price) if stop_loss > entry_price else 0
            
            if risk_reward >= config["min_risk_reward"]:
                signal_candidates.append({
                    "direction": "short",
                    "entry_price": float(entry_price),
                    "stop_loss": float(stop_loss),
                    "take_profit": float(take_profit),
                    "confidence": float(confidence),
                    "risk_reward": float(risk_reward),
                    "reason": f"EMA Cross + VWAP + Volume: {sr_signal or 'N/A'} | {tbt_signal or 'N/A'} | {sd_signal or 'N/A'}",
                    "indicators": {
                        "ema_cross": True,
                        "vwap_position": "below",
                        "volume_confirmed": volume_confirmed,
                        "sr_signal": sr_signal,
                        "tbt_signal": tbt_signal,
                        "sd_signal": sd_signal,
                        "key_levels": key_levels,
                    },
                })
    
    # Add metadata to signals
    for signal in signal_candidates:
        signal["timestamp"] = current_time.isoformat()
        signal["symbol"] = config["symbol"]
        signal["timeframe"] = config["timeframe"]
        signal["type"] = "pearlbot_pinescript"
        signal["virtual_broker"] = True  # Mark as virtual - no real execution
    
    return signal_candidates


# ============================================================================
# VIRTUAL BROKER INTERFACE
# ============================================================================

class VirtualBroker:
    """
    Virtual broker for testing signals without real money.
    
    Tracks virtual positions and P&L for signal validation.
    """
    
    def __init__(self):
        self.positions: List[Dict] = []
        self.closed_trades: List[Dict] = []
        self.virtual_balance = 10000.0  # Starting balance
    
    def process_signal(self, signal: Dict) -> Dict:
        """
        Process a signal in virtual broker.
        
        Returns: Signal with virtual execution status
        """
        signal["virtual_status"] = "generated"
        signal["virtual_executed"] = False
        
        # In a real implementation, you'd check:
        # - If we already have a position
        # - Risk management rules
        # - Position sizing
        
        # For now, just mark as available for execution
        signal["virtual_executed"] = True
        signal["virtual_status"] = "ready_for_execution"
        
        logger.info(
            f"VIRTUAL BROKER: {signal['direction'].upper()} signal generated | "
            f"Entry: {signal['entry_price']:.2f} | "
            f"SL: {signal['stop_loss']:.2f} | "
            f"TP: {signal['take_profit']:.2f} | "
            f"Confidence: {signal['confidence']:.2f}"
        )
        
        return signal


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def run_pearlbot(
    df: pd.DataFrame,
    config: Optional[Dict] = None,
    virtual_broker: Optional[VirtualBroker] = None
) -> List[Dict]:
    """
    Run PearlBot strategy and generate signals.
    
    Args:
        df: OHLCV DataFrame
        config: Strategy configuration
        virtual_broker: Optional virtual broker instance
    
    Returns:
        List of signals (with virtual broker status if provided)
    """
    signals = generate_signals(df, config)
    
    if virtual_broker:
        signals = [virtual_broker.process_signal(sig) for sig in signals]
    
    return signals
