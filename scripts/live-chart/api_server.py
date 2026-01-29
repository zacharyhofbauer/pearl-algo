#!/usr/bin/env python3
"""
Live Main Chart API Server - Serves OHLCV data for the TradingView chart.

Endpoints:
  GET /api/candles?symbol=MNQ&timeframe=5m&bars=72
  GET /api/state - Returns current agent state
  GET /api/trades - Returns recent trades
  GET /health - Health check

Usage:
  python scripts/live-chart/api_server.py --market NQ --port 8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from fastapi import FastAPI, Query, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    print("ERROR: FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_MARKET = "NQ"

# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------

def _resolve_state_dir(market: str) -> Path:
    """Resolve the state directory for a given market."""
    market_upper = str(market or "NQ").strip().upper()
    env_state_dir = os.getenv("PEARLALGO_STATE_DIR")
    if env_state_dir:
        return Path(env_state_dir)
    return PROJECT_ROOT / "data" / "agent_state" / market_upper


def _load_json_file(path: Path) -> Dict[str, Any]:
    """Load a JSON file, returning empty dict on error."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _load_jsonl_file(path: Path, max_lines: int = 100) -> List[Dict[str, Any]]:
    """Load last N lines from a JSONL file."""
    if not path.exists():
        return []
    try:
        lines = path.read_text().strip().split("\n")
        result = []
        for line in lines[-max_lines:]:
            if line.strip():
                try:
                    result.append(json.loads(line))
                except Exception:
                    pass
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Data Provider (simplified - reads from IBKR or returns mock data)
# ---------------------------------------------------------------------------

_data_provider = None
_data_provider_error: Optional[str] = None


def _get_data_provider():
    """Lazy-load the IBKR data provider."""
    global _data_provider, _data_provider_error
    
    if _data_provider is not None:
        return _data_provider
    
    if _data_provider_error is not None:
        return None
    
    try:
        from pearlalgo.data_providers.factory import create_provider
        
        provider = create_provider(
            provider_type="ibkr",
            config={
                "host": os.getenv("IB_HOST", "127.0.0.1"),
                "port": int(os.getenv("IB_PORT", "4002")),
                "client_id": int(os.getenv("IB_CLIENT_ID_LIVE_CHART", "99")),
            }
        )
        _data_provider = provider
        return provider
    except Exception as e:
        _data_provider_error = str(e)
        return None


