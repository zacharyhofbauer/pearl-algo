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
        # Check confidence threshold (higher threshold for better quality)
        confidence = signal.get("confidence", 0)
        if confidence < 0.55:  # Require at least 55% confidence
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
        
        # Validate risk/reward ratio meets minimum
        if stop_loss and take_profit:
            if signal["direction"] == "long":
                risk = entry_price - stop_loss
                reward = take_profit - entry_price
            else:
                risk = stop_loss - entry_price
                reward = entry_price - take_profit
            
            if risk > 0:
                risk_reward = reward / risk
                if risk_reward < 1.5:  # Require at least 1.5:1 R/R
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
        
        # Calculate risk amount and expected hold time
        entry_price = signal.get("entry_price", 0)
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")
        
        if entry_price > 0 and stop_loss:
            if signal["direction"] == "long":
                risk_amount = abs(entry_price - stop_loss) * self.config.max_position_size * 20  # NQ tick value
            else:
                risk_amount = abs(stop_loss - entry_price) * self.config.max_position_size * 20
            formatted["risk_amount"] = risk_amount
        
        # Expected hold time (intraday signals typically 15-60 minutes)
        formatted["expected_hold_minutes"] = 30
        
        # Add market context
        latest_bar = market_data.get("latest_bar")
        df = market_data.get("df")
        if latest_bar:
            formatted["market_data"] = {
                "price": latest_bar.get("close"),
                "volume": latest_bar.get("volume"),
                "bid": latest_bar.get("bid"),
                "ask": latest_bar.get("ask"),
            }
        
        # Add indicator values for context
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            formatted["indicators"] = {
                "rsi": float(latest.get("rsi", 0)) if "rsi" in latest else None,
                "atr": float(latest.get("atr", 0)) if "atr" in latest else None,
                "volume_ratio": float(latest.get("volume_ratio", 0)) if "volume_ratio" in latest else None,
                "macd_histogram": float(latest.get("macd_histogram", 0)) if "macd_histogram" in latest else None,
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
        signal_time = datetime.fromisoformat(signal.get("timestamp", datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
        signal_entry = signal.get("entry_price", 0)
        
        for recent in self._recent_signals:
            recent_time = datetime.fromisoformat(recent.get("timestamp", "").replace("Z", "+00:00"))
            time_diff = (signal_time - recent_time).total_seconds()
            recent_entry = recent.get("entry_price", 0)
            
            # Check if same type and direction within time window
            same_type = recent.get("type") == signal.get("type")
            same_direction = recent.get("direction") == signal.get("direction")
            within_time_window = time_diff < self._signal_window_seconds
            
            # Also check if price is too close (within 0.5% for same signal)
            price_close = False
            if recent_entry > 0 and signal_entry > 0:
                price_diff_pct = abs(signal_entry - recent_entry) / recent_entry
                price_close = price_diff_pct < 0.005  # 0.5%
            
            if same_type and same_direction and (within_time_window or price_close):
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
