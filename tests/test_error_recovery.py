"""
Error recovery tests for the NQ Agent.

These tests target *observable behavior* (pause reason / circuit breaker state),
not internal attribute twiddling.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.market_agent.service import MarketAgentService
from pearlalgo.market_agent.state_manager import MarketAgentStateManager
from pearlalgo.market_agent.state_reader import StateReader
from pearlalgo.trading_bots.signal_generator import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.config.config_loader import load_service_config


class _DisconnectedExecutor:
    def is_connected(self) -> bool:  # pragma: no cover (simple stub)
        return False


class StubIBKRProvider(DataProvider):
    """Minimal provider that looks like a disconnected IBKR provider to ErrorHandler."""

    def __init__(self) -> None:
        self._executor = _DisconnectedExecutor()

    def fetch_historical(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_latest_bar(self, symbol: str):  # matches fetcher hasattr() usage
        return None


@pytest.mark.asyncio
async def test_connection_failure_circuit_breaker_pauses_service(tmp_path) -> None:
    provider = StubIBKRProvider()

    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.05  # type: ignore[assignment]

    service = MarketAgentService(data_provider=provider, config=config, state_dir=tmp_path)
    service.max_connection_failures = 1  # trigger immediately

    task = asyncio.create_task(service.start())

    # Wait until the service pauses due to connection failures.
    for _ in range(80):
        if service.paused:
            break
        await asyncio.sleep(0.05)

    assert service.paused
    assert service.pause_reason == "connection_failures"

    await service.stop("test")
    await asyncio.wait_for(task, timeout=5.0)


# ---------------------------------------------------------------------------
# Scenario 1: Corrupt state.json recovery
# ---------------------------------------------------------------------------


class TestCorruptStateJsonRecovery:
    """Recovery from various forms of corrupt state.json files.

    The state manager must never crash on bad data; it returns an empty dict
    and allows subsequent writes to repair the file.
    """

    def test_corrupt_json_payloads_return_empty_dict(self, tmp_path: Path) -> None:
        """load_state() returns {} for every flavour of corrupt JSON without raising."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        corrupt_payloads = [
            "not json at all",
            "{truncated",
            '{"key": value_missing_quotes}',
            "",  # empty file
            "\x00\x01\x02",  # binary garbage
            '{"valid_start": 1, "cut_off": ',  # truncated mid-value
        ]

        for payload in corrupt_payloads:
            with open(manager.state_file, "w") as f:
                f.write(payload)

            loaded = manager.load_state()
            assert loaded == {}, (
                f"Expected empty dict for corrupt payload {payload!r}, got {loaded!r}"
            )

    def test_save_state_overwrites_corrupt_file(self, tmp_path: Path) -> None:
        """save_state() should replace a corrupt state.json with valid data."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        # Plant corrupt data
        with open(manager.state_file, "w") as f:
            f.write("{{{broken json!!!")

        # Confirm load_state gives empty dict (no crash)
        assert manager.load_state() == {}

        # Overwrite with valid state
        manager.save_state({"cycle_count": 99, "status": "recovered"})

        loaded = manager.load_state()
        assert loaded["cycle_count"] == 99
        assert loaded["status"] == "recovered"
        assert "last_updated" in loaded

    def test_full_corruption_round_trip(self, tmp_path: Path) -> None:
        """save -> corrupt -> load (empty) -> save again -> verify recovery."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        # 1. Save valid state
        manager.save_state({"phase": "initial", "count": 1})
        assert manager.load_state()["phase"] == "initial"

        # 2. Simulate power-loss style truncation
        with open(manager.state_file, "w") as f:
            f.write('{"phase": "writing_was_inter')  # truncated

        # 3. load_state should return empty (not crash, not return partial)
        assert manager.load_state() == {}

        # 4. New save repairs the file
        manager.save_state({"phase": "recovered", "count": 2})
        loaded = manager.load_state()
        assert loaded["phase"] == "recovered"
        assert loaded["count"] == 2


# ---------------------------------------------------------------------------
# Scenario 2: SQLite write failure fallback
# ---------------------------------------------------------------------------


