#!/usr/bin/env python3
"""
Pearl Algo Web App API Server - Serves OHLCV data for the TradingView chart.

Endpoints:
  GET /api/candles?symbol=MNQ&timeframe=5m&bars=72
  GET /api/state - Returns current agent state
  GET /api/trades - Returns recent trades
  GET /health - Health check

Usage:
  python scripts/pearlalgo_web_app/api_server.py --market NQ --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

# Thread pool for running blocking data provider calls
_executor = ThreadPoolExecutor(max_workers=2)

# Cache for candle data when market is closed
_candle_cache: Dict[str, List[Dict[str, Any]]] = {}
_cache_file: Optional[Path] = None

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from fastapi import FastAPI, Query, HTTPException, WebSocket, WebSocketDisconnect, Depends, Security
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.security import APIKeyHeader, APIKeyQuery
    import uvicorn
except ImportError:
    print("ERROR: FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)

import hashlib
import secrets

import pandas as pd

# Pearl AI imports (optional - graceful degradation if not available)
_pearl_brain = None
try:
    from pearl_ai import PearlBrain
    from pearl_ai.api_router import create_pearl_router
    _pearl_ai_available = True
except ImportError:
    _pearl_ai_available = False
    print("[Pearl AI] Module not available - chat features disabled")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_MARKET = "NQ"

# ---------------------------------------------------------------------------
# Authentication Configuration
# ---------------------------------------------------------------------------

# Environment variables for auth:
# PEARL_API_AUTH_ENABLED=true  - Enable API key authentication (default: true for security)
# PEARL_API_KEY=<key>          - Set a specific API key (optional, auto-generates if not set)
# PEARL_API_KEY_FILE=<path>    - Path to file containing API keys (one per line)
#
# To disable auth for local development only:
#   PEARL_API_AUTH_ENABLED=false

_auth_enabled: bool = os.getenv("PEARL_API_AUTH_ENABLED", "true").lower() == "true"
_api_keys: set = set()
_api_key_file: Optional[Path] = None

# Security schemes - header only (query param removed for security)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ---------------------------------------------------------------------------
# Rate Limiting Configuration
# ---------------------------------------------------------------------------

# Simple in-memory rate limiter (per-IP, sliding window)
# For production, consider using Redis-backed rate limiting
from collections import defaultdict
import time as time_module

_rate_limit_requests = int(os.getenv("PEARL_RATE_LIMIT_REQUESTS", "100"))  # requests per window
_rate_limit_window = int(os.getenv("PEARL_RATE_LIMIT_WINDOW", "60"))  # window in seconds
_rate_limit_store: Dict[str, List[float]] = defaultdict(list)


def _load_api_keys() -> set:
    """Load API keys from environment or file."""
    keys = set()

    # Load from environment variable
    env_key = os.getenv("PEARL_API_KEY")
    if env_key:
        keys.add(env_key.strip())

    # Load from file
    key_file_path = os.getenv("PEARL_API_KEY_FILE")
    if key_file_path:
        key_file = Path(key_file_path)
        if key_file.exists():
            try:
                for line in key_file.read_text().strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        keys.add(line)
            except Exception as e:
                print(f"[Auth] Warning: Failed to read API key file: {e}")

    # Auto-generate a key if none configured and auth is enabled
    if not keys and _auth_enabled:
        auto_key = secrets.token_urlsafe(32)
        keys.add(auto_key)
        print(f"[Auth] Auto-generated API key: {auto_key}")
        print(f"[Auth] Set PEARL_API_KEY environment variable to use a persistent key")

    return keys


def _init_auth():
    """Initialize authentication on startup."""
    global _api_keys, _auth_enabled

    if _auth_enabled:
        _api_keys = _load_api_keys()
        print(f"[Auth] Authentication ENABLED - {len(_api_keys)} API key(s) configured")
    else:
        print(f"[Auth] Authentication DISABLED (set PEARL_API_AUTH_ENABLED=true to enable)")


async def verify_api_key(
    api_key_header: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """
    Verify API key from header.

    Returns the API key if valid, None if auth disabled.
    Raises HTTPException if auth enabled but key invalid/missing.

    Note: Query parameter auth has been removed for security reasons.
    Always use the X-API-Key header.
    """
    if not _auth_enabled:
        return None

    if not api_key_header:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
        )

    if api_key_header not in _api_keys:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key.",
        )

    return api_key_header


# Dependency for protected routes
def require_auth():
    """Dependency that requires authentication if enabled."""
    return Depends(verify_api_key)


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
# Data Provider (reads from IBKR - NO mock data fallback)
# ---------------------------------------------------------------------------

_data_provider = None
_data_provider_error: Optional[str] = None


class DataUnavailableError(Exception):
    """Raised when real market data is not available."""
    pass


def _get_cache_file() -> Path:
    """Get the cache file path."""
    global _cache_file
    if _cache_file is None:
        _cache_file = PROJECT_ROOT / "data" / "live_chart_cache.json"
    return _cache_file


def _save_candle_cache(key: str, candles: List[Dict[str, Any]]) -> None:
    """Save candles to cache (memory and disk)."""
    global _candle_cache
    _candle_cache[key] = candles

    # Also save to disk for persistence across restarts
    try:
        cache_file = _get_cache_file()
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing cache
        existing = {}
        if cache_file.exists():
            try:
                existing = json.loads(cache_file.read_text())
            except Exception:
                pass

        # Update with new data
        existing[key] = {
            "candles": candles,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Keep only last 24 hours of cache entries
        cache_file.write_text(json.dumps(existing))
    except Exception:
        pass  # Cache write failures are not critical


def _load_candle_cache(key: str) -> Optional[List[Dict[str, Any]]]:
    """Load candles from cache."""
    global _candle_cache

    # Try memory cache first
    if key in _candle_cache:
        return _candle_cache[key]

    # Try disk cache
    try:
        cache_file = _get_cache_file()
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            if key in data:
                cached = data[key]
                # Check if cache is less than 24 hours old
                cache_time = datetime.fromisoformat(cached["timestamp"].replace("Z", "+00:00"))
                if datetime.now(timezone.utc) - cache_time < timedelta(hours=24):
                    _candle_cache[key] = cached["candles"]
                    return cached["candles"]
    except Exception:
        pass

    return None


def _get_data_provider():
    """Lazy-load the IBKR data provider."""
    global _data_provider, _data_provider_error
    
    if _data_provider is not None:
        return _data_provider
    
    if _data_provider_error is not None:
        return None
    
    try:
        from pearlalgo.data_providers.factory import create_data_provider
        
        provider = create_data_provider(
            "ibkr",
            host=os.getenv("IB_HOST", "127.0.0.1"),
            port=int(os.getenv("IB_PORT", "4002")),
            client_id=int(os.getenv("IB_CLIENT_ID_LIVE_CHART", "88")),
        )
        _data_provider = provider
        return provider
    except Exception as e:
        _data_provider_error = str(e)
        return None


async def _fetch_candles(
    symbol: str,
    timeframe: str = "5m",
    bars: int = 72,
    use_cache_fallback: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV candles from IBKR.

    If live data is unavailable and use_cache_fallback is True, returns cached data.

    Returns data in TradingView Lightweight Charts format:
    [{"time": 1706500000, "open": 26200, "high": 26210, "low": 26195, "close": 26205}, ...]
    """
    cache_key = f"{symbol}_{timeframe}_{bars}"

    # Try cache first if provider not available (faster response when market closed)
    provider = _get_data_provider()
    if provider is None and use_cache_fallback:
        cached = _load_candle_cache(cache_key)
        if cached:
            return cached

    # Try to fetch live data with timeout
    if provider is not None:
        try:
            # Calculate time range based on bars and timeframe (case-insensitive)
            tf_lower = timeframe.lower()
            tf_minutes = {
                "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440
            }.get(tf_lower, 5)

            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=tf_minutes * bars * 1.5)  # Extra buffer

            # Run blocking fetch_historical in thread pool with timeout
            loop = asyncio.get_event_loop()
            df = await asyncio.wait_for(
                loop.run_in_executor(
                    _executor,
                    partial(
                        provider.fetch_historical,
                        symbol=symbol,
                        start=start,
                        end=end,
                        timeframe=timeframe,
                    )
                ),
                timeout=5.0  # 5 second timeout - fail fast if IBKR not responding
            )

            if df is not None and not df.empty:
                # Convert to TradingView format
                candles = []
                for idx, row in df.tail(bars).iterrows():
                    ts = idx if isinstance(idx, (int, float)) else int(idx.timestamp())
                    # Get volume - try different column name variations
                    vol = row.get("Volume", row.get("volume", row.get("vol", 0)))
                    candles.append({
                        "time": ts,
                        "open": float(row.get("Open", row.get("open", 0))),
                        "high": float(row.get("High", row.get("high", 0))),
                        "low": float(row.get("Low", row.get("low", 0))),
                        "close": float(row.get("Close", row.get("close", 0))),
                        "volume": int(vol) if vol else 0,
                    })

                # Cache successful fetch
                _save_candle_cache(cache_key, candles)
                return candles
        except asyncio.TimeoutError:
            pass  # Fall through to cache
        except Exception:
            pass  # Fall through to cache

    # Try cache fallback
    if use_cache_fallback:
        cached = _load_candle_cache(cache_key)
        if cached:
            return cached

    # No live data and no cache
    raise DataUnavailableError(
        f"Market closed - no live data available. Cache not found for {symbol} {timeframe}."
    )


