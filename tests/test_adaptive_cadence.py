"""
Tests for adaptive cadence and session boundary transitions.

Validates:
- Adaptive cadence interval computation based on market/session state
- Smooth interval transitions at session boundaries (16:10 ET close, 18:00 ET open)
- Integration with CadenceScheduler.set_interval()
- State persistence of effective interval
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from pearlalgo.utils.cadence import CadenceScheduler


def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build an ET datetime and convert to UTC for stable assertions."""
    et = ZoneInfo("America/New_York")
    return datetime(year, month, day, hour, minute, tzinfo=et).astimezone(timezone.utc)


class TestAdaptiveCadenceIntervalComputation:
    """Tests for _compute_effective_interval logic."""

    def test_paused_returns_paused_interval(self) -> None:
        """When service is paused, should return paused interval regardless of market state."""
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from tests.mock_data_provider import MockDataProvider
        
        provider = MockDataProvider(base_price=17500.0, volatility=50.0)
        config = PEARL_BOT_CONFIG.copy()
        
        with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
            mock_config.return_value = {
                "service": {
                    "adaptive_cadence_enabled": True,
                    "scan_interval_active_seconds": 5,
                    "scan_interval_idle_seconds": 30,
                    "scan_interval_market_closed_seconds": 300,
                    "scan_interval_paused_seconds": 60,
                    "status_update_interval": 3600,
                    "heartbeat_interval": 3600,
                    "state_save_interval": 100,
                },
                "circuit_breaker": {},
                "data": {"buffer_size": 100},
            }
            
            service = MarketAgentService(data_provider=provider, config=config)
            service.paused = True
            
            effective = service._compute_effective_interval()
            assert effective == 60.0, f"Expected 60s paused interval, got {effective}s"

    def test_market_closed_returns_market_closed_interval(self) -> None:
        """When futures market is closed, should return market_closed interval."""
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from tests.mock_data_provider import MockDataProvider
        
        provider = MockDataProvider(base_price=17500.0, volatility=50.0)
        config = PEARL_BOT_CONFIG.copy()
        
        with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
            mock_config.return_value = {
                "service": {
                    "adaptive_cadence_enabled": True,
                    "scan_interval_active_seconds": 5,
                    "scan_interval_idle_seconds": 30,
                    "scan_interval_market_closed_seconds": 300,
                    "scan_interval_paused_seconds": 60,
                    "status_update_interval": 3600,
                    "heartbeat_interval": 3600,
                    "state_save_interval": 100,
                },
                "circuit_breaker": {},
                "data": {"buffer_size": 100},
            }
            
            service = MarketAgentService(data_provider=provider, config=config)
            
            # Mock market hours to return closed
            with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
                mock_mh.return_value.is_market_open.return_value = False
                
                effective = service._compute_effective_interval()
                assert effective == 300.0, f"Expected 300s market_closed interval, got {effective}s"

    def test_session_open_returns_active_interval(self) -> None:
        """When strategy session is open, should return active interval."""
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from tests.mock_data_provider import MockDataProvider
        
        provider = MockDataProvider(base_price=17500.0, volatility=50.0)
        config = PEARL_BOT_CONFIG.copy()
        config.start_time = "18:00"  # type: ignore[assignment]
        config.end_time = "16:10"  # type: ignore[assignment]
        
        with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
            mock_config.return_value = {
                "service": {
                    "adaptive_cadence_enabled": True,
                    "scan_interval_active_seconds": 5,
                    "scan_interval_idle_seconds": 30,
                    "scan_interval_market_closed_seconds": 300,
                    "scan_interval_paused_seconds": 60,
                    "status_update_interval": 3600,
                    "heartbeat_interval": 3600,
                    "state_save_interval": 100,
                },
                "circuit_breaker": {},
                "data": {"buffer_size": 100},
            }
            
            service = MarketAgentService(data_provider=provider, config=config)
            
            # Mock market hours to return open
            with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                # Mock scanner.is_market_hours to return True (session open)
                service.strategy.scanner.is_market_hours = MagicMock(return_value=True)
                
                effective = service._compute_effective_interval()
                assert effective == 5.0, f"Expected 5s active interval, got {effective}s"

    def test_session_closed_returns_idle_interval(self) -> None:
        """When futures open but session closed, should return idle interval."""
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from tests.mock_data_provider import MockDataProvider
        
        provider = MockDataProvider(base_price=17500.0, volatility=50.0)
        config = PEARL_BOT_CONFIG.copy()
        
        with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
            mock_config.return_value = {
                "service": {
                    "adaptive_cadence_enabled": True,
                    "scan_interval_active_seconds": 5,
                    "scan_interval_idle_seconds": 30,
                    "scan_interval_market_closed_seconds": 300,
                    "scan_interval_paused_seconds": 60,
                    "status_update_interval": 3600,
                    "heartbeat_interval": 3600,
                    "state_save_interval": 100,
                },
                "circuit_breaker": {},
                "data": {"buffer_size": 100},
            }
            
            service = MarketAgentService(data_provider=provider, config=config)
            
            # Mock market hours to return open
            with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
                mock_mh.return_value.is_market_open.return_value = True
                
                # Mock scanner.is_market_hours to return False (session closed)
                service.strategy.scanner.is_market_hours = MagicMock(return_value=False)
                
                effective = service._compute_effective_interval()
                assert effective == 30.0, f"Expected 30s idle interval, got {effective}s"

    def test_adaptive_disabled_returns_base_interval(self) -> None:
        """When adaptive cadence is disabled, should return base config interval."""
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from tests.mock_data_provider import MockDataProvider
        
        provider = MockDataProvider(base_price=17500.0, volatility=50.0)
        config = PEARL_BOT_CONFIG.copy()
        config.scan_interval = 30
        
        with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
            mock_config.return_value = {
                "service": {
                    "adaptive_cadence_enabled": False,  # Disabled
                    "scan_interval_active_seconds": 5,
                    "scan_interval_idle_seconds": 30,
                    "scan_interval_market_closed_seconds": 300,
                    "scan_interval_paused_seconds": 60,
                    "status_update_interval": 3600,
                    "heartbeat_interval": 3600,
                    "state_save_interval": 100,
                },
                "circuit_breaker": {},
                "data": {"buffer_size": 100},
            }
            
            service = MarketAgentService(data_provider=provider, config=config)
            
            effective = service._compute_effective_interval()
            assert effective == 30.0, f"Expected 30s base interval, got {effective}s"


