"""
Centralized API Configuration for Data Providers

Provides a single source of truth for API keys, endpoints, rate limits,
and provider-specific settings. Makes it easy to switch providers or add
new ones.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ProviderConfig:
    """Configuration for a single data provider."""
    
    name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    rate_limit_per_minute: int = 60
    rate_limit_per_second: float = 1.0
    timeout_seconds: int = 30
    max_retries: int = 3
    enabled: bool = True
    additional_params: Optional[Dict] = None
    
    def __post_init__(self):
        """Set additional_params to empty dict if None."""
        if self.additional_params is None:
            self.additional_params = {}


class APIConfig:
    """
    Centralized API configuration manager.
    
    Supports multiple providers with easy switching and fallback logic.
    """
    
    def __init__(self, config_dict: Optional[Dict] = None):
        """
        Initialize API configuration.
        
        Args:
            config_dict: Optional configuration dictionary. If None, loads from environment.
        """
        self.providers: Dict[str, ProviderConfig] = {}
        
        if config_dict:
            self._load_from_dict(config_dict)
        else:
            self._load_from_environment()
    
    def _load_from_environment(self) -> None:
        """Load configuration from environment variables."""
        # Massive provider (primary)
        massive_api_key = os.getenv("MASSIVE_API_KEY", "").strip()
        if massive_api_key:
            self.providers["massive"] = ProviderConfig(
                name="massive",
                api_key=massive_api_key,
                base_url="https://api.massive.dev",
                rate_limit_per_minute=200,  # Developer tier
                rate_limit_per_second=3.33,
                timeout_seconds=30,
                max_retries=3,
                enabled=True,
            )
        
        # Add other providers as needed
        # Polygon
        polygon_api_key = os.getenv("POLYGON_API_KEY", "").strip()
        if polygon_api_key:
            self.providers["polygon"] = ProviderConfig(
                name="polygon",
                api_key=polygon_api_key,
                base_url="https://api.polygon.io",
                rate_limit_per_minute=5,  # Free tier
                rate_limit_per_second=0.083,
                timeout_seconds=30,
                max_retries=3,
                enabled=False,  # Disabled by default, enable if needed
            )
    
    def _load_from_dict(self, config_dict: Dict) -> None:
        """Load configuration from dictionary."""
        for provider_name, provider_config in config_dict.items():
            if isinstance(provider_config, dict):
                # Get API key from dict or environment
                api_key = provider_config.get("api_key") or os.getenv(
                    f"{provider_name.upper()}_API_KEY", ""
                ).strip()
                
                # Handle template variables like ${MASSIVE_API_KEY}
                if api_key and api_key.startswith("${") and api_key.endswith("}"):
                    var_name = api_key[2:-1]
                    api_key = os.getenv(var_name, "").strip()
                
                self.providers[provider_name] = ProviderConfig(
                    name=provider_name,
                    api_key=api_key if api_key else None,
                    base_url=provider_config.get("base_url"),
                    rate_limit_per_minute=provider_config.get("rate_limit_per_minute", 60),
                    rate_limit_per_second=provider_config.get("rate_limit_per_second", 1.0),
                    timeout_seconds=provider_config.get("timeout_seconds", 30),
                    max_retries=provider_config.get("max_retries", 3),
                    enabled=provider_config.get("enabled", True),
                    additional_params=provider_config.get("additional_params"),
                )
    
    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        """
        Get configuration for a specific provider.
        
        Args:
            name: Provider name (e.g., "massive", "polygon")
            
        Returns:
            ProviderConfig or None if not found
        """
        return self.providers.get(name)
    
    def get_primary_provider(self) -> Optional[ProviderConfig]:
        """
        Get the primary (enabled) provider.
        
        Returns:
            ProviderConfig for primary provider, or None if none enabled
        """
        for provider in self.providers.values():
            if provider.enabled:
                return provider
        return None
    
    def get_fallback_providers(self) -> list[ProviderConfig]:
        """
        Get list of fallback providers (enabled but not primary).
        
        Returns:
            List of ProviderConfig for fallback providers
        """
        primary = self.get_primary_provider()
        return [
            p for p in self.providers.values()
            if p.enabled and p != primary
        ]
    
    def enable_provider(self, name: str) -> bool:
        """
        Enable a provider.
        
        Args:
            name: Provider name
            
        Returns:
            True if enabled, False if provider not found
        """
        if name in self.providers:
            self.providers[name].enabled = True
            return True
        return False
    
    def disable_provider(self, name: str) -> bool:
        """
        Disable a provider.
        
        Args:
            name: Provider name
            
        Returns:
            True if disabled, False if provider not found
        """
        if name in self.providers:
            self.providers[name].enabled = False
            return True
        return False
    
    def add_provider(self, config: ProviderConfig) -> None:
        """
        Add a new provider configuration.
        
        Args:
            config: ProviderConfig instance
        """
        self.providers[config.name] = config
    
    def to_dict(self) -> Dict:
        """
        Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of configuration
        """
        return {
            name: {
                "name": config.name,
                "api_key": "***" if config.api_key else None,  # Mask API key
                "base_url": config.base_url,
                "rate_limit_per_minute": config.rate_limit_per_minute,
                "rate_limit_per_second": config.rate_limit_per_second,
                "timeout_seconds": config.timeout_seconds,
                "max_retries": config.max_retries,
                "enabled": config.enabled,
                "additional_params": config.additional_params,
            }
            for name, config in self.providers.items()
        }


# Global instance (can be overridden)
_global_config: Optional[APIConfig] = None


def get_api_config(config_dict: Optional[Dict] = None) -> APIConfig:
    """
    Get global API configuration instance.
    
    Args:
        config_dict: Optional configuration dictionary
        
    Returns:
        APIConfig instance
    """
    global _global_config
    if _global_config is None or config_dict is not None:
        _global_config = APIConfig(config_dict)
    return _global_config


def set_api_config(config: APIConfig) -> None:
    """
    Set global API configuration instance.
    
    Args:
        config: APIConfig instance
    """
    global _global_config
    _global_config = config
