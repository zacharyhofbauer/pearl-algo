"""Smart Money Concepts (SMC) signal generator for PearlAlgo.

Wraps the ``smartmoneyconcepts`` library (v0.0.26) into the standard
PearlAlgo signal-dict format so it can be consumed by pearl_bot_auto
alongside ORB, VWAP-2SD, and other strategies.

All public functions follow the same ``(df, ind, params, current_time)``
signature used by ``_check_orb_signal`` / ``_check_vwap_2sd_signal``.

StrategyParams fields this module expects (add to StrategyParams dataclass):
    allow_smc_entries: bool = False
    smc_swing_length: int = 10
    smc_fvg_lookback: int = 20
    smc_ob_lookback: int = 20
    smc_fvg_base_confidence: float = 0.55
    smc_ob_boost: float = 0.10
    smc_bos_boost: float = 0.08
    smc_volume_boost: float = 0.08
    smc_key_level_boost: float = 0.10
    smc_vwap_boost: float = 0.05
    smc_sl_atr_mult: float = 0.8
    smc_tp_atr_mult: float = 2.5
    smc_silver_bullet_windows: list = [[10, 11], [14, 15], [15, 16]]
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from pearlalgo.utils.logger import logger

# ---------------------------------------------------------------------------
# Lazy import of smartmoneyconcepts — may not be installed in all envs.
# ---------------------------------------------------------------------------
_smc = None
_smc_import_failed = False


def _get_smc():
    """Lazy-import smartmoneyconcepts.smc.smc so the module can be loaded
    even when the library is absent (returns None in that case)."""
    global _smc, _smc_import_failed
    if _smc is not None:
        return _smc
    if _smc_import_failed:
        return None
    try:
        from smartmoneyconcepts.smc import smc as _smc_lib
        _smc = _smc_lib
        return _smc
    except ImportError:
        _smc_import_failed = True
        logger.warning(
            "smartmoneyconcepts library not installed — SMC signals disabled. "
            "Install with: pip install smartmoneyconcepts"
        )
        return None
    except Exception as exc:
        _smc_import_failed = True
        logger.warning("Failed to import smartmoneyconcepts: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_ET = ZoneInfo("America/New_York")

# Default Silver Bullet windows (hour_start, hour_end) in ET
_DEFAULT_SB_WINDOWS: List[List[int]] = [[10, 11], [14, 15], [15, 16]]


# ---------------------------------------------------------------------------
# Helpers: parameter access with safe defaults
# ---------------------------------------------------------------------------

def _param(params: Any, name: str, default: Any) -> Any:
    """Read a param attribute with a fallback default so the module never
    crashes when a StrategyParams field hasn't been added yet."""
    return getattr(params, name, default)


# ---------------------------------------------------------------------------
# 1. _prepare_ohlc
# ---------------------------------------------------------------------------

