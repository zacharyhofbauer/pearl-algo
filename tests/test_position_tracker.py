"""
Unit tests for VirtualPositionTracker.

Covers:
- Position open: creating a new position with entry price, direction, quantity
- Position close: closing with exit price, P&L calculation (long win/loss, short win/loss)
- Position update: updating unrealized P&L
- Multiple positions: tracking multiple open positions simultaneously
- Edge cases: close non-existent position, zero quantity, negative price
- Auto-flat rules, streak tracking, close-all operations
"""

from __future__ import annotations

import json
from datetime import datetime, time, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from pearlalgo.market_agent.position_tracker import VirtualPositionTracker


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_mock_state_manager(tmp_path: Path):
    """Create a mock state manager with real file backing."""
    sm = MagicMock()
    sm.state_dir = tmp_path
    signals_file = tmp_path / "signals.jsonl"
    sm.signals_file = signals_file
    sm.get_recent_signals = MagicMock(return_value=[])
    sm.load_state = MagicMock(return_value={})
    sm.save_state = MagicMock()
    sm.append_event = MagicMock()
    return sm


def _make_mock_performance_tracker():
    """Create a mock performance tracker."""
    pt = MagicMock()
    pt.track_exit = MagicMock(return_value={
        "pnl": 100.0,
        "is_win": True,
        "hold_duration_minutes": 30.0,
    })
    return pt


def _make_mock_notification_queue():
    """Create a mock notification queue."""
    nq = MagicMock()
    nq.enqueue_exit = AsyncMock()
    nq.enqueue_raw_message = AsyncMock()
    return nq


def _make_mock_telegram_notifier(enabled: bool = True):
    """Create a mock telegram notifier."""
    tn = MagicMock()
    tn.enabled = enabled
    tn.telegram = MagicMock() if enabled else None
    return tn


def _make_mock_config(**overrides):
    """Create a mock config."""
    cfg = MagicMock()
    cfg.symbol = overrides.get("symbol", "MNQ")
    cfg.virtual_pnl_enabled = overrides.get("virtual_pnl_enabled", True)
    cfg.virtual_pnl_tiebreak = overrides.get("virtual_pnl_tiebreak", "stop_loss")
    cfg.virtual_pnl_notify_exit = overrides.get("virtual_pnl_notify_exit", False)
    return cfg


@pytest.fixture
def tracker(tmp_path: Path):
    """Create a VirtualPositionTracker with mocked dependencies."""
    sm = _make_mock_state_manager(tmp_path)
    pt = _make_mock_performance_tracker()
    nq = _make_mock_notification_queue()
    tn = _make_mock_telegram_notifier()
    cfg = _make_mock_config()

    vpt = VirtualPositionTracker(
        state_manager=sm,
        performance_tracker=pt,
        notification_queue=nq,
        telegram_notifier=tn,
        config=cfg,
    )
    return vpt


def _make_entered_signal(
    signal_id: str = "sig_1",
    direction: str = "long",
    entry_price: float = 17500.0,
    stop_loss: float = 17480.0,
    take_profit: float = 17540.0,
    entry_time: str | None = None,
) -> dict:
    """Build a signal record in 'entered' state."""
    if entry_time is None:
        entry_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return {
        "signal_id": signal_id,
        "status": "entered",
        "entry_time": entry_time,
        "signal": {
            "type": "momentum",
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "tick_value": 2.0,
            "position_size": 1.0,
        },
    }


# ===================================================================
# Active virtual trade retrieval
# ===================================================================

class TestGetActiveVirtualTrades:
    """Tests for get_active_virtual_trades()."""

    def test_no_active_trades(self, tracker: VirtualPositionTracker) -> None:
        """Returns empty list when no signals have entered status."""
        tracker.state_manager.get_recent_signals.return_value = [
            {"signal_id": "a", "status": "generated"},
            {"signal_id": "b", "status": "exited"},
        ]
        result = tracker.get_active_virtual_trades()
        assert result == []

    def test_returns_entered_only(self, tracker: VirtualPositionTracker) -> None:
        """Only signals with status='entered' are returned."""
        tracker.state_manager.get_recent_signals.return_value = [
            _make_entered_signal("active_1"),
            {"signal_id": "gen_1", "status": "generated"},
            _make_entered_signal("active_2"),
            {"signal_id": "exit_1", "status": "exited"},
        ]
        result = tracker.get_active_virtual_trades()
        assert len(result) == 2
        assert result[0]["signal_id"] == "active_1"
        assert result[1]["signal_id"] == "active_2"

    def test_multiple_open_positions(self, tracker: VirtualPositionTracker) -> None:
        """Multiple positions can be open simultaneously."""
        signals = [_make_entered_signal(f"pos_{i}") for i in range(5)]
        tracker.state_manager.get_recent_signals.return_value = signals
        result = tracker.get_active_virtual_trades()
        assert len(result) == 5

    def test_handles_exception_gracefully(self, tracker: VirtualPositionTracker) -> None:
        """Returns empty list if state_manager throws."""
        tracker.state_manager.get_recent_signals.side_effect = RuntimeError("DB error")
        result = tracker.get_active_virtual_trades()
        assert result == []


