#!/usr/bin/env python
"""
Automated Trading Script - Entry point for the automated trading agent.
Can be run directly or via systemd service.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.agents.automated_trading_agent import AutomatedTradingAgent
from pearlalgo.utils.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated IBKR paper trading agent with market hours awareness and error recovery."
    )
    parser.add_argument("--symbols", nargs="+", default=["ES", "NQ", "GC"], help="Symbols to trade")
    parser.add_argument("--sec-types", nargs="+", default=["FUT", "FUT", "FUT"], help="Security types")
    parser.add_argument("--strategy", type=str, default="sr", help="Trading strategy (sr, ma_cross, scalping, intraday_swing, etc.)")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval in seconds (default: 300 = 5min)")
    parser.add_argument("--tiny-size", type=int, default=1, help="Base contract size (will be adjusted by risk)")
    parser.add_argument("--profile-config", default=None, help="Prop profile config path")
    parser.add_argument("--ib-host", default=None, help="IB Gateway host override")
    parser.add_argument("--ib-port", type=int, default=None, help="IB Gateway port override")
    parser.add_argument("--ib-client-id", type=int, default=None, help="IB clientId override")
    parser.add_argument("--expiries", nargs="*", help="Futures expiries (YYYYMM or YYYYMMDD)")
    parser.add_argument("--local-symbols", nargs="*", help="IBKR local symbols")
    parser.add_argument("--trading-classes", nargs="*", help="Trading classes")
    parser.add_argument("--max-retries", type=int, default=3, help="Max consecutive errors before reconnect")
    parser.add_argument("--retry-delay", type=int, default=60, help="Delay before retry (seconds)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-file", default=None, help="Optional log file path")
    
    args = parser.parse_args(argv)
    
    # Setup logging
    setup_logging(level=args.log_level, log_file=args.log_file)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("Starting Automated Trading Agent")
    logger.info("=" * 60)
    logger.info(f"Symbols: {args.symbols}")
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Interval: {args.interval}s")
    logger.info(f"Profile: {args.profile_config or 'default'}")
    
    # Create and start agent
    agent = AutomatedTradingAgent(
        symbols=args.symbols,
        sec_types=args.sec_types,
        strategy=args.strategy,
        profile_config=args.profile_config,
        interval=args.interval,
        tiny_size=args.tiny_size,
        ib_host=args.ib_host,
        ib_port=args.ib_port,
        ib_client_id=args.ib_client_id,
        expiries=args.expiries,
        local_symbols=args.local_symbols,
        trading_classes=args.trading_classes,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
    )
    
    try:
        agent.start()
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

