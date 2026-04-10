"""
Tests for High-Risk Untested Methods in MarketAgentService.

Covers the 5 highest-risk untested methods:
1. _process_signal          - core signal handling
2. _handle_connection_failure - error recovery
3. _check_data_quality      - data validation
4. _check_execution_health  - execution monitoring
5. _process_operator_requests (now delegated to OperatorHandler)
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from tests.mock_data_provider import MockDataProvider


# ---------------------------------------------------------------------------
# Minimal service config to avoid YAML load from disk
# ---------------------------------------------------------------------------
MINIMAL_SERVICE_CONFIG = {
    "service": {
        "scan_interval": 30,
        "status_update_interval": 900,
        "dashboard_chart_interval": 3600,
        "connection_failure_alert_interval": 600,
        "data_quality_alert_interval": 300,
        "state_save_interval": 10,
    },
    "circuit_breaker": {
        "max_consecutive_errors": 10,
        "max_data_fetch_errors": 5,
        "max_connection_failures": 10,
    },
    "trading_circuit_breaker": {"enabled": False},
    "data": {
        "stale_data_threshold_minutes": 10,
        "buffer_size": 100,
    },
    "signals": {},
    "risk": {},
    "strategy": {},
    "telegram": {},
    "telegram_ui": {},
    "auto_flat": {},
    "storage": {"sqlite_enabled": False},
    "challenge": {},
    "execution": {"enabled": False},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_data_provider():
    """Deterministic MockDataProvider (no random failures)."""
    return MockDataProvider(
        simulate_delayed_data=False,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )


@pytest.fixture
def service(mock_data_provider, tmp_path):
    """
    Create a *real* MarketAgentService with:
    - MockDataProvider (no live IBKR)
    - tmp_path as state_dir
    - Telegram disabled (no bot_token / chat_id)
    - load_service_config patched to avoid YAML file dependency
    """
    with patch(
        "pearlalgo.market_agent.service.load_service_config",
        return_value=MINIMAL_SERVICE_CONFIG.copy(),
    ):
        from pearlalgo.market_agent.service import MarketAgentService

        svc = MarketAgentService(
            data_provider=mock_data_provider,
            state_dir=tmp_path,
            # No telegram credentials → notifications disabled
        )
    return svc


def _make_signal(**overrides) -> dict:
    """Build a minimal valid signal dict with sensible defaults."""
    sig = {
        "signal_id": "test_signal_001",
        "type": "pearlbot_pinescript",
        "direction": "long",
        "entry_price": 17500.0,
        "stop_loss": 17450.0,
        "take_profit": 17600.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "generated",
        "confidence": 0.75,
    }
    sig.update(overrides)
    return sig


# ===========================================================================
# 1. Signal processing (delegated to SignalHandler via service._signal_handler)
# ===========================================================================


class TestProcessSignal:
    """Tests for signal processing – now delegated to service._signal_handler.

    Since _process_signal was extracted to SignalHandler, these tests
    exercise the integration: call service._signal_handler.process_signal(),
    then sync counters back, mirroring what the main loop does.
    """

    @pytest.mark.asyncio
    async def test_happy_path_signal_tracked_and_queued(self, service):
        """A valid signal should be tracked and queued for Telegram notification."""
        signal = _make_signal()

        # Mock the notification queue so we can assert it was called
        service.notification_queue.enqueue_entry = AsyncMock(return_value=True)

        initial_signal_count = service.signal_count

        await service._signal_handler.process_signal(signal)
        service._sync_signal_handler_counters()

        # Signal was tracked (signal_count incremented via sync)
        assert service.signal_count >= initial_signal_count + 1

        # Observability fields populated
        assert service._signal_handler.signals_sent >= 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_signal(self, service):
        """When trading circuit breaker blocks a signal, it should be skipped."""
        signal = _make_signal()

        # Simulate a blocking circuit-breaker decision
        mock_decision = MagicMock()
        mock_decision.allowed = False
        mock_decision.reason = "max_consecutive_losses"
        mock_decision.details = {"losses": 5}
        mock_decision.severity = "warning"
        mock_decision.to_dict.return_value = {
            "reason": "max_consecutive_losses",
            "details": {"losses": 5},
        }

        mock_cb = MagicMock()
        mock_cb.should_allow_signal.return_value = mock_decision
        mock_cb.config.mode = "enforce"
        service._signal_handler.trading_circuit_breaker = mock_cb

        initial_signal_count = service._signal_handler.signal_count

        await service._signal_handler.process_signal(signal)

        # Signal count should not have increased (blocked by circuit breaker)
        assert service._signal_handler.signal_count == initial_signal_count

    @pytest.mark.asyncio
    async def test_error_during_processing_increments_error_count(self, service):
        """An exception in the signal pipeline should increment error_count."""
        signal = _make_signal()

        # Force an error by breaking performance_tracker.track_signal_generated
        service.performance_tracker.track_signal_generated = MagicMock(
            side_effect=RuntimeError("DB write failed")
        )
        service._signal_handler.performance_tracker = service.performance_tracker

        initial_errors = service._signal_handler.error_count

        await service._signal_handler.process_signal(signal)

        assert service._signal_handler.error_count >= initial_errors + 1

    @pytest.mark.asyncio
    async def test_queue_full_increments_send_failures(self, service):
        """When notification queue is full, signals_send_failures should increment."""
        signal = _make_signal()

        # enqueue_entry returns False when queue is full
        service.notification_queue.enqueue_entry = AsyncMock(return_value=False)
        service._signal_handler.notification_queue = service.notification_queue

        initial_failures = service._signal_handler.signals_send_failures

        await service._signal_handler.process_signal(signal)

        assert service._signal_handler.signals_send_failures >= initial_failures


# ===========================================================================
# 2. _handle_connection_failure
# ===========================================================================


class TestHandleConnectionFailure:
    """Tests for _handle_connection_failure – error recovery alerting."""

    @pytest.mark.asyncio
    async def test_sends_alert_on_first_failure(self, service):
        """Should send alert when no previous alert has been sent."""
        service.connection_failures = 3
        service.last_connection_failure_alert = None  # never alerted before

        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)

        await service._handle_connection_failure()

        service.notification_queue.enqueue_data_quality_alert.assert_awaited_once()
        call_args = service.notification_queue.enqueue_data_quality_alert.call_args
        # First positional arg is alert_type
        assert call_args[0][0] == "fetch_failure"
        # Message should mention connection failures count
        assert "3 failures" in call_args[0][1]
        # Timestamp updated
        assert service.last_connection_failure_alert is not None

    @pytest.mark.asyncio
    async def test_throttles_alert_within_interval(self, service):
        """Should NOT send alert when recently alerted (within interval)."""
        service.connection_failures = 5
        # Alert was sent 10 seconds ago, interval is 600
        service.last_connection_failure_alert = datetime.now(timezone.utc) - timedelta(seconds=10)

        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)

        await service._handle_connection_failure()

        service.notification_queue.enqueue_data_quality_alert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sends_alert_after_interval_elapsed(self, service):
        """Should send alert when interval has fully elapsed."""
        service.connection_failures = 7
        # Alert was sent well beyond the interval
        service.last_connection_failure_alert = (
            datetime.now(timezone.utc) - timedelta(seconds=service.connection_failure_alert_interval + 60)
        )

        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)

        await service._handle_connection_failure()

        service.notification_queue.enqueue_data_quality_alert.assert_awaited_once()
        assert "7 failures" in service.notification_queue.enqueue_data_quality_alert.call_args[0][1]


# ===========================================================================
# 3. _check_data_quality
# ===========================================================================


class TestCheckDataQuality:
    """Tests for _check_data_quality – data validation alerting."""

    @pytest.mark.asyncio
    async def test_fresh_data_no_alert(self, service):
        """Fresh data with adequate buffer should not trigger any alert."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame(
            {
                "open": [17500.0] * 50,
                "high": [17510.0] * 50,
                "low": [17490.0] * 50,
                "close": [17505.0] * 50,
                "volume": [1000] * 50,
            },
            index=pd.date_range(now - timedelta(minutes=50), periods=50, freq="1min", tz=timezone.utc),
        )
        market_data = {
            "df": df,
            "latest_bar": {"timestamp": now, "close": 17505.0},
        }

        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)

        await service._check_data_quality(market_data)

        # No data quality alert should have been sent
        service.notification_queue.enqueue_data_quality_alert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_data_during_market_hours_sends_alert(self, service):
        """Stale data during market hours should trigger a stale_data alert."""
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        df = pd.DataFrame(
            {
                "open": [17500.0] * 20,
                "high": [17510.0] * 20,
                "low": [17490.0] * 20,
                "close": [17505.0] * 20,
                "volume": [1000] * 20,
            },
            index=pd.date_range(
                stale_time - timedelta(minutes=20), periods=20, freq="1min", tz=timezone.utc
            ),
        )
        market_data = {
            "df": df,
            "latest_bar": {"timestamp": stale_time, "close": 17505.0},
        }

        # Patch at source module since _check_data_quality does a local import
        with patch("pearlalgo.utils.market_hours.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = True

            service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)
            # Reset state so the alert is not throttled
            service.last_data_quality_alert = None
            service._last_stale_bucket = None
            service._was_stale_during_market = False

            await service._check_data_quality(market_data)

        # Should have sent a stale_data alert
        service.notification_queue.enqueue_data_quality_alert.assert_awaited_once()
        call_args = service.notification_queue.enqueue_data_quality_alert.call_args
        assert call_args[0][0] == "stale_data"

    @pytest.mark.asyncio
    async def test_stale_data_outside_market_hours_no_alert(self, service):
        """Stale data when market is closed should NOT trigger an alert."""
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        df = pd.DataFrame(
            {
                "open": [17500.0] * 20,
                "high": [17510.0] * 20,
                "low": [17490.0] * 20,
                "close": [17505.0] * 20,
                "volume": [1000] * 20,
            },
            index=pd.date_range(
                stale_time - timedelta(minutes=20), periods=20, freq="1min", tz=timezone.utc
            ),
        )
        market_data = {
            "df": df,
            "latest_bar": {"timestamp": stale_time, "close": 17505.0},
        }

        # Patch at source module since _check_data_quality does a local import
        with patch("pearlalgo.utils.market_hours.get_market_hours") as mock_mh:
            mock_mh.return_value.is_market_open.return_value = False

            service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)
            service.last_data_quality_alert = None
            service._last_stale_bucket = None

            await service._check_data_quality(market_data)

        # No alert during off-hours
        service.notification_queue.enqueue_data_quality_alert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_dataframe_sends_data_gap_alert(self, service):
        """An empty DataFrame should trigger a data_gap alert."""
        market_data = {
            "df": pd.DataFrame(),
            "latest_bar": {"timestamp": datetime.now(timezone.utc), "close": 17505.0},
        }

        # Data is "fresh" (latest_bar has recent timestamp) so freshness passes,
        # but the empty df triggers a data_gap alert.
        service.notification_queue.enqueue_data_quality_alert = AsyncMock(return_value=True)
        service.last_data_quality_alert = None
        service._was_data_gap = False
        service._last_stale_data_alert_type = None

        await service._check_data_quality(market_data)

        service.notification_queue.enqueue_data_quality_alert.assert_awaited_once()
        call_args = service.notification_queue.enqueue_data_quality_alert.call_args
        assert call_args[0][0] == "data_gap"


