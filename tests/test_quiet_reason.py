"""
Tests for MarketAgentService._get_quiet_reason() method.

Verifies that the quiet reason is correctly determined for all expected scenarios,
ensuring "correctly quiet" behavior remains stable across refactors.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from pearlalgo.market_agent.service import MarketAgentService
from pearlalgo.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.config.config_loader import load_service_config


class MockDataProvider:
    """Minimal mock data provider for testing."""
    
    def fetch_historical(self, symbol, start, end, timeframe):
        return pd.DataFrame()
    
    async def get_latest_bar(self, symbol):
        return None


@pytest.fixture
def mock_service():
    """Create a minimal MarketAgentService for testing quiet reason logic."""
    with patch('pearlalgo.market_agent.service.load_service_config') as mock_config:
        mock_config.return_value = {
            "service": {
                "status_update_interval": 900,
                "heartbeat_interval": 86400,
                "state_save_interval": 10,
                "enable_new_bar_gating": False,
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
        
        # Create service without Telegram to avoid network calls
        service = MarketAgentService(
            data_provider=provider,
            config=config,
            telegram_bot_token=None,
            telegram_chat_id=None,
        )
        
        yield service


class TestQuietReasonStrategySession:
    """Tests for strategy session closed scenarios."""
    
    def test_returns_strategy_session_closed_when_outside_session(self, mock_service):
        """When scanner.is_market_hours() returns False, should return StrategySessionClosed."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=False):
            reason = mock_service._get_quiet_reason(market_data=None, has_data=True, no_signals=True)
            assert reason == "StrategySessionClosed"
    
    def test_strategy_session_checked_first(self, mock_service):
        """Strategy session is checked before futures market hours."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=False):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True  # Futures open
                
                reason = mock_service._get_quiet_reason(market_data=None, has_data=True, no_signals=True)
                assert reason == "StrategySessionClosed"


class TestQuietReasonFuturesMarket:
    """Tests for futures market closed scenarios."""
    
    def test_returns_futures_market_closed_when_market_closed(self, mock_service):
        """When futures market is closed, should return FuturesMarketClosed."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = False
                
                reason = mock_service._get_quiet_reason(market_data=None, has_data=True, no_signals=True)
                assert reason == "FuturesMarketClosed"


class TestQuietReasonNoData:
    """Tests for no-data scenarios."""
    
    def test_returns_no_data_when_has_data_false(self, mock_service):
        """When has_data=False, should return NoData."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                mock_service.last_successful_cycle = None  # No prior cycle
                reason = mock_service._get_quiet_reason(market_data=None, has_data=False, no_signals=False)
                assert reason == "NoData"
    
    def test_returns_no_data_when_df_is_empty(self, mock_service):
        """When df is empty, should return NoData."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                mock_service.last_successful_cycle = None
                market_data = {"df": pd.DataFrame()}
                reason = mock_service._get_quiet_reason(market_data=market_data, has_data=True, no_signals=False)
                assert reason == "NoData"


