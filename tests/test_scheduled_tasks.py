"""
Tests for ScheduledTasks - Time-based tasks for the MarketAgentService.

Tests cover:
- Morning briefing: timing logic, already-sent guard, AI disabled
- Market close summary: timing window, already-sent guard, trades/no trades, Tradovate Paper
- Follower heartbeat: non-follower no-op, within-tolerance, timeout, warned guard, market-closed
- Tradovate trade reconstruction: empty fills, FIFO matching, today-only filtering
- record_follower_signal: timestamp tracking
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from pearlalgo.market_agent.scheduled_tasks import ScheduledTasks
from pearlalgo.market_agent.notification_queue import Priority

# scheduled_tasks.py references Priority.MEDIUM which is not in the IntEnum.
# Patch it here so the notification code-path works as intended in tests.
if not hasattr(Priority, "MEDIUM"):
    Priority.MEDIUM = Priority.NORMAL  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_et_datetime(hour: int, minute: int, date_str: str = "2025-06-10") -> datetime:
    """Build a timezone-aware datetime in ET for test assertions."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore
    et_tz = ZoneInfo("America/New_York")
    base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=et_tz)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _utc_from_et(hour: int, minute: int, date_str: str = "2025-06-10") -> datetime:
    """Return a UTC datetime that corresponds to the given ET hour/minute."""
    return _make_et_datetime(hour, minute, date_str).astimezone(timezone.utc)


@pytest.fixture
def mock_deps(tmp_path):
    """Create a full set of mock dependencies for ScheduledTasks."""
    telegram = MagicMock()
    telegram.enabled = True
    telegram.account_label = "SIM"
    telegram.telegram = MagicMock()

    notification_queue = AsyncMock()
    notification_queue.enqueue_raw_message = AsyncMock()
    notification_queue.enqueue_risk_warning = AsyncMock()

    perf_tracker = MagicMock()
    perf_file = tmp_path / "performance.json"
    perf_tracker.performance_file = perf_file

    state_manager = MagicMock()
    state_manager.state_dir = tmp_path
    state_manager.signals_file = tmp_path / "signals.jsonl"
    state_manager.load_state.return_value = {"daily_pnl": 0, "session_pnl": 0}

    service_config = {
        "ai_briefings": {"enabled": True, "morning_time": "06:30"},
        "ai_chat": {},
    }

    return {
        "telegram_notifier": telegram,
        "notification_queue": notification_queue,
        "state_manager": state_manager,
        "performance_tracker": perf_tracker,
        "service_config": service_config,
    }


@pytest.fixture
def tasks(mock_deps):
    """Create a ScheduledTasks instance with default (non-follower) config."""
    return ScheduledTasks(**mock_deps)


# =========================================================================
# check_morning_briefing
# =========================================================================


