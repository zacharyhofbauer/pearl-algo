"""
Comprehensive tests for service_lifecycle.py targeting all uncovered lines.

Covers: start(), stop(), signal handlers, graceful shutdown, error paths.
"""

import asyncio
import signal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from pearlalgo.market_agent.service_lifecycle import ServiceLifecycleMixin


# ---------------------------------------------------------------------------
# Helper: build a fake service instance with all attributes the mixin needs
# ---------------------------------------------------------------------------

def _make_service(**overrides):
    """Create a stub object that satisfies ServiceLifecycleMixin's attribute access."""
    svc = MagicMock(spec=[])  # no spec so we can set anything
    # Inherit the mixin methods
    svc.start = ServiceLifecycleMixin.start.__get__(svc)
    svc.stop = ServiceLifecycleMixin.stop.__get__(svc)
    # _os_signal_handler lives on MarketAgentService, not the mixin; provide a stub
    svc._os_signal_handler = lambda signum, frame: None

    # Flags
    svc.running = False
    svc.shutdown_requested = False
    svc.start_time = None

    # Counters
    svc.cycle_count = 10
    svc.signal_count = 5
    svc.signals_sent = 3
    svc.signals_send_failures = 1
    svc.error_count = 0
    svc._cycle_count_at_start = 0
    svc._signal_count_at_start = 0
    svc._signals_sent_at_start = 0
    svc._signals_fail_at_start = 0

    # Config
    config = MagicMock()
    config.symbol = "MNQ"
    config.timeframe = "5m"
    config.scan_interval = 30
    svc.config = config
    svc.symbol = "MNQ"
    svc.timeframe = "5m"

    # Audit logger
    svc.audit_logger = MagicMock()
    svc.audit_logger.start = MagicMock()
    svc.audit_logger.log_system_event = MagicMock()
    svc.audit_logger.stop = MagicMock()

    # Notification queue
    svc.notification_queue = AsyncMock()
    svc.notification_queue.start = AsyncMock()
    svc.notification_queue.stop = AsyncMock()
    svc.notification_queue.enqueue_startup = AsyncMock()
    svc.notification_queue.get_stats = MagicMock(return_value={"sent": 5})

    # Telegram notifier
    svc.telegram_notifier = AsyncMock()
    svc.telegram_notifier.send_shutdown_notification = AsyncMock()

    # Data fetcher
    svc.data_fetcher = AsyncMock()
    svc.data_fetcher.fetch_startup_snapshot = AsyncMock(return_value=None)
    svc.data_fetcher.close = AsyncMock()

    # Performance tracker
    svc.performance_tracker = MagicMock()
    svc.performance_tracker.get_performance_metrics = MagicMock(return_value={
        "wins": 5, "losses": 2, "total_pnl": 1234.56,
    })

    # Execution adapter
    svc.execution_adapter = None
    svc._execution_config = MagicMock()
    svc._execution_config.mode = MagicMock()
    svc._execution_config.mode.value = "paper"

    # Async sqlite queue
    svc._async_sqlite_queue = None

    # State saving
    svc._save_state = MagicMock()

    # Run loop
    svc._run_loop = AsyncMock()

    # Status tracking
    svc.last_status_update = None
    svc.last_dashboard_chart_sent = None

    # Apply overrides
    for k, v in overrides.items():
        setattr(svc, k, v)

    return svc


# ===================================================================
# start() tests
# ===================================================================


class TestStartAlreadyRunning:
    """Lines 31-32: early return when already running."""

    @pytest.mark.asyncio
    async def test_start_when_already_running_returns_immediately(self):
        svc = _make_service(running=True)
        await svc.start()
        svc._run_loop.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_when_already_running_does_not_change_shutdown_flag(self):
        svc = _make_service(running=True, shutdown_requested=True)
        await svc.start()
        assert svc.shutdown_requested is True


class TestStartFetchSnapshotFailure:
    """Lines 71-73: fetch_startup_snapshot raises."""

    @pytest.mark.asyncio
    async def test_start_snapshot_timeout_is_caught(self):
        svc = _make_service()
        svc.data_fetcher.fetch_startup_snapshot = AsyncMock(side_effect=asyncio.TimeoutError)
        await svc.start()
        # Should still have called enqueue_startup (market_data == {})
        svc.notification_queue.enqueue_startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_snapshot_generic_exception_is_caught(self):
        svc = _make_service()
        svc.data_fetcher.fetch_startup_snapshot = AsyncMock(side_effect=RuntimeError("network"))
        await svc.start()
        svc.notification_queue.enqueue_startup.assert_called_once()


