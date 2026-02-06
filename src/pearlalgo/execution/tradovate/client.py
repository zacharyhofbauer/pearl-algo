"""
Tradovate REST + WebSocket Client

Handles:
- Authentication (access token request + renewal)
- Account resolution (integer ID from /account/list)
- Order placement (placeOrder, placeOSO, cancelOrder, liquidatePosition)
- Position and balance queries
- Contract lookup (roll to front-month)
- WebSocket real-time sync (user/syncrequest)

Environment: demo.tradovateapi.com for paper trading.

IMPORTANT:
- All automated orders MUST set isAutomated=true (exchange requirement).
- Max 2 concurrent sessions per user -- never call accesstokenrequest
  from multiple processes. Use a shared token or single-process design.
- WebSocket heartbeat: send "[]" every 2.5 seconds.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import aiohttp

from pearlalgo.execution.tradovate.config import TradovateConfig

logger = logging.getLogger(__name__)


class TradovateAuthError(Exception):
    """Raised when authentication fails."""
    pass


class TradovateAPIError(Exception):
    """Raised when an API call returns an error."""

    def __init__(self, message: str, status: int = 0, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class TradovateClient:
    """
    Async client for the Tradovate REST API + WebSocket.

    Lifecycle:
        client = TradovateClient(config)
        await client.connect()       # authenticate + resolve account
        ...                           # place orders, query positions
        await client.disconnect()     # clean up
    """

    def __init__(self, config: TradovateConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

        # Auth state
        self._access_token: Optional[str] = None
        self._md_access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._user_id: Optional[int] = None

        # Account state
        self._account_id: Optional[int] = None
        self._account_name: Optional[str] = None

        # WebSocket
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_request_id: int = 0
        self._ws_heartbeat_task: Optional[asyncio.Task] = None
        self._ws_listener_task: Optional[asyncio.Task] = None
        self._ws_authorized: bool = False

        # Callbacks for real-time events
        self._event_handlers: List[Callable[[Dict[str, Any]], None]] = []

        # Token renewal task
        self._renewal_task: Optional[asyncio.Task] = None

    # ── Properties ────────────────────────────────────────────────────

    @property
    def account_id(self) -> Optional[int]:
        """Tradovate integer account ID (resolved after connect)."""
        return self._account_id

    @property
    def account_name(self) -> Optional[str]:
        """Tradovate account display name (e.g. DEMO6315448)."""
        return self._account_name

    @property
    def is_authenticated(self) -> bool:
        """Whether we have a valid (non-expired) access token."""
        if not self._access_token or not self._token_expiry:
            return False
        return datetime.now(timezone.utc) < self._token_expiry

    # ── Connection lifecycle ──────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Authenticate, resolve account, and start token renewal.

        Returns True if successful.
        """
        self.config.validate()

        self._session = aiohttp.ClientSession(
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        )

        # Authenticate
        await self._authenticate()

        if not self._access_token:
            logger.error("Tradovate authentication failed")
            return False

        # Resolve account ID
        await self._resolve_account()

        if not self._account_id:
            logger.error("Could not resolve Tradovate account ID")
            return False

        # Start token renewal background task
        self._renewal_task = asyncio.create_task(self._token_renewal_loop())

        logger.info(
            f"Tradovate connected: account={self._account_name} "
            f"(id={self._account_id}), env={self.config.env}"
        )
        return True

    async def disconnect(self) -> None:
        """Close all connections and cancel background tasks."""
        if self._renewal_task and not self._renewal_task.done():
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass

        await self._close_websocket()

        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        self._access_token = None
        self._account_id = None
        logger.info("Tradovate client disconnected")

    # ── Authentication ────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        """Request an access token using client credentials."""
        url = f"{self.config.rest_url}/auth/accesstokenrequest"
        body = {
            "name": self.config.username,
            "password": self.config.password,
            "appId": self.config.app_id,
            "appVersion": self.config.app_version,
            "cid": self.config.cid,
            "sec": self.config.sec,
            "deviceId": self.config.device_id,
        }

        try:
            data = await self._post(url, body, auth=False)
        except Exception as e:
            raise TradovateAuthError(f"Authentication request failed: {e}") from e

        error_text = data.get("errorText")
        if error_text:
            # Handle time penalty (rate limited)
            p_ticket = data.get("p-ticket")
            p_time = data.get("p-time")
            if p_ticket and p_time:
                raise TradovateAuthError(
                    f"Auth rate limited: wait {p_time}s then retry with p-ticket={p_ticket}"
                )
            raise TradovateAuthError(f"Auth error: {error_text}")

        self._access_token = data.get("accessToken")
        self._md_access_token = data.get("mdAccessToken")
        self._user_id = data.get("userId")

        expiry_str = data.get("expirationTime")
        if expiry_str:
            try:
                self._token_expiry = datetime.fromisoformat(
                    expiry_str.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                # Fallback: 90 min from now
                from datetime import timedelta
                self._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=90)

        logger.info(
            f"Tradovate authenticated: userId={self._user_id}, "
            f"expires={self._token_expiry}"
        )

    async def _renew_token(self) -> None:
        """Renew the access token before it expires."""
        if not self._access_token:
            return

        url = f"{self.config.rest_url}/auth/renewaccesstoken"
        try:
            data = await self._get(url)
            new_token = data.get("accessToken")
            if new_token:
                self._access_token = new_token
                expiry_str = data.get("expirationTime")
                if expiry_str:
                    try:
                        self._token_expiry = datetime.fromisoformat(
                            expiry_str.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        from datetime import timedelta
                        self._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=90)
                logger.info(f"Tradovate token renewed, expires={self._token_expiry}")
            else:
                logger.warning("Token renewal returned no accessToken, re-authenticating")
                await self._authenticate()
        except Exception as e:
            logger.warning(f"Token renewal failed, re-authenticating: {e}")
            await self._authenticate()

    async def _token_renewal_loop(self) -> None:
        """Background task to renew token periodically."""
        while True:
            try:
                await asyncio.sleep(self.config.token_renewal_seconds)
                await self._renew_token()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Token renewal loop error: {e}")
                await asyncio.sleep(60)  # Back off

    # ── Account resolution ────────────────────────────────────────────

    async def _resolve_account(self) -> None:
        """Resolve the integer account ID from /account/list."""
        accounts = await self.get_accounts()

        if not accounts:
            raise TradovateAPIError("No accounts found")

        # If a specific account name was requested, find it
        if self.config.account_name:
            for acct in accounts:
                if acct.get("name") == self.config.account_name:
                    self._account_id = acct["id"]
                    self._account_name = acct["name"]
                    return
            raise TradovateAPIError(
                f"Account '{self.config.account_name}' not found. "
                f"Available: {[a.get('name') for a in accounts]}"
            )

        # Auto-select first active account
        for acct in accounts:
            if acct.get("active", True):
                self._account_id = acct["id"]
                self._account_name = acct.get("name", str(acct["id"]))
                return

        # Fallback to first account
        self._account_id = accounts[0]["id"]
        self._account_name = accounts[0].get("name", str(accounts[0]["id"]))

    # ── REST API: Accounting ──────────────────────────────────────────

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """GET /account/list -- all accounts for the authenticated user."""
        url = f"{self.config.rest_url}/account/list"
        return await self._get(url)

    async def get_cash_balance_snapshot(self, account_id: Optional[int] = None) -> Dict[str, Any]:
        """POST /cashBalance/getCashBalanceSnapshot -- current cash balance."""
        aid = account_id or self._account_id
        url = f"{self.config.rest_url}/cashBalance/getCashBalanceSnapshot"
        return await self._post(url, {"accountId": aid})

    async def get_account_risk_status(self) -> List[Dict[str, Any]]:
        """GET /accountRiskStatus/list -- liquidation status for all accounts."""
        url = f"{self.config.rest_url}/accountRiskStatus/list"
        return await self._get(url)

    # ── REST API: Positions ───────────────────────────────────────────

    async def get_positions(self, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /position/deps -- positions for an account."""
        aid = account_id or self._account_id
        url = f"{self.config.rest_url}/position/deps?masterid={aid}"
        return await self._get(url)

    async def get_fills(self, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /fill/deps -- fills for an account."""
        aid = account_id or self._account_id
        url = f"{self.config.rest_url}/fill/deps?masterid={aid}"
        return await self._get(url)

    # ── REST API: Orders ──────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        action: str,
        order_qty: int,
        order_type: str = "Market",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "Day",
    ) -> Dict[str, Any]:
        """
        POST /order/placeOrder -- place a single order.

        Args:
            symbol: Contract symbol (e.g. "MNQH6")
            action: "Buy" or "Sell"
            order_qty: Number of contracts
            order_type: "Market", "Limit", "Stop", "StopLimit"
            price: Limit price (for Limit/StopLimit orders)
            stop_price: Stop price (for Stop/StopLimit orders)
            time_in_force: "Day", "GTC", etc.
        """
        body: Dict[str, Any] = {
            "accountSpec": self._account_name,
            "accountId": self._account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": order_qty,
            "orderType": order_type,
            "timeInForce": time_in_force,
            "isAutomated": True,  # MANDATORY for algorithmic orders
        }

        if price is not None:
            body["price"] = price
        if stop_price is not None:
            body["stopPrice"] = stop_price

        url = f"{self.config.rest_url}/order/placeorder"
        return await self._post(url, body)

    async def place_oso(
        self,
        symbol: str,
        action: str,
        order_qty: int,
        order_type: str = "Market",
        price: Optional[float] = None,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        time_in_force: str = "Day",
    ) -> Dict[str, Any]:
        """
        POST /order/placeOSO -- place an OSO bracket order.

        The entry order spawns an OCO pair (take profit + stop loss).
        This is the recommended way to place bracket orders on Tradovate.

        Args:
            symbol: Contract symbol (e.g. "MNQH6")
            action: "Buy" (long) or "Sell" (short)
            order_qty: Number of contracts
            order_type: Entry order type ("Market" or "Limit")
            price: Entry limit price (if order_type is "Limit")
            tp_price: Take profit limit price
            sl_price: Stop loss price
            time_in_force: "Day", "GTC", etc.
        """
        exit_action = "Sell" if action == "Buy" else "Buy"

        body: Dict[str, Any] = {
            "accountSpec": self._account_name,
            "accountId": self._account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": order_qty,
            "orderType": order_type,
            "timeInForce": time_in_force,
            "isAutomated": True,  # MANDATORY for algorithmic orders
        }

        if price is not None:
            body["price"] = price

        # OCO bracket legs
        if tp_price is not None:
            body["bracket1"] = {
                "action": exit_action,
                "orderType": "Limit",
                "price": tp_price,
                "timeInForce": time_in_force,
                "isAutomated": True,
            }

        if sl_price is not None:
            body["bracket2"] = {
                "action": exit_action,
                "orderType": "Stop",
                "stopPrice": sl_price,
                "timeInForce": time_in_force,
                "isAutomated": True,
            }

        url = f"{self.config.rest_url}/order/placeoso"
        return await self._post(url, body)

    async def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """POST /order/cancelorder -- cancel a specific order."""
        url = f"{self.config.rest_url}/order/cancelorder"
        return await self._post(url, {"orderId": order_id})

    async def liquidate_position(self, account_id: Optional[int] = None) -> Dict[str, Any]:
        """POST /order/liquidatePosition -- liquidate a specific position."""
        aid = account_id or self._account_id
        url = f"{self.config.rest_url}/order/liquidateposition"
        return await self._post(url, {"accountId": aid})

    async def liquidate_all_positions(self) -> Dict[str, Any]:
        """
        Liquidate all positions for the account.

        Uses individual position liquidation since /order/liquidatePositions
        may not exist on all environments.
        """
        positions = await self.get_positions()
        results = []
        for pos in positions:
            net_pos = pos.get("netPos", 0)
            if net_pos != 0:
                contract_id = pos.get("contractId")
                try:
                    result = await self.place_order(
                        symbol=str(contract_id),
                        action="Sell" if net_pos > 0 else "Buy",
                        order_qty=abs(net_pos),
                        order_type="Market",
                    )
                    results.append(result)
                except Exception as e:
                    logger.error(f"Failed to liquidate position {contract_id}: {e}")
                    results.append({"error": str(e), "contractId": contract_id})
        return {"positions_liquidated": len(results), "results": results}

    # ── REST API: Contracts ───────────────────────────────────────────

    async def find_contract(self, name: str) -> Dict[str, Any]:
        """GET /contract/find -- find contract by symbol name."""
        url = f"{self.config.rest_url}/contract/find?name={name}"
        return await self._get(url)

    async def roll_contract(self, name: str, forward: bool = True) -> Dict[str, Any]:
        """POST /contract/rollcontract -- get front-month contract for a product."""
        url = f"{self.config.rest_url}/contract/rollcontract"
        body = {"name": name, "forward": forward, "ifExpired": True}
        return await self._post(url, body)

    async def resolve_front_month(self, product: str = "MNQ") -> str:
        """
        Resolve the front-month contract symbol for a product.

        E.g. "MNQ" -> "MNQH6"
        """
        try:
            result = await self.roll_contract(product)
            contract = result.get("contract", {})
            name = contract.get("name")
            if name:
                return name
        except Exception as e:
            logger.warning(f"roll_contract failed for {product}: {e}")

        # Fallback: try to find directly
        try:
            result = await self.find_contract(product)
            name = result.get("name")
            if name:
                return name
        except Exception:
            pass

        raise TradovateAPIError(f"Could not resolve front-month contract for {product}")

    # ── REST API: Risk ────────────────────────────────────────────────

    async def get_position_limits(self, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /userAccountPositionLimit/deps -- position limits for an account."""
        aid = account_id or self._account_id
        url = f"{self.config.rest_url}/userAccountPositionLimit/deps?masterid={aid}"
        return await self._get(url)

    async def create_position_limit(
        self,
        total_by: str = "Overall",
        exposed_limit: int = 5,
        description: str = "Pearl MFFU max contracts",
    ) -> Dict[str, Any]:
        """POST /userAccountPositionLimit/create -- set a position limit."""
        url = f"{self.config.rest_url}/userAccountPositionLimit/create"
        body = {
            "accountId": self._account_id,
            "active": True,
            "totalBy": total_by,
            "exposedLimit": exposed_limit,
            "description": description,
        }
        return await self._post(url, body)

    # ── WebSocket ─────────────────────────────────────────────────────

    async def start_websocket(self) -> None:
        """Open WebSocket connection, authorize, and subscribe to user sync."""
        if not self._session or not self._access_token:
            raise TradovateAPIError("Must authenticate before starting WebSocket")

        ws_url = self.config.ws_url
        logger.info(f"Connecting to Tradovate WebSocket: {ws_url}")

        self._ws = await self._session.ws_connect(ws_url)

        # Wait for open frame
        msg = await self._ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT and msg.data.startswith("o"):
            logger.debug("WebSocket open frame received")

        # Authorize
        self._ws_request_id += 1
        auth_msg = f"authorize\n{self._ws_request_id}\n\n{self._access_token}"
        await self._ws.send_str(auth_msg)

        # Wait for auth response
        msg = await self._ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = msg.data
            if data.startswith("a"):
                payload = json.loads(data[1:])
                if payload and isinstance(payload, list):
                    resp = payload[0] if payload else {}
                    if resp.get("s") == 200:
                        self._ws_authorized = True
                        logger.info("Tradovate WebSocket authorized")
                    else:
                        raise TradovateAuthError(
                            f"WebSocket auth failed: {resp.get('d', 'unknown')}"
                        )

        # Subscribe to user sync
        self._ws_request_id += 1
        sync_msg = f"user/syncrequest\n{self._ws_request_id}\n"
        await self._ws.send_str(sync_msg)

        # Start heartbeat + listener tasks
        self._ws_heartbeat_task = asyncio.create_task(self._ws_heartbeat_loop())
        self._ws_listener_task = asyncio.create_task(self._ws_listener_loop())

    def add_event_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for real-time WebSocket events."""
        self._event_handlers.append(handler)

    async def _ws_heartbeat_loop(self) -> None:
        """Send heartbeat every 2.5 seconds to keep WS alive."""
        while self._ws and not self._ws.closed:
            try:
                await self._ws.send_str("[]")
                await asyncio.sleep(2.5)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _ws_listener_loop(self) -> None:
        """Listen for WebSocket messages and dispatch to handlers."""
        while self._ws and not self._ws.closed:
            try:
                msg = await self._ws.receive(timeout=10)

                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = msg.data
                    if data.startswith("a"):
                        try:
                            payload = json.loads(data[1:])
                            for item in (payload if isinstance(payload, list) else [payload]):
                                if isinstance(item, dict):
                                    for handler in self._event_handlers:
                                        try:
                                            handler(item)
                                        except Exception as e:
                                            logger.debug(f"WS event handler error: {e}")
                        except json.JSONDecodeError:
                            pass
                    elif data.startswith("h"):
                        # Server heartbeat -- respond with our own
                        pass

                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    logger.warning("Tradovate WebSocket closed")
                    break

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"Tradovate WebSocket error: {self._ws.exception()}")
                    break

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WS listener error: {e}")
                break

    async def _close_websocket(self) -> None:
        """Close WebSocket connection and cancel tasks."""
        for task in (self._ws_heartbeat_task, self._ws_listener_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self._ws_authorized = False

    # ── HTTP helpers ──────────────────────────────────────────────────

    async def _get(self, url: str) -> Any:
        """Make an authenticated GET request."""
        if not self._session:
            raise TradovateAPIError("Client not connected")

        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        async with self._session.get(url, headers=headers) as resp:
            if resp.status == 401:
                # Try to re-authenticate
                await self._authenticate()
                headers["Authorization"] = f"Bearer {self._access_token}"
                async with self._session.get(url, headers=headers) as retry_resp:
                    return await self._handle_response(retry_resp)
            return await self._handle_response(resp)

    async def _post(self, url: str, body: Dict[str, Any], auth: bool = True) -> Any:
        """Make an optionally-authenticated POST request."""
        if not self._session:
            raise TradovateAPIError("Client not connected")

        headers = {}
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        async with self._session.post(url, json=body, headers=headers) as resp:
            if resp.status == 401 and auth:
                await self._authenticate()
                headers["Authorization"] = f"Bearer {self._access_token}"
                async with self._session.post(url, json=body, headers=headers) as retry_resp:
                    return await self._handle_response(retry_resp)
            return await self._handle_response(resp)

    async def _handle_response(self, resp: aiohttp.ClientResponse) -> Any:
        """Parse response and raise on errors."""
        text = await resp.text()

        if resp.status == 429:
            raise TradovateAPIError("Rate limited (429)", status=429, body=text)

        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {"raw": text}

        if resp.status >= 400:
            error_text = ""
            if isinstance(data, dict):
                error_text = data.get("errorText", "") or data.get("message", "") or str(data)
            else:
                error_text = str(data)
            raise TradovateAPIError(
                f"HTTP {resp.status}: {error_text}",
                status=resp.status,
                body=data,
            )

        # Check for business-level errors in successful responses
        if isinstance(data, dict) and data.get("errorText"):
            raise TradovateAPIError(
                data["errorText"],
                status=resp.status,
                body=data,
            )

        return data