class TestSessionBoundaryTransitions:
    """Tests for interval transitions at session open/close boundaries."""

    def test_transition_at_session_close_1610_et(self) -> None:
        """
        Test interval transition when session closes at 16:10 ET.
        
        Before 16:10: strategy session open -> active interval (5s)
        After 16:10: strategy session closed, futures open -> idle interval (30s)
        """
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from pearlalgo.strategies.nq_intraday.scanner import NQScanner
        
        config = PEARL_BOT_CONFIG.copy()
        config.start_time = "18:00"  # type: ignore[assignment]
        config.end_time = "16:10"  # type: ignore[assignment]
        
        scanner = NQScanner(config=config)
        
        # Monday 16:05 ET (5 minutes before close) - should be OPEN
        before_close = _to_utc(2025, 12, 22, 16, 5)
        assert scanner.is_market_hours(dt=before_close) is True
        
        # Monday 16:15 ET (5 minutes after close) - should be CLOSED
        after_close = _to_utc(2025, 12, 22, 16, 15)
        assert scanner.is_market_hours(dt=after_close) is False
        
        # Edge case: exactly at 16:10 - should be OPEN (end time is inclusive)
        # The session includes the 16:10 minute, closes at 16:11
        at_close = _to_utc(2025, 12, 22, 16, 10)
        assert scanner.is_market_hours(dt=at_close) is True
        
        # 16:11 ET - should be CLOSED (first minute after session)
        after_close_1min = _to_utc(2025, 12, 22, 16, 11)
        assert scanner.is_market_hours(dt=after_close_1min) is False

    def test_transition_at_session_open_1800_et(self) -> None:
        """
        Test interval transition when session opens at 18:00 ET.
        
        Before 18:00: strategy session closed, futures may be open -> idle interval (30s)
        After 18:00: strategy session open -> active interval (5s)
        """
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from pearlalgo.strategies.nq_intraday.scanner import NQScanner
        
        config = PEARL_BOT_CONFIG.copy()
        config.start_time = "18:00"  # type: ignore[assignment]
        config.end_time = "16:10"  # type: ignore[assignment]
        
        scanner = NQScanner(config=config)
        
        # Monday 17:55 ET (5 minutes before open) - should be CLOSED
        before_open = _to_utc(2025, 12, 22, 17, 55)
        assert scanner.is_market_hours(dt=before_open) is False
        
        # Monday 18:05 ET (5 minutes after open) - should be OPEN
        after_open = _to_utc(2025, 12, 22, 18, 5)
        assert scanner.is_market_hours(dt=after_open) is True
        
        # Edge case: exactly at 18:00 - should be OPEN (start is inclusive)
        at_open = _to_utc(2025, 12, 22, 18, 0)
        assert scanner.is_market_hours(dt=at_open) is True

    def test_cadence_scheduler_handles_interval_change_smoothly(self) -> None:
        """
        Test that CadenceScheduler handles interval changes without catch-up storms.
        
        Simulates the scenario where interval changes from 5s (active) to 30s (idle)
        at session close.
        """
        scheduler = CadenceScheduler(interval_seconds=5.0)
        
        # Run a few cycles at 5s interval
        for _ in range(3):
            scheduler.mark_cycle_start()
            scheduler.mark_cycle_end()
        
        # Change interval to 30s (simulating session close)
        scheduler.set_interval(30.0)
        
        # Verify schedule was reset (no catch-up)
        assert scheduler._next_scheduled is None
        assert scheduler.interval_seconds == 30.0
        
        # Next cycle should work normally at new interval
        scheduler.mark_cycle_start()
        sleep_time = scheduler.mark_cycle_end()
        
        # Sleep time should be approximately the new interval
        assert 29.5 <= sleep_time <= 30.5, f"Expected ~30s sleep, got {sleep_time}s"

    def test_rapid_interval_changes_do_not_cause_storms(self) -> None:
        """
        Test that rapid interval changes (edge case) don't cause timing issues.
        """
        scheduler = CadenceScheduler(interval_seconds=5.0)
        
        # Simulate rapid changes
        for interval in [5.0, 30.0, 5.0, 300.0, 5.0]:
            scheduler.set_interval(interval)
            scheduler.mark_cycle_start()
            sleep_time = scheduler.mark_cycle_end()
            
            # Each cycle should sleep approximately the current interval
            assert sleep_time >= interval * 0.9, f"Sleep too short: {sleep_time}s for interval {interval}s"
            assert sleep_time <= interval * 1.1, f"Sleep too long: {sleep_time}s for interval {interval}s"


