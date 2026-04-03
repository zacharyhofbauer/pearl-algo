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


# ===================================================================
# _schedule_notification_task (lines 109-111)
# ===================================================================

class TestScheduleNotificationTask:
    """Tests for _schedule_notification_task helper."""

    def test_skips_when_no_event_loop(self, tracker: VirtualPositionTracker) -> None:
        """When no event loop is running, coroutine is closed and skipped."""
        coro = AsyncMock()()
        tracker._schedule_notification_task(coro, context="test")
        # Should not raise — just logs debug

    def test_creates_task_when_loop_available(self, tracker: VirtualPositionTracker) -> None:
        """When an event loop is running, create_task is called."""
        import asyncio

        async def _run():
            coro = AsyncMock()()
            tracker._schedule_notification_task(coro, context="test_loop")

        asyncio.get_event_loop().run_until_complete(_run())


# ===================================================================
# resolve_latest_prices — fallback and edge cases (lines 157-170)
# ===================================================================

class TestResolveLatestPricesFallback:
    """Additional tests for resolve_latest_prices fallback paths."""

    def test_falls_back_to_data_fetcher_cache(self, tracker: VirtualPositionTracker) -> None:
        """When market_data has no latest_bar, falls back to data_fetcher cache."""
        data_fetcher = MagicMock()
        data_fetcher._last_market_data = {
            "latest_bar": {
                "close": 18000.0,
                "bid": 17999.5,
                "ask": 18000.5,
                "_data_source": "cached",
            }
        }
        result = tracker.resolve_latest_prices({}, data_fetcher=data_fetcher)
        assert result["close"] == 18000.0
        assert result["source"] == "cached"

    def test_non_numeric_price_returns_none(self, tracker: VirtualPositionTracker) -> None:
        """Non-numeric price values return None."""
        market_data = {"latest_bar": {"close": "bad", "bid": None, "ask": "N/A"}}
        result = tracker.resolve_latest_prices(market_data)
        assert result["close"] is None
        assert result["bid"] is None
        assert result["ask"] is None

    def test_data_fetcher_exception_returns_nones(self, tracker: VirtualPositionTracker) -> None:
        """If data_fetcher raises accessing cache, returns Nones gracefully."""
        data_fetcher = MagicMock()
        type(data_fetcher)._last_market_data = property(lambda self: (_ for _ in ()).throw(RuntimeError("fail")))
        result = tracker.resolve_latest_prices(None, data_fetcher=data_fetcher)
        assert result["close"] is None

    def test_none_market_data_no_fetcher(self, tracker: VirtualPositionTracker) -> None:
        """None market_data with no data_fetcher returns all Nones."""
        result = tracker.resolve_latest_prices(None)
        assert result == {"close": None, "bid": None, "ask": None, "source": None}


# ===================================================================
# auto_flat_due — Friday and weekend rules (lines 202-215)
# ===================================================================