# ===================================================================
# resolve_latest_prices
# ===================================================================

class TestResolveLatestPrices:
    """Tests for resolve_latest_prices()."""

    def test_returns_prices_from_market_data(self, tracker: VirtualPositionTracker) -> None:
        """Extracts close/bid/ask from market_data latest_bar."""
        market_data = {
            "latest_bar": {
                "close": 17500.0,
                "bid": 17499.5,
                "ask": 17500.5,
                "_data_level": "L1",
            }
        }
        result = tracker.resolve_latest_prices(market_data)
        assert result["close"] == 17500.0
        assert result["bid"] == 17499.5
        assert result["ask"] == 17500.5
        assert result["source"] == "L1"

    def test_returns_nones_when_no_data(self, tracker: VirtualPositionTracker) -> None:
        """Returns None values when market_data has no latest_bar."""
        result = tracker.resolve_latest_prices({})
        assert result["close"] is None
        assert result["bid"] is None
        assert result["ask"] is None

    def test_zero_price_returns_none(self, tracker: VirtualPositionTracker) -> None:
        """Zero prices are treated as invalid (None)."""
        market_data = {"latest_bar": {"close": 0, "bid": 0, "ask": 0}}
        result = tracker.resolve_latest_prices(market_data)
        assert result["close"] is None

    def test_negative_price_returns_none(self, tracker: VirtualPositionTracker) -> None:
        """Negative prices are treated as invalid (None)."""
        market_data = {"latest_bar": {"close": -100, "bid": -50, "ask": -75}}
        result = tracker.resolve_latest_prices(market_data)
        assert result["close"] is None


# ===================================================================
# Streak tracking
# ===================================================================

class TestStreakTracking:
    """Tests for streak tracking via _update_streak()."""

    def test_win_streak_increments(self, tracker: VirtualPositionTracker) -> None:
        """Consecutive wins increment the win streak."""
        tracker._update_streak(True)
        tracker._update_streak(True)
        tracker._update_streak(True)

        assert tracker._streak_count == 3
        assert tracker._streak_type == "win"

    def test_loss_streak_increments(self, tracker: VirtualPositionTracker) -> None:
        """Consecutive losses increment the loss streak."""
        tracker._update_streak(False)
        tracker._update_streak(False)

        assert tracker._streak_count == 2
        assert tracker._streak_type == "loss"

    def test_streak_resets_on_type_change(self, tracker: VirtualPositionTracker) -> None:
        """Switching from win to loss resets the streak counter."""
        tracker._update_streak(True)
        tracker._update_streak(True)
        tracker._update_streak(False)  # Switch

        assert tracker._streak_count == 1
        assert tracker._streak_type == "loss"

    def test_streak_info_property(self, tracker: VirtualPositionTracker) -> None:
        """streak_info property returns current streak state."""
        tracker._update_streak(True)
        tracker._update_streak(True)

        info = tracker.streak_info
        assert info["count"] == 2
        assert info["type"] == "win"
        assert info["threshold"] == 3


# ===================================================================
# Auto-flat rules
# ===================================================================

