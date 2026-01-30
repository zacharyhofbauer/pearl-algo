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
            # Calculate time range based on bars and timeframe
            tf_minutes = {
                "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440
            }.get(timeframe, 5)

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

    Returns data in format:
    [{"time": 1706500000, "open": 26200, "high": 26210, "low": 26195, "close": 26205}, ...]
    """
    try:
        candles = await _fetch_candles(symbol=symbol, timeframe=timeframe, bars=bars, use_cache_fallback=True)
        return JSONResponse(content=candles)
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


@app.get("/api/state")
async def get_state():
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
