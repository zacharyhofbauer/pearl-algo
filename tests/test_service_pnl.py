"""
Tests for Service P&L and Virtual Trade Exit Methods.

Tests the ServicePnLMixin class which provides virtual trade exit handling,
P&L tracking, and related functionality for the MarketAgentService.
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
        yield state_dir


@pytest.fixture
def mock_service(temp_state_dir):
    """Create a mock MarketAgentService with the mixin."""
    from pearlalgo.market_agent.service_pnl import ServicePnLMixin

    class MockStateManager:
        def __init__(self, state_dir):
            self.state_dir = state_dir

        def get_recent_signals(self, limit=100):
            return []

    class MockConfig:
        symbol = "MNQ"
        virtual_pnl_enabled = True
        virtual_pnl_tiebreak = "stop_loss"
        virtual_pnl_notify_exit = True

    class MockPerformanceTracker:
        def track_exit(self, signal_id, exit_price, exit_reason, exit_time):
            return {
                "pnl": 100.0,
                "is_win": True,
                "hold_duration_minutes": 30,
            }

    class MockNotificationQueue:
        async def enqueue_exit(self, **kwargs):
            self.last_exit = kwargs

        async def enqueue_raw_message(self, msg, **kwargs):
            self.last_message = msg

    class MockTelegramNotifier:
        enabled = True
        telegram = MagicMock()

    class TestService(ServicePnLMixin):
        def __init__(self, state_dir):
            self.state_manager = MockStateManager(state_dir)
            self.config = MockConfig()
            self.performance_tracker = MockPerformanceTracker()
            self.notification_queue = MockNotificationQueue()
            self.telegram_notifier = MockTelegramNotifier()
            self.trading_circuit_breaker = None
            self._challenge_tracker = None
            self.bandit_policy = None
            self.contextual_policy = None
            self.execution_adapter = None
            self._streak_type = None
            self._streak_count = 0
            self._last_streak_alert_count = 0
            self._streak_alert_threshold = 3

    return TestService(temp_state_dir)


def create_market_data_with_bars(bars: list[dict]) -> dict:
    """Helper to create market data with OHLCV bars."""
    df = pd.DataFrame(bars)
    return {"df": df}


class TestUpdateVirtualTradeExits:
    """Tests for _update_virtual_trade_exits method."""

    def test_exits_long_on_stop_loss(self, mock_service):
        """Should exit long trade when stop loss is hit."""
        now = datetime.now(timezone.utc)
        entry_time = (now - timedelta(hours=1)).isoformat()

        # Signal with long position
        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": entry_time,
                "signal": {
                    "direction": "long",
                    "entry_price": 15000.00,
                    "stop_loss": 14990.00,
                    "take_profit": 15050.00,
                },
            },
        ])

        # Bar that hits stop loss (low touches 14990)
        market_data = create_market_data_with_bars([
            {
                "timestamp": now.isoformat(),
                "high": 15010.00,
                "low": 14985.00,  # Below stop
                "close": 14995.00,
            },
        ])

        mock_service.performance_tracker.track_exit = MagicMock(return_value={
            "pnl": -20.0,
            "is_win": False,
        })

        mock_service._update_virtual_trade_exits(market_data)

        mock_service.performance_tracker.track_exit.assert_called_once()
        call_args = mock_service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "stop_loss"

    def test_exits_long_on_take_profit(self, mock_service):
        """Should exit long trade when take profit is hit."""
        now = datetime.now(timezone.utc)
        entry_time = (now - timedelta(hours=1)).isoformat()

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": entry_time,
                "signal": {
                    "direction": "long",
                    "entry_price": 15000.00,
                    "stop_loss": 14990.00,
                    "take_profit": 15050.00,
                },
            },
        ])

        # Bar that hits take profit (high touches 15050)
        market_data = create_market_data_with_bars([
            {
                "timestamp": now.isoformat(),
                "high": 15055.00,  # Above target
                "low": 15010.00,
                "close": 15040.00,
            },
        ])

        mock_service.performance_tracker.track_exit = MagicMock(return_value={
            "pnl": 100.0,
            "is_win": True,
        })

        mock_service._update_virtual_trade_exits(market_data)

        mock_service.performance_tracker.track_exit.assert_called_once()
        call_args = mock_service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "take_profit"

    def test_exits_short_on_stop_loss(self, mock_service):
        """Should exit short trade when stop loss is hit."""
        now = datetime.now(timezone.utc)
        entry_time = (now - timedelta(hours=1)).isoformat()

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": entry_time,
                "signal": {
                    "direction": "short",
                    "entry_price": 15000.00,
                    "stop_loss": 15010.00,  # Stop is above for shorts
                    "take_profit": 14950.00,  # Target is below for shorts
                },
            },
        ])

        # Bar that hits stop loss (high touches 15010)
        market_data = create_market_data_with_bars([
            {
                "timestamp": now.isoformat(),
                "high": 15015.00,  # Above stop
                "low": 14990.00,
                "close": 15005.00,
            },
        ])

        mock_service.performance_tracker.track_exit = MagicMock(return_value={
            "pnl": -20.0,
            "is_win": False,
        })

        mock_service._update_virtual_trade_exits(market_data)

        mock_service.performance_tracker.track_exit.assert_called_once()
        call_args = mock_service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "stop_loss"

    def test_exits_short_on_take_profit(self, mock_service):
        """Should exit short trade when take profit is hit."""
        now = datetime.now(timezone.utc)
        entry_time = (now - timedelta(hours=1)).isoformat()

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": entry_time,
                "signal": {
                    "direction": "short",
                    "entry_price": 15000.00,
                    "stop_loss": 15010.00,
                    "take_profit": 14950.00,
                },
            },
        ])

        # Bar that hits take profit (low touches 14950)
        market_data = create_market_data_with_bars([
            {
                "timestamp": now.isoformat(),
                "high": 14990.00,
                "low": 14945.00,  # Below target
                "close": 14960.00,
            },
        ])

        mock_service.performance_tracker.track_exit = MagicMock(return_value={
            "pnl": 100.0,
            "is_win": True,
        })

        mock_service._update_virtual_trade_exits(market_data)

        mock_service.performance_tracker.track_exit.assert_called_once()
        call_args = mock_service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "take_profit"

    def test_tiebreak_stop_loss_default(self, mock_service):
        """Should use stop loss on tie when tiebreak is stop_loss."""
        now = datetime.now(timezone.utc)
        entry_time = (now - timedelta(hours=1)).isoformat()

        mock_service.config.virtual_pnl_tiebreak = "stop_loss"

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": entry_time,
                "signal": {
                    "direction": "long",
                    "entry_price": 15000.00,
                    "stop_loss": 14990.00,
                    "take_profit": 15050.00,
                },
            },
        ])

        # Bar hits both TP and SL
        market_data = create_market_data_with_bars([
            {
                "timestamp": now.isoformat(),
                "high": 15060.00,  # Above TP
                "low": 14980.00,  # Below SL
                "close": 15000.00,
            },
        ])

        mock_service.performance_tracker.track_exit = MagicMock(return_value={
            "pnl": -20.0,
            "is_win": False,
        })

        mock_service._update_virtual_trade_exits(market_data)

        call_args = mock_service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "stop_loss"

    def test_tiebreak_take_profit(self, mock_service):
        """Should use take profit on tie when tiebreak is take_profit."""
        now = datetime.now(timezone.utc)
        entry_time = (now - timedelta(hours=1)).isoformat()

        mock_service.config.virtual_pnl_tiebreak = "take_profit"

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": entry_time,
                "signal": {
                    "direction": "long",
                    "entry_price": 15000.00,
                    "stop_loss": 14990.00,
                    "take_profit": 15050.00,
                },
            },
        ])

        # Bar hits both TP and SL
        market_data = create_market_data_with_bars([
            {
                "timestamp": now.isoformat(),
                "high": 15060.00,
                "low": 14980.00,
                "close": 15000.00,
            },
        ])

        mock_service.performance_tracker.track_exit = MagicMock(return_value={
            "pnl": 100.0,
            "is_win": True,
        })

        mock_service._update_virtual_trade_exits(market_data)

        call_args = mock_service.performance_tracker.track_exit.call_args
        assert call_args[1]["exit_reason"] == "take_profit"

    def test_only_exits_after_entry_time(self, mock_service):
        """Should only consider bars after entry time."""
        now = datetime.now(timezone.utc)
        entry_time = now.isoformat()  # Entry is now

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": entry_time,
                "signal": {
                    "direction": "long",
                    "entry_price": 15000.00,
                    "stop_loss": 14990.00,
                    "take_profit": 15050.00,
                },
            },
        ])

        # Bar is BEFORE entry time
        bar_time = (now - timedelta(hours=1)).isoformat()
        market_data = create_market_data_with_bars([
            {
                "timestamp": bar_time,
                "high": 15060.00,  # Would hit TP
                "low": 14980.00,  # Would hit SL
                "close": 15000.00,
            },
        ])

        mock_service.performance_tracker.track_exit = MagicMock()

        mock_service._update_virtual_trade_exits(market_data)

        # Should not exit because bar is before entry
        mock_service.performance_tracker.track_exit.assert_not_called()

    def test_skips_when_disabled(self, mock_service):
        """Should skip processing when virtual PnL is disabled."""
        mock_service.config.virtual_pnl_enabled = False
        mock_service.performance_tracker.track_exit = MagicMock()

        mock_service._update_virtual_trade_exits({})

        mock_service.performance_tracker.track_exit.assert_not_called()

    def test_skips_already_exited(self, mock_service):
        """Should skip signals that are not in 'entered' status."""
        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "exited",  # Already exited
                "signal": {},
            },
        ])

        market_data = create_market_data_with_bars([
            {"timestamp": datetime.now(timezone.utc).isoformat(), "high": 15100, "low": 14900},
        ])

        mock_service.performance_tracker.track_exit = MagicMock()

        mock_service._update_virtual_trade_exits(market_data)

        mock_service.performance_tracker.track_exit.assert_not_called()


class TestProcessExitResult:
    """Tests for _process_exit_result method."""

    def test_logs_exit(self, mock_service):
        """Should log the exit."""
        perf = {"pnl": 100.0, "is_win": True}
        sig = {"type": "breakout"}

        # Just verify it doesn't raise
        mock_service._process_exit_result(
            perf=perf,
            sig=sig,
            sig_id="test_sig",
            exit_price=15050.00,
            exit_reason="take_profit",
            exit_bar_ts=datetime.now(timezone.utc),
            df=pd.DataFrame(),
        )


class TestRecordCircuitBreakerTrade:
    """Tests for _record_circuit_breaker_trade method."""

    def test_records_with_circuit_breaker(self, mock_service):
        """Should record trade with circuit breaker."""
        mock_cb = MagicMock()
        mock_service.trading_circuit_breaker = mock_cb

        mock_service._record_circuit_breaker_trade(
            is_win=True,
            pnl_value=100.0,
            exit_bar_ts=datetime.now(timezone.utc),
            exit_reason="take_profit",
        )

        mock_cb.record_trade_result.assert_called_once()

    def test_skips_when_no_circuit_breaker(self, mock_service):
        """Should skip when no circuit breaker."""
        mock_service.trading_circuit_breaker = None

        # Should not raise
        mock_service._record_circuit_breaker_trade(
            is_win=True,
            pnl_value=100.0,
            exit_bar_ts=None,
            exit_reason="take_profit",
        )


class TestRecordChallengeTrade:
    """Tests for _record_challenge_trade method."""

    def test_records_with_challenge_tracker(self, mock_service):
        """Should record trade with challenge tracker."""
        mock_tracker = MagicMock()
        mock_tracker.record_trade.return_value = {"triggered": False}
        mock_service._challenge_tracker = mock_tracker

        mock_service._record_challenge_trade(pnl_value=100.0, is_win=True)

        mock_tracker.record_trade.assert_called_once_with(pnl=100.0, is_win=True)

    def test_handles_challenge_trigger(self, mock_service):
        """Should handle challenge pass/fail triggers."""
        mock_tracker = MagicMock()
        mock_tracker.record_trade.return_value = {
            "triggered": True,
            "outcome": "pass",
            "attempt": {"attempt_id": 1, "pnl": 3500.0, "trades": 50, "win_rate": 60},
        }
        mock_service._challenge_tracker = mock_tracker

        mock_service._record_challenge_trade(pnl_value=100.0, is_win=True)

        # Should have queued a notification
        # (actual implementation creates asyncio task)


class TestRecordBanditOutcome:
    """Tests for _record_bandit_outcome method."""

    def test_records_with_bandit_policy(self, mock_service):
        """Should record outcome with bandit policy."""
        mock_policy = MagicMock()
        mock_service.bandit_policy = mock_policy

        mock_service._record_bandit_outcome(
            sig_id="test_sig",
            sig={"type": "momentum"},
            is_win=True,
            pnl_value=100.0,
        )

        mock_policy.record_outcome.assert_called_once()

    def test_skips_when_no_policy(self, mock_service):
        """Should skip when no bandit policy."""
        mock_service.bandit_policy = None

        # Should not raise
        mock_service._record_bandit_outcome(
            sig_id="test_sig",
            sig={},
            is_win=True,
            pnl_value=100.0,
        )


class TestRecordContextualOutcome:
    """Tests for _record_contextual_outcome method."""

    def test_records_with_contextual_policy(self, mock_service):
        """Should record outcome with contextual policy."""
        with patch('pearlalgo.learning.contextual_bandit.ContextFeatures') as MockFeatures:
            mock_ctx = MagicMock()
            mock_ctx.to_dict.return_value = {"context_key": "test"}
            MockFeatures.from_dict.return_value = mock_ctx

            mock_policy = MagicMock()
            mock_policy.get_expected_win_rate.return_value = 0.6
            mock_service.contextual_policy = mock_policy

            mock_service._record_contextual_outcome(
                sig_id="test_sig",
                sig={
                    "type": "breakout",
                    "_context_features": {"volatility": "high"},
                },
                is_win=True,
                pnl_value=100.0,
            )

            mock_policy.record_outcome.assert_called_once()


class TestUpdateExecutionPnl:
    """Tests for _update_execution_pnl method."""

    def test_updates_execution_adapter(self, mock_service):
        """Should update execution adapter's daily PnL."""
        mock_adapter = MagicMock()
        mock_service.execution_adapter = mock_adapter

        mock_service._update_execution_pnl(150.0)

        mock_adapter.update_daily_pnl.assert_called_once_with(150.0)

    def test_skips_when_no_adapter(self, mock_service):
        """Should skip when no execution adapter."""
        mock_service.execution_adapter = None

        # Should not raise
        mock_service._update_execution_pnl(150.0)


