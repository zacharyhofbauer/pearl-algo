"""
50k Challenge Tracker

Tracks account attempts with pass/fail rules:
- Start balance: $50,000
- Max drawdown: -$2,000 → FAIL (auto-reset)
- Profit target: +$3,000 → PASS (auto-reset)

Design:
- Keeps all historical trades (never deletes performance.json / signals.jsonl / trades.db)
- Maintains a separate "challenge_state.json" tracking current attempt
- Appends attempt records to SQLite table for historical analysis
- PnL shown in Telegram = current attempt only (not all-time)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir, get_utc_timestamp


@dataclass
class ChallengeConfig:
    """Challenge (prop firm sim) configuration."""
    enabled: bool = True
    start_balance: float = 50_000.0
    max_drawdown: float = 2_000.0  # Negative PnL threshold → FAIL
    profit_target: float = 3_000.0  # Positive PnL threshold → PASS
    auto_reset_on_pass: bool = True
    auto_reset_on_fail: bool = True


@dataclass
class ChallengeAttempt:
    """Single challenge attempt record."""
    attempt_id: int
    started_at: str  # ISO timestamp
    ended_at: Optional[str] = None  # ISO timestamp (None if active)
    outcome: str = "active"  # "active", "pass", "fail", "reset_manual"
    starting_balance: float = 50_000.0
    ending_balance: Optional[float] = None
    pnl: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    max_drawdown_hit: float = 0.0  # Deepest PnL dip during attempt
    profit_peak: float = 0.0  # Highest PnL during attempt

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "attempt_id": self.attempt_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "outcome": self.outcome,
            "starting_balance": self.starting_balance,
            "ending_balance": self.ending_balance,
            "pnl": self.pnl,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "max_drawdown_hit": self.max_drawdown_hit,
            "profit_peak": self.profit_peak,
            "win_rate": (self.wins / self.trades * 100) if self.trades > 0 else 0.0,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChallengeAttempt":
        """Create from dictionary."""
        return cls(
            attempt_id=int(data.get("attempt_id", 1)),
            started_at=str(data.get("started_at", get_utc_timestamp())),
            ended_at=data.get("ended_at"),
            outcome=str(data.get("outcome", "active")),
            starting_balance=float(data.get("starting_balance", 50_000.0)),
            ending_balance=data.get("ending_balance"),
            pnl=float(data.get("pnl", 0.0)),
            trades=int(data.get("trades", 0)),
            wins=int(data.get("wins", 0)),
            losses=int(data.get("losses", 0)),
            max_drawdown_hit=float(data.get("max_drawdown_hit", 0.0)),
            profit_peak=float(data.get("profit_peak", 0.0)),
        )


class ChallengeTracker:
    """
    Tracks 50k challenge attempts with pass/fail rules.
    
    - Monitors trade exits and updates current attempt PnL
    - Auto-triggers PASS or FAIL when thresholds are hit
    - Records completed attempts to SQLite + JSON for history
    - Provides attempt-specific metrics for Telegram display
    """

    def __init__(
        self,
        config: Optional[ChallengeConfig] = None,
        state_dir: Optional[Path] = None,
        trade_db: Optional[Any] = None,  # TradeDatabase instance (optional)
    ):
        """
        Initialize challenge tracker.

        Args:
            config: Challenge configuration
            state_dir: State directory (default: data/agent_state/<MARKET>)
            trade_db: TradeDatabase for attempt history (optional)
        """
        self.config = config or ChallengeConfig()
        self.state_dir = ensure_state_dir(state_dir)
        self._trade_db = trade_db

        self.state_file = self.state_dir / "challenge_state.json"
        self.history_file = self.state_dir / "challenge_history.json"

        # Load current attempt (or create first one)
        self.current_attempt = self._load_current_attempt()
        # Track state file mtime so UIs can refresh from disk without restarting.
        self._last_state_mtime: Optional[float] = None
        try:
            if self.state_file.exists():
                self._last_state_mtime = float(self.state_file.stat().st_mtime)
        except Exception:
            self._last_state_mtime = None

        logger.info(
            f"ChallengeTracker initialized: attempt={self.current_attempt.attempt_id}, "
            f"pnl=${self.current_attempt.pnl:.2f}, outcome={self.current_attempt.outcome}"
        )

    def refresh(self) -> None:
        """
        Refresh current attempt from disk (best-effort).

        The agent service mutates + persists challenge state. Other processes (e.g., Telegram
        command handler) may keep a cached ChallengeTracker instance and need to reflect updates
        without restarting.
        """
        try:
            if not self.state_file.exists():
                return
            mtime = float(self.state_file.stat().st_mtime)
            if self._last_state_mtime is None or mtime > self._last_state_mtime:
                self.current_attempt = self._load_current_attempt()
                self._last_state_mtime = mtime
        except Exception as e:
            logger.debug(f"Could not refresh challenge state: {e}")

    def _load_current_attempt(self) -> ChallengeAttempt:
        """Load current attempt from state file (or create new)."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                attempt = ChallengeAttempt.from_dict(data.get("current_attempt", {}))
                # If last attempt ended, start a new one
                if attempt.outcome != "active":
                    return self._create_new_attempt(attempt.attempt_id + 1)
                return attempt
            except Exception as e:
                logger.warning(f"Could not load challenge state: {e}")

        return self._create_new_attempt(1)

    def _create_new_attempt(self, attempt_id: int) -> ChallengeAttempt:
        """Create a new attempt."""
        return ChallengeAttempt(
            attempt_id=attempt_id,
            started_at=get_utc_timestamp(),
            starting_balance=self.config.start_balance,
        )

    def _save_state(self) -> None:
        """Save current state to JSON."""
        try:
            state = {
                "config": {
                    "enabled": self.config.enabled,
                    "start_balance": self.config.start_balance,
                    "max_drawdown": self.config.max_drawdown,
                    "profit_target": self.config.profit_target,
                },
                "current_attempt": self.current_attempt.to_dict(),
                "last_updated": get_utc_timestamp(),
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save challenge state: {e}")

    def _save_attempt_to_history(self, attempt: ChallengeAttempt) -> None:
        """Append completed attempt to history file."""
        try:
            history: List[Dict[str, Any]] = []
            if self.history_file.exists():
                try:
                    with open(self.history_file) as f:
                        history = json.load(f)
                except Exception:
                    history = []

            history.append(attempt.to_dict())

            with open(self.history_file, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save challenge history: {e}")

        # Also write to SQLite if available
        if self._trade_db is not None:
            try:
                self._trade_db.add_challenge_attempt(
                    attempt_id=attempt.attempt_id,
                    started_at=attempt.started_at,
                    ended_at=attempt.ended_at or get_utc_timestamp(),
                    outcome=attempt.outcome,
                    starting_balance=attempt.starting_balance,
                    ending_balance=attempt.ending_balance or (attempt.starting_balance + attempt.pnl),
                    pnl=attempt.pnl,
                    trades=attempt.trades,
                    wins=attempt.wins,
                    losses=attempt.losses,
                    max_drawdown_hit=attempt.max_drawdown_hit,
                    profit_peak=attempt.profit_peak,
                )
            except Exception as e:
                logger.debug(f"Could not save challenge attempt to SQLite: {e}")

    def record_trade(self, pnl: float, is_win: bool) -> Dict[str, Any]:
        """
        Record a trade result and check pass/fail thresholds.

        Args:
            pnl: Trade P&L in dollars
            is_win: Whether trade was profitable

        Returns:
            Dict with keys: triggered (bool), outcome (str), attempt (dict)
        """
        if not self.config.enabled:
            return {"triggered": False, "outcome": None, "attempt": None}

        # Update current attempt
        self.current_attempt.pnl += pnl
        self.current_attempt.trades += 1
        if is_win:
            self.current_attempt.wins += 1
        else:
            self.current_attempt.losses += 1

        # Track high-water mark and drawdown
        if self.current_attempt.pnl > self.current_attempt.profit_peak:
            self.current_attempt.profit_peak = self.current_attempt.pnl
        if self.current_attempt.pnl < self.current_attempt.max_drawdown_hit:
            self.current_attempt.max_drawdown_hit = self.current_attempt.pnl

        result: Dict[str, Any] = {
            "triggered": False,
            "outcome": None,
            "attempt": self.current_attempt.to_dict(),
        }

        # Check FAIL threshold (max drawdown)
        if self.current_attempt.pnl <= -self.config.max_drawdown:
            result["triggered"] = True
            result["outcome"] = "fail"
            self._end_attempt("fail")

        # Check PASS threshold (profit target)
        elif self.current_attempt.pnl >= self.config.profit_target:
            result["triggered"] = True
            result["outcome"] = "pass"
            self._end_attempt("pass")

        # Save state after every trade
        self._save_state()

        return result

    def _end_attempt(self, outcome: str) -> None:
        """End current attempt and optionally start a new one."""
        logger.info(
            f"Challenge attempt {self.current_attempt.attempt_id} ended: {outcome.upper()} | "
            f"PnL: ${self.current_attempt.pnl:.2f} | Trades: {self.current_attempt.trades} | "
            f"Win Rate: {(self.current_attempt.wins / max(1, self.current_attempt.trades)) * 100:.1f}%"
        )

        self.current_attempt.outcome = outcome
        self.current_attempt.ended_at = get_utc_timestamp()
        self.current_attempt.ending_balance = self.config.start_balance + self.current_attempt.pnl

        # Save to history
        self._save_attempt_to_history(self.current_attempt)

        # Auto-reset if configured
        should_reset = (
            (outcome == "pass" and self.config.auto_reset_on_pass)
            or (outcome == "fail" and self.config.auto_reset_on_fail)
        )

        if should_reset:
            self.current_attempt = self._create_new_attempt(self.current_attempt.attempt_id + 1)
            logger.info(f"New challenge attempt started: #{self.current_attempt.attempt_id}")

        self._save_state()

    def manual_reset(self, reason: str = "manual") -> ChallengeAttempt:
        """
        Manually reset the current attempt (e.g., user wants to start fresh).

        Args:
            reason: Reason for manual reset

        Returns:
            The new attempt
        """
        if self.current_attempt.outcome == "active":
            self.current_attempt.outcome = f"reset_{reason}"
            self.current_attempt.ended_at = get_utc_timestamp()
            self.current_attempt.ending_balance = self.config.start_balance + self.current_attempt.pnl
            self._save_attempt_to_history(self.current_attempt)

        self.current_attempt = self._create_new_attempt(self.current_attempt.attempt_id + 1)
        self._save_state()

        logger.info(f"Manual reset: new attempt #{self.current_attempt.attempt_id}")
        return self.current_attempt

    def get_attempt_performance(self, *, unrealized_pnl: Optional[float] = None) -> Dict[str, Any]:
        """
        Get current attempt performance metrics (for Telegram display).

        Args:
            unrealized_pnl: Optional unrealized PNL from open positions to include in total

        Returns:
            Dict with attempt-specific metrics that can replace all-time PnL
        """
        attempt = self.current_attempt
        win_rate = (attempt.wins / attempt.trades * 100) if attempt.trades > 0 else 0.0

        # Include unrealized PNL in total if provided
        total_pnl = attempt.pnl
        if unrealized_pnl is not None:
            total_pnl = attempt.pnl + float(unrealized_pnl)

        # Progress towards target (0-100%)
        if total_pnl >= 0:
            progress_pct = min(100.0, (total_pnl / self.config.profit_target) * 100)
        else:
            progress_pct = 0.0

        # Drawdown risk (0-100%) - use total PNL including unrealized
        drawdown_risk_pct = min(100.0, (abs(min(0.0, total_pnl)) / self.config.max_drawdown) * 100)

        return {
            # Core metrics (replaces all-time performance)
            "wins": attempt.wins,
            "losses": attempt.losses,
            "win_rate": win_rate / 100.0,  # 0-1 scale for compatibility
            "total_pnl": total_pnl,  # Includes unrealized if provided
            "realized_pnl": attempt.pnl,  # Realized PNL only
            "unrealized_pnl": unrealized_pnl if unrealized_pnl is not None else 0.0,
            "exited_signals": attempt.trades,
            # Challenge-specific
            "attempt_id": attempt.attempt_id,
            "attempt_started_at": attempt.started_at,
            "attempt_outcome": attempt.outcome,
            "starting_balance": attempt.starting_balance,
            "current_balance": attempt.starting_balance + total_pnl,  # Includes unrealized
            "profit_target": self.config.profit_target,
            "max_drawdown": self.config.max_drawdown,
            "progress_pct": progress_pct,
            "drawdown_risk_pct": drawdown_risk_pct,
            "max_drawdown_hit": attempt.max_drawdown_hit,
            "profit_peak": attempt.profit_peak,
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent attempt history."""
        history: List[Dict[str, Any]] = []
        if self.history_file.exists():
            try:
                with open(self.history_file) as f:
                    history = json.load(f)
            except Exception:
                history = []

        # Return most recent first
        return list(reversed(history[-limit:]))

    def get_status_summary(self, *, bot_label: Optional[str] = None, unrealized_pnl: Optional[float] = None) -> str:
        """
        Get challenge status as a formatted string for Telegram.

        Args:
            bot_label: Optional bot label to include in header
            unrealized_pnl: Optional unrealized PNL from open positions to include in total

        Returns:
            Compact summary string for Home Card
        """
        p = self.get_attempt_performance(unrealized_pnl=unrealized_pnl)
        pnl = p["total_pnl"]
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

        # Progress bar (simple)
        if pnl >= 0:
            bar_filled = min(10, int(p["progress_pct"] / 10))
            bar = "▓" * bar_filled + "░" * (10 - bar_filled)
            target_str = f"Target: {bar} {p['progress_pct']:.0f}%"
        else:
            bar_filled = min(10, int(p["drawdown_risk_pct"] / 10))
            bar = "▓" * bar_filled + "░" * (10 - bar_filled)
            target_str = f"DD Risk: {bar} {p['drawdown_risk_pct']:.0f}%"

        header = "🏆 *50k Challenge*"
        if bot_label:
            header += f" ({bot_label})"

        return (
            f"{header}\n"
            f"Balance: `${p['current_balance']:,.2f}` | {pnl_emoji} {pnl_str}\n"
            f"{target_str}\n"
            f"Trades: {p['exited_signals']} | WR: {p['win_rate'] * 100:.0f}%"
        )

