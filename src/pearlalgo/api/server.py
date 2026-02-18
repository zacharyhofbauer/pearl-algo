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
import logging
import os
import statistics
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

# Thread pool for running blocking I/O (data provider calls, file reads)
_executor = ThreadPoolExecutor(max_workers=4)


def _read_json_sync(path: Path) -> Any:
    """Read and parse a JSON file (sync, for use with run_in_executor).

    Returns ``None`` when the file does not exist or cannot be parsed.

    Delegates to :func:`~pearlalgo.utils.state_io.load_json_file` for
    consistent encoding/error handling, translating its ``{}`` sentinel to
    ``None`` for backward compatibility with callers.
    """
    from pearlalgo.utils.state_io import load_json_file

    data = load_json_file(path)
    return data or None


async def _read_json_async(path: Path) -> Any:
    """Read and parse a JSON file without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _read_json_sync, path)

# Cache for candle data when market is closed (LRU, bounded)
_CANDLE_CACHE_MAX_ENTRIES = 50
_candle_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
_candle_cache_lock = threading.Lock()


def _candle_cache_get(key: str) -> Optional[List[Dict[str, Any]]]:
    """Get a value from the candle cache, promoting it to most-recently-used."""
    with _candle_cache_lock:
        if key in _candle_cache:
            _candle_cache.move_to_end(key)
            return _candle_cache[key]
        return None


def _candle_cache_set(key: str, value: List[Dict[str, Any]]) -> None:
    """Set a value in the candle cache with LRU eviction."""
    with _candle_cache_lock:
        if key in _candle_cache:
            _candle_cache.move_to_end(key)
        _candle_cache[key] = value
        while len(_candle_cache) > _CANDLE_CACHE_MAX_ENTRIES:
            _candle_cache.popitem(last=False)

# Project root: src/pearlalgo/api/server.py -> src/pearlalgo/api -> src/pearlalgo -> src -> project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

try:
    from fastapi import FastAPI, Query, HTTPException, WebSocket, WebSocketDisconnect, Depends, Security, Body, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.security import APIKeyHeader, APIKeyQuery
    import uvicorn
except ImportError:
    print("ERROR: FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)

import hashlib
import secrets

from pearlalgo.market_agent.stats_computation import (
    compute_daily_stats as _shared_compute_daily_stats,
    get_trading_day_start as _shared_get_trading_day_start,
)
from pearlalgo.utils.state_io import (
    load_json_file as _load_json_file,
    load_jsonl_file as _load_jsonl_file,
    atomic_write_json as _atomic_write_json,
)
from pearlalgo.market_agent.state_reader import StateReader
from pearlalgo.execution.tradovate.utils import tradovate_fills_to_trades as _tradovate_fills_to_trades

# -- Extracted modules (Phase 0 refactor) ------------------------------------
from pearlalgo.api.data_layer import (
    cached as _cached_new,
    read_state_for_dir as _read_state_for_dir_new,
    is_tv_paper_account as _is_tv_paper_account_new,
    get_start_balance as _get_start_balance_new,
    get_cached_performance_data as _get_cached_performance_data_new,
    load_performance_data as _load_performance_data_new,
    get_signals as _get_signals,
    TvPaperChallengeState,
)
from pearlalgo.api.tradovate_helpers import (
    normalize_fill as _normalize_fill_new,
    get_tradovate_state as _get_tradovate_state_new,
    get_paired_tradovate_trades as _get_paired_tradovate_trades,
    tradovate_positions_for_api as _tradovate_positions_for_api_new,
    tradovate_performance_summary as _tradovate_performance_summary_new,
    tradovate_performance_for_period as _tradovate_performance_for_period_new,
)
from pearlalgo.api.metrics import (
    compute_risk_metrics,
    DEFAULT_RISK_METRICS,
)

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL Cache for expensive broadcast-loop helpers
# ---------------------------------------------------------------------------

_ttl_cache: Dict[str, Any] = {}
_ttl_cache_lock = threading.Lock()
_TTL_CLEANUP_INTERVAL = 60.0  # seconds between expired-entry sweeps
_last_ttl_cleanup: float = 0.0


def _cleanup_ttl_cache() -> None:
    """Remove all expired entries from ``_ttl_cache``.

    Must be called while ``_ttl_cache_lock`` is held.
    """
    global _last_ttl_cleanup
    now = time.monotonic()
    expired_keys = [k for k, (_, expires) in _ttl_cache.items() if now >= expires]
    for k in expired_keys:
        del _ttl_cache[k]
    _last_ttl_cleanup = now


def _cached(key: str, ttl_seconds: float, fn, *args, **kwargs):
    """Return cached result if still fresh, otherwise call fn and cache."""
    now = time.monotonic()
    with _ttl_cache_lock:
        # Periodic cleanup of expired entries
        if now - _last_ttl_cleanup >= _TTL_CLEANUP_INTERVAL:
            _cleanup_ttl_cache()

        entry = _ttl_cache.get(key)
        if entry is not None:
            value, expires = entry
            if now < expires:
                return value
    # Compute outside lock to avoid blocking other readers
    result = fn(*args, **kwargs)
    with _ttl_cache_lock:
        _ttl_cache[key] = (result, now + ttl_seconds)
    return result


def _get_cached_performance_data(state_dir: Path) -> dict:
    """Delegates to :func:`pearlalgo.api.data_layer.get_cached_performance_data`."""
    return _get_cached_performance_data_new(state_dir)


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
# Set PEARL_API_AUTH_ENABLED=false explicitly to disable (e.g. trusted local dev).

_auth_enabled: bool = os.getenv("PEARL_API_AUTH_ENABLED", "true").lower() == "true"
_api_keys: set = set()
_api_key_file: Optional[Path] = None

# ---------------------------------------------------------------------------
# Rate Limiting for Operator Endpoints
# ---------------------------------------------------------------------------

import collections as _collections

_rate_limit_window: int = 60  # seconds
_rate_limit_max: int = 5  # max requests per window per endpoint
_rate_limit_buckets: Dict[str, _collections.deque] = {}
_RATE_LIMIT_MAX_ENDPOINTS: int = 1000  # cap on tracked endpoints
_rate_limit_lock = threading.Lock()  # thread safety for concurrent access


def _check_rate_limit(endpoint: str) -> None:
    """
    Simple in-memory token bucket rate limiter for operator endpoints.

    Raises HTTPException(429) if the rate limit is exceeded.
    Thread-safe: uses _rate_limit_lock for concurrent access.
    """
    import time as _time

    now = _time.monotonic()
    with _rate_limit_lock:
        bucket = _rate_limit_buckets.setdefault(endpoint, _collections.deque())

        # Evict expired entries from this bucket
        while bucket and bucket[0] < now - _rate_limit_window:
            bucket.popleft()

        if len(bucket) >= _rate_limit_max:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {endpoint}. Max {_rate_limit_max} requests per {_rate_limit_window}s.",
            )

        bucket.append(now)

        # Periodic full cleanup: remove stale endpoint entries (Issue 18)
        if len(_rate_limit_buckets) > _RATE_LIMIT_MAX_ENDPOINTS:
            stale = [k for k, v in _rate_limit_buckets.items() if not v or v[-1] < now - _rate_limit_window]
            for k in stale:
                del _rate_limit_buckets[k]

# Security schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

# ---------------------------------------------------------------------------
# Operator Passphrase (public read-only, operator-only interactivity)
# ---------------------------------------------------------------------------
#
# If PEARL_OPERATOR_PASSPHRASE is set, interactive endpoints require the caller
# to present it via the X-PEARL-OPERATOR header (in addition to any API key).
#
# This enables a shareable, read-only dashboard link while keeping actions + chat
# operator-only, without exposing secrets in the public frontend bundle.
#
# Environment variables:
# - PEARL_OPERATOR_PASSPHRASE=<secret phrase>  (recommended)
# - PEARL_OPERATOR_PHRASE=<secret phrase>      (alias)
# - PEARL_OPERATOR_MAX_ATTEMPTS_PER_MINUTE=20  (basic brute-force throttling)
#
_operator_passphrase: str = (
    os.getenv("PEARL_OPERATOR_PASSPHRASE") or os.getenv("PEARL_OPERATOR_PHRASE") or ""
).strip()
_operator_enabled: bool = bool(_operator_passphrase)

operator_header = APIKeyHeader(name="X-PEARL-OPERATOR", auto_error=False)
_operator_failures: Dict[str, List[float]] = {}
_operator_max_attempts_per_minute: int = int(os.getenv("PEARL_OPERATOR_MAX_ATTEMPTS_PER_MINUTE", "20") or "20")
_OPERATOR_FAILURES_MAX_CLIENTS: int = 1000  # cap on tracked client IPs
_operator_failures_lock = threading.Lock()  # thread safety for concurrent access


def _get_client_id(request: Request) -> str:
    """Best-effort client identifier for basic throttling."""
    try:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return (fwd.split(",")[0] or "").strip() or "unknown"
    except Exception as e:
        logger.warning(f"Non-critical: {e}")
    try:
        return request.client.host if request.client else "unknown"
    except Exception:
        logger.debug("Failed to determine client host", exc_info=True)
        return "unknown"


async def verify_operator(
    request: Request,
    operator: Optional[str] = Security(operator_header),
) -> Optional[str]:
    """
    Verify operator passphrase if configured.

    Returns operator token if valid, None if operator mode is disabled.
    Raises HTTPException on invalid/missing operator token when enabled.
    """
    if not _operator_enabled:
        return None

    client_id = _get_client_id(request)
    now = time.time()

    with _operator_failures_lock:
        bucket = _operator_failures.get(client_id, [])
        # Keep only last 60 seconds
        bucket = [t for t in bucket if now - t < 60.0]
        _operator_failures[client_id] = bucket

        if _operator_max_attempts_per_minute > 0 and len(bucket) >= _operator_max_attempts_per_minute:
            raise HTTPException(status_code=429, detail="Too many attempts.")

        if not operator:
            bucket.append(now)
            raise HTTPException(status_code=403, detail="Operator access required.")

        # Constant-time compare
        if secrets.compare_digest(operator.strip(), _operator_passphrase):
            return operator

        bucket.append(now)

        # Periodic cleanup: remove stale client entries (Issue 18)
        if len(_operator_failures) > _OPERATOR_FAILURES_MAX_CLIENTS:
            stale_clients = [k for k, v in _operator_failures.items()
                            if not v or v[-1] < now - 120.0]
            for k in stale_clients:
                del _operator_failures[k]

    raise HTTPException(status_code=403, detail="Operator access required.")


async def require_operator_or_api_key(
    request: Request,
    operator: Optional[str] = Security(operator_header),
    api_key_from_header: Optional[str] = Security(api_key_header),
    api_key_from_query: Optional[str] = Security(api_key_query),
) -> str:
    """
    Require either operator passphrase (if configured) or API key (if auth enabled).

    This is used for interactive endpoints: kill switch, close trades, and LLM chat.
    """
    if _operator_enabled:
        # Enforce operator passphrase when configured (public link can remain read-only).
        await verify_operator(request=request, operator=operator)
        return "operator"

    # Fall back to API-key auth when operator mode is not configured.
    if not _auth_enabled:
        raise HTTPException(status_code=403, detail="Operator access required.")

    api_key = (api_key_from_header or api_key_from_query or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header or api_key query parameter.",
        )
    if not any(secrets.compare_digest(api_key, k) for k in _api_keys):
        raise HTTPException(status_code=403, detail="Invalid API key.")

    return "api_key"


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
        # Write auto-generated key to a file (mode 0600) instead of stdout
        # to avoid leaking secrets in logs / log aggregators.
        try:
            auto_key_file = PROJECT_ROOT / "data" / ".api_key"
            auto_key_file.parent.mkdir(parents=True, exist_ok=True)
            auto_key_file.write_text(auto_key + "\n")
            os.chmod(str(auto_key_file), 0o600)
            print(f"[Auth] Auto-generated API key written to {auto_key_file} (mode 0600)")
        except Exception as e:
            # Last resort: print to stdout only if file write fails
            print(f"[Auth] WARNING: Could not write API key to file ({e}), printing to stdout")
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
    api_key_query: Optional[str] = Security(api_key_query),
) -> Optional[str]:
    """
    Verify API key from header or query parameter.

    Returns the API key if valid, None if auth disabled.
    Raises HTTPException if auth enabled but key invalid/missing.
    """
    if not _auth_enabled:
        return None

    # Check header first, then query param
    api_key = api_key_header or api_key_query

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header or api_key query parameter.",
        )

    if not any(secrets.compare_digest(api_key, k) for k in _api_keys):
        raise HTTPException(
            status_code=403,
            detail="Invalid API key.",
        )

    return api_key


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



# _load_json_file and _load_jsonl_file imported directly from pearlalgo.utils.state_io above.

_DEFAULT_START_BALANCE = 50000.0


def _get_start_balance(state_dir: Path) -> float:
    """Delegates to :func:`pearlalgo.api.data_layer.get_start_balance`."""
    return _get_start_balance_new(state_dir)


# ---------------------------------------------------------------------------
# Data Provider (reads from IBKR - NO mock data fallback)
# ---------------------------------------------------------------------------

_data_provider = None
_data_provider_error: Optional[str] = None


class DataUnavailableError(Exception):
    """Raised when real market data is not available."""
    pass


def _get_candle_cache_dir() -> Path:
    """Return the directory for per-key candle cache files."""
    return PROJECT_ROOT / "data"


def _per_key_cache_path(key: str) -> Path:
    """Return the cache file path for a specific candle cache key.

    Each symbol/timeframe/bars combination gets its own file, e.g.
    ``candle_cache_MNQ_5m_72.json``, avoiding the need to read-modify-write
    a single monolithic cache file.
    """
    return _get_candle_cache_dir() / f"candle_cache_{key}.json"


def _save_candle_cache(key: str, candles: List[Dict[str, Any]]) -> None:
    """Save candles to cache (memory and per-key disk file)."""
    _candle_cache_set(key, candles)

    # Persist to a per-key file for crash-safe restarts
    try:
        cache_path = _per_key_cache_path(key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(cache_path, {
            "candles": candles,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.debug(f"Cache write failures are not critical: {e}")


def _load_candle_cache(key: str) -> Optional[List[Dict[str, Any]]]:
    """Load candles from cache."""
    # Try memory cache first (promotes to most-recently-used)
    cached_value = _candle_cache_get(key)
    if cached_value is not None:
        return cached_value

    # Try per-key disk cache
    try:
        cache_path = _per_key_cache_path(key)
        if cache_path.exists():
            data = json.loads(cache_path.read_text())
            # Check if cache is less than 24 hours old
            cache_time = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - cache_time < timedelta(hours=24):
                _candle_cache_set(key, data["candles"])
                return data["candles"]
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

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
) -> tuple[List[Dict[str, Any]], str]:
    """
    Fetch OHLCV candles from IBKR and return with data source indicator.

    If live data is unavailable and use_cache_fallback is True, returns cached data.

    Returns:
        Tuple of (candles, data_source) where data_source is ``'live'`` or ``'cache'``.
        Candles are in TradingView Lightweight Charts format:
        [{"time": 1706500000, "open": 26200, "high": 26210, "low": 26195, "close": 26205}, ...]
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
        except Exception as e:
            logger.debug(f"Fall through to cache: {e}")

    # Try cache fallback
    if use_cache_fallback:
        cached = _load_candle_cache(cache_key)
        if cached:
            return (cached, "cache")

    # No live data and no cache
    raise DataUnavailableError(
        f"Market closed - no live data available. Cache not found for {symbol} {timeframe}."
    )


