#!/usr/bin/env python3
"""
Data Quality Comparison: IBKR vs Tradovate

Fetches historical MNQ candles from both brokers for the same time window
and compares accuracy, latency, and completeness.

Usage:
    # Ensure IBKR Gateway is running and Tradovate credentials are in secrets.env
    python scripts/testing/compare_data_quality.py

    # Custom options
    python scripts/testing/compare_data_quality.py --bars 200 --symbol MNQ --timeframe 1m

Output:
    - Candle-by-candle comparison (OHLCV differences)
    - Missing bars on each side
    - Volume correlation
    - Price deviation statistics
    - Recommendation: which data source to use

Requires:
    - IBKR Gateway running on localhost:4002
    - Tradovate credentials in environment (TRADOVATE_USERNAME, TRADOVATE_PASSWORD, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load secrets
try:
    from dotenv import load_dotenv
    secrets_path = Path.home() / ".config" / "pearlalgo" / "secrets.env"
    if secrets_path.exists():
        load_dotenv(secrets_path, override=False)
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
except ImportError:
    pass


# ---------------------------------------------------------------------------
# IBKR data fetch
# ---------------------------------------------------------------------------

async def fetch_ibkr_candles(
    symbol: str, bars: int, timeframe: str, host: str, port: int, client_id: int
) -> pd.DataFrame | None:
    """Fetch historical candles from IBKR Gateway via ib_insync."""
    try:
        from ib_insync import IB, Contract, util
    except ImportError:
        print("[IBKR] ib_insync not installed, skipping IBKR data fetch")
        return None

    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=15)
        print(f"[IBKR] Connected to {host}:{port} (clientId={client_id})")

        # Map timeframe to IB bar size
        tf_map = {"1m": "1 min", "5m": "5 mins", "15m": "15 mins", "1h": "1 hour"}
        bar_size = tf_map.get(timeframe, "1 min")

        # Calculate duration string
        tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}.get(timeframe, 1)
        total_minutes = bars * tf_minutes
        if total_minutes > 1440:
            duration_str = f"{total_minutes // 1440 + 1} D"
        else:
            duration_str = f"{total_minutes * 60} S"

        contract = Contract(symbol=symbol, secType="FUT", exchange="CME", currency="USD")
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            print(f"[IBKR] Could not qualify contract for {symbol}")
            return None

        print(f"[IBKR] Fetching {bars} bars of {symbol} {timeframe} data...")
        ibkr_bars = await ib.reqHistoricalDataAsync(
            qualified[0],
            endDateTime="",
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=False,
            formatDate=2,
        )

        if not ibkr_bars:
            print("[IBKR] No bars returned")
            return None

        df = util.df(ibkr_bars)
        df = df.rename(columns={"date": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        df = df[["open", "high", "low", "close", "volume"]].tail(bars)
        print(f"[IBKR] Got {len(df)} bars")
        return df

    except Exception as e:
        print(f"[IBKR] Error: {e}")
        return None
    finally:
        if ib.isConnected():
            ib.disconnect()


# ---------------------------------------------------------------------------
# Tradovate data fetch
# ---------------------------------------------------------------------------

async def fetch_tradovate_candles(
    symbol: str, bars: int, timeframe: str
) -> pd.DataFrame | None:
    """Fetch historical candles from Tradovate market data API."""
    try:
        import aiohttp
    except ImportError:
        print("[TV] aiohttp not installed, skipping Tradovate data fetch")
        return None

    try:
        from pearlalgo.execution.tradovate.config import TradovateConfig
    except ImportError:
        print("[TV] TradovateConfig not found")
        return None

    config = TradovateConfig.from_env()
    try:
        config.validate()
    except ValueError as e:
        print(f"[TV] Config validation failed: {e}")
        return None

    # Map timeframe to Tradovate chart parameters
    tf_map = {
        "1m": {"elementSize": 1, "elementSizeUnit": "MinuteBar"},
        "5m": {"elementSize": 5, "elementSizeUnit": "MinuteBar"},
        "15m": {"elementSize": 15, "elementSizeUnit": "MinuteBar"},
        "1h": {"elementSize": 60, "elementSizeUnit": "MinuteBar"},
    }
    chart_params = tf_map.get(timeframe)
    if chart_params is None:
        print(f"[TV] Unsupported timeframe: {timeframe}")
        return None

    async with aiohttp.ClientSession() as session:
        # Authenticate
        auth_url = f"{config.rest_url}/auth/accesstokenrequest"
        auth_payload = {
            "name": config.username,
            "password": config.password,
            "appId": config.app_id,
            "appVersion": config.app_version,
            "cid": config.cid,
            "sec": config.sec,
            "deviceId": config.device_id,
        }

        try:
            async with session.post(auth_url, json=auth_payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[TV] Auth failed ({resp.status}): {text}")
                    return None
                auth_data = await resp.json()

            access_token = auth_data.get("accessToken")
            if not access_token:
                print(f"[TV] No access token in auth response")
                return None

            print(f"[TV] Authenticated as {config.username}")

            # Resolve contract ID for the symbol
            headers = {"Authorization": f"Bearer {access_token}"}
            contract_url = f"{config.rest_url}/contract/suggest"
            async with session.get(
                contract_url, headers=headers, params={"t": symbol, "l": 1}
            ) as resp:
                contracts = await resp.json()

            if not contracts:
                print(f"[TV] No contract found for {symbol}")
                return None

            contract_id = contracts[0].get("id")
            contract_name = contracts[0].get("name", symbol)
            print(f"[TV] Resolved {symbol} -> contract {contract_name} (id={contract_id})")

            # Fetch chart data via market data WebSocket
            # Tradovate provides historical bars via md/getChart
            md_url = config.md_url
            print(f"[TV] Connecting to market data WebSocket: {md_url}")

            async with session.ws_connect(md_url) as ws:
                # Authorize on MD WebSocket
                auth_msg = f"authorize\n0\n\n{access_token}"
                await ws.send_str(auth_msg)

                # Wait for auth response
                auth_response = await asyncio.wait_for(ws.receive(), timeout=10)
                if "s" not in str(auth_response.data) or "200" not in str(auth_response.data):
                    print(f"[TV] MD auth response: {auth_response.data}")

                # Request chart data
                chart_request = {
                    "symbol": contract_name,
                    "chartDescription": {
                        "underlyingType": "MinuteBar",
                        "elementSize": chart_params["elementSize"],
                        "elementSizeUnit": chart_params["elementSizeUnit"],
                        "withHistogram": True,
                    },
                    "timeRange": {
                        "closestTimestamp": datetime.now(timezone.utc).isoformat(),
                        "asFarAsTimestamp": (
                            datetime.now(timezone.utc) - timedelta(hours=24)
                        ).isoformat(),
                    },
                }
                chart_msg = f"md/getChart\n1\n\n{json.dumps(chart_request)}"
                await ws.send_str(chart_msg)

                # Collect bars from responses
                all_bars = []
                timeout_at = asyncio.get_event_loop().time() + 15

                while asyncio.get_event_loop().time() < timeout_at:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=5)
                        data_str = str(msg.data)

                        # Parse Tradovate's response format
                        if "charts" in data_str or "bars" in data_str:
                            # Try to extract JSON from the response
                            lines = data_str.split("\n")
                            for line in lines:
                                line = line.strip()
                                if line.startswith("{") or line.startswith("["):
                                    try:
                                        parsed = json.loads(line)
                                        if isinstance(parsed, dict):
                                            charts = parsed.get("charts", [])
                                            for chart in charts:
                                                bars_data = chart.get("bars", [])
                                                all_bars.extend(bars_data)
                                            if charts:
                                                break
                                    except json.JSONDecodeError:
                                        pass

                        # Check if we got an end-of-history marker
                        if "eoh" in data_str.lower():
                            break

                    except asyncio.TimeoutError:
                        break

                if not all_bars:
                    print("[TV] No bars received from market data WebSocket")
                    return None

                # Convert to DataFrame
                rows = []
                for bar in all_bars:
                    ts = bar.get("timestamp")
                    if ts:
                        rows.append({
                            "timestamp": pd.to_datetime(ts, utc=True),
                            "open": float(bar.get("open", 0)),
                            "high": float(bar.get("high", 0)),
                            "low": float(bar.get("low", 0)),
                            "close": float(bar.get("close", 0)),
                            "volume": int(bar.get("upVolume", 0) + bar.get("downVolume", 0)),
                        })

                if not rows:
                    print("[TV] Could not parse any bars from response")
                    return None

                df = pd.DataFrame(rows)
                df = df.set_index("timestamp").sort_index().tail(bars)
                print(f"[TV] Got {len(df)} bars")
                return df

        except Exception as e:
            print(f"[TV] Error: {e}")
            return None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_dataframes(
    ibkr_df: pd.DataFrame | None,
    tv_df: pd.DataFrame | None,
    symbol: str,
    timeframe: str,
) -> dict:
    """Compare IBKR and Tradovate candles and produce a report."""
    report: dict = {
        "symbol": symbol,
        "timeframe": timeframe,
        "ibkr_available": ibkr_df is not None and len(ibkr_df) > 0,
        "tv_available": tv_df is not None and len(tv_df) > 0,
    }

    if ibkr_df is None or len(ibkr_df) == 0:
        report["recommendation"] = "IBKR data unavailable. Use Tradovate if available."
        return report

    if tv_df is None or len(tv_df) == 0:
        report["recommendation"] = "Tradovate data unavailable. Use IBKR."
        return report

    report["ibkr_bars"] = len(ibkr_df)
    report["tv_bars"] = len(tv_df)

    # Find overlapping timestamps (within 30s tolerance for alignment)
    ibkr_idx = set(ibkr_df.index)
    tv_idx = set(tv_df.index)
    common = sorted(ibkr_idx & tv_idx)

    report["common_bars"] = len(common)
    report["ibkr_only_bars"] = len(ibkr_idx - tv_idx)
    report["tv_only_bars"] = len(tv_idx - ibkr_idx)

    if len(common) < 10:
        report["recommendation"] = (
            f"Only {len(common)} overlapping bars found. "
            "Timestamps may not align between brokers. "
            "Cannot make a reliable comparison."
        )
        return report

    # Compare OHLCV on common timestamps
    ibkr_common = ibkr_df.loc[common]
    tv_common = tv_df.loc[common]

    price_diffs = {}
    for col in ["open", "high", "low", "close"]:
        diff = (ibkr_common[col] - tv_common[col]).abs()
        price_diffs[col] = {
            "mean_diff": float(diff.mean()),
            "max_diff": float(diff.max()),
            "bars_with_diff_gt_1pt": int((diff > 1.0).sum()),
        }

    report["price_differences"] = price_diffs

    # Volume comparison
    vol_corr = ibkr_common["volume"].corr(tv_common["volume"])
    report["volume_correlation"] = float(vol_corr) if pd.notna(vol_corr) else 0.0

    # Overall quality score
    avg_close_diff = price_diffs["close"]["mean_diff"]
    completeness_ibkr = len(ibkr_df) / max(len(ibkr_df), len(tv_df))
    completeness_tv = len(tv_df) / max(len(ibkr_df), len(tv_df))

    report["summary"] = {
        "avg_close_price_diff_points": avg_close_diff,
        "ibkr_completeness_pct": round(completeness_ibkr * 100, 1),
        "tv_completeness_pct": round(completeness_tv * 100, 1),
        "volume_correlation_pct": round(report["volume_correlation"] * 100, 1),
    }

    # Recommendation
    if avg_close_diff < 0.5 and completeness_tv > 0.95:
        report["recommendation"] = (
            "TRADOVATE DATA IS GOOD ENOUGH. "
            f"Average close price difference is only {avg_close_diff:.2f} points. "
            "Recommend: Single Tradovate agent (Path A)."
        )
    elif avg_close_diff < 2.0 and completeness_tv > 0.90:
        report["recommendation"] = (
            "TRADOVATE DATA IS ACCEPTABLE. "
            f"Average close price difference is {avg_close_diff:.2f} points. "
            "Recommend: Single Tradovate agent (Path A) with monitoring."
        )
    elif completeness_ibkr > completeness_tv * 1.1:
        report["recommendation"] = (
            "IBKR DATA IS MORE COMPLETE. "
            f"IBKR has {report['ibkr_bars']} bars vs Tradovate {report['tv_bars']}. "
            "Recommend: IBKR data + Tradovate execution (Path B)."
        )
    else:
        report["recommendation"] = (
            "MIXED RESULTS. "
            f"Close price diff: {avg_close_diff:.2f} pts, "
            f"IBKR completeness: {completeness_ibkr:.0%}, "
            f"TV completeness: {completeness_tv:.0%}. "
            "Recommend: Run for a longer period and re-evaluate."
        )

    return report


def print_report(report: dict) -> None:
    """Pretty-print the comparison report."""
    print("\n" + "=" * 70)
    print(f"  DATA QUALITY COMPARISON: {report['symbol']} {report['timeframe']}")
    print("=" * 70)

    print(f"\n  IBKR available:     {'YES' if report.get('ibkr_available') else 'NO'}")
    print(f"  Tradovate available: {'YES' if report.get('tv_available') else 'NO'}")

    if "ibkr_bars" in report:
        print(f"\n  IBKR bars:     {report['ibkr_bars']}")
        print(f"  Tradovate bars: {report['tv_bars']}")
        print(f"  Common bars:    {report['common_bars']}")
        print(f"  IBKR only:      {report['ibkr_only_bars']}")
        print(f"  Tradovate only: {report['tv_only_bars']}")

    if "price_differences" in report:
        print("\n  Price Differences (points):")
        for col, stats in report["price_differences"].items():
            print(
                f"    {col:>5}: mean={stats['mean_diff']:.3f}  "
                f"max={stats['max_diff']:.3f}  "
                f"bars>1pt={stats['bars_with_diff_gt_1pt']}"
            )

    if "summary" in report:
        s = report["summary"]
        print(f"\n  Volume correlation:  {s['volume_correlation_pct']}%")
        print(f"  IBKR completeness:   {s['ibkr_completeness_pct']}%")
        print(f"  TV completeness:     {s['tv_completeness_pct']}%")

    print(f"\n  RECOMMENDATION: {report.get('recommendation', 'N/A')}")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Compare IBKR vs Tradovate data quality")
    parser.add_argument("--symbol", default="MNQ", help="Symbol to compare (default: MNQ)")
    parser.add_argument("--bars", type=int, default=300, help="Number of bars to compare (default: 300)")
    parser.add_argument("--timeframe", default="1m", help="Timeframe: 1m, 5m, 15m, 1h (default: 1m)")
    parser.add_argument("--ibkr-host", default="127.0.0.1", help="IBKR Gateway host")
    parser.add_argument("--ibkr-port", type=int, default=4002, help="IBKR Gateway port")
    parser.add_argument("--ibkr-client-id", type=int, default=99, help="IBKR client ID (use unused ID)")
    parser.add_argument("--output", default=None, help="Save report to JSON file")
    args = parser.parse_args()

    print(f"Comparing {args.symbol} {args.timeframe} data quality ({args.bars} bars)")
    print(f"IBKR: {args.ibkr_host}:{args.ibkr_port} (clientId={args.ibkr_client_id})")
    print()

    # Fetch from both sources
    ibkr_df = await fetch_ibkr_candles(
        args.symbol, args.bars, args.timeframe,
        args.ibkr_host, args.ibkr_port, args.ibkr_client_id,
    )
    tv_df = await fetch_tradovate_candles(args.symbol, args.bars, args.timeframe)

    # Compare
    report = compare_dataframes(ibkr_df, tv_df, args.symbol, args.timeframe)
    print_report(report)

    # Save report if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Report saved to {output_path}")

    return report


if __name__ == "__main__":
    asyncio.run(main())
