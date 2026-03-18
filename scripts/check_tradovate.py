#!/usr/bin/env python3
"""
Tradovate Position Checker — PearlAlgo
Queries Tradovate REST API directly for ground-truth position data.
Usage: PYTHONPATH=/home/pearlalgo/PearlAlgoWorkspace .venv/bin/python3 check_tradovate.py [--orders] [--account] [--fills N]
"""
import asyncio
import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Must run from PearlAlgoWorkspace with PYTHONPATH set
sys.path.insert(0, "/home/pearlalgo/PearlAlgoWorkspace")

from src.pearlalgo.execution.tradovate.client import TradovateClient
from src.pearlalgo.execution.tradovate.config import TradovateConfig


async def check_positions(client):
    """Get all positions from Tradovate REST API."""
    positions = await client.get_positions()
    open_positions = [p for p in positions if p.get("netPos", 0) != 0]
    return positions, open_positions


async def check_orders(client):
    """Get open/working orders."""
    try:
        orders = await client._request("GET", "/order/list")
        working = [o for o in (orders or []) if o.get("ordStatus") in ("Working", "Accepted", "PendingSubmit")]
        return orders or [], working
    except Exception as e:
        return [], []


async def check_account(client):
    """Get account cash balance and margin info."""
    try:
        account_id = client._account_id
        if account_id:
            bal = await client._request("GET", f"/cashBalance/getCashBalanceSnapshot?accountId={account_id}")
            return bal
    except Exception:
        pass
    return {}


async def check_fills(client, limit=10):
    """Get recent fills."""
    try:
        fills = await client._request("GET", "/fill/list")
        fills = fills or []
        # Sort by timestamp descending, take last N
        fills.sort(key=lambda f: f.get("timestamp", ""), reverse=True)
        return fills[:limit]
    except Exception:
        return []


def format_position(p):
    """Format a single position for display."""
    net = p.get("netPos", 0)
    price = p.get("netPrice", 0)
    pnl = p.get("oTE", 0)
    cid = p.get("contractId", "?")
    side = "LONG" if net > 0 else "SHORT"
    return f"  {side} {abs(net)}x @ ${price:,.2f} | Unrealized: ${pnl:+,.2f} | Contract: {cid}"


def format_order(o):
    """Format a single order for display."""
    action = o.get("action", "?")
    qty = o.get("totalQty", 0)
    price = o.get("price", 0) or o.get("stopPrice", 0) or 0
    status = o.get("ordStatus", "?")
    otype = o.get("ordType", "?")
    oid = o.get("id", "?")
    return f"  {action} {qty}x {otype} @ ${price:,.2f} | Status: {status} | ID: {oid}"


def format_fill(f):
    """Format a single fill for display."""
    action = f.get("action", "?")
    qty = f.get("qty", 0)
    price = f.get("price", 0)
    ts = f.get("timestamp", "?")
    fid = f.get("id", "?")
    return f"  {action} {qty}x @ ${price:,.2f} | {ts} | ID: {fid}"


async def main():
    parser = argparse.ArgumentParser(description="Check Tradovate positions, orders, and account")
    parser.add_argument("--orders", action="store_true", help="Include open/working orders")
    parser.add_argument("--account", action="store_true", help="Include account balance/margin")
    parser.add_argument("--fills", type=int, default=0, help="Show last N fills")
    parser.add_argument("--all", action="store_true", help="Show everything")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    if args.all:
        args.orders = True
        args.account = True
        args.fills = args.fills or 10

    config = TradovateConfig.from_env()
    client = TradovateClient(config)

    try:
        await client.connect()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Always check positions
        all_positions, open_positions = await check_positions(client)
        total_contracts = sum(abs(p.get("netPos", 0)) for p in open_positions)
        total_pnl = sum(p.get("oTE", 0) for p in open_positions)

        if args.json:
            result = {
                "timestamp": now,
                "positions": open_positions,
                "total_contracts": total_contracts,
                "total_unrealized_pnl": total_pnl,
            }
            if args.orders:
                _, working = await check_orders(client)
                result["working_orders"] = working
            if args.account:
                result["account"] = await check_account(client)
            if args.fills:
                result["recent_fills"] = await check_fills(client, args.fills)
            print(json.dumps(result, indent=2, default=str))
            return

        # Human-readable output
        print(f"═══ TRADOVATE POSITIONS ({now}) ═══")
        print(f"Account: {client._account_name or client._account_id or '?'}")
        print(f"Environment: {config.env}")
        print()

        if open_positions:
            print(f"📊 OPEN POSITIONS: {len(open_positions)} position(s), {total_contracts} contract(s)")
            for p in open_positions:
                print(format_position(p))
            print(f"\n  Total unrealized P&L: ${total_pnl:+,.2f}")
        else:
            print("📊 NO OPEN POSITIONS (flat)")

        # Risk check
        print(f"\n⚠️  RISK CHECK:")
        print(f"  Contracts: {total_contracts}/5 ({'✅' if total_contracts <= 5 else '🚨 OVER LIMIT'})")
        max_per_pos = max((abs(p.get("netPos", 0)) for p in open_positions), default=0)
        print(f"  Max per position: {max_per_pos}/1 ({'✅' if max_per_pos <= 1 else '⚠️ OVER 1'})")
        if total_pnl < 0:
            pct = abs(total_pnl) / 1000 * 100
            print(f"  Daily loss: ${abs(total_pnl):,.2f}/$1,000 ({pct:.1f}%) {'✅' if pct < 80 else '🚨'}")

        if args.orders:
            print()
            all_orders, working = await check_orders(client)
            print(f"📋 WORKING ORDERS: {len(working)}")
            if working:
                for o in working:
                    print(format_order(o))
            else:
                print("  None")

        if args.account:
            print()
            bal = await check_account(client)
            if bal:
                print(f"💰 ACCOUNT:")
                print(f"  Cash balance: ${bal.get('cashBalance', 0):,.2f}")
                print(f"  Realized P&L: ${bal.get('realizedPnL', 0):,.2f}")
                print(f"  Unrealized P&L: ${bal.get('unrealizedPnL', 0):,.2f}")
            else:
                print("💰 ACCOUNT: Could not retrieve balance")

        if args.fills:
            print()
            fills = await check_fills(client, args.fills)
            print(f"📝 RECENT FILLS (last {args.fills}):")
            if fills:
                for f in fills:
                    print(format_fill(f))
            else:
                print("  None")

        print(f"\n{'═' * 50}")
        print("VERIFIED ✅ (direct Tradovate REST API query)")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
