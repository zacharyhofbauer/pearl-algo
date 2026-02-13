#!/usr/bin/env python3
"""
Tradovate Connection Test

Verifies:
  1. Credentials load from secrets.env
  2. Authentication succeeds (access token)
  3. Account list resolves (integer account ID)
  4. Cash balance snapshot works
  5. Position query works
  6. Front-month contract resolution works (MNQ -> MNQH6 etc.)
  7. Account risk status query works

Usage:
    python scripts/test_tradovate_connection.py

Requires: TRADOVATE_USERNAME, TRADOVATE_PASSWORD, TRADOVATE_CID, TRADOVATE_SEC
          in ~/.config/pearlalgo/secrets.env or environment.
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

    results = {"passed": 0, "failed": 0}

    # ── Test 1: Config loading ────────────────────────────────────────
    header("1. Configuration")
    try:
        config = TradovateConfig.from_env()
        config.validate()
        ok(f"Username: {config.username}")
        ok(f"CID: {config.cid}")
        ok(f"Environment: {config.env} -> {config.rest_url}")
        ok(f"Device ID: {config.device_id[:16]}...")
        results["passed"] += 1
    except ValueError as e:
        fail(f"Config validation failed: {e}")
        results["failed"] += 1
        print("\nCannot continue without valid credentials.")
        return results

    # ── Test 2: Authentication ────────────────────────────────────────
    header("2. Authentication")
    client = TradovateClient(config)
    try:
        # Create session manually for just auth test
        import aiohttp
        client._session = aiohttp.ClientSession(
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        await client._authenticate()

        if client._access_token:
            ok(f"Access token received (expires: {client._token_expiry})")
            ok(f"User ID: {client._user_id}")
            # Show token preview (first 20 chars only)
            token_preview = client._access_token[:20] + "..."
            info(f"Token preview: {token_preview}")
            results["passed"] += 1
        else:
            fail("No access token returned")
            results["failed"] += 1
    except TradovateAuthError as e:
        fail(f"Auth error: {e}")
        results["failed"] += 1
        await client._session.close()
        return results
    except Exception as e:
        fail(f"Unexpected error: {e}")
        results["failed"] += 1
        await client._session.close()
        return results

    # ── Test 3: Account list ──────────────────────────────────────────
    header("3. Account Resolution")
    try:
        accounts = await client.get_accounts()
        if accounts:
            ok(f"Found {len(accounts)} account(s)")
            for acct in accounts:
                active = "active" if acct.get("active") else "inactive"
                info(f"  {acct.get('name')} (id={acct.get('id')}, {active})")

            # Resolve account
            await client._resolve_account()
            ok(f"Selected account: {client.account_name} (id={client.account_id})")
            results["passed"] += 1
        else:
            fail("No accounts returned")
            results["failed"] += 1
    except Exception as e:
        fail(f"Account query failed: {e}")
        results["failed"] += 1

    # ── Test 4: Cash balance ──────────────────────────────────────────
    header("4. Cash Balance")
    try:
        balance = await client.get_cash_balance_snapshot()
        if balance:
            ok(f"Balance snapshot received")
            # The response structure varies; show what we got
            for key in ["totalCashValue", "realizedPnl", "unrealizedPnl", "cashBalance", "netLiq"]:
                val = balance.get(key)
                if val is not None:
                    info(f"  {key}: ${val:,.2f}" if isinstance(val, (int, float)) else f"  {key}: {val}")
            # Also try the raw response keys
            if isinstance(balance, dict):
                for key, val in balance.items():
                    if key not in ["totalCashValue", "realizedPnl", "unrealizedPnl", "cashBalance", "netLiq"]:
                        if isinstance(val, (int, float)):
                            info(f"  {key}: {val}")
            results["passed"] += 1
        else:
            fail("Empty balance response")
            results["failed"] += 1
    except Exception as e:
        fail(f"Balance query failed: {e}")
        results["failed"] += 1

    # ── Test 5: Positions ─────────────────────────────────────────────
    header("5. Positions")
    try:
        positions = await client.get_positions()
        ok(f"Position query returned {len(positions)} position(s)")
        for pos in positions:
            net = pos.get("netPos", 0)
            contract_id = pos.get("contractId")
            info(f"  contractId={contract_id}, netPos={net}")
        results["passed"] += 1
    except Exception as e:
        fail(f"Position query failed: {e}")
        results["failed"] += 1

    # ── Test 6: Contract resolution ───────────────────────────────────
    header("6. Front-Month Contract Resolution")
    try:
        front_month = await client.resolve_front_month("MNQ")
        ok(f"MNQ front-month: {front_month}")
        results["passed"] += 1
    except Exception as e:
        fail(f"Contract resolution failed: {e}")
        info("This may be normal if the contract name format differs on demo")
        results["failed"] += 1

    # Try NQ too
    try:
        front_nq = await client.resolve_front_month("NQ")
        ok(f"NQ front-month: {front_nq}")
    except Exception as e:
        info(f"NQ resolution: {e} (non-critical)")

    # ── Test 7: Risk status ───────────────────────────────────────────
    header("7. Account Risk Status")
    try:
        risk_status = await client.get_account_risk_status()
        ok(f"Risk status query returned {len(risk_status)} item(s)")
        for item in risk_status:
            info(f"  adminAction={item.get('adminAction')}, autoLiqCount={item.get('autoLiquidateThreshold')}")
        results["passed"] += 1
    except Exception as e:
        fail(f"Risk status query failed: {e}")
        info("This may fail with 'Denied' if Account Risk Settings permission is not granted")
        results["failed"] += 1

    # ── Cleanup ───────────────────────────────────────────────────────
    if client._session and not client._session.closed:
        await client._session.close()

    # ── Summary ───────────────────────────────────────────────────────
    header("RESULTS")
    total = results["passed"] + results["failed"]
    print(f"  Passed: {results['passed']}/{total}")
    print(f"  Failed: {results['failed']}/{total}")
    if results["failed"] == 0:
        print(f"\n  All tests passed! Tradovate connection is working.")
        print(f"  Your account: {client.account_name} (id={client.account_id})")
        print(f"\n  Next steps:")
        print(f"    1. Set execution.enabled=true in config/accounts/tradovate_paper.yaml")
        print(f"    2. Launch: ./scripts/lifecycle/tv_paper_eval.sh start --background")
        print(f"    3. View: http://localhost:3000?api_port=8001")
    else:
        print(f"\n  Some tests failed. Check the errors above.")

    return results


if __name__ == "__main__":
    results = asyncio.run(main())
    sys.exit(0 if results.get("failed", 1) == 0 else 1)
