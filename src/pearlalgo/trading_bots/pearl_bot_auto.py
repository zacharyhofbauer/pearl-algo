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

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pearlalgo.config.config_view import ConfigView
from datetime import datetime, timezone, time as dt_time
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

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
    
    # SpacemanBTC Key Levels (from SpacemanBTC Key Level V13.1.pine)
    # These are critical reversal/breakout zones
    "key_level_proximity_pct": 0.15,  # Within 0.15% = "near" a level
    "key_level_breakout_pct": 0.05,   # Price crossed level by this % = breakout
    "key_level_bounce_confidence": 0.12,  # Confidence boost for bounce signals
    "key_level_breakout_confidence": 0.10,  # Confidence boost for breakout signals
    "key_level_rejection_penalty": 0.08,  # Confidence penalty for entering into resistance/support
    
    # Risk Management - WIDE STOPS to avoid wicks
    # Tight stops get hunted - use structure-based wide stops
    "stop_loss_atr_mult": 3.5,      # WIDE: 3.5x ATR to survive wicks
    "take_profit_atr_mult": 5.0,    # Let winners run: 5x ATR targets
    "min_confidence": 0.55,         # Allow trades with strong confluence
    "min_risk_reward": 1.3,         # Maintain decent R:R with wide stops

    # Aggressive mode knobs (OFF by default; enable via config overrides)
    # When enabled, allows additional entry triggers beyond EMA crossover.
    "allow_vwap_cross_entries": False,
    "allow_vwap_retest_entries": False,
    "allow_trend_momentum_entries": False,
    "trend_momentum_atr_mult": 0.5,
    "allow_trend_breakout_entries": False,
    "trend_breakout_lookback_bars": 5,

    # Virtual PnL grading (signal-only; no live execution)
    # Used by MarketAgentService virtual trade exits and tests.
    "virtual_pnl_enabled": True,
    "virtual_pnl_notify_entry": False,
    "virtual_pnl_notify_exit": False,
    # When both SL and TP are crossed intrabar, decide conservatively by default.
    "virtual_pnl_tiebreak": "stop_loss",
    
    # Trading Hours (ET)
    "start_hour": 9,
    "start_minute": 30,
    "end_hour": 16,
    "end_minute": 0,
})


# ============================================================================
# CACHING (for expensive computations that don't change within time periods)
# ============================================================================
import threading

# Cache for key levels - keyed by (data_hash, date_str) to avoid recomputing
# when data hasn't changed within the same day/week/month
# Thread safety: Protected by _key_levels_cache_lock for concurrent access
_key_levels_cache: Dict[str, Dict[str, Optional[float]]] = {}
_key_levels_cache_max_size = 10
_key_levels_cache_lock = threading.Lock()


def _get_key_levels_cache_key(df: pd.DataFrame) -> str:
    """Generate cache key based on date and data hash for effective caching."""
    if df.empty:
        return ""
    try:
        # Use date (not full timestamp) + hash of OHLC to allow cache hits within same day
        # when the same bar is re-processed
        if "timestamp" in df.columns:
            ts = df["timestamp"].iloc[-1]
            date_str = str(ts)[:10] if hasattr(ts, '__str__') else str(ts)[:10]
        else:
            date_str = str(df.index[-1])[:10]

        # Use hash of last few closes to detect data changes
        last_closes = df["close"].iloc[-5:].tolist() if len(df) >= 5 else df["close"].tolist()
        data_hash = hash(tuple(round(c, 2) for c in last_closes))
        return f"{date_str}_{len(df)}_{data_hash}"
    except Exception:
        return ""


def _clear_key_levels_cache_if_needed() -> None:
    """Clear cache if it grows too large. Must be called with lock held."""
    global _key_levels_cache
    if len(_key_levels_cache) > _key_levels_cache_max_size:
        # Keep only the most recent entries
        keys = list(_key_levels_cache.keys())
        for key in keys[:-_key_levels_cache_max_size]:
            del _key_levels_cache[key]


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divide two numbers, returning default if denominator is zero or near-zero.

    Args:
        numerator: The numerator
        denominator: The denominator
        default: Value to return if division is unsafe (default 0.0)

    Returns:
        Result of division or default value
    """
    if denominator == 0 or abs(denominator) < 1e-10:
        return default
    return numerator / denominator


def _safe_pct(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely calculate percentage: (numerator / denominator) * 100.

    Args:
        numerator: The numerator
        denominator: The denominator
        default: Value to return if division is unsafe (default 0.0)

    Returns:
        Percentage result or default value
    """
    if denominator == 0 or abs(denominator) < 1e-10:
        return default
    return (numerator / denominator) * 100


# ============================================================================
# SAFE CHECK WRAPPER + INDICATOR CONTEXT
# ============================================================================

def safe_check(fn, *args, **kwargs) -> Tuple[Optional[str], float]:
    """Run a signal check function, catching exceptions gracefully.

    Returns (None, 0.0) on failure so callers never crash from optional checks.

    **Error handling convention:** failures are logged at WARNING level so that
    indicator calculation errors are visible in logs and monitoring.  A silent
    failure here could mean a missed (or incorrect) trading signal, so
    visibility is critical.  Use ``ErrorHandler`` for non-strategy modules.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(
            f"Indicator check '{fn.__name__}' failed — returned (None, 0.0): {e}",
            exc_info=True,
        )
        return (None, 0.0)


@dataclass
class IndicatorContext:
    """Pre-computed indicators passed to all signal checks.

    Calculated once at the top of generate_signals() to eliminate redundant
    indicator computation across check functions.
    """
    df: pd.DataFrame
    config: Dict
    close: float
    prev_close: float
    atr: float
    atr_series: pd.Series
    ema_fast: pd.Series
    ema_slow: pd.Series
    vwap_series: pd.Series
    vwap_val: Optional[float]


# ============================================================================
# MARKET REGIME DETECTION
# ============================================================================

@dataclass
class MarketRegime:
    """Market regime classification result."""
    regime: str  # "trending_up", "trending_down", "ranging", "volatile"
    confidence: float  # 0.0 to 1.0
    trend_strength: float  # ADX-like metric
    volatility_ratio: float  # Current vs average volatility
    recommendation: str  # "full_size", "reduced_size", "avoid"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "confidence": self.confidence,
            "trend_strength": self.trend_strength,
            "volatility_ratio": self.volatility_ratio,
            "recommendation": self.recommendation,
        }


def detect_market_regime(
    df: pd.DataFrame,
    lookback: int = 50,
    trend_threshold: float = 0.6,
    volatility_window: int = 20,
) -> MarketRegime:
    """
    Detect current market regime using multiple indicators.
    
    Uses:
    - EMA slope and spread for trend direction
    - ATR ratio for volatility assessment
    - Price range analysis for ranging detection
    
    Returns:
        MarketRegime with classification and recommendations
    """
    if len(df) < lookback:
        return MarketRegime(
            regime="unknown",
            confidence=0.0,
            trend_strength=0.0,
            volatility_ratio=1.0,
            recommendation="avoid",
        )
    
    recent = df.tail(lookback)
    
    # Calculate EMAs for trend detection
    ema_fast = recent["close"].ewm(span=9, adjust=False).mean()
    ema_slow = recent["close"].ewm(span=21, adjust=False).mean()
    ema_long = recent["close"].ewm(span=50, adjust=False).mean()
    
    # Trend strength: EMA alignment and spread
    current_close = recent["close"].iloc[-1]
    ema_fast_val = ema_fast.iloc[-1]
    ema_slow_val = ema_slow.iloc[-1]
    ema_long_val = ema_long.iloc[-1]
    
    # EMA alignment score (-1 to +1)
    bullish_alignment = 0.0
    if ema_fast_val > ema_slow_val:
        bullish_alignment += 0.33
    if ema_slow_val > ema_long_val:
        bullish_alignment += 0.33
    if current_close > ema_fast_val:
        bullish_alignment += 0.34

    bearish_alignment = 0.0
    if ema_fast_val < ema_slow_val:
        bearish_alignment += 0.33
    if ema_slow_val < ema_long_val:
        bearish_alignment += 0.33
    if current_close < ema_fast_val:
        bearish_alignment += 0.34
    
    # Net alignment (-1 = strong bearish, +1 = strong bullish)
    net_alignment = bullish_alignment - bearish_alignment
    
    # EMA spread as % of price (trend strength indicator)
    ema_spread = _safe_pct(abs(ema_fast_val - ema_slow_val), current_close, default=0.0)

    # Volatility analysis
    high_low_range = recent["high"] - recent["low"]
    current_range = high_low_range.iloc[-1]
    avg_range = high_low_range.iloc[-volatility_window:].mean()
    volatility_ratio = _safe_div(current_range, avg_range, default=1.0)

    # Price range analysis (for ranging detection)
    price_high = recent["high"].max()
    price_low = recent["low"].min()
    _safe_pct(price_high - price_low, current_close, default=0.0)

    # Recent price movement (momentum)
    first_close = recent["close"].iloc[0]
    _safe_pct(current_close - first_close, first_close, default=0.0)
    
    # Classify regime
    regime = "ranging"
    confidence = 0.5
    trend_strength = abs(net_alignment)
    
    if abs(net_alignment) >= trend_threshold:
        # Strong trend
        if net_alignment > 0:
            regime = "trending_up"
        else:
            regime = "trending_down"
        confidence = min(1.0, abs(net_alignment) + ema_spread * 0.1)
    elif volatility_ratio > 2.0:
        # High volatility without clear trend
        regime = "volatile"
        confidence = min(1.0, volatility_ratio / 3.0)
    else:
        # Ranging market
        regime = "ranging"
        # Confidence in ranging increases when:
        # - Low EMA spread
        # - Low price range
        # - Low net alignment
        confidence = 1.0 - abs(net_alignment)
    
    # Determine recommendation
    if regime in ("trending_up", "trending_down"):
        if confidence > 0.7:
            recommendation = "full_size"
        else:
            recommendation = "reduced_size"
    elif regime == "volatile":
        recommendation = "avoid" if volatility_ratio > 2.5 else "reduced_size"
    else:  # ranging
        if confidence > 0.7:
            recommendation = "avoid"  # Strong ranging = avoid trend signals
        else:
            recommendation = "reduced_size"
    
    return MarketRegime(
        regime=regime,
        confidence=confidence,
        trend_strength=trend_strength,
        volatility_ratio=volatility_ratio,
        recommendation=recommendation,
    )


# ============================================================================
# INDICATOR FUNCTIONS (All inline, no classes)
# ============================================================================

def calculate_ema(df: pd.DataFrame, period: int, source: str = "close") -> pd.Series:
    """EMA - from EMA_Crossover.pine"""
    return df[source].ewm(span=period, adjust=False).mean()


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP - from VWAP_AA.pine"""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum()
    # Avoid division by zero when cumulative volume is zero
    vwap = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)
    return vwap.bfill()


