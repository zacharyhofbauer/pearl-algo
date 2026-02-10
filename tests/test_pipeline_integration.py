"""Pipeline integration tests -- verifies format compatibility between components.

Wires together real instances (StateManager) with known data to verify
that the connection points between pipeline stages work correctly.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from unittest.mock import patch

import pytest


def _make_signal(entry: float = 17600.0, direction: str = "long") -> Dict:
    """Return a minimal signal dict compatible with state_manager.save_signal()."""
    sl = entry - 20.0 if direction == "long" else entry + 20.0
    tp = entry + 30.0 if direction == "long" else entry - 30.0
    return {
        "direction": direction,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "confidence": 0.72,
        "risk_reward": 1.5,
        "reason": "ema_crossover",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": "MNQ",
        "timeframe": "1m",
        "type": "pearlbot_pinescript",
        "virtual_broker": True,
    }


# ---------------------------------------------------------------------------
# Signal persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSignalPersistence:
    """Verify signal round-trip through state manager."""

    def test_signal_generated_and_persisted(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        signal = _make_signal()
        sm.save_signal(signal)

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 1
        saved = recent[-1]
        inner = saved.get("signal", saved)
        assert inner.get("direction") == "long"
        assert inner.get("confidence") == 0.72

    def test_multiple_signals_ordered(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        for i in range(5):
            sig = _make_signal(entry=17600.0 + i)
            sm.save_signal(sig)

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 5


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStateRoundTrip:
    """Verify state save/load preserves data."""

    def test_state_round_trip(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        state = {
            "signal_count": 42,
            "running": True,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        sm.save_state(state)
        loaded = sm.load_state()
        assert loaded["signal_count"] == 42
        assert loaded["running"] is True

    def test_state_overwrite(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        sm.save_state({"signal_count": 1})
        sm.save_state({"signal_count": 2, "extra": "field"})
        loaded = sm.load_state()
        assert loaded["signal_count"] == 2
        assert loaded.get("extra") == "field"


# ---------------------------------------------------------------------------
# Format compatibility
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSignalFormatCompatibility:
    """Verify signal dict format is compatible with save_signal."""

    def test_pipeline_data_format_compatibility(self, tmp_path: Path):
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        sm.save_signal(_make_signal())
        sm.save_signal(_make_signal(direction="short"))
        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 2

    def test_signal_with_extra_fields_accepted(self, tmp_path: Path):
        """Extra fields (indicators, regime, etc.) should not break save_signal."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        signal = _make_signal()
        signal["market_regime"] = {"regime": "trending_up", "confidence": 0.8}
        signal["indicators"] = {"ema_cross": True, "volume_confirmed": True}
        signal["regime_adjustment"] = {
            "original_confidence": 0.72,
            "multiplier": 1.0,
            "adjusted_confidence": 0.72,
        }
        sm.save_signal(signal)
        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 1


