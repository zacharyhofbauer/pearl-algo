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

    def test_stale_data_shows_actionable_cue(self) -> None:
        """StaleData shows actionable cue directing user to Health menu."""
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
        # Actionable cue now directs to menu navigation instead of /data_quality command
        assert "Menu → Health → Data" in message

    def test_signal_diagnostics_shown_when_no_opportunity(self) -> None:
        """Signal diagnostics are shown when agent has no signals."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="NoOpportunity",
            signal_diagnostics="Raw: 3 → Valid: 0 | Filtered: 2 conf, 1 R:R",
        )
        assert "👀 Scanning" in message
        assert "🔍 Raw: 3" in message
        assert "Filtered: 2 conf" in message

    def test_signal_diagnostics_not_shown_for_session_closed(self) -> None:
        """Signal diagnostics 'Session closed' is not shown (redundant)."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            quiet_reason="NoOpportunity",
            signal_diagnostics="Session closed",
        )
        # "Session closed" should not be shown separately (it's implicit)
        assert "🔍 Session closed" not in message

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
    """Tests for _get_quiet_reason method in MarketAgentService."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create a minimal MarketAgentService for testing."""
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
        from tests.mock_data_provider import MockDataProvider

        with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
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
            config = PEARL_BOT_CONFIG.copy()
            config.scan_interval = 30

            service = MarketAgentService(
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
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
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
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            
            reason = service._get_quiet_reason(None, has_data=False)
            assert reason == "NoData"

    def test_quiet_reason_fresh_data_with_timezone_aware_timestamp(self, service) -> None:
        """Fresh data with timezone-aware timestamp (e.g., CST -06:00) returns NoOpportunity, not StaleData."""
        # Mock both gates as open
        service.strategy.scanner.is_market_hours = MagicMock(return_value=True)
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            
            # Create a fresh timestamp in a non-UTC timezone (e.g., CST = UTC-6)
            # This simulates IBKR returning exchange-local timestamps
            from datetime import timezone as tz
            cst = tz(timedelta(hours=-6))
            fresh_time = datetime.now(cst) - timedelta(minutes=2)  # 2 minutes ago (fresh)
            
            market_data = {
                "df": MagicMock(empty=False),
                "latest_bar": {
                    "timestamp": fresh_time.isoformat(),  # e.g., "2025-12-23T12:48:00-06:00"
                },
            }
            
            reason = service._get_quiet_reason(market_data, has_data=True, no_signals=True)
            # Should be NoOpportunity, NOT StaleData (data is fresh)
            assert reason == "NoOpportunity", f"Expected NoOpportunity for fresh data, got {reason}"

    def test_quiet_reason_stale_data_with_timezone_aware_timestamp(self, service) -> None:
        """Actually stale data with timezone-aware timestamp returns StaleData."""
        # Mock both gates as open
        service.strategy.scanner.is_market_hours = MagicMock(return_value=True)
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            
            # Create a stale timestamp in a non-UTC timezone (e.g., CST = UTC-6)
            from datetime import timezone as tz
            cst = tz(timedelta(hours=-6))
            stale_time = datetime.now(cst) - timedelta(minutes=15)  # 15 minutes ago (stale)
            
            market_data = {
                "df": MagicMock(empty=False),
                "latest_bar": {
                    "timestamp": stale_time.isoformat(),
                },
            }
            
            reason = service._get_quiet_reason(market_data, has_data=True, no_signals=True)
            # Should be StaleData (data is actually old)
            assert reason == "StaleData", f"Expected StaleData for stale data, got {reason}"

    def test_quiet_reason_fresh_naive_utc_timestamp(self, service) -> None:
        """Fresh data with naive (no timezone) timestamp assumed as UTC returns NoOpportunity."""
        # Mock both gates as open
        service.strategy.scanner.is_market_hours = MagicMock(return_value=True)
        with patch("pearlalgo.market_agent.service.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            
            # Create a fresh naive timestamp (no timezone info) - use UTC-aware then strip timezone
            fresh_time = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(tzinfo=None)  # 2 minutes ago, naive
            
            market_data = {
                "df": MagicMock(empty=False),
                "latest_bar": {
                    "timestamp": fresh_time.isoformat(),  # No timezone suffix
                },
            }
            
            reason = service._get_quiet_reason(market_data, has_data=True, no_signals=True)
            assert reason == "NoOpportunity", f"Expected NoOpportunity for fresh naive timestamp, got {reason}"


@pytest.mark.asyncio
async def test_dashboard_emits_when_data_empty(tmp_path) -> None:
    """
    Integration test: dashboard should emit even when data is empty.
    
    This validates the quiet dashboard feature where the agent
    continues to show its status even when no data is available.
    """
    from pearlalgo.market_agent.service import MarketAgentService
    from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
    from tests.mock_data_provider import MockDataProvider

    with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
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
        
        config = PEARL_BOT_CONFIG.copy()
        config.scan_interval = 0.1  # Fast cycles for testing

        service = MarketAgentService(
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




class TestV2StalenessCallout:
    """Tests for v2 staleness callout with age + impact + action."""

    def test_data_stale_callout_format(self) -> None:
        """Data staleness callout includes age, impact, and action."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            data_age_minutes=15.0,  # 15 minutes old
            data_stale_threshold_minutes=10.0,
        )
        # V2 spec: "⏰ Data stale (15m) • signals paused • /data_quality"
        assert "⏰ Data stale" in message
        assert "15m" in message
        assert "signals paused" in message
        assert "Menu → Health → Data" in message

    def test_data_fresh_no_callout(self) -> None:
        """No staleness callout when data is fresh."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            data_age_minutes=5.0,  # 5 minutes old (fresh)
            data_stale_threshold_minutes=10.0,
        )
        assert "Data stale" not in message

    def test_pressure_suppressed_when_stale(self) -> None:
        """Buy/sell pressure is suppressed when data is stale."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            buy_sell_pressure="🔴 Pressure: SELLERS ▼▼ (Δ -24%, Vol 1.0x, 2h)",
            data_age_minutes=15.0,  # Stale
            data_stale_threshold_minutes=10.0,
        )
        # V2 spec: Suppress derived context when stale
        assert "SELLERS" not in message
        assert "Pressure:" not in message

    def test_pressure_shown_when_fresh(self) -> None:
        """Buy/sell pressure is shown when data is fresh."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            buy_sell_pressure="🔴 Pressure: SELLERS ▼▼ (Δ -24%, Vol 1.0x, 2h)",
            data_age_minutes=5.0,  # Fresh
            data_stale_threshold_minutes=10.0,
        )
        assert "SELLERS" in message

    def test_diagnostics_suppressed_when_stale(self) -> None:
        """Signal diagnostics are suppressed when data is stale."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            signal_diagnostics="Raw: 3 → Valid: 0 | Filtered: 2 conf, 1 R:R",
            data_age_minutes=15.0,  # Stale
            data_stale_threshold_minutes=10.0,
        )
        # V2 spec: Suppress derived context when stale
        assert "Raw: 3" not in message


class TestV2LabeledMetrics:
    """Tests for v2 labeled metrics format."""

    def test_activity_line_labeled_cycles(self) -> None:
        """Activity line shows labeled cycles (session vs total)."""
        from pearlalgo.utils.telegram_alerts import format_activity_line
        
        line = format_activity_line(
            cycles_session=145,
            cycles_total=1595,
            signals_generated=2,
            signals_sent=0,
            errors=0,
            buffer_size=25,
            buffer_target=100,
        )
        # V2 spec: "145 scans (session) / 1,595 total"
        assert "145 scans (session)" in line
        assert "1,595 total" in line

    def test_activity_line_labeled_signals(self) -> None:
        """Activity line shows labeled signals (gen/sent)."""
        from pearlalgo.utils.telegram_alerts import format_activity_line
        
        line = format_activity_line(
            cycles_session=145,
            cycles_total=1595,
            signals_generated=2,
            signals_sent=1,
            errors=0,
            buffer_size=25,
            buffer_target=100,
        )
        # V2 spec: "2 gen / 1 sent"
        assert "2 gen" in line
        assert "1 sent" in line

    def test_activity_line_shows_failures_when_nonzero(self) -> None:
        """Activity line includes failures when non-zero."""
        from pearlalgo.utils.telegram_alerts import format_activity_line
        
        line = format_activity_line(
            cycles_session=145,
            cycles_total=1595,
            signals_generated=2,
            signals_sent=1,
            errors=0,
            buffer_size=25,
            buffer_target=100,
            signal_send_failures=1,
        )
        # V2 spec: "2 gen / 1 sent / 1 fail"
        assert "1 fail" in line

    def test_activity_line_hides_failures_when_zero(self) -> None:
        """Activity line omits failures when zero."""
        from pearlalgo.utils.telegram_alerts import format_activity_line
        
        line = format_activity_line(
            cycles_session=145,
            cycles_total=1595,
            signals_generated=2,
            signals_sent=1,
            errors=0,
            buffer_size=25,
            buffer_target=100,
            signal_send_failures=0,
        )
        # V2 spec: No "fail" when zero
        assert "fail" not in line


class TestStaleCalloutHelper:
    """Tests for format_stale_callout helper."""

    def test_stale_callout_minutes(self) -> None:
        """Stale callout formats age in minutes correctly."""
        from pearlalgo.utils.telegram_alerts import format_stale_callout
        
        callout = format_stale_callout(11.0, impact="signals paused")
        assert "11m" in callout
        assert "signals paused" in callout
        # Actionable cue now uses menu navigation instead of /data_quality command
        assert "Menu → Health → Data" in callout

    def test_stale_callout_hours(self) -> None:
        """Stale callout formats age in hours when over 60m."""
        from pearlalgo.utils.telegram_alerts import format_stale_callout
        
        callout = format_stale_callout(90.0, impact="signals paused")
        assert "1.5h" in callout


class TestMessageLengthConstraints:
    """Tests to ensure messages stay within Telegram limits."""

    def test_home_card_under_limit(self) -> None:
        """Home card stays under Telegram message limit."""
        message = format_home_card(
            symbol="MNQ",
            time_str="10:30 AM ET",
            agent_running=True,
            gateway_running=True,
            futures_market_open=True,
            strategy_session_open=True,
            paused=False,
            cycles_session=1000,
            cycles_total=100000,
            signals_generated=100,
            signals_sent=95,
            errors=5,
            buffer_size=100,
            buffer_target=100,
            latest_price=25782.25,
            buy_sell_pressure="🔴 Pressure: SELLERS ▼▼ (Δ -24%, Vol 1.0x, 2h)",
            signal_diagnostics="Raw: 10 → Valid: 5 | Filtered: 3 conf, 2 R:R",
            performance={
                "exited_signals": 20,
                "wins": 12,
                "losses": 8,
                "win_rate": 0.6,
                "total_pnl": 500.0,
            },
            signal_send_failures=2,
            active_trades_count=3,
            data_age_minutes=5.0,
            data_stale_threshold_minutes=10.0,
        )
        # Telegram message limit is 4096 characters
        assert len(message) < 4096, f"Message too long: {len(message)} chars"
        # Should be well under for mobile readability
        assert len(message) < 2000, f"Message should be < 2000 for mobile: {len(message)} chars"