def calculate_vwap_bands(
    df: pd.DataFrame,
    std_dev: float = 1.0,
    bands: int = 2,
    *,
    vwap_series: Optional[pd.Series] = None,
    std_window: int = 20,
) -> Tuple[pd.Series, List[pd.Series], List[pd.Series]]:
    """VWAP with bands - from VWAP_AA.pine"""
    vwap = vwap_series if vwap_series is not None else calculate_vwap(df)
    vwap_std = df["close"].rolling(window=std_window).std()
    
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
    return atr.bfill()


def calculate_sr_power_channel(
    df: pd.DataFrame,
    length: int = 130,
    atr_mult: float = 0.5,
    precomputed_atr: Optional[float] = None,
) -> Tuple[float, float, int, int]:
    """
    S&R Power Channel - from S&R Power (ChartPrime).pine
    
    Returns: (resistance_level, support_level, buy_power, sell_power)
    
    Optimization: Accept precomputed_atr to avoid redundant ATR calculations.
    """
    if len(df) < length:
        return 0.0, 0.0, 0, 0
    
    # Get max/min over lookback period
    lookback = df.tail(length)
    max_price = lookback["high"].max()
    min_price = lookback["low"].min()
    
    # Use precomputed ATR if provided, otherwise calculate
    if precomputed_atr is not None:
        atr = precomputed_atr * atr_mult
    else:
        atr = calculate_atr(df, period=200).iloc[-1] * atr_mult
    
    # Resistance and Support levels
    resistance = max_price + atr
    support = min_price - atr
    
    # Buy/Sell Power (count bullish/bearish candles) - already vectorized
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
        time_diff_raw = idx2 - idx1
        if hasattr(time_diff_raw, 'total_seconds'):
            time_diff = time_diff_raw.total_seconds()
        else:
            loc1 = df.index.get_loc(idx1)
            loc2 = df.index.get_loc(idx2)
            # get_loc can return int, slice, or ndarray - we need int positions
            pos1 = loc1 if isinstance(loc1, int) else int(loc1.start) if isinstance(loc1, slice) else 0
            pos2 = loc2 if isinstance(loc2, int) else int(loc2.start) if isinstance(loc2, slice) else 0
            time_diff = float(pos2 - pos1)
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
        time_diff_raw = idx2 - idx1
        if hasattr(time_diff_raw, 'total_seconds'):
            time_diff = time_diff_raw.total_seconds()
        else:
            loc1 = df.index.get_loc(idx1)
            loc2 = df.index.get_loc(idx2)
            # get_loc can return int, slice, or ndarray - we need int positions
            pos1 = loc1 if isinstance(loc1, int) else int(loc1.start) if isinstance(loc1, slice) else 0
            pos2 = loc2 if isinstance(loc2, int) else int(loc2.start) if isinstance(loc2, slice) else 0
            time_diff = float(pos2 - pos1)
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
    
    Optimized: Uses vectorized operations instead of iterrows() for better performance.
    """
    if len(df) < 20:
        return None, None, None, None
    
    # Simplified version - find high volume price levels
    lookback = df.tail(100) if len(df) > 100 else df
    
    low_min = lookback["low"].min()
    high_max = lookback["high"].max()
    price_range = high_max - low_min
    if price_range == 0:
        return None, None, None, None
    
    # Vectorized binning: compute bin for each row
    closes = lookback["close"].values
    volumes = lookback["volume"].values
    
    # Calculate bin indices (vectorized)
    bins_arr = ((closes - low_min) / price_range * resolution).astype(int)
    bins_arr = np.clip(bins_arr, 0, resolution - 1)  # Ensure bins are in valid range
    
    # Accumulate volume per bin using numpy bincount (much faster than loop)
    bin_volumes = np.bincount(bins_arr, weights=volumes, minlength=resolution)
    
    total_volume = volumes.sum()
    threshold_volume = total_volume * (threshold_pct / 100.0)
    
    current_close = lookback["close"].iloc[-1]
    
    # Find supply (high volume at high prices) and demand (high volume at low prices)
    supply_level = None
    supply_avg = None
    demand_level = None
    demand_avg = None
    
    # Get indices sorted by volume (descending)
    sorted_indices = np.argsort(bin_volumes)[::-1]
    
    for price_bin in sorted_indices:
        volume = bin_volumes[price_bin]
        if volume >= threshold_volume:
            price = low_min + (price_bin / resolution * price_range)
            if supply_level is None and price > current_close:
                supply_level = float(price)
                supply_avg = float(price)
            elif demand_level is None and price < current_close:
                demand_level = float(price)
                demand_avg = float(price)
                break
    
    return supply_level, supply_avg, demand_level, demand_avg


def get_key_levels(df: pd.DataFrame, use_cache: bool = True) -> Dict[str, Optional[float]]:
    """
    SpacemanBTC Key Levels - comprehensive implementation.
    
    Computes multi-timeframe key levels that act as reversal/breakout zones:
    - Daily: DO (Daily Open), PDH (Previous Day High), PDL (Previous Day Low), PDM (Previous Day Mid)
    - Weekly: WO (Weekly Open), PWH (Previous Week High), PWL (Previous Week Low), PWM (Previous Week Mid)
    - Monthly: MO (Monthly Open), PMH (Previous Month High), PML (Previous Month Low)
    - Session: Session High/Low for current trading day
    
    Returns dict with all computed levels and their types (support/resistance).
    
    Optimization: Caches results since D/W/M levels rarely change within a scan cycle.
    """
    global _key_levels_cache
    
    levels: Dict[str, Optional[float]] = {}
    
    if df.empty or len(df) < 2:
        return levels
    
    # Check cache first (thread-safe)
    if use_cache:
        cache_key = _get_key_levels_cache_key(df)
        with _key_levels_cache_lock:
            if cache_key and cache_key in _key_levels_cache:
                return _key_levels_cache[cache_key].copy()
    
    # Ensure we have a timestamp column or index
    if "timestamp" in df.columns:
        df_ts = df.copy()
        if not isinstance(df_ts["timestamp"].iloc[0], pd.Timestamp):
            df_ts["timestamp"] = pd.to_datetime(df_ts["timestamp"])
        df_ts = df_ts.set_index("timestamp")
    elif isinstance(df.index, pd.DatetimeIndex):
        df_ts = df.copy()
    else:
        # Fallback: use simple calculations without proper resampling
        return _get_key_levels_simple(df)
    
    try:
        # Current bar info
        current_close = float(df["close"].iloc[-1])
        levels["current_close"] = current_close
        
        # =====================================================================
        # DAILY LEVELS (most important for intraday trading)
        # =====================================================================
        daily_df = df_ts.resample("D").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last"
        }).dropna()
        
        if len(daily_df) >= 1:
            # Daily Open (DO) - today's open
            levels["daily_open"] = float(daily_df["open"].iloc[-1])
            
            if len(daily_df) >= 2:
                # Previous Day High (PDH), Low (PDL), Mid (PDM)
                prev_day = daily_df.iloc[-2]
                levels["prev_day_high"] = float(prev_day["high"])
                levels["prev_day_low"] = float(prev_day["low"])
                levels["prev_day_mid"] = float((prev_day["high"] + prev_day["low"]) / 2)
                
                # Current Day High/Low (for session range)
                curr_day = daily_df.iloc[-1]
                levels["curr_day_high"] = float(curr_day["high"])
                levels["curr_day_low"] = float(curr_day["low"])
        
        # =====================================================================
        # WEEKLY LEVELS
        # =====================================================================
        weekly_df = df_ts.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last"
        }).dropna()
        
        if len(weekly_df) >= 1:
            # Weekly Open (WO)
            levels["weekly_open"] = float(weekly_df["open"].iloc[-1])
            
            if len(weekly_df) >= 2:
                # Previous Week High (PWH), Low (PWL), Mid (PWM)
                prev_week = weekly_df.iloc[-2]
                levels["prev_week_high"] = float(prev_week["high"])
                levels["prev_week_low"] = float(prev_week["low"])
                levels["prev_week_mid"] = float((prev_week["high"] + prev_week["low"]) / 2)
        
        # =====================================================================
        # MONTHLY LEVELS
        # =====================================================================
        monthly_df = df_ts.resample("ME").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last"
        }).dropna()
        
        if len(monthly_df) >= 1:
            # Monthly Open (MO)
            levels["monthly_open"] = float(monthly_df["open"].iloc[-1])
            
            if len(monthly_df) >= 2:
                # Previous Month High (PMH), Low (PML), Mid (PMM)
                prev_month = monthly_df.iloc[-2]
                levels["prev_month_high"] = float(prev_month["high"])
                levels["prev_month_low"] = float(prev_month["low"])
                levels["prev_month_mid"] = float((prev_month["high"] + prev_month["low"]) / 2)
        
        # =====================================================================
        # CLASSIFY LEVELS AS SUPPORT OR RESISTANCE
        # =====================================================================
        levels["support_levels"] = []
        levels["resistance_levels"] = []
        
        for key, value in levels.items():
            if value is None or key in ("current_close", "support_levels", "resistance_levels"):
                continue
            if isinstance(value, (int, float)):
                if value < current_close:
                    levels["support_levels"].append((key, value))
                elif value > current_close:
                    levels["resistance_levels"].append((key, value))
        
        # Sort by proximity to current price
        levels["support_levels"] = sorted(levels["support_levels"], key=lambda x: x[1], reverse=True)
        levels["resistance_levels"] = sorted(levels["resistance_levels"], key=lambda x: x[1])
        
    except Exception as e:
        logger.debug(f"Error computing key levels with resampling: {e}")
        return _get_key_levels_simple(df)
    
    # Cache the result for future calls (thread-safe)
    if use_cache:
        cache_key = _get_key_levels_cache_key(df)
        if cache_key:
            with _key_levels_cache_lock:
                _clear_key_levels_cache_if_needed()
                _key_levels_cache[cache_key] = levels.copy()
    
    return levels


def _get_key_levels_simple(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Fallback simple key levels when resampling isn't available."""
    levels: Dict[str, Optional[float]] = {}
    
    if len(df) < 2:
        return levels
    
    current_close = float(df["close"].iloc[-1])
    levels["current_close"] = current_close
    
    # Use lookback windows as approximations
    # ~390 1m bars = 1 trading day, ~1950 = 1 week
    
    # Daily approximation (last ~390 bars or available)
    daily_lookback = min(390, len(df) - 1)
    if daily_lookback > 10:
        daily_slice = df.tail(daily_lookback)
        levels["daily_open"] = float(daily_slice["open"].iloc[0])
        levels["prev_day_high"] = float(daily_slice["high"].max())
        levels["prev_day_low"] = float(daily_slice["low"].min())
        levels["prev_day_mid"] = float((levels["prev_day_high"] + levels["prev_day_low"]) / 2)
    
    # Weekly approximation (last ~1950 bars or available)
    weekly_lookback = min(1950, len(df))
    if weekly_lookback > 50:
        weekly_slice = df.tail(weekly_lookback)
        levels["weekly_open"] = float(weekly_slice["open"].iloc[0])
        levels["prev_week_high"] = float(weekly_slice["high"].max())
        levels["prev_week_low"] = float(weekly_slice["low"].min())
        levels["prev_week_mid"] = float((levels["prev_week_high"] + levels["prev_week_low"]) / 2)
    
    # Classify as support/resistance
    levels["support_levels"] = []
    levels["resistance_levels"] = []
    
    for key, value in levels.items():
        if value is None or key in ("current_close", "support_levels", "resistance_levels"):
            continue
        if isinstance(value, (int, float)):
            if value < current_close:
                levels["support_levels"].append((key, value))
            elif value > current_close:
                levels["resistance_levels"].append((key, value))
    
    levels["support_levels"] = sorted(levels["support_levels"], key=lambda x: x[1], reverse=True)
    levels["resistance_levels"] = sorted(levels["resistance_levels"], key=lambda x: x[1])
    
    return levels