async def _fetch_candles_with_source(
    symbol: str,
    timeframe: str = "5m",
    bars: int = 72,
    use_cache_fallback: bool = True,
) -> tuple:
    """
    Fetch OHLCV candles and return with data source indicator.

    Returns:
        Tuple of (candles, data_source) where data_source is 'live' or 'cache'
    """
    cache_key = f"{symbol}_{timeframe}_{bars}"

    # Try cache first if provider not available (faster response when market closed)
    provider = _get_data_provider()
    if provider is None and use_cache_fallback:
        cached = _load_candle_cache(cache_key)
        if cached:
            return (cached, "cache")

    # Try to fetch live data with timeout
    if provider is not None:
        try:
            # Calculate time range based on bars and timeframe (case-insensitive)
            tf_lower = timeframe.lower()
            tf_minutes = {
                "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440
            }.get(tf_lower, 5)

            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=tf_minutes * bars * 1.5)  # Extra buffer

            # Run blocking fetch_historical in thread pool with timeout
            loop = asyncio.get_event_loop()
            df = await asyncio.wait_for(
                loop.run_in_executor(
                    _executor,
                    partial(
                        provider.fetch_historical,
                        symbol=symbol,
                        start=start,
                        end=end,
                        timeframe=timeframe,
                    )
                ),
                timeout=5.0  # 5 second timeout - fail fast if IBKR not responding
            )

            if df is not None and not df.empty:
                # Convert to TradingView format
                candles = []
                for idx, row in df.tail(bars).iterrows():
                    ts = idx if isinstance(idx, (int, float)) else int(idx.timestamp())
                    # Get volume - try different column name variations
                    vol = row.get("Volume", row.get("volume", row.get("vol", 0)))
                    candles.append({
                        "time": ts,
                        "open": float(row.get("Open", row.get("open", 0))),
                        "high": float(row.get("High", row.get("high", 0))),
                        "low": float(row.get("Low", row.get("low", 0))),
                        "close": float(row.get("Close", row.get("close", 0))),
                        "volume": int(vol) if vol else 0,
                    })

                # Cache successful fetch
                _save_candle_cache(cache_key, candles)
                return (candles, "live")
        except asyncio.TimeoutError:
            pass  # Fall through to cache
        except Exception:
            pass  # Fall through to cache

    # Try cache fallback
    if use_cache_fallback:
        cached = _load_candle_cache(cache_key)
        if cached:
            return (cached, "cache")

    # No live data and no cache
    raise DataUnavailableError(
        f"Market closed - no live data available. Cache not found for {symbol} {timeframe}."
    )