class TestQuietReasonDataGap:
    """Tests for data gap scenarios."""
    
    def test_returns_data_gap_when_recent_gap(self, mock_service):
        """When last_successful_cycle is between 60s and stale threshold, should return DataGap."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                # Set last_successful_cycle to 2 minutes ago (between 60s and 10min threshold)
                mock_service.last_successful_cycle = datetime.now(timezone.utc) - timedelta(minutes=2)
                mock_service.stale_data_threshold_minutes = 10
                
                reason = mock_service._get_quiet_reason(market_data=None, has_data=False, no_signals=False)
                assert reason == "DataGap"


class TestQuietReasonStaleData:
    """Tests for stale data scenarios."""
    
    def test_returns_stale_data_when_no_data_and_past_threshold(self, mock_service):
        """When no data and last cycle exceeds stale threshold, should return StaleData."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                # Set last_successful_cycle to 15 minutes ago (past 10min threshold)
                mock_service.last_successful_cycle = datetime.now(timezone.utc) - timedelta(minutes=15)
                mock_service.stale_data_threshold_minutes = 10
                
                reason = mock_service._get_quiet_reason(market_data=None, has_data=False, no_signals=False)
                assert reason == "StaleData"
    
    def test_returns_stale_data_when_latest_bar_old(self, mock_service):
        """When latest_bar timestamp exceeds stale threshold, should return StaleData."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                mock_service.stale_data_threshold_minutes = 10
                old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=15)
                
                market_data = {
                    "df": pd.DataFrame({"close": [100]}),  # Non-empty df
                    "latest_bar": {"timestamp": old_timestamp.isoformat()},
                }
                
                reason = mock_service._get_quiet_reason(market_data=market_data, has_data=True, no_signals=True)
                assert reason == "StaleData"


class TestQuietReasonNoOpportunity:
    """Tests for no opportunity scenarios."""
    
    def test_returns_no_opportunity_when_data_fresh_no_signals(self, mock_service):
        """When data is fresh but no signals generated, should return NoOpportunity."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                mock_service.stale_data_threshold_minutes = 10
                fresh_timestamp = datetime.now(timezone.utc) - timedelta(minutes=1)
                
                market_data = {
                    "df": pd.DataFrame({"close": [100]}),
                    "latest_bar": {"timestamp": fresh_timestamp.isoformat()},
                }
                
                reason = mock_service._get_quiet_reason(market_data=market_data, has_data=True, no_signals=True)
                assert reason == "NoOpportunity"
    
    def test_returns_no_opportunity_when_no_latest_bar_but_df_present(self, mock_service):
        """When df is present but no latest_bar, should return NoOpportunity."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                market_data = {
                    "df": pd.DataFrame({"close": [100]}),
                    "latest_bar": None,
                }
                
                reason = mock_service._get_quiet_reason(market_data=market_data, has_data=True, no_signals=True)
                assert reason == "NoOpportunity"


class TestQuietReasonActive:
    """Tests for active (not quiet) scenarios."""
    
    def test_returns_active_when_not_quiet(self, mock_service):
        """When conditions are normal and signals could be generated, should return Active."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                market_data = {
                    "df": pd.DataFrame({"close": [100]}),
                    "latest_bar": {"timestamp": datetime.now(timezone.utc).isoformat()},
                }
                
                # no_signals=False means signals were generated (not quiet)
                reason = mock_service._get_quiet_reason(market_data=market_data, has_data=True, no_signals=False)
                assert reason == "Active"


class TestQuietReasonExceptionHandling:
    """Tests for exception handling in quiet reason determination."""
    
    def test_returns_unknown_on_exception(self, mock_service):
        """When an exception occurs, should return Unknown."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', side_effect=Exception("Test error")):
            reason = mock_service._get_quiet_reason(market_data=None, has_data=True, no_signals=True)
            assert reason == "Unknown"


class TestQuietReasonTimestampFormats:
    """Tests for different timestamp formats in latest_bar."""
    
    def test_handles_datetime_timestamp(self, mock_service):
        """Should handle datetime object timestamps."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                mock_service.stale_data_threshold_minutes = 10
                fresh_timestamp = datetime.now(timezone.utc) - timedelta(minutes=1)
                
                market_data = {
                    "df": pd.DataFrame({"close": [100]}),
                    "latest_bar": {"timestamp": fresh_timestamp},  # datetime object
                }
                
                reason = mock_service._get_quiet_reason(market_data=market_data, has_data=True, no_signals=True)
                assert reason == "NoOpportunity"
    
    def test_handles_naive_datetime_timestamp(self, mock_service):
        """Should handle naive datetime (assumes UTC)."""
        with patch.object(mock_service.strategy.scanner, 'is_market_hours', return_value=True):
            with patch('pearlalgo.market_agent.service.get_market_hours') as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                mock_service.stale_data_threshold_minutes = 10
                # Naive datetime (no timezone) - simulate legacy format
                fresh_timestamp = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
                
                market_data = {
                    "df": pd.DataFrame({"close": [100]}),
                    "latest_bar": {"timestamp": fresh_timestamp.isoformat()},
                }
                
                reason = mock_service._get_quiet_reason(market_data=market_data, has_data=True, no_signals=True)
                assert reason == "NoOpportunity"

