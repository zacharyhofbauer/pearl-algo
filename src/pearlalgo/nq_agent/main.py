"""
NQ Agent Main Entry Point

Main entry point for running the NQ agent service.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


async def main():
    """Main entry point."""
    logger.info("Starting NQ Agent Service...")
    
    # Create configuration
    config = NQIntradayConfig()
    
    # Create data provider (use factory to get appropriate provider)
    # Default to IBKR if no provider specified via env var
    import os
    provider_name = os.getenv("PEARLALGO_DATA_PROVIDER", "ibkr")
    
    try:
        data_provider = create_data_provider(provider_name)
        logger.info(f"Data provider: {type(data_provider).__name__} (provider={provider_name})")
    except Exception as e:
        logger.error(f"Failed to create data provider '{provider_name}': {e}")
        return
    
    # Create service
    service = NQAgentService(
        data_provider=data_provider,
        config=config,
    )
    
    # Run service
    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
    finally:
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