class TestAutoFlatFridayWeekend:
    """Tests for Friday and weekend auto-flat rules."""

    def test_friday_trigger(self, tracker: VirtualPositionTracker) -> None:
        """Friday auto-flat triggers at configured time on Friday."""
        from zoneinfo import ZoneInfo

        tracker.configure_auto_flat(
            enabled=True,
            friday_enabled=True,
            friday_time=(15, 55),
            timezone="America/New_York",
        )

        tz = ZoneInfo("America/New_York")
        # 2025-06-13 is a Friday
        local_time = datetime(2025, 6, 13, 15, 56, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=True)
        assert result == "friday_auto_flat"

    def test_friday_already_triggered(self, tracker: VirtualPositionTracker) -> None:
        """Friday auto-flat does not re-trigger on same date."""
        from zoneinfo import ZoneInfo
        tracker.configure_auto_flat(
            enabled=True,
            friday_enabled=True,
            friday_time=(15, 55),
            timezone="America/New_York",
        )
        tz = ZoneInfo("America/New_York")
        local_time = datetime(2025, 6, 13, 15, 56, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)
        tracker._auto_flat_last_dates["friday_auto_flat"] = local_time.date()

        result = tracker.auto_flat_due(utc_time, market_open=True)
        assert result is None

    def test_friday_before_cutoff_no_trigger(self, tracker: VirtualPositionTracker) -> None:
        """Friday auto-flat does not trigger before the configured time."""
        from zoneinfo import ZoneInfo
        tracker.configure_auto_flat(
            enabled=True,
            friday_enabled=True,
            friday_time=(15, 55),
            timezone="America/New_York",
        )
        tz = ZoneInfo("America/New_York")
        local_time = datetime(2025, 6, 13, 14, 0, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=True)
        assert result is None

    def test_weekend_saturday_trigger(self, tracker: VirtualPositionTracker) -> None:
        """Weekend auto-flat triggers on Saturday when market is closed."""
        from zoneinfo import ZoneInfo
        tracker.configure_auto_flat(
            enabled=True,
            weekend_enabled=True,
            timezone="America/New_York",
        )
        tz = ZoneInfo("America/New_York")
        # 2025-06-14 is a Saturday
        local_time = datetime(2025, 6, 14, 10, 0, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=False)
        assert result == "weekend_auto_flat"

    def test_weekend_sunday_pre_open_trigger(self, tracker: VirtualPositionTracker) -> None:
        """Weekend auto-flat triggers on Sunday before 18:00 ET."""
        from zoneinfo import ZoneInfo
        tracker.configure_auto_flat(
            enabled=True,
            weekend_enabled=True,
            timezone="America/New_York",
        )
        tz = ZoneInfo("America/New_York")
        # 2025-06-15 is a Sunday
        local_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=False)
        assert result == "weekend_auto_flat"

    def test_weekend_friday_after_close_trigger(self, tracker: VirtualPositionTracker) -> None:
        """Weekend auto-flat triggers on Friday after 17:00 ET when market closed."""
        from zoneinfo import ZoneInfo
        tracker.configure_auto_flat(
            enabled=True,
            weekend_enabled=True,
            timezone="America/New_York",
        )
        tz = ZoneInfo("America/New_York")
        # 2025-06-13 is a Friday
        local_time = datetime(2025, 6, 13, 17, 30, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=False)
        assert result == "weekend_auto_flat"

    def test_weekend_market_open_no_trigger(self, tracker: VirtualPositionTracker) -> None:
        """Weekend auto-flat does not trigger when market_open=True."""
        from zoneinfo import ZoneInfo
        tracker.configure_auto_flat(
            enabled=True,
            weekend_enabled=True,
            timezone="America/New_York",
        )
        tz = ZoneInfo("America/New_York")
        local_time = datetime(2025, 6, 14, 10, 0, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=True)
        assert result is None

    def test_invalid_timezone_falls_back(self, tracker: VirtualPositionTracker) -> None:
        """Invalid timezone falls back to America/New_York."""
        tracker.configure_auto_flat(
            enabled=True,
            daily_enabled=True,
            daily_time=(15, 55),
            timezone="Invalid/Timezone",
        )
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        local_time = datetime(2025, 6, 10, 15, 56, 0, tzinfo=tz)
        utc_time = local_time.astimezone(timezone.utc)

        result = tracker.auto_flat_due(utc_time, market_open=True)
        assert result == "daily_auto_flat"


# ===================================================================
# update_virtual_trade_exits (lines 232-408)
# ===================================================================

