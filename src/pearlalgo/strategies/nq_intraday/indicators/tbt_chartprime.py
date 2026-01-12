"""
Trendline Breakouts With Targets (TBT) [ChartPrime] - PineScript Port

Source PineScript:
  "Trendline Breakouts With Targets [ Chartprime ]"
  © ChartPrime
  MPL 2.0: https://mozilla.org/MPL/2.0/

This is a best-effort Python/pandas port of the core logic used by the Pine indicator:
- Pivot-based trendline construction (pivot highs for bearish line, pivot lows for bullish line)
- Breakout detection on close crossing the active trendline
- Target/stop projection based on a volatility-adjusted band ("Zband")

Notes / Differences vs Pine:
- Pine uses `time` in milliseconds; this port uses tz-aware pandas timestamps converted to seconds.
- Pine shifts Zband by 20 bars: `base[20] / 2`. We preserve the shift when possible and fall back
  to the unshifted value when the series is too short.
- Pine uses an internal `TradeisON` state to prevent new trades while in a trade. This framework
  is stateless at the indicator level; the surrounding system handles de-duping and trade lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pearlalgo.strategies.nq_intraday.indicators.base import IndicatorBase, IndicatorSignal


@dataclass(frozen=True)
class _Trendline:
    start_time: pd.Timestamp
    start_price: float
    end_time: pd.Timestamp
    end_price: float
    slope_per_sec: float
    updated_idx: int  # index in df where the last pivot was confirmed (detection bar)

    def value_at(self, ts: pd.Timestamp) -> float:
        dt = (ts - self.start_time).total_seconds()
        return float(self.start_price + dt * self.slope_per_sec)


class TBTChartPrime(IndicatorBase):
    """
    ChartPrime TBT (Trendline Breakouts with Targets).

    Config:
    - period: pivot lookback period (Pine default: 10)
    - trend_type: "wicks" or "body" (Pine default: wicks)
    - atr_len: ATR length used in volAdj (Pine uses 30 inside volAdj(30))
    - zband_shift: bars to shift Zband (Pine uses [20])
    - zband_atr_mult: multiplier for ATR inside volAdj (Pine uses 0.3)
    - zband_close_pct: cap as pct of close inside volAdj (Pine uses 0.3%)
    - breakout_buffer_mult: buffer used on short cross (Pine uses Zband*0.1)
    - target_mult: multiplier for TP/SL distances (Pine uses Zband*20)
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.period = int(self.config.get("period", 10))
        self.trend_type = str(self.config.get("trend_type", "wicks")).strip().lower()
        self.atr_len = int(self.config.get("atr_len", 30))
        self.zband_shift = int(self.config.get("zband_shift", 20))
        self.zband_atr_mult = float(self.config.get("zband_atr_mult", 0.3))
        self.zband_close_pct = float(self.config.get("zband_close_pct", 0.003))
        self.breakout_buffer_mult = float(self.config.get("breakout_buffer_mult", 0.1))
        self.target_mult = float(self.config.get("target_mult", 20.0))

    @property
    def name(self) -> str:
        return "tbt_chartprime"

    @property
    def description(self) -> str:
        return "ChartPrime TBT trendline breakouts with TP/SL targets (Pine port)"

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate_dataframe(df):
            return df
        df = self.normalize_columns(df)
        df = df.copy()

        # Ensure we have a usable timestamp series.
        ts = self._get_ts(df)
        if ts is None:
            # Can't compute time-based slopes; still add columns so the pipeline stays stable.
            return self._add_empty_columns(df)

        # Zband (volAdj) — Pine: min(ATR(len)*0.3, close*0.3%)[20]/2
        close = pd.to_numeric(df["close"], errors="coerce")
        atr = self._atr(df, period=self.atr_len)
        base = np.minimum(atr * self.zband_atr_mult, close * self.zband_close_pct)
        zband = base.shift(self.zband_shift) / 2.0
        # Fallback (short history): use unshifted base/2
        zband = zband.fillna(base / 2.0)
        df["tbt_zband"] = zband

        # Pivot points (confirmed right bars later, Pine-style)
        p = int(max(2, self.period))
        right = max(1, p // 2)
        left = p

        hi_src, lo_src = self._select_pivot_sources(df, mode=self.trend_type)
        df["tbt_pivoth"] = self._pivot_high(hi_src, left=left, right=right)
        df["tbt_pivotl"] = self._pivot_low(lo_src, left=left, right=right)

        return df

    def as_features(self, latest: pd.Series, df: Optional[pd.DataFrame] = None) -> Dict[str, float]:
        if df is None or df.empty:
            return self._default_features()

        try:
            close = float(latest.get("close", 0.0) or 0.0)
            if close <= 0:
                return self._default_features()
        except Exception:
            return self._default_features()

        feats: Dict[str, float] = {}

        # Zband (volatility proxy)
        try:
            z = float(latest.get("tbt_zband", 0.0) or 0.0)
            feats["tbt_zband"] = z
            feats["tbt_zband_pct"] = (z / close) if close > 0 else 0.0
        except Exception:
            feats["tbt_zband"] = 0.0
            feats["tbt_zband_pct"] = 0.0

        ts = self._get_ts(df)
        if ts is None or len(df) < 3:
            feats.update(self._default_features())
            feats.update({"tbt_zband": feats.get("tbt_zband", 0.0), "tbt_zband_pct": feats.get("tbt_zband_pct", 0.0)})
            return feats

        # Trendline distances (if available)
        bearish = self._latest_trendline(df, ts=ts, pivot_col="tbt_pivoth", direction="bearish")
        bullish = self._latest_trendline(df, ts=ts, pivot_col="tbt_pivotl", direction="bullish")

        last_ts = ts.iloc[-1]
        if bearish is not None:
            y = bearish.value_at(last_ts)
            feats["tbt_bear_line_dist"] = (close - y) / max(close, 1e-9)
            feats["tbt_bear_slope"] = float(np.tanh(bearish.slope_per_sec * 60.0))  # scale to ~per-minute then squash
        else:
            feats["tbt_bear_line_dist"] = 0.0
            feats["tbt_bear_slope"] = 0.0

        if bullish is not None:
            y = bullish.value_at(last_ts)
            feats["tbt_bull_line_dist"] = (close - y) / max(close, 1e-9)
            feats["tbt_bull_slope"] = float(np.tanh(bullish.slope_per_sec * 60.0))
        else:
            feats["tbt_bull_line_dist"] = 0.0
            feats["tbt_bull_slope"] = 0.0

        return feats

    def generate_signal(
        self,
        latest: pd.Series,
        df: pd.DataFrame,
        atr: Optional[float] = None,
    ) -> Optional[IndicatorSignal]:
        """
        Generate a breakout signal when close crosses the active trendline.

        Signal types:
        - tbt_breakout_long
        - tbt_breakout_short
        """
        if df is None or df.empty or len(df) < 5:
            return None

        # Require computed columns
        if "tbt_zband" not in df.columns:
            return None

        ts = self._get_ts(df)
        if ts is None or len(ts) < 3:
            return None

        # Current bar values
        try:
            close_now = float(latest.get("close", 0.0) or 0.0)
            close_prev = float(df.iloc[-2].get("close", 0.0) or 0.0)
            high_now = float(latest.get("high", 0.0) or 0.0)
            low_now = float(latest.get("low", 0.0) or 0.0)
            zband = float(latest.get("tbt_zband", 0.0) or 0.0)
        except Exception:
            return None

        if close_now <= 0 or high_now <= 0 or low_now <= 0 or zband <= 0:
            return None

        p = int(max(2, self.period))

        # Build latest bearish (pivot highs) and bullish (pivot lows) lines
        bearish = self._latest_trendline(df, ts=ts, pivot_col="tbt_pivoth", direction="bearish")
        bullish = self._latest_trendline(df, ts=ts, pivot_col="tbt_pivotl", direction="bullish")

        # Pine-style "line is fresh" gate: StartPrice[Period] != StartPrice → allow only for <period bars
        def _fresh(line: _Trendline) -> bool:
            try:
                bars_since_update = int((len(df) - 1) - int(line.updated_idx))
            except Exception:
                return False
            return bars_since_update < p

        last_ts = ts.iloc[-1]
        prev_ts = ts.iloc[-2]

        # Long breakout (cross above bearish line, slope <= 0)
        if bearish is not None and bearish.slope_per_sec <= 0 and _fresh(bearish):
            prev_line = bearish.value_at(prev_ts)
            curr_line = bearish.value_at(last_ts)
            if close_prev < prev_line and close_now > curr_line:
                tp = high_now + (zband * self.target_mult)
                sl = low_now - (zband * self.target_mult)
                return IndicatorSignal(
                    type="tbt_breakout_long",
                    direction="long",
                    confidence=0.70,
                    entry_price=close_now,
                    stop_loss=float(sl),
                    take_profit=float(tp),
                    reason="TBT breakout: close crossed above bearish trendline",
                    metadata={
                        "zband": zband,
                        "line_start": bearish.start_time.isoformat(),
                        "line_end": bearish.end_time.isoformat(),
                        "line_slope_per_sec": bearish.slope_per_sec,
                    },
                )

        # Short breakout (cross below bullish line, slope >= 0) with buffer (Zband*0.1)
        if bullish is not None and bullish.slope_per_sec >= 0 and _fresh(bullish):
            prev_line = bullish.value_at(prev_ts)
            curr_line = bullish.value_at(last_ts)
            buf = zband * float(self.breakout_buffer_mult)
            if (close_prev > (prev_line - buf)) and (close_now < (curr_line - buf)):
                tp = low_now - (zband * self.target_mult)
                sl = high_now + (zband * self.target_mult)
                return IndicatorSignal(
                    type="tbt_breakout_short",
                    direction="short",
                    confidence=0.70,
                    entry_price=close_now,
                    stop_loss=float(sl),
                    take_profit=float(tp),
                    reason="TBT breakout: close crossed below bullish trendline",
                    metadata={
                        "zband": zband,
                        "line_start": bullish.start_time.isoformat(),
                        "line_end": bullish.end_time.isoformat(),
                        "line_slope_per_sec": bullish.slope_per_sec,
                        "buffer": buf,
                    },
                )

        return None

    def get_signal_types(self) -> List[str]:
        return ["tbt_breakout_long", "tbt_breakout_short"]

    # -----------------
    # Implementation helpers
    # -----------------

    @staticmethod
    def _get_ts(df: pd.DataFrame) -> Optional[pd.Series]:
        try:
            if "timestamp" in df.columns:
                ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
                return ts
            if isinstance(df.index, pd.DatetimeIndex):
                ts = pd.to_datetime(pd.Series(df.index, index=df.index), errors="coerce", utc=True)
                return ts
        except Exception:
            return None
        return None

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(window=max(2, int(period)), min_periods=2).mean()

    @staticmethod
    def _pivot_high(src: pd.Series, *, left: int, right: int) -> pd.Series:
        arr = pd.to_numeric(src, errors="coerce").to_numpy(dtype=float)
        n = len(arr)
        out = np.full(n, np.nan, dtype=float)
        left = int(max(1, left))
        right = int(max(1, right))

        for i in range(left + right, n):
            pivot_idx = i - right
            a = pivot_idx - left
            b = pivot_idx + right + 1
            if a < 0 or b > n:
                continue
            window = arr[a:b]
            pv = arr[pivot_idx]
            if not np.isfinite(pv):
                continue
            mx = np.nanmax(window)
            if not np.isfinite(mx):
                continue
            # Pine pivots are strict; prefer uniqueness to reduce duplicates.
            if pv == mx and np.sum(window == pv) == 1:
                out[i] = pv

        return pd.Series(out, index=src.index)

    @staticmethod
    def _pivot_low(src: pd.Series, *, left: int, right: int) -> pd.Series:
        arr = pd.to_numeric(src, errors="coerce").to_numpy(dtype=float)
        n = len(arr)
        out = np.full(n, np.nan, dtype=float)
        left = int(max(1, left))
        right = int(max(1, right))

        for i in range(left + right, n):
            pivot_idx = i - right
            a = pivot_idx - left
            b = pivot_idx + right + 1
            if a < 0 or b > n:
                continue
            window = arr[a:b]
            pv = arr[pivot_idx]
            if not np.isfinite(pv):
                continue
            mn = np.nanmin(window)
            if not np.isfinite(mn):
                continue
            if pv == mn and np.sum(window == pv) == 1:
                out[i] = pv

        return pd.Series(out, index=src.index)

    @staticmethod
    def _select_pivot_sources(df: pd.DataFrame, *, mode: str) -> Tuple[pd.Series, pd.Series]:
        """
        Pine:
          PH source = Trendtype ? high : (close>open ? close : open)
          PL source = Trendtype ? low  : (close>open ? open : close)
        """
        mode = (mode or "wicks").strip().lower()
        o = pd.to_numeric(df["open"], errors="coerce")
        c = pd.to_numeric(df["close"], errors="coerce")
        h = pd.to_numeric(df["high"], errors="coerce")
        l = pd.to_numeric(df["low"], errors="coerce")

        if mode in ("wicks", "wick"):
            return h, l

        # Body mode
        hi_src = c.where(c > o, o)
        lo_src = o.where(c > o, c)
        return hi_src, lo_src

    def _latest_trendline(
        self,
        df: pd.DataFrame,
        *,
        ts: pd.Series,
        pivot_col: str,
        direction: str,
    ) -> Optional[_Trendline]:
        if pivot_col not in df.columns:
            return None
        piv = pd.to_numeric(df[pivot_col], errors="coerce")
        idxs = np.where(np.isfinite(piv.to_numpy(dtype=float)))[0]
        if idxs is None or len(idxs) < 2:
            return None

        p = int(max(2, self.period))
        right = max(1, p // 2)

        i_prev = int(idxs[-2])
        i_curr = int(idxs[-1])

        # Pivot time is time[right] on detection bar → detection_idx - right
        prev_pivot_idx = max(0, i_prev - right)
        curr_pivot_idx = max(0, i_curr - right)

        try:
            t1 = pd.Timestamp(ts.iloc[prev_pivot_idx])
            t2 = pd.Timestamp(ts.iloc[curr_pivot_idx])
        except Exception:
            return None

        if pd.isna(t1) or pd.isna(t2):
            return None

        y1 = float(piv.iloc[i_prev])
        y2 = float(piv.iloc[i_curr])

        dt = (t2 - t1).total_seconds()
        if dt == 0:
            slope = 0.0
        else:
            slope = float((y2 - y1) / dt)

        return _Trendline(
            start_time=t1,
            start_price=y1,
            end_time=t2,
            end_price=y2,
            slope_per_sec=slope,
            updated_idx=i_curr,
        )

    def _add_empty_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["tbt_zband"] = np.nan
        df["tbt_pivoth"] = np.nan
        df["tbt_pivotl"] = np.nan
        return df

    @staticmethod
    def _default_features() -> Dict[str, float]:
        return {
            "tbt_zband": 0.0,
            "tbt_zband_pct": 0.0,
            "tbt_bear_line_dist": 0.0,
            "tbt_bear_slope": 0.0,
            "tbt_bull_line_dist": 0.0,
            "tbt_bull_slope": 0.0,
        }

