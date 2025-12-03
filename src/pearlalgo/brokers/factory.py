"""
Broker Factory - Unified broker selection and initialization.

Provides a factory pattern for creating brokers (IBKR, Bybit, Alpaca).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional


try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.brokers.alpaca_broker import AlpacaBroker
from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.brokers.bybit_broker import BybitBroker
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.brokers.mock_broker import MockBroker
from pearlalgo.brokers.paper_broker import PaperBroker
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.risk.limits import RiskGuard, RiskLimits

logger = logging.getLogger(__name__)


def get_broker(
    broker_name: str,
    portfolio: Portfolio,
    config: Optional[Dict] = None,
    risk_guard: Optional[RiskGuard] = None,
    settings: Optional[any] = None,
) -> Broker:
    """
    Factory function to create a broker instance.

    Args:
        broker_name: "ibkr", "bybit", or "alpaca"
        portfolio: Portfolio instance
        config: Configuration dictionary
        risk_guard: Optional risk guard

    Returns:
        Broker instance
    """
    broker_name = broker_name.lower()
    config = config or {}

    if broker_name == "ibkr":
        from pearlalgo.config.settings import get_settings

        settings = get_settings()
        risk_guard = risk_guard or RiskGuard(RiskLimits())

        return IBKRBroker(
            portfolio=portfolio,
            settings=settings,
            risk_guard=risk_guard,
        )

    elif broker_name == "bybit":
        bybit_config = config.get("broker", {}).get("bybit", {})

        return BybitBroker(
            portfolio=portfolio,
            api_key=bybit_config.get("api_key"),
            api_secret=bybit_config.get("api_secret"),
            testnet=bybit_config.get("testnet", False),
            unified_margin=bybit_config.get("unified_margin", True),
        )

    elif broker_name == "alpaca":
        alpaca_config = config.get("broker", {}).get("alpaca", {})

        return AlpacaBroker(
            portfolio=portfolio,
            api_key=alpaca_config.get("api_key"),
            api_secret=alpaca_config.get("api_secret"),
            base_url=alpaca_config.get("base_url"),
        )

    elif broker_name == "paper":
        # Paper broker for internal simulation
        broker_config_obj = BrokerConfig(paper=True)
        return PaperBroker(
            portfolio=portfolio,
            config=broker_config_obj,
            deterministic=config.get("deterministic", False),
        )

    elif broker_name == "mock":
        # Mock broker for testing
        broker_config_obj = BrokerConfig(paper=True)
        return MockBroker(
            portfolio=portfolio,
            config=broker_config_obj,
            always_fill=config.get("always_fill", True),
        )

    else:
        raise ValueError(
            f"Unknown broker: {broker_name}. "
            f"Supported: ibkr, bybit, alpaca, paper, mock"
        )
