"""
Tests for Tradovate execution components.

Covers:
- tradovate_fills_to_trades(): FIFO matching, PnL calculations, edge cases
- TradovateConfig: creation, URL properties, validation, from_env
- TradovateExecutionAdapter: initialization, lifecycle, dry-run, mocked client
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pearlalgo.execution.tradovate.utils import tradovate_fills_to_trades
from pearlalgo.execution.tradovate.config import TradovateConfig
from pearlalgo.execution.tradovate.adapter import TradovateExecutionAdapter
from pearlalgo.execution.base import (
    ExecutionConfig,
    ExecutionMode,
    OrderStatus,
)


# ═══════════════════════════════════════════════════════════════════════════
# tradovate_fills_to_trades  (FIFO matching — highest priority)
# ═══════════════════════════════════════════════════════════════════════════


class TestFillsToTradesEmpty:
    """Edge case: no fills or trivially empty input."""

    def test_empty_list_returns_empty(self):
        assert tradovate_fills_to_trades([]) == []

    def test_none_like_falsy_returns_empty(self):
        """Passing an empty-ish list still returns []."""
        assert tradovate_fills_to_trades(list()) == []


class TestFillsToTradesSingleRoundTrip:
    """A single buy followed by a single sell (simplest round-trip)."""

    def test_long_round_trip(self):
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "f1"},
            {"action": "Sell", "price": 18010.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "f2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 1
        t = trades[0]
        assert t["direction"] == "long"
        assert t["entry_price"] == 18000.0
        assert t["exit_price"] == 18010.0
        assert t["position_size"] == 1
        assert t["symbol"] == "MNQ"
        # PnL = (18010 - 18000) * 1 * $2 = $20
        assert t["pnl"] == 20.0
        assert t["exit_reason"] == "take_profit"
        assert t["entry_time"] == "2025-06-01T10:00:00Z"
        assert t["exit_time"] == "2025-06-01T10:05:00Z"

    def test_short_round_trip(self):
        fills = [
            {"action": "Sell", "price": 18050.0, "qty": 1, "timestamp": "2025-06-01T11:00:00Z", "id": "s1"},
            {"action": "Buy", "price": 18030.0, "qty": 1, "timestamp": "2025-06-01T11:05:00Z", "id": "s2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 1
        t = trades[0]
        assert t["direction"] == "short"
        assert t["entry_price"] == 18050.0
        assert t["exit_price"] == 18030.0
        # PnL = (18050 - 18030) * 1 * $2 = $40
        assert t["pnl"] == 40.0
        assert t["exit_reason"] == "take_profit"

    def test_long_losing_trade(self):
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "f1"},
            {"action": "Sell", "price": 17990.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "f2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 1
        # PnL = (17990 - 18000) * 1 * $2 = -$20
        assert trades[0]["pnl"] == -20.0
        assert trades[0]["exit_reason"] == "stop_loss"

    def test_short_losing_trade(self):
        fills = [
            {"action": "Sell", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "s1"},
            {"action": "Buy", "price": 18015.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "s2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 1
        # PnL = (18000 - 18015) * 1 * $2 = -$30
        assert trades[0]["pnl"] == -30.0
        assert trades[0]["exit_reason"] == "stop_loss"

    def test_breakeven_trade_classified_as_stop_loss(self):
        """PnL == 0 is not > 0, so exit_reason should be stop_loss."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "f1"},
            {"action": "Sell", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "f2"},
        ]
        trades = tradovate_fills_to_trades(fills)
        assert trades[0]["pnl"] == 0.0
        assert trades[0]["exit_reason"] == "stop_loss"


