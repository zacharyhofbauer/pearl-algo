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

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pearlalgo.config.config_view import ConfigView
from datetime import datetime, timezone
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
    "key_level_bounce_confidence": 0.15,  # Confidence boost for bounce/rejection signals
    "key_level_breakout_confidence": 0.10,  # Confidence boost for breakout signals
    "key_level_rejection_penalty": 0.08,  # Confidence penalty for entering into resistance/support
    
    # Risk Management - Scalp-appropriate ATR-based stops
    "stop_loss_atr_mult": 1.0,      # 1.0x ATR (~15-25 pts on 5m MNQ)
    "take_profit_atr_mult": 2.0,    # 2.0x ATR (~30-50 pts) for 1:2 R:R
    "min_confidence": 0.55,         # Allow trades with strong confluence
    "min_risk_reward": 1.3,         # Minimum R:R filter

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
    except Exception as e:
        logger.debug(f"Cache key generation failed: {e}")
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
    """Safely calculate percentage: (numerator / denominator) * 100."""
    result = _safe_div(numerator, denominator, default)
    return result * 100 if result != default else default


# ============================================================================
# SAFE CHECK WRAPPER + INDICATOR CONTEXT
# ============================================================================

# Indicator health tracking — incremented by safe_check on failure
_indicator_failures: Dict[str, int] = {}
_indicator_successes: Dict[str, int] = {}


def get_indicator_health() -> Dict[str, Any]:
    """Return indicator failure/success counts for observability (exposed via /api/state)."""
    return {
        "failures": dict(_indicator_failures),
        "successes": dict(_indicator_successes),
        "total_failures": sum(_indicator_failures.values()),
        "total_successes": sum(_indicator_successes.values()),
    }


def safe_check(fn, *args, **kwargs) -> Tuple[Optional[str], float]:
    """Run a signal check function, catching exceptions gracefully.

    Returns (None, 0.0) on failure so callers never crash from optional checks.

    **Error handling convention:** failures are logged at WARNING level so that
    indicator calculation errors are visible in logs and monitoring.  A silent
    failure here could mean a missed (or incorrect) trading signal, so
    visibility is critical.  Use ``ErrorHandler`` for non-strategy modules.
    """
    try:
        result = fn(*args, **kwargs)
        _indicator_successes[fn.__name__] = _indicator_successes.get(fn.__name__, 0) + 1
        return result
    except Exception as e:
        _indicator_failures[fn.__name__] = _indicator_failures.get(fn.__name__, 0) + 1
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
    adx_value: float = 0.0  # Actual ADX(14) value for strategy routing

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "confidence": self.confidence,
            "trend_strength": self.trend_strength,
            "volatility_ratio": self.volatility_ratio,
            "recommendation": self.recommendation,
            "adx_value": self.adx_value,
        }


def detect_market_regime(
    df: pd.DataFrame,
    lookback: int = 50,
    trend_threshold: float = 0.6,
    volatility_window: int = 20,
    adx_period: int = 14,
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

    # ADX for true trend strength measurement
    adx_value = calculate_adx(df, period=adx_period)

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
        adx_value=adx_value,
    )


# ============================================================================
# INDICATOR FUNCTIONS (All inline, no classes)
# ============================================================================


def calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate Average Directional Index (ADX).

    Returns the current ADX value (0-100).  Higher values indicate stronger
    trend regardless of direction.  Returns 0.0 if insufficient data.
    """
    if len(df) < period + 1:
        return 0.0
    try:
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        plus_dm = np.zeros(len(df))
        minus_dm = np.zeros(len(df))
        tr = np.zeros(len(df))

        for i in range(1, len(df)):
            up_move = high[i] - high[i - 1]
            down_move = low[i - 1] - low[i]
            plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        # Wilder smoothing (exponential with alpha = 1/period)
        alpha = 1.0 / period
        atr_s = np.zeros(len(df))
        plus_di_s = np.zeros(len(df))
        minus_di_s = np.zeros(len(df))

        # Seed with SMA of first `period` values
        atr_s[period] = np.mean(tr[1 : period + 1])
        plus_di_s[period] = np.mean(plus_dm[1 : period + 1])
        minus_di_s[period] = np.mean(minus_dm[1 : period + 1])

        for i in range(period + 1, len(df)):
            atr_s[i] = atr_s[i - 1] * (1 - alpha) + tr[i] * alpha
            plus_di_s[i] = plus_di_s[i - 1] * (1 - alpha) + plus_dm[i] * alpha
            minus_di_s[i] = minus_di_s[i - 1] * (1 - alpha) + minus_dm[i] * alpha

        # DX series
        dx = np.zeros(len(df))
        for i in range(period, len(df)):
            if atr_s[i] > 0:
                pdi = 100.0 * plus_di_s[i] / atr_s[i]
                mdi = 100.0 * minus_di_s[i] / atr_s[i]
                di_sum = pdi + mdi
                dx[i] = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0

        # ADX = Wilder-smoothed DX
        adx = np.zeros(len(df))
        start = 2 * period
        if start < len(df):
            adx[start] = np.mean(dx[period : start + 1]) if start >= period else 0.0
            for i in range(start + 1, len(df)):
                adx[i] = adx[i - 1] * (1 - alpha) + dx[i] * alpha

        return float(adx[-1])
    except Exception as e:
        logger.debug(f"ADX calculation failed: {e}")
        return 0.0


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
    # FAILED RETEST DETECTION (Zach's highest conviction short setup)
    # Price breaks below a key level, retests from below, fails to reclaim = SHORT
    # =========================================================================
    if nearest_resistance is not None and len(df) >= 5:
        # Check if current resistance was recently support (broken level)
        # Pattern: prev bars were ABOVE this level, then broke below, now retesting
        recent_closes = df["close"].iloc[-5:-1].values
        prev_above = any(c > nearest_resistance for c in recent_closes[:2])  # was above in last 2-4 bars
        recent_below = all(c < nearest_resistance for c in recent_closes[2:])  # then broke below
        current_retest = _safe_div(abs(current_close - nearest_resistance), current_close) <= proximity_pct
        
        if prev_above and recent_below and current_retest and current_close < prev_close:
            # Failed retest confirmed - price came back to broken level and rejected
            level_info["level_interaction"] = f"failed_retest:{nearest_resistance_name}"
            return "bounce_resistance_short", bounce_conf, level_info

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
    Return whether the current time is within the configured trading session.

    Session window is defined by session.start_time / session.end_time in ET.
    Supports overnight sessions (e.g. 18:00 start, 16:00 end = Sun-Fri futures).
    """
    import zoneinfo

    try:
        # Respect enforce_session_window flag (False = always allow)
        strategy = config.get("strategy") or {}
        if strategy.get("enforce_session_window") is False:
            return True

        session = config.get("session") or {}
        start_str = str(session.get("start_time", "18:00") or "18:00")
        end_str = str(session.get("end_time", "16:00") or "16:00")
        tz_name = str(session.get("timezone", "America/New_York") or "America/New_York")
    except Exception:
        return True  # If config is unparseable, allow trading

    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = zoneinfo.ZoneInfo("America/New_York")

    try:
        # Convert dt to session timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
        local = dt.astimezone(tz)
        now_minutes = local.hour * 60 + local.minute

        sh, sm = (int(x) for x in start_str.split(":"))
        eh, em = (int(x) for x in end_str.split(":"))
        start_minutes = sh * 60 + sm
        end_minutes = eh * 60 + em
    except Exception:
        return True  # If parsing fails, allow trading

    if start_minutes < end_minutes:
        # Same-day session (e.g. 09:30 - 16:00)
        return start_minutes <= now_minutes < end_minutes
    else:
        # Overnight session (e.g. 18:00 - 16:00)
        return now_minutes >= start_minutes or now_minutes < end_minutes


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
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.debug("detect_vwap_cross fallback: %s", exc)
        return False, False

    # NaN guards
    if any(pd.isna(x) for x in (close_prev, close_curr, vwap_prev, vwap_curr)):
        return False, False

    bullish = close_prev <= vwap_prev and close_curr > vwap_curr
    bearish = close_prev >= vwap_prev and close_curr < vwap_curr
    return bool(bullish), bool(bearish)


def check_volume_confirmation(df: pd.DataFrame, config: Dict) -> bool:
    """Check volume confirmation - from Volume.pine"""
    if len(df) < config.get("volume_ma_length", 20):
        return False
    
    vol_ma = calculate_volume_ma(df, config.get("volume_ma_length", 20))
    current_vol = df["volume"].iloc[-1]
    avg_vol = vol_ma.iloc[-1]
    
    return current_vol > avg_vol


