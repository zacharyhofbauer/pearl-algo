"""
Failure-mode tests for MarketAgentService._run_loop error handling.

These tests verify that the service loop survives individual component
failures without crashing:
- Data fetch exceptions
- Strategy analysis exceptions
- State save IOError
- Execution adapter failure during signal processing

Because the service has many tightly-coupled dependencies, we create a
fully-constructed service via the configured_service fixture and then
monkeypatch individual components to inject failures.
"""

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestServiceLoopFailures:
    """Failure-mode tests for the service's main loop error paths."""

    @pytest.mark.asyncio
    async def test_run_loop_handles_data_fetch_exception(self, configured_service, caplog):
        """When data_fetcher.fetch_latest_data raises, the service should
        increment error counters, log the error, and continue (not crash)."""
        service = configured_service
        service.running = True
        service.shutdown_requested = False
        service.paused = False

        # Make data fetch raise an exception
        service.data_fetcher.fetch_latest_data = AsyncMock(
            side_effect=RuntimeError("IBKR connection timeout")
        )

        # Stub out notification methods to avoid Telegram calls
        service.notification_queue = MagicMock()
        service.notification_queue.enqueue_data_quality_alert = AsyncMock()
        service.notification_queue.enqueue_circuit_breaker = AsyncMock()
        service.notification_queue.enqueue_heartbeat = AsyncMock()

        # Stub out signal forwarder process to avoid side effects

        # Record initial error state
        initial_errors = service.data_fetch_errors

        # Run one cycle by requesting shutdown after the first data fetch failure
        cycle_count = 0

        original_sleep = asyncio.sleep

        async def count_and_stop(*args, **kwargs):
            nonlocal cycle_count
            cycle_count += 1
            service.shutdown_requested = True
            # Don't actually sleep
            return

        # Patch the sleep methods to stop after one cycle
        service._sleep_until_next_cycle = AsyncMock(side_effect=count_and_stop)
        service._interruptible_sleep = AsyncMock(side_effect=count_and_stop)

        # Stub out all scheduled tasks and other loop operations
        service.execution_orchestrator = MagicMock()
        service.execution_orchestrator.check_daily_reset = MagicMock()
        service.execution_orchestrator.check_execution_health = AsyncMock()
        service.scheduled_tasks = MagicMock()
        service.scheduled_tasks.check_morning_briefing = AsyncMock()
        service.scheduled_tasks.check_market_close_summary = AsyncMock()
        service.scheduled_tasks.check_follower_heartbeat = AsyncMock()
        service.scheduled_tasks.check_signal_pruning = AsyncMock()
        service.scheduled_tasks.check_audit_retention = AsyncMock()
        service.scheduled_tasks.check_equity_snapshot = AsyncMock()
        service._check_execution_control_flags = AsyncMock()
        service.cadence_scheduler = None
        service._adaptive_cadence_enabled = False

        with caplog.at_level(logging.WARNING):
            await service._run_loop()

        assert service.data_fetch_errors > initial_errors, (
            "data_fetch_errors should have incremented after fetch failure"
        )

    @pytest.mark.asyncio
    async def test_run_loop_handles_strategy_exception(self, configured_service, caplog):
        """When strategy.analyze raises, the service should catch the error
        and continue without crashing."""
        service = configured_service
        service.running = True
        service.shutdown_requested = False
        service.paused = False
        service._signal_follower_mode = False
        service._enable_new_bar_gating = False

        # Return valid data from fetcher
        valid_data = {
            "df": pd.DataFrame({
                "Open": [17500.0],
                "High": [17510.0],
                "Low": [17490.0],
                "Close": [17505.0],
                "Volume": [1000],
                "timestamp": [datetime.now(timezone.utc)],
            }),
            "latest_bar": {"close": 17505.0, "timestamp": datetime.now(timezone.utc).isoformat()},
        }
        service.data_fetcher.fetch_latest_data = AsyncMock(return_value=valid_data)

        # Make strategy analysis blow up
        service.strategy.analyze = MagicMock(
            side_effect=ValueError("NaN in EMA computation")
        )

        # Stubs for everything else
        service.notification_queue = MagicMock()
        service.notification_queue.enqueue_data_quality_alert = AsyncMock()
        service.notification_queue.enqueue_heartbeat = AsyncMock()
        service.notification_queue.enqueue_circuit_breaker = AsyncMock()
        service.notification_queue.enqueue_raw_message = AsyncMock()
        service.execution_orchestrator = MagicMock()
        service.execution_orchestrator.check_daily_reset = MagicMock()
        service.execution_orchestrator.check_execution_health = AsyncMock()
        service.scheduled_tasks = MagicMock()
        service.scheduled_tasks.check_morning_briefing = AsyncMock()
        service.scheduled_tasks.check_market_close_summary = AsyncMock()
        service.scheduled_tasks.check_follower_heartbeat = AsyncMock()
        service.scheduled_tasks.check_signal_pruning = AsyncMock()
        service.scheduled_tasks.check_audit_retention = AsyncMock()
        service.scheduled_tasks.check_equity_snapshot = AsyncMock()
        service._check_execution_control_flags = AsyncMock()
        service._check_data_quality = AsyncMock()
        service._handle_close_all_requests = AsyncMock()
        service.cadence_scheduler = None
        service._adaptive_cadence_enabled = False

        # ErrorHandler mock: simulate that data is valid (not a connection error)
        with patch(
            "pearlalgo.market_agent.service.ErrorHandler"
        ) as mock_eh:
            mock_eh.is_connection_error_from_data.return_value = False

            # Auto-shutdown after first sleep
            service._sleep_until_next_cycle = AsyncMock(
                side_effect=lambda *a, **kw: setattr(service, "shutdown_requested", True)
            )
            service._interruptible_sleep = AsyncMock(
                side_effect=lambda *a, **kw: setattr(service, "shutdown_requested", True)
            )

            # The strategy.analyze exception is called inside run_in_executor.
            # Since we mocked it with a MagicMock that raises, it will propagate
            # through run_in_executor. The service's outer try/except should catch it.
            await service._run_loop()

        # If we get here without exception, the service handled it gracefully.
        # The test passes by not crashing.

    @pytest.mark.asyncio
    async def test_state_save_failure_does_not_crash(self, configured_service, caplog):
        """When state_manager.save_state raises IOError inside _run_loop, the loop
        should catch it, increment error_count, and continue (not crash)."""
        from datetime import datetime, timezone

        service = configured_service
        service.running = True
        service.shutdown_requested = False
        service.paused = False
        service._signal_follower_mode = False
        service._enable_new_bar_gating = False

        # Succeed through fetch and strategy so we reach _save_state in the loop
        service.data_fetcher.fetch_latest_data = AsyncMock(return_value={
            "df": pd.DataFrame({
                "Open": [17500.0], "High": [17510.0], "Low": [17490.0],
                "Close": [17505.0], "Volume": [1000],
                "timestamp": [datetime.now(timezone.utc)],
            }),
            "latest_bar": {"close": 17505.0, "timestamp": datetime.now(timezone.utc).isoformat()},
        })
        service.strategy.analyze = MagicMock(return_value=[])

        # Make save_state raise so the loop hits the exception path
        service.state_manager.save_state = MagicMock(side_effect=IOError("Disk full"))
        service.state_manager.append_event = MagicMock()
        service._state_dirty = True
        service.state_save_interval = 1
        service.cycle_count = 0

        # Stub loop dependencies and stop after one cycle
        service.notification_queue = MagicMock()
        service.notification_queue.enqueue_data_quality_alert = AsyncMock()
        service.notification_queue.enqueue_circuit_breaker = AsyncMock()
        service.notification_queue.enqueue_heartbeat = AsyncMock()
        service.execution_orchestrator = MagicMock()
        service.execution_orchestrator.check_daily_reset = MagicMock()
        service.execution_orchestrator.check_execution_health = AsyncMock()
        service.scheduled_tasks = MagicMock()
        for m in ("check_morning_briefing", "check_market_close_summary", "check_follower_heartbeat",
                  "check_signal_pruning", "check_audit_retention", "check_equity_snapshot"):
            setattr(service.scheduled_tasks, m, AsyncMock())
        service._check_execution_control_flags = AsyncMock()
        service._check_data_quality = AsyncMock()
        service._handle_close_all_requests = AsyncMock()
        service._check_pearl_suggestions = AsyncMock()
        service._check_dashboard = AsyncMock()
        service.cadence_scheduler = None
        service._adaptive_cadence_enabled = False

        def stop_after_one(*args, **kwargs):
            service.shutdown_requested = True
        service._sleep_until_next_cycle = AsyncMock(side_effect=stop_after_one)
        service._interruptible_sleep = AsyncMock(side_effect=stop_after_one)

        initial_errors = service.error_count
        with caplog.at_level(logging.ERROR):
            await service._run_loop()

        assert service.error_count > initial_errors, (
            "error_count should have incremented after state save IOError"
        )
        assert service.state_manager is not None

    @pytest.mark.asyncio
    async def test_execution_adapter_failure_during_signal_processing(
        self, configured_service, caplog
    ):
        """When process_signal raises inside _run_loop (e.g. execution adapter
        failure), the loop should catch it, increment error_count, and continue."""
        from datetime import datetime, timezone

        service = configured_service
        service.running = True
        service.shutdown_requested = False
        service.paused = False
        service._signal_follower_mode = False
        service._enable_new_bar_gating = False

        # Data fetch succeeds
        service.data_fetcher.fetch_latest_data = AsyncMock(return_value={
            "df": pd.DataFrame({
                "Open": [17500.0], "High": [17510.0], "Low": [17490.0],
                "Close": [17505.0], "Volume": [1000],
                "timestamp": [datetime.now(timezone.utc)],
            }),
            "latest_bar": {"close": 17505.0, "timestamp": datetime.now(timezone.utc).isoformat()},
        })

        # Strategy returns one signal so we call process_signal
        test_signal = {
            "type": "momentum_ema_cross",
            "direction": "long",
            "entry_price": 17500.0,
            "stop_loss": 17480.0,
            "take_profit": 17540.0,
            "confidence": 0.8,
            "symbol": "MNQ",
            "position_size": 1,
        }
        service.strategy.analyze = MagicMock(return_value=[test_signal])

        # process_signal raises (e.g. broker connection dropped)
        service._signal_handler.process_signal = AsyncMock(
            side_effect=RuntimeError("Broker connection dropped mid-order")
        )
        service._signal_handler.get_signal_count = MagicMock(return_value=0)

        # Stub loop dependencies and stop after one cycle
        service.notification_queue = MagicMock()
        service.notification_queue.enqueue_data_quality_alert = AsyncMock()
        service.notification_queue.enqueue_circuit_breaker = AsyncMock()
        service.notification_queue.enqueue_heartbeat = AsyncMock()
        service.notification_queue.enqueue_raw_message = AsyncMock()
        service.execution_orchestrator = MagicMock()
        service.execution_orchestrator.check_daily_reset = MagicMock()
        service.execution_orchestrator.check_execution_health = AsyncMock()
        service.scheduled_tasks = MagicMock()
        for m in ("check_morning_briefing", "check_market_close_summary", "check_follower_heartbeat",
                  "check_signal_pruning", "check_audit_retention", "check_equity_snapshot"):
            setattr(service.scheduled_tasks, m, AsyncMock())
        service._check_execution_control_flags = AsyncMock()
        service._check_data_quality = AsyncMock()
        service._handle_close_all_requests = AsyncMock()
        service._check_pearl_suggestions = AsyncMock()
        service._check_dashboard = AsyncMock()
        service.state_manager.append_event = MagicMock()
        service.cadence_scheduler = None
        service._adaptive_cadence_enabled = False

        def stop_after_one(*args, **kwargs):
            service.shutdown_requested = True
        service._sleep_until_next_cycle = AsyncMock(side_effect=stop_after_one)
        service._interruptible_sleep = AsyncMock(side_effect=stop_after_one)

        initial_errors = service.error_count
        with caplog.at_level(logging.ERROR):
            await service._run_loop()

        assert service.error_count > initial_errors, (
            "error_count should have incremented after process_signal failure"
        )
        service._signal_handler.process_signal.assert_called_once()
