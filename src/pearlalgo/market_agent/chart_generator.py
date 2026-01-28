"""
Chart Generator for Market Agent using mplfinance.

Generates professional trading charts with entry, stop loss, and take profit levels.
This is the production chart generator using mplfinance library.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib.ticker import MaxNLocator

from pearlalgo.utils.logger import logger

# Try to import mplfinance
try:
    import mplfinance as mpf
    MPLFINANCE_AVAILABLE = True
except ImportError:
    MPLFINANCE_AVAILABLE = False
    logger.warning("mplfinance not installed. Install with: pip install mplfinance")

# TradingView-style color constants
DARK_BG = "#0e1013"
GRID_COLOR = "#1e2127"
TEXT_PRIMARY = "#d1d4dc"
TEXT_SECONDARY = "#787b86"
CANDLE_UP = "#26a69a"
CANDLE_DOWN = "#ef5350"
SIGNAL_LONG = "#26a69a"
SIGNAL_SHORT = "#ef5350"
ENTRY_COLOR = "#2962ff"
VWAP_COLOR = "#2196f3"
# MA colors: supports up to 4 EMAs (9, 20, 50, 200) with unique colors
# Cyan for EMA9, Blue for EMA20, Purple for EMA50, Red for EMA200
MA_COLORS = ['#00bcd4', '#2196f3', '#9c27b0', '#f44336']

# TBT Trendline colors (configurable via ChartConfig)
TBT_RESISTANCE_COLOR = "#ffc107"  # Amber/yellow for resistance trendlines
TBT_SUPPORT_COLOR = "#00e676"     # Light green for support trendlines

# Zone colors (LuxAlgo/ChartPrime style)
SUPPLY_ZONE_COLOR = "#2157f3"  # LuxAlgo supply zone (resistance) - blue
DEMAND_ZONE_COLOR = "#ff5d00"  # LuxAlgo demand zone (support) - orange
POWER_CHANNEL_RESISTANCE = "#ff00ff"  # ChartPrime power channel upper - fuchsia
POWER_CHANNEL_SUPPORT = "#00ff00"  # ChartPrime power channel lower - lime

# Z-order constants for layering (lower = further back)
# Session shading is ambient background - never obscures price data
ZORDER_SESSION_SHADING = 0
# Supply/demand zones, power channel, RR boxes - structural context behind candles
ZORDER_ZONES = 1
# Key levels, VWAP bands, S/R lines - reference lines visible but not dominant
ZORDER_LEVEL_LINES = 2
# Candlesticks - primary price data, always visible (mplfinance default)
ZORDER_CANDLES = 3
# Right labels, session names, RR text - critical info, never hidden
ZORDER_TEXT_LABELS = 4

# Font size constants (in points) - for consistent text sizing across chart elements
# Tuned for Telegram/mobile readability.
FONT_SIZE_LABEL = 8           # Right-side level labels (compact for mobile)
FONT_SIZE_LABEL_MOBILE = 7    # Even smaller for mobile merged labels
FONT_SIZE_SESSION = 8         # Session names (Tokyo/London/NY)
FONT_SIZE_POWER_READOUT = 10  # Power channel buy/sell readout
FONT_SIZE_RR_BOX = 9          # Risk/reward box USD labels
FONT_SIZE_LEGEND = 8          # Dashboard legend text (compact)
FONT_SIZE_TITLE = 10          # Chart title (smaller, header-style)
FONT_SIZE_TITLE_MOBILE = 9    # Even smaller title for mobile
FONT_SIZE_SUMMARY = 10        # Performance summary text
FONT_SIZE_AXIS_TICK = 8       # X/Y axis tick labels
FONT_SIZE_AXIS_TICK_MOBILE = 7  # Smaller axis ticks for mobile

# Alpha (opacity) constants - for consistent transparency across chart elements
# Low alpha values ensure zones don't obscure candles (visual contract)
ALPHA_ZONE_SUPPLY_DEMAND = 0.18  # Supply/demand zone fills
ALPHA_ZONE_POWER_CHANNEL = 0.10  # Power channel zone fills
ALPHA_ZONE_RR_BOX_PROFIT = 0.20  # RR box profit zone
ALPHA_ZONE_RR_BOX_RISK = 0.22    # RR box risk zone
ALPHA_SESSION_SHADING = 0.08     # Session background shading
ALPHA_VWAP_BAND_FILL = 0.12      # VWAP band fill between VWAP and ±1σ (subtle but visible)
ALPHA_LINE_PRIMARY = 0.9         # Entry line, primary levels
ALPHA_LINE_SECONDARY = 0.7       # Stop/target, secondary levels
ALPHA_LINE_CONTEXTUAL = 0.55     # S/R, session averages
ALPHA_VWAP_BAND_1 = 0.35         # VWAP ±1 sigma bands
ALPHA_VWAP_BAND_2 = 0.25         # VWAP ±2 sigma bands
ALPHA_LEGEND_BG = 0.6            # Legend background


def _stabilize_matplotlib_rcparams() -> None:
    """
    Set minimal matplotlib rcParams for cross-machine rendering consistency.
    
    This reduces visual drift from font/rendering differences across environments.
    Called once at module load to ensure deterministic baseline generation.
    """
    import matplotlib as mpl
    
    # Use a font family that's broadly available and renders consistently
    # DejaVu Sans is matplotlib's default fallback and ships with mpl
    mpl.rcParams['font.family'] = 'sans-serif'
    mpl.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica', 'sans-serif']
    
    # Disable font hinting variations that cause pixel drift
    mpl.rcParams['text.hinting'] = 'native'
    mpl.rcParams['text.hinting_factor'] = 8
    
    # Consistent figure rendering
    mpl.rcParams['figure.dpi'] = 100  # Base DPI (savefig can override)
    mpl.rcParams['savefig.dpi'] = 150
    mpl.rcParams['figure.autolayout'] = False  # We control layout explicitly
    
    # Consistent antialiasing
    mpl.rcParams['text.antialiased'] = True
    mpl.rcParams['lines.antialiased'] = True


# Apply rcParams stabilization at module load
_stabilize_matplotlib_rcparams()


def compute_spaceman_key_levels(levels_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute SpacemanBTC-style higher-timeframe key levels.

    The visual regression baselines in this repo rely on the **4H** subset only.
    This helper returns a dict shaped like:

    {
      "intra_4h": {
        "current": {"open": ..., "high": ..., "low": ..., "mid": ...},
        "previous": {"open": ..., "high": ..., "low": ..., "mid": ...},
      }
    }

    Args:
        levels_df: UTC-indexed OHLC dataframe with lowercase columns (`open/high/low/close`).
    """
    try:
        if levels_df is None or levels_df.empty:
            return {}
        if not isinstance(levels_df.index, pd.DatetimeIndex):
            return {}

        df = levels_df.copy()
        try:
            if df.index.tz is None:
                df.index = df.index.tz_localize(timezone.utc)
            else:
                df.index = df.index.tz_convert(timezone.utc)
        except Exception:
            return {}

        # Normalize column casing defensively
        cols = {str(c).lower(): str(c) for c in df.columns}
        if not all(k in cols for k in ("open", "high", "low", "close")):
            return {}
        ohlc = df.rename(
            columns={
                cols["open"]: "open",
                cols["high"]: "high",
                cols["low"]: "low",
                cols["close"]: "close",
            }
        )[["open", "high", "low", "close"]]
        ohlc = ohlc.dropna(subset=["open", "high", "low", "close"])
        if ohlc.empty:
            return {}

        def _pack(row: pd.Series) -> Dict[str, float]:
            hi = float(row["high"])
            lo = float(row["low"])
            return {
                "open": float(row["open"]),
                "high": hi,
                "low": lo,
                "mid": float((hi + lo) / 2.0),
            }

        result = {}

        # 4H levels
        resampled_4h = (
            ohlc.resample("4h")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna(subset=["open", "high", "low", "close"])
        )
        if len(resampled_4h) >= 2:
            cur = resampled_4h.iloc[-1]
            prev = resampled_4h.iloc[-2]
            result["intra_4h"] = {"current": _pack(cur), "previous": _pack(prev)}

        # Weekly levels (W-Mon anchored, or W for pandas default Sunday)
        try:
            resampled_w = (
                ohlc.resample("W")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna(subset=["open", "high", "low", "close"])
            )
            if len(resampled_w) >= 2:
                cur_w = resampled_w.iloc[-1]
                prev_w = resampled_w.iloc[-2]
                result["weekly"] = {"current": _pack(cur_w), "previous": _pack(prev_w)}
        except Exception:
            pass

        # Monthly levels (MS = Month Start)
        try:
            resampled_m = (
                ohlc.resample("MS")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna(subset=["open", "high", "low", "close"])
            )
            if len(resampled_m) >= 2:
                cur_m = resampled_m.iloc[-1]
                prev_m = resampled_m.iloc[-2]
                result["monthly"] = {"current": _pack(cur_m), "previous": _pack(prev_m)}
        except Exception:
            pass

        # Monday Range (current week's Monday high/low/mid)
        try:
            # Filter to Monday bars only (dayofweek == 0)
            monday_mask = ohlc.index.dayofweek == 0
            monday_bars = ohlc[monday_mask]
            if not monday_bars.empty:
                # Get the most recent Monday's range
                last_monday = monday_bars.index[-1].date()
                today_monday = monday_bars[monday_bars.index.date == last_monday]
                if not today_monday.empty:
                    mon_high = float(today_monday["high"].max())
                    mon_low = float(today_monday["low"].min())
                    mon_mid = (mon_high + mon_low) / 2.0
                    result["monday_range"] = {
                        "high": mon_high,
                        "low": mon_low,
                        "mid": mon_mid,
                    }
        except Exception:
            pass

        # Quarterly levels (QS = Quarter Start)
        try:
            resampled_q = (
                ohlc.resample("QS")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna(subset=["open", "high", "low", "close"])
            )
            if len(resampled_q) >= 2:
                cur_q = resampled_q.iloc[-1]
                prev_q = resampled_q.iloc[-2]
                result["quarterly"] = {"current": _pack(cur_q), "previous": _pack(prev_q)}
        except Exception:
            pass

        # Yearly levels (YS = Year Start)
        try:
            resampled_y = (
                ohlc.resample("YS")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna(subset=["open", "high", "low", "close"])
            )
            if len(resampled_y) >= 1:
                cur_y = resampled_y.iloc[-1]
                # Yearly shows current year's H/L/M (not previous)
                result["yearly"] = {
                    "current": _pack(cur_y),
                    # If we have a previous year, include it
                    "previous": _pack(resampled_y.iloc[-2]) if len(resampled_y) >= 2 else None,
                }
        except Exception:
            pass

        return result
    except Exception:
        # Best-effort feature: never fail charting if this computation breaks.
        return {}


def build_hud_context(
    df: pd.DataFrame,
    *,
    symbol: str = "MNQ",
    tick_size: float = 0.25,
) -> Dict[str, Any]:
    """
    Build the HUD context dict used by TradingView-style overlays.

    This is intentionally **self-contained and deterministic**: it only uses the provided
    dataframe window, and never reaches out to live services.

    Expected input:
      - a dataframe with `timestamp` column (ISO string or datetime), and lowercase
        `open/high/low/close/volume` columns.
    """
    hud: Dict[str, Any] = {"symbol": str(symbol), "tick_size": float(tick_size)}
    try:
        if df is None or df.empty:
            return hud

        work = df.copy()

        # Normalize timestamp → UTC DatetimeIndex
        if "timestamp" in work.columns:
            ts = pd.to_datetime(work["timestamp"], errors="coerce", utc=True)
            work = work.assign(timestamp=ts).dropna(subset=["timestamp"]).sort_values("timestamp").set_index("timestamp")
        else:
            if not isinstance(work.index, pd.DatetimeIndex):
                return hud
            idx = work.index
            if idx.tz is None:
                idx = idx.tz_localize(timezone.utc)
            else:
                idx = idx.tz_convert(timezone.utc)
            work = work.copy()
            work.index = idx
            work = work.sort_index()

        # Coerce numeric columns
        for col in ("open", "high", "low", "close", "volume"):
            if col in work.columns:
                work[col] = pd.to_numeric(work[col], errors="coerce")
        work = work.dropna(subset=["open", "high", "low", "close"])
        if work.empty:
            return hud

        # Use PearlBot config defaults for HUD computations (keeps charts aligned with strategy defaults).
        try:
            from pearlalgo.trading_bots.pearl_bot_auto import CONFIG as _BOT_CFG
            from pearlalgo.trading_bots.pearl_bot_auto import calculate_atr as _calc_atr
        except Exception:
            _BOT_CFG = {}
            _calc_atr = None  # type: ignore

        # Load base config/config.yaml (no overlays) for deterministic chart semantics.
        base_cfg: Dict[str, Any] = {}
        try:
            from pearlalgo.config.config_file import load_config_yaml

            repo_root = Path(__file__).resolve().parents[3]
            base_cfg_path = repo_root / "config" / "config.yaml"
            base_cfg = load_config_yaml(config_path=base_cfg_path, substitute_env=False, validate=False) or {}
        except Exception:
            base_cfg = {}

        # ----------------------------
        # Sessions (Tokyo/London/NY)
        # ----------------------------
        sessions: List[Dict[str, Any]] = []
        try:
            # Session definitions come from the repo's base `config/config.yaml`
            # (do not consult overlays for deterministic baselines).
            try:
                from pearlalgo.config.config_file import load_config_yaml

                repo_root = Path(__file__).resolve().parents[3]
                base_cfg_path = repo_root / "config" / "config.yaml"
                cfg = load_config_yaml(config_path=base_cfg_path, substitute_env=False, validate=False) or {}
                session_defs = cfg.get("sessions") or []
            except Exception:
                session_defs = []

            if not isinstance(session_defs, list) or not session_defs:
                # Fallback defaults (match config.yaml committed in this repo)
                session_defs = [
                    {"name": "Tokyo", "session": "0000-0900", "timezone": "UTC", "color": "#2962FF"},
                    {"name": "London", "session": "0800-1600", "timezone": "UTC", "color": "#FF9800"},
                    {"name": "New York", "session": "1400-2100", "timezone": "UTC", "color": "#089981"},
                ]

            def _parse_hhmm(hhmm: str) -> tuple[int, int]:
                s = str(hhmm or "").strip()
                if len(s) != 4 or not s.isdigit():
                    raise ValueError(f"Invalid HHMM: {hhmm!r}")
                return int(s[:2]), int(s[2:])

            def _session_stats(name: str, start_dt: datetime, end_dt: datetime, color: str) -> Optional[Dict[str, Any]]:
                # Compute stats using UTC-indexed source data for deterministic ordering.
                start_utc = start_dt.astimezone(timezone.utc)
                end_utc = end_dt.astimezone(timezone.utc)
                # Session end is treated as exclusive (matches baselines).
                w = work.loc[(work.index >= start_utc) & (work.index < end_utc)]
                if w.empty:
                    return None
                hi = float(w["high"].max())
                lo = float(w["low"].min())
                rt = None
                if tick_size and tick_size > 0 and np.isfinite(hi) and np.isfinite(lo):
                    rt = int(round((hi - lo) / float(tick_size)))
                return {
                    "name": name,
                    "start": start_utc.isoformat(),
                    "end": end_utc.isoformat(),
                    "color": str(color),
                    "open": float(w["open"].iloc[0]),
                    "close": float(w["close"].iloc[-1]),
                    "avg": float(w["close"].mean()),
                    "range_ticks": rt,
                }

            # Build per-day sessions from config definitions
            idx_utc = work.index
            for sdef in session_defs:
                if not isinstance(sdef, dict):
                    continue
                name = str(sdef.get("name") or "").strip()
                sess = str(sdef.get("session") or "").strip()
                if not name or "-" not in sess:
                    continue
                tz_name = str(sdef.get("timezone") or "UTC").strip() or "UTC"
                color = str(sdef.get("color") or "#444444").strip() or "#444444"

                try:
                    tz = ZoneInfo(tz_name)
                except Exception:
                    tz = ZoneInfo("UTC")

                try:
                    start_s, end_s = sess.split("-", 1)
                    sh, sm = _parse_hhmm(start_s)
                    eh, em = _parse_hhmm(end_s)
                except Exception:
                    continue

                # Determine local date range spanned by the data
                try:
                    idx_local = idx_utc.tz_convert(tz)
                    start_date = idx_local.min().date()
                    end_date = idx_local.max().date()
                except Exception:
                    start_date = idx_utc.min().date()
                    end_date = idx_utc.max().date()

                days = pd.date_range(start=start_date, end=end_date, freq="D", tz=tz)
                for d in days:
                    start_dt = datetime(d.year, d.month, d.day, sh, sm, tzinfo=tz)
                    end_dt = datetime(d.year, d.month, d.day, eh, em, tzinfo=tz)
                    if end_dt <= start_dt:
                        end_dt = end_dt + timedelta(days=1)
                    stats = _session_stats(name, start_dt, end_dt, color)
                    if stats:
                        sessions.append(stats)

            # Keep chronological order by session start time
            sessions.sort(key=lambda s: str(s.get("start") or ""))
        except Exception:
            sessions = []
        if sessions:
            hud["sessions"] = sessions

        # ----------------------------
        # Power Channel (ChartPrime)
        # ----------------------------
        try:
            sr_len = int(_BOT_CFG.get("sr_length", 130) or 130) if isinstance(_BOT_CFG, dict) else int(getattr(_BOT_CFG, "sr_length", 130))
            atr_mult = float(_BOT_CFG.get("sr_atr_mult", 0.5) or 0.5) if isinstance(_BOT_CFG, dict) else float(getattr(_BOT_CFG, "sr_atr_mult", 0.5))

            lookback = work.tail(sr_len) if len(work) >= sr_len else work
            max_price = float(lookback["high"].max())
            min_price = float(lookback["low"].min())

            atr_width = 0.0
            if _calc_atr is not None and len(work) >= 20:
                try:
                    atr_width = float(_calc_atr(work, period=200).iloc[-1]) * atr_mult
                except Exception:
                    atr_width = 0.0

            buy_power = int((lookback["close"] > lookback["open"]).sum())
            sell_power = int((lookback["close"] < lookback["open"]).sum())

            hud["power_channel"] = {
                "res_area_top": max_price + atr_width,
                "res_area_bottom": max_price,
                "sup_area_top": min_price,
                "sup_area_bottom": min_price - atr_width,
                "mid": (max_price + min_price) / 2.0,
                "buy_power": buy_power,
                "sell_power": sell_power,
            }
        except Exception:
            pass

        # ----------------------------
        # Supply & Demand (LuxAlgo VR)
        # ----------------------------
        # Baseline contract: dashboard charts include visible-range supply/demand zones,
        # but do NOT include a POC right-label.
        try:
            sd_resolution = (
                int(_BOT_CFG.get("sd_resolution", 50) or 50)
                if isinstance(_BOT_CFG, dict)
                else int(getattr(_BOT_CFG, "sd_resolution", 50))
            )

            # Use the full visible window to match "visible range" semantics.
            lookback = work
            if sd_resolution > 0 and not lookback.empty:
                hi = float(lookback["high"].max())
                lo = float(lookback["low"].min())
                pr = float(hi - lo)
                if pr > 0:
                    bin_size = pr / float(sd_resolution)

                    # Accumulate per-bin volume + avg/wavg for label lines.
                    bins: Dict[int, Dict[str, float]] = {}
                    for _, row in lookback.iterrows():
                        close = float(row.get("close", 0.0) or 0.0)
                        vol = float(row.get("volume", 0.0) or 0.0)
                        if not np.isfinite(close) or not np.isfinite(vol) or vol <= 0:
                            continue
                        b = int(((close - lo) / pr) * sd_resolution)
                        b = max(0, min(sd_resolution - 1, b))
                        rec = bins.get(b) or {"vol": 0.0, "w_sum": 0.0, "p_sum": 0.0, "n": 0.0}
                        rec["vol"] += vol
                        rec["w_sum"] += close * vol
                        rec["p_sum"] += close
                        rec["n"] += 1.0
                        bins[b] = rec

                    if bins:
                        last_close = float(lookback["close"].iloc[-1])

                        # Select zones from the visible-range volume profile.
                        # Bias towards the extremes of the visible range (matches baselines).
                        sd_cfg = (
                            ((base_cfg.get("indicators") or {}).get("supply_demand_zones") or {})
                            if isinstance(base_cfg, dict)
                            else {}
                        )
                        zone_thr = float(sd_cfg.get("zone_threshold_pct", 0.3) or 0.3)
                        if zone_thr > 1.0:
                            zone_thr = zone_thr / 100.0
                        zone_thr = max(0.0, min(0.5, zone_thr))
                        bottom_limit = lo + zone_thr * pr
                        top_limit = hi - zone_thr * pr

                        # Expand zones to a minimum size in ATR terms (config-driven).
                        zone_min_width = 0.0
                        try:
                            min_zone_atr = float(sd_cfg.get("min_zone_size_atr", 0.5) or 0.5)
                        except Exception:
                            min_zone_atr = 0.0
                        if _calc_atr is not None and min_zone_atr > 0:
                            try:
                                atr_val = float(_calc_atr(lookback, period=14).iloc[-1])
                            except Exception:
                                atr_val = 0.0
                            if np.isfinite(atr_val) and atr_val > 0:
                                zone_min_width = float(min_zone_atr) * atr_val

                        supply_bin: Optional[int] = None
                        demand_bin: Optional[int] = None
                        for b, rec in sorted(bins.items(), key=lambda kv: float(kv[1].get("vol", 0.0)), reverse=True):
                            center = lo + (b + 0.5) * bin_size
                            if demand_bin is None and center <= bottom_limit:
                                demand_bin = b
                            if supply_bin is None and center >= top_limit:
                                supply_bin = b
                            if supply_bin is not None and demand_bin is not None:
                                break

                        # Fallback to above/below last close if thresholds were too strict.
                        if supply_bin is None or demand_bin is None:
                            for b, rec in sorted(bins.items(), key=lambda kv: float(kv[1].get("vol", 0.0)), reverse=True):
                                center = lo + (b + 0.5) * bin_size
                                if supply_bin is None and center > last_close:
                                    supply_bin = b
                                if demand_bin is None and center < last_close:
                                    demand_bin = b
                                if supply_bin is not None and demand_bin is not None:
                                    break

                        def _zone(bin_idx: Optional[int]) -> Optional[Dict[str, float]]:
                            if bin_idx is None:
                                return None
                            rec = bins.get(bin_idx) or {}
                            bottom = lo + bin_idx * bin_size
                            top = bottom + bin_size
                            vol = float(rec.get("vol", 0.0) or 0.0)
                            n = float(rec.get("n", 0.0) or 0.0)
                            avg = float(rec.get("p_sum", 0.0) or 0.0) / n if n > 0 else (top + bottom) / 2.0
                            wavg = float(rec.get("w_sum", 0.0) or 0.0) / vol if vol > 0 else avg
                            if zone_min_width and zone_min_width > (top - bottom):
                                # Expand around the bin center for stable zone geometry.
                                center = lo + (bin_idx + 0.5) * bin_size
                                half = zone_min_width / 2.0
                                bottom = center - half
                                top = center + half
                            return {
                                "top": float(top),
                                "bottom": float(bottom),
                                "avg": float(avg),
                                "wavg": float(wavg),
                            }

                        supply = _zone(supply_bin)
                        demand = _zone(demand_bin)
                        # Match baseline visuals: zones extend to range extremes.
                        # Demand fills from visible low → demand boundary; supply fills from
                        # supply boundary → visible high.
                        if isinstance(demand, dict) and demand:
                            demand["bottom"] = float(lo)
                        if isinstance(supply, dict) and supply:
                            supply["top"] = float(hi)
                        if supply or demand:
                            hud["supply_demand_vr"] = {"supply": supply or {}, "demand": demand or {}}
        except Exception:
            pass

        # ----------------------------
        # TBT Trendlines (ChartPrime)
        # ----------------------------
        # Adds the missing "trendlines" geometry to match the TradingView indicator set.
        # This is best-effort and intentionally does not affect chart scaling.
        try:
            # Pull defaults from PearlBot config (keeps semantics aligned with strategy defaults).
            if isinstance(_BOT_CFG, dict):
                tbt_period = int(_BOT_CFG.get("tbt_period", 10) or 10)
                tbt_trend_type = str(_BOT_CFG.get("tbt_trend_type", "wicks") or "wicks")
                tbt_extend = int(_BOT_CFG.get("tbt_extend", 25) or 25)
            else:
                tbt_period = int(getattr(_BOT_CFG, "tbt_period", 10) or 10)
                tbt_trend_type = str(getattr(_BOT_CFG, "tbt_trend_type", "wicks") or "wicks")
                tbt_extend = int(getattr(_BOT_CFG, "tbt_extend", 25) or 25)

            tbt_period = max(4, min(50, int(tbt_period)))
            # Pine uses rightBars = period/2; keep at least 1 bar.
            right_bars = max(1, int(round(float(tbt_period) / 2.0)))
            # Extension options in the Pine script are 25/50/75 bars.
            tbt_extend = int(max(10, min(200, tbt_extend)))

            if len(work) >= (tbt_period + right_bars + 2):
                trend_type = tbt_trend_type.strip().lower()
                if trend_type not in ("wicks", "wick", "body"):
                    trend_type = "wicks"

                if trend_type == "body":
                    src_high = work[["open", "close"]].max(axis=1).to_numpy(dtype=float)
                    src_low = work[["open", "close"]].min(axis=1).to_numpy(dtype=float)
                else:
                    src_high = work["high"].to_numpy(dtype=float)
                    src_low = work["low"].to_numpy(dtype=float)

                close_arr = work["close"].to_numpy(dtype=float)
                high_arr = work["high"].to_numpy(dtype=float)
                low_arr = work["low"].to_numpy(dtype=float)

                n = int(len(work))

                def _pivot_indices(arr: np.ndarray, *, kind: str) -> List[int]:
                    out: List[int] = []
                    for i in range(tbt_period, n - right_bars):
                        v = float(arr[i])
                        if not np.isfinite(v):
                            continue
                        win = arr[(i - tbt_period):(i + right_bars + 1)]
                        if win.size == 0:
                            continue
                        if kind == "high":
                            m = float(np.nanmax(win))
                            if np.isfinite(m) and v == m:
                                out.append(i)
                        else:
                            m = float(np.nanmin(win))
                            if np.isfinite(m) and v == m:
                                out.append(i)
                    return out

                piv_hi = _pivot_indices(src_high, kind="high")
                piv_lo = _pivot_indices(src_low, kind="low")

                # Z-band (volatility band) from Pine reference:
                # min(ATR(30)*0.3, close*0.3%) shifted 20 bars, then /2
                zband = 0.0
                try:
                    if _calc_atr is not None and n >= 35:
                        atr30 = _calc_atr(work, period=30)
                        if atr30 is not None and not atr30.empty:
                            vol_adj = np.minimum(
                                pd.to_numeric(atr30, errors="coerce") * 0.3,
                                pd.to_numeric(work["close"], errors="coerce") * 0.003,
                            )
                            zb = float(pd.Series(vol_adj).shift(20).iloc[-1])
                            if np.isfinite(zb) and zb > 0:
                                zband = float(zb) / 2.0
                except Exception:
                    zband = 0.0

                tbt_lines: List[Dict[str, Any]] = []

                def _add_line(pivots: List[int], src: np.ndarray, *, kind: str) -> Optional[Dict[str, Any]]:
                    if len(pivots) < 2:
                        return None
                    i1, i2 = int(pivots[-2]), int(pivots[-1])
                    if i2 <= i1:
                        return None
                    y1 = float(src[i1])
                    y2 = float(src[i2])
                    if not (np.isfinite(y1) and np.isfinite(y2)):
                        return None
                    slope = (y2 - y1) / float(i2 - i1)

                    # NOTE: The Pine script conditionally draws trendlines based on slope sign.
                    # For chart readability and "always-on" indicator parity, we keep the latest
                    # pivot-high (resistance) and pivot-low (support) trendlines regardless of slope.

                    x1 = float(i1)
                    x2 = float(i2 + tbt_extend)
                    y_end = y2 + slope * float(tbt_extend)
                    return {
                        "kind": kind,
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": float(y_end),
                        "pivot_x": float(i2),
                        "pivot_y": float(y2),
                        "slope": float(slope),
                    }

                res_line = _add_line(piv_hi, src_high, kind="resistance")
                sup_line = _add_line(piv_lo, src_low, kind="support")
                if res_line:
                    tbt_lines.append(res_line)
                if sup_line:
                    tbt_lines.append(sup_line)

                # Optional breakout target (TP) for the most recent bar.
                tp: Optional[float] = None
                tp_dir: Optional[str] = None
                try:
                    if n >= 2 and zband > 0:
                        c0 = float(close_arr[-2])
                        c1 = float(close_arr[-1])
                        if res_line and tp is None:
                            # Break above descending resistance
                            slope = float(res_line["slope"])
                            x1 = float(res_line["x1"])
                            y1 = float(res_line["y1"])
                            prev_line = y1 + (float(n - 2) - x1) * slope
                            cur_line = y1 + (float(n - 1) - x1) * slope
                            if np.isfinite(c0) and np.isfinite(c1) and (c0 < prev_line) and (c1 > cur_line):
                                hi = float(high_arr[-1])
                                if np.isfinite(hi) and hi > 0:
                                    tp = hi + (zband * 20.0)
                                    tp_dir = "long"
                        if sup_line and tp is None:
                            # Break below ascending support
                            slope = float(sup_line["slope"])
                            x1 = float(sup_line["x1"])
                            y1 = float(sup_line["y1"])
                            prev_line = y1 + (float(n - 2) - x1) * slope
                            cur_line = y1 + (float(n - 1) - x1) * slope
                            if np.isfinite(c0) and np.isfinite(c1) and (c0 > prev_line) and (c1 < cur_line):
                                lo_v = float(low_arr[-1])
                                if np.isfinite(lo_v) and lo_v > 0:
                                    tp = lo_v - (zband * 20.0)
                                    tp_dir = "short"
                except Exception:
                    tp = None
                    tp_dir = None

                if tbt_lines:
                    hud["tbt"] = {
                        "period": int(tbt_period),
                        "trend_type": trend_type,
                        "extend_bars": int(tbt_extend),
                        "zband": float(zband),
                        "lines": tbt_lines,
                    }
                    if tp is not None and np.isfinite(tp) and float(tp) > 0:
                        hud["tbt"]["tp"] = float(tp)
                        hud["tbt"]["direction"] = str(tp_dir or "")
        except Exception:
            pass

        # ----------------------------
        # Key Levels (RTH + ETH daily)
        # ----------------------------
        try:
            et_idx = work.index.tz_convert(ZoneInfo("America/New_York"))
            et_time = et_idx.time

            # ETH session = 18:00 → 17:00 ET (maintenance break 17:00–18:00 excluded)
            in_eth = [(t >= datetime(2000, 1, 1, 18, 0).time()) or (t < datetime(2000, 1, 1, 17, 0).time()) for t in et_time]
            eth_work = work.loc[in_eth]
            eth_et = et_idx[in_eth]
            eth_id = []
            for ts in eth_et:
                d = ts.date()
                if ts.time() >= datetime(2000, 1, 1, 18, 0).time():
                    eth_id.append(d)
                else:
                    eth_id.append((ts - timedelta(days=1)).date())
            eth_work = eth_work.copy()
            eth_work["__eth_id"] = eth_id
            eth_groups = (
                eth_work.groupby("__eth_id", sort=True)
                .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
            )

            # RTH = 09:30 → 16:00 ET
            rth_mask = [
                (t >= datetime(2000, 1, 1, 9, 30).time()) and (t <= datetime(2000, 1, 1, 16, 0).time())
                for t in et_time
            ]
            rth_work = work.loc[rth_mask].copy()
            rth_et = et_idx[rth_mask]
            rth_work["__rth_id"] = [ts.date() for ts in rth_et]
            rth_groups = (
                rth_work.groupby("__rth_id", sort=True)
                .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
            )

            def _pack_levels(df_levels: pd.DataFrame) -> Dict[str, Any]:
                out: Dict[str, Any] = {"current": {}, "previous": {}}
                if df_levels is None or df_levels.empty:
                    return out
                df_levels = df_levels.sort_index()
                cur = df_levels.iloc[-1]
                prev = df_levels.iloc[-2] if len(df_levels) >= 2 else None

                def _one(row) -> Dict[str, float]:
                    hi = float(row["high"])
                    lo = float(row["low"])
                    return {
                        "open": float(row["open"]),
                        "high": hi,
                        "low": lo,
                        "mid": float((hi + lo) / 2.0),
                    }

                out["current"] = _one(cur)
                if prev is not None:
                    out["previous"] = _one(prev)
                return out

            hud["key_levels"] = {"eth": _pack_levels(eth_groups), "rth": _pack_levels(rth_groups)}
        except Exception:
            pass

        return hud
    except Exception:
        return hud


