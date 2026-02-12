"""
Tradovate Paper 50K Rapid Evaluation Tracker

Tracks challenge state for Tradovate Paper 50K Rapid Plan (Evaluation Stage).

Rules enforced (per official Tradovate Paper Rapid 50K rules):
  E1  Profit target:       PnL >= $3,000  -> PASS (if consistency + min days met)
  E2  Max loss (EOD):       Balance < floor ($48,000) at EOD -> FAIL
  E3  Drawdown floor:       EVALUATION: fixed at start_balance - max_loss ($48,000). No trailing.
                            SIM_FUNDED: intraday trailing from HWM, locks at $100 balance.
  E4  Open equity breach:   Unrealized equity < floor -> FAIL (polled externally)
  E5  Consistency (50%):    No single day > 50% of total profit (delays pass, no breach)
  E6  Min trading days:     At least 2 days with trades (delays pass)

Design:
  - Separate from the existing ChallengeTracker (IBKR Virtual account keeps its own).
  - Persists state to <state_dir>/challenge_state.json (same filename so the API
    server's _get_challenge_status() reads it transparently).
  - Tradovate Paper-specific fields are nested under "tv_paper" key so the UI can
    detect the stage and render extended info.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir, get_utc_timestamp


# ── Configuration ─────────────────────────────────────────────────────────

@dataclass
class TvPaperEvalConfig:
    """Tradovate Paper 50K Rapid Evaluation configuration."""

    enabled: bool = True
    stage: str = "evaluation"  # evaluation | sim_funded | live

    # Account parameters
    start_balance: float = 50_000.0
    profit_target: float = 3_000.0
    max_loss_distance: float = 2_000.0

    # EOD trailing drawdown (evaluation); intraday trailing (sim_funded)
    drawdown_type: str = "eod_trailing"
    # Sim funded lock: floor locks at this absolute balance (no lock during evaluation)
    drawdown_lock_threshold: float = 100.0  # sim_funded only: account must stay above $100

    # Contract limits
    max_contracts_mini: int = 5
    max_contracts_micro: int = 50

    # Consistency rule (evaluation only)
    consistency_pct: float = 0.50
    min_trading_days: int = 2

    # News trading
    t1_news_allowed: bool = True  # True for evaluation, False for sim_funded

    # Auto-reset behaviour
    auto_reset_on_pass: bool = True
    auto_reset_on_fail: bool = True


# ── Attempt State ─────────────────────────────────────────────────────────

@dataclass
class TvPaperEvalAttempt:
    """Single Tradovate Paper evaluation attempt."""

    attempt_id: int = 1
    started_at: str = ""
    ended_at: Optional[str] = None
    outcome: str = "active"  # active | pass | fail | reset_manual

    # Balance tracking
    starting_balance: float = 50_000.0
    pnl: float = 0.0

    # EOD trailing drawdown
    eod_high_water_mark: float = 50_000.0
    current_drawdown_floor: float = 48_000.0  # HWM - max_loss_distance
    drawdown_locked: bool = False

    # Daily PnL breakdown (for consistency tracking)
    daily_pnl_by_date: Dict[str, float] = field(default_factory=dict)
    trading_days: List[str] = field(default_factory=list)

    # Counters
    trades: int = 0
    wins: int = 0
    losses: int = 0
    max_drawdown_hit: float = 0.0
    profit_peak: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        wr = (self.wins / self.trades * 100) if self.trades > 0 else 0.0
        return {
            "attempt_id": self.attempt_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "outcome": self.outcome,
            "starting_balance": self.starting_balance,
            "ending_balance": self.starting_balance + self.pnl,
            "pnl": self.pnl,
            "eod_high_water_mark": self.eod_high_water_mark,
            "current_drawdown_floor": self.current_drawdown_floor,
            "drawdown_locked": self.drawdown_locked,
            "daily_pnl_by_date": dict(self.daily_pnl_by_date),
            "trading_days": list(self.trading_days),
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(wr, 2),
            "max_drawdown_hit": self.max_drawdown_hit,
            "profit_peak": self.profit_peak,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TvPaperEvalAttempt":
        return cls(
            attempt_id=int(data.get("attempt_id", 1)),
            started_at=str(data.get("started_at", get_utc_timestamp())),
            ended_at=data.get("ended_at"),
            outcome=str(data.get("outcome", "active")),
            starting_balance=float(data.get("starting_balance", 50_000.0)),
            pnl=float(data.get("pnl", 0.0)),
            eod_high_water_mark=float(data.get("eod_high_water_mark", 50_000.0)),
            current_drawdown_floor=float(data.get("current_drawdown_floor", 48_000.0)),
            drawdown_locked=bool(data.get("drawdown_locked", False)),
            daily_pnl_by_date=dict(data.get("daily_pnl_by_date", {})),
            trading_days=list(data.get("trading_days", [])),
            trades=int(data.get("trades", 0)),
            wins=int(data.get("wins", 0)),
            losses=int(data.get("losses", 0)),
            max_drawdown_hit=float(data.get("max_drawdown_hit", 0.0)),
            profit_peak=float(data.get("profit_peak", 0.0)),
        )


# ── Tracker ───────────────────────────────────────────────────────────────

class TvPaperEvalTracker:
    """
    Tracks Tradovate Paper 50K Rapid Evaluation challenge state.

    Call record_trade() after every trade exit.
    Call update_eod_hwm() at session close (4:10 PM ET).
    Call check_intraday_breach() periodically with current equity.
    """

    def __init__(
        self,
        config: Optional[TvPaperEvalConfig] = None,
        state_dir: Optional[Path] = None,
    ):
        self.config = config or TvPaperEvalConfig()
        self.state_dir = ensure_state_dir(state_dir)
        self.state_file = self.state_dir / "challenge_state.json"
        self.history_file = self.state_dir / "challenge_history.json"

        self.current_attempt = self._load_or_create_attempt()

        logger.info(
            f"TvPaperEvalTracker initialized: attempt={self.current_attempt.attempt_id}, "
            f"pnl=${self.current_attempt.pnl:.2f}, floor=${self.current_attempt.current_drawdown_floor:.2f}, "
            f"outcome={self.current_attempt.outcome}"
        )

    # ── Load / Save ───────────────────────────────────────────────────

    def _load_or_create_attempt(self) -> TvPaperEvalAttempt:
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                attempt_data = data.get("current_attempt", {})
                attempt = TvPaperEvalAttempt.from_dict(attempt_data)
                if attempt.outcome != "active":
                    return self._create_new_attempt(attempt.attempt_id + 1)
                return attempt
            except Exception as e:
                logger.warning(f"Could not load Tradovate Paper challenge state: {e}")
        return self._create_new_attempt(1)

    def _create_new_attempt(self, attempt_id: int) -> TvPaperEvalAttempt:
        initial_floor = self.config.start_balance - self.config.max_loss_distance
        attempt = TvPaperEvalAttempt(
            attempt_id=attempt_id,
            started_at=get_utc_timestamp(),
            starting_balance=self.config.start_balance,
            eod_high_water_mark=self.config.start_balance,
            current_drawdown_floor=initial_floor,
        )
        self._save_state(attempt)
        return attempt

    def _save_state(self, attempt: Optional[TvPaperEvalAttempt] = None) -> None:
        attempt = attempt or self.current_attempt
        try:
            state = {
                "config": {
                    "enabled": self.config.enabled,
                    "stage": self.config.stage,
                    "start_balance": self.config.start_balance,
                    "profit_target": self.config.profit_target,
                    "max_drawdown": self.config.max_loss_distance,
                    "drawdown_type": self.config.drawdown_type,
                    "max_contracts_mini": self.config.max_contracts_mini,
                    "max_contracts_micro": self.config.max_contracts_micro,
                    "consistency_pct": self.config.consistency_pct,
                    "min_trading_days": self.config.min_trading_days,
                },
                "current_attempt": attempt.to_dict(),
                "tv_paper": {
                    "stage": self.config.stage,
                    "eod_high_water_mark": attempt.eod_high_water_mark,
                    "current_drawdown_floor": attempt.current_drawdown_floor,
                    "drawdown_locked": attempt.drawdown_locked,
                    "consistency": self.check_consistency(),
                    "min_days": self.check_min_days(),
                    "trading_days_count": len(attempt.trading_days),
                    "max_contracts_mini": self.config.max_contracts_mini,
                },
                "last_updated": get_utc_timestamp(),
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save Tradovate Paper challenge state: {e}")

    def _save_to_history(self, attempt: TvPaperEvalAttempt) -> None:
        try:
            history: List[Dict[str, Any]] = []
            if self.history_file.exists():
                try:
                    with open(self.history_file) as f:
                        history = json.load(f)
                except Exception:
                    logger.debug("Failed to parse challenge history file", exc_info=True)
                    history = []
            history.append(attempt.to_dict())
            with open(self.history_file, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save Tradovate Paper challenge history: {e}")

    # ── Core logic ────────────────────────────────────────────────────

    def record_trade(
        self,
        pnl: float,
        is_win: bool,
        trade_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a completed trade and check pass/fail.

        Args:
            pnl: Realized P&L in USD
            is_win: Whether the trade was profitable
            trade_date: ISO date string (YYYY-MM-DD). Defaults to today's trading day.

        Returns:
            Dict with: triggered (bool), outcome (str|None), attempt (dict|None)
        """
        if not self.config.enabled or self.current_attempt.outcome != "active":
            return {"triggered": False, "outcome": None, "attempt": None}

        # Determine trading day
        if not trade_date:
            trade_date = date.today().isoformat()

        # Update attempt
        self.current_attempt.pnl += pnl
        self.current_attempt.trades += 1
        if is_win:
            self.current_attempt.wins += 1
        else:
            self.current_attempt.losses += 1

        # Track daily PnL
        if trade_date in self.current_attempt.daily_pnl_by_date:
            self.current_attempt.daily_pnl_by_date[trade_date] += pnl
        else:
            self.current_attempt.daily_pnl_by_date[trade_date] = pnl

        # Track unique trading days
        if trade_date not in self.current_attempt.trading_days:
            self.current_attempt.trading_days.append(trade_date)

        # Track high / low
        if self.current_attempt.pnl > self.current_attempt.profit_peak:
            self.current_attempt.profit_peak = self.current_attempt.pnl
        if self.current_attempt.pnl < self.current_attempt.max_drawdown_hit:
            self.current_attempt.max_drawdown_hit = self.current_attempt.pnl

        # Check FAIL: balance below drawdown floor
        current_balance = self.current_attempt.starting_balance + self.current_attempt.pnl
        if current_balance < self.current_attempt.current_drawdown_floor:
            return self._end_attempt("fail")

        # Check PASS: profit target reached + consistency + min days
        if self.current_attempt.pnl >= self.config.profit_target:
            consistency = self.check_consistency()
            min_days = self.check_min_days()
            if consistency["met"] and min_days["met"]:
                return self._end_attempt("pass")
            else:
                # Profit target reached but consistency/days not met -- keep trading
                logger.info(
                    f"Tradovate Paper profit target reached but cannot pass yet: "
                    f"consistency={consistency['met']}, min_days={min_days['met']}"
                )

        self._save_state()
        return {"triggered": False, "outcome": None, "attempt": None}

    def update_eod_hwm(self, eod_balance: Optional[float] = None) -> None:
        """
        Update the End-of-Day high-water mark (call at 4:10 PM ET).

        If eod_balance is not provided, uses starting_balance + pnl.

        EVALUATION: Floor is fixed at start_balance - max_loss ($48,000). No trailing.
                    HWM is still tracked for stats but does not move the floor.
        SIM_FUNDED: Floor trails intraday HWM. Locks at $100.
        """
        if self.current_attempt.outcome != "active":
            return

        if eod_balance is None:
            eod_balance = self.current_attempt.starting_balance + self.current_attempt.pnl

        # Always track HWM for stats/display
        if eod_balance > self.current_attempt.eod_high_water_mark:
            self.current_attempt.eod_high_water_mark = eod_balance

        # Floor trailing only applies to sim_funded / live (intraday trailing).
        # During evaluation, floor is fixed at start_balance - max_loss ($48,000).
        if self.config.stage in ("sim_funded", "live"):
            new_floor = self.current_attempt.eod_high_water_mark - self.config.max_loss_distance
            if new_floor > self.current_attempt.current_drawdown_floor:
                self.current_attempt.current_drawdown_floor = new_floor

            # Check if floor should lock at $100
            if (
                not self.current_attempt.drawdown_locked
                and self.current_attempt.current_drawdown_floor >= self.config.drawdown_lock_threshold
            ):
                self.current_attempt.drawdown_locked = True
                self.current_attempt.current_drawdown_floor = self.config.drawdown_lock_threshold
                logger.info(
                    f"Tradovate Paper drawdown floor LOCKED at ${self.config.drawdown_lock_threshold:.2f}"
                )

        self._save_state()
        logger.info(
            f"Tradovate Paper EOD HWM updated: balance=${eod_balance:.2f}, "
            f"hwm=${self.current_attempt.eod_high_water_mark:.2f}, "
            f"floor=${self.current_attempt.current_drawdown_floor:.2f}, "
            f"locked={self.current_attempt.drawdown_locked}"
        )

    def check_intraday_breach(self, current_equity: float) -> bool:
        """
        Check if current equity (including unrealized) breaches the drawdown floor.

        Returns True if breached (FAIL).
        """
        if self.current_attempt.outcome != "active":
            return False

        if current_equity < self.current_attempt.current_drawdown_floor:
            logger.warning(
                f"Tradovate Paper INTRADAY BREACH: equity=${current_equity:.2f} < "
                f"floor=${self.current_attempt.current_drawdown_floor:.2f}"
            )
            self._end_attempt("fail")
            return True
        return False

    def check_consistency(self) -> Dict[str, Any]:
        """
        Check the 50% consistency rule.

        Returns dict: {met: bool, best_day_pnl, best_day_pct, best_day_date}
        """
        total_profit = self.current_attempt.pnl
        daily = self.current_attempt.daily_pnl_by_date

        if not daily or total_profit <= 0:
            return {"met": True, "best_day_pnl": 0.0, "best_day_pct": 0.0, "best_day_date": None}

        best_day_date = max(daily, key=lambda d: daily[d])
        best_day_pnl = daily[best_day_date]
        best_day_pct = best_day_pnl / total_profit if total_profit > 0 else 0.0

        met = best_day_pct <= self.config.consistency_pct

        return {
            "met": met,
            "best_day_pnl": round(best_day_pnl, 2),
            "best_day_pct": round(best_day_pct * 100, 1),
            "best_day_date": best_day_date,
        }

    def check_min_days(self) -> Dict[str, Any]:
        """
        Check minimum trading days requirement.

        Returns dict: {met: bool, days_traded: int, days_required: int}
        """
        days_traded = len(self.current_attempt.trading_days)
        return {
            "met": days_traded >= self.config.min_trading_days,
            "days_traded": days_traded,
            "days_required": self.config.min_trading_days,
        }

    def _end_attempt(self, outcome: str) -> Dict[str, Any]:
        """End the current attempt with the given outcome."""
        self.current_attempt.outcome = outcome
        self.current_attempt.ended_at = get_utc_timestamp()

        logger.info(
            f"Tradovate Paper attempt #{self.current_attempt.attempt_id} ended: "
            f"{outcome.upper()} | PnL: ${self.current_attempt.pnl:.2f}"
        )

        self._save_state()
        self._save_to_history(self.current_attempt)

        result = {
            "triggered": True,
            "outcome": outcome,
            "attempt": self.current_attempt.to_dict(),
        }

        # Auto-reset if configured
        if outcome == "pass" and self.config.auto_reset_on_pass:
            self.current_attempt = self._create_new_attempt(
                self.current_attempt.attempt_id + 1
            )
        elif outcome == "fail" and self.config.auto_reset_on_fail:
            self.current_attempt = self._create_new_attempt(
                self.current_attempt.attempt_id + 1
            )

        return result

    # ── UI status ─────────────────────────────────────────────────────

    def get_status_for_ui(self) -> Dict[str, Any]:
        """
        Build status dict for the web UI's ChallengePanel.

        Compatible with the existing ChallengeStatus TypeScript interface
        plus Tradovate Paper-specific extensions.
        """
        a = self.current_attempt
        c = self.config

        current_balance = a.starting_balance + a.pnl
        dd_used = max(0.0, a.eod_high_water_mark - current_balance)
        dd_risk_pct = min(100.0, (dd_used / c.max_loss_distance * 100)) if c.max_loss_distance > 0 else 0.0

        return {
            # Standard ChallengeStatus fields
            "enabled": c.enabled,
            "current_balance": round(current_balance, 2),
            "pnl": round(a.pnl, 2),
            "trades": a.trades,
            "wins": a.wins,
            "win_rate": round((a.wins / a.trades * 100) if a.trades > 0 else 0.0, 1),
            "drawdown_risk_pct": round(dd_risk_pct, 1),
            "outcome": a.outcome,
            "profit_target": c.profit_target,
            "max_drawdown": c.max_loss_distance,
            "attempt_number": a.attempt_id,
            # Tradovate Paper extensions
            "tv_paper": {
                "stage": c.stage,
                "eod_high_water_mark": round(a.eod_high_water_mark, 2),
                "current_drawdown_floor": round(a.current_drawdown_floor, 2),
                "drawdown_locked": a.drawdown_locked,
                "consistency": self.check_consistency(),
                "min_days": self.check_min_days(),
                "max_contracts_mini": c.max_contracts_mini,
                "max_contracts_micro": c.max_contracts_micro,
                "t1_news_allowed": c.t1_news_allowed,
            },
        }

    def refresh(self) -> None:
        """Reload state from disk (for multi-process access)."""
        try:
            if self.state_file.exists():
                self.current_attempt = self._load_or_create_attempt()
        except Exception as e:
            logger.debug(f"Could not refresh Tradovate Paper state: {e}")