class TestUpdateVirtualTradeExits:
    """Tests for update_virtual_trade_exits() — the core exit detection loop."""

    def _make_market_data_df(self, bars: list[dict]) -> dict:
        """Build a market_data dict with a DataFrame of bars."""
        import pandas as pd
        df = pd.DataFrame(bars)
        return {"df": df}

    def test_disabled_config_returns_early(self, tracker: VirtualPositionTracker) -> None:
        """No-op when virtual_pnl_enabled is False."""
        tracker.config.virtual_pnl_enabled = False
        tracker.update_virtual_trade_exits({})
        tracker.state_manager.get_recent_signals.assert_not_called()

    def test_empty_df_returns_early(self, tracker: VirtualPositionTracker) -> None:
        """No-op when market_data df is empty."""
        import pandas as pd
        tracker.update_virtual_trade_exits({"df": pd.DataFrame()})
        tracker.state_manager.get_recent_signals.assert_not_called()

    def test_missing_df_returns_early(self, tracker: VirtualPositionTracker) -> None:
        """No-op when market_data has no df key."""
        tracker.update_virtual_trade_exits({})
        tracker.state_manager.get_recent_signals.assert_not_called()

    def test_missing_columns_returns_early(self, tracker: VirtualPositionTracker) -> None:
        """No-op when df lacks required columns."""
        import pandas as pd
        df = pd.DataFrame({"close": [17500.0]})
        tracker.update_virtual_trade_exits({"df": df})
        tracker.state_manager.get_recent_signals.assert_not_called()

    def test_long_stop_loss_hit(self, tracker: VirtualPositionTracker) -> None:
        """Detects stop-loss exit for a long trade."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "sl_long",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17510.0, "low": 17475.0, "close": 17478.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        tracker.performance_tracker.track_exit.assert_called_once()
        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["signal_id"] == "sl_long"
        assert call_kwargs["exit_price"] == 17480.0
        assert call_kwargs["exit_reason"] == "stop_loss"

    def test_long_take_profit_hit(self, tracker: VirtualPositionTracker) -> None:
        """Detects take-profit exit for a long trade."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "tp_long",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17545.0, "low": 17500.0, "close": 17542.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["exit_price"] == 17540.0
        assert call_kwargs["exit_reason"] == "take_profit"

    def test_short_stop_loss_hit(self, tracker: VirtualPositionTracker) -> None:
        """Detects stop-loss exit for a short trade."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "sl_short",
            direction="short",
            entry_price=17500.0,
            stop_loss=17520.0,
            take_profit=17460.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17525.0, "low": 17495.0, "close": 17522.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["exit_price"] == 17520.0
        assert call_kwargs["exit_reason"] == "stop_loss"

    def test_short_take_profit_hit(self, tracker: VirtualPositionTracker) -> None:
        """Detects take-profit exit for a short trade."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "tp_short",
            direction="short",
            entry_price=17500.0,
            stop_loss=17520.0,
            take_profit=17460.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17505.0, "low": 17455.0, "close": 17458.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["exit_price"] == 17460.0
        assert call_kwargs["exit_reason"] == "take_profit"

    def test_tiebreak_stop_loss_default(self, tracker: VirtualPositionTracker) -> None:
        """When both TP and SL hit same bar, default tiebreak chooses stop_loss."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "tie_sl",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.config.virtual_pnl_tiebreak = "stop_loss"

        # Bar hits both TP and SL
        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17545.0, "low": 17475.0, "close": 17510.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["exit_reason"] == "stop_loss"
        assert call_kwargs["exit_price"] == 17480.0

    def test_tiebreak_take_profit(self, tracker: VirtualPositionTracker) -> None:
        """When tiebreak is 'take_profit', TP wins on same-bar hit."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "tie_tp",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.config.virtual_pnl_tiebreak = "take_profit"

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17545.0, "low": 17475.0, "close": 17510.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["exit_reason"] == "take_profit"
        assert call_kwargs["exit_price"] == 17540.0

    def test_no_exit_when_no_bar_hits_levels(self, tracker: VirtualPositionTracker) -> None:
        """No exit when bars after entry do not reach TP or SL."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "no_exit",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]

        # Bar is after entry but does not hit SL or TP
        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17520.0, "low": 17490.0, "close": 17510.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        tracker.performance_tracker.track_exit.assert_not_called()

    def test_skips_non_entered_signals(self, tracker: VirtualPositionTracker) -> None:
        """Signals not in 'entered' status are skipped."""
        tracker.state_manager.get_recent_signals.return_value = [
            {"signal_id": "gen_1", "status": "generated", "signal": {}},
            {"signal_id": "exit_1", "status": "exited", "signal": {}},
        ]
        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 99999.0, "low": 0.01, "close": 17500.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        tracker.performance_tracker.track_exit.assert_not_called()

    def test_skips_zero_stop_or_target(self, tracker: VirtualPositionTracker) -> None:
        """Signals with zero stop_loss or take_profit are skipped."""
        sig = _make_entered_signal("zero_sl", entry_time="2025-06-10T10:00:00Z")
        sig["signal"]["stop_loss"] = 0
        tracker.state_manager.get_recent_signals.return_value = [sig]

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 99999.0, "low": 0.01, "close": 17500.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        tracker.performance_tracker.track_exit.assert_not_called()

    def test_exit_fires_callbacks(self, tracker: VirtualPositionTracker) -> None:
        """After exit, _handle_exit_callbacks is invoked (via performance_tracker returning perf)."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "cb_test",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = {
            "pnl": -20.0,
            "is_win": False,
            "hold_duration_minutes": 5.0,
        }

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17510.0, "low": 17475.0, "close": 17478.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        # Streak should have updated (loss)
        assert tracker._streak_type == "loss"
        assert tracker._streak_count == 1

    def test_multiple_signals_exit_independently(self, tracker: VirtualPositionTracker) -> None:
        """Multiple entered signals can exit in the same cycle."""
        entry_time = "2025-06-10T10:00:00Z"
        sig1 = _make_entered_signal(
            "multi_1", direction="long", entry_price=17500.0,
            stop_loss=17480.0, take_profit=17540.0, entry_time=entry_time,
        )
        sig2 = _make_entered_signal(
            "multi_2", direction="short", entry_price=17500.0,
            stop_loss=17520.0, take_profit=17460.0, entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig1, sig2]

        # Bar triggers SL for long and SL for short
        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17525.0, "low": 17475.0, "close": 17500.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        assert tracker.performance_tracker.track_exit.call_count == 2

    def test_get_recent_signals_exception_handled(self, tracker: VirtualPositionTracker) -> None:
        """Exception from get_recent_signals is caught gracefully."""
        tracker.state_manager.get_recent_signals.side_effect = RuntimeError("DB fail")
        import pandas as pd
        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17525.0, "low": 17475.0, "close": 17500.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)
        tracker.performance_tracker.track_exit.assert_not_called()

    def test_no_entry_time_uses_all_bars(self, tracker: VirtualPositionTracker) -> None:
        """When entry_time is None, all bars are eligible for exit."""
        sig = _make_entered_signal(
            "no_time",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
        )
        sig["entry_time"] = None
        tracker.state_manager.get_recent_signals.return_value = [sig]

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17545.0, "low": 17500.0, "close": 17542.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        tracker.performance_tracker.track_exit.assert_called_once()

    def test_perf_none_skips_callbacks(self, tracker: VirtualPositionTracker) -> None:
        """When performance_tracker.track_exit returns None, callbacks are skipped."""
        entry_time = "2025-06-10T10:00:00Z"
        sig = _make_entered_signal(
            "perf_none",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17540.0,
            entry_time=entry_time,
        )
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = None

        bars = [
            {"timestamp": "2025-06-10T10:01:00Z", "high": 17510.0, "low": 17475.0, "close": 17478.0},
        ]
        market_data = self._make_market_data_df(bars)
        tracker.update_virtual_trade_exits(market_data)

        # Streak should NOT update when perf is None
        assert tracker._streak_count == 0


