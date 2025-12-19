"""
Chart Generator for NQ Agent

Generates professional trading charts with entry, stop loss, and take profit levels.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("matplotlib not installed, chart generation disabled")


class ChartGenerator:
    """Generates trading charts for signals and trades."""
    
    def __init__(self):
        """Initialize chart generator."""
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
        
        # Candle width - explicit spacing ensures candles don't touch
        candle_width = 0.6
        
        # Draw each candlestick
        for i, x in enumerate(x_indices):
            # Determine color based on close vs open
            is_bullish = closes[i] >= opens[i]
            color = '#26a69a' if is_bullish else '#ef5350'
            
            # Draw wick (high-low line) using vlines
            ax.vlines(
                x, 
                lows[i], 
                highs[i], 
                colors=color, 
                linewidths=1.0, 
                alpha=1.0,
                zorder=1
            )
            
            # Calculate body dimensions
            body_bottom = min(opens[i], closes[i])
            body_height = abs(closes[i] - opens[i])
            
            # For doji (very small body), ensure minimum visibility
            if body_height < 0.01:
                body_height = 0.5
                body_bottom = closes[i] - body_height / 2
            
            # Draw body using Rectangle
            rect = Rectangle(
                (x - candle_width/2, body_bottom),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                alpha=1.0,
                linewidth=0.5,
                zorder=2
            )
            ax.add_patch(rect)
    
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
        
        # Set background color
        ax.set_facecolor('#0b0e11')
        
        # Price axis on right side only
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position('right')
        ax.set_ylabel('Price ($)', fontsize=10, color='white')
        
        # Remove top and left spines
        ax.spines['top'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['right'].set_color('white')
        ax.spines['bottom'].set_color('white')
        
        # Grid with low alpha
        ax.grid(True, alpha=0.2, color='gray', linestyle='-')
        
        # Set x-axis to use categorical indices but show timestamp labels
        ax.set_xlabel('Time', fontsize=9, color='white')
        
        # Ensure x-axis limits are set to categorical range
        ax.set_xlim(-1, len(timestamps))
        
        # Select tick positions (show ~10 ticks)
        num_ticks = min(10, len(timestamps))
        if num_ticks > 1:
            tick_indices = np.linspace(0, len(timestamps) - 1, num_ticks, dtype=int)
            # Set ticks at categorical positions
            tick_positions = x_indices[tick_indices]
            ax.set_xticks(tick_positions)
            
            # Format timestamps for labels (but positions are categorical)
            try:
                timestamp_labels = [pd.to_datetime(ts).strftime('%H:%M') for ts in timestamps[tick_indices]]
                ax.set_xticklabels(timestamp_labels, rotation=0, ha='center', color='white')
            except:
                # Fallback if timestamp conversion fails
                ax.set_xticklabels([str(i) for i in tick_indices], rotation=0, ha='center', color='white')
        else:
            ax.set_xticks([])
        
        # Minimal ticks
        ax.tick_params(colors='white', which='both', length=3)
    
    def generate_entry_chart(
        self,
        signal: Dict,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
    ) -> Optional[Path]:
        """
        Generate entry chart with entry, stop loss, and take profit levels.
        
        Args:
            signal: Signal dictionary with entry_price, stop_loss, take_profit, direction
            buffer_data: DataFrame with OHLCV data (columns: open, high, low, close, volume, timestamp)
            symbol: Trading symbol
            
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
            
            # Plot volume
            if "volume" in chart_data.columns:
                self._plot_volume(ax2, chart_data)
            else:
                ax2.axis('off')
            
            # Add title
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            title = f"{symbol} {direction.upper()} {signal_type} - Entry Chart"
            fig.suptitle(title, fontsize=14, fontweight='bold', color='white')
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            # Set figure background to TradingView dark color
            fig.patch.set_facecolor('#0b0e11')
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor='#0b0e11')
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
            
            # Plot volume
            if "volume" in chart_data.columns:
                self._plot_volume(ax2, chart_data)
            else:
                ax2.axis('off')
            
            # Add title
            signal_type = signal.get("type", "unknown").replace("_", " ").title()
            result = "WIN" if pnl > 0 else "LOSS"
            title = f"{symbol} {direction.upper()} {signal_type} - Exit ({result})"
            fig.suptitle(title, fontsize=14, fontweight='bold', 
                        color='green' if pnl > 0 else 'red')
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            # Set figure background to TradingView dark color
            fig.patch.set_facecolor('#0b0e11')
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor='#0b0e11')
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
    ) -> Optional[Path]:
        """
        Generate backtest results chart showing price action and signal markers.
        
        Args:
            backtest_data: DataFrame with OHLCV data (must have timestamp column or index)
            signals: List of signal dictionaries from backtest
            symbol: Trading symbol
            title: Chart title
            
        Returns:
            Path to generated chart image, or None if generation failed
        """
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        try:
            if backtest_data.empty:
                logger.warning("Cannot generate backtest chart: data is empty")
                return None
            
            # Prepare data
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
            
            # Add title with chart type clarification
            chart_type_title = f"{title} - Candlestick Chart with Signal Markers"
            fig.suptitle(chart_type_title, fontsize=14, fontweight='bold', color='white')
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = Path(temp_file.name)
            # Set figure background to TradingView dark color
            fig.patch.set_facecolor('#0b0e11')
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor='#0b0e11')
            plt.close(fig)
            
            logger.debug(f"Generated backtest chart: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating backtest chart: {e}", exc_info=True)
            if 'fig' in locals():
                plt.close(fig)
            return None
    
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
        
        # Plot signal markers - positioned at categorical indices
        signal_labels_added = {'long': False, 'short': False}
        price_range = highs.max() - lows.min()
        price_offset = price_range * 0.02  # 2% of price range
        
        for signal in signals:
            entry_price = signal.get("entry_price", 0)
            direction = signal.get("direction", "long").lower()
            
            if entry_price > 0:
                # Find closest index in data for signal timestamp
                signal_idx = None
                
                if "timestamp" in signal:
                    try:
                        signal_time = pd.to_datetime(signal["timestamp"])
                        # Find closest index
                        time_diffs = [abs((pd.to_datetime(ts) - signal_time).total_seconds()) 
                                    for ts in timestamps]
                        signal_idx = time_diffs.index(min(time_diffs))
                    except:
                        pass
                
                if signal_idx is None:
                    # Use middle of data range if timestamp not found
                    signal_idx = len(timestamps) // 2
                
                # Position markers: long at low - offset, short at high + offset
                if direction == 'long':
                    marker_y = lows[signal_idx] - price_offset
                    marker_color = '#00ff88'  # Green for long
                    marker_shape = '^'
                else:
                    marker_y = highs[signal_idx] + price_offset
                    marker_color = '#ff8800'  # Orange for short
                    marker_shape = 'v'
                
                # Plot signal marker
                label = None
                if not signal_labels_added[direction]:
                    label = f'{direction.upper()} Signal'
                    signal_labels_added[direction] = True
                
                ax.scatter(
                    signal_idx,  # Use categorical index
                    marker_y,
                    color=marker_color,
                    marker=marker_shape,
                    s=300,
                    alpha=0.9,
                    edgecolors='white',
                    linewidths=2.5,
                    zorder=10,
                    label=label
                )
        
        # Apply TradingView-style formatting (pass x_indices to ensure proper setup)
        self._apply_tradingview_styling(ax, timestamps, x_indices)
        
        if signals:
            ax.legend(loc='upper left', fontsize=8, facecolor='black', edgecolor='white', framealpha=0.9)
    
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
        
        # Plot entry, stop, and TP lines
        entry_color = 'lime' if direction == 'long' else 'orange'
        ax.axhline(y=entry_price, color=entry_color, linestyle='-', linewidth=2, 
                  label=f'Entry: ${entry_price:.2f}', alpha=0.8, zorder=5)
        
        if stop_loss and stop_loss > 0:
            ax.axhline(y=stop_loss, color='red', linestyle='--', linewidth=2,
                      label=f'Stop: ${stop_loss:.2f}', alpha=0.8, zorder=5)
        
        if take_profit and take_profit > 0:
            ax.axhline(y=take_profit, color='green', linestyle='--', linewidth=2,
                      label=f'TP: ${take_profit:.2f}', alpha=0.8, zorder=5)
        
        # Apply TradingView-style formatting
        self._apply_tradingview_styling(ax, timestamps, x_indices)
        
        ax.legend(loc='upper left', fontsize=8, facecolor='black', edgecolor='white', framealpha=0.9)
    
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
        
        # Plot entry line
        entry_color = 'lime' if direction == 'long' else 'orange'
        ax.axhline(y=entry_price, color=entry_color, linestyle='-', linewidth=2,
                  label=f'Entry: ${entry_price:.2f}', alpha=0.8, zorder=5)
        
        # Plot exit line
        exit_color = 'cyan'
        ax.axhline(y=exit_price, color=exit_color, linestyle='-', linewidth=2,
                  label=f'Exit: ${exit_price:.2f} ({exit_reason})', alpha=0.8, zorder=5)
        
        # Plot stop and TP lines (dashed for reference)
        if stop_loss and stop_loss > 0:
            ax.axhline(y=stop_loss, color='red', linestyle='--', linewidth=1.5,
                      label=f'Stop: ${stop_loss:.2f}', alpha=0.6, zorder=5)
        
        if take_profit and take_profit > 0:
            ax.axhline(y=take_profit, color='green', linestyle='--', linewidth=1.5,
                      label=f'TP: ${take_profit:.2f}', alpha=0.6, zorder=5)
        
        # Add P&L annotation
        pnl_color = 'green' if pnl > 0 else 'red'
        pnl_text = f"P&L: ${pnl:,.2f}"
        ax.text(0.02, 0.98, pnl_text, transform=ax.transAxes,
               fontsize=12, fontweight='bold', color=pnl_color,
               verticalalignment='top', bbox=dict(boxstyle='round', 
               facecolor='black', edgecolor=pnl_color, alpha=0.8))
        
        # Apply TradingView-style formatting
        self._apply_tradingview_styling(ax, timestamps, x_indices)
        
        ax.legend(loc='upper left', fontsize=8, facecolor='black', edgecolor='white', framealpha=0.9)
    
    def _plot_volume(self, ax, data: pd.DataFrame):
        """Plot volume bars with categorical indices matching candle width."""
        if "volume" not in data.columns:
            return
        
        timestamps = data["timestamp"].values
        volumes = data["volume"].values
        
        # Use categorical indices matching price panel
        x_indices = np.arange(len(data))
        
        # Color volume bars by candle direction (green/red matching candles)
        colors = ['#26a69a' if data.iloc[i]["close"] >= data.iloc[i]["open"] 
                 else '#ef5350' for i in range(len(data))]
        
        # CRITICAL: Disable datetime formatting on x-axis
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: ''))
        ax.xaxis.set_major_locator(plt.NullLocator())
        
        # Bar width matches candle width (0.6)
        bar_width = 0.6
        ax.bar(x_indices, volumes, color=colors, alpha=0.6, width=bar_width)
        
        # Set x-axis limits to match price panel (categorical indices)
        ax.set_xlim(-1, len(data))
        ax.set_autoscalex_on(False)
        
        # Volume panel styling
        ax.set_facecolor('#0b0e11')
        ax.set_ylabel('Volume', fontsize=10, color='white')
        ax.tick_params(colors='white', which='both', length=3)
        ax.grid(True, alpha=0.2, color='gray', axis='y', linestyle='-')
        
        # Remove top and left spines
        ax.spines['top'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['right'].set_color('white')
        ax.spines['bottom'].set_color('white')
        
        # Format x-axis with timestamp labels (matching price panel)
        num_ticks = min(10, len(timestamps))
        if num_ticks > 1:
            tick_indices = np.linspace(0, len(timestamps) - 1, num_ticks, dtype=int)
            tick_positions = x_indices[tick_indices]
            ax.set_xticks(tick_positions)
            
            try:
                timestamp_labels = [pd.to_datetime(ts).strftime('%H:%M') for ts in timestamps[tick_indices]]
                ax.set_xticklabels(timestamp_labels, rotation=0, ha='center', color='white')
            except:
                ax.set_xticklabels([str(i) for i in tick_indices], rotation=0, ha='center', color='white')
        else:
            ax.set_xticks([])
