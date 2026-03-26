"""
Market Agent Main Entry Point

Supports two modes:
  1. Legacy: python -m pearlalgo.market_agent.main
     Uses config/config.yaml + PEARLALGO_CONFIG_OVERLAY environment variable.

  2. New (parameterized): python -m pearlalgo.market_agent.main \
       --config config/accounts/tradovate_paper.yaml \
       --data-dir data/tradovate/paper
     Loads config/base.yaml merged with the account config.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import fcntl
import os
import sys
from pathlib import Path

import yaml

from pearlalgo.utils.logger import logger
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
# take precedence over .env file values.
try:
    from dotenv import load_dotenv
    secrets_path = Path.home() / ".config" / "pearlalgo" / "secrets.env"
    if secrets_path.exists():
        load_dotenv(secrets_path, override=False)
        logger.info(f"Loaded secrets from {secrets_path}")
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
        logger.info(f"Loaded environment variables from {env_path}")
except ImportError:
    pass
except Exception as e:
    logger.warning(f"Could not load .env file: {e}")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (override wins on conflicts)."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_new_config(config_path: str) -> dict:
    """Load config/base.yaml merged with the account-specific config file.

    The account config only needs to contain keys that differ from base.yaml.
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Account config not found: {config_file}")

    # Resolve base.yaml relative to the account config (../base.yaml)
    base_path = config_file.parent.parent / "base.yaml"
    if not base_path.exists():
        # Fallback: project root config/base.yaml
        base_path = project_root / "config" / "base.yaml"

    base_config: dict = {}
    if base_path.exists():
        with open(base_path) as f:
            base_config = yaml.safe_load(f) or {}
        logger.info(f"Loaded base config: {base_path}")

    with open(config_file) as f:
        account_config = yaml.safe_load(f) or {}
    logger.info(f"Loaded account config: {config_file}")

    merged = _deep_merge(base_config, account_config)
    account_name = merged.get("account", {}).get("name", config_file.stem)
    logger.info(f"Config merged: account={account_name}")
    return merged


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PearlAlgo Market Agent")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to account config YAML (e.g., config/accounts/tradovate_paper.yaml). "
             "If not provided, falls back to legacy config.yaml loading.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Path to data directory for this agent (e.g., data/tradovate/paper). "
             "If not provided, uses PEARLALGO_STATE_DIR or default.",
    )
    return parser.parse_args()


_lock_file = None  # module-level so GC doesn't close it


async def main():
    """Main entry point."""
    # ── Singleton guard: only one agent process at a time ──────────
    global _lock_file
    lock_path = Path("/tmp/pearlalgo-agent.lock")
    fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, 0o644)
    _lock_file = os.fdopen(fd, "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file.truncate(0)
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
    except BlockingIOError:
        print(
            f"FATAL: Another agent is already running (lock held by PID in {lock_path}). Exiting.",
            file=sys.stderr,
        )
        sys.exit(1)

    log_file = project_root / "logs" / "agent_TV_PAPER.log"
    setup_logging(level="INFO", log_file=log_file)
    run_id = set_run_id()

    try:
        from loguru import logger as loguru_logger
        loguru_logger.configure(extra={"run_id": run_id})
    except ImportError:
        pass

    args = _parse_args()

    # ---------------------------------------------------------------
    # Config loading: --config required (base.yaml + account overlay)
    # ---------------------------------------------------------------
    if not args.config:
        logger.error(
            "Missing --config. Example: --config config/accounts/tradovate_paper.yaml"
        )
        return
    logger.info(f"Starting Market Agent Service | run_id={run_id}")
    config_data = _load_new_config(args.config)
    try:
        from pearlalgo.config.schema_v2 import validate_config
        config_data = validate_config(config_data)
        logger.info("Config validated (schema_v2)")
    except Exception as e:
        logger.error(f"Config validation failed: {e}")
        return

    # Telegram config: env vars take precedence
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    telegram_thread_id_str = os.getenv("TELEGRAM_THREAD_ID")
    telegram_thread_id = int(telegram_thread_id_str) if telegram_thread_id_str else None

    if not telegram_bot_token or not telegram_chat_id:
        telegram_config = config_data.get("telegram", {})
        if telegram_config.get("enabled", True):
            telegram_bot_token = telegram_bot_token or telegram_config.get("bot_token")
            telegram_chat_id = telegram_chat_id or telegram_config.get("chat_id")

    # Build strategy config
    strategy_config = build_strategy_config(PEARL_BOT_CONFIG.copy(), config_data)
    config = ConfigView(strategy_config)

    # Data provider
    provider_name = os.getenv("PEARLALGO_DATA_PROVIDER", "ibkr")
    try:
        data_provider = create_data_provider(provider_name)
        provider_type = type(data_provider).__name__
        logger.info(f"Data provider: {provider_type} (provider={provider_name})")

        if "Mock" in provider_type or "mock" in provider_type.lower():
            logger.warning(
                "WARNING: Using MOCK data provider! "
                "This generates synthetic prices and is for testing only."
            )
    except Exception as e:
        logger.error(f"Failed to create data provider '{provider_name}': {e}")
        return

    # State directory: --data-dir > PEARLALGO_STATE_DIR > default
    if args.data_dir:
        state_dir = Path(args.data_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"State directory (from --data-dir): {state_dir}")
    else:
        state_dir = ensure_state_dir()

    # Build service
    deps = build_service_dependencies(
        data_provider=data_provider,
        config=config,
        state_dir=state_dir,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        telegram_thread_id=telegram_thread_id,
        service_config=config_data,
    )
    service = MarketAgentService(deps=deps)

    # Run
    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt at main level")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
