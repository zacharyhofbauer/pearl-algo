"""
NQ Intraday Signal Generator

Generates trading signals from scanner results with validation and filtering.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.scanner import NQScanner


class NQSignalGenerator:
    """
    Signal generator for NQ intraday strategy.
    
    Processes scanner results and generates validated trading signals.
    """
    
    def __init__(
        self,
        config: Optional[NQIntradayConfig] = None,
        scanner: Optional[NQScanner] = None,
    ):
        """
        Initialize signal generator.
        
        Args:
            config: Configuration instance (optional)
            scanner: Scanner instance (optional, creates new if not provided)
        """
        self.config = config or NQIntradayConfig()
        self.scanner = scanner or NQScanner(config=self.config)
        
        # Track recent signals to avoid duplicates
        self._recent_signals: List[Dict] = []
        self._signal_window_seconds = 300  # 5 minutes
        
        logger.info("NQSignalGenerator initialized")
    
    def generate(self, market_data: Dict) -> List[Dict]:
        """
        Generate trading signals from market data.
        
        Args:
            market_data: Dictionary with 'df' (DataFrame) and optionally 'latest_bar' (Dict)
            
        Returns:
            List of validated signal dictionaries
        """
        df = market_data.get("df")
        if df is None or df.empty:
            return []
        
        # Check market hours
        if not self.scanner.is_market_hours():
            return []
        
        # Scan for signals
        raw_signals = self.scanner.scan(df)
        
        # Validate and filter signals
        validated_signals = []
        for signal in raw_signals:
            if self._validate_signal(signal):
                validated_signal = self._format_signal(signal, market_data)
                if not self._is_duplicate(validated_signal):
                    validated_signals.append(validated_signal)
                    self._recent_signals.append(validated_signal)
        
        # Clean up old signals from recent list
        self._cleanup_recent_signals()
        
        if validated_signals:
            logger.info(f"Generated {len(validated_signals)} validated signal(s)")
        
        return validated_signals
    
    def _validate_signal(self, signal: Dict) -> bool:
        """
        Validate a signal meets criteria.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            True if signal is valid
        """
        # Check confidence threshold
        if signal.get("confidence", 0) < 0.5:
            return False
        
        # Check entry price is valid
        entry_price = signal.get("entry_price")
        if not entry_price or entry_price <= 0:
            return False
        
        # Check stop loss and take profit are valid
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")
        
        if signal["direction"] == "long":
            if stop_loss and stop_loss >= entry_price:
                return False
            if take_profit and take_profit <= entry_price:
                return False
        else:  # short
            if stop_loss and stop_loss <= entry_price:
                return False
            if take_profit and take_profit >= entry_price:
                return False
        
        return True
    
    def _format_signal(self, signal: Dict, market_data: Dict) -> Dict:
        """
        Format signal with additional metadata.
        
        Args:
            signal: Raw signal dictionary
            market_data: Market data context
            
        Returns:
            Formatted signal dictionary
        """
        formatted = signal.copy()
        
        # Add metadata
        formatted["symbol"] = self.config.symbol
        formatted["timestamp"] = datetime.now(timezone.utc).isoformat()
        formatted["strategy"] = "nq_intraday"
        formatted["timeframe"] = self.config.timeframe
        
        # Add market context
        latest_bar = market_data.get("latest_bar")
        if latest_bar:
            formatted["market_data"] = {
                "price": latest_bar.get("close"),
                "volume": latest_bar.get("volume"),
                "bid": latest_bar.get("bid"),
                "ask": latest_bar.get("ask"),
            }
        
        return formatted
    
    def _is_duplicate(self, signal: Dict) -> bool:
        """
        Check if signal is a duplicate of a recent signal.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            True if duplicate
        """
        signal_time = datetime.fromisoformat(signal["timestamp"].replace("Z", "+00:00"))
        
        for recent in self._recent_signals:
            recent_time = datetime.fromisoformat(recent["timestamp"].replace("Z", "+00:00"))
            time_diff = (signal_time - recent_time).total_seconds()
            
            # Same type and direction within time window
            if (
                recent["type"] == signal["type"]
                and recent["direction"] == signal["direction"]
                and time_diff < self._signal_window_seconds
            ):
                return True
        
        return False
    
    def _cleanup_recent_signals(self) -> None:
        """Remove old signals from recent signals list."""
        now = datetime.now(timezone.utc)
        self._recent_signals = [
            s for s in self._recent_signals
            if (now - datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00"))).total_seconds()
            < self._signal_window_seconds
        ]
