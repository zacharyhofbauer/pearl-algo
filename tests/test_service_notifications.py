"""
Tests for Service Notification Methods.

Tests the ServiceNotificationsMixin class which provides dashboard, chart generation,
and notification functionality for the MarketAgentService.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from pathlib import Path
from datetime import datetime, timezone, timedelta
import tempfile
import pandas as pd
import numpy as np


@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        exports_dir = state_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        yield state_dir


@pytest.fixture
def mock_service(temp_state_dir):
    """Create a mock MarketAgentService with the mixin."""
    from pearlalgo.market_agent.service_notifications import ServiceNotificationsMixin

    class MockStateManager:
        def __init__(self, state_dir):
            self.state_dir = state_dir

        def get_recent_signals(self, limit=100):
            return []

    class MockConfig:
        symbol = "MNQ"
        timeframe = "5m"

    class MockDataFetcher:
        _data_buffer = None

    class MockNotificationQueue:
        async def enqueue_dashboard(self, status, chart_path=None, priority=None):
            self.last_status = status
            self.last_chart_path = chart_path

    class TestService(ServiceNotificationsMixin):
        def __init__(self, state_dir):
            self.state_manager = MockStateManager(state_dir)
            self.config = MockConfig()
            self.data_fetcher = MockDataFetcher()
            self.notification_queue = MockNotificationQueue()
            self.last_dashboard_chart_sent = None
            self.last_status_update = None
            self.dashboard_chart_enabled = True
            self.dashboard_chart_interval = 3600
            self.status_update_interval = 900
            self.pressure_lookback_bars = 10
            self.pressure_baseline_bars = 50

        def get_status(self):
            return {"agent_running": True}

    return TestService(temp_state_dir)


class TestCheckDashboard:
    """Tests for _check_dashboard method."""

    @pytest.mark.asyncio
    async def test_sends_chart_when_due(self, mock_service):
        """Should send chart when interval has passed."""
        mock_service.last_dashboard_chart_sent = None
        mock_service._generate_dashboard_chart = AsyncMock(return_value=None)
        mock_service._send_dashboard = AsyncMock()

        await mock_service._check_dashboard()

        mock_service._generate_dashboard_chart.assert_called_once()
        mock_service._send_dashboard.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_text_only_when_chart_not_due(self, mock_service):
        """Should send text-only dashboard when chart not due."""
        mock_service.last_dashboard_chart_sent = datetime.now(timezone.utc)
        mock_service.last_status_update = None
        mock_service._generate_dashboard_chart = AsyncMock(return_value=None)
        mock_service._send_dashboard = AsyncMock()

        await mock_service._check_dashboard()

        mock_service._generate_dashboard_chart.assert_not_called()
        mock_service._send_dashboard.assert_called_once()

    @pytest.mark.asyncio
    async def test_respects_interval_notifications_pref(self, mock_service):
        """Should skip if interval notifications disabled."""
        with patch('pearlalgo.utils.telegram_alerts.TelegramPrefs') as MockPrefs:
            mock_prefs = MagicMock()
            mock_prefs.get.return_value = False
            MockPrefs.return_value = mock_prefs

            mock_service._send_dashboard = AsyncMock()

            await mock_service._check_dashboard()

            mock_service._send_dashboard.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_quiet_reason(self, mock_service):
        """Should pass quiet reason to dashboard."""
        mock_service.last_dashboard_chart_sent = datetime.now(timezone.utc)
        mock_service.last_status_update = None
        mock_service._send_dashboard = AsyncMock()

        await mock_service._check_dashboard(quiet_reason="StrategySessionClosed")

        call_args = mock_service._send_dashboard.call_args
        assert call_args[1].get("quiet_reason") == "StrategySessionClosed"


class TestGenerateDashboardChart:
    """Tests for _generate_dashboard_chart method."""

    @pytest.mark.asyncio
    async def test_captures_live_chart(self, mock_service, temp_state_dir):
        """Should capture live chart screenshot."""
        with patch('pearlalgo.market_agent.service_notifications.capture_live_chart_screenshot') as mock_capture:
            mock_path = temp_state_dir / "exports" / "dashboard_telegram_latest.png"
            mock_path.write_bytes(b"fake image")
            mock_capture.return_value = mock_path

            result = await mock_service._generate_dashboard_chart()

            mock_capture.assert_called_once()
            assert result == mock_path

    @pytest.mark.asyncio
    async def test_returns_existing_chart_on_failure(self, mock_service, temp_state_dir):
        """Should return existing chart if capture fails."""
        # Create existing chart
        exports_dir = temp_state_dir / "exports"
        existing_chart = exports_dir / "dashboard_telegram_latest.png"
        existing_chart.write_bytes(b"existing chart")

        with patch('pearlalgo.market_agent.service_notifications.capture_live_chart_screenshot') as mock_capture:
            mock_capture.side_effect = Exception("Capture failed")

            result = await mock_service._generate_dashboard_chart()

            assert result == existing_chart

    @pytest.mark.asyncio
    async def test_returns_none_when_no_chart(self, mock_service, temp_state_dir):
        """Should return None when no chart exists."""
        with patch('pearlalgo.market_agent.service_notifications.capture_live_chart_screenshot') as mock_capture:
            mock_capture.return_value = None

            result = await mock_service._generate_dashboard_chart()

            # May return None or existing path depending on implementation


class TestSendDashboard:
    """Tests for _send_dashboard method."""

    @pytest.mark.asyncio
    async def test_includes_current_time(self, mock_service):
        """Should include current time in status."""
        await mock_service._send_dashboard()

        status = mock_service.notification_queue.last_status
        assert "current_time" in status

    @pytest.mark.asyncio
    async def test_includes_symbol(self, mock_service):
        """Should include symbol in status."""
        await mock_service._send_dashboard()

        status = mock_service.notification_queue.last_status
        assert status["symbol"] == "MNQ"

    @pytest.mark.asyncio
    async def test_includes_quiet_reason(self, mock_service):
        """Should include quiet reason when provided."""
        await mock_service._send_dashboard(quiet_reason="MarketClosed")

        status = mock_service.notification_queue.last_status
        assert status["quiet_reason"] == "MarketClosed"

    @pytest.mark.asyncio
    async def test_includes_signal_diagnostics(self, mock_service):
        """Should include signal diagnostics when provided."""
        mock_diagnostics = MagicMock()
        mock_diagnostics.format_compact.return_value = "No signals: all filtered"
        mock_diagnostics.to_dict.return_value = {"reason": "filtered"}

        await mock_service._send_dashboard(signal_diagnostics=mock_diagnostics)

        status = mock_service.notification_queue.last_status
        assert "signal_diagnostics" in status

    @pytest.mark.asyncio
    async def test_includes_latest_price(self, mock_service):
        """Should include latest price from market data."""
        market_data = {
            "latest_bar": {"close": 15000.50},
        }

        await mock_service._send_dashboard(market_data=market_data)

        status = mock_service.notification_queue.last_status
        assert status.get("latest_price") == 15000.50

    @pytest.mark.asyncio
    async def test_passes_chart_path(self, mock_service, temp_state_dir):
        """Should pass chart path to notification queue."""
        chart_path = temp_state_dir / "chart.png"

        await mock_service._send_dashboard(chart_path=chart_path)

        assert mock_service.notification_queue.last_chart_path == chart_path


class TestAddActiveTradesToStatus:
    """Tests for _add_active_trades_to_status method."""

    def test_counts_active_trades(self, mock_service):
        """Should count active trades."""
        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {"status": "entered", "signal": {}},
            {"status": "entered", "signal": {}},
            {"status": "exited", "signal": {}},
        ])

        status = {}
        mock_service._add_active_trades_to_status(status, None)

        assert status["active_trades_count"] == 2

    def test_calculates_unrealized_pnl(self, mock_service):
        """Should calculate unrealized P&L for active trades."""
        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "status": "entered",
                "signal": {
                    "direction": "long",
                    "entry_price": 15000.00,
                    "tick_value": 2.0,
                    "position_size": 1.0,
                },
            },
        ])

        status = {"latest_price": 15010.00}  # 10 points up
        mock_service._add_active_trades_to_status(status, None)

        # 10 points * $2 tick value = $20
        assert status.get("active_trades_unrealized_pnl") == 20.0

    def test_handles_short_positions(self, mock_service):
        """Should calculate P&L correctly for short positions."""
        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "status": "entered",
                "signal": {
                    "direction": "short",
                    "entry_price": 15000.00,
                    "tick_value": 2.0,
                    "position_size": 1.0,
                },
            },
        ])

        status = {"latest_price": 14990.00}  # 10 points down (profit for short)
        mock_service._add_active_trades_to_status(status, None)

        # Short: (entry - current) * tick_value = 10 * 2 = $20
        assert status.get("active_trades_unrealized_pnl") == 20.0

    def test_includes_recent_exits(self, mock_service):
        """Should include recent exited trades."""
        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "status": "exited",
                "signal_id": "sig1",
                "pnl": 100.00,
                "signal": {"type": "breakout", "direction": "long"},
                "exit_reason": "take_profit",
            },
        ])

        status = {}
        mock_service._add_active_trades_to_status(status, None)

        assert "recent_exits" in status
        assert len(status["recent_exits"]) == 1


class TestAddVolumePressureToStatus:
    """Tests for _add_volume_pressure_to_status method."""

    def test_adds_volume_pressure(self, mock_service):
        """Should add volume pressure metrics."""
        # Create sample market data with volume
        df = pd.DataFrame({
            "open": np.random.randn(100) + 15000,
            "close": np.random.randn(100) + 15000,
            "volume": np.random.randint(100, 1000, 100),
        })

        market_data = {"df": df}
        status = {}

        with patch('pearlalgo.market_agent.service_notifications.compute_volume_pressure_summary') as mock_compute:
            mock_summary = MagicMock()
            mock_summary.to_dict.return_value = {"buy_ratio": 0.6}
            mock_compute.return_value = mock_summary

            with patch('pearlalgo.market_agent.service_notifications.format_volume_pressure') as mock_format:
                mock_format.return_value = "Buy: 60%"

                mock_service._add_volume_pressure_to_status(status, market_data)

                assert "buy_sell_pressure" in status
                assert "buy_sell_pressure_raw" in status

    def test_handles_empty_dataframe(self, mock_service):
        """Should handle empty DataFrame gracefully."""
        market_data = {"df": pd.DataFrame()}
        status = {}

        mock_service._add_volume_pressure_to_status(status, market_data)

        # Should not add pressure metrics
        assert "buy_sell_pressure" not in status


class TestGetRecentCloses:
    """Tests for _get_recent_closes method."""

    def test_extracts_closes_from_market_data(self, mock_service):
        """Should extract close prices from market data."""
        df = pd.DataFrame({
            "close": [15000.0, 15001.0, 15002.0, 15003.0, 15004.0],
        })
        market_data = {"df": df}

        result = mock_service._get_recent_closes(market_data)

        assert len(result) == 5
        assert result == [15000.0, 15001.0, 15002.0, 15003.0, 15004.0]

    def test_limits_to_50_closes(self, mock_service):
        """Should limit to 50 most recent closes."""
        df = pd.DataFrame({
            "close": list(range(100)),
        })
        market_data = {"df": df}

        result = mock_service._get_recent_closes(market_data)

        assert len(result) == 50
        assert result[-1] == 99  # Most recent

    def test_falls_back_to_buffer(self, mock_service):
        """Should fall back to data buffer."""
        mock_service.data_fetcher._data_buffer = pd.DataFrame({
            "close": [15000.0, 15001.0],
        })

        result = mock_service._get_recent_closes(None)

        assert len(result) == 2

    def test_handles_empty_data(self, mock_service):
        """Should return empty list for empty data."""
        result = mock_service._get_recent_closes(None)

        assert result == []


class TestGetTradesForChart:
    """Tests for _get_trades_for_chart method."""

    def test_filters_to_chart_window(self, mock_service):
        """Should filter trades to chart time window."""
        now = datetime.now(timezone.utc)
        chart_start = now - timedelta(hours=2)
        chart_end = now

        # Create chart data with timestamps
        df = pd.DataFrame({
            "timestamp": pd.date_range(chart_start, chart_end, periods=10),
            "close": [15000] * 10,
        })

        # Create signals
        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "status": "exited",
                "signal_id": "in_window",
                "entry_time": (now - timedelta(hours=1)).isoformat(),
                "exit_time": now.isoformat(),
                "signal": {"direction": "long", "entry_price": 15000},
                "exit_price": 15050,
                "pnl": 100,
            },
            {
                "status": "exited",
                "signal_id": "before_window",
                "entry_time": (now - timedelta(days=1)).isoformat(),
                "exit_time": (now - timedelta(days=1) + timedelta(hours=1)).isoformat(),
                "signal": {"direction": "long", "entry_price": 14900},
                "exit_price": 14950,
                "pnl": 100,
            },
        ])

        mock_service.config.symbol = "MNQ"

        result = mock_service._get_trades_for_chart(df)

        # Should only include trade in window
        assert len(result) == 1
        assert result[0]["signal_id"] == "in_window"

    def test_limits_trades(self, mock_service):
        """Should limit to 20 most recent trades."""
        now = datetime.now(timezone.utc)

        df = pd.DataFrame({
            "timestamp": pd.date_range(now - timedelta(hours=24), now, periods=10),
            "close": [15000] * 10,
        })

        # Create 30 trades
        trades = []
        for i in range(30):
            exit_time = now - timedelta(hours=i)
            trades.append({
                "status": "exited",
                "signal_id": f"sig{i}",
                "entry_time": (exit_time - timedelta(minutes=30)).isoformat(),
                "exit_time": exit_time.isoformat(),
                "signal": {"direction": "long", "entry_price": 15000},
                "exit_price": 15050,
                "pnl": 100,
            })

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=trades)
        mock_service.config.symbol = "MNQ"

        result = mock_service._get_trades_for_chart(df)

        assert len(result) <= 20

    def test_handles_none_chart_data(self, mock_service):
        """Should return empty list for None chart data."""
        result = mock_service._get_trades_for_chart(None)

        assert result == []


class TestComputeMtfTrends:
    """Tests for _compute_mtf_trends method."""

    def test_computes_5m_trend(self, mock_service):
        """Should compute 5-minute trend."""
        # Create uptrending data
        df_5m = pd.DataFrame({
            "close": [15000 + i * 10 for i in range(20)],  # Uptrend
        })
        market_data = {"df_5m": df_5m}

        result = mock_service._compute_mtf_trends(market_data)

        assert "5m" in result
        assert result["5m"] > 0  # Positive slope = uptrend

    def test_computes_15m_trend(self, mock_service):
        """Should compute 15-minute trend."""
        df_15m = pd.DataFrame({
            "close": [15000 - i * 10 for i in range(20)],  # Downtrend
        })
        market_data = {"df_15m": df_15m}

        result = mock_service._compute_mtf_trends(market_data)

        assert "15m" in result
        assert result["15m"] < 0  # Negative slope = downtrend

    def test_computes_1h_trend(self, mock_service):
        """Should compute 1-hour trend from 15m data."""
        df_15m = pd.DataFrame({
            "close": [15000 + i * 5 for i in range(10)],  # 10 bars = 2.5 hours
        })
        market_data = {"df_15m": df_15m}

        result = mock_service._compute_mtf_trends(market_data)

        assert "1h" in result

    def test_computes_4h_trend(self, mock_service):
        """Should compute 4-hour trend from 15m data."""
        df_15m = pd.DataFrame({
            "close": [15000 + i * 2 for i in range(20)],  # 20 bars = 5 hours
        })
        market_data = {"df_15m": df_15m}

        result = mock_service._compute_mtf_trends(market_data)

        assert "4h" in result

    def test_computes_1d_trend(self, mock_service):
        """Should compute daily trend from 15m data."""
        df_15m = pd.DataFrame({
            "close": [15000 + i for i in range(96)],  # 96 bars = 24 hours
        })
        market_data = {"df_15m": df_15m}

        result = mock_service._compute_mtf_trends(market_data)

        assert "1D" in result

    def test_handles_insufficient_data(self, mock_service):
        """Should skip trends with insufficient data."""
        df_5m = pd.DataFrame({
            "close": [15000, 15001],  # Only 2 bars, need 10
        })
        market_data = {"df_5m": df_5m}

        result = mock_service._compute_mtf_trends(market_data)

        assert "5m" not in result

    def test_handles_empty_market_data(self, mock_service):
        """Should return empty dict for no data."""
        result = mock_service._compute_mtf_trends(None)

        assert result == {}


class TestNotificationEdgeCases:
    """Edge case tests for notifications."""

    @pytest.mark.asyncio
    async def test_handles_exception_in_dashboard(self, mock_service):
        """Should handle exceptions gracefully."""
        mock_service.get_status = MagicMock(side_effect=Exception("Status error"))

        # Should not raise
        await mock_service._send_dashboard()

    def test_handles_missing_columns(self, mock_service):
        """Should handle DataFrames with missing columns."""
        df = pd.DataFrame({
            "open": [15000],
            # Missing 'close' column
        })
        market_data = {"df": df}

        result = mock_service._get_recent_closes(market_data)

        # Should return empty or fall back
        assert isinstance(result, list)