def check_sr_signals(df: pd.DataFrame, config: Dict) -> Tuple[Optional[str], float]:
    """
    Check S&R Power Channel signals - from S&R Power.pine
    
    Returns: (signal_type, confidence)
    """
    resistance, support, buy_power, sell_power = calculate_sr_power_channel(
        df, config.get("sr_length", 130), config.get("sr_atr_mult", 0.5)
    )
    
    if resistance == 0 or support == 0:
        return None, 0.0
    
    close = df["close"].iloc[-1]
    
    # Breakout above resistance
    if close > resistance:
        confidence = min(buy_power / config.get("sr_length", 130), 1.0)
        return "sr_breakout_long", confidence
    
    # Breakout below support
    if close < support:
        confidence = min(sell_power / config.get("sr_length", 130), 1.0)
        return "sr_breakout_short", confidence
    
    # Pullback to support in uptrend
    if support < close < (support + resistance) / 2 and buy_power > sell_power:
        confidence = min(buy_power / config.get("sr_length", 130) * 0.8, 1.0)
        return "sr_pullback_long", confidence
    
    # Pullback to resistance in downtrend
    if (support + resistance) / 2 < close < resistance and sell_power > buy_power:
        confidence = min(sell_power / config.get("sr_length", 130) * 0.8, 1.0)
        return "sr_pullback_short", confidence
    
    return None, 0.0