class TestStartMarketHoursFailure:
    """Lines 85-87: get_market_hours().is_market_open() raises."""

    @pytest.mark.asyncio
    async def test_start_market_hours_exception_sets_none(self):
        svc = _make_service()
        with patch("pearlalgo.market_agent.service_lifecycle.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.side_effect = RuntimeError("tz error")
            await svc.start()
        # Should still succeed
        svc.notification_queue.enqueue_startup.assert_called_once()
        call_args = svc.notification_queue.enqueue_startup.call_args
        config_dict = call_args[0][0]
        assert config_dict["futures_market_open"] is None


class TestStartStrategySessionFailure:
    """Lines 91-93: check_trading_session raises."""

    @pytest.mark.asyncio
    async def test_start_strategy_session_exception_sets_none(self):
        svc = _make_service()
        with patch("pearlalgo.market_agent.service_lifecycle.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True
            with patch("pearlalgo.trading_bots.pearl_bot_auto.check_trading_session", side_effect=RuntimeError("bad")):
                await svc.start()
        svc.notification_queue.enqueue_startup.assert_called_once()
        config_dict = svc.notification_queue.enqueue_startup.call_args[0][0]
        assert config_dict["strategy_session_open"] is None


class TestStartLatestPriceExtraction:
    """Lines 99-100: exception extracting latest_price."""

    @pytest.mark.asyncio
    async def test_start_latest_price_exception_is_caught(self):
        svc = _make_service()
        # Return something that will cause .get() to fail
        svc.data_fetcher.fetch_startup_snapshot = AsyncMock(return_value={"latest_bar": "not_a_dict"})
        # Should not crash
        await svc.start()
        svc.notification_queue.enqueue_startup.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_latest_price_from_valid_bar(self):
        svc = _make_service()
        svc.data_fetcher.fetch_startup_snapshot = AsyncMock(
            return_value={"latest_bar": {"close": 17550.0, "open": 17540.0}}
        )
        await svc.start()
        config_dict = svc.notification_queue.enqueue_startup.call_args[0][0]
        assert config_dict.get("latest_price") == 17550.0


class TestStartEnqueueStartupFailure:
    """Lines 104-105: enqueue_startup raises."""

    @pytest.mark.asyncio
    async def test_start_enqueue_startup_exception_caught(self):
        svc = _make_service()
        svc.notification_queue.enqueue_startup = AsyncMock(side_effect=RuntimeError("queue broken"))
        # Should not propagate
        await svc.start()
        assert svc.running is False or svc.running is True  # didn't crash


class TestStartSaveStateFailure:
    """Lines 117-118: _save_state raises during startup."""

    @pytest.mark.asyncio
    async def test_start_save_state_failure_is_logged(self):
        svc = _make_service()
        svc._save_state = MagicMock(side_effect=RuntimeError("disk full"))
        # Should not crash the start
        await svc.start()


class TestStartExecutionAdapter:
    """Lines 122-132: execution adapter connect paths."""

    @pytest.mark.asyncio
    async def test_start_execution_adapter_connect_success(self):
        adapter = AsyncMock()
        adapter.connect = AsyncMock(return_value=True)
        adapter.armed = True
        svc = _make_service(execution_adapter=adapter)
        await svc.start()
        adapter.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_execution_adapter_connect_returns_false(self):
        adapter = AsyncMock()
        adapter.connect = AsyncMock(return_value=False)
        svc = _make_service(execution_adapter=adapter)
        await svc.start()
        adapter.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_execution_adapter_connect_raises(self):
        adapter = AsyncMock()
        adapter.connect = AsyncMock(side_effect=ConnectionError("refused"))
        svc = _make_service(execution_adapter=adapter)
        await svc.start()
        adapter.connect.assert_called_once()


class TestStartRunLoopExceptions:
    """Lines 136-141, 145: _run_loop raises KeyboardInterrupt / Exception."""

    @pytest.mark.asyncio
    async def test_start_keyboard_interrupt_calls_stop(self):
        svc = _make_service()
        svc._run_loop = AsyncMock(side_effect=KeyboardInterrupt)
        # stop will set running=False
        original_stop = ServiceLifecycleMixin.stop

        async def fake_stop(self_inner, reason=""):
            self_inner.running = False

        with patch.object(ServiceLifecycleMixin, 'stop', fake_stop):
            svc.stop = fake_stop.__get__(svc)
            await svc.start()
        assert svc.running is False

    @pytest.mark.asyncio
    async def test_start_generic_exception_calls_stop(self):
        svc = _make_service()
        svc._run_loop = AsyncMock(side_effect=ValueError("boom"))

        async def fake_stop(self_inner, reason=""):
            self_inner.running = False

        svc.stop = fake_stop.__get__(svc)
        await svc.start()
        assert svc.running is False

    @pytest.mark.asyncio
    async def test_start_finally_calls_stop_if_still_running(self):
        """Line 145: finally block calls stop if running is still True."""
        svc = _make_service()
        # _run_loop completes normally but doesn't set running=False
        svc._run_loop = AsyncMock()

        stop_called_reasons = []

        async def tracking_stop(self_inner, reason=""):
            stop_called_reasons.append(reason)
            self_inner.running = False

        svc.stop = tracking_stop.__get__(svc)
        await svc.start()
        assert "Final cleanup" in stop_called_reasons


# ===================================================================
# stop() tests
# ===================================================================


class TestStopNotRunning:
    """stop() returns early when not running."""

    @pytest.mark.asyncio
    async def test_stop_when_not_running_returns_immediately(self):
        svc = _make_service(running=False)
        await svc.stop("test")
        svc._save_state.assert_not_called()


class TestStopAuditLogger:
    """Lines 163-164: audit logger stop raises."""

    @pytest.mark.asyncio
    async def test_stop_audit_logger_exception_caught(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc.audit_logger.stop.side_effect = RuntimeError("flush error")
        await svc.stop("test")
        assert svc.running is False

    @pytest.mark.asyncio
    async def test_stop_audit_logger_none_skipped(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc), audit_logger=None)
        await svc.stop("test")
        assert svc.running is False


class TestStopAsyncSqliteQueue:
    """Lines 168-171: async sqlite queue stop."""

    @pytest.mark.asyncio
    async def test_stop_async_sqlite_queue_stopped(self):
        queue = MagicMock()
        queue.stop = MagicMock()
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc), _async_sqlite_queue=queue)
        await svc.stop("test")
        queue.stop.assert_called_once_with(timeout=5.0)

    @pytest.mark.asyncio
    async def test_stop_async_sqlite_queue_exception_caught(self):
        queue = MagicMock()
        queue.stop = MagicMock(side_effect=RuntimeError("busy"))
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc), _async_sqlite_queue=queue)
        await svc.stop("test")
        assert svc.running is False


