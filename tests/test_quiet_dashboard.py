"""
Tests for the quiet dashboard feature.

Validates:
- Dashboard emits even when data is empty
- Quiet reason is determined correctly for various scenarios
- Telegram formatting includes quiet reason
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.utils.telegram_alerts import format_home_card


class TestQuietReasonFormatting:
    """Tests for quiet reason display in format_home_card."""

    def test_no_quiet_reason_when_active(self) -> None:
        """No quiet reason line when agent is actively trading."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="Active",
        )
        # "Active" should not show a quiet reason line
        assert "Session closed" not in message
        assert "Scanning" not in message
        assert "Status unknown" not in message

    def test_strategy_session_closed_reason(self) -> None:
        """Strategy session closed reason shows correctly."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=False,  # Session gate is closed
            quiet_reason="StrategySessionClosed",
        )
        assert "📴 Session closed" in message

    def test_futures_market_closed_reason(self) -> None:
        """Futures market closed reason shows correctly."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=False,  # Market gate is closed
            strategy_session_open=True,
            quiet_reason="FuturesMarketClosed",
        )
        assert "🌙 Market closed" in message

    def test_stale_data_reason(self) -> None:
        """Stale data reason shows correctly."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="StaleData",
        )
        assert "⏰ Data stale" in message

    def test_no_opportunity_reason(self) -> None:
        """No opportunity reason shows correctly."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="NoOpportunity",
        )
        assert "👀 Scanning" in message

    def test_data_gap_reason(self) -> None:
        """Data gap reason shows correctly."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="DataGap",
        )
        assert "📉 Data gap" in message

    def test_no_quiet_reason_when_paused(self) -> None:
        """Quiet reason not shown when agent is paused."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            paused=True,
            quiet_reason="NoOpportunity",
        )
        # When paused, quiet reason should not appear
        assert "Scanning" not in message


class TestQuietReasonDetermination:
    """Tests for _get_quiet_reason method in NQAgentService."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create a minimal NQAgentService for testing."""
        from pearlalgo.nq_agent.service import NQAgentService
        from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
        from tests.mock_data_provider import MockDataProvider

        with patch("pearlalgo.nq_agent.service.load_service_config") as mock_config:
            mock_config.return_value = {
                "service": {
                    "status_update_interval": 3600,
                    "heartbeat_interval": 3600,
                    "state_save_interval": 100,
                    "cadence_mode": "fixed",
                },
                "circuit_breaker": {
                    "max_consecutive_errors": 10,
                    "max_connection_failures": 10,
                    "max_data_fetch_errors": 5,
                },
                "data": {
                    "stale_data_threshold_minutes": 10,
                    "connection_timeout_minutes": 30,
                    "buffer_size": 100,
                },
            }

            provider = MockDataProvider(base_price=17500.0, volatility=50.0)
            config = NQIntradayConfig()
            config.scan_interval = 30

            service = NQAgentService(
                data_provider=provider,
                config=config,
                state_dir=tmp_path,
            )
            return service

    def test_quiet_reason_strategy_session_closed(self, service) -> None:
        """Returns StrategySessionClosed when strategy session is closed."""
        # Mock strategy session to be closed
        service.strategy.scanner.is_market_hours = MagicMock(return_value=False)
        
        reason = service._get_quiet_reason({}, has_data=True, no_signals=True)
        assert reason == "StrategySessionClosed"

    def test_quiet_reason_no_opportunity(self, service) -> None:
        """Returns NoOpportunity when session is open but no signals."""
        # Mock both gates as open
        service.strategy.scanner.is_market_hours = MagicMock(return_value=True)
        with patch("pearlalgo.nq_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            
            # Provide fresh market data
            market_data = {
                "df": MagicMock(empty=False),
                "latest_bar": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }
            
            reason = service._get_quiet_reason(market_data, has_data=True, no_signals=True)
            assert reason == "NoOpportunity"

    def test_quiet_reason_no_data(self, service) -> None:
        """Returns NoData when no data is available."""
        # Mock both gates as open
        service.strategy.scanner.is_market_hours = MagicMock(return_value=True)
        with patch("pearlalgo.nq_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            
            reason = service._get_quiet_reason(None, has_data=False)
            assert reason == "NoData"


@pytest.mark.asyncio
async def test_dashboard_emits_when_data_empty(tmp_path) -> None:
    """
    Integration test: dashboard should emit even when data is empty.
    
    This validates the quiet dashboard feature where the agent
    continues to show its status even when no data is available.
    """
    from pearlalgo.nq_agent.service import NQAgentService
    from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
    from tests.mock_data_provider import MockDataProvider

    with patch("pearlalgo.nq_agent.service.load_service_config") as mock_config:
        mock_config.return_value = {
            "service": {
                "status_update_interval": 0.1,  # Very short for testing
                "heartbeat_interval": 3600,
                "state_save_interval": 100,
                "cadence_mode": "fixed",
            },
            "circuit_breaker": {
                "max_consecutive_errors": 10,
                "max_connection_failures": 10,
                "max_data_fetch_errors": 5,
            },
            "data": {
                "stale_data_threshold_minutes": 10,
                "connection_timeout_minutes": 30,
                "buffer_size": 100,
            },
        }

        # Create provider that returns empty data
        import pandas as pd
        provider = MockDataProvider(base_price=17500.0, volatility=50.0)
        provider.get_historical_bars = AsyncMock(return_value=pd.DataFrame())
        
        config = NQIntradayConfig()
        config.scan_interval = 0.1  # Fast cycles for testing

        service = NQAgentService(
            data_provider=provider,
            config=config,
            state_dir=tmp_path,
        )
        
        # Mock the Telegram notifier
        service.telegram_notifier.send_dashboard = AsyncMock(return_value=True)
        
        # Run service briefly
        task = asyncio.create_task(service.start())
        await asyncio.sleep(0.3)  # Run for ~3 cycles
        await service.stop("test")
        await asyncio.wait_for(task, timeout=2.0)
        
        # Verify dashboard was called
        assert service.telegram_notifier.send_dashboard.called
        
        # Check that a quiet_reason was passed
        call_args = service.telegram_notifier.send_dashboard.call_args
        status_arg = call_args[0][0]  # First positional arg
        # Status should have been passed (could be empty dict or None)
        # The key test is that dashboard was called despite empty data

