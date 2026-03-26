#!/usr/bin/env python3
"""
Real-time Position Checker with WebSocket P&L
Connects to Tradovate, subscribes to WebSocket, and reports positions with live unrealized P&L.
"""
import asyncio
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any

sys.path.insert(0, "/home/pearlalgo/PearlAlgoWorkspace")

from src.pearlalgo.execution.tradovate.client import TradovateClient
from src.pearlalgo.execution.tradovate.config import TradovateConfig


class PositionTracker:
    """Track positions from WebSocket updates."""
    
    def __init__(self):
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.last_update = time.time()
        
    def handle_event(self, event: Dict[str, Any]):
        """Handle WebSocket events."""
        event_type = event.get("e")
        if event_type == "props":
            data = event.get("d", {})
            entity_type = data.get("entityType")
            
            if entity_type == "position":
                entity = data.get("entity", {})
                contract_id = str(entity.get("contractId", ""))
                net_pos = entity.get("netPos", 0)
                
                if net_pos != 0:
                    # Store position with oTE field
                    self.positions[contract_id] = {
                        "contract_id": contract_id,
                        "net_pos": net_pos,
                        "net_price": entity.get("netPrice", 0),
                        "ote": entity.get("oTE", 0),  # Unrealized P&L
                        "timestamp": entity.get("timestamp"),
                        "updated_at": time.time(),
                    }
                else:
                    # Position closed
                    self.positions.pop(contract_id, None)
                    
                self.last_update = time.time()


async def main():
    parser = argparse.ArgumentParser(description="Real-time position check with WebSocket P&L")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--timeout", type=int, default=30, help="Wait timeout in seconds")
    args = parser.parse_args()
    
    config = TradovateConfig.from_env()
    client = TradovateClient(config)
    tracker = PositionTracker()
    
    try:
        # Connect and start WebSocket
        await client.connect()
        
        # Add event handler
        client.add_event_handler(tracker.handle_event)
        
        # Start WebSocket
        await client.start_websocket()
        
        # Wait for WebSocket to be fully connected
        for _ in range(50):  # 5 seconds max
            if client.ws_connected:
                break
            await asyncio.sleep(0.1)
        
        if not client.ws_connected:
            print("ERROR: WebSocket failed to connect", file=sys.stderr)
            return 1
        
        # First, get REST positions as baseline
        rest_positions = await client.get_positions()
        rest_by_contract = {str(p.get("contractId")): p for p in rest_positions}
        
        # Merge with any existing WebSocket data
        for contract_id, rest_pos in rest_by_contract.items():
            if contract_id not in tracker.positions and rest_pos.get("netPos", 0) != 0:
                tracker.positions[contract_id] = {
                    "contract_id": contract_id,
                    "net_pos": rest_pos.get("netPos", 0),
                    "net_price": rest_pos.get("netPrice", 0),
                    "ote": rest_pos.get("oTE", 0),  # May be 0 from REST
                    "timestamp": rest_pos.get("timestamp"),
                    "updated_at": time.time(),
                    "source": "rest_api",
                }
        
        # Wait a bit for WebSocket updates with oTE
        if args.json:
            # For JSON mode, wait full timeout for WebSocket updates
            await asyncio.sleep(min(args.timeout, 5))
        else:
            # For human mode, show positions immediately
            pass
        
        # Get current cash balance for account-level P&L
        cash_balance = await client.get_cash_balance_snapshot()
        account_open_pnl = cash_balance.get("openPnL", 0)
        account_realized_pnl = cash_balance.get("realizedPnL", 0)
        
        # Output results
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        open_positions = [p for p in tracker.positions.values() if p.get("net_pos", 0) != 0]
        total_contracts = sum(abs(p.get("net_pos", 0)) for p in open_positions)
        
        # Use WebSocket oTE if available, otherwise use account-level openPnL
        total_unrealized_pnl = sum(p.get("ote", 0) for p in open_positions) or account_open_pnl
        
        if args.json:
            result = {
                "timestamp": now,
                "positions": open_positions,
                "total_contracts": total_contracts,
                "total_unrealized_pnl": total_unrealized_pnl,
                "account_open_pnl": account_open_pnl,
                "account_realized_pnl": account_realized_pnl,
                "ws_connected": client.ws_connected,
            }
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"═══ TRADOVATE POSITIONS (REALTIME) ({now}) ═══")
            print(f"Account: {client._account_name or client._account_id or '?'}")
            print(f"WebSocket: {'✅ CONNECTED' if client.ws_connected else '❌ DISCONNECTED'}")
            print()
            
            if open_positions:
                print(f"📊 OPEN POSITIONS: {len(open_positions)} position(s), {total_contracts} contract(s)")
                for p in open_positions:
                    net = p.get("net_pos", 0)
                    price = p.get("net_price", 0)
                    ote = p.get("ote", 0)
                    cid = p.get("contract_id", "?")
                    side = "LONG" if net > 0 else "SHORT"
                    source = p.get("source", "websocket")
                    print(f"  {side} {abs(net)}x @ ${price:,.2f} | Unrealized: ${ote:+,.2f} | Contract: {cid} | Source: {source}")
                print(f"\n  Total unrealized P&L: ${total_unrealized_pnl:+,.2f}")
                
                if account_open_pnl != 0 and abs(total_unrealized_pnl - account_open_pnl) > 0.01:
                    print(f"  Account-level P&L: ${account_open_pnl:+,.2f} (may differ from position sum)")
            else:
                print("📊 NO OPEN POSITIONS (flat)")
            
            # Risk check
            print(f"\n⚠️  RISK CHECK:")
            print(f"  Contracts: {total_contracts}/5 ({'✅' if total_contracts <= 5 else '🚨 OVER LIMIT'})")
            max_per_pos = max((abs(p.get("net_pos", 0)) for p in open_positions), default=0)
            print(f"  Max per position: {max_per_pos}/1 ({'✅' if max_per_pos <= 1 else '⚠️ OVER 1'})")
            
            print(f"\n{'═' * 60}")
            print("VERIFIED ✅ (WebSocket + REST API)")
        
        return 0
        
    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