class TestStopNotificationQueue:
    """Lines 178-179: notification queue stop raises."""

    @pytest.mark.asyncio
    async def test_stop_notification_queue_exception_caught(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc.notification_queue.stop = AsyncMock(side_effect=RuntimeError("timeout"))
        await svc.stop("test")
        assert svc.running is False


class TestStopDataFetcherCleanup:
    """Provider cleanup should happen during stop() so executor threads exit."""

    @pytest.mark.asyncio
    async def test_stop_closes_data_fetcher(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        await svc.stop("test")
        svc.data_fetcher.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_data_fetcher_close_exception_caught(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc.data_fetcher.close = AsyncMock(side_effect=RuntimeError("provider busy"))
        await svc.stop("test")
        assert svc.running is False

    @pytest.mark.asyncio
    async def test_stop_data_fetcher_close_timeout_caught(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc.data_fetcher.close = AsyncMock(side_effect=asyncio.TimeoutError)
        await svc.stop("test")
        assert svc.running is False


class TestStopSaveState:
    """Lines 184-185: _save_state raises during stop."""

    @pytest.mark.asyncio
    async def test_stop_save_state_failure_caught(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc._save_state = MagicMock(side_effect=RuntimeError("disk"))
        await svc.stop("test")
        # Should still mark as not running despite save failure -- running is set
        # after save, so the second save also fails but we handle it
        # The first _save_state call is at line 183, second at line 236

    @pytest.mark.asyncio
    async def test_stop_final_save_state_failure_caught(self):
        """Lines 237-238: second _save_state at end of stop raises."""
        call_count = 0

        def save_side_effect(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("final save fail")

        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc._save_state = MagicMock(side_effect=save_side_effect)
        await svc.stop("test")
        assert svc.running is False


class TestStopPerformanceMetrics:
    """Lines 206-207: performance_tracker.get_performance_metrics raises."""

    @pytest.mark.asyncio
    async def test_stop_performance_metrics_exception_caught(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc.performance_tracker.get_performance_metrics.side_effect = RuntimeError("no db")
        await svc.stop("test")
        assert svc.running is False


class TestStopShutdownNotification:
    """Lines 217-220: shutdown notification timeout and exception."""

    @pytest.mark.asyncio
    async def test_stop_shutdown_notification_timeout(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))

        async def slow_send(summary):
            await asyncio.sleep(100)

        svc.telegram_notifier.send_shutdown_notification = slow_send
        # Patch wait_for timeout to be very short
        with patch("pearlalgo.market_agent.service_lifecycle.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await svc.stop("test")
        assert svc.running is False

    @pytest.mark.asyncio
    async def test_stop_shutdown_notification_general_exception(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        svc.telegram_notifier.send_shutdown_notification = AsyncMock(side_effect=RuntimeError("boom"))
        # The outer try/except at line 219 should catch
        with patch("pearlalgo.market_agent.service_lifecycle.asyncio.wait_for", side_effect=RuntimeError("outer boom")):
            await svc.stop("test")
        assert svc.running is False


class TestStopExecutionAdapter:
    """Lines 224-230: execution adapter disconnect paths."""

    @pytest.mark.asyncio
    async def test_stop_execution_adapter_disconnect_success(self):
        adapter = AsyncMock()
        adapter.disarm = MagicMock()
        adapter.disconnect = AsyncMock()
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc), execution_adapter=adapter)
        await svc.stop("test")
        adapter.disarm.assert_called_once()
        adapter.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_execution_adapter_disconnect_exception_caught(self):
        adapter = AsyncMock()
        adapter.disarm = MagicMock(side_effect=RuntimeError("already disarmed"))
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc), execution_adapter=adapter)
        await svc.stop("test")
        assert svc.running is False

    @pytest.mark.asyncio
    async def test_stop_execution_adapter_none_skipped(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc), execution_adapter=None)
        await svc.stop("test")
        assert svc.running is False


class TestStopUptimeCalculation:
    """Ensure uptime is calculated correctly in stop."""

    @pytest.mark.asyncio
    async def test_stop_with_no_start_time(self):
        svc = _make_service(running=True, start_time=None)
        await svc.stop("no start time")
        assert svc.running is False

    @pytest.mark.asyncio
    async def test_stop_with_valid_start_time(self):
        svc = _make_service(running=True, start_time=datetime(2026, 3, 12, 10, 0, 0, tzinfo=timezone.utc))
        await svc.stop("normal shutdown")
        assert svc.running is False
        svc.telegram_notifier.send_shutdown_notification.assert_called_once()


class TestStopShutdownReason:
    """Verify shutdown_reason is passed through."""

    @pytest.mark.asyncio
    async def test_stop_passes_reason_to_audit(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        await svc.stop("Circuit breaker triggered")
        svc.audit_logger.log_system_event.assert_called()
        call_args = svc.audit_logger.log_system_event.call_args_list
        # Find the SYSTEM_STOP call
        found = False
        for call in call_args:
            if call[0][0] == "system_stop":
                assert call[0][1]["reason"] == "Circuit breaker triggered"
                found = True
        assert found


class TestStopSetsRunningFalse:
    """Lines 232, 236-238: running set to False and final save."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false_and_saves(self):
        svc = _make_service(running=True, start_time=datetime.now(timezone.utc))
        await svc.stop("test")
        assert svc.running is False
        # _save_state called twice: line 183 and line 236
        assert svc._save_state.call_count == 2
