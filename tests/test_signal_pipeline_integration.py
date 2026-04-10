"""
Integration tests for the signal pipeline.

Tests the full flow: data fetch → signal generation → state persistence → performance tracking.

This validates that all components wire together correctly using real instances
(not mocks) of MarketAgentStateManager, PerformanceTracker, and MarketAgentDataFetcher,
backed by MockDataProvider and a temporary state directory.

Test Philosophy:
- Use real component instances, not unittest.mock patches
- Isolate via tmp_path so tests never touch production state
- Async tests use @pytest.mark.asyncio for data_fetcher calls
- Synthetic signals supplement strategy output when mock data doesn't trigger signals
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from pearlalgo.market_agent.performance_tracker import PerformanceTracker
from pearlalgo.market_agent.service import MarketAgentService
from pearlalgo.market_agent.signal_handler import SignalHandler
from pearlalgo.market_agent.state_manager import MarketAgentStateManager
from tests.mock_data_provider import MockDataProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    signal_type: str = "pearlbot_pinescript",
    direction: str = "long",
    entry_price: float = 17500.0,
    stop_loss: float = 17480.0,
    take_profit: float = 17550.0,
    confidence: float = 0.75,
) -> Dict:
    """Create a realistic test signal dictionary.

    Does NOT set ``_is_test=True`` so the signal will actually be persisted
    (production code skips persistence for test-flagged signals).
    """
    return {
        "type": signal_type,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "confidence": confidence,
        "symbol": "MNQ",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": f"Test {signal_type} signal",
    }


# ---------------------------------------------------------------------------
# Fixtures (standalone — don't depend on conftest.configured_service)
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Isolated state directory for each test."""
    d = tmp_path / "agent_state"
    d.mkdir()
    return d


@pytest.fixture
def state_manager(state_dir: Path) -> MarketAgentStateManager:
    """Real state manager backed by tmp_path (no SQLite, no config file)."""
    return MarketAgentStateManager(state_dir=state_dir, service_config={})


@pytest.fixture
def perf_tracker(
    state_dir: Path,
    state_manager: MarketAgentStateManager,
) -> PerformanceTracker:
    """Real performance tracker wired to state manager."""
    return PerformanceTracker(state_dir=state_dir, state_manager=state_manager)


# ---------------------------------------------------------------------------
# 1. Basic Pipeline
# ---------------------------------------------------------------------------


class TestBasicPipeline:
    """Integration: data fetch → signal generation → persist → verify."""

    @pytest.mark.asyncio
    async def test_full_pipeline_fetch_analyze_persist(
        self,
        configured_service: MarketAgentService,
        tmp_state_dir: Path,
    ) -> None:
        """
        Full pipeline using the ``configured_service`` fixture from conftest.

        Steps:
        1. Fetch market data via data_fetcher (async).
        2. Run strategy.analyze() to generate signals.
        3. Persist via performance_tracker.track_signal_generated().
        4. Verify signals.jsonl exists and state.json round-trips.
        """
        service = configured_service

        # --- Step 1: Fetch data ---
        market_data = await service.data_fetcher.fetch_latest_data()
        assert market_data is not None
        assert "df" in market_data
        assert "latest_bar" in market_data

        # --- Step 2: Analyze ---
        df = market_data.get("df")
        if df is not None and not df.empty:
            signals = service.strategy.analyze(df)
        else:
            signals = []

        # If the strategy didn't produce signals from mock data, inject a
        # synthetic one so we can still exercise the persistence path.
        if not signals:
            signals = [_make_signal()]

        # --- Step 3: Persist ---
        for signal in signals:
            signal_id = service.performance_tracker.track_signal_generated(signal)
            assert signal_id, "track_signal_generated must return a non-empty signal_id"

        # --- Step 4: Verify ---
        assert service.state_manager.signals_file.exists(), (
            "signals.jsonl should be created after persisting signals"
        )

        service.state_manager.save_state({
            "cycle_count": 1,
            "signal_count": len(signals),
            "running": True,
        })
        assert service.state_manager.state_file.exists(), (
            "state.json should exist after save_state()"
        )

        loaded = service.state_manager.load_state()
        assert loaded["cycle_count"] == 1
        assert loaded["signal_count"] == len(signals)
        assert "last_updated" in loaded

    @pytest.mark.asyncio
    async def test_data_fetch_returns_expected_structure(
        self,
        configured_service: MarketAgentService,
    ) -> None:
        """Verify data_fetcher returns the expected dict shape."""
        market_data = await configured_service.data_fetcher.fetch_latest_data()

        assert isinstance(market_data, dict)
        assert isinstance(market_data["df"], pd.DataFrame)

        latest_bar = market_data["latest_bar"]
        if latest_bar is not None:
            assert isinstance(latest_bar, dict)
            for key in ("open", "high", "low", "close", "volume"):
                assert key in latest_bar, f"latest_bar missing '{key}'"


