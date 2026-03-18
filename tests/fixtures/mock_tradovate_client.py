"""
Shared mock TradovateClient fixture for execution layer tests.

Provides a configurable AsyncMock TradovateClient that can be injected
into TradovateExecutionAdapter for deterministic testing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock
from typing import Any, Dict, List, Optional

import pytest

from pearlalgo.execution.base import ExecutionConfig, ExecutionMode
from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
from pearlalgo.execution.tradovate.config import TradovateConfig


def make_mock_client(
    *,
    authenticated: bool = True,
    ws_connected: bool = False,
    account_name: str = "DEMO0001",
    account_id: int = 12345,
    positions: Optional[List[Dict[str, Any]]] = None,
    place_oso_result: Optional[Dict[str, Any]] = None,
    fills: Optional[List[Dict[str, Any]]] = None,
    orders: Optional[List[Dict[str, Any]]] = None,
    cash_snapshot: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """
    Create a fully-mocked TradovateClient with configurable responses.

    Args:
        authenticated: Whether is_authenticated returns True.
        ws_connected: Whether ws_connected returns True.
        account_name: Mock account name.
        account_id: Mock account ID.
        positions: Return value for get_positions().
        place_oso_result: Return value for place_oso().
        fills: Return value for get_fills().
        orders: Return value for get_orders().
        cash_snapshot: Return value for get_cash_balance_snapshot().
    """
    client = MagicMock()
    client.is_authenticated = authenticated
    client.ws_connected = ws_connected
    client.account_name = account_name
    client.account_id = account_id

    # Async methods
    client.connect = AsyncMock(return_value=True)
    client.disconnect = AsyncMock()
    client.resolve_front_month = AsyncMock(return_value="MNQM6")
    client.find_contract = AsyncMock(return_value={"id": 999, "name": "MNQM6"})
    client.start_websocket = AsyncMock()
    client.add_event_handler = MagicMock()

    client.place_oso = AsyncMock(return_value=place_oso_result or {"orderId": 42})
    client.place_order = AsyncMock(return_value={"orderId": 100})
    client.cancel_order = AsyncMock(return_value={"orderId": 42})
    client.modify_order = AsyncMock(return_value={"orderId": 42})
    client.get_positions = AsyncMock(return_value=positions or [])
    client.get_orders = AsyncMock(return_value=orders or [])
    client.get_fills = AsyncMock(return_value=fills or [])
    client.liquidate_all_positions = AsyncMock(
        return_value={"positions_liquidated": 0}
    )
    client.get_cash_balance_snapshot = AsyncMock(
        return_value=cash_snapshot or {
            "netLiq": 50000.0,
            "totalCashValue": 50000.0,
            "openPnL": 0.0,
            "realizedPnL": 0.0,
            "weekRealizedPnL": 0.0,
            "initialMargin": 0.0,
            "maintenanceMargin": 0.0,
        }
    )

    return client


def make_adapter(
    *,
    mode: str = "dry_run",
    armed: bool = False,
    enabled: bool = True,
    connected: bool = False,
    contract_symbol: Optional[str] = None,
    max_positions: int = 5,
    max_orders_per_day: int = 20,
    max_daily_loss: float = 500.0,
    cooldown_seconds: int = 0,
    allow_reversal: bool = True,
    client_kwargs: Optional[Dict[str, Any]] = None,
    **config_kw,
) -> TradovateExecutionAdapter:
    """
    Create a TradovateExecutionAdapter with mocked client for testing.

    Returns a fully configured adapter ready for test assertions.
    """
    exec_config = ExecutionConfig(
        enabled=enabled,
        armed=armed,
        mode=ExecutionMode(mode),
        symbol_whitelist=["MNQ"],
        max_positions=max_positions,
        max_orders_per_day=max_orders_per_day,
        max_daily_loss=max_daily_loss,
        cooldown_seconds=cooldown_seconds,
        allow_reversal_on_opposite_signal=allow_reversal,
        **config_kw,
    )
    tv_config = TradovateConfig(
        username="test", password="test", cid=1, sec="sec", env="demo",
    )
    adapter = TradovateExecutionAdapter(exec_config, tv_config)
    adapter._client = make_mock_client(**(client_kwargs or {}))
    adapter._connected = connected
    if contract_symbol:
        adapter._contract_symbol = contract_symbol

    return adapter


def make_signal(
    *,
    signal_id: str = "test_sig_1",
    direction: str = "long",
    entry_price: float = 18000.0,
    stop_loss: float = 17990.0,
    take_profit: float = 18020.0,
    position_size: int = 1,
    symbol: str = "MNQ",
    signal_type: str = "momentum_ema_cross",
    **overrides,
) -> Dict[str, Any]:
    """Build a minimal valid signal dict for execution tests."""
    sig = {
        "signal_id": signal_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_size": position_size,
        "type": signal_type,
    }
    sig.update(overrides)
    return sig


# ── Pytest fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_tv_client():
    """Fixture returning a fresh mock TradovateClient."""
    return make_mock_client()


@pytest.fixture
def dry_run_adapter():
    """Adapter in dry_run mode, armed, with mocked client."""
    return make_adapter(mode="dry_run", armed=True)


@pytest.fixture
def paper_adapter():
    """Adapter in paper mode, armed, connected, with contract symbol."""
    return make_adapter(
        mode="paper", armed=True, connected=True, contract_symbol="MNQM6",
    )


@pytest.fixture
def unarmed_adapter():
    """Adapter in paper mode, NOT armed."""
    return make_adapter(mode="paper", armed=False, connected=True)
