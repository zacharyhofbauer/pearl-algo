#!/usr/bin/env python3
"""Backtest the PearlAlgo BTC Trend Defender research candidate on Coinbase BTC-USD hourly candles.

This is a research harness, not the live execution engine. It mirrors the Pine defaults closely:
4h EMA regime, daily EMA filter, 1h Donchian breakout, ATR% volatility gate, and a Chandelier stop.
Data source is Coinbase Exchange public candles. Trades assume 100% notional exposure, 0.06% fee per
side, and fixed USD slippage per side.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

COINBASE = "https://api.exchange.coinbase.com/products/{product}/candles"


@dataclass(frozen=True)
class Params:
    product: str = "BTC-USD"
    start: str = "2018-12-17T00:00:00Z"
    end: str = "2026-07-01T00:00:00Z"
    donchian: int = 100
    htf_fast: int = 20
    htf_slow: int = 50
    daily_ema: int = 200
    adx_len: int = 14
    adx_min: float = 10.0
    atr_len: int = 14
    trail_atr: float = 8.0
    min_atr_pct: float = 0.30
    max_atr_pct: float = 8.0
    fee_bps_side: float = 6.0
    slippage_usd_side: float = 5.0
    allow_shorts: bool = False
    max_bars_trade: int = 0


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_coinbase(product: str, start: str, end: str, granularity: int = 3600) -> pd.DataFrame:
    start_dt, end_dt = _dt(start), _dt(end)
    step = pd.Timedelta(seconds=granularity * 300)
    frames: list[pd.DataFrame] = []
    cur = pd.Timestamp(start_dt)
    stop = pd.Timestamp(end_dt)
    while cur < stop:
        nxt = min(cur + step, stop)
        q = urlencode({"granularity": granularity, "start": cur.isoformat(), "end": nxt.isoformat()})
        req = Request(COINBASE.format(product=product) + "?" + q, headers={"User-Agent": "pearl-algo-research"})
        with urlopen(req, timeout=30) as resp:
            raw = json.load(resp)
        if raw:
            df = pd.DataFrame(raw, columns=["time", "low", "high", "open", "close", "volume"])
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            frames.append(df)
        cur = nxt
        time.sleep(0.04)
    if not frames:
        raise RuntimeError("No candles returned from Coinbase")
    out = pd.concat(frames, ignore_index=True).drop_duplicates("time").sort_values("time")
    out = out.set_index("time")[["open", "high", "low", "close", "volume"]].astype(float)
    return out


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([(df["high"] - df["low"]), (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr_atr = atr(df, n)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr_atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr_atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def with_indicators(h1: pd.DataFrame, p: Params) -> pd.DataFrame:
    h = h1.copy()
    h["atr"] = atr(h, p.atr_len)
    h["atr_pct"] = h["atr"] / h["close"] * 100
    h["upper"] = h["high"].shift(1).rolling(p.donchian, min_periods=p.donchian).max()
    h["lower"] = h["low"].shift(1).rolling(p.donchian, min_periods=p.donchian).min()

    h4 = h.resample("4h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    h4["fast"] = ema(h4["close"], p.htf_fast)
    h4["slow"] = ema(h4["close"], p.htf_slow)
    h4["adx"] = adx(h4, p.adx_len)
    confirmed_h4 = h4[["close", "fast", "slow", "adx"]].shift(1).add_prefix("h4_")
    h = h.join(confirmed_h4.reindex(h.index, method="ffill"))

    d = h.resample("1D", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    d["daily_ema"] = ema(d["close"], p.daily_ema).shift(1)
    h = h.join(d[["daily_ema"]].reindex(h.index, method="ffill"))
    return h


def backtest(df: pd.DataFrame, p: Params) -> dict[str, Any]:
    equity = 10_000.0
    start_equity = equity
    fee = p.fee_bps_side / 10_000.0
    pos = 0
    qty = 0.0
    entry = 0.0
    entry_i = 0
    high_water = math.nan
    low_water = math.nan
    entry_fee = 0.0
    trades: list[dict[str, Any]] = []
    curve: list[tuple[pd.Timestamp, float]] = []
    pending: int | None = None

    rows = list(df.itertuples())
    for i, r in enumerate(rows):
        ts = df.index[i]
        open_px, high_px, low_px, close_px = float(r.open), float(r.high), float(r.low), float(r.close)
        if pos != 0:
            if pos > 0:
                high_water = max(high_water, high_px)
                stop = high_water - p.trail_atr * float(r.atr)
                timed = p.max_bars_trade > 0 and i - entry_i >= p.max_bars_trade
                if low_px <= stop or timed:
                    exit_px = (stop if low_px <= stop else close_px) - p.slippage_usd_side
                    gross = qty * (exit_px - entry)
                    exit_fee = abs(qty * exit_px) * fee
                    pnl = gross - entry_fee - exit_fee
                    equity += pnl
                    trades.append({"entry_time": str(df.index[entry_i]), "exit_time": str(ts), "side": "long", "entry": entry, "exit": exit_px, "pnl": pnl, "pnl_pct": pnl / start_equity, "bars": i - entry_i})
                    pos = 0
            else:
                low_water = min(low_water, low_px)
                stop = low_water + p.trail_atr * float(r.atr)
                timed = p.max_bars_trade > 0 and i - entry_i >= p.max_bars_trade
                if high_px >= stop or timed:
                    exit_px = (stop if high_px >= stop else close_px) + p.slippage_usd_side
                    gross = qty * (entry - exit_px)
                    exit_fee = abs(qty * exit_px) * fee
                    pnl = gross - entry_fee - exit_fee
                    equity += pnl
                    trades.append({"entry_time": str(df.index[entry_i]), "exit_time": str(ts), "side": "short", "entry": entry, "exit": exit_px, "pnl": pnl, "pnl_pct": pnl / start_equity, "bars": i - entry_i})
                    pos = 0

        if pending and pos == 0 and not any(pd.isna([r.atr, r.h4_fast, r.h4_slow, r.h4_adx, r.daily_ema])):
            pos = pending
            entry_i = i
            entry = open_px + (p.slippage_usd_side if pos > 0 else -p.slippage_usd_side)
            qty = equity / entry
            entry_fee = abs(qty * entry) * fee
            high_water = high_px
            low_water = low_px
            pending = None

        if pos == 0 and i + 1 < len(rows):
            trend_long = r.h4_close > r.h4_fast > r.h4_slow and r.h4_adx >= p.adx_min and close_px > r.daily_ema and p.min_atr_pct <= r.atr_pct <= p.max_atr_pct
            trend_short = r.h4_close < r.h4_fast < r.h4_slow and r.h4_adx >= p.adx_min and close_px < r.daily_ema and p.min_atr_pct <= r.atr_pct <= p.max_atr_pct
            if trend_long and close_px > r.upper:
                pending = 1
            elif p.allow_shorts and trend_short and close_px < r.lower:
                pending = -1
        mark = equity if pos == 0 else equity + (qty * (close_px - entry) if pos > 0 else qty * (entry - close_px))
        curve.append((ts, mark))

    eq = pd.Series(dict(curve)).sort_index()
    dd = eq / eq.cummax() - 1.0
    pnls = [t["pnl"] for t in trades]
    pct = [t["pnl_pct"] for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    boot = bootstrap_mean_ci(pct)
    return {
        "params": asdict(p),
        "source": "Coinbase Exchange BTC-USD hourly candles",
        "bars": int(len(df)),
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
        "trades": len(trades),
        "total_return_pct": round((eq.iloc[-1] / start_equity - 1) * 100, 2),
        "buy_hold_return_pct": round(bh * 100, 2),
        "max_drawdown_pct": round(float(dd.min()) * 100, 2),
        "win_rate_pct": round((len(wins) / len(trades) * 100) if trades else 0, 2),
        "profit_factor": round((sum(wins) / abs(sum(losses))) if losses else float("inf"), 3),
        "expectancy_usd": round(statistics.mean(pnls), 2) if pnls else 0.0,
        "expectancy_pct_trade": round((statistics.mean(pct) * 100), 3) if pct else 0.0,
        "bootstrap_mean_pct_trade": boot,
        "sample_trades": trades[:3] + ([{"ellipsis": len(trades) - 6}] if len(trades) > 6 else []) + trades[-3:],
    }


def bootstrap_mean_ci(samples: list[float], n_boot: int = 5000, seed: int = 12345) -> dict[str, Any]:
    if not samples:
        return {"n": 0, "mean_pct": 0.0, "ci95_pct": [0.0, 0.0]}
    a = np.asarray(samples, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    means = a[idx].mean(axis=1)
    return {"n": int(len(a)), "mean_pct": round(float(a.mean() * 100), 3), "ci95_pct": [round(float(np.quantile(means, 0.025) * 100), 3), round(float(np.quantile(means, 0.975) * 100), 3)]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="BTC-USD")
    ap.add_argument("--start", default="2018-12-17T00:00:00Z")
    ap.add_argument("--end", default="2026-07-01T00:00:00Z")
    ap.add_argument("--out", default="docs/audits/2026-07-01-btc-trend-defender-backtest.json")
    args = ap.parse_args()
    p = Params(product=args.product, start=args.start, end=args.end)
    candles = fetch_coinbase(p.product, p.start, p.end)
    df = with_indicators(candles, p).dropna()
    result = backtest(df, p)
    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps({k: result[k] for k in ["source", "bars", "start", "end", "trades", "total_return_pct", "buy_hold_return_pct", "max_drawdown_pct", "win_rate_pct", "profit_factor", "expectancy_pct_trade", "bootstrap_mean_pct_trade"]}, indent=2))
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