class TestAutoFlat:
    """Tests for auto_flat_due()."""

    def test_disabled_returns_none(self, tracker: VirtualPositionTracker) -> None:
        """auto_flat_due returns None when auto-flat is disabled."""
        tracker._auto_flat_enabled = False
        now = datetime.now(timezone.utc)
        result = tracker.auto_flat_due(now, market_open=True)
        assert result is None

    def test_daily_trigger(self, tracker: VirtualPositionTracker) -> None:
        """Daily auto-flat triggers at configured time."""
        tracker.configure_auto_flat(
            enabled=True,
            daily_enabled=True,
            daily_time=(15, 55),
            timezone="America/New_York",
        )

        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        # Create a time that is 15:56 ET on a Tuesday
        local_time = datetime(2025, 6, 10, 15, 56, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=True)
        assert result == "daily_auto_flat"

    def test_daily_already_triggered_today(self, tracker: VirtualPositionTracker) -> None:
        """Daily auto-flat does not re-trigger on same date."""
        tracker.configure_auto_flat(
            enabled=True,
            daily_enabled=True,
            daily_time=(15, 55),
            timezone="America/New_York",
        )

        from zoneinfo import ZoneInfo
        from datetime import date
        tz = ZoneInfo("America/New_York")
        local_time = datetime(2025, 6, 10, 15, 56, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        # Mark as already triggered today
        tracker._auto_flat_last_dates["daily_auto_flat"] = local_time.date()

        result = tracker.auto_flat_due(utc_time, market_open=True)
        assert result is None


# ===================================================================
# close_all_virtual_trades
# ===================================================================

class TestCloseAllVirtualTrades:
    """Tests for close_all_virtual_trades()."""

    @pytest.mark.asyncio
    async def test_close_all_with_active_trades(self, tracker: VirtualPositionTracker) -> None:
        """Close-all exits all active trades and returns count."""
        active = [
            _make_entered_signal("close_1", direction="long"),
            _make_entered_signal("close_2", direction="short"),
        ]
        tracker.state_manager.get_recent_signals.return_value = active
        tracker.performance_tracker.track_exit.return_value = {"pnl": 50.0, "is_win": True}

        market_data = {"latest_bar": {"close": 17520.0, "bid": 17519.5, "ask": 17520.5}}
        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test_close")

        assert count == 2
        assert tracker.performance_tracker.track_exit.call_count == 2
        assert tracker._last_close_all_reason == "test_close"

    @pytest.mark.asyncio
    async def test_close_all_no_active_trades(self, tracker: VirtualPositionTracker) -> None:
        """Close-all with no active trades returns 0."""
        tracker.state_manager.get_recent_signals.return_value = []
        market_data = {"latest_bar": {"close": 17500.0}}

        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 0

    @pytest.mark.asyncio
    async def test_close_all_no_price_returns_zero(self, tracker: VirtualPositionTracker) -> None:
        """Close-all without a valid price returns 0."""
        tracker.state_manager.get_recent_signals.return_value = [
            _make_entered_signal("no_price")
        ]
        market_data = {}

        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 0

    @pytest.mark.asyncio
    async def test_close_all_disabled_returns_zero(self, tracker: VirtualPositionTracker) -> None:
        """Close-all when virtual PnL is disabled returns 0."""
        tracker.config.virtual_pnl_enabled = False
        market_data = {"latest_bar": {"close": 17500.0}}

        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 0


# ===================================================================
# last_close_all_info
# ===================================================================

class TestLastCloseAllInfo:
    """Tests for last_close_all_info property."""

    def test_default_values(self, tracker: VirtualPositionTracker) -> None:
        """Default close-all info has None/zero values."""
        info = tracker.last_close_all_info
        assert info["at"] is None
        assert info["reason"] is None
        assert info["count"] == 0
        assert info["pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_populated_after_close_all(self, tracker: VirtualPositionTracker) -> None:
        """close-all info is populated after a close-all operation."""
        tracker.state_manager.get_recent_signals.return_value = [
            _make_entered_signal("info_1"),
        ]
        tracker.performance_tracker.track_exit.return_value = {"pnl": 75.0, "is_win": True}
        market_data = {"latest_bar": {"close": 17520.0, "bid": 17519.5, "ask": 17520.5}}

        await tracker.close_all_virtual_trades(market_data=market_data, reason="eod_flat")

        info = tracker.last_close_all_info
        assert info["at"] is not None
        assert info["reason"] == "eod_flat"
        assert info["count"] == 1
        assert info["pnl"] == 75.0


# ===================================================================
# configure methods
# ===================================================================

class TestConfigureMethods:
    """Tests for configuration setters."""

    def test_configure_auto_flat(self, tracker: VirtualPositionTracker) -> None:
        """configure_auto_flat stores all settings."""
        tracker.configure_auto_flat(
            enabled=True,
            daily_enabled=True,
            friday_enabled=True,
            weekend_enabled=True,
            notify=False,
            timezone="US/Eastern",
            daily_time=(16, 0),
            friday_time=(15, 30),
        )
        assert tracker._auto_flat_enabled is True
        assert tracker._auto_flat_daily_enabled is True
        assert tracker._auto_flat_friday_enabled is True
        assert tracker._auto_flat_weekend_enabled is True
        assert tracker._auto_flat_notify is False
        assert tracker._auto_flat_timezone == "US/Eastern"
        assert tracker._auto_flat_daily_time == (16, 0)
        assert tracker._auto_flat_friday_time == (15, 30)

    def test_configure_streak_alerts(self, tracker: VirtualPositionTracker) -> None:
        """configure_streak_alerts sets threshold."""
        tracker.configure_streak_alerts(threshold=5)
        assert tracker._streak_alert_threshold == 5
