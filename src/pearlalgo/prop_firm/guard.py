"""
Prop Firm Guard (rule engine)

Provides a lightweight compliance layer that can:
- Compute an estimated "prop firm status" from agent state files
- Gate/adjust position sizing for automated execution
- Annotate signals for manual workflows

NOTE: This is **broker-agnostic** and uses the agent's own tracked PnL (virtual exits).
If you wire real broker fills/equity later, you can swap the ledger source while keeping
the same decision API.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_performance_file,
    get_signals_file,
    parse_utc_timestamp,
)


_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    # My Funded Futures - Core 50K (Evaluation)
    # From user-provided rules:
    # - Profit Target: $3,000
    # - Maximum Loss Limit (EOD trailing): $2,000
    # - Daily Loss Limit: None
    # - Max Contracts: 3 mini / 30 micro
    # - Consistency: 50% (evaluation only)
    # - Minimum Trading Days: 2
    # - T1 News Trading: Yes
    "mff_core_50k_eval": {
        "account_size": 50_000.0,
        "profit_target": 3_000.0,
        "max_loss_limit_eod": 2_000.0,
        "daily_loss_limit": None,
        "max_contracts_mini": 3,
        "max_contracts_micro": 30,
        "consistency_pct": 0.50,
        "min_trading_days": 2,
        "allow_t1_news_trading": True,
        # Futures "trade day" commonly rolls at the Globex reopen (18:00 ET).
        "timezone": "America/New_York",
        "trading_day_start_time": "18:00",
        # Bot already defaults to flat by 16:10 ET; use that as the EOD lock.
        "eod_lock_time": "16:10",
        # Safety defaults
        "enforce_consistency_cap": True,
        "enforce_drawdown_risk_cap": True,
        "drawdown_safety_buffer": 0.0,
    }
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _parse_hhmm(raw: Any) -> Optional[time]:
    """Parse 'HH:MM' into a time object."""
    if not raw:
        return None
    try:
        s = str(raw).strip()
        parts = s.split(":")
        if len(parts) != 2:
            return None
        hh = int(parts[0])
        mm = int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return time(hour=hh, minute=mm)
    except Exception:
        return None


def _trading_day_key(dt_utc: datetime, tz: ZoneInfo, day_start: time) -> str:
    """
    Return a stable trading-day key (YYYY-MM-DD) using a configurable start time.

    If local time is before `day_start`, treat it as part of the *previous* trading day.
    This matches common futures day boundaries (e.g., 18:00 ET).
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    local = dt_utc.astimezone(tz)
    local_date = local.date()
    if local.time() < day_start:
        # Belongs to the prior trading day
        from datetime import timedelta

        local_date = local_date - timedelta(days=1)
    return local_date.isoformat()


def _risk_per_contract(signal: Dict[str, Any]) -> float:
    """Estimate worst-case stop loss ($) per 1 contract for the given signal."""
    try:
        entry = float(signal.get("entry_price") or 0.0)
        stop = float(signal.get("stop_loss") or 0.0)
        tick_value = float(signal.get("tick_value") or 0.0)
        if entry <= 0 or stop <= 0 or tick_value <= 0:
            return 0.0
        risk_points = abs(entry - stop)
        return risk_points * tick_value
    except Exception:
        return 0.0


def _derive_risk_amount(signal: Dict[str, Any], size: int) -> float:
    """Recompute risk_amount for a given size."""
    rpc = _risk_per_contract(signal)
    return rpc * max(0, int(size))