def check_tbt_signals(df: pd.DataFrame, config: Dict) -> Tuple[Optional[str], float]:
    """
    Check TBT Trendline Breakout signals - from TBT.pine
    
    Returns: (signal_type, confidence)
    """
    res_slope, res_start, sup_slope, sup_start = calculate_tbt_trendlines(
        df, config.get("tbt_period", 10), config.get("tbt_trend_type", "wicks")
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
        df, config.get("sd_threshold_pct", 10.0), config.get("sd_resolution", 50)
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
    stop_loss_atr_mult: float = _Field(default=1.0, ge=0.3, description="SL ATR multiplier")
    take_profit_atr_mult: float = _Field(default=2.0, ge=0.5, description="TP ATR multiplier")
    volatile_sl_mult: float = _Field(default=1.3, description="SL multiplier in volatile regime")
    volatile_tp_mult: float = _Field(default=1.3, description="TP multiplier in volatile regime")
    ranging_sl_mult: float = _Field(default=0.8, description="SL multiplier in ranging regime")
    ranging_tp_mult: float = _Field(default=0.7, description="TP multiplier in ranging regime")

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
    min_confidence_long: float = _Field(default=0.72, ge=0.0, le=1.0)
    min_confidence_short: float = _Field(default=0.60, ge=0.0, le=1.0)
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

    # -- ADX regime enhancement ------------------------------------------
    adx_period: int = _Field(default=14, ge=5, description="ADX lookback period")
    adx_trending_threshold: float = _Field(default=25.0, description="ADX above this = trending")
    adx_ranging_threshold: float = _Field(default=20.0, description="ADX below this = ranging")

    # -- ORB (Opening Range Breakout) ------------------------------------
    allow_orb_entries: bool = False  # Disabled by default
    orb_range_minutes: int = _Field(default=15, ge=5, description="Minutes to build opening range")
    orb_window_end: str = _Field(default="11:00", description="Latest time for ORB entries (ET)")
    orb_max_trades_per_day: int = _Field(default=1, ge=1, description="Max ORB trades per session")
    orb_base_confidence: float = _Field(default=0.60, ge=0.0, le=1.0)
    orb_vwap_boost: float = _Field(default=0.10, description="Boost if VWAP-aligned")
    orb_volume_boost: float = _Field(default=0.08, description="Boost if volume confirmed")
    orb_adx_boost: float = _Field(default=0.05, description="Boost if ADX > trending threshold")
    orb_sl_atr_mult: float = _Field(default=1.0, description="SL ATR mult (or ORB range, whichever wider)")
    orb_tp_atr_mult: float = _Field(default=2.0, description="TP ATR mult")

    # -- VWAP 2SD Mean Reversion -----------------------------------------
    allow_vwap_2sd_entries: bool = False  # Disabled by default
    vwap_2sd_multiplier: float = _Field(default=2.0, ge=1.0, description="SD multiplier for outer bands")
    vwap_2sd_rsi_long_threshold: float = _Field(default=35.0, description="RSI below = oversold for long")
    vwap_2sd_rsi_short_threshold: float = _Field(default=65.0, description="RSI above = overbought for short")
    vwap_2sd_window_start: str = _Field(default="10:00", description="Earliest time for 2SD entries (ET)")
    vwap_2sd_window_end: str = _Field(default="15:00", description="Latest time for 2SD entries (ET)")
    vwap_2sd_base_confidence: float = _Field(default=0.55, ge=0.0, le=1.0)
    vwap_2sd_rsi_extreme_boost: float = _Field(default=0.12, description="Boost for RSI < 30 or > 70")
    vwap_2sd_volume_boost: float = _Field(default=0.08, description="Boost for volume spike")
    vwap_2sd_sl_atr_mult: float = _Field(default=0.75, description="SL ATR mult beyond the band")
    vwap_2sd_volume_spike_mult: float = _Field(default=1.5, description="Volume > N × avg = spike")

    # -- SMC (Smart Money Concepts) ----------------------------------------
    allow_smc_entries: bool = False  # Disabled by default
    smc_swing_length: int = _Field(default=10, ge=3, description="Swing high/low lookback for SMC")
    smc_fvg_lookback: int = _Field(default=20, ge=5, description="Bars back to search for active FVGs")
    smc_ob_lookback: int = _Field(default=20, ge=5, description="Bars back to search for order blocks")
    smc_fvg_base_confidence: float = _Field(default=0.55, ge=0.0, le=1.0)
    smc_ob_boost: float = _Field(default=0.10, description="Confidence boost for OB confluence")
    smc_bos_boost: float = _Field(default=0.08, description="Confidence boost for BOS/CHoCH")
    smc_volume_boost: float = _Field(default=0.08, description="Confidence boost for volume confirmation")
    smc_key_level_boost: float = _Field(default=0.10, description="Confidence boost for key level alignment")
    smc_vwap_boost: float = _Field(default=0.05, description="Confidence boost for VWAP alignment")
    smc_sl_atr_mult: float = _Field(default=0.8, description="SL ATR mult beyond FVG boundary")
    smc_tp_atr_mult: float = _Field(default=2.5, description="TP ATR mult (fallback when no liquidity target)")
    smc_silver_bullet_windows: list = _Field(default_factory=lambda: [[10, 11], [14, 15], [15, 16]],
                                              description="Silver Bullet time windows [[start_h, end_h], ...] ET")


def _load_strategy_params(config: Dict) -> StrategyParams:
    """Build a :class:`StrategyParams` from a config dict.

    Keys present in *config* override the Pydantic defaults; unknown keys
    are silently ignored (``extra="ignore"``).
    """
    # Collect values from the config dict that match StrategyParams fields
    overrides: Dict[str, Any] = {}
    strategy_cfg = config.get("strategy", {}) if hasattr(config, "get") else {}
    strategies_cfg = config.get("strategies", {}) if hasattr(config, "get") else {}
    active_strategy = "composite_intraday"
    if isinstance(strategy_cfg, dict):
        active_strategy = str(strategy_cfg.get("active", active_strategy) or active_strategy)
    nested_params: Dict[str, Any] = {}
    if isinstance(strategies_cfg, dict):
        raw_nested = strategies_cfg.get(active_strategy, {}) or {}
        if isinstance(raw_nested, dict):
            nested_params = raw_nested
    for field_name in StrategyParams.model_fields:
        if field_name in config:
            overrides[field_name] = config[field_name]
        elif field_name in nested_params:
            overrides[field_name] = nested_params[field_name]
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
    key_level_info: Dict
    vwap_band_signal: Optional[str]
    regime: "MarketRegime"
    adx_value: float  # ADX(14) for strategy routing
    # Aggressive triggers (only populated when config enables them)
    vwap_cross_signal: Optional[str]
    vwap_retest_signal: Optional[str]
    trend_breakout_signal: Optional[str]
    trend_momentum_signal: Optional[str]


@dataclass
class DirectionalTriggers:
    """Entry triggers for one direction."""

    ema_cross: bool = False
    vwap_cross: bool = False
    vwap_retest: bool = False
    trend_breakout: bool = False
    mean_reversion: bool = False
    ema_pullback: bool = False
    vwap_reclaim: bool = False
    trend_momentum: bool = False


@dataclass
class DirectionalScoreState:
    """Mutable confidence state while building a candidate signal."""

    confidence: float
    entry_trigger: str
    active_indicators: List[str]


@dataclass
class DirectionalConfidenceContext:
    """Inputs shared across directional confidence adjustments."""

    direction: str
    close: float
    atr: float
    volume_confirmed: bool
    sr_signal: Optional[str]
    sr_confidence: float
    tbt_signal: Optional[str]
    tbt_confidence: float
    sd_signal: Optional[str]
    key_levels: Dict[str, Optional[float]]
    key_level_signal: Optional[str]
    key_level_confidence: float
    key_level_info: Dict[str, Any]
    vwap_band_signal: Optional[str]
    or_state: Dict[str, Any]


def _initialize_directional_score(
    direction: str,
    triggers: DirectionalTriggers,
    params: StrategyParams,
) -> Optional[DirectionalScoreState]:
    """Choose the active entry trigger and base confidence for one direction."""

    if direction == "long":
        price_label = "VWAP_ABOVE"
        cross_label = "VWAP_CROSS_UP"
        retest_label = "VWAP_RETEST_UP"
        mean_reversion_label = "RSI_OVERSOLD"
    else:
        price_label = "VWAP_BELOW"
        cross_label = "VWAP_CROSS_DOWN"
        retest_label = "VWAP_RETEST_DOWN"
        mean_reversion_label = "RSI_OVERBOUGHT"

    if triggers.ema_cross:
        return DirectionalScoreState(
            confidence=params.base_confidence,
            entry_trigger="ema_cross",
            active_indicators=["EMA_CROSS", price_label],
        )
    if triggers.vwap_cross:
        return DirectionalScoreState(
            confidence=params.base_confidence,
            entry_trigger="vwap_cross",
            active_indicators=["EMA_TREND", cross_label, price_label],
        )
    if triggers.vwap_retest:
        return DirectionalScoreState(
            confidence=params.base_confidence,
            entry_trigger="vwap_retest",
            active_indicators=["EMA_TREND", retest_label, price_label],
        )
    if triggers.trend_breakout:
        return DirectionalScoreState(
            confidence=params.base_confidence,
            entry_trigger="trend_breakout",
            active_indicators=["EMA_TREND", "TREND_BREAKOUT", price_label],
        )
    if triggers.mean_reversion:
        return DirectionalScoreState(
            confidence=0.55,
            entry_trigger="mean_reversion",
            active_indicators=[mean_reversion_label, "VWAP_STRETCHED"],
        )
    if triggers.ema_pullback:
        return DirectionalScoreState(
            confidence=params.base_confidence,
            entry_trigger="ema_pullback",
            active_indicators=["EMA_TREND", "EMA_PULLBACK", price_label],
        )
    if triggers.vwap_reclaim:
        return DirectionalScoreState(
            confidence=0.55,
            entry_trigger="vwap_reclaim",
            active_indicators=["VWAP_RECLAIM", "VOL_CONFIRM"],
        )
    if triggers.trend_momentum:
        return DirectionalScoreState(
            confidence=params.base_confidence,
            entry_trigger="trend_momentum",
            active_indicators=["EMA_TREND", "TREND_MOMENTUM", price_label],
        )

    return None


def _apply_directional_confidence_adjustments(
    state: DirectionalScoreState,
    ctx: DirectionalConfidenceContext,
    params: StrategyParams,
) -> None:
    """Apply additive confidence adjustments for one directional setup."""

    direction = ctx.direction

    if ctx.volume_confirmed:
        state.confidence += params.volume_boost
        state.active_indicators.append("VOL_CONFIRM")

    if ctx.sr_signal and direction in ctx.sr_signal:
        state.confidence += params.sr_boost + (ctx.sr_confidence * 0.05)
        state.active_indicators.append(f"SR:{ctx.sr_signal}")

    if ctx.tbt_signal and direction in ctx.tbt_signal:
        state.confidence += params.tbt_boost + (ctx.tbt_confidence * 0.05)
        state.active_indicators.append(f"TBT:{ctx.tbt_signal}")

    if direction == "long":
        if ctx.sd_signal and "demand" in ctx.sd_signal:
            state.confidence += params.sd_boost
            state.active_indicators.append(f"SD:{ctx.sd_signal}")

        if ctx.vwap_band_signal == "extended_above":
            state.confidence += params.vwap_extended_penalty
            state.active_indicators.append("VWAP_EXTENDED_CAUTION")
        elif ctx.vwap_band_signal == "near_vwap_above":
            state.confidence += params.vwap_bounce_boost
            state.active_indicators.append("VWAP_NEAR")

        if ctx.key_level_signal == "bounce_support_long":
            state.confidence += ctx.key_level_confidence + 0.05
            state.active_indicators.append(
                f"KEY_BOUNCE:{ctx.key_level_info.get('nearest_support_name', 'support')}"
            )
        elif ctx.key_level_signal == "breakout_resistance_long":
            state.confidence += ctx.key_level_confidence + params.breakout_boost
            state.active_indicators.append(
                f"KEY_BREAKOUT:{ctx.key_level_info.get('nearest_resistance_name', 'resistance')}"
            )
        elif ctx.key_level_signal == "near_resistance_caution":
            state.confidence += ctx.key_level_confidence
            state.active_indicators.append("CAUTION_RESIST")

        prev_day_low = ctx.key_levels.get("prev_day_low")
        prev_week_low = ctx.key_levels.get("prev_week_low")
        prev_day_high = ctx.key_levels.get("prev_day_high")
        prev_week_high = ctx.key_levels.get("prev_week_high")

        if prev_day_low and ctx.close > prev_day_low:
            distance_pct = _safe_pct(ctx.close - prev_day_low, prev_day_low, default=100.0)
            if distance_pct < params.pdl_pdh_distance_pct:
                state.confidence += params.pdl_pdh_boost
                state.active_indicators.append("PDL_BOUNCE")

        if prev_week_low and ctx.close > prev_week_low:
            distance_pct = _safe_pct(ctx.close - prev_week_low, prev_week_low, default=100.0)
            if distance_pct < params.pwl_pwh_distance_pct:
                state.confidence += params.pwl_pwh_boost
                state.active_indicators.append("PWL_BOUNCE")

        if prev_day_high and ctx.close < prev_day_high:
            distance_pct = _safe_pct(prev_day_high - ctx.close, ctx.close, default=100.0)
            if distance_pct < params.pdl_pdh_distance_pct:
                state.confidence += params.pdh_pdl_caution_penalty
                state.active_indicators.append("PDH_CAUTION")

        if prev_week_high and ctx.close < prev_week_high:
            distance_pct = _safe_pct(prev_week_high - ctx.close, ctx.close, default=100.0)
            if distance_pct < params.pwl_pwh_distance_pct:
                state.confidence += params.pwh_pwl_caution_penalty
                state.active_indicators.append("PWH_CAUTION")
    else:
        if ctx.sd_signal and "supply" in ctx.sd_signal:
            state.confidence += params.sd_boost
            state.active_indicators.append(f"SD:{ctx.sd_signal}")

        if ctx.vwap_band_signal == "extended_below":
            state.confidence += params.vwap_extended_penalty
            state.active_indicators.append("VWAP_EXTENDED_CAUTION")
        elif ctx.vwap_band_signal == "near_vwap_below":
            state.confidence += params.vwap_bounce_boost
            state.active_indicators.append("VWAP_NEAR")

        if ctx.key_level_signal == "bounce_resistance_short":
            state.confidence += ctx.key_level_confidence + 0.05
            state.active_indicators.append(
                f"KEY_BOUNCE:{ctx.key_level_info.get('nearest_resistance_name', 'resistance')}"
            )
        elif ctx.key_level_signal == "breakout_support_short":
            state.confidence += ctx.key_level_confidence + params.breakout_boost
            state.active_indicators.append(
                f"KEY_BREAKOUT:{ctx.key_level_info.get('nearest_support_name', 'support')}"
            )
        elif ctx.key_level_signal == "near_support_caution":
            state.confidence += ctx.key_level_confidence
            state.active_indicators.append("CAUTION_SUPPORT")

        prev_day_high = ctx.key_levels.get("prev_day_high")
        prev_week_high = ctx.key_levels.get("prev_week_high")
        prev_day_low = ctx.key_levels.get("prev_day_low")
        prev_week_low = ctx.key_levels.get("prev_week_low")

        if prev_day_high and ctx.close < prev_day_high:
            distance_pct = _safe_pct(prev_day_high - ctx.close, prev_day_high, default=100.0)
            if distance_pct < params.pdl_pdh_distance_pct:
                state.confidence += params.pdl_pdh_boost
                state.active_indicators.append("PDH_BOUNCE")

        if prev_week_high and ctx.close < prev_week_high:
            distance_pct = _safe_pct(prev_week_high - ctx.close, prev_week_high, default=100.0)
            if distance_pct < params.pwl_pwh_distance_pct:
                state.confidence += params.pwl_pwh_boost
                state.active_indicators.append("PWH_BOUNCE")

        if prev_day_low and ctx.close > prev_day_low:
            distance_pct = _safe_pct(ctx.close - prev_day_low, ctx.close, default=100.0)
            if distance_pct < params.pdl_pdh_distance_pct:
                state.confidence += params.pdh_pdl_caution_penalty
                state.active_indicators.append("PDL_CAUTION")

        if prev_week_low and ctx.close > prev_week_low:
            distance_pct = _safe_pct(ctx.close - prev_week_low, ctx.close, default=100.0)
            if distance_pct < params.pwl_pwh_distance_pct:
                state.confidence += params.pwh_pwl_caution_penalty
                state.active_indicators.append("PWL_CAUTION")

    or_adj, or_notes = get_opening_range_adjustments(ctx.close, ctx.atr, direction, ctx.or_state)
    if or_adj != 0:
        state.confidence += or_adj
        state.active_indicators.extend(or_notes)


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

    try:
        volume_confirmed = check_volume_confirmation(ctx.df, ctx.config)
    except Exception as e:
        logger.warning("check_volume_confirmation failed: %s", e, exc_info=True)
        volume_confirmed = False

    sr_signal, sr_conf = safe_check(check_sr_signals, ctx.df, ctx.config)
    tbt_signal, tbt_conf = safe_check(check_tbt_signals, ctx.df, ctx.config)
    sd_signal, sd_conf = safe_check(check_supply_demand_signals, ctx.df, ctx.config)

    key_levels = get_key_levels(df) if len(df) >= 5 else {}
    kl_signal, kl_conf, kl_info = (None, 0.0, {})
    if key_levels:
        try:
            result = check_key_level_signals(df, key_levels, config)
            if result and len(result) >= 3:
                kl_signal, kl_conf, kl_info = result[0], result[1], result[2]
            elif result and len(result) >= 2:
                kl_signal, kl_conf = result[0], result[1]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.debug("check_key_level_signals fallback: %s", exc)
            kl_signal, kl_conf, kl_info = (None, 0.0, {})

    vwap_band_signal: Optional[str] = None
    try:
        if vwap_val is not None:
            _vwap, upper_bands, lower_bands = calculate_vwap_bands(
                df,
                std_dev=params.vwap_std_dev,
                bands=params.vwap_bands,
                vwap_series=vwap_series,
            )
            if upper_bands and lower_bands:
                outer_upper = upper_bands[-1].iloc[-1] if len(upper_bands) > 0 else None
                outer_lower = lower_bands[-1].iloc[-1] if len(lower_bands) > 0 else None
                if outer_upper is not None and close > outer_upper:
                    vwap_band_signal = "extended_above"
                elif outer_lower is not None and close < outer_lower:
                    vwap_band_signal = "extended_below"
                elif len(upper_bands) > 0 and len(lower_bands) > 0:
                    inner_upper = upper_bands[0].iloc[-1]
                    inner_lower = lower_bands[0].iloc[-1]
                    if close > vwap_val and close <= inner_upper:
                        vwap_band_signal = "near_vwap_above"
                    elif close < vwap_val and close >= inner_lower:
                        vwap_band_signal = "near_vwap_below"
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.debug("vwap_band_signal fallback: %s", exc)

    regime = detect_market_regime(df, lookback=params.regime_lookback)

    # Aggressive triggers (optional)
    vwap_cross_sig = vwap_retest_sig = trend_brk_sig = trend_mom_sig = None
    if params.allow_vwap_cross_entries and vwap_val is not None:
        vc_sig, _ = safe_check(detect_vwap_cross, df, vwap_series=vwap_series)
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
        key_level_info=kl_info, vwap_band_signal=vwap_band_signal, regime=regime,
        adx_value=regime.adx_value,
        vwap_cross_signal=vwap_cross_sig, vwap_retest_signal=vwap_retest_sig,
        trend_breakout_signal=trend_brk_sig, trend_momentum_signal=trend_mom_sig,
    )


