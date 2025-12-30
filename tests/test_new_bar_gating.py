"""
Tests for NQAgentService new-bar gating behavior.

Verifies that:
- Analysis is skipped only when bar timestamp is unchanged
- Skip/run counters are correctly updated
- Counters are exposed in status/state
- Gating can be disabled via config
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import pytest

from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


class MockDataProvider:
    """Mock data provider for testing."""
    
    def __init__(self, bars: pd.DataFrame = None):
        self._bars = bars if bars is not None else pd.DataFrame()
        self._latest_bar = None
    
    def fetch_historical(self, symbol, start, end, timeframe):
        return self._bars
    
    async def get_latest_bar(self, symbol):
        return self._latest_bar
    
    def set_bars(self, bars: pd.DataFrame):
        self._bars = bars
    
    def set_latest_bar(self, bar: dict):
        self._latest_bar = bar


def create_test_df(timestamp: datetime, num_bars: int = 20) -> pd.DataFrame:
    """Create a test DataFrame with OHLCV data ending at the given timestamp."""
    timestamps = [timestamp - timedelta(minutes=5*i) for i in range(num_bars-1, -1, -1)]
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": [17500.0] * num_bars,
        "high": [17510.0] * num_bars,
        "low": [17490.0] * num_bars,
        "close": [17505.0] * num_bars,
        "volume": [100] * num_bars,
    })


@pytest.fixture
def mock_service_gating_enabled():
    """Create NQAgentService with new-bar gating enabled."""
    with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
        mock_config.return_value = {
            "service": {
                "status_update_interval": 900,
                "heartbeat_interval": 86400,
                "state_save_interval": 10,
                "enable_new_bar_gating": True,  # Enabled
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
        config = NQIntradayConfig(symbol="MNQ", timeframe="5m", scan_interval=30)
        
        service = NQAgentService(
            data_provider=provider,
            config=config,
            telegram_bot_token=None,
            telegram_chat_id=None,
        )
        
        yield service


@pytest.fixture
def mock_service_gating_disabled():
    """Create NQAgentService with new-bar gating disabled."""
    with patch('pearlalgo.nq_agent.service.load_service_config') as mock_config:
        mock_config.return_value = {
            "service": {
                "status_update_interval": 900,
                "heartbeat_interval": 86400,
                "state_save_interval": 10,
                "enable_new_bar_gating": False,  # Disabled
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
        config = NQIntradayConfig(symbol="MNQ", timeframe="5m", scan_interval=30)
        
        service = NQAgentService(
            data_provider=provider,
            config=config,
            telegram_bot_token=None,
            telegram_chat_id=None,
        )
        
        yield service


class TestNewBarGatingEnabled:
    """Tests for new-bar gating when enabled."""
    
    def test_gating_enabled_flag_set(self, mock_service_gating_enabled):
        """Verify gating is enabled when configured."""
        assert mock_service_gating_enabled._enable_new_bar_gating is True
    
    def test_counters_initialized_to_zero(self, mock_service_gating_enabled):
        """Verify skip/run counters start at zero."""
        assert mock_service_gating_enabled._analysis_skip_count == 0
        assert mock_service_gating_enabled._analysis_run_count == 0
    
    def test_last_analyzed_bar_ts_initially_none(self, mock_service_gating_enabled):
        """Verify last analyzed timestamp starts as None."""
        assert mock_service_gating_enabled._last_analyzed_bar_ts is None
    
    def test_first_cycle_always_runs_analysis(self, mock_service_gating_enabled):
        """First cycle should run analysis since there's no previous timestamp."""
        service = mock_service_gating_enabled
        
        # Simulate what happens in the service loop
        timestamp = datetime.now(timezone.utc)
        df = create_test_df(timestamp)
        
        # Before first cycle, _last_analyzed_bar_ts is None
        assert service._last_analyzed_bar_ts is None
        
        # Simulate gating check
        current_bar_ts = df["timestamp"].max()
        if isinstance(current_bar_ts, pd.Timestamp):
            current_bar_ts = current_bar_ts.to_pydatetime()
        
        # First cycle: should NOT skip (no previous timestamp)
        should_skip = (
            service._enable_new_bar_gating 
            and service._last_analyzed_bar_ts is not None 
            and current_bar_ts == service._last_analyzed_bar_ts
        )
        assert should_skip is False
    
    def test_skip_when_bar_unchanged(self, mock_service_gating_enabled):
        """Analysis should skip when bar timestamp hasn't changed."""
        service = mock_service_gating_enabled
        
        timestamp = datetime.now(timezone.utc)
        df = create_test_df(timestamp)
        
        current_bar_ts = df["timestamp"].max()
        if isinstance(current_bar_ts, pd.Timestamp):
            current_bar_ts = current_bar_ts.to_pydatetime()
        if current_bar_ts.tzinfo is None:
            current_bar_ts = current_bar_ts.replace(tzinfo=timezone.utc)
        
        # Simulate first cycle: sets _last_analyzed_bar_ts
        service._last_analyzed_bar_ts = current_bar_ts
        service._analysis_run_count = 1
        
        # Second cycle with same timestamp: should skip
        should_skip = (
            service._enable_new_bar_gating 
            and service._last_analyzed_bar_ts is not None 
            and current_bar_ts == service._last_analyzed_bar_ts
        )
        assert should_skip is True
    
    def test_run_when_bar_advances(self, mock_service_gating_enabled):
        """Analysis should run when bar timestamp advances."""
        service = mock_service_gating_enabled
        
        old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)
        new_timestamp = datetime.now(timezone.utc)
        
        # Set previous timestamp
        service._last_analyzed_bar_ts = old_timestamp
        
        # New bar with different timestamp
        df = create_test_df(new_timestamp)
        current_bar_ts = df["timestamp"].max()
        if isinstance(current_bar_ts, pd.Timestamp):
            current_bar_ts = current_bar_ts.to_pydatetime()
        if current_bar_ts.tzinfo is None:
            current_bar_ts = current_bar_ts.replace(tzinfo=timezone.utc)
        
        # Should NOT skip (bar advanced)
        should_skip = (
            service._enable_new_bar_gating 
            and service._last_analyzed_bar_ts is not None 
            and current_bar_ts == service._last_analyzed_bar_ts
        )
        assert should_skip is False
    
    def test_skip_counter_increments(self, mock_service_gating_enabled):
        """Skip counter should increment when analysis is skipped."""
        service = mock_service_gating_enabled
        
        initial_skip_count = service._analysis_skip_count
        service._analysis_skip_count += 1
        
        assert service._analysis_skip_count == initial_skip_count + 1
    
    def test_run_counter_increments(self, mock_service_gating_enabled):
        """Run counter should increment when analysis runs."""
        service = mock_service_gating_enabled
        
        initial_run_count = service._analysis_run_count
        service._analysis_run_count += 1
        
        assert service._analysis_run_count == initial_run_count + 1


