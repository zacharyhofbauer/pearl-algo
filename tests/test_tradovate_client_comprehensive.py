"""Comprehensive tests for TradovateClient (~60 tests)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from pearlalgo.execution.tradovate.client import (
    TradovateClient,
    TradovateAPIError,
    TradovateAuthError,
)
from pearlalgo.execution.tradovate.config import TradovateConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**overrides) -> TradovateClient:
    defaults = dict(username="test", password="test", cid=1, sec="sec", env="demo")
    defaults.update(overrides)
    cfg = TradovateConfig(**defaults)
    return TradovateClient(cfg)


def _future(value):
    """Wrap a value in a completed future for awaitable returns."""
    f = asyncio.Future()
    f.set_result(value)
    return f


# ============================================================================
# TestTradovateClientInit
# ============================================================================

class TestTradovateClientInit:
    def test_initial_state(self):
        client = _make_client()
        assert client._access_token is None
        assert client._md_access_token is None
        assert client._user_id is None
        assert client._token_expiry is None
        assert client._account_id is None
        assert client._account_name is None
        assert client._session is None
        assert client._ws is None

    def test_properties_before_connect(self):
        client = _make_client()
        assert client.account_id is None
        assert client.account_name is None
        assert client.is_authenticated is False
        assert client.ws_connected is False

    def test_is_authenticated_false_no_token(self):
        client = _make_client()
        client._access_token = None
        client._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        assert client.is_authenticated is False

    def test_is_authenticated_expired_token(self):
        client = _make_client()
        client._access_token = "tok_abc"
        client._token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)
        assert client.is_authenticated is False


# ============================================================================
# TestAuthenticate
# ============================================================================

class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_authenticate_success(self):
        client = _make_client()
        client._post = AsyncMock(return_value={
            "accessToken": "tok_main",
            "mdAccessToken": "tok_md",
            "userId": 42,
            "expirationTime": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        await client._authenticate()
        assert client._access_token == "tok_main"
        assert client._md_access_token == "tok_md"
        assert client._user_id == 42

    @pytest.mark.asyncio
    async def test_authenticate_error_text_raises(self):
        client = _make_client()
        client._post = AsyncMock(return_value={
            "errorText": "Invalid credentials",
        })
        with pytest.raises(TradovateAuthError, match="Invalid credentials"):
            await client._authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_rate_limited(self):
        client = _make_client()
        client._post = AsyncMock(return_value={
            "errorText": "Rate limited",
            "p-ticket": "abc123",
            "p-time": 5,
            "p-captcha": False,
        })
        with pytest.raises(TradovateAuthError, match="[Rr]ate"):
            await client._authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_request_failure_raises(self):
        client = _make_client()
        client._post = AsyncMock(side_effect=TradovateAPIError("fail", 500, "err"))
        with pytest.raises((TradovateAPIError, TradovateAuthError)):
            await client._authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_sets_token_and_expiry(self):
        client = _make_client()
        future_dt = datetime.now(timezone.utc) + timedelta(hours=2)
        client._post = AsyncMock(return_value={
            "accessToken": "tok",
            "mdAccessToken": "md",
            "userId": 1,
            "expirationTime": future_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        })
        await client._authenticate()
        assert client._token_expiry is not None
        assert client._token_expiry > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_authenticate_fallback_expiry_on_bad_date(self):
        client = _make_client()
        client._post = AsyncMock(return_value={
            "accessToken": "tok",
            "mdAccessToken": "md",
            "userId": 1,
            "expirationTime": "not-a-date",
        })
        await client._authenticate()
        assert client._access_token == "tok"
        # Should have a fallback expiry set despite bad date
        assert client._token_expiry is not None


# ============================================================================
# TestTokenRenewal
# ============================================================================

class TestTokenRenewal:
    @pytest.mark.asyncio
    async def test_renew_token_success(self):
        client = _make_client()
        client._access_token = "old"
        client._post = AsyncMock(return_value={
            "accessToken": "renewed",
            "mdAccessToken": "md_renewed",
            "expirationTime": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        await client._renew_token()
        assert client._access_token == "renewed"

    @pytest.mark.asyncio
    async def test_renew_token_no_access_token_returns(self):
        client = _make_client()
        client._access_token = None
        client._post = AsyncMock()
        # Should return early without calling _post
        await client._renew_token()
        client._post.assert_not_called()

    @pytest.mark.asyncio
    async def test_renew_token_empty_result_reauthenticates(self):
        client = _make_client()
        client._access_token = "old"
        client._post = AsyncMock(return_value={})
        client._authenticate = AsyncMock()
        await client._renew_token()
        client._authenticate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_renew_token_failure_reauthenticates(self):
        client = _make_client()
        client._access_token = "old"
        client._post = AsyncMock(side_effect=Exception("renew failed"))
        client._authenticate = AsyncMock()
        await client._renew_token()
        client._authenticate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_renewal_loop_cancel(self):
        client = _make_client()
        client._access_token = "tok"
        client._renew_token = AsyncMock()

        task = asyncio.create_task(client._token_renewal_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        # The loop catches CancelledError internally and returns cleanly
        await task
        assert task.done()


# ============================================================================
# TestResolveAccount
# ============================================================================

class TestResolveAccount:
    @pytest.mark.asyncio
    async def test_resolve_specific_account_name(self):
        client = _make_client()
        client.config.account_name = "DEMO123"
        client._get = AsyncMock(return_value=[
            {"id": 1, "name": "DEMO000", "active": True},
            {"id": 2, "name": "DEMO123", "active": True},
        ])
        await client._resolve_account()
        assert client._account_id == 2
        assert client._account_name == "DEMO123"

    @pytest.mark.asyncio
    async def test_resolve_account_name_not_found_raises(self):
        client = _make_client()
        client.config.account_name = "MISSING"
        client._get = AsyncMock(return_value=[
            {"id": 1, "name": "DEMO000", "active": True},
        ])
        with pytest.raises((TradovateAuthError, TradovateAPIError, ValueError, KeyError)):
            await client._resolve_account()

    @pytest.mark.asyncio
    async def test_resolve_auto_selects_first_active(self):
        client = _make_client()
        client.config.account_name = None
        client._get = AsyncMock(return_value=[
            {"id": 1, "name": "INACTIVE", "active": False},
            {"id": 2, "name": "ACTIVE1", "active": True},
            {"id": 3, "name": "ACTIVE2", "active": True},
        ])
        await client._resolve_account()
        assert client._account_id == 2
        assert client._account_name == "ACTIVE1"

    @pytest.mark.asyncio
    async def test_resolve_fallback_to_first(self):
        client = _make_client()
        client.config.account_name = None
        client._get = AsyncMock(return_value=[
            {"id": 1, "name": "ONLY", "active": False},
        ])
        await client._resolve_account()
        assert client._account_id == 1
        assert client._account_name == "ONLY"

    @pytest.mark.asyncio
    async def test_resolve_no_accounts_raises(self):
        client = _make_client()
        client.config.account_name = None
        client._get = AsyncMock(return_value=[])
        with pytest.raises((TradovateAuthError, TradovateAPIError, ValueError, IndexError)):
            await client._resolve_account()


# ============================================================================
# TestRESTMethods
# ============================================================================

class TestRESTMethods:
    @pytest.mark.asyncio
    async def test_place_order_body_construction(self):
        client = _make_client()
        client._account_id = 100
        client._post = AsyncMock(return_value={"orderId": 1})
        await client.place_order("MNQH6", "Buy", 2)
        call_args = client._post.call_args
        body = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("body", call_args[0][1])
        assert body["symbol"] == "MNQH6"
        assert body["action"] == "Buy"
        assert body["orderQty"] == 2
        assert body["accountId"] == 100

    @pytest.mark.asyncio
    async def test_place_oso_bracket_construction(self):
        client = _make_client()
        client._account_id = 100
        client._post = AsyncMock(return_value={"orderId": 2})
        await client.place_oso("MNQH6", "Buy", 1, tp_price=20000.0, sl_price=19000.0)
        call_args = client._post.call_args
        body = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("body", call_args[0][1])
        assert body["symbol"] == "MNQH6"
        assert body["action"] == "Buy"
        assert body["orderQty"] == 1
        # Should have bracket / other orders
        assert "bracket1" in body or "other" in body or "brackets" in body or body.get("orderType") is not None

    @pytest.mark.asyncio
    async def test_place_oso_no_tp_no_sl(self):
        client = _make_client()
        client._account_id = 100
        client._post = AsyncMock(return_value={"orderId": 3})
        await client.place_oso("MNQH6", "Sell", 1, tp_price=None, sl_price=None)
        client._post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_modify_order_body_construction(self):
        client = _make_client()
        client._post = AsyncMock(return_value={"orderId": 10})
        await client.modify_order(order_id=10, price=20500.0, stop_price=None, order_qty=1)
        call_args = client._post.call_args
        body = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("body", call_args[0][1])
        assert body["orderId"] == 10
        assert body["price"] == 20500.0
        assert body["orderQty"] == 1

    @pytest.mark.asyncio
    async def test_cancel_order_body_construction(self):
        client = _make_client()
        client._post = AsyncMock(return_value={"orderId": 11})
        await client.cancel_order(order_id=11)
        call_args = client._post.call_args
        body = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("body", call_args[0][1])
        assert body["orderId"] == 11

    @pytest.mark.asyncio
    async def test_liquidate_all_positions_closes_nonzero(self):
        client = _make_client()
        client._account_id = 100
        client._account_name = "DEMO100"
        # liquidate_all_positions calls get_positions then place_order for each nonzero
        client.get_positions = AsyncMock(return_value=[
            {"id": 1, "accountId": 100, "netPos": 2, "contractId": 10},
            {"id": 2, "accountId": 100, "netPos": 0, "contractId": 11},
            {"id": 3, "accountId": 100, "netPos": -1, "contractId": 12},
        ])
        client.place_order = AsyncMock(return_value={"orderId": 1})
        result = await client.liquidate_all_positions()
        # Should liquidate only non-zero positions (id 1 and 3)
        assert client.place_order.await_count == 2
        assert result["positions_liquidated"] == 2

    @pytest.mark.asyncio
    async def test_liquidate_all_positions_empty(self):
        client = _make_client()
        client._account_id = 100
        client.get_positions = AsyncMock(return_value=[])
        result = await client.liquidate_all_positions()
        assert result["positions_liquidated"] == 0

    @pytest.mark.asyncio
    async def test_get_positions_url(self):
        client = _make_client()
        client._account_id = 100
        client._get = AsyncMock(return_value=[])
        await client.get_positions(account_id=100)
        url = client._get.call_args[0][0]
        assert "position" in url.lower()

    @pytest.mark.asyncio
    async def test_get_fills_url(self):
        client = _make_client()
        client._get = AsyncMock(return_value=[])
        await client.get_fills()
        url = client._get.call_args[0][0]
        assert "fill" in url.lower()

    @pytest.mark.asyncio
    async def test_get_orders_url(self):
        client = _make_client()
        client._get = AsyncMock(return_value=[])
        await client.get_orders()
        url = client._get.call_args[0][0]
        assert "order" in url.lower()


# ============================================================================
# TestResolveFrontMonth
# ============================================================================

class TestResolveFrontMonth:
    @pytest.mark.asyncio
    async def test_resolve_via_suggest(self):
        client = _make_client()
        client.suggest_contracts = AsyncMock(return_value=[
            {"name": "MNQM6", "contractMaturityDate": "2026-06-20"},
        ])
        client.roll_contract = AsyncMock()
        client.find_contract = AsyncMock()
        result = await client.resolve_front_month("MNQ")
        assert result == "MNQM6"
        client.roll_contract.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_suggest_fails_uses_roll(self):
        client = _make_client()
        client.suggest_contracts = AsyncMock(side_effect=Exception("suggest failed"))
        client.roll_contract = AsyncMock(return_value={"contract": {"name": "MNQM6"}})
        client.find_contract = AsyncMock()
        result = await client.resolve_front_month("MNQ")
        assert result == "MNQM6"

    @pytest.mark.asyncio
    async def test_resolve_roll_fails_uses_find(self):
        client = _make_client()
        client.suggest_contracts = AsyncMock(side_effect=Exception("fail"))
        client.roll_contract = AsyncMock(side_effect=Exception("fail"))
        client.find_contract = AsyncMock(return_value={"name": "MNQM6"})
        result = await client.resolve_front_month("MNQ")
        assert result == "MNQM6"

    @pytest.mark.asyncio
    async def test_resolve_all_fail_raises(self):
        client = _make_client()
        client.suggest_contracts = AsyncMock(side_effect=Exception("fail"))
        client.roll_contract = AsyncMock(side_effect=Exception("fail"))
        client.find_contract = AsyncMock(side_effect=Exception("fail"))
        with pytest.raises(Exception):
            await client.resolve_front_month("MNQ")

    @pytest.mark.asyncio
    async def test_resolve_suggest_empty_tries_roll(self):
        client = _make_client()
        client.suggest_contracts = AsyncMock(return_value=[])
        client.roll_contract = AsyncMock(return_value={"contract": {"name": "MNQU6"}})
        client.find_contract = AsyncMock()
        result = await client.resolve_front_month("MNQ")
        assert result == "MNQU6"
        client.roll_contract.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_returns_correct_symbol(self):
        client = _make_client()
        client.suggest_contracts = AsyncMock(return_value=[
            {"name": "ESM6", "contractMaturityDate": "2026-06-20"},
        ])
        result = await client.resolve_front_month("ES")
        assert result == "ESM6"


# ============================================================================
# TestHTTPHelpers
# ============================================================================

class TestHTTPHelpers:
    """Tests for _get, _post, and _handle_response.

    _handle_response uses ``await resp.text()`` then ``json.loads()``,
    NOT ``resp.json()``.  Mocks must set ``.text`` as an AsyncMock returning a string.
    """

    @pytest.mark.asyncio
    async def test_handle_response_429_raises(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status = 429
        mock_resp.text = AsyncMock(return_value="Rate limited")
        with pytest.raises(TradovateAPIError) as exc_info:
            await client._handle_response(mock_resp)
        assert exc_info.value.status == 429

    @pytest.mark.asyncio
    async def test_handle_response_400_raises(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value='{"errorText": "Bad request"}')
        with pytest.raises(TradovateAPIError) as exc_info:
            await client._handle_response(mock_resp)
        assert exc_info.value.status == 400

    @pytest.mark.asyncio
    async def test_handle_response_business_error(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value='{"errorText": "Business error"}')
        with pytest.raises(TradovateAPIError, match="Business error"):
            await client._handle_response(mock_resp)

    @pytest.mark.asyncio
    async def test_handle_response_success(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value='{"id": 1, "name": "test"}')
        result = await client._handle_response(mock_resp)
        assert result == {"id": 1, "name": "test"}

    @pytest.mark.asyncio
    async def test_handle_response_empty_body(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="")
        result = await client._handle_response(mock_resp)
        assert result == {}

    @pytest.mark.asyncio
    async def test_handle_response_non_json_body(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="not json at all")
        result = await client._handle_response(mock_resp)
        assert isinstance(result, dict)
        assert "raw" in result

    @pytest.mark.asyncio
    async def test_get_no_session_raises(self):
        client = _make_client()
        client._session = None
        with pytest.raises(TradovateAPIError, match="not connected"):
            await client._get("http://test.com/api")

    @pytest.mark.asyncio
    async def test_post_no_session_raises(self):
        client = _make_client()
        client._session = None
        with pytest.raises(TradovateAPIError, match="not connected"):
            await client._post("http://test.com/api", {"x": 1})


# ============================================================================
# TestWebSocket
# ============================================================================

class TestWebSocket:
    @pytest.mark.asyncio
    async def test_start_websocket_no_session_raises(self):
        client = _make_client()
        client._session = None
        with pytest.raises((RuntimeError, AttributeError, TradovateAPIError)):
            await client.start_websocket()

    def test_add_event_handler(self):
        """add_event_handler(handler) appends to flat list _event_handlers."""
        client = _make_client()

        def handler(data):
            pass

        client.add_event_handler(handler)
        assert handler in client._event_handlers
        assert len(client._event_handlers) == 1

    @pytest.mark.asyncio
    async def test_close_websocket(self):
        client = _make_client()
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.close = AsyncMock()
        client._ws = mock_ws
        client._ws_heartbeat_task = None
        client._ws_listener_task = None
        await client._close_websocket()
        mock_ws.close.assert_awaited_once()
        assert client._ws is None

    def test_ws_connected_property(self):
        """ws_connected is backed by _ws_connected bool."""
        client = _make_client()
        assert client.ws_connected is False
        client._ws_connected = True
        assert client.ws_connected is True
        client._ws_connected = False
        assert client.ws_connected is False

    def test_add_multiple_event_handlers(self):
        client = _make_client()

        def handler1(data):
            pass

        def handler2(data):
            pass

        client.add_event_handler(handler1)
        client.add_event_handler(handler2)
        assert len(client._event_handlers) == 2


# ============================================================================
# TestConnect
# ============================================================================

class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self):
        client = _make_client()

        async def _fake_authenticate():
            client._access_token = "tok"
            client._token_expiry = datetime.now(timezone.utc) + timedelta(hours=2)

        async def _fake_resolve():
            client._account_id = 100
            client._account_name = "DEMO100"

        client._authenticate = AsyncMock(side_effect=_fake_authenticate)
        client._resolve_account = AsyncMock(side_effect=_fake_resolve)

        with patch("aiohttp.ClientSession") as mock_cls:
            mock_session = MagicMock()
            mock_cls.return_value = mock_session
            result = await client.connect()

        assert result is True
        client._authenticate.assert_awaited_once()
        client._resolve_account.assert_awaited_once()
        # Clean up renewal task
        if client._renewal_task and not client._renewal_task.done():
            client._renewal_task.cancel()
            try:
                await client._renewal_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_connect_auth_fails(self):
        client = _make_client()
        client._authenticate = AsyncMock(side_effect=TradovateAuthError("bad creds"))

        with patch("aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = MagicMock()
            with pytest.raises(TradovateAuthError):
                await client.connect()

    @pytest.mark.asyncio
    async def test_connect_auth_returns_no_token(self):
        """If _authenticate succeeds but sets no token, connect returns False."""
        client = _make_client()
        client._authenticate = AsyncMock()  # doesn't set _access_token

        with patch("aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = await client.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_validates_config(self):
        cfg = TradovateConfig(username="", password="", cid=0, sec="", env="demo")
        client = TradovateClient(cfg)
        with pytest.raises(ValueError, match="[Mm]issing"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        client = _make_client()
        client._access_token = "tok"
        client._account_id = 100
        client._account_name = "DEMO"

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        client._session = mock_session
        client._renewal_task = None
        client._ws = None
        client._ws_heartbeat_task = None
        client._ws_listener_task = None

        await client.disconnect()
        assert client._access_token is None
        assert client._account_id is None
        assert client._session is None


# ============================================================================
# TestErrorClasses
# ============================================================================

class TestErrorClasses:
    def test_api_error_attributes(self):
        err = TradovateAPIError("something broke", 500, "internal server error")
        assert err.status == 500
        assert err.body == "internal server error"
        assert "something broke" in str(err)

    def test_auth_error_message(self):
        err = TradovateAuthError("invalid credentials")
        assert "invalid credentials" in str(err)
        assert isinstance(err, Exception)

    def test_api_error_status_and_body(self):
        err = TradovateAPIError("rate limited", 429, '{"error": "too many requests"}')
        assert err.status == 429
        assert "too many requests" in err.body
        assert isinstance(err, Exception)