# ---------------------------------------------------------------------------
# Failure-path integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFailurePaths:
    """Verify the pipeline handles edge cases and failures gracefully."""

    def test_malformed_signal_input_handled_gracefully(self, tmp_path: Path):
        """A signal dict missing required fields (type, direction) must not
        crash the pipeline and should still be persisted."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        # Signal with no type, no direction -- only minimal fields
        malformed: Dict = {
            "entry_price": 17500.0,
            "confidence": 0.55,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        sm.save_signal(malformed)  # must not raise

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 1
        inner = recent[0].get("signal", recent[0])
        # Missing fields should fall back to defaults, not crash
        assert inner.get("entry_price") == 17500.0
        assert inner.get("confidence") == 0.55

    def test_state_persistence_failure_does_not_lose_data(self, tmp_path: Path):
        """If state.json write fails (I/O error), previously saved signals
        must remain accessible from the signals file."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        signal = _make_signal()
        sm.save_signal(signal)

        # Verify signal exists before the failure
        assert len(sm.get_recent_signals(limit=10)) == 1

        # Mock atomic_write_json to simulate an I/O failure during state save
        with patch(
            "pearlalgo.market_agent.state_manager.atomic_write_json",
            side_effect=OSError("disk full"),
        ):
            sm.save_state({"signal_count": 1})  # should not propagate

        # Signal must still be accessible despite state-save failure
        sm.invalidate_signals_cache()
        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 1
        inner = recent[0].get("signal", recent[0])
        assert inner.get("direction") == "long"

    def test_concurrent_signal_writes_no_corruption(self, tmp_path: Path):
        """Writing signals from multiple threads must not lose data or
        corrupt the signals file."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        n_threads = 8
        signals_per_thread = 5
        errors: list = []

        def _writer(thread_idx: int) -> None:
            try:
                for j in range(signals_per_thread):
                    sig = _make_signal(entry=17600.0 + thread_idx * 100 + j)
                    sm.save_signal(sig)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_writer, args=(i,))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

        # Invalidate cache and re-read from disk
        sm.invalidate_signals_cache()
        recent = sm.get_recent_signals(limit=200)
        expected = n_threads * signals_per_thread
        assert len(recent) == expected, (
            f"Expected {expected} signals, got {len(recent)}"
        )

    def test_corrupt_signals_file_recovery(self, tmp_path: Path):
        """Valid signals written before corruption must survive; corrupt
        lines are silently skipped."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        # Write 3 valid signals
        for i in range(3):
            sm.save_signal(_make_signal(entry=17600.0 + i))

        sm.invalidate_signals_cache()
        assert len(sm.get_recent_signals(limit=10)) == 3

        # Corrupt the file by appending garbage lines
        signals_file = tmp_path / "signals.jsonl"
        with open(signals_file, "a") as f:
            f.write("{{{CORRUPTED LINE\n")
            f.write("not json at all\n")
            f.write("\x00\x01\x02 binary garbage\n")

        # Invalidate cache so the reader re-reads the file
        sm.invalidate_signals_cache()
        recent = sm.get_recent_signals(limit=100)

        # The 3 valid signals must still be recoverable
        assert len(recent) == 3
        prices = sorted(
            r.get("signal", r).get("entry_price", 0) for r in recent
        )
        assert prices == [17600.0, 17601.0, 17602.0]

    def test_signal_to_exit_pipeline(self, tmp_path: Path):
        """Full lifecycle: generate signal -> track entry -> track exit ->
        verify performance metrics are consistent."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        # 1. Generate signal
        entry_price = 17600.0
        exit_price = 17630.0
        signal = _make_signal(entry=entry_price, direction="long")
        sm.save_signal(signal)

        recent_signals = sm.get_recent_signals(limit=10)
        assert len(recent_signals) == 1
        signal_record = recent_signals[0]
        signal_id = signal_record["signal_id"]

        # 2. Track entry
        sm.append_event("trade_entry", {
            "signal_id": signal_id,
            "direction": "long",
            "entry_price": entry_price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 3. Track exit
        pnl = exit_price - entry_price  # 30.0 for a long trade
        sm.append_event("trade_exit", {
            "signal_id": signal_id,
            "direction": "long",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 4. Verify events
        events = sm.get_recent_events(limit=10)
        assert len(events) == 2

        entry_event = events[0]
        exit_event = events[1]

        assert entry_event["type"] == "trade_entry"
        assert entry_event["payload"]["signal_id"] == signal_id
        assert entry_event["payload"]["entry_price"] == entry_price

        assert exit_event["type"] == "trade_exit"
        assert exit_event["payload"]["pnl"] == 30.0
        assert exit_event["payload"]["exit_price"] == exit_price

        # 5. Verify performance metrics are derivable
        assert exit_event["payload"]["exit_price"] > exit_event["payload"]["entry_price"]
        assert exit_event["payload"]["pnl"] == exit_price - entry_price

        # 6. Save state with performance summary and verify round-trip
        sm.save_state({
            "total_signals": 1,
            "total_trades": 1,
            "win_count": 1,
            "loss_count": 0,
            "total_pnl": pnl,
            "win_rate": 1.0,
        })
        loaded = sm.load_state()
        assert loaded["total_pnl"] == 30.0
        assert loaded["win_rate"] == 1.0
        assert loaded["win_count"] == 1
        assert loaded["loss_count"] == 0

    def test_signal_with_invalid_field_types(self, tmp_path: Path):
        """Signal fields with wrong types (str instead of float, list instead
        of str) must not crash save_signal; values are stored as-is."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        invalid_types_signal: Dict = {
            "direction": 12345,               # expected str
            "entry_price": "not_a_number",    # expected float
            "stop_loss": None,                # expected float
            "take_profit": [17630.0],         # expected float
            "confidence": {"value": 0.72},    # expected float
            "risk_reward": True,              # expected float
            "reason": 42,                     # expected str
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": "MNQ",
            "timeframe": "1m",
            "type": "pearlbot_pinescript",
            "virtual_broker": True,
        }
        sm.save_signal(invalid_types_signal)  # must not raise

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 1
        inner = recent[0].get("signal", recent[0])
        # Values should be preserved as-is, not coerced or dropped
        assert inner.get("entry_price") == "not_a_number"
        assert inner.get("direction") == 12345
        assert inner.get("confidence") == {"value": 0.72}
        assert inner.get("stop_loss") is None
        assert inner.get("take_profit") == [17630.0]
        assert inner.get("risk_reward") is True
        assert inner.get("reason") == 42

    def test_signal_save_io_failure_preserves_existing_data(self, tmp_path: Path):
        """If save_signal encounters an I/O error, previously persisted
        signals must remain intact on disk."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        # Persist one valid signal first
        sm.save_signal(_make_signal(entry=17600.0))
        assert len(sm.get_recent_signals(limit=10)) == 1

        # Force I/O error during the next save_signal by breaking open()
        with patch("builtins.open", side_effect=OSError("disk full")):
            try:
                sm.save_signal(_make_signal(entry=17601.0))
            except OSError:
                pass  # acceptable: error propagated

        # Original signal must survive the I/O failure
        sm.invalidate_signals_cache()
        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 1
        inner = recent[0].get("signal", recent[0])
        assert inner.get("entry_price") == 17600.0
        assert inner.get("direction") == "long"

    def test_concurrent_reads_and_writes_no_corruption(self, tmp_path: Path):
        """Interleaving get_recent_signals reads with save_signal writes
        from multiple threads must not raise or return corrupt data."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        n_writers = 4
        signals_per_writer = 5
        n_readers = 4
        reads_per_reader = 5
        errors: list = []

        def _writer(idx: int) -> None:
            try:
                for j in range(signals_per_writer):
                    sm.save_signal(_make_signal(entry=18000.0 + idx * 100 + j))
            except Exception as exc:
                errors.append(exc)

        def _reader() -> None:
            try:
                for _ in range(reads_per_reader):
                    result = sm.get_recent_signals(limit=100)
                    # Every returned record must be a well-formed dict
                    for r in result:
                        assert isinstance(r, dict), f"Expected dict, got {type(r)}"
            except Exception as exc:
                errors.append(exc)

        threads: list = []
        for i in range(n_writers):
            threads.append(threading.Thread(target=_writer, args=(i,)))
        for _ in range(n_readers):
            threads.append(threading.Thread(target=_reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

        sm.invalidate_signals_cache()
        recent = sm.get_recent_signals(limit=200)
        expected = n_writers * signals_per_writer
        assert len(recent) == expected, (
            f"Expected {expected} signals, got {len(recent)}"
        )

    def test_empty_signal_dict_persisted(self, tmp_path: Path):
        """An empty dict {} passed to save_signal must be accepted and
        persisted without crashing."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        sm.save_signal({})  # must not raise

        recent = sm.get_recent_signals(limit=10)
        assert len(recent) == 1
        # The record wraps the empty dict; inner signal has no domain fields
        inner = recent[0].get("signal", recent[0])
        assert inner.get("direction") is None
        assert inner.get("entry_price") is None
        # A signal_id must still have been auto-generated
        assert recent[0].get("signal_id") is not None
        assert recent[0]["signal_id"] != ""

    def test_none_signal_preserves_existing_data(self, tmp_path: Path):
        """Passing None to save_signal must not corrupt previously saved data.
        The method may raise or silently discard the None value."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        # Save one valid signal first
        sm.save_signal(_make_signal(entry=17700.0))
        assert len(sm.get_recent_signals(limit=10)) == 1

        # Attempt to save None -- may raise or be swallowed internally
        try:
            sm.save_signal(None)  # type: ignore[arg-type]
        except (TypeError, AttributeError, ValueError):
            pass  # acceptable: error propagated

        # The original valid signal must survive regardless
        sm.invalidate_signals_cache()
        recent = sm.get_recent_signals(limit=10)
        # None.get() raises AttributeError caught by outer try/except,
        # so no new record is added -- count stays at 1
        assert len(recent) == 1
        inner = recent[0].get("signal", recent[0])
        assert inner.get("entry_price") == 17700.0
        assert inner.get("direction") == "long"


# ---------------------------------------------------------------------------
# WS12: State persist-and-reload across manager instances
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStatePersistAndReload:
    """Verify state and signals persist across MarketAgentStateManager instances."""

    def test_state_survives_manager_recreation(self, tmp_path: Path):
        """Save state + signal with one manager, load them with a brand-new instance."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        # --- Write with first manager ---
        sm1 = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        state = {
            "signal_count": 42,
            "running": True,
            "win_rate": 0.65,
            "total_pnl": 1250.50,
        }
        sm1.save_state(state)

        signal = _make_signal(entry=17600.0, direction="long")
        sm1.save_signal(signal)

        # --- Create a brand-new manager for the same directory ---
        sm2 = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        # State must round-trip through a fresh instance
        loaded = sm2.load_state()
        assert loaded["signal_count"] == 42
        assert loaded["running"] is True
        assert loaded["win_rate"] == 0.65
        assert loaded["total_pnl"] == 1250.50
        assert "last_updated" in loaded

        # Signal must also survive across instances
        recent = sm2.get_recent_signals(limit=10)
        assert len(recent) == 1
        inner = recent[0].get("signal", recent[0])
        assert inner.get("direction") == "long"
        assert inner.get("entry_price") == 17600.0

    def test_events_survive_manager_recreation(self, tmp_path: Path):
        """Events persisted by one manager must be readable by a new instance."""
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm1 = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        sm1.append_event("trade_entry", {
            "signal_id": "test-001",
            "direction": "long",
            "entry_price": 17600.0,
        })
        sm1.append_event("trade_exit", {
            "signal_id": "test-001",
            "exit_price": 17630.0,
            "pnl": 30.0,
        })

        sm2 = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        events = sm2.get_recent_events(limit=10)
        assert len(events) == 2
        assert events[0]["type"] == "trade_entry"
        assert events[1]["type"] == "trade_exit"
        assert events[1]["payload"]["pnl"] == 30.0


# ---------------------------------------------------------------------------
# WS12: Full signal pipeline through SignalHandler
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSignalPipeline:
    """Verify the signal processing pipeline end-to-end via SignalHandler."""

    def test_process_signal_updates_counters(self, tmp_path: Path):
        """A valid signal should flow through the pipeline and update all counters."""
        import asyncio
        from unittest.mock import MagicMock, AsyncMock

        from pearlalgo.market_agent.signal_handler import SignalHandler
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        # Real state manager (persists to disk)
        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})

        # Mock performance tracker — returns a known signal_id
        perf_tracker = MagicMock()
        perf_tracker.track_signal_generated.return_value = "test-signal-id-001"
        perf_tracker.track_entry = MagicMock()

        # Mock notification queue — async enqueue returns True (success)
        notif_queue = MagicMock()
        notif_queue.enqueue_entry = AsyncMock(return_value=True)

        # Mock order manager
        order_manager = MagicMock()

        handler = SignalHandler(
            state_manager=sm,
            performance_tracker=perf_tracker,
            notification_queue=notif_queue,
            order_manager=order_manager,
        )

        # Pre-conditions
        assert handler.signal_count == 0
        assert handler.signals_sent == 0
        assert handler.error_count == 0

        signal = _make_signal(entry=17600.0, direction="long")
        asyncio.run(handler.process_signal(signal))

        # Post-conditions: signal was fully processed
        assert handler.signal_count == 1, "signal_count should be incremented"
        assert handler.signals_sent == 1, "signals_sent should be incremented"
        assert handler.error_count == 0, "no errors expected"
        assert handler.last_signal_generated_at is not None
        assert handler.last_signal_id_prefix == "test-signal-id-0"

        # Performance tracker should have been called
        perf_tracker.track_signal_generated.assert_called_once()
        perf_tracker.track_entry.assert_called_once()

        # Notification should have been queued
        notif_queue.enqueue_entry.assert_called_once()

    def test_process_signal_rejects_none_entry_price(self, tmp_path: Path):
        """A signal with None entry_price should be rejected (no crash, no counter bump)."""
        import asyncio
        from unittest.mock import MagicMock, AsyncMock

        from pearlalgo.market_agent.signal_handler import SignalHandler
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        sm = MarketAgentStateManager(state_dir=tmp_path, service_config={})
        perf_tracker = MagicMock()
        perf_tracker.track_signal_generated.return_value = "bad-signal-id"
        notif_queue = MagicMock()
        notif_queue.enqueue_entry = AsyncMock(return_value=True)
        order_manager = MagicMock()

        handler = SignalHandler(
            state_manager=sm,
            performance_tracker=perf_tracker,
            notification_queue=notif_queue,
            order_manager=order_manager,
        )

        signal = _make_signal(entry=17600.0, direction="long")
        signal["entry_price"] = None  # Invalid

        asyncio.run(handler.process_signal(signal))

        # Signal should be rejected: signal_count NOT incremented
        assert handler.signal_count == 0
        assert handler.error_count == 0  # rejection is not an error
        # Notification should NOT have been queued
        notif_queue.enqueue_entry.assert_not_called()


# ---------------------------------------------------------------------------
# WS12: Config-to-service startup via ServiceDependencies
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConfigToServiceStartup:
    """Verify ServiceDependencies resolves defaults and service can be constructed."""

    def test_service_dependencies_resolve_defaults(self, tmp_path: Path):
        """ServiceDependencies.resolve_defaults() should populate all core deps."""
        import asyncio
        from unittest.mock import MagicMock

        # asyncio.run() in earlier tests closes the main loop;
        # ib_insync/eventkit need one at import time on Python 3.12+.
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        from pearlalgo.config.config_view import ConfigView
        from pearlalgo.market_agent.service_factory import ServiceDependencies

        mock_provider = MagicMock()
        config = ConfigView({
            "symbol": "MNQ",
            "timeframe": "5m",
            "scan_interval": 30,
            "virtual_pnl_enabled": True,
        })

        deps = ServiceDependencies(
            data_provider=mock_provider,
            config=config,
            state_dir=tmp_path,
            service_config={"_test": True},  # non-empty to skip file load
        )
        deps.resolve_defaults()

        # All core dependencies should have been created
        assert deps.state_manager is not None
        assert deps.performance_tracker is not None
        assert deps.telegram_notifier is not None
        assert deps.notification_queue is not None
        assert deps.health_monitor is not None
        assert deps.data_fetcher is not None

        # State manager should point to the correct directory
        assert deps.state_manager.state_dir == tmp_path

    def test_market_agent_service_construction(self, tmp_path: Path):
        """MarketAgentService can be constructed from ServiceDependencies without errors."""
        import asyncio
        from unittest.mock import MagicMock

        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        from pearlalgo.config.config_view import ConfigView
        from pearlalgo.market_agent.service import MarketAgentService
        from pearlalgo.market_agent.service_factory import ServiceDependencies

        mock_provider = MagicMock()
        config = ConfigView({
            "symbol": "MNQ",
            "timeframe": "5m",
            "scan_interval": 30,
            "virtual_pnl_enabled": True,
        })

        deps = ServiceDependencies(
            data_provider=mock_provider,
            config=config,
            state_dir=tmp_path,
            service_config={"_test": True},
        )

        service = MarketAgentService(deps=deps)

        # Key attributes should be initialized
        assert service.symbol == "MNQ"
        assert service.timeframe == "5m"
        assert service.state_manager is not None
        assert service.performance_tracker is not None
        assert service.telegram_notifier is not None
        assert service.notification_queue is not None
        assert service.running is False
        assert service.signal_count >= 0