def _prepare_ohlc(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Convert PearlAlgo DataFrame to smartmoneyconcepts format.

    Requirements for the library:
    - Columns: open, high, low, close, volume (lowercase)
    - DatetimeIndex

    Returns None if the data is insufficient or malformed.
    """
    if df is None or df.empty or len(df) < 5:
        return None

    required = {"open", "high", "low", "close", "volume"}

    # PearlAlgo already uses lowercase columns, but guard against edge cases
    col_map = {}
    existing = set(df.columns)
    for col in required:
        if col in existing:
            col_map[col] = col
        elif col.capitalize() in existing:
            col_map[col.capitalize()] = col
        elif col.upper() in existing:
            col_map[col.upper()] = col
        else:
            logger.warning("SMC: missing required column '%s' in DataFrame", col)
            return None

    ohlc = df.rename(columns={v: k for k, v in col_map.items() if v != k})[
        ["open", "high", "low", "close", "volume"]
    ].copy()

    # Ensure DatetimeIndex
    if not isinstance(ohlc.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            ohlc.index = pd.DatetimeIndex(df["timestamp"])
        elif "datetime" in df.columns:
            ohlc.index = pd.DatetimeIndex(df["datetime"])
        elif "date" in df.columns:
            ohlc.index = pd.DatetimeIndex(df["date"])
        else:
            # Try converting the existing index
            try:
                ohlc.index = pd.DatetimeIndex(ohlc.index)
            except Exception:
                logger.warning("SMC: could not create DatetimeIndex from DataFrame")
                return None

    # Drop rows with NaN in OHLC (volume NaN is tolerable — fill with 0)
    ohlc["volume"] = ohlc["volume"].fillna(0)
    ohlc = ohlc.dropna(subset=["open", "high", "low", "close"])

    if len(ohlc) < 5:
        return None

    return ohlc


# ---------------------------------------------------------------------------
# 2. _detect_active_fvgs
# ---------------------------------------------------------------------------

def _detect_active_fvgs(
    fvg_df: pd.DataFrame,
    current_price: float,
    lookback: int = 20,
) -> List[Dict]:
    """Find unmitigated FVGs within *lookback* bars where price is inside or
    near the gap.

    Returns a list of dicts with keys: direction, top, bottom, bar_index.
    """
    if fvg_df is None or fvg_df.empty:
        return []

    active: List[Dict] = []
    n = len(fvg_df)
    start = max(0, n - lookback)

    for i in range(start, n):
        try:
            fvg_val = fvg_df["FVG"].iloc[i]
            # 0 or NaN means no FVG on this bar
            if pd.isna(fvg_val) or fvg_val == 0:
                continue

            top = float(fvg_df["Top"].iloc[i])
            bottom = float(fvg_df["Bottom"].iloc[i])

            # Skip if already mitigated
            mitigated = fvg_df["MitigatedIndex"].iloc[i]
            if not pd.isna(mitigated) and float(mitigated) > 0:
                continue

            # Validate boundaries
            if pd.isna(top) or pd.isna(bottom) or top <= bottom:
                continue

            direction = "long" if int(fvg_val) == 1 else "short"

            # Check if current price is inside or within 25% of gap height
            gap_height = top - bottom
            tolerance = gap_height * 0.25

            price_inside_or_near = (
                (bottom - tolerance) <= current_price <= (top + tolerance)
            )

            # For longs, price should be retracing DOWN into a bullish FVG
            # For shorts, price should be retracing UP into a bearish FVG
            if price_inside_or_near:
                active.append({
                    "direction": direction,
                    "top": top,
                    "bottom": bottom,
                    "bar_index": i,
                    "gap_height": gap_height,
                })
        except (IndexError, KeyError, ValueError, TypeError):
            continue

    return active


# ---------------------------------------------------------------------------
# 3. _detect_active_obs
# ---------------------------------------------------------------------------

def _detect_active_obs(
    ob_df: pd.DataFrame,
    current_price: float,
    lookback: int = 20,
) -> List[Dict]:
    """Find unmitigated order blocks within *lookback* bars where price is
    inside or near the block.

    Returns a list of dicts with keys: direction, top, bottom, bar_index, volume.
    """
    if ob_df is None or ob_df.empty:
        return []

    active: List[Dict] = []
    n = len(ob_df)
    start = max(0, n - lookback)

    for i in range(start, n):
        try:
            ob_val = ob_df["OB"].iloc[i]
            if pd.isna(ob_val) or ob_val == 0:
                continue

            top = float(ob_df["Top"].iloc[i])
            bottom = float(ob_df["Bottom"].iloc[i])

            if pd.isna(top) or pd.isna(bottom) or top <= bottom:
                continue

            direction = "long" if int(ob_val) == 1 else "short"

            ob_height = top - bottom
            tolerance = ob_height * 0.25

            price_inside_or_near = (
                (bottom - tolerance) <= current_price <= (top + tolerance)
            )

            if price_inside_or_near:
                ob_volume = 0.0
                try:
                    ob_volume = float(ob_df["OBVolume"].iloc[i])
                except (KeyError, ValueError, TypeError):
                    pass

                active.append({
                    "direction": direction,
                    "top": top,
                    "bottom": bottom,
                    "bar_index": i,
                    "volume": ob_volume,
                })
        except (IndexError, KeyError, ValueError, TypeError):
            continue

    return active


# ---------------------------------------------------------------------------
# 4. _check_smc_signal  (main entry point)
# ---------------------------------------------------------------------------

def _check_smc_signal(
    df: pd.DataFrame,
    ind: Any,
    params: Any,
    current_time: datetime,
) -> Optional[Dict]:
    """Check for an SMC-based entry signal.

    Signature matches ``_check_orb_signal`` / ``_check_vwap_2sd_signal`` in
    pearl_bot_auto.py so it can be wired in identically.

    Returns a signal dict or None.
    """
    # ------------------------------------------------------------------
    # Guard: feature flag
    # ------------------------------------------------------------------
    if not _param(params, "allow_smc_entries", False):
        return None

    # ------------------------------------------------------------------
    # Guard: library available
    # ------------------------------------------------------------------
    smc_lib = _get_smc()
    if smc_lib is None:
        return None

    # ------------------------------------------------------------------
    # Guard: Silver Bullet window check
    # ------------------------------------------------------------------
    sb_windows = _param(params, "smc_silver_bullet_windows", _DEFAULT_SB_WINDOWS)
    if not _in_silver_bullet_window(current_time, sb_windows):
        return None

    # ------------------------------------------------------------------
    # Prepare data
    # ------------------------------------------------------------------
    ohlc = _prepare_ohlc(df)
    if ohlc is None:
        return None

    swing_length = _param(params, "smc_swing_length", 10)
    fvg_lookback = _param(params, "smc_fvg_lookback", 20)
    ob_lookback = _param(params, "smc_ob_lookback", 20)

    # Ensure enough data for swing detection
    if len(ohlc) < swing_length + 5:
        return None

    # ------------------------------------------------------------------
    # Run SMC detections (each wrapped individually)
    # ------------------------------------------------------------------
    swing_hl = _safe_smc_call(smc_lib.swing_highs_lows, ohlc, swing_length=swing_length)
    if swing_hl is None or swing_hl.empty:
        return None

    fvg_df = _safe_smc_call(smc_lib.fvg, ohlc, join_consecutive=False)
    bos_choch = _safe_smc_call(smc_lib.bos_choch, ohlc, swing_hl, close_break=True)
    ob_df = _safe_smc_call(smc_lib.ob, ohlc, swing_hl, close_mitigation=False)
    liq_df = _safe_smc_call(smc_lib.liquidity, ohlc, swing_hl, range_percent=0.01)

    # ------------------------------------------------------------------
    # Current price from indicator context (most recent)
    # ------------------------------------------------------------------
    try:
        current_price = float(ind.close)
    except (AttributeError, TypeError, ValueError):
        current_price = float(ohlc["close"].iloc[-1])

    atr = _safe_atr(ind)
    if atr is None or atr <= 0:
        return None

    # ------------------------------------------------------------------
    # Detect active (unmitigated) FVGs
    # ------------------------------------------------------------------
    active_fvgs = _detect_active_fvgs(fvg_df, current_price, lookback=fvg_lookback)
    if not active_fvgs:
        return None

    # ------------------------------------------------------------------
    # Pick the best FVG (closest to price)
    # ------------------------------------------------------------------
    best_fvg = _pick_best_fvg(active_fvgs, current_price)
    if best_fvg is None:
        return None

    direction = best_fvg["direction"]

    # ------------------------------------------------------------------
    # Build confidence & indicator list
    # ------------------------------------------------------------------
    base_conf = _param(params, "smc_fvg_base_confidence", 0.55)
    confidence = base_conf
    active_indicators: List[str] = [f"FVG_{direction.upper()}"]

    # OB confluence: FVG zone overlaps an OB zone in same direction
    active_obs = _detect_active_obs(ob_df, current_price, lookback=ob_lookback)
    has_ob_confluence = _check_ob_confluence(best_fvg, active_obs)
    if has_ob_confluence:
        confidence += _param(params, "smc_ob_boost", 0.10)
        active_indicators.append("OB_CONFLUENCE")

    # BOS / CHoCH confirmation
    if _check_bos_choch_confirmation(bos_choch, direction):
        confidence += _param(params, "smc_bos_boost", 0.08)
        active_indicators.append(f"BOS_CHOCH_{direction.upper()}")

    # Volume confirmation (from existing indicators)
    try:
        if ind.volume_confirmed:
            confidence += _param(params, "smc_volume_boost", 0.08)
            active_indicators.append("VOL_CONFIRM")
    except AttributeError:
        pass

    # Key level alignment
    try:
        key_levels = ind.key_levels
        if key_levels and _check_key_level_alignment(key_levels, current_price, atr):
            confidence += _param(params, "smc_key_level_boost", 0.10)
            active_indicators.append("KEY_LEVEL_ALIGN")
    except AttributeError:
        pass

    # VWAP alignment
    try:
        vwap_val = ind.vwap_val
        if vwap_val is not None:
            vwap_aligned = (
                (direction == "long" and current_price > vwap_val)
                or (direction == "short" and current_price < vwap_val)
            )
            if vwap_aligned:
                confidence += _param(params, "smc_vwap_boost", 0.05)
                active_indicators.append("VWAP_ALIGNED")
    except AttributeError:
        pass

    # Cap confidence
    confidence = float(min(confidence, 0.99))

    # ------------------------------------------------------------------
    # SL / TP calculation
    # ------------------------------------------------------------------
    sl_atr_mult = _param(params, "smc_sl_atr_mult", 0.8)
    tp_atr_mult = _param(params, "smc_tp_atr_mult", 2.5)

    fvg_top = best_fvg["top"]
    fvg_bottom = best_fvg["bottom"]

    if direction == "long":
        # Entry at bottom of FVG (retracement into gap)
        entry_price = current_price
        stop_loss = fvg_bottom - (sl_atr_mult * atr)
        # TP: next liquidity level above, or ATR-based
        tp_target = _find_liquidity_target(liq_df, direction, current_price)
        take_profit = tp_target if tp_target is not None else entry_price + (tp_atr_mult * atr)
    else:
        entry_price = current_price
        stop_loss = fvg_top + (sl_atr_mult * atr)
        tp_target = _find_liquidity_target(liq_df, direction, current_price)
        take_profit = tp_target if tp_target is not None else entry_price - (tp_atr_mult * atr)

    # Validate SL/TP sanity
    sl_distance = abs(entry_price - stop_loss)
    tp_distance = abs(take_profit - entry_price)

    if sl_distance <= 0 or tp_distance <= 0:
        return None

    risk_reward = tp_distance / sl_distance

    # Determine signal type
    signal_type = "smc_fvg"
    if has_ob_confluence:
        signal_type = "smc_ob"
    if _in_silver_bullet_window(current_time, sb_windows):
        # If inside SB window AND has confluence, upgrade to silver bullet
        if has_ob_confluence or len(active_indicators) >= 3:
            signal_type = "smc_silver_bullet"

    return {
        "direction": direction,
        "entry_price": float(entry_price),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "confidence": confidence,
        "risk_reward": float(risk_reward),
        "signal_type": signal_type,
        "active_indicators": active_indicators,
        "signal_source": "smc",
        # Fields matching pearl_bot_auto signal dict convention
        "reason": (
            f"SMC_{direction.upper()}[{len(active_indicators)}]: "
            + " | ".join(active_indicators)
        ),
        "indicators": {
            "active_count": len(active_indicators),
            "active_list": active_indicators,
            "entry_trigger": signal_type,
            "fvg_top": fvg_top,
            "fvg_bottom": fvg_bottom,
            "ob_confluence": has_ob_confluence,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_smc_call(fn, *args, **kwargs):
    """Call a smartmoneyconcepts function, returning None on any error."""
    try:
        result = fn(*args, **kwargs)
        if result is None:
            return None
        if isinstance(result, pd.DataFrame) and result.empty:
            return result
        return result
    except Exception as exc:
        logger.warning("SMC library call %s failed: %s", getattr(fn, "__name__", "?"), exc)
        return None


def _safe_atr(ind: Any) -> Optional[float]:
    """Extract ATR from indicator context, returning None on failure."""
    try:
        atr = float(ind.atr)
        if pd.isna(atr) or atr <= 0:
            return None
        return atr
    except (AttributeError, TypeError, ValueError):
        return None


def _in_silver_bullet_window(
    current_time: datetime,
    windows: List[List[int]],
) -> bool:
    """Check if current_time falls within any Silver Bullet window (ET)."""
    try:
        ct_et = (
            current_time.astimezone(_ET)
            if current_time.tzinfo
            else current_time.replace(tzinfo=_ET)
        )
        hour = ct_et.hour
        for window in windows:
            if len(window) >= 2 and window[0] <= hour < window[1]:
                return True
        return False
    except Exception:
        return False


def _pick_best_fvg(fvgs: List[Dict], current_price: float) -> Optional[Dict]:
    """Pick the FVG whose midpoint is closest to current price."""
    if not fvgs:
        return None

    best = None
    best_dist = float("inf")
    for fvg in fvgs:
        mid = (fvg["top"] + fvg["bottom"]) / 2.0
        dist = abs(current_price - mid)
        if dist < best_dist:
            best_dist = dist
            best = fvg

    return best


def _check_ob_confluence(fvg: Dict, active_obs: List[Dict]) -> bool:
    """Check if the FVG zone overlaps with an OB zone in the same direction."""
    if not active_obs:
        return False

    fvg_top = fvg["top"]
    fvg_bottom = fvg["bottom"]
    fvg_dir = fvg["direction"]

    for ob in active_obs:
        if ob["direction"] != fvg_dir:
            continue
        # Check overlap: two ranges overlap if one starts before the other ends
        ob_top = ob["top"]
        ob_bottom = ob["bottom"]
        if fvg_bottom <= ob_top and ob_bottom <= fvg_top:
            return True

    return False


def _check_bos_choch_confirmation(
    bos_choch_df: Optional[pd.DataFrame],
    direction: str,
) -> bool:
    """Check if a recent BOS or CHoCH confirms the signal direction.

    Looks at the last 5 bars for a structure break in the signal direction.
    """
    if bos_choch_df is None or bos_choch_df.empty:
        return False

    target_val = 1 if direction == "long" else -1
    lookback = min(5, len(bos_choch_df))

    for i in range(len(bos_choch_df) - lookback, len(bos_choch_df)):
        try:
            bos = bos_choch_df["BOS"].iloc[i]
            choch = bos_choch_df["CHOCH"].iloc[i]
            if (not pd.isna(bos) and int(bos) == target_val) or (
                not pd.isna(choch) and int(choch) == target_val
            ):
                return True
        except (IndexError, KeyError, ValueError, TypeError):
            continue

    return False


def _check_key_level_alignment(
    key_levels: Dict[str, Optional[float]],
    current_price: float,
    atr: float,
) -> bool:
    """Check if price is near a key level (within 1.5 ATR)."""
    threshold = atr * 1.5
    for _name, level in key_levels.items():
        if level is not None:
            try:
                if abs(current_price - float(level)) <= threshold:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _find_liquidity_target(
    liq_df: Optional[pd.DataFrame],
    direction: str,
    current_price: float,
) -> Optional[float]:
    """Find the next unswept liquidity level in the signal direction.

    For longs: find the nearest liquidity level ABOVE current price.
    For shorts: find the nearest liquidity level BELOW current price.

    Returns None if no suitable level found.
    """
    if liq_df is None or liq_df.empty:
        return None

    best_level: Optional[float] = None
    best_dist = float("inf")

    for i in range(len(liq_df)):
        try:
            liq_val = liq_df["Liquidity"].iloc[i]
            if pd.isna(liq_val) or liq_val == 0:
                continue

            level = float(liq_df["Level"].iloc[i])
            if pd.isna(level):
                continue

            # Skip swept levels
            swept = liq_df["Swept"].iloc[i]
            if not pd.isna(swept) and float(swept) > 0:
                continue

            if direction == "long" and level > current_price:
                dist = level - current_price
                if dist < best_dist:
                    best_dist = dist
                    best_level = level
            elif direction == "short" and level < current_price:
                dist = current_price - level
                if dist < best_dist:
                    best_dist = dist
                    best_level = level
        except (IndexError, KeyError, ValueError, TypeError):
            continue

    return best_level