class TestStatePersistence:
    """Tests for effective interval state persistence."""

    def test_effective_interval_persisted_in_state(self, tmp_path) -> None:
        """
        Test that effective interval is persisted in state.json.
        """
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from tests.mock_data_provider import MockDataProvider
        import json
        
        provider = MockDataProvider(base_price=17500.0, volatility=50.0)
        config = PEARL_BOT_CONFIG.copy()
        
        with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
            mock_config.return_value = {
                "service": {
                    "adaptive_cadence_enabled": True,
                    "scan_interval_active_seconds": 5,
                    "scan_interval_idle_seconds": 30,
                    "scan_interval_market_closed_seconds": 300,
                    "scan_interval_paused_seconds": 60,
                    "status_update_interval": 3600,
                    "heartbeat_interval": 3600,
                    "state_save_interval": 1,
                },
                "circuit_breaker": {},
                "data": {"buffer_size": 100},
            }
            
            service = MarketAgentService(
                data_provider=provider,
                config=config,
                state_dir=tmp_path,
            )
            
            # Set effective interval
            service._effective_interval = 5.0
            service._adaptive_cadence_enabled = True
            
            # Save state
            service._save_state()
            
            # Read state file
            state_file = tmp_path / "state.json"
            with open(state_file) as f:
                state = json.load(f)
            
            # Verify effective interval is persisted
            assert state["config"]["scan_interval_effective"] == 5.0
            assert state["config"]["adaptive_cadence_enabled"] is True
            assert state["cadence_mode"] == "adaptive"

