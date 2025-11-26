from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
import csv

from pearlalgo.risk.pnl import DailyPnLTracker
from pearlalgo.risk.sizing import volatility_position_size


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RiskAgent:
    """
    Tracks daily PnL against prop-style limits and suggests position sizes.
    - Blocks trading when daily loss breached or profit target hit.
    - Scales sizing down as remaining drawdown shrinks; optional ATR sizing.
    """

    max_daily_loss: float | None = None
    profit_target: float | None = None
    max_contracts: float | None = None
    base_size: float = 1.0
    min_size: float = 0.1
    starting_equity: float = 0.0
    pnl_tracker: DailyPnLTracker = field(default_factory=DailyPnLTracker)

    def __post_init__(self) -> None:
        self._equity_peak = float(self.starting_equity)
        self._equity_trough = float(self.starting_equity)
        self._equity_curve: list[float] = [float(self.starting_equity)]

    def update(self, realized_pnl: float | None = None, equity: float | None = None) -> None:
        pnl = self.pnl_tracker.realized_today() if realized_pnl is None else realized_pnl
        eq = equity if equity is not None else self.starting_equity + pnl
        self._equity_peak = max(self._equity_peak, eq)
        self._equity_trough = min(self._equity_trough, eq)
        self._equity_curve.append(eq)

    def remaining_drawdown(self) -> float | None:
        if self.max_daily_loss is None:
            return None
        pnl = self.pnl_tracker.realized_today()
        return max(0.0, float(self.max_daily_loss) + pnl)

    def max_intraday_drawdown(self) -> float:
        peak = self._equity_curve[0] if self._equity_curve else 0.0
        max_dd = 0.0
        for eq in self._equity_curve:
            peak = max(peak, eq)
            max_dd = min(max_dd, eq - peak)
        return abs(max_dd)

    def allow_trade(self) -> tuple[bool, str]:
        pnl = self.pnl_tracker.realized_today()
        if self.max_daily_loss is not None and pnl <= -abs(self.max_daily_loss):
            return False, "daily_loss_breached"
        if self.profit_target is not None and pnl >= self.profit_target:
            return False, "profit_target_hit"
        return True, "ok"

    def size_for_trade(
        self,
        *,
        base_size: float | None = None,
        atr: float | None = None,
        dollar_vol_per_point: float | None = None,
        risk_fraction: float = 0.001,
        account_equity: float | None = None,
    ) -> float:
        """
        Suggest a position size that respects drawdown and optional ATR stop.
        - base_size is scaled by remaining drawdown.
        - If atr and dollar_vol_per_point provided, cap size using vol sizing.
        """
        size = base_size if base_size is not None else self.base_size
        if self.max_daily_loss:
            remaining = self.remaining_drawdown() or 0.0
            scale = min(1.0, max(0.1, remaining / float(self.max_daily_loss))) if self.max_daily_loss > 0 else 1.0
            size *= scale

        if atr and dollar_vol_per_point and account_equity:
            vol_units = volatility_position_size(
                account_equity=account_equity,
                risk_per_trade=risk_fraction,
                atr=atr,
                dollar_vol_per_point=dollar_vol_per_point,
                max_units=int(self.max_contracts) if self.max_contracts is not None else None,
            )
            if vol_units > 0:
                size = min(size, vol_units)

        if self.max_contracts is not None:
            size = min(size, self.max_contracts)

        if size < self.min_size:
            return 0.0
        return float(size)

    def status(self) -> dict[str, Any]:
        pnl = self.pnl_tracker.realized_today()
        allowed, reason = self.allow_trade()
        return {
            "pnl": pnl,
            "allowed": allowed,
            "reason": reason,
            "remaining_drawdown": self.remaining_drawdown(),
            "max_intraday_drawdown": self.max_intraday_drawdown(),
        }


class PerformanceTracker:
    """
    Collects per-trade stats and computes daily summaries (PnL, win rate, DD).
    """

    def __init__(self):
        self.trades: list[dict[str, Any]] = []

    def record_trade(
        self,
        *,
        symbol: str,
        direction: str,
        size: float,
        entry_price: float,
        exit_price: float | None = None,
        pnl: float | None = None,
        mae: float | None = None,
        mfe: float | None = None,
        stop_hit: bool | None = None,
        target_hit: bool | None = None,
        timestamp: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        ts = timestamp or _now_iso()
        trade_pnl = pnl
        if trade_pnl is None and exit_price is not None:
            side_mult = 1.0 if direction.upper() == "BUY" else -1.0
            trade_pnl = (exit_price - entry_price) * size * side_mult
        trade = {
            "timestamp": ts,
            "symbol": symbol,
            "direction": direction,
            "size": size,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": trade_pnl,
            "mae": mae,
            "mfe": mfe,
            "stop_hit": stop_hit,
            "target_hit": target_hit,
            "reason": reason,
        }
        self.trades.append(trade)
        return trade

    def _equity_curve(self) -> list[float]:
        eq = 0.0
        curve: list[float] = []
        for t in self.trades:
            eq += t.get("pnl") or 0.0
            curve.append(eq)
        return curve

    def max_drawdown(self) -> float:
        curve = self._equity_curve()
        peak = 0.0
        max_dd = 0.0
        for eq in curve:
            peak = max(peak, eq)
            max_dd = min(max_dd, eq - peak)
        return abs(max_dd)

    def summary(self) -> dict[str, Any]:
        wins = [t for t in self.trades if (t.get("pnl") or 0.0) > 0]
        losses = [t for t in self.trades if (t.get("pnl") or 0.0) < 0]
        gross_win = sum(t.get("pnl") or 0.0 for t in wins)
        gross_loss = sum(t.get("pnl") or 0.0 for t in losses)
        total_pnl = gross_win + gross_loss
        trades_count = len(self.trades)
        profit_factor = gross_win / abs(gross_loss) if gross_loss != 0 else None
        win_rate = len(wins) / trades_count if trades_count else 0.0
        expectancy = total_pnl / trades_count if trades_count else 0.0
        return {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "total_pnl": total_pnl,
            "trades": trades_count,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": self.max_drawdown(),
            "expectancy": expectancy,
        }

    def reset(self) -> None:
        self.trades.clear()


def append_trade_log(row: Dict[str, Any], path: Path = Path("logs/trades_detailed.csv")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "symbol",
                "direction",
                "size",
                "entry_price",
                "exit_price",
                "pnl",
                "mae",
                "mfe",
                "stop_hit",
                "target_hit",
                "reason",
                "risk_state",
            ],
        )
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    return path


def append_daily_summary(row: Dict[str, Any], path: Path = Path("logs/daily_summary.csv")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "total_pnl",
                "trades",
                "wins",
                "losses",
                "win_rate",
                "profit_factor",
                "max_drawdown",
                "expectancy",
                "reason",
            ],
        )
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    return path
