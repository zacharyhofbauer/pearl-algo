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

from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.utils.logging_config import setup_logging


async def main():
    """Main entry point."""
    # Setup logging for console output (matches testing behavior)
    setup_logging(level="INFO")
    
    logger.info("Starting NQ Agent Service...")

    import os

    # Load Telegram configuration from environment or config.yaml
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    # Try loading from config.yaml if env vars not set
    if not telegram_bot_token or not telegram_chat_id:
        try:
            from pathlib import Path
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "config.yaml"
            if config_path.exists():
                import yaml
                with open(config_path) as f:
                    config_data = yaml.safe_load(f) or {}
                    telegram_config = config_data.get("telegram", {})
                    if telegram_config.get("enabled", True):
                        telegram_bot_token = telegram_bot_token or telegram_config.get("bot_token")
                        telegram_chat_id = telegram_chat_id or telegram_config.get("chat_id")
                        # Support environment variable substitution in config
                        if telegram_bot_token and telegram_bot_token.startswith("${"):
                            env_var = telegram_bot_token[2:-1].split(":")[0]
                            telegram_bot_token = os.getenv(env_var) or telegram_config.get("bot_token", "")
                        if telegram_chat_id and telegram_chat_id.startswith("${"):
                            env_var = telegram_chat_id[2:-1].split(":")[0]
                            telegram_chat_id = os.getenv(env_var) or telegram_config.get("chat_id", "")
        except Exception as e:
            logger.warning(f"Could not load Telegram config from config.yaml: {e}")

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

    # Create service with Telegram configuration
    service = NQAgentService(
        data_provider=data_provider,
        config=config,
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