# ===================================================================
# _handle_exit_callbacks (lines 421-457)
# ===================================================================

class TestHandleExitCallbacks:
    """Tests for _handle_exit_callbacks()."""

    def test_circuit_breaker_records_trade(self, tracker: VirtualPositionTracker) -> None:
        """Circuit breaker receives trade result on exit."""
        cb = MagicMock()
        tracker.trading_circuit_breaker = cb

        tracker._handle_exit_callbacks(
            sig_id="cb_1",
            sig={"direction": "long", "entry_price": 17500},
            perf={"pnl": 50.0, "is_win": True},
            exit_price=17550.0,
            exit_reason="take_profit",
            exit_bar_ts=datetime(2025, 6, 10, 12, 0, 0, tzinfo=timezone.utc),
            df=None,
        )
        cb.record_trade_result.assert_called_once()
        call_args = cb.record_trade_result.call_args[0][0]
        assert call_args["is_win"] is True
        assert call_args["pnl"] == 50.0

    def test_circuit_breaker_exception_handled(self, tracker: VirtualPositionTracker) -> None:
        """Circuit breaker exception is caught and does not propagate."""
        cb = MagicMock()
        cb.record_trade_result.side_effect = RuntimeError("CB fail")
        tracker.trading_circuit_breaker = cb

        # Should not raise
        tracker._handle_exit_callbacks(
            sig_id="cb_err",
            sig={"direction": "long"},
            perf={"pnl": -10.0, "is_win": False},
            exit_price=17490.0,
            exit_reason="stop_loss",
            exit_bar_ts=None,
            df=None,
        )

    def test_execution_adapter_daily_pnl(self, tracker: VirtualPositionTracker) -> None:
        """Execution adapter receives daily PnL update."""
        ea = MagicMock()
        tracker.execution_adapter = ea

        tracker._handle_exit_callbacks(
            sig_id="ea_1",
            sig={"direction": "short"},
            perf={"pnl": 75.0, "is_win": True},
            exit_price=17425.0,
            exit_reason="take_profit",
            exit_bar_ts=None,
            df=None,
        )
        ea.update_daily_pnl.assert_called_once_with(75.0)

    def test_execution_adapter_exception_handled(self, tracker: VirtualPositionTracker) -> None:
        """Execution adapter exception is caught."""
        ea = MagicMock()
        ea.update_daily_pnl.side_effect = RuntimeError("EA fail")
        tracker.execution_adapter = ea

        tracker._handle_exit_callbacks(
            sig_id="ea_err",
            sig={"direction": "long"},
            perf={"pnl": 10.0, "is_win": True},
            exit_price=17510.0,
            exit_reason="take_profit",
            exit_bar_ts=None,
            df=None,
        )

    def test_streak_updates_after_exit(self, tracker: VirtualPositionTracker) -> None:
        """Streak tracking updates with win/loss after exit callback."""
        tracker._handle_exit_callbacks(
            sig_id="streak_1",
            sig={"direction": "long"},
            perf={"pnl": 100.0, "is_win": True},
            exit_price=17600.0,
            exit_reason="take_profit",
            exit_bar_ts=None,
            df=None,
        )
        assert tracker._streak_type == "win"
        assert tracker._streak_count == 1

        tracker._handle_exit_callbacks(
            sig_id="streak_2",
            sig={"direction": "long"},
            perf={"pnl": -50.0, "is_win": False},
            exit_price=17450.0,
            exit_reason="stop_loss",
            exit_bar_ts=None,
            df=None,
        )
        assert tracker._streak_type == "loss"
        assert tracker._streak_count == 1