@dataclass
class RenderManifest:
    """
    Optional debug manifest capturing render semantics for non-pixel regression.
    
    This enables semantic regression checks even when small anti-aliasing
    differences cause pixel noise. Default OFF to avoid performance impact.
    
    Usage:
        chart_path = generator.generate_dashboard_chart(
            ...,
            manifest_path=Path("/tmp/chart_manifest.json"),
        )
        # Produces both chart.png and chart_manifest.json
    """
    # Render inputs
    chart_type: str = ""
    symbol: str = ""
    timeframe: str = ""
    lookback_bars: int = 0
    figsize: Tuple[float, float] = (0.0, 0.0)
    dpi: int = 0
    render_mode: str = "telegram"
    
    # Timestamp info
    render_timestamp: str = ""
    title_time: str = ""
    
    # Drawn elements summary
    num_candles: int = 0
    price_range: Tuple[float, float] = (0.0, 0.0)
    
    # Levels and labels
    levels: List[Dict[str, Any]] = field(default_factory=list)
    merged_labels: List[Dict[str, Any]] = field(default_factory=list)
    
    # Overlays
    sessions: List[str] = field(default_factory=list)
    zones: List[Dict[str, Any]] = field(default_factory=list)
    
    # Markers
    trade_markers: List[Dict[str, Any]] = field(default_factory=list)
    ema_crossover_markers: List[Dict[str, Any]] = field(default_factory=list)
    
    # Indicators
    indicators: List[str] = field(default_factory=list)
    
    # Config snapshot (for reproducibility)
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to JSON-serializable dict."""
        return {
            "chart_type": self.chart_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "lookback_bars": self.lookback_bars,
            "figsize": list(self.figsize),
            "dpi": self.dpi,
            "render_mode": self.render_mode,
            "render_timestamp": self.render_timestamp,
            "title_time": self.title_time,
            "num_candles": self.num_candles,
            "price_range": list(self.price_range),
            "levels": self.levels,
            "merged_labels": self.merged_labels,
            "sessions": self.sessions,
            "zones": self.zones,
            "trade_markers": self.trade_markers,
            "ema_crossover_markers": self.ema_crossover_markers,
            "indicators": self.indicators,
            "config_snapshot": self.config_snapshot,
        }
    
    def save(self, path: Path) -> None:
        """Save manifest to JSON file."""
        import json
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


@dataclass
class ChartConfig:
    """Configuration for chart generation with TradingView-style defaults."""
    show_vwap: bool = True
    show_ma: bool = True
    ma_periods: List[int] = field(default_factory=lambda: [9, 20, 50, 200])  # EMA9/20/50/200 by default
    signal_marker_size: int = 300
    max_signals_displayed: int = 50
    cluster_signals: bool = True
    show_performance_metrics: bool = True
    timeframe: str = "5m"  # Default to 5m for better visual context (HTF/LTF still used for analysis)
    show_entry_sl_tp_bands: bool = True
    candle_width: float = 0.8  # mplfinance uses 0.8 as default (80% of interval)

    # TradingView-style HUD layers
    show_hud: bool = True
    show_rr_box: bool = True
    rr_box_forward_bars: int = 30
    right_pad_bars: int = 30

    show_sessions: bool = True
    show_session_names: bool = True
    show_session_oc: bool = True
    show_session_tick_range: bool = True
    show_session_average: bool = True
    show_session_range_stats: bool = True  # Show Range/Avg inside session shading

    show_supply_demand: bool = True
    show_power_channel: bool = True
    show_power_readout: bool = True  # Show Power buy/sell ratio in top-left corner
    show_tbt_targets: bool = True
    show_key_levels: bool = True
    show_regime_label: bool = False
    show_ml_confidence: bool = False

    # Key level timeframes to display (SpacemanBTC style)
    # Options: "4h", "daily", "weekly", "monthly", "monday"
    # Default shows 4H, Daily, and Weekly levels. Add "monthly" or "monday" for more.
    key_level_timeframes: tuple = ("4h", "daily", "weekly")

    # TBT Trendline styling (configurable colors for visibility)
    tbt_resistance_color: str = "#ffc107"  # Amber/yellow for resistance
    tbt_support_color: str = "#00e676"     # Light green for support
    tbt_line_style: str = "--"             # Dashed line style
    tbt_line_width: float = 1.8            # Line width

    show_right_labels: bool = True
    max_right_labels: int = 12
    right_label_merge_ticks: int = 4  # merge labels when within N ticks

    show_rsi: bool = True
    rsi_period: int = 14
    rsi_overbought_oversold_shading: bool = True  # Shade overbought (>70) and oversold (<30) zones

    # Panel visibility options (allows hiding panels for more price space)
    show_pressure_panel: bool = True  # Pressure panel (signed volume histogram)
    show_volume_panel: bool = True    # Volume panel (can disable for cleaner charts)
    # Trade recap panel (replaces pressure panel when enabled)
    show_trade_recap_panel: bool = False

    # Panel ratio configuration (advanced - controls vertical space allocation)
    # Default optimized ratios give ~66% to price panel when all sub-panels enabled
    panel_ratio_price: float = 8.0    # Price panel ratio (larger = more space)
    panel_ratio_volume: float = 1.8   # Volume panel ratio
    panel_ratio_sub: float = 1.2      # Sub-panel ratio (applied to pressure and RSI)

    # VWAP band fill option (visual enhancement)
    vwap_fill_bands: bool = False  # Fill between VWAP and ±1σ bands

    # Legend display option
    show_legend: bool = True  # Show indicator legend in top-right corner

    # Optional mobile readability enhancement (P7 from visual integrity plan)
    # When True, uses 10pt font for RR box labels (vs default 9pt) for better
    # mobile readability on Telegram. Default False to preserve baseline stability.
    mobile_enhanced_fonts: bool = False
    rr_box_font_size: int = 9  # Default 9pt, set to 10 for mobile enhancement

    # Compact label mode (P6 from visual integrity plan)
    # When True, reduces label clutter for range-bound days:
    # - max_right_labels reduced to 6 (from 12)
    # - right_label_merge_ticks increased to 6 (from 4)
    # Default False to preserve current behavior.
    compact_labels: bool = False

    # Mobile mode: consolidates all mobile optimizations
    # When True, enables: mobile_enhanced_fonts, larger tick labels, thicker lines,
    # auto-compact labels, and reduced max_right_labels
    mobile_mode: bool = False

    # Smart Trade Markers (P8 from visual integrity plan)
    # Replaces standard triangle/circle markers with cohesive "smart" markers:
    # - Entry: Large triangle with pair letter (A, B, C)
    # - Exit: Circle/Square with pair letter (A, B, C)
    # - Outcome: Color-coded (Green=Win, Red=Loss, Gray=Open)
    # Lettering is helpful at low density, but can overwhelm dense charts.
    # Default True to preserve current trusted behavior.
    smart_marker_size: int = 300
    smart_marker_show_letters: bool = True
    # Optional decluttering controls (default True to preserve current meaning)
    smart_marker_show_entry: bool = True
    smart_marker_show_exit: bool = True
    smart_marker_show_path: bool = True
    # Path-only enhancements (default off for baseline stability)
    # - Arrowheads emulate TradingView's arrow line styles.
    # - Fade-by-age keeps the most recent trades visually dominant.
    # - Label last P&L adds detail without cluttering the full history.
    smart_marker_path_arrowheads: bool = False
    smart_marker_path_fade_by_age: bool = False
    smart_marker_path_label_last_pnl: bool = False
    
    # Trade overlay profiles (reference mapping to config knobs):
    # - path_only_clean:
    #   show_entry=False, show_exit=False, show_path=True, arrowheads=False, fade=False, last_pnl=False
    # - path_only_detailed:
    #   show_entry=False, show_exit=False, show_path=True, arrowheads=True, fade=True, last_pnl=True
    # - entry_exit_no_letters:
    #   show_entry=True, show_exit=True, show_path=True, show_letters=False
    # - lettered_pairs:
    #   show_entry=True, show_exit=True, show_path=True, show_letters=True
    # - entries_only / exits_only:
    #   show_entry=True, show_exit=False OR show_entry=False, show_exit=True (path optional)

    @classmethod
    def from_strategy_config(cls, strategy_config) -> "ChartConfig":
        """Create ChartConfig from config dict (or any object with hud_* attrs)."""
        config = cls()
        
        # Map config dict hud_* attributes to ChartConfig
        attr_map = {
            "hud_enabled": "show_hud",
            "hud_show_rr_box": "show_rr_box",
            "hud_rr_box_forward_bars": "rr_box_forward_bars",
            "hud_right_pad_bars": "right_pad_bars",
            "hud_show_sessions": "show_sessions",
            "hud_show_session_names": "show_session_names",
            "hud_show_session_oc": "show_session_oc",
            "hud_show_session_tick_range": "show_session_tick_range",
            "hud_show_session_average": "show_session_average",
            "hud_show_session_range_stats": "show_session_range_stats",
            "hud_show_supply_demand": "show_supply_demand",
            "hud_show_power_channel": "show_power_channel",
            "hud_show_power_readout": "show_power_readout",
            "hud_show_tbt_targets": "show_tbt_targets",
            "hud_show_key_levels": "show_key_levels",
            "hud_tbt_resistance_color": "tbt_resistance_color",
            "hud_tbt_support_color": "tbt_support_color",
            "hud_tbt_line_style": "tbt_line_style",
            "hud_tbt_line_width": "tbt_line_width",
            "hud_show_right_labels": "show_right_labels",
            "hud_max_right_labels": "max_right_labels",
            "hud_right_label_merge_ticks": "right_label_merge_ticks",
            "hud_show_rsi": "show_rsi",
            "hud_rsi_period": "rsi_period",
            "hud_rsi_overbought_oversold_shading": "rsi_overbought_oversold_shading",
            "hud_show_pressure_panel": "show_pressure_panel",
            "hud_show_trade_recap_panel": "show_trade_recap_panel",
            "hud_show_volume_panel": "show_volume_panel",
            "hud_panel_ratio_price": "panel_ratio_price",
            "hud_panel_ratio_volume": "panel_ratio_volume",
            "hud_panel_ratio_sub": "panel_ratio_sub",
            "hud_key_level_timeframes": "key_level_timeframes",
            "hud_vwap_fill_bands": "vwap_fill_bands",
            "hud_show_legend": "show_legend",
            "hud_mobile_enhanced_fonts": "mobile_enhanced_fonts",
            "hud_rr_box_font_size": "rr_box_font_size",
            "hud_compact_labels": "compact_labels",
            "hud_mobile_mode": "mobile_mode",
            "hud_smart_marker_size": "smart_marker_size",
        }
        
        for src_attr, dst_attr in attr_map.items():
            if hasattr(strategy_config, src_attr):
                setattr(config, dst_attr, getattr(strategy_config, src_attr))
        
        return config


class ChartGenerator:
    """Generates TradingView-style charts using mplfinance."""
    
    def __init__(self, config: Optional[ChartConfig] = None):
        """Initialize chart generator.
        
        Args:
            config: Chart configuration (optional, uses defaults if not provided)
        """
        if not MPLFINANCE_AVAILABLE:
            raise ImportError("mplfinance required. Install with: pip install mplfinance")
        
        self.config = config or ChartConfig()
        
        # Apply mobile mode optimizations if enabled
        # This consolidates all mobile-friendly settings into a single flag
        if self.config.mobile_mode:
            self._apply_mobile_mode()
        
        # Default export DPI tuned for Telegram clarity while keeping file sizes reasonable.
        self.dpi = 200

        # Optional historical cache for computing higher-timeframe key levels (SpacemanBTC-style)
        # without requiring long candle windows in the rendered chart.
        # Cached per symbol for the lifetime of this ChartGenerator instance.
        self._key_level_history_cache: Dict[str, pd.DataFrame] = {}
        self._key_level_history_mtime: Dict[str, float] = {}
        
        # Create TradingView dark theme style
        self._create_tradingview_style()
    
    def _apply_mobile_mode(self) -> None:
        """Apply all mobile-friendly optimizations when mobile_mode=True.
        
        Consolidates multiple settings for optimal mobile/Telegram viewing:
        - Larger fonts for readability on small screens
        - Compact labels to reduce clutter
        - Thicker lines for visibility
        - Fewer right-side labels
        """
        # Enable mobile-enhanced fonts (larger RR box labels)
        self.config.mobile_enhanced_fonts = True
        self.config.rr_box_font_size = 10  # Slightly larger than default 9pt
        
        # Enable compact label mode
        self.config.compact_labels = True
        self.config.max_right_labels = 6  # Reduced from default 12
        self.config.right_label_merge_ticks = 6  # More aggressive merging
        
        # Keep legend visible but session stats may clutter on small screens
        # Users can still override these individually if needed

    def _load_key_level_history(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Best-effort load of local historical 1m data (parquet) for key level computation.

        This is intentionally used ONLY at chart render time (not during scanning) to keep the
        trading loop fast. If files are missing, returns None and callers should fall back to
        computing levels from the visible chart window only.
        """
        sym = str(symbol or "").strip().upper()
        if not sym:
            return None

        # Resolve repo root from this file location: src/pearlalgo/market_agent/chart_generator.py
        try:
            repo_root = Path(__file__).resolve().parents[3]
        except Exception:
            return None

        hist_dir = repo_root / "data" / "historical"
        if not hist_dir.exists():
            return None

        candidates = [
            hist_dir / f"{sym}_1m_6w.parquet",
            hist_dir / f"{sym}_1m_4w.parquet",
            hist_dir / f"{sym}_1m_2w.parquet",
            hist_dir / f"{sym}_1m_1w.parquet",
        ]

        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            return None

        try:
            mtime = float(path.stat().st_mtime)
        except Exception:
            mtime = 0.0

        cached = self._key_level_history_cache.get(sym)
        if cached is not None:
            # Reload if the file changed
            if float(self._key_level_history_mtime.get(sym, 0.0) or 0.0) == mtime:
                return cached

        try:
            h = pd.read_parquet(path)
        except Exception:
            return None

        # Normalize expected schema: timestamp + open/high/low/close
        try:
            if "timestamp" not in h.columns:
                return None
            ts = pd.to_datetime(h["timestamp"], errors="coerce", utc=True)
            o = pd.to_numeric(h.get("open"), errors="coerce")
            hi = pd.to_numeric(h.get("high"), errors="coerce")
            lo = pd.to_numeric(h.get("low"), errors="coerce")
            c = pd.to_numeric(h.get("close"), errors="coerce")

            out = pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c}, index=pd.DatetimeIndex(ts))
            out = out.dropna(subset=["open", "high", "low", "close"])
            out = out[~out.index.isna()].sort_index()
            out = out[~out.index.duplicated(keep="last")]
        except Exception:
            return None

        self._key_level_history_cache[sym] = out
        self._key_level_history_mtime[sym] = mtime
        return out

    @staticmethod
    def _df_to_levels_ohlc(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Convert a chart df (mplfinance formatted) into a UTC-indexed OHLC dataframe
        with lowercase column names suitable for key-level computations.
        """
        if df is None or df.empty:
            return None
        if not all(c in df.columns for c in ("Open", "High", "Low", "Close")):
            return None
        if not isinstance(df.index, pd.DatetimeIndex):
            return None

        idx = df.index
        try:
            if idx.tz is None:
                idx = idx.tz_localize(timezone.utc)
            else:
                idx = idx.tz_convert(timezone.utc)
        except Exception:
            return None

        try:
            out = pd.DataFrame(
                {
                    "open": pd.to_numeric(df["Open"], errors="coerce"),
                    "high": pd.to_numeric(df["High"], errors="coerce"),
                    "low": pd.to_numeric(df["Low"], errors="coerce"),
                    "close": pd.to_numeric(df["Close"], errors="coerce"),
                },
                index=idx,
            )
            out = out.dropna(subset=["open", "high", "low", "close"])
            out = out.sort_index()
            out = out[~out.index.duplicated(keep="last")]
            return out
        except Exception:
            return None
    
    def _create_tradingview_style(self):
        """Create custom mplfinance style matching TradingView dark theme."""
        # Define market colors (TradingView style)
        mc = mpf.make_marketcolors(
            up=CANDLE_UP,           # Teal-green for bullish
            down=CANDLE_DOWN,       # Red for bearish
            edge='inherit',         # Same color as body
            wick='inherit',         # Match body colors for wicks
            volume={'up': CANDLE_UP, 'down': CANDLE_DOWN},  # Color-code volume
            ohlc='i'                # Inherit colors
        )
        
        # Create style with TradingView dark theme
        self.style = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpl_style='dark_background',  # Start with dark theme
            gridstyle='--',                     # Dashed grid lines
            gridcolor=GRID_COLOR,               # Subtle grid color
            facecolor=DARK_BG,                  # Chart background
            edgecolor=GRID_COLOR,               # Edge color
            figcolor=DARK_BG,                   # Figure background
            y_on_right=True,                    # Price axis on right (TradingView style)
            rc={
                'axes.labelcolor': TEXT_PRIMARY,
                'axes.edgecolor': GRID_COLOR,
                'axes.spines.top': False,       # Remove top spine
                'axes.spines.right': False,     # Remove right spine
                'axes.spines.left': False,      # Remove left spine
                'xtick.color': TEXT_SECONDARY,
                'ytick.color': TEXT_PRIMARY,
                'text.color': TEXT_PRIMARY,
                'font.size': 10,
            }
        )
    
    @staticmethod
    def _save_png(
        fig,
        path: Path,
        *,
        dpi: int,
        render_mode: str = "telegram",
        pad_inches: float = 0.25,
        optimize: bool = False,
    ) -> None:
        """
        Save a chart PNG for Telegram/mobile delivery.

        Notes:
        - We always use content-cropping (`bbox_inches='tight'`) to avoid huge empty margins
          and to keep charts readable on phones.
        - `render_mode` is kept for backwards compatibility but is intentionally ignored.
        """
        try:
            pad = float(pad_inches)
        except Exception:
            pad = 0.25
        # Bound pad_inches to avoid accidental huge whitespace.
        pad = max(0.0, min(1.0, pad))

        fig.savefig(
            str(path),
            dpi=int(dpi),
            facecolor=DARK_BG,
            edgecolor="none",
            bbox_inches="tight",
            pad_inches=pad,
        )

        # Optional: lossless PNG optimization to reduce payload size.
        # This can improve Telegram preview load behavior on slow clients.
        if optimize:
            try:
                from PIL import Image  # type: ignore

                with Image.open(str(path)) as im:
                    im.save(str(path), format="PNG", optimize=True, compress_level=9)
            except Exception:
                # Best-effort only; keep the already-saved PNG.
                pass

    def _limit_yaxis_ticks(self, ax, max_ticks: int = 8) -> None:
        """Limit y-axis ticks to prevent overlapping labels.
        
        Args:
            ax: Matplotlib axis object
            max_ticks: Maximum number of ticks to show (default: 8)
        """
        try:
            ax.yaxis.set_major_locator(MaxNLocator(nbins=max_ticks, prune='both'))
        except Exception:
            pass  # If it fails, continue without limiting ticks
    
    def _add_price_labels_to_xaxis(self, ax, df: pd.DataFrame) -> None:
        """Add price numbers to the x-axis (bottom of chart).
        
        Args:
            ax: Matplotlib axis object
            df: DataFrame with price data
        """
        try:
            # Get current y-axis tick positions (these are the price levels)
            y_ticks = ax.get_yticks()
            
            # Get axis limits
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            
            # Filter y_ticks to only include those within the visible range
            visible_ticks = [tick for tick in y_ticks if ylim[0] <= tick <= ylim[1]]
            
            # Add price labels at the bottom of the chart (x-axis area)
            # Distribute them evenly along the x-axis
            num_labels = min(len(visible_ticks), 8)  # Limit to avoid clutter
            if num_labels > 0:
                # Select evenly spaced price levels
                selected_indices = np.linspace(0, len(visible_ticks) - 1, num_labels, dtype=int)
                selected_prices = [visible_ticks[i] for i in selected_indices]
                
                # Position labels evenly along x-axis
                x_positions = np.linspace(xlim[0], xlim[1], num_labels)
                
                # Add price labels at the bottom
                for x_pos, price in zip(x_positions, selected_prices):
                    ax.text(
                        x_pos,
                        ylim[0],
                        f"${price:.2f}",
                        horizontalalignment='center',
                        verticalalignment='top',
                        color=TEXT_SECONDARY,
                        fontsize=8,
                        alpha=0.75,
                        transform=ax.transData
                    )
        except Exception as e:
            logger.debug(f"Could not add price labels to x-axis: {e}")
            pass  # If it fails, continue without price labels on x-axis
    
    def _prepare_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """Prepare data for mplfinance (requires DatetimeIndex)."""
        df = data.copy()
        
        # Ensure timestamp is in index
        if "timestamp" not in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            if isinstance(df.index, pd.DatetimeIndex):
                pass  # Already correct
            else:
                # Create timestamp index
                df["timestamp"] = pd.date_range(
                    periods=len(df),
                    end=datetime.now(timezone.utc),
                    freq="1min"
                )
                df = df.set_index("timestamp")
        elif "timestamp" in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
                df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp")
        
        # Ensure required columns exist
        required_cols = ['open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Rename to uppercase for mplfinance
        df = df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
        })
        
        if 'volume' in df.columns:
            df = df.rename(columns={'volume': 'Volume'})
        
        return df
    
    def _infer_timeframe_from_data(self, df: pd.DataFrame) -> str:
        """Infer timeframe label from DataFrame index frequency."""
        if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
            return "1m"  # Default fallback
        
        # Try pandas frequency inference first
        try:
            freq = pd.infer_freq(df.index)
            if freq in ("T", "min", "1T", "1min"):
                return "1m"
            elif freq in ("5T", "5min"):
                return "5m"
            elif freq in ("15T", "15min"):
                return "15m"
            elif freq in ("H", "60T", "60min"):
                return "1h"
        except Exception:
            pass
        
        # Fallback: compute median interval between bars
        try:
            deltas = df.index.to_series().diff().dropna()
            if len(deltas) > 0:
                median_sec = deltas.median().total_seconds()
                if median_sec <= 90:
                    return "1m"
                elif median_sec <= 330:
                    return "5m"
                elif median_sec <= 960:
                    return "15m"
                else:
                    return "1h"
        except Exception:
            pass
        
        return "1m"  # Default
    
    def _add_indicators(self, data: pd.DataFrame) -> List:
        """Create list of indicators for mplfinance."""
        indicators = []
        
        # Add moving averages (EMA - Exponential Moving Average)
        if self.config.show_ma:
            for period in self.config.ma_periods:
                if period <= len(data):
                    color = MA_COLORS[self.config.ma_periods.index(period) % len(MA_COLORS)]
                    indicators.append(mpf.make_addplot(
                        data['Close'].ewm(span=period, adjust=False).mean(),
                        color=color,
                        width=1.2,
                        alpha=0.7,
                        label=f'EMA{period}'
                    ))
        
        # Add VWAP if requested
        if self.config.show_vwap:
            try:
                from pearlalgo.utils.vwap import VWAPCalculator
                vwap_calc = VWAPCalculator()
                # Convert back to lowercase for VWAPCalculator (it expects lowercase columns)
                vwap_df = data.reset_index().copy()
                vwap_df = vwap_df.rename(columns={
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low',
                    'Close': 'close',
                })
                if 'Volume' in vwap_df.columns:
                    vwap_df = vwap_df.rename(columns={'Volume': 'volume'})
                vwap_data = vwap_calc.calculate_vwap(vwap_df)
                vwap_value = vwap_data.get("vwap", 0)
                if vwap_value > 0:
                    # Create constant VWAP line
                    vwap_series = pd.Series([vwap_value] * len(data), index=data.index)
                    indicators.append(mpf.make_addplot(
                        vwap_series,
                        color=VWAP_COLOR,
                        width=1.5,
                        alpha=0.7,
                        label='VWAP'
                    ))
            except Exception as e:
                logger.debug(f"Error adding VWAP: {e}")
        
        return indicators
    
    def _add_entry_sl_tp_lines(self, data: pd.DataFrame, entry_price: float,
                               stop_loss: float, take_profit: float, direction: str) -> List:
        """Add Entry/SL/TP horizontal lines."""
        lines = []
        
        # Entry line
        entry_series = pd.Series([entry_price] * len(data), index=data.index)
        lines.append(mpf.make_addplot(
            entry_series,
            color=ENTRY_COLOR,
            width=2.5,
            linestyle='-',
            alpha=0.9,
            label=f'Entry: ${entry_price:.2f}'
        ))
        
        # Stop loss line
        if stop_loss and stop_loss > 0:
            sl_series = pd.Series([stop_loss] * len(data), index=data.index)
            lines.append(mpf.make_addplot(
                sl_series,
                color=SIGNAL_SHORT,
                width=2,
                linestyle='--',
                alpha=0.7,
                label=f'Stop: ${stop_loss:.2f}'
            ))
        
        # Take profit line
        if take_profit and take_profit > 0:
            tp_series = pd.Series([take_profit] * len(data), index=data.index)
            lines.append(mpf.make_addplot(
                tp_series,
                color=SIGNAL_LONG,
                width=2,
                linestyle='--',
                alpha=0.7,
                label=f'TP: ${take_profit:.2f}'
            ))
        
        return lines

    def _add_context_levels(self, data: pd.DataFrame, signal: Dict) -> List:
        """Add lightweight context levels (S/R + VWAP bands) for mobile readability."""
        lines: List = []

        try:
            # Support/Resistance levels (if available)
            sr = signal.get("sr_levels") or {}
            support = sr.get("strongest_support")
            resistance = sr.get("strongest_resistance")

            if support:
                sup_series = pd.Series([float(support)] * len(data), index=data.index)
                lines.append(
                    mpf.make_addplot(
                        sup_series,
                        color=TEXT_SECONDARY,
                        width=1.4,
                        linestyle=":",
                        alpha=0.7,
                        label=f"Support: {float(support):.2f}",
                    )
                )
            if resistance:
                res_series = pd.Series([float(resistance)] * len(data), index=data.index)
                lines.append(
                    mpf.make_addplot(
                        res_series,
                        color=TEXT_SECONDARY,
                        width=1.4,
                        linestyle=":",
                        alpha=0.7,
                        label=f"Resistance: {float(resistance):.2f}",
                    )
                )

            # VWAP bands (if computed by the scanner)
            vwap = signal.get("vwap_data") or {}
            vwap_val = vwap.get("vwap")
            if vwap_val and float(vwap_val) > 0:
                for k, lbl, alpha in (
                    ("vwap_upper_1", "VWAP +1", 0.35),
                    ("vwap_lower_1", "VWAP -1", 0.35),
                    ("vwap_upper_2", "VWAP +2", 0.25),
                    ("vwap_lower_2", "VWAP -2", 0.25),
                ):
                    level = vwap.get(k)
                    if level and float(level) > 0 and float(level) != float(vwap_val):
                        series = pd.Series([float(level)] * len(data), index=data.index)
                        lines.append(
                            mpf.make_addplot(
                                series,
                                color=VWAP_COLOR,
                                width=1.0,
                                linestyle="--",
                                alpha=alpha,
                                label=lbl,
                            )
                        )
        except Exception as e:
            logger.debug(f"Error adding context levels: {e}")

        return lines

    def _infer_bar_delta(self, idx: pd.DatetimeIndex) -> timedelta:
        """Infer bar spacing from index; fallback to 1 minute."""
        try:
            if idx is not None and len(idx) >= 2:
                dt = idx[-1] - idx[-2]
                if isinstance(dt, pd.Timedelta):
                    dt = dt.to_pytimedelta()
                if isinstance(dt, timedelta) and dt.total_seconds() > 0:
                    return dt
        except Exception:
            pass
        return timedelta(minutes=1)

    def _safe_parse_dt(self, value: Any) -> Optional[pd.Timestamp]:
        try:
            ts = pd.to_datetime(value, errors="coerce")
            if pd.isna(ts):
                return None
            if isinstance(ts, pd.Timestamp):
                # Normalize tz handling to UTC
                if ts.tzinfo is None:
                    ts = ts.tz_localize(timezone.utc)
                else:
                    ts = ts.tz_convert(timezone.utc)
                return ts
        except Exception:
            return None
        return None

    def _ts_to_x(
        self,
        idx: Optional[pd.DatetimeIndex],
        ts: Optional[pd.Timestamp],
        *,
        side: str = "left",
    ) -> Optional[float]:
        """Convert a timestamp into mplfinance x-coordinate space (0..N).

        mplfinance candlestick charts use integer x positions (0..N-1) and format
        tick labels as datetimes. HUD overlays must use the same numeric x space.
        """
        if idx is None or ts is None:
            return None
        if not isinstance(idx, pd.DatetimeIndex) or len(idx) == 0:
            return None
        try:
            if not isinstance(ts, pd.Timestamp):
                ts = pd.to_datetime(ts, errors="coerce")
            if ts is None or pd.isna(ts):
                return None

            # Align timezone to index timezone if needed
            if getattr(idx, "tz", None) is not None:
                if ts.tzinfo is None:
                    ts = ts.tz_localize(idx.tz)
                else:
                    ts = ts.tz_convert(idx.tz)

            pos = int(idx.searchsorted(ts, side=side))
            if pos < 0:
                pos = 0
            if pos > len(idx):
                pos = len(idx)
            return float(pos)
        except Exception:
            return None

    def _collect_level_candidates(
        self,
        df: pd.DataFrame,
        signal: Dict,
        hud: Dict,
        *,
        extra_levels: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Collect level candidates for right-side merged labeling."""
        levels: List[Dict[str, Any]] = []

        # Current price (anchor for level relevance ranking)
        try:
            current_price = float(df["Close"].iloc[-1])
        except Exception:
            current_price = float(signal.get("entry_price") or 0.0) or 0.0

        def _add(price: Any, label: str, color: str, *, priority: int, linestyle: str = "--", lw: float = 1.0, alpha: float = 0.6, kind: str = "key_level"):
            """Add a level candidate with optional kind tag for filtering."""
            try:
                p = float(price)
            except Exception:
                return
            if not np.isfinite(p) or p <= 0:
                return
            levels.append(
                {
                    "price": float(p),
                    "label": str(label),
                    "color": str(color),
                    "priority": int(priority),
                    "linestyle": linestyle,
                    "lw": float(lw),
                    "alpha": float(alpha),
                    "kind": str(kind),  # Category for filtering (vwap, key_level, trade, etc.)
                }
            )

        # Trade lines (always highest priority)
        _add(signal.get("entry_price"), "Entry", ENTRY_COLOR, priority=100, linestyle="-", lw=1.8, alpha=0.95, kind="trade")
        _add(signal.get("stop_loss"), "Stop", SIGNAL_SHORT, priority=95, linestyle="--", lw=1.4, alpha=0.9, kind="trade")
        _add(signal.get("take_profit"), "Target", SIGNAL_LONG, priority=95, linestyle="--", lw=1.4, alpha=0.9, kind="trade")

        # Extra levels (e.g., Exit)
        if extra_levels:
            for e in extra_levels:
                _add(
                    e.get("price"),
                    str(e.get("label") or "Level"),
                    str(e.get("color") or TEXT_PRIMARY),
                    priority=int(e.get("priority") or 80),
                    linestyle=str(e.get("linestyle") or "-"),
                    lw=float(e.get("lw") or 1.4),
                    alpha=float(e.get("alpha") or 0.9),
                )

        if not self.config.show_key_levels:
            return levels, current_price

        # VWAP + bands (from scanner)
        vwap = (hud.get("vwap") or signal.get("vwap_data") or {}) if isinstance(hud, dict) else (signal.get("vwap_data") or {})
        if isinstance(vwap, dict):
            _add(vwap.get("vwap"), "VWAP", VWAP_COLOR, priority=60, linestyle="-", lw=1.2, alpha=0.65, kind="vwap")
            # Use sigma wording (matches VWAP AA bands + avoids “2x” ambiguity in right labels)
            _add(vwap.get("vwap_upper_1"), "VWAP +1σ", VWAP_COLOR, priority=40, linestyle="--", lw=1.0, alpha=0.35, kind="vwap")
            _add(vwap.get("vwap_lower_1"), "VWAP -1σ", VWAP_COLOR, priority=40, linestyle="--", lw=1.0, alpha=0.35, kind="vwap")
            _add(vwap.get("vwap_upper_2"), "VWAP +2σ", VWAP_COLOR, priority=30, linestyle="--", lw=0.9, alpha=0.25, kind="vwap")
            _add(vwap.get("vwap_lower_2"), "VWAP -2σ", VWAP_COLOR, priority=30, linestyle="--", lw=0.9, alpha=0.25, kind="vwap")

        # Volume profile levels (POC/VAH/VAL)
        vp = hud.get("volume_profile") or signal.get("volume_profile") or {}
        if isinstance(vp, dict):
            _add(vp.get("poc"), "POC", TEXT_SECONDARY, priority=35, linestyle=":", lw=1.1, alpha=0.55)
            _add(vp.get("value_area_high"), "VAH", TEXT_SECONDARY, priority=30, linestyle=":", lw=1.0, alpha=0.45)
            _add(vp.get("value_area_low"), "VAL", TEXT_SECONDARY, priority=30, linestyle=":", lw=1.0, alpha=0.45)

        # Strongest S/R
        sr = hud.get("sr_levels") or signal.get("sr_levels") or {}
        if isinstance(sr, dict):
            _add(sr.get("strongest_support"), "Support", TEXT_SECONDARY, priority=25, linestyle=":", lw=1.0, alpha=0.55)
            _add(sr.get("strongest_resistance"), "Resist", TEXT_SECONDARY, priority=25, linestyle=":", lw=1.0, alpha=0.55)

        # RTH + ETH key levels
        # ETH (18:00→17:00 ET) represents the CME trading day, so we use Pine-style
        # daily labels: DO (Daily Open), PDH/PDL/PDM (Prev Day High/Low/Mid).
        kl = hud.get("key_levels") if isinstance(hud, dict) else None
        if isinstance(kl, dict):
            rth = (kl.get("rth") or {})
            eth = (kl.get("eth") or {})

            rth_cur = rth.get("current") or {}
            rth_prev = rth.get("previous") or {}
            eth_cur = eth.get("current") or {}
            eth_prev = eth.get("previous") or {}

            # RTH session levels (regular trading hours 09:30-16:00 ET)
            _add(rth_cur.get("open"), "RTH Open", ENTRY_COLOR, priority=50, linestyle="--", lw=1.0, alpha=0.35)
            _add(rth_prev.get("high"), "RTH PDH", TEXT_SECONDARY, priority=45, linestyle="--", lw=1.0, alpha=0.30)
            _add(rth_prev.get("mid"), "RTH PDM", TEXT_SECONDARY, priority=40, linestyle=":", lw=1.0, alpha=0.25)
            _add(rth_prev.get("low"), "RTH PDL", TEXT_SECONDARY, priority=45, linestyle="--", lw=1.0, alpha=0.30)

            # Pine-style Daily key levels (ETH = CME trading day 18:00→17:00 ET)
            # DO = Daily Open, PDH/PDL/PDM = Prev Day High/Low/Mid
            _add(eth_cur.get("open"), "DO", ENTRY_COLOR, priority=60, linestyle="-", lw=1.2, alpha=0.50)
            _add(eth_prev.get("high"), "PDH", TEXT_SECONDARY, priority=58, linestyle="--", lw=1.1, alpha=0.45)
            _add(eth_prev.get("low"), "PDL", TEXT_SECONDARY, priority=58, linestyle="--", lw=1.1, alpha=0.45)
            _add(eth_prev.get("mid"), "PDM", TEXT_SECONDARY, priority=52, linestyle=":", lw=1.0, alpha=0.35)

        # SpacemanBTC-style higher-timeframe levels (Weekly/Monthly/Quarterly/Yearly/4H/Monday).
        # Compute at chart-render time using the candle window + optional local parquet history.
        try:
            symbol = str(signal.get("symbol") or hud.get("symbol") or "MNQ")
            hist = self._load_key_level_history(symbol)
            base = self._df_to_levels_ohlc(df)

            levels_df = None
            if hist is not None and base is not None:
                # Determinism + relevance guard:
                # Only merge external historical data if it is time-aligned with the chart window.
                # This prevents local `data/historical/*` files from contaminating deterministic tests
                # (e.g., history ending in 2025 while synthetic chart data is 2024).
                try:
                    hist_end = hist.index.max()
                    base_end = base.index.max()
                    if hist_end is not None and base_end is not None:
                        gap_days = abs((hist_end - base_end).total_seconds()) / 86400.0
                        if gap_days > 7.0:
                            hist = None
                except Exception:
                    pass

            if hist is not None and base is not None:
                levels_df = pd.concat([hist, base]).sort_index()
                levels_df = levels_df[~levels_df.index.duplicated(keep="last")]
            elif base is not None:
                levels_df = base
            elif hist is not None:
                levels_df = hist

            if levels_df is not None and not levels_df.empty:
                sp = compute_spaceman_key_levels(levels_df)
            else:
                sp = None

            if isinstance(sp, dict):
                # Get configured timeframes to display
                enabled_tfs = set(tf.lower() for tf in self.config.key_level_timeframes)

                # 4H levels (orange) - show if "4h" in config
                if "4h" in enabled_tfs:
                    c_4h = "#ff9800"  # orange
                    intra = sp.get("intra_4h") or {}
                    if isinstance(intra, dict):
                        cur = intra.get("current") or {}
                        prev = intra.get("previous") or {}
                        _add(cur.get("open"), "4H-O", c_4h, priority=44, linestyle="--", lw=1.0, alpha=0.30)
                        _add(prev.get("high"), "P-4H-H", c_4h, priority=43, linestyle="--", lw=1.0, alpha=0.26)
                        _add(prev.get("low"), "P-4H-L", c_4h, priority=43, linestyle="--", lw=1.0, alpha=0.26)
                        _add(prev.get("mid"), "P-4H-M", c_4h, priority=40, linestyle=":", lw=1.0, alpha=0.22)

                # Weekly levels (yellow) - show if "weekly" in config
                if "weekly" in enabled_tfs:
                    c_weekly = "#fffcbc"  # pale yellow (SpacemanBTC style)
                    weekly = sp.get("weekly") or {}
                    if isinstance(weekly, dict):
                        cur_w = weekly.get("current") or {}
                        prev_w = weekly.get("previous") or {}
                        _add(cur_w.get("open"), "W-O", c_weekly, priority=38, linestyle="--", lw=1.2, alpha=0.35)
                        _add(prev_w.get("high"), "P-W-H", c_weekly, priority=37, linestyle="--", lw=1.2, alpha=0.30)
                        _add(prev_w.get("low"), "P-W-L", c_weekly, priority=37, linestyle="--", lw=1.2, alpha=0.30)
                        _add(prev_w.get("mid"), "P-W-M", c_weekly, priority=35, linestyle=":", lw=1.0, alpha=0.25)

                # Monthly levels (green) - show if "monthly" in config
                if "monthly" in enabled_tfs:
                    c_monthly = "#08d48c"  # green (SpacemanBTC style)
                    monthly = sp.get("monthly") or {}
                    if isinstance(monthly, dict):
                        cur_m = monthly.get("current") or {}
                        prev_m = monthly.get("previous") or {}
                        _add(cur_m.get("open"), "M-O", c_monthly, priority=34, linestyle="--", lw=1.4, alpha=0.35)
                        _add(prev_m.get("high"), "P-M-H", c_monthly, priority=33, linestyle="--", lw=1.4, alpha=0.30)
                        _add(prev_m.get("low"), "P-M-L", c_monthly, priority=33, linestyle="--", lw=1.4, alpha=0.30)
                        _add(prev_m.get("mid"), "P-M-M", c_monthly, priority=32, linestyle=":", lw=1.0, alpha=0.25)

                # Monday Range levels (white) - show if "monday" in config
                if "monday" in enabled_tfs:
                    c_monday = "#ffffff"  # white (SpacemanBTC style)
                    monday = sp.get("monday_range") or {}
                    if isinstance(monday, dict):
                        _add(monday.get("high"), "Mon-H", c_monday, priority=31, linestyle="--", lw=1.0, alpha=0.30)
                        _add(monday.get("low"), "Mon-L", c_monday, priority=31, linestyle="--", lw=1.0, alpha=0.30)
                        _add(monday.get("mid"), "Mon-M", c_monday, priority=30, linestyle=":", lw=1.0, alpha=0.25)

                # Quarterly levels (red) - show if "quarterly" in config
                if "quarterly" in enabled_tfs:
                    c_quarterly = "#ff0000"  # red (SpacemanBTC style)
                    quarterly = sp.get("quarterly") or {}
                    if isinstance(quarterly, dict):
                        cur_q = quarterly.get("current") or {}
                        prev_q = quarterly.get("previous") or {}
                        _add(cur_q.get("open"), "Q-O", c_quarterly, priority=29, linestyle="--", lw=1.4, alpha=0.35)
                        _add(prev_q.get("high"), "P-Q-H", c_quarterly, priority=28, linestyle="--", lw=1.4, alpha=0.30)
                        _add(prev_q.get("low"), "P-Q-L", c_quarterly, priority=28, linestyle="--", lw=1.4, alpha=0.30)
                        _add(prev_q.get("mid"), "P-Q-M", c_quarterly, priority=27, linestyle=":", lw=1.0, alpha=0.25)

                # Yearly levels (red) - show if "yearly" in config
                if "yearly" in enabled_tfs:
                    c_yearly = "#ff0000"  # red (SpacemanBTC style)
                    yearly = sp.get("yearly") or {}
                    if isinstance(yearly, dict):
                        cur_y = yearly.get("current") or {}
                        # Yearly shows current year's O/H/L/M
                        _add(cur_y.get("open"), "Y-O", c_yearly, priority=26, linestyle="--", lw=1.6, alpha=0.40)
                        _add(cur_y.get("high"), "CY-H", c_yearly, priority=25, linestyle="--", lw=1.6, alpha=0.35)
                        _add(cur_y.get("low"), "CY-L", c_yearly, priority=25, linestyle="--", lw=1.6, alpha=0.35)
                        _add(cur_y.get("mid"), "CY-M", c_yearly, priority=24, linestyle=":", lw=1.2, alpha=0.30)
        except Exception:
            pass

        return levels, current_price

    def _merge_levels(
        self,
        levels: List[Dict[str, Any]],
        *,
        tick_size: float,
        merge_ticks: int,
    ) -> List[Dict[str, Any]]:
        """Merge nearby levels into a single right-label cluster.
        
        Visual integrity note: The merged level is drawn at the TOP-PRIORITY level's
        exact price (not a weighted average) to preserve semantic accuracy. This
        ensures traders see the actual level, not a synthetic interpolated price.
        """
        if not levels:
            return []

        thr = max(0.0, float(tick_size) * float(max(0, int(merge_ticks))))
        if thr <= 0:
            return levels

        levels_sorted = sorted(levels, key=lambda x: float(x.get("price", 0.0)))
        groups: List[List[Dict[str, Any]]] = []
        cur: List[Dict[str, Any]] = []

        for lvl in levels_sorted:
            if not cur:
                cur = [lvl]
                continue
            if abs(float(lvl["price"]) - float(cur[-1]["price"])) <= thr:
                cur.append(lvl)
            else:
                groups.append(cur)
                cur = [lvl]
        if cur:
            groups.append(cur)

        merged: List[Dict[str, Any]] = []
        for g in groups:
            # Sort by priority descending to identify the anchor level
            g_sorted = sorted(g, key=lambda x: int(x.get("priority", 0)), reverse=True)
            
            # Use the TOP-PRIORITY level's exact price as the anchor (not averaged)
            # This preserves semantic accuracy - the line is at an actual level
            top = g_sorted[0]
            anchor_price = float(top.get("price", 0.0))

            labels = [str(x.get("label") or "") for x in g_sorted if str(x.get("label") or "")]
            # Compact merged labels: max 2 labels, use "/" separator (no spaces)
            # If more than 2, show top 2 + count
            if len(labels) > 2:
                label = f"{labels[0]}/{labels[1]}+{len(labels)-2}"
            elif len(labels) == 2:
                label = f"{labels[0]}/{labels[1]}"
            else:
                label = labels[0] if labels else ""

            merged.append(
                {
                    "price": anchor_price,  # Exact price of top-priority level
                    "label": label,
                    "color": str(top.get("color") or TEXT_PRIMARY),
                    "priority": int(top.get("priority", 0)),
                    "linestyle": str(top.get("linestyle") or "--"),
                    "lw": float(top.get("lw") or 1.0),
                    "alpha": float(top.get("alpha") or 0.6),
                    "kind": str(top.get("kind") or "key_level"),  # Preserve kind for filtering
                }
            )

        return merged

    def _draw_right_labels(
        self,
        fig,
        ax,
        merged_levels: List[Dict[str, Any]],
        *,
        current_price: float,
        max_labels: int,
        min_label_spacing_pts: float = 10.0,
    ) -> None:
        """Draw TradingView-style right-side level labels with minimal clutter.
        
        Only draws levels that fall within the current visible y-range to avoid
        expanding the chart scale or cluttering with out-of-view levels.
        
        Visual integrity notes:
        - Labels are drawn with explicit z-order (ZORDER_TEXT_LABELS)
        - Level lines use ZORDER_LEVEL_LINES
        - Collision detection prevents overlapping labels within min_label_spacing_pts
        """
        if not merged_levels:
            return

        # Capture current y-limits BEFORE drawing - only show levels in visible range
        try:
            ymin, ymax = ax.get_ylim()
        except Exception:
            ymin, ymax = 0.0, float("inf")

        # Filter to levels within visible y-range (with small margin for edge labels)
        margin = (ymax - ymin) * 0.02 if ymax > ymin else 0.0
        visible_levels = [
            lvl for lvl in merged_levels
            if (ymin - margin) <= float(lvl.get("price", 0.0)) <= (ymax + margin)
        ]

        if not visible_levels:
            return

        # Hybrid label policy: filter out VWAP right labels for mobile/Telegram mode
        # (VWAP lines/bands are still drawn; only the right-side text labels are removed)
        if self.config.mobile_mode:
            visible_levels = [
                lvl for lvl in visible_levels
                if lvl.get("kind") != "vwap"
            ]
            if not visible_levels:
                return

        # Pick most relevant levels (priority first, then proximity to current price)
        def _score(lvl: Dict[str, Any]) -> Tuple[int, float]:
            pri = int(lvl.get("priority", 0))
            try:
                dist = abs(float(lvl.get("price", 0.0)) - float(current_price))
            except Exception:
                dist = 1e9
            return (-pri, dist)

        candidates = sorted(visible_levels, key=_score)
        
        # Collision-free stacking: compute dynamic max labels and stack overlapping labels
        # Convert min_label_spacing_pts to data units using figure transform
        try:
            # Get pixels-per-data-unit for y-axis
            bbox = ax.get_window_extent()
            y_pixels = bbox.height
            y_range = ymax - ymin
            pts_per_data = y_pixels / y_range if y_range > 0 else 1.0
            min_spacing_data = min_label_spacing_pts / pts_per_data if pts_per_data > 0 else 0.0
            
            # Dynamic max labels: estimate how many labels fit vertically
            # ~18pt per label (font + padding), with buffer
            label_height_pts = 18.0
            dynamic_max = max(4, int(y_pixels / label_height_pts * 0.7))  # 70% fill
            effective_max = min(max_labels, dynamic_max)
        except Exception:
            min_spacing_data = (ymax - ymin) * 0.02  # Fallback: 2% of range
            effective_max = max_labels
        
        # Select top-priority labels up to effective_max
        selected = candidates[:max(1, int(effective_max))]
        
        if not selected:
            return

        # Create extra right margin so labels aren't clipped (wider for safety)
        try:
            fig.subplots_adjust(right=0.78)
        except Exception:
            pass

        trans = ax.get_yaxis_transform()
        
        # Collision-free stacking: assign display positions (may differ from true price)
        # This prevents overlapping labels while preserving accurate price lines
        occupied_positions: List[float] = []
        label_positions: List[Tuple[Dict[str, Any], float]] = []  # (level, display_y)
        
        for lvl in selected:
            p = float(lvl["price"])
            display_y = p
            
            # Check collision with already-placed labels and shift if needed
            for _ in range(20):  # Max iterations to prevent infinite loop
                collision = False
                for occ_y in occupied_positions:
                    if abs(display_y - occ_y) < min_spacing_data:
                        collision = True
                        # Shift up or down depending on position in range
                        if display_y > (ymin + ymax) / 2:
                            display_y = occ_y - min_spacing_data  # Shift down
                        else:
                            display_y = occ_y + min_spacing_data  # Shift up
                        break
                if not collision:
                    break
            
            # Clamp to visible range
            display_y = max(ymin + min_spacing_data * 0.5, min(ymax - min_spacing_data * 0.5, display_y))
            occupied_positions.append(display_y)
            label_positions.append((lvl, display_y))

        # Draw all labels with leader lines where needed
        for lvl, display_y in label_positions:
            p = float(lvl["price"])
            label = str(lvl.get("label") or "")
            color = str(lvl.get("color") or TEXT_PRIMARY)
            alpha = float(lvl.get("alpha") or 0.6)
            ls = str(lvl.get("linestyle") or "--")
            lw = float(lvl.get("lw") or 1.0)

            # Level line at TRUE price (not display position)
            ax.axhline(
                p,
                color=color,
                linestyle=ls,
                linewidth=lw,
                alpha=min(1.0, max(0.05, alpha)),
                zorder=ZORDER_LEVEL_LINES,
            )

            # Leader line if label is shifted from true price
            needs_leader = abs(display_y - p) > min_spacing_data * 0.3
            if needs_leader:
                # Draw subtle connector from true price to label position
                ax.plot(
                    [1.0, 1.003], [p, display_y],
                    color=color,
                    linewidth=0.8,
                    alpha=0.4,
                    transform=trans,
                    clip_on=False,
                    zorder=ZORDER_TEXT_LABELS - 1,
                )

            # Right label at DISPLAY position (may be stacked)
            try:
                rgba = mcolors.to_rgba(color, alpha=0.20)
            except Exception:
                rgba = (0, 0, 0, 0.2)
            # Compact label format: "Label price" with single space, no thousands separator for cleaner look
            txt = f"{label} {p:.2f}" if label else f"{p:.2f}"
            # Use smaller font for mobile mode
            label_fontsize = FONT_SIZE_LABEL_MOBILE if self.config.mobile_mode else FONT_SIZE_LABEL
            ax.text(
                1.005,
                display_y,
                txt,
                transform=trans,
                ha="left",
                va="center",
                fontsize=label_fontsize,
                color=TEXT_PRIMARY,
                bbox=dict(facecolor=rgba, edgecolor="none", boxstyle="round,pad=0.2"),
                clip_on=False,
                zorder=ZORDER_TEXT_LABELS,
            )

        # Restore original y-limits to prevent autoscale from level lines
        try:
            ax.set_ylim(ymin, ymax)
        except Exception:
            pass

    def _draw_sessions_overlay(self, ax, hud: Dict, *, idx: Optional[pd.DatetimeIndex] = None) -> None:
        """Draw session shading/labels in mplfinance x-coordinate space (0..N).

        NOTE: mplfinance candle charts use integer x positions and a datetime formatter.
        Do NOT pass datetimes directly into axvspan/hlines; it can push candles off-screen.
        
        Visual integrity notes:
        - Session shading uses ZORDER_SESSION_SHADING (lowest layer)
        - Session O/C/Avg lines use ZORDER_ZONES (behind candles)
        - Session labels placed slightly inside panel (ymin + offset) for consistent visibility
        """
        if not self.config.show_sessions:
            return
        sessions = hud.get("sessions") if isinstance(hud, dict) else None
        if not isinstance(sessions, list) or not sessions:
            return
        if idx is None or not isinstance(idx, pd.DatetimeIndex) or len(idx) == 0:
            return

        # Get y-limits once for consistent label placement
        try:
            ymin, ymax = ax.get_ylim()
            y_range = ymax - ymin
            # Place labels slightly inside the panel (above ymin)
            # Mobile mode: higher offset (8%) to avoid RR-box overlap
            # Desktop mode: smaller offset (3%)
            offset_pct = 0.08 if self.config.mobile_mode else 0.03
            label_y_offset = y_range * offset_pct if y_range > 0 else 0.0
        except Exception:
            ymin = 0.0
            label_y_offset = 0.0

        for s in sessions:
            try:
                start = self._safe_parse_dt(s.get("start"))
                end = self._safe_parse_dt(s.get("end"))
                if not start or not end:
                    continue

                start_x = self._ts_to_x(idx, start, side="left")
                # Treat session end as exclusive (aligns with baseline shading geometry).
                end_x = self._ts_to_x(idx, end, side="left")
                if start_x is None or end_x is None or end_x <= start_x:
                    continue

                color = str(s.get("color") or "#444444")
                
                # Session shading (lowest z-order - behind everything)
                ax.axvspan(
                    start_x, end_x,
                    color=color,
                    alpha=0.08,
                    linewidth=0,
                    zorder=ZORDER_SESSION_SHADING,
                )

                if self.config.show_session_oc:
                    open_ = float(s.get("open", 0.0) or 0.0)
                    close_ = float(s.get("close", 0.0) or 0.0)
                    if open_ > 0:
                        ax.hlines(
                            open_, start_x, end_x,
                            colors=color,
                            linestyles="--",
                            linewidth=1.0,
                            alpha=0.55,
                            zorder=ZORDER_ZONES,
                        )
                    if close_ > 0:
                        ax.hlines(
                            close_, start_x, end_x,
                            colors=color,
                            linestyles="--",
                            linewidth=1.0,
                            alpha=0.35,
                            zorder=ZORDER_ZONES,
                        )

                if self.config.show_session_average:
                    avg = float(s.get("avg", 0.0) or 0.0)
                    if avg > 0:
                        ax.hlines(
                            avg, start_x, end_x,
                            colors=color,
                            linestyles=":",
                            linewidth=1.2,
                            alpha=0.55,
                            zorder=ZORDER_ZONES,
                        )

                if self.config.show_session_names:
                    # Build label with session name on top, stats below (like TradingView)
                    name = str(s.get("name") or "Session")
                    
                    # Stats line (Range and Avg on same line, comma-separated)
                    stats_parts = []
                    if self.config.show_session_range_stats:
                        if self.config.show_session_tick_range:
                            rt = s.get("range_ticks")
                            if rt is not None:
                                stats_parts.append(f"Range: {rt}")
                        if self.config.show_session_average:
                            avg = s.get("avg")
                            if avg is not None:
                                stats_parts.append(f"Avg: {float(avg):,.2f}")
                    
                    # Format: "SessionName\nRange: X, Avg: Y,YYY.YY"
                    if stats_parts:
                        label = f"{name}\n{', '.join(stats_parts)}"
                    else:
                        label = name

                    # Place label inside the panel (ymin + offset) for consistent visibility
                    # This prevents labels from overlapping panel boundaries
                    label_y = ymin + label_y_offset
                    x_label = min(max(start_x + 0.5, 0.0), float(max(0, len(idx) - 1)))
                    ax.text(
                        x_label,
                        label_y,
                        label,
                        ha="left",
                        va="bottom",
                        fontsize=FONT_SIZE_SESSION,
                        color=color,
                        alpha=0.9,
                        zorder=ZORDER_TEXT_LABELS,
                    )
            except Exception:
                continue

    def _draw_supply_demand_overlay(self, ax, hud: Dict) -> None:
        """Draw LuxAlgo-style supply/demand zones with explicit z-order.
        
        Only draws zones that intersect with the visible y-range (dynamic filtering).
        """
        if not self.config.show_supply_demand:
            return
        sd = hud.get("supply_demand_vr") if isinstance(hud, dict) else None
        if not isinstance(sd, dict):
            return

        supply = sd.get("supply") or {}
        demand = sd.get("demand") or {}

        try:
            # Get visible y-range for dynamic filtering
            ymin, ymax = ax.get_ylim()
            
            def _zone_visible(bot: float, top: float) -> bool:
                """Check if zone intersects with visible range."""
                return top >= ymin and bot <= ymax
            
            def _price_visible(price: float) -> bool:
                """Check if price is within visible range."""
                return ymin <= price <= ymax

            # Colors from Pine reference (LuxAlgo): supply blue, demand orange.
            sup_color = SUPPLY_ZONE_COLOR
            dem_color = DEMAND_ZONE_COLOR

            s_top = float(supply.get("top", 0.0) or 0.0)
            s_bot = float(supply.get("bottom", 0.0) or 0.0)
            d_top = float(demand.get("top", 0.0) or 0.0)
            d_bot = float(demand.get("bottom", 0.0) or 0.0)

            # Only draw supply zone if it intersects visible range
            if s_top > 0 and s_bot > 0 and s_top > s_bot and _zone_visible(s_bot, s_top):
                ax.axhspan(s_bot, s_top, facecolor=sup_color, alpha=ALPHA_ZONE_SUPPLY_DEMAND, edgecolor="none", zorder=ZORDER_ZONES)
                s_avg = float(supply.get("avg", (s_top + s_bot) / 2.0))
                s_wavg = float(supply.get("wavg", (s_top + s_bot) / 2.0))
                if _price_visible(s_avg):
                    ax.axhline(s_avg, color=sup_color, linewidth=1.0, alpha=0.7, zorder=ZORDER_ZONES)
                if _price_visible(s_wavg):
                    ax.axhline(s_wavg, color=sup_color, linewidth=1.0, alpha=0.7, linestyle="--", zorder=ZORDER_ZONES)

            # Only draw demand zone if it intersects visible range
            if d_top > 0 and d_bot > 0 and d_top > d_bot and _zone_visible(d_bot, d_top):
                ax.axhspan(d_bot, d_top, facecolor=dem_color, alpha=ALPHA_ZONE_SUPPLY_DEMAND, edgecolor="none", zorder=ZORDER_ZONES)
                d_avg = float(demand.get("avg", (d_top + d_bot) / 2.0))
                d_wavg = float(demand.get("wavg", (d_top + d_bot) / 2.0))
                if _price_visible(d_avg):
                    ax.axhline(d_avg, color=dem_color, linewidth=1.0, alpha=0.7, zorder=ZORDER_ZONES)
                if _price_visible(d_wavg):
                    ax.axhline(d_wavg, color=dem_color, linewidth=1.0, alpha=0.7, linestyle="--", zorder=ZORDER_ZONES)
        except Exception:
            return

    def _draw_vwap_band_fills(self, ax, hud: Dict) -> None:
        """Draw VWAP band fills (optional visual enhancement).
        
        Creates semi-transparent fills between VWAP line and ±1σ bands for better
        visibility of the VWAP channel. Only drawn if vwap_fill_bands is enabled.
        """
        if not self.config.vwap_fill_bands:
            return
        
        vwap_data = hud.get("vwap") if isinstance(hud, dict) else None
        if not isinstance(vwap_data, dict):
            return
        
        try:
            # Get stored series data
            vwap_series = vwap_data.get("_series")
            upper1 = vwap_data.get("_upper1")
            lower1 = vwap_data.get("_lower1")
            
            if vwap_series is None or upper1 is None or lower1 is None:
                return
            
            # Fill between VWAP and upper band
            if not vwap_series.isna().all() and not upper1.isna().all():
                x_coords = np.arange(len(vwap_series))
                # Fill between VWAP and +1σ (upper region)
                ax.fill_between(
                    x_coords,
                    vwap_series.ffill().bfill().values,
                    upper1.ffill().bfill().values,
                    color=VWAP_COLOR,
                    alpha=ALPHA_VWAP_BAND_FILL,
                    zorder=ZORDER_ZONES,
                    linewidth=0,
                )
            
            # Fill between VWAP and lower band
            if not vwap_series.isna().all() and not lower1.isna().all():
                x_coords = np.arange(len(vwap_series))
                # Fill between VWAP and -1σ (lower region)
                ax.fill_between(
                    x_coords,
                    lower1.ffill().bfill().values,
                    vwap_series.ffill().bfill().values,
                    color=VWAP_COLOR,
                    alpha=ALPHA_VWAP_BAND_FILL,
                    zorder=ZORDER_ZONES,
                    linewidth=0,
                )
        except Exception:
            return

    def _draw_rsi_overbought_oversold_shading(self, ax_rsi, rsi_series: pd.Series) -> None:
        """Draw optional overbought/oversold shading on RSI panel.
        
        Adds subtle background shading:
        - Green tint in oversold zone (RSI < 30)
        - Red tint in overbought zone (RSI > 70)
        """
        if not self.config.rsi_overbought_oversold_shading:
            return
        
        if ax_rsi is None or rsi_series is None or rsi_series.empty:
            return
        
        try:
            x_coords = np.arange(len(rsi_series))
            rsi_vals = rsi_series.fillna(50).values  # Default to 50 for NaN
            
            # Oversold zone shading (RSI < 30) - green tint
            oversold_mask = rsi_vals < 30
            if oversold_mask.any():
                ax_rsi.fill_between(
                    x_coords,
                    0,
                    30,
                    where=oversold_mask,
                    color=SIGNAL_LONG,  # Green
                    alpha=0.08,
                    zorder=0,
                    linewidth=0,
                )
            
            # Overbought zone shading (RSI > 70) - red tint
            overbought_mask = rsi_vals > 70
            if overbought_mask.any():
                ax_rsi.fill_between(
                    x_coords,
                    70,
                    100,
                    where=overbought_mask,
                    color=SIGNAL_SHORT,  # Red
                    alpha=0.08,
                    zorder=0,
                    linewidth=0,
                )
        except Exception:
            return

    def _draw_power_channel_overlay(self, ax, hud: Dict) -> None:
        """Draw ChartPrime-style power channel with explicit z-order.
        
        Only draws zones/lines that intersect with the visible y-range (dynamic filtering).
        """
        pc = hud.get("power_channel") if isinstance(hud, dict) else None
        if not isinstance(pc, dict):
            return

        try:
            # Get visible y-range for dynamic filtering
            ymin, ymax = ax.get_ylim()
            
            def _zone_visible(bot: float, top: float) -> bool:
                """Check if zone intersects with visible range."""
                return top >= ymin and bot <= ymax
            
            def _price_visible(price: float) -> bool:
                """Check if price is within visible range."""
                return ymin <= price <= ymax

            # Draw power channel zones only if show_power_channel is True
            if self.config.show_power_channel:
                t_col = POWER_CHANNEL_RESISTANCE  # fuchsia (Pine default)
                b_col = POWER_CHANNEL_SUPPORT  # lime (Pine default)

                res_top = float(pc.get("res_area_top", 0.0) or 0.0)
                res_bot = float(pc.get("res_area_bottom", 0.0) or 0.0)
                sup_top = float(pc.get("sup_area_top", 0.0) or 0.0)
                sup_bot = float(pc.get("sup_area_bottom", 0.0) or 0.0)
                mid = float(pc.get("mid", 0.0) or 0.0)

                # Only draw resistance zone if visible
                if res_top > 0 and res_bot > 0 and res_top > res_bot and _zone_visible(res_bot, res_top):
                    ax.axhspan(res_bot, res_top, facecolor=t_col, alpha=ALPHA_ZONE_POWER_CHANNEL, edgecolor="none", zorder=ZORDER_ZONES)
                    if _price_visible(res_top):
                        ax.axhline(res_top, color=t_col, linewidth=1.2, alpha=ALPHA_LINE_SECONDARY, zorder=ZORDER_ZONES)
                # Only draw support zone if visible
                if sup_top > 0 and sup_bot > 0 and sup_top > sup_bot and _zone_visible(sup_bot, sup_top):
                    ax.axhspan(sup_bot, sup_top, facecolor=b_col, alpha=ALPHA_ZONE_POWER_CHANNEL, edgecolor="none", zorder=ZORDER_ZONES)
                    if _price_visible(sup_bot):
                        ax.axhline(sup_bot, color=b_col, linewidth=1.2, alpha=0.7, zorder=ZORDER_ZONES)
                # Only draw mid line if visible
                if mid > 0 and _price_visible(mid):
                    ax.axhline(mid, color=TEXT_SECONDARY, linewidth=1.0, alpha=0.45, linestyle=":", zorder=ZORDER_ZONES)

            # Power readout (compact) - can be shown independently of power channel zones
            # Placed in top-left with semi-transparent background for visibility
            # Positioned at (0.01, 0.92) to avoid overlap with chart title
            if self.config.show_power_readout:
                buy = pc.get("buy_power")
                sell = pc.get("sell_power")
                if buy is not None or sell is not None:
                    txt = f"Power {int(buy or 0)}/{int(sell or 0)}"
                    # Place in upper-left of price panel with background box
                    ax.text(
                        0.01,
                        0.92,
                        txt,
                        transform=ax.transAxes,
                        ha="left",
                        va="top",
                        fontsize=FONT_SIZE_POWER_READOUT,
                        color=TEXT_PRIMARY,
                        alpha=0.95,
                        zorder=ZORDER_TEXT_LABELS,
                        bbox=dict(
                            facecolor=DARK_BG,
                            alpha=ALPHA_LEGEND_BG,
                            edgecolor=GRID_COLOR,
                            boxstyle="round,pad=0.3",
                        ),
                    )
        except Exception:
            return

    def _draw_tbt_overlay(self, ax, hud: Dict) -> None:
        """Draw TBT (ChartPrime) trendlines + optional breakout target."""
        if not self.config.show_tbt_targets:
            return
        tbt = hud.get("tbt") if isinstance(hud, dict) else None
        if not isinstance(tbt, dict):
            return

        try:
            # Trendlines (optional). Stored in bar-index x-space (0..N) so we can draw
            # directly on mplfinance axes without datetime conversion.
            lines = tbt.get("lines")
            try:
                zband = float(tbt.get("zband") or 0.0)
            except Exception:
                zband = 0.0
            if isinstance(lines, list) and lines:
                for ln in lines[:4]:  # hard cap to avoid clutter
                    if not isinstance(ln, dict):
                        continue
                    try:
                        x1 = float(ln.get("x1"))
                        y1 = float(ln.get("y1"))
                        x2 = float(ln.get("x2"))
                        y2 = float(ln.get("y2"))
                    except Exception:
                        continue
                    if not (np.isfinite(x1) and np.isfinite(x2) and np.isfinite(y1) and np.isfinite(y2)):
                        continue

                    kind = str(ln.get("kind") or "").strip().lower()
                    # Use configurable high-contrast colors so trendlines remain visible over dense candles.
                    if kind == "resistance":
                        col = self.config.tbt_resistance_color
                    elif kind == "support":
                        col = self.config.tbt_support_color
                    else:
                        col = TEXT_PRIMARY
                    ls = self.config.tbt_line_style if kind in ("resistance", "support") else ":"
                    lw = self.config.tbt_line_width
                    ax.plot(
                        [x1, x2],
                        [y1, y2],
                        color=col,
                        linewidth=lw,
                        alpha=0.80,
                        linestyle=ls,
                        zorder=(ZORDER_CANDLES + 0.05),
                    )
                    # Optional filled "channel" (ChartPrime style) to make trendlines readable
                    # without overpowering candles.
                    if np.isfinite(zband) and float(zband) > 0:
                        try:
                            zb = float(zband)
                            y1a, y2a = (y1 - zb), (y2 - zb)
                            y1b, y2b = (y1 - (zb * 2.0)), (y2 - (zb * 2.0))
                            # Neutral band + directional overlay
                            ax.fill_between(
                                [x1, x2],
                                [y1a, y2a],
                                [y1b, y2b],
                                color=GRID_COLOR,
                                alpha=0.10,
                                zorder=ZORDER_ZONES,
                            )
                            ax.fill_between(
                                [x1, x2],
                                [y1a, y2a],
                                [y1, y2],
                                color=col,
                                alpha=0.08,
                                zorder=ZORDER_ZONES,
                            )
                        except Exception:
                            pass

            # Optional: breakout target (TP)
            tp = tbt.get("tp")
            if tp is None:
                return
            tp = float(tp)
            if not np.isfinite(tp) or tp <= 0:
                return

            col = "#9a6714"  # target brown
            ax.axhline(tp, color=col, linewidth=1.6, alpha=0.85, linestyle="--", zorder=ZORDER_LEVEL_LINES)
            ax.text(
                0.55,
                tp,
                "Target",
                transform=ax.get_yaxis_transform(),
                ha="left",
                va="center",
                fontsize=FONT_SIZE_LABEL,
                color=TEXT_PRIMARY,
                bbox=dict(facecolor=mcolors.to_rgba(col, alpha=0.35), edgecolor="none", boxstyle="round,pad=0.25"),
                clip_on=False,
                zorder=ZORDER_TEXT_LABELS,
            )
        except Exception:
            return

    def _draw_dashboard_legend(
        self,
        ax,
        *,
        show_vwap: bool = True,
        show_ma: bool = True,
        ma_periods: Optional[List[int]] = None,
    ) -> None:
        """Draw a consistent legend for dashboard charts.
        
        Fixed order: VWAP, EMA(…) lines (or configured periods).
        Placed in upper-right corner with stable styling.
        Respects the show_legend config option.
        """
        # Check if legend is enabled via config
        if not self.config.show_legend:
            return
            
        try:
            from matplotlib.lines import Line2D
            
            legend_items: List[Tuple[Any, str]] = []
            
            # VWAP first (highest visual priority after candles)
            if show_vwap:
                legend_items.append((
                    Line2D([0], [0], color=VWAP_COLOR, linewidth=1.8, alpha=0.75),
                    "VWAP"
                ))
            
            # Moving averages in order (supports up to 4 EMAs with distinct colors)
            if show_ma:
                ma_periods_list = ma_periods or self.config.ma_periods
                for i, period in enumerate(ma_periods_list):
                    color = MA_COLORS[i % len(MA_COLORS)]
                    legend_items.append((
                        Line2D([0], [0], color=color, linewidth=1.2, alpha=0.7),
                        f"EMA{period}"
                    ))
            
            if not legend_items:
                return
            
            handles, labels = zip(*legend_items)
            # Place legend away from the Power readout (which lives upper-left at y≈0.92).
            # Upper-right with bbox_to_anchor for precise positioning below title.
            # Use ncol=2 for compact horizontal layout with 5 items (VWAP + 4 EMAs).
            # Position at 0.86 (14% from top) to avoid overlap with title text.
            legend_y = 0.86 if self.config.mobile_mode else 0.92
            ax.legend(
                handles,
                labels,
                loc="upper right",
                bbox_to_anchor=(0.99, legend_y),
                fontsize=FONT_SIZE_LEGEND,
                framealpha=ALPHA_LEGEND_BG,
                facecolor=DARK_BG,
                edgecolor=GRID_COLOR,
                labelcolor=TEXT_PRIMARY,
                ncol=2,  # 2 columns for compact layout
                handlelength=1.2,
                handletextpad=0.4,
                columnspacing=1.0,
            )
        except Exception:
            pass

    def _draw_trade_markers(self, ax, df: pd.DataFrame, trades: list[dict], *, max_trades: int = 6) -> None:
        """Draw cohesive 'smart' markers that combine entry/exit/outcome in a single visual element.
        
        Design:
        - Entry: Large triangle with pair letter (A, B, C)
        - Exit: Circle/Square with pair letter (A, B, C)
        - Outcome: Color-coded (Green=Win, Red=Loss, Gray=Open)
        - Path: Subtle dashed line connecting the pair
        """
        if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
            return
        if not trades:
            return

        try:
            max_n = int(max_trades)
        except Exception:
            max_n = 6
        max_n = max(1, min(20, max_n))

        idx_series = df.index
        idx_tz = getattr(idx_series, "tz", None)

        def _align_ts(raw):
            if not raw:
                return None
            try:
                tsx = pd.Timestamp(raw)
            except Exception:
                return None
            try:
                if idx_tz is None:
                    if tsx.tzinfo is not None:
                        tsx = tsx.tz_convert("UTC").tz_localize(None)
                    else:
                        tsx = tsx.tz_localize(None) if hasattr(tsx, "tz_localize") else tsx
                else:
                    if tsx.tzinfo is None:
                        tsx = tsx.tz_localize("UTC").tz_convert(idx_tz)
                    else:
                        tsx = tsx.tz_convert(idx_tz)
            except Exception:
                return None
            return tsx

        # 1. Collect valid trades with coordinates
        items: list[dict] = []
        for tr in [t for t in trades if isinstance(t, dict)]:
            direction = str(tr.get("direction") or "long").lower()
            et = _align_ts(tr.get("entry_time"))
            if et is None:
                continue
            try:
                xe = int(idx_series.get_indexer([et], method="nearest")[0])
            except Exception:
                continue
            if xe < 0 or xe >= len(idx_series):
                continue

            # Entry y
            try:
                ye = float(tr.get("entry_price") or 0.0)
            except Exception:
                ye = 0.0
            if ye <= 0:
                continue

            # Exit coordinates
            xt = _align_ts(tr.get("exit_time"))
            xx = None
            yx = None
            if xt is not None and tr.get("exit_price") is not None:
                try:
                    xx = int(idx_series.get_indexer([xt], method="nearest")[0])
                except Exception:
                    xx = None
                try:
                    yx = float(tr.get("exit_price") or 0.0)
                except Exception:
                    yx = None
                if xx is not None and (xx < 0 or xx >= len(idx_series)):
                    xx = None
                if yx is not None and yx <= 0:
                    yx = None

            # Outcome color
            pnl_val = tr.get("pnl", None)
            is_win: Optional[bool] = None
            if pnl_val is not None:
                try:
                    is_win = float(pnl_val) > 0
                except Exception:
                    is_win = None
            if is_win is None and isinstance(tr.get("is_win"), bool):
                is_win = bool(tr.get("is_win"))

            if is_win is True:
                col = SIGNAL_LONG
            elif is_win is False:
                col = SIGNAL_SHORT
            else:
                col = TEXT_SECONDARY

            items.append(
                {
                    "xe": xe,
                    "ye": ye,
                    "xx": xx,
                    "yx": yx,
                    "col": col,
                    "direction": direction,
                    "pnl": tr.get("pnl"),
                }
            )

        if not items:
            return

        # 2. Sort and limit
        items.sort(key=lambda d: int(d.get("xe", 0)))
        items = items[-max_n:]

        # 3. Draw markers
        def _to_letters(n: int) -> str:
            try:
                n = int(n)
            except Exception:
                return "?"
            if n <= 0:
                return "?"
            out = ""
            while n > 0:
                n, r = divmod(n - 1, 26)
                out = chr(65 + int(r)) + out
            return out

        marker_size = self.config.smart_marker_size
        try:
            show_letters = bool(getattr(self.config, "smart_marker_show_letters", True))
        except Exception:
            show_letters = True
        try:
            show_entry = bool(getattr(self.config, "smart_marker_show_entry", True))
        except Exception:
            show_entry = True
        try:
            show_exit = bool(getattr(self.config, "smart_marker_show_exit", True))
        except Exception:
            show_exit = True
        try:
            show_path = bool(getattr(self.config, "smart_marker_show_path", True))
        except Exception:
            show_path = True
        try:
            path_arrowheads = bool(getattr(self.config, "smart_marker_path_arrowheads", False))
        except Exception:
            path_arrowheads = False
        try:
            path_fade_by_age = bool(getattr(self.config, "smart_marker_path_fade_by_age", False))
        except Exception:
            path_fade_by_age = False
        try:
            path_label_last_pnl = bool(getattr(self.config, "smart_marker_path_label_last_pnl", False))
        except Exception:
            path_label_last_pnl = False

        for i, it in enumerate(items, start=1):
            label = _to_letters(i)
            col = it.get("col", TEXT_PRIMARY)
            direction = str(it.get("direction") or "long")
            xe, ye = it["xe"], it["ye"]
            xx, yx = it.get("xx"), it.get("yx")
            pnl = it.get("pnl")

            # Age-based emphasis: newest trades more visible.
            if path_fade_by_age and len(items) > 1:
                t = float(i - 1) / float(max(1, len(items) - 1))  # 0 oldest → 1 newest
                alpha_path = 0.18 + (0.55 - 0.18) * t
                lw_path = 0.9 + (1.7 - 0.9) * t
            else:
                alpha_path = 0.40
                lw_path = 1.2

            # Draw Ghost Path first (behind markers)
            if show_path and xx is not None and yx is not None:
                try:
                    if path_arrowheads:
                        # TradingView-inspired arrow line style (arrowhead at the exit).
                        from matplotlib.patches import FancyArrowPatch

                        patch = FancyArrowPatch(
                            (float(xe), float(ye)),
                            (float(xx), float(yx)),
                            arrowstyle="-|>",
                            mutation_scale=9.0,
                            linewidth=lw_path,
                            linestyle="--",
                            color=col,
                            alpha=alpha_path,
                            zorder=ZORDER_LEVEL_LINES,
                        )
                        ax.add_patch(patch)
                    else:
                        ax.plot(
                            [float(xe), float(xx)],
                            [float(ye), float(yx)],
                            color=col,
                            linestyle="--",
                            linewidth=lw_path,
                            alpha=alpha_path,
                            zorder=ZORDER_LEVEL_LINES,
                        )
                except Exception:
                    pass
                # If we're in "path-only" mode (no entry/exit markers), draw small endcaps:
                # - Entry: hollow circle
                # - Exit: filled circle (slightly larger)
                if (not show_entry) and (not show_exit):
                    try:
                        ax.scatter(
                            [xe],
                            [ye],
                            s=24,
                            facecolors="none",
                            edgecolors=col,
                            linewidths=1.2,
                            alpha=min(1.0, alpha_path + 0.10),
                            zorder=ZORDER_TEXT_LABELS,
                        )
                        ax.scatter(
                            [xx],
                            [yx],
                            s=34,
                            color=col,
                            edgecolors=DARK_BG,
                            linewidths=0.9,
                            alpha=min(1.0, alpha_path + 0.15),
                            zorder=ZORDER_TEXT_LABELS,
                        )
                    except Exception:
                        pass

                # Optional: label only the MOST RECENT trade's P&L at the exit.
                if path_label_last_pnl and i == len(items):
                    try:
                        if pnl is not None:
                            pnl_f = float(pnl)
                            sign = "+" if pnl_f >= 0 else ""
                            txt = f"{sign}${pnl_f:,.0f}"
                            ax.text(
                                float(xx) + 1.0,
                                float(yx),
                                txt,
                                ha="left",
                                va="center",
                                fontsize=8,
                                color=col,
                                alpha=0.92,
                                zorder=ZORDER_TEXT_LABELS,
                                bbox=dict(
                                    boxstyle="round,pad=0.15",
                                    facecolor=DARK_BG,
                                    edgecolor=col,
                                    alpha=ALPHA_LEGEND_BG,
                                ),
                            )
                    except Exception:
                        pass

            # Draw Entry Marker (Triangle with Letter)
            if show_entry:
                try:
                    # Up triangle for Long, Down for Short
                    marker_shape = "^" if direction == "long" else "v"
                    
                    # Draw the colored shape background
                    ax.scatter(
                        [xe], [ye],
                        marker=marker_shape,
                        s=marker_size,
                        color=col,
                        edgecolors=DARK_BG,
                        linewidths=1.5,
                        zorder=ZORDER_TEXT_LABELS,
                        alpha=0.95
                    )
                    
                    if show_letters:
                        # Draw the letter inside (white text)
                        ax.text(
                            xe, ye,
                            label,
                            ha="center",
                            va="center",
                            fontsize=8,
                            fontweight="bold",
                            color="white",  # Always white for contrast against colored marker
                            zorder=ZORDER_TEXT_LABELS + 1,
                        )
                except Exception:
                    pass

            # Draw Exit Marker (Circle with Letter)
            if show_exit and xx is not None and yx is not None:
                try:
                    # Circle for exit
                    ax.scatter(
                        [xx], [yx],
                        marker="o",
                        s=marker_size * 0.8, # Slightly smaller than entry
                        color=col,
                        edgecolors=DARK_BG,
                        linewidths=1.5,
                        zorder=ZORDER_TEXT_LABELS,
                        alpha=0.95
                    )
                    
                    if show_letters:
                        ax.text(
                            xx, yx,
                            label,
                            ha="center",
                            va="center",
                            fontsize=7,
                            fontweight="bold",
                            color="white",
                            zorder=ZORDER_TEXT_LABELS + 1,
                        )
                except Exception:
                    pass

    def _draw_trade_overlay_legend(
        self,
        ax,
        *,
        ema_crossovers_shown: bool,
    ) -> None:
        """Draw a compact legend explaining trade overlays on the dashboard chart."""
        try:
            lines = ["Trade overlay"]
            try:
                show_letters = bool(getattr(self.config, "smart_marker_show_letters", True))
            except Exception:
                show_letters = True
            try:
                show_entry = bool(getattr(self.config, "smart_marker_show_entry", True))
            except Exception:
                show_entry = True
            try:
                show_exit = bool(getattr(self.config, "smart_marker_show_exit", True))
            except Exception:
                show_exit = True
            try:
                show_path = bool(getattr(self.config, "smart_marker_show_path", True))
            except Exception:
                show_path = True

            if show_letters and show_entry and show_exit:
                lines.append("Marker: Letter pairs entry/exit")
            else:
                if show_entry and show_exit:
                    lines.append("Marker: Entry/Exit pairs (no letters)")
                elif show_entry and not show_exit:
                    lines.append("Marker: Entries only")
                elif show_exit and not show_entry:
                    lines.append("Marker: Exits only")
                else:
                    lines.append("Marker: Paths only")
            lines.append("Color: green win / red loss")
            if show_entry and show_exit:
                lines.append("Shape: ▲ Entry / ● Exit")
            elif show_entry and not show_exit:
                lines.append("Shape: ▲ Entry")
            elif show_exit and not show_entry:
                lines.append("Shape: ● Exit")
            elif show_path:
                lines.append("Endcaps: entry/exit dots")
            if show_path:
                lines.append("Path: dashed connector")
            else:
                lines.append("Path: hidden")
            # Path-only enhancements (kept compact; static Telegram-friendly)
            try:
                path_arrow = bool(getattr(self.config, "smart_marker_path_arrowheads", False))
            except Exception:
                path_arrow = False
            try:
                path_fade = bool(getattr(self.config, "smart_marker_path_fade_by_age", False))
            except Exception:
                path_fade = False
            try:
                path_last = bool(getattr(self.config, "smart_marker_path_label_last_pnl", False))
            except Exception:
                path_last = False
            if path_arrow and show_path:
                lines.append("Arrow: entry→exit")
            if path_fade and show_path:
                lines.append("Opacity: newer brighter")
            if path_last and show_path:
                lines.append("Label: last P&L")
            
            if ema_crossovers_shown:
                lines.append("EMA cross: cyan/pink")
            else:
                lines.append("EMA cross: hidden")

            try:
                legend_y = 0.84 if self.config.mobile_mode else 0.88
                if bool(getattr(self.config, "show_power_readout", True)):
                    legend_y -= 0.06
            except Exception:
                legend_y = 0.84

            ax.text(
                0.01,
                legend_y,
                "\n".join(lines),
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=FONT_SIZE_LEGEND,
                color=TEXT_PRIMARY,
                alpha=0.92,
                zorder=ZORDER_TEXT_LABELS,
                bbox=dict(
                    facecolor=DARK_BG,
                    alpha=ALPHA_LEGEND_BG,
                    edgecolor=GRID_COLOR,
                    boxstyle="round,pad=0.3",
                ),
            )
        except Exception:
            return

    def _draw_trade_recap_panel(
        self,
        ax,
        pnl_overlay: Optional[Dict[str, Any]],
        *,
        range_label: Optional[str] = None,
    ) -> None:
        """Draw a compact Trade Recap panel (equity + drawdown + summary stats)."""
        if ax is None:
            return

        try:
            ax.set_xticks([])
            ax.set_yticks([])
            try:
                for sp in ax.spines.values():
                    sp.set_visible(False)
            except Exception:
                pass
            ax.set_facecolor(mcolors.to_rgba(DARK_BG, alpha=0.0))

            title = str(range_label or "Trade Recap").strip()
            if not pnl_overlay or not isinstance(pnl_overlay, dict):
                ax.text(
                    0.02,
                    0.92,
                    title,
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=FONT_SIZE_LEGEND,
                    color=TEXT_PRIMARY,
                    alpha=0.9,
                )
                ax.text(
                    0.02,
                    0.65,
                    "No closed trades in window",
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=FONT_SIZE_SUMMARY,
                    color=TEXT_SECONDARY,
                    alpha=0.85,
                )
                return

            daily_pnl = float(pnl_overlay.get("daily_pnl") or 0.0)
            trades_count = int(pnl_overlay.get("trades") or 0)
            win_rate = float(pnl_overlay.get("win_rate") or 0.0)
            label = str(pnl_overlay.get("label") or title).strip()
            curve_raw = pnl_overlay.get("pnl_curve")

            if not isinstance(curve_raw, (list, tuple)) or len(curve_raw) < 2:
                ax.text(
                    0.02,
                    0.92,
                    label,
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=FONT_SIZE_LEGEND,
                    color=TEXT_PRIMARY,
                    alpha=0.9,
                )
                ax.text(
                    0.02,
                    0.65,
                    "No closed trades in window",
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=FONT_SIZE_SUMMARY,
                    color=TEXT_SECONDARY,
                    alpha=0.85,
                )
                return

            try:
                y_vals = [float(v) for v in curve_raw if v is not None]
            except Exception:
                y_vals = []
            if len(y_vals) < 2:
                return

            y = np.array(y_vals, dtype=float)
            x = np.arange(len(y), dtype=float)
            cummax = np.maximum.accumulate(y)
            dd = y - cummax
            max_dd = float(abs(np.min(dd))) if len(dd) else 0.0

            pnl_color = CANDLE_UP if daily_pnl >= 0 else CANDLE_DOWN
            pnl_sign = "+" if daily_pnl >= 0 else ""

            # Header text
            header = f"{label} • {trades_count} trades • {win_rate:.0f}% WR • MaxDD ${max_dd:,.0f}"
            ax.text(
                0.02,
                0.96,
                header,
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=FONT_SIZE_LEGEND,
                color=TEXT_PRIMARY,
                alpha=0.92,
            )
            ax.text(
                0.02,
                0.80,
                f"{pnl_sign}${daily_pnl:,.2f}",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=FONT_SIZE_SUMMARY,
                color=pnl_color,
                alpha=0.95,
            )

            # Equity subplot
            ax_eq = ax.inset_axes([0.02, 0.25, 0.96, 0.50])
            ax_eq.set_facecolor(mcolors.to_rgba(DARK_BG, alpha=0.0))
            ax_eq.axhline(0.0, color=GRID_COLOR, linewidth=0.8, linestyle="--", alpha=0.7)
            ax_eq.plot(x, y, color=TEXT_PRIMARY, linewidth=1.2, alpha=0.9)
            ax_eq.fill_between(x, 0.0, y, where=(y >= 0), color=CANDLE_UP, alpha=0.22)
            ax_eq.fill_between(x, 0.0, y, where=(y < 0), color=CANDLE_DOWN, alpha=0.22)
            ax_eq.scatter(
                [x[-1]],
                [y[-1]],
                s=18,
                color=pnl_color,
                edgecolors=DARK_BG,
                linewidths=0.8,
                zorder=ZORDER_TEXT_LABELS,
            )

            # Drawdown subplot
            ax_dd = ax.inset_axes([0.02, 0.08, 0.96, 0.12])
            ax_dd.set_facecolor(mcolors.to_rgba(DARK_BG, alpha=0.0))
            ax_dd.axhline(0.0, color=GRID_COLOR, linewidth=0.8, linestyle="--", alpha=0.7)
            ax_dd.fill_between(x, 0.0, dd, color=CANDLE_DOWN, alpha=0.30)

            # Tight framing
            try:
                ymin = float(np.min(y))
                ymax = float(np.max(y))
                yr = ymax - ymin
                pad = (yr * 0.12) if yr > 0 else max(1.0, abs(ymax) * 0.15, abs(ymin) * 0.15)
                ax_eq.set_xlim(float(x[0]), float(x[-1]))
                ax_eq.set_ylim(ymin - pad, ymax + pad)
                ddmin = float(np.min(dd)) if len(dd) else 0.0
                ax_dd.set_xlim(float(x[0]), float(x[-1]))
                ax_dd.set_ylim(ddmin * 1.15, 0.0 + max(1.0, abs(ddmin) * 0.05))
            except Exception:
                pass

            for ax_small in (ax_eq, ax_dd):
                ax_small.set_xticks([])
                ax_small.set_yticks([])
                try:
                    for sp in ax_small.spines.values():
                        sp.set_visible(False)
                except Exception:
                    pass
        except Exception:
            return

    def _draw_rr_box(self, ax, idx: pd.DatetimeIndex, signal: Dict, direction: str) -> Optional[float]:
        """Draw TradingView-like risk/reward box to the right of the last bar."""
        if not self.config.show_rr_box:
            return None

        try:
            entry = float(signal.get("entry_price") or 0.0)
            stop = float(signal.get("stop_loss") or 0.0)
            target = float(signal.get("take_profit") or 0.0)
            if entry <= 0 or stop <= 0 or target <= 0:
                return None
            if idx is None or len(idx) < 2:
                return None
        except Exception:
            return None

        # mplfinance uses integer x positions (0..N-1). Use that coordinate space for the RR box.
        x_start = float(len(idx) - 1)
        x_end = x_start + float(max(1, int(self.config.rr_box_forward_bars)))

        # Dollars (optional – if present in signal)
        try:
            tick_value = float(signal.get("tick_value") or 2.0)
            size = float(signal.get("position_size") or 1.0)
        except Exception:
            tick_value = 2.0
            size = 1.0

        if direction == "short":
            risk_pts = abs(stop - entry)
            reward_pts = abs(entry - target)
            risk_y0, risk_y1 = entry, stop
            reward_y0, reward_y1 = target, entry
        else:
            risk_pts = abs(entry - stop)
            reward_pts = abs(target - entry)
            risk_y0, risk_y1 = stop, entry
            reward_y0, reward_y1 = entry, target

        rr = (reward_pts / risk_pts) if risk_pts > 0 else 0.0
        risk_usd = risk_pts * tick_value * size
        reward_usd = reward_pts * tick_value * size

        # Boxes (use ZORDER_ZONES to stay behind candles but above session shading)
        ax.fill_between([x_start, x_end], risk_y0, risk_y1, color=SIGNAL_SHORT, alpha=0.22, zorder=ZORDER_ZONES)
        ax.fill_between([x_start, x_end], reward_y0, reward_y1, color=SIGNAL_LONG, alpha=0.20, zorder=ZORDER_ZONES)

        # Labels (use ZORDER_TEXT_LABELS for visibility)
        # Use configurable font size (default 9pt, optionally 10pt for mobile enhancement)
        rr_font_size = self.config.rr_box_font_size if self.config.mobile_enhanced_fonts else FONT_SIZE_RR_BOX
        x_mid = x_start + (x_end - x_start) / 2
        ax.text(
            x_mid,
            (reward_y0 + reward_y1) / 2,
            f"+{reward_usd:.0f} USD\nR:R {rr:.2f}",
            ha="center",
            va="center",
            fontsize=rr_font_size,
            color=TEXT_PRIMARY,
            bbox=dict(facecolor=mcolors.to_rgba(SIGNAL_LONG, alpha=0.22), edgecolor="none", boxstyle="round,pad=0.25"),
            zorder=ZORDER_TEXT_LABELS,
        )
        ax.text(
            x_mid,
            (risk_y0 + risk_y1) / 2,
            f"-{risk_usd:.0f} USD",
            ha="center",
            va="center",
            fontsize=rr_font_size,
            color=TEXT_PRIMARY,
            bbox=dict(facecolor=mcolors.to_rgba(SIGNAL_SHORT, alpha=0.22), edgecolor="none", boxstyle="round,pad=0.25"),
            zorder=ZORDER_TEXT_LABELS,
        )

        return float(x_end)

    def _apply_hud(self, fig, ax_price, df: pd.DataFrame, signal: Dict, direction: str, *, extra_levels: Optional[List[Dict[str, Any]]] = None) -> None:
        """Apply TradingView-style HUD overlays to an mplfinance-rendered figure."""
        if not self.config.show_hud:
            return

        hud = signal.get("hud_context") or {}
        if not isinstance(hud, dict):
            hud = {}

        # Right padding (for RR boxes + right labels)
        idx = df.index if isinstance(df.index, pd.DatetimeIndex) else None
        # IMPORTANT: mplfinance uses integer x-coordinates (0..N-1) for candles.
        # HUD overlays must stay in that coordinate space, or candles will be pushed off-screen.
        try:
            n = int(len(df) or 0)
        except Exception:
            n = 0
        if n > 0:
            right_pad = max(0, int(self.config.right_pad_bars))
            try:
                ax_price.set_xlim(-0.5, float((n - 1) + right_pad))
            except Exception:
                pass

        # Overlays
        self._draw_sessions_overlay(ax_price, hud, idx=idx)
        self._draw_supply_demand_overlay(ax_price, hud)
        self._draw_power_channel_overlay(ax_price, hud)
        self._draw_tbt_overlay(ax_price, hud)

        # RR box (extends xlim if needed)
        if idx is not None and len(idx) >= 2:
            rr_end = self._draw_rr_box(ax_price, idx, signal, direction)
            if rr_end is not None:
                try:
                    left, right = ax_price.get_xlim()
                    ax_price.set_xlim(left, max(float(right), float(rr_end)))
                except Exception:
                    pass

        # Levels + right labels
        if self.config.show_right_labels:
            tick_size = float(hud.get("tick_size") or 0.25)
            candidates, current_price = self._collect_level_candidates(df, signal, hud, extra_levels=extra_levels)
            
            # Apply compact label mode if enabled (P6 visual integrity plan)
            # Reduces clutter on range-bound days by merging more aggressively
            # and showing fewer labels
            merge_ticks = 6 if self.config.compact_labels else int(self.config.right_label_merge_ticks)
            max_labels = 6 if self.config.compact_labels else int(self.config.max_right_labels)
            
            merged = self._merge_levels(candidates, tick_size=tick_size, merge_ticks=merge_ticks)
            self._draw_right_labels(
                fig,
                ax_price,
                merged,
                current_price=current_price,
                max_labels=max_labels,
            )
    
    def generate_entry_chart(
        self,
        signal: Dict,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
        timeframe: Optional[str] = None,
        *,
        figsize: Optional[Tuple[float, float]] = None,
        dpi: Optional[int] = None,
    ) -> Optional[Path]:
        """Generate entry chart using mplfinance."""
        if not MPLFINANCE_AVAILABLE:
            return None
        
        try:
            if buffer_data.empty:
                logger.warning("Cannot generate chart: buffer data is empty")
                return None
            
            entry_price = signal.get("entry_price", 0)
            stop_loss = signal.get("stop_loss", 0)
            take_profit = signal.get("take_profit", 0)
            direction = signal.get("direction", "long").lower()
            
            if not entry_price or entry_price <= 0:
                logger.warning("Cannot generate chart: invalid entry price")
                return None
            
            # Prepare data
            chart_data = buffer_data.tail(100).copy()
            df = self._prepare_data(chart_data)
            
            # Create indicators
            addplot = self._add_indicators(df)
            
            # Add Entry/SL/TP lines
            entry_lines = self._add_entry_sl_tp_lines(df, entry_price, stop_loss, take_profit, direction)
            addplot.extend(entry_lines)

            # NOTE: Context levels are rendered via HUD (right labels + merged lines) instead of legend lines.
            
            # Create title (no emoji to avoid font rendering issues)
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            is_test = signal.get("reason", "").lower().startswith("test")
            title_prefix = "[TEST] " if is_test else ""
            tf_label = self._infer_timeframe_from_data(df)
            title = f"{title_prefix}{symbol} {direction.upper()} {signal_type} - Entry Chart ({tf_label})"
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Plot with mplfinance (return fig so we can draw HUD overlays)
            volume_on = True if 'Volume' in df.columns else False
            if self.config.show_rsi:
                # RSI is plotted in a separate panel below volume.
                # Uses Wilder's smoothing (EMA with alpha=1/period) for standard RSI
                close = df["Close"]
                delta = close.diff()
                alpha = 1.0 / self.config.rsi_period
                gain = delta.clip(lower=0).ewm(alpha=alpha, adjust=False).mean()
                loss = (-delta.clip(upper=0)).ewm(alpha=alpha, adjust=False).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi = 100 - (100 / (1 + rs))

                rsi_panel = 2 if volume_on else 1
                addplot.append(
                    mpf.make_addplot(rsi, panel=rsi_panel, color="#b388ff", width=1.2, ylabel="RSI", alpha=0.9)
                )
                for lvl, a in ((30, 0.25), (50, 0.18), (70, 0.25)):
                    addplot.append(
                        mpf.make_addplot(
                            pd.Series([lvl] * len(df), index=df.index),
                            panel=rsi_panel,
                            color=TEXT_SECONDARY,
                            width=1.0,
                            linestyle="--",
                            alpha=a,
                        )
                    )

                panel_ratios = (8, 1.8, 1.4) if volume_on else (8, 2)  # Optimized: ~71% price

            # Wider candles + thicker wicks for Telegram visibility
            # Build kwargs - only include panel_ratios if RSI is enabled (mplfinance rejects None)
            # Blank ylabel for mobile/Telegram to avoid collision with right labels
            ylabel_str = '' if self.config.mobile_mode else 'Price ($)'
            plot_kwargs = dict(
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=title,
                ylabel=ylabel_str,
                ylabel_lower='Volume',
                figsize=figsize or (14, 9),
                show_nontrading=False,
                tight_layout=True,
                returnfig=True,
                scale_width_adjustment=dict(candle=1.5, volume=0.8, lines=1.0),
                update_width_config=dict(candle_linewidth=1.4, candle_width=0.8),
            )
            if volume_on:
                plot_kwargs['volume_panel'] = 1
            if self.config.show_rsi:
                plot_kwargs['panel_ratios'] = panel_ratios

            fig, axlist = mpf.plot(df, **plot_kwargs)

            # Apply HUD overlays on the price axis.
            try:
                ax_price = axlist[0] if isinstance(axlist, list) and axlist else None
                if ax_price is not None:
                    # Limit y-axis ticks to prevent overlapping labels
                    self._limit_yaxis_ticks(ax_price, max_ticks=8)
                    # Add price numbers to x-axis (bottom of chart)
                    self._add_price_labels_to_xaxis(ax_price, df)
                    # Entry/Exit charts are intentionally calm-minimal:
                    # keep RR box + entry/stop/target labels, but suppress heavy context overlays
                    # (key levels, sessions, zones) to preserve baseline stability and readability.
                    _prev = {
                        "show_key_levels": self.config.show_key_levels,
                        "show_sessions": self.config.show_sessions,
                        "show_supply_demand": self.config.show_supply_demand,
                        "show_power_channel": self.config.show_power_channel,
                        "show_tbt_targets": self.config.show_tbt_targets,
                    }
                    try:
                        self.config.show_key_levels = False
                        self.config.show_sessions = False
                        self.config.show_supply_demand = False
                        self.config.show_power_channel = False
                        self.config.show_tbt_targets = False
                        self._apply_hud(fig, ax_price, df, signal, direction)

                        # ML Confidence Badge (Top-Right)
                        if self.config.show_ml_confidence:
                            try:
                                ml_conf = float(signal.get("confidence", 0.0))
                                if ml_conf > 0:
                                    ml_color = SIGNAL_LONG if ml_conf > 0.6 else (SIGNAL_SHORT if ml_conf < 0.4 else TEXT_SECONDARY)
                                    ax_price.text(
                                        0.98, 0.95,
                                        f"ML: {ml_conf:.0%}",
                                        transform=ax_price.transAxes,
                                        ha="right", va="top",
                                        fontsize=FONT_SIZE_LEGEND,
                                        color=ml_color,
                                        fontweight="bold",
                                        bbox=dict(
                                            boxstyle='round,pad=0.2',
                                            facecolor=DARK_BG,
                                            edgecolor=ml_color,
                                            alpha=ALPHA_LEGEND_BG,
                                        ),
                                        zorder=ZORDER_TEXT_LABELS
                                    )
                            except Exception as e:
                                logger.debug(f"Error adding ML confidence badge: {e}")

                    finally:
                        for k, v in _prev.items():
                            try:
                                setattr(self.config, k, v)
                            except Exception:
                                pass
            except Exception:
                pass

            # Save + cleanup
            fig.savefig(
                str(temp_path),
                dpi=int(dpi or self.dpi),
                facecolor=DARK_BG,
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.20,
            )
            plt.close(fig)
            
            logger.debug(f"Generated entry chart with mplfinance: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating entry chart with mplfinance: {e}", exc_info=True)
            return None
    
    def generate_exit_chart(
        self,
        signal: Dict,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
        timeframe: Optional[str] = None,
        *,
        figsize: Optional[Tuple[float, float]] = None,
        dpi: Optional[int] = None,
    ) -> Optional[Path]:
        """Generate exit chart using mplfinance."""
        if not MPLFINANCE_AVAILABLE:
            return None
        
        try:
            if buffer_data.empty:
                logger.warning("Cannot generate chart: buffer data is empty")
                return None
            
            entry_price = signal.get("entry_price", 0)
            stop_loss = signal.get("stop_loss", 0)
            take_profit = signal.get("take_profit", 0)
            direction = signal.get("direction", "long").lower()
            
            if not entry_price or entry_price <= 0:
                logger.warning("Cannot generate chart: invalid entry price")
                return None
            
            # Prepare data
            chart_data = buffer_data.tail(150).copy()
            df = self._prepare_data(chart_data)
            
            # Create indicators
            addplot = self._add_indicators(df)
            
            # Add Entry/SL/TP lines
            entry_lines = self._add_entry_sl_tp_lines(df, entry_price, stop_loss, take_profit, direction)
            addplot.extend(entry_lines)

            # NOTE: Context levels are rendered via HUD (right labels + merged lines) instead of legend lines.
            
            # Add exit line
            exit_series = pd.Series([exit_price] * len(df), index=df.index)
            addplot.append(mpf.make_addplot(
                exit_series,
                color=MA_COLORS[0],
                width=2.5,
                linestyle='-',
                alpha=0.9,
                label=f'Exit: ${exit_price:.2f} ({exit_reason})'
            ))
            
            # Create title
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            result = "WIN" if pnl > 0 else "LOSS"
            tf_label = self._infer_timeframe_from_data(df)
            title = f"{symbol} {direction.upper()} {signal_type} - Exit ({result}) ({tf_label})"
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            volume_on = True if 'Volume' in df.columns else False
            if self.config.show_rsi:
                # Uses Wilder's smoothing (EMA with alpha=1/period) for standard RSI
                close = df["Close"]
                delta = close.diff()
                alpha = 1.0 / self.config.rsi_period
                gain = delta.clip(lower=0).ewm(alpha=alpha, adjust=False).mean()
                loss = (-delta.clip(upper=0)).ewm(alpha=alpha, adjust=False).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi = 100 - (100 / (1 + rs))

                rsi_panel = 2 if volume_on else 1
                addplot.append(
                    mpf.make_addplot(rsi, panel=rsi_panel, color="#b388ff", width=1.2, ylabel="RSI", alpha=0.9)
                )
                for lvl, a in ((30, 0.25), (50, 0.18), (70, 0.25)):
                    addplot.append(
                        mpf.make_addplot(
                            pd.Series([lvl] * len(df), index=df.index),
                            panel=rsi_panel,
                            color=TEXT_SECONDARY,
                            width=1.0,
                            linestyle="--",
                            alpha=a,
                        )
                    )
                panel_ratios = (8, 1.8, 1.4) if volume_on else (8, 2)  # Optimized: ~71% price

            # Wider candles + thicker wicks for Telegram visibility
            # Build kwargs - only include panel_ratios if RSI is enabled (mplfinance rejects None)
            # Blank ylabel for mobile/Telegram to avoid collision with right labels
            ylabel_str = '' if self.config.mobile_mode else 'Price ($)'
            plot_kwargs = dict(
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=title,
                ylabel=ylabel_str,
                ylabel_lower='Volume',
                figsize=figsize or (14, 9),
                show_nontrading=False,
                tight_layout=True,
                returnfig=True,
                scale_width_adjustment=dict(candle=1.5, volume=0.8, lines=1.0),
                update_width_config=dict(candle_linewidth=1.4, candle_width=0.8),
            )
            if volume_on:
                plot_kwargs['volume_panel'] = 1
            if self.config.show_rsi:
                plot_kwargs['panel_ratios'] = panel_ratios

            fig, axlist = mpf.plot(df, **plot_kwargs)

            # Apply HUD overlays, including an Exit right-label.
            try:
                ax_price = axlist[0] if isinstance(axlist, list) and axlist else None
                if ax_price is not None:
                    # Limit y-axis ticks to prevent overlapping labels
                    self._limit_yaxis_ticks(ax_price, max_ticks=8)
                    # Add price numbers to x-axis (bottom of chart)
                    self._add_price_labels_to_xaxis(ax_price, df)
                    _prev = {
                        "show_key_levels": self.config.show_key_levels,
                        "show_sessions": self.config.show_sessions,
                        "show_supply_demand": self.config.show_supply_demand,
                        "show_power_channel": self.config.show_power_channel,
                        "show_tbt_targets": self.config.show_tbt_targets,
                    }
                    try:
                        self.config.show_key_levels = False
                        self.config.show_sessions = False
                        self.config.show_supply_demand = False
                        self.config.show_power_channel = False
                        self.config.show_tbt_targets = False
                        self._apply_hud(
                            fig,
                            ax_price,
                            df,
                            signal,
                            direction,
                            extra_levels=[
                                {
                                    "price": float(exit_price),
                                    "label": f"Exit ({exit_reason})",
                                    "color": MA_COLORS[0],
                                    "priority": 90,
                                    "linestyle": "-",
                                    "lw": 1.6,
                                    "alpha": 0.9,
                                }
                            ],
                        )
                    finally:
                        for k, v in _prev.items():
                            try:
                                setattr(self.config, k, v)
                            except Exception:
                                pass
            except Exception:
                pass

            fig.savefig(
                str(temp_path),
                dpi=int(dpi or self.dpi),
                facecolor=DARK_BG,
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.20,
            )
            plt.close(fig)
            
            logger.debug(f"Generated exit chart with mplfinance: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating exit chart with mplfinance: {e}", exc_info=True)
            return None
    
    def generate_trade_chart(
        self,
        trade: Dict,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
        timeframe: Optional[str] = None,
        *,
        lookback_bars: int = 30,
        forward_bars: int = 15,
        show_hold_shading: bool = True,
        show_hud: bool = True,
        figsize: Optional[Tuple[float, float]] = None,
        dpi: Optional[int] = None,
    ) -> Optional[Path]:
        """Generate a focused chart centered on a single trade's entry-to-exit window.

        This method is designed for backtest report "trade gallery" views, showing
        each trade in isolation with clear entry/exit markers and optional hold-period
        shading.

        Args:
            trade: Trade dict with keys:
                - entry_time: ISO timestamp or datetime
                - exit_time: ISO timestamp or datetime
                - entry_price: float
                - exit_price: float
                - direction: "long" or "short"
                - stop_loss: float (optional)
                - take_profit: float (optional)
                - pnl: float (optional, for title)
                - exit_reason: str (optional, for title)
            buffer_data: Full OHLCV DataFrame (will be sliced to trade window)
            symbol: Symbol name for title
            timeframe: Timeframe label for title
            lookback_bars: Bars to show before entry
            forward_bars: Bars to show after exit
            show_hold_shading: If True, shade the entry-to-exit hold period
            show_hud: If True, apply HUD overlays (sessions, levels)
            figsize: Optional override for figure size
            dpi: Optional override for DPI

        Returns:
            Path to generated PNG, or None on failure
        """
        if not MPLFINANCE_AVAILABLE:
            return None

        try:
            if buffer_data is None or buffer_data.empty:
                logger.warning("Cannot generate trade chart: buffer data is empty")
                return None

            # Parse trade data
            entry_time = self._safe_parse_dt(trade.get("entry_time"))
            exit_time = self._safe_parse_dt(trade.get("exit_time"))
            entry_price = float(trade.get("entry_price") or 0)
            exit_price = float(trade.get("exit_price") or 0)
            direction = (trade.get("direction") or "long").lower()
            stop_loss = float(trade.get("stop_loss") or 0)
            take_profit = float(trade.get("take_profit") or 0)
            pnl = trade.get("pnl")
            exit_reason = trade.get("exit_reason") or "exit"

            if entry_price <= 0:
                logger.warning("Cannot generate trade chart: invalid entry price")
                return None

            # Slice data around trade window
            df_full = buffer_data.copy()
            if not isinstance(df_full.index, pd.DatetimeIndex):
                # Try to set timestamp as index
                if "timestamp" in df_full.columns:
                    df_full["timestamp"] = pd.to_datetime(df_full["timestamp"])
                    df_full = df_full.set_index("timestamp")
                else:
                    logger.warning("Cannot generate trade chart: no timestamp index")
                    return None

            # Find entry/exit bar indices
            entry_idx = None
            exit_idx = None
            if entry_time is not None:
                try:
                    # Align timezone
                    if getattr(df_full.index, "tz", None) is not None:
                        if entry_time.tzinfo is None:
                            entry_time = entry_time.tz_localize(df_full.index.tz)
                        else:
                            entry_time = entry_time.tz_convert(df_full.index.tz)
                    entry_idx = df_full.index.get_indexer([entry_time], method="nearest")[0]
                except Exception:
                    pass

            if exit_time is not None:
                try:
                    if getattr(df_full.index, "tz", None) is not None:
                        if exit_time.tzinfo is None:
                            exit_time = exit_time.tz_localize(df_full.index.tz)
                        else:
                            exit_time = exit_time.tz_convert(df_full.index.tz)
                    exit_idx = df_full.index.get_indexer([exit_time], method="nearest")[0]
                except Exception:
                    pass

            # Default to last bars if indices not found
            if entry_idx is None:
                entry_idx = max(0, len(df_full) - lookback_bars - forward_bars)
            if exit_idx is None:
                exit_idx = min(len(df_full) - 1, entry_idx + lookback_bars)

            # Compute slice bounds
            start_idx = max(0, entry_idx - lookback_bars)
            end_idx = min(len(df_full), exit_idx + forward_bars + 1)

            chart_data = df_full.iloc[start_idx:end_idx].copy()
            if chart_data.empty:
                logger.warning("Cannot generate trade chart: sliced data is empty")
                return None

            df = self._prepare_data(chart_data)

            # Recompute entry/exit positions in sliced data
            entry_x = entry_idx - start_idx
            exit_x = exit_idx - start_idx

            # Create indicators
            addplot = self._add_indicators(df)

            # Add Entry/SL/TP lines
            if entry_price > 0:
                entry_lines = self._add_entry_sl_tp_lines(df, entry_price, stop_loss, take_profit, direction)
                addplot.extend(entry_lines)

            # Add exit line
            if exit_price > 0:
                exit_series = pd.Series([exit_price] * len(df), index=df.index)
                addplot.append(mpf.make_addplot(
                    exit_series,
                    color=MA_COLORS[0],
                    width=2.5,
                    linestyle='-',
                    alpha=0.9,
                    label=f'Exit: ${exit_price:.2f}'
                ))

            # RSI panel - Uses Wilder's smoothing (EMA with alpha=1/period) for standard RSI
            volume_on = "Volume" in df.columns
            panel_ratios = None
            if self.config.show_rsi:
                close = df["Close"]
                delta = close.diff()
                alpha = 1.0 / self.config.rsi_period
                gain = delta.clip(lower=0).ewm(alpha=alpha, adjust=False).mean()
                loss = (-delta.clip(upper=0)).ewm(alpha=alpha, adjust=False).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi = 100 - (100 / (1 + rs))

                rsi_panel = 2 if volume_on else 1
                addplot.append(
                    mpf.make_addplot(rsi, panel=rsi_panel, color="#b388ff", width=1.2, ylabel="RSI", alpha=0.9)
                )
                for lvl, a in ((30, 0.25), (50, 0.18), (70, 0.25)):
                    addplot.append(
                        mpf.make_addplot(
                            pd.Series([lvl] * len(df), index=df.index),
                            panel=rsi_panel,
                            color=TEXT_SECONDARY,
                            width=1.0,
                            linestyle="--",
                            alpha=a,
                        )
                    )
                panel_ratios = (6, 2, 2) if volume_on else (7, 3)

            # Title
            signal_type = trade.get("signal_type", trade.get("type", "trade")).replace("_", " ").title()
            result_str = ""
            if pnl is not None:
                result_str = f" - {'WIN' if float(pnl) > 0 else 'LOSS'} (${float(pnl):,.2f})"
            tf_label = timeframe or self.config.timeframe
            title = f"{symbol} {direction.upper()} {signal_type}{result_str} ({tf_label})"

            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()

            # Plot kwargs
            # Blank ylabel for mobile/Telegram to avoid collision with right labels
            ylabel_str = '' if self.config.mobile_mode else 'Price ($)'
            plot_kwargs = dict(
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=title,
                ylabel=ylabel_str,
                ylabel_lower='Volume',
                figsize=figsize or (14, 9),
                show_nontrading=False,
                tight_layout=True,
                returnfig=True,
                scale_width_adjustment=dict(candle=1.5, volume=0.8, lines=1.0),
                update_width_config=dict(candle_linewidth=1.4, candle_width=0.8),
            )
            if volume_on:
                plot_kwargs['volume_panel'] = 1
            if panel_ratios is not None:
                plot_kwargs['panel_ratios'] = panel_ratios

            fig, axlist = mpf.plot(df, **plot_kwargs)

            # Get price axis
            ax_price = axlist[0] if isinstance(axlist, list) and axlist else None

            if ax_price is not None:
                # Limit y-axis ticks to prevent overlapping labels
                self._limit_yaxis_ticks(ax_price, max_ticks=8)
                # Add price numbers to x-axis (bottom of chart)
                self._add_price_labels_to_xaxis(ax_price, df)
                # Hold-period shading (entry_x to exit_x)
                if show_hold_shading and 0 <= entry_x < len(df) and 0 <= exit_x < len(df):
                    shade_color = SIGNAL_LONG if pnl is not None and float(pnl) > 0 else SIGNAL_SHORT
                    ax_price.axvspan(
                        float(entry_x), float(exit_x),
                        color=shade_color,
                        alpha=0.12,
                        zorder=ZORDER_SESSION_SHADING,
                    )

                # Entry/Exit markers
                try:
                    ymin, ymax = ax_price.get_ylim()
                    marker_offset = (ymax - ymin) * 0.015

                    # Smart Trade Markers (P8) - cohesive entry/exit/outcome visualization
                    # Build a synthetic trade list for _draw_trade_markers
                    trade_rec = {
                        "entry_time": trade.get("entry_time"),
                        "exit_time": trade.get("exit_time"),
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "direction": direction,
                        "pnl": pnl,
                        "is_win": float(pnl) > 0 if pnl is not None else None
                    }
                    self._draw_trade_markers(ax_price, df, [trade_rec], max_trades=1)
                except Exception:
                    pass

                # HUD overlays
                if show_hud:
                    # Build signal dict for HUD compatibility
                    signal_dict = {
                        "entry_price": entry_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "direction": direction,
                    }
                    self._apply_hud(
                        fig,
                        ax_price,
                        df,
                        signal_dict,
                        direction,
                        extra_levels=[
                            {
                                "price": float(exit_price),
                                "label": f"Exit ({exit_reason})",
                                "color": MA_COLORS[0],
                                "priority": 90,
                                "linestyle": "-",
                                "lw": 1.6,
                                "alpha": 0.9,
                            }
                        ] if exit_price > 0 else None,
                    )

            # Save
            fig.savefig(
                str(temp_path),
                dpi=dpi or self.dpi,
                facecolor=DARK_BG,
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.20,
            )
            plt.close(fig)

            logger.debug(f"Generated trade chart: {temp_path}")
            return temp_path

        except Exception as e:
            logger.error(f"Error generating trade chart: {e}", exc_info=True)
            return None

    def generate_equity_curve_chart(
        self,
        trades: List[Dict],
        symbol: str = "MNQ",
        title: str = "Backtest Equity Curve",
        performance_data: Optional[Dict] = None,
        *,
        figsize: Tuple[float, float] = (16, 9),
        dpi: int = 200,
    ) -> Optional[Path]:
        """Generate equity curve chart from trades.
        
        For long backtests, equity curve is more informative than candlesticks.
        Shows cumulative P&L over time with drawdown shading.
        
        Args:
            trades: List of trade dicts with entry_time, exit_time, pnl
            symbol: Symbol name for title
            title: Chart title
            performance_data: Optional performance metrics for annotations
            figsize: Figure size
            dpi: Resolution
            
        Returns:
            Path to generated PNG, or None on failure
        """
        if not trades:
            logger.warning("Cannot generate equity curve: no trades")
            return None
        
        try:
            # Build equity curve from trades
            trade_times = []
            trade_pnls = []
            
            for trade in trades:
                exit_time = trade.get("exit_time")
                pnl = trade.get("pnl", 0)
                
                if exit_time:
                    try:
                        dt = pd.to_datetime(exit_time)
                        trade_times.append(dt)
                        trade_pnls.append(float(pnl))
                    except Exception:
                        continue
            
            if not trade_times:
                logger.warning("Cannot generate equity curve: no valid trade times")
                return None
            
            # Create DataFrame
            equity_df = pd.DataFrame({
                'time': trade_times,
                'pnl': trade_pnls,
            }).sort_values('time')
            
            equity_df['cumulative_pnl'] = equity_df['pnl'].cumsum()
            equity_df['cumulative_max'] = equity_df['cumulative_pnl'].cummax()
            equity_df['drawdown'] = equity_df['cumulative_pnl'] - equity_df['cumulative_max']
            
            # Create figure
            fig, (ax_equity, ax_dd) = plt.subplots(
                2, 1, figsize=figsize,
                gridspec_kw={'height_ratios': [3, 1]},
                facecolor=DARK_BG,
            )
            
            # Equity curve
            ax_equity.plot(
                equity_df['time'],
                equity_df['cumulative_pnl'],
                color=SIGNAL_LONG,
                linewidth=2.5,
                alpha=0.9,
            )
            ax_equity.fill_between(
                equity_df['time'],
                0,
                equity_df['cumulative_pnl'],
                where=equity_df['cumulative_pnl'] >= 0,
                color=SIGNAL_LONG,
                alpha=0.2,
            )
            ax_equity.fill_between(
                equity_df['time'],
                0,
                equity_df['cumulative_pnl'],
                where=equity_df['cumulative_pnl'] < 0,
                color=SIGNAL_SHORT,
                alpha=0.2,
            )
            ax_equity.axhline(0, color=TEXT_SECONDARY, linestyle='--', linewidth=1, alpha=0.5)
            ax_equity.set_ylabel('Cumulative P&L ($)', color=TEXT_PRIMARY)
            ax_equity.set_title(title, color=TEXT_PRIMARY, fontsize=FONT_SIZE_TITLE, pad=15)
            ax_equity.grid(True, alpha=0.2, color=GRID_COLOR)
            ax_equity.tick_params(colors=TEXT_PRIMARY)
            
            # Drawdown chart
            ax_dd.fill_between(
                equity_df['time'],
                0,
                equity_df['drawdown'],
                color=SIGNAL_SHORT,
                alpha=0.4,
            )
            ax_dd.set_ylabel('Drawdown ($)', color=TEXT_PRIMARY)
            ax_dd.set_xlabel('Date', color=TEXT_PRIMARY)
            ax_dd.grid(True, alpha=0.2, color=GRID_COLOR)
            ax_dd.tick_params(colors=TEXT_PRIMARY)
            
            # Add performance annotations if available
            if performance_data:
                stats_text = (
                    f"Trades: {performance_data.get('total_trades', 0)}\n"
                    f"Win Rate: {performance_data.get('win_rate', 0):.1%}\n"
                    f"Total P&L: ${performance_data.get('total_pnl', 0):,.0f}\n"
                    f"Max DD: ${abs(performance_data.get('max_drawdown', 0)):,.0f}\n"
                    f"Sharpe: {performance_data.get('sharpe_ratio', 0):.2f}"
                )
                ax_equity.text(
                    0.02, 0.98,
                    stats_text,
                    transform=ax_equity.transAxes,
                    fontsize=FONT_SIZE_SUMMARY,
                    verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor=DARK_BG, alpha=0.8, edgecolor=GRID_COLOR),
                    color=TEXT_PRIMARY,
                )
            
            # Style
            for ax in [ax_equity, ax_dd]:
                ax.set_facecolor(DARK_BG)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_color(GRID_COLOR)
                ax.spines['bottom'].set_color(GRID_COLOR)
            
            plt.tight_layout()
            
            # Save
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            fig.savefig(
                str(temp_path),
                dpi=dpi,
                facecolor=DARK_BG,
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.20,
            )
            plt.close(fig)
            
            logger.debug(f"Generated equity curve chart: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating equity curve chart: {e}", exc_info=True)
            return None

    def generate_backtest_chart(
        self,
        backtest_data: pd.DataFrame,
        signals: List[Dict],
        symbol: str = "MNQ",
        title: str = "Backtest Results",
        performance_data: Optional[Dict] = None,
        timeframe: Optional[str] = None,
        *,
        figsize: Optional[Tuple[float, float]] = None,
        dpi: Optional[int] = None,
        use_line_chart: bool = False,
    ) -> Optional[Path]:
        """Generate backtest chart using mplfinance.

        Args:
            backtest_data: OHLCV DataFrame for the backtest period
            signals: List of signal dicts with timestamp, direction, etc.
            symbol: Symbol name for title
            title: Chart title prefix
            performance_data: Optional performance metrics for title
            timeframe: Timeframe label for title
            figsize: Optional override for figure size (default: (14, 9))
            dpi: Optional override for DPI (default: self.dpi)

        Returns:
            Path to generated PNG, or None on failure
        """
        if not MPLFINANCE_AVAILABLE:
            return None
        
        try:
            if backtest_data.empty:
                logger.warning("Cannot generate backtest chart: data is empty")
                return None
            
            # Prepare data
            df = self._prepare_data(backtest_data.copy())
            
            # Create indicators
            addplot = self._add_indicators(df)

            # Add signal markers (scatter)
            try:
                if signals:
                    max_n = self.config.max_signals_displayed
                    sigs = signals[-max_n:] if max_n and len(signals) > max_n else signals

                    # Dynamic marker size (prevent "marker soup" when many signals exist)
                    # We intentionally cap the effective marker size for readability on Telegram/mobile.
                    n_sigs = max(1, int(len(sigs)))
                    base = float(getattr(self.config, "signal_marker_size", 140) or 140)
                    base = min(base, 140.0)
                    scale = math.sqrt(50.0 / float(n_sigs))
                    marker_size = int(max(40.0, min(base, base * scale)))

                    # Marker series:
                    # - If a signal includes 'pnl', we color by outcome: green=win, red=loss
                    #   and keep marker SHAPE = direction (^ long, v short).
                    # - Otherwise, we fall back to direction-colored markers.
                    long_y = pd.Series(np.nan, index=df.index)   # unknown outcome
                    short_y = pd.Series(np.nan, index=df.index)  # unknown outcome
                    win_long_y = pd.Series(np.nan, index=df.index)
                    loss_long_y = pd.Series(np.nan, index=df.index)
                    win_short_y = pd.Series(np.nan, index=df.index)
                    loss_short_y = pd.Series(np.nan, index=df.index)

                    for s in sigs:
                        ts = s.get("timestamp")
                        if not ts:
                            continue
                        try:
                            dt = pd.to_datetime(ts)
                        except Exception:
                            continue

                        # Align timezone to chart index if needed
                        try:
                            if getattr(df.index, "tz", None) is not None:
                                if getattr(dt, "tzinfo", None) is None:
                                    dt = dt.tz_localize(timezone.utc)
                                dt = dt.tz_convert(df.index.tz)
                        except Exception:
                            pass

                        try:
                            pos = df.index.get_indexer([dt], method="nearest")[0]
                        except Exception:
                            continue
                        if pos < 0 or pos >= len(df.index):
                            continue

                        direction = (s.get("direction") or "long").lower()
                        # Optional: outcome (trade dicts will include pnl; raw signals won't)
                        pnl_val = s.get("pnl", None)
                        is_win: Optional[bool] = None
                        if pnl_val is not None:
                            try:
                                is_win = float(pnl_val) > 0
                            except Exception:
                                is_win = None
                        if direction == "long":
                            # Plot just below candle low
                            low_val = float(df["Low"].iloc[pos])
                            y = low_val * 0.999
                            if is_win is True:
                                win_long_y.iloc[pos] = y
                            elif is_win is False:
                                loss_long_y.iloc[pos] = y
                            else:
                                long_y.iloc[pos] = y
                        else:
                            high_val = float(df["High"].iloc[pos])
                            y = high_val * 1.001
                            if is_win is True:
                                win_short_y.iloc[pos] = y
                            elif is_win is False:
                                loss_short_y.iloc[pos] = y
                            else:
                                short_y.iloc[pos] = y

                    # Outcome-colored markers (preferred when pnl is available)
                    if not win_long_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                win_long_y,
                                type="scatter",
                                marker="^",
                                markersize=marker_size,
                                color=SIGNAL_LONG,  # win
                                alpha=0.85,
                            )
                        )
                    if not loss_long_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                loss_long_y,
                                type="scatter",
                                marker="^",
                                markersize=marker_size,
                                color=SIGNAL_SHORT,  # loss
                                alpha=0.85,
                            )
                        )
                    if not win_short_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                win_short_y,
                                type="scatter",
                                marker="v",
                                markersize=marker_size,
                                color=SIGNAL_LONG,  # win
                                alpha=0.85,
                            )
                        )
                    if not loss_short_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                loss_short_y,
                                type="scatter",
                                marker="v",
                                markersize=marker_size,
                                color=SIGNAL_SHORT,  # loss
                                alpha=0.85,
                            )
                        )

                    # Fallback direction-colored markers (when pnl not available)
                    if not long_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                long_y,
                                type="scatter",
                                marker="^",
                                markersize=max(35, int(marker_size * 0.9)),
                                color=SIGNAL_LONG,
                                alpha=0.65,
                            )
                        )
                    if not short_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                short_y,
                                type="scatter",
                                marker="v",
                                markersize=max(35, int(marker_size * 0.9)),
                                color=SIGNAL_SHORT,
                                alpha=0.65,
                            )
                        )
            except Exception as e:
                logger.debug(f"Error adding signal markers: {e}")
            
            # Create title
            tf_label = timeframe or self.config.timeframe
            # Keep titles short for mobile readability (avoid redundant suffixes)
            chart_title = f"{title} ({tf_label})" if tf_label and tf_label not in str(title) else str(title)
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Use provided figsize/dpi or defaults
            effective_figsize = figsize or (14, 9)
            effective_dpi = dpi or self.dpi

            # Use line chart for long backtests (clearer than thousands of candles)
            chart_type = 'line' if use_line_chart else 'candle'
            
            # Blank ylabel for mobile/Telegram to avoid collision with right labels
            ylabel_str = '' if self.config.mobile_mode else 'Price ($)'
            plot_kwargs = {
                'type': chart_type,
                'style': self.style,
                'addplot': addplot if addplot else None,
                'volume': True if 'Volume' in df.columns else False,
                'title': chart_title,
                'ylabel': ylabel_str,
                'ylabel_lower': 'Volume',
                'figsize': effective_figsize,
                'savefig': dict(
                    fname=str(temp_path),
                    dpi=effective_dpi,
                    facecolor=DARK_BG,
                    edgecolor='none',
                    bbox_inches='tight'
                ),
                'show_nontrading': False,
                'tight_layout': True,
                'returnfig': False,
                'warn_too_much_data': 10000,
            }
            
            if chart_type == 'candle':
                plot_kwargs.update({
                    'scale_width_adjustment': dict(candle=1.4, volume=0.8, lines=1.0),
                    'update_width_config': dict(candle_linewidth=1.2, candle_width=0.7),
                })
            
            # Plot with mplfinance - need to get axes to limit ticks
            plot_kwargs['returnfig'] = True
            plot_kwargs.pop('savefig', None)  # Remove savefig to handle manually
            fig, axlist = mpf.plot(df, **plot_kwargs)
            
            # Limit y-axis ticks to prevent overlapping labels
            try:
                ax_price = axlist[0] if isinstance(axlist, list) and axlist else None
                if ax_price is not None:
                    self._limit_yaxis_ticks(ax_price, max_ticks=8)
                    # Add price numbers to x-axis (bottom of chart)
                    self._add_price_labels_to_xaxis(ax_price, backtest_data)
            except Exception:
                pass
            
            # Save the figure
            fig.savefig(
                str(temp_path),
                dpi=effective_dpi,
                facecolor=DARK_BG,
                edgecolor='none',
                bbox_inches='tight',
                pad_inches=0.20,
            )
            plt.close(fig)
            
            logger.debug(f"Generated backtest chart with mplfinance: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating backtest chart with mplfinance: {e}", exc_info=True)
            return None

    def generate_dashboard_chart(
        self,
        data: pd.DataFrame,
        symbol: str = "MNQ",
        timeframe: str = "5m",
        *,
        lookback_bars: int = 288,
        range_label: Optional[str] = None,
        # Mobile-first default: portrait aspect for phone readability in Telegram.
        figsize: Tuple[float, float] = (8, 12),
        dpi: int = 200,
        render_mode: str = "telegram",
        show_sessions: bool = True,
        show_key_levels: bool = True,
        show_vwap: bool = True,
        show_ma: bool = True,
        ma_periods: Optional[List[int]] = None,
        show_rsi: bool = True,
        show_pressure: bool = True,
        show_trade_recap: bool = False,
        title_time: Optional[str] = None,
        right_pad_bars: Optional[int] = None,
        trades: Optional[List[Dict[str, Any]]] = None,
        regime_info: Optional[Dict[str, Any]] = None,
        manifest_path: Optional[Path] = None,
        # UX overlay options (mobile-first)
        pnl_overlay: Optional[Dict[str, Any]] = None,  # {"daily_pnl": float, "trades": int, "win_rate": float}
        session_label: Optional[str] = None,  # e.g., "NY Session"
        # Telegram/dashboard render tuning (service-controlled; defaults preserve baselines)
        show_ema_crossover_markers: bool = True,
        show_trade_paths: bool = False,
        show_trade_pair_numbers: bool = False,
        use_addplot_trade_markers: bool = False,
        trade_paths_max: int = 6,
        trade_pair_numbers_max: int = 6,
        trade_markers_max: int = 20,
        show_trade_overlay_legend: bool = False,
        save_pad_inches: float = 0.25,
        telegram_top_headroom_pct: float = 0.06,
        optimize_png: bool = False,
    ) -> Optional[Path]:
        """
        Generate a TradingView-style dashboard chart.

        Args:
            data: OHLCV DataFrame (expects timestamp/DatetimeIndex; works with any bar timeframe)
            symbol: Symbol name for title
            timeframe: Timeframe label for title (e.g. "5m")
            lookback_bars: Number of bars to display
            range_label: Optional range label for title (e.g., "24h", "48h", "3d")
            figsize: Figure size (width, height) – portrait recommended for mobile
            dpi: Resolution for Telegram delivery
            show_sessions: Shade Tokyo/London/NY sessions
            show_key_levels: Show RTH/ETH PDH/PDL/Open levels
            show_vwap: Show VWAP line + bands
            show_ma: Show moving averages (default: True)
            ma_periods: List of MA periods to display (default: [20, 50, 200])
            show_rsi: Show RSI panel
            show_pressure: Show buy/sell pressure proxy panel (signed volume histogram)
            title_time: Optional fixed time string for title (e.g., "12:00 UTC").
                        If None, uses current UTC time. Used for deterministic testing.
            right_pad_bars: Optional extra bars of right-side padding beyond last candle.
            trades: Optional list of trade dicts to overlay as markers.
            manifest_path: Optional path to save a JSON render manifest for semantic
                          regression checks. Default None (no manifest). When provided,
                          saves chart metadata (inputs, indicators, config) alongside PNG.

        Returns:
            Path to generated PNG, or None on failure
        """
        if not MPLFINANCE_AVAILABLE:
            logger.warning("mplfinance not available for dashboard chart")
            return None

        try:
            if data is None or data.empty:
                logger.warning("Cannot generate dashboard chart: data is empty")
                return None

            # Limit to lookback_bars (bars, not hours — caller controls based on timeframe)
            chart_data = data.tail(int(lookback_bars)).copy()
            df = self._prepare_data(chart_data)

            if df.empty:
                logger.warning("Cannot generate dashboard chart: prepared data is empty")
                return None

            # Build HUD context for overlays
            hud: Dict[str, Any] = {}
            try:
                # Convert back to lowercase for hud_context (it expects lowercase OHLCV)
                hud_df = df.reset_index().copy()
                hud_df = hud_df.rename(columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                })
                if "Volume" in hud_df.columns:
                    hud_df = hud_df.rename(columns={"Volume": "volume"})
                # Rename index column to timestamp if needed
                if "index" in hud_df.columns:
                    hud_df = hud_df.rename(columns={"index": "timestamp"})

                hud = build_hud_context(hud_df, symbol=symbol, tick_size=0.25)
            except Exception as e:
                logger.debug(f"Could not build HUD context for dashboard chart: {e}")

            # Addplots
            addplot: List = []

            # Moving averages (EMA-style) + crossover markers (to match TradingView scripts)
            if show_ma:
                # Always include the common crossover pair (9/20) for the "EMA Crossover" script.
                raw_periods = ma_periods or [20, 50, 200]
                ma_periods_list: List[int] = []
                for p in [9, 20] + list(raw_periods):
                    try:
                        pi = int(p)
                    except Exception:
                        continue
                    if pi <= 0 or pi in ma_periods_list:
                        continue
                    ma_periods_list.append(pi)

                for period in ma_periods_list:
                    if period <= len(df):
                        color_idx = ma_periods_list.index(period) % len(MA_COLORS)
                        color = MA_COLORS[color_idx]
                        ma_series = df["Close"].ewm(span=int(period), adjust=False).mean()
                        addplot.append(
                            mpf.make_addplot(
                                ma_series,
                                color=color,
                                width=1.2,
                                alpha=0.7,
                                label=f"EMA{period}",
                            )
                        )

                # EMA crossover markers (9/20) — kept visually light to avoid mobile clutter
                if show_ema_crossover_markers:
                    try:
                        fast, slow = 9, 20
                        if fast <= len(df) and slow <= len(df):
                            ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
                            ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
                            cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
                            cross_dn = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

                            max_markers = 12
                            up_idx = np.where(cross_up.fillna(False).to_numpy(dtype=bool))[0]
                            dn_idx = np.where(cross_dn.fillna(False).to_numpy(dtype=bool))[0]
                            if len(up_idx) > max_markers:
                                up_idx = up_idx[-max_markers:]
                            if len(dn_idx) > max_markers:
                                dn_idx = dn_idx[-max_markers:]

                            if len(up_idx) > 0:
                                y_up = pd.Series(np.nan, index=df.index)
                                y_up.iloc[up_idx] = df["Low"].iloc[up_idx] * 0.999
                                addplot.append(
                                    mpf.make_addplot(
                                        y_up,
                                        type="scatter",
                                        marker="^",
                                        markersize=55,
                                        color="#00bcd4",  # cyan (distinct from trade markers)
                                        alpha=0.65,
                                    )
                                )
                            if len(dn_idx) > 0:
                                y_dn = pd.Series(np.nan, index=df.index)
                                y_dn.iloc[dn_idx] = df["High"].iloc[dn_idx] * 1.001
                                addplot.append(
                                    mpf.make_addplot(
                                        y_dn,
                                        type="scatter",
                                        marker="v",
                                        markersize=55,
                                        color="#e91e63",  # pink (distinct from trade markers)
                                        alpha=0.65,
                                    )
                                )
                    except Exception:
                        pass

            # VWAP (anchored) + bands (VWAP AA-style)
            if show_vwap and ("Volume" in df.columns):
                try:
                    idx = df.index
                    if not isinstance(idx, pd.DatetimeIndex) or len(idx) < 2:
                        raise ValueError("Dashboard VWAP requires DatetimeIndex")

                    # Compute anchored VWAP series (default: CME ETH session start = 18:00 ET)
                    idx_utc = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
                    try:
                        idx_local = idx_utc.tz_convert("America/New_York")
                        anchor_min = 18 * 60  # 18:00 ET
                    except Exception:
                        idx_local = idx_utc
                        anchor_min = 0  # midnight UTC fallback

                    mins = idx_local.hour * 60 + idx_local.minute
                    day = idx_local.floor("D")
                    session_key = day.where(mins >= anchor_min, day - pd.Timedelta(days=1))
                    try:
                        session_key = session_key.tz_localize(None)
                    except Exception:
                        pass

                    close = pd.to_numeric(df["Close"], errors="coerce")
                    high = pd.to_numeric(df["High"], errors="coerce")
                    low = pd.to_numeric(df["Low"], errors="coerce")
                    vol = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
                    typical = (high + low + close) / 3.0
                    vp = typical * vol
                    cum_vp = vp.groupby(session_key).cumsum()
                    cum_vol = vol.groupby(session_key).cumsum()
                    vwap_series = (cum_vp / cum_vol.replace(0.0, np.nan)).astype(float)

                    if not vwap_series.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                vwap_series,
                                color=VWAP_COLOR,
                                width=1.8,
                                alpha=0.80,
                                label="VWAP",
                            )
                        )

                        # VWAP AA bands: rolling stdev around VWAP (±1σ, ±2σ)
                        stdev = close.rolling(window=20, min_periods=5).std()
                        upper1 = vwap_series + stdev
                        lower1 = vwap_series - stdev
                        upper2 = vwap_series + (stdev * 2.0)
                        lower2 = vwap_series - (stdev * 2.0)

                        for band, a in (
                            (upper1, ALPHA_VWAP_BAND_1),
                            (lower1, ALPHA_VWAP_BAND_1),
                            (upper2, ALPHA_VWAP_BAND_2),
                            (lower2, ALPHA_VWAP_BAND_2),
                        ):
                            if band is None or band.isna().all():
                                continue
                            addplot.append(
                                mpf.make_addplot(
                                    band,
                                    color=VWAP_COLOR,
                                    width=1.0,
                                    linestyle="--",
                                    alpha=a,
                                )
                            )

                        # Feed into HUD so right labels can include VWAP + bands
                        try:
                            last_vwap = float(vwap_series.dropna().iloc[-1])
                            hud["vwap"] = {
                                "vwap": last_vwap,
                                "vwap_upper_1": float(upper1.dropna().iloc[-1]) if not upper1.isna().all() else last_vwap,
                                "vwap_lower_1": float(lower1.dropna().iloc[-1]) if not lower1.isna().all() else last_vwap,
                                "vwap_upper_2": float(upper2.dropna().iloc[-1]) if not upper2.isna().all() else last_vwap,
                                "vwap_lower_2": float(lower2.dropna().iloc[-1]) if not lower2.isna().all() else last_vwap,
                            }
                            # Store full series for fill_between when enabled
                            if self.config.vwap_fill_bands:
                                hud["vwap"]["_series"] = vwap_series
                                hud["vwap"]["_upper1"] = upper1
                                hud["vwap"]["_lower1"] = lower1
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug(f"Error adding VWAP to dashboard chart: {e}")

            # Volume MA overlay (Vol script)
            if "Volume" in df.columns:
                try:
                    vol_ma = pd.to_numeric(df["Volume"], errors="coerce").rolling(window=20, min_periods=2).mean()
                    addplot.append(
                        mpf.make_addplot(
                            vol_ma,
                            panel=1,
                            color="#42a5f5",
                            width=1.2,
                            alpha=0.7,
                        )
                    )
                except Exception:
                    pass

            volume_on = "Volume" in df.columns and self.config.show_volume_panel
            # Trade recap panel (replaces pressure panel when enabled)
            recap_enabled = bool(show_trade_recap and self.config.show_trade_recap_panel)
            recap_panel_idx = (2 if volume_on else 1) if recap_enabled else None
            # Pressure panel (buy/sell proxy): signed volume histogram (+vol for up candles, -vol for down candles)
            # Respects both function parameter and config option, but is disabled when recap is active.
            pressure_enabled = bool(show_pressure and volume_on and self.config.show_pressure_panel and not recap_enabled)
            if pressure_enabled:
                try:
                    close = df["Close"]
                    open_ = df["Open"]
                    vol = df["Volume"].fillna(0.0)
                    sign = np.sign((close - open_).fillna(0.0))
                    signed_vol = vol * sign
                    addplot.append(
                        mpf.make_addplot(
                            signed_vol,
                            panel=2,  # price=0, volume=1, pressure=2
                            type="bar",
                            width=0.8,
                            alpha=0.65,
                            color=[
                                (CANDLE_UP if v >= 0 else CANDLE_DOWN)
                                for v in signed_vol.fillna(0.0).tolist()
                            ],
                            ylabel="Pressure",
                        )
                    )
                except Exception as e:
                    pressure_enabled = False
                    logger.debug(f"Error adding pressure panel to dashboard chart: {e}")

            # Reserve a panel slot for the Trade Recap panel (no visible plot).
            if recap_enabled and recap_panel_idx is not None:
                try:
                    recap_stub = pd.Series([0.0] * len(df), index=df.index)
                    addplot.append(
                        mpf.make_addplot(
                            recap_stub,
                            panel=recap_panel_idx,
                            color=TEXT_SECONDARY,
                            alpha=0.0,
                        )
                    )
                except Exception as e:
                    logger.debug(f"Error reserving trade recap panel: {e}")

            # RSI panel (shift down if pressure is enabled)
            # Uses Wilder's smoothing (EMA with alpha=1/period) for standard RSI
            panel_ratios = None
            rsi_series_for_shading = None
            rsi_panel_idx = None
            if show_rsi:
                try:
                    close = df["Close"]
                    delta = close.diff()
                    alpha = 1.0 / self.config.rsi_period
                    gain = delta.clip(lower=0).ewm(alpha=alpha, adjust=False).mean()
                    loss = (-delta.clip(upper=0)).ewm(alpha=alpha, adjust=False).mean()
                    rs = gain / loss.replace(0, np.nan)
                    rsi = 100 - (100 / (1 + rs))

                    # Panel allocation:
                    # - price: 0
                    # - volume: 1 (built-in)
                    # - recap: 2 (optional)
                    # - pressure: 2 (optional, only if recap disabled)
                    # - rsi: 3 (if volume+recap/pressure) else 2 if volume else 1
                    if volume_on:
                        recap_panel_idx = 2 if recap_enabled else None
                        rsi_panel = 3 if (recap_enabled or pressure_enabled) else 2
                    else:
                        recap_panel_idx = 1 if recap_enabled else None
                        rsi_panel = 2 if recap_enabled else 1
                    addplot.append(
                        mpf.make_addplot(
                            rsi,
                            panel=rsi_panel,
                            color="#b388ff",
                            width=1.2,
                            ylabel="RSI",
                            alpha=0.9,
                        )
                    )
                    for lvl, a in ((30, 0.25), (50, 0.18), (70, 0.25)):
                        addplot.append(
                            mpf.make_addplot(
                                pd.Series([lvl] * len(df), index=df.index),
                                panel=rsi_panel,
                                color=TEXT_SECONDARY,
                                width=1.0,
                                linestyle="--",
                                alpha=a,
                            )
                        )
                    # Use configurable panel ratios
                    pr_price = self.config.panel_ratio_price
                    pr_vol = self.config.panel_ratio_volume
                    pr_sub = self.config.panel_ratio_sub
                    sub_panels = int(recap_enabled or pressure_enabled) + int(show_rsi)
                    if volume_on:
                        if sub_panels >= 2:
                            panel_ratios = (pr_price, pr_vol, pr_sub, pr_sub)
                        elif sub_panels == 1:
                            panel_ratios = (pr_price, pr_vol, pr_sub + 0.2)
                    else:
                        if sub_panels >= 2:
                            panel_ratios = (pr_price, pr_sub + 0.4, pr_sub + 0.4)
                        elif sub_panels == 1:
                            panel_ratios = (pr_price, pr_sub + 0.8)
                    
                    # Store for overbought/oversold shading (applied after mpf.plot)
                    rsi_series_for_shading = rsi
                    rsi_panel_idx = rsi_panel
                except Exception as e:
                    logger.debug(f"Error adding RSI to dashboard chart: {e}")

            # If RSI is off but pressure is on, still provide panel ratios for stable layout
            if panel_ratios is None and volume_on and (recap_enabled or pressure_enabled):
                pr_price = self.config.panel_ratio_price
                pr_vol = self.config.panel_ratio_volume
                pr_sub = self.config.panel_ratio_sub
                panel_ratios = (pr_price, pr_vol, pr_sub + 0.2)

            # Trade markers overlay (entries/exits) for transparency on push dashboards.
            # NOTE: Keep this visually light; too many markers will clutter mobile charts.
            overlay_trades: List[Dict[str, Any]] = []
            if trades:
                try:
                    overlay_trades = [t for t in trades if isinstance(t, dict)]
                    try:
                        max_m = int(trade_markers_max)
                    except Exception:
                        max_m = 20
                    max_m = max(1, min(30, max_m))
                    overlay_trades = overlay_trades[-max_m:]

                    idx = df.index
                    idx_tz = getattr(idx, "tz", None)

                    def _align_ts(raw):
                        if not raw:
                            return None
                        try:
                            tsx = pd.Timestamp(raw)
                        except Exception:
                            return None

                        try:
                            if idx_tz is None:
                                # Normalize to naive UTC for matching.
                                if tsx.tzinfo is not None:
                                    tsx = tsx.tz_convert("UTC").tz_localize(None)
                                else:
                                    tsx = tsx.tz_localize(None) if hasattr(tsx, "tz_localize") else tsx
                            else:
                                # Normalize to the chart index timezone.
                                if tsx.tzinfo is None:
                                    # Assume UTC when missing tz.
                                    tsx = tsx.tz_localize("UTC").tz_convert(idx_tz)
                                else:
                                    tsx = tsx.tz_convert(idx_tz)
                        except Exception:
                            return None
                        return tsx

                    # Pre-allocate marker series (NaN by default).
                    # We color entries/exits by outcome (pnl) when available:
                    #   - Green = win, Red = loss
                    # and keep marker SHAPE = direction (^ long, v short).
                    win_long_y = pd.Series(np.nan, index=idx)
                    loss_long_y = pd.Series(np.nan, index=idx)
                    open_long_y = pd.Series(np.nan, index=idx)
                    win_short_y = pd.Series(np.nan, index=idx)
                    loss_short_y = pd.Series(np.nan, index=idx)
                    open_short_y = pd.Series(np.nan, index=idx)

                    win_exit_y = pd.Series(np.nan, index=idx)
                    loss_exit_y = pd.Series(np.nan, index=idx)
                    exit_y = pd.Series(np.nan, index=idx)  # unknown outcome / missing pnl

                    # Dynamic sizing (avoid clutter when many markers).
                    n_trades = max(1, min(20, len(overlay_trades)))
                    entry_size = int(max(55.0, min(90.0, 90.0 * math.sqrt(10.0 / float(n_trades)))))
                    exit_size = int(max(45.0, min(70.0, 65.0 * math.sqrt(10.0 / float(n_trades)))))

                    for tr in overlay_trades:
                        direction = str(tr.get("direction") or "long").lower()

                        # Outcome (prefer pnl if available; fall back to is_win bool if present)
                        pnl_val = tr.get("pnl", None)
                        is_win: Optional[bool] = None
                        if pnl_val is not None:
                            try:
                                is_win = float(pnl_val) > 0
                            except Exception:
                                is_win = None
                        if is_win is None and isinstance(tr.get("is_win"), bool):
                            is_win = bool(tr.get("is_win"))

                        et = _align_ts(tr.get("entry_time"))
                        if et is not None:
                            try:
                                pos = int(idx.get_indexer([et], method="nearest")[0])
                            except Exception:
                                pos = -1
                            if 0 <= pos < len(df):
                                # Place entries at/near candle extremes for visibility (TradingView-like).
                                try:
                                    if direction == "short":
                                        y = float(df["High"].iloc[pos]) * 1.001
                                        if is_win is True:
                                            win_short_y.iloc[pos] = y
                                        elif is_win is False:
                                            loss_short_y.iloc[pos] = y
                                        else:
                                            open_short_y.iloc[pos] = y
                                    else:
                                        y = float(df["Low"].iloc[pos]) * 0.999
                                        if is_win is True:
                                            win_long_y.iloc[pos] = y
                                        elif is_win is False:
                                            loss_long_y.iloc[pos] = y
                                        else:
                                            open_long_y.iloc[pos] = y
                                except Exception:
                                    # If High/Low missing for any reason, skip entry marker.
                                    pass

                        xt = _align_ts(tr.get("exit_time"))
                        xp = tr.get("exit_price")
                        if xt is not None and xp is not None:
                            try:
                                xp_f = float(xp)
                            except Exception:
                                xp_f = 0.0
                            if xp_f > 0:
                                try:
                                    pos = int(idx.get_indexer([xt], method="nearest")[0])
                                except Exception:
                                    pos = -1
                                if 0 <= pos < len(df):
                                    if is_win is True:
                                        win_exit_y.iloc[pos] = xp_f
                                    elif is_win is False:
                                        loss_exit_y.iloc[pos] = xp_f
                                    else:
                                        exit_y.iloc[pos] = xp_f

                    # Addplots for markers (only if we have any)
                    if not win_long_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                win_long_y,
                                type="scatter",
                                marker="^",
                                markersize=entry_size,
                                color=SIGNAL_LONG,  # win
                                alpha=0.9,
                            )
                        )
                    if not loss_long_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                loss_long_y,
                                type="scatter",
                                marker="^",
                                markersize=entry_size,
                                color=SIGNAL_SHORT,  # loss
                                alpha=0.9,
                            )
                        )
                    if not open_long_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                open_long_y,
                                type="scatter",
                                marker="^",
                                markersize=max(45, int(entry_size * 0.85)),
                                color=SIGNAL_LONG,
                                alpha=0.55,
                            )
                        )

                    if not win_short_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                win_short_y,
                                type="scatter",
                                marker="v",
                                markersize=entry_size,
                                color=SIGNAL_LONG,  # win
                                alpha=0.9,
                            )
                        )
                    if not loss_short_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                loss_short_y,
                                type="scatter",
                                marker="v",
                                markersize=entry_size,
                                color=SIGNAL_SHORT,  # loss
                                alpha=0.9,
                            )
                        )
                    if not open_short_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                open_short_y,
                                type="scatter",
                                marker="v",
                                markersize=max(45, int(entry_size * 0.85)),
                                color=SIGNAL_SHORT,
                                alpha=0.55,
                            )
                        )

                    # Exit markers (colored by outcome when available)
                    if not win_exit_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                win_exit_y,
                                type="scatter",
                                marker="o",
                                markersize=exit_size,
                                color=SIGNAL_LONG,
                                alpha=0.85,
                            )
                        )
                    if not loss_exit_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                loss_exit_y,
                                type="scatter",
                                marker="o",
                                markersize=exit_size,
                                color=SIGNAL_SHORT,
                                alpha=0.85,
                            )
                        )
                    if not exit_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                exit_y,
                                type="scatter",
                                marker="o",
                                markersize=max(40, int(exit_size * 0.9)),
                                color=TEXT_PRIMARY,
                                alpha=0.7,
                            )
                        )
                except Exception as e:
                    logger.debug(f"Could not add trade markers to dashboard chart: {e}")

            # Title (use fixed title_time if provided for deterministic testing)
            if title_time is not None:
                now_str = str(title_time)
            else:
                try:
                    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
                except Exception:
                    now_str = ""
            label = range_label or "Dashboard"
            title = f"{symbol} {label} ({timeframe}) • {now_str}"

            # Temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_path = Path(temp_file.name)
            temp_file.close()

            # Wider candles for Telegram visibility
            # Build kwargs - only include panel_ratios if RSI added successfully (mplfinance rejects None)
            # Blank ylabel for mobile/Telegram to avoid collision with right labels
            is_telegram = render_mode == "telegram" or self.config.mobile_mode
            ylabel_str = "" if is_telegram else "Price ($)"
            
            # For Telegram/mobile: use figure-level suptitle (not axes title) to save chart space
            # Pass empty title to mpf.plot, add suptitle after
            mpf_title = "" if is_telegram else title
            
            plot_kwargs = dict(
                type="candle",
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=mpf_title,
                ylabel=ylabel_str,
                ylabel_lower="Volume" if volume_on else None,
                figsize=figsize,
                show_nontrading=False,
                tight_layout=True,
                returnfig=True,
                scale_width_adjustment=dict(candle=1.4, volume=0.8, lines=1.0),
                update_width_config=dict(candle_linewidth=1.2, candle_width=0.75),
                warn_too_much_data=500,
            )
            if volume_on:
                plot_kwargs['volume_panel'] = 1
            if panel_ratios is not None:
                plot_kwargs['panel_ratios'] = panel_ratios

            fig, axlist = mpf.plot(df, **plot_kwargs)

            # For Telegram/mobile: add compact figure-level title and reduce axis font sizes
            if is_telegram:
                try:
                    # Add figure-level suptitle (outside plot area, at very top)
                    fig.suptitle(
                        title,
                        fontsize=FONT_SIZE_TITLE_MOBILE,
                        color=TEXT_PRIMARY,
                        y=0.995,  # Very top of figure
                        fontweight='normal',
                    )
                    # Reduce axis tick font sizes for all panels
                    for ax in (axlist if isinstance(axlist, list) else [axlist]):
                        if ax is not None:
                            ax.tick_params(axis='both', labelsize=FONT_SIZE_AXIS_TICK_MOBILE)
                except Exception:
                    pass

            # RSI overbought/oversold shading (must be done after mpf.plot, before other overlays)
            if rsi_series_for_shading is not None and rsi_panel_idx is not None:
                try:
                    # In mplfinance, axlist indices map to panels:
                    # [0]=price, [1]=volume, [2]=pressure or RSI, [3]=RSI (if pressure enabled)
                    # Each panel may have sub-axes, so we need to find the right one
                    ax_rsi = None
                    if isinstance(axlist, list):
                        # Find the axis for the RSI panel
                        # mplfinance returns axes in panel order, with volume sharing index with price
                        # The actual mapping depends on panel_ratios and which panels are enabled
                        potential_idx = rsi_panel_idx * 2 if volume_on else rsi_panel_idx
                        if potential_idx < len(axlist):
                            ax_rsi = axlist[potential_idx]
                    if ax_rsi is not None:
                        self._draw_rsi_overbought_oversold_shading(ax_rsi, rsi_series_for_shading)
                except Exception as e:
                    logger.debug(f"Error adding RSI shading: {e}")

            # Trade Recap panel (equity + drawdown) - rendered after mpf.plot.
            if recap_enabled and recap_panel_idx is not None:
                try:
                    ax_recap = None
                    if isinstance(axlist, list):
                        potential_idx = recap_panel_idx * 2 if volume_on else recap_panel_idx
                        if potential_idx < len(axlist):
                            ax_recap = axlist[potential_idx]
                    if ax_recap is not None:
                        self._draw_trade_recap_panel(ax_recap, pnl_overlay, range_label=range_label)
                except Exception as e:
                    logger.debug(f"Error adding trade recap panel: {e}")

            # HUD overlays (sessions, key levels, legend)
            try:
                ax_price = axlist[0] if isinstance(axlist, list) and axlist else None
                if ax_price is not None:
                    # Add right-side padding so the last candle has visual "future" space.
                    try:
                        if right_pad_bars is None:
                            right_pad = max(0, int(self.config.right_pad_bars))
                        else:
                            right_pad = max(0, int(right_pad_bars))
                    except Exception:
                        right_pad = 0
                    if right_pad and len(df) > 0:
                        ax_price.set_xlim(-0.5, float((len(df) - 1) + right_pad))

                    # Add TOP PADDING for title/legend headroom (prevents overlap with candles)
                    # Extend y-max by ~5% for Telegram/mobile mode to create space for title+legend
                    if is_telegram:
                        try:
                            ymin, ymax = ax_price.get_ylim()
                            y_range = ymax - ymin
                            try:
                                top_headroom_pct = float(telegram_top_headroom_pct)
                            except Exception:
                                top_headroom_pct = 0.06
                            top_headroom_pct = max(0.0, min(0.15, top_headroom_pct))
                            top_padding = y_range * top_headroom_pct
                            ax_price.set_ylim(ymin, ymax + top_padding)
                        except Exception:
                            pass


                    trades_for_overlay = overlay_trades if overlay_trades else (trades or [])

                    # Smart Trade Markers (P8) - cohesive entry/exit/outcome visualization
                    # Replaces legacy trade paths and numbered pairs
                    if trades_for_overlay:
                        try:
                            self._draw_trade_markers(
                                ax_price, df, trades_for_overlay, max_trades=int(trade_markers_max)
                            )
                        except Exception:
                            pass

                    # Compact overlay legend (Telegram/mobile)
                    if show_trade_overlay_legend:
                        try:
                            self._draw_trade_overlay_legend(
                                ax_price,
                                ema_crossovers_shown=bool(show_ema_crossover_markers),
                            )
                        except Exception:
                            pass

                    # Limit y-axis ticks to prevent overlapping labels
                    self._limit_yaxis_ticks(ax_price, max_ticks=8)
                    # Sessions shading
                    if show_sessions:
                        self._draw_sessions_overlay(ax_price, hud, idx=df.index if isinstance(df.index, pd.DatetimeIndex) else None)

                    # Indicator overlays from your TradingView scripts (LuxAlgo / ChartPrime ports)
                    # These are z-ordered behind candles and do not affect axis scaling.
                    self._draw_supply_demand_overlay(ax_price, hud)
                    self._draw_power_channel_overlay(ax_price, hud)
                    self._draw_tbt_overlay(ax_price, hud)
                    
                    # VWAP band fills (optional, enabled via vwap_fill_bands config)
                    self._draw_vwap_band_fills(ax_price, hud)

                    # Key levels (DO/PDH/PDL/PDM, RTH, VWAP, POC) via shared pipeline
                    # Reuses _collect_level_candidates for consistency with entry/exit charts
                    if show_key_levels and self.config.show_right_labels:
                        # Use shared level collection (signal={} since this is a dashboard, not a trade)
                        candidates, current_price = self._collect_level_candidates(df, {}, hud)
                        if candidates:
                            try:
                                merge_ticks = 6 if bool(self.config.compact_labels) else int(self.config.right_label_merge_ticks)
                            except Exception:
                                merge_ticks = 4
                            try:
                                max_labels = 6 if bool(self.config.compact_labels) else int(self.config.max_right_labels)
                            except Exception:
                                max_labels = 10
                            merged = self._merge_levels(candidates, tick_size=0.25, merge_ticks=merge_ticks)
                            self._draw_right_labels(
                                fig,
                                ax_price,
                                merged,
                                current_price=current_price,
                                max_labels=max_labels,
                            )
                    
                    # Dashboard legend (consistent order: VWAP, MAs)
                    self._draw_dashboard_legend(
                        ax_price,
                        show_vwap=show_vwap,
                        show_ma=show_ma,
                        ma_periods=ma_periods_list if show_ma else None,
                    )
                    
                    # Session label overlay (top-left corner)
                    if session_label:
                        try:
                            ax_price.text(
                                0.02, 0.97,
                                session_label,
                                transform=ax_price.transAxes,
                                fontsize=FONT_SIZE_SESSION,
                                color=TEXT_PRIMARY,
                                alpha=0.9,
                                verticalalignment='top',
                                horizontalalignment='left',
                                bbox=dict(
                                    boxstyle='round,pad=0.3',
                                    facecolor=DARK_BG,
                                    edgecolor=GRID_COLOR,
                                    alpha=ALPHA_LEGEND_BG,
                                ),
                                zorder=ZORDER_TEXT_LABELS,
                            )
                        except Exception as e:
                            logger.debug(f"Error adding session label: {e}")
                    
                    # P&L overlay (bottom-right corner) - only when recap panel is off.
                    if (not recap_enabled) and pnl_overlay and isinstance(pnl_overlay, dict):
                        try:
                            daily_pnl = pnl_overlay.get("daily_pnl", 0.0)
                            trades_count = pnl_overlay.get("trades", 0)
                            win_rate = pnl_overlay.get("win_rate", 0.0)
                            label = str(pnl_overlay.get("label") or "").strip()
                            detailed = bool(pnl_overlay.get("detailed", False))
                            
                            pnl_color = CANDLE_UP if daily_pnl >= 0 else CANDLE_DOWN
                            pnl_sign = "+" if daily_pnl >= 0 else ""
                            
                            pnl_lines = [f"{pnl_sign}${daily_pnl:,.2f}"]
                            meta_parts: List[str] = []
                            if label:
                                meta_parts.append(label)
                            if trades_count > 0:
                                meta_parts.append(f"{trades_count} trades")
                                meta_parts.append(f"{win_rate:.0f}% WR")
                            if meta_parts:
                                pnl_lines.append(" | ".join(meta_parts))

                            # Optional: in-chart performance section (larger than the sparkline).
                            # Enabled only when `pnl_curve` is provided to avoid changing default charts.
                            curve_raw = pnl_overlay.get("pnl_curve")
                            if detailed and isinstance(curve_raw, (list, tuple)) and len(curve_raw) >= 2:
                                try:
                                    y_vals = [float(v) for v in curve_raw if v is not None]
                                except Exception:
                                    y_vals = []
                                if len(y_vals) >= 2:
                                    try:
                                        y = np.array(y_vals, dtype=float)
                                        x = np.arange(len(y), dtype=float)
                                        cummax = np.maximum.accumulate(y)
                                        dd = y - cummax
                                        max_dd = float(abs(np.min(dd))) if len(dd) else 0.0

                                        # Dedicated panel in the bottom-right of the PRICE panel.
                                        ax_panel = ax_price.inset_axes([0.63, 0.03, 0.35, 0.22])
                                        ax_panel.set_zorder(ZORDER_TEXT_LABELS)
                                        ax_panel.set_facecolor(mcolors.to_rgba(DARK_BG, alpha=0.45))
                                        ax_panel.set_xticks([])
                                        ax_panel.set_yticks([])

                                        # Border in P&L color for quick sign recognition.
                                        try:
                                            for sp in ax_panel.spines.values():
                                                sp.set_visible(True)
                                                sp.set_edgecolor(pnl_color)
                                                sp.set_alpha(0.55)
                                                sp.set_linewidth(1.0)
                                        except Exception:
                                            pass

                                        # Title/metrics inside the panel (top-left)
                                        stats_lines = [
                                            f"{pnl_sign}${daily_pnl:,.2f}  •  {label}".strip(),
                                            f"{trades_count} trades  •  {win_rate:.0f}% WR  •  MaxDD ${max_dd:,.0f}",
                                        ]
                                        ax_panel.text(
                                            0.04,
                                            0.96,
                                            "\n".join([s for s in stats_lines if s]),
                                            transform=ax_panel.transAxes,
                                            ha="left",
                                            va="top",
                                            fontsize=8,
                                            color=TEXT_PRIMARY,
                                            alpha=0.92,
                                        )

                                        # Equity sub-plot (top area)
                                        ax_eq = ax_panel.inset_axes([0.05, 0.38, 0.92, 0.54])
                                        ax_eq.set_facecolor(mcolors.to_rgba(DARK_BG, alpha=0.0))
                                        ax_eq.axhline(0.0, color=GRID_COLOR, linewidth=0.8, linestyle="--", alpha=0.7)
                                        ax_eq.plot(x, y, color=TEXT_PRIMARY, linewidth=1.2, alpha=0.9)
                                        ax_eq.fill_between(x, 0.0, y, where=(y >= 0), color=CANDLE_UP, alpha=0.22)
                                        ax_eq.fill_between(x, 0.0, y, where=(y < 0), color=CANDLE_DOWN, alpha=0.22)
                                        ax_eq.scatter(
                                            [x[-1]],
                                            [y[-1]],
                                            s=20,
                                            color=pnl_color,
                                            edgecolors=DARK_BG,
                                            linewidths=0.8,
                                            zorder=ZORDER_TEXT_LABELS,
                                        )

                                        # Drawdown sub-plot (bottom area)
                                        ax_dd = ax_panel.inset_axes([0.05, 0.10, 0.92, 0.22])
                                        ax_dd.set_facecolor(mcolors.to_rgba(DARK_BG, alpha=0.0))
                                        ax_dd.axhline(0.0, color=GRID_COLOR, linewidth=0.8, linestyle="--", alpha=0.7)
                                        ax_dd.fill_between(x, 0.0, dd, color=CANDLE_DOWN, alpha=0.30)

                                        # Tight framing
                                        try:
                                            ymin = float(np.min(y))
                                            ymax = float(np.max(y))
                                            yr = ymax - ymin
                                            pad = (yr * 0.12) if yr > 0 else max(
                                                1.0, abs(ymax) * 0.15, abs(ymin) * 0.15
                                            )
                                            ax_eq.set_xlim(float(x[0]), float(x[-1]))
                                            ax_eq.set_ylim(ymin - pad, ymax + pad)
                                            ddmin = float(np.min(dd)) if len(dd) else 0.0
                                            ax_dd.set_xlim(float(x[0]), float(x[-1]))
                                            ax_dd.set_ylim(ddmin * 1.15, 0.0 + max(1.0, abs(ddmin) * 0.05))
                                        except Exception:
                                            pass

                                        for ax_small in (ax_eq, ax_dd):
                                            ax_small.set_xticks([])
                                            ax_small.set_yticks([])
                                            try:
                                                for sp in ax_small.spines.values():
                                                    sp.set_visible(False)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            else:
                                # Default (compact): text card + small sparkline above it.
                                ax_price.text(
                                    0.98, 0.03,
                                    "\n".join(pnl_lines),
                                    transform=ax_price.transAxes,
                                    fontsize=FONT_SIZE_SUMMARY,
                                    color=pnl_color,
                                    alpha=0.9,
                                    verticalalignment='bottom',
                                    horizontalalignment='right',
                                    bbox=dict(
                                        boxstyle='round,pad=0.3',
                                        facecolor=DARK_BG,
                                        edgecolor=pnl_color,
                                        alpha=ALPHA_LEGEND_BG,
                                    ),
                                    zorder=ZORDER_TEXT_LABELS,
                                )

                                if isinstance(curve_raw, (list, tuple)) and len(curve_raw) >= 2:
                                    try:
                                        y_vals = [float(v) for v in curve_raw if v is not None]
                                    except Exception:
                                        y_vals = []
                                    if len(y_vals) >= 2:
                                        try:
                                            y = np.array(y_vals, dtype=float)
                                            x = np.arange(len(y), dtype=float)

                                            # Place sparkline just above the P&L text card (bottom-right).
                                            ax_pnl = ax_price.inset_axes([0.70, 0.12, 0.28, 0.10])
                                            ax_pnl.set_zorder(ZORDER_TEXT_LABELS)
                                            ax_pnl.set_facecolor(mcolors.to_rgba(DARK_BG, alpha=0.40))

                                            # Border in P&L color for quick sign recognition.
                                            try:
                                                for sp in ax_pnl.spines.values():
                                                    sp.set_visible(True)
                                                    sp.set_edgecolor(pnl_color)
                                                    sp.set_alpha(0.55)
                                                    sp.set_linewidth(1.0)
                                            except Exception:
                                                pass

                                            # Core sparkline + 0 baseline
                                            ax_pnl.axhline(0.0, color=GRID_COLOR, linewidth=0.8, linestyle="--", alpha=0.7)
                                            ax_pnl.plot(x, y, color=TEXT_PRIMARY, linewidth=1.2, alpha=0.9)
                                            ax_pnl.fill_between(x, 0.0, y, where=(y >= 0), color=CANDLE_UP, alpha=0.22)
                                            ax_pnl.fill_between(x, 0.0, y, where=(y < 0), color=CANDLE_DOWN, alpha=0.22)

                                            # Last point marker
                                            ax_pnl.scatter(
                                                [x[-1]],
                                                [y[-1]],
                                                s=22,
                                                color=pnl_color,
                                                edgecolors=DARK_BG,
                                                linewidths=0.8,
                                                zorder=ZORDER_TEXT_LABELS,
                                            )

                                            # Tight framing with padding
                                            ymin = float(np.min(y))
                                            ymax = float(np.max(y))
                                            yr = ymax - ymin
                                            pad = (yr * 0.12) if yr > 0 else max(
                                                1.0, abs(ymax) * 0.15, abs(ymin) * 0.15
                                            )
                                            ax_pnl.set_xlim(float(x[0]), float(x[-1]))
                                            ax_pnl.set_ylim(ymin - pad, ymax + pad)

                                            # No ticks/labels (sparkline only)
                                            ax_pnl.set_xticks([])
                                            ax_pnl.set_yticks([])
                                        except Exception:
                                            pass
                        except Exception as e:
                            logger.debug(f"Error adding P&L overlay: {e}")

                    # Regime Label (Top-Center)
                    if self.config.show_regime_label and regime_info:
                        try:
                            regime_type = str(regime_info.get("regime", "Unknown")).replace("_", " ").title()
                            ax_price.text(
                                0.5, 0.97,
                                f"Regime: {regime_type}",
                                transform=ax_price.transAxes,
                                ha="center", va="top",
                                fontsize=FONT_SIZE_TITLE_MOBILE,
                                color=TEXT_SECONDARY,
                                alpha=0.8,
                                zorder=ZORDER_TEXT_LABELS
                            )
                        except Exception as e:
                            logger.debug(f"Error adding regime label: {e}")

                    # ML Confidence Badge (Top-Right, below Legend)
                    if self.config.show_ml_confidence and regime_info:
                        try:
                            ml_conf = float(regime_info.get("confidence", 0.0))
                            if ml_conf > 0:
                                ml_color = SIGNAL_LONG if ml_conf > 0.6 else (SIGNAL_SHORT if ml_conf < 0.4 else TEXT_SECONDARY)
                                ax_price.text(
                                    0.98, 0.82 if self.config.mobile_mode else 0.88,
                                    f"ML: {ml_conf:.0%}",
                                    transform=ax_price.transAxes,
                                    ha="right", va="top",
                                    fontsize=FONT_SIZE_LEGEND,
                                    color=ml_color,
                                    fontweight="bold",
                                    bbox=dict(
                                        boxstyle='round,pad=0.2',
                                        facecolor=DARK_BG,
                                        edgecolor=ml_color,
                                        alpha=ALPHA_LEGEND_BG,
                                    ),
                                    zorder=ZORDER_TEXT_LABELS
                                )
                        except Exception as e:
                            logger.debug(f"Error adding ML confidence badge: {e}")
                    
            except Exception as e:
                logger.debug(f"Error applying HUD to dashboard chart: {e}")

            self._save_png(fig, temp_path, dpi=dpi, render_mode=render_mode, pad_inches=save_pad_inches, optimize=optimize_png)
            plt.close(fig)

            # Optional: emit render manifest for semantic regression checks
            if manifest_path is not None:
                try:
                    manifest = RenderManifest(
                        chart_type="dashboard",
                        symbol=symbol,
                        timeframe=timeframe,
                        lookback_bars=lookback_bars,
                        figsize=figsize,
                        dpi=dpi,
                        render_mode=render_mode,
                        render_timestamp=datetime.now(timezone.utc).isoformat(),
                        title_time=str(title_time) if title_time else "",
                        num_candles=len(df),
                        price_range=(float(df["Low"].min()), float(df["High"].max())),
                        indicators=[
                            f"EMA{p}" for p in (ma_periods_list if show_ma else [])
                        ] + (["VWAP"] if show_vwap else []) + (["RSI"] if show_rsi else []),
                        sessions=list(hud.get("sessions", [])) if isinstance(hud, dict) else [],
                        config_snapshot={
                            "show_sessions": show_sessions,
                            "show_key_levels": show_key_levels,
                            "show_vwap": show_vwap,
                            "show_ma": show_ma,
                            "show_rsi": show_rsi,
                            "show_pressure": show_pressure,
                        },
                    )
                    manifest.save(Path(manifest_path))
                    logger.debug(f"Saved render manifest: {manifest_path}")
                except Exception as me:
                    logger.debug(f"Could not save render manifest: {me}")

            logger.debug(f"Generated dashboard chart: {temp_path}")
            return temp_path

        except Exception as e:
            logger.error(f"Error generating dashboard chart: {e}", exc_info=True)
            return None
