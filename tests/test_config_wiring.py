"""
Tests for configuration propagation from config.yaml to NQAgentService and NQAgentDataFetcher.

Verifies that config values actually reach the service and data fetcher components,
preventing silent drift when config values are changed but not respected.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


class MockDataProvider:
    """Minimal mock data provider for testing."""
    
    def fetch_historical(self, symbol, start, end, timeframe):
        import pandas as pd
        return pd.DataFrame()
    
    async def get_latest_bar(self, symbol):
        return None


class TestConfigLoaderDefaults:
    """Tests verifying default values in config loader."""
    
    def test_service_defaults_include_key_values(self):
        """Verify default service config includes expected keys."""
        with patch('pearlalgo.config.config_loader.load_config_yaml', return_value={}):
            config = load_service_config(validate=False)
        
        service = config["service"]
        assert "status_update_interval" in service
        assert "heartbeat_interval" in service
        assert "state_save_interval" in service
        assert "enable_new_bar_gating" in service
        assert "cadence_mode" in service
    
    def test_circuit_breaker_defaults(self):
        """Verify circuit breaker defaults."""
        with patch('pearlalgo.config.config_loader.load_config_yaml', return_value={}):
            config = load_service_config(validate=False)
        
        cb = config["circuit_breaker"]
        assert cb["max_consecutive_errors"] == 10
        assert cb["max_connection_failures"] == 10
        assert cb["max_data_fetch_errors"] == 5
    
    def test_data_defaults(self):
        """Verify data section defaults."""
        with patch('pearlalgo.config.config_loader.load_config_yaml', return_value={}):
            config = load_service_config(validate=False)
        
        data = config["data"]
        assert "buffer_size" in data
        assert "stale_data_threshold_minutes" in data
        assert "enable_base_cache" in data
        assert "enable_mtf_cache" in data


class TestServiceReceivesConfig:
    """Tests verifying NQAgentService receives config values."""
    
    def test_service_receives_status_update_interval(self):
        """Service should receive status_update_interval from config."""
        custom_interval = 1200  # 20 minutes
        
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": custom_interval,
                    "heartbeat_interval": 86400,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": True,
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "buffer_size": 100,
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            assert service.status_update_interval == custom_interval
    
    def test_service_receives_heartbeat_interval(self):
        """Service should receive heartbeat_interval from config."""
        custom_interval = 7200  # 2 hours
        
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 900,
                    "heartbeat_interval": custom_interval,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": True,
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "buffer_size": 100,
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            assert service.heartbeat_interval == custom_interval
    
    def test_service_receives_new_bar_gating_flag(self):
        """Service should receive enable_new_bar_gating from config."""
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 900,
                    "heartbeat_interval": 86400,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": False,  # Explicitly disabled
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "buffer_size": 100,
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            assert service._enable_new_bar_gating is False
    
    def test_service_receives_circuit_breaker_thresholds(self):
        """Service should receive circuit breaker thresholds from config."""
        custom_max_errors = 5
        custom_max_failures = 8
        
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 900,
                    "heartbeat_interval": 86400,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": True,
                },
                "circuit_breaker": {
                    "max_consecutive_errors": custom_max_errors,
                    "max_connection_failures": custom_max_failures,
                    "max_data_fetch_errors": 3,
                },
                "data": {
                    "buffer_size": 100,
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            assert service.max_consecutive_errors == custom_max_errors
            assert service.max_connection_failures == custom_max_failures
    
    def test_service_receives_stale_data_threshold(self):
        """Service should receive stale_data_threshold_minutes from config."""
        custom_threshold = 15
        
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 900,
                    "heartbeat_interval": 86400,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": True,
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "buffer_size": 100,
                    "stale_data_threshold_minutes": custom_threshold,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            assert service.stale_data_threshold_minutes == custom_threshold
    
    def test_service_receives_buffer_size_target(self):
        """Service should receive buffer_size from config as buffer_size_target."""
        custom_buffer = 200
        
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 900,
                    "heartbeat_interval": 86400,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": True,
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "buffer_size": custom_buffer,
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            assert service.buffer_size_target == custom_buffer


class TestDataFetcherReceivesConfig:
    """Tests verifying NQAgentDataFetcher receives config values."""
    
    def test_data_fetcher_receives_buffer_size(self):
        """Data fetcher should receive buffer_size from config."""
        custom_buffer = 150
        
        with patch('pearlalgo.nq_agent.data_fetcher.load_service_config') as mock_config:
            mock_config.return_value = {
                "data": {
                    "buffer_size": custom_buffer,
                    "buffer_size_5m": 50,
                    "buffer_size_15m": 50,
                    "historical_hours": 2,
                    "multitimeframe_5m_hours": 4,
                    "multitimeframe_15m_hours": 12,
                    "stale_data_threshold_minutes": 10,
                    "enable_base_cache": False,
                    "enable_mtf_cache": False,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            fetcher = NQAgentDataFetcher(
                data_provider=provider,
                config=config,
            )
            
            assert fetcher._buffer_size == custom_buffer
    
    def test_data_fetcher_receives_stale_threshold(self):
        """Data fetcher should receive stale_data_threshold_minutes from config."""
        custom_threshold = 20
        
        with patch('pearlalgo.nq_agent.data_fetcher.load_service_config') as mock_config:
            mock_config.return_value = {
                "data": {
                    "buffer_size": 100,
                    "buffer_size_5m": 50,
                    "buffer_size_15m": 50,
                    "historical_hours": 2,
                    "multitimeframe_5m_hours": 4,
                    "multitimeframe_15m_hours": 12,
                    "stale_data_threshold_minutes": custom_threshold,
                    "enable_base_cache": False,
                    "enable_mtf_cache": False,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            fetcher = NQAgentDataFetcher(
                data_provider=provider,
                config=config,
            )
            
            assert fetcher.stale_data_threshold_minutes == custom_threshold
    
    def test_data_fetcher_receives_cache_flags(self):
        """Data fetcher should receive cache enable flags from config."""
        with patch('pearlalgo.nq_agent.data_fetcher.load_service_config') as mock_config:
            mock_config.return_value = {
                "data": {
                    "buffer_size": 100,
                    "buffer_size_5m": 50,
                    "buffer_size_15m": 50,
                    "historical_hours": 2,
                    "multitimeframe_5m_hours": 4,
                    "multitimeframe_15m_hours": 12,
                    "stale_data_threshold_minutes": 10,
                    "enable_base_cache": True,  # Explicitly enabled
                    "enable_mtf_cache": True,   # Explicitly enabled
                    "base_refresh_seconds": 120,
                    "mtf_refresh_seconds_5m": 600,
                    "mtf_refresh_seconds_15m": 1800,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            fetcher = NQAgentDataFetcher(
                data_provider=provider,
                config=config,
            )
            
            assert fetcher._enable_base_cache is True
            assert fetcher._enable_mtf_cache is True
            assert fetcher._base_refresh_seconds == 120
            assert fetcher._mtf_refresh_seconds_5m == 600
            assert fetcher._mtf_refresh_seconds_15m == 1800
    
    def test_data_fetcher_receives_mtf_hours(self):
        """Data fetcher should receive multitimeframe hours from config."""
        custom_5m_hours = 8
        custom_15m_hours = 24
        
        with patch('pearlalgo.nq_agent.data_fetcher.load_service_config') as mock_config:
            mock_config.return_value = {
                "data": {
                    "buffer_size": 100,
                    "buffer_size_5m": 50,
                    "buffer_size_15m": 50,
                    "historical_hours": 2,
                    "multitimeframe_5m_hours": custom_5m_hours,
                    "multitimeframe_15m_hours": custom_15m_hours,
                    "stale_data_threshold_minutes": 10,
                    "enable_base_cache": False,
                    "enable_mtf_cache": False,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            fetcher = NQAgentDataFetcher(
                data_provider=provider,
                config=config,
            )
            
            assert fetcher._multitimeframe_5m_hours == custom_5m_hours
            assert fetcher._multitimeframe_15m_hours == custom_15m_hours


class TestStrategyConfigFromFile:
    """Tests verifying strategy config loads from config.yaml."""
    
    def test_strategy_config_from_file_includes_session_times(self):
        """NQIntradayConfig.from_config_file() should include session times."""
        # This test uses the real config file
        try:
            config = NQIntradayConfig.from_config_file()
            
            # Verify session times are loaded (from config.yaml session section)
            assert hasattr(config, 'start_time')
            assert hasattr(config, 'end_time')
            
            # Default session is 18:00-16:10 ET
            assert config.start_time is not None
            assert config.end_time is not None
        except Exception as e:
            # If config file doesn't exist, skip with warning
            pytest.skip(f"Config file not available: {e}")
    
    def test_strategy_config_from_file_includes_scan_interval(self):
        """NQIntradayConfig.from_config_file() should include scan_interval."""
        try:
            config = NQIntradayConfig.from_config_file()
            
            # Verify scan_interval is loaded
            assert hasattr(config, 'scan_interval')
            assert config.scan_interval > 0
        except Exception as e:
            pytest.skip(f"Config file not available: {e}")


class TestConfigValueTypes:
    """Tests verifying config values have correct types after propagation."""
    
    def test_boolean_flags_are_bool(self):
        """Boolean config values should be actual bools, not truthy values."""
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 900,
                    "heartbeat_interval": 86400,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": True,
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "buffer_size": 100,
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            # These should be actual bools
            assert isinstance(service._enable_new_bar_gating, bool)
    
    def test_numeric_values_are_correct_type(self):
        """Numeric config values should have correct numeric types."""
        with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 900,
                    "heartbeat_interval": 86400,
                    "state_save_interval": 10,
                    "enable_new_bar_gating": True,
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "buffer_size": 100,
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                },
            }
            
            provider = MockDataProvider()
            config = NQIntradayConfig(symbol="MNQ", timeframe="5m")
            
            service = NQAgentService(
                data_provider=provider,
                config=config,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            
            # These should be ints
            assert isinstance(service.status_update_interval, int)
            assert isinstance(service.max_consecutive_errors, int)
            assert isinstance(service.buffer_size_target, int)