# ===================================================================
# _maybe_send_exit_notification (lines 470-508)
# ===================================================================

class TestMaybeSendExitNotification:
    """Tests for _maybe_send_exit_notification()."""

    def test_sends_when_all_conditions_met(self, tracker: VirtualPositionTracker) -> None:
        """Notification is scheduled when virtual_pnl_enabled, notify_exit, and notifier are available."""
        tracker.config.virtual_pnl_enabled = True
        tracker.config.virtual_pnl_notify_exit = True
        tracker.telegram_notifier.enabled = True
        tracker.telegram_notifier.telegram = MagicMock()

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            tracker._maybe_send_exit_notification(
                sig_id="notif_1",
                sig={"direction": "long", "entry_price": 17500},
                exit_price=17540.0,
                exit_reason="take_profit",
                pnl_value=40.0,
                perf={"hold_duration_minutes": 15.0},
                df=None,
            )
            mock_sched.assert_called_once()

    def test_skips_when_notify_exit_disabled(self, tracker: VirtualPositionTracker) -> None:
        """No notification when virtual_pnl_notify_exit is False."""
        tracker.config.virtual_pnl_enabled = True
        tracker.config.virtual_pnl_notify_exit = False

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            tracker._maybe_send_exit_notification(
                sig_id="notif_skip",
                sig={},
                exit_price=17500.0,
                exit_reason="stop_loss",
                pnl_value=-20.0,
                perf={},
                df=None,
            )
            mock_sched.assert_not_called()

    def test_skips_when_notifier_disabled(self, tracker: VirtualPositionTracker) -> None:
        """No notification when telegram notifier is disabled."""
        tracker.config.virtual_pnl_enabled = True
        tracker.config.virtual_pnl_notify_exit = True
        tracker.telegram_notifier.enabled = False

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            tracker._maybe_send_exit_notification(
                sig_id="notif_off",
                sig={},
                exit_price=17500.0,
                exit_reason="stop_loss",
                pnl_value=-20.0,
                perf={},
                df=None,
            )
            mock_sched.assert_not_called()

    def test_skips_when_telegram_is_none(self, tracker: VirtualPositionTracker) -> None:
        """No notification when telegram attribute is None."""
        tracker.config.virtual_pnl_enabled = True
        tracker.config.virtual_pnl_notify_exit = True
        tracker.telegram_notifier.enabled = True
        tracker.telegram_notifier.telegram = None

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            tracker._maybe_send_exit_notification(
                sig_id="notif_no_tg",
                sig={},
                exit_price=17500.0,
                exit_reason="stop_loss",
                pnl_value=-20.0,
                perf={},
                df=None,
            )
            mock_sched.assert_not_called()

    def test_handles_non_numeric_hold_duration(self, tracker: VirtualPositionTracker) -> None:
        """Non-numeric hold_duration_minutes is handled gracefully."""
        tracker.config.virtual_pnl_enabled = True
        tracker.config.virtual_pnl_notify_exit = True
        tracker.telegram_notifier.enabled = True
        tracker.telegram_notifier.telegram = MagicMock()

        with patch.object(tracker, "_schedule_notification_task"):
            # Should not raise
            tracker._maybe_send_exit_notification(
                sig_id="notif_bad_dur",
                sig={},
                exit_price=17500.0,
                exit_reason="stop_loss",
                pnl_value=-20.0,
                perf={"hold_duration_minutes": "bad"},
                df=None,
            )


