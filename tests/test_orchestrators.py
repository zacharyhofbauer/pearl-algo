from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from pearlalgo.market_agent.execution_orchestrator import ExecutionOrchestrator
from pearlalgo.market_agent.observability_orchestrator import ObservabilityOrchestrator
from pearlalgo.market_agent.signal_orchestrator import SignalOrchestrator


@pytest.mark.asyncio
async def test_signal_orchestrator_process_signals_delegates_to_handler() -> None:
    signal_handler = MagicMock()
    signal_handler.process_signal = AsyncMock(return_value=None)
    orchestrator = SignalOrchestrator(
        signal_handler=signal_handler,
        order_manager=MagicMock(),
        state_manager=MagicMock(),
    )

    callback = MagicMock()
    market_data = {"df": pd.DataFrame({"Close": [100.0, 101.0]})}
    processed = await orchestrator.process_signals(
        [{"type": "entry"}, {"type": "exit"}],
        market_data,
        sync_counters_callback=callback,
    )

    assert processed == 2
    assert signal_handler.process_signal.call_count == 2
    assert callback.call_count == 2


def test_execution_orchestrator_compute_position_size_delegates() -> None:
    order_manager = MagicMock()
    order_manager.compute_base_position_size.return_value = 3
    orchestrator = ExecutionOrchestrator(
        virtual_trade_manager=MagicMock(),
        order_manager=order_manager,
        state_manager=MagicMock(),
    )

    size = orchestrator.compute_position_size({"type": "pearlbot_pinescript"})

    assert size == 3
    order_manager.compute_base_position_size.assert_called_once()


def test_execution_orchestrator_active_virtual_trades_filters_entered() -> None:
    state_manager = MagicMock()
    state_manager.get_recent_signals.return_value = [
        {"signal_id": "a", "status": "entered"},
        {"signal_id": "b", "status": "generated"},
        {"signal_id": "c", "status": "entered"},
    ]
    orchestrator = ExecutionOrchestrator(
        virtual_trade_manager=MagicMock(),
        order_manager=MagicMock(),
        state_manager=state_manager,
    )

    trades = orchestrator.get_active_virtual_trades(limit=50)

    assert [trade["signal_id"] for trade in trades] == ["a", "c"]


def test_observability_orchestrator_daily_summary_includes_queue_status() -> None:
    performance_tracker = MagicMock()
    performance_tracker.get_daily_performance.return_value = {"wins": 2, "losses": 1}
    notification_queue = MagicMock()
    notification_queue.queue_size = 4
    telegram_notifier = MagicMock()
    telegram_notifier.enabled = True
    state_manager = MagicMock()
    state_manager.state_dir = Path("/tmp")

    orchestrator = ObservabilityOrchestrator(
        performance_tracker=performance_tracker,
        notification_queue=notification_queue,
        telegram_notifier=telegram_notifier,
        state_manager=state_manager,
    )

    summary = orchestrator.get_daily_summary()

    assert summary["performance"] == {"wins": 2, "losses": 1}
    assert summary["notifications"] == {"queue_size": 4, "telegram_enabled": True}


def test_observability_orchestrator_compute_quiet_period_minutes() -> None:
    orchestrator = ObservabilityOrchestrator(
        performance_tracker=MagicMock(),
        notification_queue=MagicMock(),
        telegram_notifier=MagicMock(),
        state_manager=MagicMock(),
    )

    quiet_period = orchestrator.compute_quiet_period_minutes(
        datetime.now(timezone.utc).replace(microsecond=0)
    )

    assert quiet_period is not None
    assert quiet_period >= 0.0