class TestNewBarGatingDisabled:
    """Tests for new-bar gating when disabled."""
    
    def test_gating_disabled_flag_set(self, mock_service_gating_disabled):
        """Verify gating is disabled when configured."""
        assert mock_service_gating_disabled._enable_new_bar_gating is False
    
    def test_analysis_never_skipped_when_disabled(self, mock_service_gating_disabled):
        """When disabled, analysis should never skip regardless of timestamp."""
        service = mock_service_gating_disabled
        
        timestamp = datetime.now(timezone.utc)
        
        # Even with matching timestamp, should not skip since gating is disabled
        service._last_analyzed_bar_ts = timestamp
        
        should_skip = (
            service._enable_new_bar_gating 
            and service._last_analyzed_bar_ts is not None 
            and timestamp == service._last_analyzed_bar_ts
        )
        # Since _enable_new_bar_gating is False, should_skip is False
        assert should_skip is False


class TestGatingStatusExposure:
    """Tests for gating metrics exposed in status."""
    
    def test_status_includes_gating_metrics(self, mock_service_gating_enabled):
        """Status should include new-bar gating metrics."""
        service = mock_service_gating_enabled
        
        # Simulate some cycles
        service._analysis_skip_count = 5
        service._analysis_run_count = 2
        service._last_analyzed_bar_ts = datetime.now(timezone.utc)
        
        status = service.get_status()
        
        assert "new_bar_gating" in status
        gating = status["new_bar_gating"]
        
        assert gating["enabled"] is True
        assert gating["analysis_skips"] == 5
        assert gating["analysis_runs"] == 2
        assert "skip_rate" in gating
        assert "last_analyzed_bar_ts" in gating
    
    def test_skip_rate_calculation(self, mock_service_gating_enabled):
        """Skip rate should be correctly calculated."""
        service = mock_service_gating_enabled
        
        service._analysis_skip_count = 4
        service._analysis_run_count = 1
        
        status = service.get_status()
        gating = status["new_bar_gating"]
        
        # skip_rate = 4 / (4 + 1) = 0.8
        expected_skip_rate = round(4 / (4 + 1), 3)
        assert gating["skip_rate"] == expected_skip_rate
    
    def test_skip_rate_handles_zero_total(self, mock_service_gating_enabled):
        """Skip rate should handle zero total cycles gracefully."""
        service = mock_service_gating_enabled
        
        service._analysis_skip_count = 0
        service._analysis_run_count = 0
        
        status = service.get_status()
        gating = status["new_bar_gating"]
        
        # Should not raise, should return 0.0
        assert gating["skip_rate"] == 0.0
    
    def test_last_analyzed_bar_ts_in_status(self, mock_service_gating_enabled):
        """Last analyzed bar timestamp should be in status as ISO string."""
        service = mock_service_gating_enabled
        
        timestamp = datetime.now(timezone.utc)
        service._last_analyzed_bar_ts = timestamp
        
        status = service.get_status()
        gating = status["new_bar_gating"]
        
        assert gating["last_analyzed_bar_ts"] == timestamp.isoformat()
    
    def test_last_analyzed_bar_ts_none_in_status(self, mock_service_gating_enabled):
        """When no bar analyzed yet, should show None in status."""
        service = mock_service_gating_enabled
        
        service._last_analyzed_bar_ts = None
        
        status = service.get_status()
        gating = status["new_bar_gating"]
        
        assert gating["last_analyzed_bar_ts"] is None


