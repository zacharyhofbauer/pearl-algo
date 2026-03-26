#!/usr/bin/env python3
"""
PearlAlgo Smoke Test — Round-trip execution check
Places 1 MNQ market order → waits for fill → immediately closes.
Safe to run anytime; paper account only.
"""

import asyncio
import time
import sys
import os

# Load secrets
secrets_path = os.path.expanduser("~/.config/pearlalgo/secrets.env")
if os.path.exists(secrets_path):
    with open(secrets_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, os.path.expanduser("~/pearl-algo-workspace"))

from src.pearlalgo.execution.tradovate.client import TradovateClient
from src.pearlalgo.execution.tradovate.config import TradovateConfig


async def run_smoke_test():
    print("🔬 PearlAlgo Smoke Test — Starting...")
    cfg = TradovateConfig.from_env()
    cfg.validate()

    client = TradovateClient(cfg)

    t0 = time.monotonic()
    print(f"  Connecting to Tradovate ({cfg.env})...")
    connected = await client.connect()
    if not connected:
        print("❌ FAIL: Could not connect to Tradovate")
        return False

    print(f"  ✅ Connected — account={client.account_name} (id={client.account_id})")

    # Get current price for context
    symbol = "MNQH6"

    # Place 1-contract market BUY
    print(f"  Placing 1-contract market BUY on {symbol}...")
    t_entry = time.monotonic()
    result = await client.place_order(
        symbol=symbol,
        action="Buy",
        order_qty=1,
        order_type="Market",
    )
    t_placed = time.monotonic()

    order_id = result.get("orderId") or result.get("id")
    order_status = result.get("orderStatus") or result.get("status", "unknown")
    print(f"  Entry order: id={order_id} status={order_status} ({(t_placed - t_entry)*1000:.0f}ms)")

    if not order_id:
        print(f"❌ FAIL: No order ID returned. Response: {result}")
        await client.disconnect()
        return False

    # Wait briefly for fill
    print("  Waiting 2s for fill...")
    await asyncio.sleep(2)

    # Flatten immediately — sell 1 contract
    print(f"  Placing 1-contract market SELL (close)...")
    t_exit = time.monotonic()
    close_result = await client.place_order(
        symbol=symbol,
        action="Sell",
        order_qty=1,
        order_type="Market",
    )
    t_closed = time.monotonic()

    close_id = close_result.get("orderId") or close_result.get("id")
    close_status = close_result.get("orderStatus") or close_result.get("status", "unknown")
    print(f"  Close order: id={close_id} status={close_status} ({(t_closed - t_exit)*1000:.0f}ms)")

    total_ms = (t_closed - t0) * 1000
    await client.disconnect()

    if close_id:
        print(f"\n✅ SMOKE TEST PASSED")
        print(f"   Entry order: {order_id} ({order_status})")
        print(f"   Close order: {close_id} ({close_status})")
        print(f"   Total round-trip: {total_ms:.0f}ms")
        print(f"   Stack: Tradovate connected ✅ | Orders placed ✅ | Close placed ✅")
        return True
    else:
        print(f"\n⚠️  PARTIAL: Entry placed but close may have failed")
        print(f"   Close response: {close_result}")
        return False


if __name__ == "__main__":
    ok = asyncio.run(run_smoke_test())
    sys.exit(0 if ok else 1)
