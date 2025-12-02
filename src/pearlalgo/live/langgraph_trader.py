"""
LangGraph Trader - Main trading loop with paper/live mode switching.

This is the entry point for the LangGraph multi-agent trading system.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:
    # Fallback if PyYAML not installed
    try:
        from yaml import safe_load
    except ImportError:
        yaml = None

import logging

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.agents.langgraph_workflow import TradingWorkflow
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.futures.config import load_profile

logger = logging.getLogger(__name__)


class LangGraphTrader:
    """
    Main trading system using LangGraph multi-agent workflow.
    
    Supports paper and live trading modes with one-click switching.
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        broker: Optional[str] = None,
        strategy: Optional[str] = None,
        mode: str = "paper",
    ):
        # Load configuration
        if config_path:
            with open(config_path, "r") as f:
                if yaml:
                    self.config = yaml.safe_load(f)
                else:
                    import json
                    self.config = json.load(f)
        else:
            # Default config path
            default_config = Path(__file__).parent.parent.parent.parent / "config" / "config.yaml"
            if default_config.exists():
                with open(default_config, "r") as f:
                    if yaml:
                        self.config = yaml.safe_load(f)
                    else:
                        import json
                        self.config = json.load(f)
            else:
                self.config = {}
        
        # Override with parameters
        self.symbols = symbols or self.config.get("symbols", {}).get("futures", [])
        if isinstance(self.symbols, list) and len(self.symbols) > 0 and isinstance(self.symbols[0], dict):
            # Extract symbol names from config
            self.symbols = [s["symbol"] for s in self.symbols]
        
        self.broker = broker or self.config.get("broker", {}).get("primary", "ibkr")
        self.strategy = strategy or self.config.get("strategy", {}).get("default", "sr")
        self.mode = mode or self.config.get("trading", {}).get("mode", "paper")
        
        # Load profile
        self.profile = load_profile()
        
        # Initialize portfolio
        starting_balance = (
            self.config.get("trading", {}).get("paper", {}).get("starting_balance", 50000.0)
            if self.mode == "paper"
            else self.config.get("trading", {}).get("live", {}).get("starting_balance", 50000.0)
        )
        
        self.portfolio = Portfolio(cash=starting_balance)
        
        # Initialize workflow
        self.workflow = TradingWorkflow(
            symbols=self.symbols,
            portfolio=self.portfolio,
            broker_name=self.broker,
            strategy=self.strategy,
            config=self.config,
        )
        
        logger.info(
            f"LangGraphTrader initialized: mode={self.mode}, "
            f"broker={self.broker}, strategy={self.strategy}, symbols={self.symbols}"
        )
    
    async def start(
        self,
        interval: int = 60,
        max_cycles: Optional[int] = None,
    ) -> None:
        """
        Start the trading system.
        
        Args:
            interval: Seconds between trading cycles
            max_cycles: Maximum number of cycles (None for infinite)
        """
        logger.info(f"Starting LangGraph trader: mode={self.mode}, interval={interval}s")
        
        if self.mode == "live":
            logger.warning("LIVE TRADING MODE - Real money will be used!")
            # Add confirmation prompt in production
        
        # Run continuous workflow
        await self.workflow.run_continuous(interval=interval, max_cycles=max_cycles)
    
    def run_single_cycle(self) -> None:
        """Run a single trading cycle (synchronous)."""
        asyncio.run(self.workflow.run_cycle())


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="LangGraph Multi-Agent Trading System")
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    parser.add_argument("--symbols", nargs="+", help="Trading symbols")
    parser.add_argument("--broker", type=str, choices=["ibkr", "bybit", "alpaca"], help="Broker")
    parser.add_argument("--strategy", type=str, help="Trading strategy")
    parser.add_argument("--mode", type=str, choices=["paper", "live"], default="paper", help="Trading mode")
    parser.add_argument("--interval", type=int, default=60, help="Cycle interval in seconds")
    parser.add_argument("--max-cycles", type=int, help="Maximum number of cycles")
    
    args = parser.parse_args()
    
    # Create trader
    trader = LangGraphTrader(
        config_path=args.config,
        symbols=args.symbols,
        broker=args.broker,
        strategy=args.strategy,
        mode=args.mode,
    )
    
    # Start trading
    asyncio.run(trader.start(interval=args.interval, max_cycles=args.max_cycles))


if __name__ == "__main__":
    main()

