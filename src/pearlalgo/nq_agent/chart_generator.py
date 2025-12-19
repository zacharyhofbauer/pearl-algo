"""
Chart Generator for NQ Agent

Generates professional trading charts with entry, stop loss, and take profit levels.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
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
        self.dpi = 100
    
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
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor='black')
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
            plt.savefig(temp_path, dpi=self.dpi, bbox_inches='tight', facecolor='black')
            plt.close(fig)
            
            logger.debug(f"Generated exit chart: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error generating exit chart: {e}", exc_info=True)
            if 'fig' in locals():
                plt.close(fig)
            return None
    
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
        
        # Plot candlesticks
        for i, (ts, open_val, high_val, low_val, close_val) in enumerate(
            zip(timestamps, opens, highs, lows, closes)
        ):
            color = 'green' if close_val >= open_val else 'red'
            alpha = 0.8
            
            # Draw the wick
            ax.plot([ts, ts], [low_val, high_val], color=color, linewidth=0.5, alpha=alpha)
            
            # Draw the body
            body_height = abs(close_val - open_val)
            body_bottom = min(open_val, close_val)
            rect = Rectangle(
                (mdates.date2num(ts) - 0.3, body_bottom),
                0.6,
                body_height,
                facecolor=color,
                edgecolor=color,
                alpha=alpha
            )
            ax.add_patch(rect)
        
        # Plot entry, stop, and TP lines
        entry_color = 'lime' if direction == 'long' else 'orange'
        ax.axhline(y=entry_price, color=entry_color, linestyle='-', linewidth=2, 
                  label=f'Entry: ${entry_price:.2f}', alpha=0.8)
        
        if stop_loss and stop_loss > 0:
            ax.axhline(y=stop_loss, color='red', linestyle='--', linewidth=2,
                      label=f'Stop: ${stop_loss:.2f}', alpha=0.8)
        
        if take_profit and take_profit > 0:
            ax.axhline(y=take_profit, color='green', linestyle='--', linewidth=2,
                      label=f'TP: ${take_profit:.2f}', alpha=0.8)
        
        # Formatting
        ax.set_ylabel('Price ($)', fontsize=10, color='white')
        ax.grid(True, alpha=0.3, color='gray')
        ax.legend(loc='upper left', fontsize=8, facecolor='black', edgecolor='white')
        ax.tick_params(colors='white')
        
        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, len(data) // 10)))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
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
        
        # Plot candlesticks
        for i, (ts, open_val, high_val, low_val, close_val) in enumerate(
            zip(timestamps, opens, highs, lows, closes)
        ):
            color = 'green' if close_val >= open_val else 'red'
            alpha = 0.8
            
            # Draw the wick
            ax.plot([ts, ts], [low_val, high_val], color=color, linewidth=0.5, alpha=alpha)
            
            # Draw the body
            body_height = abs(close_val - open_val)
            body_bottom = min(open_val, close_val)
            rect = Rectangle(
                (mdates.date2num(ts) - 0.3, body_bottom),
                0.6,
                body_height,
                facecolor=color,
                edgecolor=color,
                alpha=alpha
            )
            ax.add_patch(rect)
        
        # Plot entry line
        entry_color = 'lime' if direction == 'long' else 'orange'
        ax.axhline(y=entry_price, color=entry_color, linestyle='-', linewidth=2,
                  label=f'Entry: ${entry_price:.2f}', alpha=0.8)
        
        # Plot exit line
        exit_color = 'cyan'
        ax.axhline(y=exit_price, color=exit_color, linestyle='-', linewidth=2,
                  label=f'Exit: ${exit_price:.2f} ({exit_reason})', alpha=0.8)
        
        # Plot stop and TP lines (dashed for reference)
        if stop_loss and stop_loss > 0:
            ax.axhline(y=stop_loss, color='red', linestyle='--', linewidth=1.5,
                      label=f'Stop: ${stop_loss:.2f}', alpha=0.6)
        
        if take_profit and take_profit > 0:
            ax.axhline(y=take_profit, color='green', linestyle='--', linewidth=1.5,
                      label=f'TP: ${take_profit:.2f}', alpha=0.6)
        
        # Add P&L annotation
        pnl_color = 'green' if pnl > 0 else 'red'
        pnl_text = f"P&L: ${pnl:,.2f}"
        ax.text(0.02, 0.98, pnl_text, transform=ax.transAxes,
               fontsize=12, fontweight='bold', color=pnl_color,
               verticalalignment='top', bbox=dict(boxstyle='round', 
               facecolor='black', edgecolor=pnl_color, alpha=0.8))
        
        # Formatting
        ax.set_ylabel('Price ($)', fontsize=10, color='white')
        ax.grid(True, alpha=0.3, color='gray')
        ax.legend(loc='upper left', fontsize=8, facecolor='black', edgecolor='white')
        ax.tick_params(colors='white')
        
        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, len(data) // 10)))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    def _plot_volume(self, ax, data: pd.DataFrame):
        """Plot volume bars."""
        if "volume" not in data.columns:
            return
        
        timestamps = data["timestamp"].values
        volumes = data["volume"].values
        
        # Plot volume bars
        colors = ['green' if data.iloc[i]["close"] >= data.iloc[i]["open"] 
                 else 'red' for i in range(len(data))]
        
        ax.bar(timestamps, volumes, color=colors, alpha=0.6, width=0.8)
        ax.set_ylabel('Volume', fontsize=10, color='white')
        ax.tick_params(colors='white')
        ax.grid(True, alpha=0.3, color='gray', axis='y')
        
        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, len(data) // 10)))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