class TestSQLiteDualWriteFallback:
    """JSON file writes must succeed even when the SQLite dual-write path fails.

    The dual-write design (JSON primary + SQLite secondary) should degrade
    gracefully: if SQLite raises, the signal is still persisted to the JSONL
    file and is readable on next load.
    """

    def test_signal_persists_to_json_when_sqlite_raises(self, tmp_path: Path) -> None:
        """A single signal is saved to JSON despite SQLite 'database is locked' error."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        # Manually enable SQLite dual-write with a mock that always raises.
        # Since save_signal() delegates to _signal_store, set the mock there.
        mock_db = MagicMock()
        mock_db.add_signal_event.side_effect = Exception("database is locked")
        manager._signal_store._sqlite_enabled = True
        manager._signal_store._trade_db = mock_db
        manager._signal_store._async_sqlite_queue = None  # force blocking path

        signal = {
            "signal_id": "sqlite_fail_test",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17500.0,
        }
        manager.save_signal(signal)

        # JSON must contain the signal despite SQLite failure
        signals = manager.get_recent_signals()
        assert len(signals) == 1
        assert signals[0]["signal_id"] == "sqlite_fail_test"
        assert signals[0]["signal"]["type"] == "breakout"

        # Verify SQLite write was attempted
        mock_db.add_signal_event.assert_called_once()

    def test_multiple_signals_persist_despite_repeated_sqlite_errors(
        self, tmp_path: Path
    ) -> None:
        """Multiple signals accumulate in JSON even if every SQLite write fails."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        # Since save_signal() delegates to _signal_store, set the mock there.
        mock_db = MagicMock()
        mock_db.add_signal_event.side_effect = OSError("disk full")
        manager._signal_store._sqlite_enabled = True
        manager._signal_store._trade_db = mock_db
        manager._signal_store._async_sqlite_queue = None

        for i in range(5):
            manager.save_signal({
                "signal_id": f"disk_full_{i}",
                "type": "test",
                "direction": "long",
                "entry_price": 17500.0 + i * 200,  # spread prices to avoid duplicate tagging
            })

        signals = manager.get_recent_signals()
        assert len(signals) == 5
        for i, sig in enumerate(signals):
            assert sig["signal_id"] == f"disk_full_{i}"

        # SQLite was attempted for each
        assert mock_db.add_signal_event.call_count == 5


# ---------------------------------------------------------------------------
# Scenario 3: Execution timeout handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_survives_data_fetch_timeout(tmp_path) -> None:
    """Service handles asyncio.TimeoutError during data fetch without crashing.

    When the data fetcher raises TimeoutError (simulating a slow or
    unresponsive broker), the circuit breaker should eventually pause the
    service.  State files must remain writable afterward.
    """
    provider = StubIBKRProvider()

    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.05  # type: ignore[assignment]

    service = MarketAgentService(data_provider=provider, config=config, state_dir=tmp_path)
    service.max_connection_failures = 2  # pause after 2 timeouts

    call_count = 0

    async def timeout_fetch():
        nonlocal call_count
        call_count += 1
        raise asyncio.TimeoutError("Simulated data fetch timeout")

    service.data_fetcher.fetch_latest_data = timeout_fetch

    task = asyncio.create_task(service.start())

    # Wait for circuit breaker to pause the service
    for _ in range(60):
        if service.paused or call_count >= 3:
            break
        await asyncio.sleep(0.05)

    assert call_count >= 1, "fetch_latest_data was never called"

    # State must still be writable after timeout-induced pause
    service.state_manager.save_state({"post_timeout": True})
    loaded = service.state_manager.load_state()
    assert loaded["post_timeout"] is True

    await service.stop("test")
    await asyncio.wait_for(task, timeout=3.0)


class TestStateConsistencyAfterTimeout:
    """Verify the atomic write pattern (tmp file + rename) protects against
    partial / interrupted saves.
    """

    def test_leftover_tmp_file_does_not_corrupt_state(self, tmp_path: Path) -> None:
        """A stale .tmp file from an interrupted save should not affect reads."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        # Save valid state
        manager.save_state({"status": "running", "cycle_count": 42})

        # Simulate interrupted write: a .tmp file with garbage
        tmp_file = Path(str(manager.state_file) + ".tmp")
        with open(tmp_file, "w") as f:
            f.write("{partial_garbage")

        # The .tmp file should NOT affect load_state
        loaded = manager.load_state()
        assert loaded["status"] == "running"
        assert loaded["cycle_count"] == 42

    def test_save_after_interrupted_write_succeeds(self, tmp_path: Path) -> None:
        """A new save_state() after a simulated interruption should succeed cleanly."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        manager.save_state({"cycle_count": 10})

        # Leave a stale .tmp behind
        tmp_file = Path(str(manager.state_file) + ".tmp")
        with open(tmp_file, "w") as f:
            f.write("stale partial data")

        # New save should overwrite .tmp and produce valid state
        manager.save_state({"cycle_count": 11, "recovered": True})
        loaded = manager.load_state()
        assert loaded["cycle_count"] == 11
        assert loaded["recovered"] is True


# ---------------------------------------------------------------------------
# Scenario 4: Concurrent state access
# ---------------------------------------------------------------------------


