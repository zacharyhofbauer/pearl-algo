"""
VectorBT Backtesting Engine - Vectorized backtesting with performance metrics.

Enhanced to support:
- Options data backtesting
- ES/NQ historical data integration
- Multi-symbol correlation analysis

One-line command: pearlalgo backtest --symbol ES --strategy sr --start 2024-01-01
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import vectorbt as vbt

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class VectorBTBacktestEngine:
    """
    Vectorized backtesting engine using vectorbt.
    
    Enhanced to support:
    - Options data backtesting
    - ES/NQ historical data for correlation
    - Multi-symbol backtesting

    Provides fast backtesting with equity curve generation and performance metrics.
    """

    def __init__(
        self,
        initial_cash: float = 100000.0,
        commission: float = 0.85,
    ):
        self.initial_cash = initial_cash
        self.commission = commission

    def run_backtest(
        self,
        data: pd.DataFrame,
        symbol: str,
        strategy: str = "sr",
        strategy_params: Optional[Dict] = None,
        es_nq_data: Optional[Dict[str, pd.DataFrame]] = None,
        is_options: bool = False,
    ) -> Dict:
        """
        Run backtest on historical data.
        
        Enhanced to support options and ES/NQ correlation data.

        Args:
            data: OHLCV DataFrame with datetime index
            symbol: Symbol being backtested
            strategy: Strategy name (sr, ma_cross, breakout, mean_reversion)
            strategy_params: Strategy-specific parameters
            es_nq_data: Optional ES/NQ data for correlation (dict of symbol -> DataFrame)
            is_options: Whether data is options data (affects commission calculation)

        Returns:
            Dictionary with backtest results including:
            - equity_curve: pd.Series
            - trades: pd.DataFrame
            - performance_metrics: Dict
        """
        logger.info(f"Running vectorbt backtest: {symbol}, strategy={strategy}, is_options={is_options}")

        # Adjust commission for options if needed
        commission = self.commission
        if is_options:
            # Options typically have different commission structure
            commission = strategy_params.get("options_commission", self.commission) if strategy_params else self.commission

        # Generate signals (with ES/NQ correlation if provided)
        signals_df = self._generate_signals(
            data, symbol, strategy, strategy_params, es_nq_data
        )

        # Create entries and exits
        entries = signals_df["entry"] > 0
        exits = signals_df["entry"] < 0

        # Use appropriate price column
        price_col = "close" if "close" in data.columns else "Close"
        if price_col not in data.columns:
            logger.error(f"Price column not found in data. Available columns: {list(data.columns)}")
            raise ValueError(f"Price column '{price_col}' not found")

        # Run vectorbt backtest
        pf = vbt.Portfolio.from_signals(
            data[price_col],
            entries=entries,
            exits=exits,
            size=signals_df["size"].abs(),
            fees=commission,
            init_cash=self.initial_cash,
            freq="1D",  # Adjust based on data frequency
        )

        # Extract results
        equity_curve = pf.value()
        trades = pf.trades.records_readable

        # Calculate performance metrics
        performance_metrics = {
            "total_return": pf.total_return(),
            "sharpe_ratio": pf.sharpe_ratio(),
            "max_drawdown": pf.max_drawdown(),
            "win_rate": pf.trades.win_rate(),
            "total_trades": len(trades),
            "profit_factor": pf.trades.profit_factor(),
        }

        logger.info(
            f"Backtest complete: {performance_metrics['total_trades']} trades, "
            f"return={performance_metrics['total_return'] * 100:.2f}%"
        )

        return {
            "equity_curve": equity_curve,
            "trades": trades,
            "performance_metrics": performance_metrics,
            "portfolio": pf,
        }

    def _generate_signals(
        self,
        data: pd.DataFrame,
        symbol: str,
        strategy: str,
        strategy_params: Optional[Dict],
        es_nq_data: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> pd.DataFrame:
        """
        Generate signals for backtesting.
        
        Enhanced to use ES/NQ data for correlation if provided.
        """
        signals_list = []
        
        # Import strategy function (fallback to simple implementation)
        try:
            from pearlalgo.strategies.base import generate_signal
        except ImportError:
            # Fallback: simple signal generation
            def generate_signal(symbol, data, strategy_name, **params):
                # Simple momentum strategy as fallback
                if len(data) < 20:
                    return {"side": "flat", "confidence": 0.0, "size": 0}
                
                price_col = "close" if "close" in data.columns else "Close"
                recent_prices = data[price_col].tail(20)
                price_change = (recent_prices.iloc[-1] - recent_prices.iloc[0]) / recent_prices.iloc[0]
                
                if price_change > 0.01:
                    return {"side": "long", "confidence": 0.6, "size": 1}
                elif price_change < -0.01:
                    return {"side": "short", "confidence": 0.6, "size": 1}
                else:
                    return {"side": "flat", "confidence": 0.0, "size": 0}

        # Generate signals for each bar (rolling window)
        for i in range(50, len(data)):  # Start after enough data for indicators
            window_data = data.iloc[: i + 1]
            
            # Include ES/NQ correlation data if available
            correlation_data = {}
            if es_nq_data:
                for corr_symbol, corr_df in es_nq_data.items():
                    if i < len(corr_df):
                        correlation_data[corr_symbol] = corr_df.iloc[: i + 1]

            # Generate signal
            signal_dict = generate_signal(
                symbol,
                window_data,
                strategy_name=strategy,
                correlation_data=correlation_data if correlation_data else None,
                **(strategy_params or {}),
            )

            # Create signal row
            price_col = "close" if "close" in data.columns else "Close"
            signal_row = {
                "timestamp": data.index[i],
                "entry": 1
                if signal_dict["side"] == "long"
                else (-1 if signal_dict["side"] == "short" else 0),
                "size": abs(signal_dict.get("size", 1))
                if signal_dict["side"] != "flat"
                else 0,
                "price": data[price_col].iloc[i],
                "side": signal_dict["side"],
                "confidence": signal_dict.get("confidence", 0.5),
            }
            signals_list.append(signal_row)

        # Create DataFrame
        signals_df = pd.DataFrame(signals_list)
        signals_df.set_index("timestamp", inplace=True)

        return signals_df

    def plot_results(
        self,
        results: Dict,
        output_path: Optional[Path] = None,
    ) -> None:
        """
        Plot backtest results (equity curve, trades, etc.).

        Args:
            results: Results dictionary from run_backtest
            output_path: Optional path to save plot
        """
        try:
            pf = results["portfolio"]

            # Plot equity curve and trades
            fig = pf.plot()

            if output_path:
                fig.write_image(str(output_path))
                logger.info(f"Plot saved to {output_path}")
            else:
                fig.show()

        except Exception as e:
            logger.warning(f"Failed to plot results: {e}")


def run_backtest_cli(
    data_path: str,
    symbol: str,
    strategy: str = "sr",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    initial_cash: float = 100000.0,
    commission: float = 0.85,
    output_dir: Optional[str] = None,
) -> Dict:
    """
    CLI-friendly backtest function.

    Usage:
        python -m pearlalgo.backtesting.vectorbt_engine --data data.csv --symbol ES --strategy sr
    """
    # Load data
    data = pd.read_csv(data_path, index_col=0, parse_dates=True)

    # Filter by date range
    if start_date:
        data = data[data.index >= pd.to_datetime(start_date)]
    if end_date:
        data = data[data.index <= pd.to_datetime(end_date)]

    # Run backtest
    engine = VectorBTBacktestEngine(
        initial_cash=initial_cash,
        commission=commission,
    )

    results = engine.run_backtest(data, symbol, strategy)

    # Save results if output_dir provided
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save equity curve
        results["equity_curve"].to_csv(output_path / "equity_curve.csv")

        # Save trades
        results["trades"].to_csv(output_path / "trades.csv")

        # Save metrics
        import json

        with open(output_path / "metrics.json", "w") as f:
            json.dump(results["performance_metrics"], f, indent=2)

        # Plot
        engine.plot_results(results, output_path / "backtest_plot.png")

        logger.info(f"Backtest results saved to {output_dir}")

    return results
