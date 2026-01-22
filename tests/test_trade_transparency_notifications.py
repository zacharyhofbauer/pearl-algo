from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.market_agent.service import MarketAgentService
from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
from pearlalgo.config.config_loader import load_service_config
from pearlalgo.utils.telegram_alerts import format_home_card


class _DummyProvider(DataProvider):
    """Minimal DataProvider stub for service construction in unit tests."""

    def fetch_historical(self, symbol: str, start=None, end=None, timeframe: str | None = None) -> pd.DataFrame:
        return pd.DataFrame()


def test_config_loads_virtual_pnl_notify_flags(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "symbol: MNQ",
                "timeframe: 1m",
                "virtual_pnl:",
                "  enabled: true",
                "  intrabar_tiebreak: stop_loss",
                "  notify_entry: true",
                "  notify_exit: true",
                "",
            ]
        )
    )

    cfg = load_service_config()
    # Load config from file path if needed
    if cfg_path:
        from pearlalgo.config.config_file import load_config_yaml
        file_config = load_config_yaml(cfg_path)
        cfg.update(file_config)
    assert cfg.virtual_pnl_enabled is True
    assert cfg.virtual_pnl_notify_entry is True
    assert cfg.virtual_pnl_notify_exit is True


def test_home_card_active_trades_appends_unrealized_pnl_suffix() -> None:
    msg = format_home_card(
        symbol="MNQ",
        time_str="08:41 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        cycles_session=10,
        cycles_total=10,
        signals_generated=1,
        signals_sent=1,
        errors=0,
        buffer_size=100,
        buffer_target=100,
        latest_price=25702.25,
        active_trades_count=1,
        active_trades_unrealized_pnl=123.45,
        active_trades_price_source="level1",
    )

    assert "active trade" in msg
    assert "+$123.45" in msg

    msg_delayed = format_home_card(
        symbol="MNQ",
        time_str="08:41 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        cycles_session=10,
        cycles_total=10,
        signals_generated=1,
        signals_sent=1,
        errors=0,
        buffer_size=100,
        buffer_target=100,
        latest_price=25702.25,
        active_trades_count=1,
        active_trades_unrealized_pnl=-10.0,
        active_trades_price_source="historical",
    )
    assert "(delayed)" in msg_delayed


@pytest.mark.asyncio
async def test_entry_exit_notifications_disable_dedupe() -> None:
    notifier = MarketAgentTelegramNotifier(enabled=False)
    notifier.enabled = True
    notifier.chart_generator = None  # avoid chart generation in this unit test
    notifier.telegram = MagicMock()
    notifier.telegram.send_message = AsyncMock(return_value=True)

    ok_entry = await notifier.send_entry_notification(
        signal_id="test_signal_1",
        entry_price=25728.25,
        signal={"symbol": "MNQ", "direction": "short", "stop_loss": 25736.25, "take_profit": 25718.50},
        buffer_data=None,
    )
    assert ok_entry is True
    assert notifier.telegram.send_message.call_args.kwargs.get("dedupe") is False

    notifier.telegram.send_message.reset_mock()

    ok_exit = await notifier.send_exit_notification(
        signal_id="test_signal_1",
        exit_price=25718.50,
        exit_reason="take_profit",
        pnl=100.0,
        signal={"symbol": "MNQ", "direction": "short", "entry_price": 25728.25},
        hold_duration_minutes=1.0,
        buffer_data=None,
    )
    assert ok_exit is True
    assert notifier.telegram.send_message.call_args.kwargs.get("dedupe") is False


def test_virtual_exit_schedules_telegram_exit_notification(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Build service with virtual exit notifications enabled
    cfg = PEARL_BOT_CONFIG.copy()
    cfg.virtual_pnl_enabled = True
    cfg.virtual_pnl_notify_exit = True

    svc = MarketAgentService(
        data_provider=_DummyProvider(),
        config=cfg,
        state_dir=tmp_path,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )

    # Seed a single entered trade in signals.jsonl
    sig_id = "momentum_short_test_1"
    entered = {
        "signal_id": sig_id,
        "timestamp": "2025-12-30T13:31:03+00:00",
        "status": "entered",
        "signal": {
            "signal_id": sig_id,
            "symbol": "MNQ",
            "type": "momentum_short",
            "direction": "short",
            "entry_price": 25728.25,
            "stop_loss": 25736.25,
            "take_profit": 25718.50,
            "position_size": 15,
            "tick_value": 2.0,
        },
        "entry_time": "2025-12-30T13:31:03+00:00",
        "entry_price": 25728.25,
    }
    svc.state_manager.signals_file.parent.mkdir(parents=True, exist_ok=True)
    svc.state_manager.signals_file.write_text(json.dumps(entered) + "\n")

    # Mock the exit notifier and intercept create_task.
    svc.telegram_notifier.send_exit_notification = AsyncMock(return_value=True)
    scheduled = {"count": 0}

    def _fake_create_task(coro):
        scheduled["count"] += 1
        # Consume the coroutine to avoid "never awaited" warnings in unit tests.
        try:
            coro.close()
        except Exception:
            pass
        # Return a dummy object; the service doesn't interact with the task after scheduling.
        return MagicMock()

    monkeypatch.setattr("pearlalgo.market_agent.service.asyncio.create_task", _fake_create_task)

    # Market data bars: second bar hits TP for a short after entry_time.
    df = pd.DataFrame(
        {
            "timestamp": [
                "2025-12-30T13:31:00+00:00",
                "2025-12-30T13:32:00+00:00",
            ],
            "open": [25728.25, 25727.00],
            "high": [25730.00, 25729.00],
            "low": [25727.50, 25718.00],  # touches TP
            "close": [25727.00, 25718.50],
            "volume": [100, 100],
        }
    )
    svc._update_virtual_trade_exits({"df": df})

    assert scheduled["count"] == 1