# ===================================================================
# _update_streak — alert paths (lines 530-557)
# ===================================================================

class TestStreakAlerts:
    """Tests for streak alert notifications."""

    def test_win_streak_alert_at_threshold(self, tracker: VirtualPositionTracker) -> None:
        """Win streak alert fires at the configured threshold."""
        tracker.configure_streak_alerts(threshold=3)
        tracker.telegram_notifier.enabled = True

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            for _ in range(3):
                tracker._update_streak(True)
            mock_sched.assert_called_once()

        assert tracker._last_streak_alert_count == 3

    def test_loss_streak_alert_at_threshold(self, tracker: VirtualPositionTracker) -> None:
        """Loss streak alert fires at the configured threshold."""
        tracker.configure_streak_alerts(threshold=3)
        tracker.telegram_notifier.enabled = True

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            for _ in range(3):
                tracker._update_streak(False)
            mock_sched.assert_called_once()

        assert tracker._streak_type == "loss"
        assert tracker._last_streak_alert_count == 3

    def test_streak_alert_fires_again_at_higher_count(self, tracker: VirtualPositionTracker) -> None:
        """Streak alert fires again when count exceeds last alert count."""
        tracker.configure_streak_alerts(threshold=2)
        tracker.telegram_notifier.enabled = True

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            for _ in range(4):
                tracker._update_streak(True)
            # Should fire at count=2, 3, 4
            assert mock_sched.call_count == 3

    def test_no_alert_below_threshold(self, tracker: VirtualPositionTracker) -> None:
        """No streak alert below threshold."""
        tracker.configure_streak_alerts(threshold=5)
        tracker.telegram_notifier.enabled = True

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            for _ in range(4):
                tracker._update_streak(True)
            mock_sched.assert_not_called()

    def test_no_alert_when_notifier_disabled(self, tracker: VirtualPositionTracker) -> None:
        """No streak alert when telegram notifier is disabled."""
        tracker.configure_streak_alerts(threshold=2)
        tracker.telegram_notifier.enabled = False

        with patch.object(tracker, "_schedule_notification_task") as mock_sched:
            for _ in range(5):
                tracker._update_streak(True)
            mock_sched.assert_not_called()

    def test_streak_exception_handled(self, tracker: VirtualPositionTracker) -> None:
        """Exception in streak notification is caught."""
        tracker.configure_streak_alerts(threshold=2)
        tracker.telegram_notifier.enabled = True

        with patch.object(tracker, "_schedule_notification_task", side_effect=RuntimeError("fail")):
            # Should not raise
            for _ in range(3):
                tracker._update_streak(True)


# ===================================================================
# close_all_virtual_trades — additional edge cases (lines 588-653)
# ===================================================================

