"""
LangGraph Trader - Main trading loop with paper/live mode switching.

This is the entry point for the LangGraph multi-agent trading system.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import warnings
from pathlib import Path
from typing import List, Optional

# Suppress noisy warnings from third-party libraries
warnings.filterwarnings('ignore', message='.*Task exception was never retrieved.*')
warnings.filterwarnings('ignore', message='.*This event loop is already running.*')

try:
    import yaml
except ImportError:
    yaml = None


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
        strategy: Optional[str] = None,
        mode: str = "paper",
    ):
        # Load configuration
        import os
        import re
        
        def expand_env_vars(obj):
            """Recursively expand ${VAR} environment variables in config."""
            if isinstance(obj, dict):
                return {k: expand_env_vars(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [expand_env_vars(item) for item in obj]
            elif isinstance(obj, str):
                # Match ${VAR} or ${VAR:-default} (handles both ${VAR} and \${VAR} from YAML)
                def replace_env(match):
                    var_expr = match.group(1)
                    if ':-' in var_expr:
                        var_name, default = var_expr.split(':-', 1)
                        return os.getenv(var_name.strip(), default)
                    else:
                        var_name = var_expr.strip()
                        env_value = os.getenv(var_name)
                        if env_value:
                            return env_value
                        # Return original if not found (keep ${VAR} in config)
                        return match.group(0)
                # Match ${VAR} pattern
                result = re.sub(r'\$\{([^}]+)\}', replace_env, obj)
                return result
            return obj
        
        if config_path:
            with open(config_path, "r") as f:
                if yaml:
                    self.config = yaml.safe_load(f)  # noqa: F401
                else:
                    import json

                    self.config = json.load(f)
        else:
            # Default config path
            default_config = (
                Path(__file__).parent.parent.parent.parent / "config" / "config.yaml"
            )
            if default_config.exists():
                with open(default_config, "r") as f:
                    if yaml:
                        self.config = yaml.safe_load(f)
                    else:
                        import json

                        self.config = json.load(f)
            else:
                self.config = {}
        
        # Expand environment variables in config
        self.config = expand_env_vars(self.config)

        # Override with parameters
        self.symbols = symbols or self.config.get("symbols", {}).get("futures", [])
        if (
            isinstance(self.symbols, list)
            and len(self.symbols) > 0
            and isinstance(self.symbols[0], dict)
        ):
            # Extract symbol names from config
            self.symbols = [s["symbol"] for s in self.symbols]

        self.strategy = strategy or self.config.get("strategy", {}).get("default", "sr")
        self.mode = mode or self.config.get("trading", {}).get("mode", "paper")

        # Load profile
        self.profile = load_profile()

        # Initialize portfolio (data-only system)
        starting_balance = self.config.get("trading", {}).get("paper", {}).get("starting_balance", 50000.0)

        self.portfolio = Portfolio(cash=starting_balance)

        # Initialize workflow
        self.workflow = TradingWorkflow(
            symbols=self.symbols,
            portfolio=self.portfolio,
            strategy=self.strategy,
            config=self.config,
        )
        
        # Shutdown flag for graceful shutdown
        self.shutdown_requested = False

        logger.info(
            f"LangGraphTrader initialized: strategy={self.strategy}, symbols={self.symbols}"
        )

    async def start(
        self,
        interval: int = 60,
        max_cycles: Optional[int] = None,
    ) -> None:
        """
        Start the trading system with graceful shutdown handling.

        Args:
            interval: Seconds between trading cycles
            max_cycles: Maximum number of cycles (None for infinite)
        """
        logger.info(
            f"Starting LangGraph trader: mode={self.mode}, interval={interval}s"
        )

        if self.mode == "live":
            logger.warning("LIVE TRADING MODE - Real money will be used!")
            # Add confirmation prompt in production

        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_requested = True
            # Give workflow a chance to finish current cycle
            if hasattr(self.workflow, 'shutdown'):
                self.workflow.shutdown()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
        # Run continuous workflow
            await self.workflow.run_continuous(
                interval=interval,
                max_cycles=max_cycles,
                shutdown_check=lambda: self.shutdown_requested,
            )
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, shutting down...")
        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)
            raise
        finally:
            logger.info("Trading system stopped")

    def run_single_cycle(self) -> None:
        """Run a single trading cycle (synchronous)."""
        asyncio.run(self.workflow.run_cycle())


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="LangGraph Multi-Agent Trading System")
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    parser.add_argument("--symbols", nargs="+", help="Trading symbols")
    # Broker argument removed - system is data-only
    parser.add_argument("--strategy", type=str, help="Trading strategy")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["paper", "live"],
        default="paper",
        help="Trading mode",
    )
    parser.add_argument(
        "--interval", type=int, default=60, help="Cycle interval in seconds"
    )
    parser.add_argument("--max-cycles", type=int, help="Maximum number of cycles")

    args = parser.parse_args()

    # Create trader
    trader = LangGraphTrader(
        config_path=args.config,
        symbols=args.symbols,
        strategy=args.strategy,
        mode=args.mode,
    )

    # Start trading
    asyncio.run(trader.start(interval=args.interval, max_cycles=args.max_cycles))


if __name__ == "__main__":
    main()
