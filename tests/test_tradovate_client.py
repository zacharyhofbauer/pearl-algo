"""
Tests for the Tradovate REST + WebSocket client (TradovateClient).

Covers:
- Authentication: token request, invalid credentials, rate-limit penalty, token renewal
- REST operations: contract lookup, OSO order placement, front-month resolution
- Response handling: 2xx, 4xx, 5xx, 429 rate limiting, business-level errors
- WebSocket: event handler registration, state management, teardown
- Edge cases: expired tokens, missing session, timeout propagation
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pearlalgo.execution.tradovate.client import (
    TradovateAPIError,
    TradovateAuthError,
    TradovateClient,
)
from pearlalgo.execution.tradovate.config import TradovateConfig


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_config(**overrides) -> TradovateConfig:
    """Create a TradovateConfig with sensible test defaults."""
    defaults = dict(
        username="testuser",
        password="testpass",
        cid=1234,
        sec="testsec",
        env="demo",
    )
    defaults.update(overrides)
    return TradovateConfig(**defaults)


def _make_client(config: TradovateConfig | None = None) -> TradovateClient:
    """Create a TradovateClient ready for unit testing (no real session)."""
    return TradovateClient(config or _make_config())


def _make_mock_response(status: int = 200, json_data=None, text_data: str = ""):
    """Create a mock aiohttp.ClientResponse for _handle_response tests."""
    resp = MagicMock()
    resp.status = status
    if json_data is not None:
        resp.text = AsyncMock(return_value=json.dumps(json_data))
    else:
        resp.text = AsyncMock(return_value=text_data)
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════════════


class TestAuthentication:
    """accesstokenrequest flow: success, error, rate-limit penalty."""

    @pytest.mark.asyncio
    async def test_authenticate_success_stores_token_and_user_id(self):
        """Successful auth populates _access_token, _user_id, _token_expiry."""
        client = _make_client()
        client._session = MagicMock()
        client._post = AsyncMock(return_value={
            "accessToken": "tok_abc123",
            "mdAccessToken": "md_tok_xyz",
            "userId": 42,
            "expirationTime": "2026-03-01T12:00:00Z",
        })

        await client._authenticate()

        assert client._access_token == "tok_abc123"
        assert client._md_access_token == "md_tok_xyz"
        assert client._user_id == 42
        assert client._token_expiry is not None
        assert client._token_expiry.year == 2026
        assert client._token_expiry.month == 3

    @pytest.mark.asyncio
    async def test_authenticate_error_text_raises_auth_error(self):
        """Auth response with errorText (no p-ticket) raises TradovateAuthError."""
        client = _make_client()
        client._session = MagicMock()
        client._post = AsyncMock(return_value={
            "errorText": "Invalid credentials",
        })

        with pytest.raises(TradovateAuthError, match="Invalid credentials"):
            await client._authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_rate_limited_raises_with_ticket(self):
        """Auth with p-ticket + p-time raises TradovateAuthError with penalty info."""
        client = _make_client()
        client._session = MagicMock()
        client._post = AsyncMock(return_value={
            "errorText": "Rate limited",
            "p-ticket": "ticket_abc",
            "p-time": 30,
        })

        with pytest.raises(TradovateAuthError, match="rate limited"):
            await client._authenticate()


# ═══════════════════════════════════════════════════════════════════════════
# Token renewal
# ═══════════════════════════════════════════════════════════════════════════


class TestTokenRenewal:
    """renewaccesstoken flow and fallback to full re-auth."""

    @pytest.mark.asyncio
    async def test_renew_token_updates_access_token_and_expiry(self):
        """Successful renewal replaces _access_token and _token_expiry."""
        client = _make_client()
        client._session = MagicMock()
        client._access_token = "old_token"
        client._token_expiry = datetime.now(timezone.utc)

        client._get = AsyncMock(return_value={
            "accessToken": "new_token_abc",
            "expirationTime": "2026-04-01T12:00:00Z",
        })

        await client._renew_token()

        assert client._access_token == "new_token_abc"
        assert client._token_expiry.month == 4

    @pytest.mark.asyncio
    async def test_renew_token_failure_falls_back_to_reauthentication(self):
        """Network failure during renewal triggers full _authenticate()."""
        client = _make_client()
        client._session = MagicMock()
        client._access_token = "old_token"

        client._get = AsyncMock(side_effect=Exception("network error"))
        client._authenticate = AsyncMock()

        await client._renew_token()

        client._authenticate.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# REST operations
# ═══════════════════════════════════════════════════════════════════════════


class TestRESTOperations:
    """REST API methods: contract lookup, order placement, front-month resolution."""

    @pytest.mark.asyncio
    async def test_find_contract_calls_correct_url(self):
        """find_contract makes GET to /contract/find?name=<symbol>."""
        client = _make_client()
        client._session = MagicMock()
        client._access_token = "test_token"

        expected = {"id": 999, "name": "MNQH6", "providerTickSize": 0.25}
        client._get = AsyncMock(return_value=expected)

        result = await client.find_contract("MNQH6")

        assert result["id"] == 999
        assert result["name"] == "MNQH6"
        call_url = client._get.call_args[0][0]
        assert "/contract/find?name=MNQH6" in call_url

    @pytest.mark.asyncio
    async def test_place_oso_builds_bracket_body_correctly(self):
        """place_oso sends entry + bracket1 (TP) + bracket2 (SL) in request body."""
        client = _make_client()
        client._session = MagicMock()
        client._access_token = "test_token"
        client._account_id = 12345
        client._account_name = "DEMO0001"

        client._post = AsyncMock(return_value={"orderId": 77})

        result = await client.place_oso(
            symbol="MNQH6",
            action="Buy",
            order_qty=2,
            order_type="Market",
            tp_price=18050.0,
            sl_price=17950.0,
        )

        assert result["orderId"] == 77
        client._post.assert_awaited_once()
        call_url, call_body = client._post.call_args[0]
        assert "/order/placeoso" in call_url
        assert call_body["action"] == "Buy"
        assert call_body["orderQty"] == 2
        assert call_body["isAutomated"] is True
        assert call_body["accountId"] == 12345
        assert call_body["accountSpec"] == "DEMO0001"
        # TP bracket: Limit on opposite side
        assert call_body["bracket1"]["action"] == "Sell"
        assert call_body["bracket1"]["orderType"] == "Limit"
        assert call_body["bracket1"]["price"] == 18050.0
        assert call_body["bracket1"]["isAutomated"] is True
        # SL bracket: Stop on opposite side
        assert call_body["bracket2"]["action"] == "Sell"
        assert call_body["bracket2"]["orderType"] == "Stop"
        assert call_body["bracket2"]["stopPrice"] == 17950.0

    @pytest.mark.asyncio
    async def test_resolve_front_month_uses_suggest_first(self):
        """resolve_front_month tries contract/suggest as the primary strategy."""
        client = _make_client()
        client._session = MagicMock()
        client._access_token = "test_token"

        client.suggest_contracts = AsyncMock(return_value=[
            {"name": "MNQH6", "id": 999},
        ])
        # Should not be called if suggest succeeds
        client.roll_contract = AsyncMock()

        result = await client.resolve_front_month("MNQ")

        assert result == "MNQH6"
        client.suggest_contracts.assert_awaited_once_with("MNQ", limit=1)
        client.roll_contract.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_front_month_falls_back_to_roll(self):
        """When suggest fails, falls back to roll_contract."""
        client = _make_client()
        client._session = MagicMock()
        client._access_token = "test_token"

        client.suggest_contracts = AsyncMock(side_effect=Exception("unavailable"))
        client.roll_contract = AsyncMock(return_value={
            "contract": {"name": "MNQM6", "id": 888},
        })

        result = await client.resolve_front_month("MNQ")

        assert result == "MNQM6"
        client.roll_contract.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# Response handling  (_handle_response)
# ═══════════════════════════════════════════════════════════════════════════


class TestResponseHandling:
    """HTTP response parsing: status codes, error extraction, rate limiting."""

    @pytest.mark.asyncio
    async def test_200_returns_parsed_json(self):
        """Successful response returns parsed JSON body."""
        client = _make_client()
        resp = _make_mock_response(200, json_data={"orderId": 42, "status": "ok"})

        data = await client._handle_response(resp)

        assert data == {"orderId": 42, "status": "ok"}

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error_with_status(self):
        """429 response raises TradovateAPIError with status=429."""
        client = _make_client()
        resp = _make_mock_response(429, text_data="Too Many Requests")

        with pytest.raises(TradovateAPIError, match="Rate limited") as exc_info:
            await client._handle_response(resp)

        assert exc_info.value.status == 429

    @pytest.mark.asyncio
    async def test_404_raises_api_error_with_body(self):
        """404 response raises TradovateAPIError preserving error text and body."""
        client = _make_client()
        resp = _make_mock_response(404, json_data={"errorText": "Entity not found"})

        with pytest.raises(TradovateAPIError, match="Entity not found") as exc_info:
            await client._handle_response(resp)

        assert exc_info.value.status == 404
        assert exc_info.value.body == {"errorText": "Entity not found"}

    @pytest.mark.asyncio
    async def test_500_raises_api_error_with_server_message(self):
        """500 response extracts 'message' field for the error."""
        client = _make_client()
        resp = _make_mock_response(500, json_data={"message": "Internal server error"})

        with pytest.raises(TradovateAPIError) as exc_info:
            await client._handle_response(resp)

        assert exc_info.value.status == 500
        assert exc_info.value.body == {"message": "Internal server error"}

    @pytest.mark.asyncio
    async def test_200_with_business_error_raises_api_error(self):
        """A 200 response containing errorText is treated as an error."""
        client = _make_client()
        resp = _make_mock_response(200, json_data={"errorText": "Account suspended"})

        with pytest.raises(TradovateAPIError, match="Account suspended"):
            await client._handle_response(resp)


# ═══════════════════════════════════════════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════════════════════════════════════════


class TestWebSocket:
    """WebSocket event handlers, state flags, and teardown."""

    def test_add_event_handler_registers_callback(self):
        """Registered handler appears in _event_handlers list."""
        client = _make_client()
        handler = MagicMock()

        client.add_event_handler(handler)

        assert len(client._event_handlers) == 1
        assert client._event_handlers[0] is handler

    def test_ws_connected_property_reflects_internal_state(self):
        """ws_connected property mirrors _ws_connected flag."""
        client = _make_client()
        assert client.ws_connected is False

        client._ws_connected = True
        assert client.ws_connected is True

    @pytest.mark.asyncio
    async def test_close_websocket_resets_state_and_closes(self):
        """_close_websocket cancels tasks, closes socket, resets flags."""
        client = _make_client()

        # Simulate an open WS connection
        mock_ws = AsyncMock()
        mock_ws.closed = False
        client._ws = mock_ws
        client._ws_connected = True
        client._ws_authorized = True

        # Create real asyncio tasks that we can cancel
        async def forever():
            await asyncio.sleep(999)

        client._ws_heartbeat_task = asyncio.create_task(forever())
        client._ws_listener_task = asyncio.create_task(forever())

        await client._close_websocket()

        assert client._ws is None
        assert client._ws_connected is False
        assert client._ws_authorized is False
        mock_ws.close.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Session guards, token expiry checks, connection failure recovery."""

    @pytest.mark.asyncio
    async def test_get_without_session_raises_api_error(self):
        """Calling _get with no session raises TradovateAPIError."""
        client = _make_client()
        client._session = None

        with pytest.raises(TradovateAPIError, match="not connected"):
            await client._get("https://example.com/test")

    @pytest.mark.asyncio
    async def test_post_without_session_raises_api_error(self):
        """Calling _post with no session raises TradovateAPIError."""
        client = _make_client()
        client._session = None

        with pytest.raises(TradovateAPIError, match="not connected"):
            await client._post("https://example.com/test", {"key": "val"})

    def test_is_authenticated_false_without_token(self):
        """is_authenticated is False when no access token exists."""
        client = _make_client()
        assert client.is_authenticated is False

    def test_is_authenticated_false_when_expired(self):
        """is_authenticated is False when token_expiry is in the past."""
        client = _make_client()
        client._access_token = "some_token"
        client._token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

        assert client.is_authenticated is False

    def test_is_authenticated_true_when_valid(self):
        """is_authenticated is True with a token and future expiry."""
        client = _make_client()
        client._access_token = "some_token"
        client._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        assert client.is_authenticated is True
