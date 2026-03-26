#!/usr/bin/env python3
"""
PearlAlgo Backtester (Production-Grade)

Runs generate_signals() over historical 1-min bars and simulates bracket exits
(SL/TP) with full circuit breaker, TOD scaling, direction gating, and regime
filtering — matching the live trading pipeline.

Data sources (in priority order):
1. SQLite bars.db (from data_collector.py)
2. CSV files in data/backtest/
3. Cached candle JSON files in data/

Usage:
    # Basic backtest with all filters enabled
    python scripts/backtesting/backtest_engine.py --days 7 --trailing

    # Disable circuit breaker to see raw signal quality
    python scripts/backtesting/backtest_engine.py --days 7 --trailing --no-cb

    # Use 5m regime detection
    python scripts/backtesting/backtest_engine.py --days 7 --trailing --regime 5m

    # A/B comparison
    python scripts/backtesting/backtest_engine.py --days 7 --trailing --compare \\
        --config-a current --config-b "proposed:min_confidence=0.5,sl_atr=4.0"

    # JSON output for cron
    python scripts/backtesting/backtest_engine.py --days 7 --trailing \\
        --json-out data/backtest/latest_results.json

    # Parameter sweep
    python scripts/backtesting/backtest_engine.py --days 7 --sweep \\
        --ema-fast 5,7,9 --ema-slow 13,17,21 --sl-atr 2.5,3.0,3.5,4.0
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pearlalgo.trading_bots.pearl_bot_auto import generate_signals, detect_market_regime, CONFIG

# ---------------------------------------------------------------------------
# Circuit breaker simulator (backtest-safe, no logger/market_hours imports)
# ---------------------------------------------------------------------------

class BacktestCircuitBreaker:
    """
    Lightweight circuit breaker simulator for backtesting.

    Reimplements core checks from TradingCircuitBreaker without runtime deps
    (logger, market_hours, Tradovate state).  Operates on simulated time.
    """

    def __init__(
        self,
        max_consecutive_losses: int = 3,
        cooldown_minutes: int = 30,
        max_session_drawdown: float = 1800.0,
        max_daily_drawdown: float = 99999.0,
        max_daily_profit: float = 3000.0,
        rolling_window: int = 20,
        min_rolling_win_rate: float = 0.30,
        enable_direction_gating: bool = True,
        direction_gating_min_confidence: float = 0.50,
        enable_regime_avoidance: bool = True,
        blocked_regimes: Optional[List[str]] = None,
        regime_avoidance_min_confidence: float = 0.70,
    ):
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self.max_session_drawdown = max_session_drawdown
        self.max_daily_drawdown = max_daily_drawdown
        self.max_daily_profit = max_daily_profit
        self.rolling_window = rolling_window
        self.min_rolling_win_rate = min_rolling_win_rate
        self.enable_direction_gating = enable_direction_gating
        self.direction_gating_min_confidence = direction_gating_min_confidence
        self.enable_regime_avoidance = enable_regime_avoidance
        self.blocked_regimes = blocked_regimes or ["ranging", "volatile"]
        self.regime_avoidance_min_confidence = regime_avoidance_min_confidence

        # State
        self._consecutive_losses: int = 0
        self._daily_pnl: float = 0.0
        self._session_pnl: float = 0.0
        self._recent_trades: List[Dict[str, Any]] = []
        self._cooldown_until: Optional[datetime] = None
        self._current_day: Optional[int] = None  # day-of-year for daily reset

        # Stats
        self.blocks: Dict[str, int] = {}
        self.total_blocks: int = 0

    def _record_block(self, reason: str) -> None:
        self.total_blocks += 1
        self.blocks[reason] = self.blocks.get(reason, 0) + 1

    def should_allow(
        self,
        signal: Dict[str, Any],
        sim_time: datetime,
        regime: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Check if signal should be allowed.

        Returns:
            (allowed, reason)
        """
        # Daily reset check
        day = sim_time.timetuple().tm_yday
        if self._current_day is not None and day != self._current_day:
            self._daily_pnl = 0.0
            self._session_pnl = 0.0
            self._consecutive_losses = 0
            self._cooldown_until = None
        self._current_day = day

        # Cooldown
        if self._cooldown_until and sim_time < self._cooldown_until:
            self._record_block("cooldown")
            return False, "cooldown"

        # Clear expired cooldown
        if self._cooldown_until and sim_time >= self._cooldown_until:
            self._cooldown_until = None

        # Consecutive losses
        if self._consecutive_losses >= self.max_consecutive_losses:
            self._cooldown_until = sim_time + timedelta(minutes=self.cooldown_minutes)
            self._record_block("consecutive_losses")
            return False, f"consecutive_losses({self._consecutive_losses})"

        # Session drawdown
        if self._session_pnl <= -self.max_session_drawdown:
            self._cooldown_until = sim_time + timedelta(minutes=60)
            self._record_block("session_drawdown")
            return False, f"session_drawdown(${self._session_pnl:.0f})"

        # Daily drawdown
        if self._daily_pnl <= -self.max_daily_drawdown:
            self._cooldown_until = sim_time + timedelta(hours=12)
            self._record_block("daily_drawdown")
            return False, f"daily_drawdown(${self._daily_pnl:.0f})"

        # Daily profit cap
        if self.max_daily_profit > 0 and self._daily_pnl >= self.max_daily_profit:
            self._cooldown_until = sim_time + timedelta(hours=12)
            self._record_block("daily_profit_cap")
            return False, f"daily_profit_cap(${self._daily_pnl:.0f})"

        # Rolling win rate
        if len(self._recent_trades) >= self.rolling_window // 2:
            recent = self._recent_trades[-self.rolling_window:]
            wr = sum(1 for t in recent if t.get("is_win")) / len(recent)
            if wr < self.min_rolling_win_rate:
                self._cooldown_until = sim_time + timedelta(minutes=self.cooldown_minutes)
                self._record_block("rolling_win_rate")
                return False, f"rolling_win_rate({wr:.0%})"

        # Direction gating
        if self.enable_direction_gating and regime:
            direction = str(signal.get("direction", "")).lower()
            regime_type = str(regime.get("regime", "unknown")).lower()
            regime_conf = float(regime.get("confidence", 0))

            effective_regime = regime_type if regime_conf >= self.direction_gating_min_confidence else "unknown"

            allowed_dir = "long"
            if effective_regime == "trending_down":
                allowed_dir = "short"

            if direction != allowed_dir:
                self._record_block("direction_gating")
                return False, f"direction_gating({direction} in {effective_regime})"

        # Regime avoidance
        if self.enable_regime_avoidance and regime:
            regime_type = str(regime.get("regime", "unknown")).lower()
            regime_conf = float(regime.get("confidence", 0))
            if regime_conf >= self.regime_avoidance_min_confidence and regime_type in self.blocked_regimes:
                self._record_block("regime_avoidance")
                return False, f"regime_avoidance({regime_type})"

        return True, "passed"

    def record_trade(self, pnl: float, is_win: bool, sim_time: datetime) -> None:
        """Record a completed trade."""
        if is_win:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1

        self._daily_pnl += pnl
        self._session_pnl += pnl
        self._recent_trades.append({"is_win": is_win, "pnl": pnl})

        # Trim ring buffer
        if len(self._recent_trades) > self.rolling_window * 2:
            self._recent_trades = self._recent_trades[-self.rolling_window * 2:]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_blocks": self.total_blocks,
            "blocks_by_reason": dict(self.blocks),
            "consecutive_losses": self._consecutive_losses,
            "daily_pnl": round(self._daily_pnl, 2),
            "session_pnl": round(self._session_pnl, 2),
        }