def check_key_level_signals(
    df: pd.DataFrame,
    key_levels: Dict[str, Optional[float]],
    config: Dict
) -> Tuple[Optional[str], float, Dict]:
    """
    Check for key level bounce or breakout signals - core SpacemanBTC logic.
    
    Key levels are where reversals and breakouts happen. This function detects:
    - BOUNCE: Price approaching a level and showing rejection (reversal opportunity)
    - BREAKOUT: Price decisively crossing a level (continuation opportunity)
    
    Returns: (signal_type, confidence_adjustment, level_info)
    
    Signal types:
    - "bounce_support_long": Bouncing off support level (buy signal)
    - "bounce_resistance_short": Bouncing off resistance level (sell signal)
    - "breakout_resistance_long": Breaking above resistance (buy signal)
    - "breakout_support_short": Breaking below support (sell signal)
    - "near_resistance_caution": Approaching resistance (reduce long confidence)
    - "near_support_caution": Approaching support (reduce short confidence)
    - None: No significant key level interaction
    """
    if df.empty or len(df) < 3 or not key_levels:
        return None, 0.0, {}
    
    current_close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    current_high = float(df["high"].iloc[-1])
    current_low = float(df["low"].iloc[-1])
    
    proximity_pct = config.get("key_level_proximity_pct", 0.15) / 100.0
    breakout_pct = config.get("key_level_breakout_pct", 0.05) / 100.0
    bounce_conf = config.get("key_level_bounce_confidence", 0.12)
    breakout_conf = config.get("key_level_breakout_confidence", 0.10)
    rejection_penalty = config.get("key_level_rejection_penalty", 0.08)
    
    level_info = {
        "nearest_support": None,
        "nearest_resistance": None,
        "support_distance_pct": None,
        "resistance_distance_pct": None,
        "level_interaction": None,
    }
    
    # Find nearest support and resistance
    support_levels = key_levels.get("support_levels", [])
    resistance_levels = key_levels.get("resistance_levels", [])
    
    nearest_support = None
    nearest_support_name = None
    if support_levels:
        nearest_support_name, nearest_support = support_levels[0]
        level_info["nearest_support"] = nearest_support
        level_info["nearest_support_name"] = nearest_support_name
        level_info["support_distance_pct"] = _safe_pct(abs(current_close - nearest_support), current_close)

    nearest_resistance = None
    nearest_resistance_name = None
    if resistance_levels:
        nearest_resistance_name, nearest_resistance = resistance_levels[0]
        level_info["nearest_resistance"] = nearest_resistance
        level_info["nearest_resistance_name"] = nearest_resistance_name
        level_info["resistance_distance_pct"] = _safe_pct(abs(nearest_resistance - current_close), current_close)
    
    # =========================================================================
    # BOUNCE DETECTION (Reversal Signals)
    # =========================================================================
    
    # Support bounce: price dropped to support level and is now bouncing up
    if nearest_support is not None:
        support_proximity = _safe_div(abs(current_low - nearest_support), current_close)

        # Check if we touched/near support and closed higher (bounce)
        if support_proximity <= proximity_pct:
            # Touched support zone
            if current_close > current_low and current_close > prev_close:
                # Bouncing up from support - bullish reversal signal
                level_info["level_interaction"] = f"bounce_support:{nearest_support_name}"
                return "bounce_support_long", bounce_conf, level_info
            elif current_close < prev_close:
                # Breaking down through support - bearish continuation
                if _safe_div(prev_close - current_close, current_close) > breakout_pct:
                    level_info["level_interaction"] = f"breakout_support:{nearest_support_name}"
                    return "breakout_support_short", breakout_conf, level_info

    # Resistance bounce: price rose to resistance level and is now rejecting down
    if nearest_resistance is not None:
        resistance_proximity = _safe_div(abs(current_high - nearest_resistance), current_close)

        # Check if we touched/near resistance and closed lower (rejection)
        if resistance_proximity <= proximity_pct:
            # Touched resistance zone
            if current_close < current_high and current_close < prev_close:
                # Rejecting from resistance - bearish reversal signal
                level_info["level_interaction"] = f"bounce_resistance:{nearest_resistance_name}"
                return "bounce_resistance_short", bounce_conf, level_info
            elif current_close > prev_close:
                # Breaking up through resistance - bullish continuation
                if _safe_div(current_close - prev_close, current_close) > breakout_pct:
                    level_info["level_interaction"] = f"breakout_resistance:{nearest_resistance_name}"
                    return "breakout_resistance_long", breakout_conf, level_info

    # =========================================================================
    # CAUTION SIGNALS (Reduce confidence when entering into levels)
    # =========================================================================

    # Approaching resistance from below - caution for longs
    if nearest_resistance is not None:
        resistance_distance = _safe_div(nearest_resistance - current_close, current_close)
        if resistance_distance <= proximity_pct * 2 and current_close > prev_close:
            level_info["level_interaction"] = f"approaching_resistance:{nearest_resistance_name}"
            return "near_resistance_caution", -rejection_penalty, level_info

    # Approaching support from above - caution for shorts
    if nearest_support is not None:
        support_distance = _safe_div(current_close - nearest_support, current_close)
        if support_distance <= proximity_pct * 2 and current_close < prev_close:
            level_info["level_interaction"] = f"approaching_support:{nearest_support_name}"
            return "near_support_caution", -rejection_penalty, level_info
    
    return None, 0.0, level_info