class TestSendExitNotification:
    """Tests for _send_exit_notification method."""

    def test_sends_when_enabled(self, mock_service):
        """Should send notification when enabled."""
        mock_service.config.virtual_pnl_enabled = True
        mock_service.config.virtual_pnl_notify_exit = True

        mock_service._send_exit_notification(
            sig_id="test_sig",
            sig={"type": "breakout"},
            exit_price=15050.0,
            exit_reason="take_profit",
            pnl_value=100.0,
            perf={"hold_duration_minutes": 30},
            df=pd.DataFrame(),
        )

        # Notification should be queued (via asyncio.create_task)

    def test_skips_when_disabled(self, mock_service):
        """Should skip when notifications disabled."""
        mock_service.config.virtual_pnl_notify_exit = False

        # Should not raise and not send
        mock_service._send_exit_notification(
            sig_id="test_sig",
            sig={},
            exit_price=15050.0,
            exit_reason="take_profit",
            pnl_value=100.0,
            perf={},
            df=pd.DataFrame(),
        )


class TestTrackStreak:
    """Tests for _track_streak method."""

    def test_starts_win_streak(self, mock_service):
        """Should start a win streak."""
        mock_service._track_streak(is_win=True)

        assert mock_service._streak_type == "win"
        assert mock_service._streak_count == 1

    def test_continues_win_streak(self, mock_service):
        """Should continue a win streak."""
        mock_service._streak_type = "win"
        mock_service._streak_count = 2

        mock_service._track_streak(is_win=True)

        assert mock_service._streak_count == 3

    def test_breaks_win_streak_on_loss(self, mock_service):
        """Should break win streak on loss."""
        mock_service._streak_type = "win"
        mock_service._streak_count = 5

        mock_service._track_streak(is_win=False)

        assert mock_service._streak_type == "loss"
        assert mock_service._streak_count == 1

    def test_starts_loss_streak(self, mock_service):
        """Should start a loss streak."""
        mock_service._track_streak(is_win=False)

        assert mock_service._streak_type == "loss"
        assert mock_service._streak_count == 1

    def test_sends_alert_at_threshold(self, mock_service):
        """Should send alert when streak reaches threshold."""
        mock_service._streak_type = "win"
        mock_service._streak_count = 2
        mock_service._streak_alert_threshold = 3

        mock_service._track_streak(is_win=True)

        # Should have queued an alert (streak now = 3)
        assert mock_service._streak_count == 3
        assert mock_service._last_streak_alert_count == 3


