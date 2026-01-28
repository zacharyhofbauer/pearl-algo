"""
Tests for Health Monitor.

Validates health monitoring of service components.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock

from pearlalgo.market_agent.health_monitor import HealthMonitor


class TestHealthMonitor:
    """Test HealthMonitor class."""

    def test_init_creates_state_dir(self, tmp_path):
        """Should initialize with state directory."""
        state_dir = tmp_path / "state"
        monitor = HealthMonitor(state_dir=state_dir)
        
        assert monitor.state_dir == state_dir
        assert monitor.last_check is None

    def test_check_data_provider_health_with_connected_executor(self):
        """Should check data provider with connected executor."""
        monitor = HealthMonitor()
        provider = Mock()
        provider._executor = Mock()
        provider._executor.is_connected = Mock(return_value=True)
        
        health = monitor.check_data_provider_health(provider)
        
        assert health["healthy"] is True
        assert health["status"] == "Connected"
        assert "last_check" in health

    def test_check_data_provider_health_with_disconnected_executor(self):
        """Should report disconnected when executor is disconnected."""
        monitor = HealthMonitor()
        provider = Mock()
        provider._executor = Mock()
        provider._executor.is_connected = Mock(return_value=False)
        
        health = monitor.check_data_provider_health(provider)
        
        assert health["healthy"] is False
        assert health["status"] == "Disconnected"
        assert "last_check" in health

    def test_check_data_provider_health_without_executor(self):
        """Should report unverified if no executor to check."""
        monitor = HealthMonitor()
        provider = Mock(spec=[])  # No _executor attribute
        
        health = monitor.check_data_provider_health(provider)
        
        assert health["healthy"] is True
        assert health["status"] == "Present (connection unverified)"

    def test_check_data_provider_health_with_error(self):
        """Should handle errors gracefully."""
        monitor = HealthMonitor()
        provider = Mock()
        provider._executor = Mock()
        provider._executor.is_connected = Mock(side_effect=Exception("Connection failed"))
        
        # When is_connected raises, should fall through to "Present (connection unverified)"
        health = monitor.check_data_provider_health(provider)
        
        assert health["healthy"] is True
        assert health["status"] == "Present (connection unverified)"
        assert "last_check" in health

    def test_check_telegram_health_disabled(self):
        """Should return disabled status for disabled notifier."""
        monitor = HealthMonitor()
        notifier = Mock()
        notifier.enabled = False
        
        health = monitor.check_telegram_health(notifier)
        
        assert health["healthy"] is False
        assert health["status"] == "Disabled"

    def test_check_telegram_health_none(self):
        """Should return disabled status for None notifier."""
        monitor = HealthMonitor()
        
        health = monitor.check_telegram_health(None)
        
        assert health["healthy"] is False
        assert health["status"] == "Disabled"

    def test_check_telegram_health_connected(self):
        """Should return connected status for working notifier."""
        monitor = HealthMonitor()
        notifier = Mock()
        notifier.enabled = True
        notifier.telegram = Mock()
        notifier.telegram.bot = Mock()
        
        health = monitor.check_telegram_health(notifier)
        
        assert health["healthy"] is True
        assert health["status"] == "Connected"

    def test_check_telegram_health_not_initialized(self):
        """Should return not initialized for notifier without bot."""
        monitor = HealthMonitor()
        notifier = Mock()
        notifier.enabled = True
        notifier.telegram = None
        
        health = monitor.check_telegram_health(notifier)
        
        assert health["healthy"] is False
        assert health["status"] == "Not initialized"

    def test_check_file_system_health_writable(self, tmp_path):
        """Should return healthy for writable directory."""
        monitor = HealthMonitor(state_dir=tmp_path)
        
        health = monitor.check_file_system_health()
        
        assert health["healthy"] is True
        assert health["status"] == "Writable"

    def test_get_overall_health_all_healthy(self, tmp_path):
        """Should return healthy when all components are healthy."""
        monitor = HealthMonitor(state_dir=tmp_path)
        
        provider = Mock()
        provider.validate_connection = Mock(return_value=True)
        
        notifier = Mock()
        notifier.enabled = True
        notifier.telegram = Mock()
        notifier.telegram.bot = Mock()
        
        health = monitor.get_overall_health(
            data_provider=provider,
            telegram_notifier=notifier
        )
        
        assert health["overall"] == "healthy"
        assert "timestamp" in health
        assert "components" in health
        assert monitor.last_check is not None

    def test_get_overall_health_degraded(self, tmp_path):
        """Should return degraded when non-critical components fail."""
        monitor = HealthMonitor(state_dir=tmp_path)
        
        provider = Mock()
        provider.validate_connection = Mock(return_value=True)
        
        # Telegram disabled (non-critical)
        notifier = Mock()
        notifier.enabled = False
        
        health = monitor.get_overall_health(
            data_provider=provider,
            telegram_notifier=notifier
        )
        
        assert health["overall"] == "degraded"

    def test_get_overall_health_no_providers(self, tmp_path):
        """Should check only file system when no providers given."""
        monitor = HealthMonitor(state_dir=tmp_path)
        
        health = monitor.get_overall_health()
        
        assert "components" in health
        assert "file_system" in health["components"]
        assert health["overall"] in ("healthy", "unhealthy")


class TestHealthMonitorEdgeCases:
    """Test edge cases and error handling."""

    def test_init_with_none_state_dir(self):
        """Should handle None state_dir."""
        monitor = HealthMonitor(state_dir=None)
        # Should use default state directory
        assert monitor.state_dir is not None

    def test_telegram_health_exception(self):
        """Should handle exceptions in telegram health check."""
        monitor = HealthMonitor()
        
        # Create notifier that raises on attribute access
        notifier = Mock()
        notifier.enabled = True
        type(notifier).telegram = property(lambda self: (_ for _ in ()).throw(Exception("Test error")))
        
        health = monitor.check_telegram_health(notifier)
        
        assert health["healthy"] is False
        assert "Error" in health["status"]