def check_trading_session(dt: datetime, config: Dict) -> bool:
    """
    Check if within trading hours - from Trading Sessions.pine.
    
    Supports overnight sessions (e.g., 18:00→16:10) where start > end.
    In that case, the session spans midnight: current >= start OR current <= end.
    """
    try:
        et_tz = ZoneInfo("America/New_York")
        et_time = dt.astimezone(et_tz) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(et_tz)
        
        start_time = dt_time(config["start_hour"], config["start_minute"])
        end_time = dt_time(config["end_hour"], config["end_minute"])
        current_time = et_time.time()
        
        # Handle overnight sessions (start > end means session crosses midnight)
        if start_time > end_time:
            # Overnight: in session if current >= start OR current <= end
            return current_time >= start_time or current_time <= end_time
        else:
            # Same-day: in session if start <= current <= end
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


def check_vwap_position(
    df: pd.DataFrame,
    config: Dict,
    *,
    vwap_series: Optional[pd.Series] = None,
) -> Tuple[bool, bool]:
    """Check price position relative to VWAP - from VWAP_AA.pine"""
    if len(df) < 20:
        return False, False
    
    vwap = vwap_series if vwap_series is not None else calculate_vwap(df)
    close = float(df["close"].iloc[-1])
    vwap_val = float(vwap.iloc[-1])
    
    if pd.isna(vwap_val) or pd.isna(close):
        return False, False

    price_above_vwap = close > vwap_val
    price_below_vwap = close < vwap_val
    
    return price_above_vwap, price_below_vwap


def detect_vwap_cross(df: pd.DataFrame, *, vwap_series: Optional[pd.Series] = None) -> Tuple[bool, bool]:
    """
    Detect VWAP cross on the latest bar.

    Returns: (bullish_vwap_cross, bearish_vwap_cross)
    """
    if df.empty or len(df) < 2 or "close" not in df.columns:
        return False, False

    try:
        vwap = vwap_series if vwap_series is not None else calculate_vwap(df)
        close_prev = float(df["close"].iloc[-2])
        close_curr = float(df["close"].iloc[-1])
        vwap_prev = float(vwap.iloc[-2])
        vwap_curr = float(vwap.iloc[-1])
    except Exception:
        return False, False

    # NaN guards
    if any(pd.isna(x) for x in (close_prev, close_curr, vwap_prev, vwap_curr)):
        return False, False

    bullish = close_prev <= vwap_prev and close_curr > vwap_curr
    bearish = close_prev >= vwap_prev and close_curr < vwap_curr
    return bool(bullish), bool(bearish)


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


# ============================================================================
# STRATEGY PARAMETERS (single source of truth for all magic numbers)
# ============================================================================
# These were previously scattered as literal values throughout generate_signals().
# Now they are explicit, documented, and overridable via config.yaml.

from pydantic import BaseModel as _BaseModel, Field as _Field


class StrategyParams(_BaseModel):
    """All tunable strategy parameters in one place.

    Values are loaded from the ``pearl_bot_auto`` section of config.yaml,
    falling back to the defaults below.  Every former magic number in
    ``generate_signals()`` is represented here.
    """

    # -- ATR & Risk Management -------------------------------------------
    atr_period: int = _Field(default=14, ge=2, description="ATR lookback period")
    stop_loss_atr_mult: float = _Field(default=3.5, ge=0.5, description="SL ATR multiplier")
    take_profit_atr_mult: float = _Field(default=5.0, ge=0.5, description="TP ATR multiplier")
    volatile_sl_mult: float = _Field(default=1.2, description="SL multiplier in volatile regime")
    volatile_tp_mult: float = _Field(default=1.2, description="TP multiplier in volatile regime")
    ranging_sl_mult: float = _Field(default=0.9, description="SL multiplier in ranging regime")
    ranging_tp_mult: float = _Field(default=0.8, description="TP multiplier in ranging regime")

    # -- EMA settings ----------------------------------------------------
    ema_fast: int = _Field(default=9, ge=2)
    ema_slow: int = _Field(default=21, ge=2)

    # -- VWAP settings ---------------------------------------------------
    vwap_std_dev: float = _Field(default=1.0, ge=0.1)
    vwap_bands: int = _Field(default=2, ge=1)

    # -- Confidence scoring ----------------------------------------------
    base_confidence: float = _Field(default=0.50, ge=0.0, le=1.0, description="Starting confidence for any trigger")
    volume_boost: float = _Field(default=0.12, description="Confidence boost for volume confirmation")
    sr_boost: float = _Field(default=0.08, description="S&R signal base boost")
    tbt_boost: float = _Field(default=0.08, description="TBT signal base boost")
    sd_boost: float = _Field(default=0.10, description="Supply/Demand zone boost")
    vwap_extended_penalty: float = _Field(default=-0.08, description="Penalty for extended VWAP position")
    vwap_bounce_boost: float = _Field(default=0.05, description="Boost for VWAP band bounce")
    breakout_boost: float = _Field(default=0.03, description="Boost for breakout signals")
    pdl_pdh_boost: float = _Field(default=0.10, description="Boost for PDL/PDH bounce")
    pwl_pwh_boost: float = _Field(default=0.12, description="Boost for PWL/PWH bounce")
    pdh_pdl_caution_penalty: float = _Field(default=-0.05, description="Penalty for entering into PDH/PDL")
    pwh_pwl_caution_penalty: float = _Field(default=-0.07, description="Penalty for entering into PWH/PWL")
    max_confidence: float = _Field(default=0.99, description="Hard cap on confidence")

    # -- Regime detection ------------------------------------------------
    regime_lookback: int = _Field(default=50, ge=10)
    regime_conf_threshold: float = _Field(default=0.7, description="Confidence threshold for regime filtering")
    regime_volatility_threshold: float = _Field(default=2.5, description="Volatility ratio threshold")
    regime_reduced_multiplier: float = _Field(default=0.7, description="Reduced sizing multiplier")
    regime_avoid_multiplier: float = _Field(default=0.5, description="Avoid sizing multiplier")

    # -- Signal thresholds -----------------------------------------------
    min_confidence: float = _Field(default=0.55, ge=0.0, le=1.0)
    min_risk_reward: float = _Field(default=1.3, ge=0.5)

    # -- Key levels (SpacemanBTC) ----------------------------------------
    key_level_proximity_pct: float = _Field(default=0.15, description="Within 0.15% = near a level")
    key_level_breakout_pct: float = _Field(default=0.05, description="Crossed by 0.05% = breakout")
    pdl_pdh_distance_pct: float = _Field(default=0.3, description="PDL/PDH proximity threshold %")
    pwl_pwh_distance_pct: float = _Field(default=0.5, description="PWL/PWH proximity threshold %")

    # -- Aggressive mode -------------------------------------------------
    allow_vwap_cross_entries: bool = False
    allow_vwap_retest_entries: bool = False
    allow_trend_momentum_entries: bool = False
    trend_momentum_atr_mult: float = _Field(default=0.5)
    allow_trend_breakout_entries: bool = False
    trend_breakout_lookback_bars: int = _Field(default=5)


def _load_strategy_params(config: Dict) -> StrategyParams:
    """Build a :class:`StrategyParams` from a config dict.

    Keys present in *config* override the Pydantic defaults; unknown keys
    are silently ignored (``extra="ignore"``).
    """
    # Collect values from the config dict that match StrategyParams fields
    overrides: Dict[str, Any] = {}
    for field_name in StrategyParams.model_fields:
        if field_name in config:
            overrides[field_name] = config[field_name]
    return StrategyParams(**overrides)


