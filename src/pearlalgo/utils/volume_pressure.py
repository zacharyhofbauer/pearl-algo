"""
Volume pressure helpers (buy/sell pressure proxy).

This is **not** true order-flow / volume delta from the tape. It is a robust proxy
computed from OHLCV candles:

- If a candle closes above open -> treat its volume as "buying pressure"
- If a candle closes below open -> treat its volume as "selling pressure"
- Doji candles contribute 0

We aggregate across a lookback window and normalize by total volume to produce a
bounded score in [-1, 1].

This is useful for operator observability (Telegram dashboard) and for chart
overlays, but should not be used as an execution signal without real delta data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class VolumePressureSummary:
    """Compact summary of buy/sell pressure over a lookback window."""

    bias: str  # "buyers" | "sellers" | "mixed"
    strength: str  # "flat" | "light" | "moderate" | "strong"
    score: float  # [-1, 1]
    score_pct: float  # [-100, 100]
    lookback_bars: int
    total_volume: float
    volume_ratio: Optional[float] = None  # recent_avg / baseline_avg

    def to_dict(self) -> dict:
        return {
            "bias": self.bias,
            "strength": self.strength,
            "score": float(self.score),
            "score_pct": float(self.score_pct),
            "lookback_bars": int(self.lookback_bars),
            "total_volume": float(self.total_volume),
            "volume_ratio": float(self.volume_ratio) if self.volume_ratio is not None else None,
        }


def timeframe_to_minutes(timeframe: str) -> Optional[int]:
    """Parse timeframe like '5m', '15m', '1h' into minutes."""
    if not timeframe:
        return None
    s = str(timeframe).strip().lower()
    try:
        if s.endswith("m"):
            return int(s[:-1])
        if s.endswith("h"):
            return int(s[:-1]) * 60
    except Exception:
        return None
    return None


def format_minutes_short(minutes: int) -> str:
    """Format minutes into a compact human string (e.g., 120 -> '2h', 180 -> '3h')."""
    if minutes <= 0:
        return ""
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    if minutes >= 60:
        hrs = minutes // 60
        mins = minutes % 60
        return f"{hrs}h{mins}m"
    return f"{minutes}m"


def compute_signed_volume_series(
    df: pd.DataFrame,
    *,
    open_col: str,
    close_col: str,
    volume_col: str,
) -> Optional[pd.Series]:
    """Compute signed volume series (+vol for up candles, -vol for down candles)."""
    if df is None or df.empty:
        return None
    if open_col not in df.columns or close_col not in df.columns or volume_col not in df.columns:
        return None

    try:
        o = pd.to_numeric(df[open_col], errors="coerce")
        c = pd.to_numeric(df[close_col], errors="coerce")
        v = pd.to_numeric(df[volume_col], errors="coerce").fillna(0.0)
        sign = np.sign((c - o).fillna(0.0))
        return v * sign
    except Exception:
        return None


def compute_volume_pressure_summary(
    df: pd.DataFrame,
    *,
    lookback_bars: int = 24,
    baseline_bars: int = 120,
    open_col: str = "open",
    close_col: str = "close",
    volume_col: str = "volume",
) -> Optional[VolumePressureSummary]:
    """
    Compute buy/sell pressure summary from OHLCV.

    Returns None if required columns are missing or insufficient data exists.
    """
    if df is None or df.empty:
        return None
    if lookback_bars <= 0:
        return None
    if open_col not in df.columns or close_col not in df.columns or volume_col not in df.columns:
        return None

    tail = df.tail(int(lookback_bars)).copy()
    if tail.empty:
        return None

    signed = compute_signed_volume_series(
        tail,
        open_col=open_col,
        close_col=close_col,
        volume_col=volume_col,
    )
    if signed is None:
        return None

    vol = pd.to_numeric(tail[volume_col], errors="coerce").fillna(0.0)
    total_vol = float(vol.sum())
    if total_vol <= 0:
        return None

    net = float(signed.sum())
    score = float(np.clip(net / total_vol, -1.0, 1.0))
    score_pct = score * 100.0

    abs_score = abs(score)
    if abs_score < 0.05:
        bias = "mixed"
        strength = "flat"
    else:
        bias = "buyers" if score > 0 else "sellers"
        if abs_score >= 0.20:
            strength = "strong"
        elif abs_score >= 0.10:
            strength = "moderate"
        else:
            strength = "light"

    # Volume ratio: recent avg vs baseline avg
    volume_ratio: Optional[float] = None
    try:
        baseline = df.tail(int(max(baseline_bars, lookback_bars))).copy()
        baseline_vol = pd.to_numeric(baseline[volume_col], errors="coerce").fillna(0.0)
        base_avg = float(baseline_vol.mean()) if len(baseline_vol) > 0 else 0.0
        recent_avg = float(vol.mean()) if len(vol) > 0 else 0.0
        if base_avg > 0:
            volume_ratio = float(recent_avg / base_avg)
    except Exception:
        volume_ratio = None

    return VolumePressureSummary(
        bias=bias,
        strength=strength,
        score=score,
        score_pct=score_pct,
        lookback_bars=int(len(tail)),
        total_volume=total_vol,
        volume_ratio=volume_ratio,
    )


def format_volume_pressure(
    summary: VolumePressureSummary,
    *,
    timeframe_minutes: Optional[int] = None,
    data_fresh: Optional[bool] = None,
) -> str:
    """
    Format pressure into a compact, operator-friendly string.

    Example:
      '🟢 Pressure: BUYERS ▲▲ (Δ +18%, Vol 1.3x, 2h)'
    """
    bias = (summary.bias or "mixed").lower()
    strength = (summary.strength or "flat").lower()

    arrows = ""
    if strength == "light":
        arrows = "▲" if bias == "buyers" else "▼" if bias == "sellers" else ""
    elif strength == "moderate":
        arrows = "▲▲" if bias == "buyers" else "▼▼" if bias == "sellers" else ""
    elif strength == "strong":
        arrows = "▲▲▲" if bias == "buyers" else "▼▼▼" if bias == "sellers" else ""

    if bias == "buyers":
        emoji = "🟢"
        label = "BUYERS"
    elif bias == "sellers":
        emoji = "🔴"
        label = "SELLERS"
    else:
        emoji = "⚪"
        label = "MIXED"

    # Period label
    period = ""
    if timeframe_minutes is not None and timeframe_minutes > 0:
        mins = int(timeframe_minutes) * int(summary.lookback_bars)
        period = format_minutes_short(mins)

    parts: list[str] = []
    delta = f"Δ {summary.score_pct:+.0f}%"
    parts.append(delta)
    if summary.volume_ratio is not None and np.isfinite(summary.volume_ratio):
        parts.append(f"Vol {summary.volume_ratio:.1f}x")
    if period:
        parts.append(period)

    stale_prefix = ""
    if data_fresh is False:
        stale_prefix = "⚠️ "

    arrow_part = f" {arrows}" if arrows else ""
    details = ", ".join(parts) if parts else ""
    details_part = f" ({details})" if details else ""

    return f"{stale_prefix}{emoji} Pressure: {label}{arrow_part}{details_part}"















