"""
NQ Agent Main Entry Point

Main entry point for running the NQ agent service.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pearlalgo.utils.logger import logger

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded environment variables from {env_path}")
except ImportError:
    pass  # dotenv not required, but helpful
except Exception as e:
    logger.warning(f"Could not load .env file: {e}")

from pearlalgo.config.config_file import load_config_yaml
from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.utils.logging_config import set_run_id, setup_logging
from pearlalgo.utils.paths import ensure_state_dir


async def main():
    """Main entry point."""
    # Setup logging for console output (matches testing behavior)
    setup_logging(level="INFO")
    
    # Generate a stable run_id for this process lifetime
    # This helps correlate all logs from a single service run in journald
    run_id = set_run_id()
    
    # Bind run_id to loguru context if available (appears in all subsequent logs)
    try:
        from loguru import logger as loguru_logger
        loguru_logger.configure(extra={"run_id": run_id})
    except ImportError:
        pass  # loguru not available, run_id still in context var
    
    logger.info(f"Starting NQ Agent Service (MNQ-native config) | run_id={run_id}")

    import os

    # Load Telegram configuration from environment or config.yaml
    # Precedence: env vars > config.yaml (unified loader handles ${ENV} substitution)
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not telegram_bot_token or not telegram_chat_id:
        config_data = load_config_yaml()
        telegram_config = config_data.get("telegram", {})
        if telegram_config.get("enabled", True):
            # Unified loader already substitutes ${ENV} patterns
            telegram_bot_token = telegram_bot_token or telegram_config.get("bot_token")
            telegram_chat_id = telegram_chat_id or telegram_config.get("chat_id")

    # Create configuration (load from config.yaml if available)
    try:
        config = NQIntradayConfig.from_config_file()
    except Exception as e:
        logger.warning(f"Could not load config from file, using defaults: {e}")
        config = NQIntradayConfig()

    # Create data provider (use factory to get appropriate provider)
    # Default to IBKR if no provider specified via env var
    provider_name = os.getenv("PEARLALGO_DATA_PROVIDER", "ibkr")

    try:
        data_provider = create_data_provider(provider_name)
        provider_type = type(data_provider).__name__
        logger.info(f"Data provider: {provider_type} (provider={provider_name})")
        
        # Warn if using mock data in production
        if "Mock" in provider_type or "mock" in provider_type.lower():
            logger.warning(
                "⚠️  WARNING: Using MOCK data provider! "
                "This generates synthetic prices (~17,500) and is for testing only.\n"
                "For real market data, ensure PEARLALGO_DATA_PROVIDER=ibkr and IBKR Gateway is running."
            )
    except Exception as e:
        logger.error(f"Failed to create data provider '{provider_name}': {e}")
        return

    # Resolve state directory (supports PEARLALGO_STATE_DIR / PEARLALGO_MARKET overrides)
    state_dir = ensure_state_dir()

    # Create service with Telegram configuration
    service = NQAgentService(
        data_provider=data_provider,
        config=config,
        state_dir=state_dir,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )

    # Run service
    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt at main level, service should handle shutdown")
        # Service.stop() will be called in finally block via service.start()'s finally
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
        # Service.stop() will be called in finally block via service.start()'s finally


if __name__ == "__main__":
    asyncio.run(main())