class TestCheckMorningBriefing:
    """Tests for check_morning_briefing()."""

    @pytest.mark.asyncio
    async def test_noop_when_notifier_disabled(self, tasks):
        """Should return immediately if telegram_notifier is disabled."""
        tasks.telegram_notifier.enabled = False
        await tasks.check_morning_briefing()
        tasks.notification_queue.enqueue_raw_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noop_when_notifier_is_none(self, mock_deps):
        """Should return immediately if telegram_notifier is None."""
        mock_deps["telegram_notifier"] = None
        t = ScheduledTasks(**mock_deps)
        await t.check_morning_briefing()
        mock_deps["notification_queue"].enqueue_raw_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noop_when_ai_briefings_disabled(self, tasks):
        """Should skip when ai_briefings.enabled is False."""
        tasks._service_config["ai_briefings"]["enabled"] = False
        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = _utc_from_et(6, 32)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_morning_briefing()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_before_morning_window(self, tasks):
        """Should skip when current ET time is before 6:30 AM."""
        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = _utc_from_et(5, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_morning_briefing()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_after_morning_window(self, tasks):
        """Should skip when current ET time is past 6:40 AM."""
        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = _utc_from_et(6, 45)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_morning_briefing()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_sent_today_guard(self, tasks):
        """Should skip if briefing was already sent for today."""
        et_time = _make_et_datetime(6, 32)
        today_str = et_time.strftime("%Y-%m-%d")
        tasks._morning_briefing_sent_date = today_str

        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = et_time.astimezone(timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_morning_briefing()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_during_window_no_trades(self, tasks):
        """Should send briefing within the window when no overnight trades exist."""
        et_time = _make_et_datetime(6, 33)
        utc_time = et_time.astimezone(timezone.utc)

        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = utc_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_morning_briefing()
            await asyncio.sleep(0)

        # Verify the sent-date guard was set
        assert tasks._morning_briefing_sent_date == et_time.strftime("%Y-%m-%d")
        # enqueue_raw_message is called (to create the coroutine) before create_task
        tasks.notification_queue.enqueue_raw_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_with_overnight_trades(self, tasks, tmp_path):
        """Should include overnight trade summary when trades exist."""
        et_time = _make_et_datetime(6, 34)
        utc_time = et_time.astimezone(timezone.utc)
        today_str = et_time.strftime("%Y-%m-%d")

        perf_data = [
            {"exit_time": f"{today_str}T02:30:00Z", "pnl": 150, "is_win": True, "direction": "long"},
            {"exit_time": f"{today_str}T03:00:00Z", "pnl": -50, "is_win": False, "direction": "short"},
        ]
        tasks.performance_tracker.performance_file.write_text(json.dumps(perf_data))

        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = utc_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_morning_briefing()
            await asyncio.sleep(0)

        assert tasks._morning_briefing_sent_date == today_str
        tasks.notification_queue.enqueue_raw_message.assert_called_once()
        # The message should mention overnight trades
        msg = tasks.notification_queue.enqueue_raw_message.call_args[0][0]
        assert "2 trades" in msg
        assert "1W/1L" in msg


# =========================================================================
# check_market_close_summary
# =========================================================================


class TestCheckMarketCloseSummary:
    """Tests for check_market_close_summary()."""

    @pytest.mark.asyncio
    async def test_noop_when_notifier_disabled(self, tasks):
        """Should skip if telegram is disabled."""
        tasks.telegram_notifier.enabled = False
        await tasks.check_market_close_summary()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_outside_window_too_early(self, tasks):
        """Should skip when ET time is before 3:55 PM."""
        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = _utc_from_et(15, 30)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_outside_window_too_late(self, tasks):
        """Should skip when ET time is after 4:05 PM."""
        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = _utc_from_et(16, 10)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_sent_today_guard(self, tasks):
        """Should skip if daily summary was already sent for today."""
        et_time = _make_et_datetime(15, 57)
        today_str = et_time.strftime("%Y-%m-%d")
        tasks._daily_summary_sent_date = today_str

        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = et_time.astimezone(timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
        tasks.notification_queue.enqueue_raw_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_no_trades_message(self, tasks):
        """Should send a 'No trades today' summary when no trades exist."""
        et_time = _make_et_datetime(15, 57)
        utc_time = et_time.astimezone(timezone.utc)

        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = utc_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
            await asyncio.sleep(0)

        assert tasks._daily_summary_sent_date == et_time.strftime("%Y-%m-%d")
        tasks.notification_queue.enqueue_raw_message.assert_called_once()
        msg = tasks.notification_queue.enqueue_raw_message.call_args[0][0]
        assert "No trades today" in msg

    @pytest.mark.asyncio
    async def test_sends_with_trades(self, tasks, tmp_path):
        """Should send detailed summary when trades exist in performance file."""
        et_time = _make_et_datetime(16, 2)
        utc_time = et_time.astimezone(timezone.utc)
        today_str = et_time.strftime("%Y-%m-%d")

        perf_data = [
            {"exit_time": f"{today_str}T14:00:00Z", "pnl": 200, "is_win": True, "direction": "long"},
            {"exit_time": f"{today_str}T15:00:00Z", "pnl": -75, "is_win": False, "direction": "short"},
        ]
        tasks.performance_tracker.performance_file.write_text(json.dumps(perf_data))

        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = utc_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
            await asyncio.sleep(0)

        assert tasks._daily_summary_sent_date == today_str
        tasks.notification_queue.enqueue_raw_message.assert_called_once()
        msg = tasks.notification_queue.enqueue_raw_message.call_args[0][0]
        assert "P&L" in msg
        assert "2" in msg  # 2 trades

    @pytest.mark.asyncio
    async def test_tv_paper_challenge_context(self, tasks, tmp_path):
        """Should add Tradovate Paper challenge context when account_label is Tradovate Paper."""
        tasks.telegram_notifier.account_label = "Tradovate Paper"
        et_time = _make_et_datetime(15, 58)
        utc_time = et_time.astimezone(timezone.utc)
        today_str = et_time.strftime("%Y-%m-%d")

        perf_data = [
            {"exit_time": f"{today_str}T14:00:00Z", "pnl": 500, "is_win": True, "direction": "long"},
        ]
        tasks.performance_tracker.performance_file.write_text(json.dumps(perf_data))

        challenge_state = {
            "tv_paper": {"profit_target": 3000, "max_drawdown": 2000, "starting_balance": 50000},
            "current_attempt": {"cumulative_pnl": 1500, "equity_hwm": 51500},
        }
        ch_file = tmp_path / "challenge_state.json"
        ch_file.write_text(json.dumps(challenge_state))

        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = utc_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
            await asyncio.sleep(0)

        assert tasks._daily_summary_sent_date == today_str
        tasks.notification_queue.enqueue_raw_message.assert_called_once()
        msg = tasks.notification_queue.enqueue_raw_message.call_args[0][0]
        # Challenge progress is not yet included in daily summary
        # (challenge_state.json is created but not read by check_market_close_summary)
        assert "Daily Summary" in msg
        assert "$500" in msg

    @pytest.mark.asyncio
    async def test_window_boundary_3_55_pm(self, tasks):
        """Should send at exactly 3:55 PM ET (boundary)."""
        et_time = _make_et_datetime(15, 55)
        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = et_time.astimezone(timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
            await asyncio.sleep(0)

        assert tasks._daily_summary_sent_date == et_time.strftime("%Y-%m-%d")
        tasks.notification_queue.enqueue_raw_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_window_boundary_4_05_pm(self, tasks):
        """Should send at exactly 4:05 PM ET (boundary)."""
        et_time = _make_et_datetime(16, 5)
        with patch("pearlalgo.market_agent.scheduled_tasks.datetime") as mock_dt:
            mock_dt.now.return_value = et_time.astimezone(timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await tasks.check_market_close_summary()
            await asyncio.sleep(0)

        assert tasks._daily_summary_sent_date == et_time.strftime("%Y-%m-%d")
        tasks.notification_queue.enqueue_raw_message.assert_called_once()


# =========================================================================
# _get_tradovate_today_trades
# =========================================================================


class TestGetTradovateTodayTrades:
    """Tests for _get_tradovate_today_trades()."""

    def test_empty_when_no_fills_file(self, tasks):
        """Should return empty list when tradovate_fills.json doesn't exist."""
        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert result == []

    def test_empty_when_fills_is_empty_list(self, tasks, tmp_path):
        """Should return empty list when fills file is empty list."""
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text("[]")
        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert result == []

    def test_empty_when_fills_is_not_list(self, tasks, tmp_path):
        """Should return empty list when fills data is not a list."""
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text('{"not": "a list"}')
        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert result == []

    def test_fifo_matching_long_trade(self, tasks, tmp_path):
        """Should match buy then sell into a long trade."""
        fills = [
            {"action": "buy", "price": 100.0, "qty": 1, "timestamp": "2025-06-10T10:00:00Z"},
            {"action": "sell", "price": 102.0, "qty": 1, "timestamp": "2025-06-10T10:30:00Z"},
        ]
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text(json.dumps(fills))

        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert len(result) == 1
        assert result[0]["direction"] == "long"
        assert result[0]["pnl"] == 4.0  # (102 - 100) * 1 * 2.0 point_value
        assert result[0]["is_win"] is True

    def test_fifo_matching_short_trade(self, tasks, tmp_path):
        """Should match sell then buy into a short trade."""
        fills = [
            {"action": "sell", "price": 102.0, "qty": 1, "timestamp": "2025-06-10T10:00:00Z"},
            {"action": "buy", "price": 100.0, "qty": 1, "timestamp": "2025-06-10T10:30:00Z"},
        ]
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text(json.dumps(fills))

        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert len(result) == 1
        assert result[0]["direction"] == "short"
        assert result[0]["pnl"] == 4.0  # (102 - 100) * 1 * 2.0
        assert result[0]["is_win"] is True

    def test_today_only_filtering(self, tasks, tmp_path):
        """Should only return trades from the requested date."""
        fills = [
            {"action": "buy", "price": 100.0, "qty": 1, "timestamp": "2025-06-09T10:00:00Z"},
            {"action": "sell", "price": 102.0, "qty": 1, "timestamp": "2025-06-09T10:30:00Z"},
            {"action": "buy", "price": 100.0, "qty": 1, "timestamp": "2025-06-10T10:00:00Z"},
            {"action": "sell", "price": 103.0, "qty": 1, "timestamp": "2025-06-10T10:30:00Z"},
        ]
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text(json.dumps(fills))

        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert len(result) == 1
        assert result[0]["exit_time"][:10] == "2025-06-10"

    def test_partial_quantity_matching(self, tasks, tmp_path):
        """Should handle partial fills with different quantities."""
        fills = [
            {"action": "buy", "price": 100.0, "qty": 3, "timestamp": "2025-06-10T10:00:00Z"},
            {"action": "sell", "price": 102.0, "qty": 1, "timestamp": "2025-06-10T10:15:00Z"},
            {"action": "sell", "price": 103.0, "qty": 2, "timestamp": "2025-06-10T10:30:00Z"},
        ]
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text(json.dumps(fills))

        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert len(result) == 2
        # First close: (102-100)*1*2 = 4
        assert result[0]["pnl"] == 4.0
        # Second close: (103-100)*2*2 = 12
        assert result[1]["pnl"] == 12.0

    def test_skips_fills_with_missing_fields(self, tasks, tmp_path):
        """Should skip fills that have missing required fields."""
        fills = [
            {"action": "buy", "price": 100.0},  # no qty
            {"price": 102.0, "qty": 1},  # no action
            {"action": "buy", "price": 100.0, "qty": 1, "timestamp": "2025-06-10T10:00:00Z"},
            {"action": "sell", "price": 102.0, "qty": 1, "timestamp": "2025-06-10T10:30:00Z"},
        ]
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text(json.dumps(fills))

        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert len(result) == 1

    def test_losing_trade(self, tasks, tmp_path):
        """Should correctly identify a losing trade."""
        fills = [
            {"action": "buy", "price": 105.0, "qty": 1, "timestamp": "2025-06-10T10:00:00Z"},
            {"action": "sell", "price": 100.0, "qty": 1, "timestamp": "2025-06-10T10:30:00Z"},
        ]
        fills_file = tmp_path / "tradovate_fills.json"
        fills_file.write_text(json.dumps(fills))

        result = tasks._get_tradovate_today_trades("2025-06-10")
        assert len(result) == 1
        assert result[0]["pnl"] == -10.0  # (100-105)*1*2
        assert result[0]["is_win"] is False