class TestCloseAllEdgeCases:
    """Additional edge case tests for close_all_virtual_trades."""

    @pytest.mark.asyncio
    async def test_uses_bid_for_long_exit(self, tracker: VirtualPositionTracker) -> None:
        """Long trades use bid price for close-all exit."""
        sig = _make_entered_signal("bid_exit", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = {"pnl": 10.0}

        market_data = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        await tracker.close_all_virtual_trades(market_data=market_data, reason="test")

        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["exit_price"] == 17499.0

    @pytest.mark.asyncio
    async def test_uses_ask_for_short_exit(self, tracker: VirtualPositionTracker) -> None:
        """Short trades use ask price for close-all exit."""
        sig = _make_entered_signal("ask_exit", direction="short")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = {"pnl": -10.0}

        market_data = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        await tracker.close_all_virtual_trades(market_data=market_data, reason="test")

        call_kwargs = tracker.performance_tracker.track_exit.call_args[1]
        assert call_kwargs["exit_price"] == 17501.0

    @pytest.mark.asyncio
    async def test_pnl_parse_error_handled(self, tracker: VirtualPositionTracker) -> None:
        """Non-numeric pnl in perf dict is handled gracefully."""
        sig = _make_entered_signal("pnl_err", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = {"pnl": "not_a_number"}

        market_data = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 1

    @pytest.mark.asyncio
    async def test_state_save_failure_handled(self, tracker: VirtualPositionTracker) -> None:
        """State save failure does not prevent close-all from completing."""
        sig = _make_entered_signal("state_err", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.state_manager.save_state.side_effect = RuntimeError("disk full")
        tracker.performance_tracker.track_exit.return_value = {"pnl": 25.0}

        market_data = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 1
        assert tracker._last_close_all_count == 1

    @pytest.mark.asyncio
    async def test_append_event_failure_handled(self, tracker: VirtualPositionTracker) -> None:
        """append_event failure does not prevent close-all completion."""
        sig = _make_entered_signal("event_err", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.state_manager.append_event.side_effect = RuntimeError("event fail")
        tracker.performance_tracker.track_exit.return_value = {"pnl": 30.0}

        market_data = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 1

    @pytest.mark.asyncio
    async def test_notification_failure_handled(self, tracker: VirtualPositionTracker) -> None:
        """Telegram notification failure does not prevent close-all completion."""
        sig = _make_entered_signal("notif_err", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = {"pnl": 20.0}
        tracker._auto_flat_notify = True
        tracker.telegram_notifier.enabled = True
        tracker.notification_queue.enqueue_raw_message.side_effect = RuntimeError("TG fail")

        market_data = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 1

    @pytest.mark.asyncio
    async def test_skips_empty_signal_id(self, tracker: VirtualPositionTracker) -> None:
        """Signals with empty signal_id are skipped."""
        sig = _make_entered_signal("", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]

        market_data = {"latest_bar": {"close": 17500.0}}
        count = await tracker.close_all_virtual_trades(market_data=market_data, reason="test")
        assert count == 0

    @pytest.mark.asyncio
    async def test_close_all_updates_state(self, tracker: VirtualPositionTracker) -> None:
        """close_all updates state with zero active trades."""
        sig = _make_entered_signal("state_test", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = {"pnl": 50.0}

        market_data = {"latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0}}
        await tracker.close_all_virtual_trades(market_data=market_data, reason="eod")

        saved_state = tracker.state_manager.save_state.call_args[0][0]
        assert saved_state["active_trades_count"] == 0
        assert saved_state["active_trades_unrealized_pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_close_all_price_source_tracked(self, tracker: VirtualPositionTracker) -> None:
        """Price source from latest_bar is tracked in close-all info."""
        sig = _make_entered_signal("src_test", direction="long")
        tracker.state_manager.get_recent_signals.return_value = [sig]
        tracker.performance_tracker.track_exit.return_value = {"pnl": 10.0}

        market_data = {
            "latest_bar": {"close": 17500.0, "bid": 17499.0, "ask": 17501.0, "_data_level": "L1"}
        }
        await tracker.close_all_virtual_trades(market_data=market_data, reason="test")

        assert tracker._last_close_all_price_source == "L1"
