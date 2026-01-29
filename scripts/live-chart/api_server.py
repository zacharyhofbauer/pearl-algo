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


# Cache for mock data (to avoid regenerating on each request)
_mock_candles_cache: List[Dict[str, Any]] = []
_mock_candles_generated_at: float = 0

def _generate_mock_candles(bars: int = 72) -> List[Dict[str, Any]]:
    """Generate mock candle data for testing when IBKR is unavailable.
    
    Uses a seeded random generator and caches data to ensure consistency
    across requests. Data regenerates only if the cache is stale (>5 min old).
    """
    import random
    global _mock_candles_cache, _mock_candles_generated_at
    
    now = datetime.now(timezone.utc).timestamp()
    
    # Return cached data if fresh (regenerate every 5 minutes for "live" feel)
    if _mock_candles_cache and (now - _mock_candles_generated_at) < 300:
        return _mock_candles_cache
    
    # Seed random with current 5-minute window for consistency
    seed = int(now // 300)
    random.seed(seed)
    
    candles = []
    base_time = int(now) - (bars * 300)  # 5m bars
    price = 26200.0  # Starting price
    
    for i in range(bars):
        ts = base_time + (i * 300)
        
        # Random walk
        change = random.uniform(-20, 20)
        open_price = price
        close_price = price + change
        high_price = max(open_price, close_price) + random.uniform(0, 10)
        low_price = min(open_price, close_price) - random.uniform(0, 10)
        volume = int(random.uniform(500, 5000))  # Mock volume
        
        candles.append({
            "time": ts,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })
        
        price = close_price
    
    _mock_candles_cache = candles
    _mock_candles_generated_at = now
    return candles


def _calculate_indicators(candles: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Calculate EMA, VWAP, and RSI from candle data."""
    if not candles:
        return {"ema9": [], "ema21": [], "vwap": [], "rsi": []}
    
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 1000) for c in candles]
    times = [c["time"] for c in candles]
    
    # EMA calculation
    def ema(data, period):
        result = []
        multiplier = 2 / (period + 1)
        ema_val = sum(data[:period]) / period if len(data) >= period else data[0]
        for i, val in enumerate(data):
            if i < period - 1:
                result.append(None)
            elif i == period - 1:
                result.append(ema_val)
            else:
                ema_val = (val - ema_val) * multiplier + ema_val
                result.append(ema_val)
        return result
    
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    
    # VWAP calculation (simplified - cumulative)
    vwap = []
    cum_vol_price = 0
    cum_vol = 0
    for i, c in enumerate(candles):
        typical_price = (highs[i] + lows[i] + closes[i]) / 3
        cum_vol_price += typical_price * volumes[i]
        cum_vol += volumes[i]
        vwap.append(cum_vol_price / cum_vol if cum_vol > 0 else typical_price)
    
    # RSI calculation
    def rsi(data, period=14):
        result = []
        gains = []
        losses = []
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            gains.append(max(0, change))
            losses.append(max(0, -change))
        
        for i in range(len(data)):
            if i < period:
                result.append(None)
            else:
                avg_gain = sum(gains[i-period:i]) / period
                avg_loss = sum(losses[i-period:i]) / period
                if avg_loss == 0:
                    result.append(100)
                else:
                    rs = avg_gain / avg_loss
                    result.append(100 - (100 / (1 + rs)))
        return result
    
    rsi_values = rsi(closes, 14)
    
    # Format for TradingView
    return {
        "ema9": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(ema9) if v is not None],
        "ema21": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(ema21) if v is not None],
        "vwap": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(vwap)],
        "rsi": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(rsi_values) if v is not None],
    }


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PEARL Live Chart API",
    description="API for the PEARL Live Main Chart",
    version="1.0.0",
)

def _cors_origins() -> list[str]:
    """
    Allowed web origins for the Live Chart UI.

    - Local dev defaults include localhost ports.
    - For Telegram Mini App / production deployments, set:
        PEARL_LIVE_CHART_ORIGINS="https://your-domain.com,https://another-domain.com"
    """
    raw = str(os.getenv("PEARL_LIVE_CHART_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
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


@app.get("/api/indicators")
async def get_indicators(
    symbol: str = Query(default="MNQ", description="Symbol"),
    timeframe: str = Query(default="5m", description="Timeframe"),
    bars: int = Query(default=72, ge=10, le=500, description="Number of bars"),
):
    """Get technical indicators (EMA, VWAP, RSI) for overlay."""
    try:
        candles = _fetch_candles(symbol=symbol, timeframe=timeframe, bars=bars)
        indicators = _calculate_indicators(candles)
        return JSONResponse(content=indicators)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markers")
async def get_markers(
    hours: int = Query(default=6, ge=1, le=24, description="Hours of markers to return"),
):
    """Get trade entry/exit markers for chart overlay with tooltip metadata."""
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")
    
    signals_file = _state_dir / "signals.jsonl"
    signals = _load_jsonl_file(signals_file, max_lines=200)
    
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    cutoff_ts = cutoff.timestamp()
    
    markers = []
    for s in signals:
        direction = s.get("direction", "long")
        signal_id = s.get("signal_id", "")
        signal_data = s.get("signal", {})
        reason = signal_data.get("reason", "") if isinstance(signal_data, dict) else ""
        
        # Entry marker
        entry_time = s.get("entry_time")
        if entry_time:
            try:
                entry_ts = datetime.fromisoformat(entry_time.replace("Z", "+00:00")).timestamp()
                if entry_ts >= cutoff_ts:
                    markers.append({
                        # TradingView marker fields
                        "time": int(entry_ts),
                        "position": "belowBar" if direction == "long" else "aboveBar",
                        "color": "#00e676" if direction == "long" else "#ff5252",
                        "shape": "arrowUp" if direction == "long" else "arrowDown",
                        "text": "",  # Minimal - tooltip provides detail
                        # Tooltip metadata
                        "kind": "entry",
                        "signal_id": signal_id,
                        "direction": direction,
                        "entry_price": s.get("entry_price"),
                        "reason": reason,
                    })
            except Exception:
                pass
        
        # Exit marker
        exit_time = s.get("exit_time")
        if exit_time and s.get("status") == "exited":
            try:
                exit_ts = datetime.fromisoformat(exit_time.replace("Z", "+00:00")).timestamp()
                if exit_ts >= cutoff_ts:
                    pnl = s.get("pnl", 0)
                    is_win = pnl > 0 if pnl else False
                    markers.append({
                        # TradingView marker fields
                        "time": int(exit_ts),
                        "position": "aboveBar" if direction == "long" else "belowBar",
                        "color": "#00e676" if is_win else "#ff5252",
                        "shape": "circle",
                        "text": "",  # Minimal - tooltip provides detail
                        # Tooltip metadata
                        "kind": "exit",
                        "signal_id": signal_id,
                        "direction": direction,
                        "exit_price": s.get("exit_price"),
                        "pnl": pnl,
                        "exit_reason": s.get("exit_reason", ""),
                    })
            except Exception:
                pass
    
    return markers


@app.get("/api/sessions")
async def get_sessions(hours: int = Query(default=6, ge=1, le=24)):
    """Get session boundaries for RTH/ETH shading."""
    now = datetime.now(timezone.utc)
    
    sessions = []
    # Check the past 'hours' hours for session boundaries
    # RTH: 9:30 AM - 4:00 PM ET (13:30 - 20:00 UTC, adjust for DST)
    # For simplicity, we'll return time ranges
    
    for day_offset in range(2):  # Check today and yesterday
        day = now - timedelta(days=day_offset)
        # RTH session (simplified UTC times - should adjust for DST)
        rth_start = day.replace(hour=14, minute=30, second=0, microsecond=0)  # ~9:30 ET
        rth_end = day.replace(hour=21, minute=0, second=0, microsecond=0)    # ~4:00 ET
        
        start_ts = rth_start.timestamp()
        end_ts = rth_end.timestamp()
        
        # Only include if within our window
        cutoff = (now - timedelta(hours=hours)).timestamp()
        if end_ts >= cutoff:
            sessions.append({
                "start": int(max(start_ts, cutoff)),
                "end": int(min(end_ts, now.timestamp())),
                "type": "rth",
                "color": "rgba(0, 150, 136, 0.05)",  # Subtle teal
            })
    
    return sessions


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
    print(f"  GET /api/indicators?symbol=MNQ&timeframe=5m&bars=72")
    print(f"  GET /api/markers?hours=6")
    print(f"  GET /api/sessions?hours=6")
    print(f"  GET /api/state")
    print(f"  GET /api/trades")
    print(f"  GET /health")
    
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