@dataclass
class PropFirmConfig:
    enabled: bool = False
    profile: str = "mff_core_50k_eval"

    # Rules
    account_size: float = 50_000.0
    profit_target: float = 3_000.0
    max_loss_limit_eod: float = 2_000.0  # trailing, locked at EOD
    daily_loss_limit: float | None = None
    max_contracts_mini: int = 3
    max_contracts_micro: int = 30
    consistency_pct: float = 0.50  # max single-day profit as % of profit_target (safe-cap)
    min_trading_days: int = 2
    allow_t1_news_trading: bool = True

    # Trading-day semantics
    timezone: str = "America/New_York"
    trading_day_start_time: str = "18:00"
    eod_lock_time: str = "16:10"

    # Enforcement toggles
    enforce_consistency_cap: bool = True
    enforce_drawdown_risk_cap: bool = True
    drawdown_safety_buffer: float = 0.0  # dollars; keep this buffer unused

    @classmethod
    def from_dict(
        cls,
        cfg: Dict[str, Any],
        *,
        default_profile: str = "mff_core_50k_eval",
        session_start_time: str | None = None,
        session_end_time: str | None = None,
    ) -> "PropFirmConfig":
        """
        Build config from config.yaml `prop_firm` section.

        `session_start_time` / `session_end_time` (ET) are used as fallbacks for
        trading day semantics when not explicitly set in prop_firm config.
        """
        cfg = cfg or {}
        profile = str(cfg.get("profile") or default_profile)
        preset = dict(_PROFILE_PRESETS.get(profile, {}))

        # Allow session-based defaults if not set in preset or cfg
        if session_start_time and "trading_day_start_time" not in preset:
            preset["trading_day_start_time"] = session_start_time
        if session_end_time and "eod_lock_time" not in preset:
            preset["eod_lock_time"] = session_end_time

        merged: Dict[str, Any] = {**preset, **cfg}

        # "None" / "none" handling for YAML strings
        dll = merged.get("daily_loss_limit")
        if isinstance(dll, str) and dll.strip().lower() in ("none", "null", ""):
            merged["daily_loss_limit"] = None

        return cls(
            enabled=bool(merged.get("enabled", False)),
            profile=profile,
            account_size=_safe_float(merged.get("account_size"), 50_000.0),
            profit_target=_safe_float(merged.get("profit_target"), 3_000.0),
            max_loss_limit_eod=_safe_float(merged.get("max_loss_limit_eod"), 2_000.0),
            daily_loss_limit=(
                None
                if merged.get("daily_loss_limit") is None
                else _safe_float(merged.get("daily_loss_limit"), 0.0)
            ),
            max_contracts_mini=_safe_int(merged.get("max_contracts_mini"), 3),
            max_contracts_micro=_safe_int(merged.get("max_contracts_micro"), 30),
            consistency_pct=_safe_float(merged.get("consistency_pct"), 0.50),
            min_trading_days=_safe_int(merged.get("min_trading_days"), 2),
            allow_t1_news_trading=bool(merged.get("allow_t1_news_trading", True)),
            timezone=str(merged.get("timezone") or "America/New_York"),
            trading_day_start_time=str(merged.get("trading_day_start_time") or "18:00"),
            eod_lock_time=str(merged.get("eod_lock_time") or "16:10"),
            enforce_consistency_cap=bool(merged.get("enforce_consistency_cap", True)),
            enforce_drawdown_risk_cap=bool(merged.get("enforce_drawdown_risk_cap", True)),
            drawdown_safety_buffer=_safe_float(merged.get("drawdown_safety_buffer"), 0.0),
        )


@dataclass
class PropFirmStatus:
    enabled: bool
    profile: str

    # Rules
    account_size: float
    profit_target: float
    max_loss_limit_eod: float
    daily_loss_limit: float | None
    max_contracts_mini: int
    max_contracts_micro: int
    consistency_pct: float
    min_trading_days: int
    allow_t1_news_trading: bool

    # Ledger (estimated from agent state)
    trading_day_key: str
    total_pnl: float
    equity_est: float
    daily_pnl: float
    days_traded: int
    open_risk_total: float

    # EOD trailing drawdown
    eod_high_watermark: float
    min_balance: float
    remaining_drawdown: float
    available_drawdown: float
    last_eod_lock_day: str | None = None

    # Consistency cap
    daily_profit_cap: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "profile": self.profile,
            "account_size": self.account_size,
            "profit_target": self.profit_target,
            "max_loss_limit_eod": self.max_loss_limit_eod,
            "daily_loss_limit": self.daily_loss_limit,
            "max_contracts_mini": self.max_contracts_mini,
            "max_contracts_micro": self.max_contracts_micro,
            "consistency_pct": self.consistency_pct,
            "min_trading_days": self.min_trading_days,
            "allow_t1_news_trading": self.allow_t1_news_trading,
            "trading_day_key": self.trading_day_key,
            "total_pnl": self.total_pnl,
            "equity_est": self.equity_est,
            "daily_pnl": self.daily_pnl,
            "days_traded": self.days_traded,
            "open_risk_total": self.open_risk_total,
            "eod_high_watermark": self.eod_high_watermark,
            "min_balance": self.min_balance,
            "remaining_drawdown": self.remaining_drawdown,
            "available_drawdown": self.available_drawdown,
            "last_eod_lock_day": self.last_eod_lock_day,
            "daily_profit_cap": self.daily_profit_cap,
        }


