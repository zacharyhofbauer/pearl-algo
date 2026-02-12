"""
Failure-mode tests for TradovateClient (tradovate/client.py).

Covers:
- Heartbeat loop error handling and graceful exit
- Authentication failure (errorText in response)
- WebSocket reconnection failure after all attempts exhausted
- Order placement with expired/missing token triggering re-auth
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from pearlalgo.execution.tradovate.client import (
    TradovateClient,
    TradovateAuthError,
    TradovateAPIError,
)
from pearlalgo.execution.tradovate.config import TradovateConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> TradovateConfig:
    """Create a minimal TradovateConfig for testing."""
    return TradovateConfig(
        username="test_user",
        password="test_pass",
        cid=12345,
        sec="test_sec",
        env="demo",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTradovateClientFailures:
    """Failure-mode tests for TradovateClient."""

    @pytest.mark.asyncio
    async def test_heartbeat_loop_logs_error_on_exception(self, caplog):
        """When the WebSocket send raises, the heartbeat loop should log
        an error and exit gracefully instead of crashing."""
        config = _make_config()
        client = TradovateClient(config)

        # Create a mock WebSocket that raises on send_str
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.send_str = AsyncMock(side_effect=ConnectionError("WS broken"))
        client._ws = mock_ws

        with caplog.at_level(logging.ERROR, logger="pearlalgo.execution.tradovate.client"):
            await client._ws_heartbeat_loop()

        # The loop should have exited (not hung forever)
        assert any(
            "heartbeat loop failed" in record.message.lower()
            for record in caplog.records
        ), "Expected heartbeat error to be logged"

    @pytest.mark.asyncio
    async def test_auth_failure_raises_tradovate_auth_error(self):
        """When the auth endpoint returns an errorText, _authenticate
        should raise TradovateAuthError."""
        config = _make_config()
        client = TradovateClient(config)

        # Mock the HTTP session so _post returns an error response
        mock_session = AsyncMock()
        client._session = mock_session

        # Simulate the auth response containing an error
        async def mock_post(url, body, auth=False):
            return {"errorText": "Invalid credentials"}

        client._post = AsyncMock(side_effect=mock_post)

        with pytest.raises(TradovateAuthError, match="Invalid credentials"):
            await client._authenticate()

    @pytest.mark.asyncio
    async def test_ws_reconnect_fails_after_max_attempts(self, caplog):
        """When all reconnection attempts fail, the listener loop should
        exit and log an error about exhausted attempts."""
        config = _make_config()
        client = TradovateClient(config)
        client._max_ws_reconnect_attempts = 2  # Keep test fast

        # Mock _open_ws_connection to always fail
        client._open_ws_connection = AsyncMock(
            side_effect=ConnectionError("Cannot reconnect")
        )

        # Mock a dead WebSocket so the inner loop exits immediately
        mock_ws = AsyncMock()
        mock_ws.closed = True
        client._ws = mock_ws
        client._ws_connected = False
        client._ws_authorized = False

        # The heartbeat task should be a no-op
        client._ws_heartbeat_task = None

        with caplog.at_level(logging.ERROR, logger="pearlalgo.execution.tradovate.client"):
            await client._ws_listener_loop()

        assert any(
            "reconnection failed" in record.message.lower()
            for record in caplog.records
        ), "Expected reconnection failure to be logged after max attempts"
        assert not client._ws_connected, "Should not be connected after failed reconnection"

    @pytest.mark.asyncio
    async def test_place_order_with_expired_token_triggers_reauth(self):
        """When the token is expired (401), the _post helper should
        re-authenticate and retry the request."""
        config = _make_config()
        client = TradovateClient(config)
        client._access_token = "expired_token"
        client._account_id = 999
        client._account_name = "DEMO_TEST"

        # Track calls to _authenticate
        auth_call_count = 0
        original_token = client._access_token

        async def mock_authenticate():
            nonlocal auth_call_count
            auth_call_count += 1
            client._access_token = "fresh_token"
            client._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        client._authenticate = AsyncMock(side_effect=mock_authenticate)

        # Build a mock session where first POST returns 401, retry returns 200
        mock_resp_401 = AsyncMock()
        mock_resp_401.status = 401
        mock_resp_401.text = AsyncMock(return_value='{"errorText": "Unauthorized"}')

        mock_resp_200 = AsyncMock()
        mock_resp_200.status = 200
        mock_resp_200.text = AsyncMock(
            return_value='{"orderId": 12345, "ordStatus": "Working"}'
        )

        # Use a context manager mock for aiohttp session.post
        call_count = 0

        class FakeContextManager:
            def __init__(self, resp):
                self.resp = resp

            async def __aenter__(self):
                return self.resp

            async def __aexit__(self, *args):
                pass

        mock_session = MagicMock()

        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeContextManager(mock_resp_401)
            return FakeContextManager(mock_resp_200)

        mock_session.post = MagicMock(side_effect=post_side_effect)
        client._session = mock_session

        # Call _post (which place_order ultimately uses)
        result = await client._post(
            f"{config.rest_url}/order/placeorder",
            {"symbol": "MNQH6", "action": "Buy", "orderQty": 1},
        )

        assert auth_call_count == 1, "Should have re-authenticated once on 401"
        assert result.get("orderId") == 12345, "Retry should return the order"
