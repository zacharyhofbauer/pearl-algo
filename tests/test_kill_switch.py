from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def api_server_module(monkeypatch, tmp_path):
    """
    Provide the FastAPI app module with side effects disabled.

    The API server starts a background WS broadcast loop on startup. In tests we
    patch that loop (and other startup init) to avoid hanging tasks.
    """
    # Avoid importing the API server module unless FastAPI/uvicorn exist.
    # The module calls sys.exit(1) on missing deps.
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")

    import scripts.pearlalgo_web_app.api_server as api_server

    async def _noop_broadcast_loop(*args, **kwargs):
        return None

    monkeypatch.setattr(api_server.ws_manager, "start_broadcast_loop", _noop_broadcast_loop)
    monkeypatch.setattr(api_server, "_init_auth", lambda: None)
    monkeypatch.setattr(api_server, "_init_pearl_ai", lambda: None)
    # Ensure operator lock does not interfere with API-key auth tests, even if
    # the local environment has PEARL_OPERATOR_PASSPHRASE set.
    monkeypatch.setattr(api_server, "_operator_passphrase", "")
    monkeypatch.setattr(api_server, "_operator_enabled", False)

    # Ensure the state dir is isolated per-test
    api_server._state_dir = tmp_path
    api_server._market = "NQ"

    return api_server


def test_kill_switch_endpoint_rejects_when_auth_disabled(api_server_module):
    from fastapi.testclient import TestClient

    api_server_module._auth_enabled = False
    api_server_module._api_keys = {"test-key"}

    with TestClient(api_server_module.app) as client:
        res = client.post("/api/kill-switch", headers={"X-API-Key": "test-key"})

    assert res.status_code == 403


def test_kill_switch_endpoint_writes_kill_flag(api_server_module):
    from fastapi.testclient import TestClient

    api_server_module._auth_enabled = True
    api_server_module._api_keys = {"test-key"}

    with TestClient(api_server_module.app) as client:
        res = client.post("/api/kill-switch", headers={"X-API-Key": "test-key"})

    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is True

    flag = api_server_module._state_dir / "kill_request.flag"
    assert flag.exists()
    assert "requested_at" in flag.read_text(encoding="utf-8")


def test_flatten_all_positions_task_places_offset_market_orders():
    from pearlalgo.execution.ibkr.tasks import FlattenAllPositionsTask
    from ib_insync import MarketOrder

    class DummyContract:
        def __init__(self, symbol: str, secType: str = "FUT", localSymbol: str = ""):
            self.symbol = symbol
            self.secType = secType
            self.localSymbol = localSymbol or symbol

    class DummyPosition:
        def __init__(self, contract, position: int, account: str = "TEST"):
            self.contract = contract
            self.position = position
            self.account = account

    ib = MagicMock()
    ib.sleep = MagicMock()

    fut1 = DummyPosition(DummyContract("MNQ"), position=3)
    fut2 = DummyPosition(DummyContract("ES"), position=-2)
    non_fut = DummyPosition(DummyContract("AAPL", secType="STK"), position=10)

    ib.positions.return_value = [fut1, fut2, non_fut]

    placed = []

    def _place(contract, order):
        placed.append((contract, order))
        trade = MagicMock()
        trade.order.orderId = 1000 + len(placed)
        return trade

    ib.placeOrder.side_effect = _place

    result = FlattenAllPositionsTask(task_id="t1").execute(ib)

    assert result["success"] is True
    assert result["total_flattened"] == 2
    assert len(placed) == 2

    # Long -> SELL qty
    assert isinstance(placed[0][1], MarketOrder)
    assert placed[0][1].action == "SELL"
    assert int(placed[0][1].totalQuantity) == 3

    # Short -> BUY qty
    assert isinstance(placed[1][1], MarketOrder)
    assert placed[1][1].action == "BUY"
    assert int(placed[1][1].totalQuantity) == 2


@pytest.mark.asyncio
async def test_telegram_confirm_kill_switch_writes_flag(monkeypatch, tmp_path):
    from pearlalgo.market_agent.telegram_command_handler import TelegramCommandHandler
    import pearlalgo.market_agent.telegram_command_handler as tch

    # Patch Telegram types so the test doesn't depend on python-telegram-bot internals.
    class MockInlineKeyboardButton:
        def __init__(self, text: str, callback_data: str | None = None, url: str | None = None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

    class MockInlineKeyboardMarkup:
        def __init__(self, keyboard: list):
            self.inline_keyboard = keyboard

    monkeypatch.setattr(tch, "InlineKeyboardButton", MockInlineKeyboardButton)
    monkeypatch.setattr(tch, "InlineKeyboardMarkup", MockInlineKeyboardMarkup)

    handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
    handler.state_dir = tmp_path
    handler.active_market = "NQ"
    handler._nav_back_row = lambda: [MockInlineKeyboardButton("🏠 Menu", callback_data="back")]

    query = MagicMock()
    query.edit_message_text = AsyncMock()

    await TelegramCommandHandler._handle_confirm_action(handler, query, "kill_switch")

    flag = tmp_path / "kill_request.flag"
    assert flag.exists()
    assert "requested_at=" in flag.read_text(encoding="utf-8")