# ============================================================================
# ORB (Opening Range Breakout) SESSION STATE
# ============================================================================
# Module-level state for tracking the opening range across bar updates.
# Reset daily when a new RTH session is detected.

_orb_state: Dict[str, Any] = {
    "date": None,          # Current session date (str)
    "orb_high": None,      # Opening range high
    "orb_low": None,       # Opening range low
    "orb_defined": False,  # Whether the range is locked
    "trades_today": 0,     # ORB trades taken today
}
_orb_state_lock = threading.Lock()


# ============================================================================
# OPENING RANGE REFERENCE STATE (Upgrade 1)
# ============================================================================
# Tracks opening range (first 15 bars) for both RTH and Overnight sessions.
# Keyed by session date+type so it persists within a session but resets on new.

_opening_range_state: Dict[str, Dict[str, Any]] = {}
_opening_range_lock = threading.Lock()


def _get_session_key(current_time: datetime) -> Tuple[str, str]:
    """Determine session key (date+type) for opening range tracking.

    Returns (session_key, session_type) where session_type is 'rth' or 'overnight'.
    """
    et = ZoneInfo("America/New_York")
    ct_et = current_time.astimezone(et) if current_time.tzinfo else current_time.replace(tzinfo=et)
    hour = ct_et.hour
    minute = ct_et.minute
    date_str = ct_et.strftime("%Y-%m-%d")

    # RTH: 09:30-16:00 ET
    if (hour > 9 or (hour == 9 and minute >= 30)) and hour < 16:
        return f"{date_str}_rth", "rth"
    # Overnight: 18:00-09:29 ET (spans midnight)
    if hour >= 18:
        return f"{date_str}_overnight", "overnight"
    # Before 09:30 — still overnight from previous day
    prev_date = (ct_et - pd.Timedelta(hours=12)).strftime("%Y-%m-%d")
    return f"{prev_date}_overnight", "overnight"


def _get_session_open_time(current_time: datetime, session_type: str) -> datetime:
    """Get the open time of the current session in ET."""
    et = ZoneInfo("America/New_York")
    ct_et = current_time.astimezone(et) if current_time.tzinfo else current_time.replace(tzinfo=et)

    if session_type == "rth":
        return ct_et.replace(hour=9, minute=30, second=0, microsecond=0)
    else:  # overnight
        if ct_et.hour >= 18:
            return ct_et.replace(hour=18, minute=0, second=0, microsecond=0)
        # Before midnight — overnight started previous calendar day
        prev = ct_et - pd.Timedelta(days=1)
        return prev.replace(hour=18, minute=0, second=0, microsecond=0).replace(tzinfo=et)


def update_opening_range(
    df: pd.DataFrame,
    current_time: datetime,
    or_bars: int = 15,
) -> Dict[str, Any]:
    """Track opening range for the current session.

    Returns dict with keys: session_open_price, or_high, or_low, or_defined, bar_count.
    """
    global _opening_range_state

    session_key, session_type = _get_session_key(current_time)
    session_open = _get_session_open_time(current_time, session_type)

    with _opening_range_lock:
        if session_key not in _opening_range_state:
            _opening_range_state[session_key] = {
                "session_open_price": None,
                "or_high": None,
                "or_low": None,
                "or_defined": False,
                "bar_count": 0,
            }
            # Prune old sessions (keep last 4)
            if len(_opening_range_state) > 4:
                keys = sorted(_opening_range_state.keys())
                for k in keys[:-4]:
                    del _opening_range_state[k]

        state = _opening_range_state[session_key]

        if state["or_defined"]:
            return dict(state)

    # Filter bars within the session window
    if "timestamp" in df.columns:
        ts_col = pd.to_datetime(df["timestamp"], utc=True)
        et = ZoneInfo("America/New_York")
        # session_open already has tzinfo — don't re-specify tz
        session_start_ts = pd.Timestamp(session_open)
        or_end_ts = session_start_ts + pd.Timedelta(minutes=or_bars)
        mask = (ts_col >= session_start_ts) & (ts_col <= or_end_ts)
        range_bars = df.loc[mask]
    else:
        # Fallback: use last N bars
        range_bars = df.tail(or_bars)

    bar_count = len(range_bars)

    with _opening_range_lock:
        state = _opening_range_state[session_key]

        if not range_bars.empty:
            if state["session_open_price"] is None:
                state["session_open_price"] = float(range_bars["open"].iloc[0])
            state["or_high"] = float(range_bars["high"].max())
            state["or_low"] = float(range_bars["low"].min())
            state["bar_count"] = bar_count

        # Check if OR is complete: past the OR window
        et = ZoneInfo("America/New_York")
        ct_et = current_time.astimezone(et) if current_time.tzinfo else current_time.replace(tzinfo=et)
        or_end_time = session_open + pd.Timedelta(minutes=or_bars)
        if ct_et > or_end_time and state["or_high"] is not None:
            state["or_defined"] = True

        return dict(state)


def get_opening_range_adjustments(
    close: float,
    atr: float,
    direction: str,
    or_state: Dict[str, Any],
) -> Tuple[float, List[str]]:
    """Compute confidence adjustments based on opening range position.

    Returns (confidence_adjustment, list_of_notes).
    """
    if not or_state.get("or_defined"):
        return 0.0, []

    or_high = or_state["or_high"]
    or_low = or_state["or_low"]
    session_open = or_state.get("session_open_price")

    if or_high is None or or_low is None:
        return 0.0, []

    adj = 0.0
    notes: List[str] = []

    # Breakout/breakdown confirmation
    if close > or_high and direction == "long":
        adj += 0.10
        notes.append("OR_BREAKOUT_CONFIRM")
    elif close < or_low and direction == "short":
        adj += 0.10
        notes.append("OR_BREAKDOWN_CONFIRM")
    elif or_low < close < or_high:
        # Inside the opening range — chop
        adj -= 0.05
        notes.append("OR_INSIDE_CHOP")

    # Near session open check
    if session_open is not None and atr > 0:
        if abs(close - session_open) < 0.25 * atr:
            notes.append("near_session_open")

    return adj, notes


# ============================================================================
# COMPOSITE REGIME SCORE (Upgrade 3)
# ============================================================================