# ---------------------------------------------------------------------------
# TOD (Time-of-Day) confidence scaling
# ---------------------------------------------------------------------------

# Default TOD multipliers matching tradovate_paper.yaml
DEFAULT_TOD_MULTIPLIERS = {
    "overnight":       0.60,   # 00:00-03:59 ET
    "premarket_early": 0.75,   # 04:00-05:59 ET
    "premarket_late":  0.85,   # 06:00-09:29 ET
    "rth":             1.00,   # 09:30-15:59 ET
    "post_close":      0.85,   # 16:00-17:59 ET
    "evening":         0.70,   # 18:00-23:59 ET
}


def get_tod_multiplier(utc_time: datetime, multipliers: Optional[Dict[str, float]] = None) -> float:
    """Get time-of-day confidence multiplier based on ET hour."""
    mults = multipliers or DEFAULT_TOD_MULTIPLIERS
    try:
        import zoneinfo
        et = zoneinfo.ZoneInfo("America/New_York")
    except ImportError:
        import pytz
        et = pytz.timezone("America/New_York")

    et_dt = utc_time.astimezone(et) if utc_time.tzinfo else utc_time.replace(tzinfo=timezone.utc).astimezone(et)
    h = et_dt.hour
    m = et_dt.minute

    if 0 <= h < 4:
        return mults.get("overnight", 0.60)
    elif 4 <= h < 6:
        return mults.get("premarket_early", 0.75)
    elif 6 <= h < 9 or (h == 9 and m < 30):
        return mults.get("premarket_late", 0.85)
    elif (h == 9 and m >= 30) or (10 <= h < 16):
        return mults.get("rth", 1.00)
    elif 16 <= h < 18:
        return mults.get("post_close", 0.85)
    else:  # 18-23
        return mults.get("evening", 0.70)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_bars_from_csv(csv_path: Path) -> pd.DataFrame:
    """Load bars from a CSV file with columns: timestamp, open, high, low, close, volume."""
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_bars_from_cache(cache_path: Path) -> pd.DataFrame:
    """Load bars from PearlAlgo candle cache JSON format."""
    with open(cache_path) as f:
        data = json.load(f)

    candles = data.get("candles", data) if isinstance(data, dict) else data
    if not candles:
        return pd.DataFrame()

    rows = []
    for c in candles:
        ts = c.get("time") or c.get("timestamp")
        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc)
        rows.append({
            "timestamp": ts,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0)),
        })

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_bars_from_db(db_path: Path, table: str, days: int) -> pd.DataFrame:
    """Load bars from SQLite database."""
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(db_path))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    df = pd.read_sql_query(
        f"SELECT timestamp, open, high, low, close, volume FROM {table} "
        f"WHERE timestamp >= ? ORDER BY timestamp ASC",
        conn,
        params=[cutoff],
    )
    conn.close()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def load_bars(days: int = 7, csv_dir: Optional[Path] = None, timeframe: str = "1m") -> pd.DataFrame:
    """Load bars from available sources, filtered to the last N days.

    Priority: bars.db > CSV > cache JSON.
    """
    data_dir = PROJECT_ROOT / "data"
    backtest_dir = csv_dir or (data_dir / "backtest")
    db_path = backtest_dir / "bars.db"
    table = "bars_1m" if timeframe == "1m" else "bars_5m"

    # Try SQLite first
    df = load_bars_from_db(db_path, table, days)
    if not df.empty:
        print(f"  Loaded {len(df)} {timeframe} bars from bars.db")
        return df

    frames: List[pd.DataFrame] = []

    # Try CSVs
    if backtest_dir.exists():
        for csv_file in sorted(backtest_dir.glob(f"MNQ_{timeframe}_*.csv")):
            try:
                frames.append(load_bars_from_csv(csv_file))
            except Exception as e:
                print(f"  Warning: Failed to load {csv_file.name}: {e}")

    # Fall back to cache files
    if not frames:
        tf_patterns = [f"candle_cache_MNQ_{timeframe}_500.json",
                       f"candle_cache_MNQ_{timeframe}_200.json"]
        for cache_name in tf_patterns:
            cache_file = data_dir / cache_name
            if cache_file.exists():
                try:
                    frames.append(load_bars_from_cache(cache_file))
                    print(f"  Loaded {len(frames[-1])} bars from {cache_name}")
                except Exception as e:
                    print(f"  Warning: Failed to load {cache_name}: {e}")

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Filter to last N days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Config loading helpers
# ---------------------------------------------------------------------------