from pearlalgo.api.indicator_service import calculate_indicators as _calculate_indicators  # noqa: E402


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

# Route modules (health; more to follow per plan 15A)
from pearlalgo.api.routes.health import router as _health_router
app.include_router(_health_router)


# ---------------------------------------------------------------------------
# Request body size limit middleware (defence-in-depth against OOM)
# ---------------------------------------------------------------------------
_MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024  # 1 MB


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    """Reject requests whose Content-Length exceeds the configured limit."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large. Max {_MAX_REQUEST_BODY_BYTES} bytes."},
                )
        except ValueError:
            pass  # malformed header — let downstream handle it
    return await call_next(request)


# Path prefix stripping middleware for reverse-proxy deployments
# (e.g., Cloudflare Tunnel routes /tv_paper/api/* to port 8001)
@app.middleware("http")
async def strip_path_prefix(request, call_next):
    """Strip /tv_paper prefix so routes match when behind a reverse proxy."""
    path = request.scope.get("path", "")
    if path.startswith("/tv_paper/"):
        request.scope["path"] = path[9:]  # Remove "/tv_paper" prefix, keep the "/"
    elif path == "/tv_paper":
        request.scope["path"] = "/"
    return await call_next(request)

# Global state
_market: str = DEFAULT_MARKET
_state_dir: Optional[Path] = None
_state_reader: Optional[StateReader] = None


def _require_state_dir() -> Path:
    """Return ``_state_dir`` or raise 500 if not configured."""
    if _state_dir is None:
        raise HTTPException(status_code=500, detail="State directory not configured")
    return _state_dir


def _get_state_reader() -> Optional[StateReader]:
    """Return the global StateReader, creating it lazily if _state_dir is set."""
    global _state_reader
    if _state_reader is None and _state_dir is not None:
        _state_reader = StateReader(_state_dir)
    return _state_reader


def _read_state_safe() -> Dict[str, Any]:
    """Read state.json via StateReader (locked) with fallback to direct read."""
    reader = _get_state_reader()
    if reader is not None:
        return reader.read_state()
    # Fallback: direct read when state_dir not configured
    if _state_dir is not None:
        return _load_json_file(_state_dir / "state.json") or {}
    return {}


# Cache of StateReader instances per state_dir (for multi-market helpers)
# Bounded to avoid unbounded memory growth; LRU eviction via OrderedDict.
_STATE_READER_CACHE_MAX = 10
_state_reader_cache: OrderedDict[str, StateReader] = OrderedDict()
_state_reader_cache_lock = threading.Lock()


def _read_state_for_dir(state_dir: Path) -> Dict[str, Any]:
    """Read state.json via a locked StateReader for the given directory.

    Caches the StateReader per directory to avoid repeated construction.
    Thread-safe with LRU eviction (max ``_STATE_READER_CACHE_MAX`` entries).
    """
    key = str(state_dir)
    with _state_reader_cache_lock:
        if key in _state_reader_cache:
            _state_reader_cache.move_to_end(key)
            return _state_reader_cache[key].read_state()
    # Build outside lock to avoid blocking other readers during construction
    reader = StateReader(state_dir)
    with _state_reader_cache_lock:
        # Another thread may have inserted while we were constructing
        if key not in _state_reader_cache:
            _state_reader_cache[key] = reader
            while len(_state_reader_cache) > _STATE_READER_CACHE_MAX:
                _state_reader_cache.popitem(last=False)
        else:
            _state_reader_cache.move_to_end(key)
            reader = _state_reader_cache[key]
    return reader.read_state()


# ---------------------------------------------------------------------------
# WebSocket Connection Manager
# ---------------------------------------------------------------------------

_WS_MAX_CONNECTIONS: int = 100  # max concurrent WebSocket connections


# ---------------------------------------------------------------------------
# Broadcast-only helpers (sync, run via run_in_executor)
# ---------------------------------------------------------------------------

def _get_positions_for_broadcast(state_dir: Path) -> List[Dict[str, Any]]:
    """Build positions list for the WS broadcast payload.

    Reuses the same logic as ``/api/positions`` but via cached data.
    """
    try:
        if _is_tv_paper_account(state_dir):
            tv, _ = _get_tradovate_state(state_dir)
            positions = _tradovate_positions_for_api(tv)
            # Enrich with TP/SL from virtual signals
            if positions:
                try:
                    signals = _get_signals(state_dir, max_lines=300)
                    active_signals = [
                        s for s in signals
                        if s.get("status") == "entered" and s.get("signal", {}).get("stop_loss")
                    ]
                    for pos in positions:
                        matching = [
                            s for s in active_signals
                            if (s.get("signal", {}).get("direction", "").lower() == pos["direction"])
                        ]
                        if matching:
                            best = min(
                                matching,
                                key=lambda s: abs(float(s.get("entry_price", 0) or 0) - pos["entry_price"]),
                            )
                            sig = best.get("signal", {})
                            pos["stop_loss"] = sig.get("stop_loss")
                            pos["take_profit"] = sig.get("take_profit")
                except Exception:
                    logger.debug("Failed to enrich positions with SL/TP from signals", exc_info=True)
                    pass
            return positions

        # IBKR Virtual: from signals.jsonl
        # Optimize: only read recent signals (enough to find active positions, typically <50)
        signals = _get_signals(state_dir, max_lines=100)
        positions = []
        for s in signals:
            if s.get("status") == "exited":
                continue
            entry_price = s.get("entry_price")
            if not entry_price:
                continue
            signal_data = s.get("signal", {})
            direction = signal_data.get("direction", "long") if isinstance(signal_data, dict) else s.get("direction", "long")
            symbol = signal_data.get("symbol") if isinstance(signal_data, dict) else None
            position_size = signal_data.get("position_size") if isinstance(signal_data, dict) else None
            stop_loss = signal_data.get("stop_loss") if isinstance(signal_data, dict) else None
            take_profit = signal_data.get("take_profit") if isinstance(signal_data, dict) else None
            positions.append({
                "signal_id": s.get("signal_id"),
                "symbol": symbol or "MNQ",
                "direction": direction,
                "position_size": position_size,
                "entry_price": entry_price,
                "entry_time": s.get("entry_time"),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            })
        return positions
    except Exception as e:
        logger.debug(f"Broadcast positions error: {e}")
        return []


def _get_trades_for_broadcast(state_dir: Path, limit: int = 50) -> List[Dict[str, Any]]:
    """Build recent trades list for the WS broadcast payload."""
    try:
        if _is_tv_paper_account(state_dir):
            trades = _get_paired_tradovate_trades(state_dir)
            return trades[-limit:]

        # Optimize: only read enough lines to get 'limit' exited trades (typically need ~2-3x limit)
        # Cap at 1000 to avoid reading entire file for large signals.jsonl
        read_lines = min(max(limit * 3, 100), 1000)
        signals = _get_signals(state_dir, max_lines=read_lines)
        trades = []
        for s in signals:
            if s.get("status") != "exited":
                continue
            signal_data = s.get("signal", {})
            if not isinstance(signal_data, dict):
                signal_data = {}
            trades.append({
                "signal_id": s.get("signal_id"),
                "symbol": signal_data.get("symbol") or s.get("symbol") or "MNQ",
                "direction": signal_data.get("direction") or s.get("direction"),
                "position_size": signal_data.get("position_size"),
                "entry_time": s.get("entry_time"),
                "entry_price": s.get("entry_price"),
                "exit_time": s.get("exit_time"),
                "exit_price": s.get("exit_price"),
                "pnl": s.get("pnl"),
                "exit_reason": s.get("exit_reason"),
            })
        return trades[-limit:]
    except Exception as e:
        logger.debug(f"Broadcast trades error: {e}")
        return []


def _get_performance_summary_for_broadcast(state_dir: Path) -> Optional[Dict[str, Any]]:
    """Build performance summary for the WS broadcast payload.

    Returns the same structure as ``/api/performance-summary`` but cached.
    """
    def _compute() -> Optional[Dict[str, Any]]:
        try:
            if _is_tv_paper_account(state_dir):
                tv, fills = _get_tradovate_state(state_dir)
                equity_stats = _tradovate_performance_summary(tv, fills, state_dir)

                now = datetime.now(timezone.utc)
                td_start = _get_trading_day_start()
                yday_start, yday_end = _get_previous_trading_day_bounds()
                wtd_start = _get_trading_week_start(now)
                mtd_start = _get_month_to_date_start(now)
                ytd_start = _get_year_to_date_start(now)
                all_start = datetime(2020, 1, 1, tzinfo=timezone.utc)

                all_trades_raw = _tradovate_fills_to_trades(fills)
                total_fill_pnl = sum(t.get("pnl", 0) or 0 for t in all_trades_raw)
                equity = float(tv.get("equity", 0)) if tv else 0
                start_balance = _get_start_balance(state_dir)
                total_trades = len(all_trades_raw)

                # Commission estimation requires live equity as ground truth.
                # When equity is 0 (adapter offline), skip commission deduction
                # and use raw fill P&L to avoid wildly incorrect numbers.
                commission_per_trade = 0.0
                if equity > 0:
                    equity_pnl = equity - start_balance
                    if total_trades > 0 and total_fill_pnl > equity_pnl:
                        commission_per_trade = (total_fill_pnl - equity_pnl) / total_trades

                cpt = commission_per_trade
                all_fill_stats = _tradovate_performance_for_period(fills, all_start, commission_per_trade=cpt)

                # Provide equity (live) or estimated equity (start_balance + fill P&L)
                live_equity = equity_stats.get("tradovate_equity", 0)
                if live_equity:
                    all_fill_stats["tradovate_equity"] = live_equity
                else:
                    all_fill_stats["tradovate_equity"] = round(start_balance + total_fill_pnl, 2)

                return {
                    "as_of": now.isoformat(),
                    "td": _tradovate_performance_for_period(fills, td_start, commission_per_trade=cpt),
                    "yday": _tradovate_performance_for_period(fills, yday_start, yday_end, commission_per_trade=cpt),
                    "wtd": _tradovate_performance_for_period(fills, wtd_start, commission_per_trade=cpt),
                    "mtd": _tradovate_performance_for_period(fills, mtd_start, commission_per_trade=cpt),
                    "ytd": _tradovate_performance_for_period(fills, ytd_start, commission_per_trade=cpt),
                    "all": all_fill_stats,
                }

            # IBKR Virtual
            cached_perf = _get_cached_performance_data(state_dir)
            trades = cached_perf.get("trades")
            if trades is None:
                empty = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
                return {
                    "as_of": datetime.now(timezone.utc).isoformat(),
                    "td": empty, "yday": empty, "wtd": empty,
                    "mtd": empty, "ytd": empty, "all": empty,
                }

            now = datetime.now(timezone.utc)
            td_start = _get_trading_day_start()
            yday_start, yday_end = _get_previous_trading_day_bounds()
            wtd_start = _get_trading_week_start(now)
            mtd_start = _get_month_to_date_start(now)
            ytd_start = _get_year_to_date_start(now)
            all_time_start = datetime(2020, 1, 1, tzinfo=timezone.utc)

            return {
                "as_of": now.isoformat(),
                "td": _aggregate_performance_since(trades, td_start),
                "yday": _aggregate_performance_since(trades, yday_start, yday_end),
                "wtd": _aggregate_performance_since(trades, wtd_start),
                "mtd": _aggregate_performance_since(trades, mtd_start),
                "ytd": _aggregate_performance_since(trades, ytd_start),
                "all": _aggregate_performance_since(trades, all_time_start),
            }
        except Exception as e:
            logger.debug(f"Broadcast performance-summary error: {e}")
            return None

    return _cached("broadcast_perf_summary", 3.0, _compute)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._broadcast_task: Optional[asyncio.Task] = None
        self._last_state_hash: str = ""
        # File mtime fingerprint to avoid unnecessary disk reads + json.dumps
        self._last_state_mtime_ns: int = 0
        self._last_state_size: int = 0
        self._cached_state: Dict[str, Any] = {}

    async def connect(self, websocket: WebSocket) -> bool:
        """Register a new WebSocket connection (assumes accepted).

        Returns False if the connection cap has been reached.
        """
        if len(self.active_connections) >= _WS_MAX_CONNECTIONS:
            logger.warning(f"[WebSocket] Connection rejected: max {_WS_MAX_CONNECTIONS} reached")
            return False
        self.active_connections.append(websocket)
        print(f"[WebSocket] Client connected. Total connections: {len(self.active_connections)}")
        return True

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WebSocket] Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients using asyncio.gather."""
        if not self.active_connections:
            return

        async def _safe_send(conn: WebSocket) -> Optional[WebSocket]:
            try:
                await asyncio.wait_for(conn.send_json(message), timeout=5.0)
                return None
            except Exception:
                logger.debug("WebSocket send failed, marking connection for removal", exc_info=True)
                return conn  # mark for removal

        # Copy list to avoid mutation during iteration
        results = await asyncio.gather(
            *[_safe_send(conn) for conn in list(self.active_connections)],
            return_exceptions=True,
        )

        # Clean up disconnected / timed-out clients (_safe_send returns conn to remove)
        for result in results:
            if isinstance(result, Exception):
                pass  # gather caught it
            elif result is not None:
                self.disconnect(result)

    async def start_broadcast_loop(self, interval: float = 2.0):
        """Start broadcasting state updates at regular intervals."""
        while True:
            try:
                if _state_dir:
                    # Get current state (use empty dict as fallback so we can
                    # still broadcast challenge/performance data when the agent
                    # is stopped and state.json doesn't exist).
                    state_file = _state_dir / "state.json"

                    # Use file mtime + size as a cheap fingerprint to avoid
                    # unnecessary disk reads and json.dumps serialization.
                    try:
                        st = state_file.stat()
                        if st.st_mtime_ns != self._last_state_mtime_ns or st.st_size != self._last_state_size:
                            self._last_state_mtime_ns = st.st_mtime_ns
                            self._last_state_size = st.st_size
                            self._cached_state = await asyncio.get_event_loop().run_in_executor(None, _read_state_safe)
                    except FileNotFoundError:
                        if self._cached_state:
                            self._cached_state = {}
                            self._last_state_mtime_ns = 0
                            self._last_state_size = 0
                    except Exception as e:
                        logger.warning(f"Non-critical: {e}")
                    state = self._cached_state

                    if state or _get_challenge_status(_state_dir):
                        # -- Fingerprint-first: only compute payload when state changed --
                        combined_hash = f"{self._last_state_mtime_ns}:{self._last_state_size}"

                        if self.active_connections and combined_hash != self._last_state_hash:
                            self._last_state_hash = combined_hash

                            # Build the full broadcast payload (computed only on change)
                            daily_stats = await asyncio.get_event_loop().run_in_executor(None, _compute_daily_stats, _state_dir)

                            broadcast_payload = {
                                "running": state.get("running", False),
                                "paused": state.get("paused", False),
                                "daily_pnl": daily_stats["daily_pnl"],
                                "daily_trades": daily_stats["daily_trades"],
                                "daily_wins": daily_stats["daily_wins"],
                                "daily_losses": daily_stats["daily_losses"],
                                # For Tradovate Paper: use Tradovate position count & open PnL
                                "active_trades_count": daily_stats.get("tradovate_positions", state.get("active_trades_count", 0)),
                                "active_trades_unrealized_pnl": daily_stats.get("tradovate_open_pnl", state.get("active_trades_unrealized_pnl")),
                                "futures_market_open": state.get("futures_market_open", False),
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
                                # Performance data
                                "challenge": _get_challenge_status(_state_dir),
                                "recent_exits": _cached("recent_exits", 5.0, _get_recent_exits, _state_dir, limit=100),
                                "performance": _compute_performance_stats(_state_dir),
                                "equity_curve": _cached("equity_curve", 10.0, _get_equity_curve, _state_dir, hours=72),
                                "risk_metrics": _cached("risk_metrics", 10.0, _get_risk_metrics, _state_dir),
                                # --- NEW: positions, trades, performance_summary ---
                                # These were previously HTTP-only (30s poll).  Including them
                                # here gives the frontend ~2s latency on trade updates.
                                "positions": await asyncio.get_event_loop().run_in_executor(
                                    None, partial(_cached, "positions_broadcast", 2.5, _get_positions_for_broadcast, _state_dir)),
                                "recent_trades": await asyncio.get_event_loop().run_in_executor(
                                    None, partial(_cached, "trades_broadcast", 2.5, _get_trades_for_broadcast, _state_dir, 50)),
                                "performance_summary": await asyncio.get_event_loop().run_in_executor(
                                    None, partial(_cached, "performance_broadcast", 2.5, _get_performance_summary_for_broadcast, _state_dir)),
                                # Signal activity & execution state
                                "signal_rejections_24h": state.get("signal_rejections_24h"),
                                "last_signal_decision": state.get("last_signal_decision"),
                                "shadow_counters": state.get("shadow_counters"),
                                "execution_state": state.get("execution_state"),
                                "tradovate_account": state.get("tradovate_account"),
                                "circuit_breaker": state.get("circuit_breaker"),
                                "ml_filter_performance": state.get("ml_filter_performance"),
                                "session_context": state.get("session_context"),
                                "signal_activity": state.get("signal_activity"),
                                # Pearl AI (removed – keys retained for web-app compat)
                                "pearl_suggestion": None,
                                "pearl_insights": None,
                                "pearl_ai_available": False,
                                "pearl_feed": [],
                                "pearl_ai_heartbeat": None,
                                "pearl_ai_debug": None,
                                "operator_lock_enabled": bool(_operator_enabled),
                            }

                            await self.broadcast({"type": "state_update", "data": broadcast_payload})

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
    global _market, _state_dir

    # Support uvicorn --reload import mode (main() may not run in that process)
    if not _market:
        _market = str(os.getenv("PEARLALGO_MARKET", DEFAULT_MARKET)).strip().upper()
    if _state_dir is None:
        _state_dir = _resolve_state_dir(_market)

    _init_auth()
    _init_accounts_config()
    asyncio.create_task(ws_manager.start_broadcast_loop(interval=2.0))