class TestPnLEdgeCases:
    """Edge case tests for P&L handling."""

    def test_handles_missing_stop_loss(self, mock_service):
        """Should skip signals without stop loss."""
        now = datetime.now(timezone.utc)

        mock_service.state_manager.get_recent_signals = MagicMock(return_value=[
            {
                "signal_id": "sig1",
                "status": "entered",
                "entry_time": (now - timedelta(hours=1)).isoformat(),
                "signal": {
                    "direction": "long",
                    "entry_price": 15000.00,
                    # No stop_loss
                    "take_profit": 15050.00,
                },
            },
        ])

        market_data = create_market_data_with_bars([
            {"timestamp": now.isoformat(), "high": 15100, "low": 14900},
        ])

        mock_service.performance_tracker.track_exit = MagicMock()

        mock_service._update_virtual_trade_exits(market_data)

        # Should not exit without valid SL/TP
        mock_service.performance_tracker.track_exit.assert_not_called()

    def test_handles_empty_dataframe(self, mock_service):
        """Should handle empty market data."""
        mock_service._update_virtual_trade_exits({"df": pd.DataFrame()})

        # Should not raise

    def test_handles_none_market_data(self, mock_service):
        """Should handle None market data."""
        mock_service._update_virtual_trade_exits(None)

        # Should not raise

    def test_handles_missing_required_columns(self, mock_service):
        """Should handle DataFrame without required columns."""
        df = pd.DataFrame({
            "close": [15000.0],
            # Missing timestamp, high, low
        })

        mock_service._update_virtual_trade_exits({"df": df})

        # Should not raise