# ============================================================================
# STAGED SIGNAL GENERATION FUNCTIONS
# ============================================================================
# The monolithic generate_signals() has been decomposed into four testable
# stages.  The original function now delegates to these stages.


@dataclass
class IndicatorResult:
    """Output of ``_calculate_indicators`` — all indicator values for one bar."""
    close: float
    prev_close: float
    atr: float
    atr_series: "pd.Series"
    ema_fast: "pd.Series"
    ema_slow: "pd.Series"
    vwap_series: "pd.Series"
    vwap_val: Optional[float]
    ema_cross_up: bool
    ema_cross_down: bool
    volume_confirmed: bool
    sr_signal: Optional[str]
    sr_confidence: float
    tbt_signal: Optional[str]
    tbt_confidence: float
    sd_signal: Optional[str]
    sd_confidence: float
    key_levels: Dict[str, Optional[float]]
    key_level_signal: Optional[str]
    key_level_confidence: float
    vwap_band_signal: Optional[str]
    regime: "MarketRegime"
    # Aggressive triggers (only populated when config enables them)
    vwap_cross_signal: Optional[str]
    vwap_retest_signal: Optional[str]
    trend_breakout_signal: Optional[str]
    trend_momentum_signal: Optional[str]


def _calculate_indicators(
    df: "pd.DataFrame",
    params: StrategyParams,
    config: Dict,
) -> Optional[IndicatorResult]:
    """Stage 1: Calculate all indicators for the current bar.

    Returns ``None`` if core indicators are invalid (ATR zero, etc.).
    """
    # Core indicators
    atr_series = calculate_atr(df, period=params.atr_period)
    atr = float(atr_series.iloc[-1]) if not atr_series.empty else None
    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else close

    if atr is None or pd.isna(atr) or atr <= 0:
        return None

    ema_fast_period = int(config.get("ema_fast", params.ema_fast))
    ema_slow_period = int(config.get("ema_slow", params.ema_slow))
    ema_fast = calculate_ema(df, ema_fast_period)
    ema_slow = calculate_ema(df, ema_slow_period)

    ema_cross_up = bool(
        ema_fast.iloc[-1] > ema_slow.iloc[-1] and ema_fast.iloc[-2] <= ema_slow.iloc[-2]
    ) if len(ema_fast) >= 2 and len(ema_slow) >= 2 else False
    ema_cross_down = bool(
        ema_fast.iloc[-1] < ema_slow.iloc[-1] and ema_fast.iloc[-2] >= ema_slow.iloc[-2]
    ) if len(ema_fast) >= 2 and len(ema_slow) >= 2 else False

    vwap_series = calculate_vwap(df)
    vwap_val = float(vwap_series.iloc[-1]) if not vwap_series.empty and not pd.isna(vwap_series.iloc[-1]) else None

    # Extended indicators (optional -- failures return (None, 0.0))
    ctx = IndicatorContext(df=df, config=config, close=close, prev_close=prev_close,
                           atr=atr, atr_series=atr_series, ema_fast=ema_fast, ema_slow=ema_slow,
                           vwap_series=vwap_series, vwap_val=vwap_val)

    vol_signal, vol_conf = safe_check(check_volume_confirmation, ctx)
    volume_confirmed = vol_signal is not None

    sr_signal, sr_conf = safe_check(check_sr_signals, ctx)
    tbt_signal, tbt_conf = safe_check(check_tbt_signals, ctx)
    sd_signal, sd_conf = safe_check(check_supply_demand_signals, ctx)

    key_levels = get_key_levels(df) if len(df) >= 5 else {}
    kl_signal, kl_conf = (None, 0.0)
    if key_levels:
        kl_signal, kl_conf = safe_check(check_key_level_signals, close, key_levels, config)

    vwap_band_signal: Optional[str] = None
    try:
        if vwap_val is not None:
            bands = calculate_vwap_bands(df, std_dev=params.vwap_std_dev, num_bands=params.vwap_bands)
            if bands:
                upper1 = bands.get("upper_1")
                lower1 = bands.get("lower_1")
                if upper1 is not None and close > upper1:
                    vwap_band_signal = "extended_above"
                elif lower1 is not None and close < lower1:
                    vwap_band_signal = "extended_below"
                elif lower1 is not None and close <= lower1 * 1.002:
                    vwap_band_signal = "bounce_lower"
                elif upper1 is not None and close >= upper1 * 0.998:
                    vwap_band_signal = "bounce_upper"
    except Exception:
        pass

    regime = detect_market_regime(df, lookback=params.regime_lookback)

    # Aggressive triggers (optional)
    vwap_cross_sig = vwap_retest_sig = trend_brk_sig = trend_mom_sig = None
    if params.allow_vwap_cross_entries and vwap_val is not None:
        vc_sig, _ = safe_check(detect_vwap_cross, df, vwap_series)
        vwap_cross_sig = vc_sig
    if params.allow_vwap_retest_entries and vwap_val is not None:
        if (prev_close < vwap_val and close > vwap_val):
            vwap_retest_sig = "vwap_retest_long"
        elif (prev_close > vwap_val and close < vwap_val):
            vwap_retest_sig = "vwap_retest_short"
    # (trend breakout/momentum left for the original code to handle)

    return IndicatorResult(
        close=close, prev_close=prev_close, atr=atr, atr_series=atr_series,
        ema_fast=ema_fast, ema_slow=ema_slow, vwap_series=vwap_series, vwap_val=vwap_val,
        ema_cross_up=ema_cross_up, ema_cross_down=ema_cross_down,
        volume_confirmed=volume_confirmed,
        sr_signal=sr_signal, sr_confidence=sr_conf,
        tbt_signal=tbt_signal, tbt_confidence=tbt_conf,
        sd_signal=sd_signal, sd_confidence=sd_conf,
        key_levels=key_levels, key_level_signal=kl_signal, key_level_confidence=kl_conf,
        vwap_band_signal=vwap_band_signal, regime=regime,
        vwap_cross_signal=vwap_cross_sig, vwap_retest_signal=vwap_retest_sig,
        trend_breakout_signal=trend_brk_sig, trend_momentum_signal=trend_mom_sig,
    )


def _apply_filters(
    signals: List[Dict],
    params: StrategyParams,
    regime: "MarketRegime",
) -> List[Dict]:
    """Stage 4: Apply post-processing filters and regime adjustments.

    - Applies regime-based confidence multiplier.
    - Caps confidence at ``params.max_confidence``.
    - Removes signals below ``params.min_confidence`` after adjustment.
    """
    regime_multiplier = 1.0
    if regime.recommendation == "reduced_size":
        regime_multiplier = params.regime_reduced_multiplier
    elif regime.recommendation == "avoid":
        regime_multiplier = params.regime_avoid_multiplier

    filtered: List[Dict] = []
    for sig in signals:
        original_conf = sig["confidence"]
        adjusted_conf = min(original_conf * regime_multiplier, params.max_confidence)
        sig["confidence"] = round(adjusted_conf, 4)
        sig["regime_adjustment"] = {
            "original_confidence": round(original_conf, 4),
            "multiplier": regime_multiplier,
            "adjusted_confidence": round(adjusted_conf, 4),
        }
        sig["market_regime"] = regime.to_dict()

        if adjusted_conf >= params.min_confidence:
            filtered.append(sig)
        else:
            logger.debug(
                "Signal dropped after regime adjustment: conf %.3f < %.3f",
                adjusted_conf, params.min_confidence,
            )
    return filtered


