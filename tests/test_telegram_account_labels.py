"""Tests for Telegram account label configuration."""

import pytest
from unittest.mock import MagicMock, patch


class TestServiceFactoryAccountLabels:
    """Test that service factory uses config-driven Telegram labels."""

    def test_inception_label_from_config(self):
        """Inception account should use telegram_prefix from config."""
        from pearlalgo.market_agent.service_factory import ServiceDependencies

        deps = ServiceDependencies(
            service_config={
                "accounts": {
                    "inception": {"telegram_prefix": "MY-IBKR"},
                    "mffu": {"telegram_prefix": "MY-TV"},
                },
                "challenge": {"stage": ""},
            },
            telegram_bot_token="test",
            telegram_chat_id="123",
        )
        deps.resolve_defaults()
        # The account label should come from config
        assert deps.telegram_notifier.account_label == "MY-IBKR"

    def test_mffu_label_from_config(self):
        """MFFU account should use telegram_prefix from config."""
        from pearlalgo.market_agent.service_factory import ServiceDependencies

        deps = ServiceDependencies(
            service_config={
                "accounts": {
                    "inception": {"telegram_prefix": "MY-IBKR"},
                    "mffu": {"telegram_prefix": "MY-TV"},
                },
                "challenge": {"stage": "mffu_eval"},
            },
            telegram_bot_token="test",
            telegram_chat_id="123",
        )
        deps.resolve_defaults()
        assert deps.telegram_notifier.account_label == "MY-TV"

    def test_default_labels_without_config(self):
        """Without accounts config, should use default labels."""
        from pearlalgo.market_agent.service_factory import ServiceDependencies

        deps = ServiceDependencies(
            service_config={
                "challenge": {"stage": ""},
            },
            telegram_bot_token="test",
            telegram_chat_id="123",
        )
        deps.resolve_defaults()
        assert deps.telegram_notifier.account_label == "IBKR-V"