def load_live_config() -> Dict[str, Any]:
    """Load the merged live config (base + tradovate_paper)."""
    import yaml
    base_path = PROJECT_ROOT / "config" / "base.yaml"
    paper_path = PROJECT_ROOT / "config" / "accounts" / "tradovate_paper.yaml"

    cfg: Dict[str, Any] = {}
    if base_path.exists():
        with open(base_path) as f:
            cfg = yaml.safe_load(f) or {}
    if paper_path.exists():
        with open(paper_path) as f:
            overrides = yaml.safe_load(f) or {}
        _deep_merge(cfg, overrides)
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def parse_config_spec(spec: str) -> Dict[str, Any]:
    """Parse a config spec like 'proposed:min_confidence=0.5,sl_atr=4.0'."""
    if spec == "current":
        return {}

    overrides: Dict[str, Any] = {}
    if ":" in spec:
        _, params = spec.split(":", 1)
    else:
        params = spec

    for pair in params.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        key = key.strip()
        try:
            overrides[key] = float(val)
        except ValueError:
            overrides[key] = val
    return overrides


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    bars_df: pd.DataFrame,
    config_overrides: Optional[Dict] = None,
    trailing_config: Optional[Dict] = None,
    window_size: int = 200,
    point_value: float = 2.0,
    circuit_breaker: Optional[BacktestCircuitBreaker] = None,
    enable_tod: bool = True,
    tod_multipliers: Optional[Dict[str, float]] = None,
    min_confidence: float = 0.40,
    df_5m: Optional[pd.DataFrame] = None,
    use_5m_regime: bool = False,
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Run backtest over bars using generate_signals().

    Returns:
        Tuple of (trade_results, metadata) where metadata includes CB stats, etc.
    """
    # Build config — merge pearl_bot_auto defaults with live session settings
    cfg = dict(CONFIG)
    # Override session to use full futures session (18:00-17:00 ET) for backtesting
    # The default CONFIG has RTH-only (9:30-16:00) which blocks most signals
    cfg["session"] = {"start_time": "18:00", "end_time": "17:00", "timezone": "America/New_York"}
    cfg["start_hour"] = 18
    cfg["start_minute"] = 0
    cfg["end_hour"] = 17
    cfg["end_minute"] = 0
    if config_overrides:
        cfg.update(config_overrides)

    # Apply min_confidence from overrides or default
    effective_min_conf = config_overrides.get("min_confidence", min_confidence) if config_overrides else min_confidence

    results: List[Dict] = []
    open_trades: List[Dict] = []
    signal_cooldown: Dict[str, datetime] = {}
    cooldown_seconds = 60

    # Track CB blocked signals for metadata
    cb_blocked = 0
    tod_blocked = 0
    total_signals_generated = 0

    total_bars = len(bars_df)
    last_progress = 0

    # Pre-build 5m regime index if available
    regime_cache: Dict[str, Dict] = {}
    if use_5m_regime and df_5m is not None and not df_5m.empty:
        print("  Pre-computing 5m regimes...")
        for i in range(50, len(df_5m)):
            window_5m = df_5m.iloc[max(0, i - 50):i + 1]
            r = detect_market_regime(window_5m)
            ts_key = str(df_5m.iloc[i]["timestamp"])
            regime_cache[ts_key] = r.to_dict() if hasattr(r, "to_dict") else {
                "regime": r.regime, "confidence": r.confidence,
                "trend_strength": r.trend_strength, "volatility_ratio": r.volatility_ratio,
                "recommendation": r.recommendation,
            }

    def _find_5m_regime(bar_time: datetime) -> Optional[Dict]:
        """Find the most recent 5m regime for a given 1m bar time."""
        if not regime_cache:
            return None
        # Find nearest 5m timestamp <= bar_time
        best = None
        best_ts = None
        for ts_str, regime_dict in regime_cache.items():
            ts = pd.Timestamp(ts_str)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            if ts <= bar_time:
                if best_ts is None or ts > best_ts:
                    best_ts = ts
                    best = regime_dict
        return best

    for i in range(window_size, total_bars):
        # Progress indicator
        pct = int((i / total_bars) * 100)
        if pct >= last_progress + 10:
            last_progress = pct
            print(f"  Progress: {pct}% ({i}/{total_bars} bars, {len(results)} trades)")

        current_bar = bars_df.iloc[i]
        bar_high = float(current_bar["high"])
        bar_low = float(current_bar["low"])
        bar_time = current_bar["timestamp"]

        # Check open trades for exits
        still_open = []
        for trade in open_trades:
            direction = trade["direction"]
            stop = trade["stop_loss"]
            target = trade["take_profit"]
            entry_px = trade["entry_price"]

            # Trailing stop update
            if trailing_config and trailing_config.get("enabled"):
                best_key = "best_price"
                if best_key not in trade:
                    trade[best_key] = entry_px
                if direction == "long":
                    trade[best_key] = max(trade[best_key], bar_high)
                    favorable_move = trade[best_key] - entry_px
                else:
                    trade[best_key] = min(trade[best_key], bar_low)
                    favorable_move = entry_px - trade[best_key]

                atr = trade.get("atr", 1.0)
                for phase in reversed(trailing_config.get("phases", [])):
                    if favorable_move >= phase["activation_atr"] * atr:
                        if phase["trail_atr"] == 0.0:
                            new_stop = entry_px + (0.25 if direction == "long" else -0.25)
                        else:
                            trail_dist = phase["trail_atr"] * atr
                            if direction == "long":
                                new_stop = trade[best_key] - trail_dist
                            else:
                                new_stop = trade[best_key] + trail_dist
                        if direction == "long" and new_stop > stop:
                            stop = new_stop
                            trade["stop_loss"] = stop
                            trade["trailing_phase"] = phase["name"]
                        elif direction == "short" and new_stop < stop:
                            stop = new_stop
                            trade["stop_loss"] = stop
                            trade["trailing_phase"] = phase["name"]
                        break

            # Check SL/TP hits
            if direction == "long":
                hit_tp = bar_high >= target
                hit_sl = bar_low <= stop
            else:
                hit_tp = bar_low <= target
                hit_sl = bar_high >= stop

            if hit_tp or hit_sl:
                if hit_sl and hit_tp:
                    exit_reason = "stop_loss"  # Conservative tiebreak
                    exit_price = stop
                elif hit_sl:
                    exit_reason = "stop_loss"
                    exit_price = stop
                else:
                    exit_reason = "take_profit"
                    exit_price = target

                if direction == "long":
                    pnl_points = exit_price - entry_px
                else:
                    pnl_points = entry_px - exit_price
                pnl_dollars = pnl_points * point_value

                max_px = trade.get("max_price", entry_px)
                min_px = trade.get("min_price", entry_px)
                if direction == "long":
                    mfe = max_px - entry_px
                    mae = entry_px - min_px
                else:
                    mfe = entry_px - min_px
                    mae = max_px - entry_px

                trade_result = {
                    "entry_time": trade["entry_time"].isoformat(),
                    "exit_time": bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time),
                    "direction": direction,
                    "entry_price": entry_px,
                    "exit_price": exit_price,
                    "stop_loss": trade["original_stop"],
                    "take_profit": target,
                    "exit_reason": exit_reason,
                    "pnl_points": round(pnl_points, 4),
                    "pnl_dollars": round(pnl_dollars, 2),
                    "mfe_points": round(mfe, 4),
                    "mae_points": round(mae, 4),
                    "confidence": trade.get("confidence", 0),
                    "reason": trade.get("reason", ""),
                    "regime": trade.get("regime", "unknown"),
                    "trailing_phase": trade.get("trailing_phase"),
                    "hold_bars": i - trade["entry_bar_idx"],
                    "cb_allowed": trade.get("cb_allowed", True),
                }
                results.append(trade_result)

                # Record trade in CB
                if circuit_breaker:
                    circuit_breaker.record_trade(
                        pnl=pnl_dollars,
                        is_win=pnl_dollars > 0,
                        sim_time=bar_time.to_pydatetime() if hasattr(bar_time, "to_pydatetime") else bar_time,
                    )
            else:
                trade["max_price"] = max(trade.get("max_price", entry_px), bar_high)
                trade["min_price"] = min(trade.get("min_price", entry_px), bar_low)
                still_open.append(trade)

        open_trades = still_open

        # Generate signals on rolling window
        window = bars_df.iloc[max(0, i - window_size):i + 1].copy()
        try:
            bar_dt = pd.Timestamp(bar_time).to_pydatetime()
            if bar_dt.tzinfo is None:
                bar_dt = bar_dt.replace(tzinfo=timezone.utc)

            # Pass 5m dataframe if using 5m regime
            sig_5m = None
            if use_5m_regime and df_5m is not None and not df_5m.empty:
                # Get 5m bars up to current time
                mask = df_5m["timestamp"] <= bar_time
                if mask.any():
                    sig_5m = df_5m[mask].tail(100)

            signals = generate_signals(window, config=cfg, current_time=bar_dt, df_5m=sig_5m)
        except Exception:
            continue

        for sig in signals:
            total_signals_generated += 1
            direction = sig["direction"]
            confidence = float(sig.get("confidence", 0))

            # Cooldown: skip if we recently generated a signal in this direction
            cd_key = direction
            last_sig_time = signal_cooldown.get(cd_key)
            if last_sig_time and (bar_time - last_sig_time).total_seconds() < cooldown_seconds:
                continue

            # Skip if we already have an open trade in this direction
            if any(t["direction"] == direction for t in open_trades):
                continue

            # TOD scaling
            if enable_tod:
                tod_mult = get_tod_multiplier(bar_dt, tod_multipliers)
                scaled_confidence = confidence * tod_mult
                if scaled_confidence < effective_min_conf:
                    tod_blocked += 1
                    continue
                confidence = scaled_confidence

            # Get regime for CB
            regime_dict = None
            if use_5m_regime:
                regime_dict = _find_5m_regime(bar_time)
            if regime_dict is None:
                # Fall back to signal's own regime
                mr = sig.get("market_regime")
                if mr:
                    regime_dict = mr.to_dict() if hasattr(mr, "to_dict") else (mr if isinstance(mr, dict) else None)

            # Circuit breaker check
            if circuit_breaker:
                allowed, reason = circuit_breaker.should_allow(
                    signal=sig,
                    sim_time=bar_dt,
                    regime=regime_dict,
                )
                if not allowed:
                    cb_blocked += 1
                    continue

            signal_cooldown[cd_key] = bar_time

            # Compute ATR for trailing stop
            atr_val = 1.0
            try:
                if len(window) >= 14:
                    tr = pd.concat([
                        window["high"] - window["low"],
                        (window["high"] - window["close"].shift(1)).abs(),
                        (window["low"] - window["close"].shift(1)).abs(),
                    ], axis=1).max(axis=1)
                    atr_val = float(tr.iloc[-14:].mean())
            except Exception:
                pass

            regime_str = "unknown"
            if regime_dict:
                regime_str = regime_dict.get("regime", "unknown")

            open_trades.append({
                "direction": direction,
                "entry_price": float(sig["entry_price"]),
                "stop_loss": float(sig["stop_loss"]),
                "take_profit": float(sig["take_profit"]),
                "original_stop": float(sig["stop_loss"]),
                "confidence": confidence,
                "reason": sig.get("reason", ""),
                "regime": regime_str,
                "entry_time": bar_time,
                "entry_bar_idx": i,
                "max_price": float(sig["entry_price"]),
                "min_price": float(sig["entry_price"]),
                "atr": atr_val,
                "cb_allowed": True,
            })

    # Close any remaining open trades at last bar's close
    if open_trades:
        last_close = float(bars_df.iloc[-1]["close"])
        last_time = bars_df.iloc[-1]["timestamp"]
        for trade in open_trades:
            direction = trade["direction"]
            entry_px = trade["entry_price"]
            if direction == "long":
                pnl_points = last_close - entry_px
            else:
                pnl_points = entry_px - last_close
            pnl_dollars = pnl_points * point_value

            max_px = trade.get("max_price", entry_px)
            min_px = trade.get("min_price", entry_px)
            if direction == "long":
                mfe = max_px - entry_px
                mae = entry_px - min_px
            else:
                mfe = entry_px - min_px
                mae = max_px - entry_px

            results.append({
                "entry_time": trade["entry_time"].isoformat() if hasattr(trade["entry_time"], "isoformat") else str(trade["entry_time"]),
                "exit_time": last_time.isoformat() if hasattr(last_time, "isoformat") else str(last_time),
                "direction": direction,
                "entry_price": entry_px,
                "exit_price": last_close,
                "stop_loss": trade["original_stop"],
                "take_profit": trade["take_profit"],
                "exit_reason": "end_of_data",
                "pnl_points": round(pnl_points, 4),
                "pnl_dollars": round(pnl_points * point_value, 2),
                "mfe_points": round(mfe, 4),
                "mae_points": round(mae, 4),
                "confidence": trade.get("confidence", 0),
                "reason": trade.get("reason", ""),
                "regime": trade.get("regime", "unknown"),
                "trailing_phase": trade.get("trailing_phase"),
                "hold_bars": len(bars_df) - 1 - trade["entry_bar_idx"],
                "cb_allowed": True,
            })

    metadata = {
        "total_signals_generated": total_signals_generated,
        "cb_blocked": cb_blocked,
        "tod_blocked": tod_blocked,
        "trades_taken": len(results),
        "cb_stats": circuit_breaker.get_stats() if circuit_breaker else None,
    }

    return results, metadata


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(results: List[Dict]) -> Dict[str, Any]:
    """Compute comprehensive backtest metrics from trade results."""
    if not results:
        return {"total_trades": 0, "error": "No trades generated"}

    df = pd.DataFrame(results)
    total = len(df)
    winners = df[df["pnl_dollars"] > 0]
    losers = df[df["pnl_dollars"] < 0]
    breakeven = df[df["pnl_dollars"] == 0]

    win_count = len(winners)
    loss_count = len(losers)
    win_rate = win_count / total if total > 0 else 0

    total_pnl = float(df["pnl_dollars"].sum())
    avg_win = float(winners["pnl_dollars"].mean()) if len(winners) > 0 else 0
    avg_loss = float(losers["pnl_dollars"].mean()) if len(losers) > 0 else 0
    profit_factor = abs(float(winners["pnl_dollars"].sum()) / float(losers["pnl_dollars"].sum())) if len(losers) > 0 and losers["pnl_dollars"].sum() != 0 else float("inf")

    # Max drawdown
    cumulative = df["pnl_dollars"].cumsum()
    running_max = cumulative.cummax()
    drawdown = cumulative - running_max
    max_drawdown = float(drawdown.min())

    # Sharpe
    if df["pnl_dollars"].std() > 0:
        sharpe = float(df["pnl_dollars"].mean() / df["pnl_dollars"].std()) * (252 ** 0.5)
    else:
        sharpe = 0.0

    # MFE/MAE analysis
    avg_mfe = float(df["mfe_points"].mean())
    avg_mae = float(df["mae_points"].mean())
    avg_winner_mfe = float(winners["mfe_points"].mean()) if len(winners) > 0 else 0
    avg_loser_mae = float(losers["mae_points"].mean()) if len(losers) > 0 else 0

    if len(winners) > 0:
        giveback = float((winners["mfe_points"] - winners["pnl_points"]).mean())
    else:
        giveback = 0

    # By direction
    by_direction = {}
    for d in ["long", "short"]:
        ddf = df[df["direction"] == d]
        if len(ddf) > 0:
            dw = ddf[ddf["pnl_dollars"] > 0]
            by_direction[d] = {
                "trades": len(ddf),
                "win_rate": round(len(dw) / len(ddf), 4),
                "total_pnl": round(float(ddf["pnl_dollars"].sum()), 2),
                "avg_pnl": round(float(ddf["pnl_dollars"].mean()), 2),
            }

    # By exit reason
    by_exit = {}
    for reason in df["exit_reason"].unique():
        rdf = df[df["exit_reason"] == reason]
        by_exit[reason] = {
            "count": len(rdf),
            "total_pnl": round(float(rdf["pnl_dollars"].sum()), 2),
        }

    # By regime
    by_regime = {}
    if "regime" in df.columns:
        for regime in df["regime"].unique():
            rdf = df[df["regime"] == regime]
            if len(rdf) > 0:
                rw = rdf[rdf["pnl_dollars"] > 0]
                by_regime[regime] = {
                    "trades": len(rdf),
                    "win_rate": round(len(rw) / len(rdf), 4),
                    "total_pnl": round(float(rdf["pnl_dollars"].sum()), 2),
                }

    metrics = {
        "total_trades": total,
        "winners": win_count,
        "losers": loss_count,
        "breakeven": len(breakeven),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_trade_pnl": round(total_pnl / total, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_approx": round(sharpe, 4),
        "avg_mfe_points": round(avg_mfe, 2),
        "avg_mae_points": round(avg_mae, 2),
        "avg_winner_mfe": round(avg_winner_mfe, 2),
        "avg_loser_mae": round(avg_loser_mae, 2),
        "avg_winner_giveback": round(giveback, 2),
        "avg_hold_bars": round(float(df["hold_bars"].mean()), 1),
        "by_direction": by_direction,
        "by_exit_reason": by_exit,
        "by_regime": by_regime,
    }

    return metrics


# ---------------------------------------------------------------------------
# Parameter sweep
# ---------------------------------------------------------------------------

def run_parameter_sweep(
    bars_df: pd.DataFrame,
    param_grid: Dict[str, List],
    trailing_config: Optional[Dict] = None,
    circuit_breaker: Optional[BacktestCircuitBreaker] = None,
    enable_tod: bool = True,
    df_5m: Optional[pd.DataFrame] = None,
    use_5m_regime: bool = False,
) -> List[Dict]:
    """Run backtest across a grid of parameter combinations."""
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(product(*values))

    print(f"\n  Parameter sweep: {len(combos)} combinations")
    sweep_results = []

    for idx, combo in enumerate(combos, 1):
        overrides = dict(zip(keys, combo))
        label = ", ".join(f"{k}={v}" for k, v in overrides.items())
        print(f"\n  [{idx}/{len(combos)}] {label}")

        # Fresh CB for each run
        cb = None
        if circuit_breaker:
            cb = BacktestCircuitBreaker(
                max_consecutive_losses=circuit_breaker.max_consecutive_losses,
                cooldown_minutes=circuit_breaker.cooldown_minutes,
                max_session_drawdown=circuit_breaker.max_session_drawdown,
                max_daily_drawdown=circuit_breaker.max_daily_drawdown,
                max_daily_profit=circuit_breaker.max_daily_profit,
                enable_direction_gating=circuit_breaker.enable_direction_gating,
                direction_gating_min_confidence=circuit_breaker.direction_gating_min_confidence,
                enable_regime_avoidance=circuit_breaker.enable_regime_avoidance,
                blocked_regimes=circuit_breaker.blocked_regimes,
            )

        results, meta = run_backtest(
            bars_df, config_overrides=overrides, trailing_config=trailing_config,
            circuit_breaker=cb, enable_tod=enable_tod,
            df_5m=df_5m, use_5m_regime=use_5m_regime,
        )
        metrics = compute_metrics(results)
        metrics["params"] = overrides
        metrics["label"] = label
        metrics["cb_blocked"] = meta.get("cb_blocked", 0)
        metrics["tod_blocked"] = meta.get("tod_blocked", 0)
        sweep_results.append(metrics)

    sweep_results.sort(key=lambda x: x.get("total_pnl", 0), reverse=True)
    return sweep_results


# ---------------------------------------------------------------------------
# A/B Comparison
# ---------------------------------------------------------------------------

def run_ab_comparison(
    bars_df: pd.DataFrame,
    config_a_spec: str,
    config_b_spec: str,
    trailing_config: Optional[Dict] = None,
    enable_cb: bool = True,
    enable_tod: bool = True,
    df_5m: Optional[pd.DataFrame] = None,
    use_5m_regime: bool = False,
) -> Dict[str, Any]:
    """Run two configs side-by-side and compare."""
    live_cfg = load_live_config()
    pba = live_cfg.get("pearl_bot_auto", {})
    tcb = live_cfg.get("trading_circuit_breaker", {})

    def _make_overrides(spec: str) -> Dict:
        if spec == "current":
            return {
                "ema_fast": pba.get("ema_fast", 9),
                "ema_slow": pba.get("ema_slow", 21),
                "stop_loss_atr_mult": pba.get("stop_loss_atr_mult", 1.0),
                "take_profit_atr_mult": pba.get("take_profit_atr_mult", 2.0),
                "min_confidence": pba.get("min_confidence", 0.40),
            }
        base = _make_overrides("current")
        base.update(parse_config_spec(spec))
        return base

    overrides_a = _make_overrides(config_a_spec)
    overrides_b = _make_overrides(config_b_spec)

    def _make_cb() -> Optional[BacktestCircuitBreaker]:
        if not enable_cb:
            return None
        return BacktestCircuitBreaker(
            max_consecutive_losses=tcb.get("max_consecutive_losses", 3),
            cooldown_minutes=30,
            max_session_drawdown=tcb.get("max_session_drawdown", 1800),
            max_daily_drawdown=tcb.get("max_daily_drawdown", 99999),
            max_daily_profit=tcb.get("max_daily_profit", 3000),
            enable_direction_gating=tcb.get("enable_direction_gating", True),
            direction_gating_min_confidence=tcb.get("direction_gating_min_confidence", 0.50),
            enable_regime_avoidance=tcb.get("enable_regime_avoidance", True),
            blocked_regimes=tcb.get("blocked_regimes", ["ranging", "volatile"]),
        )

    print(f"\n  Config A: {overrides_a}")
    results_a, meta_a = run_backtest(
        bars_df, config_overrides=overrides_a, trailing_config=trailing_config,
        circuit_breaker=_make_cb(), enable_tod=enable_tod,
        df_5m=df_5m, use_5m_regime=use_5m_regime,
    )
    metrics_a = compute_metrics(results_a)

    print(f"\n  Config B: {overrides_b}")
    results_b, meta_b = run_backtest(
        bars_df, config_overrides=overrides_b, trailing_config=trailing_config,
        circuit_breaker=_make_cb(), enable_tod=enable_tod,
        df_5m=df_5m, use_5m_regime=use_5m_regime,
    )
    metrics_b = compute_metrics(results_b)

    return {
        "config_a": {"spec": config_a_spec, "overrides": overrides_a, "metrics": metrics_a, "meta": meta_a},
        "config_b": {"spec": config_b_spec, "overrides": overrides_b, "metrics": metrics_b, "meta": meta_b},
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_metrics(metrics: Dict, title: str = "Backtest Results", metadata: Optional[Dict] = None) -> None:
    """Pretty-print backtest metrics."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

    if metrics.get("total_trades", 0) == 0:
        print("  No trades generated.")
        return

    print(f"  Total Trades:     {metrics['total_trades']}")
    print(f"  Win Rate:         {metrics['win_rate']:.1%}")
    print(f"  Total PnL:        ${metrics['total_pnl']:,.2f}")
    print(f"  Avg Trade:        ${metrics['avg_trade_pnl']:,.2f}")
    print(f"  Avg Win:          ${metrics['avg_win']:,.2f}")
    print(f"  Avg Loss:         ${metrics['avg_loss']:,.2f}")
    print(f"  Profit Factor:    {metrics['profit_factor']}")
    print(f"  Max Drawdown:     ${metrics['max_drawdown']:,.2f}")
    print(f"  Sharpe (approx):  {metrics['sharpe_approx']:.2f}")
    print(f"  Avg Hold (bars):  {metrics['avg_hold_bars']:.0f}")

    if metadata:
        print(f"\n  Signal Pipeline:")
        print(f"    Signals Generated: {metadata.get('total_signals_generated', 'N/A')}")
        print(f"    CB Blocked:        {metadata.get('cb_blocked', 0)}")
        print(f"    TOD Blocked:       {metadata.get('tod_blocked', 0)}")
        print(f"    Trades Taken:      {metadata.get('trades_taken', 'N/A')}")
        cb_stats = metadata.get("cb_stats")
        if cb_stats:
            print(f"    CB Blocks Detail:  {cb_stats.get('blocks_by_reason', {})}")

    print(f"\n  MFE/MAE Analysis:")
    print(f"    Avg MFE:          {metrics['avg_mfe_points']:.2f} pts")
    print(f"    Avg MAE:          {metrics['avg_mae_points']:.2f} pts")
    print(f"    Winner Avg MFE:   {metrics['avg_winner_mfe']:.2f} pts")
    print(f"    Loser Avg MAE:    {metrics['avg_loser_mae']:.2f} pts")
    print(f"    Winner Giveback:  {metrics['avg_winner_giveback']:.2f} pts")

    if metrics.get("by_direction"):
        print(f"\n  By Direction:")
        for d, stats in metrics["by_direction"].items():
            print(f"    {d.upper():6s}: {stats['trades']} trades, "
                  f"WR={stats['win_rate']:.1%}, PnL=${stats['total_pnl']:,.2f}")

    if metrics.get("by_exit_reason"):
        print(f"\n  By Exit Reason:")
        for reason, stats in metrics["by_exit_reason"].items():
            print(f"    {reason:15s}: {stats['count']} trades, PnL=${stats['total_pnl']:,.2f}")

    if metrics.get("by_regime"):
        print(f"\n  By Regime:")
        for regime, stats in metrics["by_regime"].items():
            print(f"    {regime:15s}: {stats['trades']} trades, "
                  f"WR={stats['win_rate']:.1%}, PnL=${stats['total_pnl']:,.2f}")

    print(f"{'='*60}\n")