# ---------------------------------------------------------------------------
# 2. Empty / Missing Data
# ---------------------------------------------------------------------------


class TestEmptyDataHandling:
    """Pipeline behavior when data is empty or unavailable."""

    @pytest.mark.asyncio
    async def test_empty_data_no_crash(self, state_dir: Path) -> None:
        """
        Components must handle empty DataFrames without crashing.

        Neither signals.jsonl nor state.json should be corrupted.
        """
        state_mgr = MarketAgentStateManager(state_dir=state_dir, service_config={})
        perf = PerformanceTracker(state_dir=state_dir, state_manager=state_mgr)

        # Simulate an analysis cycle that yielded no signals
        empty_df = pd.DataFrame()
        signals: list = []  # No signals from empty data

        # No signals saved → file should not exist (or be empty)
        recent = state_mgr.get_recent_signals()
        assert recent == []

        # State persistence still works
        state_mgr.save_state({"cycle_count": 0, "signal_count": 0})
        loaded = state_mgr.load_state()
        assert loaded["cycle_count"] == 0
        assert "last_updated" in loaded

    def test_no_signals_file_before_first_signal(self, state_dir: Path) -> None:
        """signals.jsonl should not exist until the first signal is saved."""
        state_mgr = MarketAgentStateManager(state_dir=state_dir, service_config={})

        assert not state_mgr.signals_file.exists()
        assert state_mgr.get_recent_signals() == []

    def test_state_json_absent_returns_empty_dict(self, state_dir: Path) -> None:
        """load_state() returns ``{}`` when state.json hasn't been written yet."""
        state_mgr = MarketAgentStateManager(state_dir=state_dir, service_config={})

        assert state_mgr.load_state() == {}


# ---------------------------------------------------------------------------
# 3. Signal Persistence Format
# ---------------------------------------------------------------------------


class TestSignalPersistenceFormat:
    """Verify that persisted signals follow the expected JSONL contract."""

    def test_each_line_is_valid_json(
        self,
        state_manager: MarketAgentStateManager,
        perf_tracker: PerformanceTracker,
    ) -> None:
        """Every line in signals.jsonl must be independently parseable JSON."""
        for i in range(5):
            signal = _make_signal(
                signal_type=f"type_{i}",
                direction="long" if i % 2 == 0 else "short",
                entry_price=17500.0 + i * 10,
            )
            perf_tracker.track_signal_generated(signal)

        assert state_manager.signals_file.exists()

        with open(state_manager.signals_file, "r") as f:
            lines = [line.strip() for line in f if line.strip()]

        assert len(lines) == 5, f"Expected 5 lines, got {len(lines)}"

        for idx, line in enumerate(lines):
            record = json.loads(line)  # Must not raise
            assert isinstance(record, dict), f"Line {idx} is not a JSON object"

    def test_record_has_required_keys(
        self,
        state_manager: MarketAgentStateManager,
        perf_tracker: PerformanceTracker,
    ) -> None:
        """
        Each signal record must contain: signal_id, timestamp, status, signal.

        This is the contract consumed by /signals command and Telegram UI.
        """
        perf_tracker.track_signal_generated(
            _make_signal(signal_type="pearlbot_pinescript", direction="long"),
        )

        records = state_manager.get_recent_signals()
        assert len(records) == 1

        record = records[0]
        for key in ("signal_id", "timestamp", "status", "signal"):
            assert key in record, f"Missing required key '{key}'"

        assert record["status"] == "generated"

        inner = record["signal"]
        assert inner["type"] == "pearlbot_pinescript"
        assert inner["direction"] == "long"
        assert isinstance(inner["entry_price"], (int, float))

    def test_signal_ids_are_unique(
        self,
        state_manager: MarketAgentStateManager,
        perf_tracker: PerformanceTracker,
    ) -> None:
        """Each persisted signal must receive a distinct signal_id."""
        ids: List[str] = []
        for i in range(10):
            sid = perf_tracker.track_signal_generated(
                _make_signal(entry_price=17500.0 + i),
            )
            ids.append(sid)

        assert len(set(ids)) == len(ids), "Duplicate signal_id detected"

    def test_timestamp_is_valid_iso8601(
        self,
        state_manager: MarketAgentStateManager,
        perf_tracker: PerformanceTracker,
    ) -> None:
        """Persisted timestamp must be valid ISO-8601 with timezone info."""
        perf_tracker.track_signal_generated(_make_signal())

        records = state_manager.get_recent_signals()
        ts_str = records[0]["timestamp"]

        parsed = datetime.fromisoformat(ts_str)
        assert parsed.tzinfo is not None, "Timestamp should include timezone"

    def test_nested_signal_dict_preserves_fields(
        self,
        state_manager: MarketAgentStateManager,
        perf_tracker: PerformanceTracker,
    ) -> None:
        """The nested ``signal`` dict must faithfully preserve all input fields."""
        original = _make_signal(
            signal_type="vwap_cross",
            direction="short",
            entry_price=18000.50,
            stop_loss=18020.0,
            take_profit=17950.0,
            confidence=0.82,
        )
        perf_tracker.track_signal_generated(original)

        records = state_manager.get_recent_signals()
        inner = records[0]["signal"]

        assert inner["type"] == "vwap_cross"
        assert inner["direction"] == "short"
        assert float(inner["entry_price"]) == 18000.50
        assert float(inner["stop_loss"]) == 18020.0
        assert float(inner["take_profit"]) == 17950.0
        assert float(inner["confidence"]) == pytest.approx(0.82)
        assert inner["symbol"] == "MNQ"