def _calculate_indicators(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate EMA, VWAP, RSI, MACD, Bollinger Bands, ATR Bands, and Volume Profile from candle data."""
    if not candles:
        return {
            "ema9": [], "ema21": [], "vwap": [], "rsi": [],
            "macd": [], "bollingerBands": [], "atrBands": [], "volumeProfile": None
        }

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    opens = [c["open"] for c in candles]
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

    # MACD calculation (12, 26, 9)
    def calculate_macd(data, fast=12, slow=26, signal=9):
        ema_fast = ema(data, fast)
        ema_slow = ema(data, slow)

        macd_line = []
        for i in range(len(data)):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                macd_line.append(ema_fast[i] - ema_slow[i])
            else:
                macd_line.append(None)

        # Signal line (EMA of MACD line)
        valid_macd = [m for m in macd_line if m is not None]
        signal_line = []
        if len(valid_macd) >= signal:
            signal_ema = ema(valid_macd, signal)
            # Pad with None to align with macd_line
            none_count = len(macd_line) - len(valid_macd)
            signal_line = [None] * none_count + signal_ema
        else:
            signal_line = [None] * len(macd_line)

        return macd_line, signal_line

    macd_line, signal_line = calculate_macd(closes)

    # Bollinger Bands (20 SMA, 2 std dev)
    def calculate_bollinger_bands(data, period=20, num_std=2):
        result = []
        for i in range(len(data)):
            if i < period - 1:
                result.append(None)
            else:
                window = data[i - period + 1:i + 1]
                sma = sum(window) / period
                variance = sum((x - sma) ** 2 for x in window) / period
                std = variance ** 0.5
                result.append({
                    "upper": sma + (num_std * std),
                    "middle": sma,
                    "lower": sma - (num_std * std)
                })
        return result

    bb_values = calculate_bollinger_bands(closes)

    # ATR Bands (14-period ATR, 2x multiplier)
    def calculate_atr_bands(highs, lows, closes, period=14, multiplier=2):
        # Calculate True Range
        true_ranges = []
        for i in range(len(closes)):
            if i == 0:
                tr = highs[i] - lows[i]
            else:
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i-1]),
                    abs(lows[i] - closes[i-1])
                )
            true_ranges.append(tr)

        # Calculate ATR using EMA
        atr_values = []
        atr = 0
        for i in range(len(closes)):
            if i < period - 1:
                atr_values.append(None)
            elif i == period - 1:
                atr = sum(true_ranges[:period]) / period
                atr_values.append(atr)
            else:
                atr = ((atr * (period - 1)) + true_ranges[i]) / period
                atr_values.append(atr)

        # Calculate bands around typical price
        result = []
        for i in range(len(closes)):
            if atr_values[i] is not None:
                typical_price = (highs[i] + lows[i] + closes[i]) / 3
                result.append({
                    "upper": typical_price + (multiplier * atr_values[i]),
                    "lower": typical_price - (multiplier * atr_values[i]),
                    "atr": atr_values[i]
                })
            else:
                result.append(None)
        return result

    atr_bands = calculate_atr_bands(highs, lows, closes)

    # Volume Profile calculation
    def calculate_volume_profile(candles, num_levels=50, value_area_pct=0.70):
        if not candles:
            return None

        max_price = max(highs)
        min_price = min(lows)
        price_range = max_price - min_price
        if price_range == 0:
            return None

        level_height = price_range / num_levels

        # Initialize levels
        levels = {}
        for i in range(num_levels):
            level_price = min_price + (level_height * i) + (level_height / 2)
            level_price = round(level_price, 2)
            levels[level_price] = {"volume": 0, "buyVolume": 0, "sellVolume": 0}

        # Distribute volume to price levels
        for i, c in enumerate(candles):
            vol = volumes[i]
            is_bullish = closes[i] >= opens[i]
            candle_high = highs[i]
            candle_low = lows[i]

            for price, level_data in levels.items():
                if candle_low <= price <= candle_high:
                    # Distribute volume proportionally
                    candle_range = candle_high - candle_low
                    if candle_range > 0:
                        level_vol = vol / (candle_range / level_height)
                    else:
                        level_vol = vol / num_levels

                    level_data["volume"] += level_vol
                    if is_bullish:
                        level_data["buyVolume"] += level_vol * 0.6
                        level_data["sellVolume"] += level_vol * 0.4
                    else:
                        level_data["buyVolume"] += level_vol * 0.4
                        level_data["sellVolume"] += level_vol * 0.6

        # Find POC (Point of Control - highest volume level)
        poc = min_price
        max_vol = 0
        for price, data in levels.items():
            if data["volume"] > max_vol:
                max_vol = data["volume"]
                poc = price

        # Calculate Value Area (70% of volume)
        total_volume = sum(d["volume"] for d in levels.values())
        target_volume = total_volume * value_area_pct

        sorted_prices = sorted(levels.keys())
        poc_index = sorted_prices.index(poc) if poc in sorted_prices else len(sorted_prices) // 2

        cum_volume = levels.get(poc, {}).get("volume", 0)
        vah_index = poc_index
        val_index = poc_index

        while cum_volume < target_volume:
            upper_vol = levels.get(sorted_prices[vah_index + 1], {}).get("volume", 0) if vah_index < len(sorted_prices) - 1 else 0
            lower_vol = levels.get(sorted_prices[val_index - 1], {}).get("volume", 0) if val_index > 0 else 0

            if upper_vol >= lower_vol and vah_index < len(sorted_prices) - 1:
                vah_index += 1
                cum_volume += levels[sorted_prices[vah_index]]["volume"]
            elif val_index > 0:
                val_index -= 1
                cum_volume += levels[sorted_prices[val_index]]["volume"]
            else:
                break

        vah = sorted_prices[vah_index] if vah_index < len(sorted_prices) else max_price
        val = sorted_prices[val_index] if val_index >= 0 else min_price

        # Format levels for response
        levels_list = [
            {
                "price": price,
                "volume": round(data["volume"]),
                "buyVolume": round(data["buyVolume"]),
                "sellVolume": round(data["sellVolume"])
            }
            for price, data in levels.items()
            if data["volume"] > 0
        ]

        return {
            "levels": sorted(levels_list, key=lambda x: x["price"]),
            "poc": round(poc, 2),
            "vah": round(vah, 2),
            "val": round(val, 2)
        }

    volume_profile = calculate_volume_profile(candles)

    # Format MACD data
    macd_data = []
    for i in range(len(times)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram = macd_line[i] - signal_line[i]
            macd_data.append({
                "time": times[i],
                "macd": round(macd_line[i], 2),
                "signal": round(signal_line[i], 2),
                "histogram": round(histogram, 2)
            })

    # Format Bollinger Bands data
    bb_data = [
        {
            "time": times[i],
            "upper": round(bb["upper"], 2),
            "middle": round(bb["middle"], 2),
            "lower": round(bb["lower"], 2)
        }
        for i, bb in enumerate(bb_values) if bb is not None
    ]

    # Format ATR Bands data
    atr_data = [
        {
            "time": times[i],
            "upper": round(atr["upper"], 2),
            "lower": round(atr["lower"], 2),
            "atr": round(atr["atr"], 2)
        }
        for i, atr in enumerate(atr_bands) if atr is not None
    ]

    # Format for TradingView
    return {
        "ema9": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(ema9) if v is not None],
        "ema21": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(ema21) if v is not None],
        "vwap": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(vwap)],
        "rsi": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(rsi_values) if v is not None],
        "macd": macd_data,
        "bollingerBands": bb_data,
        "atrBands": atr_data,
        "volumeProfile": volume_profile,
    }


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Pearl Algo Web App API",
    description="API for the Pearl Algo Web App",
    version="1.0.0",
)

def _cors_origins() -> list[str]:
    """
    Allowed web origins for the Pearl Algo Web App UI.

    - Local dev defaults include localhost ports.
    - For Telegram Mini App / production deployments, set:
        PEARL_WEB_APP_ORIGINS="https://your-domain.com,https://another-domain.com"
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


# ---------------------------------------------------------------------------
# Rate Limiting Middleware
# ---------------------------------------------------------------------------

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiting middleware (per-IP, sliding window)."""

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health check
        if request.url.path == "/health":
            return await call_next(request)

        # Get client IP (handle proxy headers)
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        # Clean up old requests and check rate limit
        now = time_module.time()
        window_start = now - _rate_limit_window

        # Remove old entries
        _rate_limit_store[client_ip] = [
            t for t in _rate_limit_store[client_ip] if t > window_start
        ]

        # Check if over limit
        if len(_rate_limit_store[client_ip]) >= _rate_limit_requests:
            return Response(
                content='{"detail": "Rate limit exceeded. Try again later."}',
                status_code=429,
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": str(_rate_limit_window),
                    "X-RateLimit-Limit": str(_rate_limit_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(window_start + _rate_limit_window)),
                },
            )

        # Record this request
        _rate_limit_store[client_ip].append(now)

        # Add rate limit headers to response
        response = await call_next(request)
        remaining = _rate_limit_requests - len(_rate_limit_store[client_ip])
        response.headers["X-RateLimit-Limit"] = str(_rate_limit_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(int(now + _rate_limit_window))

        return response


# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# ---------------------------------------------------------------------------
# Pearl AI Router (Optional - graceful degradation if not available)
# ---------------------------------------------------------------------------

def _init_pearl_ai():
    """Initialize Pearl AI brain and mount router."""
    global _pearl_brain

    if not _pearl_ai_available:
        return

    # Get Claude API key from environment
    claude_api_key = os.getenv("ANTHROPIC_API_KEY")
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model = os.getenv("PEARL_OLLAMA_MODEL", "llama3.1:8b")

    try:
        # Initialize Pearl Brain with available LLMs
        _pearl_brain = PearlBrain(
            claude_api_key=claude_api_key,
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            enable_local=True,  # Try Ollama
            enable_claude=bool(claude_api_key),
        )

        # Create and mount the Pearl AI router
        pearl_router = create_pearl_router(_pearl_brain)
        app.include_router(pearl_router, prefix="/api/pearl")

        print(f"[Pearl AI] Initialized successfully")
        print(f"  - Local LLM (Ollama): {'enabled' if True else 'disabled'} ({ollama_model})")
        print(f"  - Claude API: {'enabled' if claude_api_key else 'disabled (no API key)'}")

    except Exception as e:
        print(f"[Pearl AI] Failed to initialize: {e}")
        _pearl_brain = None

# Initialize Pearl AI at module load time (before startup)
_init_pearl_ai()

# Global state
_market: str = DEFAULT_MARKET
_state_dir: Optional[Path] = None


# ---------------------------------------------------------------------------
# WebSocket Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._broadcast_task: Optional[asyncio.Task] = None
        self._last_state_hash: str = ""

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WebSocket] Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WebSocket] Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def start_broadcast_loop(self, interval: float = 2.0):
        """Start broadcasting state updates at regular intervals."""
        while True:
            try:
                if self.active_connections and _state_dir:
                    # Get current state
                    state_file = _state_dir / "state.json"
                    state = _load_json_file(state_file)

                    if state:
                        # Create a hash to detect changes
                        state_hash = str(hash(json.dumps(state, sort_keys=True, default=str)))

                        # Only broadcast if state changed
                        if state_hash != self._last_state_hash:
                            self._last_state_hash = state_hash

                            # Build the same response as /api/state
                            daily_stats = _compute_daily_stats(_state_dir)
                            broadcast_data = {
                                "type": "state_update",
                                "data": {
                                    "running": state.get("running", False),
                                    "paused": state.get("paused", False),
                                    "daily_pnl": daily_stats["daily_pnl"],
                                    "daily_trades": daily_stats["daily_trades"],
                                    "daily_wins": daily_stats["daily_wins"],
                                    "daily_losses": daily_stats["daily_losses"],
                                    "active_trades_count": state.get("active_trades_count", 0),
                                    "data_fresh": state.get("data_fresh", False),
                                    "last_updated": datetime.now(timezone.utc).isoformat(),
                                    "ai_status": _get_ai_status(state),
                                    "cadence_metrics": _get_cadence_metrics_enhanced(state),
                                    "market_regime": _get_market_regime(state),
                                    "buy_sell_pressure": state.get("buy_sell_pressure_raw"),
                                    "gateway_status": _get_gateway_status(),
                                    "connection_health": _get_connection_health(state),
                                    "error_summary": _get_error_summary(_state_dir, state),
                                    "config": _get_config(state),
                                    "data_quality": _get_data_quality(state),
                                }
                            }
                            await self.broadcast(broadcast_data)

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[WebSocket] Broadcast error: {e}")
                await asyncio.sleep(interval)


# Global connection manager
ws_manager = ConnectionManager()


@app.on_event("startup")
async def startup_event():
    """Initialize authentication and start WebSocket broadcast loop."""
    _init_auth()
    asyncio.create_task(ws_manager.start_broadcast_loop(interval=2.0))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, api_key: Optional[str] = Query(default=None)):
    """WebSocket endpoint for real-time state updates."""
    # Verify API key if authentication is enabled
    if _auth_enabled:
        if not api_key:
            await websocket.close(code=1008, reason="Missing API key")
            return
        if api_key not in _api_keys:
            await websocket.close(code=1008, reason="Invalid API key")
            return

    await ws_manager.connect(websocket)
    try:
        # Send initial state immediately
        if _state_dir:
            state_file = _state_dir / "state.json"
            state = _load_json_file(state_file)
            if state:
                daily_stats = _compute_daily_stats(_state_dir)
                initial_data = {
                    "type": "initial_state",
                    "data": {
                        "running": state.get("running", False),
                        "paused": state.get("paused", False),
                        "daily_pnl": daily_stats["daily_pnl"],
                        "daily_trades": daily_stats["daily_trades"],
                        "daily_wins": daily_stats["daily_wins"],
                        "daily_losses": daily_stats["daily_losses"],
                        "active_trades_count": state.get("active_trades_count", 0),
                        "data_fresh": state.get("data_fresh", False),
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "ai_status": _get_ai_status(state),
                        "challenge": _get_challenge_status(_state_dir),
                        "recent_exits": _get_recent_exits(_state_dir, limit=3),
                        "performance": _compute_performance_stats(_state_dir),
                        "equity_curve": _get_equity_curve(_state_dir, hours=72),
                        "risk_metrics": _get_risk_metrics(_state_dir),
                        "cadence_metrics": _get_cadence_metrics_enhanced(state),
                        "market_regime": _get_market_regime(state),
                        "buy_sell_pressure": state.get("buy_sell_pressure_raw"),
                        "signal_rejections_24h": _get_signal_rejections_24h(state),
                        "last_signal_decision": _get_last_signal_decision(state),
                        "shadow_counters": _get_shadow_counters(state),
                        "gateway_status": _get_gateway_status(),
                        "connection_health": _get_connection_health(state),
                        "error_summary": _get_error_summary(_state_dir, state),
                        "config": _get_config(state),
                        "data_quality": _get_data_quality(state),
                    }
                }
                await websocket.send_json(initial_data)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message (ping/pong or requests)
                data = await websocket.receive_text()

                # Handle ping
                if data == "ping":
                    await websocket.send_json({"type": "pong"})

                # Handle request for full state refresh
                elif data == "refresh":
                    if _state_dir:
                        state_file = _state_dir / "state.json"
                        state = _load_json_file(state_file)
                        if state:
                            daily_stats = _compute_daily_stats(_state_dir)
                            refresh_data = {
                                "type": "full_refresh",
                                "data": {
                                    "running": state.get("running", False),
                                    "paused": state.get("paused", False),
                                    "daily_pnl": daily_stats["daily_pnl"],
                                    "daily_trades": daily_stats["daily_trades"],
                                    "daily_wins": daily_stats["daily_wins"],
                                    "daily_losses": daily_stats["daily_losses"],
                                    "active_trades_count": state.get("active_trades_count", 0),
                                    "data_fresh": state.get("data_fresh", False),
                                    "last_updated": datetime.now(timezone.utc).isoformat(),
                                    "ai_status": _get_ai_status(state),
                                    "challenge": _get_challenge_status(_state_dir),
                                    "recent_exits": _get_recent_exits(_state_dir, limit=3),
                                    "performance": _compute_performance_stats(_state_dir),
                                    "equity_curve": _get_equity_curve(_state_dir, hours=72),
                                    "risk_metrics": _get_risk_metrics(_state_dir),
                                    "cadence_metrics": _get_cadence_metrics_enhanced(state),
                                    "market_regime": _get_market_regime(state),
                                    "buy_sell_pressure": state.get("buy_sell_pressure_raw"),
                                    "signal_rejections_24h": _get_signal_rejections_24h(state),
                                    "last_signal_decision": _get_last_signal_decision(state),
                                    "shadow_counters": _get_shadow_counters(state),
                                    "gateway_status": _get_gateway_status(),
                                    "connection_health": _get_connection_health(state),
                                    "error_summary": _get_error_summary(_state_dir, state),
                                    "config": _get_config(state),
                                    "data_quality": _get_data_quality(state),
                                }
                            }
                            await websocket.send_json(refresh_data)

            except WebSocketDisconnect:
                break
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        ws_manager.disconnect(websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "market": _market}


def _get_market_status() -> Dict[str, Any]:
    """Get futures market open/closed status and next open time."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    et_tz = ZoneInfo("America/New_York")
    now_et = datetime.now(et_tz)
    weekday = now_et.weekday()  # 0=Monday, 6=Sunday
    hour = now_et.hour
    minute = now_et.minute

    # Futures market hours (simplified):
    # Open: Sunday 6pm ET - Friday 5pm ET
    # Closed: Friday 5pm ET - Sunday 6pm ET
    # Daily maintenance: 5pm-6pm ET (Mon-Thu)

    is_open = True
    next_open = None
    close_reason = None

    # Check if weekend closed (Friday 5pm to Sunday 6pm)
    if weekday == 4 and hour >= 17:  # Friday after 5pm
        is_open = False
        close_reason = "Weekend"
        # Next open is Sunday 6pm
        days_until_sunday = 2
        next_open = now_et.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
    elif weekday == 5:  # Saturday
        is_open = False
        close_reason = "Weekend"
        next_open = now_et.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif weekday == 6 and hour < 18:  # Sunday before 6pm
        is_open = False
        close_reason = "Weekend"
        next_open = now_et.replace(hour=18, minute=0, second=0, microsecond=0)
    # Daily maintenance break (5pm-6pm ET, Mon-Thu)
    elif weekday < 4 and hour == 17:
        is_open = False
        close_reason = "Daily maintenance"
        next_open = now_et.replace(hour=18, minute=0, second=0, microsecond=0)

    return {
        "is_open": is_open,
        "close_reason": close_reason,
        "next_open": next_open.isoformat() if next_open else None,
        "current_time_et": now_et.isoformat(),
    }


@app.get("/api/market-status")
async def get_market_status():
    """Get current market open/closed status."""
    return _get_market_status()


@app.get("/api/candles")
async def get_candles(
    symbol: str = Query(default="MNQ", description="Symbol to fetch"),
    timeframe: str = Query(default="5m", description="Timeframe (1m, 5m, 15m, 1h)"),
    bars: int = Query(default=72, ge=10, le=500, description="Number of bars"),
):
    """
    Get OHLCV candle data for TradingView Lightweight Charts.

    Returns cached data if live data is unavailable (market closed).
    Includes X-Data-Source header: 'live' or 'cache'

    Returns data in format:
    [{"time": 1706500000, "open": 26200, "high": 26210, "low": 26195, "close": 26205}, ...]
    """
    try:
        # Track whether we get cached or live data
        candles, data_source = await _fetch_candles_with_source(
            symbol=symbol, timeframe=timeframe, bars=bars, use_cache_fallback=True
        )
        return JSONResponse(
            content=candles,
            headers={"X-Data-Source": data_source}
        )
    except DataUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail={"error": "data_unavailable", "message": str(e)}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_trading_day_start() -> datetime:
    """
    Get the start of the current trading day (6pm ET previous calendar day).

    Futures trading day runs from 6pm ET to 6pm ET next day.
    Example: Trading day "Jan 29" starts at 6pm ET on Jan 28 and ends at 6pm ET on Jan 29.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    et_tz = ZoneInfo("America/New_York")
    now_et = datetime.now(et_tz)

    # If before 6pm ET, trading day started yesterday at 6pm
    # If after 6pm ET, trading day started today at 6pm
    if now_et.hour < 18:
        # Before 6pm - use yesterday 6pm as start
        trading_day_start = now_et.replace(hour=18, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        # After 6pm - use today 6pm as start
        trading_day_start = now_et.replace(hour=18, minute=0, second=0, microsecond=0)

    return trading_day_start.astimezone(timezone.utc)


def _compute_daily_stats(state_dir: Path) -> Dict[str, Any]:
    """Compute daily P&L and trade stats from signals.jsonl since 6pm ET."""
    signals_file = state_dir / "signals.jsonl"
    if not signals_file.exists():
        return {"daily_pnl": 0.0, "daily_trades": 0, "daily_wins": 0, "daily_losses": 0}

    # Get trading day start (6pm ET)
    trading_day_start = _get_trading_day_start()

    daily_pnl = 0.0
    daily_wins = 0
    daily_losses = 0

    try:
        # Read all signals (we need to check all for today's trades)
        signals = _load_jsonl_file(signals_file, max_lines=2000)
        for s in signals:
            if s.get("status") != "exited":
                continue

            # Check if trade exited after trading day start (6pm ET)
            exit_time_str = s.get("exit_time") or s.get("timestamp")
            if not exit_time_str:
                continue

            try:
                # Parse ISO format timestamp
                exit_time = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                if exit_time < trading_day_start:
                    continue
            except (ValueError, AttributeError):
                continue

            # Count this trade
            pnl = s.get("pnl", 0.0)
            if pnl is not None:
                daily_pnl += pnl
                if pnl >= 0:
                    daily_wins += 1
                else:
                    daily_losses += 1
    except Exception:
        pass

    return {
        "daily_pnl": round(daily_pnl, 2),
        "daily_trades": daily_wins + daily_losses,
        "daily_wins": daily_wins,
        "daily_losses": daily_losses,
    }


def _compute_performance_stats(state_dir: Path) -> Dict[str, Any]:
    """Compute performance stats for 24h, 72h, and 30d periods."""
    performance_file = state_dir / "performance.json"
    if not performance_file.exists():
        empty_stats = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
        return {"24h": empty_stats.copy(), "72h": empty_stats.copy(), "30d": empty_stats.copy()}

    now = datetime.now(timezone.utc)
    cutoffs = {
        "24h": now - timedelta(hours=24),
        "72h": now - timedelta(hours=72),
        "30d": now - timedelta(days=30),
    }

    stats = {period: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0} for period in cutoffs}

    try:
        data = json.loads(performance_file.read_text())
        if not isinstance(data, list):
            data = []

        for trade in data:
            exit_time_str = trade.get("exit_time")
            if not exit_time_str:
                continue
            try:
                exit_time = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            pnl = trade.get("pnl", 0.0) or 0.0
            is_win = trade.get("is_win", pnl > 0)

            for period, cutoff in cutoffs.items():
                if exit_time >= cutoff:
                    stats[period]["pnl"] += pnl
                    stats[period]["trades"] += 1
                    if is_win:
                        stats[period]["wins"] += 1
                    else:
                        stats[period]["losses"] += 1
    except Exception:
        pass

    # Calculate win rates and compute streaks for 24h
    for period in stats:
        total = stats[period]["trades"]
        stats[period]["pnl"] = round(stats[period]["pnl"], 2)
        stats[period]["win_rate"] = round(stats[period]["wins"] / total * 100, 1) if total > 0 else 0.0

    # Compute current streak for 24h
    stats["24h"]["streak"] = 0
    stats["24h"]["streak_type"] = "none"
    try:
        data = json.loads(performance_file.read_text())
        if isinstance(data, list):
            cutoff_24h = cutoffs["24h"]
            recent_trades = []
            for trade in data:
                exit_time_str = trade.get("exit_time")
                if not exit_time_str:
                    continue
                try:
                    exit_time = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                    if exit_time >= cutoff_24h:
                        recent_trades.append((exit_time, trade.get("is_win", trade.get("pnl", 0) > 0)))
                except (ValueError, TypeError):
                    continue
            # Sort by exit time descending
            recent_trades.sort(key=lambda x: x[0], reverse=True)
            if recent_trades:
                streak = 0
                streak_type = "win" if recent_trades[0][1] else "loss"
                for _, is_win in recent_trades:
                    if (streak_type == "win" and is_win) or (streak_type == "loss" and not is_win):
                        streak += 1
                    else:
                        break
                stats["24h"]["streak"] = streak
                stats["24h"]["streak_type"] = streak_type
    except Exception:
        pass

    return stats


def _get_recent_exits(state_dir: Path, limit: int = 5) -> List[Dict[str, Any]]:
    """Get recent exits from signals.jsonl with full trade details."""
    signals_file = state_dir / "signals.jsonl"
    if not signals_file.exists():
        return []

    exits = []
    try:
        signals = _load_jsonl_file(signals_file, max_lines=200)
        for s in signals:
            if s.get("status") != "exited":
                continue
            signal_data = s.get("signal", {})
            direction = signal_data.get("direction", s.get("direction", "long")) if isinstance(signal_data, dict) else s.get("direction", "long")
            entry_reason = signal_data.get("reason", "") if isinstance(signal_data, dict) else ""

            # Calculate duration
            duration_seconds = None
            entry_time = s.get("entry_time", "")
            exit_time = s.get("exit_time", "")
            if entry_time and exit_time:
                try:
                    entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                    exit_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                    duration_seconds = int((exit_dt - entry_dt).total_seconds())
                except Exception:
                    pass

            exits.append({
                "signal_id": s.get("signal_id", ""),
                "direction": direction,
                "pnl": round(s.get("pnl", 0.0) or 0.0, 2),
                "exit_reason": s.get("exit_reason", ""),
                "exit_time": exit_time,
                # NEW: Full trade details
                "entry_time": entry_time,
                "entry_price": s.get("entry_price"),
                "exit_price": s.get("exit_price"),
                "entry_reason": entry_reason,
                "duration_seconds": duration_seconds,
            })
        # Sort by exit time descending and take most recent
        exits.sort(key=lambda x: x.get("exit_time", ""), reverse=True)
    except Exception:
        pass

    return exits[:limit]


def _get_ai_status(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract AI/ML status from agent state."""
    learning = state.get("learning", {})
    learning_contextual = state.get("learning_contextual", {})
    ml_filter = state.get("ml_filter", {})
    circuit_breaker = state.get("trading_circuit_breaker", {})

    # Determine mode (off, shadow, live)
    def get_mode(section: Dict) -> str:
        if not section.get("enabled", False):
            return "off"
        return section.get("mode", "off")

    return {
        "bandit_mode": get_mode(learning),
        "contextual_mode": get_mode(learning_contextual),
        "ml_filter": {
            "enabled": ml_filter.get("enabled", False),
            "mode": ml_filter.get("mode", "off"),
            "lift": ml_filter.get("lift", {}),
        },
        "direction_gating": {
            "enabled": circuit_breaker.get("direction_gating_enabled", False),
            "blocks": circuit_breaker.get("blocks_by_reason", {}).get("direction_gating", 0),
            "shadow_regime": circuit_breaker.get("would_have_blocked_regime", 0),
            "shadow_trigger": circuit_breaker.get("would_have_blocked_trigger", 0),
        },
    }


def _get_challenge_status(state_dir: Path) -> Optional[Dict[str, Any]]:
    """Get challenge status from challenge_state.json."""
    challenge_file = state_dir / "challenge_state.json"
    if not challenge_file.exists():
        return None

    try:
        data = json.loads(challenge_file.read_text())
        config = data.get("config", {})
        current = data.get("current_attempt", {})

        if not config.get("enabled", False):
            return None

        # Calculate drawdown risk percentage
        max_dd = config.get("max_drawdown", 2000.0)
        current_dd = abs(current.get("max_drawdown_hit", 0.0))
        dd_risk_pct = min(100.0, (current_dd / max_dd * 100)) if max_dd > 0 else 0.0

        return {
            "enabled": True,
            "current_balance": round(config.get("start_balance", 50000.0) + current.get("pnl", 0.0), 2),
            "pnl": round(current.get("pnl", 0.0), 2),
            "trades": current.get("trades", 0),
            "wins": current.get("wins", 0),
            "win_rate": round(current.get("win_rate", 0.0), 1),
            "drawdown_risk_pct": round(dd_risk_pct, 1),
            "outcome": current.get("outcome", "active"),
            "profit_target": config.get("profit_target", 3000.0),
            "max_drawdown": max_dd,
        }
    except Exception:
        return None


def _get_pearl_suggestion() -> Optional[Dict[str, Any]]:
    """Get current Pearl suggestion if any. Placeholder for actual suggestion logic."""
    # Pearl suggestions are generated dynamically - return None for now
    # In future, this could read from a suggestion queue or state file
    return None


def _get_equity_curve(state_dir: Path, hours: int = 72) -> List[Dict[str, Any]]:
    """Get equity curve data (cumulative P&L over time) for the mini chart."""
    performance_file = state_dir / "performance.json"
    if not performance_file.exists():
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    curve = []
    try:
        data = json.loads(performance_file.read_text())
        if not isinstance(data, list):
            return []

        # Sort trades by exit time
        trades = []
        for trade in data:
            exit_time_str = trade.get("exit_time")
            if not exit_time_str:
                continue
            try:
                exit_time = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                if exit_time >= cutoff:
                    trades.append({
                        "time": int(exit_time.timestamp()),
                        "pnl": trade.get("pnl", 0.0) or 0.0,
                    })
            except (ValueError, TypeError):
                continue

        # Sort by time and calculate cumulative P&L
        trades.sort(key=lambda x: x["time"])

        # Aggregate trades with same timestamp and ensure unique ascending times
        cumulative = 0.0
        last_time = 0
        for t in trades:
            cumulative += t["pnl"]
            # Ensure strictly ascending timestamps (add 1 second if duplicate)
            time_val = t["time"]
            if time_val <= last_time:
                time_val = last_time + 1
            last_time = time_val
            curve.append({
                "time": time_val,
                "value": round(cumulative, 2),
            })
    except Exception:
        pass

    return curve


def _get_risk_metrics(state_dir: Path) -> Dict[str, Any]:
    """Calculate risk metrics: max drawdown, Sharpe ratio, average R:R, profit factor."""
    performance_file = state_dir / "performance.json"
    signals_file = state_dir / "signals.jsonl"
    default_metrics = {
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe_ratio": None,
        "profit_factor": None,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "avg_rr": None,
        "largest_win": 0.0,
        "largest_loss": 0.0,
        "expectancy": 0.0,
        # NEW: Exposure metrics
        "max_concurrent_positions_peak": 0,
        "max_stop_risk_exposure": 0.0,
        "top_losses": [],
    }

    if not performance_file.exists():
        return default_metrics

    try:
        data = json.loads(performance_file.read_text())
        if not isinstance(data, list) or len(data) == 0:
            return default_metrics

        # Extract P&L values
        pnls = [t.get("pnl", 0.0) or 0.0 for t in data if t.get("pnl") is not None]
        if not pnls:
            return default_metrics

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        # Max drawdown calculation
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (simplified - daily returns, annualized)
        sharpe = None
        if len(pnls) >= 5:
            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 0
            if std_pnl > 0:
                # Approximate annualization (assuming ~5 trades per day, 252 trading days)
                sharpe = round((mean_pnl / std_pnl) * (252 ** 0.5), 2)

        # Profit factor
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        profit_factor = round(total_wins / total_losses, 2) if total_losses > 0 else None

        # Average win/loss
        avg_win = round(statistics.mean(wins), 2) if wins else 0.0
        avg_loss = round(statistics.mean(losses), 2) if losses else 0.0

        # Average R:R (reward to risk ratio)
        avg_rr = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else None

        # Expectancy
        win_rate = len(wins) / len(pnls) if pnls else 0
        expectancy = round((win_rate * avg_win) + ((1 - win_rate) * avg_loss), 2)

        # NEW: Top 3 losses
        top_losses = []
        trades_with_losses = [
            t for t in data
            if t.get("pnl") is not None and t.get("pnl") < 0
        ]
        # Sort by pnl ascending (most negative first)
        trades_with_losses.sort(key=lambda x: x.get("pnl", 0))
        for t in trades_with_losses[:3]:
            top_losses.append({
                "signal_id": t.get("signal_id", "unknown"),
                "pnl": round(t.get("pnl", 0), 2),
                "exit_reason": t.get("exit_reason", ""),
            })

        # NEW: Calculate max concurrent positions from signals.jsonl
        max_concurrent = 0
        max_stop_risk = 0.0

        if signals_file.exists():
            try:
                signals = _load_jsonl_file(signals_file, max_lines=2000)

                # Build list of entries and exits with timestamps
                events = []
                for s in signals:
                    entry_time = s.get("entry_time")
                    exit_time = s.get("exit_time")
                    signal_data = s.get("signal", {})

                    # Calculate stop risk for this position
                    entry_price = s.get("entry_price", 0)
                    stop_loss = signal_data.get("stop_loss", 0) if isinstance(signal_data, dict) else 0
                    stop_risk = abs(entry_price - stop_loss) * 2 if entry_price and stop_loss else 0  # MNQ = $2/pt

                    if entry_time:
                        try:
                            entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                            events.append(("entry", entry_dt, stop_risk))
                        except (ValueError, TypeError):
                            pass

                    if exit_time:
                        try:
                            exit_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                            events.append(("exit", exit_dt, -stop_risk))
                        except (ValueError, TypeError):
                            pass

                # Sort events by time
                events.sort(key=lambda x: x[1])

                # Track concurrent positions and stop risk
                current_positions = 0
                current_stop_risk = 0.0
                for event_type, _, risk_delta in events:
                    if event_type == "entry":
                        current_positions += 1
                        current_stop_risk += risk_delta
                    else:
                        current_positions -= 1
                        current_stop_risk += risk_delta  # risk_delta is negative for exits

                    max_concurrent = max(max_concurrent, current_positions)
                    max_stop_risk = max(max_stop_risk, current_stop_risk)

            except Exception:
                pass

        return {
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round((max_dd / peak * 100), 1) if peak > 0 else 0.0,
            "sharpe_ratio": sharpe,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_rr": avg_rr,
            "largest_win": round(max(wins), 2) if wins else 0.0,
            "largest_loss": round(min(losses), 2) if losses else 0.0,
            "expectancy": expectancy,
            # NEW: Exposure metrics
            "max_concurrent_positions_peak": max_concurrent,
            "max_stop_risk_exposure": round(max_stop_risk, 2),
            "top_losses": top_losses,
        }
    except Exception:
        return default_metrics


def _get_market_regime(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract market regime information from circuit breaker state."""
    circuit_breaker = state.get("trading_circuit_breaker", {})

    # Try to get regime from state (if available)
    regime = state.get("regime") or "unknown"

    # Calculate confidence based on various factors
    confidence = 0.0
    if regime and regime != "unknown":
        confidence = 0.75  # Base confidence when regime is known

    # Determine allowed direction based on direction gating
    allowed_direction = "both"
    if circuit_breaker.get("direction_gating_enabled", False):
        # Check if there's a specific direction allowed
        min_confidence = circuit_breaker.get("direction_gating_min_confidence", 0.7)
        if confidence >= min_confidence:
            if regime in ["trending_up"]:
                allowed_direction = "long"
            elif regime in ["trending_down"]:
                allowed_direction = "short"

    return {
        "regime": regime,
        "confidence": round(confidence, 2),
        "allowed_direction": allowed_direction,
    }


def _get_signal_rejections_24h(state: Dict[str, Any]) -> Dict[str, int]:
    """Get signal rejection counts from the last 24 hours."""
    circuit_breaker = state.get("trading_circuit_breaker", {})
    blocks_by_reason = circuit_breaker.get("blocks_by_reason", {})
    would_block_by_reason = circuit_breaker.get("would_block_by_reason", {})

    # Combine actual blocks and would-have-blocked counts
    return {
        "direction_gating": blocks_by_reason.get("direction_gating", 0) + would_block_by_reason.get("direction_gating", 0),
        "ml_filter": 0,  # ML filter tracks separately
        "circuit_breaker": (
            blocks_by_reason.get("consecutive_losses", 0) +
            blocks_by_reason.get("rolling_win_rate", 0) +
            would_block_by_reason.get("consecutive_losses", 0) +
            would_block_by_reason.get("rolling_win_rate", 0) +
            would_block_by_reason.get("in_cooldown:consecutive_losses", 0) +
            would_block_by_reason.get("in_cooldown:rolling_win_rate", 0)
        ),
        "session_filter": 0,  # Track if session filter is enabled
        "max_positions": blocks_by_reason.get("max_positions", 0) + would_block_by_reason.get("max_positions", 0),
    }


def _get_last_signal_decision(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get the last signal decision information."""
    learning = state.get("learning", {})
    last_decision = learning.get("last_decision")

    if not last_decision:
        return None

    return {
        "signal_type": last_decision.get("signal_type", "unknown"),
        "ml_probability": last_decision.get("score", 0.0),
        "action": "execute" if last_decision.get("execute", False) else "skip",
        "reason": last_decision.get("reason", ""),
        "timestamp": last_decision.get("at"),
    }


def _get_shadow_counters(state: Dict[str, Any]) -> Dict[str, Any]:
    """Get shadow mode counters showing what would have been blocked."""
    circuit_breaker = state.get("trading_circuit_breaker", {})
    ml_filter = state.get("ml_filter", {})
    learning = state.get("learning", {})

    return {
        "would_block_total": circuit_breaker.get("would_block_total", 0),
        "would_block_by_reason": circuit_breaker.get("would_block_by_reason", {}),
        "ml_would_skip": learning.get("total_skips", 0) if learning.get("mode") == "shadow" else 0,
        "ml_total_decisions": learning.get("total_decisions", 0),
        "ml_execute_rate": learning.get("execute_rate", 1.0),
    }


def _get_cadence_metrics_enhanced(state: Dict[str, Any]) -> Dict[str, Any]:
    """Get enhanced cadence metrics from state."""
    cadence = state.get("cadence_metrics", {})

    return {
        "cycle_duration_ms": cadence.get("cycle_duration_ms", 0),
        "duration_p50_ms": cadence.get("duration_p50_ms", 0),
        "duration_p95_ms": cadence.get("duration_p95_ms", 0),
        "velocity_mode_active": cadence.get("velocity_mode_active", False),
        "velocity_reason": cadence.get("velocity_reason", ""),
        "missed_cycles": cadence.get("missed_cycles", 0),
        "current_interval_seconds": cadence.get("current_interval_seconds", 0),
        "cadence_lag_ms": cadence.get("cadence_lag_ms", 0),
    }


def _get_gateway_status() -> Dict[str, Any]:
    """
    Check IBKR Gateway status: process running and port listening.

    Returns gateway health for live chart display.
    """
    import socket
    import subprocess

    gateway_port = int(os.getenv("IB_PORT", "4002"))
    process_running = False
    port_listening = False

    # Check if any IBKR Gateway process is running
    # Pattern matches IBC-launched gateway (java.*IBC.jar) or direct gateway (IbcGateway)
    try:
        result = subprocess.run(
            ["pgrep", "-f", "java.*IBC.jar|IbcGateway"],
            capture_output=True,
            timeout=2,
        )
        process_running = result.returncode == 0
    except Exception:
        # If pgrep fails, try checking port as fallback
        pass

    # Check if gateway port is listening
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", gateway_port))
            port_listening = result == 0
    except Exception:
        pass

    # Determine overall status
    if process_running and port_listening:
        status = "online"
    elif port_listening:
        status = "online"  # Port responding is what matters
    elif process_running:
        status = "degraded"  # Process up but port not responding
    else:
        status = "offline"

    return {
        "process_running": process_running,
        "port_listening": port_listening,
        "port": gateway_port,
        "status": status,
    }


def _get_connection_health(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract connection health metrics from agent state.

    Includes connection failures, data fetch errors, and data level.
    """
    # Connection metrics are tracked in state.json
    connection = state.get("connection", {})
    data_provider = state.get("data_provider", {})

    return {
        "connection_failures": connection.get("failures", 0),
        "data_fetch_errors": connection.get("data_fetch_errors", 0),
        "data_level": data_provider.get("data_level", "UNKNOWN"),
        "consecutive_errors": connection.get("consecutive_errors", 0),
        "last_successful_fetch": connection.get("last_successful_fetch"),
    }


def _get_error_summary(state_dir: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get error summary from state and logs.

    Returns session error count and last error message.
    """
    error_count = state.get("session_error_count", 0)
    last_error = state.get("last_error")
    last_error_time = state.get("last_error_time")

    # Try to get more details from error log if available
    error_log = state_dir / "errors.log"
    if last_error is None and error_log.exists():
        try:
            # Read last line of error log
            lines = error_log.read_text().strip().split("\n")
            if lines and lines[-1]:
                last_line = lines[-1]
                # Parse if it's a JSON line
                try:
                    error_data = json.loads(last_line)
                    last_error = error_data.get("message", last_line[:100])
                    last_error_time = error_data.get("timestamp")
                except json.JSONDecodeError:
                    last_error = last_line[:100]
        except Exception:
            pass

    # Truncate error message if too long
    if last_error and len(last_error) > 80:
        last_error = last_error[:77] + "..."

    return {
        "session_error_count": error_count,
        "last_error": last_error,
        "last_error_time": last_error_time,
    }


def _get_config(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract agent configuration for display.

    Returns symbol, timeframe, scan interval, session times, and mode.
    """
    config = state.get("config", {})

    # Determine agent mode
    running = state.get("running", False)
    paused = state.get("paused", False)
    shadow_mode = state.get("shadow_mode", False)

    if not running:
        mode = "stopped"
    elif paused:
        mode = "paused"
    elif shadow_mode:
        mode = "shadow"
    else:
        mode = "live"

    return {
        "symbol": config.get("symbol", state.get("symbol", "MNQ")),
        "market": config.get("market", state.get("market", "NQ")),
        "timeframe": config.get("timeframe", state.get("timeframe", "5m")),
        "scan_interval": config.get("scan_interval", state.get("scan_interval_seconds", 30)),
        "session_start": config.get("session_start_time", state.get("session_start", "09:30")),
        "session_end": config.get("session_end_time", state.get("session_end", "16:00")),
        "mode": mode,
    }


def _get_data_quality(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get extended data quality metrics.

    Includes data age, buffer size, stale reason, and expected stale indicator.
    """
    data_quality = state.get("data_quality", {})
    data_provider = state.get("data_provider", {})

    # Get latest bar age
    latest_bar_age = data_quality.get("latest_bar_age_minutes", data_provider.get("latest_bar_age_minutes"))
    stale_threshold = data_quality.get("stale_threshold_minutes", 2.0)

    # Buffer info
    buffer_size = data_provider.get("buffer_size", data_quality.get("buffer_size"))
    buffer_target = data_provider.get("buffer_target", data_quality.get("buffer_target", 500))

    # Stale reason and expectation
    quiet_reason = state.get("quiet_reason")
    is_expected_stale = state.get("is_expected_stale", False)

    # If we're outside market hours, stale data is expected
    if not state.get("futures_market_open", True):
        is_expected_stale = True
        if not quiet_reason:
            quiet_reason = "Market closed"

    return {
        "latest_bar_age_minutes": round(latest_bar_age, 2) if latest_bar_age is not None else None,
        "stale_threshold_minutes": stale_threshold,
        "buffer_size": buffer_size,
        "buffer_target": buffer_target,
        "quiet_reason": quiet_reason,
        "is_expected_stale": is_expected_stale,
        "is_stale": not state.get("data_fresh", True),
    }


@app.get("/api/state")
async def get_state(api_key: Optional[str] = Depends(verify_api_key)):
    """Get current agent state with AI status, challenge, performance, and suggestions."""
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")

    state_file = _state_dir / "state.json"
    state = _load_json_file(state_file)

    if not state:
        return {"error": "state_file_missing", "path": str(state_file)}

    # Compute daily stats from actual trades
    daily_stats = _compute_daily_stats(_state_dir)

    # Return relevant fields for live chart
    return {
        # Existing fields
        "running": state.get("running", False),
        "paused": state.get("paused", False),
        "daily_pnl": daily_stats["daily_pnl"],
        "daily_trades": daily_stats["daily_trades"],
        "daily_wins": daily_stats["daily_wins"],
        "daily_losses": daily_stats["daily_losses"],
        "active_trades_count": state.get("active_trades_count", 0),
        "futures_market_open": state.get("futures_market_open", False),
        "data_fresh": state.get("data_fresh", False),
        "last_updated": datetime.now(timezone.utc).isoformat(),

        # NEW: AI/ML Status
        "ai_status": _get_ai_status(state),

        # NEW: Challenge Status
        "challenge": _get_challenge_status(_state_dir),

        # NEW: Recent exits
        "recent_exits": _get_recent_exits(_state_dir, limit=3),

        # NEW: Performance stats
        "performance": _compute_performance_stats(_state_dir),

        # NEW: Pearl suggestion
        "pearl_suggestion": _get_pearl_suggestion(),

        # NEW: Equity curve for mini chart
        "equity_curve": _get_equity_curve(_state_dir, hours=72),

        # NEW: Risk metrics
        "risk_metrics": _get_risk_metrics(_state_dir),

        # NEW: Buy/Sell Pressure (already in state.json)
        "buy_sell_pressure": state.get("buy_sell_pressure_raw"),

        # NEW: Cadence/System Health metrics
        "cadence_metrics": _get_cadence_metrics_enhanced(state),

        # NEW: Market Regime
        "market_regime": _get_market_regime(state),

        # NEW: Signal rejections breakdown
        "signal_rejections_24h": _get_signal_rejections_24h(state),

        # NEW: Last signal decision
        "last_signal_decision": _get_last_signal_decision(state),

        # NEW: Shadow mode counters
        "shadow_counters": _get_shadow_counters(state),

        # NEW: Gateway status (process + port check)
        "gateway_status": _get_gateway_status(),

        # NEW: Connection health
        "connection_health": _get_connection_health(state),

        # NEW: Error summary
        "error_summary": _get_error_summary(_state_dir, state),

        # NEW: Config for display
        "config": _get_config(state),

        # NEW: Extended data quality
        "data_quality": _get_data_quality(state),
    }


@app.get("/api/trades")
async def get_trades(
    limit: int = Query(default=20, ge=1, le=100, description="Max trades to return"),
    api_key: Optional[str] = Depends(verify_api_key),
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


@app.get("/api/positions")
async def get_positions(
    api_key: Optional[str] = Depends(verify_api_key),
):
    """Get currently open positions with entry price, stop loss, and take profit.

    Returns positions for display on chart as price lines.
    """
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")

    signals_file = _state_dir / "signals.jsonl"
    signals = _load_jsonl_file(signals_file, max_lines=500)

    # Filter to open positions only (not exited)
    positions = []
    for s in signals:
        # Skip exited trades
        if s.get("status") == "exited":
            continue

        # Must have entry to be an open position
        entry_price = s.get("entry_price")
        if not entry_price:
            continue

        signal_data = s.get("signal", {})
        direction = signal_data.get("direction", "long") if isinstance(signal_data, dict) else s.get("direction", "long")

        # Get stop loss and take profit from signal data
        stop_loss = signal_data.get("stop_loss") if isinstance(signal_data, dict) else None
        take_profit = signal_data.get("take_profit") if isinstance(signal_data, dict) else None

        positions.append({
            "signal_id": s.get("signal_id"),
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": s.get("entry_time"),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        })

    return positions


@app.post("/api/positions/{signal_id}/close")
async def close_position(
    signal_id: str,
    api_key: Optional[str] = Depends(verify_api_key),
):
    """Request to close a specific position by signal_id.

    Sets close_signal_requested in state.json which the market agent will pick up.
    """
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")

    # Verify the position exists and is open
    signals_file = _state_dir / "signals.jsonl"
    signals = _load_jsonl_file(signals_file, max_lines=500)

    position_exists = False
    for s in signals:
        if s.get("signal_id") == signal_id and s.get("status") != "exited":
            if s.get("entry_price"):  # Has an entry = open position
                position_exists = True
                break

    if not position_exists:
        raise HTTPException(status_code=404, detail=f"Position {signal_id} not found or already closed")

    # Set the close request in state.json
    state_file = _state_dir / "state.json"
    try:
        state = _load_json_file(state_file) or {}
    except Exception:
        state = {}

    # Add to close_signals_requested list
    close_requests = state.get("close_signals_requested", [])
    if signal_id not in close_requests:
        close_requests.append(signal_id)
    state["close_signals_requested"] = close_requests
    state["close_signals_requested_time"] = datetime.now(timezone.utc).isoformat()

    try:
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write state: {e}")

    return {"status": "close_requested", "signal_id": signal_id}


@app.post("/api/positions/close-all")
async def close_all_positions(
    api_key: Optional[str] = Depends(verify_api_key),
):
    """Request to close all open positions.

    Sets close_all_requested flag in state.json which the market agent will pick up.
    """
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")

    # Count open positions first
    signals_file = _state_dir / "signals.jsonl"
    signals = _load_jsonl_file(signals_file, max_lines=500)

    open_count = 0
    for s in signals:
        if s.get("status") != "exited" and s.get("entry_price"):
            open_count += 1

    if open_count == 0:
        return {"status": "no_positions", "message": "No open positions to close"}

    # Set the close_all_requested flag in state.json
    state_file = _state_dir / "state.json"
    try:
        state = _load_json_file(state_file) or {}
    except Exception:
        state = {}

    state["close_all_requested"] = True
    state["close_all_requested_time"] = datetime.now(timezone.utc).isoformat()

    try:
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write state: {e}")

    return {"status": "close_all_requested", "positions_count": open_count}


@app.get("/api/indicators")
async def get_indicators(
    symbol: str = Query(default="MNQ", description="Symbol"),
    timeframe: str = Query(default="5m", description="Timeframe"),
    bars: int = Query(default=72, ge=10, le=500, description="Number of bars"),
):
    """Get technical indicators (EMA, VWAP, RSI) for overlay.
    
    Returns 503 if real data is unavailable.
    """
    try:
        candles = await _fetch_candles(symbol=symbol, timeframe=timeframe, bars=bars)
        indicators = _calculate_indicators(candles)
        return JSONResponse(content=indicators)
    except DataUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail={"error": "data_unavailable", "message": str(e)}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _snap_to_bar(timestamp: float, bar_seconds: int = 300) -> int:
    """Snap timestamp to nearest bar boundary (default 5-minute bars)."""
    return int((timestamp // bar_seconds) * bar_seconds)


@app.get("/api/markers")
async def get_markers(
    hours: int = Query(default=24, ge=1, le=72, description="Hours of markers to return"),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """Get trade entry/exit markers for chart overlay with tooltip metadata."""
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")

    signals_file = _state_dir / "signals.jsonl"
    signals = _load_jsonl_file(signals_file, max_lines=2000)
    
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    cutoff_ts = cutoff.timestamp()
    
    markers = []
    for s in signals:
        signal_data = s.get("signal", {})
        # Direction is nested inside signal object
        direction = signal_data.get("direction", "long") if isinstance(signal_data, dict) else s.get("direction", "long")
        signal_id = s.get("signal_id", "")
        reason = signal_data.get("reason", "") if isinstance(signal_data, dict) else ""
        
        # Entry marker
        entry_time = s.get("entry_time")
        if entry_time:
            try:
                entry_ts = datetime.fromisoformat(entry_time.replace("Z", "+00:00")).timestamp()
                if entry_ts >= cutoff_ts:
                    # Snap to 5-minute bar boundary so marker aligns with candle
                    bar_time = _snap_to_bar(entry_ts, 300)
                    markers.append({
                        # TradingView marker fields
                        "time": bar_time,
                        "position": "belowBar" if direction == "long" else "aboveBar",
                        # ENTRY: Blue arrow up for LONG, Red arrow down for SHORT
                        "color": "#2196F3" if direction == "long" else "#f44336",
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
                    # Snap to 5-minute bar boundary so marker aligns with candle
                    bar_time = _snap_to_bar(exit_ts, 300)
                    # EXIT markers: Just X with color
                    # Win: Bright green
                    # Loss: Bright red
                    exit_color = "#00ff88" if is_win else "#ff3333"
                    
                    markers.append({
                        # TradingView marker fields
                        "time": bar_time,
                        "position": "aboveBar" if direction == "long" else "belowBar",
                        "color": exit_color,
                        "shape": "circle",  # Small circle, X shows as text
                        "text": "✕",  # X marker for exits
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
    
    # Sort markers by time (required by Lightweight Charts)
    markers.sort(key=lambda m: m["time"])
    
    return markers


def _get_session_analytics(state_dir: Path) -> Dict[str, Any]:
    """
    Compute session and time-based performance analytics from performance.json.

    Returns session performance, best/worst hours, hold duration stats,
    direction breakdown, and status breakdown.
    """
    performance_file = state_dir / "performance.json"
    signals_file = state_dir / "signals.jsonl"

    # Session definitions (ET timezone)
    sessions = {
        "overnight": {"start": 18, "end": 4, "name": "Overnight", "pnl": 0.0, "wins": 0, "losses": 0},
        "premarket": {"start": 4, "end": 6, "name": "Premarket", "pnl": 0.0, "wins": 0, "losses": 0},
        "morning": {"start": 6, "end": 10, "name": "Morning", "pnl": 0.0, "wins": 0, "losses": 0},
        "midday": {"start": 10, "end": 14, "name": "Midday", "pnl": 0.0, "wins": 0, "losses": 0},
        "afternoon": {"start": 14, "end": 17, "name": "Afternoon", "pnl": 0.0, "wins": 0, "losses": 0},
        "close": {"start": 17, "end": 18, "name": "Close", "pnl": 0.0, "wins": 0, "losses": 0},
    }

    # Hourly stats
    hourly_stats: Dict[int, Dict[str, Any]] = {h: {"pnl": 0.0, "trades": 0, "wins": 0} for h in range(24)}

    # Hold duration stats
    duration_stats = {
        "quick": {"name": "Quick (<30m)", "pnl": 0.0, "wins": 0, "losses": 0},
        "medium": {"name": "Medium (30-60m)", "pnl": 0.0, "wins": 0, "losses": 0},
        "long": {"name": "Long (60m+)", "pnl": 0.0, "wins": 0, "losses": 0},
    }

    # Direction breakdown
    direction_stats = {
        "long": {"count": 0, "pnl": 0.0},
        "short": {"count": 0, "pnl": 0.0},
    }

    # Status breakdown from signals.jsonl
    status_breakdown = {
        "generated": 0,
        "entered": 0,
        "exited": 0,
        "cancelled": 0,
    }

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    et_tz = ZoneInfo("America/New_York")

    def get_session_for_hour(hour: int) -> str:
        """Determine which session an hour belongs to."""
        if hour >= 18 or hour < 4:
            return "overnight"
        elif 4 <= hour < 6:
            return "premarket"
        elif 6 <= hour < 10:
            return "morning"
        elif 10 <= hour < 14:
            return "midday"
        elif 14 <= hour < 17:
            return "afternoon"
        else:  # 17-18
            return "close"

    # Process performance.json for closed trades
    if performance_file.exists():
        try:
            data = json.loads(performance_file.read_text())
            if isinstance(data, list):
                for trade in data:
                    exit_time_str = trade.get("exit_time")
                    entry_time_str = trade.get("entry_time")
                    pnl = trade.get("pnl", 0.0) or 0.0
                    is_win = trade.get("is_win", pnl > 0)
                    direction = trade.get("direction", "long").lower()

                    # Direction stats
                    if direction in direction_stats:
                        direction_stats[direction]["count"] += 1
                        direction_stats[direction]["pnl"] += pnl

                    if exit_time_str:
                        try:
                            exit_time = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                            exit_time_et = exit_time.astimezone(et_tz)
                            hour = exit_time_et.hour

                            # Session stats
                            session_key = get_session_for_hour(hour)
                            sessions[session_key]["pnl"] += pnl
                            if is_win:
                                sessions[session_key]["wins"] += 1
                            else:
                                sessions[session_key]["losses"] += 1

                            # Hourly stats
                            hourly_stats[hour]["pnl"] += pnl
                            hourly_stats[hour]["trades"] += 1
                            if is_win:
                                hourly_stats[hour]["wins"] += 1
                        except (ValueError, TypeError):
                            pass

                    # Duration stats
                    if entry_time_str and exit_time_str:
                        try:
                            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                            exit_time = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                            duration_minutes = (exit_time - entry_time).total_seconds() / 60

                            if duration_minutes < 30:
                                duration_key = "quick"
                            elif duration_minutes < 60:
                                duration_key = "medium"
                            else:
                                duration_key = "long"

                            duration_stats[duration_key]["pnl"] += pnl
                            if is_win:
                                duration_stats[duration_key]["wins"] += 1
                            else:
                                duration_stats[duration_key]["losses"] += 1
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass

    # Process signals.jsonl for status breakdown
    if signals_file.exists():
        try:
            signals = _load_jsonl_file(signals_file, max_lines=2000)
            for s in signals:
                status = s.get("status", "").lower()
                if status in status_breakdown:
                    status_breakdown[status] += 1
        except Exception:
            pass

    # Calculate win rates and format session performance
    session_performance = []
    for key, session in sessions.items():
        total = session["wins"] + session["losses"]
        win_rate = round(session["wins"] / total * 100, 1) if total > 0 else 0.0
        session_performance.append({
            "id": key,
            "name": session["name"],
            "pnl": round(session["pnl"], 2),
            "wins": session["wins"],
            "losses": session["losses"],
            "win_rate": win_rate,
        })

    # Best and worst hours (min 5 trades)
    qualified_hours = [
        {"hour": h, **stats}
        for h, stats in hourly_stats.items()
        if stats["trades"] >= 5
    ]

    # Sort by P&L
    sorted_by_pnl = sorted(qualified_hours, key=lambda x: x["pnl"], reverse=True)
    best_hours = []
    worst_hours = []

    for h in sorted_by_pnl[:3]:
        win_rate = round(h["wins"] / h["trades"] * 100, 1) if h["trades"] > 0 else 0.0
        best_hours.append({
            "hour": h["hour"],
            "hour_label": f"{h['hour']:02d}:00 ET",
            "pnl": round(h["pnl"], 2),
            "trades": h["trades"],
            "win_rate": win_rate,
        })

    for h in sorted_by_pnl[-3:][::-1]:  # Reverse to get worst first
        if h["pnl"] < 0:  # Only include negative hours
            win_rate = round(h["wins"] / h["trades"] * 100, 1) if h["trades"] > 0 else 0.0
            worst_hours.append({
                "hour": h["hour"],
                "hour_label": f"{h['hour']:02d}:00 ET",
                "pnl": round(h["pnl"], 2),
                "trades": h["trades"],
                "win_rate": win_rate,
            })

    # Format duration breakdown
    hold_duration = []
    for key, dur in duration_stats.items():
        total = dur["wins"] + dur["losses"]
        win_rate = round(dur["wins"] / total * 100, 1) if total > 0 else 0.0
        hold_duration.append({
            "id": key,
            "name": dur["name"],
            "pnl": round(dur["pnl"], 2),
            "wins": dur["wins"],
            "losses": dur["losses"],
            "win_rate": win_rate,
        })

    # Format direction breakdown
    direction_breakdown = {
        "long": {
            "count": direction_stats["long"]["count"],
            "pnl": round(direction_stats["long"]["pnl"], 2),
        },
        "short": {
            "count": direction_stats["short"]["count"],
            "pnl": round(direction_stats["short"]["pnl"], 2),
        },
    }

    return {
        "session_performance": session_performance,
        "best_hours": best_hours,
        "worst_hours": worst_hours,
        "hold_duration": hold_duration,
        "direction_breakdown": direction_breakdown,
        "status_breakdown": status_breakdown,
    }


@app.get("/api/analytics")
async def get_analytics(api_key: Optional[str] = Depends(verify_api_key)):
    """
    Session and time-based performance analytics.

    Returns:
    - session_performance: 6 trading sessions with wins, losses, pnl, win_rate
    - best_hours: Top 3 hours by P&L (min 5 trades)
    - worst_hours: Bottom 3 hours by P&L (min 5 trades)
    - hold_duration: Quick/Medium/Long breakdown with win rates
    - direction_breakdown: LONG vs SHORT counts and P&L
    - status_breakdown: Generated/Entered/Exited/Cancelled counts
    """
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")

    return _get_session_analytics(_state_dir)


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
# Prometheus Metrics Endpoint
# ---------------------------------------------------------------------------

@app.get("/api/metrics")
async def get_metrics(api_key: Optional[str] = Depends(verify_api_key)):
    """
    Prometheus-compatible metrics endpoint.

    Returns metrics in Prometheus text format:
    - pearl_active_positions: Number of currently open positions
    - pearl_daily_pnl_dollars: Today's P&L in dollars
    - pearl_daily_trades_total: Total trades today
    - pearl_daily_wins_total: Winning trades today
    - pearl_daily_losses_total: Losing trades today
    - pearl_signal_rate_per_hour: Signal generation rate (last hour)
    - pearl_websocket_connections: Active WebSocket connections
    - pearl_api_requests_total: Total API requests (by endpoint)
    - pearl_agent_running: Whether the agent is running (1/0)
    - pearl_data_fresh: Whether data is fresh (1/0)
    - pearl_gateway_status: IBKR gateway status (1=online, 0=offline)
    - pearl_rate_limit_remaining: Remaining rate limit for client
    """
    if _state_dir is None:
        return Response(
            content="# No state directory configured\n",
            media_type="text/plain; version=0.0.4",
        )

    # Load state
    state_file = _state_dir / "state.json"
    state = _load_json_file(state_file)

    # Load daily stats
    daily_stats = _compute_daily_stats(_state_dir)

    # Count active positions from signals
    signals_file = _state_dir / "signals.jsonl"
    active_positions = 0
    signals_last_hour = 0

    if signals_file.exists():
        signals = _load_jsonl_file(signals_file, max_lines=500)
        now_ts = datetime.now(timezone.utc)
        hour_ago = (now_ts - timedelta(hours=1)).isoformat()

        for s in signals:
            # Count active (non-exited) positions
            if s.get("status") != "exited" and s.get("entry_price"):
                active_positions += 1

            # Count signals in last hour
            ts = s.get("timestamp", "")
            if ts and ts >= hour_ago:
                signals_last_hour += 1

    # Gateway status
    gateway = _get_gateway_status()
    gateway_online = 1 if gateway.get("status") == "online" else 0

    # Build Prometheus text output
    lines = [
        "# HELP pearl_active_positions Number of currently open positions",
        "# TYPE pearl_active_positions gauge",
        f"pearl_active_positions {active_positions}",
        "",
        "# HELP pearl_daily_pnl_dollars Today's P&L in dollars",
        "# TYPE pearl_daily_pnl_dollars gauge",
        f"pearl_daily_pnl_dollars {daily_stats['daily_pnl']}",
        "",
        "# HELP pearl_daily_trades_total Total trades completed today",
        "# TYPE pearl_daily_trades_total counter",
        f"pearl_daily_trades_total {daily_stats['daily_trades']}",
        "",
        "# HELP pearl_daily_wins_total Winning trades today",
        "# TYPE pearl_daily_wins_total counter",
        f"pearl_daily_wins_total {daily_stats['daily_wins']}",
        "",
        "# HELP pearl_daily_losses_total Losing trades today",
        "# TYPE pearl_daily_losses_total counter",
        f"pearl_daily_losses_total {daily_stats['daily_losses']}",
        "",
        "# HELP pearl_signal_rate_per_hour Signals generated in the last hour",
        "# TYPE pearl_signal_rate_per_hour gauge",
        f"pearl_signal_rate_per_hour {signals_last_hour}",
        "",
        "# HELP pearl_websocket_connections Active WebSocket connections",
        "# TYPE pearl_websocket_connections gauge",
        f"pearl_websocket_connections {len(ws_manager.active_connections)}",
        "",
        "# HELP pearl_agent_running Whether the trading agent is running (1=yes, 0=no)",
        "# TYPE pearl_agent_running gauge",
        f"pearl_agent_running {1 if state.get('running', False) else 0}",
        "",
        "# HELP pearl_agent_paused Whether the trading agent is paused (1=yes, 0=no)",
        "# TYPE pearl_agent_paused gauge",
        f"pearl_agent_paused {1 if state.get('paused', False) else 0}",
        "",
        "# HELP pearl_data_fresh Whether market data is fresh (1=yes, 0=no)",
        "# TYPE pearl_data_fresh gauge",
        f"pearl_data_fresh {1 if state.get('data_fresh', False) else 0}",
        "",
        "# HELP pearl_gateway_status IBKR gateway connection status (1=online, 0=offline)",
        "# TYPE pearl_gateway_status gauge",
        f"pearl_gateway_status {gateway_online}",
        "",
        "# HELP pearl_gateway_port_listening IBKR gateway port responding (1=yes, 0=no)",
        "# TYPE pearl_gateway_port_listening gauge",
        f"pearl_gateway_port_listening {1 if gateway.get('port_listening', False) else 0}",
        "",
    ]

    # Add circuit breaker metrics if available
    circuit_breaker = state.get("trading_circuit_breaker", {})
    if circuit_breaker:
        blocks = circuit_breaker.get("blocks_by_reason", {})
        lines.extend([
            "# HELP pearl_circuit_breaker_blocks Signals blocked by circuit breaker (by reason)",
            "# TYPE pearl_circuit_breaker_blocks counter",
        ])
        for reason, count in blocks.items():
            lines.append(f'pearl_circuit_breaker_blocks{{reason="{reason}"}} {count}')
        lines.append("")

    # Add performance metrics
    perf = _compute_performance_stats(_state_dir)
    if perf:
        lines.extend([
            "# HELP pearl_win_rate_24h Win rate in the last 24 hours (percentage)",
            "# TYPE pearl_win_rate_24h gauge",
            f"pearl_win_rate_24h {perf.get('24h', {}).get('win_rate', 0)}",
            "",
            "# HELP pearl_pnl_24h P&L in the last 24 hours",
            "# TYPE pearl_pnl_24h gauge",
            f"pearl_pnl_24h {perf.get('24h', {}).get('pnl', 0)}",
            "",
        ])

    # Add risk metrics
    risk = _get_risk_metrics(_state_dir)
    if risk:
        lines.extend([
            "# HELP pearl_max_drawdown Maximum drawdown in dollars",
            "# TYPE pearl_max_drawdown gauge",
            f"pearl_max_drawdown {risk.get('max_drawdown', 0)}",
            "",
            "# HELP pearl_profit_factor Profit factor (gross profit / gross loss)",
            "# TYPE pearl_profit_factor gauge",
            f"pearl_profit_factor {risk.get('profit_factor', 0) or 0}",
            "",
            "# HELP pearl_expectancy Expected value per trade",
            "# TYPE pearl_expectancy gauge",
            f"pearl_expectancy {risk.get('expectancy', 0)}",
            "",
        ])

    # Return as Prometheus text format
    from starlette.responses import Response as StarletteResponse
    return StarletteResponse(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _market, _state_dir

    parser = argparse.ArgumentParser(description="Pearl Algo Web App API Server")
    parser.add_argument("--market", default=os.getenv("PEARLALGO_MARKET", DEFAULT_MARKET))
    parser.add_argument("--host", default=os.getenv("API_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("API_PORT", DEFAULT_PORT)))
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    args = parser.parse_args()

    _market = str(args.market or DEFAULT_MARKET).strip().upper()
    _state_dir = _resolve_state_dir(_market)

    print(f"Starting Pearl Algo Web App API Server")
    print(f"  Market: {_market}")
    print(f"  State dir: {_state_dir}")
    print(f"  Listening: http://{args.host}:{args.port}")
    print(f"  Auto-reload: {'ON' if args.reload else 'OFF'}")
    print(f"")
    print(f"Endpoints:")
    print(f"  GET /api/candles?symbol=MNQ&timeframe=5m&bars=72")
    print(f"  GET /api/indicators?symbol=MNQ&timeframe=5m&bars=72")
    print(f"  GET /api/markers?hours=6")
    print(f"  GET /api/sessions?hours=6")
    print(f"  GET /api/state")
    print(f"  GET /api/trades")
    print(f"  GET /api/metrics (Prometheus format)")
    print(f"  GET /health")
    print(f"")
    print(f"Tips:")
    print(f"  - Use --reload for development (auto-restarts on file changes)")
    print(f"  - Set API_PORT=8001 to use different port")
    print(f"  - Kill server: pkill -f 'api_server.py'")

    if args.reload:
        # Use uvicorn's reload feature for development
        uvicorn.run(
            "scripts.pearlalgo_web_app.api_server:app",
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[str(PROJECT_ROOT / "scripts" / "pearlalgo_web_app")],
            log_level="info",
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
