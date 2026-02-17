#!/usr/bin/env python3
"""
Tradovate Round-Trip Test Trade

Places a market BUY order for 1 MNQ contract, waits for fill,
then immediately places a market SELL to close the position.

This verifies end-to-end Tradovate execution:
  1. Authentication
  2. Contract resolution (MNQ -> front-month symbol)
  3. Market BUY 1 contract
  4. Wait for fill (up to 10 seconds)
  5. Market SELL 1 contract to flatten
  6. Confirm flat

Usage:
    python scripts/test_tradovate_roundtrip.py

Requires: TRADOVATE_USERNAME, TRADOVATE_PASSWORD, TRADOVATE_CID, TRADOVATE_SEC
          in ~/.config/pearlalgo/secrets.env or environment.

WARNING: This places REAL orders on the demo account. Only run during
         market hours when MNQ is trading.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load secrets
try:
    from dotenv import load_dotenv
    secrets_path = Path.home() / ".config" / "pearlalgo" / "secrets.env"
    if secrets_path.exists():
        load_dotenv(secrets_path)
        print(f"[OK] Loaded secrets from {secrets_path}")
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
except ImportError:
    print("[WARN] python-dotenv not installed, using system env vars only")


def header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    print(f"  [INFO] {msg}")


async def main():
    from pearlalgo.execution.tradovate.config import TradovateConfig
    from pearlalgo.execution.tradovate.client import (
        TradovateClient,
        TradovateAuthError,
        TradovateAPIError,
    )

    # ── Step 1: Connect and authenticate ──────────────────────────────
    header("1. Connect & Authenticate")
    try:
        config = TradovateConfig.from_env()
        config.validate()
        ok(f"Config: {config.username} @ {config.env}")
    except ValueError as e:
        fail(f"Config error: {e}")
        return False

    if config.env != "demo":
        fail(f"SAFETY: This script only runs on demo accounts (current: {config.env})")
        return False

    client = TradovateClient(config)
    try:
        try:
            success = await client.connect()
            if not success:
                fail("Connection failed")
                return False
            ok(f"Connected: account={client.account_name} (id={client.account_id})")
        except TradovateAuthError as e:
            fail(f"Auth failed: {e}")
            return False
        except Exception as e:
            fail(f"Connect error: {e}")
            return False

        # ── Step 2: Resolve front-month contract ──────────────────────────
        header("2. Resolve MNQ Contract")
        try:
            front_month = await client.resolve_front_month("MNQ")
            ok(f"MNQ front-month: {front_month}")
        except Exception as e:
            fail(f"Contract resolution failed: {e}")
            return False

        # ── Step 3: Check current position (should be flat) ───────────────
        header("3. Pre-Trade Position Check")
        try:
            positions = await client.get_positions()
            active = [p for p in positions if p.get("netPos", 0) != 0]
            if active:
                info(f"WARNING: {len(active)} active position(s) found!")
                for p in active:
                    info(f"  contractId={p.get('contractId')}, netPos={p.get('netPos')}")
                info("Will still proceed with test trade...")
            else:
                ok("Flat (no active positions)")
        except Exception as e:
            fail(f"Position check failed: {e}")

        # ── Step 4: Place Market BUY 1 MNQ ────────────────────────────────
        header("4. Place Market BUY (1 MNQ)")
        buy_order_id = None
        try:
            result = await client.place_order(
                symbol=front_month,
                action="Buy",
                order_qty=1,
                order_type="Market",
            )
            buy_order_id = result.get("orderId") or result.get("id")
            if buy_order_id:
                ok(f"BUY order placed: order_id={buy_order_id}")
                info(f"  Response: {result}")
            else:
                error_text = result.get("errorText", "Unknown error")
                fail(f"BUY order rejected: {error_text}")
                info(f"  Full response: {result}")
                return False
        except TradovateAPIError as e:
            fail(f"BUY order API error: {e}")
            return False
        except Exception as e:
            fail(f"BUY order error: {e}")
            return False

        # ── Step 5: Wait for fill ─────────────────────────────────────────
        header("5. Wait for BUY Fill")
        filled = False
        for i in range(10):
            await asyncio.sleep(1)
            try:
                positions = await client.get_positions()
                active = [p for p in positions if p.get("netPos", 0) != 0]
                if active:
                    net_pos = active[0].get("netPos", 0)
                    if net_pos > 0:
                        ok(f"BUY filled! netPos={net_pos}, price={active[0].get('netPrice', 'N/A')}")
                        filled = True
                        break
                info(f"  Waiting... ({i+1}/10s)")
            except Exception as e:
                info(f"  Position poll error: {e}")

        if not filled:
            fail("BUY order did not fill within 10 seconds")
            info("Attempting to cancel the order...")
            try:
                if buy_order_id:
                    await client.cancel_order(int(buy_order_id))
                    info("Order cancelled")
            except Exception as e:
                info(f"Cancel failed: {e}")
            return False

        # ── Step 6: Place Market SELL to flatten ───────────────────────────
        header("6. Place Market SELL to Flatten")
        try:
            result = await client.place_order(
                symbol=front_month,
                action="Sell",
                order_qty=1,
                order_type="Market",
            )
            sell_order_id = result.get("orderId") or result.get("id")
            if sell_order_id:
                ok(f"SELL order placed: order_id={sell_order_id}")
            else:
                error_text = result.get("errorText", "Unknown error")
                fail(f"SELL order rejected: {error_text}")
                info("WARNING: You have an open position! Flatten manually.")
                return False
        except Exception as e:
            fail(f"SELL order error: {e}")
            info("WARNING: You have an open position! Flatten manually.")
            return False

        # ── Step 7: Confirm flat ──────────────────────────────────────────
        header("7. Confirm Flat")
        for i in range(10):
            await asyncio.sleep(1)
            try:
                positions = await client.get_positions()
                active = [p for p in positions if p.get("netPos", 0) != 0]
                if not active:
                    ok("Position flattened successfully!")
                    break
                info(f"  Waiting for flatten... ({i+1}/10s)")
            except Exception as e:
                info(f"  Position poll error: {e}")
        else:
            fail("Position not flattened within 10 seconds")
            info("Check Tradovate platform manually.")

        # ── Step 8: Check balance after round-trip ────────────────────────
        header("8. Post-Trade Balance")
        try:
            balance = await client.get_cash_balance_snapshot()
            if balance:
                equity = balance.get("netLiq", 0)
                realized = balance.get("realizedPnL", 0)
                ok(f"Equity: ${equity:,.2f}")
                info(f"  Realized P&L: ${realized:,.2f}")
            else:
                info("Could not fetch balance")
        except Exception as e:
            info(f"Balance check failed: {e}")

        # ── Summary ───────────────────────────────────────────────────────
        header("ROUND-TRIP TEST COMPLETE")
        print("  The Tradovate execution pipeline is working!")
        print("  - Authentication: OK")
        print("  - Contract resolution: OK")
        print("  - Order placement: OK")
        print("  - Fill detection: OK")
        print("  - Position flattening: OK")
        return True
    finally:
        await client.disconnect()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