def print_ab_comparison(ab_result: Dict) -> None:
    """Print side-by-side A/B comparison."""
    a = ab_result["config_a"]
    b = ab_result["config_b"]
    ma = a["metrics"]
    mb = b["metrics"]

    print(f"\n{'='*75}")
    print(f"  A/B Comparison")
    print(f"{'='*75}")
    print(f"  Config A: {a['spec']}")
    print(f"  Config B: {b['spec']}")

    header = f"\n  {'Metric':<20} {'Config A':>15} {'Config B':>15} {'Delta':>15}"
    print(header)
    print(f"  {'-'*20} {'-'*15} {'-'*15} {'-'*15}")

    def _row(label: str, va: Any, vb: Any, fmt: str = ",.2f", prefix: str = "$") -> None:
        if isinstance(va, str) or isinstance(vb, str):
            print(f"  {label:<20} {str(va):>15} {str(vb):>15}")
            return
        if fmt == "d":
            va, vb = int(va), int(vb)
        else:
            va, vb = float(va), float(vb)
        delta = vb - va
        sign = "+" if delta >= 0 else ""
        va_s = f"{prefix}{va:{fmt}}"
        vb_s = f"{prefix}{vb:{fmt}}"
        delta_s = f"{sign}{prefix}{delta:{fmt}}"
        print(f"  {label:<20} {va_s:>15} {vb_s:>15} {delta_s:>15}")

    _row("Total PnL", ma.get("total_pnl", 0), mb.get("total_pnl", 0))
    _row("Win Rate", ma.get("win_rate", 0), mb.get("win_rate", 0), ".1%", "")
    _row("Trades", ma.get("total_trades", 0), mb.get("total_trades", 0), "d", "")
    _row("Profit Factor", ma.get("profit_factor", 0) if isinstance(ma.get("profit_factor"), (int, float)) else 0,
         mb.get("profit_factor", 0) if isinstance(mb.get("profit_factor"), (int, float)) else 0, ".2f", "")
    _row("Max Drawdown", ma.get("max_drawdown", 0), mb.get("max_drawdown", 0))
    _row("Sharpe", ma.get("sharpe_approx", 0), mb.get("sharpe_approx", 0), ".2f", "")
    _row("Avg Trade PnL", ma.get("avg_trade_pnl", 0), mb.get("avg_trade_pnl", 0))
    _row("CB Blocked", a["meta"].get("cb_blocked", 0), b["meta"].get("cb_blocked", 0), "d", "")
    _row("TOD Blocked", a["meta"].get("tod_blocked", 0), b["meta"].get("tod_blocked", 0), "d", "")

    # Verdict
    pnl_a = ma.get("total_pnl", 0)
    pnl_b = mb.get("total_pnl", 0)
    dd_a = ma.get("max_drawdown", 0)
    dd_b = mb.get("max_drawdown", 0)
    if pnl_b > pnl_a and dd_b >= dd_a:
        verdict = "Config B is BETTER (higher PnL, equal/better drawdown)"
    elif pnl_b > pnl_a:
        verdict = "Config B has higher PnL but worse drawdown - CAUTION"
    elif pnl_b < pnl_a and dd_b >= dd_a:
        verdict = "Config A is BETTER"
    else:
        verdict = "Mixed results - manual review needed"
    print(f"\n  Verdict: {verdict}")
    print(f"{'='*75}\n")


