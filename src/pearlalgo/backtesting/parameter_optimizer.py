"""
Parameter Optimizer for Options Backtesting

Compares different parameter sets, expiration selections, and strike selections.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class ParameterOptimizer:
    """
    Optimizes strategy parameters by comparing backtest results.
    """
    
    def __init__(self):
        """Initialize parameter optimizer."""
        logger.info("ParameterOptimizer initialized")
    
    def optimize_parameters(
        self,
        strategy,
        data: Dict,
        param_grid: Dict[str, List],
    ) -> List[Dict]:
        """
        Optimize parameters using grid search.
        
        Args:
            strategy: Strategy class or instance
            data: Historical data
            param_grid: Dictionary of parameter name -> list of values
            
        Returns:
            List of backtest results for each parameter combination
        """
        logger.info(f"Optimizing parameters: {list(param_grid.keys())}")
        
        results = []
        
        # Generate all parameter combinations
        from itertools import product
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        
        for param_combo in product(*param_values):
            params = dict(zip(param_names, param_combo))
            
            # Run backtest with these parameters
            # This would call the backtest engine with modified strategy
            result = {
                "parameters": params,
                "metrics": {},  # Would be populated by actual backtest
            }
            results.append(result)
        
        logger.info(f"Tested {len(results)} parameter combinations")
        return results
    
    def compare_results(self, results_list: List[Dict]) -> pd.DataFrame:
        """
        Compare multiple backtest results.
        
        Args:
            results_list: List of backtest result dictionaries
            
        Returns:
            DataFrame comparing all results
        """
        comparison_data = []
        
        for result in results_list:
            metrics = result.get("metrics", {})
            params = result.get("parameters", {})
            
            row = {**params, **metrics}
            comparison_data.append(row)
        
        df = pd.DataFrame(comparison_data)
        
        if len(df) > 0:
            logger.info(f"Compared {len(df)} backtest results")
            logger.info(f"Best total return: {df['total_return'].max():.2%}")
            logger.info(f"Best Sharpe ratio: {df['sharpe_ratio'].max():.2f}")
        
        return df
    
    def generate_report(self, backtest_results: List[Dict]) -> str:
        """
        Generate comparison report.
        
        Args:
            backtest_results: List of backtest results
            
        Returns:
            Formatted report string
        """
        df = self.compare_results(backtest_results)
        
        if df.empty:
            return "No results to compare"
        
        report = "Parameter Optimization Report\n"
        report += "=" * 50 + "\n\n"
        
        # Sort by total return
        df_sorted = df.sort_values("total_return", ascending=False)
        
        report += "Top 5 Parameter Sets:\n"
        report += "-" * 50 + "\n"
        
        for idx, row in df_sorted.head(5).iterrows():
            report += f"\nRank {idx + 1}:\n"
            report += f"  Parameters: {row.to_dict()}\n"
            report += f"  Total Return: {row.get('total_return', 0):.2%}\n"
            report += f"  Sharpe Ratio: {row.get('sharpe_ratio', 0):.2f}\n"
            report += f"  Max Drawdown: {row.get('max_drawdown', 0):.2%}\n"
            report += f"  Win Rate: {row.get('win_rate', 0):.2%}\n"
        
        return report
