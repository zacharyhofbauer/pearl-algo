"""
Alternative Chart Generator using mplfinance for TradingView-style charts.

mplfinance is specifically designed for financial charts and handles
candlestick rendering, spacing, and styling much better than raw matplotlib.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

import pandas as pd
import numpy as np
from datetime import datetime, timezone

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
VWAP_COLOR = "#ffa726"
MA_COLORS = ['#2196f3', '#9c27b0', '#f44336']


@dataclass
class MplfinanceChartConfig:
    """Configuration for mplfinance chart generation."""
    show_vwap: bool = True
    show_ma: bool = True
    ma_periods: List[int] = field(default_factory=lambda: [20, 50])
    signal_marker_size: int = 300
    max_signals_displayed: int = 50
    cluster_signals: bool = True
    show_performance_metrics: bool = True
    timeframe: str = "1m"
    show_entry_sl_tp_bands: bool = True
    candle_width: float = 0.8  # mplfinance uses 0.8 as default (80% of interval)


class MplfinanceChartGenerator:
    """Generates TradingView-style charts using mplfinance."""
    
    def __init__(self, config: Optional[MplfinanceChartConfig] = None):
        """Initialize mplfinance chart generator.
        
        Args:
            config: Chart configuration (optional, uses defaults if not provided)
        """
        if not MPLFINANCE_AVAILABLE:
            raise ImportError("mplfinance required. Install with: pip install mplfinance")
        
        self.config = config or MplfinanceChartConfig()
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
                vwap_data = vwap_calc.calculate_vwap(data.reset_index())
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
        """Add Entry/SL/TP horizontal lines and shaded bands."""
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
        
        # Add shaded bands if enabled
        if self.config.show_entry_sl_tp_bands:
            # Stop-loss zone
            if stop_loss and stop_loss > 0:
                if direction == 'long':
                    # Long: stop below entry
                    sl_zone_top = entry_price
                    sl_zone_bottom = stop_loss
                else:
                    # Short: stop above entry
                    sl_zone_top = stop_loss
                    sl_zone_bottom = entry_price
                
                sl_zone = pd.Series([sl_zone_top] * len(data), index=data.index)
                sl_zone_bottom_series = pd.Series([sl_zone_bottom] * len(data), index=data.index)
                # Use fill_between via addplot (requires custom approach)
                # For now, we'll add as a line and handle shading separately if needed
            
            # Take-profit zone
            if take_profit and take_profit > 0:
                if direction == 'long':
                    # Long: TP above entry
                    tp_zone_bottom = entry_price
                    tp_zone_top = take_profit
                else:
                    # Short: TP below entry
                    tp_zone_bottom = take_profit
                    tp_zone_top = entry_price
        
        return lines
    
    def _add_signal_markers(self, data: pd.DataFrame, signals: List[Dict]) -> List:
        """Add signal markers to chart."""
        markers = []
        
        if not signals:
            return markers
        
        # Limit signals
        signals_to_plot = signals[:self.config.max_signals_displayed] if len(signals) > self.config.max_signals_displayed else signals
        
        # Prepare marker data
        marker_prices = []
        marker_colors = []
        marker_shapes = []
        marker_indices = []
        
        for signal in signals_to_plot:
            entry_price = signal.get("entry_price", 0)
            direction = signal.get("direction", "long").lower()
            
            if entry_price <= 0:
                continue
            
            # Find closest timestamp/index
            signal_time = signal.get("timestamp")
            if signal_time:
                try:
                    signal_time = pd.to_datetime(signal_time)
                    # Find closest index
                    time_diffs = abs(data.index - signal_time)
                    closest_idx = time_diffs.argmin()
                    if time_diffs.iloc[closest_idx] < pd.Timedelta(minutes=5):
                        marker_indices.append(closest_idx)
                        marker_prices.append(entry_price)
                        marker_colors.append(SIGNAL_LONG if direction == 'long' else SIGNAL_SHORT)
                        marker_shapes.append('^' if direction == 'long' else 'v')
                except:
                    pass
        
        if marker_indices:
            # Create marker series
            marker_series = pd.Series(index=data.index, dtype=float)
            for idx, price in zip(marker_indices, marker_prices):
                marker_series.iloc[idx] = price
            
            # Add as scatter plot
            markers.append(mpf.make_addplot(
                marker_series,
                type='scatter',
                markersize=self.config.signal_marker_size,
                marker='^' if len([s for s in signals_to_plot if s.get('direction', '').lower() == 'long']) > 0 else 'v',
                color=SIGNAL_LONG,
                alpha=1.0
            ))
        
        return markers
    
    def generate_entry_chart(
        self,
        signal: Dict,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
        timeframe: str = "1m",
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
            
            # Create title
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            is_test = signal.get("reason", "").lower().startswith("test")
            title_prefix = "🧪 TEST: " if is_test else ""
            title = f"{title_prefix}{symbol} {direction.upper()} {signal_type} - Entry Chart ({timeframe})"
            
            # Generate metadata
            start_time = df.index[0].strftime('%H:%M') if len(df) > 0 else ""
            end_time = df.index[-1].strftime('%H:%M') if len(df) > 0 else ""
            metadata = f"{symbol} | {len(df)} bars | {timeframe} | {start_time} - {end_time}"
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Plot with mplfinance
            mpf.plot(
                df,
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=True if 'Volume' in df.columns else False,
                title=title,
                ylabel='Price ($)',
                ylabel_lower='Volume',
                figsize=(12, 8),
                savefig=dict(
                    fname=str(temp_path),
                    dpi=self.dpi,
                    facecolor=DARK_BG,
                    edgecolor='none',
                    bbox_inches='tight'
                ),
                show_nontrading=False,
                tight_layout=True,
                returnfig=False
            )
            
            logger.debug(f"Generated entry chart with mplfinance: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating entry chart with mplfinance: {e}", exc_info=True)
            return None
    
    def generate_backtest_chart(
        self,
        backtest_data: pd.DataFrame,
        signals: List[Dict],
        symbol: str = "MNQ",
        title: str = "Backtest Results",
        performance_data: Optional[Dict] = None,
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
            
            # Add signal markers (simplified - mplfinance handles this better)
            # For now, we'll add them as scatter points if needed
            
            # Create title
            timeframe = self.config.timeframe
            chart_title = f"{title} - Candlestick Chart with Signal Markers ({timeframe})"
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Plot with mplfinance
            mpf.plot(
                df,
                type='candle',
                style=self.style,
                addplot=addplot if addplot else None,
                volume=True if 'Volume' in df.columns else False,
                title=chart_title,
                ylabel='Price ($)',
                ylabel_lower='Volume',
                figsize=(12, 8),
                savefig=dict(
                    fname=str(temp_path),
                    dpi=self.dpi,
                    facecolor=DARK_BG,
                    edgecolor='none',
                    bbox_inches='tight'
                ),
                show_nontrading=False,
                tight_layout=True,
                returnfig=False
            )
            
            logger.debug(f"Generated backtest chart with mplfinance: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating backtest chart with mplfinance: {e}", exc_info=True)
            return None
