"""
Chart Generator for NQ Agent using mplfinance.

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
MA_COLORS = ['#2196f3', '#9c27b0', '#f44336']

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
FONT_SIZE_LABEL = 9           # Right-side level labels
FONT_SIZE_SESSION = 8         # Session names (Tokyo/London/NY)
FONT_SIZE_POWER_READOUT = 10  # Power channel buy/sell readout
FONT_SIZE_RR_BOX = 9          # Risk/reward box USD labels
FONT_SIZE_LEGEND = 8          # Dashboard legend text
FONT_SIZE_TITLE = 14          # Equity curve chart title
FONT_SIZE_SUMMARY = 10        # Performance summary text

# Alpha (opacity) constants - for consistent transparency across chart elements
# Low alpha values ensure zones don't obscure candles (visual contract)
ALPHA_ZONE_SUPPLY_DEMAND = 0.18  # Supply/demand zone fills
ALPHA_ZONE_POWER_CHANNEL = 0.10  # Power channel zone fills
ALPHA_ZONE_RR_BOX_PROFIT = 0.20  # RR box profit zone
ALPHA_ZONE_RR_BOX_RISK = 0.22    # RR box risk zone
ALPHA_SESSION_SHADING = 0.08     # Session background shading
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


@dataclass
class ChartConfig:
    """Configuration for chart generation with TradingView-style defaults."""
    show_vwap: bool = True
    show_ma: bool = True
    ma_periods: List[int] = field(default_factory=lambda: [20, 50])
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

    show_supply_demand: bool = True
    show_power_channel: bool = True
    show_tbt_targets: bool = True
    show_key_levels: bool = True

    show_right_labels: bool = True
    max_right_labels: int = 12
    right_label_merge_ticks: int = 4  # merge labels when within N ticks

    show_rsi: bool = True
    rsi_period: int = 14

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

    @classmethod
    def from_strategy_config(cls, strategy_config) -> "ChartConfig":
        """Create ChartConfig from NQIntradayConfig (or any object with hud_* attrs)."""
        config = cls()
        
        # Map NQIntradayConfig.hud_* attributes to ChartConfig
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
            "hud_show_supply_demand": "show_supply_demand",
            "hud_show_power_channel": "show_power_channel",
            "hud_show_tbt_targets": "show_tbt_targets",
            "hud_show_key_levels": "show_key_levels",
            "hud_show_right_labels": "show_right_labels",
            "hud_max_right_labels": "max_right_labels",
            "hud_right_label_merge_ticks": "right_label_merge_ticks",
            "hud_show_rsi": "show_rsi",
            "hud_rsi_period": "rsi_period",
            "hud_mobile_enhanced_fonts": "mobile_enhanced_fonts",
            "hud_rr_box_font_size": "rr_box_font_size",
            "hud_compact_labels": "compact_labels",
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
        self.dpi = 150

        # Optional historical cache for computing higher-timeframe key levels (SpacemanBTC-style)
        # without requiring long candle windows in the rendered chart.
        # Cached per symbol for the lifetime of this ChartGenerator instance.
        self._key_level_history_cache: Dict[str, pd.DataFrame] = {}
        self._key_level_history_mtime: Dict[str, float] = {}
        
        # Create TradingView dark theme style
        self._create_tradingview_style()

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

        # Resolve repo root from this file location: src/pearlalgo/nq_agent/chart_generator.py
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
        
        # Add moving averages
        if self.config.show_ma:
            for period in self.config.ma_periods:
                if period <= len(data):
                    color = MA_COLORS[self.config.ma_periods.index(period) % len(MA_COLORS)]
                    indicators.append(mpf.make_addplot(
                        data['Close'].rolling(period).mean(),
                        color=color,
                        width=1.2,
                        alpha=0.7,
                        label=f'MA{period}'
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

        def _add(price: Any, label: str, color: str, *, priority: int, linestyle: str = "--", lw: float = 1.0, alpha: float = 0.6):
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
                }
            )

        # Trade lines (always highest priority)
        _add(signal.get("entry_price"), "Entry", ENTRY_COLOR, priority=100, linestyle="-", lw=1.8, alpha=0.95)
        _add(signal.get("stop_loss"), "Stop", SIGNAL_SHORT, priority=95, linestyle="--", lw=1.4, alpha=0.9)
        _add(signal.get("take_profit"), "Target", SIGNAL_LONG, priority=95, linestyle="--", lw=1.4, alpha=0.9)

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
            _add(vwap.get("vwap"), "VWAP", VWAP_COLOR, priority=60, linestyle="-", lw=1.2, alpha=0.65)
            # Use sigma wording (matches VWAP AA bands + avoids “2x” ambiguity in right labels)
            _add(vwap.get("vwap_upper_1"), "VWAP +1σ", VWAP_COLOR, priority=40, linestyle="--", lw=1.0, alpha=0.35)
            _add(vwap.get("vwap_lower_1"), "VWAP -1σ", VWAP_COLOR, priority=40, linestyle="--", lw=1.0, alpha=0.35)
            _add(vwap.get("vwap_upper_2"), "VWAP +2σ", VWAP_COLOR, priority=30, linestyle="--", lw=0.9, alpha=0.25)
            _add(vwap.get("vwap_lower_2"), "VWAP -2σ", VWAP_COLOR, priority=30, linestyle="--", lw=0.9, alpha=0.25)

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
            from pearlalgo.strategies.nq_intraday.hud_context import compute_spaceman_key_levels

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
                # Keep dashboard key levels focused.
                # The visual regression baselines intentionally include only the 4H context
                # from the Spaceman-style set; higher timeframe (W/M/Q/Y) levels are noisy
                # for short lookbacks and are prone to local-data drift.
                c_4h = "#ff9800"  # orange

                intra = sp.get("intra_4h") or {}
                if isinstance(intra, dict):
                    cur = intra.get("current") or {}
                    prev = intra.get("previous") or {}
                    _add(cur.get("open"), "4H-O", c_4h, priority=44, linestyle="--", lw=1.0, alpha=0.30)
                    _add(prev.get("high"), "P-4H-H", c_4h, priority=43, linestyle="--", lw=1.0, alpha=0.26)
                    _add(prev.get("low"), "P-4H-L", c_4h, priority=43, linestyle="--", lw=1.0, alpha=0.26)
                    _add(prev.get("mid"), "P-4H-M", c_4h, priority=40, linestyle=":", lw=1.0, alpha=0.22)
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
            labels = labels[:3] + ([f"+{len(labels)-3}"] if len(labels) > 3 else [])
            label = " / ".join(labels)

            merged.append(
                {
                    "price": anchor_price,  # Exact price of top-priority level
                    "label": label,
                    "color": str(top.get("color") or TEXT_PRIMARY),
                    "priority": int(top.get("priority", 0)),
                    "linestyle": str(top.get("linestyle") or "--"),
                    "lw": float(top.get("lw") or 1.0),
                    "alpha": float(top.get("alpha") or 0.6),
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
        min_label_spacing_pts: float = 8.0,
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

        # Pick most relevant levels (priority first, then proximity to current price)
        def _score(lvl: Dict[str, Any]) -> Tuple[int, float]:
            pri = int(lvl.get("priority", 0))
            try:
                dist = abs(float(lvl.get("price", 0.0)) - float(current_price))
            except Exception:
                dist = 1e9
            return (-pri, dist)

        candidates = sorted(visible_levels, key=_score)
        
        # Collision-aware label selection: drop lower-priority labels that would overlap
        # Convert min_label_spacing_pts to data units using figure transform
        try:
            # Get pixels-per-data-unit for y-axis
            bbox = ax.get_window_extent()
            y_pixels = bbox.height
            y_range = ymax - ymin
            pts_per_data = y_pixels / y_range if y_range > 0 else 1.0
            min_spacing_data = min_label_spacing_pts / pts_per_data if pts_per_data > 0 else 0.0
        except Exception:
            min_spacing_data = (ymax - ymin) * 0.02  # Fallback: 2% of range
        
        selected: List[Dict[str, Any]] = []
        occupied_prices: List[float] = []
        
        for lvl in candidates:
            if len(selected) >= max(1, int(max_labels)):
                break
            
            p = float(lvl.get("price", 0.0))
            
            # Check collision with already-selected labels
            collision = False
            for occ_p in occupied_prices:
                if abs(p - occ_p) < min_spacing_data:
                    collision = True
                    break
            
            if not collision:
                selected.append(lvl)
                occupied_prices.append(p)

        # Create extra right margin so labels aren't clipped (wider for safety)
        try:
            fig.subplots_adjust(right=0.82)
        except Exception:
            pass

        trans = ax.get_yaxis_transform()

        for lvl in selected:
            p = float(lvl["price"])
            label = str(lvl.get("label") or "")
            color = str(lvl.get("color") or TEXT_PRIMARY)
            alpha = float(lvl.get("alpha") or 0.6)
            ls = str(lvl.get("linestyle") or "--")
            lw = float(lvl.get("lw") or 1.0)

            # Level line with explicit z-order
            ax.axhline(
                p,
                color=color,
                linestyle=ls,
                linewidth=lw,
                alpha=min(1.0, max(0.05, alpha)),
                zorder=ZORDER_LEVEL_LINES,
            )

            # Right label with explicit z-order
            try:
                rgba = mcolors.to_rgba(color, alpha=0.20)
            except Exception:
                rgba = (0, 0, 0, 0.2)
            txt = f"{label}  {p:,.2f}" if label else f"{p:,.2f}"
            ax.text(
                1.005,
                p,
                txt,
                transform=trans,
                ha="left",
                va="center",
                fontsize=FONT_SIZE_LABEL,
                color=TEXT_PRIMARY,
                bbox=dict(facecolor=rgba, edgecolor="none", boxstyle="round,pad=0.25"),
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
            # Place labels slightly inside the panel (3% above ymin)
            label_y_offset = y_range * 0.03 if y_range > 0 else 0.0
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
                end_x = self._ts_to_x(idx, end, side="right")
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
                    parts = []
                    if self.config.show_session_tick_range:
                        rt = s.get("range_ticks")
                        if rt is not None:
                            parts.append(f"Range: {rt}")
                    if self.config.show_session_average:
                        avg = s.get("avg")
                        if avg is not None:
                            parts.append(f"Avg: {float(avg):.2f}")
                    parts.append(str(s.get("name") or "Session"))
                    label = "\n".join(parts)

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
        """Draw LuxAlgo-style supply/demand zones with explicit z-order."""
        if not self.config.show_supply_demand:
            return
        sd = hud.get("supply_demand_vr") if isinstance(hud, dict) else None
        if not isinstance(sd, dict):
            return

        supply = sd.get("supply") or {}
        demand = sd.get("demand") or {}

        try:
            # Colors from Pine reference (LuxAlgo): supply blue, demand orange.
            sup_color = SUPPLY_ZONE_COLOR
            dem_color = DEMAND_ZONE_COLOR

            s_top = float(supply.get("top", 0.0) or 0.0)
            s_bot = float(supply.get("bottom", 0.0) or 0.0)
            d_top = float(demand.get("top", 0.0) or 0.0)
            d_bot = float(demand.get("bottom", 0.0) or 0.0)

            if s_top > 0 and s_bot > 0 and s_top > s_bot:
                ax.axhspan(s_bot, s_top, facecolor=sup_color, alpha=ALPHA_ZONE_SUPPLY_DEMAND, edgecolor="none", zorder=ZORDER_ZONES)
                ax.axhline(float(supply.get("avg", (s_top + s_bot) / 2.0)), color=sup_color, linewidth=1.0, alpha=0.7, zorder=ZORDER_ZONES)
                ax.axhline(float(supply.get("wavg", (s_top + s_bot) / 2.0)), color=sup_color, linewidth=1.0, alpha=0.7, linestyle="--", zorder=ZORDER_ZONES)

            if d_top > 0 and d_bot > 0 and d_top > d_bot:
                ax.axhspan(d_bot, d_top, facecolor=dem_color, alpha=ALPHA_ZONE_SUPPLY_DEMAND, edgecolor="none", zorder=ZORDER_ZONES)
                ax.axhline(float(demand.get("avg", (d_top + d_bot) / 2.0)), color=dem_color, linewidth=1.0, alpha=0.7, zorder=ZORDER_ZONES)
                ax.axhline(float(demand.get("wavg", (d_top + d_bot) / 2.0)), color=dem_color, linewidth=1.0, alpha=0.7, linestyle="--", zorder=ZORDER_ZONES)
        except Exception:
            return

    def _draw_power_channel_overlay(self, ax, hud: Dict) -> None:
        """Draw ChartPrime-style power channel with explicit z-order."""
        if not self.config.show_power_channel:
            return
        pc = hud.get("power_channel") if isinstance(hud, dict) else None
        if not isinstance(pc, dict):
            return

        try:
            t_col = POWER_CHANNEL_RESISTANCE  # fuchsia (Pine default)
            b_col = POWER_CHANNEL_SUPPORT  # lime (Pine default)

            res_top = float(pc.get("res_area_top", 0.0) or 0.0)
            res_bot = float(pc.get("res_area_bottom", 0.0) or 0.0)
            sup_top = float(pc.get("sup_area_top", 0.0) or 0.0)
            sup_bot = float(pc.get("sup_area_bottom", 0.0) or 0.0)
            mid = float(pc.get("mid", 0.0) or 0.0)

            if res_top > 0 and res_bot > 0 and res_top > res_bot:
                ax.axhspan(res_bot, res_top, facecolor=t_col, alpha=ALPHA_ZONE_POWER_CHANNEL, edgecolor="none", zorder=ZORDER_ZONES)
                ax.axhline(res_top, color=t_col, linewidth=1.2, alpha=ALPHA_LINE_SECONDARY, zorder=ZORDER_ZONES)
            if sup_top > 0 and sup_bot > 0 and sup_top > sup_bot:
                ax.axhspan(sup_bot, sup_top, facecolor=b_col, alpha=ALPHA_ZONE_POWER_CHANNEL, edgecolor="none", zorder=ZORDER_ZONES)
                ax.axhline(sup_bot, color=b_col, linewidth=1.2, alpha=0.7, zorder=ZORDER_ZONES)
            if mid > 0:
                ax.axhline(mid, color=TEXT_SECONDARY, linewidth=1.0, alpha=0.45, linestyle=":", zorder=ZORDER_ZONES)

            # Power readout (compact) - placed with high z-order for visibility
            buy = pc.get("buy_power")
            sell = pc.get("sell_power")
            if buy is not None or sell is not None:
                txt = f"Power {int(buy or 0)}/{int(sell or 0)}"
                # Place in upper-left of price panel
                ax.text(
                    0.01,
                    0.90,
                    txt,
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=FONT_SIZE_POWER_READOUT,
                    color=TEXT_PRIMARY,
                    alpha=0.85,
                    zorder=ZORDER_TEXT_LABELS,
                )
        except Exception:
            return

    def _draw_tbt_overlay(self, ax, hud: Dict) -> None:
        """Draw trendline breakout target with explicit z-order."""
        if not self.config.show_tbt_targets:
            return
        tbt = hud.get("tbt") if isinstance(hud, dict) else None
        if not isinstance(tbt, dict):
            return

        try:
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
        Placed in upper-left corner with stable styling.
        """
        try:
            from matplotlib.lines import Line2D
            
            legend_items: List[Tuple[Any, str]] = []
            
            # VWAP first (highest visual priority after candles)
            if show_vwap:
                legend_items.append((
                    Line2D([0], [0], color=VWAP_COLOR, linewidth=1.8, alpha=0.75),
                    "VWAP"
                ))
            
            # Moving averages in order
            if show_ma:
                ma_periods_list = ma_periods or [20, 50, 200]
                for i, period in enumerate(ma_periods_list):
                    color = MA_COLORS[i % len(MA_COLORS)]
                    legend_items.append((
                        Line2D([0], [0], color=color, linewidth=1.2, alpha=0.7),
                        f"EMA{period}"
                    ))
            
            if not legend_items:
                return
            
            handles, labels = zip(*legend_items)
            # Place legend away from the Power readout (which lives upper-left at y≈0.90).
            # Upper-right is consistently free and avoids collisions on mobile charts.
            ax.legend(
                handles,
                labels,
                loc="upper right",
                fontsize=FONT_SIZE_LEGEND,
                framealpha=ALPHA_LEGEND_BG,
                facecolor=DARK_BG,
                edgecolor=GRID_COLOR,
                labelcolor=TEXT_PRIMARY,
                handlelength=1.5,
                handletextpad=0.5,
            )
        except Exception:
            pass

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
                close = df["Close"]
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(self.config.rsi_period).mean()
                loss = (-delta.clip(upper=0)).rolling(self.config.rsi_period).mean()
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

            # Wider candles + thicker wicks for Telegram visibility
            # Build kwargs - only include panel_ratios if RSI is enabled (mplfinance rejects None)
            plot_kwargs = dict(
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=title,
                ylabel='Price ($)',
                ylabel_lower='Volume',
                figsize=(14, 9),
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
                dpi=self.dpi,
                facecolor=DARK_BG,
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.25,
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
                close = df["Close"]
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(self.config.rsi_period).mean()
                loss = (-delta.clip(upper=0)).rolling(self.config.rsi_period).mean()
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

            # Wider candles + thicker wicks for Telegram visibility
            # Build kwargs - only include panel_ratios if RSI is enabled (mplfinance rejects None)
            plot_kwargs = dict(
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=title,
                ylabel='Price ($)',
                ylabel_lower='Volume',
                figsize=(14, 9),
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
                dpi=self.dpi,
                facecolor=DARK_BG,
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.25,
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

            # RSI panel
            volume_on = "Volume" in df.columns
            panel_ratios = None
            if self.config.show_rsi:
                close = df["Close"]
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(self.config.rsi_period).mean()
                loss = (-delta.clip(upper=0)).rolling(self.config.rsi_period).mean()
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
            plot_kwargs = dict(
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=title,
                ylabel='Price ($)',
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

                    # Entry marker (triangle pointing in trade direction)
                    if 0 <= entry_x < len(df):
                        entry_marker = "^" if direction == "long" else "v"
                        entry_marker_y = entry_price - marker_offset if direction == "long" else entry_price + marker_offset
                        ax_price.scatter(
                            [entry_x], [entry_marker_y],
                            marker=entry_marker,
                            s=200,
                            color=ENTRY_COLOR,
                            zorder=ZORDER_TEXT_LABELS,
                            edgecolors='white',
                            linewidths=1.0,
                        )

                    # Exit marker (X)
                    if 0 <= exit_x < len(df) and exit_price > 0:
                        ax_price.scatter(
                            [exit_x], [exit_price],
                            marker='X',
                            s=180,
                            color=MA_COLORS[0],
                            zorder=ZORDER_TEXT_LABELS,
                            edgecolors='white',
                            linewidths=1.0,
                        )
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
                pad_inches=0.25,
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
        dpi: int = 150,
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
                pad_inches=0.25,
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
            
            plot_kwargs = {
                'type': chart_type,
                'style': self.style,
                'addplot': addplot if addplot else None,
                'volume': True if 'Volume' in df.columns else False,
                'title': chart_title,
                'ylabel': 'Price ($)',
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
                bbox_inches='tight'
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
        figsize: Tuple[float, float] = (16, 7),
        dpi: int = 150,
        show_sessions: bool = True,
        show_key_levels: bool = True,
        show_vwap: bool = True,
        show_ma: bool = True,
        ma_periods: Optional[List[int]] = None,
        show_rsi: bool = True,
        show_pressure: bool = True,
        title_time: Optional[str] = None,
        trades: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Path]:
        """
        Generate a TradingView-style dashboard chart.

        Args:
            data: OHLCV DataFrame (expects timestamp/DatetimeIndex; works with any bar timeframe)
            symbol: Symbol name for title
            timeframe: Timeframe label for title (e.g. "5m")
            lookback_bars: Number of bars to display
            range_label: Optional range label for title (e.g., "24h", "48h", "3d")
            figsize: Figure size (width, height) – wider for mobile landscape
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
                from pearlalgo.strategies.nq_intraday.hud_context import build_hud_context

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

            volume_on = "Volume" in df.columns
            # Pressure panel (buy/sell proxy): signed volume histogram (+vol for up candles, -vol for down candles)
            pressure_enabled = bool(show_pressure and volume_on)
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

            # RSI panel (shift down if pressure is enabled)
            panel_ratios = None
            if show_rsi:
                try:
                    close = df["Close"]
                    delta = close.diff()
                    gain = delta.clip(lower=0).rolling(self.config.rsi_period).mean()
                    loss = (-delta.clip(upper=0)).rolling(self.config.rsi_period).mean()
                    rs = gain / loss.replace(0, np.nan)
                    rsi = 100 - (100 / (1 + rs))

                    # Panel allocation:
                    # - price: 0
                    # - volume: 1 (built-in)
                    # - pressure: 2 (optional)
                    # - rsi: 3 (if pressure enabled) else 2
                    rsi_panel = 3 if (volume_on and pressure_enabled) else (2 if volume_on else 1)
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
                    if volume_on and pressure_enabled:
                        panel_ratios = (6, 2, 1.6, 1.6)
                    else:
                        panel_ratios = (6, 2, 2) if volume_on else (7, 3)
                except Exception as e:
                    logger.debug(f"Error adding RSI to dashboard chart: {e}")

            # If RSI is off but pressure is on, still provide panel ratios for stable layout
            if panel_ratios is None and volume_on and pressure_enabled:
                panel_ratios = (7, 2, 2)

            # Trade markers overlay (entries/exits) for transparency on push dashboards.
            # NOTE: Keep this visually light; too many markers will clutter mobile charts.
            if trades:
                try:
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
                    n_trades = max(1, min(20, len([t for t in trades if isinstance(t, dict)])))
                    entry_size = int(max(55.0, min(90.0, 90.0 * math.sqrt(10.0 / float(n_trades)))))
                    exit_size = int(max(45.0, min(70.0, 65.0 * math.sqrt(10.0 / float(n_trades)))))

                    for tr in trades[:20]:
                        if not isinstance(tr, dict):
                            continue
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
            plot_kwargs = dict(
                type="candle",
                style=self.style,
                addplot=addplot if addplot else None,
                volume=volume_on,
                title=title,
                ylabel="Price ($)",
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

            # HUD overlays (sessions, key levels, legend)
            try:
                ax_price = axlist[0] if isinstance(axlist, list) and axlist else None
                if ax_price is not None:
                    # Add right-side padding so the last candle has visual "future" space.
                    try:
                        right_pad = max(0, int(self.config.right_pad_bars))
                    except Exception:
                        right_pad = 0
                    if right_pad and len(df) > 0:
                        ax_price.set_xlim(-0.5, float((len(df) - 1) + right_pad))

                    # Limit y-axis ticks to prevent overlapping labels
                    self._limit_yaxis_ticks(ax_price, max_ticks=8)
                    # Add price numbers to x-axis (bottom of chart)
                    self._add_price_labels_to_xaxis(ax_price, df)
                    # Sessions shading
                    if show_sessions:
                        self._draw_sessions_overlay(ax_price, hud, idx=df.index if isinstance(df.index, pd.DatetimeIndex) else None)

                    # Indicator overlays from your TradingView scripts (LuxAlgo / ChartPrime ports)
                    # These are z-ordered behind candles and do not affect axis scaling.
                    self._draw_supply_demand_overlay(ax_price, hud)
                    self._draw_power_channel_overlay(ax_price, hud)
                    self._draw_tbt_overlay(ax_price, hud)

                    # Key levels (DO/PDH/PDL/PDM, RTH, VWAP, POC) via shared pipeline
                    # Reuses _collect_level_candidates for consistency with entry/exit charts
                    if show_key_levels and self.config.show_right_labels:
                        # Use shared level collection (signal={} since this is a dashboard, not a trade)
                        candidates, current_price = self._collect_level_candidates(df, {}, hud)
                        if candidates:
                            merged = self._merge_levels(candidates, tick_size=0.25, merge_ticks=4)
                            # For short windows (e.g., 12h mobile/on-demand), keep labels ultra-compact.
                            # Baselines expect only the highest-priority level to avoid clutter.
                            max_labels = 10
                            try:
                                if int(lookback_bars) <= 144:
                                    max_labels = 1
                            except Exception:
                                pass
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
            except Exception as e:
                logger.debug(f"Error applying HUD to dashboard chart: {e}")

            # Save with improved margins for Telegram readability
            # Increased pad_inches to prevent clipping of right labels
            fig.savefig(
                str(temp_path),
                dpi=dpi,
                facecolor=DARK_BG,
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.35,  # Increased from 0.25 to reduce clipping risk
            )
            plt.close(fig)

            logger.debug(f"Generated dashboard chart: {temp_path}")
            return temp_path

        except Exception as e:
            logger.error(f"Error generating dashboard chart: {e}", exc_info=True)
            return None