def compute_composite_regime_score(df_5m: pd.DataFrame, lookback: int = 50) -> float:
    """Compute composite regime score 1-10.

    1-3 = Strong trend (trade freely)
    4-6 = Chop zone (block most signals)
    7-10 = Volatile trend (trade with wider stops)

    Components (each 0-2.5):
    1. ATR Percentile — U-shaped: extremes good, middle is chop
    2. EMA Slope — steeper = higher score
    3. Bollinger Band Width — narrow = chop, wide = trending/volatile
    4. Volume Ratio — higher volume = more conviction
    """
    if df_5m is None or df_5m.empty or len(df_5m) < max(lookback, 20):
        return 5.0  # Default to middle (chop zone) when insufficient data

    try:
        recent = df_5m.tail(lookback)

        # Component 1: ATR Percentile (0-2.5)
        high_low = recent["high"] - recent["low"]
        tr = pd.concat([
            high_low,
            (recent["high"] - recent["close"].shift(1)).abs(),
            (recent["low"] - recent["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr_14 = tr.rolling(14).mean()
        atr_values = atr_14.dropna()
        if len(atr_values) < 5:
            return 5.0
        current_atr = atr_values.iloc[-1]
        from scipy.stats import percentileofscore
        atr_pctile = percentileofscore(atr_values.values, current_atr) / 100.0
        # U-shaped: extremes are good (trending or volatile), middle is chop
        atr_score = abs(atr_pctile - 0.5) * 5.0  # 0-2.5

        # Component 2: EMA Slope (0-2.5)
        ema_13 = recent["close"].ewm(span=13, adjust=False).mean()
        if len(ema_13) >= 5 and ema_13.iloc[-5] != 0:
            slope = (ema_13.iloc[-1] - ema_13.iloc[-5]) / ema_13.iloc[-5] * 100
        else:
            slope = 0.0
        slope_score = min(2.5, abs(slope) * 10)

        # Component 3: Bollinger Band Width (0-2.5)
        bb_sma = recent["close"].rolling(20).mean()
        bb_std = recent["close"].rolling(20).std()
        if bb_sma.iloc[-1] and bb_sma.iloc[-1] != 0 and not pd.isna(bb_std.iloc[-1]):
            bb_width = (bb_std.iloc[-1] * 2) / bb_sma.iloc[-1] * 100
        else:
            bb_width = 0.0
        bb_score = min(2.5, bb_width * 5)

        # Component 4: Volume Ratio (0-2.5)
        if "volume" in recent.columns and recent["volume"].sum() > 0:
            vol_avg = recent["volume"].rolling(20).mean()
            if vol_avg.iloc[-1] and vol_avg.iloc[-1] > 0:
                vol_ratio = recent["volume"].iloc[-1] / vol_avg.iloc[-1]
            else:
                vol_ratio = 1.0
        else:
            vol_ratio = 1.0
        vol_score = min(2.5, max(0.0, (vol_ratio - 0.5) * 2.5))

        total = atr_score + slope_score + bb_score + vol_score
        return max(1.0, min(10.0, total))

    except Exception as e:
        logger.warning(f"compute_composite_regime_score failed: {e}")
        return 5.0


def _update_orb_range(
    df: pd.DataFrame,
    current_time: datetime,
    params: "StrategyParams",
) -> Tuple[Optional[float], Optional[float], bool]:
    """Track the opening range (first N minutes of RTH).

    Returns (orb_high, orb_low, orb_defined).  The range is only
    "defined" once we are past the range-building window.
    """
    global _orb_state

    et = ZoneInfo("America/New_York")
    ct_et = current_time.astimezone(et) if current_time.tzinfo else current_time.replace(tzinfo=et)
    today_str = ct_et.strftime("%Y-%m-%d")
    rth_start = ct_et.replace(hour=9, minute=30, second=0, microsecond=0)
    range_end = ct_et.replace(
        hour=9,
        minute=30 + params.orb_range_minutes,
        second=0,
        microsecond=0,
    )

    with _orb_state_lock:
        # Reset on new day
        if _orb_state["date"] != today_str:
            _orb_state = {
                "date": today_str,
                "orb_high": None,
                "orb_low": None,
                "orb_defined": False,
                "trades_today": 0,
            }

        # Only build the range during the window
        if ct_et < rth_start:
            return None, None, False

        if ct_et <= range_end and not _orb_state["orb_defined"]:
            # Filter bars within the range window
            if "timestamp" in df.columns:
                ts_col = pd.to_datetime(df["timestamp"], utc=True)
                mask = (ts_col >= pd.Timestamp(rth_start, tz=et)) & (ts_col <= pd.Timestamp(range_end, tz=et))
                range_bars = df.loc[mask]
            else:
                # Fallback: use last N bars (orb_range_minutes bars on 1m)
                range_bars = df.tail(params.orb_range_minutes)

            if not range_bars.empty:
                _orb_state["orb_high"] = float(range_bars["high"].max())
                _orb_state["orb_low"] = float(range_bars["low"].min())

        # Lock the range once past the window
        if ct_et > range_end and _orb_state["orb_high"] is not None:
            _orb_state["orb_defined"] = True

        return _orb_state["orb_high"], _orb_state["orb_low"], _orb_state["orb_defined"]


def _check_orb_signal(
    df: pd.DataFrame,
    ind: "IndicatorResult",
    params: "StrategyParams",
    current_time: datetime,
) -> Optional[Dict]:
    """Check for Opening Range Breakout entry.

    Returns a signal dict or None.
    """
    if not params.allow_orb_entries:
        return None

    et = ZoneInfo("America/New_York")
    ct_et = current_time.astimezone(et) if current_time.tzinfo else current_time.replace(tzinfo=et)

    # Parse window end time
    try:
        end_parts = params.orb_window_end.split(":")
        window_end = ct_et.replace(hour=int(end_parts[0]), minute=int(end_parts[1]), second=0, microsecond=0)
    except (ValueError, IndexError):
        window_end = ct_et.replace(hour=11, minute=0, second=0, microsecond=0)

    range_end = ct_et.replace(hour=9, minute=30 + params.orb_range_minutes, second=0, microsecond=0)

    # Only fire after range is defined and before window closes
    if ct_et <= range_end or ct_et > window_end:
        return None

    orb_high, orb_low, orb_defined = _update_orb_range(df, current_time, params)
    if not orb_defined or orb_high is None or orb_low is None:
        return None

    with _orb_state_lock:
        if _orb_state["trades_today"] >= params.orb_max_trades_per_day:
            return None

    close = ind.close
    adx = ind.adx_value
    vwap_val = ind.vwap_val

    # Minimum ADX filter — need some directional movement
    if adx < params.adx_ranging_threshold:
        return None

    direction = None
    if close > orb_high:
        direction = "long"
    elif close < orb_low:
        direction = "short"

    if direction is None:
        return None

    # Build confidence
    confidence = params.orb_base_confidence
    active_indicators = [f"ORB_BREAKOUT_{direction.upper()}"]

    # VWAP alignment boost
    if vwap_val is not None:
        if (direction == "long" and close > vwap_val) or (direction == "short" and close < vwap_val):
            confidence += params.orb_vwap_boost
            active_indicators.append("VWAP_ALIGNED")

    # Volume boost
    if ind.volume_confirmed:
        confidence += params.orb_volume_boost
        active_indicators.append("VOL_CONFIRM")

    # ADX strength boost
    if adx > params.adx_trending_threshold:
        confidence += params.orb_adx_boost
        active_indicators.append(f"ADX_STRONG({adx:.0f})")

    # SL/TP: SL at opposite side of ORB range or ATR-based (whichever is wider)
    orb_range = orb_high - orb_low
    atr = ind.atr
    if direction == "long":
        sl_distance = max(orb_range, atr * params.orb_sl_atr_mult)
        stop_loss = close - sl_distance
        take_profit = close + atr * params.orb_tp_atr_mult
    else:
        sl_distance = max(orb_range, atr * params.orb_sl_atr_mult)
        stop_loss = close + sl_distance
        take_profit = close - atr * params.orb_tp_atr_mult

    # Record the trade
    with _orb_state_lock:
        _orb_state["trades_today"] += 1

    return {
        "direction": direction,
        "entry_price": float(close),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "confidence": float(min(confidence, 0.99)),
        "risk_reward": float(abs(take_profit - close) / abs(close - stop_loss)) if abs(close - stop_loss) > 0 else 0.0,
        "reason": f"ORB_{direction.upper()}[{len(active_indicators)}]: " + " | ".join(active_indicators),
        "indicators": {
            "active_count": len(active_indicators),
            "active_list": active_indicators,
            "entry_trigger": "orb_breakout",
            "orb_high": orb_high,
            "orb_low": orb_low,
            "orb_range": orb_range,
            "adx_value": adx,
        },
    }


def _check_vwap_2sd_signal(
    df: pd.DataFrame,
    ind: "IndicatorResult",
    params: "StrategyParams",
    current_time: datetime,
) -> Optional[Dict]:
    """Check for VWAP 2SD mean reversion entry.

    Returns a signal dict or None.
    """
    if not params.allow_vwap_2sd_entries:
        return None

    et = ZoneInfo("America/New_York")
    ct_et = current_time.astimezone(et) if current_time.tzinfo else current_time.replace(tzinfo=et)

    # Time window check
    try:
        start_parts = params.vwap_2sd_window_start.split(":")
        end_parts = params.vwap_2sd_window_end.split(":")
        window_start = ct_et.replace(hour=int(start_parts[0]), minute=int(start_parts[1]), second=0, microsecond=0)
        window_end = ct_et.replace(hour=int(end_parts[0]), minute=int(end_parts[1]), second=0, microsecond=0)
    except (ValueError, IndexError):
        window_start = ct_et.replace(hour=10, minute=0, second=0, microsecond=0)
        window_end = ct_et.replace(hour=15, minute=0, second=0, microsecond=0)

    if ct_et < window_start or ct_et > window_end:
        return None

    # Need VWAP
    if ind.vwap_val is None:
        return None

    # Mean reversion works best in non-trending conditions
    adx = ind.adx_value
    if adx > params.adx_trending_threshold:
        return None

    close = ind.close
    vwap_val = ind.vwap_val
    atr = ind.atr

    # Calculate 2SD bands from existing VWAP infrastructure
    try:
        _vwap, upper_bands, lower_bands = calculate_vwap_bands(
            df,
            std_dev=params.vwap_2sd_multiplier,
            bands=1,
            vwap_series=ind.vwap_series,
        )
        if not upper_bands or not lower_bands:
            return None
        upper_2sd = float(upper_bands[0].iloc[-1])
        lower_2sd = float(lower_bands[0].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.debug("vwap_2sd bands fallback: %s", exc)
        return None

    # Calculate RSI
    if len(df) < 14:
        return None
    try:
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100.0
        rsi = 100.0 - (100.0 / (1.0 + rs))
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        logger.debug("vwap_2sd RSI fallback: %s", exc)
        return None

    direction = None
    # Long: price at/below lower 2SD + RSI oversold + reversal candle
    if close <= lower_2sd and rsi < params.vwap_2sd_rsi_long_threshold:
        candle_open = float(df["open"].iloc[-1])
        if close > candle_open:  # Bullish reversal candle
            direction = "long"
    # Short: price at/above upper 2SD + RSI overbought + reversal candle
    elif close >= upper_2sd and rsi > params.vwap_2sd_rsi_short_threshold:
        candle_open = float(df["open"].iloc[-1])
        if close < candle_open:  # Bearish reversal candle
            direction = "short"

    if direction is None:
        return None

    # Volume spike check
    vol_ma = df["volume"].rolling(20).mean().iloc[-1] if len(df) >= 20 else df["volume"].mean()
    current_vol = float(df["volume"].iloc[-1])
    volume_spike = current_vol > vol_ma * params.vwap_2sd_volume_spike_mult

    # Build confidence
    confidence = params.vwap_2sd_base_confidence
    active_indicators = [f"VWAP_2SD_{direction.upper()}", f"RSI({rsi:.0f})"]

    # RSI extreme boost
    if rsi < 30 or rsi > 70:
        confidence += params.vwap_2sd_rsi_extreme_boost
        active_indicators.append("RSI_EXTREME")

    # Volume spike boost
    if volume_spike:
        confidence += params.vwap_2sd_volume_boost
        active_indicators.append("VOL_SPIKE")

    # S&R confirmation
    if ind.sr_signal:
        if (direction == "long" and "long" in ind.sr_signal) or (direction == "short" and "short" in ind.sr_signal):
            confidence += 0.05
            active_indicators.append(f"SR:{ind.sr_signal}")

    # SL/TP: SL beyond the band by ATR, TP at VWAP midline
    if direction == "long":
        stop_loss = close - atr * params.vwap_2sd_sl_atr_mult
        take_profit = vwap_val  # Mean reversion target = VWAP
    else:
        stop_loss = close + atr * params.vwap_2sd_sl_atr_mult
        take_profit = vwap_val

    risk = abs(close - stop_loss)
    reward = abs(take_profit - close)
    risk_reward = reward / risk if risk > 0 else 0.0

    return {
        "direction": direction,
        "entry_price": float(close),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "confidence": float(min(confidence, 0.99)),
        "risk_reward": float(risk_reward),
        "reason": f"VWAP2SD_{direction.upper()}[{len(active_indicators)}]: " + " | ".join(active_indicators),
        "indicators": {
            "active_count": len(active_indicators),
            "active_list": active_indicators,
            "entry_trigger": "vwap_2sd_reversion",
            "rsi": float(rsi),
            "upper_2sd": upper_2sd,
            "lower_2sd": lower_2sd,
            "vwap": vwap_val,
            "adx_value": adx,
            "volume_spike": volume_spike,
        },
    }


def generate_signals(
    df: pd.DataFrame,
    config: Optional[Dict] = None,
    current_time: Optional[datetime] = None,
    df_5m: Optional[pd.DataFrame] = None,
    diagnostics: Optional[Dict] = None,
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
        - Directional trigger selection and confidence helpers (Stages 2-3)
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
    
    # Session windows are observability-only; strategy generation is always on.
    check_trading_session(current_time, config)

    # =====================================================================
    # OPENING RANGE REFERENCE (Upgrade 1)
    # Track OR for current session. During first 15 bars, suppress signals.
    # =====================================================================
    or_state = update_opening_range(df, current_time, or_bars=15)
    or_forming = not or_state.get("or_defined", False) and or_state.get("bar_count", 0) > 0
    if or_forming and or_state.get("bar_count", 0) <= 15:
        logger.debug(
            f"Opening range forming (bar {or_state.get('bar_count', 0)}/15) — suppressing signals"
        )
        return signals

    # Stage 1: Calculate all indicators (on 1m bars for signal generation)
    ind = _calculate_indicators(df, params, config)
    if ind is None:
        return signals  # ATR invalid or zero

    # Stage 1b: Override regime with 5m-based detection when available.
    # 5m regime is more stable and catches trend changes faster than
    # 50-bar lookback on 1m (which is only ~50 min of noisy data).
    _mtf_override_enabled = bool(
        (config or {}).get("composite_regime", {}).get("mtf_override_enabled", True)
    )
    if _mtf_override_enabled and df_5m is not None and not df_5m.empty and len(df_5m) >= 30:
        regime_5m = detect_market_regime(df_5m, lookback=min(50, len(df_5m)))
        old_regime = ind.regime
        ind.regime = regime_5m
        if regime_5m.regime != old_regime.regime:
            logger.info(
                f"MTF regime override: 1m={old_regime.regime}({old_regime.confidence:.2f}) "
                f"→ 5m={regime_5m.regime}({regime_5m.confidence:.2f})"
            )
    elif not _mtf_override_enabled:
        logger.debug("MTF regime override: disabled by config")

    # ------------------------------------------------------------------
    # Extract core indicators from ind (already computed by
    # _calculate_indicators) to avoid redundant ATR / EMA / VWAP work.
    # ------------------------------------------------------------------
    atr = ind.atr
    atr_series = ind.atr_series
    close = ind.close
    prev_close = ind.prev_close
    ema_fast = ind.ema_fast
    ema_slow = ind.ema_slow
    vwap_series = ind.vwap_series
    vwap_val = ind.vwap_val
    key_levels = ind.key_levels

    fast_curr = float(ema_fast.iloc[-1])
    fast_prev = float(ema_fast.iloc[-2]) if len(ema_fast) > 1 else fast_curr
    slow_curr = float(ema_slow.iloc[-1])
    slow_prev = float(ema_slow.iloc[-2]) if len(ema_slow) > 1 else slow_curr
    
    # 1) EMA crossover (event) + EMA trend (state)
    if any(pd.isna(x) for x in (fast_curr, fast_prev, slow_curr, slow_prev)):
        bullish_cross, bearish_cross = False, False
        ema_bull_trend, ema_bear_trend = False, False
    else:
        bullish_cross = ind.ema_cross_up
        bearish_cross = ind.ema_cross_down
        ema_bull_trend = fast_curr > slow_curr
        ema_bear_trend = fast_curr < slow_curr
    
    # 2) VWAP position (core - required)
    if vwap_val is None or pd.isna(vwap_val) or pd.isna(close):
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

    # =====================================================================
    # NEW TRIGGERS: fire when EMA/VWAP alignment triggers are quiet
    # =====================================================================
    allow_mean_reversion = bool(config.get("allow_mean_reversion_entries", True))
    allow_ema_pullback = bool(config.get("allow_ema_pullback_entries", True))
    allow_vwap_reclaim = bool(config.get("allow_vwap_reclaim_entries", True))
    mean_reversion_long, mean_reversion_short = False, False
    ema_pullback_long, ema_pullback_short = False, False
    vwap_reclaim_long, vwap_reclaim_short = False, False

    # MEAN REVERSION: RSI oversold/overbought with price stretched from VWAP
    if allow_mean_reversion and len(df) >= 14 and vwap_curr is not None:
        try:
            delta = df["close"].diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100.0
            rsi = 100.0 - (100.0 / (1.0 + rs))
            vwap_dist_pct = (close - vwap_curr) / vwap_curr if vwap_curr != 0 else 0
            # Long: RSI oversold + price stretched below VWAP
            mean_reversion_long = bool(rsi < 35 and vwap_dist_pct < -0.001)
            # Short: RSI overbought + price stretched above VWAP
            mean_reversion_short = bool(rsi > 65 and vwap_dist_pct > 0.001)
        except Exception as e:
            logger.debug(f"Mean reversion check failed: {e}")

    # EMA PULLBACK: price pulls back to EMA21 in a trend (not just crosses)
    if allow_ema_pullback and len(df) >= 3:
        try:
            ema_slow_val = float(df["close"].ewm(span=int(config.get("ema_slow", 21))).mean().iloc[-1])
            ema_fast_val = float(df["close"].ewm(span=int(config.get("ema_fast", 9))).mean().iloc[-1])
            prev_low = float(df["low"].iloc[-1])
            prev_high = float(df["high"].iloc[-1])
            # Long: uptrend (EMA9>EMA21), bar wick touched EMA21 but closed above
            ema_pullback_long = bool(
                ema_fast_val > ema_slow_val
                and prev_low <= ema_slow_val * 1.001
                and close > ema_slow_val
            )
            # Short: downtrend, bar wick touched EMA21 but closed below
            ema_pullback_short = bool(
                ema_fast_val < ema_slow_val
                and prev_high >= ema_slow_val * 0.999
                and close < ema_slow_val
            )
        except Exception as e:
            logger.debug(f"EMA pullback check failed: {e}")

    # VWAP RECLAIM: price crosses back above/below VWAP (no EMA requirement)
    if allow_vwap_reclaim and vwap_curr is not None and len(df) >= 2:
        try:
            prev_close_val = float(df["close"].iloc[-2])
            # Long: previous bar closed below VWAP, current closes above
            vwap_reclaim_long = bool(prev_close_val < vwap_curr and close > vwap_curr and ind.volume_confirmed)
            # Short: previous bar closed above VWAP, current closes below
            vwap_reclaim_short = bool(prev_close_val > vwap_curr and close < vwap_curr and ind.volume_confirmed)
        except Exception as e:
            logger.debug(f"VWAP reclaim check failed: {e}")

    # ------------------------------------------------------------------
    # Use pre-computed indicator signals from _calculate_indicators()
    # to avoid redundant computation of volume, S&R, TBT, S&D,
    # key level, and VWAP band signals.
    # ------------------------------------------------------------------

    # 3. Volume confirmation (core - pre-computed)
    volume_confirmed = ind.volume_confirmed

    # 4. S&R Power Channel (extended - pre-computed)
    sr_signal, sr_confidence = ind.sr_signal, ind.sr_confidence

    # 5. TBT Trendlines (extended - pre-computed)
    tbt_signal, tbt_confidence = ind.tbt_signal, ind.tbt_confidence

    # 6. Supply & Demand (extended - pre-computed)
    sd_signal, sd_confidence = ind.sd_signal, ind.sd_confidence

    # 7. SpacemanBTC Key Levels (extended - pre-computed)
    key_level_signal = ind.key_level_signal
    key_level_conf_adj = ind.key_level_confidence
    key_level_info = ind.key_level_info

    # 8. VWAP bands (for extension/reversion detection - pre-computed)
    vwap_band_signal = ind.vwap_band_signal
    
    # ==========================================================================
    # MARKET REGIME DETECTION
    # Adjusts confidence and filters signals based on market conditions
    # ==========================================================================
    market_regime = ind.regime
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
    
    # Set dynamic SL/TP multipliers based on regime (configurable)
    base_sl_mult = float(config.get("stop_loss_atr_mult", 1.0))
    base_tp_mult = float(config.get("take_profit_atr_mult", 2.0))
    volatile_sl_scale = float(config.get("volatile_sl_mult", 1.3))
    volatile_tp_scale = float(config.get("volatile_tp_mult", 1.3))
    ranging_sl_scale = float(config.get("ranging_sl_mult", 0.8))
    ranging_tp_scale = float(config.get("ranging_tp_mult", 0.7))

    if market_regime.regime == "volatile":
        dynamic_sl_mult = base_sl_mult * volatile_sl_scale
        dynamic_tp_mult = base_tp_mult * volatile_tp_scale
    elif market_regime.regime == "ranging":
        dynamic_sl_mult = base_sl_mult * ranging_sl_scale
        dynamic_tp_mult = base_tp_mult * ranging_tp_scale
    else:
        dynamic_sl_mult = base_sl_mult
        dynamic_tp_mult = base_tp_mult
    
    # =====================================================================
    # COMPOSITE REGIME SCORE (Upgrade 3)
    # =====================================================================
    composite_regime_cfg = config.get("composite_regime", {})
    composite_regime_enabled = bool(composite_regime_cfg.get("enabled", False))
    regime_score = 5.0  # Default mid-range
    chop_low = float(composite_regime_cfg.get("chop_zone_low", 4.0))
    chop_high = float(composite_regime_cfg.get("chop_zone_high", 6.0))
    chop_min_conf = float(composite_regime_cfg.get("chop_zone_min_confidence", 0.75))
    if composite_regime_enabled and df_5m is not None:
        regime_score = compute_composite_regime_score(df_5m, lookback=50)
        logger.debug(f"Composite regime score: {regime_score:.1f}")

        # Volatile trend: widen stops
        volatile_stop_mult = float(composite_regime_cfg.get("volatile_stop_multiplier", 1.2))
        if regime_score >= 7.0:
            dynamic_sl_mult *= volatile_stop_mult
            logger.debug(f"Volatile regime score {regime_score:.1f} — widened SL mult to {dynamic_sl_mult:.2f}")

    # Combine signals with confidence scoring
    signal_candidates = []

    # Long signals - ALL 8 INDICATORS CONTRIBUTE + NEW TRIGGERS
    long_trigger = (
        bullish_cross
        or (allow_vwap_cross_entries and bullish_vwap_cross and ema_bull_trend)
        or (allow_vwap_retest_entries and vwap_retest_long)
        or (allow_trend_momentum_entries and trend_momentum_long)
        or (allow_trend_breakout_entries and trend_breakout_long)
        or (allow_mean_reversion and mean_reversion_long)
        or (allow_ema_pullback and ema_pullback_long)
        or (allow_vwap_reclaim and vwap_reclaim_long)
    )
    # New triggers don't require price_above_vwap (that's their whole point)
    needs_vwap_filter = not (mean_reversion_long or vwap_reclaim_long)
    if long_trigger and (price_above_vwap or not needs_vwap_filter):
        long_state = _initialize_directional_score(
            "long",
            DirectionalTriggers(
                ema_cross=bullish_cross,
                vwap_cross=bullish_vwap_cross,
                vwap_retest=vwap_retest_long,
                trend_breakout=trend_breakout_long,
                mean_reversion=mean_reversion_long,
                ema_pullback=ema_pullback_long,
                vwap_reclaim=vwap_reclaim_long,
                trend_momentum=trend_momentum_long,
            ),
            params,
        )
        if long_state is None:
            return signals

        _apply_directional_confidence_adjustments(
            long_state,
            DirectionalConfidenceContext(
                direction="long",
                close=close,
                atr=atr,
                volume_confirmed=volume_confirmed,
                sr_signal=sr_signal,
                sr_confidence=sr_confidence,
                tbt_signal=tbt_signal,
                tbt_confidence=tbt_confidence,
                sd_signal=sd_signal,
                key_levels=key_levels,
                key_level_signal=key_level_signal,
                key_level_confidence=key_level_conf_adj,
                key_level_info=key_level_info,
                vwap_band_signal=vwap_band_signal,
                or_state=or_state,
            ),
            params,
        )
        confidence = long_state.confidence
        entry_trigger = long_state.entry_trigger
        active_indicators = long_state.active_indicators

        # Composite Regime Score chop filter (Upgrade 3)
        _chop_blocked_long = False
        if composite_regime_enabled and chop_low <= regime_score <= chop_high and confidence < chop_min_conf:
            logger.debug(f"LONG blocked by composite regime chop zone (score={regime_score:.1f}, conf={confidence:.2f})")
            _chop_blocked_long = True

        _min_conf_long = config.get("min_confidence_long", config.get("min_confidence", 0.55))
        if confidence >= _min_conf_long and not _chop_blocked_long:
            entry_price = close
            # Use dynamic regime-adaptive parameters
            sl_mult = dynamic_sl_mult
            tp_mult = dynamic_tp_mult
            stop_loss = entry_price - (atr * sl_mult)
            take_profit = entry_price + (atr * tp_mult)
            
            # NaN guards: ensure valid SL/TP before calculating R:R
            risk_amount = entry_price - stop_loss
            max_stop_pts = float(config.get("max_stop_points", 45.0))
            if pd.isna(stop_loss) or pd.isna(take_profit) or stop_loss >= entry_price or risk_amount <= 0:
                pass  # Skip invalid signal
            elif risk_amount > max_stop_pts:
                logger.debug(f"LONG rejected: SL {risk_amount:.1f} pts > max_stop_points {max_stop_pts}")
            else:
                risk_reward = _safe_div(take_profit - entry_price, risk_amount, default=0.0)

                if risk_reward >= config["min_risk_reward"] and not pd.isna(risk_reward):
                    signal_candidates.append({
                        "direction": "long",
                        "entry_price": float(entry_price),
                        "stop_loss": float(stop_loss),
                        "take_profit": float(take_profit),
                        "confidence": float(min(confidence, 0.99)),
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

    # Short signals - ALL 8 INDICATORS CONTRIBUTE + NEW TRIGGERS
    short_trigger = (
        bearish_cross
        or (allow_vwap_cross_entries and bearish_vwap_cross and ema_bear_trend)
        or (allow_vwap_retest_entries and vwap_retest_short)
        or (allow_trend_momentum_entries and trend_momentum_short)
        or (allow_trend_breakout_entries and trend_breakout_short)
        or (allow_mean_reversion and mean_reversion_short)
        or (allow_ema_pullback and ema_pullback_short)
        or (allow_vwap_reclaim and vwap_reclaim_short)
    )
    needs_vwap_filter_short = not (mean_reversion_short or vwap_reclaim_short)
    if short_trigger and (price_below_vwap or not needs_vwap_filter_short):
        short_state = _initialize_directional_score(
            "short",
            DirectionalTriggers(
                ema_cross=bearish_cross,
                vwap_cross=bearish_vwap_cross,
                vwap_retest=vwap_retest_short,
                trend_breakout=trend_breakout_short,
                mean_reversion=mean_reversion_short,
                ema_pullback=ema_pullback_short,
                vwap_reclaim=vwap_reclaim_short,
                trend_momentum=trend_momentum_short,
            ),
            params,
        )
        if short_state is None:
            return signals

        _apply_directional_confidence_adjustments(
            short_state,
            DirectionalConfidenceContext(
                direction="short",
                close=close,
                atr=atr,
                volume_confirmed=volume_confirmed,
                sr_signal=sr_signal,
                sr_confidence=sr_confidence,
                tbt_signal=tbt_signal,
                tbt_confidence=tbt_confidence,
                sd_signal=sd_signal,
                key_levels=key_levels,
                key_level_signal=key_level_signal,
                key_level_confidence=key_level_conf_adj,
                key_level_info=key_level_info,
                vwap_band_signal=vwap_band_signal,
                or_state=or_state,
            ),
            params,
        )
        confidence = short_state.confidence
        entry_trigger = short_state.entry_trigger
        active_indicators = short_state.active_indicators

        # Composite Regime Score chop filter (Upgrade 3)
        _chop_blocked_short = False
        if composite_regime_enabled and chop_low <= regime_score <= chop_high and confidence < chop_min_conf:
            logger.debug(f"SHORT blocked by composite regime chop zone (score={regime_score:.1f}, conf={confidence:.2f})")
            _chop_blocked_short = True

        _min_conf_short = config.get("min_confidence_short", 0.78)
        if confidence >= _min_conf_short and not _chop_blocked_short:
            entry_price = close
            # Use dynamic regime-adaptive parameters
            sl_mult = dynamic_sl_mult
            tp_mult = dynamic_tp_mult
            stop_loss = entry_price + (atr * sl_mult)
            take_profit = entry_price - (atr * tp_mult)
            
            # NaN guards: ensure valid SL/TP before calculating R:R
            risk_amount = stop_loss - entry_price
            max_stop_pts = float(config.get("max_stop_points", 45.0))
            if pd.isna(stop_loss) or pd.isna(take_profit) or stop_loss <= entry_price or risk_amount <= 0:
                pass  # Skip invalid signal
            elif risk_amount > max_stop_pts:
                logger.debug(f"SHORT rejected: SL {risk_amount:.1f} pts > max_stop_points {max_stop_pts}")
            else:
                risk_reward = _safe_div(entry_price - take_profit, risk_amount, default=0.0)

                if risk_reward >= config["min_risk_reward"] and not pd.isna(risk_reward):
                    signal_candidates.append({
                        "direction": "short",
                        "entry_price": float(entry_price),
                        "stop_loss": float(stop_loss),
                        "take_profit": float(take_profit),
                        "confidence": float(min(confidence, 0.99)),
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

    # ==========================================================================
    # NEW STRATEGIES: ORB + VWAP 2SD (session-aware, additive)
    # ==========================================================================
    # Update ORB range state (must run every bar to track high/low)
    if params.allow_orb_entries:
        _update_orb_range(df, current_time, params)

    orb_signal = safe_check(_check_orb_signal, df, ind, params, current_time)
    if isinstance(orb_signal, tuple):
        orb_signal = orb_signal[0] if orb_signal[0] else None
    if isinstance(orb_signal, dict):
        signal_candidates.append(orb_signal)
        logger.info("ORB signal generated: %s conf=%.2f", orb_signal.get("direction"), orb_signal.get("confidence", 0))

    vwap_2sd_signal = safe_check(_check_vwap_2sd_signal, df, ind, params, current_time)
    if isinstance(vwap_2sd_signal, tuple):
        vwap_2sd_signal = vwap_2sd_signal[0] if vwap_2sd_signal[0] else None
    if isinstance(vwap_2sd_signal, dict):
        signal_candidates.append(vwap_2sd_signal)
        logger.info("VWAP 2SD signal generated: %s conf=%.2f", vwap_2sd_signal.get("direction"), vwap_2sd_signal.get("confidence", 0))

    # SMC (Smart Money Concepts) — FVG + Order Block + Silver Bullet
    try:
        from pearlalgo.trading_bots.smc_signals import _check_smc_signal
        smc_signal = safe_check(_check_smc_signal, df, ind, params, current_time)
        if isinstance(smc_signal, tuple):
            smc_signal = smc_signal[0] if smc_signal[0] else None
        if isinstance(smc_signal, dict):
            signal_candidates.append(smc_signal)
            logger.info("SMC signal generated: %s conf=%.2f type=%s",
                        smc_signal.get("direction"), smc_signal.get("confidence", 0),
                        smc_signal.get("signal_type", "smc"))
    except Exception as e:
        logger.debug("SMC signal check unavailable: %s", e)

    # Add metadata to signals including regime information
    for signal in signal_candidates:
        signal["timestamp"] = current_time.isoformat()
        signal["symbol"] = config["symbol"]
        signal["timeframe"] = config["timeframe"]
        signal["type"] = signal.get("signal_type", "pearlbot_pinescript")
        # Tag signal source for multi-strategy analysis
        st = signal.get("signal_type", "")
        if "orb" in st.lower():
            signal["signal_source"] = "orb"
        elif "vwap_2sd" in st.lower():
            signal["signal_source"] = "vwap_2sd"
        elif "smc" in st.lower():
            signal["signal_source"] = "smc"
        else:
            signal["signal_source"] = "ema_pinescript"
        signal["virtual_broker"] = True  # Mark as virtual - no real execution
        
        # Apply market-state confidence adjustment only.
        original_confidence = signal.get("confidence", 0.5)
        adjusted_confidence = original_confidence * regime_multiplier

        signal["confidence"] = float(min(adjusted_confidence, 0.99))

        # Add regime information for transparency
        signal["market_regime"] = market_regime.to_dict()
        signal["composite_regime_score"] = regime_score
        signal["opening_range"] = or_state
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
    min_conf_generic = config.get("min_confidence", 0.55)
    min_conf_long = config.get("min_confidence_long", min_conf_generic)
    min_conf_short = config.get("min_confidence_short", min_conf_generic)
    pre_filter_count = len(signal_candidates)

    def _passes_conf(s):
        d = s.get("direction", "")
        c = s.get("confidence", 0)
        if d == "short":
            return c >= min_conf_short
        elif d == "long":
            return c >= min_conf_long
        return c >= min_conf_generic

    signal_candidates = [s for s in signal_candidates if _passes_conf(s)]

    if len(signal_candidates) < pre_filter_count:
        filtered_count = pre_filter_count - len(signal_candidates)
        if diagnostics is not None:
            diagnostics["rejected_confidence"] = (
                int(diagnostics.get("rejected_confidence", 0) or 0) + filtered_count
            )
        logger.debug(
            f"Post-regime confidence filter removed {filtered_count} signal(s) "
            f"that fell below confidence threshold after regime adjustment"
        )

    # ==========================================================================
    # PRICE SANITY FILTER (Issue 5)
    # Reject signals with NaN, Inf, or non-positive prices before they enter
    # the pipeline. This catches edge cases from all signal sources (core,
    # ORB, VWAP 2SD, SMC) that may bypass per-direction NaN guards above.
    # ==========================================================================
    _PRICE_FIELDS = ("entry_price", "stop_loss", "take_profit")
    pre_sanity_count = len(signal_candidates)
    validated = []
    for sig in signal_candidates:
        valid = True
        for field in _PRICE_FIELDS:
            val = sig.get(field)
            if val is None or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
                logger.warning(
                    "Signal rejected: %s=%s is invalid (direction=%s, source=%s)",
                    field, val, sig.get("direction"), sig.get("signal_source"),
                )
                valid = False
                break
        if valid:
            validated.append(sig)
    signal_candidates = validated

    if len(signal_candidates) < pre_sanity_count:
        rejected_price_count = pre_sanity_count - len(signal_candidates)
        if diagnostics is not None:
            diagnostics["rejected_invalid_prices"] = (
                int(diagnostics.get("rejected_invalid_prices", 0) or 0)
                + rejected_price_count
            )
        logger.warning(
            "Price sanity filter removed %d signal(s) with NaN/Inf/non-positive prices",
            rejected_price_count,
        )

    if diagnostics is not None:
        diagnostics["raw_signals"] = (
            int(diagnostics.get("raw_signals", 0) or 0) + len(signal_candidates)
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
