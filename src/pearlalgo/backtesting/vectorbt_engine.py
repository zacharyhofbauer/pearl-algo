"""
VectorBT Backtesting Engine - Vectorized backtesting with performance metrics.

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

from pearlalgo.futures.signals import generate_signal

logger = logging.getLogger(__name__)


class VectorBTBacktestEngine:
    """
    Vectorized backtesting engine using vectorbt.

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
    ) -> Dict:
        """
        Run backtest on historical data.

        Args:
            data: OHLCV DataFrame with datetime index
            symbol: Symbol being backtested
            strategy: Strategy name (sr, ma_cross, breakout, mean_reversion)
            strategy_params: Strategy-specific parameters

        Returns:
            Dictionary with backtest results including:
            - equity_curve: pd.Series
            - trades: pd.DataFrame
            - performance_metrics: Dict
        """
        logger.info(f"Running vectorbt backtest: {symbol}, strategy={strategy}")

        # Generate signals
        signals_df = self._generate_signals(data, symbol, strategy, strategy_params)

        # Create entries and exits
        entries = signals_df["entry"] > 0
        exits = signals_df["entry"] < 0

        # Run vectorbt backtest
        pf = vbt.Portfolio.from_signals(
            data["Close"],
            entries=entries,
            exits=exits,
            size=signals_df["size"].abs(),
            fees=self.commission,
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
    ) -> pd.DataFrame:
        """Generate signals for backtesting."""
        signals_list = []

        # Generate signals for each bar (rolling window)
        for i in range(50, len(data)):  # Start after enough data for indicators
            window_data = data.iloc[: i + 1]

            # Generate signal
            signal_dict = generate_signal(
                symbol,
                window_data,
                strategy_name=strategy,
                **(strategy_params or {}),
            )

            # Create signal row
            signal_row = {
                "timestamp": data.index[i],
                "entry": 1
                if signal_dict["side"] == "long"
                else (-1 if signal_dict["side"] == "short" else 0),
                "size": abs(signal_dict.get("size", 1))
                if signal_dict["side"] != "flat"
                else 0,
                "price": data["Close"].iloc[i],
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
