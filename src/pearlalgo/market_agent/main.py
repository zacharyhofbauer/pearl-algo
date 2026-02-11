"""
Market Agent Main Entry Point

Main entry point for running the market agent service.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from pearlalgo.utils.logger import logger
from pearlalgo.config.config_file import load_config_yaml
from pearlalgo.config.config_loader import build_strategy_config
from pearlalgo.config.config_view import ConfigView
from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.market_agent.service import MarketAgentService
from pearlalgo.market_agent.service_factory import build_service_dependencies
from pearlalgo.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.utils.logging_config import set_run_id, setup_logging
from pearlalgo.utils.paths import ensure_state_dir

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env files if they exist.
# IMPORTANT: override=False so that shell-level env vars (from launch scripts)
# take precedence over .env file values. This lets tv_paper_eval.sh set its own
# IBKR_CLIENT_ID/IBKR_DATA_CLIENT_ID without .env clobbering them.
try:
    from dotenv import load_dotenv
    # Load secrets (Tradovate credentials, API keys, etc.) - don't clobber shell env
    secrets_path = Path.home() / ".config" / "pearlalgo" / "secrets.env"
    if secrets_path.exists():
        load_dotenv(secrets_path, override=False)
        logger.info(f"Loaded secrets from {secrets_path}")
    # Load project .env defaults - don't clobber shell env or secrets
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
        logger.info(f"Loaded environment variables from {env_path}")
except ImportError:
    pass  # dotenv not required, but helpful
except Exception as e:
    logger.warning(f"Could not load .env file: {e}")

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
    
    logger.info(f"Starting Market Agent Service | run_id={run_id}")

    # Load config.yaml (base + optional overlay) once for this run.
    config_data = load_config_yaml()

    # Load Telegram configuration from environment or config.yaml
    # Precedence: env vars > config.yaml (unified loader handles ${ENV} substitution)
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not telegram_bot_token or not telegram_chat_id:
        telegram_config = config_data.get("telegram", {})
        if telegram_config.get("enabled", True):
            # Unified loader already substitutes ${ENV} patterns
            telegram_bot_token = telegram_bot_token or telegram_config.get("bot_token")
            telegram_chat_id = telegram_chat_id or telegram_config.get("chat_id")

    # Build strategy config from base + config.yaml overrides.
    strategy_config = build_strategy_config(PEARL_BOT_CONFIG.copy(), config_data)
    config = ConfigView(strategy_config)

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

    # Build dependencies via factory and create service
    deps = build_service_dependencies(
        data_provider=data_provider,
        config=config,
        state_dir=state_dir,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )
    service = MarketAgentService(deps=deps)

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
