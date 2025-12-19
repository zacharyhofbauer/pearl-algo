"""
Chart Generator for NQ Agent

Generates professional trading charts with entry, stop loss, and take profit levels.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd
import numpy as np
from datetime import datetime, timezone

from pearlalgo.utils.logger import logger

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MultipleLocator
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("matplotlib not installed, chart generation disabled")


# TradingView-style color constants
DARK_BG = "#0e1013"  # TradingView dark theme background
GRID_COLOR = "#1e2127"  # Subtle grid and axis color
TEXT_PRIMARY = "#d1d4dc"  # Primary text color (white/light gray)
TEXT_SECONDARY = "#787b86"  # Secondary text color (muted gray)
CANDLE_UP = "#26a69a"  # Teal-green for bullish candles
CANDLE_DOWN = "#ef5350"  # Red for bearish candles
SIGNAL_LONG = "#26a69a"  # Green for long signals
SIGNAL_SHORT = "#ef5350"  # Red for short signals
ENTRY_COLOR = "#2962ff"  # Blue for entry lines
VWAP_COLOR = "#ffa726"  # Orange for VWAP
MA_COLORS = ['#2196f3', '#9c27b0', '#f44336']  # Blue, Purple, Red for MAs


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
    timeframe: str = "1m"
    signal_density_threshold: int = 3  # Signals per 10 bars to trigger clustering
    use_tradingview_style: bool = True  # Enable TradingView-style enhancements
    candle_width_fraction: float = 0.75  # 75% of interval (70-80% range)
    wick_linewidth: float = 1.0  # Thin wicks (~1px)
    volume_ma_period: int = 20  # Period for volume moving average
    show_entry_sl_tp_bands: bool = True  # Show shaded bands for entry/SL/TP
    use_mplfinance: bool = False  # Use mplfinance instead of matplotlib (recommended)


class ChartGenerator:
    """Generates trading charts for signals and trades.
    
    Can use either matplotlib (default) or mplfinance (recommended).
    Set config.use_mplfinance=True to use the mplfinance implementation.
    """
    
    def __init__(self, config: Optional[ChartConfig] = None):
        """Initialize chart generator.
        
        Args:
            config: Chart configuration (optional, uses defaults if not provided)
        """
        self.config = config or ChartConfig()
        
        # Check if mplfinance should be used
        if self.config.use_mplfinance:
            try:
                from pearlalgo.nq_agent.chart_generator_mplfinance import (
                    MplfinanceChartGenerator,
                    MplfinanceChartConfig
                )
                # Convert config
                mplf_config = MplfinanceChartConfig(
                    show_vwap=self.config.show_vwap,
                    show_ma=self.config.show_ma,
                    ma_periods=self.config.ma_periods,
                    signal_marker_size=self.config.signal_marker_size,
                    max_signals_displayed=self.config.max_signals_displayed,
                    cluster_signals=self.config.cluster_signals,
                    show_performance_metrics=self.config.show_performance_metrics,
                    timeframe=self.config.timeframe,
                    show_entry_sl_tp_bands=self.config.show_entry_sl_tp_bands,
                )
                self._mplf_generator = MplfinanceChartGenerator(mplf_config)
                self._use_mplfinance = True
                logger.info("Using mplfinance chart generator (recommended)")
                return
            except ImportError:
                logger.warning("mplfinance not available, falling back to matplotlib. Install with: pip install mplfinance")
                self._use_mplfinance = False
        else:
            self._use_mplfinance = False
        
        # Use matplotlib implementation
        if not MATPLOTLIB_AVAILABLE:
            raise ImportError("matplotlib required for chart generation")
        
        # Set style
        plt.style.use('dark_background')
        self.fig_size = (12, 8)
        self.dpi = 150  # Increased for Telegram quality
    
    def draw_candles(
        self,
        ax,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        x_indices: Optional[np.ndarray] = None,
    ) -> None:
        """
        Draw TradingView-correct candlesticks with explicit spacing.
        
        Uses categorical indices for x-axis to prevent diagonal banding and merged candles.
        Candles are rendered with explicit spacing (width=0.6) ensuring visible gaps.
        
        Args:
            ax: Matplotlib axes to draw on
            opens: Array of open prices
            highs: Array of high prices
            lows: Array of low prices
            closes: Array of close prices
            x_indices: Optional array of x positions (defaults to range(len(opens)))
        """
        # Convert to numpy arrays if needed
        opens = np.asarray(opens)
        highs = np.asarray(highs)
        lows = np.asarray(lows)
        closes = np.asarray(closes)
        
        # Use categorical indices if not provided
        if x_indices is None:
            x_indices = np.arange(len(opens))
        else:
            x_indices = np.asarray(x_indices)
        
        # CRITICAL: Disable datetime formatting BEFORE setting limits
        # This prevents matplotlib from trying to use datetime coordinates
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
        ax.xaxis.set_major_locator(plt.NullLocator())
        
        # Set x-axis limits to ensure proper spacing (categorical indices)
        ax.set_xlim(-1, len(opens))

        # Disable autoscaling to prevent matplotlib from changing our limits
        ax.set_autoscalex_on(False)

        # Candle width - TradingView style: 70-80% of interval (default 75%)
        candle_width = self.config.candle_width_fraction if hasattr(self, 'config') else 0.75

        # Draw each candlestick - TradingView style with proper filled rectangles
        # TradingView color logic: Teal-green (#26a69a) for bullish, Red (#ef5350) for bearish
        bullish_count = 0
        bearish_count = 0

        # Get wick linewidth from config
        wick_linewidth = self.config.wick_linewidth if hasattr(self, 'config') else 1.0

        for i, x in enumerate(x_indices):
            # Validate OHLC data
            if highs[i] < max(opens[i], closes[i]) or lows[i] > min(opens[i], closes[i]):
                logger.warning(f"Invalid OHLC at index {i}: High={highs[i]}, Low={lows[i]}, Open={opens[i]}, Close={closes[i]}")
                # Fix invalid data
                highs[i] = max(highs[i], opens[i], closes[i])
                lows[i] = min(lows[i], opens[i], closes[i])
            
            # Determine color based on close vs open (TradingView colors)
            is_bullish = closes[i] >= opens[i]
            if is_bullish:
                bullish_count += 1
            else:
                bearish_count += 1
            
            # TradingView colors: Teal-green for bullish, Red for bearish
            body_color = CANDLE_UP if is_bullish else CANDLE_DOWN
            wick_color = body_color  # Same color for wick
            
            # Calculate body dimensions
            body_bottom = min(opens[i], closes[i])
            body_top = max(opens[i], closes[i])
            body_height = abs(closes[i] - opens[i])
            
            # For doji (very small body), ensure minimum visibility
            if body_height < 0.5:
                min_body = max(0.5, (highs[i] - lows[i]) * 0.08)
                if body_height < min_body:
                    body_height = min_body
                    body_bottom = closes[i] - body_height / 2
                    body_top = closes[i] + body_height / 2
            
            # Draw full wick first (from low to high) - TradingView style with thin wicks
            ax.vlines(
                x,
                lows[i],
                highs[i],
                colors=wick_color,
                linewidths=wick_linewidth,  # Thin wicks (~1px)
                alpha=1.0,
                zorder=1
            )
            
            # Draw body using Rectangle - TradingView style: SOLID FILLED rectangles
            # Always draw body, even if very small (for doji)
            rect = Rectangle(
                (x - candle_width/2, body_bottom),
                candle_width,
                body_height,
                facecolor=body_color,
                edgecolor=body_color,  # Match face for solid fill (no border)
                alpha=1.0,
                linewidth=0,  # No edge line
                zorder=3  # Above wick
            )
            ax.add_patch(rect)
        
        # Log color distribution for debugging (only if significant data)
        if len(opens) > 10:
            logger.debug(f"Candle colors: {bullish_count} bullish (green), {bearish_count} bearish (red) out of {len(opens)} candles")
    
    def _apply_tradingview_styling(
        self,
        ax,
        timestamps: np.ndarray,
        x_indices: Optional[np.ndarray] = None,
    ) -> None:
        """
        Apply TradingView-style formatting to axes.
        
        Args:
            ax: Matplotlib axes to style
            timestamps: Array of timestamps for x-axis labels
            x_indices: Optional array of x positions (defaults to range(len(timestamps)))
        """
        # Use categorical indices if not provided
        if x_indices is None:
            x_indices = np.arange(len(timestamps))
        else:
            x_indices = np.asarray(x_indices)
        
        # CRITICAL: Disable any datetime formatting on x-axis
        # This prevents matplotlib from trying to use datetime coordinates
        # Clear any existing formatters/locators that might be datetime-based
        try:
            import matplotlib.dates as mdates
            # Remove any date formatters
            if isinstance(ax.xaxis.get_major_formatter(), mdates.DateFormatter):
                ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
            if isinstance(ax.xaxis.get_major_locator(), (mdates.MinuteLocator, mdates.HourLocator, mdates.DayLocator)):
                ax.xaxis.set_major_locator(plt.NullLocator())
        except:
            pass
        # Always set to null formatter/locator to be safe
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
        ax.xaxis.set_major_locator(plt.NullLocator())
        
        # Set background color - TradingView dark theme (#0e1013)
        ax.set_facecolor(DARK_BG)
        
        # Price axis on right side only - TradingView style
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position('right')
        ax.set_ylabel('Price ($)', fontsize=11, color=TEXT_PRIMARY, weight='normal')
        
        # Remove top and right spines - TradingView style (keep bottom for time axis)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_color(GRID_COLOR)
        
        # Horizontal gridlines with muted color - TradingView style
        # Use logical price intervals
        if len(timestamps) > 0:
            # Get current y-axis data range to set grid intervals
            ylim = ax.get_ylim()
            price_range = ylim[1] - ylim[0]
            
            # Calculate logical grid interval (rounded to nice numbers)
            if price_range > 0:
                # Try to get ~5-10 grid lines
                rough_interval = price_range / 8
                # Round to nice number
                magnitude = 10 ** np.floor(np.log10(rough_interval))
                normalized = rough_interval / magnitude
                if normalized < 1.5:
                    nice_interval = magnitude
                elif normalized < 3:
                    nice_interval = 2 * magnitude
                elif normalized < 7:
                    nice_interval = 5 * magnitude
                else:
                    nice_interval = 10 * magnitude
                
                # Set grid locator
                ax.yaxis.set_major_locator(MultipleLocator(nice_interval))
        
        # Enable grid with subtle color
        ax.grid(True, axis='y', alpha=0.3, color=GRID_COLOR, linestyle='--', linewidth=0.5)
        ax.grid(True, axis='x', alpha=0.2, color=GRID_COLOR, linestyle='--', linewidth=0.3)
        
        # Set x-axis to use categorical indices but show timestamp labels
        ax.set_xlabel('Time', fontsize=10, color=TEXT_SECONDARY)
        
        # Ensure x-axis limits are set to categorical range
        ax.set_xlim(-1, len(timestamps))
        
        # Select tick positions (show ~10 ticks at regular intervals)
        num_ticks = min(10, len(timestamps))
        if num_ticks > 1:
            tick_indices = np.linspace(0, len(timestamps) - 1, num_ticks, dtype=int)
            # Set ticks at categorical positions
            tick_positions = x_indices[tick_indices]
            ax.set_xticks(tick_positions)
            
            # Format timestamps for labels (but positions are categorical)
            try:
                timestamp_labels = [pd.to_datetime(ts).strftime('%H:%M') for ts in timestamps[tick_indices]]
                ax.set_xticklabels(timestamp_labels, rotation=0, ha='center', color=TEXT_SECONDARY, fontsize=9)
            except:
                # Fallback if timestamp conversion fails
                ax.set_xticklabels([str(i) for i in tick_indices], rotation=0, ha='center', color=TEXT_SECONDARY)
        else:
            ax.set_xticks([])
        
        # Y-axis labels: high contrast, white, slightly larger
        ax.tick_params(axis='y', colors=TEXT_PRIMARY, which='both', length=4, width=0.5, labelsize=10)
        # X-axis ticks: subtle
        ax.tick_params(axis='x', colors=TEXT_SECONDARY, which='both', length=3, width=0.5, labelsize=9)
        
        # Minimal padding: remove excessive margins
        ax.margins(x=0.01, y=0.01)  # Very small margins
    
    def generate_entry_chart(
        self,
        signal: Dict,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
        timeframe: str = "1m",
    ) -> Optional[Path]:
        """
        Generate entry chart with entry, stop loss, and take profit levels.
        
        Args:
            signal: Signal dictionary with entry_price, stop_loss, take_profit, direction
            buffer_data: DataFrame with OHLCV data (columns: open, high, low, close, volume, timestamp)
            symbol: Trading symbol
            timeframe: Chart timeframe (e.g., "1m", "5m", "15m")
            
        Returns:
            Path to generated chart image, or None if generation failed
        """
        # Use mplfinance if configured
        if self._use_mplfinance:
            return self._mplf_generator.generate_entry_chart(signal, buffer_data, symbol, timeframe)
        
        if not MATPLOTLIB_AVAILABLE:
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
            
            # Prepare data - use last 50-100 bars
            chart_data = buffer_data.tail(100).copy()
            
            # Ensure timestamp column exists
            if "timestamp" not in chart_data.columns:
                if chart_data.index.name == "timestamp" or isinstance(chart_data.index, pd.DatetimeIndex):
                    chart_data = chart_data.reset_index()
                    if "timestamp" not in chart_data.columns:
                        chart_data["timestamp"] = pd.date_range(
                            periods=len(chart_data),
                            end=datetime.now(timezone.utc),
                            freq="1min"
                        )
                else:
                    chart_data["timestamp"] = pd.date_range(
                        periods=len(chart_data),
                        end=datetime.now(timezone.utc),
                        freq="1min"
                    )
            
            # Convert timestamp to datetime if needed
            if not pd.api.types.is_datetime64_any_dtype(chart_data["timestamp"]):
                chart_data["timestamp"] = pd.to_datetime(chart_data["timestamp"])
            
            # Create figure with subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.fig_size, dpi=self.dpi,
                                         gridspec_kw={'height_ratios': [3, 1]})
            
            # CRITICAL: Disable datetime formatting immediately after subplot creation
            ax1.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
            ax1.xaxis.set_major_locator(plt.NullLocator())
            ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
            ax2.xaxis.set_major_locator(plt.NullLocator())
            
            # Plot candlesticks
            self._plot_candlesticks(ax1, chart_data, entry_price, stop_loss, take_profit, direction, symbol)
            
            # Plot indicators
            x_indices = np.arange(len(chart_data))
            self._plot_vwap(ax1, chart_data, x_indices)
            self._plot_moving_averages(ax1, chart_data, x_indices)
            
            # Plot volume
            if "volume" in chart_data.columns:
                self._plot_volume(ax2, chart_data)
            else:
                ax2.axis('off')
            
            # Add title with timeframe - TradingView style: top-left alignment
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            is_test = signal.get("reason", "").lower().startswith("test")
            title_prefix = "🧪 TEST: " if is_test else ""
            title = f"{title_prefix}{symbol} {direction.upper()} {signal_type} - Entry Chart ({timeframe})"
            # Title at top-left (TradingView style)
            fig.text(0.02, 0.98, title, ha='left', va='top', fontsize=14, fontweight='bold', 
                    color='#ffd54f' if is_test else TEXT_PRIMARY, transform=fig.transFigure)
            
            # Add chart metadata with timeframe - below title, muted color
            self._add_chart_metadata(fig, chart_data, symbol, title, timeframe)
            
            # Add metadata for test signals - muted gray color
            if is_test:
                confidence = signal.get("confidence", 0)
                rr_ratio = signal.get("risk_reward", 0)
                metadata_parts = []
                if confidence > 0:
                    metadata_parts.append(f"Confidence: {confidence:.2f}")
                if rr_ratio > 0:
                    metadata_parts.append(f"R:R: {rr_ratio:.2f}:1")
                if metadata_parts:
                    metadata = " | ".join(metadata_parts)
                    fig.text(0.02, 0.95, metadata, ha='left', va='top', fontsize=10, 
                            color=TEXT_SECONDARY, style='italic', transform=fig.transFigure)
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            # Set figure background to TradingView dark color
            fig.patch.set_facecolor(DARK_BG)  # TradingView dark theme (#0e1013)
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor=DARK_BG, 
                       edgecolor='none', pad_inches=0.1, format='png', transparent=False)
            plt.close(fig)
            
            logger.debug(f"Generated entry chart: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating entry chart: {e}", exc_info=True)
            if 'fig' in locals():
                plt.close(fig)
            return None
    
    def generate_exit_chart(
        self,
        signal: Dict,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
        timeframe: str = "1m",
    ) -> Optional[Path]:
        """
        Generate exit chart showing full trade with entry and exit points.
        
        Args:
            signal: Original signal dictionary
            exit_price: Exit price
            exit_reason: Reason for exit (stop_loss, take_profit, manual, etc.)
            pnl: Profit/loss amount
            buffer_data: DataFrame with OHLCV data
            symbol: Trading symbol
            timeframe: Chart timeframe (e.g., "1m", "5m", "15m")
            
        Returns:
            Path to generated chart image, or None if generation failed
        """
        if not MATPLOTLIB_AVAILABLE:
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
            
            # Prepare data - use more bars to show full trade
            chart_data = buffer_data.tail(150).copy()
            
            # Ensure timestamp column exists
            if "timestamp" not in chart_data.columns:
                if chart_data.index.name == "timestamp" or isinstance(chart_data.index, pd.DatetimeIndex):
                    chart_data = chart_data.reset_index()
                    if "timestamp" not in chart_data.columns:
                        chart_data["timestamp"] = pd.date_range(
                            periods=len(chart_data),
                            end=datetime.now(timezone.utc),
                            freq="1min"
                        )
                else:
                    chart_data["timestamp"] = pd.date_range(
                        periods=len(chart_data),
                        end=datetime.now(timezone.utc),
                        freq="1min"
                    )
            
            # Convert timestamp to datetime if needed
            if not pd.api.types.is_datetime64_any_dtype(chart_data["timestamp"]):
                chart_data["timestamp"] = pd.to_datetime(chart_data["timestamp"])
            
            # Create figure with subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.fig_size, dpi=self.dpi,
                                         gridspec_kw={'height_ratios': [3, 1]})
            
            # CRITICAL: Disable datetime formatting immediately after subplot creation
            ax1.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
            ax1.xaxis.set_major_locator(plt.NullLocator())
            ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
            ax2.xaxis.set_major_locator(plt.NullLocator())
            
            # Plot candlesticks with entry and exit
            self._plot_candlesticks_with_exit(
                ax1, chart_data, entry_price, exit_price, stop_loss, take_profit, 
                direction, symbol, exit_reason, pnl
            )
            
            # Plot indicators
            x_indices = np.arange(len(chart_data))
            self._plot_vwap(ax1, chart_data, x_indices)
            self._plot_moving_averages(ax1, chart_data, x_indices)
            
            # Plot volume
            if "volume" in chart_data.columns:
                self._plot_volume(ax2, chart_data)
            else:
                ax2.axis('off')
            
            # Add title with timeframe - TradingView style: top-left alignment
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            result = "WIN" if pnl > 0 else "LOSS"
            title = f"{symbol} {direction.upper()} {signal_type} - Exit ({result}) ({timeframe})"
            # Title at top-left (TradingView style)
            fig.text(0.02, 0.98, title, ha='left', va='top', fontsize=14, fontweight='bold', 
                    color=SIGNAL_LONG if pnl > 0 else SIGNAL_SHORT, transform=fig.transFigure)
            
            # Add chart metadata with timeframe - below title, muted color
            self._add_chart_metadata(fig, chart_data, symbol, title, timeframe)
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            # Set figure background to TradingView dark color
            fig.patch.set_facecolor(DARK_BG)  # TradingView dark theme (#0e1013)
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor=DARK_BG, 
                       edgecolor='none', pad_inches=0.1, format='png', transparent=False)
            plt.close(fig)
            
            logger.debug(f"Generated exit chart: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating exit chart: {e}", exc_info=True)
            if 'fig' in locals():
                plt.close(fig)
            return None
    
    def generate_backtest_chart(
        self,
        backtest_data: pd.DataFrame,
        signals: List[Dict],
        symbol: str = "MNQ",
        title: str = "Backtest Results",
        performance_data: Optional[Dict] = None,
    ) -> Optional[Path]:
        """
        Generate backtest results chart showing price action and signal markers.
        
        Args:
            backtest_data: DataFrame with OHLCV data (must have timestamp column or index)
            signals: List of signal dictionaries from backtest
            symbol: Trading symbol
            title: Chart title
            performance_data: Optional dictionary with performance metrics
            
        Returns:
            Path to generated chart image, or None if generation failed
        """
        # Use mplfinance if configured
        if self._use_mplfinance:
            return self._mplf_generator.generate_backtest_chart(
                backtest_data, signals, symbol, title, performance_data
            )
        
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        try:
            if backtest_data.empty:
                logger.warning("Cannot generate backtest chart: data is empty")
                return None
            
            # Resample data if needed
            timeframe = self.config.timeframe
            if timeframe != "1m":
                chart_data = self._resample_data(backtest_data.copy(), timeframe)
            else:
                chart_data = backtest_data.copy()
            
            # Ensure timestamp column exists
            if "timestamp" not in chart_data.columns:
                if chart_data.index.name == "timestamp" or isinstance(chart_data.index, pd.DatetimeIndex):
                    chart_data = chart_data.reset_index()
                    if "timestamp" not in chart_data.columns:
                        chart_data["timestamp"] = chart_data.index
                else:
                    chart_data["timestamp"] = pd.date_range(
                        periods=len(chart_data),
                        end=datetime.now(timezone.utc),
                        freq="1min"
                    )
            
            # Convert timestamp to datetime if needed
            if not pd.api.types.is_datetime64_any_dtype(chart_data["timestamp"]):
                chart_data["timestamp"] = pd.to_datetime(chart_data["timestamp"])
            
            # Create figure with subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.fig_size, dpi=self.dpi,
                                         gridspec_kw={'height_ratios': [3, 1]})
            
            # CRITICAL: Disable datetime formatting on both axes immediately after creation
            # This prevents matplotlib from auto-detecting datetime data and applying datetime formatters
            try:
                import matplotlib.dates as mdates
                # Remove any date formatters that might have been auto-applied
                ax1.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
                ax1.xaxis.set_major_locator(plt.NullLocator())
                ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
                ax2.xaxis.set_major_locator(plt.NullLocator())
            except:
                pass
            
            # Plot price action
            self._plot_backtest_price_action(ax1, chart_data, signals, symbol)
            
            # Plot volume
            if "volume" in chart_data.columns:
                self._plot_volume(ax2, chart_data)
            else:
                ax2.axis('off')
            
            # Add title with chart type clarification and timeframe - TradingView style: top-left
            chart_type_title = f"{title} - Candlestick Chart with Signal Markers ({timeframe})"
            fig.text(0.02, 0.98, chart_type_title, ha='left', va='top', fontsize=14, fontweight='bold', 
                    color=TEXT_PRIMARY, transform=fig.transFigure)
            
            # Add chart metadata - below title, muted color
            self._add_chart_metadata(fig, chart_data, symbol, title, timeframe)
            
            # Adjust layout - no need to reserve space for transparent overlay
            plt.tight_layout(rect=[0, 0, 1, 0.98])
            # Add performance panel as transparent overlay
            if performance_data:
                self._add_performance_panel(fig, performance_data)
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            # Set figure background to TradingView dark color
            fig.patch.set_facecolor(DARK_BG)  # TradingView dark theme (#0e1013)
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor=DARK_BG, 
                       edgecolor='none', pad_inches=0.1, format='png', transparent=False)
            plt.close(fig)
            
            logger.debug(f"Generated backtest chart: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating backtest chart: {e}", exc_info=True)
            if 'fig' in locals():
                plt.close(fig)
            return None
    
    def _find_signal_index(
        self,
        signal: Dict,
        timestamps: np.ndarray,
        data: pd.DataFrame,
    ) -> Optional[int]:
        """
        Find the index in data for a signal using binary search for timestamp matching.
        
        Args:
            signal: Signal dictionary with timestamp or entry_price
            timestamps: Array of timestamps from data
            data: DataFrame with OHLCV data
            
        Returns:
            Index in data, or None if not found
        """
        # Try timestamp matching first
        if "timestamp" in signal and signal.get("timestamp"):
            try:
                signal_time = pd.to_datetime(signal["timestamp"])
                if signal_time.tzinfo is None:
                    # Assume UTC if no timezone
                    signal_time = signal_time.replace(tzinfo=timezone.utc)
                
                # Binary search for closest timestamp
                timestamps_dt = pd.to_datetime(timestamps)
                if timestamps_dt.tzinfo is None:
                    timestamps_dt = timestamps_dt.tz_localize(timezone.utc)
                else:
                    timestamps_dt = timestamps_dt.tz_convert(timezone.utc)
                
                # Find closest index
                time_diffs = np.abs((timestamps_dt - signal_time).total_seconds())
                min_idx = np.argmin(time_diffs)
                min_diff = time_diffs[min_idx]
                
                # Accept if within 5 minutes
                if min_diff < 300:  # 5 minutes in seconds
                    return int(min_idx)
            except Exception as e:
                logger.debug(f"Error matching timestamp: {e}")
        
        # Fallback: use entry_price to find closest bar
        entry_price = signal.get("entry_price", 0)
        if entry_price > 0:
            # Find bar with closest close price
            closes = data["close"].values
            price_diffs = np.abs(closes - entry_price)
            closest_idx = np.argmin(price_diffs)
            return int(closest_idx)
        
        return None
    
    def _cluster_signals(
        self,
        signals: List[Dict],
        data: pd.DataFrame,
        timestamps: np.ndarray,
    ) -> Dict[int, List[Dict]]:
        """
        Cluster signals that are close together in time.
        
        Args:
            signals: List of signal dictionaries
            data: DataFrame with OHLCV data
            timestamps: Array of timestamps
            
        Returns:
            Dictionary mapping cluster index to list of signals in that cluster
        """
        if not self.config.cluster_signals or len(signals) <= self.config.max_signals_displayed:
            # No clustering needed
            clusters = {}
            for i, signal in enumerate(signals):
                clusters[i] = [signal]
            return clusters
        
        # Find indices for all signals
        signal_indices = []
        for signal in signals:
            idx = self._find_signal_index(signal, timestamps, data)
            if idx is not None:
                signal_indices.append((idx, signal))
        
        if not signal_indices:
            return {}
        
        # Sort by index
        signal_indices.sort(key=lambda x: x[0])
        
        # Cluster signals that are within threshold distance
        clusters = {}
        cluster_idx = 0
        current_cluster = []
        current_cluster_start = None
        
        threshold = max(10, len(data) // 20)  # At least 10 bars, or 5% of data
        
        for idx, signal in signal_indices:
            if current_cluster_start is None:
                current_cluster_start = idx
                current_cluster = [signal]
            elif idx - current_cluster_start <= threshold:
                # Add to current cluster
                current_cluster.append(signal)
            else:
                # Start new cluster
                clusters[cluster_idx] = current_cluster
                cluster_idx += 1
                current_cluster = [signal]
                current_cluster_start = idx
        
        # Add last cluster
        if current_cluster:
            clusters[cluster_idx] = current_cluster
        
        return clusters
    
    def _calculate_signal_positions(
        self,
        signals: List[Dict],
        data: pd.DataFrame,
        timestamps: np.ndarray,
        x_indices: np.ndarray,
        ax=None,
    ) -> List[Tuple[int, float, str, str, str, Dict]]:
        """
        Calculate optimal positions for signal markers with minimal offset (points, not price units).
        
        Args:
            signals: List of signal dictionaries
            data: DataFrame with OHLCV data
            timestamps: Array of timestamps
            x_indices: Array of x-axis indices
            ax: Matplotlib axes (optional, for point-based offset calculation)
            
        Returns:
            List of tuples: (x_index, y_position, direction, color, shape, signal_dict)
        """
        positions = []
        highs = data["high"].values
        lows = data["low"].values
        
        # Minimal offset in points (pixels), not price units
        # Convert ~5-10 points to price units if axes available
        offset_points = 8  # Small pixel offset to avoid overlapping wick
        
        # Track used positions to avoid collisions
        used_x_positions = set()
        used_y_positions = {}  # x_index -> set of y positions
        
        for signal in signals:
            signal_idx = self._find_signal_index(signal, timestamps, data)
            if signal_idx is None:
                continue
            
            entry_price = signal.get("entry_price", 0)
            direction = signal.get("direction", "long").lower()
            
            if entry_price <= 0:
                continue
            
            # Calculate base y position - TradingView style: LONG at low, SHORT at high
            if direction == 'long':
                base_y = lows[signal_idx]  # Right at the low
                marker_color = SIGNAL_LONG  # Teal-green for long
                marker_shape = '^'  # Upward triangle
                offset_direction = -1  # Below the low
            else:
                base_y = highs[signal_idx]  # Right at the high
                marker_color = SIGNAL_SHORT  # Red for short
                marker_shape = 'v'  # Downward triangle
                offset_direction = 1  # Above the high
            
            # Convert point offset to price units if axes available
            if ax is not None:
                # Get transform to convert points to data coordinates
                trans = ax.get_yaxis_transform()
                # Convert points to data coordinates
                # Approximate: use a small fraction of price range
                price_range = highs.max() - lows.min()
                if price_range > 0:
                    # Rough conversion: assume ~500 pixels height, so 1 point ≈ price_range/500
                    offset_price = (offset_points / 500.0) * price_range * 0.1  # Very small
                else:
                    offset_price = 0.5  # Fallback
            else:
                # Fallback: use tiny price offset
                price_range = highs.max() - lows.min()
                offset_price = price_range * 0.005 if price_range > 0 else 0.5  # 0.5% of range
            
            y_pos = base_y + (offset_price * offset_direction)
            
            # Check for collisions and adjust slightly if needed
            x_pos = x_indices[signal_idx]
            
            # If x position already used, adjust y position slightly
            if x_pos in used_x_positions:
                if x_pos not in used_y_positions:
                    used_y_positions[x_pos] = set()
                
                # Try different small offsets
                for offset_mult in [1.0, 1.5, 2.0, 2.5]:
                    test_y = base_y + (offset_price * offset_mult * offset_direction)
                    if test_y not in used_y_positions[x_pos]:
                        y_pos = test_y
                        used_y_positions[x_pos].add(test_y)
                        break
            else:
                used_x_positions.add(x_pos)
                if x_pos not in used_y_positions:
                    used_y_positions[x_pos] = set()
                used_y_positions[x_pos].add(y_pos)
            
            positions.append((int(x_pos), y_pos, direction, marker_color, marker_shape, signal))
        
        return positions
    
    def _plot_backtest_price_action(
        self,
        ax,
        data: pd.DataFrame,
        signals: List[Dict],
        symbol: str,
    ):
        """Plot proper candlestick chart with signal markers for backtest."""
        # Extract OHLC data
        opens = data["open"].values
        highs = data["high"].values
        lows = data["low"].values
        closes = data["close"].values
        timestamps = data["timestamp"].values
        
        # Use categorical indices for x-axis (prevents diagonal banding)
        x_indices = np.arange(len(data))
        
        # Draw candlesticks using the unified function
        self.draw_candles(ax, opens, highs, lows, closes, x_indices)
        
        # Plot indicators
        self._plot_vwap(ax, data, x_indices)
        self._plot_moving_averages(ax, data, x_indices)
        
        # Limit signals if too many
        signals_to_plot = signals[:self.config.max_signals_displayed] if len(signals) > self.config.max_signals_displayed else signals
        
        # Cluster signals if needed
        clusters = self._cluster_signals(signals_to_plot, data, timestamps)
        
        # Calculate signal positions with collision detection (pass ax for point-based offset)
        all_positions = []
        signal_labels_added = {'long': False, 'short': False}
        zones_to_plot = []  # Store zones for horizontal highlights
        
        for cluster_idx, cluster_signals in clusters.items():
            if len(cluster_signals) == 1:
                # Single signal, plot normally
                positions = self._calculate_signal_positions(cluster_signals, data, timestamps, x_indices, ax)
                all_positions.extend(positions)
            else:
                # Clustered signals - replace with horizontal zone highlight
                # Calculate price range and time range for the cluster
                cluster_prices = []
                cluster_indices = []
                cluster_directions = []
                
                for signal in cluster_signals:
                    signal_idx = self._find_signal_index(signal, timestamps, data)
                    if signal_idx is not None:
                        entry_price = signal.get("entry_price", 0)
                        direction = signal.get("direction", "long").lower()
                        if entry_price > 0:
                            cluster_prices.append(entry_price)
                            cluster_indices.append(signal_idx)
                            cluster_directions.append(direction)
                
                if cluster_prices and cluster_indices:
                    # Determine zone bounds
                    price_min = min(cluster_prices)
                    price_max = max(cluster_prices)
                    price_mid = (price_min + price_max) / 2
                    time_start = min(cluster_indices)
                    time_end = max(cluster_indices)
                    
                    # Use most common direction
                    direction = max(set(cluster_directions), key=cluster_directions.count)
                    
                    # Create zone highlight
                    zone_color = SIGNAL_LONG if direction == 'long' else SIGNAL_SHORT
                    zone_label = f"{direction.upper()} Power: {len(cluster_signals)}"
                    
                    zones_to_plot.append({
                        'ymin': price_min - (price_max - price_min) * 0.1,  # Slight padding
                        'ymax': price_max + (price_max - price_min) * 0.1,
                        'xmin': x_indices[time_start] - 0.5,
                        'xmax': x_indices[time_end] + 0.5,
                        'color': zone_color,
                        'label': zone_label,
                        'price_mid': price_mid,
                        'x_label': x_indices[time_end] + 1,  # Label at right edge
                    })
        
        # Plot horizontal zone highlights
        for zone in zones_to_plot:
            # Draw translucent rectangle
            from matplotlib.patches import Rectangle as ZoneRect
            zone_rect = ZoneRect(
                (zone['xmin'], zone['ymin']),
                zone['xmax'] - zone['xmin'],
                zone['ymax'] - zone['ymin'],
                facecolor=zone['color'],
                alpha=0.2,  # Semi-transparent
                edgecolor=zone['color'],
                linewidth=1,
                zorder=2  # Behind candles but visible
            )
            ax.add_patch(zone_rect)
            
            # Add label with arrow pointing to zone
            ax.annotate(
                zone['label'],
                xy=(zone['x_label'], zone['price_mid']),
                xytext=(zone['x_label'] + 2, zone['price_mid']),
                fontsize=9,
                color=zone['color'],
                weight='bold',
                ha='left',
                va='center',
                arrowprops=dict(arrowstyle='->', color=zone['color'], lw=1.5),
                bbox=dict(boxstyle='round,pad=0.3', facecolor=DARK_BG, edgecolor=zone['color'], alpha=0.8),
                zorder=12
            )
        
        # Plot all signal markers
        for x_pos, y_pos, direction, color, shape, signal in all_positions:
            label = None
            if not signal_labels_added[direction]:
                label = f'{direction.upper()} Signal'
                signal_labels_added[direction] = True
            
            # TradingView style signal markers: solid, bold, with subtle edge
            ax.scatter(
                x_pos,
                y_pos,
                color=color,
                marker=shape,
                s=350,  # Slightly larger for visibility
                alpha=1.0,  # Fully opaque
                edgecolors='white' if color == SIGNAL_LONG else '#ffcccc',  # White edge for green, light edge for red
                linewidths=2.0,  # Bold edge
                zorder=15,  # Above candlesticks
                label=label
            )
        
        # Apply TradingView-style formatting (pass x_indices to ensure proper setup)
        self._apply_tradingview_styling(ax, timestamps, x_indices)
        
        if signals:
            ax.legend(loc='upper left', fontsize=9, facecolor='#1e222d', edgecolor='#2a2e39', 
                     framealpha=0.95, labelcolor='#d1d4dc')  # TradingView legend style
    
    def _plot_vwap(
        self,
        ax,
        data: pd.DataFrame,
        x_indices: np.ndarray,
    ) -> None:
        """
        Plot VWAP indicator on chart.
        
        Args:
            ax: Matplotlib axes to plot on
            data: DataFrame with OHLCV data
            x_indices: Array of x-axis indices
        """
        if not self.config.show_vwap:
            return
        
        try:
            from pearlalgo.utils.vwap import VWAPCalculator
            
            vwap_calc = VWAPCalculator()
            vwap_data = vwap_calc.calculate_vwap(data)
            vwap_value = vwap_data.get("vwap", 0)
            
            if vwap_value > 0:
                # Plot VWAP line
                ax.axhline(
                    y=vwap_value,
                    color=VWAP_COLOR,  # Orange/amber color for VWAP
                    linestyle='-',
                    linewidth=1.5,
                    alpha=0.7,
                    label='VWAP',
                    zorder=3
                )
        except Exception as e:
            logger.debug(f"Error plotting VWAP: {e}")
    
    def _plot_moving_averages(
        self,
        ax,
        data: pd.DataFrame,
        x_indices: np.ndarray,
    ) -> None:
        """
        Plot moving averages on chart.
        
        Args:
            ax: Matplotlib axes to plot on
            data: DataFrame with OHLCV data
            x_indices: Array of x-axis indices
        """
        if not self.config.show_ma or not self.config.ma_periods:
            return
        
        try:
            closes = data["close"].values
            
            # Color palette for different MA periods
            ma_colors = MA_COLORS  # Blue, Purple, Red
            
            for i, period in enumerate(self.config.ma_periods):
                if period > len(closes):
                    continue
                
                # Calculate SMA
                ma_values = []
                for j in range(len(closes)):
                    if j < period - 1:
                        ma_values.append(np.nan)
                    else:
                        ma_values.append(np.mean(closes[j - period + 1:j + 1]))
                
                ma_values = np.array(ma_values)
                
                # Only plot where we have values
                valid_mask = ~np.isnan(ma_values)
                if np.any(valid_mask):
                    color = ma_colors[i % len(ma_colors)]
                    ax.plot(
                        x_indices[valid_mask],
                        ma_values[valid_mask],
                        color=color,
                        linestyle='-',
                        linewidth=1.2,
                        alpha=0.6,
                        marker=None,  # Explicitly no markers
                        label=f'MA{period}',
                        zorder=3
                    )
        except Exception as e:
            logger.debug(f"Error plotting moving averages: {e}")
    
    def _plot_candlesticks(
        self,
        ax,
        data: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        direction: str,
        symbol: str,
    ):
        """Plot candlestick chart with entry, stop, and TP levels."""
        # Extract OHLC data
        opens = data["open"].values
        highs = data["high"].values
        lows = data["low"].values
        closes = data["close"].values
        timestamps = data["timestamp"].values
        
        # Use categorical indices for x-axis
        x_indices = np.arange(len(data))
        
        # Draw candlesticks using the unified function
        self.draw_candles(ax, opens, highs, lows, closes, x_indices)
        
        # Plot entry, stop, and TP lines with shaded bands - TradingView style
        entry_color = ENTRY_COLOR if direction == 'long' else SIGNAL_SHORT
        
        # Add shaded bands if enabled
        if hasattr(self.config, 'show_entry_sl_tp_bands') and self.config.show_entry_sl_tp_bands:
            x_range = np.array([x_indices[0] - 0.5, x_indices[-1] + 0.5])
            
            # Stop-loss zone (light red, semi-transparent)
            if stop_loss and stop_loss > 0:
                if direction == 'long':
                    # Long: stop is below entry
                    ax.fill_between(x_range, stop_loss, entry_price, 
                                   color=SIGNAL_SHORT, alpha=0.15, zorder=1, label='Stop Zone')
                else:
                    # Short: stop is above entry
                    ax.fill_between(x_range, entry_price, stop_loss, 
                                   color=SIGNAL_SHORT, alpha=0.15, zorder=1, label='Stop Zone')
            
            # Take-profit zone (light green, semi-transparent)
            if take_profit and take_profit > 0:
                if direction == 'long':
                    # Long: TP is above entry
                    ax.fill_between(x_range, entry_price, take_profit, 
                                   color=SIGNAL_LONG, alpha=0.15, zorder=1, label='TP Zone')
                else:
                    # Short: TP is below entry
                    ax.fill_between(x_range, take_profit, entry_price, 
                                   color=SIGNAL_LONG, alpha=0.15, zorder=1, label='TP Zone')
        
        # Plot boundary lines
        ax.axhline(y=entry_price, color=entry_color, linestyle='-', linewidth=2.5, 
                  label=f'Entry: ${entry_price:.2f}', alpha=0.9, zorder=5)
        
        if stop_loss and stop_loss > 0:
            ax.axhline(y=stop_loss, color=SIGNAL_SHORT, linestyle='--', linewidth=2,
                      label=f'Stop: ${stop_loss:.2f}', alpha=0.7, zorder=5, dashes=(5, 3))
        
        if take_profit and take_profit > 0:
            ax.axhline(y=take_profit, color=SIGNAL_LONG, linestyle='--', linewidth=2,
                      label=f'TP: ${take_profit:.2f}', alpha=0.7, zorder=5, dashes=(5, 3))
        
        # Apply TradingView-style formatting
        self._apply_tradingview_styling(ax, timestamps, x_indices)
        
        ax.legend(loc='upper left', fontsize=9, facecolor=DARK_BG, edgecolor=GRID_COLOR, 
                 framealpha=0.8, labelcolor=TEXT_PRIMARY)
    
    def _plot_candlesticks_with_exit(
        self,
        ax,
        data: pd.DataFrame,
        entry_price: float,
        exit_price: float,
        stop_loss: float,
        take_profit: float,
        direction: str,
        symbol: str,
        exit_reason: str,
        pnl: float,
    ):
        """Plot candlestick chart with entry and exit points."""
        # Extract OHLC data
        opens = data["open"].values
        highs = data["high"].values
        lows = data["low"].values
        closes = data["close"].values
        timestamps = data["timestamp"].values
        
        # Use categorical indices for x-axis
        x_indices = np.arange(len(data))
        
        # Draw candlesticks using the unified function
        self.draw_candles(ax, opens, highs, lows, closes, x_indices)
        
        # Plot entry line with shaded bands - TradingView style
        entry_color = ENTRY_COLOR if direction == 'long' else SIGNAL_SHORT
        
        # Add shaded bands if enabled
        if hasattr(self.config, 'show_entry_sl_tp_bands') and self.config.show_entry_sl_tp_bands:
            x_range = np.array([x_indices[0] - 0.5, x_indices[-1] + 0.5])
            
            # Stop-loss zone (light red, semi-transparent)
            if stop_loss and stop_loss > 0:
                if direction == 'long':
                    ax.fill_between(x_range, stop_loss, entry_price, 
                                   color=SIGNAL_SHORT, alpha=0.15, zorder=1, label='Stop Zone')
                else:
                    ax.fill_between(x_range, entry_price, stop_loss, 
                                   color=SIGNAL_SHORT, alpha=0.15, zorder=1, label='Stop Zone')
            
            # Take-profit zone (light green, semi-transparent)
            if take_profit and take_profit > 0:
                if direction == 'long':
                    ax.fill_between(x_range, entry_price, take_profit, 
                                   color=SIGNAL_LONG, alpha=0.15, zorder=1, label='TP Zone')
                else:
                    ax.fill_between(x_range, take_profit, entry_price, 
                                   color=SIGNAL_LONG, alpha=0.15, zorder=1, label='TP Zone')
        
        # Plot boundary lines
        ax.axhline(y=entry_price, color=entry_color, linestyle='-', linewidth=2.5,
                  label=f'Entry: ${entry_price:.2f}', alpha=0.9, zorder=5)
        
        # Plot exit line - TradingView style
        exit_color = MA_COLORS[0]  # Blue for exit
        ax.axhline(y=exit_price, color=exit_color, linestyle='-', linewidth=2.5,
                  label=f'Exit: ${exit_price:.2f} ({exit_reason})', alpha=0.9, zorder=5)
        
        # Plot stop and TP lines (dashed for reference) - TradingView style
        if stop_loss and stop_loss > 0:
            ax.axhline(y=stop_loss, color=SIGNAL_SHORT, linestyle='--', linewidth=2,
                      label=f'Stop: ${stop_loss:.2f}', alpha=0.7, zorder=5, dashes=(5, 3))
        
        if take_profit and take_profit > 0:
            ax.axhline(y=take_profit, color=SIGNAL_LONG, linestyle='--', linewidth=2,
                      label=f'TP: ${take_profit:.2f}', alpha=0.7, zorder=5, dashes=(5, 3))
        
        # Add P&L annotation - transparent overlay style
        pnl_color = SIGNAL_LONG if pnl > 0 else SIGNAL_SHORT
        pnl_text = f"P&L: ${pnl:,.2f}"
        ax.text(0.02, 0.98, pnl_text, transform=ax.transAxes,
               fontsize=11, fontweight='bold', color=pnl_color,
               verticalalignment='top', bbox=dict(boxstyle='round,pad=0.5', 
               facecolor='#00000080', edgecolor='none', alpha=0.7))
        
        # Apply TradingView-style formatting
        self._apply_tradingview_styling(ax, timestamps, x_indices)
        
        ax.legend(loc='upper left', fontsize=9, facecolor=DARK_BG, edgecolor=GRID_COLOR, 
                 framealpha=0.8, labelcolor=TEXT_PRIMARY)
    
    def _add_performance_panel(
        self,
        fig,
        performance_data: Optional[Dict] = None,
    ) -> None:
        """
        Add performance metrics panel to chart.
        
        Args:
            fig: Matplotlib figure
            performance_data: Dictionary with performance metrics
        """
        if not self.config.show_performance_metrics or not performance_data:
            return
        
        try:
            # Create text for performance metrics
            metrics_text = []
            
            total_signals = performance_data.get("total_signals", 0)
            if total_signals is not None and total_signals >= 0:
                metrics_text.append(f"Signals: {total_signals}")
            
            avg_confidence = performance_data.get("avg_confidence", None)
            if avg_confidence is not None and avg_confidence >= 0:
                metrics_text.append(f"Avg Confidence: {avg_confidence:.2f}")
            
            avg_rr = performance_data.get("avg_risk_reward", None)
            if avg_rr is not None and avg_rr >= 0:
                metrics_text.append(f"Avg R:R: {avg_rr:.2f}:1")
            
            win_rate = performance_data.get("win_rate", None)
            if win_rate is not None:
                metrics_text.append(f"Win Rate: {win_rate:.1f}%")
            
            total_pnl = performance_data.get("total_pnl", None)
            if total_pnl is not None:
                pnl_color = 'green' if total_pnl >= 0 else 'red'
                metrics_text.append(f"Total P&L: ${total_pnl:,.2f}")
            
            # Always show at least signals count if we have performance data
            if not metrics_text and performance_data:
                metrics_text.append("Performance data available")
            
            if metrics_text:
                # Add transparent overlay - TradingView style: no border, semi-transparent background
                metrics_str = " | ".join(metrics_text)
                # Position at bottom-right inside chart area (floating overlay)
                fig.text(
                    0.99, 0.01,  # Bottom-right corner
                    metrics_str,
                    ha='right',
                    va='bottom',
                    fontsize=10,
                    color=TEXT_PRIMARY,
                    weight='normal',
                    bbox=dict(boxstyle='round,pad=0.5', facecolor='#00000080', edgecolor='none', alpha=0.7),
                    transform=fig.transFigure
                )
                logger.debug(f"Performance panel added: {metrics_str}")
        except Exception as e:
            logger.debug(f"Error adding performance panel: {e}")
    
    def _resample_data(
        self,
        data: pd.DataFrame,
        timeframe: str,
    ) -> pd.DataFrame:
        """
        Resample 1m data to specified timeframe.
        
        Args:
            data: DataFrame with 1m OHLCV data
            timeframe: Target timeframe ('1m', '5m', '15m')
            
        Returns:
            Resampled DataFrame
        """
        if timeframe == "1m" or data.empty:
            return data.copy()
        
        # Ensure timestamp is in index for resampling
        data_copy = data.copy()
        timestamp_in_index = False
        
        if "timestamp" in data_copy.columns:
            # Convert timestamp to datetime if needed
            if not pd.api.types.is_datetime64_any_dtype(data_copy["timestamp"]):
                data_copy["timestamp"] = pd.to_datetime(data_copy["timestamp"])
            data_copy = data_copy.set_index("timestamp")
            timestamp_in_index = True
        elif isinstance(data_copy.index, pd.DatetimeIndex):
            timestamp_in_index = True
        
        if not timestamp_in_index:
            logger.warning("Cannot resample: data has no timestamp column or DatetimeIndex")
            return data.copy()
        
        # Map timeframe strings to pandas frequency
        freq_map = {
            "5m": "5min",
            "15m": "15min",
            "1h": "1H",
        }
        
        freq = freq_map.get(timeframe, "1min")
        
        try:
            # Resample OHLCV data
            resampled = data_copy.resample(freq).agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna()
            
            # Reset index to timestamp column
            resampled = resampled.reset_index()
            resampled.rename(columns={resampled.index.name: "timestamp"}, inplace=True)
            if "timestamp" not in resampled.columns:
                resampled["timestamp"] = resampled.index
            
            return resampled
        except Exception as e:
            logger.warning(f"Error resampling data: {e}")
            return data.copy()
    
    def _add_chart_metadata(
        self,
        fig,
        data: pd.DataFrame,
        symbol: str,
        title: str,
        timeframe: str = "1m",
    ) -> None:
        """
        Add chart metadata (time range, bar count, timeframe) to chart.
        
        Args:
            fig: Matplotlib figure
            data: DataFrame with OHLCV data
            symbol: Trading symbol
            title: Chart title
            timeframe: Chart timeframe (e.g., "1m", "5m", "15m")
        """
        try:
            if "timestamp" in data.columns and len(data) > 0:
                timestamps = data["timestamp"]
                start_time = pd.to_datetime(timestamps.iloc[0])
                end_time = pd.to_datetime(timestamps.iloc[-1])
                
                time_range = f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
                bar_count = len(data)
                
                metadata = f"{symbol} | {bar_count} bars | {timeframe} | {time_range}"
                
                # Add metadata below title - TradingView style: top-left, muted color
                fig.text(
                    0.02, 0.95,
                    metadata,
                    ha='left',
                    va='top',
                    fontsize=10,
                    color=TEXT_SECONDARY,  # Muted gray
                    style='italic',
                    transform=fig.transFigure
                )
        except Exception as e:
            logger.debug(f"Error adding chart metadata: {e}")
    
    def _plot_volume(self, ax, data: pd.DataFrame):
        """Plot volume bars with categorical indices matching candle width, MA baseline, and color-coding."""
        if "volume" not in data.columns:
            return
        
        timestamps = data["timestamp"].values
        volumes = data["volume"].values
        
        # Use categorical indices matching price panel
        x_indices = np.arange(len(data))
        
        # Color volume bars by candle direction (matching TradingView candlestick colors)
        # Use exact TradingView colors: #26a69a for up, #ef5350 for down
        colors = [CANDLE_UP if data.iloc[i]["close"] >= data.iloc[i]["open"] 
                 else CANDLE_DOWN for i in range(len(data))]
        
        # CRITICAL: Disable datetime formatting on x-axis
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
        ax.xaxis.set_major_locator(plt.NullLocator())
        
        # Bar width matches candle width - TradingView style (sync with candle width)
        candle_width = self.config.candle_width_fraction if hasattr(self, 'config') else 0.75
        bar_width = candle_width  # Same width as candles
        
        # Plot volume bars
        ax.bar(x_indices, volumes, color=colors, alpha=0.7, width=bar_width, edgecolor='none')
        
        # Add volume moving average baseline
        volume_ma_period = self.config.volume_ma_period if hasattr(self, 'config') else 20
        if len(volumes) >= volume_ma_period:
            volume_ma = []
            for i in range(len(volumes)):
                if i < volume_ma_period - 1:
                    volume_ma.append(np.nan)
                else:
                    volume_ma.append(np.mean(volumes[i - volume_ma_period + 1:i + 1]))
            volume_ma = np.array(volume_ma)
            
            # Plot MA line where valid
            valid_mask = ~np.isnan(volume_ma)
            if np.any(valid_mask):
                ax.plot(
                    x_indices[valid_mask],
                    volume_ma[valid_mask],
                    color='#777777',  # Mid-gray for baseline
                    linestyle='-',
                    linewidth=1.0,
                    alpha=0.5,  # Faint but visible
                    label=f'Vol MA{volume_ma_period}',
                    zorder=3
                )
        
        # Set x-axis limits to match price panel (categorical indices)
        ax.set_xlim(-1, len(data))
        ax.set_autoscalex_on(False)
        
        # Volume panel styling - TradingView dark theme
        ax.set_facecolor(DARK_BG)
        ax.set_ylabel('Volume', fontsize=11, color=TEXT_PRIMARY, weight='normal')
        ax.tick_params(colors=TEXT_SECONDARY, which='both', length=4, width=0.5)
        
        # Subtle grid for volume panel
        ax.grid(True, alpha=0.2, color=GRID_COLOR, axis='y', linestyle='--', linewidth=0.5)
        
        # Remove top and left spines - TradingView style
        ax.spines['top'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color(GRID_COLOR)
        
        # Format x-axis with timestamp labels (matching price panel)
        num_ticks = min(10, len(timestamps))
        if num_ticks > 1:
            tick_indices = np.linspace(0, len(timestamps) - 1, num_ticks, dtype=int)
            tick_positions = x_indices[tick_indices]
            ax.set_xticks(tick_positions)
            
            try:
                timestamp_labels = [pd.to_datetime(ts).strftime('%H:%M') for ts in timestamps[tick_indices]]
                ax.set_xticklabels(timestamp_labels, rotation=0, ha='center', color=TEXT_SECONDARY, fontsize=9)
            except:
                ax.set_xticklabels([str(i) for i in tick_indices], rotation=0, ha='center', color=TEXT_SECONDARY)
        else:
            ax.set_xticks([])