# ---------------------------------------------------------------------------
# 4. Multi-Cycle Accumulation
# ---------------------------------------------------------------------------


class TestMultiCycleAccumulation:
    """Verify that repeated pipeline cycles accumulate signals correctly."""

    @pytest.mark.asyncio
    async def test_signals_accumulate_across_cycles(
        self,
        configured_service: MarketAgentService,
    ) -> None:
        """
        Run 3 fetch→analyze→persist cycles; all signals must be retrievable.
        """
        service = configured_service
        total_signals = 0

        for cycle in range(3):
            market_data = await service.data_fetcher.fetch_latest_data()

            df = market_data.get("df")
            if df is not None and not df.empty:
                signals = service.strategy.analyze(df)
            else:
                signals = []

            # Guarantee at least one signal per cycle
            if not signals:
                signals = [
                    _make_signal(
                        signal_type=f"cycle_{cycle}_signal",
                        entry_price=17500.0 + cycle * 100,
                    ),
                ]

            for signal in signals:
                service.performance_tracker.track_signal_generated(signal)
                total_signals += 1

            service.state_manager.save_state({
                "cycle_count": cycle + 1,
                "signal_count": total_signals,
            })

        # All signals present
        all_signals = service.state_manager.get_recent_signals(limit=100)
        assert len(all_signals) == total_signals
        assert total_signals >= 3, "At least one signal per cycle"

        # State reflects last cycle
        state = service.state_manager.load_state()
        assert state["cycle_count"] == 3
        assert state["signal_count"] == total_signals

    @pytest.mark.asyncio
    async def test_state_json_updated_each_cycle(
        self,
        configured_service: MarketAgentService,
    ) -> None:
        """state.json must reflect the latest cycle count after each save."""
        service = configured_service

        for cycle in range(5):
            service.state_manager.save_state({"cycle_count": cycle + 1})
            loaded = service.state_manager.load_state()
            assert loaded["cycle_count"] == cycle + 1
            assert "last_updated" in loaded

    @pytest.mark.asyncio
    async def test_performance_tracker_ids_unique_across_cycles(
        self,
        configured_service: MarketAgentService,
    ) -> None:
        """signal_id assignment must remain unique across multiple cycles."""
        service = configured_service
        all_ids: List[str] = []

        for cycle in range(3):
            signal = _make_signal(
                signal_type=f"cycle_{cycle}",
                entry_price=17500.0 + cycle * 50,
            )
            signal_id = service.performance_tracker.track_signal_generated(signal)
            assert signal_id, f"Cycle {cycle}: signal_id should be non-empty"
            all_ids.append(signal_id)

        assert len(set(all_ids)) == 3, "All signal IDs must be unique"

        # Every ID should be retrievable from state_manager
        persisted = service.state_manager.get_recent_signals(limit=10)
        persisted_ids = {s["signal_id"] for s in persisted}
        for sid in all_ids:
            assert sid in persisted_ids, f"Signal {sid} not found in persisted signals"

    def test_many_signals_in_single_cycle(
        self,
        state_manager: MarketAgentStateManager,
        perf_tracker: PerformanceTracker,
    ) -> None:
        """
        A single cycle may produce multiple signals (e.g. breakout + reversal).

        All must be persisted and retrievable.
        """
        signals = [
            _make_signal(signal_type="pearlbot_pinescript", direction="long", entry_price=17500.0),
            _make_signal(signal_type="smc_fvg", direction="short", entry_price=17600.0),
            _make_signal(signal_type="smc_silver_bullet", direction="long", entry_price=17550.0),
        ]

        ids = []
        for sig in signals:
            sid = perf_tracker.track_signal_generated(sig)
            ids.append(sid)

        assert len(set(ids)) == 3

        persisted = state_manager.get_recent_signals(limit=10)
        assert len(persisted) == 3

        persisted_types = {r["signal"]["type"] for r in persisted}
        assert persisted_types == {"pearlbot_pinescript", "smc_fvg", "smc_silver_bullet"}