@app.websocket("/ws")
@app.websocket("/tv_paper/ws")
async def websocket_endpoint(websocket: WebSocket, api_key: Optional[str] = Query(default=None)):
    """WebSocket endpoint for real-time state updates."""
    # Verify API key if authentication is enabled.
    #
    # Supports two modes:
    # - Legacy: api_key query param (?api_key=...)
    # - Preferred (client): first WS message: {"type":"auth","api_key":"..."}
    accepted = False
    if _auth_enabled:
        key = (api_key or "").strip()
        if key:
            if key not in _api_keys:
                await websocket.close(code=1008, reason="Invalid API key")
                return
            await websocket.accept()
            accepted = True
        else:
            # Accept first so we can receive the auth message
            await websocket.accept()
            accepted = True
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            except asyncio.TimeoutError:
                await websocket.close(code=1008, reason="Missing API key")
                return

            try:
                payload = json.loads(raw)
            except Exception:
                logger.debug("Failed to parse WebSocket auth payload", exc_info=True)
                payload = None

            msg_key = ""
            if isinstance(payload, dict) and payload.get("type") == "auth":
                msg_key = str(payload.get("api_key") or "").strip()

            if not msg_key:
                await websocket.close(code=1008, reason="Missing API key")
                return
            if msg_key not in _api_keys:
                await websocket.close(code=1008, reason="Invalid API key")
                return
    else:
        await websocket.accept()
        accepted = True

    if not accepted:
        await websocket.accept()

    await ws_manager.connect(websocket)
    try:
        # Send initial state immediately (even when agent is stopped,
        # so the dashboard can show challenge / performance data).
        if _state_dir:
            state = await asyncio.get_event_loop().run_in_executor(None, _read_state_safe)
            # Broadcast if we have agent state OR persistent challenge data
            if state or _get_challenge_status(_state_dir):
                daily_stats = await asyncio.get_event_loop().run_in_executor(None, _compute_daily_stats, _state_dir)
                recent_exits = await asyncio.get_event_loop().run_in_executor(None, partial(_cached, "recent_exits", 5.0, _get_recent_exits, _state_dir, limit=100))
                # Build initial_state with the SAME field set as state_update
                # so the client has full data from the first message.
                initial_data = {
                    "type": "initial_state",
                    "data": {
                        "running": state.get("running", False),
                        "paused": state.get("paused", False),
                        "daily_pnl": daily_stats["daily_pnl"],
                        "daily_trades": daily_stats["daily_trades"],
                        "daily_wins": daily_stats["daily_wins"],
                        "daily_losses": daily_stats["daily_losses"],
                        "active_trades_count": daily_stats.get("tradovate_positions", state.get("active_trades_count", 0)),
                        "active_trades_unrealized_pnl": daily_stats.get("tradovate_open_pnl", state.get("active_trades_unrealized_pnl")),
                        "futures_market_open": state.get("futures_market_open", False),
                        "data_fresh": state.get("data_fresh", False),
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "ai_status": _get_ai_status(state),
                        "challenge": _get_challenge_status(_state_dir),
                        "recent_exits": recent_exits,
                        "performance": _compute_performance_stats(_state_dir),
                        "equity_curve": _cached("equity_curve", 10.0, _get_equity_curve, _state_dir, hours=72),
                        "risk_metrics": _cached("risk_metrics", 10.0, _get_risk_metrics, _state_dir),
                        "positions": _cached("positions_broadcast", 2.5, _get_positions_for_broadcast, _state_dir),
                        "recent_trades": _cached("trades_broadcast", 2.5, _get_trades_for_broadcast, _state_dir, 50),
                        "performance_summary": _cached("performance_broadcast", 2.5, _get_performance_summary_for_broadcast, _state_dir),
                        "cadence_metrics": _get_cadence_metrics_enhanced(state),
                        "market_regime": _get_market_regime(state),
                        "buy_sell_pressure": state.get("buy_sell_pressure_raw"),
                        "signal_rejections_24h": _get_signal_rejections_24h(state),
                        "last_signal_decision": _get_last_signal_decision(state),
                        "shadow_counters": _get_shadow_counters(state),
                        "execution_state": state.get("execution_state"),
                        "tradovate_account": state.get("tradovate_account"),
                        "circuit_breaker": state.get("circuit_breaker"),
                        "ml_filter_performance": state.get("ml_filter_performance"),
                        "session_context": state.get("session_context"),
                        "signal_activity": state.get("signal_activity"),
                        "gateway_status": _get_gateway_status(),
                        "connection_health": _get_connection_health(state),
                        "error_summary": _get_error_summary(_state_dir, state),
                        "config": _get_config(state),
                        "data_quality": _get_data_quality(state),
                        "pearl_suggestion": None,
                        "pearl_insights": None,
                        "pearl_ai_available": False,
                        "pearl_feed": [],
                        "pearl_ai_heartbeat": None,
                        "pearl_ai_debug": None,
                        "operator_lock_enabled": bool(_operator_enabled),
                    }
                }
                await websocket.send_json(initial_data)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message (ping/pong or requests)
                data = await websocket.receive_text()

                # Ignore auth payloads (client sends on connect)
                if data and data.startswith("{"):
                    try:
                        payload = json.loads(data)
                        if isinstance(payload, dict) and payload.get("type") == "auth":
                            await websocket.send_json({"type": "auth_ok"})
                            continue
                    except Exception as e:
                        logger.warning(f"Non-critical: {e}")

                # Handle ping
                if data == "ping":
                    await websocket.send_json({"type": "pong"})

                # Handle request for full state refresh
                elif data == "refresh":
                    if _state_dir:
                        state = await asyncio.get_event_loop().run_in_executor(None, _read_state_safe)
                        if state or _get_challenge_status(_state_dir):
                            daily_stats = await asyncio.get_event_loop().run_in_executor(None, _compute_daily_stats, _state_dir)
                            recent_exits = await asyncio.get_event_loop().run_in_executor(None, partial(_cached, "recent_exits", 5.0, _get_recent_exits, _state_dir, limit=100))
                            refresh_data = {
                                "type": "full_refresh",
                                "data": {
                                    "running": state.get("running", False),
                                    "paused": state.get("paused", False),
                                    "daily_pnl": daily_stats["daily_pnl"],
                                    "daily_trades": daily_stats["daily_trades"],
                                    "daily_wins": daily_stats["daily_wins"],
                                    "daily_losses": daily_stats["daily_losses"],
                                    "active_trades_count": daily_stats.get("tradovate_positions", state.get("active_trades_count", 0)),
                                    "active_trades_unrealized_pnl": daily_stats.get("tradovate_open_pnl", state.get("active_trades_unrealized_pnl")),
                                    "futures_market_open": state.get("futures_market_open", False),
                                    "data_fresh": state.get("data_fresh", False),
                                    "last_updated": datetime.now(timezone.utc).isoformat(),
                                    "ai_status": _get_ai_status(state),
                                    "challenge": _get_challenge_status(_state_dir),
                                    "recent_exits": recent_exits,
                                    "performance": _compute_performance_stats(_state_dir),
                                    "equity_curve": _cached("equity_curve", 10.0, _get_equity_curve, _state_dir, hours=72),
                                    "risk_metrics": _cached("risk_metrics", 10.0, _get_risk_metrics, _state_dir),
                                    "positions": _cached("positions_broadcast", 2.5, _get_positions_for_broadcast, _state_dir),
                                    "recent_trades": _cached("trades_broadcast", 2.5, _get_trades_for_broadcast, _state_dir, 50),
                                    "performance_summary": _cached("performance_broadcast", 2.5, _get_performance_summary_for_broadcast, _state_dir),
                                    "cadence_metrics": _get_cadence_metrics_enhanced(state),
                                    "market_regime": _get_market_regime(state),
                                    "buy_sell_pressure": state.get("buy_sell_pressure_raw"),
                                    "signal_rejections_24h": _get_signal_rejections_24h(state),
                                    "last_signal_decision": _get_last_signal_decision(state),
                                    "shadow_counters": _get_shadow_counters(state),
                                    "execution_state": state.get("execution_state"),
                                    "tradovate_account": state.get("tradovate_account"),
                                    "circuit_breaker": state.get("circuit_breaker"),
                                    "ml_filter_performance": state.get("ml_filter_performance"),
                                    "session_context": state.get("session_context"),
                                    "signal_activity": state.get("signal_activity"),
                                    "gateway_status": _get_gateway_status(),
                                    "connection_health": _get_connection_health(state),
                                    "error_summary": _get_error_summary(_state_dir, state),
                                    "config": _get_config(state),
                                    "data_quality": _get_data_quality(state),
                                    "pearl_suggestion": None,
                                    "pearl_insights": None,
                                    "pearl_ai_available": False,
                                    "pearl_feed": [],
                                    "pearl_ai_heartbeat": None,
                                    "pearl_ai_debug": None,
                                    "operator_lock_enabled": bool(_operator_enabled),
                                }
                            }
                            await websocket.send_json(refresh_data)

            except WebSocketDisconnect:
                break
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        ws_manager.disconnect(websocket)