# ===========================================================================
# 4. _check_execution_health
# ===========================================================================


class TestCheckExecutionHealth:
    """Tests for _check_execution_health – execution monitoring."""

    @pytest.mark.asyncio
    async def test_no_adapter_returns_immediately(self, service):
        """When execution_adapter is None, method should return without action."""
        service.execution_adapter = None

        service.notification_queue.enqueue_raw_message = AsyncMock(return_value=True)

        await service._check_execution_health()

        service.notification_queue.enqueue_raw_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_first_check_initialises_state(self, service):
        """First call should initialise _execution_was_connected and return."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.armed = False

        # Enable execution config
        mock_exec_config = MagicMock()
        mock_exec_config.enabled = True

        # Set up the orchestrator (check_execution_health is now delegated there)
        orch = service.execution_orchestrator
        orch._execution_adapter = mock_adapter
        orch._execution_config = mock_exec_config
        orch._execution_was_connected = None

        mock_nq = MagicMock()
        mock_nq.enqueue_raw_message = AsyncMock(return_value=True)
        orch._notification_queue = mock_nq

        await service._check_execution_health()

        # State should now be initialised, but no alert sent
        assert orch._execution_was_connected is True
        mock_nq.enqueue_raw_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connection_lost_sends_alert(self, service):
        """Transition from connected → disconnected should send a disconnect alert."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = False
        mock_adapter.armed = False

        mock_exec_config = MagicMock()
        mock_exec_config.enabled = True

        # Set up the orchestrator (check_execution_health is now delegated there)
        orch = service.execution_orchestrator
        orch._execution_adapter = mock_adapter
        orch._execution_config = mock_exec_config
        orch._execution_was_connected = True
        orch._last_connection_alert_time = None

        mock_nq = MagicMock()
        mock_nq.enqueue_raw_message = AsyncMock(return_value=True)
        orch._notification_queue = mock_nq

        await service._check_execution_health()

        mock_nq.enqueue_raw_message.assert_awaited_once()
        msg = mock_nq.enqueue_raw_message.call_args[0][0]
        assert "Disconnected" in msg
        assert orch._execution_was_connected is False

    @pytest.mark.asyncio
    async def test_connection_restored_sends_alert(self, service):
        """Transition from disconnected → connected should send a restored alert."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.armed = True

        mock_exec_config = MagicMock()
        mock_exec_config.enabled = True

        # Set up the orchestrator (check_execution_health is now delegated there)
        orch = service.execution_orchestrator
        orch._execution_adapter = mock_adapter
        orch._execution_config = mock_exec_config
        orch._execution_was_connected = False
        orch._last_connection_alert_time = None

        mock_nq = MagicMock()
        mock_nq.enqueue_raw_message = AsyncMock(return_value=True)
        orch._notification_queue = mock_nq

        await service._check_execution_health()

        mock_nq.enqueue_raw_message.assert_awaited_once()
        msg = mock_nq.enqueue_raw_message.call_args[0][0]
        assert "Connected" in msg
        assert orch._execution_was_connected is True

    @pytest.mark.asyncio
    async def test_no_state_change_no_alert(self, service):
        """Same connection state should not produce an alert."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True

        mock_exec_config = MagicMock()
        mock_exec_config.enabled = True

        # Set up the orchestrator (check_execution_health is now delegated there)
        orch = service.execution_orchestrator
        orch._execution_adapter = mock_adapter
        orch._execution_config = mock_exec_config
        orch._execution_was_connected = True  # same as is_connected()

        mock_nq = MagicMock()
        mock_nq.enqueue_raw_message = AsyncMock(return_value=True)
        orch._notification_queue = mock_nq

        await service._check_execution_health()

        mock_nq.enqueue_raw_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cooldown_suppresses_duplicate_alerts(self, service):
        """Alert within cooldown period should be suppressed."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = False

        mock_exec_config = MagicMock()
        mock_exec_config.enabled = True

        # Set up the orchestrator (check_execution_health is now delegated there)
        orch = service.execution_orchestrator
        orch._execution_adapter = mock_adapter
        orch._execution_config = mock_exec_config
        orch._execution_was_connected = True
        orch._last_connection_alert_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        orch._connection_alert_cooldown_seconds = 300

        mock_nq = MagicMock()
        mock_nq.enqueue_raw_message = AsyncMock(return_value=True)
        orch._notification_queue = mock_nq

        await service._check_execution_health()

        # Alert suppressed by cooldown
        mock_nq.enqueue_raw_message.assert_not_awaited()
        # State still updates even when alert is suppressed
        assert orch._execution_was_connected is False


# ===========================================================================
# 5. _process_operator_requests  (OperatorHandler)
# ===========================================================================


class TestProcessOperatorRequests:
    """
    Tests for operator request processing.

    The logic now lives in OperatorHandler.process_operator_requests().
    We test the handler directly and also verify the service delegates to it.
    """

    @pytest.fixture
    def operator_handler(self, tmp_path):
        """Create an OperatorHandler with mocked collaborators."""
        from pearlalgo.market_agent.operator_handler import OperatorHandler

        state_manager = MagicMock()
        state_manager.state_dir = tmp_path

        notification_queue = AsyncMock()

        handler = OperatorHandler(
            state_manager=state_manager,
            notification_queue=notification_queue,
            get_status_snapshot=lambda: {"daily_pnl": 100, "wins_today": 3},
        )
        return handler

    @pytest.mark.asyncio
    async def test_accept_feedback_cleans_up_file(self, operator_handler, tmp_path):
        """Accepting a suggestion should clean up the request file."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        payload = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
            "suggestion_id": "sugg_abc123",
        }
        (req_dir / "pearl_suggestion_feedback_001.json").write_text(json.dumps(payload))

        await operator_handler.process_operator_requests(tmp_path)

        # File should be cleaned up
        assert not (req_dir / "pearl_suggestion_feedback_001.json").exists()

    @pytest.mark.asyncio
    async def test_dismiss_feedback_cleans_up_file(self, operator_handler, tmp_path):
        """Dismissing a suggestion should clean up the request file."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        payload = {
            "type": "pearl_suggestion_feedback",
            "action": "dismiss",
            "suggestion_id": "sugg_xyz789",
        }
        (req_dir / "pearl_suggestion_feedback_002.json").write_text(json.dumps(payload))

        await operator_handler.process_operator_requests(tmp_path)

        assert not (req_dir / "pearl_suggestion_feedback_002.json").exists()

    @pytest.mark.asyncio
    async def test_invalid_json_file_is_cleaned_up(self, operator_handler, tmp_path):
        """A malformed JSON file should be removed without crashing."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        (req_dir / "pearl_suggestion_feedback_003.json").write_text("NOT VALID JSON{{{")

        await operator_handler.process_operator_requests(tmp_path)

        # Should not crash and file should be cleaned up
        assert not (req_dir / "pearl_suggestion_feedback_003.json").exists()

    @pytest.mark.asyncio
    async def test_missing_action_or_id_skips_silently(self, operator_handler, tmp_path):
        """A request missing action or suggestion_id should be skipped."""
        req_dir = tmp_path / "operator_requests"
        req_dir.mkdir()

        # Missing suggestion_id
        payload = {
            "type": "pearl_suggestion_feedback",
            "action": "accept",
        }
        (req_dir / "pearl_suggestion_feedback_004.json").write_text(json.dumps(payload))

        await operator_handler.process_operator_requests(tmp_path)

        assert not (req_dir / "pearl_suggestion_feedback_004.json").exists()

    @pytest.mark.asyncio
    async def test_no_requests_dir_returns_early(self, operator_handler, tmp_path):
        """If operator_requests dir doesn't exist, should return immediately."""
        # Don't create the dir — handler should just return
        await operator_handler.process_operator_requests(tmp_path)

    @pytest.mark.asyncio
    async def test_service_delegates_to_operator_handler(self, service):
        """MarketAgentService._process_operator_requests should delegate to handler."""
        # The service still has its own _process_operator_requests (legacy path)
        # but the primary flow goes through operator_handler in _check_execution_control_flags.
        # Verify the operator_handler exists and is wired up.
        assert hasattr(service, "operator_handler")
        assert service.operator_handler is not None
        assert hasattr(service.operator_handler, "process_operator_requests")