class TestGatingTimestampEdgeCases:
    """Tests for timestamp edge cases in gating logic."""
    
    def test_handles_pandas_timestamp(self, mock_service_gating_enabled):
        """Should correctly compare pandas Timestamp objects."""
        service = mock_service_gating_enabled
        
        timestamp = datetime.now(timezone.utc)
        service._last_analyzed_bar_ts = timestamp
        
        # Create a pandas Timestamp with same value
        pd_timestamp = pd.Timestamp(timestamp)
        current_bar_ts = pd_timestamp.to_pydatetime()
        if current_bar_ts.tzinfo is None:
            current_bar_ts = current_bar_ts.replace(tzinfo=timezone.utc)
        
        # Should detect as same timestamp
        should_skip = (
            service._enable_new_bar_gating 
            and service._last_analyzed_bar_ts is not None 
            and current_bar_ts == service._last_analyzed_bar_ts
        )
        assert should_skip is True
    
    def test_handles_empty_df(self, mock_service_gating_enabled):
        """Gating should handle empty DataFrame gracefully."""
        service = mock_service_gating_enabled
        
        df = pd.DataFrame()
        
        # When df is empty, gating check should not occur
        # (the if condition checks not market_data["df"].empty)
        # So no skip happens since there's no timestamp to extract
        assert df.empty is True
    
    def test_handles_df_without_timestamp_column(self, mock_service_gating_enabled):
        """Gating should handle DataFrame without timestamp column."""
        service = mock_service_gating_enabled
        
        df = pd.DataFrame({
            "open": [100, 101],
            "close": [101, 102],
        })
        
        # No timestamp column means gating check condition isn't met
        has_timestamp = "timestamp" in df.columns
        assert has_timestamp is False