def print_sweep_results(sweep_results: List[Dict]) -> None:
    """Print sweep results as a ranked table."""
    print(f"\n{'='*80}")
    print(f"  Parameter Sweep Results (ranked by PnL)")
    print(f"{'='*80}")
    print(f"  {'#':>3}  {'PnL':>10}  {'WR':>6}  {'Trades':>6}  {'PF':>6}  {'MaxDD':>10}  Parameters")
    print(f"  {'-'*3}  {'-'*10}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*10}  {'-'*30}")

    for i, m in enumerate(sweep_results[:20], 1):
        pf = m.get("profit_factor", 0)
        pf_str = f"{pf:.2f}" if isinstance(pf, (int, float)) else str(pf)
        print(
            f"  {i:>3}  ${m.get('total_pnl', 0):>9,.2f}  "
            f"{m.get('win_rate', 0):>5.1%}  "
            f"{m.get('total_trades', 0):>6}  "
            f"{pf_str:>6}  "
            f"${m.get('max_drawdown', 0):>9,.2f}  "
            f"{m.get('label', '')}"
        )

    print(f"{'='*80}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_list(value: str) -> List[float]:
    """Parse comma-separated values into a list of floats."""
    return [float(v.strip()) for v in value.split(",")]


def main():
    parser = argparse.ArgumentParser(description="PearlAlgo Backtester (Production-Grade)")
    parser.add_argument("--days", type=int, default=7, help="Days of data to backtest (default: 7)")
    parser.add_argument("--csv-dir", type=str, help="Directory with CSV bar files")
    parser.add_argument("--output", type=str, help="Write results to JSON file (legacy alias for --json-out)")
    parser.add_argument("--json-out", type=str, help="Write structured results to JSON file")
    parser.add_argument("--sweep", action="store_true", help="Run parameter sweep mode")

    # Strategy parameter overrides
    parser.add_argument("--ema-fast", type=str, default=None)
    parser.add_argument("--ema-slow", type=str, default=None)
    parser.add_argument("--sl-atr", type=str, default=None)
    parser.add_argument("--tp-atr", type=str, default=None)
    parser.add_argument("--min-confidence", type=str, default=None)

    # Trailing stop simulation
    parser.add_argument("--trailing", action="store_true", help="Enable trailing stop simulation")
    parser.add_argument("--trail-be-atr", type=float, default=1.0)
    parser.add_argument("--trail-lock-atr", type=float, default=2.0)
    parser.add_argument("--trail-lock-trail", type=float, default=1.5)
    parser.add_argument("--trail-tight-atr", type=float, default=3.0)
    parser.add_argument("--trail-tight-trail", type=float, default=1.0)

    # Circuit breaker
    parser.add_argument("--no-cb", action="store_true", help="Disable circuit breaker simulation")
    parser.add_argument("--no-tod", action="store_true", help="Disable TOD confidence scaling")
    parser.add_argument("--no-gating", action="store_true", help="Disable direction gating")

    # Regime
    parser.add_argument("--regime", type=str, default="1m", choices=["1m", "5m"],
                        help="Regime detection timeframe (default: 1m)")

    # A/B comparison
    parser.add_argument("--compare", action="store_true", help="A/B comparison mode")
    parser.add_argument("--config-a", type=str, default="current", help="Config A spec (default: current)")
    parser.add_argument("--config-b", type=str, default=None, help="Config B spec (e.g. proposed:min_confidence=0.5)")

    args = parser.parse_args()
    json_out_path = args.json_out or args.output

    print(f"\nPearlAlgo Backtester (Production-Grade)")
    print(f"{'='*40}")

    # Load data
    print(f"\nLoading {args.days} days of bar data...")
    csv_dir = Path(args.csv_dir) if args.csv_dir else None
    bars_df = load_bars(days=args.days, csv_dir=csv_dir, timeframe="1m")
    if bars_df.empty:
        print("ERROR: No 1m bar data found.")
        sys.exit(1)
    print(f"  Loaded {len(bars_df)} 1m bars")
    print(f"  Range: {bars_df['timestamp'].iloc[0]} to {bars_df['timestamp'].iloc[-1]}")

    # Load 5m bars if needed
    df_5m = None
    use_5m_regime = args.regime == "5m"
    if use_5m_regime:
        df_5m = load_bars(days=args.days, csv_dir=csv_dir, timeframe="5m")
        if df_5m.empty:
            print("  WARNING: No 5m bars found, falling back to 1m regime")
            use_5m_regime = False
        else:
            print(f"  Loaded {len(df_5m)} 5m bars for regime detection")

    # Build trailing config
    trailing_config = None
    if args.trailing:
        trailing_config = {
            "enabled": True,
            "phases": [
                {"name": "breakeven", "activation_atr": args.trail_be_atr, "trail_atr": 0.0},
                {"name": "lock_profit", "activation_atr": args.trail_lock_atr, "trail_atr": args.trail_lock_trail},
                {"name": "tight_trail", "activation_atr": args.trail_tight_atr, "trail_atr": args.trail_tight_trail},
            ],
        }
        print(f"  Trailing stops: ENABLED")

    # Build circuit breaker from live config
    cb = None
    if not args.no_cb:
        live_cfg = load_live_config()
        tcb = live_cfg.get("trading_circuit_breaker", {})
        cb = BacktestCircuitBreaker(
            max_consecutive_losses=tcb.get("max_consecutive_losses", 3),
            cooldown_minutes=30,
            max_session_drawdown=tcb.get("max_session_drawdown", 1800),
            max_daily_drawdown=tcb.get("max_daily_drawdown", 99999),
            max_daily_profit=tcb.get("max_daily_profit", 3000),
            enable_direction_gating=tcb.get("enable_direction_gating", True) and not args.no_gating,
            direction_gating_min_confidence=tcb.get("direction_gating_min_confidence", 0.50),
            enable_regime_avoidance=tcb.get("enable_regime_avoidance", True),
            blocked_regimes=tcb.get("blocked_regimes", ["ranging", "volatile"]),
        )
        print(f"  Circuit breaker: ENABLED (losses={cb.max_consecutive_losses}, "
              f"gating={'ON' if cb.enable_direction_gating else 'OFF'}, "
              f"regime_avoid={'ON' if cb.enable_regime_avoidance else 'OFF'})")
    else:
        print(f"  Circuit breaker: DISABLED")

    enable_tod = not args.no_tod
    print(f"  TOD scaling: {'ENABLED' if enable_tod else 'DISABLED'}")
    print(f"  Regime source: {args.regime}")

    start = time.time()

    # A/B comparison mode
    if args.compare:
        if not args.config_b:
            print("ERROR: --compare requires --config-b")
            sys.exit(1)
        ab_result = run_ab_comparison(
            bars_df, args.config_a, args.config_b,
            trailing_config=trailing_config,
            enable_cb=not args.no_cb, enable_tod=enable_tod,
            df_5m=df_5m, use_5m_regime=use_5m_regime,
        )
        print_ab_comparison(ab_result)
        elapsed = time.time() - start
        print(f"  A/B comparison completed in {elapsed:.1f}s")

        if json_out_path:
            out_path = Path(json_out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                json.dump(ab_result, f, indent=2, default=str)
            print(f"  Results saved to {json_out_path}")
        return

    # Sweep mode
    if args.sweep:
        param_grid: Dict[str, List] = {}
        if args.ema_fast:
            param_grid["ema_fast"] = [int(v) for v in parse_list(args.ema_fast)]
        if args.ema_slow:
            param_grid["ema_slow"] = [int(v) for v in parse_list(args.ema_slow)]
        if args.sl_atr:
            param_grid["stop_loss_atr_mult"] = parse_list(args.sl_atr)
        if args.tp_atr:
            param_grid["take_profit_atr_mult"] = parse_list(args.tp_atr)
        if args.min_confidence:
            param_grid["min_confidence"] = parse_list(args.min_confidence)

        if not param_grid:
            print("ERROR: --sweep requires at least one parameter with multiple values")
            sys.exit(1)

        sweep_results = run_parameter_sweep(
            bars_df, param_grid, trailing_config=trailing_config,
            circuit_breaker=cb, enable_tod=enable_tod,
            df_5m=df_5m, use_5m_regime=use_5m_regime,
        )
        print_sweep_results(sweep_results)

        elapsed = time.time() - start
        print(f"  Sweep completed in {elapsed:.1f}s")

        if json_out_path:
            out_path = Path(json_out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                json.dump(sweep_results, f, indent=2, default=str)
            print(f"  Results saved to {json_out_path}")
        return

    # Single backtest run
    overrides: Dict[str, Any] = {}
    if args.ema_fast:
        overrides["ema_fast"] = int(parse_list(args.ema_fast)[0])
    if args.ema_slow:
        overrides["ema_slow"] = int(parse_list(args.ema_slow)[0])
    if args.sl_atr:
        overrides["stop_loss_atr_mult"] = parse_list(args.sl_atr)[0]
    if args.tp_atr:
        overrides["take_profit_atr_mult"] = parse_list(args.tp_atr)[0]
    if args.min_confidence:
        overrides["min_confidence"] = parse_list(args.min_confidence)[0]

    if overrides:
        print(f"  Overrides: {overrides}")

    print(f"\nRunning backtest...")
    results, metadata = run_backtest(
        bars_df, config_overrides=overrides, trailing_config=trailing_config,
        circuit_breaker=cb, enable_tod=enable_tod,
        df_5m=df_5m, use_5m_regime=use_5m_regime,
    )
    metrics = compute_metrics(results)

    elapsed = time.time() - start
    title = "Backtest Results"
    parts = []
    if trailing_config:
        parts.append("trailing stops")
    if cb:
        parts.append("circuit breaker")
    if enable_tod:
        parts.append("TOD scaling")
    if use_5m_regime:
        parts.append("5m regime")
    if parts:
        title += f" (with {', '.join(parts)})"

    print_metrics(metrics, title=title, metadata=metadata)
    print(f"  Completed in {elapsed:.1f}s")

    if json_out_path:
        output_data = {
            "metrics": metrics,
            "trades": results,
            "metadata": metadata,
            "config": {
                "days": args.days,
                "trailing": bool(trailing_config),
                "circuit_breaker": not args.no_cb,
                "tod_scaling": enable_tod,
                "regime_source": args.regime,
                "overrides": overrides,
            },
        }
        out_path = Path(json_out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"  Results saved to {json_out_path}")


if __name__ == "__main__":
    main()