# ---------------------------------------------------------------------------
# 5. Signal → Execution Pipeline (mocked dependencies)
# ---------------------------------------------------------------------------


class TestSignalExecutionPipeline:
    """Integration: signal → execution adapter coordination via SignalHandler.

    Uses MagicMock/AsyncMock for infrastructure dependencies (execution adapter,
    notification queue, etc.) to isolate the SignalHandler pipeline logic.
    The actual SignalHandler.process_signal() is exercised end-to-end.
    """

    @staticmethod
    def _build_handler(
        *,
        execution_adapter=None,
        trading_circuit_breaker=None,
    ):
        """Build a SignalHandler with mocked infrastructure dependencies.

        Returns:
            Tuple of (handler, state_mgr_mock, perf_tracker_mock,
                       notif_queue_mock, order_mgr_mock).
        """
        state_mgr = MagicMock()
        state_mgr.get_recent_signals.return_value = []

        perf_tracker = MagicMock()
        perf_tracker.track_signal_generated.return_value = "test-signal-id-001"
        perf_tracker.track_entry.return_value = None

        notif_queue = AsyncMock()
        notif_queue.enqueue_entry.return_value = True
        notif_queue.enqueue_circuit_breaker.return_value = True

        order_mgr = MagicMock()

        handler = SignalHandler(
            state_manager=state_mgr,
            performance_tracker=perf_tracker,
            notification_queue=notif_queue,
            order_manager=order_mgr,
            execution_adapter=execution_adapter,
            trading_circuit_breaker=trading_circuit_breaker,
        )

        return handler, state_mgr, perf_tracker, notif_queue, order_mgr

    # -----------------------------------------------------------------------
    # 5a. Signal → Execution adapter called with correct parameters
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_check_preconditions_called_with_signal(self) -> None:
        """check_preconditions is invoked with the signal dict."""
        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = MagicMock(execute=True)
        mock_adapter.place_bracket = AsyncMock(
            return_value=MagicMock(success=True, parent_order_id="ORD-001"),
        )

        handler, *_ = self._build_handler(execution_adapter=mock_adapter)

        signal = _make_signal()
        signal["position_size"] = 1
        await handler.process_signal(signal)

        mock_adapter.check_preconditions.assert_called_once_with(signal)

    @pytest.mark.asyncio
    async def test_place_bracket_called_and_status_placed(self) -> None:
        """place_bracket is called with the signal and _execution_status set to 'placed'."""
        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = MagicMock(execute=True)
        mock_adapter.place_bracket = AsyncMock(
            return_value=MagicMock(success=True, parent_order_id="ORD-002"),
        )

        handler, *_ = self._build_handler(execution_adapter=mock_adapter)

        signal = _make_signal(
            signal_type="pearlbot_pinescript",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17550.0,
        )
        signal["position_size"] = 1
        await handler.process_signal(signal)

        mock_adapter.place_bracket.assert_called_once_with(signal)
        assert signal["_execution_status"] == "placed"

    # -----------------------------------------------------------------------
    # 5b. Signal → Precondition rejects → No execution
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_preconditions_reject_no_order_placed(self) -> None:
        """
        A rejecting precondition decision skips execution cleanly and no order
        is placed.
        """
        # Execution adapter mock → preconditions fail
        mock_adapter = MagicMock()
        mock_adapter.get_account_summary = AsyncMock(return_value={})
        mock_adapter.check_preconditions.return_value = MagicMock(
            execute=False, reason="preconditions_rejected",
        )
        mock_adapter.place_bracket = AsyncMock()

        handler, _, mock_perf, notif_queue, _ = self._build_handler(execution_adapter=mock_adapter)

        signal = _make_signal()
        signal["position_size"] = 1
        await handler.process_signal(signal)

        # No order was placed
        mock_adapter.place_bracket.assert_not_called()
        mock_perf.track_entry.assert_not_called()
        notif_queue.enqueue_entry.assert_not_awaited()

        # Execution status reflects the skip
        assert signal["_execution_status"] == "skipped:preconditions_rejected"

    # -----------------------------------------------------------------------
    # 5c. Signal → Circuit breaker blocks → No execution
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_skips_execution(self) -> None:
        """
        Circuit breaker returning allowed=False in enforce mode stops the
        pipeline before the execution adapter is ever consulted.
        """
        # Circuit breaker mock → blocks
        mock_cb = MagicMock()
        cb_decision = MagicMock()
        cb_decision.allowed = False
        cb_decision.reason = "max_consecutive_losses"
        cb_decision.severity = "warning"
        cb_decision.details = {"consecutive_losses": 5}
        cb_decision.to_dict.return_value = {
            "allowed": False,
            "reason": "max_consecutive_losses",
            "severity": "warning",
            "details": {"consecutive_losses": 5},
        }
        mock_cb.should_allow_signal.return_value = cb_decision
        mock_cb.config = MagicMock()
        mock_cb.config.mode = "enforce"

        # Execution adapter mock (should never be touched)
        mock_adapter = MagicMock()
        mock_adapter.place_bracket = AsyncMock()

        handler, *_ = self._build_handler(
            execution_adapter=mock_adapter,
            trading_circuit_breaker=mock_cb,
        )

        signal = _make_signal()
        signal["position_size"] = 1
        await handler.process_signal(signal)

        # Circuit breaker was consulted
        mock_cb.should_allow_signal.assert_called_once()

        # Execution adapter was NOT consulted (pipeline stopped early)
        mock_adapter.check_preconditions.assert_not_called()
        mock_adapter.place_bracket.assert_not_called()

        # Risk warnings attached to signal
        assert "_risk_warnings" in signal
        assert len(signal["_risk_warnings"]) == 1
        assert signal["_risk_warnings"][0]["reason"] == "max_consecutive_losses"

    # -----------------------------------------------------------------------
    # 5d. Signal → Execution succeeds → State updated
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_execution_success_updates_signal_state(self) -> None:
        """
        Successful execution sets ``_execution_status='placed'``,
        ``_execution_order_id``, and ``track_signal_generated`` is called.
        """
        mock_adapter = MagicMock()
        mock_adapter.check_preconditions.return_value = MagicMock(execute=True)
        mock_adapter.place_bracket = AsyncMock(
            return_value=MagicMock(
                success=True,
                parent_order_id="ORD-100",
                error_message=None,
            ),
        )

        handler, _, mock_perf, _, _ = self._build_handler(
            execution_adapter=mock_adapter,
        )

        signal = _make_signal(
            signal_type="pearlbot_pinescript",
            direction="long",
            entry_price=17500.0,
            stop_loss=17480.0,
            take_profit=17550.0,
        )
        signal["position_size"] = 1
        await handler.process_signal(signal)

        # Execution state
        assert signal["_execution_status"] == "placed"
        assert signal["_execution_order_id"] == "ORD-100"

        # Performance tracking was invoked
        mock_perf.track_signal_generated.assert_called_once()
        mock_perf.update_signal_execution_metadata.assert_called_once_with("test-signal-id-001", signal)