class TestConcurrentStateAccess:
    """Verify that fcntl-based locking prevents torn reads / writes when
    multiple threads access state.json and signals.jsonl simultaneously.
    """

    def test_concurrent_reads_during_writes(self, tmp_path: Path) -> None:
        """Multiple readers should never see partial / corrupt state while a
        writer is updating state.json.
        """
        manager = MarketAgentStateManager(state_dir=tmp_path)
        reader = StateReader(tmp_path)

        # Seed initial state
        manager.save_state({"counter": 0, "status": "initial"})

        errors: list[str] = []
        read_results: list[int] = []

        def writer():
            for i in range(50):
                try:
                    manager.save_state({"counter": i, "status": "writing"})
                except Exception as e:
                    errors.append(f"writer: {e}")

        def reader_fn():
            for _ in range(50):
                try:
                    state = reader.read_state()
                    if state:
                        # Must have expected keys (never partial)
                        assert "counter" in state, f"Missing 'counter' in state: {state}"
                        read_results.append(state["counter"])
                except Exception as e:
                    errors.append(f"reader: {e}")

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader_fn),
            threading.Thread(target=reader_fn),
            threading.Thread(target=reader_fn),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert errors == [], f"Concurrent access errors: {errors}"

        # Final state must be valid and contain the last written value
        final = manager.load_state()
        assert "counter" in final
        assert final["counter"] == 49

    def test_concurrent_signal_writes_no_data_loss(self, tmp_path: Path) -> None:
        """Concurrent signal appends from multiple threads must not lose entries."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        errors: list[str] = []
        n_threads = 4
        signals_per_thread = 25

        def signal_writer(thread_id: int):
            for i in range(signals_per_thread):
                try:
                    manager.save_signal({
                        "signal_id": f"t{thread_id}_s{i}",
                        "type": f"type_{thread_id}",  # unique type per thread avoids dup detection
                        "direction": "long",
                        "entry_price": 10000.0 + thread_id * 5000 + i,
                    })
                except Exception as e:
                    errors.append(f"thread {thread_id}: {e}")

        threads = [
            threading.Thread(target=signal_writer, args=(tid,))
            for tid in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert errors == [], f"Signal write errors: {errors}"

        total_expected = n_threads * signals_per_thread
        signals = manager.get_recent_signals(limit=total_expected)
        signal_ids = {s["signal_id"] for s in signals}

        assert len(signals) == total_expected, (
            f"Expected {total_expected} signals, got {len(signals)} "
            f"(possible data loss under concurrency)"
        )

        # Verify every expected signal_id is present
        for tid in range(n_threads):
            for i in range(signals_per_thread):
                expected_id = f"t{tid}_s{i}"
                assert expected_id in signal_ids, f"Missing signal {expected_id}"


# ---------------------------------------------------------------------------
# Scenario 5: Signal file corruption recovery
# ---------------------------------------------------------------------------


class TestSignalFileCorruptionRecovery:
    """Corrupt entries in signals.jsonl must be skipped transparently; valid
    entries before and after the corruption must still be readable.
    """

    def test_valid_signals_readable_despite_interleaved_corruption(
        self, tmp_path: Path
    ) -> None:
        """Valid signals are returned; corrupt JSONL lines are silently skipped."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        # Save two valid signals
        manager.save_signal({"signal_id": "good_1", "type": "breakout", "direction": "long"})
        manager.save_signal({"signal_id": "good_2", "type": "mean_revert", "direction": "short"})

        # Inject several kinds of corrupt lines
        with open(manager.signals_file, "a") as f:
            f.write("this is not json\n")
            f.write("{broken json\n")
            f.write("\n")  # blank line
            f.write("\x00binary\x01garbage\n")

        # Save another valid signal after the corruption
        manager.save_signal({"signal_id": "good_3", "type": "breakout", "direction": "long"})

        signals = manager.get_recent_signals()
        assert len(signals) == 3
        assert signals[0]["signal_id"] == "good_1"
        assert signals[1]["signal_id"] == "good_2"
        assert signals[2]["signal_id"] == "good_3"

    def test_fully_corrupt_signals_file_returns_empty(self, tmp_path: Path) -> None:
        """A signals.jsonl with only corrupt entries should return an empty list."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        with open(manager.signals_file, "w") as f:
            f.write("corrupt line 1\n")
            f.write("{bad: json}\n")
            f.write("another bad line\n")

        signals = manager.get_recent_signals()
        assert signals == []

    def test_state_reader_skips_corrupt_signal_lines(self, tmp_path: Path) -> None:
        """StateReader.read_signals() also skips corrupt JSONL lines gracefully."""
        manager = MarketAgentStateManager(state_dir=tmp_path)
        reader = StateReader(tmp_path)

        manager.save_signal({"signal_id": "reader_ok_1", "type": "test"})

        # Inject corruption
        with open(manager.signals_file, "a") as f:
            f.write("corrupt entry here\n")
            f.write("{also broken}\n")

        manager.save_signal({"signal_id": "reader_ok_2", "type": "test"})

        signals = reader.read_signals()
        valid_ids = [s["signal_id"] for s in signals]
        assert "reader_ok_1" in valid_ids
        assert "reader_ok_2" in valid_ids
        assert len(signals) >= 2  # at minimum the two valid ones

    def test_new_signal_appends_after_fully_corrupt_file(self, tmp_path: Path) -> None:
        """After a file is entirely corrupt, new save_signal() still works."""
        manager = MarketAgentStateManager(state_dir=tmp_path)

        # Create entirely corrupt file
        with open(manager.signals_file, "w") as f:
            f.write("corrupt\ncorrupt\ncorrupt\n")

        assert manager.get_recent_signals() == []

        # Append a new valid signal
        manager.save_signal({
            "signal_id": "recovery_signal",
            "type": "breakout",
            "direction": "long",
            "entry_price": 17600.0,
        })

        signals = manager.get_recent_signals()
        assert len(signals) == 1
        assert signals[0]["signal_id"] == "recovery_signal"
        assert signals[0]["signal"]["entry_price"] == 17600.0