def _fetch_candles(
    symbol: str,
    timeframe: str = "5m",
    bars: int = 72,
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV candles from IBKR or return mock data.
    
    Returns data in TradingView Lightweight Charts format:
    [{"time": 1706500000, "open": 26200, "high": 26210, "low": 26195, "close": 26205}, ...]
    """
    provider = _get_data_provider()
    
    if provider is not None:
        try:
            # Calculate time range based on bars and timeframe
            tf_minutes = {
                "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440
            }.get(timeframe, 5)
            
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=tf_minutes * bars * 1.5)  # Extra buffer
            
            df = provider.fetch_historical(
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
            )
            
            if df is not None and not df.empty:
                # Convert to TradingView format
                candles = []
                for idx, row in df.tail(bars).iterrows():
                    ts = idx if isinstance(idx, (int, float)) else int(idx.timestamp())
                    candles.append({
                        "time": ts,
                        "open": float(row.get("Open", row.get("open", 0))),
                        "high": float(row.get("High", row.get("high", 0))),
                        "low": float(row.get("Low", row.get("low", 0))),
                        "close": float(row.get("Close", row.get("close", 0))),
                    })
                return candles
        except Exception as e:
            print(f"Warning: Failed to fetch from IBKR: {e}")
    
    # Return mock data as fallback
    return _generate_mock_candles(bars)


def _generate_mock_candles(bars: int = 72) -> List[Dict[str, Any]]:
    """Generate mock candle data for testing when IBKR is unavailable."""
    import random
    
    candles = []
    base_time = int(datetime.now(timezone.utc).timestamp()) - (bars * 300)  # 5m bars
    price = 26200.0  # Starting price
    
    for i in range(bars):
        ts = base_time + (i * 300)
        
        # Random walk
        change = random.uniform(-20, 20)
        open_price = price
        close_price = price + change
        high_price = max(open_price, close_price) + random.uniform(0, 10)
        low_price = min(open_price, close_price) - random.uniform(0, 10)
        
        candles.append({
            "time": ts,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
        })
        
        price = close_price
    
    return candles


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PEARL Live Chart API",
    description="API for the PEARL Live Main Chart",
    version="1.0.0",
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
_market: str = DEFAULT_MARKET
_state_dir: Optional[Path] = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "market": _market}


@app.get("/api/candles")
async def get_candles(
    symbol: str = Query(default="MNQ", description="Symbol to fetch"),
    timeframe: str = Query(default="5m", description="Timeframe (1m, 5m, 15m, 1h)"),
    bars: int = Query(default=72, ge=10, le=500, description="Number of bars"),
):
    """
    Get OHLCV candle data for TradingView Lightweight Charts.
    
    Returns data in format:
    [{"time": 1706500000, "open": 26200, "high": 26210, "low": 26195, "close": 26205}, ...]
    """
    try:
        candles = _fetch_candles(symbol=symbol, timeframe=timeframe, bars=bars)
        return JSONResponse(content=candles)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/state")
async def get_state():
    """Get current agent state."""
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")
    
    state_file = _state_dir / "state.json"
    state = _load_json_file(state_file)
    
    if not state:
        return {"error": "state_file_missing", "path": str(state_file)}
    
    # Return relevant fields for live chart
    return {
        "running": state.get("running", False),
        "paused": state.get("paused", False),
        "daily_pnl": state.get("daily_pnl", 0.0),
        "daily_trades": state.get("daily_trades", 0),
        "daily_wins": state.get("daily_wins", 0),
        "daily_losses": state.get("daily_losses", 0),
        "active_trades_count": state.get("active_trades_count", 0),
        "futures_market_open": state.get("futures_market_open", False),
        "data_fresh": state.get("data_fresh", False),
        "last_updated": state.get("last_updated"),
    }


@app.get("/api/trades")
async def get_trades(
    limit: int = Query(default=20, ge=1, le=100, description="Max trades to return"),
):
    """Get recent trades from signals.jsonl."""
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")
    
    signals_file = _state_dir / "signals.jsonl"
    signals = _load_jsonl_file(signals_file, max_lines=limit * 2)
    
    # Filter to exited trades only
    trades = [
        {
            "signal_id": s.get("signal_id"),
            "direction": s.get("direction"),
            "entry_time": s.get("entry_time"),
            "entry_price": s.get("entry_price"),
            "exit_time": s.get("exit_time"),
            "exit_price": s.get("exit_price"),
            "pnl": s.get("pnl"),
            "exit_reason": s.get("exit_reason"),
        }
        for s in signals
        if s.get("status") == "exited"
    ]
    
    return trades[-limit:]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _market, _state_dir
    
    parser = argparse.ArgumentParser(description="Live Chart API Server")
    parser.add_argument("--market", default=os.getenv("PEARLALGO_MARKET", DEFAULT_MARKET))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    
    _market = str(args.market or DEFAULT_MARKET).strip().upper()
    _state_dir = _resolve_state_dir(_market)
    
    print(f"Starting Live Chart API Server")
    print(f"  Market: {_market}")
    print(f"  State dir: {_state_dir}")
    print(f"  Listening: http://{args.host}:{args.port}")
    print(f"")
    print(f"Endpoints:")
    print(f"  GET /api/candles?symbol=MNQ&timeframe=5m&bars=72")
    print(f"  GET /api/state")
    print(f"  GET /api/trades")
    print(f"  GET /health")
    
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