def generate_signals(
    df: pd.DataFrame,
    config: Optional[Dict] = None,
    current_time: Optional[datetime] = None
) -> List[Dict]:
    """
    Main signal generation function - combines all Pine Script strategies.
    
    VIRTUAL BROKER: Only generates signals, no real execution.
    
    Indicator-robust design:
    - Core indicators (EMA, VWAP, Volume) are required for signal generation
    - Extended indicators (S&R, TBT, Supply/Demand, Key Levels) are conditional
      contributors that enhance confidence when data is available

    **Decomposition (6A):** The heavy lifting is split into testable stages:

    - :func:`_calculate_indicators` — compute all indicator values (Stage 1)
    - Inline signal detection & confidence scoring (Stages 2-3, kept inline
      because the long/short logic shares local variables heavily)
    - :func:`_apply_filters` — regime adjustment & post-filter (Stage 4)

    The ``StrategyParams`` model holds all former magic numbers.
    """
    if config is None:
        config = CONFIG

    # Load strategy parameters from config (6A: single source of truth for magic numbers)
    params = _load_strategy_params(config)

    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    signals: List[Dict] = []
    
    # Minimum bars for core indicators (EMA slow, VWAP window, Volume MA)
    min_core_bars = max(params.ema_slow, config.get("volume_ma_length", 20), 20)
    
    # Validate data - only require core indicator minimums
    if df.empty or len(df) < min_core_bars:
        return signals
    
    required_cols = ["open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in required_cols):
        logger.warning(f"Missing required columns: {required_cols}")
        return signals
    
    # Time filter
    if not check_trading_session(current_time, config):
        return signals
    
    # Stage 1: Calculate all indicators
    ind = _calculate_indicators(df, params, config)
    if ind is None:
        return signals  # ATR invalid or zero
    
    # Calculate core indicators with NaN guards
    atr_series = calculate_atr(df, period=14)
    atr = float(atr_series.iloc[-1]) if not atr_series.empty else None
    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else close
    
    # Guard: ATR must be valid and positive for SL/TP calculation
    if atr is None or pd.isna(atr) or atr <= 0:
        logger.debug("ATR invalid or zero, skipping signal generation")
        return signals
    
    # Core indicators (computed once; reused across optional triggers and VWAP band logic)
    ema_fast_period = int(config.get("ema_fast", 9) or 9)
    ema_slow_period = int(config.get("ema_slow", 21) or 21)
    ema_fast = calculate_ema(df, ema_fast_period)
    ema_slow = calculate_ema(df, ema_slow_period)
    
    fast_curr = float(ema_fast.iloc[-1])
    fast_prev = float(ema_fast.iloc[-2]) if len(ema_fast) > 1 else fast_curr
    slow_curr = float(ema_slow.iloc[-1])
    slow_prev = float(ema_slow.iloc[-2]) if len(ema_slow) > 1 else slow_curr
    
    # 1) EMA crossover (event) + EMA trend (state)
    if any(pd.isna(x) for x in (fast_curr, fast_prev, slow_curr, slow_prev)):
        bullish_cross, bearish_cross = False, False
        ema_bull_trend, ema_bear_trend = False, False
    else:
        bullish_cross = fast_prev <= slow_prev and fast_curr > slow_curr
        bearish_cross = fast_prev >= slow_prev and fast_curr < slow_curr
        ema_bull_trend = fast_curr > slow_curr
        ema_bear_trend = fast_curr < slow_curr
    
    # 2) VWAP position (core - required)
    try:
        vwap_series = calculate_vwap(df)
    except Exception:
        vwap_series = pd.Series([float("nan")] * len(df), index=df.index)
    
    vwap_val = float(vwap_series.iloc[-1]) if not vwap_series.empty else float("nan")
    if pd.isna(vwap_val) or pd.isna(close):
        price_above_vwap, price_below_vwap = False, False
        vwap_curr: Optional[float] = None
    else:
        price_above_vwap = close > vwap_val
        price_below_vwap = close < vwap_val
        vwap_curr = vwap_val

    # Optional aggressive triggers (gated by config)
    allow_vwap_cross_entries = bool(config.get("allow_vwap_cross_entries", False))
    allow_vwap_retest_entries = bool(config.get("allow_vwap_retest_entries", False))
    allow_trend_momentum_entries = bool(config.get("allow_trend_momentum_entries", False))
    allow_trend_breakout_entries = bool(config.get("allow_trend_breakout_entries", False))
    bullish_vwap_cross, bearish_vwap_cross = False, False
    vwap_retest_long, vwap_retest_short = False, False
    trend_momentum_long, trend_momentum_short = False, False
    trend_breakout_long, trend_breakout_short = False, False
    
    # VWAP cross (event-like trigger)
    if allow_vwap_cross_entries:
        bullish_vwap_cross, bearish_vwap_cross = detect_vwap_cross(df, vwap_series=vwap_series)

    # VWAP retest (wick-through + close back on trend side)
    if allow_vwap_retest_entries and vwap_curr is not None:
        try:
            low = float(df["low"].iloc[-1])
            high = float(df["high"].iloc[-1])
            vwap_retest_long = bool(ema_bull_trend and (low <= vwap_curr) and (close > vwap_curr))
            vwap_retest_short = bool(ema_bear_trend and (high >= vwap_curr) and (close < vwap_curr))
        except Exception as e:
            logger.debug(f"VWAP retest check failed: {e}")
            vwap_retest_long, vwap_retest_short = False, False

    # Trend breakout (new local high/low in direction of trend)
    if allow_trend_breakout_entries:
        try:
            lookback = int(config.get("trend_breakout_lookback_bars", 5) or 5)
            lookback = max(1, lookback)
            if len(df) >= lookback + 1:
                prev_slice = df.iloc[-(lookback + 1) : -1]  # exclude current bar
                prev_high = float(prev_slice["high"].max())
                prev_low = float(prev_slice["low"].min())
                trend_breakout_long = bool(ema_bull_trend and price_above_vwap and close > prev_high)
                trend_breakout_short = bool(ema_bear_trend and price_below_vwap and close < prev_low)
        except Exception as e:
            logger.debug(f"Trend breakout check failed: {e}")
            trend_breakout_long, trend_breakout_short = False, False

    # Trend momentum (strong candle in direction of trend)
    if allow_trend_momentum_entries:
        try:
            mult = float(config.get("trend_momentum_atr_mult", 0.5) or 0.5)
            mult = max(0.0, mult)
            move = close - prev_close
            trend_momentum_long = bool(ema_bull_trend and price_above_vwap and move >= float(atr) * mult)
            trend_momentum_short = bool(ema_bear_trend and price_below_vwap and (-move) >= float(atr) * mult)
        except Exception as e:
            logger.debug(f"Trend momentum check failed: {e}")
            trend_momentum_long, trend_momentum_short = False, False
    
    # 3. Volume confirmation (core - required)
    volume_confirmed = check_volume_confirmation(df, config)
    
    # 4. S&R Power Channel (extended - conditional on data availability)
    sr_signal, sr_confidence = None, 0.0
    sr_length = config.get("sr_length", 130)
    if len(df) >= sr_length:
        try:
            sr_signal, sr_confidence = check_sr_signals(df, config)
        except Exception as e:
            logger.debug(f"S&R signals check failed (optional): {e}")

    # 5. TBT Trendlines (extended - conditional on data availability)
    tbt_signal, tbt_confidence = None, 0.0
    tbt_period = config.get("tbt_period", 10)
    if len(df) >= tbt_period * 2:
        try:
            tbt_signal, tbt_confidence = check_tbt_signals(df, config)
        except Exception as e:
            logger.debug(f"TBT signals check failed (optional): {e}")

    # 6. Supply & Demand (extended - conditional, needs ~100 bars ideally)
    sd_signal, sd_confidence = None, 0.0
    if len(df) >= 20:
        try:
            sd_signal, sd_confidence = check_supply_demand_signals(df, config)
        except Exception as e:
            logger.debug(f"Supply/Demand signals check failed (optional): {e}")
    
    # 7. SpacemanBTC Key Levels (extended - conditional)
    # These are CRITICAL for reversal/breakout detection
    key_levels = {}
    key_level_signal = None
    key_level_conf_adj = 0.0
    key_level_info = {}
    if len(df) >= 5:
        try:
            key_levels = get_key_levels(df) or {}
            # Check for bounce/breakout signals at key levels
            key_level_signal, key_level_conf_adj, key_level_info = check_key_level_signals(
                df, key_levels, config
            )
        except Exception:
            pass  # Key levels are optional enhancement
    
    # 8. VWAP bands (for extension/reversion detection)
    vwap_band_signal = None
    try:
        vwap, upper_bands, lower_bands = calculate_vwap_bands(
            df, 
            std_dev=config.get("vwap_std_dev", 1.0),
            bands=config.get("vwap_bands", 2),
            vwap_series=vwap_series,
        )
        vwap_val = vwap.iloc[-1]
        # Check if price is extended beyond outer band
        if upper_bands and lower_bands:
            outer_upper = upper_bands[-1].iloc[-1] if len(upper_bands) > 0 else None
            outer_lower = lower_bands[-1].iloc[-1] if len(lower_bands) > 0 else None
            if outer_upper is not None and close > outer_upper:
                vwap_band_signal = "extended_above"
            elif outer_lower is not None and close < outer_lower:
                vwap_band_signal = "extended_below"
            # Check for mean reversion opportunity (near inner band)
            elif len(upper_bands) > 0 and len(lower_bands) > 0:
                inner_upper = upper_bands[0].iloc[-1]
                inner_lower = lower_bands[0].iloc[-1]
                if close > vwap_val and close <= inner_upper:
                    vwap_band_signal = "near_vwap_above"
                elif close < vwap_val and close >= inner_lower:
                    vwap_band_signal = "near_vwap_below"
    except Exception:
        pass  # VWAP bands optional - continue without
    
    # ==========================================================================
    # MARKET REGIME DETECTION
    # Adjusts confidence and filters signals based on market conditions
    # ==========================================================================
    market_regime = detect_market_regime(df, lookback=50)
    regime_multiplier = 1.0
    
    # Skip signals in unfavorable regimes (configurable)
    skip_in_ranging = config.get("skip_signals_in_ranging", False)
    skip_in_volatile = config.get("skip_signals_in_volatile", False)
    
    if skip_in_ranging and market_regime.regime == "ranging" and market_regime.confidence > 0.7:
        logger.debug(f"Skipping signals: strong ranging market (confidence={market_regime.confidence:.2f})")
        return signals
    
    if skip_in_volatile and market_regime.regime == "volatile" and market_regime.volatility_ratio > 2.5:
        logger.debug(f"Skipping signals: extreme volatility (ratio={market_regime.volatility_ratio:.2f})")
        return signals
    
    # Adjust confidence based on regime
    if market_regime.recommendation == "full_size":
        regime_multiplier = 1.0
    elif market_regime.recommendation == "reduced_size":
        regime_multiplier = 0.7  # Reduce confidence by 30%
    else:  # "avoid"
        regime_multiplier = 0.5  # Reduce confidence by 50%
    
    # Set dynamic SL/TP multipliers based on regime
    base_sl_mult = float(config.get("stop_loss_atr_mult", 3.5))
    base_tp_mult = float(config.get("take_profit_atr_mult", 5.0))
    
    if market_regime.regime == "volatile":
        # Wider stops in volatile markets to avoid wicks
        dynamic_sl_mult = base_sl_mult * 1.2
        dynamic_tp_mult = base_tp_mult * 1.2
    elif market_regime.regime == "ranging":
        # Tighter targets in ranging markets
        dynamic_sl_mult = base_sl_mult * 0.9
        dynamic_tp_mult = base_tp_mult * 0.8
    else:
        dynamic_sl_mult = base_sl_mult
        dynamic_tp_mult = base_tp_mult
    
    # Combine signals with confidence scoring
    signal_candidates = []
    
    # Long signals - ALL 8 INDICATORS CONTRIBUTE
    long_trigger = (
        bullish_cross
        or (allow_vwap_cross_entries and bullish_vwap_cross and ema_bull_trend)
        or (allow_vwap_retest_entries and vwap_retest_long)
        or (allow_trend_momentum_entries and trend_momentum_long)
        or (allow_trend_breakout_entries and trend_breakout_long)
    )
    if long_trigger and price_above_vwap:
        # Base confidence: EMA/VWAP trigger + VWAP position = 0.5
        confidence = 0.50
        if bullish_cross:
            entry_trigger = "ema_cross"
            active_indicators = ["EMA_CROSS", "VWAP_ABOVE"]
        elif bullish_vwap_cross:
            entry_trigger = "vwap_cross"
            active_indicators = ["EMA_TREND", "VWAP_CROSS_UP", "VWAP_ABOVE"]
        elif vwap_retest_long:
            entry_trigger = "vwap_retest"
            active_indicators = ["EMA_TREND", "VWAP_RETEST_UP", "VWAP_ABOVE"]
        elif trend_breakout_long:
            entry_trigger = "trend_breakout"
            active_indicators = ["EMA_TREND", "TREND_BREAKOUT", "VWAP_ABOVE"]
        else:
            entry_trigger = "trend_momentum"
            active_indicators = ["EMA_TREND", "TREND_MOMENTUM", "VWAP_ABOVE"]
        
        # (3) Volume confirmation - additive
        if volume_confirmed:
            confidence += 0.12
            active_indicators.append("VOL_CONFIRM")
        
        # (4) S&R Power Channel - additive for alignment
        if sr_signal and "long" in sr_signal:
            confidence += 0.08 + (sr_confidence * 0.05)  # Base + scaled
            active_indicators.append(f"SR:{sr_signal}")
        
        # (5) TBT Trendlines - additive for breakouts
        if tbt_signal and "long" in tbt_signal:
            confidence += 0.08 + (tbt_confidence * 0.05)
            active_indicators.append(f"TBT:{tbt_signal}")
        
        # (6) Supply & Demand zones - additive
        if sd_signal and "demand" in sd_signal:
            confidence += 0.10  # Strong boost for demand zone entry
            active_indicators.append(f"SD:{sd_signal}")
        
        # (7) VWAP band adjustments
        if vwap_band_signal == "extended_above":
            confidence -= 0.08  # CAUTION: Overly extended, reduce confidence
            active_indicators.append("VWAP_EXTENDED_CAUTION")
        elif vwap_band_signal == "near_vwap_above":
            confidence += 0.05  # Good: Near VWAP, room to run
            active_indicators.append("VWAP_NEAR")
        
        # =====================================================================
        # (8) SPACEMAN KEY LEVEL ADJUSTMENTS FOR LONGS (CRITICAL)
        # Key levels are where reversals and breakouts happen - HIGHEST IMPACT
        # =====================================================================
        if key_level_signal:
            if key_level_signal == "bounce_support_long":
                # STRONG: Bouncing off support level - high probability reversal
                confidence += key_level_conf_adj + 0.05  # Extra boost for bounces
                active_indicators.append(f"KEY_BOUNCE:{key_level_info.get('nearest_support_name', 'support')}")
            elif key_level_signal == "breakout_resistance_long":
                # STRONG: Breaking above resistance - continuation signal
                confidence += key_level_conf_adj + 0.03
                active_indicators.append(f"KEY_BREAKOUT:{key_level_info.get('nearest_resistance_name', 'resistance')}")
            elif key_level_signal == "near_resistance_caution":
                # CAUTION: Approaching resistance - reduce confidence for longs
                confidence += key_level_conf_adj  # This is negative
                active_indicators.append("CAUTION_RESIST")
        
        # Additional key level proximity checks using enhanced levels
        if key_levels:
            # Check support levels (PDL, PWL, PML are major support)
            prev_day_low = key_levels.get("prev_day_low")
            prev_week_low = key_levels.get("prev_week_low")

            # Big boost if bouncing off previous day low (PDL)
            if prev_day_low and close > prev_day_low:
                distance_pct = _safe_pct(close - prev_day_low, prev_day_low, default=100.0)
                if distance_pct < 0.3:  # Very close to PDL
                    confidence += 0.10
                    active_indicators.append("PDL_BOUNCE")

            # Big boost if bouncing off previous week low (PWL)
            if prev_week_low and close > prev_week_low:
                distance_pct = _safe_pct(close - prev_week_low, prev_week_low, default=100.0)
                if distance_pct < 0.5:  # Close to PWL
                    confidence += 0.12
                    active_indicators.append("PWL_BOUNCE")

            # Check resistance levels (PDH, PWH, PMH are major resistance)
            prev_day_high = key_levels.get("prev_day_high")
            prev_week_high = key_levels.get("prev_week_high")

            # Reduce confidence if entering into nearby resistance
            if prev_day_high and close < prev_day_high:
                distance_pct = _safe_pct(prev_day_high - close, close, default=100.0)
                if distance_pct < 0.3:  # Very close to PDH
                    confidence -= 0.05
                    active_indicators.append("PDH_CAUTION")

            if prev_week_high and close < prev_week_high:
                distance_pct = _safe_pct(prev_week_high - close, close, default=100.0)
                if distance_pct < 0.5:  # Close to PWH
                    confidence -= 0.07
                    active_indicators.append("PWH_CAUTION")
        
        if confidence >= config["min_confidence"]:
            entry_price = close
            # Use dynamic regime-adaptive parameters
            sl_mult = dynamic_sl_mult
            tp_mult = dynamic_tp_mult
            stop_loss = entry_price - (atr * sl_mult)
            take_profit = entry_price + (atr * tp_mult)
            
            # NaN guards: ensure valid SL/TP before calculating R:R
            risk_amount = entry_price - stop_loss
            if pd.isna(stop_loss) or pd.isna(take_profit) or stop_loss >= entry_price or risk_amount <= 0:
                pass  # Skip invalid signal
            else:
                risk_reward = _safe_div(take_profit - entry_price, risk_amount, default=0.0)
                
                if risk_reward >= config["min_risk_reward"] and not pd.isna(risk_reward):
                    # Use active_indicators for comprehensive reason
                    signal_candidates.append({
                        "direction": "long",
                        "entry_price": float(entry_price),
                        "stop_loss": float(stop_loss),
                        "take_profit": float(take_profit),
                        "confidence": float(min(confidence, 0.99)),  # Cap at 0.99
                        "risk_reward": float(risk_reward),
                        "reason": f"LONG[{len(active_indicators)}]: " + " | ".join(active_indicators),
                        "indicators": {
                            "active_count": len(active_indicators),
                            "active_list": active_indicators,
                            "ema_cross": bool(bullish_cross),
                            "entry_trigger": str(entry_trigger),
                            "vwap_position": "above",
                            "vwap_band_signal": vwap_band_signal,
                            "volume_confirmed": volume_confirmed,
                            "sr_signal": sr_signal,
                            "tbt_signal": tbt_signal,
                            "sd_signal": sd_signal,
                            "key_level_signal": key_level_signal,
                            "key_level_info": key_level_info,
                            "key_levels": key_levels,
                        },
                    })
    
    # Short signals - ALL 8 INDICATORS CONTRIBUTE
    short_trigger = (
        bearish_cross
        or (allow_vwap_cross_entries and bearish_vwap_cross and ema_bear_trend)
        or (allow_vwap_retest_entries and vwap_retest_short)
        or (allow_trend_momentum_entries and trend_momentum_short)
        or (allow_trend_breakout_entries and trend_breakout_short)
    )
    if short_trigger and price_below_vwap:
        # Base confidence: EMA/VWAP trigger + VWAP position (2) = 0.5
        confidence = 0.50
        if bearish_cross:
            entry_trigger = "ema_cross"
            active_indicators = ["EMA_CROSS", "VWAP_BELOW"]
        elif bearish_vwap_cross:
            entry_trigger = "vwap_cross"
            active_indicators = ["EMA_TREND", "VWAP_CROSS_DOWN", "VWAP_BELOW"]
        elif vwap_retest_short:
            entry_trigger = "vwap_retest"
            active_indicators = ["EMA_TREND", "VWAP_RETEST_DOWN", "VWAP_BELOW"]
        elif trend_breakout_short:
            entry_trigger = "trend_breakout"
            active_indicators = ["EMA_TREND", "TREND_BREAKOUT", "VWAP_BELOW"]
        else:
            entry_trigger = "trend_momentum"
            active_indicators = ["EMA_TREND", "TREND_MOMENTUM", "VWAP_BELOW"]
        
        # (3) Volume confirmation - additive
        if volume_confirmed:
            confidence += 0.12
            active_indicators.append("VOL_CONFIRM")
        
        # (4) S&R Power Channel - additive for alignment
        if sr_signal and "short" in sr_signal:
            confidence += 0.08 + (sr_confidence * 0.05)
            active_indicators.append(f"SR:{sr_signal}")
        
        # (5) TBT Trendlines - additive for breakdowns
        if tbt_signal and "short" in tbt_signal:
            confidence += 0.08 + (tbt_confidence * 0.05)
            active_indicators.append(f"TBT:{tbt_signal}")
        
        # (6) Supply & Demand zones - additive
        if sd_signal and "supply" in sd_signal:
            confidence += 0.10  # Strong boost for supply zone entry
            active_indicators.append(f"SD:{sd_signal}")
        
        # (7) VWAP band adjustments for shorts
        if vwap_band_signal == "extended_below":
            confidence -= 0.08  # CAUTION: Overly extended, reduce confidence
            active_indicators.append("VWAP_EXTENDED_CAUTION")
        elif vwap_band_signal == "near_vwap_below":
            confidence += 0.05  # Good: Near VWAP, room to run
            active_indicators.append("VWAP_NEAR")
        
        # =====================================================================
        # (8) SPACEMAN KEY LEVEL ADJUSTMENTS FOR SHORTS (CRITICAL)
        # Key levels are where reversals and breakouts happen - HIGHEST IMPACT
        # =====================================================================
        if key_level_signal:
            if key_level_signal == "bounce_resistance_short":
                # STRONG: Bouncing off resistance level - high probability reversal
                confidence += key_level_conf_adj + 0.05  # Extra boost for bounces
                active_indicators.append(f"KEY_BOUNCE:{key_level_info.get('nearest_resistance_name', 'resistance')}")
            elif key_level_signal == "breakout_support_short":
                # STRONG: Breaking below support - continuation signal
                confidence += key_level_conf_adj + 0.03
                active_indicators.append(f"KEY_BREAKOUT:{key_level_info.get('nearest_support_name', 'support')}")
            elif key_level_signal == "near_support_caution":
                # CAUTION: Approaching support - reduce confidence for shorts
                confidence += key_level_conf_adj  # This is negative
                active_indicators.append("CAUTION_SUPPORT")
        
        # Additional key level proximity checks using enhanced levels
        if key_levels:
            # Check resistance levels (PDH, PWH, PMH are major resistance)
            prev_day_high = key_levels.get("prev_day_high")
            prev_week_high = key_levels.get("prev_week_high")

            # Big boost if bouncing off previous day high (PDH)
            if prev_day_high and close < prev_day_high:
                distance_pct = _safe_pct(prev_day_high - close, prev_day_high, default=100.0)
                if distance_pct < 0.3:  # Very close to PDH
                    confidence += 0.10
                    active_indicators.append("PDH_BOUNCE")

            # Big boost if bouncing off previous week high (PWH)
            if prev_week_high and close < prev_week_high:
                distance_pct = _safe_pct(prev_week_high - close, prev_week_high, default=100.0)
                if distance_pct < 0.5:  # Close to PWH
                    confidence += 0.12
                    active_indicators.append("PWH_BOUNCE")

            # Check support levels (PDL, PWL are major support)
            prev_day_low = key_levels.get("prev_day_low")
            prev_week_low = key_levels.get("prev_week_low")

            # Reduce confidence if entering into nearby support
            if prev_day_low and close > prev_day_low:
                distance_pct = _safe_pct(close - prev_day_low, close, default=100.0)
                if distance_pct < 0.3:  # Very close to PDL
                    confidence -= 0.05
                    active_indicators.append("PDL_CAUTION")

            if prev_week_low and close > prev_week_low:
                distance_pct = _safe_pct(close - prev_week_low, close, default=100.0)
                if distance_pct < 0.5:  # Close to PWL
                    confidence -= 0.07
                    active_indicators.append("PWL_CAUTION")
        
        if confidence >= config["min_confidence"]:
            entry_price = close
            # Use dynamic regime-adaptive parameters
            sl_mult = dynamic_sl_mult
            tp_mult = dynamic_tp_mult
            stop_loss = entry_price + (atr * sl_mult)
            take_profit = entry_price - (atr * tp_mult)
            
            # NaN guards: ensure valid SL/TP before calculating R:R
            risk_amount = stop_loss - entry_price
            if pd.isna(stop_loss) or pd.isna(take_profit) or stop_loss <= entry_price or risk_amount <= 0:
                pass  # Skip invalid signal
            else:
                risk_reward = _safe_div(entry_price - take_profit, risk_amount, default=0.0)
                
                if risk_reward >= config["min_risk_reward"] and not pd.isna(risk_reward):
                    # Use active_indicators for comprehensive reason
                    signal_candidates.append({
                        "direction": "short",
                        "entry_price": float(entry_price),
                        "stop_loss": float(stop_loss),
                        "take_profit": float(take_profit),
                        "confidence": float(min(confidence, 0.99)),  # Cap at 0.99
                        "risk_reward": float(risk_reward),
                        "reason": f"SHORT[{len(active_indicators)}]: " + " | ".join(active_indicators),
                        "indicators": {
                            "active_count": len(active_indicators),
                            "active_list": active_indicators,
                            "ema_cross": bool(bearish_cross),
                            "entry_trigger": str(entry_trigger),
                            "vwap_position": "below",
                            "vwap_band_signal": vwap_band_signal,
                            "volume_confirmed": volume_confirmed,
                            "sr_signal": sr_signal,
                            "tbt_signal": tbt_signal,
                            "sd_signal": sd_signal,
                            "key_level_signal": key_level_signal,
                            "key_level_info": key_level_info,
                            "key_levels": key_levels,
                        },
                    })
    
    # Add metadata to signals including regime information
    for signal in signal_candidates:
        signal["timestamp"] = current_time.isoformat()
        signal["symbol"] = config["symbol"]
        signal["timeframe"] = config["timeframe"]
        signal["type"] = "pearlbot_pinescript"
        signal["virtual_broker"] = True  # Mark as virtual - no real execution
        
        # Apply regime-based confidence adjustment
        original_confidence = signal.get("confidence", 0.5)
        adjusted_confidence = original_confidence * regime_multiplier
        signal["confidence"] = float(min(adjusted_confidence, 0.99))
        
        # Add regime information for transparency
        signal["market_regime"] = market_regime.to_dict()
        signal["regime_adjustment"] = {
            "original_confidence": original_confidence,
            "multiplier": regime_multiplier,
            "adjusted_confidence": signal["confidence"],
        }
    
    # ==========================================================================
    # POST-REGIME CONFIDENCE FILTER
    # Signals that passed the initial min_confidence check may have been reduced
    # below the threshold by the regime multiplier. Filter them out now.
    # ==========================================================================
    min_conf = config.get("min_confidence", 0.55)
    pre_filter_count = len(signal_candidates)
    signal_candidates = [
        s for s in signal_candidates 
        if s.get("confidence", 0) >= min_conf
    ]
    
    if len(signal_candidates) < pre_filter_count:
        filtered_count = pre_filter_count - len(signal_candidates)
        logger.debug(
            f"Post-regime confidence filter removed {filtered_count} signal(s) "
            f"that fell below {min_conf:.0%} after regime adjustment"
        )
    
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