@dataclass
class PropFirmDecision:
    allow: bool
    reason: str
    adjusted_size: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow": self.allow,
            "reason": self.reason,
            "adjusted_size": self.adjusted_size,
        }


class PropFirmGuard:
    """
    Computes prop-firm compliance status and gates/adjusts execution accordingly.
    """

    def __init__(self, config: PropFirmConfig, *, state_dir: Path):
        self.config = config
        self.state_dir = ensure_state_dir(state_dir)
        self.performance_file = get_performance_file(self.state_dir)
        self.signals_file = get_signals_file(self.state_dir)
        self.state_file = self.state_dir / "prop_firm_state.json"

    def _load_guard_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text())
        except Exception:
            return {}

    def _save_guard_state(self, state: Dict[str, Any]) -> None:
        try:
            self.state_file.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"Could not persist prop firm state: {e}")

    def compute_status(self, *, now: Optional[datetime] = None) -> PropFirmStatus:
        now = now or datetime.now(timezone.utc)

        # Resolve day semantics
        try:
            tz = ZoneInfo(self.config.timezone)
        except Exception:
            tz = ZoneInfo("America/New_York")

        day_start = _parse_hhmm(self.config.trading_day_start_time) or time(0, 0)
        day_key = _trading_day_key(now, tz, day_start)

        # Load performance ledger
        performances: list[dict] = []
        if self.performance_file.exists():
            try:
                performances = json.loads(self.performance_file.read_text()) or []
                if not isinstance(performances, list):
                    performances = []
            except Exception:
                performances = []

        total_pnl = 0.0
        daily_pnl = 0.0
        traded_days: set[str] = set()
        for rec in performances:
            if not isinstance(rec, dict):
                continue
            pnl = _safe_float(rec.get("pnl"), 0.0)
            total_pnl += pnl
            exit_time_str = rec.get("exit_time")
            if not exit_time_str:
                continue
            try:
                dt = parse_utc_timestamp(str(exit_time_str))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            k = _trading_day_key(dt, tz, day_start)
            traded_days.add(k)
            if k == day_key:
                daily_pnl += pnl

        # Open risk from entered signals
        open_risk_total = 0.0
        if self.signals_file.exists():
            try:
                with open(self.signals_file, "r") as f:
                    for line in f:
                        try:
                            rec = json.loads(line.strip())
                        except Exception:
                            continue
                        if not isinstance(rec, dict) or rec.get("status") != "entered":
                            continue
                        sig = rec.get("signal", {}) or {}
                        if not isinstance(sig, dict):
                            continue
                        ra = sig.get("risk_amount")
                        if ra is None:
                            # Compute fallback
                            size = _safe_int(sig.get("position_size"), 0)
                            ra = _derive_risk_amount(sig, size)
                        open_risk_total += max(0.0, _safe_float(ra, 0.0))
            except Exception:
                open_risk_total = 0.0

        # Load / update EOD high-watermark state
        guard_state = self._load_guard_state()
        eod_high = _safe_float(
            guard_state.get("eod_high_watermark"),
            self.config.account_size,
        )
        last_eod_lock_day = guard_state.get("last_eod_lock_day")

        eod_lock_t = _parse_hhmm(self.config.eod_lock_time)
        if eod_lock_t is None:
            eod_lock_t = time(16, 10)

        # If local time is past lock time and we haven't locked for this trading-day key, lock it.
        try:
            local = (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(tz)
            if local.time() >= eod_lock_t and last_eod_lock_day != day_key:
                # Equity estimate is based on agent PnL (virtual exits)
                equity_est = float(self.config.account_size + total_pnl)
                eod_high = max(eod_high, equity_est)
                guard_state["eod_high_watermark"] = eod_high
                guard_state["last_eod_lock_day"] = day_key
                guard_state["last_updated"] = datetime.now(timezone.utc).isoformat()
                self._save_guard_state(guard_state)
                last_eod_lock_day = day_key
        except Exception:
            pass

        equity_est = float(self.config.account_size + total_pnl)
        min_balance = float(eod_high - self.config.max_loss_limit_eod)
        remaining_drawdown = float(equity_est - min_balance)
        available_drawdown = float(
            remaining_drawdown - open_risk_total - self.config.drawdown_safety_buffer
        )

        daily_profit_cap = None
        if (
            self.config.enforce_consistency_cap
            and self.config.consistency_pct > 0
            and self.config.profit_target > 0
        ):
            daily_profit_cap = float(self.config.profit_target * self.config.consistency_pct)

        return PropFirmStatus(
            enabled=bool(self.config.enabled),
            profile=str(self.config.profile),
            account_size=float(self.config.account_size),
            profit_target=float(self.config.profit_target),
            max_loss_limit_eod=float(self.config.max_loss_limit_eod),
            daily_loss_limit=(
                None
                if self.config.daily_loss_limit is None
                else float(self.config.daily_loss_limit)
            ),
            max_contracts_mini=int(self.config.max_contracts_mini),
            max_contracts_micro=int(self.config.max_contracts_micro),
            consistency_pct=float(self.config.consistency_pct),
            min_trading_days=int(self.config.min_trading_days),
            allow_t1_news_trading=bool(self.config.allow_t1_news_trading),
            trading_day_key=day_key,
            total_pnl=float(total_pnl),
            equity_est=float(equity_est),
            daily_pnl=float(daily_pnl),
            days_traded=len(traded_days),
            open_risk_total=float(open_risk_total),
            eod_high_watermark=float(eod_high),
            min_balance=float(min_balance),
            remaining_drawdown=float(remaining_drawdown),
            available_drawdown=float(available_drawdown),
            last_eod_lock_day=str(last_eod_lock_day) if last_eod_lock_day else None,
            daily_profit_cap=daily_profit_cap,
        )

    def evaluate_signal(
        self,
        signal: Dict[str, Any],
        *,
        status: Optional[PropFirmStatus] = None,
        now: Optional[datetime] = None,
    ) -> PropFirmDecision:
        """
        Evaluate whether a signal should be allowed for execution under prop firm rules.

        Returns a decision that can:
        - block execution
        - cap/adjust the position size
        """
        if not self.config.enabled:
            return PropFirmDecision(allow=True, reason="prop_firm_disabled")

        now = now or datetime.now(timezone.utc)
        status = status or self.compute_status(now=now)

        # Consistency cap (safe interpretation): cap daily profit to consistency% of target.
        if (
            self.config.enforce_consistency_cap
            and status.daily_profit_cap is not None
            and status.daily_pnl >= status.daily_profit_cap
        ):
            return PropFirmDecision(
                allow=False,
                reason=f"consistency_cap_reached:${status.daily_pnl:,.0f}/${status.daily_profit_cap:,.0f}",
            )

        # Drawdown hard stop: if already below (or at) min balance, block.
        if status.remaining_drawdown <= 0:
            return PropFirmDecision(
                allow=False,
                reason=(
                    f"max_loss_limit_hit:equity=${status.equity_est:,.0f}"
                    f"<=min=${status.min_balance:,.0f}"
                ),
            )

        symbol = str(signal.get("symbol") or "MNQ").upper()
        requested_size = _safe_int(signal.get("position_size"), 0)
        if requested_size <= 0:
            requested_size = 1

        # Contract caps by product (mini vs micro)
        contract_cap = None
        if symbol.startswith("MNQ"):
            contract_cap = int(self.config.max_contracts_micro)
        elif symbol.startswith("NQ"):
            contract_cap = int(self.config.max_contracts_mini)

        allowed_size = requested_size
        reason_parts: list[str] = []

        if contract_cap is not None and allowed_size > contract_cap:
            allowed_size = contract_cap
            reason_parts.append(f"max_contracts_cap:{contract_cap}")

        # Risk cap by remaining drawdown (worst-case stop loss)
        if self.config.enforce_drawdown_risk_cap:
            rpc = _risk_per_contract(signal)
            if rpc > 0:
                max_by_dd = int(math.floor(status.available_drawdown / rpc))
                if max_by_dd < 1:
                    return PropFirmDecision(
                        allow=False,
                        reason=(
                            f"drawdown_buffer_too_small:avail=${status.available_drawdown:,.0f}"
                            f"<risk1=${rpc:,.0f}"
                        ),
                    )
                if allowed_size > max_by_dd:
                    allowed_size = max_by_dd
                    reason_parts.append(f"drawdown_cap:{max_by_dd}")

        if allowed_size <= 0:
            return PropFirmDecision(allow=False, reason="size_zero_after_caps")

        if allowed_size != requested_size:
            return PropFirmDecision(
                allow=True,
                reason=";".join(reason_parts) or "size_adjusted",
                adjusted_size=allowed_size,
            )

        return PropFirmDecision(allow=True, reason="ok", adjusted_size=None)