def _get_market_status() -> Dict[str, Any]:
    """Get futures market open/closed status and next open time (via utils.market_hours)."""
    from pearlalgo.utils.market_hours import get_market_hours

    mh = get_market_hours()
    status = mh.get_market_status()
    return {
        "is_open": status["is_open"],
        "close_reason": None,
        "next_open": status.get("next_open_et") or status.get("next_open_utc"),
        "current_time_et": status["current_time_et"],
    }


@app.get("/api/candles")
async def get_candles(
    symbol: str = Query(default="MNQ", description="Symbol to fetch"),
    timeframe: str = Query(default="5m", description="Timeframe (1m, 5m, 15m, 1h)"),
    bars: int = Query(default=72, ge=10, le=500, description="Number of bars"),
    _key: Optional[str] = Depends(verify_api_key),
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
        candles, data_source = await _fetch_candles(
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
    """Delegate to shared stats_computation module (single source of truth)."""
    return _shared_get_trading_day_start()


def _compute_daily_stats(state_dir: Path) -> Dict[str, Any]:
    """Compute daily P&L and trade stats.

    Priority order for Tradovate Paper accounts:
    1. Tradovate live account data (realized PnL from broker)
    2. Shared stats_computation module (signals.jsonl with caching)
    3. Challenge state fallback
    """
    # Check for live Tradovate account data in state.json first
    try:
        state_data = _read_state_for_dir(state_dir)
        if state_data:
            tv = state_data.get("tradovate_account")
            if tv and isinstance(tv, dict) and tv.get("equity"):
                equity = float(tv.get("equity", 0))
                open_pnl = round(tv.get("open_pnl", 0.0), 2)
                pos_count = tv.get("position_count", 0)
                # Trade counts from Tradovate fills — filtered to TODAY's trading day
                trades, wins, losses, daily_pnl = 0, 0, 0, 0.0
                try:
                    tv_fills = state_data.get("tradovate_fills") or tv.get("fills") or []
                    if not tv_fills:
                        fills_file = state_dir / "tradovate_fills.json"
                        _fills_data = _read_json_sync(fills_file)
                        tv_fills = _fills_data if isinstance(_fills_data, list) else []
                    if tv_fills:
                        paired = _tradovate_fills_to_trades(tv_fills)
                        # Derive per-trade commission from equity vs fill P&L gap
                        total_fill_pnl = sum(t.get("pnl", 0) or 0 for t in paired)
                        start_balance = _get_start_balance(state_dir)
                        equity_pnl = equity - start_balance
                        cpt = 0.0  # commission per trade
                        if len(paired) > 0 and total_fill_pnl > equity_pnl:
                            cpt = (total_fill_pnl - equity_pnl) / len(paired)
                        # Filter to today's trading day for accurate daily stats
                        td_start = _get_trading_day_start()
                        today_trades = []
                        for t in paired:
                            exit_time_str = t.get("exit_time") or ""
                            if exit_time_str:
                                try:
                                    exit_dt = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                                    if exit_dt.tzinfo is None:
                                        exit_dt = exit_dt.replace(tzinfo=timezone.utc)
                                    if exit_dt >= td_start:
                                        today_trades.append(t)
                                except Exception:
                                    logger.debug("Failed to parse trade exit_time", exc_info=True)
                                    pass
                        trades = len(today_trades)
                        wins = sum(1 for t in today_trades if (t.get("pnl") or 0) > 0)
                        losses = trades - wins
                        raw_daily = sum(t.get("pnl", 0) or 0 for t in today_trades)
                        daily_pnl = round(raw_daily - (trades * cpt), 2)
                except Exception as e:
                    logger.warning(f"Non-critical: {e}")
                return {
                    "daily_pnl": daily_pnl,
                    "daily_trades": trades,
                    "daily_wins": wins,
                    "daily_losses": losses,
                    "tradovate_equity": round(equity, 2),
                    "tradovate_open_pnl": open_pnl,
                    "tradovate_positions": pos_count,
                }
    except Exception as e:
        logger.warning(f"Non-critical: {e}")

    # Fallback for Tradovate Paper when adapter is offline: compute from fills
    if _is_tv_paper_account(state_dir):
        try:
            tv, tv_fills = _get_tradovate_state(state_dir)
            if tv_fills:
                paired = _tradovate_fills_to_trades(tv_fills)
                td_start = _get_trading_day_start()
                today_trades = []
                for t in paired:
                    exit_ts = t.get("exit_time") or ""
                    if exit_ts:
                        try:
                            exit_dt = datetime.fromisoformat(exit_ts.replace("Z", "+00:00"))
                            if exit_dt.tzinfo is None:
                                exit_dt = exit_dt.replace(tzinfo=timezone.utc)
                            if exit_dt >= td_start:
                                today_trades.append(t)
                        except Exception:
                            pass
                trades = len(today_trades)
                wins = sum(1 for t in today_trades if (t.get("pnl") or 0) > 0)
                losses = trades - wins
                daily_pnl = round(sum(t.get("pnl", 0) or 0 for t in today_trades), 2)
                start_balance = _get_start_balance(state_dir)
                total_fill_pnl = sum(t.get("pnl", 0) or 0 for t in paired)
                return {
                    "daily_pnl": daily_pnl,
                    "daily_trades": trades,
                    "daily_wins": wins,
                    "daily_losses": losses,
                    "tradovate_equity": round(start_balance + total_fill_pnl, 2),
                    "tradovate_open_pnl": 0.0,
                    "tradovate_positions": 0,
                }
        except Exception as e:
            logger.warning(f"Non-critical Tradovate fills fallback: {e}")

    # Delegate to shared stats_computation module (single source of truth for
    # signals.jsonl parsing with built-in 5-second TTL cache).
    result = _shared_compute_daily_stats(state_dir)

    # Fallback: if signals.jsonl produced 0 trades (e.g. after a reset) but
    # challenge_state.json has today's trade data, use today's daily PnL.
    # NOTE: Never use all-time challenge stats as "daily" — that causes
    # the header to show misleading numbers.
    if result.get("daily_trades", 0) == 0:
        try:
            challenge = _get_challenge_status(state_dir)
            if challenge and challenge.get("trades", 0) > 0:
                # Use today's date from daily_pnl_by_date if available
                tv_paper = challenge.get("tv_paper") or {}
                # Read daily breakdown from challenge state file directly
                ch_data = _read_json_sync(state_dir / "challenge_state.json")
                if ch_data:
                    daily_by_date = ch_data.get("current_attempt", {}).get("daily_pnl_by_date", {})
                    today_key = date.today().isoformat()
                    if today_key in daily_by_date:
                        result = dict(result)
                        result["daily_pnl"] = round(daily_by_date[today_key], 2)
                        # We don't have per-day W/L in challenge state, so leave trades at 0
                        # rather than showing misleading all-time counts
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

    return result


def _get_previous_trading_day_bounds() -> tuple:
    """
    Get the start and end of the previous trading day (6pm ET to 6pm ET).

    Returns (start_utc, end_utc) for the previous complete trading day.
    Delegates to shared get_trading_day_start() for the 6pm ET logic.
    """
    current_day_start = _shared_get_trading_day_start()

    # Previous trading day is the 24h window before current trading day start
    prev_day_end = current_day_start
    prev_day_start = current_day_start - timedelta(days=1)

    return prev_day_start, prev_day_end


def _compute_performance_stats(state_dir: Path) -> Dict[str, Any]:
    """Compute performance stats for yesterday, 24h, 72h, and 30d periods.

    When Tradovate live account data is available (Tradovate Paper), use the broker's
    equity-based P&L as the single source of truth for ALL periods.  This
    avoids the mismatch between virtual exit grading and real fills.
    """
    # --- Read performance.json once for all code paths below ---
    performance_file = state_dir / "performance.json"
    perf_data: Optional[list] = None  # None = missing or invalid
    try:
        _raw = _read_json_sync(performance_file)
        if isinstance(_raw, list):
            perf_data = _raw
    except Exception:
        logger.debug("Failed to read/parse performance.json", exc_info=True)

    # Priority 1: Tradovate live data (Tradovate Paper accounts)
    try:
        _sd = _read_state_for_dir(state_dir)
        if _sd:
            tv = _sd.get("tradovate_account")
            if tv and isinstance(tv, dict) and tv.get("equity"):
                start_balance = _get_start_balance(state_dir)
                equity = float(tv.get("equity", 0))
                open_pnl = float(tv.get("open_pnl", 0))
                pnl = round(equity - start_balance, 2)
                # Build a single stat block used for every period
                tv_stats = {"pnl": pnl, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                            "tradovate_equity": round(equity, 2), "tradovate_open_pnl": round(open_pnl, 2)}
                # Use Tradovate fills for trade counts (not performance.json which has virtual data)
                try:
                    _, tv_fills = _get_tradovate_state(state_dir)
                    if tv_fills:
                        paired = _tradovate_fills_to_trades(tv_fills)
                        tv_stats["trades"] = len(paired)
                        tv_stats["wins"] = sum(1 for t in paired if (t.get("pnl") or 0) > 0)
                        tv_stats["losses"] = len(paired) - tv_stats["wins"]
                        tv_stats["win_rate"] = round(tv_stats["wins"] / len(paired) * 100, 1) if paired else 0.0
                except Exception as e:
                    logger.debug(f"Tradovate fills unavailable for trade counts, falling back to performance.json: {e}")
                    # Fallback to performance.json if Tradovate fills unavailable
                    if tv_stats["trades"] == 0 and perf_data:
                        tv_stats["trades"] = len(perf_data)
                        tv_stats["wins"] = sum(1 for t in perf_data if (t.get("pnl") or 0) > 0)
                        tv_stats["losses"] = len(perf_data) - tv_stats["wins"]
                        tv_stats["win_rate"] = round(tv_stats["wins"] / len(perf_data) * 100, 1)
                return {p: tv_stats.copy() for p in ("yesterday", "24h", "72h", "30d")}
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

    # Priority 2: Tradovate fills (TV Paper accounts without live equity)
    # This avoids falling through to performance.json which may contain
    # duplicated/corrupted virtual exit data.
    try:
        if _is_tv_paper_account(state_dir):
            _, tv_fills = _get_tradovate_state(state_dir)
            if tv_fills:
                now_utc = datetime.now(timezone.utc)
                prev_day_s, prev_day_e = _get_previous_trading_day_bounds()
                fills_stats = {
                    "yesterday": _tradovate_performance_for_period(tv_fills, prev_day_s, prev_day_e),
                    "24h": _tradovate_performance_for_period(tv_fills, now_utc - timedelta(hours=24)),
                    "72h": _tradovate_performance_for_period(tv_fills, now_utc - timedelta(hours=72)),
                    "30d": _tradovate_performance_for_period(tv_fills, now_utc - timedelta(days=30)),
                }
                return fills_stats
    except Exception as e:
        logger.debug(f"Tradovate fills fallback failed: {e}")

    if perf_data is None:
        empty_stats = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
        result = {"yesterday": empty_stats.copy(), "24h": empty_stats.copy(), "72h": empty_stats.copy(), "30d": empty_stats.copy()}
        # Fallback: populate from challenge_state.json when performance.json is missing
        try:
            challenge = _get_challenge_status(state_dir)
            if challenge and challenge.get("trades", 0) > 0:
                ch_pnl = round(challenge.get("pnl", 0.0), 2)
                ch_trades = challenge.get("trades", 0)
                ch_wins = challenge.get("wins", 0)
                ch_losses = ch_trades - ch_wins
                ch_wr = round(ch_wins / ch_trades * 100, 1) if ch_trades > 0 else 0.0
                ch_stats = {"pnl": ch_pnl, "trades": ch_trades, "wins": ch_wins, "losses": ch_losses, "win_rate": ch_wr}
                for period in result:
                    result[period] = ch_stats.copy()
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
        return result

    now = datetime.now(timezone.utc)
    prev_day_start, prev_day_end = _get_previous_trading_day_bounds()

    cutoffs = {
        "24h": now - timedelta(hours=24),
        "72h": now - timedelta(hours=72),
        "30d": now - timedelta(days=30),
    }

    stats = {period: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0} for period in cutoffs}
    stats["yesterday"] = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}

    try:
        data = perf_data if perf_data is not None else []

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

            # Check rolling periods (24h, 72h, 30d)
            for period, cutoff in cutoffs.items():
                if exit_time >= cutoff:
                    stats[period]["pnl"] += pnl
                    stats[period]["trades"] += 1
                    if is_win:
                        stats[period]["wins"] += 1
                    else:
                        stats[period]["losses"] += 1

            # Check yesterday (previous complete trading day window)
            if prev_day_start <= exit_time < prev_day_end:
                stats["yesterday"]["pnl"] += pnl
                stats["yesterday"]["trades"] += 1
                if is_win:
                    stats["yesterday"]["wins"] += 1
                else:
                    stats["yesterday"]["losses"] += 1
    except Exception as e:
        logger.warning(f"Non-critical: {e}")

    # Calculate win rates and compute streaks for 24h
    for period in stats:
        total = stats[period]["trades"]
        stats[period]["pnl"] = round(stats[period]["pnl"], 2)
        stats[period]["win_rate"] = round(stats[period]["wins"] / total * 100, 1) if total > 0 else 0.0

    # Compute current streak for 24h
    stats["24h"]["streak"] = 0
    stats["24h"]["streak_type"] = "none"
    try:
        if perf_data:
            cutoff_24h = cutoffs["24h"]
            recent_trades = []
            for trade in perf_data:
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
    except Exception as e:
        logger.warning(f"Non-critical: {e}")

    # Fallback: if performance.json had zero trades but challenge has data,
    # populate all periods from the challenge so the PERFORMANCE panel isn't blank.
    total_trades = sum(stats[p]["trades"] for p in ("24h", "72h", "30d"))
    if total_trades == 0:
        try:
            challenge = _get_challenge_status(state_dir)
            if challenge and challenge.get("trades", 0) > 0:
                ch_pnl = round(challenge.get("pnl", 0.0), 2)
                ch_trades = challenge.get("trades", 0)
                ch_wins = challenge.get("wins", 0)
                ch_losses = ch_trades - ch_wins
                ch_wr = round(ch_wins / ch_trades * 100, 1) if ch_trades > 0 else 0.0
                ch_stats = {"pnl": ch_pnl, "trades": ch_trades, "wins": ch_wins, "losses": ch_losses, "win_rate": ch_wr}
                for period in ("yesterday", "24h", "72h", "30d"):
                    stats[period] = {**stats[period], **ch_stats}
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

    return stats


