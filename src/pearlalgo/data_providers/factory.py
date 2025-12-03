"""
Data Provider Factory for creating and managing data providers.

Supports multiple data providers with configuration-based selection
and automatic fallback mechanisms.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Type

from pearlalgo.config.settings import Settings, get_settings

from .base import DataProvider
from .local_csv_provider import LocalCSVProvider
from .local_parquet_provider import LocalParquetProvider
from .polygon_provider import PolygonDataProvider
from .tradier_provider import TradierDataProvider

logger = logging.getLogger(__name__)

# Registry of available providers
_PROVIDER_REGISTRY: Dict[str, Type[DataProvider]] = {
    "polygon": PolygonDataProvider,
    "tradier": TradierDataProvider,
    "local_csv": LocalCSVProvider,
    "local_parquet": LocalParquetProvider,
}


def create_data_provider(
    provider_name: str,
    settings: Optional[Settings] = None,
    **kwargs,
) -> DataProvider:
    """
    Create a data provider instance.

    Args:
        provider_name: Name of provider ('polygon', 'tradier', 'local_csv', 'local_parquet')
        settings: Settings instance (optional, will use get_settings() if not provided)
        **kwargs: Additional provider-specific arguments

    Returns:
        DataProvider instance

    Raises:
        ValueError: If provider name is unknown or configuration is invalid
    """
    settings = settings or get_settings()

    if provider_name not in _PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown data provider: {provider_name}. "
            f"Available: {list(_PROVIDER_REGISTRY.keys())}"
        )

    provider_class = _PROVIDER_REGISTRY[provider_name]

    try:
        if provider_name == "polygon":
            api_key = kwargs.get("api_key") or settings.data_api_key
            if not api_key:
                raise ValueError(
                    "Polygon API key required. Set POLYGON_API_KEY env var or pass api_key."
                )
            return provider_class(api_key=api_key, **kwargs)

        elif provider_name == "tradier":
            api_key = kwargs.get("api_key") or settings.data_api_key
            if not api_key:
                raise ValueError(
                    "Tradier API key required. Set TRADIER_API_KEY env var or pass api_key."
                )
            return provider_class(
                api_key=api_key,
                sandbox=kwargs.get("sandbox", True),
                account_id=kwargs.get("account_id"),
            )

        elif provider_name == "local_csv":
            root_dir = kwargs.get("root_dir") or settings.data_dir
            return provider_class(root_dir=root_dir)

        elif provider_name == "local_parquet":
            root_dir = kwargs.get("root_dir") or (
                settings.data_dir / "historical"
                if hasattr(settings.data_dir, "__truediv__")
                else f"{settings.data_dir}/historical"
            )
            return provider_class(root_dir=root_dir)

        else:
            # Fallback for other providers
            return provider_class(**kwargs)

    except Exception as e:
        logger.error(f"Error creating data provider {provider_name}: {e}")
        raise


def create_data_provider_with_fallback(
    primary: str,
    fallbacks: Optional[list[str]] = None,
    settings: Optional[Settings] = None,
    **kwargs,
) -> DataProvider:
    """
    Create a data provider with automatic fallback to alternatives.

    Args:
        primary: Primary provider name
        fallbacks: List of fallback provider names (in order)
        settings: Settings instance
        **kwargs: Provider-specific arguments

    Returns:
        First successfully created DataProvider

    Raises:
        ValueError: If all providers fail to initialize
    """
    if fallbacks is None:
        fallbacks = []

    providers_to_try = [primary] + fallbacks

    for provider_name in providers_to_try:
        try:
            logger.info(f"Attempting to create data provider: {provider_name}")
            return create_data_provider(provider_name, settings=settings, **kwargs)
        except Exception as e:
            logger.warning(
                f"Failed to create provider {provider_name}: {e}. "
                f"Trying fallback..."
            )
            continue

    raise ValueError(
        f"All data providers failed to initialize: {providers_to_try}"
    )


def list_available_providers() -> list[str]:
    """Return list of available data provider names."""
    return list(_PROVIDER_REGISTRY.keys())


def register_provider(name: str, provider_class: Type[DataProvider]) -> None:
    """
    Register a custom data provider.

    Args:
        name: Provider name
        provider_class: Provider class (must inherit from DataProvider)
    """
    if not issubclass(provider_class, DataProvider):
        raise TypeError(
            f"Provider class must inherit from DataProvider, got {provider_class}"
        )

    _PROVIDER_REGISTRY[name] = provider_class
    logger.info(f"Registered custom data provider: {name}")


