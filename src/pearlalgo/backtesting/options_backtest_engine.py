"""
Options Backtesting Engine

Options-specific backtesting with time progression simulation.
Handles options expirations, contract rolls, and P&L tracking.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class OptionsBacktestEngine:
    """
    Options-specific backtesting engine with time progression.
    
    Features:
    - Bar-by-bar simulation
    - Options expiration handling
    - Contract roll simulation (for ES/NQ correlation)
    - P&L tracking
    - Performance metrics calculation
    """
    
    def __init__(
        self,
        initial_cash: float = 100000.0,
        commission_per_contract: float = 0.85,
    ):
        """
        Initialize backtesting engine.
        
        Args:
            initial_cash: Starting capital
            commission_per_contract: Commission per options contract
        """
        self.initial_cash = initial_cash
        self.commission_per_contract = commission_per_contract
        
        logger.info(f"OptionsBacktestEngine initialized: initial_cash=${initial_cash:,.2f}")
    
    def run_backtest(
        self,
        strategy,
        start_date: datetime,
        end_date: datetime,
        underliers: List[str],
        historical_data: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Dict:
        """
        Run backtest on historical data.
        
        Args:
            strategy: Strategy instance with generate_signals method
            start_date: Start date
            end_date: End date
            underliers: List of underlying symbols (e.g., ["QQQ", "SPY"])
            historical_data: Dictionary of symbol -> DataFrame (optional, will fetch if not provided)
            
        Returns:
            Dictionary with backtest results
        """
        logger.info(f"Running options backtest: {underliers}, {start_date.date()} to {end_date.date()}")
        
        # Initialize state
        cash = self.initial_cash
        positions = {}  # symbol -> {contract, entry_price, size, entry_time}
        trades = []
        equity_curve = []
        
        # Get historical data (simplified - would need actual data provider)
        if historical_data is None:
            logger.warning("No historical data provided, using simulated data")
            historical_data = self._generate_simulated_data(underliers, start_date, end_date)
        
        # Align timestamps across all symbols
        aligned_data = self._align_data(historical_data)
        
        if not aligned_data:
            return {"error": "No data available for backtest"}
        
        # Get common timestamps
        timestamps = list(aligned_data.values())[0].index
        timestamps = timestamps[(timestamps >= start_date) & (timestamps <= end_date)]
        
        # Simulate time progression
        for timestamp in timestamps:
            current_prices = {}
            for symbol, df in aligned_data.items():
                if timestamp in df.index:
                    current_prices[symbol] = df.loc[timestamp, 'close']
            
            # Apply strategy logic
            signals = self._apply_strategy_logic(
                strategy, timestamp, current_prices, positions, historical_data
            )
            
            # Process signals (enter positions)
            for signal in signals:
                if signal.get("side") != "flat":
                    cash, positions = self._enter_position(
                        signal, timestamp, cash, positions, trades
                    )
            
            # Check for exits (stop loss, take profit, expiration)
            cash, positions, trades = self._check_exits(
                timestamp, current_prices, cash, positions, trades
            )
            
            # Track equity
            total_equity = cash + self._calculate_unrealized_pnl(positions, current_prices)
            equity_curve.append({
                "timestamp": timestamp,
                "equity": total_equity,
                "cash": cash,
                "positions": len(positions),
            })
        
        # Calculate metrics
        metrics = self.calculate_metrics(equity_curve, trades)
        
        return {
            "equity_curve": pd.DataFrame(equity_curve).set_index("timestamp"),
            "trades": pd.DataFrame(trades),
            "metrics": metrics,
            "final_equity": equity_curve[-1]["equity"] if equity_curve else self.initial_cash,
            "total_return": (equity_curve[-1]["equity"] - self.initial_cash) / self.initial_cash if equity_curve else 0.0,
        }
    
    def simulate_time_progression(
        self,
        data: Dict[str, pd.DataFrame],
        strategy,
    ) -> List[Dict]:
        """
        Simulate time progression bar-by-bar.
        
        Args:
            data: Dictionary of symbol -> DataFrame
            strategy: Strategy instance
            
        Returns:
            List of state snapshots
        """
        # This is called by run_backtest internally
        # Kept as separate method for clarity
        pass
    
    def apply_strategy_logic(
        self,
        timestamp: datetime,
        market_data: Dict[str, float],
        positions: Dict,
    ) -> List[Dict]:
        """
        Apply strategy logic at a given timestamp.
        
        Args:
            timestamp: Current timestamp
            market_data: Dictionary of symbol -> current price
            positions: Current positions
            
        Returns:
            List of signals
        """
        # This would call the strategy's generate_signals method
        # Simplified for now
        return []
    
    def track_pnl(
        self,
        positions: Dict,
        current_prices: Dict[str, float],
    ) -> Tuple[float, float]:
        """
        Track P&L for current positions.
        
        Args:
            positions: Current positions
            current_prices: Current prices for all symbols
            
        Returns:
            Tuple of (realized_pnl, unrealized_pnl)
        """
        realized = 0.0
        unrealized = 0.0
        
        for symbol, position in positions.items():
            current_price = current_prices.get(symbol, 0)
            if current_price > 0:
                entry_price = position.get("entry_price", 0)
                size = position.get("size", 0)
                pnl = (current_price - entry_price) * size
                unrealized += pnl
        
        return realized, unrealized
    
    def calculate_metrics(self, equity_curve: List[Dict], trades: List[Dict]) -> Dict:
        """
        Calculate performance metrics.
        
        Args:
            equity_curve: List of equity snapshots
            trades: List of completed trades
            
        Returns:
            Dictionary of metrics
        """
        if not equity_curve or not trades:
            return {
                "total_return": 0.0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "total_trades": 0,
            }
        
        # Calculate returns
        equity_df = pd.DataFrame(equity_curve)
        equity_df["returns"] = equity_df["equity"].pct_change()
        
        # Total return
        total_return = (equity_df["equity"].iloc[-1] - equity_df["equity"].iloc[0]) / equity_df["equity"].iloc[0]
        
        # Win rate
        trades_df = pd.DataFrame(trades)
        if len(trades_df) > 0 and "pnl" in trades_df.columns:
            winning_trades = trades_df[trades_df["pnl"] > 0]
            win_rate = len(winning_trades) / len(trades_df) if len(trades_df) > 0 else 0.0
        else:
            win_rate = 0.0
        
        # Max drawdown
        equity_series = equity_df["equity"]
        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max
        max_drawdown = abs(drawdown.min())
        
        # Sharpe ratio (simplified)
        returns = equity_df["returns"].dropna()
        if len(returns) > 0 and returns.std() > 0:
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252)  # Annualized
        else:
            sharpe_ratio = 0.0
        
        return {
            "total_return": float(total_return),
            "win_rate": float(win_rate),
            "max_drawdown": float(max_drawdown),
            "sharpe_ratio": float(sharpe_ratio),
            "total_trades": len(trades),
            "profit_factor": self._calculate_profit_factor(trades_df) if len(trades_df) > 0 else 0.0,
        }
    
    def _apply_strategy_logic(
        self,
        strategy,
        timestamp: datetime,
        current_prices: Dict[str, float],
        positions: Dict,
        historical_data: Dict[str, pd.DataFrame],
    ) -> List[Dict]:
        """Apply strategy logic at timestamp."""
        # Simplified - would call strategy.generate_signals()
        return []
    
    def _enter_position(
        self,
        signal: Dict,
        timestamp: datetime,
        cash: float,
        positions: Dict,
        trades: List[Dict],
    ) -> Tuple[float, Dict]:
        """Enter a new position."""
        entry_price = signal.get("entry_price", 0)
        size = signal.get("position_size", 1)
        symbol = signal.get("option_symbol") or signal.get("symbol")
        
        if entry_price <= 0 or size == 0:
            return cash, positions
        
        # Calculate cost
        cost = entry_price * size
        commission = self.commission_per_contract * size
        
        if cash < (cost + commission):
            logger.debug(f"Insufficient cash to enter position: {symbol}")
            return cash, positions
        
        # Enter position
        cash -= (cost + commission)
        positions[symbol] = {
            "contract": symbol,
            "entry_price": entry_price,
            "size": size,
            "entry_time": timestamp,
            "stop_loss": signal.get("stop_loss"),
            "take_profit": signal.get("take_profit"),
            "signal": signal,
        }
        
        trades.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "action": "enter",
            "price": entry_price,
            "size": size,
            "cost": cost + commission,
        })
        
        return cash, positions
    
    def _check_exits(
        self,
        timestamp: datetime,
        current_prices: Dict[str, float],
        cash: float,
        positions: Dict,
        trades: List[Dict],
    ) -> Tuple[float, Dict, List[Dict]]:
        """Check for exit conditions."""
        positions_to_close = []
        
        for symbol, position in list(positions.items()):
            current_price = current_prices.get(symbol, 0)
            if current_price <= 0:
                continue
            
            entry_price = position.get("entry_price", 0)
            size = position.get("size", 0)
            stop_loss = position.get("stop_loss")
            take_profit = position.get("take_profit")
            entry_time = position.get("entry_time")
            
            # Check stop loss
            if stop_loss and size > 0:
                if current_price <= stop_loss:
                    positions_to_close.append((symbol, "stop_loss", current_price))
                    continue
            
            # Check take profit
            if take_profit and size > 0:
                if current_price >= take_profit:
                    positions_to_close.append((symbol, "take_profit", current_price))
                    continue
            
            # Check expiration (simplified - would need actual expiration dates)
            # Check time-based exit
            time_exit_hours = position.get("signal", {}).get("time_exit_hours", 0)
            if time_exit_hours > 0 and entry_time:
                hours_held = (timestamp - entry_time).total_seconds() / 3600
                if hours_held >= time_exit_hours:
                    positions_to_close.append((symbol, "time_exit", current_price))
                    continue
        
        # Close positions
        for symbol, exit_reason, exit_price in positions_to_close:
            position = positions.pop(symbol)
            entry_price = position.get("entry_price", 0)
            size = position.get("size", 0)
            
            # Calculate P&L
            proceeds = exit_price * size
            commission = self.commission_per_contract * size
            pnl = (exit_price - entry_price) * size - commission * 2  # Entry + exit commission
            
            cash += proceeds - commission
            
            trades.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": "exit",
                "price": exit_price,
                "size": size,
                "pnl": pnl,
                "exit_reason": exit_reason,
            })
        
        return cash, positions, trades
    
    def _calculate_unrealized_pnl(self, positions: Dict, current_prices: Dict[str, float]) -> float:
        """Calculate unrealized P&L."""
        unrealized = 0.0
        for symbol, position in positions.items():
            current_price = current_prices.get(symbol, 0)
            if current_price > 0:
                entry_price = position.get("entry_price", 0)
                size = position.get("size", 0)
                unrealized += (current_price - entry_price) * size
        return unrealized
    
    def _align_data(self, data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """Align timestamps across dataframes."""
        if not data:
            return {}
        
        # Get common timestamps
        common_index = None
        for df in data.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)
        
        # Reindex all dataframes
        aligned = {}
        for symbol, df in data.items():
            aligned[symbol] = df.reindex(common_index)
        
        return aligned
    
    def _generate_simulated_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, pd.DataFrame]:
        """Generate simulated data for testing."""
        # This would be replaced with actual data loading
        data = {}
        dates = pd.date_range(start_date, end_date, freq="15min")
        
        for symbol in symbols:
            # Simple random walk
            prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
            data[symbol] = pd.DataFrame({
                "open": prices,
                "high": prices * 1.01,
                "low": prices * 0.99,
                "close": prices,
                "volume": np.random.randint(1000, 10000, len(dates)),
            }, index=dates)
        
        return data
    
    def _calculate_profit_factor(self, trades_df: pd.DataFrame) -> float:
        """Calculate profit factor."""
        if "pnl" not in trades_df.columns or len(trades_df) == 0:
            return 0.0
        
        gross_profit = trades_df[trades_df["pnl"] > 0]["pnl"].sum()
        gross_loss = abs(trades_df[trades_df["pnl"] < 0]["pnl"].sum())
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        
        return float(gross_profit / gross_loss)