# ==========================================================================
# TRADOVATE DATA HELPERS (Tradovate Paper: broker as single source of truth)
# ==========================================================================

def _is_tv_paper_account(state_dir: Path) -> bool:
    """Check if this state_dir has live Tradovate account data (Tradovate Paper mode).

    Delegates to :func:`pearlalgo.api.data_layer.is_tv_paper_account`.
    """
    return _is_tv_paper_account_new(state_dir)


def _normalize_fill(f: Dict[str, Any]) -> Dict[str, Any]:
    """Delegates to :func:`pearlalgo.api.tradovate_helpers.normalize_fill`."""
    return _normalize_fill_new(f)


def _get_tradovate_state(state_dir: Path) -> tuple:
    """Delegates to :func:`pearlalgo.api.tradovate_helpers.get_tradovate_state`."""
    return _get_tradovate_state_new(state_dir)



# _tradovate_fills_to_trades imported directly from pearlalgo.execution.tradovate.utils above.


def _tradovate_positions_for_api(tv: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Delegates to :func:`pearlalgo.api.tradovate_helpers.tradovate_positions_for_api`."""
    return _tradovate_positions_for_api_new(tv)


def _tradovate_performance_summary(tv: Dict[str, Any], fills: List[Dict[str, Any]], state_dir: Path) -> Dict[str, Any]:
    """Delegates to :func:`pearlalgo.api.tradovate_helpers.tradovate_performance_summary`."""
    return _tradovate_performance_summary_new(tv, fills, state_dir)


def _tradovate_performance_for_period(
    fills: List[Dict[str, Any]],
    start_utc: datetime,
    end_utc: Optional[datetime] = None,
    commission_per_trade: float = 0.0,
) -> Dict[str, Any]:
    """Delegates to :func:`pearlalgo.api.tradovate_helpers.tradovate_performance_for_period`."""
    return _tradovate_performance_for_period_new(fills, start_utc, end_utc, commission_per_trade)


def _get_recent_exits(state_dir: Path, limit: int = 5) -> List[Dict[str, Any]]:
    """Get recent exits. Tradovate Paper: from Tradovate fills. IBKR Virtual: from signals.jsonl."""
    # Tradovate Paper: use Tradovate fills
    if _is_tv_paper_account(state_dir):
        _, fills = _get_tradovate_state(state_dir)
        trades = _tradovate_fills_to_trades(fills)
        recent = []
        for t in trades[-limit:]:
            pnl = t.get("pnl", 0)
            recent.append({
                "signal_id": t.get("signal_id"),
                "direction": t.get("direction", "long"),
                "pnl": pnl,
                "exit_reason": t.get("exit_reason", ""),
                "exit_time": t.get("exit_time"),
                "entry_time": t.get("entry_time"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "entry_reason": "",
                "duration_seconds": None,
            })
        return recent

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
                except Exception as e:
                    logger.debug(f"Non-critical: {e}")

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
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

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
    """Get challenge status from challenge_state.json (supports both IBKR Virtual + Tradovate Paper)."""
    data = _read_json_sync(state_dir / "challenge_state.json")
    if not data:
        return None

    try:
        config = data.get("config", {})
        current = data.get("current_attempt", {})

        if not config.get("enabled", False):
            return None

        # Calculate drawdown risk percentage
        max_dd = config.get("max_drawdown", 2000.0)
        current_dd = abs(current.get("max_drawdown_hit", 0.0))
        dd_risk_pct = min(100.0, (current_dd / max_dd * 100)) if max_dd > 0 else 0.0

        result: Dict[str, Any] = {
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
            "attempt_number": current.get("attempt_id"),
        }

        # Tradovate Paper extensions (present when stage is set in challenge_state.json)
        tv_paper_state = TvPaperChallengeState.from_challenge_data(data)
        if tv_paper_state is not None:
            result["tv_paper"] = tv_paper_state.to_dict()

        # Tradovate Paper: override balance/pnl/trades with Tradovate live data
        if _is_tv_paper_account(state_dir):
            tv, fills = _get_tradovate_state(state_dir)
            if tv.get("equity"):
                start_balance = config.get("start_balance", 50000.0)
                equity = float(tv.get("equity", 0))
                pnl = round(equity - start_balance, 2)
                trades_list = _tradovate_fills_to_trades(fills)
                total = len(trades_list)
                wins = sum(1 for t in trades_list if (t.get("pnl") or 0) > 0)
                losses = total - wins
                win_rate = round(wins / total * 100, 1) if total > 0 else 0.0

                result["current_balance"] = round(equity, 2)
                result["pnl"] = pnl
                result["trades"] = total
                result["wins"] = wins
                result["win_rate"] = win_rate

                # Drawdown risk based on live equity vs floor
                if tv_paper_state and tv_paper_state.current_drawdown_floor:
                    floor = tv_paper_state.current_drawdown_floor
                    max_dd_dist = config.get("max_drawdown", 2000.0)
                    distance_to_floor = equity - floor
                    dd_risk = max(0, min(100, ((max_dd_dist - distance_to_floor) / max_dd_dist) * 100)) if max_dd_dist > 0 else 0
                    result["drawdown_risk_pct"] = round(dd_risk, 1)

        return result
    except Exception:
        return None


def _json_sanitize(obj: Any) -> Any:
    """
    Best-effort conversion to a JSON-serializable structure.

    We intentionally avoid leaking non-serializable objects through WebSockets.
    """
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return str(obj)


def _load_performance_data(state_dir: Path) -> Optional[list]:
    """Delegates to :func:`pearlalgo.api.data_layer.load_performance_data`."""
    return _load_performance_data_new(state_dir)


def _get_equity_curve(state_dir: Path, hours: int = 72) -> List[Dict[str, Any]]:
    """Get equity curve data (cumulative P&L over time) for the mini chart.

    Tradovate Paper accounts use Tradovate fills as the data source (real broker data).
    IBKR Virtual accounts use performance.json (virtual trade exits).
    """
    # Tradovate Paper: use Tradovate fills for equity curve (real broker data)
    if _is_tv_paper_account(state_dir):
        try:
            _, fills = _get_tradovate_state(state_dir)
            if fills:
                paired = _tradovate_fills_to_trades(fills)
                data = [
                    {
                        "exit_time": t.get("close_time") or t.get("exit_time") or t.get("timestamp"),
                        "pnl": t.get("pnl", 0.0),
                    }
                    for t in paired
                    if t.get("pnl") is not None
                ]
            else:
                data = []
        except Exception as e:
            logger.debug(f"Tradovate fills unavailable for equity curve, falling back: {e}")
            data = _cached("performance_data", 10.0, _load_performance_data, state_dir)
    else:
        data = _cached("performance_data", 10.0, _load_performance_data, state_dir)

    if not data:
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    curve = []
    try:
        # Sort trades by exit time
        trades = []
        for trade in data:
            exit_time_str = trade.get("exit_time")
            if not exit_time_str:
                continue
            try:
                exit_time = datetime.fromisoformat(str(exit_time_str).replace("Z", "+00:00"))
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
    except Exception as e:
        logger.warning(f"Non-critical: {e}")

    return curve


def _get_risk_metrics(state_dir: Path) -> Dict[str, Any]:
    """Calculate risk metrics via the shared :func:`compute_risk_metrics` function.

    Tradovate Paper: uses Tradovate paired trades.  IBKR Virtual: uses performance.json.
    Exposure metrics (max concurrent positions, stop-risk) are calculated
    from signals.jsonl when available.
    """
    # -- Gather P&L list and trades list depending on account type ----------
    if _is_tv_paper_account(state_dir):
        try:
            trades = _get_paired_tradovate_trades(state_dir)
            pnls = [t.get("pnl", 0) or 0 for t in trades]
        except Exception:
            return dict(DEFAULT_RISK_METRICS)
    else:
        data = _cached("performance_data", 10.0, _load_performance_data, state_dir)
        if not data:
            return dict(DEFAULT_RISK_METRICS)
        trades = data
        pnls = [t.get("pnl", 0.0) or 0.0 for t in data if t.get("pnl") is not None]

    if not pnls:
        return dict(DEFAULT_RISK_METRICS)

    # -- Compute via shared pure function -----------------------------------
    result = compute_risk_metrics(pnls, trades)

    # -- Exposure metrics (require signals.jsonl entry/exit timestamps) -----
    signals_file = state_dir / "signals.jsonl"
    if signals_file.exists() and not _is_tv_paper_account(state_dir):
        try:
            signals = _get_signals(state_dir, max_lines=2000)
            max_concurrent = 0
            max_stop_risk = 0.0
            events = []
            for s in signals:
                entry_time = s.get("entry_time")
                exit_time = s.get("exit_time")
                signal_data = s.get("signal", {})
                entry_price = s.get("entry_price", 0)
                stop_loss = signal_data.get("stop_loss", 0) if isinstance(signal_data, dict) else 0
                stop_risk = abs(entry_price - stop_loss) * 2 if entry_price and stop_loss else 0

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

            events.sort(key=lambda x: x[1])
            current_positions = 0
            current_stop_risk = 0.0
            for event_type, _, risk_delta in events:
                if event_type == "entry":
                    current_positions += 1
                else:
                    current_positions -= 1
                current_stop_risk += risk_delta
                max_concurrent = max(max_concurrent, current_positions)
                max_stop_risk = max(max_stop_risk, current_stop_risk)

            result["max_concurrent_positions_peak"] = max_concurrent
            result["max_stop_risk_exposure"] = round(max_stop_risk, 2)
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

    return result


def _get_market_regime(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract market regime information from agent state.
    
    The agent now computes regime from the data buffer via detect_market_regime()
    and stores regime, regime_confidence, regime_trend_strength, etc. in state.
    """
    circuit_breaker = state.get("trading_circuit_breaker", {})

    # Get regime from state (computed by service._save_state from buffer data)
    regime = state.get("regime") or "unknown"

    # Use actual confidence from detect_market_regime() if available
    confidence = float(state.get("regime_confidence", 0.0) or 0.0)

    # Determine allowed direction based on direction gating
    allowed_direction = "both"
    if circuit_breaker.get("direction_gating_enabled", False):
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
    """Get shadow mode counters showing what would have been blocked + outcome stats."""
    circuit_breaker = state.get("trading_circuit_breaker", {})
    ml_filter = state.get("ml_filter", {})
    learning = state.get("learning", {})

    # Shadow outcome stats (from circuit breaker's shadow outcome tracker)
    shadow_outcomes = circuit_breaker.get("shadow_outcomes", {})

    return {
        "would_block_total": circuit_breaker.get("would_block_total", 0),
        "would_block_by_reason": circuit_breaker.get("would_block_by_reason", {}),
        "ml_would_skip": learning.get("total_skips", 0) if learning.get("mode") == "shadow" else 0,
        "ml_total_decisions": learning.get("total_decisions", 0),
        "ml_execute_rate": learning.get("execute_rate", 1.0),
        # Shadow outcome comparison (what happened to blocked vs allowed signals)
        "blocked_wins": shadow_outcomes.get("blocked_wins", 0),
        "blocked_losses": shadow_outcomes.get("blocked_losses", 0),
        "blocked_total": shadow_outcomes.get("blocked_total", 0),
        "blocked_pnl": shadow_outcomes.get("blocked_pnl", 0.0),
        "allowed_wins": shadow_outcomes.get("allowed_wins", 0),
        "allowed_losses": shadow_outcomes.get("allowed_losses", 0),
        "allowed_total": shadow_outcomes.get("allowed_total", 0),
        "allowed_pnl": shadow_outcomes.get("allowed_pnl", 0.0),
        "net_saved": shadow_outcomes.get("net_saved", 0.0),
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


def _get_gateway_status_uncached() -> Dict[str, Any]:
    """
    Check IBKR Gateway status: process running and port listening.

    Returns gateway health for live chart display.

    NOTE: This contains blocking I/O (subprocess, socket).  It is wrapped
    by ``_get_gateway_status()`` with a short TTL cache so the blocking
    calls are amortised across the frequent broadcast-loop invocations.
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
    except Exception as e:
        logger.debug(f"Non-critical: {e}")

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


def _get_gateway_status() -> Dict[str, Any]:
    """Cached wrapper for gateway status (5s TTL).

    Avoids blocking the event loop on every broadcast tick by amortising
    the subprocess + socket checks via the existing ``_cached`` helper.
    """
    return _cached("gateway_status", 5.0, _get_gateway_status_uncached)


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

    # Try to get more details from error log if available.
    # Read only the tail of the file (last 4 KB) to avoid loading large logs
    # into memory entirely.
    error_log = state_dir / "errors.log"
    if last_error is None and error_log.exists():
        try:
            _MAX_TAIL_BYTES = 4096
            file_size = error_log.stat().st_size
            with open(error_log, "r", encoding="utf-8", errors="replace") as f:
                if file_size > _MAX_TAIL_BYTES:
                    f.seek(file_size - _MAX_TAIL_BYTES)
                    f.readline()  # skip partial first line
                lines = f.read().strip().split("\n")
            if lines and lines[-1]:
                last_line = lines[-1]
                # Parse if it's a JSON line
                try:
                    error_data = json.loads(last_line)
                    last_error = error_data.get("message", last_line[:100])
                    last_error_time = error_data.get("timestamp")
                except json.JSONDecodeError:
                    last_error = last_line[:100]
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

    # Truncate error message if too long
    if last_error and len(last_error) > 80:
        last_error = last_error[:77] + "..."

    return {
        "session_error_count": error_count,
        "last_error": last_error,
        "last_error_time": last_error_time,
    }


_accounts_config_cached: Optional[Dict[str, Any]] = None


def _init_accounts_config() -> None:
    """Load accounts config once at startup and cache it."""
    global _accounts_config_cached
    try:
        from pearlalgo.config.config_loader import load_service_config
        svc_cfg = load_service_config()
        accounts = svc_cfg.get("accounts", {})
        if accounts:
            _accounts_config_cached = accounts
            return
    except Exception:
        pass
    # Defaults if config not available
    _accounts_config_cached = {
        "ibkr_virtual": {
            "display_name": "IBKR Virtual",
            "badge": "VIRTUAL",
            "badge_color": "blue",
            "telegram_prefix": "IBKR-VIR",
            "description": "Live market data from IBKR, virtual P&L tracking",
        },
        "tv_paper": {
            "display_name": "Tradovate Paper",
            "badge": "PAPER",
            "badge_color": "purple",
            "telegram_prefix": "TV-PAPER",
            "description": "Live paper trading on Tradovate (demo)",
        },
    }


def _get_accounts_config() -> Dict[str, Any]:
    """Return cached account display config (loaded once at startup)."""
    if _accounts_config_cached is None:
        _init_accounts_config()
    return _accounts_config_cached or {}


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
    _require_state_dir()

    state = await asyncio.get_event_loop().run_in_executor(None, _read_state_safe)

    if not state:
        # Agent not running / state.json missing -- still serve persistent
        # data (challenge, performance, daily stats) so the dashboard is not
        # blank when the agent is stopped.
        daily_stats = await asyncio.get_event_loop().run_in_executor(None, _compute_daily_stats, _state_dir)
        recent_exits = await asyncio.get_event_loop().run_in_executor(None, partial(_cached, "recent_exits", 5.0, _get_recent_exits, _state_dir, limit=100))
        return {
            "running": False,
            "paused": False,
            "daily_pnl": daily_stats["daily_pnl"],
            "daily_trades": daily_stats["daily_trades"],
            "daily_wins": daily_stats["daily_wins"],
            "daily_losses": daily_stats["daily_losses"],
            "active_trades_count": 0,
            "active_trades_unrealized_pnl": None,
            "futures_market_open": False,
            "data_fresh": False,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "ai_status": None,
            "challenge": _get_challenge_status(_state_dir),
            "recent_exits": recent_exits,
            "performance": _compute_performance_stats(_state_dir),
            "equity_curve": _cached("equity_curve", 10.0, _get_equity_curve, _state_dir, hours=72),
            "risk_metrics": _cached("risk_metrics", 10.0, _get_risk_metrics, _state_dir),
            "pearl_ai_available": False,
            "operator_lock_enabled": bool(_operator_enabled),
        }

    # Compute daily stats from actual trades
    daily_stats = await asyncio.get_event_loop().run_in_executor(None, _compute_daily_stats, _state_dir)
    recent_exits = await asyncio.get_event_loop().run_in_executor(None, partial(_cached, "recent_exits", 5.0, _get_recent_exits, _state_dir, limit=100))

    # Return relevant fields for live chart
    return {
        # Existing fields
        "running": state.get("running", False),
        "paused": state.get("paused", False),
        "daily_pnl": daily_stats["daily_pnl"],
        "daily_trades": daily_stats["daily_trades"],
        "daily_wins": daily_stats["daily_wins"],
        "daily_losses": daily_stats["daily_losses"],
        # For Tradovate Paper: use Tradovate position count & open PnL when available
        "active_trades_count": daily_stats.get("tradovate_positions", state.get("active_trades_count", 0)),
        "active_trades_unrealized_pnl": daily_stats.get("tradovate_open_pnl", state.get("active_trades_unrealized_pnl")),
        "futures_market_open": state.get("futures_market_open", False),
        "data_fresh": state.get("data_fresh", False),
        "last_updated": datetime.now(timezone.utc).isoformat(),

        # NEW: AI/ML Status
        "ai_status": _get_ai_status(state),

        # NEW: Challenge Status
        "challenge": _get_challenge_status(_state_dir),

        # NEW: Recent exits
        "recent_exits": recent_exits,

        # NEW: Performance stats
        "performance": _compute_performance_stats(_state_dir),

        # Pearl AI (removed – keys retained for web-app compat)
        "pearl_suggestion": None,
        "pearl_insights": None,
        "pearl_ai_available": False,
        "pearl_feed": [],
        "pearl_ai_heartbeat": None,
        "pearl_ai_debug": None,

        # NEW: Whether operator passphrase locking is configured on this server
        "operator_lock_enabled": bool(_operator_enabled),

        # NEW: Equity curve for mini chart
        "equity_curve": _cached("equity_curve", 10.0, _get_equity_curve, _state_dir, hours=72),

        # NEW: Risk metrics
        "risk_metrics": _cached("risk_metrics", 10.0, _get_risk_metrics, _state_dir),

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

        # Tradovate live account data (Tradovate Paper)
        "tradovate_account": state.get("tradovate_account"),

        # Execution adapter status (for Tradovate Paper connection status)
        "execution": state.get("execution"),

        # Account display config (config-driven names for UI)
        "accounts": _get_accounts_config(),
    }


@app.get("/api/operator/ping")
async def operator_ping(_: str = Depends(require_operator_or_api_key)):
    """
    Operator-only: verify that operator access is working.

    Used by the web UI to validate the passphrase and avoid confusing “unlock”
    states when the server is misconfigured.
    """
    return {"ok": True}


@app.post("/api/kill-switch")
async def kill_switch(_: str = Depends(require_operator_or_api_key)):
    """
    Trigger the kill switch (operator action).

    Rate-limited to 5 requests per 60 seconds.

    Writes `kill_request.flag` into the active market state directory.

    Safety policy:
    - Requires operator access (X-PEARL-OPERATOR header) when PEARL_OPERATOR_PASSPHRASE is set
    - Otherwise requires API key authentication when PEARL_API_AUTH_ENABLED=true
    """
    _check_rate_limit("kill-switch")

    sd = _require_state_dir()

    try:
        sd.mkdir(parents=True, exist_ok=True)
        kill_file = sd / "kill_request.flag"
        payload = {
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "source": "web",
        }
        kill_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        acked = await _wait_for_ack(kill_file)
        if acked:
            return {"ok": True, "message": "Kill switch requested and acknowledged."}
        return {
            "ok": True,
            "message": "Kill switch requested (not yet acknowledged by agent).",
            "warning": "Command sent but not acknowledged within timeout",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write kill flag: {str(e)[:200]}")


@app.post("/api/resume")
async def resume_service(_: str = Depends(require_operator_or_api_key)):
    """
    Request the agent to resume (unpause) after a circuit-breaker or manual pause.

    Writes ``resume_request.flag`` into the state directory. The agent clears
    paused state and connection_failures on its next cycle.
    """
    _check_rate_limit("resume")

    sd = _require_state_dir()

    try:
        sd.mkdir(parents=True, exist_ok=True)
        flag_file = sd / "resume_request.flag"
        payload = {
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "source": "web",
        }
        flag_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("resume: wrote %s", flag_file)
        return {"ok": True, "message": "Resume requested; agent will unpause on next cycle."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write resume flag: {str(e)[:200]}")


@app.post("/api/close-all-trades", status_code=202)
async def close_all_trades(_: str = Depends(require_operator_or_api_key)):
    """
    Request the agent to close ALL virtual trades (status=entered).

    Implementation: writes a ``close_all_request.flag`` file into the state
    directory.  The Market Agent will pick this up within its next cycle.
    This avoids editing state.json directly (reduces race risk with agent writes).

    Safety policy:
    - Requires operator access (X-PEARL-OPERATOR header) when PEARL_OPERATOR_PASSPHRASE is set
    - Otherwise requires API key authentication when PEARL_API_AUTH_ENABLED=true
    """
    _check_rate_limit("close-all-trades")

    sd = _require_state_dir()

    try:
        sd.mkdir(parents=True, exist_ok=True)
        flag_file = sd / "close_all_request.flag"
        payload = {
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "source": "web",
        }
        flag_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("close-all-trades: wrote %s", flag_file)
        acked = await _wait_for_ack(flag_file)
        if acked:
            return {"ok": True, "message": "Close-all requested and acknowledged."}
        return {
            "ok": True,
            "message": "Close-all requested (not yet acknowledged by agent).",
            "warning": "Command sent but not acknowledged within timeout",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to request close-all: {str(e)[:200]}")


@app.post("/api/close-trade", status_code=202)
async def close_trade(
    payload: Dict[str, Any] = Body(default={}),
    _: str = Depends(require_operator_or_api_key),
):
    """
    Request the agent to close a specific virtual trade by signal_id.

    Implementation: writes an operator request file into
    ``{state_dir}/operator_requests/close_trade_{ts_ms}.json``.
    The Market Agent will pick this up within its next cycle.
    This avoids editing state.json directly (reduces race risk with agent writes).

    Safety policy:
    - Requires operator access (X-PEARL-OPERATOR header) when PEARL_OPERATOR_PASSPHRASE is set
    - Otherwise requires API key authentication when PEARL_API_AUTH_ENABLED=true
    """
    _check_rate_limit("close-trade")

    signal_id = str((payload or {}).get("signal_id") or "").strip()
    if not signal_id:
        raise HTTPException(status_code=422, detail="Missing required field: signal_id")

    sd = _require_state_dir()

    try:
        req_payload = {
            "action": "close_trade",
            "signal_id": signal_id,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "source": "web",
        }
        out_path = _write_operator_request(sd, "close_trade", req_payload)
        logger.info("close-trade: wrote %s (signal_id=%s)", out_path, signal_id)
        acked = await _wait_for_ack(out_path)
        if acked:
            return {"ok": True, "message": "Close requested and acknowledged.", "signal_id": signal_id}
        return {
            "ok": True,
            "message": "Close requested (not yet acknowledged by agent).",
            "signal_id": signal_id,
            "warning": "Command sent but not acknowledged within timeout",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to request close: {str(e)[:200]}")


def _write_operator_request(state_dir: Path, prefix: str, payload: Dict[str, Any]) -> Path:
    """
    Write an operator request file into the state directory (atomic best-effort).

    This avoids editing state.json directly (reduces race risk with agent writes).
    """
    req_dir = state_dir / "operator_requests"
    req_dir.mkdir(parents=True, exist_ok=True)

    ts_ms = int(time.time() * 1000)
    out_path = req_dir / f"{prefix}_{ts_ms}.json"
    tmp_path = req_dir / f".{prefix}_{ts_ms}.tmp"
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    return out_path


async def _wait_for_ack(flag_path: Path, timeout: float = 10.0) -> bool:
    """Poll for an acknowledgment file corresponding to the given flag file.

    Checks if ``flag_path.with_suffix(flag_path.suffix + '.ack')`` exists,
    polling every 0.5 seconds.  Returns *True* if the ack file appeared
    before *timeout* seconds, *False* otherwise.  The ack file is deleted
    after being read.
    """
    ack_path = flag_path.with_suffix(flag_path.suffix + ".ack")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ack_path.exists():
            try:
                ack_path.unlink()
            except OSError:
                pass
            return True
        await asyncio.sleep(0.5)
    return False


def _aggregate_performance_since(trades: List[Dict[str, Any]], cutoff: datetime, end: datetime = None) -> Dict[str, Any]:
    """Aggregate performance from cutoff onwards, optionally bounded by end time."""
    pnl = 0.0
    wins = 0
    losses = 0
    total = 0

    for trade in trades:
        exit_time_str = trade.get("exit_time")
        if not exit_time_str:
            continue
        try:
            exit_time = datetime.fromisoformat(str(exit_time_str).replace("Z", "+00:00"))
        except Exception:
            continue
        if exit_time < cutoff:
            continue
        if end is not None and exit_time >= end:
            continue

        p = trade.get("pnl", 0.0)
        try:
            p_val = float(p or 0.0)
        except Exception:
            p_val = 0.0

        is_win = trade.get("is_win", p_val > 0)

        total += 1
        pnl += p_val
        if bool(is_win):
            wins += 1
        else:
            losses += 1

    win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0
    return {
        "pnl": round(pnl, 2),
        "trades": int(total),
        "wins": int(wins),
        "losses": int(losses),
        "win_rate": win_rate,
    }


def _get_trading_week_start(now_utc: datetime) -> datetime:
    """Start of current futures trading week (Sunday 6pm ET), returned in UTC."""
    et_tz = ZoneInfo("America/New_York")
    now_et = now_utc.astimezone(et_tz)

    # Most recent Sunday
    days_since_sunday = (now_et.weekday() + 1) % 7  # Mon=0 -> 1 day since Sunday, Sun=6 -> 0
    sunday_date = (now_et - timedelta(days=days_since_sunday)).date()
    start_et = datetime(
        year=sunday_date.year,
        month=sunday_date.month,
        day=sunday_date.day,
        hour=18,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=et_tz,
    )

    # If it's Sunday but before 6pm, the "current" trading week hasn't started yet
    if now_et < start_et:
        start_et = start_et - timedelta(days=7)

    return start_et.astimezone(timezone.utc)


def _get_month_to_date_start(now_utc: datetime) -> datetime:
    """Month-to-date start aligned to futures trading day boundary (6pm ET)."""
    et_tz = ZoneInfo("America/New_York")
    now_et = now_utc.astimezone(et_tz)
    first_day = now_et.replace(day=1, hour=18, minute=0, second=0, microsecond=0)
    # Include the trading day for the 1st (which begins 6pm ET on the prior calendar day)
    start_et = first_day - timedelta(days=1)
    return start_et.astimezone(timezone.utc)


def _get_year_to_date_start(now_utc: datetime) -> datetime:
    """Year-to-date start aligned to futures trading day boundary (6pm ET)."""
    et_tz = ZoneInfo("America/New_York")
    now_et = now_utc.astimezone(et_tz)
    jan1_6pm = now_et.replace(month=1, day=1, hour=18, minute=0, second=0, microsecond=0)
    start_et = jan1_6pm - timedelta(days=1)  # include trading day that starts Dec 31 6pm ET
    return start_et.astimezone(timezone.utc)


@app.get("/api/performance-summary")
async def performance_summary(api_key: Optional[str] = Depends(verify_api_key)):
    """
    Performance summary. Tradovate Paper: from Tradovate equity/fills. IBKR Virtual: from performance.json.
    """
    _require_state_dir()

    # Tradovate Paper: bucket Tradovate fills by time period for proper breakdowns
    if _is_tv_paper_account(_state_dir):
        tv, fills = _get_tradovate_state(_state_dir)
        equity_stats = _tradovate_performance_summary(tv, fills, _state_dir)

        now = datetime.now(timezone.utc)
        td_start = _get_trading_day_start()
        yday_start, yday_end = _get_previous_trading_day_bounds()
        wtd_start = _get_trading_week_start(now)
        mtd_start = _get_month_to_date_start(now)
        ytd_start = _get_year_to_date_start(now)
        all_start = datetime(2020, 1, 1, tzinfo=timezone.utc)

        # Derive per-trade commission from equity vs fill P&L gap.
        # Tradovate fills don't include fees, but equity is the ground truth.
        # When equity is 0 (adapter offline), skip commission deduction.
        all_trades_raw = _tradovate_fills_to_trades(fills)
        total_fill_pnl = sum(t.get("pnl", 0) or 0 for t in all_trades_raw)
        equity = float(tv.get("equity", 0)) if tv else 0
        start_balance = _get_start_balance(_state_dir)
        total_trades = len(all_trades_raw)
        commission_per_trade = 0.0
        if equity > 0:
            equity_pnl = equity - start_balance
            if total_trades > 0 and total_fill_pnl > equity_pnl:
                commission_per_trade = (total_fill_pnl - equity_pnl) / total_trades

        cpt = commission_per_trade  # shorthand
        all_fill_stats = _tradovate_performance_for_period(fills, all_start, commission_per_trade=cpt)
        live_equity = equity_stats.get("tradovate_equity", 0)
        if live_equity:
            all_fill_stats["tradovate_equity"] = live_equity
        else:
            all_fill_stats["tradovate_equity"] = round(start_balance + total_fill_pnl, 2)

        return {
            "as_of": now.isoformat(),
            "td": _tradovate_performance_for_period(fills, td_start, commission_per_trade=cpt),
            "yday": _tradovate_performance_for_period(fills, yday_start, yday_end, commission_per_trade=cpt),
            "wtd": _tradovate_performance_for_period(fills, wtd_start, commission_per_trade=cpt),
            "mtd": _tradovate_performance_for_period(fills, mtd_start, commission_per_trade=cpt),
            "ytd": _tradovate_performance_for_period(fills, ytd_start, commission_per_trade=cpt),
            "all": all_fill_stats,
        }

    # IBKR Virtual: existing performance.json logic (cached read)
    cached_perf = await asyncio.get_event_loop().run_in_executor(None, _get_cached_performance_data, _state_dir)
    trades = cached_perf.get("trades")
    if trades is None:
        empty = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "td": empty, "yday": empty, "wtd": empty,
            "mtd": empty, "ytd": empty, "all": empty,
        }

    now = datetime.now(timezone.utc)
    td_start = _get_trading_day_start()
    yday_start, yday_end = _get_previous_trading_day_bounds()
    wtd_start = _get_trading_week_start(now)
    mtd_start = _get_month_to_date_start(now)
    ytd_start = _get_year_to_date_start(now)
    all_time_start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    return {
        "as_of": now.isoformat(),
        "td": _aggregate_performance_since(trades, td_start),
        "yday": _aggregate_performance_since(trades, yday_start, yday_end),
        "wtd": _aggregate_performance_since(trades, wtd_start),
        "mtd": _aggregate_performance_since(trades, mtd_start),
        "ytd": _aggregate_performance_since(trades, ytd_start),
        "all": _aggregate_performance_since(trades, all_time_start),
    }

@app.get("/api/trades")
async def get_trades(
    limit: int = Query(default=20, ge=1, le=100, description="Max trades to return"),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """Get recent trades. Tradovate Paper: from Tradovate fills. IBKR Virtual: from signals.jsonl."""
    _require_state_dir()

    # Tradovate Paper: reconstruct trades from Tradovate fills
    if _is_tv_paper_account(_state_dir):
        _, fills = _get_tradovate_state(_state_dir)
        trades = _tradovate_fills_to_trades(fills)
        return trades[-limit:]

    # IBKR Virtual: existing signals.jsonl logic
    # Optimize: only read enough lines to get 'limit' exited trades (typically need ~2-3x limit)
    signals_file = _state_dir / "signals.jsonl"
    # Read from tail: start with limit*3, but cap at 1000 to avoid reading entire file
    read_lines = min(max(limit * 3, 100), 1000)
    signals = _load_jsonl_file(signals_file, max_lines=read_lines)
    
    trades = []
    for s in signals:
        if s.get("status") != "exited":
            continue

        signal_data = s.get("signal", {})
        if not isinstance(signal_data, dict):
            signal_data = {}

        direction = signal_data.get("direction") or s.get("direction")
        symbol = signal_data.get("symbol") or s.get("symbol") or "MNQ"
        position_size = signal_data.get("position_size")

        trades.append(
            {
                "signal_id": s.get("signal_id"),
                "symbol": symbol,
                "direction": direction,
                "position_size": position_size,
                "entry_time": s.get("entry_time"),
                "entry_price": s.get("entry_price"),
                "exit_time": s.get("exit_time"),
                "exit_price": s.get("exit_price"),
                "pnl": s.get("pnl"),
                "exit_reason": s.get("exit_reason"),
            }
        )
    
    return trades[-limit:]


@app.get("/api/positions")
async def get_positions(
    api_key: Optional[str] = Depends(verify_api_key),
):
    """Get currently open positions with entry price, stop loss, and take profit.

    Returns positions for display on chart as price lines.
    Tradovate Paper: uses live Tradovate positions instead of virtual signals.jsonl.
    """
    _require_state_dir()

    # Tradovate Paper: return live Tradovate positions, enriched with TP/SL from virtual signals
    if _is_tv_paper_account(_state_dir):
        tv, _ = _get_tradovate_state(_state_dir)
        positions = _tradovate_positions_for_api(tv)

        # Enrich with TP/SL from virtual signals (signals.jsonl has bracket levels)
        if positions:
            try:
                signals_file = _state_dir / "signals.jsonl"
                # Only read recent signals (enough to match positions, typically <50)
                signals = _load_jsonl_file(signals_file, max_lines=100)
                active_signals = [
                    s for s in signals
                    if s.get("status") == "entered" and s.get("signal", {}).get("stop_loss")
                ]
                # Match by direction — attach TP/SL from the closest-priced active signal
                for pos in positions:
                    matching = [
                        s for s in active_signals
                        if (s.get("signal", {}).get("direction", "").lower() == pos["direction"])
                    ]
                    if matching:
                        # Pick the signal with entry price closest to the Tradovate position
                        best = min(
                            matching,
                            key=lambda s: abs(float(s.get("entry_price", 0) or 0) - pos["entry_price"]),
                        )
                        sig = best.get("signal", {})
                        pos["stop_loss"] = sig.get("stop_loss")
                        pos["take_profit"] = sig.get("take_profit")
            except Exception as e:
                logger.debug(f"Non-critical: could not enrich Tradovate Paper positions with TP/SL: {e}")

        return positions

    # IBKR Virtual: existing signals.jsonl logic
    signals_file = _state_dir / "signals.jsonl"
    signals = _load_jsonl_file(signals_file, max_lines=500)

    positions = []
    for s in signals:
        if s.get("status") == "exited":
            continue
        entry_price = s.get("entry_price")
        if not entry_price:
            continue

        signal_data = s.get("signal", {})
        direction = signal_data.get("direction", "long") if isinstance(signal_data, dict) else s.get("direction", "long")
        symbol = signal_data.get("symbol") if isinstance(signal_data, dict) else None
        position_size = signal_data.get("position_size") if isinstance(signal_data, dict) else None
        stop_loss = signal_data.get("stop_loss") if isinstance(signal_data, dict) else None
        take_profit = signal_data.get("take_profit") if isinstance(signal_data, dict) else None

        positions.append({
            "signal_id": s.get("signal_id"),
            "symbol": symbol or "MNQ",
            "direction": direction,
            "position_size": position_size,
            "entry_price": entry_price,
            "entry_time": s.get("entry_time"),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        })

    return positions


@app.get("/api/indicators")
async def get_indicators(
    symbol: str = Query(default="MNQ", description="Symbol"),
    timeframe: str = Query(default="5m", description="Timeframe"),
    bars: int = Query(default=72, ge=10, le=500, description="Number of bars"),
    _key: Optional[str] = Depends(verify_api_key),
):
    """Get technical indicators for overlay.
    
    Returns 503 if real data is unavailable.
    """
    try:
        candles, _source = await _fetch_candles(symbol=symbol, timeframe=timeframe, bars=bars)
        # Cache indicators by candle fingerprint (count + last time + close)
        # Include close price so intra-bar updates invalidate correctly.
        if candles:
            ind_cache_key = f"indicators:{len(candles)}:{candles[-1]['time']}:{candles[-1]['close']}"
        else:
            ind_cache_key = "indicators:empty"
        indicators = _cached(ind_cache_key, 5.0, _calculate_indicators, candles)
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
    _require_state_dir()

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
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
        
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
            except Exception as e:
                logger.debug(f"Non-critical: {e}")
    
    # Sort markers by time (required by Lightweight Charts)
    markers.sort(key=lambda m: m["time"])
    
    return markers


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _market, _state_dir
    import pearlalgo.api.server_core as _core

    parser = argparse.ArgumentParser(description="Pearl Algo Web App API Server")
    parser.add_argument("--market", default=os.getenv("PEARLALGO_MARKET", DEFAULT_MARKET))
    parser.add_argument("--host", default=os.getenv("API_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("API_PORT", DEFAULT_PORT)))
    parser.add_argument("--data-dir", default=os.getenv("PEARLALGO_STATE_DIR", None),
                        help="Explicit data directory path (overrides --market resolution)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    args = parser.parse_args()

    _market = str(args.market or DEFAULT_MARKET).strip().upper()
    if args.data_dir:
        _state_dir = Path(args.data_dir)
        if not _state_dir.exists():
            print(f"WARNING: --data-dir {_state_dir} does not exist, creating it")
            _state_dir.mkdir(parents=True, exist_ok=True)
    else:
        _state_dir = _resolve_state_dir(_market)
    # Sync globals into server_core so route modules (e.g. health) see them
    _core._market = _market
    _core._state_dir = _state_dir

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
    print(f"  GET /api/state")
    print(f"  GET /api/trades")
    print(f"  GET /health")
    print(f"")
    print(f"Tips:")
    print(f"  - Use --reload for development (auto-restarts on file changes)")
    print(f"  - Set API_PORT=8001 to use different port")
    print(f"  - Kill server: pkill -f 'api_server.py'")

    if args.reload:
        # Use uvicorn's reload feature for development
        uvicorn.run(
            "pearlalgo.api.server:app",
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[str(PROJECT_ROOT / "src" / "pearlalgo" / "api")],
            log_level="info",
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
