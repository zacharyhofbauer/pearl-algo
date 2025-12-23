"""
Chart Generator for NQ Agent using mplfinance.

Generates professional trading charts with entry, stop loss, and take profit levels.
This is the production chart generator using mplfinance library.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

import matplotlib.pyplot as plt
from matplotlib import colors as mcolors

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

# Z-order constants for layering (lower = further back)
ZORDER_SESSION_SHADING = 0
ZORDER_ZONES = 1
ZORDER_LEVEL_LINES = 2
ZORDER_CANDLES = 3  # mplfinance default
ZORDER_TEXT_LABELS = 4


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
        
        # Create TradingView dark theme style
        self._create_tradingview_style()
    
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
            _add(vwap.get("vwap_upper_1"), "VWAP+1", VWAP_COLOR, priority=40, linestyle="--", lw=1.0, alpha=0.35)
            _add(vwap.get("vwap_lower_1"), "VWAP-1", VWAP_COLOR, priority=40, linestyle="--", lw=1.0, alpha=0.35)
            _add(vwap.get("vwap_upper_2"), "VWAP+2", VWAP_COLOR, priority=30, linestyle="--", lw=0.9, alpha=0.25)
            _add(vwap.get("vwap_lower_2"), "VWAP-2", VWAP_COLOR, priority=30, linestyle="--", lw=0.9, alpha=0.25)

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
                fontsize=9,
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
                        fontsize=8,
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
            sup_color = "#2157f3"
            dem_color = "#ff5d00"

            s_top = float(supply.get("top", 0.0) or 0.0)
            s_bot = float(supply.get("bottom", 0.0) or 0.0)
            d_top = float(demand.get("top", 0.0) or 0.0)
            d_bot = float(demand.get("bottom", 0.0) or 0.0)

            if s_top > 0 and s_bot > 0 and s_top > s_bot:
                ax.axhspan(s_bot, s_top, facecolor=sup_color, alpha=0.18, edgecolor="none", zorder=ZORDER_ZONES)
                ax.axhline(float(supply.get("avg", (s_top + s_bot) / 2.0)), color=sup_color, linewidth=1.0, alpha=0.7, zorder=ZORDER_ZONES)
                ax.axhline(float(supply.get("wavg", (s_top + s_bot) / 2.0)), color=sup_color, linewidth=1.0, alpha=0.7, linestyle="--", zorder=ZORDER_ZONES)

            if d_top > 0 and d_bot > 0 and d_top > d_bot:
                ax.axhspan(d_bot, d_top, facecolor=dem_color, alpha=0.18, edgecolor="none", zorder=ZORDER_ZONES)
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
            t_col = "#ff00ff"  # fuchsia (Pine default)
            b_col = "#00ff00"  # lime (Pine default)

            res_top = float(pc.get("res_area_top", 0.0) or 0.0)
            res_bot = float(pc.get("res_area_bottom", 0.0) or 0.0)
            sup_top = float(pc.get("sup_area_top", 0.0) or 0.0)
            sup_bot = float(pc.get("sup_area_bottom", 0.0) or 0.0)
            mid = float(pc.get("mid", 0.0) or 0.0)

            if res_top > 0 and res_bot > 0 and res_top > res_bot:
                ax.axhspan(res_bot, res_top, facecolor=t_col, alpha=0.10, edgecolor="none", zorder=ZORDER_ZONES)
                ax.axhline(res_top, color=t_col, linewidth=1.2, alpha=0.7, zorder=ZORDER_ZONES)
            if sup_top > 0 and sup_bot > 0 and sup_top > sup_bot:
                ax.axhspan(sup_bot, sup_top, facecolor=b_col, alpha=0.10, edgecolor="none", zorder=ZORDER_ZONES)
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
                    fontsize=10,
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
                fontsize=9,
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
        
        Fixed order: VWAP, MA20, MA50, MA200 (or configured periods).
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
                        f"MA{period}"
                    ))
            
            if not legend_items:
                return
            
            handles, labels = zip(*legend_items)
            ax.legend(
                handles,
                labels,
                loc="upper left",
                fontsize=8,
                framealpha=0.6,
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
        x_mid = x_start + (x_end - x_start) / 2
        ax.text(
            x_mid,
            (reward_y0 + reward_y1) / 2,
            f"+{reward_usd:.0f} USD\nR:R {rr:.2f}",
            ha="center",
            va="center",
            fontsize=9,
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
            fontsize=9,
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
            merged = self._merge_levels(candidates, tick_size=tick_size, merge_ticks=int(self.config.right_label_merge_ticks))
            self._draw_right_labels(
                fig,
                ax_price,
                merged,
                current_price=current_price,
                max_labels=int(self.config.max_right_labels),
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
            tf_label = timeframe or self.config.timeframe
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
                    self._apply_hud(fig, ax_price, df, signal, direction)
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
            tf_label = timeframe or self.config.timeframe
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
    
    def generate_backtest_chart(
        self,
        backtest_data: pd.DataFrame,
        signals: List[Dict],
        symbol: str = "MNQ",
        title: str = "Backtest Results",
        performance_data: Optional[Dict] = None,
        timeframe: Optional[str] = None,
    ) -> Optional[Path]:
        """Generate backtest chart using mplfinance."""
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

                    long_y = pd.Series(np.nan, index=df.index)
                    short_y = pd.Series(np.nan, index=df.index)

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
                        if direction == "long":
                            # Plot just below candle low
                            low_val = float(df["Low"].iloc[pos])
                            long_y.iloc[pos] = low_val * 0.999
                        else:
                            high_val = float(df["High"].iloc[pos])
                            short_y.iloc[pos] = high_val * 1.001

                    if not long_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                long_y,
                                type="scatter",
                                marker="^",
                                markersize=self.config.signal_marker_size,
                                color=SIGNAL_LONG,
                            )
                        )
                    if not short_y.isna().all():
                        addplot.append(
                            mpf.make_addplot(
                                short_y,
                                type="scatter",
                                marker="v",
                                markersize=self.config.signal_marker_size,
                                color=SIGNAL_SHORT,
                            )
                        )
            except Exception as e:
                logger.debug(f"Error adding signal markers: {e}")
            
            # Create title
            tf_label = timeframe or self.config.timeframe
            chart_title = f"{title} - Candlestick Chart with Signal Markers ({tf_label})"
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Plot with mplfinance (wider candles, suppress too-much-data warning)
            mpf.plot(
                df,
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=True if 'Volume' in df.columns else False,
                title=chart_title,
                ylabel='Price ($)',
                ylabel_lower='Volume',
                figsize=(14, 9),
                savefig=dict(
                    fname=str(temp_path),
                    dpi=self.dpi,
                    facecolor=DARK_BG,
                    edgecolor='none',
                    bbox_inches='tight'
                ),
                show_nontrading=False,
                tight_layout=True,
                returnfig=False,
                scale_width_adjustment=dict(candle=1.4, volume=0.8, lines=1.0),
                update_width_config=dict(candle_linewidth=1.2, candle_width=0.7),
                warn_too_much_data=5000,
            )
            
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
    ) -> Optional[Path]:
        """
        Generate a TradingView-style dashboard chart.

        Args:
            data: OHLCV DataFrame (expects 5m bars with timestamp/DatetimeIndex)
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

            # Limit to lookback_bars (default 288 = 24h of 5m)
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

            # Moving Averages (to match TradingView-style chart)
            if show_ma:
                ma_periods_list = ma_periods or [20, 50, 200]  # Common MA periods
                for period in ma_periods_list:
                    if period <= len(df):
                        color_idx = ma_periods_list.index(period) % len(MA_COLORS)
                        color = MA_COLORS[color_idx]
                        ma_series = df["Close"].rolling(period).mean()
                        addplot.append(
                            mpf.make_addplot(
                                ma_series,
                                color=color,
                                width=1.2,
                                alpha=0.7,
                                label=f"MA{period}",
                            )
                        )

            # VWAP
            if show_vwap:
                try:
                    from pearlalgo.utils.vwap import VWAPCalculator

                    vwap_calc = VWAPCalculator()
                    vwap_df = df.reset_index().copy()
                    vwap_df = vwap_df.rename(columns={
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                    })
                    if "Volume" in vwap_df.columns:
                        vwap_df = vwap_df.rename(columns={"Volume": "volume"})
                    vwap_data = vwap_calc.calculate_vwap(vwap_df)
                    vwap_val = vwap_data.get("vwap", 0)
                    if vwap_val and vwap_val > 0:
                        vwap_series = pd.Series([float(vwap_val)] * len(df), index=df.index)
                        addplot.append(
                            mpf.make_addplot(
                                vwap_series,
                                color=VWAP_COLOR,
                                width=1.8,
                                alpha=0.75,
                                label="VWAP",
                            )
                        )
                        # VWAP bands
                        for key, alpha in (("vwap_upper_1", 0.35), ("vwap_lower_1", 0.35)):
                            band = vwap_data.get(key, 0)
                            if band and float(band) > 0 and float(band) != float(vwap_val):
                                band_series = pd.Series([float(band)] * len(df), index=df.index)
                                addplot.append(
                                    mpf.make_addplot(
                                        band_series,
                                        color=VWAP_COLOR,
                                        width=1.0,
                                        linestyle="--",
                                        alpha=alpha,
                                    )
                                )
                except Exception as e:
                    logger.debug(f"Error adding VWAP to dashboard chart: {e}")

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
                    # Sessions shading
                    if show_sessions:
                        self._draw_sessions_overlay(ax_price, hud, idx=df.index if isinstance(df.index, pd.DatetimeIndex) else None)

                    # Key levels (DO/PDH/PDL/PDM, RTH, VWAP, POC) via shared pipeline
                    # Reuses _collect_level_candidates for consistency with entry/exit charts
                    if show_key_levels and self.config.show_right_labels:
                        # Use shared level collection (signal={} since this is a dashboard, not a trade)
                        candidates, current_price = self._collect_level_candidates(df, {}, hud)
                        if candidates:
                            merged = self._merge_levels(candidates, tick_size=0.25, merge_ticks=4)
                            self._draw_right_labels(fig, ax_price, merged, current_price=current_price, max_labels=10)
                    
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
