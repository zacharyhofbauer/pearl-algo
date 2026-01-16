"""
VWAP (Volume-Weighted Average Price) Calculator

Calculates session VWAP and VWAP bands for intraday trading.
VWAP is the most important intraday level - institutions measure
performance against it.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger

# Timezone handling
try:
    from zoneinfo import ZoneInfo
    ET_TIMEZONE = ZoneInfo("America/New_York")
except ImportError:
    try:
        import pytz
        ET_TIMEZONE = pytz.timezone("America/New_York")
    except ImportError:
        ET_TIMEZONE = None


class VWAPCalculator:
    """
    Calculates VWAP (Volume-Weighted Average Price) for the trading session.
    
    VWAP is calculated from session open (9:30 ET) and resets each day.
    VWAP bands (VWAP ± 1 ATR, VWAP ± 2 ATR) provide support/resistance levels.
    """

    def __init__(self):
        """Initialize VWAP calculator."""
        self._session_vwap: Optional[float] = None
        self._session_start: Optional[datetime] = None
        self._cumulative_volume_price: float = 0.0
        self._cumulative_volume: float = 0.0
        logger.info("VWAPCalculator initialized")

    def calculate_vwap(
        self,
        df: pd.DataFrame,
        atr: Optional[float] = None,
        dt: Optional[datetime] = None,
    ) -> Dict:
        """
        Calculate session VWAP and VWAP bands.
        
        Args:
            df: DataFrame with OHLCV data (must have timestamp or index)
            atr: Current ATR value for VWAP bands (optional)
            dt: Reference timestamp for session alignment (UTC). When provided (e.g. backtests),
                VWAP session start is computed for this timestamp's date instead of wall-clock "now".
            
        Returns:
            Dictionary with VWAP data:
            {
                "vwap": float,
                "vwap_upper_1": float,  # VWAP + 1 ATR
                "vwap_upper_2": float,  # VWAP + 2 ATR
                "vwap_lower_1": float,  # VWAP - 1 ATR
                "vwap_lower_2": float,  # VWAP - 2 ATR
                "distance_from_vwap": float,  # Current price distance from VWAP
                "distance_pct": float,  # Distance as percentage
            }
        """
        if df.empty:
            return self._default_vwap()

        # Get session start (9:30 ET) for the reference datetime (or "now" if not provided).
        session_start = self._get_session_start(dt=dt)

        # Check if we need to reset (new session)
        if self._session_start is None or session_start.date() != self._session_start.date():
            self._reset_session()
            self._session_start = session_start

        # Filter data to current session (from 9:30 ET)
        df_session = self._filter_session_data(df, session_start)

        if df_session.empty:
            return self._default_vwap()

        # Calculate VWAP
        # VWAP = Sum(Price * Volume) / Sum(Volume)
        # Use typical price: (High + Low + Close) / 3
        df_session = df_session.copy()
        df_session["typical_price"] = (
            df_session["high"] + df_session["low"] + df_session["close"]
        ) / 3

        # Cumulative volume-weighted price
        df_session["volume_price"] = df_session["typical_price"] * df_session["volume"]

        cumulative_volume_price = df_session["volume_price"].sum()
        cumulative_volume = df_session["volume"].sum()

        if cumulative_volume > 0:
            vwap = cumulative_volume_price / cumulative_volume
        else:
            vwap = df_session["close"].iloc[-1]  # Fallback to last close

        # Update session totals
        self._cumulative_volume_price = cumulative_volume_price
        self._cumulative_volume = cumulative_volume
        self._session_vwap = vwap

        # Get current price
        current_price = df_session["close"].iloc[-1]

        # Calculate VWAP bands if ATR provided
        vwap_upper_1 = vwap
        vwap_upper_2 = vwap
        vwap_lower_1 = vwap
        vwap_lower_2 = vwap

        if atr and atr > 0:
            vwap_upper_1 = vwap + atr
            vwap_upper_2 = vwap + (atr * 2)
            vwap_lower_1 = vwap - atr
            vwap_lower_2 = vwap - (atr * 2)

        # Calculate distance from VWAP
        distance_from_vwap = current_price - vwap
        distance_pct = (distance_from_vwap / vwap) * 100 if vwap > 0 else 0.0

        return {
            "vwap": float(vwap),
            "vwap_upper_1": float(vwap_upper_1),
            "vwap_upper_2": float(vwap_upper_2),
            "vwap_lower_1": float(vwap_lower_1),
            "vwap_lower_2": float(vwap_lower_2),
            "distance_from_vwap": float(distance_from_vwap),
            "distance_pct": float(distance_pct),
            "current_price": float(current_price),
        }

    def _get_session_start(self, dt: Optional[datetime] = None) -> datetime:
        """Get session start (9:30 ET) for the date of `dt` (defaults to now)."""
        now = dt or datetime.now(timezone.utc)
        if isinstance(now, pd.Timestamp):
            now = now.to_pydatetime()
        if now.tzinfo is None:
            # This project treats tz-naive timestamps as UTC.
            now = now.replace(tzinfo=timezone.utc)

        # Convert to ET
        if ET_TIMEZONE is not None:
            if now.tzinfo != timezone.utc:
                now_utc = now.astimezone(timezone.utc)
            else:
                now_utc = now
            et_dt = now_utc.astimezone(ET_TIMEZONE)
        else:
            from datetime import timedelta
            et_dt = now + timedelta(hours=-5)

        # Set to 9:30 ET today
        session_start = et_dt.replace(hour=9, minute=30, second=0, microsecond=0)

        # Convert back to UTC for comparison
        if ET_TIMEZONE is not None:
            session_start_utc = session_start.astimezone(timezone.utc)
        else:
            session_start_utc = session_start.replace(tzinfo=timezone.utc)

        return session_start_utc

    def _filter_session_data(self, df: pd.DataFrame, session_start: datetime) -> pd.DataFrame:
        """
        Filter DataFrame to current session data (from 9:30 ET).
        
        Args:
            df: DataFrame with OHLCV data
            session_start: Session start datetime (UTC)
            
        Returns:
            Filtered DataFrame
        """
        if df.empty:
            return df

        # Pandas will raise on tz-naive vs tz-aware comparisons.
        # This project generally treats tz-naive timestamps as UTC (see scanner backtest handling),
        # so we normalize `session_start` accordingly for safe comparisons.
        ss = pd.Timestamp(session_start)
        if ss.tz is None:
            ss_utc = ss.tz_localize(timezone.utc)
        else:
            ss_utc = ss.tz_convert(timezone.utc)
        ss_naive_utc = ss_utc.tz_localize(None)

        # Check if DataFrame has timestamp column or uses index
        if "timestamp" in df.columns:
            ts = df["timestamp"]

            # If timestamp column is not datetime-like, coerce to UTC (best-effort).
            if not pd.api.types.is_datetime64_any_dtype(ts):
                try:
                    ts = pd.to_datetime(ts, errors="coerce", utc=True)
                except Exception:
                    ts = None

            if ts is None:
                logger.warning(
                    "DataFrame timestamp column is not datetime-like; skipping session filter for VWAP"
                )
                return df.copy()

            # Align session_start timezone awareness with the series.
            # - tz-aware series: compare against UTC-aware session start
            # - tz-naive series: compare against tz-naive UTC session start
            tz = getattr(getattr(ts, "dt", None), "tz", None)
            ss_cmp = ss_utc if tz is not None else ss_naive_utc

            # Filter by timestamp
            df_filtered = df[ts >= ss_cmp].copy()
        elif isinstance(df.index, pd.DatetimeIndex) or df.index.name == "timestamp":
            # Filter by index
            idx = df.index
            if isinstance(idx, pd.DatetimeIndex) and idx.tz is None:
                ss_cmp = ss_naive_utc
            elif isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
                ss_cmp = ss_utc.tz_convert(idx.tz)
            else:
                # Non-datetime index marked as timestamp: fall back to copying.
                logger.warning(
                    "DataFrame index is not a DatetimeIndex; skipping session filter for VWAP"
                )
                return df.copy()

            df_filtered = df[idx >= ss_cmp].copy()
        else:
            # No timestamp - assume all data is from current session
            # (This is a fallback, ideally data should have timestamps)
            logger.warning("DataFrame has no timestamp column/index, assuming all data is from current session")
            df_filtered = df.copy()

        return df_filtered

    def _reset_session(self):
        """Reset session totals for new trading day."""
        self._cumulative_volume_price = 0.0
        self._cumulative_volume = 0.0
        self._session_vwap = None
        logger.debug("VWAP session reset")

    def _default_vwap(self) -> Dict:
        """Return default VWAP when data is insufficient."""
        return {
            "vwap": 0.0,
            "vwap_upper_1": 0.0,
            "vwap_upper_2": 0.0,
            "vwap_lower_1": 0.0,
            "vwap_lower_2": 0.0,
            "distance_from_vwap": 0.0,
            "distance_pct": 0.0,
            "current_price": 0.0,
        }

    def adjust_confidence_by_vwap(
        self,
        signal_direction: str,
        signal_confidence: float,
        vwap_data: Dict,
    ) -> float:
        """
        Adjust signal confidence based on VWAP position.
        
        Args:
            signal_direction: "long" or "short"
            signal_confidence: Base signal confidence (0-1)
            vwap_data: VWAP data from calculate_vwap()
            
        Returns:
            Adjusted confidence (0-1)
        """
        vwap = vwap_data.get("vwap", 0)
        current_price = vwap_data.get("current_price", 0)
        distance_pct = vwap_data.get("distance_pct", 0)

        if vwap == 0 or current_price == 0:
            return signal_confidence  # No adjustment if VWAP not available

        adjusted = signal_confidence

        if signal_direction == "long":
            if current_price > vwap:
                # Long above VWAP - institutional support
                if distance_pct > 0.1:  # More than 0.1% above
                    adjusted += 0.10
                else:
                    adjusted += 0.05
            else:
                # Long below VWAP - fighting institutions
                if distance_pct < -0.1:  # More than 0.1% below
                    adjusted -= 0.10
                else:
                    adjusted -= 0.05

            # Breakout above VWAP gets extra boost
            if distance_pct > 0.05 and distance_pct < 0.2:
                adjusted += 0.05  # Just broke above VWAP

        elif signal_direction == "short":
            if current_price < vwap:
                # Short below VWAP - institutional support
                if distance_pct < -0.1:  # More than 0.1% below
                    adjusted += 0.10
                else:
                    adjusted += 0.05
            else:
                # Short above VWAP - fighting institutions
                if distance_pct > 0.1:  # More than 0.1% above
                    adjusted -= 0.10
                else:
                    adjusted -= 0.05

        # Clamp to [0, 1]
        return max(0.0, min(1.0, adjusted))