class TestFillsToTradesFIFO:
    """FIFO matching: multiple open lots closed in order."""

    def test_two_buys_one_sell_closes_first_buy(self):
        """Two buys at different prices, one sell should match the FIRST buy."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Buy", "price": 18005.0, "qty": 1, "timestamp": "2025-06-01T10:01:00Z", "id": "b2"},
            {"action": "Sell", "price": 18020.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 1
        # Should match b1 (FIFO), not b2
        assert trades[0]["entry_price"] == 18000.0
        assert trades[0]["exit_price"] == 18020.0
        # PnL = (18020 - 18000) * 1 * $2 = $40
        assert trades[0]["pnl"] == 40.0

    def test_two_buys_two_sells_fifo_order(self):
        """Two buys then two sells -> two trades matched in FIFO order."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Buy", "price": 18010.0, "qty": 1, "timestamp": "2025-06-01T10:01:00Z", "id": "b2"},
            {"action": "Sell", "price": 18020.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
            {"action": "Sell", "price": 18025.0, "qty": 1, "timestamp": "2025-06-01T10:06:00Z", "id": "s2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 2
        # First sell matches first buy (FIFO)
        assert trades[0]["entry_price"] == 18000.0
        assert trades[0]["exit_price"] == 18020.0
        assert trades[0]["pnl"] == 40.0  # (18020-18000)*1*2
        # Second sell matches second buy
        assert trades[1]["entry_price"] == 18010.0
        assert trades[1]["exit_price"] == 18025.0
        assert trades[1]["pnl"] == 30.0  # (18025-18010)*1*2

    def test_partial_close_splits_lot(self):
        """A single buy of qty=3, sold in two separate fills."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 3, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Sell", "price": 18010.0, "qty": 2, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
            {"action": "Sell", "price": 18020.0, "qty": 1, "timestamp": "2025-06-01T10:10:00Z", "id": "s2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 2
        # First sell closes 2 of 3 lots
        assert trades[0]["position_size"] == 2
        assert trades[0]["pnl"] == 40.0  # (18010-18000)*2*2
        # Second sell closes remaining 1 lot
        assert trades[1]["position_size"] == 1
        assert trades[1]["pnl"] == 40.0  # (18020-18000)*1*2

    def test_one_sell_closes_multiple_lots(self):
        """Multiple small buys closed by a single large sell."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Buy", "price": 18005.0, "qty": 1, "timestamp": "2025-06-01T10:01:00Z", "id": "b2"},
            {"action": "Buy", "price": 18010.0, "qty": 1, "timestamp": "2025-06-01T10:02:00Z", "id": "b3"},
            {"action": "Sell", "price": 18020.0, "qty": 3, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 3
        assert trades[0]["entry_price"] == 18000.0
        assert trades[0]["pnl"] == 40.0   # (18020-18000)*1*2
        assert trades[1]["entry_price"] == 18005.0
        assert trades[1]["pnl"] == 30.0   # (18020-18005)*1*2
        assert trades[2]["entry_price"] == 18010.0
        assert trades[2]["pnl"] == 20.0   # (18020-18010)*1*2

    def test_sell_larger_than_position_opens_opposite(self):
        """
        Buy 1, Sell 2 -> closes 1 lot (trade) + opens 1 short lot.
        Then Buy 1 closes that short lot.
        """
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Sell", "price": 18010.0, "qty": 2, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
            {"action": "Buy", "price": 18005.0, "qty": 1, "timestamp": "2025-06-01T10:10:00Z", "id": "b2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 2
        # Trade 1: long closed — buy@18000, sell@18010
        assert trades[0]["direction"] == "long"
        assert trades[0]["pnl"] == 20.0  # (18010-18000)*1*2

        # Trade 2: short opened from remaining sell, closed by buy@18005
        assert trades[1]["direction"] == "short"
        assert trades[1]["entry_price"] == 18010.0
        assert trades[1]["exit_price"] == 18005.0
        assert trades[1]["pnl"] == 10.0  # (18010-18005)*1*2


class TestFillsToTradesEdgeCases:
    """Edge cases and data quality scenarios."""

    def test_only_opening_fills_produces_no_trades(self):
        """All buys, no sells -> no completed trades."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Buy", "price": 18005.0, "qty": 1, "timestamp": "2025-06-01T10:01:00Z", "id": "b2"},
        ]
        trades = tradovate_fills_to_trades(fills)
        assert trades == []

    def test_fills_sorted_by_timestamp(self):
        """Fills provided out of order are sorted before processing."""
        fills = [
            {"action": "Sell", "price": 18010.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
        ]
        trades = tradovate_fills_to_trades(fills)

        # After sorting, Buy comes first, then Sell closes it
        assert len(trades) == 1
        assert trades[0]["direction"] == "long"
        assert trades[0]["entry_price"] == 18000.0
        assert trades[0]["exit_price"] == 18010.0

    def test_missing_fields_use_defaults(self):
        """Fills with missing optional fields still produce trades."""
        fills = [
            {"action": "Buy", "price": 18000.0},
            {"action": "Sell", "price": 18010.0},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 1
        assert trades[0]["position_size"] == 1  # default qty=1
        assert trades[0]["entry_time"] == ""
        assert trades[0]["exit_time"] == ""

    def test_signal_id_format(self):
        """signal_id is composed of tv_{entry_fill_id}_{exit_fill_id}."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "abc"},
            {"action": "Sell", "price": 18010.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "xyz"},
        ]
        trades = tradovate_fills_to_trades(fills)
        assert trades[0]["signal_id"] == "tv_abc_xyz"

    def test_large_multi_contract_pnl(self):
        """PnL calculation with multiple contracts: (exit-entry)*qty*POINT_VALUE."""
        fills = [
            {"action": "Buy", "price": 17500.0, "qty": 5, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Sell", "price": 17550.0, "qty": 5, "timestamp": "2025-06-01T10:30:00Z", "id": "s1"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 1
        # PnL = (17550 - 17500) * 5 * $2 = $500
        assert trades[0]["pnl"] == 500.0
        assert trades[0]["position_size"] == 5

    def test_pnl_rounding(self):
        """PnL is rounded to 2 decimal places."""
        fills = [
            {"action": "Buy", "price": 18000.25, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Sell", "price": 18003.50, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
        ]
        trades = tradovate_fills_to_trades(fills)
        # (18003.50 - 18000.25) * 1 * 2 = 6.50
        assert trades[0]["pnl"] == 6.5


class TestFillsToTradesMultipleRoundTrips:
    """Sequences of multiple complete round-trips."""

    def test_two_consecutive_long_round_trips(self):
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Sell", "price": 18010.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
            {"action": "Buy", "price": 18020.0, "qty": 1, "timestamp": "2025-06-01T10:10:00Z", "id": "b2"},
            {"action": "Sell", "price": 18025.0, "qty": 1, "timestamp": "2025-06-01T10:15:00Z", "id": "s2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 2
        assert trades[0]["pnl"] == 20.0   # (18010-18000)*1*2
        assert trades[1]["pnl"] == 10.0   # (18025-18020)*1*2

    def test_long_then_short_round_trips(self):
        """Close a long, then open and close a short."""
        fills = [
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:00:00Z", "id": "b1"},
            {"action": "Sell", "price": 18010.0, "qty": 1, "timestamp": "2025-06-01T10:05:00Z", "id": "s1"},
            {"action": "Sell", "price": 18008.0, "qty": 1, "timestamp": "2025-06-01T10:10:00Z", "id": "s2"},
            {"action": "Buy", "price": 18000.0, "qty": 1, "timestamp": "2025-06-01T10:15:00Z", "id": "b2"},
        ]
        trades = tradovate_fills_to_trades(fills)

        assert len(trades) == 2
        # Trade 1: long Buy@18000 -> Sell@18010
        assert trades[0]["direction"] == "long"
        assert trades[0]["pnl"] == 20.0
        # Trade 2: short Sell@18008 -> Buy@18000
        assert trades[1]["direction"] == "short"
        assert trades[1]["pnl"] == 16.0  # (18008-18000)*1*2


# ═══════════════════════════════════════════════════════════════════════════
# TradovateConfig
# ═══════════════════════════════════════════════════════════════════════════


class TestTradovateConfig:
    """TradovateConfig dataclass and derived properties."""

    def test_default_creation(self):
        cfg = TradovateConfig()
        assert cfg.username == ""
        assert cfg.password == ""
        assert cfg.app_id == "PearlAlgo"
        assert cfg.cid == 0
        assert cfg.env == "demo"
        assert cfg.token_renewal_seconds == 75 * 60

    def test_demo_urls(self):
        cfg = TradovateConfig(env="demo")
        assert "demo" in cfg.rest_url
        assert "demo" in cfg.ws_url
        assert cfg.rest_url == "https://demo.tradovateapi.com/v1"
        assert cfg.ws_url == "wss://demo.tradovateapi.com/v1/websocket"

    def test_live_urls(self):
        cfg = TradovateConfig(env="live")
        assert "live" in cfg.rest_url
        assert "live" in cfg.ws_url
        assert cfg.rest_url == "https://live.tradovateapi.com/v1"
        assert cfg.ws_url == "wss://live.tradovateapi.com/v1/websocket"

    def test_md_url_same_for_any_env(self):
        demo = TradovateConfig(env="demo")
        live = TradovateConfig(env="live")
        assert demo.md_url == live.md_url == "wss://md.tradovateapi.com/v1/websocket"

    def test_device_id_generated_automatically(self):
        cfg = TradovateConfig()
        assert cfg.device_id  # non-empty string
        assert isinstance(cfg.device_id, str)

    def test_account_name_defaults_to_none(self):
        cfg = TradovateConfig()
        assert cfg.account_name is None


class TestTradovateConfigValidation:
    """TradovateConfig.validate() checks required credentials."""

    def test_validate_all_missing(self):
        cfg = TradovateConfig()
        with pytest.raises(ValueError, match="Missing Tradovate credentials"):
            cfg.validate()

    def test_validate_partial_missing(self):
        cfg = TradovateConfig(username="user", password="pass")
        with pytest.raises(ValueError, match="TRADOVATE_CID"):
            cfg.validate()
        with pytest.raises(ValueError, match="TRADOVATE_SEC"):
            cfg.validate()

    def test_validate_passes_with_all_credentials(self):
        cfg = TradovateConfig(
            username="testuser",
            password="testpass",
            cid=1234,
            sec="my_secret",
        )
        cfg.validate()  # should not raise


class TestTradovateConfigFromEnv:
    """TradovateConfig.from_env() loads from environment variables."""

    def test_from_env_reads_variables(self):
        env = {
            "TRADOVATE_USERNAME": "envuser",
            "TRADOVATE_PASSWORD": "envpass",
            "TRADOVATE_CID": "99",
            "TRADOVATE_SEC": "envsec",
            "TRADOVATE_ENV": "live",
            "TRADOVATE_ACCOUNT_NAME": "LIVE123",
            "TRADOVATE_APP_ID": "TestApp",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = TradovateConfig.from_env()

        assert cfg.username == "envuser"
        assert cfg.password == "envpass"
        assert cfg.cid == 99
        assert cfg.sec == "envsec"
        assert cfg.env == "live"
        assert cfg.account_name == "LIVE123"
        assert cfg.app_id == "TestApp"

    def test_from_env_defaults_when_unset(self):
        env_keys = [
            "TRADOVATE_USERNAME", "TRADOVATE_PASSWORD", "TRADOVATE_CID",
            "TRADOVATE_SEC", "TRADOVATE_ENV", "TRADOVATE_ACCOUNT_NAME",
        ]
        cleaned = {k: v for k, v in os.environ.items() if k not in env_keys}
        with patch.dict(os.environ, cleaned, clear=True):
            cfg = TradovateConfig.from_env()

        assert cfg.username == ""
        assert cfg.env == "demo"
        assert cfg.cid == 0
        assert cfg.account_name is None


# ═══════════════════════════════════════════════════════════════════════════
# TradovateExecutionAdapter  (mock the TradovateClient)
# ═══════════════════════════════════════════════════════════════════════════


def _make_mock_client():
    """Create a fully-mocked TradovateClient with sensible defaults."""
    client = MagicMock()
    client.is_authenticated = True
    client.account_name = "DEMO0001"
    client.account_id = 12345

    # Async methods
    client.connect = AsyncMock(return_value=True)
    client.disconnect = AsyncMock()
    client.resolve_front_month = AsyncMock(return_value="MNQZ5")
    client.find_contract = AsyncMock(return_value={"id": 999, "name": "MNQZ5"})
    client.start_websocket = AsyncMock()
    client.add_event_handler = MagicMock()
    client.place_oso = AsyncMock(return_value={"orderId": 42})
    client.cancel_order = AsyncMock(return_value={"orderId": 42})
    client.get_positions = AsyncMock(return_value=[])
    client.liquidate_all_positions = AsyncMock(return_value={"positions_liquidated": 0})
    client.get_fills = AsyncMock(return_value=[])
    client.get_cash_balance_snapshot = AsyncMock(return_value={
        "netLiq": 50000.0,
        "totalCashValue": 50000.0,
    })
    return client


def _make_adapter(mode: str = "dry_run", armed: bool = False, **config_kw) -> TradovateExecutionAdapter:
    """Create a TradovateExecutionAdapter with mocked client."""
    exec_config = ExecutionConfig(
        enabled=True,
        armed=armed,
        mode=ExecutionMode(mode),
        symbol_whitelist=["MNQ"],
        **config_kw,
    )
    tv_config = TradovateConfig(
        username="test", password="test", cid=1, sec="sec", env="demo",
    )
    adapter = TradovateExecutionAdapter(exec_config, tv_config)
    adapter._client = _make_mock_client()
    return adapter


class TestAdapterInit:
    """Adapter construction and initial state."""

    def test_initializes_with_config(self):
        adapter = _make_adapter()
        assert adapter.config.enabled is True
        assert adapter._tv_config.env == "demo"
        assert adapter._connected is False

    def test_is_connected_false_before_connect(self):
        adapter = _make_adapter()
        assert adapter.is_connected() is False


class TestAdapterConnect:
    """Connection lifecycle with mocked client."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        adapter = _make_adapter()
        result = await adapter.connect()

        assert result is True
        assert adapter._connected is True
        assert adapter.is_connected() is True
        adapter._client.connect.assert_awaited_once()
        adapter._client.resolve_front_month.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_already_connected_is_noop(self):
        adapter = _make_adapter()
        adapter._connected = True

        result = await adapter.connect()
        assert result is True
        # Client.connect should NOT have been called again
        adapter._client.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_client_failure(self):
        adapter = _make_adapter()
        adapter._client.connect = AsyncMock(return_value=False)

        result = await adapter.connect()
        assert result is False
        assert adapter._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        adapter = _make_adapter()
        await adapter.connect()
        await adapter.disconnect()

        assert adapter._connected is False
        adapter._client.disconnect.assert_awaited_once()


class TestAdapterDryRun:
    """Dry-run mode should log but not hit the broker."""

    @pytest.mark.asyncio
    async def test_place_bracket_dry_run(self):
        adapter = _make_adapter(mode="dry_run", armed=True)
        signal = {
            "signal_id": "sig1",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }
        result = await adapter.place_bracket(signal)

        assert result.success is True
        assert result.status == OrderStatus.PLACED
        assert result.order_id.startswith("tv_dry_")
        # The real client should NOT have been called
        adapter._client.place_oso.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_order_dry_run(self):
        adapter = _make_adapter(mode="dry_run")
        result = await adapter.cancel_order("123")
        assert result.success is True
        assert result.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_all_dry_run(self):
        adapter = _make_adapter(mode="dry_run")
        results = await adapter.cancel_all()
        assert len(results) >= 1
        assert results[0].status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_flatten_all_dry_run(self):
        adapter = _make_adapter(mode="dry_run")
        results = await adapter.flatten_all_positions()
        assert len(results) == 1
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_get_positions_dry_run(self):
        adapter = _make_adapter(mode="dry_run")
        positions = await adapter.get_positions()
        assert positions == []


class TestAdapterPlaceBracketLive:
    """place_bracket in paper/live mode (mocked client)."""

    @pytest.mark.asyncio
    async def test_place_bracket_not_connected(self):
        adapter = _make_adapter(mode="paper", armed=True)
        adapter._connected = False
        adapter._client.is_authenticated = False

        signal = {
            "signal_id": "sig1",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }
        result = await adapter.place_bracket(signal)
        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "Not connected" in result.error_message

    @pytest.mark.asyncio
    async def test_place_bracket_not_armed(self):
        adapter = _make_adapter(mode="paper", armed=False)
        signal = {
            "signal_id": "sig1",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }
        result = await adapter.place_bracket(signal)
        assert result.success is False
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_place_bracket_success(self):
        adapter = _make_adapter(mode="paper", armed=True)
        adapter._connected = True
        adapter._contract_symbol = "MNQZ5"

        signal = {
            "signal_id": "sig1",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 2,
        }
        result = await adapter.place_bracket(signal)

        assert result.success is True
        assert result.status == OrderStatus.PLACED
        assert result.order_id == "42"

        adapter._client.place_oso.assert_awaited_once()
        call_kwargs = adapter._client.place_oso.call_args
        assert call_kwargs.kwargs["action"] == "Buy"
        assert call_kwargs.kwargs["order_qty"] == 2

    @pytest.mark.asyncio
    async def test_place_bracket_short_maps_to_sell(self):
        adapter = _make_adapter(mode="paper", armed=True)
        adapter._connected = True
        adapter._contract_symbol = "MNQZ5"

        signal = {
            "signal_id": "sig2",
            "symbol": "MNQ",
            "direction": "short",
            "entry_price": 18000.0,
            "stop_loss": 18020.0,
            "take_profit": 17980.0,
            "position_size": 1,
        }
        result = await adapter.place_bracket(signal)
        assert result.success is True
        call_kwargs = adapter._client.place_oso.call_args
        assert call_kwargs.kwargs["action"] == "Sell"

    @pytest.mark.asyncio
    async def test_place_bracket_api_error(self):
        from pearlalgo.execution.tradovate.client import TradovateAPIError

        adapter = _make_adapter(mode="paper", armed=True)
        adapter._connected = True
        adapter._contract_symbol = "MNQZ5"
        adapter._client.place_oso = AsyncMock(side_effect=TradovateAPIError("rate limit"))

        signal = {
            "signal_id": "sig3",
            "symbol": "MNQ",
            "direction": "long",
            "entry_price": 18000.0,
            "stop_loss": 17990.0,
            "take_profit": 18020.0,
            "position_size": 1,
        }
        result = await adapter.place_bracket(signal)
        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "rate limit" in result.error_message


class TestAdapterGetPositions:
    """get_positions with mocked client responses."""

    @pytest.mark.asyncio
    async def test_returns_non_zero_positions(self):
        adapter = _make_adapter(mode="paper")
        adapter._connected = True

        adapter._client.get_positions = AsyncMock(return_value=[
            {"contractId": 999, "netPos": 2, "netPrice": 18000.0},
            {"contractId": 888, "netPos": 0, "netPrice": 17500.0},  # flat — filtered
        ])

        positions = await adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 2
        assert positions[0].avg_price == 18000.0


class TestAdapterGetStatus:
    """get_status returns a telemetry-friendly dict."""

    def test_status_dict_keys(self):
        adapter = _make_adapter(mode="dry_run")
        adapter._connected = True
        status = adapter.get_status()

        assert status["adapter"] == "tradovate"
        assert status["connected"] is True
        assert status["env"] == "demo"
        assert status["mode"] == "dry_run"
        assert "orders_today" in status
        assert "open_orders" in status


class TestAdapterCancelOrder:
    """cancel_order in paper mode with mocked client."""

    @pytest.mark.asyncio
    async def test_cancel_order_success(self):
        adapter = _make_adapter(mode="paper")
        adapter._connected = True
        adapter._open_orders["77"] = {"signal_id": "x"}

        result = await adapter.cancel_order("77")
        assert result.success is True
        assert result.status == OrderStatus.CANCELLED
        assert "77" not in adapter._open_orders

    @pytest.mark.asyncio
    async def test_cancel_order_client_error(self):
        adapter = _make_adapter(mode="paper")
        adapter._connected = True
        adapter._client.cancel_order = AsyncMock(side_effect=Exception("network"))

        result = await adapter.cancel_order("77")
        assert result.success is False
        assert result.status == OrderStatus.ERROR


class TestAdapterFlattenAll:
    """flatten_all_positions in paper mode."""

    @pytest.mark.asyncio
    async def test_flatten_success(self):
        adapter = _make_adapter(mode="paper")
        adapter._connected = True

        results = await adapter.flatten_all_positions()
        assert len(results) == 1
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_flatten_not_connected(self):
        adapter = _make_adapter(mode="paper")
        adapter._connected = False
        adapter._client.is_authenticated = False

        results = await adapter.flatten_all_positions()
        assert results[0].success is False
        assert "Not connected" in results[0].error_message


class TestLivePositionsCache:
    """Tests for _live_positions updates from WebSocket events."""

    def test_position_event_updates_cache(self):
        adapter = _make_adapter(mode="paper")
        assert adapter._live_positions == {}

        # Simulate a position WS event
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "position",
                "entity": {
                    "contractId": 12345,
                    "netPos": 2,
                    "netPrice": 20050.0,
                    "openPnL": 25.0,
                    "timestamp": "2025-01-15T14:30:00Z",
                },
            },
        })

        assert "12345" in adapter._live_positions
        pos = adapter._live_positions["12345"]
        assert pos["net_pos"] == 2
        assert pos["net_price"] == 20050.0
        assert pos["open_pnl"] == 25.0

    def test_flat_position_removed_from_cache(self):
        adapter = _make_adapter(mode="paper")
        # Pre-populate
        adapter._live_positions["999"] = {"contract_id": "999", "net_pos": 1}

        # Simulate flat position (net_pos=0)
        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "position",
                "entity": {
                    "contractId": 999,
                    "netPos": 0,
                },
            },
        })

        assert "999" not in adapter._live_positions

    def test_order_event_removes_filled_order(self):
        adapter = _make_adapter(mode="paper")
        adapter._open_orders["555"] = {"signal_id": "test", "direction": "long"}

        adapter._handle_ws_event({
            "e": "props",
            "d": {
                "entityType": "order",
                "entity": {
                    "id": 555,
                    "ordStatus": "Filled",
                },
            },
        })

        assert "555" not in adapter._open_orders

    def test_orders_lock_exists(self):
        adapter = _make_adapter(mode="paper")
        import asyncio
        assert hasattr(adapter, "_orders_lock")
        assert isinstance(adapter._orders_lock, asyncio.Lock)
