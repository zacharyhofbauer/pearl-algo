"""
Tests for data_providers/factory.py

Validates the data provider factory pattern including:
- Provider registry
- Provider creation
- Error handling
- Custom provider registration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.data_providers.factory import (
    _PROVIDER_REGISTRY,
    create_data_provider,
    create_data_provider_with_fallback,
    list_available_providers,
    register_provider,
)
from pearlalgo.data_providers.base import DataProvider


class TestListAvailableProviders:
    """Tests for list_available_providers."""

    def test_returns_list_of_strings(self) -> None:
        """Should return a list of provider names."""
        providers = list_available_providers()
        assert isinstance(providers, list)
        assert all(isinstance(p, str) for p in providers)

    def test_includes_ibkr(self) -> None:
        """Should include IBKR provider by default."""
        providers = list_available_providers()
        assert "ibkr" in providers


class TestCreateDataProvider:
    """Tests for create_data_provider."""

    def test_raises_on_unknown_provider(self) -> None:
        """Should raise ValueError for unknown provider names."""
        with pytest.raises(ValueError, match="Unknown data provider"):
            create_data_provider("nonexistent_provider")

    def test_error_message_includes_available_providers(self) -> None:
        """Error message should list available providers."""
        with pytest.raises(ValueError) as exc_info:
            create_data_provider("fake_provider")
        assert "ibkr" in str(exc_info.value)

    def test_ibkr_provider_in_registry(self) -> None:
        """Should have IBKR provider registered by default."""
        # The registry should have IBKRProvider class
        from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
        assert _PROVIDER_REGISTRY["ibkr"] == IBKRProvider

    def test_provider_class_accessible(self) -> None:
        """Provider class should be accessible from registry."""
        provider_class = _PROVIDER_REGISTRY.get("ibkr")
        assert provider_class is not None
        # Should be a class that inherits from DataProvider
        assert issubclass(provider_class, DataProvider)


class TestCreateDataProviderWithFallback:
    """Tests for create_data_provider_with_fallback."""

    @patch("pearlalgo.data_providers.factory.create_data_provider")
    def test_returns_primary_when_successful(
        self, mock_create: MagicMock
    ) -> None:
        """Should return primary provider when it succeeds."""
        mock_provider = MagicMock()
        mock_create.return_value = mock_provider

        result = create_data_provider_with_fallback("ibkr")

        assert result == mock_provider
        mock_create.assert_called_once_with("ibkr", settings=None)

    @patch("pearlalgo.data_providers.factory.create_data_provider")
    def test_raises_when_all_providers_fail(
        self, mock_create: MagicMock
    ) -> None:
        """Should raise ValueError when all providers fail."""
        mock_create.side_effect = Exception("Connection failed")

        with pytest.raises(ValueError, match="All data providers failed"):
            create_data_provider_with_fallback("ibkr", fallbacks=["other"])


class TestRegisterProvider:
    """Tests for register_provider."""

    def test_rejects_non_dataprovider_class(self) -> None:
        """Should raise TypeError for classes not inheriting DataProvider."""

        class NotAProvider:
            pass

        with pytest.raises(TypeError, match="must inherit from DataProvider"):
            register_provider("fake", NotAProvider)

    def test_registers_valid_provider(self) -> None:
        """Should register valid DataProvider subclass."""

        class CustomProvider(DataProvider):
            def fetch_historical(self, *args, **kwargs):
                pass

            def get_latest_bar(self, *args, **kwargs):
                pass

        # Register the provider
        register_provider("custom_test", CustomProvider)

        # Verify it's in the registry
        assert "custom_test" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["custom_test"] == CustomProvider

        # Clean up: remove from registry
        del _PROVIDER_REGISTRY["custom_test"]

    def test_appears_in_list_after_registration(self) -> None:
        """Registered provider should appear in list_available_providers."""

        class AnotherCustomProvider(DataProvider):
            def fetch_historical(self, *args, **kwargs):
                pass

            def get_latest_bar(self, *args, **kwargs):
                pass

        register_provider("another_custom", AnotherCustomProvider)

        try:
            providers = list_available_providers()
            assert "another_custom" in providers
        finally:
            # Clean up
            del _PROVIDER_REGISTRY["another_custom"]
