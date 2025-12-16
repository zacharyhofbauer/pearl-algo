"""
NQ Intraday Strategy

Main strategy class that coordinates scanner and signal generation.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.signal_generator import NQSignalGenerator


class NQIntradayStrategy:
    """
    NQ Intraday Trading Strategy.
    
    Coordinates scanning and signal generation for NQ futures.
    """

    def __init__(self, config: Optional[NQIntradayConfig] = None):
        """
        Initialize strategy.
        
        Args:
            config: Configuration instance (optional)
        """
        self.config = config or NQIntradayConfig()
        self.scanner = NQScanner(config=self.config)
        self.signal_generator = NQSignalGenerator(config=self.config, scanner=self.scanner)

        logger.info(f"NQIntradayStrategy initialized: symbol={self.config.symbol}")

    def analyze(self, market_data: Dict) -> List[Dict]:
        """
        Analyze market data and generate signals.
        
        Args:
            market_data: Dictionary with 'df' (DataFrame) and optionally 'latest_bar' (Dict)
            
        Returns:
            List of trading signals
        """
        try:
            signals = self.signal_generator.generate(market_data)
            return signals
        except Exception as e:
            logger.error(f"Error analyzing market data: {e}", exc_info=True)
            return []

    def get_config(self) -> NQIntradayConfig:
        """Get strategy configuration."""
        return self.config
